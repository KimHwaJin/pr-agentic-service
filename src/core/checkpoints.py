"""Checkpoint saver whose reads and writes run side by side.

LangGraph's ``AsyncPostgresSaver`` (langgraph-checkpoint-postgres 3.1.3 and
3.2.0) holds one ``asyncio.Lock`` per saver around every database call
(``_cursor``), even when it is given a connection pool. One saver serves the
whole process, so every turn's checkpoint reads and writes waited in one
line however large ``CHECKPOINT_POOL_SIZE`` was.

The lock guards a single shared connection. With a pool each call borrows
its own connection, so here the lock does nothing; the library's own
``AsyncPostgresStore`` does the same for a pool (a new lock per call).
Two writes to the same thread at once stay impossible: a session runs one
turn at a time (``runs`` claim), and each turn is one thread.

``tests/test_checkpoint_saver.py`` fails if a library upgrade moves the
lock, so the version is pinned in pyproject.toml.
"""

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool


class _NoLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


class PooledPostgresSaver(AsyncPostgresSaver):
    def __init__(self, conn: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(conn, *args, **kwargs)
        if isinstance(conn, AsyncConnectionPool) and self.pipe is None:
            self.lock = _NoLock()  # ty: ignore[invalid-assignment]
