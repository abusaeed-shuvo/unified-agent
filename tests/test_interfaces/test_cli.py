"""Tests for the CLI interface."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Test: EOF handling
# ---------------------------------------------------------------------------


def test_run_handles_eof_gracefully(monkeypatch):
    """run() should handle EOFError gracefully and exit cleanly."""
    from ua.interfaces.cli.main import run

    # Mock asyncio.to_thread to raise EOFError immediately
    async def mock_to_thread(func, prompt):
        raise EOFError()

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

    # Mock build_default_agent to accept confirmation_callback parameter
    monkeypatch.setattr(
        "ua.interfaces.cli.main.build_default_agent",
        lambda confirmation_callback=None: MagicMock(),
    )

    # Mock configure_logging to avoid side effects
    monkeypatch.setattr("ua.interfaces.cli.main.configure_logging", lambda: None)

    # Should not raise, should exit cleanly
    run()


# ---------------------------------------------------------------------------
# Test: Import restrictions
# ---------------------------------------------------------------------------


def test_cli_imports_only_through_factory_and_logging():
    """CLI file should only import from ua.core.factory and ua.config.logging."""
    import pathlib

    cli_path = pathlib.Path(__file__).parent.parent.parent / "ua" / "interfaces" / "cli" / "main.py"
    source = cli_path.read_text()

    # Check for disallowed imports
    disallowed_imports = [
        "ua.memory",
        "ua.models",
        "ua.tools",
        "ua.personality",
    ]

    for disallowed in disallowed_imports:
        # Check for "from ua.memory" or "import ua.memory" style imports
        assert f"from {disallowed}" not in source, (
            f"CLI should not import from {disallowed} directly"
        )
        assert f"import {disallowed}" not in source, (
            f"CLI should not import {disallowed} directly"
        )


# ---------------------------------------------------------------------------
# Test: Correct platform parameter
# ---------------------------------------------------------------------------


def test_cli_calls_agent_chat_with_correct_platform(monkeypatch):
    """run() should call agent.chat with platform='cli'."""
    from ua.interfaces.cli.main import run

    # Track calls to agent.chat
    calls_made = []

    async def mock_chat(user_id, platform, message):
        calls_made.append({"user_id": user_id, "platform": platform, "message": message})
        return f"echo: {message}"

    mock_agent = MagicMock()
    mock_agent.chat = mock_chat

    # Mock asyncio.to_thread to return a test input then EOF
    input_count = [0]

    async def mock_to_thread(func, prompt):
        input_count[0] += 1
        if input_count[0] == 1:
            return "Test message"
        raise EOFError()

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)
    monkeypatch.setattr(
        "ua.interfaces.cli.main.build_default_agent",
        lambda confirmation_callback=None: mock_agent,
    )
    monkeypatch.setattr("ua.interfaces.cli.main.configure_logging", lambda: None)

    # Run the CLI
    run()

    # Verify the call was made with correct platform
    assert len(calls_made) == 1
    assert calls_made[0]["platform"] == "cli"
    assert calls_made[0]["message"] == "Test message"


# ---------------------------------------------------------------------------
# Batch 35 Tests: Confirmation callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_run_constructs_real_confirmation_callback(monkeypatch):
    """The CLI builds a real confirmation callback that prompts and parses y/n correctly."""
    from ua.interfaces.cli.main import _prompt_confirmation

    # Mock asyncio.to_thread to simulate user input
    async def mock_to_thread(func, prompt):
        # Return "y" to simulate user confirming
        return "y"

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

    # Test the callback directly
    result = await _prompt_confirmation("rm -rf /tmp/test", "rm -rf pattern detected")

    # With "y" input, should return True
    assert result is True


@pytest.mark.asyncio
async def test_cli_confirmation_callback_parses_yes(monkeypatch):
    """The callback accepts 'yes' as confirmation."""
    from ua.interfaces.cli.main import _prompt_confirmation

    async def mock_to_thread(func, prompt):
        return "yes"

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)
    result = await _prompt_confirmation("rm -rf /tmp/test", "risk reason")
    assert result is True


@pytest.mark.asyncio
async def test_cli_confirmation_callback_rejects_no_input(monkeypatch):
    """The callback treats 'no' or empty input as denial."""
    from ua.interfaces.cli.main import _prompt_confirmation

    async def mock_to_thread(func, prompt):
        return "no"

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)
    result = await _prompt_confirmation("rm -rf /tmp/test", "risk reason")
    assert result is False


@pytest.mark.asyncio
async def test_cli_confirmation_callback_rejects_empty_input(monkeypatch):
    """The callback treats empty input as denial (fail-closed)."""
    from ua.interfaces.cli.main import _prompt_confirmation

    async def mock_to_thread(func, prompt):
        return ""

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)
    result = await _prompt_confirmation("rm -rf /tmp/test", "risk reason")
    assert result is False


@pytest.mark.asyncio
async def test_cli_confirmation_callback_raises_exception_returns_false(monkeypatch):
    """The callback returns False if input() raises an exception."""
    from ua.interfaces.cli.main import _prompt_confirmation

    async def mock_to_thread(func, prompt):
        raise EOFError("Input failed")

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)
    result = await _prompt_confirmation("rm -rf /tmp/test", "risk reason")
    assert result is False


def test_cli_build_default_agent_called_with_callback(monkeypatch):
    """The CLI's run() passes a confirmation_callback to build_default_agent."""
    from ua.interfaces.cli.main import run

    captured_callback = []

    def mock_build_agent(confirmation_callback=None):
        captured_callback.append(confirmation_callback)
        agent = MagicMock()
        agent.chat = AsyncMockChat()
        return agent

    call_count = [0]

    async def mock_to_thread(func, prompt):
        call_count[0] += 1
        if call_count[0] == 1:
            return "hello"
        raise EOFError()

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)
    monkeypatch.setattr(
        "ua.interfaces.cli.main.build_default_agent",
        mock_build_agent,
    )
    monkeypatch.setattr("ua.interfaces.cli.main.configure_logging", lambda: None)

    run()

    # The callback should have been provided
    assert len(captured_callback) == 1
    assert captured_callback[0] is not None
    assert callable(captured_callback[0])


class AsyncMockChat:
    """Helper class to mock async chat method."""

    async def __call__(self, user_id, platform, message):
        return "response"
