"""UnifiedAgent — the single public entrypoint for the full chat pipeline.

Orchestrates: ConversationManager → ContextBuilder → ModelManager →
(optional multiple rounds of tool execution via ToolRegistry) →
ConversationManager again → return final text.
"""

from __future__ import annotations

import time

from ua.config.logging import get_logger
from ua.config.settings import Settings, get_settings
from ua.conversation.context_builder import ContextBuilder
from ua.conversation.manager import ConversationManager
from ua.database.engine import init_db
from ua.memory.manager import MemoryManager
from ua.models.base import Message, ToolCall
from ua.models.manager import ModelManager
from ua.tools.registry import ToolNotFoundError, ToolRegistry


class UnifiedAgent:
    """Single public entrypoint for the full chat pipeline.

    Wires together ConversationManager, ContextBuilder, ModelManager, and
    ToolRegistry into one ``await agent.chat(...)`` call.
    """

    def __init__(
        self,
        conversation: ConversationManager,
        context_builder: ContextBuilder,
        model_manager: ModelManager,
        tool_registry: ToolRegistry,
        personality_name: str,
        settings: Settings | None = None,
    ) -> None:
        """Initialise the UnifiedAgent.

        Args:
            conversation: ConversationManager for session/turn bookkeeping.
            context_builder: ContextBuilder for assembling LLM message lists.
            model_manager: ModelManager for LLM provider delegation.
            tool_registry: ToolRegistry for tool discovery and execution.
            personality_name: Name of the personality to use (e.g. "assistant").
            settings: Optional Settings instance. If not provided, uses get_settings().
        """
        self._conversation = conversation
        self._context_builder = context_builder
        self._model_manager = model_manager
        self._tool_registry = tool_registry
        self._personality_name = personality_name
        self._settings = settings if settings is not None else get_settings()
        # The agent needs a MemoryManager to resolve and persist per-user
        # personality preferences. It reaches it through the public
        # ``memory`` property on ConversationManager rather than touching a
        # private attribute directly.
        self._memory: MemoryManager = conversation.memory
        self._db_initialized = False
        self._logger = get_logger(__name__)

    async def chat(
        self,
        user_id: str,
        platform: str,
        message: str,
        personality_override: str | None = None,
    ) -> str:
        """Process a user message through the full chat pipeline.

        Steps:
        1. Resolve which personality this call uses (see resolution order below).
        2. context = await conversation.handle_incoming(user_id, platform, message)
        3. messages = context_builder.build(resolved_personality, context, message)
        4. Loop: call model_manager.generate(messages, tools=...) up to
           max_tool_call_rounds times. If response.tool_calls is non-empty,
           execute each tool call and append results, then loop again.
           If tool_calls is empty, use that response's .content as final.
           If max rounds hit while still having tool_calls, use the last
           response's .content (or fallback string) and log a warning.
        5. await conversation.handle_outgoing(user_id, platform, final_text)
        6. return final_text

        Personality resolution order (highest to lowest priority):
          1. Explicit ``personality_override`` parameter, if provided (not None).
          2. A previously-stored per-user preference, if one exists — stored via
             ``MemoryManager.remember_fact(user_id, "active_personality", name)``.
          3. This agent's own default ``self._personality_name`` (set at
             construction).

        Round limit resolution order:
          1. The resolved personality's own max_tool_call_rounds, if set (not None).
          2. The global Settings.max_tool_call_rounds fallback.

        Sticky behavior: when ``personality_override`` is provided and used, it
        is ALSO persisted as the new per-user preference via
        ``remember_fact(user_id, "active_personality", personality_override)``
        so subsequent calls (without an override) keep using the newly-chosen
        personality instead of silently reverting to the default.

        Args:
            user_id: The user identifier.
            platform: The platform identifier (e.g. "cli", "discord").
            message: The incoming user message.
            personality_override: Optional personality name to use for this call
                instead of the agent's default or any stored preference.

        Returns:
            The final assistant response text.
        """
        # Lazy database initialization on first call
        if not self._db_initialized:
            await init_db()
            self._db_initialized = True

        # Lifecycle logging: turn start (INFO) — deliberately excludes any
        # sensitive user content (that only appears at DEBUG level).
        self._logger.info(
            f"chat() started for user_id={user_id} platform={platform}"
        )
        chat_start = time.monotonic()

        # Resolve which personality this call uses, in priority order:
        #   1. Explicit personality_override (if not None)
        #   2. Previously-stored per-user preference (if any)
        #   3. Agent's own default personality_name
        stored_preference = await self._memory.get_fact(user_id, "active_personality")
        resolved_personality = (
            personality_override
            if personality_override is not None
            else (stored_preference or self._personality_name)
        )

        # Sticky behavior: an explicit override becomes the new stored preference
        # for this user, so later calls without an override keep using it.
        if personality_override is not None:
            await self._memory.remember_fact(
                user_id, "active_personality", personality_override
            )

        # Step 1: Handle incoming message (session + memory + context retrieval)
        context = await self._conversation.handle_incoming(user_id, platform, message)

        # Step 2: Build the message list for the LLM
        messages = self._context_builder.build(
            resolved_personality, context, message
        )

        # Resolve the effective round budget: personality override > global default
        max_rounds = self._settings.max_tool_call_rounds
        try:
            # Load the personality's rules to check for override
            personality_rules = self._context_builder.personality_loader.load(
                resolved_personality
            ).rules
            if personality_rules.max_tool_call_rounds is not None:
                max_rounds = personality_rules.max_tool_call_rounds
        except Exception as exc:
            # Fail gracefully: if personality loading fails, fall back to global default
            self._logger.warning(
                f"Failed to load personality '{resolved_personality}' for "
                f"max_tool_call_rounds resolution: {exc}. Using global default."
            )

        # Step 3: Get tool schemas from the registry
        tool_schemas = self._tool_registry.all_schemas()

        # Step 4: Bounded loop for tool calls
        round_count = 0
        response = None

        while round_count < max_rounds:
            round_count += 1
            self._logger.info(f"tool call round {round_count} of {max_rounds}")

            # DEBUG-only: full message payload (may contain sensitive user content).
            self._logger.debug(
                f"Sending {len(messages)} message(s) to LLM: {messages}"
            )

            gen_start = time.monotonic()
            response = await self._model_manager.generate(
                messages, tools=tool_schemas
            )
            gen_duration_ms = (time.monotonic() - gen_start) * 1000
            self._logger.info(
                f"LLM generate() call completed in {gen_duration_ms:.1f}ms "
                f"(round {round_count})"
            )

            # If no tool calls, we're done
            if not response.tool_calls:
                break

            # Execute each tool call and append results
            for tc in response.tool_calls:
                self._logger.info(
                    f"tool call round {round_count}: executing tool '{tc.name}'"
                )
                # DEBUG-only: full tool call arguments (may be sensitive).
                self._logger.debug(f"tool '{tc.name}' arguments: {tc.arguments}")
                tool_result = await self._execute_tool_safely(tc, user_id)
                # DEBUG-only: full tool result content (may be sensitive).
                self._logger.debug(f"tool '{tc.name}' result: {tool_result}")
                messages.append(
                    Message(
                        role="tool",
                        content=tool_result,
                        tool_call_id=tc.id,
                    )
                )

        # Step 5: Handle round limit hit with tool_calls still pending
        if response.tool_calls:
            # Model still wants tools but we hit the limit
            self._logger.warning(
                f"Tool call round limit ({max_rounds}) reached; "
                f"model still has {len(response.tool_calls)} pending tool call(s). "
                f"Returning last response content or fallback."
            )
            final_text = response.content or "I wasn't able to complete that request."
        else:
            final_text = response.content

        # Step 6: Handle outgoing (record assistant turn)
        await self._conversation.handle_outgoing(user_id, platform, final_text)

        # Lifecycle logging: turn completion (INFO) with total duration.
        total_duration_ms = (time.monotonic() - chat_start) * 1000
        self._logger.info(f"chat() completed in {total_duration_ms:.1f}ms")

        # Step 7: Return the final text
        return final_text

    async def _execute_tool_safely(self, tc: ToolCall, user_id: str) -> str:
        """Execute a single tool call, catching ToolNotFoundError.

        Args:
            tc: The ToolCall to execute.
            user_id: The trusted user identifier to pass to tools that need it.

        Returns:
            A human-readable string representation of the tool result.
        """
        try:
            result = await self._tool_registry.execute(tc.name, user_id=user_id, **tc.arguments)
            # Use output on success, error message on failure
            if result.success:
                return result.output
            return f"Error: {result.error}"
        except ToolNotFoundError as exc:
            return f"Error: {exc}"