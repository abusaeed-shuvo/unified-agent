"""SSRF (Server-Side Request Forgery) protection for WebFetchTool.

This module provides URL safety validation to prevent SSRF attacks. SSRF allows an
attacker to make requests from a server to internal resources that should not be accessible.

PROTECTED ADDRESS RANGES (RFC 1918 and related):
- Private ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- Loopback: 127.0.0.0/8, ::1
- Link-local: 169.254.0.0/16 (blocks cloud metadata endpoints like 169.254.169.254)
- Other reserved ranges: 0.0.0.0/8, 224.0.0.0/4 (multicast), 240.0.0.0/4 (reserved)

DNS REBINDING MITIGATION:
========================
This module resolves the hostname ONCE to validate all IPs. When used with the
`get_safe_url_with_resolved_ip()` function, the resolved IP is then used to make
the HTTP connection directly via a custom network backend, while preserving the
original hostname for SNI and certificate verification. This eliminates the TOCTOU
window where an attacker could change DNS between validation and the actual request.

The mitigation works by:
1. Resolving the hostname and checking all IPs during validation
2. Returning the validated IP address and original hostname
3. Using a custom network backend that connects to the resolved IP
4. Preserving the original hostname in the request Origin for SNI and TLS cert verification

REDIRECT SSRF BYPASS:
=====================
WebFetchTool initially used follow_redirects=True, which would allow redirects to unsafe
targets. This has been FIXED: redirects are now disabled and manual redirect handling with
SSRF re-validation is implemented. Each redirect hop re-validates and pins the IP before
making the connection.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from ua.config.logging import get_logger

logger = get_logger(__name__)


class UnsafeUrlError(Exception):
    """Raised when a URL is deemed unsafe for fetching (SSRF risk)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _get_hostname_from_url(url: str) -> str | None:
    """Extract hostname from a URL string.

    Args:
        url: The URL to parse.

    Returns:
        The hostname if present, None otherwise.
    """
    try:
        parsed = urlparse(url)
        return parsed.hostname
    except Exception:
        return None


def _resolve_hostname_once(
    hostname: str,
) -> tuple[list[ipaddress.IPv4Address | ipaddress.IPv6Address], str | None]:
    """Resolve a hostname to its IP addresses using stdlib DNS resolution.

    Args:
        hostname: The hostname to resolve.

    Returns:
        Tuple of (list of IP addresses, error message if any).
    """
    try:
        # Get all address info (both IPv4 and IPv6)
        addr_info = socket.getaddrinfo(
            hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        ips = []
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ips.append(ipaddress.ip_address(ip_str))
            except ValueError:
                continue
        return ips, None
    except socket.gaierror as e:
        return [], f"Failed to resolve hostname '{hostname}': {e}"
    except Exception as e:
        return [], f"Unexpected error resolving hostname '{hostname}': {e}"


def _is_ip_in_private_or_reserved_range(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> tuple[bool, str]:
    """Check if an IP address falls in private or reserved ranges.

    Args:
        ip: The IP address to check.

    Returns:
        Tuple of (is_unsafe, reason_string).
    """
    # Check private IPv4 ranges (RFC 1918)
    if isinstance(ip, ipaddress.IPv4Address):
        private_ranges = [
            (ipaddress.IPv4Network("10.0.0.0/8"), "private range 10.0.0.0/8"),
            (ipaddress.IPv4Network("172.16.0.0/12"), "private range 172.16.0.0/12"),
            (ipaddress.IPv4Network("192.168.0.0/16"), "private range 192.168.0.0/16"),
            (ipaddress.IPv4Network("127.0.0.0/8"), "loopback range 127.0.0.0/8"),
            (ipaddress.IPv4Network("169.254.0.0/16"), "link-local range 169.254.0.0/16"),
            (ipaddress.IPv4Network("0.0.0.0/8"), "this network (0.0.0.0/8)"),
            (ipaddress.IPv4Network("224.0.0.0/4"), "multicast range"),
            (ipaddress.IPv4Network("240.0.0.0/4"), "reserved range"),
        ]

        for network, description in private_ranges:
            if ip in network:
                return True, f"IP address {ip} is in {description}"
    else:
        # IPv6 checks
        ipv6_private_ranges = [
            (ipaddress.IPv6Network("::1/128"), "loopback ::1"),
            (ipaddress.IPv6Network("fc00::/7"), "unique local address (ULA)"),
            (ipaddress.IPv6Network("fe80::/10"), "link-local"),
            (ipaddress.IPv6Network("::/128"), "unspecified address"),
            (ipaddress.IPv6Network("::ffff:0:0/96"), "IPv4-mapped IPv6 addresses"),
            (ipaddress.IPv6Network("100::/64"), "discard-only address block"),
        ]

        for network, description in ipv6_private_ranges:
            if ip in network:
                return True, f"IP address {ip} is in {description}"

    return False, ""


def _validate_url_and_resolve_ip(
    url: str,
) -> tuple[list[ipaddress.IPv4Address | ipaddress.IPv6Address], str | None, str | None, int | None]:
    """Validate URL and resolve hostname to IPs in a single step.

    This is the core function that performs validation and resolution exactly once.

    Args:
        url: The URL to validate and resolve.

    Returns:
        Tuple of (list of IPs, hostname, error, port) - IPs and hostname are populated
        if validation succeeds, error is populated if validation fails.
    """
    # Parse and check scheme
    try:
        parsed = urlparse(url)
    except Exception as e:
        return [], None, f"Failed to parse URL: {e}", None

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return [], None, f"URL scheme '{scheme}' is not allowed. Only http and https are permitted.", None

    # Extract hostname
    hostname = parsed.hostname
    if hostname is None:
        return [], None, "URL does not contain a valid hostname.", None

    # Get port (default to 80 for http, 443 for https)
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80

    # Resolve hostname and check all IPs
    ips, error = _resolve_hostname_once(hostname)
    if error:
        return [], hostname, error, port

    if not ips:
        return [], hostname, f"Could not resolve hostname '{hostname}' to any IP addresses.", port

    # Check each resolved IP
    for ip in ips:
        is_unsafe, reason = _is_ip_in_private_or_reserved_range(ip)
        if is_unsafe:
            return [], hostname, reason, port

    return ips, hostname, None, port


def is_url_safe(url: str) -> tuple[bool, str]:
    """Check if a URL is safe to fetch (not vulnerable to SSRF).

    This function validates that a URL:
    1. Uses only http or https scheme
    2. Does not resolve to private/internal/reserved IP ranges

    Args:
        url: The URL to validate.

    Returns:
        Tuple of (is_safe, reason_if_unsafe). If safe, reason will be empty string.

    Note:
        For DNS rebinding mitigation, use get_safe_url_with_resolved_ip() to get
        the resolved IP address for pin-the-IP connections.
    """
    ips, _, error, _ = _validate_url_and_resolve_ip(url)
    if error is not None:
        return False, error
    return True, ""


def get_safe_url_with_resolved_ip(
    url: str,
) -> tuple[str, str, int] | tuple[None, None, None]:
    """Validate URL and return resolved IP for DNS rebinding-safe connections.

    This function validates the URL, resolves the hostname to an IP address, and returns
    all information needed to make a connection directly to the resolved IP while
    preserving the original hostname for SNI and certificate verification.

    The returned tuple allows the caller to construct an HTTP request using the original
    hostname in the URL (for SNI/cert verification) while connecting to a pre-validated IP.

    Args:
        url: The URL to validate and resolve.

    Returns:
        Tuple of (resolved_ip_address, original_hostname, port) if safe.
        Returns (None, None, None) if the URL is not safe or cannot be resolved.

    Note:
        For each redirect hop, call this function again to re-validate and re-pin the IP.
        This closes the TOCTOU window on both initial requests and redirects.
    """
    # Validate and resolve in a single step (no double resolution)
    ips, hostname, error, port = _validate_url_and_resolve_ip(url)
    if error is not None:
        return None, None, None

    # Return the first resolved IP (prefer IPv4 for broader compatibility)
    # In production, you might want to try all IPs or prefer based on network conditions
    for ip in ips:
        if isinstance(ip, ipaddress.IPv4Address):
            return str(ip), hostname, port

    # Fall back to IPv6 if no IPv4
    return str(ips[0]), hostname, port


def build_pinned_url(
    original_url: str,
    resolved_ip: str,
    hostname: str,
    port: int,
) -> tuple[str, str, int]:
    """Return original URL info for IP pinning (does NOT modify the URL).

    This function returns the original URL and hostname for making requests that
    connect to the pre-validated IP via a custom network backend, while keeping
    the original hostname in the URL for SNI and certificate verification.

    Args:
        original_url: The original URL to fetch (used as-is for the request).
        resolved_ip: The pre-validated resolved IP address.
        hostname: The original hostname for SNI.
        port: The port number to use.

    Returns:
        Tuple of (original_url, hostname, resolved_ip) - the caller should use
        the original URL for the httpx request and pass resolved_ip to a custom
        transport for IP-pinned connection.
    """
    # Return the original URL to preserve SNI, along with mapping info
    return original_url, hostname, resolved_ip