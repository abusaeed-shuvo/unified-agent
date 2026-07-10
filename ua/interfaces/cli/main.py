"""CLI interface for UnifiedAgent - a thin chat loop that delegates to the agent."""

from __future__ import annotations

import asyncio
import os
import sys

from ua.config.logging import configure_logging, get_logger
from ua.core.factory import build_default_agent


def run() -> None:
    """Synchronous entrypoint for the CLI.

    1. configure_logging()
    2. Build the agent via build_default_agent()
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
        agent = build_default_agent()
        print("Unified Agent CLI ready. Type 'exit' or press Ctrl+D to quit.")

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
