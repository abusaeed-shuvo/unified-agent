#!/usr/bin/env python
"""
Custom Tool Example for Unified Agent.

Demonstrates how to define a custom Tool subclass inline and register it via
ToolRegistry.register_instance() to show the EXTENSION pattern for code OUTSIDE
the core package.

Run with: uv run python examples/custom_tool_example.py
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
from ua.database.engine import get_session_factory
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.manager import MemoryManager
from ua.memory.short_term import ShortTermMemory
from ua.models.base import LLMResponse, ToolCall
from ua.models.manager import ModelManager
from ua.personality.loader import PersonalityLoader
from ua.tools.base import Tool, ToolResult
from ua.tools.registry import ToolRegistry

# =============================================================================
# Step 1: Define a custom tool (inline, demonstrating the extension pattern)
# =============================================================================

class ReverseStringTool(Tool):
    """A simple tool that reverses the given string.

    This demonstrates the Tool ABC pattern for custom tools that live
    outside the ua/tools/ package.
    """

    name = "reverse_string"
    description = "Reverses the provided text string"
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to reverse",
            }
        },
        "required": ["text"],
    }

    async def run(self, text: str) -> ToolResult:
        """Reverse the input text and return the result."""
        reversed_text = text[::-1]
        return ToolResult(success=True, output=f"Reversed: {reversed_text}")


async def main() -> None:
    """Build an agent with a custom tool, invoke it via scripted response, and show results."""
    print("=" * 60)
    print("Custom Tool Example")
    print("=" * 60)
    print()

    # Step 1: Define and show the custom tool
    print("Defining custom ReverseStringTool...")
    custom_tool = ReverseStringTool()
    print(f"  Tool name: {custom_tool.name}")
    print(f"  Tool description: {custom_tool.description}")
    print(f"  Tool parameters: {custom_tool.parameters}")
    print()

    # Step 2: Set up all dependencies manually to inject custom FakeAdapter
    print("Setting up agent with custom tool...")
    settings = get_settings()

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

    # Create ModelManager and inject a custom FakeAdapter with scripted tool call
    model_manager = ModelManager(settings=settings)

    # Inject a FakeAdapter that will request our custom tool on the first call,
    # then return a final response on the second call
    scripted_responses = [
        LLMResponse(
            content="",  # Empty content - tool call will be executed
            tool_calls=[
                ToolCall(
                    id="call_reverse",
                    name="reverse_string",
                    arguments={"text": "Hello from custom tool!"},
                )
            ],
        ),
        LLMResponse(
            content="The custom tool was executed successfully.",
            tool_calls=[],
        ),
    ]
    # Replace the adapter's _responses list to script the behavior
    model_manager._adapter._responses = scripted_responses  # type: ignore[attr-defined]
    model_manager._adapter._fixed = None  # type: ignore[attr-defined]
    model_manager._adapter._index = 0  # type: ignore[attr-defined]

    print("Scripted FakeAdapter: will call reverse_string tool on first generate(), "
          "then return final response on second generate().")
    print()

    # Step 3: Build tool registry and register the custom tool
    print("Building tool registry and registering custom tool...")
    tool_registry = ToolRegistry()
    tool_registry.discover()  # Discover built-in tools
    tool_registry.register_instance(custom_tool)  # Register our custom tool
    print(f"  Registered tools: {list(tool_registry._tools.keys())}")
    print()

    # Step 4: Assemble the agent
    agent = UnifiedAgent(
        conversation=conversation,
        context_builder=context_builder,
        model_manager=model_manager,
        tool_registry=tool_registry,
        personality_name=settings.active_personality,
    )
    print("Agent assembled with custom tool registered!")
    print()

    # Step 5: Send a message that will trigger the custom tool via scripted response
    print("Sending message: 'Use the reverse tool on Hello from custom tool!'")
    print("The scripted FakeAdapter will return a tool call for 'reverse_string'.")
    print("The agent will execute the tool and include the result in the response.")
    response = await agent.chat(
        user_id="example_user",
        platform="cli",
        message="Use the reverse tool on Hello from custom tool!",
    )
    print()

    # Step 6: Show the response (which incorporates the tool result)
    print("Response received:")
    print(f"  {response}")
    print()

    # Step 7: Verify the tool was registered and works standalone
    print("Verifying tool was registered and works standalone:")
    tool_result = await custom_tool.run(text="Hello from custom tool!")
    print(f"  Direct tool call result: {tool_result.output}")
    print(f"  Tool success: {tool_result.success}")
    print()

    # Step 8: Show the tool is in the registry
    print("Verifying tool is in registry:")
    registered_tool = tool_registry.get("reverse_string")
    print(f"  Registry lookup: {registered_tool.name}")
    print()

    print("Example completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
