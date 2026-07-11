"""Test configuration and fixtures for Unified Agent."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.config.settings import Settings
from ua.conversation.context_builder import ContextBuilder
from ua.conversation.manager import ConversationManager
from ua.database.models import Base, User
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.manager import MemoryManager
from ua.memory.short_term import ShortTermMemory
from ua.personality.loader import PersonalityLoader
from ua.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def in_memory_engine():
    """Create a fresh in-memory SQLite engine with tables created, dispose after test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(in_memory_engine):
    """Create an async_sessionmaker bound to the in_memory_engine."""
    return async_sessionmaker(in_memory_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory):
    """Provide a session for testing. Yields a single session from the factory."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def user_id(session_factory):
    """Create a test user and return its ID. Function-scoped for isolation."""
    async with session_factory() as session:
        user = User(platform="test", platform_user_id="test_user")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


# ---------------------------------------------------------------------------
# Memory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def short_term_memory():
    """Create a ShortTermMemory instance with default max_turns."""
    return ShortTermMemory(max_turns=20)


@pytest_asyncio.fixture
async def real_memory_manager(session_factory):
    """Create a MemoryManager with all real in-memory stores."""
    short_term = ShortTermMemory(max_turns=20)
    long_term = LongTermMemory(session_factory)
    knowledge = KnowledgeMemory(session_factory)
    return MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )


@pytest_asyncio.fixture
async def long_term_memory(session_factory):
    """Create a LongTermMemory instance with the test session factory."""
    return LongTermMemory(session_factory)


@pytest_asyncio.fixture
async def knowledge_memory(session_factory):
    """Create a KnowledgeMemory instance with the test session factory."""
    return KnowledgeMemory(session_factory)


@pytest_asyncio.fixture
async def conversation_manager(real_memory_manager, session_factory):
    """Create a ConversationManager instance with real memory and DB."""
    return ConversationManager(
        memory=real_memory_manager,
        session_factory=session_factory,
    )


# ---------------------------------------------------------------------------
# Agent fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def personality_loader():
    """Provide a PersonalityLoader instance."""
    return PersonalityLoader()


@pytest.fixture
def context_builder(personality_loader):
    """Provide a ContextBuilder instance."""
    return ContextBuilder(personality_loader)


@pytest.fixture
def tool_registry():
    """ToolRegistry with discover() called."""
    registry = ToolRegistry()
    registry.discover()
    return registry


@pytest.fixture
def fake_settings():
    """Settings with fake provider and in-memory database."""
    return Settings(llm_provider="fake", database_url="sqlite+aiosqlite:///:memory:")
