"""pr-batch admin calls of this service (our key's admin scope)."""

import logging

import httpx
from sqlalchemy import update

from core.config import Settings
from core.models import ApiClient, User
from core.service_headers import Identity, with_key
from core.services import Services

log = logging.getLogger(__name__)


async def disable_batches_of(settings: Settings, owner_id: str) -> int:
    """Turns off the batches of a deactivated user.

    pr-batch marks them ``disabled_reason=USER_DEACTIVATED`` and refuses
    their manual runs (409 ``OWNER_DEACTIVATED``). Idempotent: batches
    already off are not counted again. Reactivating the user does not turn
    them back on; the owner does.

    No ``X-Tenant-Id`` is sent: pr-batch then turns them off in every
    tenant our key may use (``allowed_tenants: ["*"]``), since the same
    employee id can own batches under external tenants too.
    """
    async with httpx.AsyncClient(
        base_url=settings.batch_base_url, timeout=30
    ) as http:
        response = await http.post(
            "/api/v1/batches:disable-by-owner",
            headers=with_key(settings.batch_api_key),
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


async def disable_batches_of_tenant(settings: Settings, tenant: str) -> int:
    """Turns off every batch of a revoked tenant at pr-batch.

    pr-batch marks them ``disabled_reason=TENANT_REVOKED``, skips their
    waiting runs and refuses manual runs; executions already submitted
    keep running. Idempotent. ``X-Tenant-Id`` is required there.
    """
    async with httpx.AsyncClient(
        base_url=settings.batch_base_url, timeout=30
    ) as http:
        response = await http.post(
            "/api/v1/batches:disable-by-tenant",
            headers=with_key(settings.batch_api_key, Identity(tenant=tenant)),
            json={"reason": "TENANT_REVOKED"},
        )
    response.raise_for_status()
    return response.json().get("disabled", 0)


async def tell_batch_tenant(services: Services, tenant: str) -> bool:
    """One disable-by-tenant call; clears the tenant's pending marks on
    success (unless a key of it became active again meanwhile)."""
    try:
        disabled = await disable_batches_of_tenant(services.settings, tenant)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning(
            "batch_tenant_disable_failed tenant=%s error=%s", tenant, exc
        )
        return False
    async with services.db.sessions() as db:
        await db.execute(
            update(ApiClient)
            .where(ApiClient.tenant == tenant)
            .values(batches_disable_pending=False)
        )
        await db.commit()
    log.info("batch_disabled_by_tenant tenant=%s batches=%s", tenant, disabled)
    return True
