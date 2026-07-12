"""SSH Sandbox Manager for remote execution.

This module provides SSHSandboxManager which manages SSH connections to a remote
sandbox host and provides file/execution operations within per-project directories.
"""

from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path

import asyncssh

from ua.config.settings import Settings, get_settings


class SSHSandboxNotConfiguredError(Exception):
    """Raised when sandbox host is not configured but a sandbox operation is attempted."""


class SSHSandboxConnectionError(Exception):
    """Raised when SSH connection to sandbox host fails."""


class SSHSandboxManager:
    """Manager for SSH connections to a remote sandbox host.

    This class handles:
    - SSH connection to a configurable remote host
    - Per-project working directories on the remote host
    - Fail-closed behavior when the host is unreachable

    The manager reuses a single SSH connection across multiple calls.
    """

    BASE_DIR = "/home/sandbox/projects"

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the SSH sandbox manager.

        Args:
            settings: Optional Settings object. If not provided, uses get_settings().
                     The settings must have sandbox_host configured for real connections.
        """
        if settings is None:
            settings = get_settings()

        self._settings = settings
        self._connection: asyncssh.SSHClientConnection | None = None

    def _is_configured(self) -> bool:
        """Check if the sandbox is configured (host is set)."""
        return self._settings.sandbox_host is not None

    async def _get_connection(self) -> asyncssh.SSHClientConnection:
        """Get or create an SSH connection.

        Returns:
            The SSH client connection.

        Raises:
            SSHSandboxNotConfiguredError: If no sandbox host is configured.
            SSHSandboxConnectionError: If connection fails.
        """
        if not self._is_configured():
            raise SSHSandboxNotConfiguredError(
                "Sandbox host not configured. Set UA_SANDBOX_HOST environment variable."
            )

        if self._connection is None or self._connection._closed:
            try:
                self._connection = await asyncssh.connect(
                    host=self._settings.sandbox_host,
                    port=self._settings.sandbox_port,
                    username=self._settings.sandbox_username,
                    client_keys=[self._settings.sandbox_key_path]
                    if self._settings.sandbox_key_path
                    else None,
                    known_hosts=None,  # Accept any host key (for sandbox use)
                )
            except Exception as exc:
                raise SSHSandboxConnectionError(
                    f"Failed to connect to sandbox host: {exc}"
                ) from exc

        return self._connection

    def _validate_project_id(self, project_id: str) -> str:
        """Validate and sanitize a project_id.

        Project IDs must be alphanumeric with hyphens and underscores only.
        This prevents path injection attacks via malicious project_id strings.

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

    async def ensure_project_dir(self, project_id: str) -> str:
        """Ensure the project directory exists on the remote host.

        Args:
            project_id: The project identifier (alphanumeric + hyphens/underscores only).

        Returns:
            The absolute path to the project directory on the remote host.

        Raises:
            ValueError: If project_id is invalid.
            SSHSandboxNotConfiguredError: If no sandbox host is configured.
            SSHSandboxConnectionError: If connection fails.
        """
        validated_id = self._validate_project_id(project_id)
        project_path = f"{self.BASE_DIR}/{validated_id}"

        conn = await self._get_connection()
        await conn.run(f"mkdir -p {project_path}", check=False)

        return project_path

    async def write_file(
        self, project_id: str, relative_path: str, content: str
    ) -> None:
        """Write a file to the project directory on the remote host.

        Path traversal via '../' is blocked. The relative_path is resolved
        against the project directory and verified to stay within bounds.

        Args:
            project_id: The project identifier (validated for security).
            relative_path: Path relative to the project directory.
            content: The file content to write.

        Raises:
            ValueError: If project_id or relative_path contains path traversal attempts.
            SSHSandboxNotConfiguredError: If no sandbox host is configured.
            SSHSandboxConnectionError: If connection fails.
        """
        validated_id = self._validate_project_id(project_id)

        project_path = f"{self.BASE_DIR}/{validated_id}"

        # Sanitize relative_path: reject any path traversal attempt
        if ".." in relative_path.split("/") or ".." in relative_path.split("\\"):
            raise ValueError(f"Path traversal detected in relative_path: {relative_path}")

        full_path = f"{project_path}/{relative_path}"

        conn = await self._get_connection()
        # Create parent directories if needed
        parent = str(Path(full_path).parent)
        if parent != project_path:
            await conn.run(f"mkdir -p {parent}", check=False)

        # Write the file using base64 encoding to handle any content safely
        encoded = base64.b64encode(content.encode()).decode()
        await conn.run(f"echo {encoded} | base64 -d > {full_path}", check=False)

    async def execute(
        self, project_id: str, command: str, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Execute a command in the project directory on the remote host.

        Args:
            project_id: The project identifier.
            command: The shell command to execute.
            timeout: Maximum execution time in seconds (default 60.0).

        Returns:
            Tuple of (exit_code, stdout, stderr).

        Raises:
            SSHSandboxNotConfiguredError: If no sandbox host is configured.
            SSHSandboxConnectionError: If connection fails.
            asyncio.TimeoutError: If command times out.
        """
        validated_id = self._validate_project_id(project_id)
        project_path = f"{self.BASE_DIR}/{validated_id}"

        conn = await self._get_connection()
        result = await asyncio.wait_for(
            conn.run(command, cwd=project_path),
            timeout=timeout,
        )

        return (
            result.exit_status or 0,
            result.stdout or "",
            result.stderr or "",
        )

    async def is_reachable(self) -> bool:
        """Check if the sandbox host is reachable.

        Returns:
            True if the host is configured and reachable, False otherwise.
        """
        if not self._is_configured():
            return False

        try:
            conn = await self._get_connection()
            # Run a simple command to verify connection works
            await conn.run("true", check=False)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close the SSH connection."""
        if self._connection is not None:
            self._connection.close()
            await self._connection.wait_closed()
            self._connection = None
