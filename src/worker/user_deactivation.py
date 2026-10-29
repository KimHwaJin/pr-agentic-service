"""Tells pr-batch about deactivated users until it has heard.

Deactivating a user (``PATCH /admin/users/{id}``) asks pr-batch at once to
turn off their batches; when that call fails the user stays
``batches_disable_pending`` and this retries (the call is idempotent).
"""

import asyncio
import logging

from sqlalchemy import select

from core.batch_admin import tell_batch
from core.models import User
from core.services import Services

log = logging.getLogger(__name__)


class BatchDisableRetry:
    def __init__(self, services: Services, interval_seconds: float = 300):
        self.services, self.interval = services, interval_seconds

    async def run_forever(self) -> None:
        while True:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - try again next round
                log.exception("batch_disable_retry_failed")
            await asyncio.sleep(self.interval)

    async def sweep(self) -> int:
        async with self.services.db.sessions() as db:
            pending = (
                await db.scalars(
                    select(User.id)
                    .where(
                        User.is_active.is_(False),
                        User.batches_disable_pending.is_(True),
                    )
                    .limit(100)
                )
            ).all()
        done = 0
        for user_id in pending:
            done += await tell_batch(self.services, user_id)
        return done
