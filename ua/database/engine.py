from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (  # noqa: E501
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from ua.config.settings import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def reset_engine() -> None:
    """Reset the cached engine and session factory.

    Used for testing to ensure a fresh engine is created with the current
    settings. Call this before tests that need to override database_url.
    """
    global _engine, _session_factory
    if _engine is not None:
        # Can't await in sync context - the engine will be garbage collected
        pass
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Create (or return a cached) async engine using settings.database_url.

    For sqlite+aiosqlite:///:memory: URLs, uses StaticPool to ensure all
    connections share the same in-memory database. Without this, each new
    connection would get its own separate :memory: database.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        # Use StaticPool for in-memory SQLite so all connections share one DB
        if "aiosqlite" in url and ":memory:" in url:
            _engine = create_async_engine(
                url,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            _engine = create_async_engine(url)
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
