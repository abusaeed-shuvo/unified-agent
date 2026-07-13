"""Factory for wiring up a fully-configured UnifiedAgent from settings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ua.config.settings import get_settings
from ua.conversation.context_builder import ContextBuilder
from ua.conversation.manager import ConversationManager
from ua.core.agent import UnifiedAgent
from ua.database.engine import get_session_factory
from ua.memory.knowledge import KnowledgeMemory
from ua.memory.long_term import LongTermMemory
from ua.memory.manager import MemoryManager
from ua.memory.short_term import ShortTermMemory
from ua.models.manager import ModelManager
from ua.personality.loader import PersonalityLoader
from ua.sandbox.manager import SSHSandboxManager
from ua.tools.registry import ToolRegistry


def build_default_agent(
    confirmation_callback: Callable[[str, str], Awaitable[bool]] | None = None,
) -> UnifiedAgent:
    """Wires up a real UnifiedAgent from get_settings() and real dependencies.

    Constructs:
    - Real ConversationManager (backed by a real database engine/session_factory
      via ua.database.engine)
    - Real MemoryManager (with real ShortTermMemory/LongTermMemory/KnowledgeMemory)
    - Real ContextBuilder (with a real PersonalityLoader)
    - Real ModelManager (which internally picks the adapter per
      settings.llm_provider — including "fake" for testing/dev)
    - ToolRegistry with sandbox tools explicitly registered

    Args:
        confirmation_callback: Optional async callback for confirming risky
                              sandbox commands. If provided (e.g., from CLI),
                              risky commands will prompt for confirmation. If None,
                              risky commands are automatically rejected.

    Returns:
        A fully-wired UnifiedAgent ready for chat() calls.
    """
    settings = get_settings()

    # --- Database ---
    session_factory = get_session_factory()
    # Database tables are created lazily on the first chat() call
    # via UnifiedAgent's lazy initialization.

    # --- Memory layer ---
    short_term = ShortTermMemory()
    long_term = LongTermMemory(session_factory=session_factory)
    knowledge = KnowledgeMemory(session_factory=session_factory)
    memory_manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    # --- Conversation ---
    conversation = ConversationManager(
        memory=memory_manager,
        session_factory=session_factory,
    )

    # --- Context builder ---
    personality_loader = PersonalityLoader()
    context_builder = ContextBuilder(personality_loader=personality_loader)

    # --- Model manager ---
    model_manager = ModelManager(settings=settings)

    # --- Tool registry ---
    tool_registry = ToolRegistry()

    # Always register sandbox tools (they fail closed internally if unconfigured)
    # This is different from FilesystemTool which is skipped due to auto-discovery
    # TypeError - these tools are wired explicitly, not auto-discovered.
    from ua.tools.sandbox_execute import SandboxExecuteTool
    from ua.tools.sandbox_write_file import SandboxWriteFileTool

    sandbox_manager = SSHSandboxManager(settings)
    tool_registry.register_instance(
        SandboxWriteFileTool(sandbox_manager=sandbox_manager)
    )
    tool_registry.register_instance(
        SandboxExecuteTool(
            sandbox_manager=sandbox_manager,
            confirmation_callback=confirmation_callback,
        )
    )

    # Also discover other tools (calculator, etc.)
    tool_registry.discover()

    # --- Assemble ---
    return UnifiedAgent(
        conversation=conversation,
        context_builder=context_builder,
        model_manager=model_manager,
        tool_registry=tool_registry,
        personality_name=settings.active_personality,
        settings=settings,
    )
