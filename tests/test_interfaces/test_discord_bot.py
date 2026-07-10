"""Tests for the Discord bot interface."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test: Import restrictions
# ---------------------------------------------------------------------------


def test_discord_bot_imports_only_through_factory_and_logging():
    """Discord bot file should only import from ua.core modules and ua.config.logging."""
    import pathlib

    bot_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "ua"
        / "interfaces"
        / "discord"
        / "bot.py"
    )
    source = bot_path.read_text()

    # Check for disallowed imports
    disallowed_imports = [
        "ua.memory",
        "ua.models",
        "ua.tools",
        "ua.personality",
    ]

    for disallowed in disallowed_imports:
        # Check for "from ua.memory" or "import ua.memory" style imports
        assert f"from {disallowed}" not in source, (
            f"Discord bot should not import from {disallowed} directly"
        )
        assert f"import {disallowed}" not in source, (
            f"Discord bot should not import {disallowed} directly"
        )


# ---------------------------------------------------------------------------
# Test: Ignores bot messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ignores_bot_messages():
    """Messages with author.bot=True are ignored entirely."""
    from ua.interfaces.discord.bot import on_message_handler

    # Create a mock agent
    mock_agent = MagicMock()
    mock_agent.chat = AsyncMock(return_value="response")

    # Create a mock message with author.bot = True
    mock_message = MagicMock()
    mock_message.author.bot = True
    mock_message.author.id = "12345"
    mock_message.content = "Hello bot"
    mock_message.channel = MagicMock()
    mock_message.channel.send = AsyncMock()

    # Call the handler
    await on_message_handler(mock_agent, mock_message)

    # Agent.chat should NOT have been called
    mock_agent.chat.assert_not_called()
    mock_message.channel.send.assert_not_called()


# ---------------------------------------------------------------------------
# Test: On message calls agent and replies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_message_calls_agent_and_replies():
    """Normal messages result in agent.chat() being called and response sent."""
    from ua.interfaces.discord.bot import on_message_handler

    # Create a mock agent
    mock_agent = MagicMock()
    mock_agent.chat = AsyncMock(return_value="echo: Hello human")

    # Create a mock message with author.bot = False
    mock_message = MagicMock()
    mock_message.author.bot = False
    mock_message.author.id = "12345"
    mock_message.content = "Hello human"
    mock_message.channel = MagicMock()
    mock_message.channel.send = AsyncMock()

    # Call the handler
    await on_message_handler(mock_agent, mock_message)

    # Agent.chat should have been called with correct args
    mock_agent.chat.assert_called_once()
    call_args = mock_agent.chat.call_args
    assert call_args.kwargs["user_id"] == "12345"
    assert call_args.kwargs["platform"] == "discord"
    assert call_args.kwargs["message"] == "Hello human"

    # Response should be sent
    mock_message.channel.send.assert_called_once_with("echo: Hello human")


# ---------------------------------------------------------------------------
# Test: Run raises clear error when token unset
# ---------------------------------------------------------------------------


def test_run_raises_clear_error_when_token_unset():
    """run() raises a clear RuntimeError when discord_token is None."""
    from ua.interfaces.discord.bot import run

    with patch("ua.interfaces.discord.bot.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.discord_token = None
        mock_get_settings.return_value = mock_settings

        with patch("ua.interfaces.discord.bot.build_default_agent"):
            with pytest.raises(RuntimeError) as exc_info:
                run()

    assert "UA_DISCORD_TOKEN" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test: Intents configured for message content
# ---------------------------------------------------------------------------


def test_intents_configured_for_message_content():
    """The constructed client has message_content intent enabled."""
    from ua.interfaces.discord.bot import create_bot

    mock_agent = MagicMock()
    bot = create_bot(mock_agent)

    assert bot.intents.message_content is True


# ---------------------------------------------------------------------------
# Test: Empty message content handled gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_message_content_handled_gracefully():
    """Empty/whitespace-only messages are skipped without calling agent.chat()."""
    from ua.interfaces.discord.bot import on_message_handler

    # Create a mock agent
    mock_agent = MagicMock()
    mock_agent.chat = AsyncMock(return_value="response")

    # Create a mock message with empty content
    mock_message = MagicMock()
    mock_message.author.bot = False
    mock_message.author.id = "12345"
    mock_message.content = ""
    mock_message.channel = MagicMock()
    mock_message.channel.send = AsyncMock()

    # Call the handler
    await on_message_handler(mock_agent, mock_message)

    # Agent.chat should NOT have been called
    mock_agent.chat.assert_not_called()
    mock_message.channel.send.assert_not_called()

    # Test whitespace-only content
    mock_message.content = "   "
    await on_message_handler(mock_agent, mock_message)

    # Agent.chat should still NOT have been called
    mock_agent.chat.assert_not_called()
    mock_message.channel.send.assert_not_called()
