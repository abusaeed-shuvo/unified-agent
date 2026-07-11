#!/usr/bin/env python
"""
Personality Switch Example for Unified Agent.

Demonstrates personality_override (Batch 28): one call with the default personality,
one call with personality_override="tester", showing the different system-message content
each produces.

Run with: uv run python examples/switch_personality.py
"""

# Set environment variables BEFORE importing anything from ua.config
# This is critical because get_settings() is lru_cached
import os

os.environ["UA_LLM_PROVIDER"] = "fake"
os.environ["UA_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio

from ua.config.settings import get_settings
from ua.conversation.context_builder import ContextBuilder
from ua.conversation.manager import ConversationManager
from ua.core.agent import UnifiedAgent
from ua.database.engine import get_session_factory, init_db
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.manager import MemoryManager
from ua.memory.short_term import ShortTermMemory
from ua.models.manager import ModelManager
from ua.personality.loader import PersonalityLoader
from ua.tools.registry import ToolRegistry


async def main() -> None:
    """Demonstrate personality override showing different system prompts."""
    print("=" * 60)
    print("Personality Switch Example")
    print("=" * 60)
    print()

    # Step 1: Build the agent with default personality
    print("Building agent with default personality...")
    settings = get_settings()
    print(f"  Default personality from settings: {settings.active_personality}")
    print()

    session_factory = get_session_factory()
    short_term = ShortTermMemory()
    long_term = LongTermMemory(session_factory=session_factory)
    knowledge = KnowledgeMemory(session_factory=session_factory)
    memory_manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    conversation = ConversationManager(
        memory=memory_manager,
        session_factory=session_factory,
    )

    personality_loader = PersonalityLoader()
    context_builder = ContextBuilder(personality_loader=personality_loader)

    model_manager = ModelManager(settings=settings)
    tool_registry = ToolRegistry()
    tool_registry.discover()

    agent = UnifiedAgent(
        conversation=conversation,
        context_builder=context_builder,
        model_manager=model_manager,
        tool_registry=tool_registry,
        personality_name=settings.active_personality,
    )
    print("Agent created successfully!")
    print()

    # Step 1.5: Initialize the database (required for any DB operations)
    print("Initializing database (required for memory operations)...")
    await init_db()
    print("Database initialized!")
    print()

    # Step 2: Make a call WITHOUT personality_override and show the system prompt
    print("=" * 40)
    print("Call 1: Default personality (assistant)")
    print("=" * 40)

    # Get the system prompt that will be used (before the chat call)

    assistant_personality = personality_loader.load("assistant")
    print("System prompt for 'assistant' personality:")
    print(f"  {assistant_personality.system_prompt[:80]}...")
    print()

    # Also check the stored preference (should be None initially)
    stored_pref_before = await memory_manager.get_fact("test_user", "active_personality")
    print(f"Stored personality preference before call: {stored_pref_before}")
    print()

    # Send the message
    response1 = await agent.chat(
        user_id="test_user",
        platform="cli",
        message="Hello!",
    )
    print(f"Response: {response1}")
    print()

    # Check stored preference AFTER the call (should still be None, no override was used)
    stored_pref_after_call1 = await memory_manager.get_fact("test_user", "active_personality")
    print(f"Stored personality preference after call 1: {stored_pref_after_call1}")
    print()

    # Step 3: Make a call WITH personality_override="tester" and show the difference
    print("=" * 40)
    print("Call 2: With personality_override='tester'")
    print("=" * 40)

    tester_personality = personality_loader.load("tester")
    print("System prompt for 'tester' personality:")
    print(f"  {tester_personality.system_prompt}")
    print()

    # Show difference between personalities
    print("Difference: 'assistant' prompt starts with 'You are a helpful, honest...'")
    print("          while 'tester' prompt starts with 'You are TESTER, a minimal...'")
    print()

    response2 = await agent.chat(
        user_id="test_user",
        platform="cli",
        message="Test message",
        personality_override="tester",
    )
    print(f"Response: {response2}")
    print()

    # Check stored preference AFTER the second call (should now be "tester" due to sticky behavior)
    stored_pref_after_call2 = await memory_manager.get_fact("test_user", "active_personality")
    print(f"Stored personality preference after call 2: {stored_pref_after_call2}")
    print()

    # Step 4: Demonstrate sticky behavior - next call uses "tester" without override
    print("=" * 40)
    print("Call 3: No override (demonstrates sticky behavior)")
    print("=" * 40)
    print("Without any override, the agent should remember 'tester' as the preferred personality.")
    print()

    response3 = await agent.chat(
        user_id="test_user",
        platform="cli",
        message="Do I get tester personality?",
    )
    print(f"Response: {response3}")
    print()

    final_pref = await memory_manager.get_fact("test_user", "active_personality")
    print(f"Final stored personality preference: {final_pref}")
    print()

    print("=" * 60)
    print("Summary of personality differences:")
    print("=" * 60)
    print("  - 'assistant' system prompt focuses on being helpful, honest, and direct")
    print("  - 'tester' system prompt is terse, literal, and machine-oriented")
    print("  - Personality override is 'sticky' - it persists as user preference")
    print()

    print("Example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
