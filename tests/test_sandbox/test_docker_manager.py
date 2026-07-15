"""Tests for DockerSandboxManager with mocked subprocess calls."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ua.config.settings import Settings
from ua.sandbox.docker_manager import DockerSandboxManager, DockerSandboxError
from ua.sandbox.base import SandboxManager


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_proc(
    exit_code: int = 0, stdout: str = "", stderr: str = ""
) -> MagicMock:
    """Create a mock subprocess that returns specific exit code and output."""

    mock = MagicMock()
    mock.returncode = exit_code
    mock.communicate = AsyncMock(return_value=(stdout.encode(), stderr.encode()))
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_project_dir_creates_container_if_not_exists():
    """Test that ensure_project_dir creates the container when it doesn't exist."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    mock_proc_inspect = _make_mock_proc(exit_code=1, stdout="", stderr="")
    mock_proc_run = _make_mock_proc(exit_code=0, stdout="", stderr="")

    calls = [mock_proc_inspect, mock_proc_run]
    call_idx = [0]

    async def mock_exec(*args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        return calls[idx % len(calls)]

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        result = await mgr.ensure_project_dir("test-project")

        assert result == "/workspace"


@pytest.mark.asyncio
async def test_ensure_project_dir_reuses_existing_running_container():
    """Test that ensure_project_dir reuses an existing running container."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        # Both inspect calls return success with "true" (running)
        return _make_mock_proc(exit_code=0, stdout="true", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        result = await mgr.ensure_project_dir("test-project")

        assert result == "/workspace"


@pytest.mark.asyncio
async def test_ensure_project_dir_restarts_stopped_container():
    """Test that ensure_project_dir restarts a stopped container."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        # Return different responses based on the command
        if args[1] == "start":
            return _make_mock_proc(exit_code=0, stdout="", stderr="")
        # inspect calls - return running=false
        return _make_mock_proc(exit_code=0, stdout="false", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        result = await mgr.ensure_project_dir("test-project")

        assert result == "/workspace"


@pytest.mark.asyncio
async def test_write_file_uses_docker_cp():
    """Test that write_file uses docker cp to write files."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        # Check if container exists (running)
        if args[1] == "inspect":
            return _make_mock_proc(exit_code=0, stdout="true", stderr="")
        return _make_mock_proc(exit_code=0, stdout="", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        await mgr.write_file("test-project", "test.txt", "Hello, World!")
        # Test passes if no exception raised


@pytest.mark.asyncio
async def test_write_file_rejects_path_traversal():
    """Test that path traversal in relative_path is rejected."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    traversal_paths = [
        "../../etc/passwd",
        "../outside.txt",
        "subdir/../../outside.txt",
        "foo/../../../bar",
    ]

    for traversal_path in traversal_paths:
        with pytest.raises(ValueError) as exc_info:
            await mgr.write_file("test-project", traversal_path, "malicious content")
        assert "Path traversal" in str(exc_info.value)


@pytest.mark.asyncio
async def test_write_file_rejects_shell_metacharacters():
    """Test that shell metacharacters in relative_path are rejected."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    shell_metachar_paths = [
        "foo; touch /tmp/pwned",
        "foo$(whoami)",
        "foo`id`",
        "foo|cat /etc/passwd",
        "foo && echo pwned",
    ]

    for injection_path in shell_metachar_paths:
        with pytest.raises(ValueError) as exc_info:
            await mgr.write_file("test-project", injection_path, "malicious content")
        assert "Shell metacharacters" in str(exc_info.value)


@pytest.mark.asyncio
async def test_write_file_rejects_null_bytes():
    """Test that null bytes in relative_path are rejected."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    with pytest.raises(ValueError) as exc_info:
        await mgr.write_file("test-project", "foo\x00bar", "content")
    assert "Null byte" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_returns_exit_code_stdout_stderr():
    """Test that execute returns exit code, stdout, and stderr correctly."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        cmd = args[1] if len(args) > 1 else ""
        if cmd == "inspect":
            return _make_mock_proc(exit_code=0, stdout="true", stderr="")
        # exec call - return mock result
        return _make_mock_proc(exit_code=0, stdout="Hello, stdout!", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        exit_code, stdout, stderr = await mgr.execute("test-project", "echo hello")

        assert exit_code == 0
        assert stdout == "Hello, stdout!"
        assert stderr == ""


@pytest.mark.asyncio
async def test_execute_kills_command_exceeding_timeout():
    """Test that execute uses container-side timeout to kill long-running commands."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        cmd = args[1] if len(args) > 1 else ""
        if cmd == "inspect":
            return _make_mock_proc(exit_code=0, stdout="true", stderr="")
        # exec call - timeout command returns 124 on kill
        return _make_mock_proc(exit_code=124, stdout="", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        # Short timeout
        exit_code, stdout, stderr = await mgr.execute(
            "test-project", "sleep 100", timeout=1.0
        )

        # The timeout command returns 124 when it kills a process
        assert exit_code == 124


@pytest.mark.asyncio
async def test_is_available_false_when_docker_not_installed():
    """Test is_available returns False when docker binary isn't installed."""
    settings = Settings(sandbox_docker_binary="/nonexistent/docker")
    mgr = DockerSandboxManager(settings=settings)

    # FileNotFoundError will be raised by create_subprocess_exec
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
        result = await mgr.is_available()
        assert result is False


@pytest.mark.asyncio
async def test_is_available_false_when_daemon_unreachable():
    """Test is_available returns False when docker daemon is unreachable."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.returncode = 1

    def raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("asyncio.wait_for", side_effect=raise_timeout):
            result = await mgr.is_available()
            assert result is False


@pytest.mark.asyncio
async def test_is_available_true_when_docker_responds():
    """Test is_available returns True when docker responds correctly."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        return _make_mock_proc(exit_code=0, stdout="", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        with patch("asyncio.wait_for", return_value=None):
            result = await mgr.is_available()
            assert result is True


@pytest.mark.asyncio
async def test_backend_name_is_docker():
    """Test that backend_name returns 'docker'."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    assert mgr.backend_name == "docker"


@pytest.mark.asyncio
async def test_malicious_project_id_rejected_before_shell_interpolation():
    """Test that malicious project_ids are rejected before any docker commands."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    malicious_ids = [
        "../etc",
        "project; rm -rf /",
        "project with spaces",
        "../..",
        "project$(whoami)",
        "project`id`",
        "project|cat /etc/passwd",
        "",
        "project\x00null",  # null byte
        "project/../../../etc",  # path traversal in project_id
    ]

    for malicious_id in malicious_ids:
        with pytest.raises(ValueError) as exc_info:
            await mgr.ensure_project_dir(malicious_id)
        assert "Invalid project_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_malicious_project_id_rejected_in_write_file():
    """Test that malicious project_ids are rejected in write_file."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    malicious_ids = [
        "; rm -rf /",
        "$(whoami)",
        "`id`",
        "project|cat /etc/passwd",
    ]

    for malicious_id in malicious_ids:
        with pytest.raises(ValueError) as exc_info:
            await mgr.write_file(malicious_id, "test.txt", "content")
        assert "Invalid project_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_malicious_project_id_rejected_in_execute():
    """Test that malicious project_ids are rejected in execute."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    malicious_ids = [
        "; rm -rf /",
        "$(whoami)",
        "`id`",
        "project|cat /etc/passwd",
    ]

    for malicious_id in malicious_ids:
        with pytest.raises(ValueError) as exc_info:
            await mgr.execute(malicious_id, "ls")
        assert "Invalid project_id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Real Docker integration test (skip if Docker not available)
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Check if Docker is actually available on the system."""
    import shutil

    return shutil.which("docker") is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not _docker_available(), reason="Docker not available on system")
async def test_real_docker_roundtrip():
    """Real integration test: create container → write file → execute → verify.

    This test requires a real Docker daemon and is skipped if docker binary
    is not found. Cleans up the container after the test.
    """
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    project_id = "test-real-roundtrip"

    # Clean up any existing container first
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", f"ua-sandbox-{project_id}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        pass

    try:
        # ensure_project_dir creates the container
        workspace = await mgr.ensure_project_dir(project_id)
        assert workspace == "/workspace"

        # write_file writes a test file
        test_content = "Hello from Docker sandbox!"
        await mgr.write_file(project_id, "test.txt", test_content)

        # execute reads the file back
        exit_code, stdout, stderr = await mgr.execute(project_id, "cat test.txt")

        assert exit_code == 0
        assert stdout.strip() == test_content

    finally:
        # Clean up - remove the container
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", f"ua-sandbox-{project_id}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_docker_sandbox_manager_isinstance_of_abstract_base():
    """Test that DockerSandboxManager is an instance of SandboxManager ABC."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    assert isinstance(mgr, SandboxManager)


@pytest.mark.asyncio
async def test_is_available_returns_false_on_exception():
    """Test that is_available returns False on any exception, never raises."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("Unexpected error")):
        result = await mgr.is_available()
        assert result is False


@pytest.mark.asyncio
async def test_is_available_returns_false_on_nonzero_exit():
    """Test that is_available returns False when docker version returns non-zero."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    async def mock_exec(*args, **kwargs):
        return _make_mock_proc(exit_code=1, stdout="", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        with patch("asyncio.wait_for", return_value=None):
            result = await mgr.is_available()
            assert result is False


@pytest.mark.asyncio
async def test_executes_command_in_workspace_directory():
    """Test that execute runs commands in the workspace directory."""
    settings = Settings()
    mgr = DockerSandboxManager(settings=settings)

    recorded_args = {}

    async def mock_exec(*args, **kwargs):
        cmd = args[1] if len(args) > 1 else ""
        if cmd == "inspect":
            return _make_mock_proc(exit_code=0, stdout="true", stderr="")
        elif cmd == "exec":
            recorded_args["exec_args"] = args
            return _make_mock_proc(exit_code=0, stdout="", stderr="")
        return _make_mock_proc(exit_code=0, stdout="", stderr="")

    with patch("asyncio.create_subprocess_exec", new=mock_exec):
        await mgr.execute("test-project", "ls -la")

        # Verify exec was called with container name
        exec_args = recorded_args.get("exec_args", ())
        assert "exec" in exec_args
        assert "ua-sandbox-test-project" in exec_args