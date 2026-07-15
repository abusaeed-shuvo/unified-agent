"""Tests for SandboxWriteFileTool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ua.sandbox.base import SandboxManager
from ua.sandbox.registry import SandboxBackendRegistry
from ua.tools.sandbox_write_file import SandboxWriteFileTool


def _make_mock_registry_and_backend(available: bool = True) -> tuple[SandboxBackendRegistry, MagicMock]:
    """Create a mock backend and registry for testing."""
    mock_mgr = MagicMock(spec=SandboxManager)
    mock_mgr.write_file = AsyncMock()
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
async def test_write_file_tool_success():
    """Test successful file write via the tool."""
    registry, mock_mgr = _make_mock_registry_and_backend()
    tool = SandboxWriteFileTool(backend_registry=registry)
    result = await tool.run(
        project_id="test-project",
        relative_path="test.txt",
        content="Hello, World!",
    )

    assert result.success is True
    assert "File written" in result.output
    mock_mgr.write_file.assert_called_once_with(
        "test-project", "test.txt", "Hello, World!"
    )


@pytest.mark.asyncio
async def test_write_file_tool_fails_closed_when_unconfigured():
    """Test that tool fails closed when sandbox_host is None."""
    mock_mgr = MagicMock(spec=SandboxManager)
    mock_mgr.write_file = AsyncMock(
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

    tool = SandboxWriteFileTool(backend_registry=registry)
    result = await tool.run(
        project_id="test-project", relative_path="test.txt", content="Hello"
    )

    assert result.success is False
    assert result.error is not None
    assert "not configured" in result.error.lower()


@pytest.mark.asyncio
async def test_write_file_tool_description_contains_no_confirmation_warning():
    """Test that the tool description contains the required warning."""
    # Check for the warning text (may be split across lines in docstring)
    warning_fragment = "WARNING: This tool currently has NO destructive-command"

    assert warning_fragment in SandboxWriteFileTool.description
    assert warning_fragment in (SandboxWriteFileTool.__doc__ or "")