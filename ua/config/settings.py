from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: Literal["lmstudio", "ollama", "openai_compat", "fake"] = "fake"
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "local-model"
    database_url: str = "sqlite+aiosqlite:///./unified_agent.db"
    active_personality: str = "assistant"
    discord_token: str | None = None
    log_level: str = "INFO"
    tools_allow_destructive: bool = False

    model_config = SettingsConfigDict(env_prefix="UA_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
