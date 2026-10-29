"""Keys of the services and agents that call this API (``X-Api-Key``).

A key is ``pas_live_`` (``pas_dev_`` in local/dev) and 32 random bytes; only
its SHA-256 is stored. A verified key is cached for
``Settings.api_client_cache_seconds``, so a revocation reaches every pod
within that window.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from sqlalchemy import select, update

from src.dtest.core.db import utcnow
from src.dtest.core.models import ApiClient
from src.dtest.core.services import Services


@dataclass(frozen=True)
class Caller:
    """The api client of a request that came with a key."""

    id: str
    name: str
    tenant: str


_cache: dict[str, tuple[float, Caller | None]] = {}


def key_prefix(env: str) -> str:
    return "pas_dev_" if env in {"local", "dev"} else "pas_live_"


def new_key(env: str) -> str:
    return key_prefix(env) + secrets.token_urlsafe(32)


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def verify(services: Services, key: str) -> Caller | None:
    """The active client of ``key``, or None (unknown, pending, revoked)."""
    hashed = digest(key)
    hit = _cache.get(hashed)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    async with services.db.sessions() as db:
        client = await db.scalar(
            select(ApiClient).where(ApiClient.key_sha256 == hashed)
        )
        caller = None
        if (
            client is not None
            and client.status == "active"
            and hmac.compare_digest(client.key_sha256, hashed)
        ):
            caller = Caller(client.id, client.name, client.tenant)
            # once per cache window, not per request
            await db.execute(
                update(ApiClient)
                .where(ApiClient.id == client.id)
                .values(last_used_at=utcnow())
            )
            await db.commit()
    if len(_cache) > 1000:
        _cache.clear()
    _cache[hashed] = (
        time.monotonic() + services.settings.api_client_cache_seconds,
        caller,
    )
    return caller


def forget(key_sha256: str) -> None:
    """Drop a cached key so a status change applies here at once."""
    _cache.pop(key_sha256, None)
