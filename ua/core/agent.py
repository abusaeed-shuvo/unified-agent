"""UnifiedAgent — the single public entrypoint for the full chat pipeline.

Orchestrates: ConversationManager → ContextBuilder → ModelManager →
(optional single round of tool execution via ToolRegistry) →
ConversationManager again → return final text.
"""

from __future__ import annotations

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

    async def chat(self, user_id: str, platform: str, message: str) -> str:
        """Process a user message through the full chat pipeline.

        Steps:
        1. context = await conversation.handle_incoming(user_id, platform, message)
        2. messages = context_builder.build(personality_name, context, message)
        3. response = await model_manager.generate(messages, tools=...)
        4. IF response.tool_calls is non-empty:
             - Execute each tool call (catching ToolNotFoundError per call).
             - Append tool results as tool-role messages.
             - Call model_manager.generate() AGAIN (one follow-up round).
             - Use the SECOND response's .content as the final text.
           ELSE:
             - Use the FIRST response's .content as the final text.
        5. await conversation.handle_outgoing(user_id, platform, final_text)
        6. return final_text

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

        # Step 4: First LLM call
        first_response = await self._model_manager.generate(
            messages, tools=tool_schemas
        )

        # Step 5: Handle tool calls if present
        if first_response.tool_calls:
            # Execute each tool call and append results
            for tc in first_response.tool_calls:
                tool_result = await self._execute_tool_safely(tc)
                messages.append(
                    Message(
                        role="tool",
                        content=tool_result,
                        tool_call_id=tc.id,
                    )
                )

            # One follow-up round with tool results included
            second_response = await self._model_manager.generate(
                messages, tools=tool_schemas
            )
            final_text = second_response.content
        else:
            final_text = first_response.content

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
