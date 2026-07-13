"""CLI interface for UnifiedAgent - a thin chat loop that delegates to the agent."""

from __future__ import annotations

import asyncio
import os
import sys

from ua.config.logging import configure_logging, get_logger
from ua.core.factory import build_default_agent


async def _prompt_confirmation(command: str, reason: str) -> bool:
    """Prompt the user for confirmation of a risky command.

    Args:
        command: The risky command that was detected.
        reason: The reason why the command was flagged as risky.

    Returns:
        True if the user confirmed (entered 'y' or 'yes'), False otherwise.
    """
    prompt = (
        f"\n[WARNING] Risky command detected: {command}\n"
        f"Reason: {reason}\n"
        f"Do you want to proceed? (y/n): "
    )
    try:
        response = await asyncio.to_thread(input, prompt)
        return response.lower().strip() in ("y", "yes")
    except Exception:
        return False


def run() -> None:
    """Synchronous entrypoint for the CLI.

    1. configure_logging()
    2. Build the agent via build_default_agent() with confirmation callback
    3. Print a short welcome line.
    4. Loop: read a line from stdin, if EOF or empty input, exit cleanly.
    5. Handle KeyboardInterrupt and EOFError gracefully.
    6. Print each agent response prefixed with "Agent: ".
    """
    configure_logging()
    logger = get_logger(__name__)

    # Fixed local user id - derived from environment or default
    user_id = os.environ.get("USER", "local-user")

    async def main_async_loop() -> None:
        """Async loop that handles stdin reading and agent chat calls."""

        # Build agent with confirmation callback for risky commands
        agent = build_default_agent(confirmation_callback=_prompt_confirmation)
        print("Unified Agent CLI ready. Press Ctrl+D or enter an empty line to quit.")

        while True:
            try:
                # Use asyncio.to_thread to read stdin without blocking the event loop
                user_input = await asyncio.to_thread(input, "You: ")
            except EOFError:
                # Ctrl+D or closed stdin - exit cleanly
                print()
                return

            # Empty input - exit cleanly
            if not user_input.strip():
                return

            # Call agent.chat and print response
            try:
                response = await agent.chat(
                    user_id=user_id,
                    platform="cli",
                    message=user_input,
                )
                print(f"Agent: {response}")
            except Exception as e:
                logger.exception("Error during chat")
                print(f"Agent: Error - {e}")

    try:
        asyncio.run(main_async_loop())
    except KeyboardInterrupt:
        # Ctrl+C - exit cleanly
        print()
        print("Goodbye!")
        sys.exit(0)
