"""Session event stream.

Durable events in PostgreSQL, live fan-out over Redis pub/sub.

Durable events carry an id so SSE clients can resume with Last-Event-ID
from any pod. Live-only events (token deltas, executor progress) are
published but not stored.

Batch report jobs stream the same events on their own channel
(``emit_report``), stored in ``batch_report_events``, so a job is drawn with
the chat components.

Load notes: each process holds ONE pattern subscription and fans events out
to its local SSE streams through in-memory queues, so SSE connections cost
no Redis connections. Token deltas are coalesced per run before publishing.
"""

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select

from core.contracts import events as contracts
from core.db import Database
from core.models import BatchReportEvent, RunEvent

log = logging.getLogger(__name__)
TOKEN_FLUSH_SECONDS = 0.05
SUBSCRIBER_QUEUE_SIZE = 1000


class EventBus:
    def __init__(self, db: Database, redis: Redis, namespace: str):
        self.db, self.redis, self.namespace = db, redis, namespace
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._listener: asyncio.Task | None = None

    def channel(self, session_id: str) -> str:
        return f"{self.namespace}:session:{session_id}"

    def report_channel(self, job_id: str) -> str:
        return f"{self.namespace}:batch-report:{job_id}"

    async def emit(
        self,
        session_id: str,
        run_id: str,
        type: str,
        data: dict[str, Any],
        durable: bool = True,
    ) -> None:
        contracts.check(type, data)  # the shape readers rely on
        event: dict[str, Any] = {"type": type, "run_id": run_id, "data": data}
        if durable:
            async with self.db.sessions() as db:
                row = RunEvent(
                    session_id=session_id, run_id=run_id, type=type, data=data
                )
                db.add(row)
                await db.commit()
                event["id"] = row.id
        await self.redis.publish(
            self.channel(session_id),
            json.dumps(event, ensure_ascii=False, default=str),
        )

    async def emit_report(
        self,
        job_id: str,
        type: str,
        data: dict[str, Any],
        durable: bool = True,
    ) -> None:
        """A batch report job's event; ``run_id`` is the job id."""
        contracts.check(type, data)
        event: dict[str, Any] = {"type": type, "run_id": job_id, "data": data}
        if durable:
            async with self.db.sessions() as db:
                row = BatchReportEvent(job_id=job_id, type=type, data=data)
                db.add(row)
                await db.commit()
                event["id"] = row.id
        await self.redis.publish(
            self.report_channel(job_id),
            json.dumps(event, ensure_ascii=False, default=str),
        )

    async def report_history(
        self, job_id: str, after_id: int = 0
    ) -> list[dict[str, Any]]:
        async with self.db.sessions() as db:
            rows = (
                await db.scalars(
                    select(BatchReportEvent)
                    .where(
                        BatchReportEvent.job_id == job_id,
                        BatchReportEvent.id > after_id,
                    )
                    .order_by(BatchReportEvent.id)
                    .limit(5000)
                )
            ).all()
        return [
            {"id": r.id, "type": r.type, "run_id": r.job_id, "data": r.data}
            for r in rows
        ]

    async def history(
        self, session_id: str, after_id: int, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = select(RunEvent).where(
            RunEvent.session_id == session_id, RunEvent.id > after_id
        )
        if run_id:
            query = query.where(RunEvent.run_id == run_id)
        async with self.db.sessions() as db:
            rows = (
                await db.scalars(query.order_by(RunEvent.id).limit(5000))
            ).all()
        return [
            {"id": r.id, "type": r.type, "run_id": r.run_id, "data": r.data}
            for r in rows
        ]

    # --- local fan-out -----------------------------------------------------

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """Register before replaying history so nothing falls in between."""
        return self.listen_to(self.channel(session_id))

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        self.stop_listening(self.channel(session_id), queue)

    def listen_to(self, channel: str) -> asyncio.Queue:
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(
                self._listen(), name="event-fanout"
            )
        queue: asyncio.Queue = asyncio.Queue(SUBSCRIBER_QUEUE_SIZE)
        self._subscribers[channel].add(queue)
        return queue

    def stop_listening(self, channel: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(channel)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                del self._subscribers[channel]

    async def _listen(self) -> None:
        patterns = (self.channel("*"), self.report_channel("*"))
        while True:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.psubscribe(*patterns)
                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue
                    for queue in self._subscribers.get(message["channel"], ()):
                        with contextlib.suppress(
                            asyncio.QueueFull
                        ):  # a stalled client drops live events
                            queue.put_nowait(message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reconnect; SSE clients resume by Last-Event-ID
                log.exception("event_fanout_reconnect")
                await asyncio.sleep(1)
            finally:
                await pubsub.aclose()

    async def close(self) -> None:
        if self._listener:
            self._listener.cancel()

    async def wake_runs(self, run_id: str = "") -> None:
        await self.redis.publish(runs_wake_channel(self.namespace), run_id)


class TokenBuffer:
    """Coalesces token deltas of one run into ~20 publishes per second.

    ``emit`` is the run's ``emit(type, data, durable)``.
    """

    def __init__(self, emit: Callable[..., Awaitable[None]]):
        self.emit = emit
        self._parts: list[str] = []
        self._flusher: asyncio.Task | None = None

    def add(self, text: str) -> None:
        self._parts.append(text)
        if self._flusher is None:
            self._flusher = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(TOKEN_FLUSH_SECONDS)
        await self.flush()

    async def flush(self) -> None:
        self._flusher = None
        if self._parts:
            text, self._parts = "".join(self._parts), []
            await self.emit("token", {"text": text}, durable=False)


def runs_wake_channel(namespace: str) -> str:
    return f"{namespace}:runs:wake"
