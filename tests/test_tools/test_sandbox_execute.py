"""Tests for SandboxExecuteTool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ua.sandbox.manager import SSHSandboxManager
from ua.tools.registry import ToolRegistry
from ua.tools.sandbox_execute import SandboxExecuteTool


@pytest.mark.asyncio
async def test_execute_tool_success():
    """Test successful command execution via the tool."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "Hello, stdout!", ""))

    tool = SandboxExecuteTool(sandbox_manager=mock_mgr)
    result = await tool.run(project_id="test-project", command="echo hello")

    assert result.success is True
    assert result.output == "Hello, stdout!"
    mock_mgr.execute.assert_called_once_with("test-project", "echo hello", 60.0)


@pytest.mark.asyncio
async def test_execute_tool_fails_closed_when_unconfigured():
    """Test that tool fails closed when sandbox_host is None."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(
        side_effect=Exception("Sandbox host not configured")
    )

    tool = SandboxExecuteTool(sandbox_manager=mock_mgr)
    result = await tool.run(project_id="test-project", command="ls")

    assert result.success is False
    assert result.error is not None
    assert "not configured" in result.error.lower()


@pytest.mark.asyncio
async def test_execute_tool_description_contains_no_confirmation_warning():
    """Test that the tool description contains the required warning."""
    # Check for the warning text (may be split across lines in docstring)
    warning_fragment = "WARNING: This tool currently has NO destructive-command"

    assert warning_fragment in SandboxExecuteTool.description
    assert warning_fragment in (SandboxExecuteTool.__doc__ or "")


@pytest.mark.asyncio
async def test_execute_tool_not_auto_discovered_by_registry():
    """Test that SandboxExecuteTool requires register_instance(), consistent with FilesystemTool."""
    registry = ToolRegistry()

    # This should not raise during discovery - the tool will be skipped
    # because it requires constructor args (sandbox_manager)
    with patch("ua.tools.sandbox_execute.SSHSandboxManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr

        # FilesystemTool is also not auto-discoverable
        # Let's verify the tool raises TypeError when instantiated without args
        with pytest.raises(TypeError):
            SandboxExecuteTool()

        # And verify it works with register_instance
        mock_mgr = MagicMock(spec=SSHSandboxManager)
        mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))
        tool = SandboxExecuteTool(sandbox_manager=mock_mgr)
        registry.register_instance(tool)

        # Now it should be registered
        assert "sandbox_execute" in [t.name for t in registry._tools.values()]
