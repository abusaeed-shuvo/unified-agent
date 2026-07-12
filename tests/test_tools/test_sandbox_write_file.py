"""Tests for SandboxWriteFileTool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ua.sandbox.manager import SSHSandboxManager
from ua.tools.sandbox_write_file import SandboxWriteFileTool


@pytest.mark.asyncio
async def test_write_file_tool_success():
    """Test successful file write via the tool."""
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.write_file = AsyncMock()

    tool = SandboxWriteFileTool(sandbox_manager=mock_mgr)
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
    mock_mgr = MagicMock(spec=SSHSandboxManager)
    mock_mgr.write_file = AsyncMock(
        side_effect=Exception("Sandbox host not configured")
    )

    tool = SandboxWriteFileTool(sandbox_manager=mock_mgr)
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
