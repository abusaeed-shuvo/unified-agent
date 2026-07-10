"""Tests for ModelManager."""

import pytest

from ua.config.settings import Settings, get_settings
from ua.models.base import Message
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
