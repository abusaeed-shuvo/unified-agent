"""MemoryManager facade over all three memory layers."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from ua.memory.base import MemoryItem
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.short_term import ShortTermMemory
from ua.models.base import Message


def default_summarizer(messages: list[Message]) -> str:
    """Default pure-Python summarizer for evicted turns.

    This is a deterministic, non-LLM summarizer that joins evicted messages
    as "{role}: {content}" lines, truncated to 500 characters max.

    Example input:
        [Message(role="user", content="Hello"), Message(role="assistant", content="Hi there!")]
    Example output:
        "user: Hello\nassistant: Hi there!"

    Args:
        messages: List of evicted messages to summarize.

    Returns:
        A string summary, truncated to 500 characters.
    """
    lines = [f"{msg.role}: {msg.content}" for msg in messages]
    summary = "\n".join(lines)
    return summary[:500] if len(summary) > 500 else summary


@dataclass
class RetrievedContext:
    """Combined context retrieved from all memory layers."""

    recent_turns: list[Message]
    relevant_facts: list[MemoryItem]
    relevant_knowledge: list[MemoryItem]


class MemoryManager:
    """
    Single facade over ShortTermMemory, LongTermMemory, and KnowledgeMemory.

    This is the ONLY class that ConversationManager and ContextBuilder are allowed
    to depend on for memory — never the three sub-stores directly.
    """

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        knowledge: KnowledgeMemory,
        summarizer: Callable[[list[Message]], str] | None = None,
    ) -> None:
        """Initialize with the three memory layer instances.

        Args:
            short_term: ShortTermMemory instance for ephemeral turn history.
            long_term: LongTermMemory instance for durable user facts.
            knowledge: KnowledgeMemory instance for uploaded knowledge documents.
            summarizer: Optional callable to summarize evicted turns.
                Defaults to a pure-Python, non-LLM function.
        """
        self._short_term = short_term
        self._long_term = long_term
        self._knowledge = knowledge
        self._summarizer = summarizer if summarizer is not None else default_summarizer

        # Track evicted messages per user for summarization
        # This is needed because on_evict is called per-message, but we want
        # to summarize all evicted messages together
        self._evicted_buffer: dict[str, list[Message]] = {}

        # Wire up the eviction callback to ShortTermMemory
        # We use a sync callback that schedules async work via the event loop
        def _on_evict(user_id: str, evicted: Message) -> None:
            # Buffer the evicted message
            if user_id not in self._evicted_buffer:
                self._evicted_buffer[user_id] = []
            self._evicted_buffer[user_id].append(evicted)

        # Wire up the eviction callback to ShortTermMemory via public method
        self._short_term.set_on_evict(_on_evict)

    async def _flush_evicted_summary(self, user_id: str) -> None:
        """Summarize and persist evicted messages for a user.

        This is called after record_turn to ensure the async long_term.put
        can be awaited properly.
        """
        if user_id not in self._evicted_buffer:
            return

        evicted_messages = self._evicted_buffer.pop(user_id)
        if evicted_messages:
            summary = self._summarizer(evicted_messages)
            await self._long_term.put(user_id, "conversation_summary", summary)

    async def retrieve_context(self, user_id: str, message: str) -> RetrievedContext:
        """Concurrently fetch context from all three memory layers.

        Args:
            user_id: The user identifier to scope the search.
            message: The query string to search for in long-term and knowledge stores.

        Returns:
            RetrievedContext with recent_turns, relevant_facts, and relevant_knowledge.
        """
        recent_turns, relevant_facts, relevant_knowledge = await asyncio.gather(
            self._short_term.recent_turns(user_id, limit=10),
            self._long_term.search(user_id, query=message, limit=5),
            self._knowledge.search(user_id, query=message, limit=5),
        )

        return RetrievedContext(
            recent_turns=recent_turns,
            relevant_facts=relevant_facts,
            relevant_knowledge=relevant_knowledge,
        )

    async def record_turn(self, user_id: str, role: str, content: str) -> None:
        """Record a conversation turn in short-term memory.

        v1 does NOT also persist to long_term automatically — see
        Batch 27 (memory summarization) for when eviction triggers a
        durable write.

        Args:
            user_id: The user identifier.
            role: The message role (system, user, assistant, tool).
            content: The message content.
        """
        await self._short_term.append_turn(user_id, role, content)
        # After appending, check if any messages were evicted and flush summary
        await self._flush_evicted_summary(user_id)

    @property
    def long_term(self) -> LongTermMemory:
        """Expose long_term for testing and inspection."""
        return self._long_term

    async def remember_fact(self, user_id: str, key: str, value: str) -> None:
        """Store a durable fact in long-term memory.

        This is the explicit path for durable fact storage, distinct from
        record_turn's ephemeral turn logging.

        Args:
            user_id: The user identifier.
            key: The fact key.
            value: The fact value.
        """
        await self._long_term.put(user_id, key, value)

    async def get_fact(self, user_id: str, key: str) -> str | None:
        """Read a previously-remembered fact for a specific key.

        Thin passthrough to ``LongTermMemory.get``. Used by the agent to
        resolve a previously-stored per-user preference (e.g. an active
        personality) without reaching into the long-term store directly.

        Args:
            user_id: The user identifier.
            key: The fact key.

        Returns:
            The stored value, or None if no fact exists for (user_id, key).
        """
        return await self._long_term.get(user_id, key)
