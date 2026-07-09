"""Pydantic models for personality data."""

from pydantic import BaseModel


class PersonalityRules(BaseModel):
    """Configuration rules for a personality."""

    allow_tools: list[str] = []
    max_response_tokens: int = 1024
    forbidden_topics: list[str] = []


class Personality(BaseModel):
    """A fully loaded personality with all its content."""

    name: str
    system_prompt: str
    style: str
    rules: PersonalityRules
    greetings: list[str]
