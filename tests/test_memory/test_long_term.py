"""Tests for LongTermMemory implementation."""

import pytest
from sqlalchemy import func, select

from ua.database.models import Base, User


@pytest.mark.asyncio
async def test_put_get_roundtrip(long_term_memory, user_id):
    """Test that put then get round-trips correctly."""
    await long_term_memory.put(user_id, "favorite_color", "blue")
    value = await long_term_memory.get(user_id, "favorite_color")
    assert value == "blue"


@pytest.mark.asyncio
async def test_put_upserts_not_duplicates(long_term_memory, user_id, session_factory):
    """Test that putting the same key twice updates rather than duplicates."""
    await long_term_memory.put(user_id, "favorite_color", "blue")
    await long_term_memory.put(user_id, "favorite_color", "green")

    # Should return the second value
    value = await long_term_memory.get(user_id, "favorite_color")
    assert value == "green"

    # Should have exactly 1 row, not 2
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(Base.metadata.tables["facts"]).where(
                Base.metadata.tables["facts"].c.user_id == user_id,
                Base.metadata.tables["facts"].c.key == "favorite_color"
            )
        )
        count = result.scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_search_substring_match_case_insensitive(long_term_memory, user_id):
    """Test that search does case-insensitive substring matching."""
    await long_term_memory.put(user_id, "hobby", "Chess")
    await long_term_memory.put(user_id, "favorite_color", "Blue")

    results = await long_term_memory.search(user_id, "ch")
    assert len(results) == 1
    assert results[0].key == "hobby"
    assert results[0].value == "Chess"


@pytest.mark.asyncio
async def test_search_respects_limit(long_term_memory, user_id):
    """Test that search respects the limit parameter."""
    await long_term_memory.put(user_id, "hobby1", "Chess")
    await long_term_memory.put(user_id, "hobby2", "Checkers")
    await long_term_memory.put(user_id, "hobby3", "Board games")

    # Search for "s" which appears in Chess, Checkers, Board games
    results = await long_term_memory.search(user_id, "s", limit=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_no_match_returns_empty_list(long_term_memory, user_id):
    """Test that search returns empty list when nothing matches."""
    await long_term_memory.put(user_id, "hobby", "Chess")

    results = await long_term_memory.search(user_id, "nonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_search_orders_most_recent_first(long_term_memory, user_id):
    """Test that search orders results by most recent first."""
    await long_term_memory.put(user_id, "color1", "Crimson")
    await long_term_memory.put(user_id, "color2", "Red")
    await long_term_memory.put(user_id, "color3", "Green")

    # Search for values containing "r" (Crimson, Red, Green - case insensitive)
    results = await long_term_memory.search(user_id, "r", limit=10)
    # Should be ordered most recent first: Green, Red, Crimson
    assert len(results) == 3
    assert results[0].value == "Green"  # Most recent
    assert results[1].value == "Red"
    assert results[2].value == "Crimson"


@pytest.mark.asyncio
async def test_memory_scoped_per_user(long_term_memory, session_factory):
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
    await long_term_memory.put(user1_id, "favorite_color", "blue")

    # user2 should not see it
    assert await long_term_memory.get(user2_id, "favorite_color") is None
    results = await long_term_memory.search(user2_id, "blue")
    assert len(results) == 0

    # user1 should see it
    assert await long_term_memory.get(user1_id, "favorite_color") == "blue"
    results = await long_term_memory.search(user1_id, "blue")
    assert len(results) == 1
