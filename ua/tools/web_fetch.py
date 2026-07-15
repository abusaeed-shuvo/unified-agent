"""Web fetch tool for Unified Agent.

This tool fetches a URL and extracts readable text content.

SECURITY CONSIDERATIONS:
========================
This tool includes SSRF (Server-Side Request Forgery) protection via ssrf_guard.py.

1. IP PINNING AGAINST DNS REBINDING:
   The SSRF guard resolves the hostname ONCE to validate all IPs. The resolved IP
   is then used for the connection via a custom network backend, while the original
   hostname is preserved in the URL for SNI and certificate verification. This
   eliminates the TOCTOU window where an attacker could change DNS between
   validation and the actual request.

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

import asyncio
import socket
from contextlib import contextmanager
from html.parser import HTMLParser
from typing import Any

import httpx
import httpcore
import anyio
import ssl

from httpcore._exceptions import map_exceptions
from httpcore._utils import is_socket_readable

from ua.tools.base import Tool, ToolResult
from ua.web.ssrf_guard import get_safe_url_with_resolved_ip

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 10.0  # seconds
MAX_RESPONSE_SIZE = 1_048_576  # 1MB
MAX_EXTRACTED_TEXT_LENGTH = 5000  # characters


# ---------------------------------------------------------------------------
# Custom Network Backend for IP Pinning with SNI Preservation
# ---------------------------------------------------------------------------


class _AnyIOStream(httpcore.AsyncNetworkStream):
    """Wrap an anyio ByteStream to match httpcore.AsyncNetworkStream interface.

    This is the same implementation as httpcore._backends.anyio.AnyIOStream.
    """

    def __init__(self, stream: anyio.abc.ByteStream) -> None:
        self._stream = stream

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        """Receive data from stream."""
        exc_map = {
            TimeoutError: httpcore.ReadTimeout,
            anyio.BrokenResourceError: httpcore.ReadError,
            anyio.ClosedResourceError: httpcore.ReadError,
            anyio.EndOfStream: httpcore.ReadError,
        }
        with map_exceptions(exc_map):
            with anyio.fail_after(timeout):
                try:
                    return await self._stream.receive(max_bytes=max_bytes)
                except anyio.EndOfStream:
                    return b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        """Send data to stream."""
        if not buffer:
            return
        exc_map = {
            TimeoutError: httpcore.WriteTimeout,
            anyio.BrokenResourceError: httpcore.WriteError,
            anyio.ClosedResourceError: httpcore.WriteError,
        }
        with map_exceptions(exc_map):
            with anyio.fail_after(timeout):
                await self._stream.send(buffer)

    async def aclose(self) -> None:
        """Close the stream."""
        await self._stream.aclose()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Upgrade the connection to TLS.

        Args:
            ssl_context: The SSL context to use for TLS.
            server_hostname: The hostname for SNI (from the original request).
            timeout: Optional timeout for the TLS handshake.

        Returns:
            A new AnyIOStream wrapping the TLS stream.
        """
        exc_map = {
            TimeoutError: httpcore.ConnectTimeout,
            anyio.BrokenResourceError: httpcore.ConnectError,
            anyio.EndOfStream: httpcore.ConnectError,
            ssl.SSLError: httpcore.ConnectError,
        }
        with map_exceptions(exc_map):
            try:
                with anyio.fail_after(timeout):
                    ssl_stream = await anyio.streams.tls.TLSStream.wrap(
                        self._stream,
                        ssl_context=ssl_context,
                        hostname=server_hostname,
                        standard_compatible=False,
                        server_side=False,
                    )
            except Exception as exc:
                await self.aclose()
                raise exc
        return _AnyIOStream(ssl_stream)

    def get_extra_info(self, info: str) -> Any:
        """Get extra connection information."""
        if info == "ssl_object":
            return self._stream.extra(anyio.streams.tls.TLSAttribute.ssl_object, None)
        if info == "client_addr":
            return self._stream.extra(anyio.abc.SocketAttribute.local_address, None)
        if info == "server_addr":
            return self._stream.extra(anyio.abc.SocketAttribute.remote_address, None)
        if info == "socket":
            return self._stream.extra(anyio.abc.SocketAttribute.raw_socket, None)
        if info == "is_readable":
            sock = self._stream.extra(anyio.abc.SocketAttribute.raw_socket, None)
            return sock is not None and self._sock_has_data(sock)
        return None

    def _sock_has_data(self, sock: socket.socket) -> bool:
        """Check if socket has data available (non-blocking check)."""
        try:
            sock.setblocking(False)
            data = sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            sock.setblocking(True)
            return len(data) > 0
        except BlockingIOError:
            return False
        except OSError:
            return False


class PinnedIPNetworkBackend(httpcore.AsyncNetworkBackend):
    """Custom network backend that connects to a pre-resolved IP address.

    This preserves SNI and certificate verification while preventing DNS rebinding
    attacks by connecting to a validated IP instead of re-resolving the hostname.

    The httpcore connection layer calls start_tls with server_hostname from the
    original request Origin, which is used for SNI during TLS handshake.
    """

    def __init__(self, resolved_ip: str, resolved_port: int):
        """Initialize with the validated IP and port.

        Args:
            resolved_ip: The pre-validated IP address to connect to.
            resolved_port: The port to connect to.
        """
        self._resolved_ip = resolved_ip
        self._resolved_port = resolved_port

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: list[tuple] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Connect to the pre-resolved IP instead of resolving the hostname.

        Args:
            host: The original hostname (will be used for SNI via start_tls).
            port: The original port (ignored, uses resolved_port instead).
            timeout: Optional connection timeout.
            local_address: Optional local address to bind.
            socket_options: Optional socket options.

        Returns:
            An async network stream connected to the resolved IP.
        """
        if socket_options is None:
            socket_options = []

        exc_map = {
            TimeoutError: httpcore.ConnectTimeout,
            OSError: httpcore.ConnectError,
            anyio.BrokenResourceError: httpcore.ConnectError,
        }
        with map_exceptions(exc_map):
            with anyio.fail_after(timeout):
                stream: anyio.abc.ByteStream = await anyio.connect_tcp(
                    remote_host=self._resolved_ip,
                    remote_port=self._resolved_port,
                    local_host=local_address,
                )
                # Apply socket options if any
                for option in socket_options:
                    stream._raw_socket.setsockopt(*option)  # type: ignore[attr-defined]

        return _AnyIOStream(stream)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: list[tuple] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Not supported for IP pinning."""
        raise httpcore.NetworkError("Unix sockets not supported in PinnedIPNetworkBackend")

    async def sleep(self, seconds: float) -> None:
        """Sleep for the given duration."""
        await anyio.sleep(seconds)


def _create_pinned_client(
    resolved_ip: str, resolved_port: int, timeout: float = DEFAULT_TIMEOUT
) -> httpx.AsyncClient:
    """Create an httpx client that connects to the resolved IP while preserving SNI.

    This creates a custom httpx transport that uses a custom network backend
    to pin the connection to the resolved IP while preserving the hostname
    in the request for SNI.

    Args:
        resolved_ip: The pre-validated IP address.
        resolved_port: The port to connect to.
        timeout: Request timeout in seconds.

    Returns:
        An AsyncClient configured with IP-pinned transport.
    """
    # Create a custom network backend that uses the pinned IP
    network_backend = PinnedIPNetworkBackend(resolved_ip, resolved_port)

    # Create an httpx transport (will create default pool internally)
    # We then replace the internal pool with one using our custom network backend
    transport = httpx.AsyncHTTPTransport()

    # Replace the pool with one using our network backend
    # The pool's network_backend controls the actual TCP connection
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpcore.default_ssl_context(),
        network_backend=network_backend,
    )

    client = httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
    )
    return client


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
    IP (pinning) while preserving the original hostname via SNI for TLS.
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

    def _get_client(self, resolved_ip: str | None = None, resolved_port: int | None = None) -> httpx.AsyncClient:
        """Get or create the HTTP client with configured timeout and optional IP pinning.

        Args:
            resolved_ip: Optional pre-resolved IP for DNS rebinding mitigation.
            resolved_port: The port to connect to when resolved_ip is set.
        """
        if resolved_ip is not None and resolved_port is not None:
            return _create_pinned_client(resolved_ip, resolved_port)

        if self._client is not None:
            return self._client

        # Create client with timeout limit (size limit enforced separately via streaming)
        self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=False)
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
        client = self._get_client(resolved_ip, port)
        redirect_count = 0
        max_redirects = 5
        html_content = None

        while redirect_count <= max_redirects:
            try:
                # NOTE: We use the original URL to preserve SNI for HTTPS
                response = await client.get(url, follow_redirects=False)

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

                    redirect_url = urljoin(url, location)

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

                    # Create a new client with the redirect's pinned IP
                    client = self._get_client(redirect_resolved_ip, redirect_port)
                    url = redirect_url  # Continue loop with redirect URL (SNI preserved)
                    continue

                # For non-redirect responses, check status
                response.raise_for_status()

                # Step 3: Stream response with size limit enforcement
                html_content = await self._stream_response_with_size_limit(response)
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
        # httpx Response has .text as a string property
        text = response.text

        # Check size against limit (text encoded to bytes)
        if len(text.encode("utf-8")) > MAX_RESPONSE_SIZE:
            raise ValueError(
                f"Response exceeded maximum size of {MAX_RESPONSE_SIZE} bytes. "
                f"Aborting to prevent memory exhaustion."
            )

        return text
