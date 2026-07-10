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

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...
