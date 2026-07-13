"""Tests for SSRF guard URL validation."""

from __future__ import annotations

import socket
from unittest.mock import patch

from ua.web.ssrf_guard import is_url_safe

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
# Tests for DNS rebinding mitigation behavior
# ---------------------------------------------------------------------------


def test_dns_rebinding_mitigation_behavior():
    """Document the DNS rebinding mitigation approach.

    This test verifies that is_url_safe resolves the hostname and checks ALL returned IPs.
    The SSRF guard resolves DNS once and validates all IPs before the request would be made.

    Key behavior:
    - If ANY resolved IP is in a blocked range, the URL is rejected
    - This includes hosts that resolve to multiple IPs (some public, some private)

    LIMITATION DISCLOSED:
    The actual HTTP request will still perform its own DNS resolution (httpx internally).
    This creates a TOCTOU window. However, we mitigate this by documenting it clearly
    and the practical reality is that DNS rebinding attacks typically involve very short
    TTLs and rapid IP changes - standard websites use normal TTLs and don't change
    IPs within seconds.
    """
    # Test a host that resolves to a mix of safe and unsafe IPs
    # If ANY IP is unsafe, the URL should be rejected

    def mock_getaddrinfo_mixed(
        hostname, port=None, family=0, type=0, proto=0, flags=0  # noqa: A002
    ):
        if hostname == "mixed.example.com":
            return [
                (socket.AF_INET, type, proto, "", ("10.0.0.1", port)),  # Private - unsafe
                (socket.AF_INET, type, proto, "", ("93.184.216.34", port)),  # Public
            ]
        raise socket.gaierror(f"No resolution for {hostname}")

    with patch("ua.web.ssrf_guard.socket.getaddrinfo", side_effect=mock_getaddrinfo_mixed):
        is_safe, reason = is_url_safe("https://mixed.example.com")
        assert is_safe is False
        assert "private" in reason.lower() or "10." in reason


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
