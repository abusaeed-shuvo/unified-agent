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
    max_tool_call_rounds: int = 3
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5

    # Sandbox SSH connection settings
    # These are optional and unset by default. If not configured, sandbox tools
    # will fail closed (return error without attempting connections).
    sandbox_host: str | None = None
    """Hostname or IP address of the SSH sandbox server. If None, sandbox tools
    are disabled.

    SECURITY WARNING: The SSH connection uses known_hosts=None, which accepts
    any host key and is vulnerable to MITM attacks. This is intentional for
    sandbox use where the host is disposable and operated by the user, but
    should only be enabled with a trusted, isolated sandbox host.
    """
    sandbox_port: int = 22
    """SSH port for the sandbox server (default 22)."""
    sandbox_username: str | None = None
    """SSH username for authentication to the sandbox server."""
    sandbox_key_path: str | None = None
    """Path to an SSH private key file for authentication (NOT raw key material)."""

    # Docker sandbox settings
    sandbox_docker_image: str = "python:3.12-slim"
    """Base image for new sandbox containers."""
    sandbox_docker_memory_limit: str = "512m"
    """Memory limit for sandbox containers (e.g., '512m', '1g')."""
    sandbox_docker_cpu_limit: str = "1.0"
    """CPU limit for sandbox containers (e.g., '0.5', '1.0', '2.0')."""
    sandbox_docker_binary: str = "docker"
    """Path to docker binary, allows override for testing / non-standard install paths."""

    model_config = SettingsConfigDict(env_prefix="UA_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()