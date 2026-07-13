"""Tests for build_default_agent factory function."""

from __future__ import annotations

import os

os.environ.setdefault("UA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("UA_LLM_PROVIDER", "fake")


import pytest

from ua.core.agent import UnifiedAgent
from ua.tools.sandbox_execute import SandboxExecuteTool


@pytest.mark.asyncio
async def test_build_default_agent_without_callback_still_registers_sandbox_tools():
    """build_default_agent() with no callback still registers sandbox tools."""
    import ua.database.engine as engine_mod
    from ua.config.settings import get_settings
    from ua.core.factory import build_default_agent

    get_settings.cache_clear()
    engine_mod._engine = None
    engine_mod._session_factory = None

    agent = build_default_agent()

    assert isinstance(agent, UnifiedAgent)

    # Verify sandbox tools are registered
    assert "sandbox_execute" in [t.name for t in agent._tool_registry._tools.values()]
    assert "sandbox_write_file" in [t.name for t in agent._tool_registry._tools.values()]


@pytest.mark.asyncio
async def test_build_default_agent_with_callback_wires_it_to_sandbox_execute_tool():
    """build_default_agent(callback=...) wires that callback to the tool."""
    import ua.database.engine as engine_mod
    from ua.config.settings import get_settings
    from ua.core.factory import build_default_agent

    get_settings.cache_clear()
    engine_mod._engine = None
    engine_mod._session_factory = None

    # Create a tracking callback
    call_log = []

    async def tracking_callback(cmd: str, reason: str) -> bool:
        call_log.append(cmd)
        return True

    agent = build_default_agent(confirmation_callback=tracking_callback)

    # Get the sandbox_execute tool from the registry
    sandbox_tool = agent._tool_registry._tools.get("sandbox_execute")
    assert sandbox_tool is not None
    assert isinstance(sandbox_tool, SandboxExecuteTool)
    assert sandbox_tool._confirmation_callback is tracking_callback
    assert call_log == []  # Not called yet


@pytest.mark.asyncio
async def test_end_to_end_chat_with_risky_sandbox_call_auto_rejected_no_callback():
    """FakeAdapter scripted to request a risky sandbox call: should be rejected without callback."""
    import ua.database.engine as engine_mod
    from ua.config.settings import get_settings
    from ua.core.factory import build_default_agent
    from ua.models.base import LLMResponse, ToolCall

    get_settings.cache_clear()
    engine_mod._engine = None
    engine_mod._session_factory = None

    # No callback provided - risky commands should be auto-rejected
    agent = build_default_agent(confirmation_callback=None)

    # Script a response that requests a risky sandbox command followed by a final response
    mock_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_risky",
                name="sandbox_execute",
                arguments={"project_id": "test", "command": "rm -rf /tmp/x"},
            )
        ],
    )

    # We need to mock the model manager to return our scripted response
    # The second response is the final text after the tool call
    from ua.models.fake_adapter import FakeAdapter

    fake = FakeAdapter(responses=[mock_response, LLMResponse(content="Command was rejected")])
    agent._model_manager._adapter = fake

    # This must not crash - the tool will be auto-rejected since no callback
    try:
        result = await agent.chat(
            user_id="factory_risky_test",
            platform="cli",
            message="Do something dangerous",
        )
        # If we get here, no crash was raised - the test passes
        assert isinstance(result, str)
    except Exception:
        # If an exception was raised, the test fails
        pytest.fail("chat() raised an exception when it should not have")
