import os
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.database.engine import get_engine, get_session, init_db
from ua.database.models import Base


@pytest.mark.asyncio
async def test_init_db_creates_tables(monkeypatch):
    """Test that init_db creates all four tables in a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        url = f"sqlite+aiosqlite:///{db_path}"

        # Clear caches and override via environment variable
        from ua.config.settings import get_settings
        from ua.database import engine as db_engine

        original_engine = db_engine._engine
        original_factory = db_engine._session_factory

        try:
            monkeypatch.setenv("UA_DATABASE_URL", url)
            db_engine._engine = None
            db_engine._session_factory = None
            get_settings.cache_clear()

            await init_db()

            # Verify tables exist using sqlite3 CLI-style check
            engine = create_async_engine(url)
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                )
                tables = [row[0] for row in result.fetchall()]

                assert "users" in tables
                assert "sessions" in tables
                assert "messages" in tables
                assert "facts" in tables

            await engine.dispose()
        finally:
            # Restore original state
            db_engine._engine = original_engine
            db_engine._session_factory = original_factory
            get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_engine_returns_cached_instance(monkeypatch):
    """Test that get_engine returns the same engine on repeated calls."""
    # Reset cache and set in-memory database
    from ua.config.settings import get_settings
    from ua.database import engine as db_engine

    db_engine._engine = None
    get_settings.cache_clear()
    monkeypatch.setenv("UA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    engine1 = get_engine()
    engine2 = get_engine()
    assert engine1 is engine2


@pytest.mark.asyncio
async def test_get_session_yields_session(monkeypatch):
    """Test that get_session yields a valid AsyncSession."""
    # Set in-memory database to avoid file leak
    from ua.config.settings import get_settings
    from ua.database import engine as db_engine

    db_engine._engine = None
    db_engine._session_factory = None
    get_settings.cache_clear()
    monkeypatch.setenv("UA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    session_gen = get_session()
    session = await session_gen.__anext__()
    assert session.is_active

    # Clean up
    try:
        await session_gen.__anext__()
    except StopAsyncIteration:
        pass


@pytest.mark.asyncio
async def test_session_roundtrip():
    """Test basic insert and query via a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        from ua.database.models import User

        user = User(platform="discord", platform_user_id="12345")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        assert user.id is not None
        assert user.platform == "discord"
        assert user.platform_user_id == "12345"

    await engine.dispose()
