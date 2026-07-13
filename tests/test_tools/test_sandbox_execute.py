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


# ---------------------------------------------------------------------------
# Batch 35 Tests: Confirmation gating for risky commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_risky_command_auto_rejected_when_no_callback():
    """Risky command with no callback is auto-rejected, execute() never called."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))

    # Tool without callback
    tool = SandboxExecuteTool(sandbox_manager=mock_mgr)
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is False
    assert "rejected" in result.error.lower()
    assert "confirmation" in result.error.lower()
    # Critical: execute() was NEVER called
    mock_mgr.execute.assert_not_called()


@pytest.mark.asyncio
async def test_risky_command_proceeds_when_callback_confirms():
    """Risky command with confirming callback proceeds to execute."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))

    async def confirm(cmd: str, reason: str) -> bool:
        return True

    tool = SandboxExecuteTool(sandbox_manager=mock_mgr, confirmation_callback=confirm)
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is True
    assert result.output == "output"
    mock_mgr.execute.assert_called_once()


@pytest.mark.asyncio
async def test_risky_command_rejected_when_callback_denies():
    """Risky command with denying callback is rejected."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))

    async def deny(cmd: str, reason: str) -> bool:
        return False

    tool = SandboxExecuteTool(sandbox_manager=mock_mgr, confirmation_callback=deny)
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is False
    assert "rejected" in result.error.lower()
    mock_mgr.execute.assert_not_called()


@pytest.mark.asyncio
async def test_risky_command_rejected_when_callback_raises_exception():
    """Callback that raises exception is treated as denial (fail-closed)."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))

    async def raise_error(cmd: str, reason: str) -> bool:
        raise RuntimeError("Oops")

    tool = SandboxExecuteTool(sandbox_manager=mock_mgr, confirmation_callback=raise_error)
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is False
    assert "rejected" in result.error.lower()
    mock_mgr.execute.assert_not_called()


@pytest.mark.asyncio
async def test_non_risky_command_executes_without_invoking_callback():
    """Non-risky command executes immediately without invoking callback at all."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))

    call_tracker = []

    async def tracked_callback(cmd: str, reason: str) -> bool:
        call_tracker.append(cmd)
        return True

    tool = SandboxExecuteTool(sandbox_manager=mock_mgr, confirmation_callback=tracked_callback)
    result = await tool.run(project_id="test", command="ls -la")

    assert result.success is True
    mock_mgr.execute.assert_called_once()
    # Callback was NEVER called
    assert len(call_tracker) == 0


# ---------------------------------------------------------------------------
# Batch 35 Test: Updated tool documentation verification
# ---------------------------------------------------------------------------


def test_tool_has_confirmation_gating_documentation():
    """Verify SandboxExecuteTool's docstring mentions confirmation gating (CLI-only)."""
    # The class docstring should mention CLI and that Web/Discord reject risky commands
    docstring = SandboxExecuteTool.__doc__ or ""
    assert "confirmation" in docstring.lower()
    assert "cli" in docstring.lower()
    assert "web api" in docstring.lower() or "discord" in docstring.lower()
    # The description should mention confirmation
    assert "confirmation" in SandboxExecuteTool.description.lower()
