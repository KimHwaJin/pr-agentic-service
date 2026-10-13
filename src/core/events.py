"""Session event stream: durable events in PostgreSQL, live fan-out over Redis pub/sub.

Durable events carry an id so SSE clients can resume with Last-Event-ID from any pod.
Token deltas are live-only; the final message is durable.
"""

import json
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select

from core.db import Database
from core.models import RunEvent


class EventBus:
    def __init__(self, db: Database, redis: Redis, namespace: str):
        self.db, self.redis, self.namespace = db, redis, namespace

    def channel(self, session_id: str) -> str:
        return f"{self.namespace}:session:{session_id}"

    async def emit(self, session_id: str, run_id: str, type: str, data: dict[str, Any], durable: bool = True) -> None:
        event: dict[str, Any] = {"type": type, "run_id": run_id, "data": data}
        if durable:
            async with self.db.sessions() as db:
                row = RunEvent(session_id=session_id, run_id=run_id, type=type, data=data)
                db.add(row)
                await db.commit()
                event["id"] = row.id
        await self.redis.publish(self.channel(session_id), json.dumps(event, ensure_ascii=False, default=str))

    async def history(self, session_id: str, after_id: int, run_id: str | None = None) -> list[dict[str, Any]]:
        query = select(RunEvent).where(RunEvent.session_id == session_id, RunEvent.id > after_id)
        if run_id:
            query = query.where(RunEvent.run_id == run_id)
        async with self.db.sessions() as db:
            rows = (await db.scalars(query.order_by(RunEvent.id).limit(5000))).all()
        return [{"id": r.id, "type": r.type, "run_id": r.run_id, "data": r.data} for r in rows]

    def pubsub(self, session_id: str):
        """Subscribe before replaying history so nothing falls in between."""
        pubsub = self.redis.pubsub()
        return pubsub, self.channel(session_id)

    async def wake_runs(self, run_id: str = "") -> None:
        await self.redis.publish(runs_wake_channel(self.namespace), run_id)


def runs_wake_channel(namespace: str) -> str:
    return f"{namespace}:runs:wake"
