"""Docker Sandbox Manager for local containerized execution.

This module provides DockerSandboxManager which manages Docker containers as sandboxes
and provides file/execution operations within per-project containers.

KNOWN RISKS AND TRADEOFFS:
- Network Isolation Not Enforced: Containers use default bridge networking without
  network isolation. A compromised sandboxed process could reach the network.
  This is deferred to a future hardening batch.
- No Non-Root User: Processes run as the image's default user (often root).
  This is deferred to a future hardening batch.
- Command Injection Risk: The execute() method runs arbitrary shell commands.
  No destructive-command detection or confirmation gating exists yet.
- Container Escape Risk: Docker containers are not security boundaries. A determined
  attacker with root privileges inside the container could escape to the host.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from ua.config.settings import Settings, get_settings
from ua.sandbox.base import SandboxManager


class DockerSandboxError(Exception):
    """Raised when Docker sandbox operations fail."""


class DockerSandboxManager(SandboxManager):
    """Manager for Docker containers as sandboxes.

    This class handles:
    - Persistent per-project containers named ua-sandbox-{project_id}
    - Container creation with security hardening (caps, pids limit, no-new-privileges)
    - Memory and CPU resource limits
    - File operations via docker cp
    - Command execution with in-container timeout

    KNOWN RISKS AND TRADEOFFS:
    - Network Isolation Not Enforced: Containers use default bridge networking.
      A compromised sandboxed process could reach the network.
      This is deferred to a future hardening batch.
    - No Non-Root User: Processes run as the image's default user (often root).
      This is deferred to a future hardening batch.
    - Command Injection Risk: The execute() method runs arbitrary shell commands.
      No destructive-command detection exists yet.
    """

    CONTAINER_PREFIX = "ua-sandbox-"
    WORKSPACE_PATH = "/workspace"

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the Docker sandbox manager.

        Args:
            settings: Optional Settings object. If not provided, uses get_settings().
        """
        if settings is None:
            settings = get_settings()

        self._settings = settings

    @property
    def backend_name(self) -> str:
        """Return the backend identifier for Docker."""
        return "docker"

    async def is_available(self) -> bool:
        """Check if the Docker backend is available.

        Runs `docker version` with a short subprocess timeout (~5s).

        Returns:
            True if Docker is installed and daemon is running, False on any failure.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._settings.sandbox_docker_binary,
                "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return proc.returncode == 0
        except Exception:
            return False

    def _validate_project_id(self, project_id: str) -> str:
        """Validate and sanitize a project_id.

        Project IDs must be alphanumeric with hyphens and underscores only.
        This prevents container-name injection attacks via malicious project_id strings.

        Args:
            project_id: The project identifier to validate.

        Returns:
            The sanitized project_id.

        Raises:
            ValueError: If project_id contains invalid characters.
        """
        if not re.match(r"^[a-zA-Z0-9_-]+$", project_id):
            raise ValueError(
                f"Invalid project_id '{project_id}': must contain only "
                "alphanumeric characters, hyphens, and underscores"
            )
        return project_id

    def _validate_relative_path(self, relative_path: str) -> str:
        """Validate and sanitize a relative path for file operations.

        Path must not contain:
        - Path traversal attempts (../)
        - Shell metacharacters that could enable command injection
        - Null bytes

        Args:
            relative_path: The relative path to validate.

        Returns:
            The validated relative path.

        Raises:
            ValueError: If path contains dangerous characters.
        """
        # Reject path traversal
        if ".." in relative_path.split("/") or ".." in relative_path.split("\\"):
            raise ValueError(f"Path traversal detected in relative_path: {relative_path}")

        # Reject null bytes
        if "\x00" in relative_path:
            raise ValueError("Null byte detected in relative_path")

        # Reject shell metacharacters that could enable command injection
        # when used in shell commands. We use docker cp for file writes, but this
        # adds defense-in-depth for any shell-based operations.
        dangerous_chars = set(";$`|&<>!(){}[]<>*?")
        if any(char in relative_path for char in dangerous_chars):
            raise ValueError(
                f"Shell metacharacters detected in relative_path: {relative_path}"
            )

        return relative_path

    def _get_container_name(self, project_id: str) -> str:
        """Get the container name for a project_id.

        Args:
            project_id: The validated project identifier.

        Returns:
            The Docker container name.
        """
        return f"{self.CONTAINER_PREFIX}{project_id}"

    async def _run_docker_command(
        self, *args: str, check: bool = True
    ) -> tuple[int, str, str]:
        """Run a docker command and return (exit_code, stdout, stderr).

        Args:
            *args: Arguments to pass to docker command.
            check: If True, raise on non-zero exit code.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        proc = await asyncio.create_subprocess_exec(
            self._settings.sandbox_docker_binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        exit_code = proc.returncode or 0
        if check and exit_code != 0:
            raise DockerSandboxError(
                f"Docker command failed: {' '.join(args)}\n{stderr.decode()}"
            )
        return exit_code, stdout.decode(), stderr.decode()

    async def _container_exists(self, project_id: str) -> bool:
        """Check if the container exists.

        Args:
            project_id: The validated project identifier.

        Returns:
            True if the container exists, False otherwise.
        """
        container_name = self._get_container_name(project_id)
        try:
            exit_code, _, _ = await self._run_docker_command(
                "inspect", container_name, check=False
            )
            return exit_code == 0
        except Exception:
            return False

    async def _container_is_running(self, project_id: str) -> bool:
        """Check if the container is running.

        Args:
            project_id: The validated project identifier.

        Returns:
            True if the container is running, False otherwise.
        """
        container_name = self._get_container_name(project_id)
        try:
            exit_code, stdout, _ = await self._run_docker_command(
                "inspect", "--format", "{{.State.Running}}", container_name, check=False
            )
            if exit_code == 0:
                # Parse the output - it will be "true" or "false"
                return stdout.strip().lower() == "true"
            return False
        except Exception:
            return False

    async def _create_container(self, project_id: str) -> None:
        """Create a new container for the project.

        Args:
            project_id: The validated project identifier.
        """
        container_name = self._get_container_name(project_id)

        await self._run_docker_command(
            "run",
            "-d",
            "--name",
            container_name,
            "--memory",
            self._settings.sandbox_docker_memory_limit,
            "--cpus",
            self._settings.sandbox_docker_cpu_limit,
            "--pids-limit",
            "256",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "-w",
            self.WORKSPACE_PATH,
            self._settings.sandbox_docker_image,
            "tail",
            "-f",
            "/dev/null",
        )

    async def _start_container(self, project_id: str) -> None:
        """Start an existing stopped container.

        Args:
            project_id: The validated project identifier.
        """
        container_name = self._get_container_name(project_id)
        await self._run_docker_command("start", container_name)

    async def ensure_project_dir(self, project_id: str) -> str:
        """Ensure the project container exists and is running.

        Creates the container if it doesn't exist, or starts it if it exists
        but is stopped. Returns "/workspace" as the workspace path.

        Args:
            project_id: The project identifier (alphanumeric + hyphens/underscores only).

        Returns:
            The absolute path to the workspace in the container.

        Raises:
            ValueError: If project_id is invalid.
            DockerSandboxError: If container creation/starting fails.
        """
        validated_id = self._validate_project_id(project_id)

        if await self._container_exists(validated_id):
            # Container exists - check if it's running
            if not await self._container_is_running(validated_id):
                await self._start_container(validated_id)
        else:
            # Container doesn't exist - create it
            await self._create_container(validated_id)

        return self.WORKSPACE_PATH

    async def write_file(
        self, project_id: str, relative_path: str, content: str
    ) -> None:
        """Write a file to the project container via docker cp.

        Creates parent directories inside the container first via docker exec.

        Args:
            project_id: The project identifier (validated for security).
            relative_path: Path relative to the workspace.
            content: The file content to write.

        Raises:
            ValueError: If project_id or relative_path contains path traversal attempts.
            DockerSandboxError: If file operations fail.
        """
        validated_id = self._validate_project_id(project_id)
        validated_path = self._validate_relative_path(relative_path)

        # Ensure the container exists
        await self.ensure_project_dir(validated_id)

        # Create parent directories inside the container
        parent_path = str(Path(validated_path).parent)
        if parent_path != ".":
            full_parent = f"{self.WORKSPACE_PATH}/{parent_path}"
            await self._run_docker_command(
                "exec",
                self._get_container_name(validated_id),
                "mkdir",
                "-p",
                full_parent,
            )

        # Write content to a temp file and copy to container
        # Use explicit permissions (644) so the file is readable in container
        # even when --cap-drop ALL prevents chmod operations inside the container
        fd, tmp_path = tempfile.mkstemp()
        try:
            os.write(fd, content.encode())
            os.close(fd)
            os.chmod(tmp_path, 0o644)
            await self._run_docker_command(
                "cp",
                tmp_path,
                f"{self._get_container_name(validated_id)}:{self.WORKSPACE_PATH}/{validated_path}",
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def execute(
        self, project_id: str, command: str, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Execute a command in the project container.

        Uses the container-side `timeout` command to ensure processes are killed
        if the subprocess is terminated.

        Args:
            project_id: The project identifier (validated for security).
            command: The shell command to execute.
            timeout: Maximum execution time in seconds (default 60.0).

        Returns:
            Tuple of (exit_code, stdout, stderr).

        Raises:
            ValueError: If project_id is invalid.
            DockerSandboxError: If execution fails.
        """
        validated_id = self._validate_project_id(project_id)

        # Ensure the container exists and is running
        await self.ensure_project_dir(validated_id)

        # Execute with container-side timeout
        # timeout command returns 124 on timeout kill
        exit_code, stdout, stderr = await self._run_docker_command(
            "exec",
            self._get_container_name(validated_id),
            "timeout",
            f"{int(timeout)}s",
            "sh",
            "-c",
            command,
            check=False,
        )

        return exit_code, stdout, stderr