"""SSRF (Server-Side Request Forgery) protection for WebFetchTool.

This module provides URL safety validation to prevent SSRF attacks. SSRF allows an
attacker to make requests from a server to internal resources that should not be accessible.

PROTECTED ADDRESS RANGES (RFC 1918 and related):
- Private ranges: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- Loopback: 127.0.0.0/8, ::1
- Link-local: 169.254.0.0/16 (blocks cloud metadata endpoints like 169.254.169.254)
- Other reserved ranges: 0.0.0.0/8, 224.0.0.0/4 (multicast), 240.0.0.0/4 (reserved)

DNS REBINDING STATUS:
====================
This module resolves the hostname ONCE to validate all IPs. However, THIS IS A VALIDATION-ONLY
MECHANISM. The actual HTTP request performed by httpx WILL perform its own DNS resolution,
creating a TOCTOU window.

WE DO NOT CLAIM TO MITIGATE DNS REBINDING IN THE REQUEST PATH. This is a known limitation.
The `get_safe_url_with_resolved_ip()` function exists for potential future use if IP pinning
is implemented, but it is NOT currently used by WebFetchTool.

KNOWN RESIDUAL RISKS:
- DNS rebinding: httpx re-resolves DNS on the actual request; an attacker could change
  DNS between our validation and the httpx request
- For high-security environments, consider DNS caching with TTL enforcement
- Running fetches in a separate process with network isolation is recommended

REDIRECT SSRF BYPASS:
=====================
WebFetchTool initially used follow_redirects=True, which would allow redirects to unsafe
targets. This has been FIXED: redirects are now disabled and manual redirect handling with
SSRF re-validation is implemented.
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
        This is a validation-only check. The actual HTTP request will re-resolve DNS.
        DNS rebinding is NOT mitigated - see module docstring for details.
    """
    # Parse and check scheme
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Failed to parse URL: {e}"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"URL scheme '{scheme}' is not allowed. Only http and https are permitted."

    # Extract hostname
    hostname = parsed.hostname
    if hostname is None:
        return False, "URL does not contain a valid hostname."

    # Resolve hostname and check all IPs
    ips, error = _resolve_hostname_once(hostname)
    if error:
        return False, error

    if not ips:
        return False, f"Could not resolve hostname '{hostname}' to any IP addresses."

    # Check each resolved IP
    for ip in ips:
        is_unsafe, reason = _is_ip_in_private_or_reserved_range(ip)
        if is_unsafe:
            return False, reason

    return True, ""


def get_safe_url_with_resolved_ip(url: str) -> tuple[str, str | None]:
    """Get a safe URL with its pre-resolved IP for connection.

    EXPERIMENTAL - NOT CURRENTLY USED BY WebFetchTool.

    This function validates the URL and returns the resolved IP address that could
    be used for the actual HTTP connection, along with the original hostname for
    the Host header/SNI.

    This is provided for potential future use if IP pinning is implemented.

    Args:
        url: The URL to validate and resolve.

    Returns:
        Tuple of (resolved_ip_address, original_hostname) if safe.
        Raises UnsafeUrlError if the URL is not safe.

    Note:
        This function exists for potential future IP-pinning implementation.
        See module docstring for DNS rebinding limitations.
    """
    # First validate the URL
    is_safe, reason = is_url_safe(url)
    if not is_safe:
        raise UnsafeUrlError(reason)

    # Parse URL and get hostname
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise UnsafeUrlError("URL does not contain a valid hostname.")

    # Resolve hostname
    ips, _ = _resolve_hostname_once(hostname)
    if not ips:
        raise UnsafeUrlError(f"Could not resolve hostname '{hostname}'")

    # Return the first resolved IP (prefer IPv4 for broader compatibility)
    # In production, you might want to try all IPs or prefer based on network conditions
    for ip in ips:
        if isinstance(ip, ipaddress.IPv4Address):
            return str(ip), hostname

    # Fall back to IPv6 if no IPv4
    return str(ips[0]), hostname
