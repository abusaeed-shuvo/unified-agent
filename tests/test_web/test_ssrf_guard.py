"""Tests for SSRF guard URL validation."""

from __future__ import annotations

import socket
from unittest.mock import patch

from ua.web.ssrf_guard import build_pinned_url, get_safe_url_with_resolved_ip, is_url_safe

# ---------------------------------------------------------------------------
# Tests for blocked URLs
# ---------------------------------------------------------------------------


def test_cloud_metadata_ip_blocked():
    """Cloud metadata endpoint 169.254.169.254 is blocked (link-local range)."""
    # Test the exact cloud metadata endpoint
    is_safe, reason = is_url_safe("http://169.254.169.254/latest/meta-data/")
    assert is_safe is False
    assert "link-local" in reason.lower() or "169.254" in reason


def test_cloud_metadata_ip_variants_blocked():
    """Other IPs in the 169.254.x.x link-local range are blocked."""
    is_safe, reason = is_url_safe("http://169.254.1.1/")
    assert is_safe is False
    assert "link-local" in reason.lower() or "169.254" in reason


def test_localhost_blocked():
    """localhost (which resolves to 127.0.0.1) is blocked."""
    is_safe, reason = is_url_safe("http://localhost:8080/")
    assert is_safe is False
    assert "loopback" in reason.lower() or "127" in reason


def test_loopback_ip_blocked():
    """Direct loopback IP 127.0.0.1 is blocked."""
    is_safe, reason = is_url_safe("http://127.0.0.1/")
    assert is_safe is False
    assert "loopback" in reason.lower() or "127" in reason


def test_private_range_10_blocked():
    """Private range 10.0.0.0/8 is blocked."""
    is_safe, reason = is_url_safe("http://10.0.0.5/")
    assert is_safe is False
    assert "private" in reason.lower() or "10." in reason


def test_private_range_192_168_blocked():
    """Private range 192.168.0.0/16 is blocked."""
    is_safe, reason = is_url_safe("http://192.168.1.1/")
    assert is_safe is False
    assert "private" in reason.lower() or "192.168" in reason


def test_private_range_172_16_blocked():
    """Private range 172.16.0.0/12 is blocked."""
    is_safe, reason = is_url_safe("http://172.16.0.1/")
    assert is_safe is False
    assert "private" in reason.lower() or "172" in reason


def test_link_local_range_blocked():
    """Link-local range 169.254.0.0/16 is blocked."""
    is_safe, reason = is_url_safe("http://169.254.0.1/")
    assert is_safe is False
    assert "link-local" in reason.lower() or "169.254" in reason


def test_non_http_scheme_blocked():
    """Non-http/https schemes (file, ftp, gopher) are blocked."""
    # file:// scheme
    is_safe, reason = is_url_safe("file:///etc/passwd")
    assert is_safe is False
    assert "scheme" in reason.lower()

    # ftp:// scheme
    is_safe, reason = is_url_safe("ftp://ftp.example.com/file.txt")
    assert is_safe is False
    assert "scheme" in reason.lower()

    # gopher:// scheme
    is_safe, reason = is_url_safe("gopher://gopher.example.com/")
    assert is_safe is False
    assert "scheme" in reason.lower()


def test_0_0_0_0_this_network_blocked():
    """0.0.0.0/8 (this network) is blocked."""
    is_safe, reason = is_url_safe("http://0.0.0.0/")
    assert is_safe is False
    assert "0.0.0" in reason or "this network" in reason.lower()


# ---------------------------------------------------------------------------
# Tests for allowed URLs
# ---------------------------------------------------------------------------


def test_public_address_allowed_with_mocked_dns():
    """A genuine public address is allowed when DNS resolution returns a public IP."""

    def mock_getaddrinfo(
        hostname, port=None, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        if hostname == "example.com":
            # Return IPv4 address info
            return [(socket.AF_INET, type, proto, "", ("1.1.1.1", port))]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
        is_safe, reason = is_url_safe("https://example.com")
        assert is_safe is True
        assert reason == ""


def test_public_address_allowed_with_ipv6():
    """A public IPv6 address is allowed."""

    def mock_getaddrinfo(
        hostname, port=None, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        if hostname == "ipv6.example.com":
            # Return IPv6 address info (public IPv6 address)
            return [(socket.AF_INET6, type, proto, "", ("2606:4700:48da::443", port, 0, 0))]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
        is_safe, reason = is_url_safe("https://ipv6.example.com")
        assert is_safe is True
        assert reason == ""


# ---------------------------------------------------------------------------
# Tests for IP pinning and get_safe_url_with_resolved_ip
# ---------------------------------------------------------------------------


def test_get_safe_url_returns_resolved_ip_for_public_host():
    """get_safe_url_with_resolved_ip returns resolved IP for safe hosts."""

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if hostname == "example.com":
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
        resolved_ip, hostname, port = get_safe_url_with_resolved_ip("https://example.com")

    assert resolved_ip == "93.184.216.34"
    assert hostname == "example.com"
    assert port == 443  # Default HTTPS port


def test_get_safe_url_returns_none_for_private_host():
    """get_safe_url_with_resolved_ip returns None tuple for unsafe hosts."""

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if hostname == "internal.example.com":
            return [(socket.AF_INET, type, proto, "", ("10.0.0.1", port))]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
        resolved_ip, hostname, port = get_safe_url_with_resolved_ip("https://internal.example.com")

    assert resolved_ip is None
    assert hostname is None
    assert port is None


def test_get_safe_url_handles_custom_port():
    """get_safe_url_with_resolved_ip preserves custom port."""

    def mock_getaddrinfo(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if hostname == "example.com":
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo):
        resolved_ip, hostname, port = get_safe_url_with_resolved_ip("https://example.com:8443")

    assert resolved_ip == "93.184.216.34"
    assert hostname == "example.com"
    assert port == 8443


def test_build_pinned_url_basic():
    """build_pinned_url constructs URL with IP and includes Host header."""
    pinned_url, headers = build_pinned_url(
        "https://example.com/path", "93.184.216.34", "example.com", 443
    )

    assert pinned_url == "https://93.184.216.34/path"
    assert headers == {"Host": "example.com"}


def test_build_pinned_url_with_custom_port():
    """build_pinned_url includes port when non-standard."""
    pinned_url, headers = build_pinned_url(
        "https://example.com:8443/path", "93.184.216.34", "example.com", 8443
    )

    assert pinned_url == "https://93.184.216.34:8443/path"
    assert headers == {"Host": "example.com"}


def test_build_pinned_url_preserves_query():
    """build_pinned_url preserves query parameters."""
    pinned_url, headers = build_pinned_url(
        "https://example.com/search?q=test", "93.184.216.34", "example.com", 443
    )

    assert pinned_url == "https://93.184.216.34/search?q=test"
    assert headers == {"Host": "example.com"}


def test_build_pinned_url_http():
    """build_pinned_url works for HTTP (port 80)."""
    pinned_url, headers = build_pinned_url(
        "http://example.com/path", "93.184.216.34", "example.com", 80
    )

    assert pinned_url == "http://93.184.216.34/path"
    assert headers == {"Host": "example.com"}


# ---------------------------------------------------------------------------
# Tests for DNS rebinding mitigation behavior
# ---------------------------------------------------------------------------


def test_dns_rebinding_mitigation_via_ip_pinning():
    """Verify that IP pinning prevents DNS rebinding attacks.

    With the new implementation, the resolved IP returned by get_safe_url_with_resolved_ip
    should be the one actually connected to, eliminating the TOCTOU window.

    This test documents that:
    - IPs are resolved once during validation
    - The same IP is returned and can be used for connection
    - No second DNS lookup happens in the request path (httpx uses the provided IP)
    """
    call_count = [0]

    def mock_getaddrinfo_once(hostname, port=None, family=0, type=0, proto=0, flags=0):  # noqa: A002
        # Detect if multiple calls are made (which would indicate re-resolution)
        call_count[0] += 1
        if hostname == "ip-pinned.example.com":
            return [(socket.AF_INET, type, proto, "", ("93.184.216.34", port))]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_once):
        resolved_ip, hostname, port = get_safe_url_with_resolved_ip("https://ip-pinned.example.com")

    # Should have called getaddrinfo exactly once
    assert call_count[0] == 1
    assert resolved_ip == "93.184.216.34"
    assert hostname == "ip-pinned.example.com"


def test_unresolvable_hostname_rejected():
    """A hostname that cannot be resolved is rejected."""

    def mock_getaddrinfo_fail(
        hostname, port=None, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        raise socket.gaierror("Name or service not known")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_fail):
        is_safe, reason = is_url_safe("https://nonexistent.invalid/")
        assert is_safe is False
        assert "failed to resolve" in reason.lower() or "resolve" in reason.lower()

    # Also test get_safe_url_with_resolved_ip returns None tuple
    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_fail):
        resolved_ip, hostname, port = get_safe_url_with_resolved_ip("https://nonexistent.invalid/")
        assert resolved_ip is None
        assert hostname is None
        assert port is None