"""The run scheduler survives database and Redis failures."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from src.dtest.worker.runtime import Worker
from src.dtest.worker.scheduler import RunScheduler


def _scheduler(lease_seconds=60):
    settings = SimpleNamespace(
        run_concurrency=4,
        run_poll_seconds=0.01,
        run_lease_seconds=lease_seconds,
        redis_namespace="t",
    )
    services = SimpleNamespace(settings=settings)
    scheduler = RunScheduler(cast(Any, services), cast(Any, None), "pod-1")

    async def no_listener():
        await asyncio.Event().wait()

    scheduler._listen = no_listener  # type: ignore[method-assign]
    return scheduler


async def test_claim_failures_do_not_end_the_loop(monkeypatch):
    scheduler = _scheduler()
    calls = 0
    real_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        await real_sleep(0)

    async def claim(limit):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("db down")
        scheduler.accepting = False  # the third claim works: stop
        return []

    monkeypatch.setattr("src.dtest.worker.scheduler.asyncio.sleep", fast_sleep)
    scheduler._claim = claim  # type: ignore[method-assign]
    await asyncio.wait_for(scheduler.run_forever(), 2)
    assert calls == 3


async def test_heartbeat_retries_then_stops_an_unrenewed_turn(monkeypatch):
    scheduler = _scheduler(lease_seconds=3)
    beats = 0
    clock = [0.0]

    real_sleep = asyncio.sleep

    async def tick(seconds):
        clock[0] += seconds
        await real_sleep(0)

    async def renew(run_id):
        nonlocal beats
        beats += 1
        raise ConnectionError("db down")

    monkeypatch.setattr("src.dtest.worker.scheduler.asyncio.sleep", tick)
    monkeypatch.setattr(
        "src.dtest.worker.scheduler.monotonic", lambda: clock[0]
    )
    scheduler._renew = renew  # type: ignore[method-assign]
    turn = asyncio.get_running_loop().create_future()
    await asyncio.wait_for(scheduler._heartbeat("r1", cast(Any, turn)), 2)
    # 1 s and 2 s without a renewal: the second reaches 2/3 of the lease
    assert beats == 2 and turn.cancelled()


async def test_one_failed_beat_keeps_the_turn(monkeypatch):
    scheduler = _scheduler(lease_seconds=30)
    results = [ConnectionError("blip"), None]

    async def renew(run_id):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result  # None: the lease is gone, the turn stops

    real_sleep = asyncio.sleep

    async def tick(seconds):
        await real_sleep(0)

    monkeypatch.setattr("src.dtest.worker.scheduler.asyncio.sleep", tick)
    scheduler._renew = renew  # type: ignore[method-assign]
    turn = asyncio.get_running_loop().create_future()
    await asyncio.wait_for(scheduler._heartbeat("r1", cast(Any, turn)), 2)
    assert results == [] and turn.cancelled()


async def test_dead_loops_are_reported_until_shutdown():
    worker = cast(Any, Worker.__new__(Worker))
    worker.stopping = False

    async def crash():
        raise RuntimeError("boom")

    async def forever():
        await asyncio.Event().wait()

    worker.tasks = [
        asyncio.create_task(crash(), name="run-scheduler"),
        asyncio.create_task(forever(), name="executor-events"),
    ]
    await asyncio.sleep(0)
    assert worker.stopped_loops() == ["run-scheduler"]
    worker.stopping = True
    assert worker.stopped_loops() == []
    for task in worker.tasks:
        task.cancel()
    await asyncio.gather(*worker.tasks, return_exceptions=True)


async def test_stop_drains_runs_and_memory_together():
    worker = cast(Any, Worker.__new__(Worker))
    worker.stopping, worker.tasks = False, []
    started: list[str] = []

    async def drain(name, seconds):
        started.append(name)
        await asyncio.sleep(0.2)

    worker.scheduler = SimpleNamespace(drain=lambda s: drain("runs", s))
    worker.memory = SimpleNamespace(stop=lambda s: drain("memory", s))
    loop = asyncio.get_running_loop()
    begin = loop.time()
    await worker.stop(drain_seconds=1)
    assert sorted(started) == ["memory", "runs"]
    assert loop.time() - begin < 0.35
