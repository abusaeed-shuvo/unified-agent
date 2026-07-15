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

    # Mock the is_closed method (public API, not private _closed attribute)
    mock_conn.is_closed = MagicMock(return_value=False)

    # Mock the run method to return a process result
    mock_process = MagicMock()
    mock_process.exit_status = 0
    mock_process.stdout = "output"
    mock_process.stderr = ""
    mock_conn.run = AsyncMock(return_value=mock_process)

    # Mock SFTP client
    mock_sftp = MagicMock()
    mock_sftp.makedirs = AsyncMock()
    mock_sftp.put = AsyncMock()
    mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
    mock_sftp.__aexit__ = AsyncMock(return_value=None)
    mock_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

    return mock_conn


def _make_mock_connection_with_result(
    exit_status: int = 0, stdout: str = "", stderr: str = ""
) -> MagicMock:
    """Create a mock SSH client connection that returns specific results."""
    mock_conn = MagicMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_process = MagicMock()
    mock_process.exit_status = exit_status
    mock_process.stdout = stdout
    mock_process.stderr = stderr
    mock_conn.run = AsyncMock(return_value=mock_process)

    # Mock SFTP client
    mock_sftp = MagicMock()
    mock_sftp.mkdir = AsyncMock()
    mock_sftp.put = AsyncMock()
    mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
    mock_sftp.__aexit__ = AsyncMock(return_value=None)
    mock_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

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
    """Test that write_file successfully writes content via SFTP."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = _make_mock_connection()
        mock_connect.return_value = mock_conn

        await mgr.write_file("test-project", "test.txt", "Hello, World!")

        # Verify connection was established
        mock_connect.assert_called_once()
        # Verify SFTP was used
        assert mock_conn.start_sftp_client.called


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
async def test_write_file_shell_metacharacters_rejected():
    """Test that shell metacharacters in relative_path are rejected.

    This prevents command injection via paths like 'foo; touch /tmp/pwned'.
    Note: Some of these may be caught by path traversal first (like ..),
    so we check for either rejection message.
    """
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    # Test paths that contain shell metacharacters but NO path traversal
    shell_metachar_paths = [
        "foo; touch /tmp/pwned",
        "foo$(whoami)",
        "foo`id`",
        "foo|cat /etc/passwd",
        "foo && echo pwned",
        "file>output",
        "file<output",
    ]

    for injection_path in shell_metachar_paths:
        with patch("asyncssh.connect", new_callable=AsyncMock):
            with pytest.raises(ValueError) as exc_info:
                await mgr.write_file(
                    "test-project", injection_path, "malicious content"
                )
            # Should be rejected - either for shell metacharacters or path traversal
            error_msg = str(exc_info.value)
            assert (
                "Shell metacharacters" in error_msg or "Path traversal" in error_msg
            ), f"Path {injection_path} was not rejected: {error_msg}"


@pytest.mark.asyncio
async def test_write_file_null_byte_rejected():
    """Test that null bytes in relative_path are rejected."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock):
        with pytest.raises(ValueError) as exc_info:
            await mgr.write_file("test-project", "foo\x00bar", "content")
        assert "Null byte" in str(exc_info.value)


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
        mock_conn.is_closed = MagicMock(return_value=False)
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


# ---------------------------------------------------------------------------
# Tests for is_available() and backend_name (Batch 39)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_name_returns_ssh():
    """Test that backend_name returns 'ssh'."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    assert mgr.backend_name == "ssh"


@pytest.mark.asyncio
async def test_is_available_true_when_connection_succeeds_mocked():
    """Test is_available returns True when connection works."""
    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = _make_mock_connection()
        mock_connect.return_value = mock_conn

        result = await mgr.is_available()

        assert result is True


@pytest.mark.asyncio
async def test_is_available_false_when_connection_fails_mocked():
    """Test is_available returns False when connection fails."""
    settings = Settings(sandbox_host="unreachable.example.com")
    mgr = SSHSandboxManager(settings=settings)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("Connection refused")

        result = await mgr.is_available()

        assert result is False


@pytest.mark.asyncio
async def test_is_available_false_when_not_configured():
    """Test is_available returns False when sandbox_host is None."""
    settings = Settings(sandbox_host=None)
    mgr = SSHSandboxManager(settings=settings)

    # is_available should return False, not raise
    result = await mgr.is_available()
    assert result is False


@pytest.mark.asyncio
async def test_is_available_false_on_timeout():
    """Test is_available returns False on timeout."""
    settings = Settings(sandbox_host="slow.example.com")
    mgr = SSHSandboxManager(settings=settings)

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(exit_status=0, stdout="", stderr="")

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = MagicMock()
        mock_conn.is_closed = MagicMock(return_value=False)
        mock_conn.run = AsyncMock(side_effect=slow_run)
        mock_connect.return_value = mock_conn

        # is_available should return False on timeout, not raise
        result = await mgr.is_available()
        assert result is False


@pytest.mark.asyncio
async def test_ssh_sandbox_manager_isinstance_of_abstract_base():
    """Test that SSHSandboxManager is an instance of SandboxManager ABC."""
    from ua.sandbox.base import SandboxManager

    settings = Settings(sandbox_host="sandbox.example.com")
    mgr = SSHSandboxManager(settings=settings)

    assert isinstance(mgr, SandboxManager)
