#!/usr/bin/env python
"""
Sandbox and Web Tools Demo for Unified Agent.

Demonstrates how the "coding" personality can use sandbox_write_file + sandbox_execute
(mocked SSHSandboxManager) AND web_search + web_fetch (mocked backend/httpx) in one
conversation. This is illustrative/educational, showing the tool schemas and pipeline
working together end-to-end with fakes, not a claim of real infrastructure.

Run with: uv run python examples/sandbox_and_web_tools_demo.py
"""

# Set environment variables BEFORE importing anything from ua.config
# This is critical because get_settings() is lru_cached
import os
import socket

os.environ["UA_LLM_PROVIDER"] = "fake"
os.environ["UA_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import asyncio
from unittest.mock import patch

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
from ua.sandbox.manager import SSHSandboxManager
from ua.tools.registry import ToolRegistry
from ua.web.search_backend import SearchBackend, SearchResult

# =============================================================================
# Mock implementations for sandbox and web components
# =============================================================================


class MockSandboxManager(SSHSandboxManager):
    """Mock sandbox manager that doesn't require real SSH connection."""

    def __init__(self):
        """Initialize without real SSH connection."""
        # Skip parent __init__ to avoid SSH connection setup
        self._settings = None
        self._connection = None

    async def write_file(
        self, project_id: str, relative_path: str, content: str
    ) -> None:
        """Mock write file - just pretend it worked."""
        pass  # No-op for demo

    async def execute(
        self, project_id: str, command: str, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Mock execute - return fake output for demo."""
        if command == "echo hello from sandbox":
            return (0, "hello from sandbox", "")
        elif command == "ls -la":
            return (0, "total 8\n-rw-r--r-- 1 user user  123 Jul 13 2026 demo.txt\n", "")
        else:
            return (0, f"Mock output for: {command}", "")


class MockSearchBackend(SearchBackend):
    """Mock search backend for testing purposes."""

    def __init__(self, results: list[SearchResult] | None = None):
        self._results = results or [
            SearchResult(
                title="Example Page", url="https://example.com/demo", snippet="Demo snippet"
            ),
        ]

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return mock results."""
        return self._results[:max_results]


# =============================================================================
# Main demo
# =============================================================================


async def main() -> None:
    """Run the demo showing sandbox + web tools working together."""
    print("=" * 60)
    print("Sandbox and Web Tools Demo")
    print("=" * 60)
    print()

    # Step 1: Set up all dependencies
    print("Step 1: Setting up agent infrastructure...")
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
    print("  Infrastructure ready.")
    print()

    # Step 2: Build tool registry with mocked sandbox manager
    print("Step 2: Building tool registry with mocked sandbox...")
    mock_sandbox = MockSandboxManager()
    tool_registry = ToolRegistry()
    tool_registry.discover()  # Discover built-in tools including web_fetch and web_search

    # Create sandbox tools with mocked manager
    from ua.tools.sandbox_execute import SandboxExecuteTool
    from ua.tools.sandbox_write_file import SandboxWriteFileTool

    sandbox_write_tool = SandboxWriteFileTool(sandbox_manager=mock_sandbox)
    sandbox_execute_tool = SandboxExecuteTool(sandbox_manager=mock_sandbox)

    tool_registry.register_instance(sandbox_write_tool)
    tool_registry.register_instance(sandbox_execute_tool)
    print(f"  Registered tools: {list(tool_registry._tools.keys())}")
    print()

    # Step 3: Set up model manager with FakeAdapter
    print("Step 3: Setting up FakeAdapter with scripted responses...")
    model_manager = ModelManager(settings=settings)

    # First response: tool calls for web_search and sandbox_execute
    # This simulates the agent deciding to use both web and sandbox tools
    scripted_response = LLMResponse(
        content="",  # Empty - tool calls will be executed
        tool_calls=[
            ToolCall(
                id="call_search",
                name="web_search",
                arguments={"query": "python asyncio best practices", "max_results": 3},
            ),
            ToolCall(
                id="call_fetch",
                name="web_fetch",
                arguments={"url": "https://example.com/page"},
            ),
            ToolCall(
                id="call_sandbox",
                name="sandbox_execute",
                arguments={"project_id": "demo-project", "command": "echo hello from sandbox"},
            ),
        ],
    )
    scripted_final = LLMResponse(
        content=(
            "I used both web_search and sandbox_execute tools to demonstrate the agent's "
            "capabilities. The web_search tool found information, web_fetch retrieved "
            "page content (mocked), and sandbox_execute ran a command in the sandbox "
            "(mocked). This shows how the coding personality can integrate web research "
            "with code execution."
        ),
        tool_calls=[],
    )

    # Inject mock search backend
    mock_search = MockSearchBackend()
    model_manager._adapter._responses = [scripted_response, scripted_final]  # type: ignore[attr-defined]
    model_manager._adapter._fixed = None  # type: ignore[attr-defined]
    model_manager._adapter._index = 0  # type: ignore[attr-defined]

    # Inject mock client into tools for web_fetch
    from ua.tools.web_search import WebSearchTool

    # Override the web_search tool with one using mock backend
    web_search_tool = WebSearchTool(backend=mock_search)
    tool_registry.register_instance(web_search_tool)

    # For web_fetch, we need to mock the httpx client
    # Get the existing web_fetch tool and mock its client
    web_fetch_tool = tool_registry.get("web_fetch")

    # Create mock response for web_fetch
    mock_response = type(
        "MockResponse",
        (),
        {
            "status_code": 200,
            "text": (
                "<html><body><h1>Demo Page</h1>"
                "<p>This is example content about Python asyncio.</p></body></html>"
            ),
            "raise_for_status": lambda: None,
        },
    )()

    # Create coroutine for get method
    async def mock_get(url, follow_redirects=True):
        return mock_response

    async def mock_aclose():
        pass

    mock_client_cls = type(
        "MockClient",
        (),
        {
            "get": mock_get,
            "aclose": mock_aclose,
        },
    )
    web_fetch_tool._client = mock_client_cls()  # type: ignore[attr-defined]

    # Mock socket.getaddrinfo for SSRF protection tests
    original_getaddrinfo = socket.getaddrinfo

    def mock_getaddrinfo_wrapper(
        hostname, port=None, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        if hostname in ("example.com", "example.com/page"):
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]
        return original_getaddrinfo(hostname, port, family, type, proto, flags)

    # Use the patch context manager from unittest.mock
    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_wrapper):
        print("  FakeAdapter configured with multiple tool calls.")
        print()

        # Step 4: Assemble the agent
        print("Step 4: Assembling the agent...")
        agent = UnifiedAgent(
            conversation=conversation,
            context_builder=context_builder,
            model_manager=model_manager,
            tool_registry=tool_registry,
            personality_name=settings.active_personality,
        )
        print("  Agent assembled successfully!")
        print()

        # Step 5: Send a message that triggers the scripted tool calls
        print("Step 5: Sending message to trigger tool calls...")
        print("  User: 'Research Python asyncio and test the sandbox'")
        print()

        response = await agent.chat(
            user_id="demo_user",
            platform="cli",
            message="Research Python asyncio and test the sandbox",
        )
        print()

        # Step 6: Show the response
        print("Step 6: Response received:")
        print(f"  {response}")
        print()

    # Step 7: Demonstrate SSRF protection
    print("Step 7: Demonstrating SSRF protection...")
    from ua.web.ssrf_guard import is_url_safe

    unsafe_urls = [
        ("http://localhost/", "localhost"),
        ("http://169.254.169.254/", "cloud metadata"),
        ("http://10.0.0.1/", "private IP"),
        ("file:///etc/passwd", "file scheme"),
    ]

    print("  Blocked URLs (SSRF protection):")
    for url, desc in unsafe_urls:
        safe, reason = is_url_safe(url)
        print(f"    {desc}: safe={safe}")

    print()
    print("Demo completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
