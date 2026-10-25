"""Bounded growth of transport data.

Purges old session events, executor inbox rows and code files already
snapshotted by the executor.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from core.db import affected, utcnow
from core.models import ChatSession, ExecutorInbox, Image, RunEvent, RunRequest
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
        await self._purge(
            RunEvent,
            RunEvent.id,
            RunEvent.created_at,
            settings.run_event_retention_days,
        )
        await self._purge(
            ExecutorInbox,
            ExecutorInbox.event_id,
            ExecutorInbox.received_at,
            settings.executor_inbox_retention_days,
        )
        await self._purge(
            RunRequest,
            RunRequest.key,
            RunRequest.created_at,
            settings.run_request_retention_days,
        )
        await self._purge_images(settings.image_retention_days)
        days = settings.code_source_retention_days
        removed = await self.services.code_sources.purge(days)
        if removed:
            log.info("code_sources_purged files=%s", removed)

    async def _purge_images(self, days: int) -> None:
        """Images of sessions deleted more than ``days`` ago."""
        cutoff = utcnow() - timedelta(days=days)
        while True:
            async with self.services.db.sessions() as db:
                ids = (
                    await db.scalars(
                        select(Image.id)
                        .join(ChatSession, ChatSession.id == Image.session_id)
                        .where(ChatSession.deleted_at < cutoff)
                        .limit(BATCH)
                    )
                ).all()
            await self.services.images.remove(list(ids))
            if len(ids) < BATCH:
                return

    async def _purge(self, model, key, stamp, days: int) -> None:
        """Delete in small batches.

        Concurrent pods and live traffic never wait on one long delete.
        """
        cutoff = utcnow() - timedelta(days=days)
        while True:
            async with self.services.db.sessions() as db:
                ids = (
                    select(key)
                    .where(stamp < cutoff)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                    .scalar_subquery()
                )
                result = await db.execute(delete(model).where(key.in_(ids)))
                await db.commit()
            if affected(result) < BATCH:
                return
