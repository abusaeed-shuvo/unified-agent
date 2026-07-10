"""MemoryManager facade over all three memory layers."""

import asyncio
from dataclasses import dataclass

from ua.memory.base import MemoryItem
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.short_term import ShortTermMemory
from ua.models.base import Message


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
    ) -> None:
        """Initialize with the three memory layer instances.

        Args:
            short_term: ShortTermMemory instance for ephemeral turn history.
            long_term: LongTermMemory instance for durable user facts.
            knowledge: KnowledgeMemory instance for uploaded knowledge documents.
        """
        self._short_term = short_term
        self._long_term = long_term
        self._knowledge = knowledge

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
