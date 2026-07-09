from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ua.database.models import Fact
from ua.memory.base import MemoryItem


class LongTermMemory:
    """
    SQLite-backed durable memory for user facts/preferences.

    NOTE: `search()` currently does a naive substring (LIKE) match over
    Fact.value. This is intentionally simple for v1. When vector-based
    memory is introduced later, this class can be replaced with a new
    implementation behind the same MemoryStore interface — no caller
    needs to change.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, user_id: str, key: str) -> str | None:
        """Return the most recent value for (user_id, key), or None."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Fact)
                .where(Fact.user_id == user_id, Fact.key == key)
                .order_by(Fact.created_at.desc())
                .limit(1)
            )
            fact = result.scalar_one_or_none()
            return fact.value if fact else None

    async def put(self, user_id: str, key: str, value: str) -> None:
        """Upsert a fact: update existing row for (user_id, key) or insert new."""
        async with self._session_factory() as session:
            # Check for existing row
            result = await session.execute(
                select(Fact).where(Fact.user_id == user_id, Fact.key == key)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.value = value
            else:
                fact = Fact(user_id=user_id, key=key, value=value)
                session.add(fact)

            await session.commit()

    async def search(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[MemoryItem]:
        """Case-insensitive substring search over Fact.value for a user."""
        pattern = f"%{query.lower()}%"
        async with self._session_factory() as session:
            result = await session.execute(
                select(Fact)
                .where(
                    Fact.user_id == user_id,
                    func.lower(Fact.value).like(pattern),
                )
                .order_by(Fact.created_at.desc())
                .limit(limit)
            )
            facts = result.scalars().all()
            return [MemoryItem(key=fact.key, value=fact.value) for fact in facts]
