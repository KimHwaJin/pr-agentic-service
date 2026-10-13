"""Bounded growth of transport tables: old session events and executor inbox rows."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from core.db import utcnow
from core.models import ExecutorInbox, RunEvent
from core.services import Services

log = logging.getLogger(__name__)
BATCH = 5000


class Retention:
    def __init__(self, services: Services, interval_seconds: float = 3600):
        self.services, self.interval = services, interval_seconds

    async def run_forever(self) -> None:
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("retention_sweep_failed")
            await asyncio.sleep(self.interval)

    async def sweep(self) -> None:
        settings = self.services.settings
        await self._purge(RunEvent, RunEvent.id, RunEvent.created_at, settings.run_event_retention_days)
        await self._purge(
            ExecutorInbox, ExecutorInbox.event_id, ExecutorInbox.received_at, settings.executor_inbox_retention_days
        )

    async def _purge(self, model, key, stamp, days: int) -> None:
        """Small batches so concurrent pods and live traffic never wait on one long delete."""
        cutoff = utcnow() - timedelta(days=days)
        while True:
            async with self.services.db.sessions() as db:
                ids = select(key).where(stamp < cutoff).limit(BATCH).with_for_update(skip_locked=True).scalar_subquery()
                result = await db.execute(delete(model).where(key.in_(ids)))
                await db.commit()
            if result.rowcount < BATCH:
                return
