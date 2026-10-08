from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings

settings = get_settings()


def _build_engine_kwargs(database_url: str) -> dict[str, Any]:
    """
    Pool sizing applies only to server databases (PostgreSQL).
    SQLite (tests only) uses pool classes that reject pool_size and max_overflow.
    """
    kwargs: dict[str, Any] = {
        "echo": settings.DEBUG,
        "pool_pre_ping": True,
    }
    if make_url(database_url).get_backend_name() != "sqlite":
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return kwargs


engine = create_async_engine(
    settings.DATABASE_URL,
    **_build_engine_kwargs(settings.DATABASE_URL),
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding a thread-safe asynchronous database session
    with automatic rollback upon unhandled downstream exceptions.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()