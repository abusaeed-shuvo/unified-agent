from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (  # noqa: E501
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ua.config.settings import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Create (or return a cached) async engine using settings.database_url."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Async generator yielding a session; usable as a FastAPI-style dependency."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """Dev/test convenience: create all tables via Base.metadata.create_all.

    Not for production migrations (a future batch may add Alembic).
    """
    engine = get_engine()
    from ua.database.models import Base  # noqa: PLC0415

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
