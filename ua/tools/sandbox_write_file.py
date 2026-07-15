"""Write files within a remote sandbox project directory.

WARNING: This tool currently has NO destructive-command detection or confirmation
gating (planned for a future batch). Any command can be executed without confirmation.
Do not expose this tool to an agent with real autonomy against a real host until
that protection is added.
"""

from ua.sandbox.base import SandboxManager
from ua.tools.base import Tool, ToolResult


class SandboxWriteFileTool(Tool):
    """Write a file within a remote sandbox project directory.

    WARNING: This tool currently has NO destructive-command detection or confirmation
    gating (planned for a future batch). Any command can be executed without confirmation.
    Do not expose this tool to an agent with real autonomy against a real host until
    that protection is added.

    This tool writes files to a per-project directory on a remote SSH sandbox host.
    Path traversal attacks are blocked. Shell metacharacters in paths are also blocked.
    """

    name = "sandbox_write_file"
    description = (
        "Write content to a file within a remote sandbox project directory. "
        "WARNING: This tool currently has NO destructive-command detection or "
        "confirmation gating (planned for a future batch). Any command can be "
        "executed without confirmation. Do not expose this tool to an agent with "
        "real autonomy against a real host until that protection is added."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "The project identifier (alphanumeric, hyphens, underscores).",
            },
            "relative_path": {
                "type": "string",
                "description": "Path relative to the project directory (no shell metacharacters).",
            },
            "content": {
                "type": "string",
                "description": "The file content to write.",
            },
        },
        "required": ["project_id", "relative_path", "content"],
    }

    def __init__(self, sandbox_manager: SandboxManager) -> None:
        """Initialize the sandbox write file tool.

        Args:
            sandbox_manager: A SandboxManager instance for remote operations.
                           This is a required constructor argument and the tool
                           cannot be auto-discovered.
        """
        self._sandbox_manager = sandbox_manager

    async def run(
        self, project_id: str, relative_path: str, content: str
    ) -> ToolResult:
        """Write a file to the remote sandbox.

        Args:
            project_id: The project identifier.
            relative_path: Path relative to the project directory.
            content: The file content to write.

        Returns:
            ToolResult with success=True if the file was written,
            or success=False with an error message.
        """
        try:
            await self._sandbox_manager.write_file(
                project_id, relative_path, content
            )
            return ToolResult(
                success=True, output=f"File written: {relative_path}"
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
