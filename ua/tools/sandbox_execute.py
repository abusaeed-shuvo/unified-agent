"""Execute commands within a remote sandbox project directory.

This tool has destructive-command detection and confirmation gating. Risky commands
require user confirmation when running via the CLI interface. Other interfaces
(Web API, Discord) automatically reject risky commands since no synchronous prompt
is available.

IMPORTANT: The confirmation gating is a DEFENSE-IN-DEPTH measure, NOT a primary
security boundary. Risk detection uses blacklist-based pattern matching which is NOT
exhaustive - a sufficiently obfuscated or unusual command can evade detection.
The real safety net is the disposability of the SSH sandbox host itself.

KNOWN RISKS:
- Symlink Escape Risk: Does NOT check for symlinks within the project directory.
  An agent could create symlinks to escape the sandbox (e.g., 'ln -s /etc').
  Combined with shell expansion, this could allow access to files outside
  the sandbox. This will be addressed in a future batch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ua.sandbox.manager import SSHSandboxManager
from ua.sandbox.risk_detection import is_risky_command
from ua.tools.base import Tool, ToolResult


class SandboxExecuteTool(Tool):
    """Execute commands within a remote sandbox project directory.

    This tool has destructive-command detection and confirmation gating. Risky commands
    require user confirmation when running via the CLI interface. Other interfaces
    (Web API, Discord) automatically reject risky commands since no synchronous prompt
    is available.

    KNOWN RISKS:
    - Symlink Escape Risk: Does NOT check for symlinks within the project directory.
      An agent could create symlinks to escape the sandbox (e.g., 'ln -s /etc').
      Combined with shell expansion, this could allow access to files outside
      the sandbox. This will be addressed in a future batch.

    This tool runs shell commands in a per-project directory on a remote SSH sandbox host.
    """

    name = "sandbox_execute"
    description = (
        "Execute a shell command within a remote sandbox project directory. "
        "Risky commands (rm -rf, sudo, dd, etc.) require confirmation. "
        "Symlink escape risk also exists - see tool docstring for details."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "The project identifier (alphanumeric, hyphens, underscores).",
            },
            "command": {
                "type": "string",
                "description": "The shell command to execute in the project directory.",
            },
            "timeout": {
                "type": "number",
                "description": "Maximum execution time in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["project_id", "command"],
    }

    def __init__(
        self,
        sandbox_manager: SSHSandboxManager,
        confirmation_callback: Callable[[str, str], Awaitable[bool]] | None = None,
    ) -> None:
        """Initialize the sandbox execute tool.

        Args:
            sandbox_manager: An SSHSandboxManager instance for remote operations.
                            This is a required constructor argument and the tool
                            cannot be auto-discovered.
            confirmation_callback: Optional async callback for confirming risky commands.
                                  Receives (command, reason) when a risky pattern
                                  is detected. If None, risky commands are auto-rejected.
        """
        self._sandbox_manager = sandbox_manager
        self._confirmation_callback = confirmation_callback

    async def run(
        self, project_id: str, command: str, timeout: float = 60.0
    ) -> ToolResult:
        """Execute a command in the remote sandbox.

        Args:
            project_id: The project identifier.
            command: The shell command to execute.
            timeout: Maximum execution time in seconds (default 60.0).

        Returns:
            ToolResult with success=True and the command output,
            or success=False with an error message.
        """
        # Check for risky command patterns
        is_risky, risk_reason = is_risky_command(command)

        if is_risky:
            # No callback available (Web API, Discord, or default) - reject automatically
            if self._confirmation_callback is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Command '{command}' was rejected because confirmation is not "
                        f"available on this interface. Risk detected: {risk_reason}"
                    ),
                )

            # Try to get confirmation via callback - fail closed on any error
            try:
                confirmed = await self._confirmation_callback(command, risk_reason)
            except Exception:
                # Callback raised an exception - treat as denial
                confirmed = False

            if not confirmed:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Command '{command}' was rejected: confirmation required "
                        f"and not received. Risk detected: {risk_reason}"
                    ),
                )

        # Execute the command
        try:
            exit_code, stdout, stderr = await self._sandbox_manager.execute(
                project_id, command, timeout
            )
            if exit_code == 0:
                return ToolResult(success=True, output=stdout)
            else:
                return ToolResult(
                    success=False,
                    output=stdout,
                    error=f"Command failed with exit code {exit_code}: {stderr}",
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
