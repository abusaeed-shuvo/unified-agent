"""Loader for data-driven personality content."""

from __future__ import annotations

import json
from pathlib import Path

from ua.personality.schema import Personality, PersonalityRules


class PersonalityLoadError(Exception):
    """Raised when a personality directory is missing or malformed."""

    pass


class PersonalityLoader:
    """Loads a personality from disk, returning a validated Personality object.

    The default base directory is derived from this file's location:
    ``ua/personality/loader.py`` → repo root → ``personalities/``.
    This assumes ``ua/personality/loader.py`` is always two levels below
    the repository root.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            # Derive repo root: ua/personality/loader.py -> ua/personality/ ->
            # ua/ -> repo root -> personalities/
            self.base_dir = (
                Path(__file__).resolve().parent.parent.parent / "personalities"
            )
        else:
            self.base_dir = base_dir

    def load(self, name: str) -> Personality:
        """Read personalities/<name>/ and return a validated Personality.

        Raises PersonalityLoadError if the directory or any required file
        is missing, or if rules.json fails schema validation.
        """
        personality_dir = self.base_dir / name

        if not personality_dir.is_dir():
            raise PersonalityLoadError(
                f"Personality directory not found: {name}"
            )

        try:
            system_prompt = (personality_dir / "system.md").read_text(
                encoding="utf-8"
            ).strip()
        except FileNotFoundError as exc:
            raise PersonalityLoadError(
                f"Missing system.md for personality: {name}"
            ) from exc

        try:
            style = (personality_dir / "style.md").read_text(
                encoding="utf-8"
            ).strip()
        except FileNotFoundError as exc:
            raise PersonalityLoadError(
                f"Missing style.md for personality: {name}"
            ) from exc

        try:
            rules_raw = json.loads(
                (personality_dir / "rules.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise PersonalityLoadError(
                f"Missing rules.json for personality: {name}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise PersonalityLoadError(
                f"Invalid JSON in rules.json for personality: {name} — {exc}"
            ) from exc

        try:
            rules = PersonalityRules(**rules_raw)
        except Exception as exc:
            # Catch pydantic ValidationError and any other schema mismatch.
            from pydantic import ValidationError

            if isinstance(exc, ValidationError):
                raise PersonalityLoadError(
                    f"Schema validation failed for personality: {name} — {exc}"
                ) from exc
            raise

        try:
            greetings_raw = (personality_dir / "greetings.txt").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as exc:
            raise PersonalityLoadError(
                f"Missing greetings.txt for personality: {name}"
            ) from exc

        greetings = [
            line.strip()
            for line in greetings_raw.splitlines()
            if line.strip()
        ]

        return Personality(
            name=name,
            system_prompt=system_prompt,
            style=style,
            rules=rules,
            greetings=greetings,
        )
