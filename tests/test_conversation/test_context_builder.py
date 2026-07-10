"""Tests for ContextBuilder."""

import pytest

from ua.conversation.context_builder import ContextBuilder
from ua.memory.base import MemoryItem
from ua.memory.manager import RetrievedContext
from ua.models.base import Message
from ua.personality.loader import PersonalityLoader


@pytest.fixture
def personality_loader() -> PersonalityLoader:
    """Provide a PersonalityLoader instance."""
    return PersonalityLoader()


@pytest.fixture
def builder(personality_loader: PersonalityLoader) -> ContextBuilder:
    """Provide a ContextBuilder instance."""
    return ContextBuilder(personality_loader)


def test_system_message_is_first(builder: ContextBuilder) -> None:
    """Test that the first message in the list is a system message."""
    context = RetrievedContext(
        recent_turns=[],
        relevant_facts=[],
        relevant_knowledge=[],
    )
    messages = builder.build("assistant", context, "Hello")

    assert len(messages) > 0
    assert messages[0].role == "system"


def test_system_message_contains_personality_system_prompt_and_style(
    builder: ContextBuilder,
) -> None:
    """Test that the system message contains both system_prompt and style."""
    context = RetrievedContext(
        recent_turns=[],
        relevant_facts=[],
        relevant_knowledge=[],
    )
    messages = builder.build("assistant", context, "Hello")

    # Load the personality directly to get expected content
    loader = PersonalityLoader()
    personality = loader.load("assistant")

    system_content = messages[0].content

    # Both system_prompt and style should appear in the system message
    assert personality.system_prompt in system_content
    assert personality.style in system_content


def test_known_context_section_present_when_facts_or_knowledge_exist(
    builder: ContextBuilder,
) -> None:
    """Test that 'Known context' section appears when facts or knowledge are present."""
    context = RetrievedContext(
        recent_turns=[],
        relevant_facts=[MemoryItem(key="favorite_color", value="blue")],
        relevant_knowledge=[],
    )
    messages = builder.build("assistant", context, "What is my favorite color?")
    system_content = messages[0].content

    assert "Known context:" in system_content
    assert "Relevant facts:" in system_content
    assert "favorite_color: blue" in system_content


def test_known_context_section_present_when_knowledge_exists(
    builder: ContextBuilder,
) -> None:
    """Test that 'Known context' section appears when only knowledge is present."""
    context = RetrievedContext(
        recent_turns=[],
        relevant_facts=[],
        relevant_knowledge=[MemoryItem(key="doc_1", value="Some knowledge")],
    )
    messages = builder.build("assistant", context, "Tell me about docs")
    system_content = messages[0].content

    assert "Known context:" in system_content
    assert "Relevant knowledge:" in system_content
    assert "doc_1: Some knowledge" in system_content


def test_known_context_section_absent_when_both_empty(builder: ContextBuilder) -> None:
    """Test that 'Known context' section does NOT appear when both facts and knowledge are empty."""
    context = RetrievedContext(
        recent_turns=[],
        relevant_facts=[],
        relevant_knowledge=[],
    )
    messages = builder.build("assistant", context, "Hello")
    system_content = messages[0].content

    # The header "Known context:" should not appear at all
    assert "Known context:" not in system_content
    assert "Relevant facts:" not in system_content
    assert "Relevant knowledge:" not in system_content


def test_recent_turns_appear_in_order_between_system_and_new_message(
    builder: ContextBuilder,
) -> None:
    """Test that recent_turns appear in order between system message and new user message."""
    turn1 = Message(role="user", content="Hi")
    turn2 = Message(role="assistant", content="Hello there")
    turn3 = Message(role="user", content="How are you?")

    context = RetrievedContext(
        recent_turns=[turn1, turn2, turn3],
        relevant_facts=[],
        relevant_knowledge=[],
    )
    messages = builder.build("assistant", context, "What is the weather?")

    # System message is first
    assert messages[0].role == "system"

    # Recent turns should follow in order
    assert messages[1] == turn1
    assert messages[2] == turn2
    assert messages[3] == turn3

    # New user message should be last
    assert messages[-1].role == "user"
    assert messages[-1].content == "What is the weather?"


def test_last_message_is_new_user_message(builder: ContextBuilder) -> None:
    """Test that the last message is the new user message."""
    context = RetrievedContext(
        recent_turns=[Message(role="user", content="Hi")],
        relevant_facts=[],
        relevant_knowledge=[],
    )
    messages = builder.build("assistant", context, "What is 2+2?")

    assert messages[-1].role == "user"
    assert messages[-1].content == "What is 2+2?"


def test_build_does_not_mutate_input_recent_turns_list(
    builder: ContextBuilder,
) -> None:
    """Test that build() does not mutate the input recent_turns list."""
    original_turns = [
        Message(role="user", content="Hi"),
        Message(role="assistant", content="Hello"),
    ]
    original_length = len(original_turns)

    context = RetrievedContext(
        recent_turns=original_turns,
        relevant_facts=[],
        relevant_knowledge=[],
    )

    # Call build
    builder.build("assistant", context, "New message")

    # Verify the original list was not mutated
    assert len(original_turns) == original_length
    assert original_turns[0].content == "Hi"
    assert original_turns[1].content == "Hello"

    # Verify it's the same list object (not a copy)
    assert context.recent_turns is original_turns
