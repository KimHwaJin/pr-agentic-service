"""Executor cancels are retried until the executor has heard."""

import time
from types import SimpleNamespace
from typing import Any, cast

import httpx

from core.executor import cancels
from core.executor.client import ExecutorError, Identity


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}

    async def hsetnx(self, key, field, value):
        self.hashes.setdefault(key, {}).setdefault(field, value)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)


class FakeExecutor:
    def __init__(self, *failures):
        self.failures, self.cancelled = list(failures), []

    async def opener(self, execution_id):
        return Identity(user_id="u")

    async def cancel(self, execution_id, **kwargs):
        if self.failures:
            raise self.failures.pop(0)
        self.cancelled.append(execution_id)


def _services(executor):
    return cast(
        Any,
        SimpleNamespace(
            executor=executor,
            redis=FakeRedis(),
            settings=SimpleNamespace(redis_namespace="t"),
        ),
    )


async def test_an_execution_already_over_needs_no_retry():
    services = _services(FakeExecutor(ExecutorError(409, {})))
    assert await cancels.cancel_execution(services, "e1", key="k", reason="r")
    assert services.redis.hashes == {}


async def test_a_down_executor_is_asked_again_by_the_worker():
    executor = FakeExecutor(
        ExecutorError(503, "down"), httpx.ConnectError("refused")
    )
    services = _services(executor)
    sent = await cancels.cancel_execution(services, "e1", key="k", reason="r")
    assert not sent and "e1" in services.redis.hashes["t:executor-cancels"]
    retry = cancels.ExecutionCancelRetry(services)
    assert await retry.sweep() == 0  # still failing: kept
    assert "e1" in services.redis.hashes["t:executor-cancels"]
    assert await retry.sweep() == 1
    assert executor.cancelled == ["e1"]
    assert services.redis.hashes["t:executor-cancels"] == {}


async def test_retries_stop_after_the_executor_limit(monkeypatch):
    services = _services(FakeExecutor(*[ExecutorError(500, "")] * 3))
    await cancels.cancel_execution(services, "e1", key="k", reason="r")
    later = time.time() + cancels.GIVE_UP_SECONDS + 1
    monkeypatch.setattr(cancels.time, "time", lambda: later)
    await cancels.ExecutionCancelRetry(services).sweep()
    assert services.redis.hashes["t:executor-cancels"] == {}
