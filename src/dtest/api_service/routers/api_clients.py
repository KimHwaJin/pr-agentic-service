"""Administration of the keys other services and agents call us with.

A client of our own tenant is active at once. A client of another tenant
stays ``pending`` until that tenant is in our keys' ``allowed_tenants`` at
the executor and pr-batch (their deploy); an administrator then activates
it. A pending or revoked key is refused (401).
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from src.dtest.api_service.deps import AdminDep, ServicesDep
from src.dtest.api_service.schemas.api_clients import (
    ApiClientCreate,
    ApiClientIssued,
    ApiClientRead,
)
from src.dtest.api_service.services import api_clients
from src.dtest.core.config import RESERVED_TENANT_IDS
from src.dtest.core.db import utcnow
from src.dtest.core.models import ApiClient

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
    tenant = body.tenant or settings.executor_tenant_id
    if tenant in RESERVED_TENANT_IDS:
        raise HTTPException(422, f"Tenant {tenant!r} is reserved.")
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
            status="active"
            if tenant == settings.executor_tenant_id
            else "pending",
            description=body.description,
            created_by=admin.id,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
    return ApiClientIssued(
        client=ApiClientRead.model_validate(client), api_key=key
    )


@router.post("/{client_id}/activate", response_model=ApiClientRead)
async def activate_client(
    client_id: str, services: ServicesDep, admin: AdminDep
):
    return await _set_status(services, client_id, "active")


@router.post("/{client_id}/revoke", response_model=ApiClientRead)
async def revoke_client(
    client_id: str, services: ServicesDep, admin: AdminDep
):
    return await _set_status(services, client_id, "revoked")


async def _set_status(services, client_id: str, status: str) -> ApiClient:
    async with services.db.sessions() as db:
        client = await db.get(ApiClient, client_id)
        if client is None:
            raise HTTPException(404, "Client not found.")
        if client.status == "revoked":
            raise HTTPException(409, "A revoked key cannot change.")
        client.status = status
        if status == "revoked":
            client.revoked_at = utcnow()
        await db.commit()
        await db.refresh(client)
    api_clients.forget(client.key_sha256)
    return client
