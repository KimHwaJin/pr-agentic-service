"""Bounded growth of transport data.

Purges old session and batch report events, executor inbox rows, run
idempotency keys, images of deleted sessions and code files already
snapshotted by the executor, and LangGraph checkpoints an idle session no
longer needs.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select, text, tuple_

from core.db import affected, utcnow
from core.models import (
    BatchReportEvent,
    ChatSession,
    ExecutorInbox,
    Image,
    RunEvent,
    RunRequest,
)
from core.services import Services

log = logging.getLogger(__name__)
BATCH = 5000
CHECKPOINT_BATCH = 200  # sessions per sweep
# latest checkpoint per namespace stays; then the writes and channel blobs
# no remaining checkpoint refers to (blobs are shared between versions)
PRUNE_THREAD = (
    """
    DELETE FROM checkpoints c
    WHERE c.thread_id = :thread
      AND c.checkpoint_id <> (
        SELECT max(k.checkpoint_id) FROM checkpoints k
        WHERE k.thread_id = c.thread_id AND k.checkpoint_ns = c.checkpoint_ns
      )
    """,
    """
    DELETE FROM checkpoint_writes w
    WHERE w.thread_id = :thread
      AND NOT EXISTS (
        SELECT 1 FROM checkpoints c
        WHERE c.thread_id = w.thread_id AND c.checkpoint_ns = w.checkpoint_ns
          AND c.checkpoint_id = w.checkpoint_id
      )
    """,
    """
    DELETE FROM checkpoint_blobs b
    WHERE b.thread_id = :thread
      AND NOT EXISTS (
        SELECT 1 FROM checkpoints c,
             jsonb_each_text(c.checkpoint -> 'channel_versions') v
        WHERE c.thread_id = b.thread_id AND c.checkpoint_ns = b.checkpoint_ns
          AND v.key = b.channel AND v.value = b.version
      )
    """,
)


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
            (RunEvent.id,),
            RunEvent.created_at,
            settings.run_event_retention_days,
        )
        await self._purge(
            BatchReportEvent,
            (BatchReportEvent.id,),
            BatchReportEvent.created_at,
            settings.run_event_retention_days,
        )
        await self._purge(
            ExecutorInbox,
            (ExecutorInbox.event_id,),
            ExecutorInbox.received_at,
            settings.executor_inbox_retention_days,
        )
        await self._purge(
            RunRequest,
            (RunRequest.session_id, RunRequest.key),
            RunRequest.created_at,
            settings.run_request_retention_days,
        )
        await self._purge_images(settings.image_retention_days)
        pruned = await self._prune_checkpoints()
        if pruned:
            log.info("checkpoints_pruned sessions=%s", pruned)
        days = settings.code_source_retention_days
        removed = await self.services.code_sources.purge(days)
        if removed:
            log.info("code_sources_purged files=%s", removed)

    async def _prune_checkpoints(self) -> int:
        """Keep only the latest checkpoint of idle sessions.

        Every graph step of a turn adds a checkpoint (thread = session) and
        nothing reads older ones (no history or time travel), so they only
        grow the tables. A session is pruned under its row lock with no
        active run: starting a turn takes the same lock (create_run), so no
        graph writes the thread meanwhile.
        """
        async with self.services.db.sessions() as db:
            threads = (
                await db.scalars(
                    text(
                        "SELECT c.thread_id FROM checkpoints c"
                        " JOIN sessions s ON s.id = c.thread_id"
                        " WHERE s.active_run_id IS NULL"
                        " GROUP BY c.thread_id HAVING count(*) > 1"
                        " LIMIT :limit"
                    ),
                    {"limit": CHECKPOINT_BATCH},
                )
            ).all()
        pruned = 0
        for thread_id in threads:
            async with self.services.db.sessions() as db:
                idle = await db.scalar(
                    select(ChatSession.id)
                    .where(
                        ChatSession.id == thread_id,
                        ChatSession.active_run_id.is_(None),
                    )
                    .with_for_update(skip_locked=True)
                )
                if not idle:
                    continue  # running, being started, or not a session
                for statement in PRUNE_THREAD:
                    await db.execute(text(statement), {"thread": thread_id})
                await db.commit()
                pruned += 1
        return pruned

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

    async def _purge(self, model, keys, stamp, days: int) -> None:
        """Delete in small batches.

        Concurrent pods and live traffic never wait on one long delete.
        ``keys`` are the primary key columns.
        """
        cutoff = utcnow() - timedelta(days=days)
        while True:
            async with self.services.db.sessions() as db:
                old = (
                    select(*keys)
                    .where(stamp < cutoff)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                )
                result = await db.execute(
                    delete(model).where(tuple_(*keys).in_(old))
                )
                await db.commit()
            if affected(result) < BATCH:
                return
