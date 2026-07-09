"""Tests for personality schema and loader."""

import json
from pathlib import Path

import pytest

from ua.personality.loader import PersonalityLoader, PersonalityLoadError
from ua.personality.schema import Personality, PersonalityRules

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def loader() -> PersonalityLoader:
    """Default loader pointing at the real personalities/ directory."""
    return PersonalityLoader()


@pytest.fixture
def tmp_personality_dir(tmp_path: Path) -> Path:
    """Create a minimal valid personality directory under tmp_path."""
    base = tmp_path / "personalities"
    pdir = base / "test_persona"
    pdir.mkdir(parents=True)
    (pdir / "system.md").write_text("You are a test assistant.", encoding="utf-8")
    (pdir / "style.md").write_text("Be concise.", encoding="utf-8")
    (pdir / "rules.json").write_text(
        json.dumps({"allow_tools": [], "max_response_tokens": 512, "forbidden_topics": []}),
        encoding="utf-8",
    )
    (pdir / "greetings.txt").write_text("Hello!\nHi there!\n", encoding="utf-8")
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPersonalityLoader:
    """Tests for PersonalityLoader.load()."""

    def test_load_assistant_personality_success(self, loader: PersonalityLoader) -> None:
        """Loading the real 'assistant' personality returns a valid Personality."""
        personality = loader.load("assistant")
        assert isinstance(personality, Personality)
        assert personality.name == "assistant"
        assert personality.system_prompt
        assert personality.style
        assert isinstance(personality.rules, PersonalityRules)
        assert len(personality.greetings) > 0

    def test_load_assistant_has_expected_rules_values(
        self, loader: PersonalityLoader
    ) -> None:
        """The assistant personality's rules match the values in rules.json."""
        personality = loader.load("assistant")
        assert "calculator" in personality.rules.allow_tools
        assert personality.rules.max_response_tokens == 800
        assert personality.rules.forbidden_topics == []

    def test_missing_personality_raises_with_name_in_message(
        self, loader: PersonalityLoader
    ) -> None:
        """Loading a nonexistent personality raises PersonalityLoadError."""
        with pytest.raises(PersonalityLoadError) as exc_info:
            loader.load("does_not_exist")
        assert "does_not_exist" in str(exc_info.value)

    def test_malformed_rules_json_raises_personality_load_error(
        self, tmp_personality_dir: Path
    ) -> None:
        """A rules.json with invalid types raises PersonalityLoadError, not
        a raw pydantic ValidationError."""
        pdir = tmp_personality_dir / "test_persona"
        # Write rules.json with max_response_tokens as a string (invalid)
        (pdir / "rules.json").write_text(
            json.dumps(
                {"allow_tools": [], "max_response_tokens": "not_an_int", "forbidden_topics": []}
            ),
            encoding="utf-8",
        )
        loader = PersonalityLoader(base_dir=tmp_personality_dir)
        with pytest.raises(PersonalityLoadError) as exc_info:
            loader.load("test_persona")
        assert "test_persona" in str(exc_info.value)

    def test_greetings_blank_lines_skipped(self, tmp_path: Path) -> None:
        """Blank lines in greetings.txt are excluded from the greetings list."""
        base = tmp_path / "personalities"
        pdir = base / "greeting_test"
        pdir.mkdir(parents=True)
        (pdir / "system.md").write_text("System prompt.", encoding="utf-8")
        (pdir / "style.md").write_text("Style guide.", encoding="utf-8")
        (pdir / "rules.json").write_text(
            json.dumps({"allow_tools": [], "max_response_tokens": 1024, "forbidden_topics": []}),
            encoding="utf-8",
        )
        # Include blank lines
        (pdir / "greetings.txt").write_text(
            "Hello!\n\n\nHi there!\n\nGreetings!\n", encoding="utf-8"
        )
        loader = PersonalityLoader(base_dir=base)
        personality = loader.load("greeting_test")
        assert personality.greetings == ["Hello!", "Hi there!", "Greetings!"]
