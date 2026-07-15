"""SSH Sandbox Manager for remote execution.

This module provides SSHSandboxManager which manages SSH connections to a remote
sandbox host and provides file/execution operations within per-project directories.

KNOWN RISKS AND TRADEOFFS:
- MITM Vulnerability: known_hosts=None accepts any host key. This is intentional
  for sandbox use where the host is disposable and operated by the user, but means
  a malicious actor could intercept connections. See .env.example for warning.
- Symlink Escape Risk: The execute() method does NOT check for symlinks within
  the project directory. Combined with the lack of destructive-command detection
  (planned for Batch 35), this could allow privilege escalation or data access
  outside the sandbox.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

import asyncssh

from ua.config.settings import Settings, get_settings
from ua.sandbox.base import SandboxManager


class SSHSandboxNotConfiguredError(Exception):
    """Raised when sandbox host is not configured but a sandbox operation is attempted."""


class SSHSandboxConnectionError(Exception):
    """Raised when SSH connection to sandbox host fails."""


class SSHSandboxManager(SandboxManager):
    """Manager for SSH connections to a remote sandbox host.

    This class handles:
    - SSH connection to a configurable remote host
    - Per-project working directories on the remote host
    - Fail-closed behavior when the host is unreachable

    The manager reuses a single SSH connection across multiple calls.

    KNOWN RISKS AND TRADEOFFS:
    - MITM Vulnerability: known_hosts=None accepts any host key. This is intentional
      for sandbox use where the host is disposable and operated by the user, but means
      a malicious actor could intercept connections. See .env.example for warning.
    - Symlink Escape Risk: The execute() method does NOT check for symlinks within
      the project directory. Combined with the lack of destructive-command detection
      (planned for Batch 35), this could allow privilege escalation or data access
      outside the sandbox.
    - Command Injection Risk: The execute() method runs arbitrary shell commands.
      No destructive-command detection or confirmation gating exists yet
      (planned for Batch 35).
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

    @property
    def backend_name(self) -> str:
        """Return the backend identifier for SSH."""
        return "ssh"

    async def is_available(self) -> bool:
        """Check if the SSH sandbox backend is available.

        Performs a lightweight connection check to verify the backend can be used.

        Returns:
            True if the host is configured and reachable, False on any failure.
        """
        if not self._is_configured():
            return False

        try:
            conn = await self._get_connection()
            # Run a trivial command with a short timeout to verify connection works
            await asyncio.wait_for(conn.run("echo ok", check=False), timeout=5.0)
            return True
        except Exception:
            return False

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

        # Use the public is_closed() method instead of private _closed attribute
        if self._connection is None or self._connection.is_closed():
            try:
                self._connection = await asyncssh.connect(
                    host=self._settings.sandbox_host,
                    port=self._settings.sandbox_port,
                    username=self._settings.sandbox_username,
                    client_keys=[self._settings.sandbox_key_path]
                    if self._settings.sandbox_key_path
                    else None,
                    known_hosts=None,  # See class docstring for MITM warning
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
        # when used in shell commands. We use SFTP for file writes, but this
        # adds defense-in-depth for any future shell-based operations.
        dangerous_chars = set(";$`|&<>!(){}[]<>*?")
        if any(char in relative_path for char in dangerous_chars):
            raise ValueError(
                f"Shell metacharacters detected in relative_path: {relative_path}"
            )

        return relative_path

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

        Uses SFTP for safe file operations, avoiding shell command injection.
        Path traversal via '../' is blocked.

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
        validated_path = self._validate_relative_path(relative_path)
        project_path = f"{self.BASE_DIR}/{validated_id}"

        full_path = f"{project_path}/{validated_path}"

        conn = await self._get_connection()
        async with conn.start_sftp_client() as sftp:
            # Create parent directories if needed
            parent_path = str(Path(full_path).parent)
            if parent_path != project_path:
                # Use SFTP makedirs for safe directory creation
                await sftp.makedirs(parent_path, exist_ok=True)

            # Write file using SFTP - safe from command injection
            # Use a temp file approach for atomic writes
            with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            try:
                await sftp.put(tmp_path, full_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    async def execute(
        self, project_id: str, command: str, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Execute a command in the project directory on the remote host.

        WARNING: This method has NO destructive-command detection or confirmation
        gating (planned for Batch 35). Any command can be executed without confirmation.
        Do not expose this tool to an agent with real autonomy against a real host
        until that protection is added.

        KNOWN RISKS:
        - Symlink Escape Risk: Does NOT check for symlinks within the project
          directory. A symlink like 'ln -s /etc' followed by shell expansion
          could allow access to files outside the sandbox.

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