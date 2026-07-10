"""Tests for UnifiedAgent — the single public entrypoint."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ua.config.settings import Settings
from ua.conversation.context_builder import ContextBuilder
from ua.conversation.manager import ConversationManager
from ua.core.agent import UnifiedAgent
from ua.database.models import Base
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.manager import MemoryManager
from ua.memory.short_term import ShortTermMemory
from ua.models.base import LLMResponse, ToolCall
from ua.models.manager import ModelManager
from ua.personality.loader import PersonalityLoader
from ua.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_session):
    """Return a callable that yields a new AsyncSession."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory


@pytest_asyncio.fixture
async def memory_manager(session_factory):
    """MemoryManager with fresh in-memory stores."""
    return MemoryManager(
        short_term=ShortTermMemory(),
        long_term=LongTermMemory(session_factory=session_factory),
        knowledge=KnowledgeMemory(session_factory=session_factory),
    )


@pytest_asyncio.fixture
async def conversation_manager(memory_manager, session_factory):
    """ConversationManager with real memory and DB."""
    return ConversationManager(
        memory=memory_manager,
        session_factory=session_factory,
    )


@pytest.fixture
def context_builder():
    """ContextBuilder with real PersonalityLoader."""
    return ContextBuilder(personality_loader=PersonalityLoader())


@pytest.fixture
def tool_registry():
    """ToolRegistry with discover() called."""
    registry = ToolRegistry()
    registry.discover()
    return registry


# ---------------------------------------------------------------------------
# Helper: build a test agent with a custom FakeAdapter
# ---------------------------------------------------------------------------

def _build_test_agent(
    conversation_manager,
    context_builder,
    tool_registry,
    fake_adapter,
    settings: Settings | None = None,
):
    """Build a UnifiedAgent with a ModelManager that uses the given FakeAdapter."""
    # Create a ModelManager with fake provider, then swap in our custom adapter
    if settings is None:
        settings = Settings()
    model_manager = ModelManager(settings=settings)
    model_manager._adapter = fake_adapter
    return UnifiedAgent(
        conversation=conversation_manager,
        context_builder=context_builder,
        model_manager=model_manager,
        tool_registry=tool_registry,
        personality_name="assistant",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_simple_roundtrip_no_tools(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """FakeAdapter in echo mode: chat() returns echoed content, turns recorded."""
    from ua.models.fake_adapter import FakeAdapter

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=FakeAdapter(),  # default echo mode
    )

    response = await agent.chat(
        user_id="test_user_no_tools",
        platform="test",
        message="Hello, agent!",
    )

    # The echo mode returns "echo: Hello, agent!" (the last user message)
    assert response == "echo: Hello, agent!"

    # Verify turns were recorded in short-term memory
    turns = await memory_manager._short_term.recent_turns("test_user_no_tools")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].content == "Hello, agent!"
    assert turns[1].role == "assistant"
    assert turns[1].content == "echo: Hello, agent!"


@pytest.mark.asyncio
async def test_chat_with_single_tool_call_uses_second_response_as_final(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """FakeAdapter scripted: first response has tool_calls, second is plain text."""
    from ua.models.fake_adapter import FakeAdapter

    # First response: tool call to "calculator"
    tool_call_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_abc123",
                name="calculator",
                arguments={"expression": "2 + 2"},
            )
        ],
    )
    # Second response: final text after tool result
    final_response = LLMResponse(content="The answer is 4.")

    fake = FakeAdapter(responses=[tool_call_response, final_response])

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=fake,
    )

    response = await agent.chat(
        user_id="test_user_tool",
        platform="test",
        message="Calculate 2 + 2",
    )

    # The final text should be the second response's content
    assert response == "The answer is 4."

    # Verify turns were recorded (user + assistant)
    turns = await memory_manager._short_term.recent_turns("test_user_tool")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"
    assert turns[1].content == "The answer is 4."


@pytest.mark.asyncio
async def test_chat_with_unknown_tool_call_degrades_gracefully_not_crashing(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """FakeAdapter first response has tool_call for nonexistent tool: no crash."""
    from ua.models.fake_adapter import FakeAdapter

    # First response: tool call to a nonexistent tool
    tool_call_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_xyz789",
                name="nonexistent_tool",
                arguments={"foo": "bar"},
            )
        ],
    )
    # Second response: final text after tool error
    final_response = LLMResponse(content="I tried but the tool was not found.")

    fake = FakeAdapter(responses=[tool_call_response, final_response])

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=fake,
    )

    # This must not crash
    response = await agent.chat(
        user_id="test_user_unknown_tool",
        platform="test",
        message="Use a tool that doesn't exist",
    )

    assert response == "I tried but the tool was not found."

    # Verify turns were recorded
    turns = await memory_manager._short_term.recent_turns("test_user_unknown_tool")
    assert len(turns) == 2


@pytest.mark.asyncio
async def test_chat_records_both_user_and_assistant_turns(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """Verify both user and assistant turns are recorded after chat()."""
    from ua.models.fake_adapter import FakeAdapter

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=FakeAdapter(),  # echo mode
    )

    await agent.chat(
        user_id="test_user_recording",
        platform="test",
        message="Record this turn",
    )

    turns = await memory_manager._short_term.recent_turns("test_user_recording")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[0].content == "Record this turn"
    assert turns[1].role == "assistant"
    assert turns[1].content == "echo: Record this turn"


@pytest.mark.asyncio
async def test_build_default_agent_uses_settings():
    """build_default_agent() with UA_LLM_PROVIDER=fake constructs and works."""
    from ua.core.factory import build_default_agent

    # Override settings via environment variables
    with patch.dict(
        os.environ,
        {
            "UA_LLM_PROVIDER": "fake",
            "UA_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        },
        clear=False,
    ):
        # Clear the cached settings so our env vars take effect
        from ua.config.settings import get_settings
        get_settings.cache_clear()

        agent = build_default_agent()

        # Should construct without error
        assert isinstance(agent, UnifiedAgent)

        # Should be able to chat (lazy DB init happens inside chat())
        response = await agent.chat(
            user_id="factory_test_user",
            platform="test",
            message="Hello from factory!",
        )

        # With fake provider, it echoes the last user message
        assert "Hello from factory!" in response


# ---------------------------------------------------------------------------
# Batch 25 Tests: Bounded tool call loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_resolves_multiple_chained_tool_call_rounds(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """FakeAdapter with 3 tool-call responses then final text: all 3 rounds resolve."""
    from ua.models.fake_adapter import FakeAdapter

    # Three responses with tool calls, then final text
    responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})],
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c2", name="calculator", arguments={"expression": "2+2"})],
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c3", name="calculator", arguments={"expression": "3+3"})],
        ),
        LLMResponse(content="All done!"),
    ]

    fake = FakeAdapter(responses=responses)
    settings = Settings(max_tool_call_rounds=4)  # Allow enough rounds

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=fake,
        settings=settings,
    )

    response = await agent.chat(
        user_id="test_user_chained",
        platform="test",
        message="Do some math",
    )

    # Should get the final text after all tool calls
    assert response == "All done!"
    # Verify exactly 4 generate() calls were made
    assert fake._call_count == 4


@pytest.mark.asyncio
async def test_chat_stops_at_max_rounds_when_model_keeps_requesting_tools(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """FakeAdapter with more tool-call responses than max_tool_call_rounds: stops at limit."""
    from ua.models.fake_adapter import FakeAdapter

    # Four responses all with tool calls, but max_rounds=2
    responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})],
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c2", name="calculator", arguments={"expression": "2+2"})],
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c3", name="calculator", arguments={"expression": "3+3"})],
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c4", name="calculator", arguments={"expression": "4+4"})],
        ),
    ]

    fake = FakeAdapter(responses=responses)
    settings = Settings(max_tool_call_rounds=2)

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=fake,
        settings=settings,
    )

    response = await agent.chat(
        user_id="test_user_max_rounds",
        platform="test",
        message="Do some math",
    )

    # Should stop at exactly 2 generate() calls
    assert fake._call_count == 2
    # Response should be the content from the 2nd response (empty) or fallback
    assert response == "I wasn't able to complete that request."


@pytest.mark.asyncio
async def test_chat_logs_warning_when_round_limit_hit(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
    caplog,
):
    """Verify a warning is logged when the round limit is hit."""
    from ua.models.fake_adapter import FakeAdapter

    # Two tool-call responses, but max_rounds=1
    responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})],
        ),
        LLMResponse(content="This should not be reached"),
    ]

    fake = FakeAdapter(responses=responses)
    settings = Settings(max_tool_call_rounds=1)

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=fake,
        settings=settings,
    )

    with caplog.at_level("WARNING"):
        response = await agent.chat(
            user_id="test_user_warning",
            platform="test",
            message="Do some math",
        )

    # Should have logged a warning
    assert any("Tool call round limit" in record.message for record in caplog.records)
    # Response should be fallback since content was empty
    assert response == "I wasn't able to complete that request."


@pytest.mark.asyncio
async def test_chat_at_round_limit_does_not_raise_exception(
    conversation_manager,
    context_builder,
    tool_registry,
    memory_manager,
):
    """Verify chat() does not raise an exception when round limit is hit."""
    from ua.models.fake_adapter import FakeAdapter

    # Multiple tool-call responses, but max_rounds=2
    responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})],
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c2", name="calculator", arguments={"expression": "2+2"})],
        ),
        LLMResponse(content="This should not be reached"),
    ]

    fake = FakeAdapter(responses=responses)
    settings = Settings(max_tool_call_rounds=2)

    agent = _build_test_agent(
        conversation_manager=conversation_manager,
        context_builder=context_builder,
        tool_registry=tool_registry,
        fake_adapter=fake,
        settings=settings,
    )

    # This must not raise an exception
    try:
        response = await agent.chat(
            user_id="test_user_no_exception",
            platform="test",
            message="Do some math",
        )
        # If we get here, no exception was raised
        assert isinstance(response, str)
    except Exception as e:
        pytest.fail(f"chat() raised an exception when it should not: {e}")
