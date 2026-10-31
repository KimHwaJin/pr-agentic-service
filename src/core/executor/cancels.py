"""Cancelling executor executions until the executor has heard.

A cancelled turn, a deleted session or project must not leave its kernel
running: a step can run for days. ``cancel_execution`` asks the executor
at once; when that fails for any reason other than "already over" the
execution is kept in a Redis hash and ``ExecutionCancelRetry`` (worker)
asks again until it succeeds or the executor's own limit has ended it.
"""

import asyncio
import json
import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import or_, select

from core.db import utcnow
from core.executor.client import ExecutorError
from core.models import CodeSource, Run
from core.services import Services

log = logging.getLogger(__name__)
# 404: no such execution; 409: already terminal (nothing left to stop)
OVER = {404, 409}
# the executor ends any execution by then (EXECUTION_MAX_RUNTIME_SECONDS)
GIVE_UP_SECONDS = 10 * 24 * 3600


def _pending_key(services: Services) -> str:
    return f"{services.settings.redis_namespace}:executor-cancels"


async def _send(
    services: Services, execution_id: str, key: str, reason: str
) -> bool:
    """True once the executor has the cancel (or nothing is left to stop)."""
    executor = services.executor
    try:
        await executor.cancel(
            execution_id,
            who=await executor.opener(execution_id),
            idempotency_key=key,
            reason=reason,
        )
    except ExecutorError as exc:
        if exc.status in OVER:
            return True
        log.warning(
            "executor_cancel_failed execution_id=%s status=%s",
            execution_id,
            exc.status,
        )
        return False
    except httpx.HTTPError as exc:
        log.warning(
            "executor_cancel_failed execution_id=%s error=%s",
            execution_id,
            type(exc).__name__,
        )
        return False
    return True


async def cancel_execution(
    services: Services, execution_id: str, *, key: str, reason: str
) -> bool:
    """Cancel now, or remember it for the retry loop. Never raises
    for executor or network failures. True if the executor has it."""
    if await _send(services, execution_id, key, reason):
        return True
    await services.redis.hsetnx(
        _pending_key(services),
        execution_id,
        json.dumps({"key": key, "reason": reason, "since": time.time()}),
    )
    return False


class ExecutionCancelRetry:
    def __init__(self, services: Services, interval_seconds: float = 60):
        self.services, self.interval = services, interval_seconds

    async def run_forever(self) -> None:
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - try again next round
                log.exception("executor_cancel_retry_failed")
            await asyncio.sleep(self.interval)

    async def sweep(self) -> int:
        """Asks again for every pending cancel; returns how many landed."""
        redis, key = self.services.redis, _pending_key(self.services)
        done = 0
        for execution_id, raw in (await redis.hgetall(key)).items():
            item = json.loads(raw)
            if await _send(
                self.services, execution_id, item["key"], item["reason"]
            ):
                await redis.hdel(key, execution_id)
                done += 1
            elif time.time() - item["since"] > GIVE_UP_SECONDS:
                log.error(
                    "executor_cancel_gave_up execution_id=%s", execution_id
                )
                await redis.hdel(key, execution_id)
        return done


async def cancel_idle_executions(
    services: Services, session_ids: list[str], *, reason: str
) -> int:
    """Cancel the MULTI executions these sessions may still keep open.

    With no turn running, a kernel lives at most the operation wait after
    the turn that used it ended, so only executions of turns that ended
    since then can still be alive. Returns how many were asked.
    """
    if not session_ids:
        return 0
    window = services.settings.executor_operation_wait_seconds + 300
    since = utcnow() - timedelta(seconds=window)
    async with services.db.sessions() as db:
        ids = (
            await db.scalars(
                select(CodeSource.execution_id)
                .join(Run, Run.id == CodeSource.run_id)
                .where(
                    CodeSource.session_id.in_(session_ids),
                    CodeSource.execution_id.is_not(None),
                    or_(Run.finished_at.is_(None), Run.finished_at > since),
                )
                .distinct()
            )
        ).all()
    for execution_id in ids:
        await cancel_execution(
            services, execution_id, key=f"delete:{execution_id}", reason=reason
        )
    return len(ids)
