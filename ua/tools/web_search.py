"""Web search tool for Unified Agent.

DISCLAIMER AND LEGAL CAVEAT:
===========================
This tool uses DuckDuckGoHTMLBackend by default, which scrapes DuckDuckGo's
HTML-only search endpoint (https://html.duckduckgo.com/html/).

This approach has important tradeoffs:

1. FRAGILITY: This scrapes a third-party service, not an official, stable API.
   The HTML structure can change without notice, breaking the scraper silently.
   This is inherently fragile and may stop working at any time.

2. LEGAL GRAY AREA: Scraping may be against DuckDuckGo's Terms of Service
   depending on your jurisdiction and use pattern. We are not lawyers and cannot
   provide legal advice. You must review DuckDuckGo's Terms of Service yourself
   and decide whether this approach is acceptable for your use case. The
   maintainers of this project make no claims about ToS compliance.

RECOMMENDATION: For production use, implement a SearchBackend that uses an
official API from a search provider and inject it via the backend parameter.
"""

from __future__ import annotations

import json

from ua.tools.base import Tool, ToolResult
from ua.web.search_backend import DuckDuckGoHTMLBackend, SearchBackend


class WebSearchTool(Tool):
    """Search the web for information using a pluggable search backend.

    This tool takes a query string and returns a list of search results
    (title, url, snippet). By default, it uses DuckDuckGoHTMLBackend which
    scrapes DuckDuckGo's HTML-only endpoint without requiring an API key.

    DISCLAIMER AND LEGAL CAVEAT:
    ===========================
    This tool's default backend scrapes a third-party service, not an official,
    stable API. The HTML structure can change without notice, breaking the
    scraper silently. This is inherently fragile and may stop working at any
    time. Additionally, scraping may be against DuckDuckGo's Terms of Service
    depending on jurisdiction and use. We are not lawyers and cannot provide
    legal advice. Review DuckDuckGo's ToS yourself. This is a tradeoff:
    zero-config convenience vs. reliability and legal clarity. For production use,
    implement and inject a proper API-based SearchBackend.
    """

    name = "web_search"
    description = (
        "Search the web for information. Returns a list of results with title, URL, and "
        "snippet. Uses DuckDuckGo HTML scraping by default (no API key needed). "
        "DISCLAIMER: The default backend scrapes a third-party service and may be fragile "
        "or violate ToS. For production, inject a proper API-based backend. "
        "Use max_results (default 5, max 10) to limit results."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5, max 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        backend: SearchBackend | None = None,
    ) -> None:
        """Initialize the web search tool.

        Args:
            backend: Optional SearchBackend implementation. If None, uses DuckDuckGoHTMLBackend.

        DISCLAIMER AND LEGAL CAVEAT:
        ===========================
        This tool's default backend scrapes a third-party service, not an official,
        stable API. The HTML structure can change without notice, breaking the
        scraper silently. This is inherently fragile and may stop working at any
        time. Additionally, scraping may be against DuckDuckGo's Terms of Service
        depending on jurisdiction and use. We are not lawyers and cannot provide
        legal advice. Review DuckDuckGo's ToS yourself.
        """
        self._backend = backend
        # Store the backend type for tests to verify injection
        self._backend_type = type(backend).__name__ if backend else "DuckDuckGoHTMLBackend"

    async def run(self, query: str, max_results: int = 5) -> ToolResult:
        """Search the web for the given query.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return (hard-capped at 10).

        Returns:
            ToolResult with success=True and JSON-formatted results, or
            success=False with an error message.
        """
        # Hard cap max_results at 10
        max_results = min(max_results, 10)

        # Use injected backend if provided, otherwise create default
        if self._backend is not None:
            backend = self._backend
        else:
            backend = DuckDuckGoHTMLBackend()

        results = await backend.search(query, max_results)

        if not results:
            return ToolResult(
                success=True,
                output="",
                error=(
                    "No search results returned. Note: this could indicate either genuinely "
                    "no results for the query, OR the scraper's parsing logic may have "
                    "silently broken due to changes in DuckDuckGo's HTML structure. "
                    "The two cases are indistinguishable without inspecting the raw response."
                ),
            )

        # Format results as JSON
        results_json = json.dumps(
            [
                {"title": r.title, "url": r.url, "snippet": r.snippet}
                for r in results
            ],
            indent=2,
        )

        return ToolResult(success=True, output=results_json)
