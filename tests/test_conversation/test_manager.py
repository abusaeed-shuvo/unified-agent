"""Tests for ConversationManager implementation."""

import pytest
from sqlalchemy import select

from ua.database.models import Message, User
from ua.database.models import Session as SessionModel


@pytest.mark.asyncio
async def test_get_or_create_session_returns_same_id_on_repeat_calls(
    conversation_manager,
):
    """Test that calling get_or_create_session twice returns the same session id."""
    sid1 = await conversation_manager.get_or_create_session("alice", "cli")
    sid2 = await conversation_manager.get_or_create_session("alice", "cli")

    assert sid1 == sid2
    assert sid1 is not None
    assert isinstance(sid1, str)


@pytest.mark.asyncio
async def test_get_or_create_session_scoped_per_platform(conversation_manager):
    """Test that same user_id with different platforms creates different sessions."""
    sid_cli = await conversation_manager.get_or_create_session("alice", "cli")
    sid_discord = await conversation_manager.get_or_create_session("alice", "discord")

    assert sid_cli != sid_discord
    assert sid_cli is not None
    assert sid_discord is not None


@pytest.mark.asyncio
async def test_handle_incoming_records_short_term_turn(conversation_manager, real_memory_manager):
    """Test that handle_incoming records the turn in short-term memory."""
    await conversation_manager.handle_incoming("alice", "cli", "Hello there")

    # Check that the turn was recorded in short-term memory
    # Access the private _short_term attribute to verify
    recent_turns = await real_memory_manager._short_term.recent_turns("alice", limit=10)

    assert len(recent_turns) == 1
    assert recent_turns[0].role == "user"
    assert recent_turns[0].content == "Hello there"


@pytest.mark.asyncio
async def test_handle_incoming_writes_durable_message_row(
    conversation_manager, session_factory
):
    """Test that handle_incoming writes a durable Message row to the database."""
    await conversation_manager.handle_incoming("alice", "cli", "Hello there")

    # Verify the message was written to the database
    async with session_factory() as session:
        # Get the user
        result = await session.execute(select(User).where(User.id == "alice"))
        user = result.scalar_one_or_none()
        assert user is not None

        # Get the session
        result = await session.execute(
            select(SessionModel).where(
                SessionModel.user_id == "alice",
                SessionModel.platform == "cli",
            )
        )
        sess = result.scalar_one_or_none()
        assert sess is not None

        # Get the message
        result = await session.execute(
            select(Message).where(Message.session_id == sess.id)
        )
        messages = result.scalars().all()

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello there"


@pytest.mark.asyncio
async def test_handle_incoming_returns_retrieved_context(conversation_manager, real_memory_manager):
    """Test that handle_incoming returns a RetrievedContext from memory.retrieve_context."""
    # First, add some data to long-term memory so retrieve_context has something to find
    await real_memory_manager.remember_fact("alice", "favorite_color", "blue")

    # Now handle incoming - search for "blue" to match the fact value
    ctx = await conversation_manager.handle_incoming("alice", "cli", "blue")

    # Verify it's a RetrievedContext with the expected structure
    assert hasattr(ctx, "recent_turns")
    assert hasattr(ctx, "relevant_facts")
    assert hasattr(ctx, "relevant_knowledge")

    # The recent_turns should NOT include the current message (it's retrieved BEFORE recording)
    # This is the fix for the duplication bug: recent_turns = prior history only
    assert len(ctx.recent_turns) == 0

    # The relevant_facts should include the fact we added
    # LongTermMemory.search does substring match on Fact.value
    assert len(ctx.relevant_facts) == 1
    assert ctx.relevant_facts[0].key == "favorite_color"
    assert ctx.relevant_facts[0].value == "blue"


@pytest.mark.asyncio
async def test_handle_outgoing_records_short_term_turn(conversation_manager, real_memory_manager):
    """Test that handle_outgoing records the assistant turn in short-term memory."""
    # First, create a session and record an incoming message
    await conversation_manager.handle_incoming("alice", "cli", "Hello")

    # Now handle outgoing
    await conversation_manager.handle_outgoing("alice", "cli", "Hi Alice, how can I help?")

    # Check that both turns were recorded
    # Access the private _short_term attribute to verify
    recent_turns = await real_memory_manager._short_term.recent_turns("alice", limit=10)

    assert len(recent_turns) == 2
    assert recent_turns[0].role == "user"
    assert recent_turns[0].content == "Hello"
    assert recent_turns[1].role == "assistant"
    assert recent_turns[1].content == "Hi Alice, how can I help?"


@pytest.mark.asyncio
async def test_handle_outgoing_writes_durable_message_row_same_session(
    conversation_manager, session_factory
):
    """Test that handle_outgoing writes a Message row linked to the same session."""
    # First, handle incoming to create a session
    await conversation_manager.handle_incoming("alice", "cli", "Hello there")

    # Now handle outgoing
    await conversation_manager.handle_outgoing("alice", "cli", "Hi Alice!")

    # Verify both messages are in the database and linked to the same session
    async with session_factory() as session:
        # Get the session
        result = await session.execute(
            select(SessionModel).where(
                SessionModel.user_id == "alice",
                SessionModel.platform == "cli",
            )
        )
        sess = result.scalar_one_or_none()
        assert sess is not None

        # Get all messages for this session
        result = await session.execute(
            select(Message)
            .where(Message.session_id == sess.id)
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello there"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi Alice!"
        assert messages[0].session_id == sess.id
        assert messages[1].session_id == sess.id


@pytest.mark.asyncio
async def test_incoming_then_outgoing_produces_exactly_two_message_rows_in_order(
    conversation_manager, session_factory
):
    """Test that incoming then outgoing produces exactly 2 Message rows in correct order."""
    # Handle incoming
    await conversation_manager.handle_incoming("alice", "cli", "What's the weather?")

    # Handle outgoing
    await conversation_manager.handle_outgoing("alice", "cli", "It's sunny today!")

    # Query the database directly to verify exactly 2 messages in order
    async with session_factory() as session:
        result = await session.execute(
            select(Message)
            .join(SessionModel)
            .where(
                SessionModel.user_id == "alice",
                SessionModel.platform == "cli",
            )
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "What's the weather?"
        assert messages[1].role == "assistant"
        assert messages[1].content == "It's sunny today!"

        # Verify they're in the correct chronological order
        assert messages[0].created_at <= messages[1].created_at


@pytest.mark.asyncio
async def test_user_creation_with_external_id(conversation_manager, session_factory):
    """Test that User rows are created with the external user_id as User.id."""
    # Create a session for a new user
    await conversation_manager.get_or_create_session("discord_user_123", "discord")

    # Verify the user was created with the external ID as User.id
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.id == "discord_user_123"))
        user = result.scalar_one_or_none()

        assert user is not None
        assert user.id == "discord_user_123"
        assert user.platform == "discord"
        assert user.platform_user_id == "discord_user_123"


@pytest.mark.asyncio
async def test_multiple_platforms_create_separate_sessions_shared_user(
    conversation_manager, session_factory
):
    """Test that multiple platforms create separate sessions but share the same User row."""
    # Create sessions for the same user on different platforms
    await conversation_manager.get_or_create_session("alice", "cli")
    await conversation_manager.get_or_create_session("alice", "discord")
    await conversation_manager.get_or_create_session("alice", "web")

    # Verify only one User row exists
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.id == "alice"))
        users = result.scalars().all()

        assert len(users) == 1
        assert users[0].id == "alice"

        # Verify three separate sessions exist
        result = await session.execute(
            select(SessionModel).where(SessionModel.user_id == "alice")
        )
        sessions = result.scalars().all()

        assert len(sessions) == 3

        # Verify each session has the correct platform
        platforms = {s.platform for s in sessions}
        assert platforms == {"cli", "discord", "web"}
