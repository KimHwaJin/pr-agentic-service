"""Administration of the keys other services and agents call us with.

We are the only place that decides which tenants may use the executor
and pr-batch: our keys there are allowed every tenant
(``allowed_tenants: ["*"]``), so issuing a key here is all a new tenant
takes, and a key is active at once. Revoking it (or every key of a
tenant) is how a tenant is cut off. A revoked key is refused (401). When
another tenant has no active key left, pr-batch turns its batches off
(``disable-by-tenant``; retried by the worker until it has heard).

The tenant is always named. Our own tenant is given only on purpose
(``own_tenant``). The kind decides the reach of gateway reads: a
``standard`` key reads only what its ``X-User-Id`` owns, a ``master`` key
the whole tenant (a ``user_id`` query narrows it). Writes are the same.
"""

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from api_service.deps import AdminDep, ServicesDep
from api_service.schemas.api_clients import (
    ApiClientCreate,
    ApiClientIssued,
    ApiClientRead,
    TenantRevoked,
)
from api_service.services import api_clients
from core.batch_admin import tell_batch_tenant
from core.config import RESERVED_TENANT_IDS
from core.db import utcnow
from core.models import ApiClient

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api-clients", tags=["api-clients"])


@router.get("", response_model=list[ApiClientRead])
async def list_clients(services: ServicesDep, admin: AdminDep):
    async with services.db.sessions() as db:
        return (
            await db.scalars(
                select(ApiClient).order_by(ApiClient.created_at.desc())
            )
        ).all()


@router.post("", response_model=ApiClientIssued, status_code=201)
async def issue_client(
    body: ApiClientCreate, services: ServicesDep, admin: AdminDep
):
    settings = services.settings
    tenant = body.tenant
    if tenant in RESERVED_TENANT_IDS:
        raise HTTPException(422, f"Tenant {tenant!r} is reserved.")
    if tenant == settings.executor_tenant_id and not body.own_tenant:
        raise HTTPException(
            422,
            f"Tenant {tenant!r} is this service's own; "
            "set own_tenant to issue a key for it.",
        )
    key = api_clients.new_key(settings.env)
    async with services.db.sessions() as db:
        if await db.scalar(
            select(ApiClient.id).where(ApiClient.name == body.name)
        ):
            raise HTTPException(409, "A client with this name exists.")
        client = ApiClient(
            name=body.name,
            tenant=tenant,
            kind=body.kind,
            key_prefix=key[: len(api_clients.key_prefix(settings.env)) + 4],
            key_sha256=api_clients.digest(key),
            status="active",
            batches_disable_pending=False,
            description=body.description,
            created_by=admin.id,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
    return ApiClientIssued(
        client=ApiClientRead.model_validate(client), api_key=key
    )


@router.post("/{client_id}/reissue", response_model=ApiClientIssued)
async def reissue_client(
    client_id: str, services: ServicesDep, admin: AdminDep
):
    """A new key for the same client (name, tenant, kind stay); the old
    key stops working at once. Keys are kept only as a hash, so this is
    how a lost key is replaced. Revoked clients are not brought back."""
    settings = services.settings
    key = api_clients.new_key(settings.env)
    async with services.db.sessions() as db:
        client = await db.get(ApiClient, client_id)
        if client is None:
            raise HTTPException(404, "Client not found.")
        if client.status == "revoked":
            raise HTTPException(409, "The key is revoked; issue a new one.")
        old = client.key_sha256
        client.key_prefix = key[
            : len(api_clients.key_prefix(settings.env)) + 4
        ]
        client.key_sha256 = api_clients.digest(key)
        client.last_used_at = None
        await db.commit()
        await db.refresh(client)
    api_clients.forget(old)
    log.info(
        "api_client_reissued client=%s tenant=%s by=%s",
        client.name,
        client.tenant,
        admin.id,
    )
    return ApiClientIssued(
        client=ApiClientRead.model_validate(client), api_key=key
    )


@router.post("/{client_id}/revoke", response_model=ApiClientRead)
async def revoke_client(
    client_id: str, services: ServicesDep, admin: AdminDep
):
    async with services.db.sessions() as db:
        client = await db.get(ApiClient, client_id)
        if client is None:
            raise HTTPException(404, "Client not found.")
        if client.status == "revoked":
            raise HTTPException(409, "The key is already revoked.")
        client.status = "revoked"
        client.revoked_at = utcnow()
        cut_off = await _mark_cut_off(db, services, client.tenant)
        await db.commit()
        await db.refresh(client)
    api_clients.forget(client.key_sha256)
    if cut_off:
        await tell_batch_tenant(services, client.tenant)
        async with services.db.sessions() as db:
            client = await db.get(ApiClient, client_id)
    return client


@router.post("/tenants/{tenant}/revoke", response_model=TenantRevoked)
async def revoke_tenant(tenant: str, services: ServicesDep, admin: AdminDep):
    """Revokes every key of ``tenant`` at once: the tenant is cut off from
    us, and so from the executor and pr-batch. Revoked keys are kept."""
    async with services.db.sessions() as db:
        clients = (
            await db.scalars(
                select(ApiClient).where(
                    ApiClient.tenant == tenant, ApiClient.status != "revoked"
                )
            )
        ).all()
        now = utcnow()
        for client in clients:
            client.status = "revoked"
            client.revoked_at = now
        cut_off = await _mark_cut_off(db, services, tenant)
        await db.commit()
    for client in clients:
        api_clients.forget(client.key_sha256)
    told = cut_off and await tell_batch_tenant(services, tenant)
    return TenantRevoked(
        tenant=tenant,
        revoked=len(clients),
        batches_disabled=told,
        batches_disable_pending=cut_off and not told,
    )


async def _mark_cut_off(db, services, tenant: str) -> bool:
    """True when ``tenant`` (not ours) has no active key left: pr-batch is
    then told to turn its batches off, retried by the worker until it has
    heard (``batches_disable_pending``). Call after the revoke, before the
    commit. Our own tenant's batches belong to our users and stay."""
    if tenant == services.settings.executor_tenant_id:
        return False
    await db.flush()
    if await db.scalar(
        select(ApiClient.id).where(
            ApiClient.tenant == tenant, ApiClient.status == "active"
        )
    ):
        return False
    await db.execute(
        update(ApiClient)
        .where(ApiClient.tenant == tenant)
        .values(batches_disable_pending=True)
    )
    return True
