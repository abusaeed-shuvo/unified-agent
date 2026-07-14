"""Web fetch tool for Unified Agent.

This tool fetches a URL and extracts readable text content.

SECURITY CONSIDERATIONS:
=======================
This tool includes SSRF (Server-Side Request Forgery) protection via ssrf_guard.py.

1. IP PINNING AGAINST DNS REBINDING:
   The SSRF guard resolves the hostname ONCE to validate all IPs. The resolved IP
   is then used to make the HTTP connection directly, with the original hostname
   passed via the Host header and SNI. This eliminates the TOCTOU window where an
   attacker could change DNS between validation and the actual request.

2. CONTENT EXTRACTION: This tool uses simple HTML tag stripping (stdlib html.parser).
   It does NOT implement sophisticated readability algorithms. Extracted text may include
   navigation menus, headers, footers, and other boilerplate content. This is a known
   simplification for v1.

3. SIZE LIMITS: Response content is capped at 1MB to prevent memory exhaustion attacks.
   This is enforced by streaming the response and checking accumulated bytes. Extracted
   text is truncated to ~5,000 characters for LLM context.

For production use, review the ssrf_guard module's docstring for detailed risk analysis.
"""

from __future__ import annotations

from html.parser import HTMLParser

import httpx

from ua.tools.base import Tool, ToolResult
from ua.web.ssrf_guard import build_pinned_url, get_safe_url_with_resolved_ip

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 10.0  # seconds
MAX_RESPONSE_SIZE = 1_048_576  # 1MB
MAX_EXTRACTED_TEXT_LENGTH = 5000  # characters


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------


class HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML by stripping tags.

    This is a simple implementation that:
    - Strips all HTML tags
    - Collapses consecutive whitespace into single spaces
    - Does NOT implement readability algorithms (navigation/footer may be included)

    This is intentionally simple - sophisticated readability extraction is a harder
    problem. This approach is sufficient for v1.
    """

    def __init__(self) -> None:
        super().__init__()
        self._text_parts: list[str] = []

    def handle_data(self, data: str) -> None:
        """Collect text content from within tags."""
        self._text_parts.append(data)

    def get_text(self) -> str:
        """Return the extracted text, collapsed whitespace."""
        # Join all parts and collapse whitespace
        raw_text = "".join(self._text_parts)
        # Collapse consecutive whitespace (spaces, newlines, tabs) into single space
        import re

        collapsed = re.sub(r"\s+", " ", raw_text)
        return collapsed.strip()


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


class WebFetchTool(Tool):
    """Fetch a URL and extract readable text content.

    This tool takes a URL, validates it against SSRF protection rules, resolves
    the hostname to an IP address, and makes the HTTP connection directly to that
    IP (pinning) while preserving the original hostname via Host header/SNI.
    This mitigates DNS rebinding attacks.

    SECURITY: DNS rebinding is mitigated by IP pinning - the IP resolved during
    validation is the IP actually connected to, not re-resolved by httpx.
    """

    name = "web_fetch"
    description = (
        "Fetch a URL and extract readable text content. "
        "Includes SSRF protection against internal/private/cloud-metadata addresses. "
        "Uses IP pinning to mitigate DNS rebinding attacks. "
        "Uses simple HTML tag stripping - may include navigation/footer text. "
        "Response capped at 1MB, extracted text truncated to ~5000 chars."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (must be http or https).",
            },
        },
        "required": ["url"],
    }

    def __init__(self) -> None:
        """Initialize the web fetch tool.

        No constructor arguments needed - uses httpx defaults with the configured
        timeout. This allows auto-discovery by ToolRegistry.
        """
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with configured timeout."""
        if self._client is not None:
            return self._client

        # Create client with timeout limit (size limit enforced separately via streaming)
        self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client

    async def run(self, url: str) -> ToolResult:
        """Fetch the URL and extract text content.

        Args:
            url: The URL to fetch.

        Returns:
            ToolResult with success=True and extracted text, or
            success=False with an error message.
        """
        # Step 1: SSRF protection check with IP pinning on initial URL
        resolved_ip, hostname, port = get_safe_url_with_resolved_ip(url)
        if resolved_ip is None:
            return ToolResult(
                success=False,
                output="",
                error="URL rejected by SSRF protection: hostname resolves to private/internal IP or scheme not allowed.",
            )

        # Step 2: Fetch the URL with manual redirect handling and size limits
        client = self._get_client()
        redirect_count = 0
        max_redirects = 5

        # Build the pinned URL for the initial request
        current_pinned_url, request_headers = build_pinned_url(url, resolved_ip, hostname, port)

        while redirect_count <= max_redirects:
            try:
                # Use streaming to enforce size limit
                response = await client.get(
                    current_pinned_url,
                    headers=request_headers,
                    stream=True,
                    follow_redirects=False,
                )

                # Check for redirect - validate redirect target before following
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_count += 1
                    if redirect_count > max_redirects:
                        return ToolResult(
                            success=False,
                            output="",
                            error="Too many redirects.",
                        )

                    # Get redirect location
                    location = response.headers.get("location")
                    if not location:
                        return ToolResult(
                            success=False,
                            output="",
                            error="Redirect response missing Location header.",
                        )
                    await response.aclose()

                    # Resolve relative redirect URLs
                    from urllib.parse import urljoin

                    redirect_url = urljoin(current_pinned_url, location)

                    # Re-validate redirect target with SSRF protection and IP pinning
                    redirect_resolved_ip, redirect_hostname, redirect_port = get_safe_url_with_resolved_ip(redirect_url)
                    if redirect_resolved_ip is None:
                        return ToolResult(
                            success=False,
                            output="",
                            error=(
                                "Redirect to unsafe URL rejected by SSRF protection: "
                                "target hostname resolves to private/internal IP or scheme not allowed."
                            ),
                        )

                    # Build pinned URL for redirect target
                    current_pinned_url, request_headers = build_pinned_url(
                        redirect_url, redirect_resolved_ip, redirect_hostname, redirect_port
                    )
                    continue

                # For non-redirect responses, check status
                response.raise_for_status()

                # Step 3: Stream response with size limit enforcement
                try:
                    html_content = await self._stream_response_with_size_limit(response)
                except ValueError as e:
                    return ToolResult(
                        success=False,
                        output="",
                        error=str(e),
                    )
                finally:
                    await response.aclose()

                break

            except httpx.ConnectError as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to connect to URL: {e}",
                )
            except httpx.TimeoutException as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Request timed out after {DEFAULT_TIMEOUT} seconds: {e}",
                )
            except httpx.HTTPStatusError as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"HTTP error {response.status_code}: {e}",
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to fetch URL: {e}",
                )

        # Step 4: Extract text from HTML
        try:
            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            text = extractor.get_text()
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to parse HTML content: {e}",
            )

        # Step 5: Truncate if necessary
        truncated = False
        if len(text) > MAX_EXTRACTED_TEXT_LENGTH:
            text = text[:MAX_EXTRACTED_TEXT_LENGTH]
            truncated = True

        # Build output with truncation note if needed
        output = text
        if truncated:
            output = (
                f"{text}\n\n[Note: Content truncated to {MAX_EXTRACTED_TEXT_LENGTH} "
                f"characters. The original page was longer.]"
            )

        return ToolResult(success=True, output=output)

    async def _stream_response_with_size_limit(
        self, response: httpx.Response
    ) -> str:
        """Stream response content with size limit enforcement.

        Args:
            response: The httpx response to stream.

        Returns:
            The complete response body as a string.

        Raises:
            ValueError: If response exceeds MAX_RESPONSE_SIZE.
        """
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_RESPONSE_SIZE:
                raise ValueError(
                    f"Response exceeded maximum size of {MAX_RESPONSE_SIZE} bytes. "
                    f"Aborting to prevent memory exhaustion."
                )

        return content.decode("utf-8", errors="replace")