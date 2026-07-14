"""Tests for WebFetchTool."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ua.tools.registry import ToolRegistry
from ua.tools.web_fetch import (
    MAX_EXTRACTED_TEXT_LENGTH,
    HTMLTextExtractor,
    WebFetchTool,
)

# ---------------------------------------------------------------------------
# Tests for HTML text extraction
# ---------------------------------------------------------------------------


def test_fetch_extracts_plain_text_from_html():
    """WebFetchTool extracts and returns plain text from an HTML page."""
    html = "<html><body><h1>Title</h1><p>Paragraph with <b>bold</b> text.</p></body></html>"
    extractor = HTMLTextExtractor()
    extractor.feed(html)

    text = extractor.get_text()
    assert "Title" in text
    assert "Paragraph" in text
    assert "bold" in text
    # Verify HTML tags are stripped
    assert "<" not in text
    assert ">" not in text


def test_fetch_extracts_plain_text_collapses_whitespace():
    """HTMLTextExtractor collapses consecutive whitespace into single spaces."""
    html = "<html><body><p>Line 1\n\n\nLine 2\t\t\tLine 3</p></body></html>"
    extractor = HTMLTextExtractor()
    extractor.feed(html)

    text = extractor.get_text()
    # All whitespace collapsed to single spaces
    assert "Line 1" in text
    assert "Line 2" in text
    assert "Line 3" in text
    # No multiple consecutive spaces (other than the single space separator)
    assert "   " not in text
    assert "\t" not in text


# ---------------------------------------------------------------------------
# Helper to create async generator for streaming mocks
# ---------------------------------------------------------------------------


async def _async_gen_single(content: bytes):
    """Helper async generator for mocking aiter_bytes."""
    yield content


# ---------------------------------------------------------------------------
# Tests for WebFetchTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_rejects_unsafe_url_before_making_request():
    """WebFetchTool rejects unsafe URLs without making any HTTP request."""
    tool = WebFetchTool()

    # Track if httpx was called
    with patch.object(tool, "_get_client") as mock_get_client:
        with patch("ua.web.ssrf_guard.socket.getaddrinfo") as mock_getaddrinfo:
            # Mock DNS to return a private IP for the metadata endpoint
            mock_getaddrinfo.return_value = [(socket.AF_INET, 0, 0, "", ("169.254.169.254", 80))]

            result = await tool.run("http://169.254.169.254/latest/meta-data/")

            # Should NOT have called _get_client (no HTTP request attempted)
            mock_get_client.assert_not_called()

    assert result.success is False
    assert "SSRF" in result.error or "private" in result.error.lower() or "internal" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_extracts_plain_text_from_html_with_mock():
    """WebFetchTool correctly extracts text from a mocked HTML response."""
    tool = WebFetchTool()

    html_content = b"<html><body><h1>Test Title</h1><p>Test content here.</p></body></html>"

    # Create mock response with proper async generator
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = html_content.decode()
    mock_response.raise_for_status = MagicMock()
    # Mock aiter_bytes as a callable that returns async generator
    mock_response.aiter_bytes = MagicMock(return_value=_async_gen_single(html_content))
    mock_response.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com")

    assert result.success is True
    assert "Test Title" in result.output
    assert "Test content" in result.output


@pytest.mark.asyncio
async def test_fetch_handles_connection_error_gracefully():
    """WebFetchTool handles connection errors gracefully."""
    tool = WebFetchTool()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com")

    assert result.success is False
    assert "Failed to connect" in result.error


@pytest.mark.asyncio
async def test_fetch_handles_timeout_gracefully():
    """WebFetchTool handles timeouts gracefully."""
    tool = WebFetchTool()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com")

    assert result.success is False
    assert "timed out" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_handles_http_error_gracefully():
    """WebFetchTool handles HTTP errors gracefully."""
    tool = WebFetchTool()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_response)
    )

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com/notfound")

    assert result.success is False
    assert "HTTP error" in result.error


@pytest.mark.asyncio
async def test_fetch_enforces_size_cap():
    """WebFetchTool enforces the response size cap via streaming."""
    tool = WebFetchTool()

    # Create mock response that yields large chunks to trigger size limit
    large_content = b"X" * (2 * 1024 * 1024)  # 2MB of content

    async def mock_aiter_bytes():
        # Yield in chunks to simulate streaming
        for i in range(0, len(large_content), 100000):
            yield large_content[i : i + 100000]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_bytes = mock_aiter_bytes
    mock_response.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com")

    assert result.success is False
    assert "exceeded maximum size" in result.error.lower()
    assert "1048576" in result.error


@pytest.mark.asyncio
async def test_fetch_truncates_long_content_with_note():
    """WebFetchTool truncates extracted text and adds a note when truncated."""
    tool = WebFetchTool()

    # Create HTML content that will be LONG when extracted (but under 1MB)
    long_text = "X" * (MAX_EXTRACTED_TEXT_LENGTH + 500)
    html = f"<html><body>{long_text}</body></html>"

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_bytes = MagicMock(return_value=_async_gen_single(html.encode("utf-8")))
    mock_response.raise_for_status = MagicMock()
    mock_response.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com")

    assert result.success is True
    assert len(result.output) <= MAX_EXTRACTED_TEXT_LENGTH + 100
    assert "truncated" in result.output.lower()


@pytest.mark.asyncio
async def test_fetch_rejects_localhost_without_http_call():
    """Verify that localhost URLs are rejected without making HTTP calls."""
    tool = WebFetchTool()

    with patch.object(tool, "_get_client") as mock_get_client:
        with patch("ua.web.ssrf_guard.socket.getaddrinfo") as mock_getaddrinfo:
            # Mock DNS to return loopback IP for localhost
            mock_getaddrinfo.return_value = [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 80))]

            result = await tool.run("http://localhost:8080/")

            # Verify no HTTP client was requested
            assert mock_get_client.call_count == 0

    assert result.success is False
    assert "SSRF" in result.error or "loopback" in result.error.lower() or "private" in result.error.lower()


@pytest.mark.asyncio
async def test_fetch_rejects_redirect_to_unsafe_url():
    """WebFetchTool validates redirect targets and rejects unsafe redirects."""
    tool = WebFetchTool()

    # Create mock response for initial request (safe URL redirecting to unsafe)
    safe_html = b"<html><body>Safe content</body></html>"
    mock_response_safe = MagicMock(spec=httpx.Response)
    mock_response_safe.status_code = 200
    mock_response_safe.headers = {}
    mock_response_safe.aiter_bytes = MagicMock(return_value=_async_gen_single(safe_html))
    mock_response_safe.raise_for_status = MagicMock()
    mock_response_safe.aclose = AsyncMock()

    mock_response_redirect = MagicMock(spec=httpx.Response)
    mock_response_redirect.status_code = 302
    mock_response_redirect.headers = {"location": "http://169.254.169.254/private-meta/"}
    mock_response_redirect.aclose = AsyncMock()

    mock_client = MagicMock()
    # First call returns redirect
    mock_client.get = AsyncMock(return_value=mock_response_redirect)

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if hostname == "example.com":
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]
        # Would be called for redirect target but we should reject before that
        return [(socket.AF_INET, type, proto, "", ("169.254.169.254", port))]

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
            result = await tool.run("https://example.com")

    # Should be rejected because redirect target is unsafe
    assert result.success is False
    assert "SSRF" in result.error or "redirect" in result.error.lower() or "private" in result.error.lower()


def test_fetch_tool_auto_discovered_by_registry():
    """WebFetchTool is auto-discovered by ToolRegistry.discover()."""
    registry = ToolRegistry()
    registry.discover()

    assert "web_fetch" in registry._tools
    assert isinstance(registry.get("web_fetch"), WebFetchTool)


# ---------------------------------------------------------------------------
# Tests for DNS rebinding mitigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dns_rebinding_blocked_by_ip_pinning():
    """DNS rebinding attack is prevented by IP pinning.

    This test simulates a hostname that resolves to a SAFE public IP during
    validation, but an ATTACKER would try to point it to a private IP at
    connection time. With IP pinning, the connection uses the validated IP
    (public), not re-resolving the hostname.

    The key assertion: even if DNS changed to a private IP between validation
    and connection, the request still goes to the originally validated public IP.
    """
    tool = WebFetchTool()

    html_content = b"<html><body>Success</body></html>"
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.aiter_bytes = MagicMock(return_value=_async_gen_single(html_content))
    mock_response.raise_for_status = MagicMock()
    mock_response.aclose = AsyncMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    # This mock simulates: DNS returns SAFE IP during initial resolution (validation)
    # But we capture what IP was actually used in the request
    captured_urls = []

    async def capture_get(url, headers=None, stream=True, follow_redirects=False):
        captured_urls.append(url)
        return mock_response

    mock_client.get = capture_get

    call_count = [0]

    def mock_getaddrinfo_rebinding(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        call_count[0] += 1
        # First call (validation time): return SAFE public IP
        if call_count[0] == 1:
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]  # Safe public IP
        # Subsequent calls: attacker tries to change DNS to private IP
        # But with IP pinning, we don't re-resolve - we use the captured IP
        return [(socket.AF_INET, type, proto, "", ("10.0.0.1", port))]  # Attacker-controlled private IP

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_rebinding):
            result = await tool.run("https://rebind.example.com/")

    # The request should succeed because:
    # 1. First DNS lookup sees safe IP (93.184.216.34)
    # 2. IP is pinned and used for connection (not re-resolved)
    # 3. The attacker-controlled private IP never gets connected to
    assert result.success is True
    assert "Success" in result.output

    # Verify the captured URL contains the validated IP, not the hostname
    assert len(captured_urls) == 1
    assert "93.184.216.34" in captured_urls[0]  # The validated public IP
    assert "rebind.example.com" not in captured_urls[0]  # Hostname not in URL (we use IP)


@pytest.mark.asyncio
async def test_dns_rebinding_on_redirect_blocked():
    """DNS rebinding on redirect is prevented by re-validating and pinning redirect IP.

    This test simulates a redirect target that would be vulnerable to DNS rebinding:
    the redirect URL points to a hostname that could change DNS between lookups.
    We verify that the redirect target is validated and pinned before connecting.
    """
    tool = WebFetchTool()

    call_count = [0]
    redirect_calls = [0]

    def mock_getaddrinfo_redirect_rebinding(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        call_count[0] += 1
        if hostname == "example.com":
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]  # Safe public IP
        elif hostname == "redirect.example.com":
            return [(socket.AF_INET, type, proto, "", ("93.184.216.35", port))]  # Safe public IP for redirect
        return [(socket.AF_INET, type, proto, "", ("10.0.0.1", port))]  # Attack IP (shouldn't be reached for safe redirects)

    captured_urls = []

    async def mock_get_response(url, headers=None, stream=True, follow_redirects=False):
        captured_urls.append(url)
        redirect_calls[0] += 1

        if redirect_calls[0] == 1:
            # First call: redirect response
            mock_response_redirect = MagicMock(spec=httpx.Response)
            mock_response_redirect.status_code = 302
            mock_response_redirect.headers = {"location": "https://redirect.example.com/target"}
            mock_response_redirect.aclose = AsyncMock()
            return mock_response_redirect
        else:
            # Second call: final response
            final_html = b"<html><body>Redirect target content</body></html>"
            mock_response_final = MagicMock(spec=httpx.Response)
            mock_response_final.status_code = 200
            mock_response_final.aiter_bytes = MagicMock(return_value=_async_gen_single(final_html))
            mock_response_final.raise_for_status = MagicMock()
            mock_response_final.aclose = AsyncMock()
            return mock_response_final

    mock_client = MagicMock()
    mock_client.get = mock_get_response

    with patch.object(tool, "_get_client", return_value=mock_client):
        with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_redirect_rebinding):
            result = await tool.run("https://example.com")

    assert result.success is True
    assert "Redirect target content" in result.output

    # Verify both URLs use IP addresses (not hostnames)
    assert len(captured_urls) == 2
    assert "93.184.216.34" in captured_urls[0]  # Initial IP
    assert "93.184.216.35" in captured_urls[1]  # Redirect IP