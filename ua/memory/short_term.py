"""In-process, ephemeral short-term memory implementation."""

from collections import deque
from typing import Callable

from ua.memory.base import MemoryItem
from ua.models.base import Message


class ShortTermMemory:
    """
    In-process, ephemeral short-term memory. NOT persisted to disk —
    data is lost on process restart. This is intentional; see
    Architecture.md §6. Durable memory belongs in LongTermMemory.
    """

    def __init__(
        self,
        max_turns: int = 20,
        on_evict: Callable[[str, Message], None] | None = None,
    ):
        """Initialize short-term memory with a maximum turn history size.

        Args:
            max_turns: Maximum number of conversation turns to retain per user.
            on_evict: Optional callback invoked when a turn is evicted.
                Receives (user_id, evicted_message) as arguments.
                The callback is sync (not async) to allow both sync and async
                callers to use it.
        """
        self.max_turns = max_turns
        self._on_evict = on_evict
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

    def set_on_evict(self, callback: Callable[[str, Message], None]) -> None:
        """Set or replace the eviction callback.

        This allows external code (like MemoryManager) to register a callback
        after construction, without directly accessing the private _on_evict attribute.

        Args:
            callback: A sync callable that receives (user_id, evicted_message).
        """
        self._on_evict = callback

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
        capped at max_turns (oldest evicted automatically).

        Eviction detection approach: We check if the deque is already at
        maxlen BEFORE appending. If so, the oldest message (deque[0]) will
        be evicted when we append. We capture it and invoke the on_evict
        callback before the append happens, ensuring the evicted message is
        not lost.
        """
        if user_id not in self._turns:
            self._turns[user_id] = deque(maxlen=self.max_turns)

        # Check if we're at capacity BEFORE appending - this is the key
        # to capturing the evicted message before it's gone
        if len(self._turns[user_id]) == self.max_turns:
            # The next append will evict deque[0], capture it now
            evicted = self._turns[user_id][0]
            if self._on_evict is not None:
                self._on_evict(user_id, evicted)

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
