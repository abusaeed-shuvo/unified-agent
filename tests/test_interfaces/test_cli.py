"""Tests for the CLI interface."""

from __future__ import annotations

from unittest.mock import MagicMock

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

    # Mock build_default_agent to avoid real initialization
    monkeypatch.setattr(
        "ua.interfaces.cli.main.build_default_agent",
        lambda: MagicMock(),
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
        lambda: mock_agent,
    )
    monkeypatch.setattr("ua.interfaces.cli.main.configure_logging", lambda: None)

    # Run the CLI
    run()

    # Verify the call was made with correct platform
    assert len(calls_made) == 1
    assert calls_made[0]["platform"] == "cli"
    assert calls_made[0]["message"] == "Test message"
