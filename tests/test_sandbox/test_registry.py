"""Tests for SandboxBackendRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ua.config.settings import Settings
from ua.sandbox.base import SandboxManager
from ua.sandbox.registry import SandboxBackendRegistry, SandboxUnavailableError
from ua.tools.base import ToolResult
from ua.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Mock backend for testing
# ---------------------------------------------------------------------------


def _make_mock_backend(name: str, available: bool = True) -> MagicMock:
    """Create a mock SandboxManager backend."""
    mock = MagicMock(spec=SandboxManager)
    mock.backend_name = name
    mock.is_available = AsyncMock(return_value=available)
    mock.execute = AsyncMock(return_value=(0, "output", ""))
    mock.write_file = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Tests for requires_user_context security mechanism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_id_from_llm_is_overridden_by_trusted_value():
    """CRITICAL: LLM-supplied _user_id is ALWAYS overridden by trusted value.

    This is the security property: a tool call cannot spoof which user_id
    it's acting as.
    """
    registry = ToolRegistry()
    # A mock tool that echoes back the _user_id it received
    mock_tool = MagicMock()
    mock_tool.name = "test_tool"
    mock_tool.description = "Test tool"
    mock_tool.parameters = {}
    mock_tool.requires_user_context = True
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="ok"))
    registry.register_instance(mock_tool)

    # Execute with trusted user_id="actual_user", but LLM tries to inject _user_id="spoofed"
    result = await registry.execute(
        "test_tool",
        user_id="actual_user",
        _user_id="spoofed",  # LLM tries to inject this
    )

    assert result.success is True
    # Verify that the tool received "actual_user", not "spoofed"
    # The pop happens before injection, so _user_id should be the trusted value
    mock_tool.run.assert_called_once()
    call_kwargs = mock_tool.run.call_args[1]
    assert call_kwargs.get("_user_id") == "actual_user"


@pytest.mark.asyncio
async def test_user_id_passed_when_tool_requires_context():
    """Verify user_id is passed to tools that have requires_user_context=True."""
    registry = ToolRegistry()
    mock_tool = MagicMock()
    mock_tool.name = "test_context_tool"
    mock_tool.description = "Test tool needing context"
    mock_tool.parameters = {}
    mock_tool.requires_user_context = True
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="ok"))
    registry.register_instance(mock_tool)

    await registry.execute("test_context_tool", user_id="user123", other_arg="value")

    mock_tool.run.assert_called_once()
    call_kwargs = mock_tool.run.call_args[1]
    assert call_kwargs.get("_user_id") == "user123"
    assert call_kwargs.get("other_arg") == "value"


@pytest.mark.asyncio
async def test_user_id_not_passed_when_tool_does_not_require_context():
    """Verify user_id is NOT passed to tools without requires_user_context."""
    registry = ToolRegistry()
    mock_tool = MagicMock()
    mock_tool.name = "test_no_context_tool"
    mock_tool.description = "Test tool not needing context"
    mock_tool.parameters = {}
    mock_tool.requires_user_context = False  # default
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="ok"))
    registry.register_instance(mock_tool)

    await registry.execute("test_no_context_tool", user_id="user123")

    mock_tool.run.assert_called_once()
    call_kwargs = mock_tool.run.call_args[1]
    assert "_user_id" not in call_kwargs


# ---------------------------------------------------------------------------
# Tests for resolve() - backend selection and fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_returns_stored_preference_when_available():
    """resolve() returns the stored backend when it's available."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=True)
    mock_docker = _make_mock_backend("docker", available=True)

    # Mock memory that returns "docker" as stored preference
    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value="docker")

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    result = await registry.resolve("user1")

    assert result is mock_docker
    # Docker is_available should be checked
    mock_docker.is_available.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_returns_default_when_no_stored_preference():
    """resolve() returns the default backend when user has no stored preference."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=True)
    mock_docker = _make_mock_backend("docker", available=True)

    # Mock memory that returns None (no preference stored)
    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    result = await registry.resolve("user1")

    assert result is mock_ssh


@pytest.mark.asyncio
async def test_resolve_falls_back_when_preferred_unavailable():
    """resolve() falls back through sandbox_fallback_order when preferred is unavailable."""
    settings = Settings()
    # SSH is unavailable (user's choice), Docker is available
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value="ssh")

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    result = await registry.resolve("user1")

    # Should return Docker (the first available in fallback order after SSH fails)
    assert result is mock_docker


@pytest.mark.asyncio
async def test_resolve_skips_failed_backend_in_fallback():
    """resolve() skips the failed backend in fallback order."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value="ssh")

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    await registry.resolve("user1")

    # Both backends should be checked for availability
    mock_ssh.is_available.assert_called_once()
    mock_docker.is_available.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_raises_sandbox_unavailable_when_all_unavailable():
    """resolve() raises SandboxUnavailableError when no backend is available."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=False)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value="ssh")

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    with pytest.raises(SandboxUnavailableError) as exc_info:
        await registry.resolve("user1")

    assert "No sandbox backend available" in str(exc_info.value)
    assert "ssh" in str(exc_info.value)
    assert "docker" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests for fallback not persisting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_does_not_persist():
    """resolve() does NOT persist fallback as the new preference.

    This is critical: when the original backend comes back online,
    resolve() should go back to using it.
    """
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value="ssh")  # User prefers SSH
    mock_memory.remember_fact = AsyncMock()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    result = await registry.resolve("user1")

    # Should return Docker (fallback)
    assert result is mock_docker
    # Should NOT have persisted the fallback as new preference
    mock_memory.remember_fact.assert_not_called()


@pytest.mark.asyncio
async def test_still_tries_original_preference_after_fallback():
    """After a fallback, a subsequent resolve() still tries the original first."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value="ssh")
    mock_memory.remember_fact = AsyncMock()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    # First call: SSH unavailable, fallback to Docker
    result1 = await registry.resolve("user1")
    assert result1 is mock_docker

    # Now SSH comes back online
    mock_ssh.is_available = AsyncMock(return_value=True)

    # Second call: should return SSH again (original preference)
    result2 = await registry.resolve("user1")
    assert result2 is mock_ssh


# ---------------------------------------------------------------------------
# Tests for set_active_backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_active_backend_rejects_unregistered_backend():
    """set_active_backend raises ValueError for unregistered backend names."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=True)

    mock_memory = MagicMock()
    mock_memory.remember_fact = AsyncMock()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh},
        memory=mock_memory,
        settings=settings,
    )

    with pytest.raises(ValueError) as exc_info:
        await registry.set_active_backend("user1", "nonexistent")

    assert "Unknown sandbox backend" in str(exc_info.value)


@pytest.mark.asyncio
async def test_set_active_backend_validates_and_persists():
    """set_active_backend validates the backend and persists via remember_fact."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=True)
    mock_docker = _make_mock_backend("docker", available=False)

    mock_memory = MagicMock()
    mock_memory.remember_fact = AsyncMock()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    # Should succeed even though Docker is unavailable
    await registry.set_active_backend("user1", "docker")

    mock_memory.remember_fact.assert_called_once_with(
        "user1", "active_sandbox_backend", "docker"
    )


def test_registered_backends_returns_all_backend_names():
    """registered_backends() returns list of all registered backend names."""
    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=True)
    mock_docker = _make_mock_backend("docker", available=True)

    mock_memory = MagicMock()

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    backends = registry.registered_backends()

    assert set(backends) == {"ssh", "docker"}


# ---------------------------------------------------------------------------
# Tests for single-backend equivalence (backward compatibility)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_backend_registry_behaves_like_original():
    """Single-backend registry works like the old SSH-only behavior."""
    settings = Settings(sandbox_default_backend="ssh")
    mock_ssh = _make_mock_backend("ssh", available=True)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh},
        memory=mock_memory,
        settings=settings,
    )

    result = await registry.resolve("user1")

    # Should return SSH (the only backend)
    assert result is mock_ssh


# ---------------------------------------------------------------------------
# Manual test script (with real MemoryManager) - if feasible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_active_backend_persists_to_real_memory_manager(tmp_path):
    """MANUAL TEST: Verify set_active_backend + resolve round-trips via real MemoryManager.

    This test uses real database/engine to prove persistence genuinely works,
    not just that remember_fact was called.
    """
    # Use a temp database
    db_path = tmp_path / "test.db"
    settings = Settings(database_url=f"sqlite+aiosqlite:///{db_path}")

    # Create real memory components
    from ua.database.engine import init_db
    await init_db()

    from ua.database.engine import get_session_factory
    session_factory = get_session_factory()

    from ua.memory.short_term import ShortTermMemory
    from ua.memory.long_term import LongTermMemory
    from ua.memory.knowledge import KnowledgeMemory
    from ua.memory.manager import MemoryManager

    short_term = ShortTermMemory()
    long_term = LongTermMemory(session_factory=session_factory)
    knowledge = KnowledgeMemory(session_factory=session_factory)
    memory_manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        knowledge=knowledge,
    )

    mock_ssh = _make_mock_backend("ssh", available=True)
    mock_docker = _make_mock_backend("docker", available=True)

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=memory_manager,
        settings=settings,
    )

    # Set docker as active backend for user1
    await registry.set_active_backend("user1", "docker")

    # Verify resolve returns Docker
    result = await registry.resolve("user1")
    assert result is mock_docker

    # Verify the stored fact is actually docker
    stored = await memory_manager.get_fact("user1", "active_sandbox_backend")
    assert stored == "docker"

    # Clean up the temp db
    db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Regression tests: Tools fail gracefully when no backend available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_execute_tool_fails_gracefully_when_no_backend_available():
    """Regression test: SandboxExecuteTool.run() returns graceful failure when no backend available."""
    from ua.tools.sandbox_execute import SandboxExecuteTool

    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=False)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    tool = SandboxExecuteTool(backend_registry=registry)
    result = await tool.run(project_id="test", command="ls")

    assert result.success is False
    assert "unavailable" in result.error.lower()


@pytest.mark.asyncio
async def test_sandbox_write_file_tool_fails_gracefully_when_no_backend_available():
    """Regression test: SandboxWriteFileTool.run() returns graceful failure when no backend available."""
    from ua.tools.sandbox_write_file import SandboxWriteFileTool

    settings = Settings()
    mock_ssh = _make_mock_backend("ssh", available=False)
    mock_docker = _make_mock_backend("docker", available=False)

    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=None)

    registry = SandboxBackendRegistry(
        backends={"ssh": mock_ssh, "docker": mock_docker},
        memory=mock_memory,
        settings=settings,
    )

    tool = SandboxWriteFileTool(backend_registry=registry)
    result = await tool.run(project_id="test", relative_path="test.txt", content="hello")

    assert result.success is False
    assert "unavailable" in result.error.lower()
