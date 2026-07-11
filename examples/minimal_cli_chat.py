#!/usr/bin/env python
"""
Minimal CLI chat example for Unified Agent.

Demonstrates the simplest possible usage: build an agent via build_default_agent(),
send one message, and print the response.

Run with: uv run python examples/minimal_cli_chat.py
"""

# Set environment variables BEFORE importing anything from ua.config
# This is critical because get_settings() is lru_cached
import os

os.environ["UA_LLM_PROVIDER"] = "fake"
os.environ["UA_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio

from ua.core.factory import build_default_agent


async def main() -> None:
    """Build an agent, send a message, and print the response."""
    print("=" * 60)
    print("Minimal CLI Chat Example")
    print("=" * 60)
    print()

    # Step 1: Build the default agent (fully wired with all dependencies)
    print("Building default agent...")
    agent = build_default_agent()
    print("Agent created successfully!")
    print()

    # Step 2: Send a single message and get the response
    print("Sending message: 'Hello, agent!'")
    response = await agent.chat(
        user_id="example_user",
        platform="cli",
        message="Hello, agent!",
    )
    print()

    # Step 3: Print the response
    print("Response received:")
    print(f"  {response}")
    print()

    print("Example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
