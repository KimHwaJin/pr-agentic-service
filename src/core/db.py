from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import CursorResult, DateTime, Result
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


APP_POOL_NAME = "pr-agentic-app"
GRAPH_POOL_NAME = "pr-agentic-graph"


class Base(DeclarativeBase):
    pass


class NotFound(LookupError):
    """A row that must exist is gone (deleted concurrently)."""


async def get_row[T](
    db: AsyncSession, model: type[T], key: Any, *, lock: bool = False
) -> T:
    row = await db.get(model, key, with_for_update=lock)
    if row is None:
        raise NotFound(f"{model.__name__} {key} not found")
    return row


def affected(result: Result[Any]) -> int:
    """Rows changed by an UPDATE/DELETE (``execute`` is typed as Result)."""
    return cast(CursorResult[Any], result).rowcount


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Database:
    def __init__(
        self, url: str, pool_size: int, application_name: str = APP_POOL_NAME
    ):
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_pre_ping=True,
            # names the connections in pg_stat_activity, so the shared
            # database can tell this pool from the checkpoint pool and
            # from the other services
            connect_args={"application_name": application_name},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.engine.dispose()
