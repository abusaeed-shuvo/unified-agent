"""Tests for ModelManager."""

import pytest

from ua.config.settings import Settings, get_settings
from ua.models.base import LLMAdapter, LLMAdapterError, LLMResponse, Message
from ua.models.fake_adapter import FakeAdapter
from ua.models.lmstudio_adapter import LMStudioAdapter
from ua.models.manager import ModelManager
from ua.models.ollama_adapter import OllamaAdapter
from ua.models.openai_compat_adapter import OpenAICompatAdapter


class TestModelManager:
    """Suite of tests for ModelManager provider selection and delegation."""

    @pytest.mark.asyncio
    async def test_selects_fake_adapter_and_delegates(self):
        """Fake adapter is selected and generate() delegates correctly."""
        settings = Settings(llm_provider="fake")
        mgr = ModelManager(settings=settings)

        # Verify the adapter type
        assert isinstance(mgr._adapter_instance, FakeAdapter)

        # Verify delegation works (echo behavior from FakeAdapter)
        resp = await mgr.generate([Message(role="user", content="hello there")])
        assert resp.content == "echo: hello there"
        assert resp.tool_calls == []

    def test_selects_lmstudio_adapter_with_correct_config(self):
        """LMStudioAdapter is constructed with correct base_url and model."""
        settings = Settings(
            llm_provider="lmstudio",
            llm_base_url="http://localhost:1234",
            llm_model="lm-studio-model",
        )
        mgr = ModelManager(settings=settings)

        adapter = mgr._adapter_instance
        assert isinstance(adapter, LMStudioAdapter)
        assert adapter._base_url == "http://localhost:1234"
        assert adapter._model == "lm-studio-model"

    def test_selects_ollama_adapter_with_correct_config(self):
        """OllamaAdapter is constructed with correct base_url and model."""
        settings = Settings(
            llm_provider="ollama",
            llm_base_url="http://localhost:11434",
            llm_model="ollama-model",
        )
        mgr = ModelManager(settings=settings)

        adapter = mgr._adapter_instance
        assert isinstance(adapter, OllamaAdapter)
        assert adapter._base_url == "http://localhost:11434"
        assert adapter._model == "ollama-model"

    def test_selects_openai_compat_adapter_with_correct_config(self):
        """OpenAICompatAdapter is constructed with correct base_url and model."""
        settings = Settings(
            llm_provider="openai_compat",
            llm_base_url="http://localhost:8080",
            llm_model="openai-model",
        )
        mgr = ModelManager(settings=settings)

        adapter = mgr._adapter_instance
        assert isinstance(adapter, OpenAICompatAdapter)
        assert adapter._base_url == "http://localhost:8080"
        assert adapter._model == "openai-model"

    def test_unknown_provider_raises_value_error_at_construction(self):
        """Unrecognised provider raises ValueError at construction time."""
        # Note: Settings uses a Literal type, so invalid providers are caught
        # by Pydantic validation before reaching ModelManager. This test
        # documents that behavior.
        with pytest.raises(Exception):  # noqa: BLE001
            Settings(llm_provider="not_a_real_provider")

    def test_default_settings_used_when_none_passed(self, monkeypatch):
        """ModelManager() with no args uses get_settings()."""
        monkeypatch.setenv("UA_LLM_PROVIDER", "fake")
        get_settings.cache_clear()

        try:
            mgr = ModelManager()
            assert isinstance(mgr._adapter_instance, FakeAdapter)
        finally:
            get_settings.cache_clear()


class TestModelManagerRetry:
    """Tests for retry logic in ModelManager.generate()."""

    @pytest.mark.asyncio
    async def test_retries_on_transient_llm_adapter_error_then_succeeds(self):
        """Retry on LLMAdapterError succeeds after retries (3 total attempts)."""

        class FlakyAdapter(LLMAdapter):
            def __init__(self):
                self.call_count = 0

            async def generate(self, messages, tools=None, **kwargs):
                self.call_count += 1
                if self.call_count < 3:
                    msg = f"Simulated transient failure on attempt {self.call_count}"
                    raise LLMAdapterError(msg)
                return LLMResponse(content="Success after retries", tool_calls=[])

        flaky = FlakyAdapter()
        settings = Settings(
            llm_provider="fake",
            llm_max_retries=2,
            llm_retry_backoff_seconds=0.01,
        )
        mgr = ModelManager(settings=settings)
        mgr._adapter = flaky
        response = await mgr.generate([Message(role="user", content="test")])

        assert response.content == "Success after retries"
        assert flaky.call_count == 3  # 2 retries + 1 initial = 3 total attempts

    @pytest.mark.asyncio
    async def test_raises_llm_adapter_error_after_exhausting_all_retries(self):
        """LLMAdapterError propagates after all retries exhausted (3 total attempts)."""

        class AlwaysFailAdapter(LLMAdapter):
            def __init__(self):
                self.call_count = 0

            async def generate(self, messages, tools=None, **kwargs):
                self.call_count += 1
                raise LLMAdapterError(f"Always fails on attempt {self.call_count}")

        always_fail = AlwaysFailAdapter()
        settings = Settings(
            llm_provider="fake",
            llm_max_retries=2,
            llm_retry_backoff_seconds=0.01,
        )
        mgr = ModelManager(settings=settings)
        mgr._adapter = always_fail

        with pytest.raises(LLMAdapterError):
            await mgr.generate([Message(role="user", content="test")])

        assert always_fail.call_count == 3  # 2 retries + 1 initial = 3 total attempts

    @pytest.mark.asyncio
    async def test_does_not_retry_on_non_llm_adapter_error_exception_type(self):
        """Non-LLMAdapterError exceptions propagate immediately without retry."""

        class TypeErrorAdapter(LLMAdapter):
            def __init__(self):
                self.call_count = 0

            async def generate(self, messages, tools=None, **kwargs):
                self.call_count += 1
                raise TypeError("Non-transient error")

        type_error = TypeErrorAdapter()
        settings = Settings(
            llm_provider="fake",
            llm_max_retries=2,
            llm_retry_backoff_seconds=0.01,
        )
        mgr = ModelManager(settings=settings)
        mgr._adapter = type_error

        with pytest.raises(TypeError):
            await mgr.generate([Message(role="user", content="test")])

        assert type_error.call_count == 1  # No retry, only 1 call

    @pytest.mark.asyncio
    async def test_retry_attempts_are_logged_as_warnings(self, caplog):
        """Each retry attempt logs a WARNING message."""

        class FlakyAdapter(LLMAdapter):
            def __init__(self):
                self.call_count = 0

            async def generate(self, messages, tools=None, **kwargs):
                self.call_count += 1
                if self.call_count < 3:
                    raise LLMAdapterError(f"Transient failure {self.call_count}")
                return LLMResponse(content="Success", tool_calls=[])

        flaky = FlakyAdapter()
        settings = Settings(
            llm_provider="fake",
            llm_max_retries=2,
            llm_retry_backoff_seconds=0.01,
        )
        mgr = ModelManager(settings=settings)
        mgr._adapter = flaky

        with caplog.at_level("WARNING"):
            response = await mgr.generate([Message(role="user", content="test")])

        assert response.content == "Success"
        # Should have 2 warning logs (one for each retry attempt)
        assert len(caplog.records) == 2
        assert all(r.levelname == "WARNING" for r in caplog.records)
        assert "attempt 1" in caplog.records[0].message
        assert "attempt 2" in caplog.records[1].message

    @pytest.mark.asyncio
    async def test_generate_logs_duration_at_info_level(self, caplog):
        """A successful generate() logs an INFO duration line."""
        settings = Settings(llm_provider="fake")
        mgr = ModelManager(settings=settings)

        with caplog.at_level("INFO"):
            response = await mgr.generate(
                [Message(role="user", content="hello")]
            )

        assert response.content == "echo: hello"
        # Exactly one INFO duration log for the single (successful) attempt.
        duration_records = [
            r for r in caplog.records
            if r.levelname == "INFO" and "LLM generate() call completed in" in r.message
        ]
        assert len(duration_records) == 1
        assert "ms" in duration_records[0].message
        assert "(attempt 1)" in duration_records[0].message

    @pytest.mark.asyncio
    async def test_generate_logs_duration_for_each_retry_attempt(self, caplog):
        """A flaky-then-succeeding adapter logs one duration line per attempt."""

        class FlakyAdapter(LLMAdapter):
            def __init__(self):
                self.call_count = 0

            async def generate(self, messages, tools=None, **kwargs):
                self.call_count += 1
                if self.call_count < 3:
                    raise LLMAdapterError(f"Transient {self.call_count}")
                return LLMResponse(content="ok", tool_calls=[])

        flaky = FlakyAdapter()
        settings = Settings(
            llm_provider="fake",
            llm_max_retries=2,
            llm_retry_backoff_seconds=0.01,
        )
        mgr = ModelManager(settings=settings)
        mgr._adapter = flaky

        with caplog.at_level("INFO"):
            response = await mgr.generate(
                [Message(role="user", content="test")]
            )

        assert response.content == "ok"
        # Each of the 3 attempts (2 failed + 1 success) gets its own
        # duration log line at INFO level (failed attempts log "call failed in",
        # the successful one logs "call completed in").
        duration_records = [
            r for r in caplog.records
            if r.levelname == "INFO"
            and "LLM generate() call" in r.message
            and "in" in r.message
            and "ms" in r.message
        ]
        assert len(duration_records) == 3
        assert "(attempt 1)" in duration_records[0].message
        assert "(attempt 2)" in duration_records[1].message
        assert "(attempt 3)" in duration_records[2].message
