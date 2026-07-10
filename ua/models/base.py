"""Abstract interfaces for LLM adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Message:
    """A single message in a conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


@dataclass
class ToolCall:
    """A tool invocation returned by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalised response from an LLM adapter."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


class LLMAdapterError(Exception):
    """Raised by adapters on transient failures.

    Covers timeouts, connection errors, and malformed responses.
    """


class LLMAdapter(ABC):
    """Abstract base class for all LLM provider adapters."""

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send messages to the LLM and return a normalised response."""
