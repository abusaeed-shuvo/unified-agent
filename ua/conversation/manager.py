"""ConversationManager - session/turn bookkeeping for the Unified Agent."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ua.database.models import Message, User
from ua.database.models import Session as SessionModel
from ua.memory.manager import MemoryManager, RetrievedContext


class ConversationManager:
    """
    Manages conversation sessions and turn bookkeeping.

    This class sits between an Interface and the rest of the Core layer.
    It establishes/looks up sessions and delegates turn-recording to
    MemoryManager, while also writing through to the database for
    durability/audit (distinct from MemoryManager's fast in-memory hot path).

    DESIGN NOTE ON user_id/User ROW LINKAGE:
    The incoming user_id string (from interfaces - e.g., Discord snowflake,
    CLI username, web request user_id) is treated AS the User.id primary key
    directly. We do NOT generate a separate UUID for User.id.

    Rationale:
    - All existing memory layers (ShortTermMemory, LongTermMemory, KnowledgeMemory,
      MemoryManager) already treat user_id as an opaque external string key and
      never generate their own UUIDs.
    - This maintains consistency across the entire memory stack - the same user_id
      string flows through ConversationManager -> MemoryManager -> all memory layers
      without any translation or mapping.
    - The tradeoff is that User.id becomes an external identifier rather than an
      internal UUID, but this is acceptable for v1 and maintains simplicity.
    """

    def __init__(
        self,
        memory: MemoryManager,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Initialize the ConversationManager.

        Args:
            memory: MemoryManager instance for turn recording and context retrieval.
            session_factory: Callable that returns a new AsyncSession for database operations.
        """
        self._memory = memory
        self._session_factory = session_factory

    @property
    def memory(self) -> MemoryManager:
        """Public accessor for the MemoryManager backing this conversation.

        Exposed so collaborators (e.g. UnifiedAgent) can read/write durable
        facts without reaching into the private ``_memory`` attribute.
        """
        return self._memory

    async def get_or_create_session(self, user_id: str, platform: str) -> str:
        """
        Look up an existing Session row for (user_id, platform). If
        none exists, create one (and a User row too, if one doesn't
        already exist for user_id).

        Args:
            user_id: The user identifier (treated as User.id directly).
            platform: The platform identifier (e.g., 'cli', 'discord').

        Returns:
            The session's id (str). Calling this again for the same
            (user_id, platform) returns the SAME session id.
        """
        async with self._session_factory() as session:
            # Ensure User row exists (user_id is used as User.id directly)
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                user = User(id=user_id, platform=platform, platform_user_id=user_id)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            # Look up existing session for (user_id, platform)
            result = await session.execute(
                select(SessionModel).where(
                    SessionModel.user_id == user_id,
                    SessionModel.platform == platform,
                )
            )
            existing_session = result.scalar_one_or_none()

            if existing_session:
                return existing_session.id

            # Create new session
            new_session = SessionModel(user_id=user_id, platform=platform)
            session.add(new_session)
            await session.commit()
            await session.refresh(new_session)

            return new_session.id

    async def handle_incoming(self, user_id: str, platform: str, message: str) -> RetrievedContext:
        """
        Process an incoming user message.

        1. get_or_create_session(user_id, platform).
        2. Retrieve context via self.memory.retrieve_context(user_id, message).
        3. Record the turn via self.memory.record_turn(user_id, "user", message).
        4. Write a durable Message row (role="user") linked to the session.

        Args:
            user_id: The user identifier.
            platform: The platform identifier.
            message: The incoming message content.

        Returns:
            RetrievedContext from memory.retrieve_context().
        """
        # Get or create session (idempotent)
        await self.get_or_create_session(user_id, platform)

        # Retrieve context BEFORE recording the turn, so that recent_turns
        # contains only PRIOR turns (not the current one being processed).
        # This preserves ContextBuilder's contract: recent_turns = history,
        # new_user_message = the turn currently being processed.
        context = await self._memory.retrieve_context(user_id, message)

        # Record turn in short-term memory
        await self._memory.record_turn(user_id, "user", message)

        # Write durable Message row
        async with self._session_factory() as session:
            # Get the current session for this user+platform
            result = await session.execute(
                select(SessionModel).where(
                    SessionModel.user_id == user_id,
                    SessionModel.platform == platform,
                )
            )
            current_session = result.scalar_one_or_none()

            if not current_session:
                # Should not happen if get_or_create_session succeeded, but handle defensively
                raise RuntimeError(
                    f"Session not found for user_id={user_id}, platform={platform}"
                )

            message_row = Message(
                session_id=current_session.id,
                role="user",
                content=message,
            )
            session.add(message_row)
            await session.commit()

        return context

    async def handle_outgoing(self, user_id: str, platform: str, response: str) -> None:
        """
        Process an outgoing assistant response.

        1. Record the assistant turn via self.memory.record_turn(user_id, "assistant", response).
        2. Write a durable Message row (role="assistant") linked to the CURRENT
           session for (user_id, platform).

        Args:
            user_id: The user identifier.
            platform: The platform identifier.
            response: The assistant's response content.
        """
        # Get or create session (idempotent)
        await self.get_or_create_session(user_id, platform)

        # Record turn in short-term memory
        await self._memory.record_turn(user_id, "assistant", response)

        # Write durable Message row
        async with self._session_factory() as session:
            # Get the current session for this user+platform
            result = await session.execute(
                select(SessionModel).where(
                    SessionModel.user_id == user_id,
                    SessionModel.platform == platform,
                )
            )
            current_session = result.scalar_one_or_none()

            if not current_session:
                # Should not happen if get_or_create_session succeeded, but handle defensively
                raise RuntimeError(
                    f"Session not found for user_id={user_id}, platform={platform}"
                )

            message_row = Message(
                session_id=current_session.id,
                role="assistant",
                content=response,
            )
            session.add(message_row)
            await session.commit()
