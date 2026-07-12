"""Execute commands within a remote sandbox project directory.

WARNING: This tool currently has NO destructive-command detection or confirmation
gating (planned for a future batch). Any command can be executed without confirmation.
Do not expose this tool to an agent with real autonomy against a real host until
that protection is added.
"""

from ua.sandbox.manager import SSHSandboxManager
from ua.tools.base import Tool, ToolResult


class SandboxExecuteTool(Tool):
    """Execute commands within a remote sandbox project directory.

    WARNING: This tool currently has NO destructive-command detection or confirmation
    gating (planned for a future batch). Any command can be executed without confirmation.
    Do not expose this tool to an agent with real autonomy against a real host until
    that protection is added.

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
        "WARNING: This tool currently has NO destructive-command detection or "
        "confirmation gating (planned for a future batch). Any command can be "
        "executed without confirmation. Do not expose this tool to an agent with "
        "real autonomy against a real host until that protection is added. "
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

    def __init__(self, sandbox_manager: SSHSandboxManager) -> None:
        """Initialize the sandbox execute tool.

        Args:
            sandbox_manager: An SSHSandboxManager instance for remote operations.
                           This is a required constructor argument and the tool
                           cannot be auto-discovered.
        """
        self._sandbox_manager = sandbox_manager

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
