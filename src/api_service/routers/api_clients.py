"""Administration of the keys other services and agents call us with.

We are the only place that decides which tenants may use the executor
and pr-batch: our keys there are allowed every tenant
(``allowed_tenants: ["*"]``), so issuing a key here is all a new tenant
takes, and a key is active at once. Revoking it (or every key of a
tenant) is how a tenant is cut off. A revoked key is refused (401).

The tenant is always named. Our own tenant is given only on purpose
(``own_tenant``): its key reads every execution of our users as a system
read.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api_service.deps import AdminDep, ServicesDep
from api_service.schemas.api_clients import (
    ApiClientCreate,
    ApiClientIssued,
    ApiClientRead,
    TenantRevoked,
)
from api_service.services import api_clients
from core.config import RESERVED_TENANT_IDS
from core.db import utcnow
from core.models import ApiClient

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
            key_prefix=key[: len(api_clients.key_prefix(settings.env)) + 4],
            key_sha256=api_clients.digest(key),
            status="active",
            description=body.description,
            created_by=admin.id,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
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
        await db.commit()
        await db.refresh(client)
    api_clients.forget(client.key_sha256)
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
        await db.commit()
    for client in clients:
        api_clients.forget(client.key_sha256)
    return TenantRevoked(tenant=tenant, revoked=len(clients))
