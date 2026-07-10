"""UnifiedAgent — the single public entrypoint for the full chat pipeline.

Orchestrates: ConversationManager → ContextBuilder → ModelManager →
(optional multiple rounds of tool execution via ToolRegistry) →
ConversationManager again → return final text.
"""

from __future__ import annotations

from ua.config.logging import get_logger
from ua.conversation.context_builder import ContextBuilder
from ua.conversation.manager import ConversationManager
from ua.database.engine import init_db
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
    ) -> None:
        """Initialise the UnifiedAgent.

        Args:
            conversation: ConversationManager for session/turn bookkeeping.
            context_builder: ContextBuilder for assembling LLM message lists.
            model_manager: ModelManager for LLM provider delegation.
            tool_registry: ToolRegistry for tool discovery and execution.
            personality_name: Name of the personality to use (e.g. "assistant").
        """
        self._conversation = conversation
        self._context_builder = context_builder
        self._model_manager = model_manager
        self._tool_registry = tool_registry
        self._personality_name = personality_name
        self._db_initialized = False
        self._logger = get_logger(__name__)

    async def chat(self, user_id: str, platform: str, message: str) -> str:
        """Process a user message through the full chat pipeline.

        Steps:
        1. context = await conversation.handle_incoming(user_id, platform, message)
        2. messages = context_builder.build(personality_name, context, message)
        3. Loop: call model_manager.generate(messages, tools=...) up to
           max_tool_call_rounds times. If response.tool_calls is non-empty,
           execute each tool call and append results, then loop again.
           If tool_calls is empty, use that response's .content as final.
           If max rounds hit while still having tool_calls, use the last
           response's .content (or fallback string) and log a warning.
        4. await conversation.handle_outgoing(user_id, platform, final_text)
        5. return final_text

        Args:
            user_id: The user identifier.
            platform: The platform identifier (e.g. "cli", "discord").
            message: The incoming user message.

        Returns:
            The final assistant response text.
        """
        # Lazy database initialization on first call
        if not self._db_initialized:
            await init_db()
            self._db_initialized = True

        # Step 1: Handle incoming message (session + memory + context retrieval)
        context = await self._conversation.handle_incoming(user_id, platform, message)

        # Step 2: Build the message list for the LLM
        messages = self._context_builder.build(
            self._personality_name, context, message
        )

        # Step 3: Get tool schemas from the registry
        tool_schemas = self._tool_registry.all_schemas()

        # Step 4: Bounded loop for tool calls
        max_rounds = self._model_manager._settings.max_tool_call_rounds
        round_count = 0
        response = None

        while round_count < max_rounds:
            round_count += 1
            response = await self._model_manager.generate(
                messages, tools=tool_schemas
            )

            # If no tool calls, we're done
            if not response.tool_calls:
                break

            # Execute each tool call and append results
            for tc in response.tool_calls:
                tool_result = await self._execute_tool_safely(tc)
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

        # Step 7: Return the final text
        return final_text

    async def _execute_tool_safely(self, tc: ToolCall) -> str:
        """Execute a single tool call, catching ToolNotFoundError.

        Args:
            tc: The ToolCall to execute.

        Returns:
            A human-readable string representation of the tool result.
        """
        try:
            result = await self._tool_registry.execute(tc.name, **tc.arguments)
            # Use output on success, error message on failure
            if result.success:
                return result.output
            return f"Error: {result.error}"
        except ToolNotFoundError as exc:
            return f"Error: {exc}"
