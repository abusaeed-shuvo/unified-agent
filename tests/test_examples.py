"""Tests for runnable example scripts.

Each test subprocess-runs an example script and asserts exit code 0.
The examples set their own UA_LLM_PROVIDER=fake and UA_DATABASE_URL in-script,
making them self-contained with no external service requirements.
"""

import subprocess


def _run_example(script_path: str) -> subprocess.CompletedProcess:
    """Helper to run an example script as a subprocess.

    Uses uv run python for reliability since the examples directory is not
    a proper Python package (it only has __init__.py for potential future use).

    Args:
        script_path: Path to the example script relative to repo root.

    Returns:
        CompletedProcess with stdout, stderr, and returncode.
    """
    result = subprocess.run(
        ["uv", "run", "python", script_path],
        capture_output=True,
        text=True,
    )
    return result


class TestExamples:
    """Tests that each example script runs successfully."""

    def test_minimal_cli_chat_example_runs_successfully(self) -> None:
        """minimal_cli_chat.py runs to completion with exit code 0."""
        result = _run_example("examples/minimal_cli_chat.py")

        assert result.returncode == 0, (
            f"Example failed with returncode {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_custom_tool_example_runs_successfully(self) -> None:
        """custom_tool_example.py runs to completion with exit code 0."""
        result = _run_example("examples/custom_tool_example.py")

        assert result.returncode == 0, (
            f"Example failed with returncode {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_switch_personality_example_runs_successfully(self) -> None:
        """switch_personality.py runs to completion with exit code 0."""
        result = _run_example("examples/switch_personality.py")

        assert result.returncode == 0, (
            f"Example failed with returncode {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
