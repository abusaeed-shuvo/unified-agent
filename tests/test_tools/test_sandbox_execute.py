"""Tests for SandboxExecuteTool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ua.sandbox.base import SandboxManager
from ua.sandbox.registry import SandboxBackendRegistry
from ua.tools.registry import ToolRegistry
from ua.tools.sandbox_execute import SandboxExecuteTool


def _make_mock_registry_and_backend(available: bool = True) -> tuple[SandboxBackendRegistry, MagicMock]:
    """Create a mock backend and registry for testing."""
    mock_mgr = MagicMock(spec=SandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "Hello, stdout!", ""))
    mock_mgr.is_available = AsyncMock(return_value=available)
    mock_mgr.backend_name = "ssh"

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    from ua.config.settings import Settings
    settings = Settings()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_mgr},
        memory=mock_memory,
        settings=settings,
    )
    return registry, mock_mgr


@pytest.mark.asyncio
async def test_execute_tool_success():
    """Test successful command execution via the tool."""
    registry, mock_mgr = _make_mock_registry_and_backend()
    tool = SandboxExecuteTool(backend_registry=registry)

    result = await tool.run(project_id="test-project", command="echo hello")

    assert result.success is True
    assert result.output == "Hello, stdout!"
    mock_mgr.execute.assert_called_once_with("test-project", "echo hello", 60.0)


@pytest.mark.asyncio
async def test_execute_tool_fails_closed_when_unconfigured():
    """Test that tool fails closed when sandbox_host is None."""
    mock_mgr = MagicMock(spec=SandboxManager)
    mock_mgr.execute = AsyncMock(
        side_effect=Exception("Sandbox host not configured")
    )
    mock_mgr.is_available = AsyncMock(return_value=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    from ua.config.settings import Settings
    settings = Settings()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_mgr},
        memory=mock_memory,
        settings=settings,
    )

    tool = SandboxExecuteTool(backend_registry=registry)
    result = await tool.run(project_id="test-project", command="ls")

    assert result.success is False
    assert result.error is not None
    assert "not configured" in result.error.lower()


@pytest.mark.asyncio
async def test_execute_tool_not_auto_discovered_by_registry():
    """Test that SandboxExecuteTool requires register_instance(), consistent with FilesystemTool."""
    registry = ToolRegistry()

    # Let's verify the tool raises TypeError when instantiated without args
    with pytest.raises(TypeError):
        SandboxExecuteTool()

    # And verify it works with register_instance
    mock_mgr = MagicMock(spec=SandboxManager)
    mock_mgr.execute = AsyncMock(return_value=(0, "output", ""))
    mock_mgr.is_available = AsyncMock(return_value=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    from ua.config.settings import Settings
    settings = Settings()

    backend_registry = SandboxBackendRegistry(
        backends={"ssh": mock_mgr},
        memory=mock_memory,
        settings=settings,
    )

    tool = SandboxExecuteTool(backend_registry=backend_registry)
    registry.register_instance(tool)

    # Now it should be registered
    assert "sandbox_execute" in [t.name for t in registry._tools.values()]


# ---------------------------------------------------------------------------
# Batch 35 Tests: Confirmation gating for risky commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_risky_command_auto_rejected_when_no_callback():
    """Risky command with no callback is auto-rejected, execute() never called."""
    registry, mock_mgr = _make_mock_registry_and_backend()

    # Tool without callback
    tool = SandboxExecuteTool(backend_registry=registry)
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is False
    assert "rejected" in result.error.lower()
    assert "confirmation" in result.error.lower()
    # Critical: execute() was NEVER called
    mock_mgr.execute.assert_not_called()


@pytest.mark.asyncio
async def test_risky_command_proceeds_when_callback_confirms():
    """Risky command with confirming callback proceeds to execute."""
    registry, mock_mgr = _make_mock_registry_and_backend()

    async def confirm(cmd: str, reason: str) -> bool:
        return True

    tool = SandboxExecuteTool(
        backend_registry=registry,
        confirmation_callback=confirm,
    )
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is True
    assert result.output == "Hello, stdout!"
    mock_mgr.execute.assert_called_once()


@pytest.mark.asyncio
async def test_risky_command_rejected_when_callback_denies():
    """Risky command with denying callback is rejected."""
    registry, mock_mgr = _make_mock_registry_and_backend()

    async def deny(cmd: str, reason: str) -> bool:
        return False

    tool = SandboxExecuteTool(backend_registry=registry, confirmation_callback=deny)
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is False
    assert "rejected" in result.error.lower()
    mock_mgr.execute.assert_not_called()


@pytest.mark.asyncio
async def test_risky_command_rejected_when_callback_raises_exception():
    """Callback that raises exception is treated as denial (fail-closed)."""
    registry, mock_mgr = _make_mock_registry_and_backend()

    async def raise_error(cmd: str, reason: str) -> bool:
        raise RuntimeError("Oops")

    tool = SandboxExecuteTool(
        backend_registry=registry,
        confirmation_callback=raise_error,
    )
    result = await tool.run(project_id="test", command="rm -rf /tmp/x")

    assert result.success is False
    assert "rejected" in result.error.lower()
    mock_mgr.execute.assert_not_called()


@pytest.mark.asyncio
async def test_non_risky_command_executes_without_invoking_callback():
    """Non-risky command executes immediately without invoking callback at all."""
    registry, mock_mgr = _make_mock_registry_and_backend()

    call_tracker = []

    async def tracked_callback(cmd: str, reason: str) -> bool:
        call_tracker.append(cmd)
        return True

    tool = SandboxExecuteTool(
        backend_registry=registry,
        confirmation_callback=tracked_callback,
    )
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