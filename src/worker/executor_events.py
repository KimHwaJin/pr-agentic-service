"""Consumes ``executor.events`` and resumes runs waiting on them.

``executor.events`` is a Redis Stream with at-least-once delivery. Each event
is stored once in ``executor_inbox`` (dedup on event_id) before XACK, so a run
that starts waiting after its event already arrived still finds it (see
``RunScheduler``). Redis 6.0 compatible: stale pending entries are reclaimed
with XPENDING + XCLAIM.
"""

import asyncio
import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from core.db import Database
from core.models import ExecutorInbox, Run

log = logging.getLogger(__name__)
WAKE_TYPES = {"execution.operation_completed", "execution.completed"}


def matches(
    waiting: dict[str, Any], event_type: str, payload: dict[str, Any]
) -> bool:
    """Does this executor event end what the run is waiting for?"""
    if event_type == "execution.completed":
        return True
    operation_id = waiting.get("operation_id")
    return (
        bool(operation_id)
        and event_type == "execution.operation_completed"
        and payload.get("operation", {}).get("id") == operation_id
    )


async def wake_waiting_run(
    db: Database, execution_id: str, event_type: str, payload: dict[str, Any]
) -> str | None:
    """Queue the run waiting on this execution.

    The event becomes its resume value.
    """
    async with db.sessions() as session:
        run = await session.scalar(
            select(Run)
            .where(
                Run.status == "waiting_executor",
                Run.waiting["execution_id"].astext == execution_id,
            )
            .with_for_update(skip_locked=True)
        )
        if run is None or not run.waiting:
            return None
        if not matches(run.waiting, event_type, payload):
            return None
        run.resume = {
            "interrupt_id": run.waiting["interrupt_id"],
            "value": {"event_type": event_type, "payload": payload},
        }
        run.status, run.waiting = "queued", None
        await session.commit()
        return run.id


class ExecutorEventConsumer:
    def __init__(
        self,
        db: Database,
        redis: Redis,
        stream: str,
        group: str,
        consumer: str,
        on_wake,
        on_progress,
    ):
        self.db, self.redis, self.stream, self.group, self.consumer = (
            db,
            redis,
            stream,
            group,
            consumer,
        )
        self.on_wake = on_wake  # async (run_id) -> None
        self.on_progress = on_progress  # async (execution_id, event) -> None

    async def run_forever(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.stream, self.group, id="$", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        reclaim_every, ticks = 12, 0
        while True:
            try:
                if ticks % reclaim_every == 0:
                    await self._reclaim()
                ticks += 1
                batches = await self.redis.xreadgroup(
                    self.group,
                    self.consumer,
                    {self.stream: ">"},
                    count=50,
                    block=5000,
                )
                for _, messages in batches or []:
                    for message_id, fields in messages:
                        await self._handle(message_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep consuming; failed entries stay pending
                log.exception("executor_event_consumer_error")
                await asyncio.sleep(2)

    async def _reclaim(self) -> None:
        pending = await self.redis.xpending_range(
            self.stream, self.group, min="-", max="+", count=50
        )
        stale = [
            p["message_id"]
            for p in pending
            if p["time_since_delivered"] > 60000
        ]
        if stale:
            for message_id, fields in await self.redis.xclaim(
                self.stream, self.group, self.consumer, 60000, stale
            ):
                await self._handle(message_id, fields)

    async def _handle(self, message_id: str, fields: dict[str, str]) -> None:
        try:
            payload = json.loads(fields["payload"])
            event = {
                "event_id": fields["event_id"],
                "execution_id": fields["execution_id"],
                "event_type": fields["event_type"],
                "event_sequence": int(fields["event_sequence"]),
                "payload": payload,
            }
        except (KeyError, ValueError):
            log.warning("executor_event_malformed message_id=%s", message_id)
            await self.redis.xack(self.stream, self.group, message_id)
            return
        if event["event_type"] in WAKE_TYPES:
            async with self.db.sessions() as session:
                await session.execute(
                    insert(ExecutorInbox)
                    .values(**event)
                    .on_conflict_do_nothing()
                )
                await session.commit()
            run_id = await wake_waiting_run(
                self.db, event["execution_id"], event["event_type"], payload
            )
            if run_id:
                await self.on_wake(run_id)
        else:
            await self.on_progress(event["execution_id"], event)
        await self.redis.xack(self.stream, self.group, message_id)
