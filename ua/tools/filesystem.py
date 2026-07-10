"""Sandboxed filesystem read tool.

This tool provides read-only access to files and directories within a configured
sandbox root, with explicit protection against path traversal attacks.
"""

from pathlib import Path

from ua.tools.base import Tool, ToolResult


class FilesystemTool(Tool):
    """Read files or list directories within an allowed sandbox root.

    This tool enforces strict path safety:
    - All paths are resolved relative to a sandbox root
    - Path traversal via "../" is blocked
    - Absolute paths outside the sandbox are blocked
    - Symlinks that escape the sandbox are detected and blocked

    Security note: The path resolution and safety check MUST happen AFTER
    `.resolve()` (which follows symlinks), not before. Resolving first is
    what catches both `../../etc/passwd`-style traversal AND a symlink inside
    the sandbox that points outside it. Getting the order wrong silently
    reintroduces the vulnerability.
    """

    name = "filesystem"
    description = "Read files or list directories within an allowed sandbox root."
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "list"]},
            "path": {"type": "string", "description": "Path relative to the sandbox root."},
        },
        "required": ["action", "path"],
    }

    def __init__(self, sandbox_root: Path):
        """Initialize the filesystem tool with a sandbox root.

        Args:
            sandbox_root: The root directory for all file operations. This should
                be resolved (Path.resolve()) at construction time to ensure
                consistent path comparisons.
        """
        self.sandbox_root = sandbox_root

    async def run(self, action: str, path: str) -> ToolResult:
        """Execute the filesystem action.

        Args:
            action: Either "read" to read a file, or "list" to list a directory.
            path: Path relative to the sandbox root.

        Returns:
            ToolResult with success=True and the file content or directory
            entries as output, or success=False with an error message.
        """
        # Resolve the candidate path - this follows symlinks, which is critical
        # for security. We must resolve BEFORE checking is_relative_to.
        candidate = (self.sandbox_root / path).resolve()

        # Security check: ensure the resolved path is within the sandbox
        # This catches both "../" traversal AND symlinks pointing outside
        if not candidate.is_relative_to(self.sandbox_root):
            return ToolResult(
                success=False,
                output="",
                error=f"Path '{path}' is outside the sandbox root",
            )

        if action == "read":
            return await self._read_file(candidate)
        elif action == "list":
            return await self._list_directory(candidate)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown action: {action}",
            )

    async def _read_file(self, file_path: Path) -> ToolResult:
        """Read a file and return its content.

        Args:
            file_path: The resolved, validated path to read.

        Returns:
            ToolResult with file content or error.
        """
        # Check if path is a directory before attempting to read
        if file_path.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path '{file_path}' is a directory, not a file",
            )

        try:
            content = file_path.read_text()
            return ToolResult(success=True, output=content)
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"File not found: {file_path}",
            )
        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                output="",
                error=f"File '{file_path}' is not a valid text file (binary?)",
            )
        except PermissionError:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied reading file: {file_path}",
            )

    async def _list_directory(self, dir_path: Path) -> ToolResult:
        """List entries in a directory.

        Args:
            dir_path: The resolved, validated path to list.

        Returns:
            ToolResult with newline-joined directory entries or error.
        """
        # Check if path is a file before attempting to list
        if dir_path.exists() and not dir_path.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path '{dir_path}' is a file, not a directory",
            )

        try:
            entries = [entry.name for entry in dir_path.iterdir()]
            return ToolResult(success=True, output="\n".join(entries))
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {dir_path}",
            )
        except PermissionError:
            return ToolResult(
                success=False,
                output="",
                error=f"Permission denied listing directory: {dir_path}",
            )
