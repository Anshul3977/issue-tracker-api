"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    connect_args=settings.database_connect_args,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session and commit if the request succeeded.

    Write handlers that must run side effects after the commit call
    ``session.commit()`` themselves. The extra commit here is then a no-op.
    """

    from sqlalchemy.exc import IntegrityError

    from app.errors import APIError

    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise APIError(409, "conflict", "Unique constraint violated") from exc
        except Exception:
            await session.rollback()
            raise
