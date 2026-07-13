"""Search backend abstraction and DuckDuckGo HTML scraper implementation.

DISCLAIMER AND LEGAL CAVEAT:
===========================
This module provides a DuckDuckGoHTMLBackend that scrapes DuckDuckGo's HTML-only
search endpoint (https://html.duckduckgo.com/html/). This approach has important
tradeoffs that you MUST understand:

1. FRAGILITY: This scrapes a third-party service, not an official, stable API.
   The HTML structure can change without notice, breaking the scraper silently.
   This is inherently fragile and may stop working at any time.

2. LEGAL GRAY AREA: Scraping may be against DuckDuckGo's Terms of Service
   depending on your jurisdiction and use pattern. We are not lawyers and cannot
   provide legal advice. You must review DuckDuckGo's Terms of Service yourself
   and decide whether this approach is acceptable for your use case. The
   maintainers of this project make no claims about ToS compliance.

RECOMMENDATION: For production use, obtain an official API key from a search
provider (such as DuckDuckGo's official API, Google Custom Search, etc.) and
implement a proper SearchBackend subclass that uses that API. The architecture
here is designed to allow swapping in a real API-based backend without changing
the WebSearchTool code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Sequence

import httpx

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single search result with title, URL, and snippet.

    Attributes:
        title: The page title extracted from the search result.
        url: The URL of the search result page.
        snippet: A brief description/snippet from the search result.
    """

    title: str
    url: str
    snippet: str


# ---------------------------------------------------------------------------
# Abstract backend interface
# ---------------------------------------------------------------------------


class SearchBackend(ABC):
    """Abstract interface for search backend implementations.

    This mirrors the LLMAdapter pattern: an abstract interface with swappable
    concrete implementations. A real API-key-based backend can be added later
    without touching WebSearchTool itself.
    """

    @abstractmethod
    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Search for the given query and return up to max_results.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return.

        Returns:
            A list of SearchResult objects (may be empty on error or no results).
        """
        ...


# ---------------------------------------------------------------------------
# DuckDuckGo HTML scraper implementation
# ---------------------------------------------------------------------------


class DuckDuckGoHTMLParser(HTMLParser):
    """Parse DuckDuckGo HTML search results into SearchResult objects.

    This parser extracts results from DuckDuckGo's HTML response format.
    It looks for result links in <a class="result__a"> tags and snippets
    in <a class="result__snippet"> tags within the same result block.

    Note: This parsing logic is FRAGILE and depends on DuckDuckGo's exact
    HTML structure. Changes to their page format will break this parser.
    """

    def __init__(self) -> None:
        super().__init__()
        self._results: list[SearchResult] = []
        # Track nesting level of ALL divs within result__body
        self._div_depth: int = 0
        # Track if we're in a result__body div
        self._in_result_body: bool = False
        # Track partial result being built
        self._current_title: str = ""
        self._current_url: str = ""
        self._current_snippet: str = ""
        self._in_title_link: bool = False
        self._in_snippet_link: bool = False

    def handle_starttag(self, tag: str, attrs: Sequence[tuple[str, str | None]]) -> None:
        """Handle opening tags to detect result links and snippets."""
        attrs_dict = dict(attrs)

        if tag == "div":
            class_val = attrs_dict.get("class", "")
            if self._in_result_body:
                # Already in result__body, count this nested div
                self._div_depth += 1
            elif "result__body" in class_val:
                # Entering a result__body div
                self._in_result_body = True
                self._div_depth = 0
                # Reset tracking for new result
                self._current_title = ""
                self._current_url = ""
                self._current_snippet = ""

        elif tag == "a" and self._in_result_body:
            class_val = attrs_dict.get("class", "")
            if class_val == "result__a":
                self._in_title_link = True
                self._current_url = attrs_dict.get("href", "")
            elif class_val == "result__snippet":
                self._in_snippet_link = True
                # Snippet has same URL as the result
                if not self._current_url:
                    self._current_url = attrs_dict.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        """Handle closing tags to finalize result data."""
        if tag == "a":
            if self._in_title_link:
                self._in_title_link = False
            elif self._in_snippet_link:
                self._in_snippet_link = False
        elif tag == "div" and self._in_result_body:
            if self._div_depth > 0:
                # Still in nested divs
                self._div_depth -= 1
            else:
                # Exiting the result__body div
                self._in_result_body = False
                # End of result body - commit if we have title and URL
                if self._current_title and self._current_url:
                    self._results.append(
                        SearchResult(
                            title=self._current_title.strip(),
                            url=self._current_url,
                            snippet=self._current_snippet.strip(),
                        )
                    )
                # Reset for next result
                self._current_title = ""
                self._current_url = ""
                self._current_snippet = ""

    def handle_data(self, data: str) -> None:
        """Extract title and snippet text from within tags."""
        if self._in_title_link:
            self._current_title += data
        elif self._in_snippet_link:
            self._current_snippet += data

    def get_results(self) -> list[SearchResult]:
        """Return all parsed search results."""
        return self._results


class DuckDuckGoHTMLBackend(SearchBackend):
    """Scrapes DuckDuckGo's HTML-only search endpoint.

    This backend scrapes https://html.duckduckgo.com/html/ which does not
    require JavaScript execution or an API key.

    DISCLAIMER AND LEGAL CAVEAT:
    ===========================
    This scrapes a third-party service, not an official, stable API.
    The HTML structure can change without notice, breaking the scraper silently.
    This is inherently fragile.

    Scraping may be against DuckDuckGo's Terms of Service depending on jurisdiction
    and use. We are not lawyers and cannot provide legal advice. You must review
    DuckDuckGo's ToS yourself. The maintainers make no claims about ToS compliance.

    For production use, implement a proper SearchBackend using DuckDuckGo's official
    API or another search provider's API.
    """

    BASE_URL = "https://html.duckduckgo.com/html/"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the backend.

        Args:
            client: Optional httpx.AsyncClient for dependency injection/testing.
            timeout: Request timeout in seconds (default 10, never infinite).
        """
        self._client = client
        self._timeout = timeout

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=self._timeout)

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Search DuckDuckGo via HTML scraping.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return (capped at 10).

        Returns:
            A list of SearchResult objects (may be empty on error or no results).

        Note:
            Connection errors, timeouts, and non-2xx responses result in an empty
            list being returned, NOT an exception. The calling tool layer handles
            this appropriately.
        """
        # Hard cap on max_results to prevent unreasonable scraping
        max_results = min(max_results, 10)

        client = await self._get_client()
        try:
            headers = {
                "User-Agent": "UnifiedAgent/0.1 (+https://github.com/unified-agent/unified-agent)"
            }
            response = await client.post(
                self.BASE_URL,
                data={"q": query},
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()

            # Parse HTML response
            parser = DuckDuckGoHTMLParser()
            parser.feed(response.text)
            results = parser.get_results()

            # Return capped results
            return results[:max_results]

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            # Return empty list on network errors / non-2xx responses
            # The tool layer will handle this appropriately
            return []
        except Exception:
            # Catch-all for any other parsing or transport errors
            return []
        finally:
            # Close client only if we created it (not injected)
            if self._client is None:
                await client.aclose()


# ---------------------------------------------------------------------------
# Convenience alias for the default backend
# ---------------------------------------------------------------------------


def default_backend() -> DuckDuckGoHTMLBackend:
    """Return the default search backend for the project.

    This is used by WebSearchTool when no backend is explicitly provided.
    """
    return DuckDuckGoHTMLBackend()
