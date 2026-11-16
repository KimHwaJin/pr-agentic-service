"""The service's Redis client: standalone or through Sentinel.

``REDIS_MODE=standalone`` (default) connects to ``REDIS_URL``.
``REDIS_MODE=sentinel`` asks the Sentinel at ``REDIS_SENTINEL_*`` for the
current master and uses DB 0, as the executor does: sessions, pub/sub and
the event stream consumer all write, so every command must reach the
master. Each new connection asks Sentinel again, so a failover needs no
restart.

A master that dies without closing its connections answers nothing and
raises nothing. ``SOCKET_TIMEOUT`` ends a command that waits that long
(above the consumer's XREADGROUP BLOCK), and ``listen`` pings an idle
subscription.
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.asyncio.sentinel import (
    MasterNotFoundError,
    Sentinel,
    SentinelConnectionPool,
)
from redis.exceptions import ConnectionError as RedisConnectionError

from core.config import Settings

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0
# every reply but a pub/sub message; XREADGROUP blocks 5 s
SOCKET_TIMEOUT = 15.0
# an idle subscription is pinged after this long, and given up on when
# the reply takes as long again
PUBSUB_IDLE_SECONDS = 15.0


def create_redis(settings: Settings) -> Redis:
    transport: dict[str, Any] = {
        "decode_responses": True,
        "socket_connect_timeout": CONNECT_TIMEOUT,
        "socket_timeout": SOCKET_TIMEOUT,
    }
    if settings.redis_mode == "standalone":
        return Redis.from_url(settings.redis_url, **transport)
    # one account signs in to Sentinel and to Redis (the internal guide)
    # a value pasted with a space or a line break is a wrong password
    password = decrypt(settings.redis_sentinel_auth.strip()).strip()
    username = settings.redis_sentinel_username.strip() or None
    master = settings.redis_sentinel_master_name.strip()
    nodes = sentinel_nodes(
        settings.redis_sentinel_host, settings.redis_sentinel_port
    )
    log.info(
        "redis_sentinel nodes=%s master=%r username=%r password_length=%d",
        nodes,
        master,
        username,
        len(password),
    )
    account = transport | {"username": username, "password": password}
    sentinel = _Sentinel(nodes, sentinel_kwargs=account, **account)
    return sentinel.master_for(
        master, db=0, connection_pool_class=_SentinelPool
    )


def sentinel_nodes(hosts: str, port: int) -> list[tuple[str, int]]:
    """``host`` or ``host1,host2`` (each may carry its own ``:port``)."""
    nodes = []
    for item in hosts.split(","):
        host, _, own_port = item.strip().partition(":")
        if host:
            nodes.append((host, int(own_port) if own_port else port))
    return nodes


class _Sentinel(Sentinel):
    """Says why no master was found.

    redis-py reports a refused login, an unreachable Sentinel and an
    unknown master name alike as "No master found", with the reason at the
    end of a very long message.
    """

    async def discover_master(self, service_name: str) -> tuple[str, int]:
        try:
            return await super().discover_master(service_name)
        except MasterNotFoundError:
            for client in self.sentinels:
                where = client.connection_pool.connection_kwargs
                node = f"{where.get('host')}:{where.get('port')}"
                try:
                    masters = await client.sentinel_masters()
                except Exception as exc:  # noqa: BLE001 - reported, not handled
                    log.error(
                        "redis_sentinel_failed node=%s error=%s: %s",
                        node,
                        type(exc).__name__,
                        exc,
                    )
                    continue
                log.error(
                    "redis_sentinel_no_master node=%s wanted=%r known=%s",
                    node,
                    service_name,
                    {
                        name: state.get("flags")
                        for name, state in masters.items()
                    },
                )
            raise


class _SentinelPool(SentinelConnectionPool):
    """Closing the client also closes its connections to Sentinel."""

    async def disconnect(self, inuse_connections: bool = True) -> None:
        await super().disconnect(inuse_connections)
        for sentinel in self.sentinel_manager.sentinels:
            await sentinel.aclose()


def decrypt(value: str) -> str:
    """REDIS_SENTINEL_AUTH: AES-encrypted, as the internal guide requires."""
    try:
        from hcp.framework.util.crypto_cipher import (  # ty: ignore[unresolved-import]
            AESCipher,
        )
    except ImportError:
        raise RuntimeError(
            "REDIS_SENTINEL_AUTH needs the internal hcp library to decrypt."
        ) from None
    return AESCipher().decrypt_str(value)


async def listen(
    pubsub: PubSub, idle_seconds: float = PUBSUB_IDLE_SECONDS
) -> AsyncIterator[dict[str, Any]]:
    """Messages of a subscription; raises when the server stops answering.

    ``pubsub.listen()`` waits forever on a connection whose server is gone
    (a failed-over master that never closed it), and the subscriber would
    miss everything published on the new master.
    """
    pinged = False
    while True:
        message = await pubsub.get_message(timeout=idle_seconds)
        if message is None:
            if pinged:
                raise RedisConnectionError("No reply on the subscription.")
            await pubsub.ping()
            pinged = True
            continue
        pinged = False
        if message["type"] != "pong":
            yield message
