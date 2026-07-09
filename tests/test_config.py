import pytest
from pydantic import ValidationError

from ua.config.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults():
    s = get_settings()
    assert s.llm_provider == "fake"
    assert s.log_level == "INFO"
    assert s.tools_allow_destructive is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("UA_LLM_PROVIDER", "ollama")
    s = get_settings()
    assert s.llm_provider == "ollama"


def test_invalid_provider_raises(monkeypatch):
    monkeypatch.setenv("UA_LLM_PROVIDER", "invalid_provider")
    with pytest.raises(ValidationError):
        get_settings()
