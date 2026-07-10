"""ContextBuilder for assembling LLM message lists from personality and memory."""

from __future__ import annotations

from ua.memory.manager import RetrievedContext
from ua.models.base import Message
from ua.personality.loader import PersonalityLoader
from ua.personality.schema import Personality


class ContextBuilder:
    """Assembles the final list[Message] sent to the LLM.

    Combines a loaded Personality, RetrievedContext from MemoryManager,
    and the new incoming user message into a properly ordered message list.
    """

    def __init__(self, personality_loader: PersonalityLoader) -> None:
        """Initialize with a PersonalityLoader instance.

        Args:
            personality_loader: Loader instance for fetching personality data.
        """
        self.personality_loader = personality_loader

    def build(
        self,
        personality_name: str,
        context: RetrievedContext,
        new_user_message: str,
    ) -> list[Message]:
        """Build the complete message list for the LLM.

        Args:
            personality_name: Name of the personality to load.
            context: Retrieved context from MemoryManager containing recent_turns,
                    relevant_facts, and relevant_knowledge.
            new_user_message: The new user message to append.

        Returns:
            Ordered list of Message objects: system message first, then recent_turns,
            then the new user message.
        """
        # Step 1: Load the personality
        personality: Personality = self.personality_loader.load(personality_name)

        # Step 2: Build the system message
        system_content = f"{personality.system_prompt}\n\n{personality.style}"

        # Add "Known context" section only if there are facts or knowledge
        if context.relevant_facts or context.relevant_knowledge:
            context_lines = ["Known context:"]

            if context.relevant_facts:
                context_lines.append("Relevant facts:")
                for item in context.relevant_facts:
                    context_lines.append(f"- {item.key}: {item.value}")

            if context.relevant_knowledge:
                context_lines.append("Relevant knowledge:")
                for item in context.relevant_knowledge:
                    context_lines.append(f"- {item.key}: {item.value}")

            system_content += "\n\n" + "\n".join(context_lines)

        system_message = Message(role="system", content=system_content)

        # Step 3: Build the message list (do not mutate context.recent_turns)
        messages: list[Message] = [system_message]
        messages.extend(context.recent_turns)

        # Step 4: Append the new user message
        messages.append(Message(role="user", content=new_user_message))

        # Note: Token limit enforcement (personality.rules.max_response_tokens)
        # happens elsewhere (e.g., ModelManager kwargs) in a later batch.

        return messages
