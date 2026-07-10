"""Tests for MemoryManager facade."""

import asyncio
import time

import pytest
import pytest_asyncio
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
