"""ModelManager — single entrypoint for LLM provider selection."""

import asyncio
import time

from ua.config.logging import get_logger
from ua.config.settings import Settings, get_settings
from ua.models.base import LLMAdapter, LLMAdapterError, LLMResponse, Message
from ua.models.fake_adapter import FakeAdapter
from ua.models.lmstudio_adapter import LMStudioAdapter
from ua.models.ollama_adapter import OllamaAdapter
from ua.models.openai_compat_adapter import OpenAICompatAdapter

logger = get_logger(__name__)


class ModelManager:
    """
    Single entrypoint for LLM provider selection and delegation.

    All higher-level components (ContextBuilder, ConversationManager,
    UnifiedAgent, etc.) must use this class rather than importing
    individual adapters directly.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """
        Initialise the ModelManager with the appropriate adapter.

        Parameters
        ----------
        settings:
            Configuration object.  Defaults to :func:`get_settings()` when
            ``None`` so that environment variables and ``.env`` files are
            honoured automatically.

        Raises
        ------
        ValueError
            If *settings.llm_provider* is not one of the recognised values.
        """
        self._settings = settings or get_settings()
        provider = self._settings.llm_provider

        if provider == "fake":
            self._adapter: LLMAdapter = FakeAdapter()
        elif provider == "lmstudio":
            self._adapter = LMStudioAdapter(
                base_url=self._settings.llm_base_url,
                model=self._settings.llm_model,
            )
        elif provider == "ollama":
            self._adapter = OllamaAdapter(
                base_url=self._settings.llm_base_url,
                model=self._settings.llm_model,
            )
        elif provider == "openai_compat":
            self._adapter = OpenAICompatAdapter(
                base_url=self._settings.llm_base_url,
                model=self._settings.llm_model,
            )
        else:
            # This branch should be unreachable in practice because
            # Settings.llm_provider is a Literal type, but we keep it as
            # a defensive guard in case Settings is bypassed.
            raise ValueError(
                f"Unrecognised LLM provider: {provider!r}. "
                f"Valid values are: 'fake', 'lmstudio', 'ollama', 'openai_compat'."
            )

    @property
    def _adapter_instance(self) -> LLMAdapter:
        """Access the underlying adapter (primarily for testing)."""
        return self._adapter

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Delegate to the configured adapter's generate method with retry logic.

        Retries on LLMAdapterError (transient failures) using linear backoff.
        Total attempts = llm_max_retries + 1 (e.g., max_retries=2 means 3 total attempts).
        """
        max_retries = self._settings.llm_max_retries
        backoff_seconds = self._settings.llm_retry_backoff_seconds

        for attempt in range(max_retries + 1):
            attempt_num = attempt + 1
            start = time.monotonic()
            try:
                result = await self._adapter.generate(messages, tools=tools, **kwargs)
            except LLMAdapterError as e:
                duration_ms = (time.monotonic() - start) * 1000
                if attempt == max_retries:
                    # Final attempt failed, propagate the error
                    logger.info(
                        f"LLM generate() call failed in {duration_ms:.1f}ms "
                        f"(attempt {attempt_num})"
                    )
                    raise
                # Log the duration of the failed attempt, then the retry warning.
                logger.info(
                    f"LLM generate() call failed in {duration_ms:.1f}ms "
                    f"(attempt {attempt_num})"
                )
                logger.warning(
                    f"LLM adapter error on attempt {attempt_num}, retrying: {e}"
                )
                # Linear backoff: backoff_seconds * (attempt + 1)
                # attempt is 0-indexed, so we use (attempt + 1) for backoff multiplier
                await asyncio.sleep(backoff_seconds * (attempt + 1))
            else:
                # Successful attempt: log its duration and return.
                duration_ms = (time.monotonic() - start) * 1000
                logger.info(
                    f"LLM generate() call completed in {duration_ms:.1f}ms "
                    f"(attempt {attempt_num})"
                )
                return result
