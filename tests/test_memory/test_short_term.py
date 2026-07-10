"""Tests for ShortTermMemory implementation."""

import pytest

from ua.memory.short_term import ShortTermMemory


@pytest.fixture
def memory():
    """Create a ShortTermMemory instance with default max_turns."""
    return ShortTermMemory(max_turns=20)


@pytest.mark.asyncio
async def test_cap_evicts_oldest_turns():
    """Test that appending more than max_turns evicts the oldest turns."""
    mem = ShortTermMemory(max_turns=3)

    # Append 5 turns
    for i in range(5):
        await mem.append_turn("user1", "user", f"message {i}")

    # Should only have the last 3 turns (2, 3, 4)
    turns = await mem.recent_turns("user1", limit=10)
    assert len(turns) == 3
    assert turns[0].content == "message 2"
    assert turns[1].content == "message 3"
    assert turns[2].content == "message 4"


@pytest.mark.asyncio
async def test_recent_turns_chronological_order():
    """Test that recent_turns returns turns in chronological order."""
    mem = ShortTermMemory(max_turns=20)

    # Append turns in order
    await mem.append_turn("user1", "user", "first")
    await mem.append_turn("user1", "assistant", "second")
    await mem.append_turn("user1", "user", "third")

    # Get recent turns
    turns = await mem.recent_turns("user1", limit=10)

    # Should be in chronological order (oldest first)
    assert turns[0].content == "first"
    assert turns[1].content == "second"
    assert turns[2].content == "third"


@pytest.mark.asyncio
async def test_recent_turns_fewer_than_limit_available():
    """Test that recent_turns returns all turns when fewer than limit exist."""
    mem = ShortTermMemory(max_turns=20)

    # Append only 3 turns
    await mem.append_turn("user1", "user", "message 1")
    await mem.append_turn("user1", "assistant", "message 2")
    await mem.append_turn("user1", "user", "message 3")

    # Request with limit=10, but only 3 exist
    turns = await mem.recent_turns("user1", limit=10)
    assert len(turns) == 3
    assert turns[0].content == "message 1"
    assert turns[1].content == "message 2"
    assert turns[2].content == "message 3"


@pytest.mark.asyncio
async def test_recent_turns_empty_for_unknown_user():
    """Test that recent_turns returns empty list for user with no turns."""
    mem = ShortTermMemory(max_turns=20)

    # User has never appended any turns
    turns = await mem.recent_turns("nonexistent_user", limit=10)
    assert turns == []


@pytest.mark.asyncio
async def test_turns_scoped_per_user():
    """Test that turn history is isolated per user_id."""
    mem = ShortTermMemory(max_turns=20)

    # Add turns for user1
    await mem.append_turn("user1", "user", "user1 message")
    await mem.append_turn("user1", "assistant", "user1 response")

    # Add turns for user2
    await mem.append_turn("user2", "user", "user2 message")
    await mem.append_turn("user2", "assistant", "user2 response")

    # Check user1's turns
    user1_turns = await mem.recent_turns("user1", limit=10)
    assert len(user1_turns) == 2
    assert user1_turns[0].content == "user1 message"
    assert user1_turns[1].content == "user1 response"

    # Check user2's turns
    user2_turns = await mem.recent_turns("user2", limit=10)
    assert len(user2_turns) == 2
    assert user2_turns[0].content == "user2 message"
    assert user2_turns[1].content == "user2 response"


@pytest.mark.asyncio
async def test_scratch_space_put_get_roundtrip(memory):
    """Test that put and get round-trip correctly for scratch space."""
    await memory.put("user1", "current_topic", "Python programming")
    value = await memory.get("user1", "current_topic")
    assert value == "Python programming"


@pytest.mark.asyncio
async def test_scratch_space_search_case_insensitive():
    """Test that search is case-insensitive."""
    mem = ShortTermMemory(max_turns=20)

    await mem.put("user1", "hobby", "Chess")
    await mem.put("user1", "favorite_color", "Blue")

    # Search with different cases
    results = await mem.search("user1", "ch")
    assert len(results) == 1
    assert results[0].key == "hobby"
    assert results[0].value == "Chess"

    results = await mem.search("user1", "CHESS")
    assert len(results) == 1
    assert results[0].key == "hobby"

    results = await mem.search("user1", "blue")
    assert len(results) == 1
    assert results[0].key == "favorite_color"


@pytest.mark.asyncio
async def test_scratch_space_scoped_per_user():
    """Test that scratch space is isolated per user_id."""
    mem = ShortTermMemory(max_turns=20)

    # Add scratch data for user1
    await mem.put("user1", "topic", "Python")
    await mem.put("user1", "mood", "happy")

    # Add scratch data for user2
    await mem.put("user2", "topic", "JavaScript")
    await mem.put("user2", "mood", "excited")

    # user1 should only see their own data
    assert await mem.get("user1", "topic") == "Python"
    assert await mem.get("user1", "mood") == "happy"
    assert await mem.get("user1", "nonexistent") is None

    # user2 should only see their own data
    assert await mem.get("user2", "topic") == "JavaScript"
    assert await mem.get("user2", "mood") == "excited"
    assert await mem.get("user2", "nonexistent") is None

    # Search should also be scoped
    results = await mem.search("user1", "python")
    assert len(results) == 1
    assert results[0].key == "topic"

    results = await mem.search("user2", "python")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_scratch_space_search_no_match_returns_empty_list():
    """Test that search returns empty list when nothing matches."""
    mem = ShortTermMemory(max_turns=20)

    await mem.put("user1", "hobby", "Chess")

    results = await mem.search("user1", "nonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_scratch_space_search_respects_limit():
    """Test that search respects the limit parameter."""
    mem = ShortTermMemory(max_turns=20)

    await mem.put("user1", "hobby1", "Chess")
    await mem.put("user1", "hobby2", "Checkers")
    await mem.put("user1", "hobby3", "Board games")

    # Search for "s" which appears in all three values
    results = await mem.search("user1", "s", limit=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_turns_and_scratch_isolated():
    """Test that turn history and scratch space are separate."""
    mem = ShortTermMemory(max_turns=20)

    # Add a turn
    await mem.append_turn("user1", "user", "Hello")

    # Add scratch data
    await mem.put("user1", "topic", "Python")

    # Turn history should have 1 turn
    turns = await mem.recent_turns("user1", limit=10)
    assert len(turns) == 1
    assert turns[0].content == "Hello"

    # Scratch space should have 1 item
    assert await mem.get("user1", "topic") == "Python"

    # They should not interfere with each other
    assert await mem.get("user1", "nonexistent") is None
