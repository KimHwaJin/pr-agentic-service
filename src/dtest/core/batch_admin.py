"""pr-batch admin calls of this service (our key's admin scope)."""

import logging

import httpx
from sqlalchemy import update

from src.dtest.core.config import Settings
from src.dtest.core.models import User
from src.dtest.core.service_headers import Identity, with_key
from src.dtest.core.services import Services

log = logging.getLogger(__name__)


async def disable_batches_of(settings: Settings, owner_id: str) -> int:
    """Turns off the batches of a deactivated user.

    pr-batch marks them ``disabled_reason=USER_DEACTIVATED`` and refuses
    their manual runs (409 ``OWNER_DEACTIVATED``). Idempotent: batches
    already off are not counted again. Reactivating the user does not turn
    them back on; the owner does.

    With our key no ``X-Tenant-Id`` is sent: pr-batch then turns them off
    in every tenant our key may use (``allowed_tenants: ["*"]``), since a
    user of ours can own batches under external tenants too. Without a key
    (header mode, local/dev) a missing tenant means pr-batch's ``dev``, so
    ours is named as before.
    """
    tenant = None if settings.batch_api_key else settings.executor_tenant_id
    async with httpx.AsyncClient(
        base_url=settings.batch_base_url, timeout=30
    ) as http:
        response = await http.post(
            "/api/v1/batches:disable-by-owner",
            headers=with_key(settings.batch_api_key, Identity(tenant=tenant)),
            json={"owner_id": owner_id, "reason": "USER_DEACTIVATED"},
        )
    response.raise_for_status()
    return response.json().get("disabled", 0)


async def tell_batch(services: Services, user_id: str) -> bool:
    """One disable-by-owner call; clears the user's pending mark on success."""
    try:
        disabled = await disable_batches_of(services.settings, user_id)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("batch_disable_failed user=%s error=%s", user_id, exc)
        return False
    async with services.db.sessions() as db:
        await db.execute(
            update(User)
            .where(User.id == user_id, User.is_active.is_(False))
            .values(batches_disable_pending=False)
        )
        await db.commit()
    log.info("batch_disabled_by_owner user=%s batches=%s", user_id, disabled)
    return True
