from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ua.database.models import KnowledgeDocument
from ua.memory.base import MemoryItem


class KnowledgeMemory:
    """
    Durable store for uploaded knowledge documents (plain text).

    NOTE: search() currently does a naive case-insensitive substring
    match over KnowledgeDocument.content, exactly like LongTermMemory
    (Batch 05). This is intentionally simple for v1 — see Architecture.md §6.
    When vector-based memory is introduced, this class can be replaced
    behind the same MemoryStore-shaped interface with no caller changes.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add_document(self, user_id: str, title: str, content: str) -> str:
        """Insert a new KnowledgeDocument row, return its generated id."""
        async with self._session_factory() as session:
            doc = KnowledgeDocument(user_id=user_id, title=title, content=content)
            session.add(doc)
            await session.commit()
            await session.refresh(doc)
            return doc.id

    async def get(self, user_id: str, key: str) -> str | None:
        """key here is a document id; return its content, or None if
        not found / not owned by user_id."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id == key,
                    KnowledgeDocument.user_id == user_id,
                )
            )
            doc = result.scalar_one_or_none()
            return doc.content if doc else None

    async def put(self, user_id: str, key: str, value: str) -> None:
        """MemoryStore-shape compatibility method. For KnowledgeMemory,
        treat this as equivalent to add_document(user_id, title=key,
        content=value) — document titles double as the 'key' here.

        Note: This mapping is an interface impedance mismatch. The MemoryStore
        protocol's put() method is designed for key-value storage where keys are
        unique identifiers. KnowledgeMemory uses document IDs as keys for get(),
        but for put() we map the key to the document title. This means:
        - put() always creates a NEW document (no upsert behavior)
        - Multiple put() calls with the same key will create multiple documents
          with the same title
        - The key/title is not unique, unlike typical key-value semantics

        This is acceptable for v1 since the primary use case is add_document()
        for explicit document management, with put() as a compatibility shim.
        """
        async with self._session_factory() as session:
            doc = KnowledgeDocument(user_id=user_id, title=key, content=value)
            session.add(doc)
            await session.commit()

    async def search(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[MemoryItem]:
        """Case-insensitive substring match over content, scoped to
        user_id, ordered most-recent-first, capped at limit. Return
        MemoryItem(key=doc.title, value=doc.content) for each match."""
        pattern = f"%{query.lower()}%"
        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.user_id == user_id,
                    func.lower(KnowledgeDocument.content).like(pattern),
                )
                .order_by(KnowledgeDocument.created_at.desc())
                .limit(limit)
            )
            docs = result.scalars().all()
            return [MemoryItem(key=doc.title, value=doc.content) for doc in docs]
