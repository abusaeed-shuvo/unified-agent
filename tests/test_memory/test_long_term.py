"""Tests for LongTermMemory implementation."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.database.models import Base, User
from ua.memory.long_term import LongTermMemory


@pytest_asyncio.fixture
async def session_factory():
    """Create an in-memory SQLite engine and session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def memory(session_factory):
    """Create a LongTermMemory instance with the test session factory."""
    return LongTermMemory(session_factory)


@pytest_asyncio.fixture
async def user_id(session_factory):
    """Create a test user and return its ID."""
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.mark.asyncio
async def test_put_get_roundtrip(memory, user_id):
    """Test that put then get round-trips correctly."""
    await memory.put(user_id, "favorite_color", "blue")
    value = await memory.get(user_id, "favorite_color")
    assert value == "blue"


@pytest.mark.asyncio
async def test_put_upserts_not_duplicates(memory, user_id, session_factory):
    """Test that putting the same key twice updates rather than duplicates."""
    await memory.put(user_id, "favorite_color", "blue")
    await memory.put(user_id, "favorite_color", "green")

    # Should return the second value
    value = await memory.get(user_id, "favorite_color")
    assert value == "green"

    # Should have exactly 1 row, not 2
    async with session_factory() as session:
        from sqlalchemy import func, select
        result = await session.execute(
            select(func.count()).select_from(Base.metadata.tables["facts"]).where(
                Base.metadata.tables["facts"].c.user_id == user_id,
                Base.metadata.tables["facts"].c.key == "favorite_color"
            )
        )
        count = result.scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_search_substring_match_case_insensitive(memory, user_id):
    """Test that search does case-insensitive substring matching."""
    await memory.put(user_id, "hobby", "Chess")
    await memory.put(user_id, "favorite_color", "Blue")

    results = await memory.search(user_id, "ch")
    assert len(results) == 1
    assert results[0].key == "hobby"
    assert results[0].value == "Chess"


@pytest.mark.asyncio
async def test_search_respects_limit(memory, user_id):
    """Test that search respects the limit parameter."""
    await memory.put(user_id, "hobby1", "Chess")
    await memory.put(user_id, "hobby2", "Checkers")
    await memory.put(user_id, "hobby3", "Board games")

    # Search for "s" which appears in Chess, Checkers, Board games
    results = await memory.search(user_id, "s", limit=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_no_match_returns_empty_list(memory, user_id):
    """Test that search returns empty list when nothing matches."""
    await memory.put(user_id, "hobby", "Chess")

    results = await memory.search(user_id, "nonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_search_orders_most_recent_first(memory, user_id):
    """Test that search orders results by most recent first."""
    await memory.put(user_id, "color1", "Crimson")
    await memory.put(user_id, "color2", "Red")
    await memory.put(user_id, "color3", "Green")

    # Search for values containing "r" (Crimson, Red, Green - case insensitive)
    results = await memory.search(user_id, "r", limit=10)
    # Should be ordered most recent first: Green, Red, Crimson
    assert len(results) == 3
    assert results[0].value == "Green"  # Most recent
    assert results[1].value == "Red"
    assert results[2].value == "Crimson"


@pytest.mark.asyncio
async def test_memory_scoped_per_user(memory, session_factory):
    """Test that facts are scoped per user."""
    # Create two users
    async with session_factory() as session:
        user1 = User(platform="test", platform_user_id="user1")
        user2 = User(platform="test", platform_user_id="user2")
        session.add_all([user1, user2])
        await session.commit()
        await session.refresh(user1)
        await session.refresh(user2)
        user1_id = user1.id
        user2_id = user2.id

    # Add fact for user1
    await memory.put(user1_id, "favorite_color", "blue")

    # user2 should not see it
    assert await memory.get(user2_id, "favorite_color") is None
    results = await memory.search(user2_id, "blue")
    assert len(results) == 0

    # user1 should see it
    assert await memory.get(user1_id, "favorite_color") == "blue"
    results = await memory.search(user1_id, "blue")
    assert len(results) == 1
