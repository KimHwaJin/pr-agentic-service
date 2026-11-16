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

from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.asyncio.sentinel import Sentinel, SentinelConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError

from core.config import Settings

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
    account = transport | {
        "username": settings.redis_sentinel_username or None,
        "password": decrypt(settings.redis_sentinel_auth),
    }
    sentinel = Sentinel(
        [(settings.redis_sentinel_host, settings.redis_sentinel_port)],
        sentinel_kwargs=account,
        **account,
    )
    return sentinel.master_for(
        settings.redis_sentinel_master_name,
        db=0,
        connection_pool_class=_SentinelPool,
    )


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
