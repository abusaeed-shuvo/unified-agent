"""Tests for WebSearchTool."""

from __future__ import annotations

import json

import pytest

from ua.tools.base import ToolResult
from ua.tools.registry import ToolRegistry
from ua.tools.web_search import WebSearchTool
from ua.web.search_backend import SearchBackend, SearchResult

# ---------------------------------------------------------------------------
# Mock backend for testing
# ---------------------------------------------------------------------------


class MockSearchBackend(SearchBackend):
    """Mock search backend for testing purposes."""

    def __init__(self, results: list[SearchResult] | None = None, fail: bool = False):
        self._results = results or []
        self._fail = fail

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return mock results or raise error."""
        if self._fail:
            return []
        return self._results[:max_results]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_tool_success_via_mocked_backend():
    """WebSearchTool returns successful results with mocked backend."""
    mock_results = [
        SearchResult(title="Result 1", url="https://example.com/1", snippet="Snippet 1"),
        SearchResult(title="Result 2", url="https://example.com/2", snippet="Snippet 2"),
    ]
    backend = MockSearchBackend(results=mock_results)
    tool = WebSearchTool(backend=backend)

    result = await tool.run(query="test query", max_results=5)

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.error is None

    # Parse output as JSON
    parsed = json.loads(result.output)
    assert len(parsed) == 2
    assert parsed[0]["title"] == "Result 1"
    assert parsed[0]["url"] == "https://example.com/1"
    assert parsed[0]["snippet"] == "Snippet 1"


@pytest.mark.asyncio
async def test_web_search_tool_handles_backend_failure_gracefully():
    """WebSearchTool handles empty results gracefully."""
    backend = MockSearchBackend(results=[], fail=True)
    tool = WebSearchTool(backend=backend)

    result = await tool.run(query="test query")

    # Success is True (no exception raised), but has error message about ambiguity
    assert result.success is True
    assert result.output == ""
    assert "no results" in result.error.lower() or "indistinguishable" in result.error.lower()


@pytest.mark.asyncio
async def test_web_search_tool_zero_results_message_acknowledges_ambiguity():
    """Zero results returns ToolResult with ambiguity acknowledgment."""
    backend = MockSearchBackend(results=[])
    tool = WebSearchTool(backend=backend)

    result = await tool.run(query="nonexistent")

    assert result.success is True  # Not an error, just empty results
    assert result.output == ""
    # The error message should acknowledge ambiguity
    assert "indistinguishable" in result.error.lower() or "silently broken" in result.error.lower()


@pytest.mark.asyncio
async def test_web_search_tool_max_results_hard_cap_enforced():
    """max_results parameter is hard-capped at 10."""
    mock_results = [
        SearchResult(title=f"Result {i}", url=f"https://example.com/{i}", snippet=f"Snippet {i}")
        for i in range(1, 20)  # 19 mock results
    ]
    backend = MockSearchBackend(results=mock_results)
    tool = WebSearchTool(backend=backend)

    # Request 100 results
    result = await tool.run(query="test", max_results=100)

    parsed = json.loads(result.output)
    # Should be capped at 10 (or less if mock doesn't have 10)
    assert len(parsed) == 10


def test_web_search_tool_auto_discovered_by_registry():
    """WebSearchTool is auto-discovered by ToolRegistry.discover()."""
    registry = ToolRegistry()
    registry.discover()

    assert "web_search" in registry._tools
    assert isinstance(registry.get("web_search"), WebSearchTool)


def test_web_search_tool_scraping_caveat_in_module_docstring():
    """The module docstring contains the scraping/ToS caveat."""
    import ua.tools.web_search as web_search_module

    docstring = web_search_module.__doc__
    assert docstring is not None
    # Check for key phrases
    assert "FRAGILITY" in docstring or "fragile" in docstring.lower()
    assert "Terms of Service" in docstring or "ToS" in docstring


def test_web_search_tool_scraping_caveat_in_class_docstring():
    """The WebSearchTool class docstring contains the scraping/ToS caveat."""
    assert WebSearchTool.__doc__ is not None
    docstring = WebSearchTool.__doc__
    # Check for key phrases
    assert "FRAGILITY" in docstring or "fragile" in docstring.lower()
    assert "Terms of Service" in docstring or "ToS" in docstring


def test_web_search_tool_scraping_caveat_in_description_field():
    """The tool's description field contains the scraping/ToS caveat."""
    assert WebSearchTool.description is not None
    # Check for key phrases in description
    desc_lower = WebSearchTool.description.lower()
    assert "scrapes" in desc_lower or "scrape" in desc_lower
    assert "fragile" in desc_lower or "ToS" in WebSearchTool.description


@pytest.mark.asyncio
async def test_web_search_tool_uses_injected_backend_when_provided():
    """WebSearchTool uses injected backend instead of default."""
    custom_backend = MockSearchBackend(results=[
        SearchResult(title="Custom", url="https://custom.com", snippet="Custom result"),
    ])
    tool = WebSearchTool(backend=custom_backend)

    # Verify the backend type is recorded
    assert tool._backend_type == "MockSearchBackend"

    result = await tool.run(query="test", max_results=5)

    # Should get the custom backend's result, not DuckDuckGo
    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Custom"
    assert parsed[0]["url"] == "https://custom.com"
