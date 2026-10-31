"""PooledPostgresSaver: checkpoint calls of different turns overlap.

Fails when a langgraph-checkpoint-postgres upgrade changes where the lock
is taken (core/checkpoints.py relies on it); check before moving the pin.
"""

import asyncio
import inspect
from contextlib import asynccontextmanager

import pytest
from langgraph.checkpoint.postgres import aio
from psycopg_pool import AsyncConnectionPool

from src.dtest.core.checkpoints import PooledPostgresSaver


class _Conn:
    @asynccontextmanager
    async def cursor(self, **kwargs):
        yield object()

    @asynccontextmanager
    async def transaction(self):
        yield


@pytest.fixture
def fake_connections(monkeypatch):
    @asynccontextmanager
    async def get_connection(conn):
        yield _Conn()

    monkeypatch.setattr(aio._ainternal, "get_connection", get_connection)


async def _peak_overlap(saver, calls: int = 4) -> int:
    inside = peak = 0

    async def one():
        nonlocal inside, peak
        async with saver._cursor():
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.05)
            inside -= 1

    await asyncio.gather(*(one() for _ in range(calls)))
    return peak


async def test_calls_on_a_pool_run_side_by_side(fake_connections):
    pool = AsyncConnectionPool("postgresql://unused", open=False)
    assert await _peak_overlap(PooledPostgresSaver(pool)) == 4


async def test_a_single_connection_keeps_the_lock(fake_connections):
    saver = PooledPostgresSaver(_Conn())
    assert isinstance(saver.lock, asyncio.Lock)
    assert await _peak_overlap(saver) == 1


def test_the_library_still_locks_where_we_expect():
    # the stock saver takes self.lock in _cursor; if this moves, revisit
    # core/checkpoints.py
    source = inspect.getsource(aio.AsyncPostgresSaver._cursor)
    assert "async with self.lock" in source
