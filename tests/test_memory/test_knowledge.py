"""Tests for KnowledgeMemory implementation."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.database.models import Base, User
from ua.memory.knowledge import KnowledgeMemory


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
    """Create a KnowledgeMemory instance with the test session factory."""
    return KnowledgeMemory(session_factory)


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
async def test_add_document_then_get_roundtrip(memory, user_id):
    """Test that add_document then get round-trips the content correctly."""
    doc_id = await memory.add_document(
        user_id, "Meeting Notes", "We discussed the Q3 roadmap and chess strategy."
    )
    content = await memory.get(user_id, doc_id)
    assert content == "We discussed the Q3 roadmap and chess strategy."


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(memory, user_id):
    """Test that get returns None for an unknown document id."""
    content = await memory.get(user_id, "nonexistent-id")
    assert content is None


@pytest.mark.asyncio
async def test_get_returns_none_when_wrong_user(memory, session_factory):
    """Test that get returns None when the document belongs to a different user."""
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

    # Add document for user1
    doc_id = await memory.add_document(
        user1_id, "Secret Notes", "This is user1's private content."
    )

    # user2 should not be able to access it
    content = await memory.get(user2_id, doc_id)
    assert content is None


@pytest.mark.asyncio
async def test_search_substring_match_case_insensitive(memory, user_id):
    """Test that search does case-insensitive substring matching."""
    await memory.add_document(user_id, "Doc1", "Chess is a strategy game")
    await memory.add_document(user_id, "Doc2", "chess is also a game")

    results = await memory.search(user_id, "chess")
    assert len(results) == 2
    # Both should match: "Chess" and "chess" (case-insensitive)
    assert any(r.value == "Chess is a strategy game" for r in results)
    assert any(r.value == "chess is also a game" for r in results)


@pytest.mark.asyncio
async def test_search_respects_limit(memory, user_id):
    """Test that search respects the limit parameter."""
    await memory.add_document(user_id, "Doc1", "Chess and strategy")
    await memory.add_document(user_id, "Doc2", "Checkers and strategy")
    await memory.add_document(user_id, "Doc3", "Board games and strategy")

    # Search for "strategy" which appears in all three
    results = await memory.search(user_id, "strategy", limit=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_no_match_returns_empty_list(memory, user_id):
    """Test that search returns empty list when nothing matches."""
    await memory.add_document(user_id, "Doc1", "Chess")

    results = await memory.search(user_id, "nonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_search_orders_most_recent_first(memory, user_id):
    """Test that search orders results by most recent first."""
    await memory.add_document(user_id, "Doc1", "First document")
    await memory.add_document(user_id, "Doc2", "Second document")
    await memory.add_document(user_id, "Doc3", "Third document")

    # Search for "document" which appears in all three
    results = await memory.search(user_id, "document", limit=10)
    assert len(results) == 3
    # Should be ordered most recent first: Third, Second, First
    assert results[0].value == "Third document"
    assert results[1].value == "Second document"
    assert results[2].value == "First document"


@pytest.mark.asyncio
async def test_documents_scoped_per_user(memory, session_factory):
    """Test that documents are scoped per user."""
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

    # Add document for user1
    await memory.add_document(user1_id, "Doc1", "User1's chess notes")

    # user2 should not see it in search
    results = await memory.search(user2_id, "chess")
    assert len(results) == 0

    # user1 should see it
    results = await memory.search(user1_id, "chess")
    assert len(results) == 1
    assert results[0].value == "User1's chess notes"


@pytest.mark.asyncio
async def test_put_creates_document_using_key_as_title(memory, user_id):
    """Test that put creates a document using key as title.

    This test documents the interface-mapping choice: put() maps the key
    parameter to the document title, and value to the document content.
    This is an interface impedance mismatch since MemoryStore's put() is
    designed for key-value storage where keys are unique identifiers,
    but KnowledgeMemory uses document IDs as keys for get() and titles
    for put(). This is acceptable for v1 as a compatibility shim.
    """
    # put() should create a document with key as title, value as content
    await memory.put(user_id, "My Notes", "This is the content of my notes.")

    # Verify the document was created by searching for its content
    results = await memory.search(user_id, "notes")
    assert len(results) == 1
    assert results[0].key == "My Notes"
    assert results[0].value == "This is the content of my notes."
