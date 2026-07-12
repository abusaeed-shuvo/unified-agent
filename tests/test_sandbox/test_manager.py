"""Tests for SSHSandboxManager with mocked SSH connections."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ua.config.settings import Settings
from ua.sandbox.manager import SSHSandboxManager, SSHSandboxNotConfiguredError

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_connection() -> MagicMock:
    """Create a mock SSH client connection."""
    mock_conn = MagicMock()
    mock_conn._closed = False
    # Mock the run method to return a process result
    mock_process = MagicMock()
    mock_process.exit_status = 0
    mock_process.stdout = "output"
    mock_process.stderr = ""
    mock_conn.run = AsyncMock(return_value=mock_process)
    return mock_conn


def _make_mock_connection_with_result(
    exit_status: int = 0, stdout: str = "", stderr: str = ""
) -> MagicMock:
    """Create a mock SSH client connection that returns specific results."""
    mock_conn = MagicMock()
    mock_conn._closed = False
    mock_process = MagicMock()
    mock_process.exit_status = exit_status
    mock_process.stdout = stdout
    mock_process.stderr = stderr
    mock_conn.run = AsyncMock(return_value=mock_process)
    return mock_conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_project_dir_creates_directory_via_mocked_ssh():
    """Test that ensure_project_dir creates the directory via SSH."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = _make_mock_connection()
        mock_connect.return_value = mock_conn

        result = await mgr.ensure_project_dir("test-project")

        assert result == "/home/sandbox/projects/test-project"
        mock_connect.assert_called_once()
        # Verify mkdir was called
        assert mock_conn.run.called
        args = mock_conn.run.call_args[0][0]
        assert "mkdir -p /home/sandbox/projects/test-project" in args


@pytest.mark.asyncio
async def test_ensure_project_dir_rejects_invalid_project_id():
    """Test that invalid project_ids are rejected (path injection attempts)."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    invalid_ids = [
        "../etc",
        "project; rm -rf /",
        "project with spaces",
        "../..",
        "project$(whoami)",
        "project`id`",
        "project|cat /etc/passwd",
        "",
    ]

    for invalid_id in invalid_ids:
        with pytest.raises(ValueError) as exc_info:
            await mgr.ensure_project_dir(invalid_id)
        assert "Invalid project_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_write_file_success_via_mocked_ssh():
    """Test that write_file successfully writes content via SSH."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = _make_mock_connection()
        mock_connect.return_value = mock_conn

        await mgr.write_file("test-project", "test.txt", "Hello, World!")

        # Verify connection was established
        mock_connect.assert_called_once()
        # Verify file write was called (parent dir is same as project for flat path)
        assert mock_conn.run.called
        args = mock_conn.run.call_args[0][0]
        assert "base64" in args  # Uses base64 encoding


@pytest.mark.asyncio
async def test_write_file_path_traversal_rejected():
    """Test that path traversal in relative_path is rejected."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    traversal_paths = [
        "../../etc/passwd",
        "../outside.txt",
        "subdir/../../outside.txt",
        "foo/../../../bar",
    ]

    for traversal_path in traversal_paths:
        with patch("asyncssh.connect", new_callable=AsyncMock):
            with pytest.raises(ValueError) as exc_info:
                await mgr.write_file("test-project", traversal_path, "malicious content")
            assert "Path traversal" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_success_via_mocked_ssh_returns_exit_code_stdout_stderr():
    """Test that execute returns exit code, stdout, and stderr correctly."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = _make_mock_connection_with_result(
            exit_status=0, stdout="Hello, stdout!", stderr=""
        )
        mock_connect.return_value = mock_conn

        exit_code, stdout, stderr = await mgr.execute("test-project", "echo hello")

        assert exit_code == 0
        assert stdout == "Hello, stdout!"
        assert stderr == ""


@pytest.mark.asyncio
async def test_execute_respects_timeout():
    """Test that execute respects the timeout parameter."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(exit_status=0, stdout="", stderr="")

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = MagicMock()
        mock_conn._closed = False
        mock_conn.run = AsyncMock(side_effect=slow_run)
        mock_connect.return_value = mock_conn

        with pytest.raises(asyncio.TimeoutError):
            await mgr.execute("test-project", "sleep 100", timeout=0.1)


@pytest.mark.asyncio
async def test_is_reachable_true_when_connection_succeeds_mocked():
    """Test is_reachable returns True when connection works."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = _make_mock_connection()
        mock_connect.return_value = mock_conn

        result = await mgr.is_reachable()

        assert result is True


@pytest.mark.asyncio
async def test_is_reachable_false_when_connection_fails_mocked():
    """Test is_reachable returns False when connection fails."""
    settings = Settings(sandbox_host="unreachable.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Connection refused")

        result = await mgr.is_reachable()

        assert result is False


@pytest.mark.asyncio
async def test_fail_closed_when_sandbox_host_not_configured():
    """Test that operations fail closed when sandbox_host is None."""
    settings = Settings(sandbox_host=None)
    mgr = SSHSandboxManager(settings=settings)

    # is_reachable should return False, not raise
    assert await mgr.is_reachable() is False

    # execute should raise SSHSandboxNotConfiguredError
    with pytest.raises(SSHSandboxNotConfiguredError):
        await mgr.execute("project", "ls")

    # write_file should raise SSHSandboxNotConfiguredError
    with pytest.raises(SSHSandboxNotConfiguredError):
        await mgr.write_file("project", "test.txt", "content")

    # ensure_project_dir should raise SSHSandboxNotConfiguredError
    with pytest.raises(SSHSandboxNotConfiguredError):
        await mgr.ensure_project_dir("project")
