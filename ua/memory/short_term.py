"""In-process, ephemeral short-term memory implementation."""

from collections import deque

from ua.memory.base import MemoryItem
from ua.models.base import Message


class ShortTermMemory:
    """
    In-process, ephemeral short-term memory. NOT persisted to disk —
    data is lost on process restart. This is intentional; see
    Architecture.md §6. Durable memory belongs in LongTermMemory.
    """

    def __init__(self, max_turns: int = 20):
        """Initialize short-term memory with a maximum turn history size.

        Args:
            max_turns: Maximum number of conversation turns to retain per user.
        """
        self.max_turns = max_turns
        # Turn history per user: dict[str, deque[Message]]
        self._turns: dict[str, deque[Message]] = {}
        # Scratch space per user: dict[str, dict[str, str]]
        self._scratch: dict[str, dict[str, str]] = {}

    async def get(self, user_id: str, key: str) -> str | None:
        """Implements the MemoryStore-shaped get; for short-term memory
        this can look up a simple key/value scratch space per user,
        separate from the turn history (e.g. 'current_topic')."""
        if user_id not in self._scratch:
            return None
        return self._scratch[user_id].get(key)

    async def put(self, user_id: str, key: str, value: str) -> None:
        """Companion to get() above — simple per-user key/value scratch space."""
        if user_id not in self._scratch:
            self._scratch[user_id] = {}
        self._scratch[user_id][key] = value

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        """Naive substring search over the per-user key/value scratch space
        (not over turn history — turn history has its own accessor below)."""
        if user_id not in self._scratch:
            return []

        query_lower = query.lower()
        matches: list[MemoryItem] = []

        for key, value in self._scratch[user_id].items():
            if query_lower in value.lower():
                matches.append(MemoryItem(key=key, value=value))
                if len(matches) >= limit:
                    break

        return matches

    async def append_turn(self, user_id: str, role: str, content: str) -> None:
        """Append one turn (role, content) to the user's turn deque,
        capped at max_turns (oldest evicted automatically)."""
        if user_id not in self._turns:
            self._turns[user_id] = deque(maxlen=self.max_turns)

        message = Message(role=role, content=content)
        self._turns[user_id].append(message)

    async def recent_turns(self, user_id: str, limit: int = 10) -> list[Message]:
        """Return up to `limit` most recent turns for user_id, in
        chronological order (oldest of the returned subset first,
        most recent last) — NOT reverse-chronological."""
        if user_id not in self._turns:
            return []

        turns = list(self._turns[user_id])
        # Return the last `limit` turns in chronological order
        recent = turns[-limit:] if limit < len(turns) else turns
        return list(recent)  # Return as list, already in chronological order
