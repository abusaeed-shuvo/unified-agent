"""Tool abstract base class and ToolResult type for Unified Agent."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ToolResult:
    """Result returned by a tool execution."""

    success: bool
    output: str
    error: str | None = None


class Tool(ABC):
    """Abstract base class for all tools.

    Every concrete tool must set name, description, and parameters as class
    attributes, and implement the async run() method.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict]
    enabled: ClassVar[bool] = True
    requires_user_context: ClassVar[bool] = False
    """If True, the tool needs a trusted user_id injected before execution.

    Tools that need per-user context (like sandbox tools using SandboxBackendRegistry)
    set this to True. The ToolRegistry's execute() will then inject the user_id
    parameter, stripping any LLM-supplied user_id from kwargs first.
    """

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...
