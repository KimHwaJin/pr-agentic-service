"""Keys of the services and agents that call this API."""

from datetime import datetime

from pydantic import Field

from api_service.schemas.base import Model


class ApiClientCreate(Model):
    name: str = Field(min_length=1, max_length=64)
    # executor/pr-batch tenant of the client; empty = this service's own
    tenant: str | None = Field(None, pattern=r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")
    description: str | None = Field(None, max_length=2000)


class ApiClientRead(Model):
    id: str
    name: str
    tenant: str
    key_prefix: str
    status: str
    description: str | None
    created_by: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class ApiClientIssued(Model):
    client: ApiClientRead
    # shown once: only its SHA-256 is kept
    api_key: str
