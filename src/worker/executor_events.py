"""Consumes executor events and resumes runs waiting on them.

The executor publishes the events of every execution submitted with our
tenant_id (agent runs and the batches registered through us) to
``executor.events.<tenant>`` (``Settings.executor_tenant_stream``), a Redis
Stream with at-least-once delivery. Each event is stored once in
``executor_inbox`` (dedup on event_id) before XACK, so a run that starts
waiting after its event already arrived still finds it (see
``RunScheduler``). ``execution.completed`` also goes to ``on_completed``,
which starts the report of a successful batch run (worker.batch_reports).
Redis 6.0 compatible: stale pending entries are reclaimed
with XPENDING + XCLAIM.
"""

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from core.db import Database, utcnow
from core.executor.client import ExecutorClient, ExecutorError
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


async def deliver(db: Database, event: dict[str, Any]) -> str | None:
    """Store a wake event once and queue the run waiting on it."""
    async with db.sessions() as session:
        await session.execute(
            insert(ExecutorInbox).values(**event).on_conflict_do_nothing()
        )
        await session.commit()
    return await wake_waiting_run(
        db, event["execution_id"], event["event_type"], event["payload"]
    )


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
        on_completed,
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
        # async (execution_id, payload) -> None
        self.on_completed = on_completed

    async def _create_group(self) -> None:
        """A new group starts at the stream's oldest entry.

        Events published before the group existed (a stream that a
        submission created first, a group lost with Redis) are still
        delivered; replaying them is harmless (inbox and report jobs are
        idempotent).
        """
        try:
            await self.redis.xgroup_create(
                self.stream, self.group, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run_forever(self) -> None:
        await self._create_group()
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
            run_id = await deliver(self.db, event)
            if run_id:
                await self.on_wake(run_id)
            if event["event_type"] == "execution.completed":
                await self.on_completed(event["execution_id"], payload)
        else:
            await self.on_progress(event["execution_id"], event)
        await self.redis.xack(self.stream, self.group, message_id)


class MissedEventRecovery:
    """Runs still waiting on the executor after ``after_seconds``.

    The stream is the fast path; if its event never reaches us (Redis lost
    it, the consumer was down past the stream's retention), the run would
    wait forever. This asks the executor's own event timeline for the event
    the run waits for and delivers it the same way.
    """

    def __init__(
        self,
        db: Database,
        executor: ExecutorClient,
        on_wake,
        after_seconds: float,
        interval_seconds: float = 60,
    ):
        self.db, self.executor, self.on_wake = db, executor, on_wake
        self.after = timedelta(seconds=after_seconds)
        self.interval = interval_seconds

    async def run_forever(self) -> None:
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - try again next round
                log.exception("missed_event_recovery_error")
            await asyncio.sleep(self.interval)

    async def sweep(self) -> list[str]:
        async with self.db.sessions() as session:
            waiting = (
                await session.scalars(
                    select(Run)
                    .where(
                        Run.status == "waiting_executor",
                        Run.updated_at < utcnow() - self.after,
                    )
                    .limit(50)
                )
            ).all()
        woken = []
        for run in waiting:
            if run_id := await self._recover(run):
                woken.append(run_id)
                await self.on_wake(run_id)
        return woken

    async def _recover(self, run: Run) -> str | None:
        execution_id = (run.waiting or {}).get("execution_id")
        if not execution_id:
            return None
        try:
            events = await self.executor.events(execution_id)
        except ExecutorError as exc:
            log.warning(
                "missed_event_lookup_failed run_id=%s status=%s",
                run.id,
                exc.status,
            )
            return None
        for item in events:
            if item.get("event_type") in WAKE_TYPES and matches(
                run.waiting or {}, item["event_type"], item.get("payload", {})
            ):
                run_id = await deliver(
                    self.db,
                    {
                        "event_id": str(item["event_id"]),
                        "execution_id": execution_id,
                        "event_type": item["event_type"],
                        "event_sequence": int(item["event_sequence"]),
                        "payload": item.get("payload", {}),
                    },
                )
                if run_id:
                    log.warning(
                        "executor_event_recovered run_id=%s event=%s",
                        run_id,
                        item["event_type"],
                    )
                return run_id
        return None
