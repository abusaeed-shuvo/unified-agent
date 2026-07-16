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


async def _get_backend_status(agent) -> str:
    """Get backend status string for CLI startup banner.

    Best-effort with short timeout to avoid hanging CLI startup.

    Args:
        agent: The UnifiedAgent instance.

    Returns:
        A string like " Sandbox backends available: ssh (online), docker (offline)"
        or empty string if status check fails.
    """
    try:
        # Use a short timeout for the status check
        result = await asyncio.wait_for(
            agent._tool_registry.execute("sandbox_backend", user_id="cli-startup", action="list"),
            timeout=2.0,
        )
        if result.success:
            # Parse the output to extract backend statuses
            lines = result.output.strip().split("\n")
            backend_parts = []
            for line in lines[1:]:  # Skip the header line
                # Parse "  - ssh: online (active)" format
                if "- " in line:
                    backend_parts.append(line.strip()[2:])  # Remove "- " prefix
            if backend_parts:
                return f" Sandbox backends available: {', '.join(backend_parts)}"
    except (asyncio.TimeoutError, Exception):
        # Silently fail - don't crash or hang CLI startup
        pass
    return ""


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
        
        # Get backend info for startup banner (best-effort, with timeout to avoid hanging)
        backend_info = await _get_backend_status(agent)
        
        print("Unified Agent CLI ready." + backend_info)
        print("Press Ctrl+D or enter an empty line to quit.")

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
