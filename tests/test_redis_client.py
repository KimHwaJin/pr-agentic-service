import asyncio
import sys
import types

import pytest
from redis.asyncio.sentinel import SentinelConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError

from src.dtest.core import config, redis_client
from src.dtest.core.config import Settings


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)  # no .env
    monkeypatch.delenv("APP_ENV", raising=False)
    (tmp_path / "config.yml").write_text("redis_namespace: t\n")
    return tmp_path


SENTINEL = {
    "REDIS_MODE": "sentinel",
    "REDIS_SENTINEL_HOST": "sentinel.internal",
    "REDIS_SENTINEL_MASTER_NAME": "mymaster",
    "REDIS_SENTINEL_USERNAME": "svc",
    "REDIS_SENTINEL_AUTH": "encrypted",
}


def test_standalone_connects_to_the_url_and_its_db(root, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis.internal:6380/3")
    kwargs = redis_client.create_redis(Settings()).connection_pool
    kwargs = kwargs.connection_kwargs
    assert (kwargs["host"], kwargs["port"], kwargs["db"]) == (
        "redis.internal",
        6380,
        3,
    )
    assert kwargs["socket_timeout"] == redis_client.SOCKET_TIMEOUT


@pytest.mark.parametrize(
    "missing",
    [
        "REDIS_SENTINEL_HOST",
        "REDIS_SENTINEL_MASTER_NAME",
        "REDIS_SENTINEL_AUTH",
    ],
)
def test_sentinel_mode_needs_its_settings(root, monkeypatch, missing):
    for key, value in SENTINEL.items():
        if key != missing:
            monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="REDIS_MODE=sentinel needs"):
        Settings()


def test_sentinel_asks_for_the_master_on_db_0(root, monkeypatch):
    for key, value in SENTINEL.items():
        monkeypatch.setenv(key, value)
    # REDIS_URL is not used: its DB must not leak into sentinel mode
    monkeypatch.setenv("REDIS_URL", "redis://elsewhere:6379/3")
    monkeypatch.setattr(redis_client, "decrypt", lambda value: f"<{value}>")
    pool = redis_client.create_redis(Settings()).connection_pool
    assert isinstance(pool, SentinelConnectionPool)
    assert pool.service_name == "mymaster" and pool.is_master
    assert pool.connection_kwargs["db"] == 0
    assert pool.connection_kwargs["username"] == "svc"
    assert pool.connection_kwargs["password"] == "<encrypted>"
    (sentinel,) = pool.sentinel_manager.sentinels
    asked = sentinel.connection_pool.connection_kwargs
    assert (asked["host"], asked["port"]) == ("sentinel.internal", 26379)
    assert asked["password"] == "<encrypted>"  # the same account


def test_the_password_is_decrypted_with_hcp(monkeypatch):
    class AESCipher:
        def decrypt_str(self, value):
            return value[::-1]

    names = [
        "hcp",
        "hcp.framework",
        "hcp.framework.util",
        "hcp.framework.util.crypto_cipher",
    ]
    for name in names:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    setattr(sys.modules[names[-1]], "AESCipher", AESCipher)  # noqa: B010
    assert redis_client.decrypt("terces") == "secret"


def test_without_hcp_sentinel_mode_says_why(monkeypatch):
    monkeypatch.setitem(sys.modules, "hcp", None)
    with pytest.raises(RuntimeError, match="internal hcp library"):
        redis_client.decrypt("encrypted")


class _PubSub:
    def __init__(self, replies):
        self.replies, self.pings = list(replies), 0

    async def get_message(self, timeout):
        return self.replies.pop(0) if self.replies else None

    async def ping(self):
        self.pings += 1


async def _collect(pubsub):
    return [m async for m in redis_client.listen(pubsub, 0.01)]


def test_an_idle_subscription_is_pinged_and_goes_on():
    message = {"type": "message", "data": "x"}
    pubsub = _PubSub([None, {"type": "pong"}, message])
    seen = []

    async def run():
        async for item in redis_client.listen(pubsub, 0.01):  # ty: ignore[invalid-argument-type]
            seen.append(item)
            break

    asyncio.run(run())
    assert seen == [message] and pubsub.pings == 1


def test_a_subscription_that_stops_answering_raises():
    # a master that failed over without closing our connection
    pubsub = _PubSub([{"type": "message", "data": "x"}])
    with pytest.raises(RedisConnectionError):
        asyncio.run(_collect(pubsub))
    assert pubsub.pings == 1
