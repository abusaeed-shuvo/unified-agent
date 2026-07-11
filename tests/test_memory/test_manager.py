"""Tests for MemoryManager facade."""

import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.database.models import Base, User
from ua.memory.base import MemoryItem
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.manager import MemoryManager, RetrievedContext
from ua.memory.short_term import ShortTermMemory


# Fixtures for real in-memory stores
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
async def user_id(session_factory):
    """Create a test user and return its ID."""
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest_asyncio.fixture
def memory_manager():
    """Create a MemoryManager with real ShortTermMemory and fake long_term/knowledge."""
    short_term = ShortTermMemory(max_turns=20)
    # Create fake stores for tests that don't need real DB
    fake_long_term = _FakeMemoryStore()
    fake_knowledge = _FakeMemoryStore()
    return MemoryManager(
        short_term=short_term,
        long_term=fake_long_term,
        knowledge=fake_knowledge,
    )


@pytest_asyncio.fixture
async def real_memory_manager(session_factory, user_id):
    """Create a MemoryManager with all real in-memory stores."""
    short_term = ShortTermMemory(max_turns=20)
    long_term = LongTermMemory(session_factory)
    knowledge = KnowledgeMemory(session_factory)
    return MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )


class _FakeMemoryStore:
    """Fake memory store for testing with artificial delays."""

    def __init__(self) -> None:
        self._data: dict[str, list[MemoryItem]] = {}
        self._calls: list[tuple[str, str, int]] = []  # Track search calls

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        """Return stored items, with optional delay for concurrency testing."""
        self._calls.append((user_id, query, limit))
        return self._data.get(user_id, [])[:limit]

    async def put(self, user_id: str, key: str, value: str) -> None:
        """Store an item."""
        if user_id not in self._data:
            self._data[user_id] = []
        self._data[user_id].append(MemoryItem(key=key, value=value))


# Test: retrieve_context aggregates all three layers
@pytest.mark.asyncio
async def test_retrieve_context_aggregates_all_three_layers(
    real_memory_manager: MemoryManager, user_id: str
) -> None:
    """Test that retrieve_context combines results from all three stores."""
    manager = real_memory_manager

    # Add data to each layer
    await manager.record_turn(user_id, "user", "Hello, I love chess!")
    await manager.remember_fact(user_id, "favorite_game", "chess")

    context = await manager.retrieve_context(user_id, "chess")

    # Check recent_turns
    assert len(context.recent_turns) == 1
    assert context.recent_turns[0].content == "Hello, I love chess!"

    # Check relevant_facts
    assert len(context.relevant_facts) == 1
    assert context.relevant_facts[0].key == "favorite_game"
    assert context.relevant_facts[0].value == "chess"

    # Check relevant_knowledge (empty since we didn't add any)
    assert context.relevant_knowledge == []


@pytest.mark.asyncio
async def test_retrieve_context_aggregates_all_three_layers_with_knowledge(
    session_factory: async_sessionmaker, user_id: str
) -> None:
    """Test that retrieve_context combines results from all three stores including knowledge."""
    short_term = ShortTermMemory(max_turns=20)
    long_term = LongTermMemory(session_factory)
    knowledge = KnowledgeMemory(session_factory)

    manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    # Add data to each layer
    await manager.record_turn(user_id, "user", "Hello, I love chess!")
    await manager.remember_fact(user_id, "favorite_game", "chess")

    # Add knowledge document directly
    await knowledge.add_document(user_id, "Chess Notes", "Chess is a strategy game")

    context = await manager.retrieve_context(user_id, "chess")

    # Check recent_turns
    assert len(context.recent_turns) == 1
    assert context.recent_turns[0].content == "Hello, I love chess!"

    # Check relevant_facts
    assert len(context.relevant_facts) == 1
    assert context.relevant_facts[0].key == "favorite_game"
    assert context.relevant_facts[0].value == "chess"

    # Check relevant_knowledge
    assert len(context.relevant_knowledge) == 1
    assert context.relevant_knowledge[0].key == "Chess Notes"
    assert context.relevant_knowledge[0].value == "Chess is a strategy game"


# Test: retrieve_context runs fetches concurrently
@pytest.mark.asyncio
async def test_retrieve_context_runs_fetches_concurrently() -> None:
    """Test that the three fetches in retrieve_context run concurrently, not sequentially."""

    class _SlowFakeMemoryStore:
        """Fake memory store with artificial delay to test concurrency."""

        def __init__(self, delay: float = 0.1) -> None:
            self._delay = delay
            self._data: dict[str, list[MemoryItem]] = {}

        async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
            """Return stored items after an artificial delay."""
            await asyncio.sleep(self._delay)
            return self._data.get(user_id, [])[:limit]

        async def put(self, user_id: str, key: str, value: str) -> None:
            """Store an item."""
            if user_id not in self._data:
                self._data[user_id] = []
            self._data[user_id].append(MemoryItem(key=key, value=value))

    short_term = ShortTermMemory(max_turns=20)
    # Add a turn to short_term
    await short_term.append_turn("user1", "user", "test message")

    slow_long_term = _SlowFakeMemoryStore(delay=0.1)
    slow_knowledge = _SlowFakeMemoryStore(delay=0.1)

    manager = MemoryManager(
        short_term=short_term,
        long_term=slow_long_term,
        knowledge=slow_knowledge,
    )

    # Time the retrieve_context call
    start = time.monotonic()
    context = await manager.retrieve_context("user1", "test query")
    elapsed = time.monotonic() - start

    # If running sequentially, it would take ~0.2s (0.1 + 0.1)
    # If running concurrently, it should take ~0.1s
    # Use a tolerance to account for test overhead
    assert elapsed < 0.2, f"Expected concurrent execution, but took {elapsed:.3f}s"

    # Verify the context is still correct
    assert isinstance(context, RetrievedContext)
    assert len(context.recent_turns) == 1


# Test: record_turn only writes short_term
@pytest.mark.asyncio
async def test_record_turn_only_writes_short_term(memory_manager: MemoryManager) -> None:
    """Test that record_turn writes only to short-term memory."""
    manager = memory_manager

    # Record a turn
    await manager.record_turn("user1", "user", "Hello!")

    # Check short_term has the turn
    turns = await manager._short_term.recent_turns("user1", limit=10)
    assert len(turns) == 1
    assert turns[0].content == "Hello!"

    # Check that long_term was NOT written to (it's a fake, we can check its data)
    assert "user1" not in memory_manager._long_term._data or len(
        memory_manager._long_term._data.get("user1", [])
    ) == 0


# Test: remember_fact only writes long_term
@pytest.mark.asyncio
async def test_remember_fact_only_writes_long_term(memory_manager: MemoryManager) -> None:
    """Test that remember_fact writes only to long-term memory."""
    manager = memory_manager

    # Remember a fact
    await manager.remember_fact("user1", "favorite_color", "blue")

    # Check long_term has the fact
    # The fake store tracks data in _data
    assert "user1" in memory_manager._long_term._data
    assert len(memory_manager._long_term._data["user1"]) == 1
    assert memory_manager._long_term._data["user1"][0].key == "favorite_color"
    assert memory_manager._long_term._data["user1"][0].value == "blue"

    # Check that short_term was NOT written to
    turns = await manager._short_term.recent_turns("user1", limit=10)
    assert turns == []


# Test: record_turn then retrieve_context includes it
@pytest.mark.asyncio
async def test_record_turn_then_retrieve_context_includes_it(
    real_memory_manager: MemoryManager, user_id: str
) -> None:
    """Test that a turn recorded via record_turn appears in retrieve_context results."""
    manager = real_memory_manager

    # Record a turn
    await manager.record_turn(user_id, "user", "What is the weather?")

    # Retrieve context
    context = await manager.retrieve_context(user_id, "weather")

    # The turn should be in recent_turns
    assert len(context.recent_turns) == 1
    assert context.recent_turns[0].role == "user"
    assert context.recent_turns[0].content == "What is the weather?"


# Tests for eviction summarization (Batch 27)
@pytest.mark.asyncio
async def test_eviction_triggers_default_summarizer_and_long_term_write(
    session_factory: async_sessionmaker,
) -> None:
    """Test that eviction triggers the default summarizer and writes to long_term."""
    # Create a user
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user_evict")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        test_user_id = user.id

    # Create memory manager with small max_turns
    short_term = ShortTermMemory(max_turns=3)
    long_term = LongTermMemory(session_factory)
    knowledge = KnowledgeMemory(session_factory)
    manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    # Record 3 turns (at cap, no eviction yet)
    for i in range(3):
        await manager.record_turn(test_user_id, "user", f"Message {i}")

    # Verify no summary exists yet
    summary = await manager._long_term.get(test_user_id, "conversation_summary")
    assert summary is None

    # Record one more turn to trigger eviction
    await manager.record_turn(test_user_id, "user", "Message 3")

    # Now a summary should exist
    summary = await manager._long_term.get(test_user_id, "conversation_summary")
    assert summary is not None
    assert "Message 0" in summary


@pytest.mark.asyncio
async def test_evicted_content_recognizable_in_stored_summary(
    session_factory: async_sessionmaker,
) -> None:
    """Test that the stored summary contains recognizable content from evicted turns."""
    # Create a user
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user_summary")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        test_user_id = user.id

    # Create memory manager with small max_turns
    short_term = ShortTermMemory(max_turns=2)
    long_term = LongTermMemory(session_factory)
    knowledge = KnowledgeMemory(session_factory)
    manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    # Record turns with specific content
    await manager.record_turn(test_user_id, "user", "I love chess and strategy games")
    await manager.record_turn(test_user_id, "assistant", "That's interesting!")
    await manager.record_turn(test_user_id, "user", "What about poker?")  # Triggers eviction

    # Get the stored summary
    summary = await manager._long_term.get(test_user_id, "conversation_summary")

    # The summary should contain content from the evicted turn
    assert "chess" in summary
    assert "strategy" in summary


@pytest.mark.asyncio
async def test_repeated_evictions_overwrite_not_duplicate_summary_fact(
    session_factory: async_sessionmaker,
) -> None:
    """Test that repeated evictions overwrite (not duplicate) the conversation_summary fact."""
    # Create a user
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user_overwrite")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        test_user_id = user.id

    # Create memory manager with small max_turns
    short_term = ShortTermMemory(max_turns=2)
    long_term = LongTermMemory(session_factory)
    knowledge = KnowledgeMemory(session_factory)
    manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    # Record 6 turns to trigger multiple evictions
    for i in range(6):
        await manager.record_turn(test_user_id, "user", f"Message number {i} about topic X")

    # Check that exactly one row exists for conversation_summary
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(Base.metadata.tables["facts"]).where(
                Base.metadata.tables["facts"].c.user_id == test_user_id,
                Base.metadata.tables["facts"].c.key == "conversation_summary"
            )
        )
        count = result.scalar_one()
        assert count == 1, f"Expected exactly 1 row, but found {count}"

    # The summary should contain the most recently evicted message (message 3)
    # With max_turns=2, each eviction overwrites the previous summary
    summary = await manager._long_term.get(test_user_id, "conversation_summary")
    assert "Message number 3" in summary  # Last evicted message


@pytest.mark.asyncio
async def test_default_summarizer_is_pure_python_no_network_dependency():
    """Test that the default summarizer is pure Python with no network dependency.

    This test verifies:
    1. The summarizer completes quickly (no network I/O)
    2. No adapter or HTTP mock is configured/needed
    3. The summarizer produces deterministic output
    """
    from ua.memory.manager import default_summarizer
    from ua.models.base import Message

    # Create test messages
    messages = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there!"),
        Message(role="user", content="How are you?"),
    ]

    # Time the summarizer execution - should be near-instant
    import time
    start = time.monotonic()
    result = default_summarizer(messages)
    elapsed = time.monotonic() - start

    # Should complete in well under 1 second (no network calls)
    assert elapsed < 0.1, f"Summarizer took {elapsed:.3f}s, likely making network calls"

    # Verify deterministic output format
    assert result == "user: Hello\nassistant: Hi there!\nuser: How are you?"

    # Verify truncation works
    long_messages = [
        Message(role="user", content="x" * 300),
        Message(role="assistant", content="y" * 300),
    ]
    result = default_summarizer(long_messages)
    assert len(result) == 500, f"Expected 500 chars max, got {len(result)}"
