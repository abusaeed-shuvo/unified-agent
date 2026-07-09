from dataclasses import dataclass
from typing import Protocol


@dataclass
class MemoryItem:
    key: str
    value: str
    score: float = 1.0


class MemoryStore(Protocol):
    async def get(self, user_id: str, key: str) -> str | None: ...
    async def put(self, user_id: str, key: str, value: str) -> None: ...
    async def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]: ...
