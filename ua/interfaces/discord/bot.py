"""Discord bot interface for UnifiedAgent - a thin message handler."""

from __future__ import annotations

import discord

from ua.config.logging import configure_logging, get_logger
from ua.config.settings import get_settings
from ua.core.agent import UnifiedAgent
from ua.core.factory import build_default_agent


async def on_message_handler(agent: UnifiedAgent, message: discord.Message) -> None:
    """Handle incoming Discord messages.

    This is the core handler logic, separated for testability.

    Args:
        agent: The UnifiedAgent instance to use for chat.
        message: The Discord message to process.
    """
    # CRITICAL: Ignore bot messages FIRST to prevent infinite reply loops
    if message.author.bot:
        return

    # Skip empty/whitespace-only messages
    if not message.content or not message.content.strip():
        return

    try:
        response = await agent.chat(
            user_id=str(message.author.id),
            platform="discord",
            message=message.content,
        )
        await message.channel.send(response)
    except Exception as e:
        logger = get_logger(__name__)
        logger.exception("Error processing Discord message")
        await message.channel.send(f"Error: {e}")


def create_bot(agent: UnifiedAgent) -> discord.Client:
    """Construct a discord.Client with an on_message event handler wired to the given agent.

    The handler:
    1. Ignores any message where message.author.bot is True (prevents infinite reply loops).
    2. Extracts user_id=str(message.author.id), platform="discord", message=message.content.
    3. Calls agent.chat() and sends the response via channel.send().
    4. Skips empty/whitespace-only messages (e.g., attachment-only messages).
    """
    # Configure intents to receive message content
    intents = discord.Intents.default()
    intents.message_content = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_message(message: discord.Message) -> None:
        """Handle incoming Discord messages."""
        await on_message_handler(agent, message)

    return client


def run() -> None:
    """Synchronous entrypoint for the Discord bot.

    1. configure_logging()
    2. Check discord_token is set, raise clear error if not.
    3. Build the agent via build_default_agent().
    4. Create and run the bot.
    """
    configure_logging()
    settings = get_settings()

    if settings.discord_token is None:
        raise RuntimeError(
            "UA_DISCORD_TOKEN environment variable must be set to run the Discord bot. "
            "Set it in your .env file or export it before running."
        )

    agent = build_default_agent()
    bot = create_bot(agent)
    bot.run(settings.discord_token)
