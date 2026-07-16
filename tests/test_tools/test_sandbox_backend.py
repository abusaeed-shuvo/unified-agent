"""Tests for SandboxBackendTool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ua.config.settings import Settings
from ua.sandbox.base import SandboxManager
from ua.sandbox.registry import SandboxBackendRegistry
from ua.tools.sandbox_backend import SandboxBackendTool


def _make_mock_backend(name: str, available: bool = True) -> MagicMock:
    """Create a mock SandboxManager backend."""
    mock = MagicMock(spec=SandboxManager)
    mock.backend_name = name
    mock.is_available = AsyncMock(return_value=available)
    mock.execute = AsyncMock(return_value=(0, "output", ""))
    mock.write_file = AsyncMock()
    return mock


def _make_mock_registry(
    backends: list[str],
    stored_preference: str | None = None,
    available_map: dict[str, bool] | None = None,
) -> tuple[SandboxBackendRegistry, dict]:
    """Create a mock registry for testing.

    Args:
        backends: List of backend names to register.
        stored_preference: What get_fact should return for stored preference.
        available_map: Map of backend_name to availability status.
    """
    mock_memory = MagicMock()
    mock_memory.get_fact = AsyncMock(return_value=stored_preference)
    mock_memory.remember_fact = AsyncMock()

    settings = Settings()

    backend_map = {}
    for name in backends:
        if available_map and name in available_map:
            backend_map[name] = _make_mock_backend(name, available_map[name])
        else:
            backend_map[name] = _make_mock_backend(name, True)

    registry = SandboxBackendRegistry(
        backends=backend_map,
        memory=mock_memory,
        settings=settings,
    )
    return registry, backend_map


# ---------------------------------------------------------------------------
# Tests for action='list'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_backends_shows_all_registered_backends():
    """action='list' returns all registered backends with availability status."""
    registry, backend_map = _make_mock_registry(["ssh", "docker"], available_map={"ssh": True, "docker": False})
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="list", _user_id="user1")

    assert result.success is True
    assert "ssh: online" in result.output
    assert "docker: offline" in result.output


@pytest.mark.asyncio
async def test_list_backends_marks_active_backend():
    """action='list' shows which backend is currently active for the user."""
    registry, backend_map = _make_mock_registry(
        ["ssh", "docker"],
        stored_preference="docker",
        available_map={"ssh": True, "docker": True},
    )
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="list", _user_id="user1")

    assert result.success is True
    assert "ssh: online" in result.output
    assert "docker: online (active)" in result.output


@pytest.mark.asyncio
async def test_list_backends_marks_default_as_active_when_no_preference():
    """action='list' marks the default backend as active when no user preference exists."""
    registry, backend_map = _make_mock_registry(
        ["ssh", "docker"],
        stored_preference=None,
        available_map={"ssh": True, "docker": True},
    )
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="list", _user_id="user1")

    assert result.success is True
    # Default backend is "ssh" per Settings
    assert "ssh: online (active)" in result.output


@pytest.mark.asyncio
async def test_list_backends_checks_availability_concurrently():
    """action='list' checks availability on all backends concurrently, not sequentially.

    This test verifies that is_available() calls happen in parallel by measuring
    timing. If sequential, total time would be sum of delays; if concurrent,
    total time should be close to max delay.
    """
    import asyncio
    import time

    registry, backend_map = _make_mock_registry(["ssh", "docker"])
    tool = SandboxBackendTool(backend_registry=registry)

    async def slow_is_available_ssh() -> bool:
        start_time = time.time()
        await asyncio.sleep(0.1)
        call_times["ssh"].append(start_time)
        return True

    async def slow_is_available_docker() -> bool:
        start_time = time.time()
        await asyncio.sleep(0.1)
        call_times["docker"].append(start_time)
        return True

    call_times: dict[str, list[float]] = {"ssh": [], "docker": []}
    backend_map["ssh"].is_available = slow_is_available_ssh
    backend_map["docker"].is_available = slow_is_available_docker

    start = time.time()
    result = await tool.run(action="list", _user_id="user1")
    elapsed = time.time() - start

    # If sequential, would take 0.2s (sum of delays). Concurrent should be ~0.1s.
    # Allow some margin for overhead, but should definitely be under 0.15s.
    assert elapsed < 0.15, f"Calls took {elapsed}s, expected < 0.15s for concurrent execution"
    assert result.success is True


@pytest.mark.asyncio
async def test_list_backends_uses_stored_preference_not_fallback():
    """action='list' shows stored preference, not what resolve() would return via fallback."""
    registry, backend_map = _make_mock_registry(
        ["ssh", "docker"],
        stored_preference="ssh",
        available_map={"ssh": False, "docker": True},  # SSH is offline
    )
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="list", _user_id="user1")

    # Even though SSH is offline (would fallback to docker via resolve()),
    # the tool should still show SSH as active per stored preference
    assert "ssh: offline (active)" in result.output


# ---------------------------------------------------------------------------
# Tests for action='switch'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_backend_to_valid_backend():
    """action='switch' to a valid backend persists and reports success."""
    registry, backend_map = _make_mock_registry(
        ["ssh", "docker"],
        available_map={"ssh": True, "docker": True},
    )
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="switch", backend_name="docker", _user_id="user1")

    assert result.success is True
    assert "Switched active sandbox backend to 'docker'" in result.output
    # Verify persistence
    registry._memory.remember_fact.assert_called_once_with(
        "user1", "active_sandbox_backend", "docker"
    )


@pytest.mark.asyncio
async def test_switch_backend_to_online_backend_reports_online():
    """action='switch' to an online backend reports it as online."""
    registry, backend_map = _make_mock_registry(
        ["ssh", "docker"],
        available_map={"ssh": True, "docker": True},
    )
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="switch", backend_name="docker", _user_id="user1")

    assert "(online)" in result.output


@pytest.mark.asyncio
async def test_switch_backend_to_offline_backend_reports_offline():
    """action='switch' to an offline backend reports it as offline but still succeeds."""
    registry, backend_map = _make_mock_registry(
        ["ssh", "docker"],
        available_map={"ssh": True, "docker": False},
    )
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="switch", backend_name="docker", _user_id="user1")

    assert result.success is True
    assert "(offline)" in result.output
    assert "currently unavailable" in result.output


@pytest.mark.asyncio
async def test_switch_backend_to_unregistered_returns_error():
    """action='switch' to an unregistered backend returns ToolResult(success=False) with valid options."""
    registry, backend_map = _make_mock_registry(["ssh"])
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="switch", backend_name="nonexistent", _user_id="user1")

    assert result.success is False
    assert "Unknown sandbox backend" in result.error
    assert "Valid options" in result.error
    assert "ssh" in result.error


@pytest.mark.asyncio
async def test_switch_backend_requires_backend_name():
    """action='switch' without backend_name returns an error."""
    registry, backend_map = _make_mock_registry(["ssh"])
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="switch", _user_id="user1")

    assert result.success is False
    assert "backend_name is required" in result.error


# ---------------------------------------------------------------------------
# Tests for persistence round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_persists_and_list_shows_changed_backend():
    """action='switch' followed by action='list' shows the changed backend as active."""
    # Create a proper mock memory that tracks state changes
    mock_memory = MagicMock()
    stored_preference = "ssh"  # Start with ssh as stored preference
    mock_memory.get_fact = AsyncMock(return_value=stored_preference)
    mock_memory.remember_fact = AsyncMock(side_effect=lambda uid, fact, val: setattr(mock_memory.get_fact, "return_value", val))

    settings = Settings()
    backend_map = {
        "ssh": _make_mock_backend("ssh", True),
        "docker": _make_mock_backend("docker", True),
    }

    registry = SandboxBackendRegistry(
        backends=backend_map,
        memory=mock_memory,
        settings=settings,
    )
    tool = SandboxBackendTool(backend_registry=registry)

    # Switch to docker
    await tool.run(action="switch", backend_name="docker", _user_id="user1")

    # List should now show docker as active
    result = await tool.run(action="list", _user_id="user1")

    assert result.success is True
    assert "docker: online (active)" in result.output


# ---------------------------------------------------------------------------
# Tests for requires_user_context security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_uses_trusted_user_id():
    """action='switch' uses the trusted _user_id, not an LLM-supplied user_id.

    The ToolRegistry.execute strips any LLM-supplied user_id, so by the time
    the tool runs, _user_id should be the trusted value.
    """
    registry, backend_map = _make_mock_registry(["ssh", "docker"])
    tool = SandboxBackendTool(backend_registry=registry)

    # The tool receives _user_id which is trusted
    result = await tool.run(action="switch", backend_name="docker", _user_id="trusted_user")

    assert result.success is True
    registry._memory.remember_fact.assert_called_once_with(
        "trusted_user", "active_sandbox_backend", "docker"
    )


# ---------------------------------------------------------------------------
# Tests for unknown action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_action_returns_error():
    """action with unknown value returns an error."""
    registry, backend_map = _make_mock_registry(["ssh"])
    tool = SandboxBackendTool(backend_registry=registry)

    result = await tool.run(action="unknown", _user_id="user1")

    assert result.success is False
    assert "Unknown action" in result.error
    assert "Use 'list' or 'switch'" in result.error