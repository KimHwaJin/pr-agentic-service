from collections.abc import AsyncIterator
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
    def __init__(self, url: str, pool_size: int):
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_pre_ping=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
