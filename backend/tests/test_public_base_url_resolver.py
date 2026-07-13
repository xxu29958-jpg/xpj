"""Coverage for ``app.config._resolve_public_base_url``.

Owner Console writes PUBLIC_BASE_URL through the form path (validated by
runtime_settings_service); the env-loading path goes through the bare
resolver here. Both paths must refuse public ``http://`` because the
UploadLink URL embeds a credential in the path.
"""

from __future__ import annotations

import pytest

from app.config import _resolve_cloudflare_access_team_domain, _resolve_public_base_url
from app.services.installation_health_service import (
    configured_mobile_endpoint_url,
    installation_mobile_capabilities,
)


@pytest.mark.parametrize(
    "raw,expected,phone_usable",
    [
        # https any host: accepted
        ("https://api.example.com", "https://api.example.com", True),
        ("https://api.zen70.cn:8443", "https://api.zen70.cn:8443", True),
        ("https://192.168.1.10:8443", "https://192.168.1.10:8443", True),
        ("https://[2001:db8::1]:8443", "https://[2001:db8::1]:8443", True),
        # http loopback: accepted (local dev)
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000", False),
        ("http://localhost", "http://localhost", False),
        ("http://[::1]:8000", "http://[::1]:8000", False),
        # HTTPS still cannot turn loopback or wildcard binds into a phone endpoint
        ("https://127.0.0.1:8000", "https://127.0.0.1:8000", False),
        ("https://localhost", "https://localhost", False),
        ("https://[::1]:8000", "https://[::1]:8000", False),
        ("https://0.0.0.0:8000", "https://0.0.0.0:8000", False),
        ("https://[::]:8000", "https://[::]:8000", False),
        # trailing slash stripped
        ("https://api.example.com/", "https://api.example.com", True),
        # whitespace stripped
        ("  https://api.example.com  ", "https://api.example.com", True),
        # empty / None
        (None, "", False),
        ("", "", False),
        ("   ", "", False),
    ],
)
def test_resolver_accepts_safe_values(
    raw: str | None,
    expected: str,
    phone_usable: bool,
) -> None:
    assert _resolve_public_base_url(raw) == expected
    capabilities = installation_mobile_capabilities(expected)
    assert configured_mobile_endpoint_url(expected) == (expected if phone_usable else None)
    assert capabilities.mobile_endpoint_state == (
        "public_configured_unverified" if phone_usable else "local_only"
    )
    assert capabilities.android_binding_state == (
        "configured_unverified" if phone_usable else "setup_required"
    )
    assert capabilities.iphone_upload_state == capabilities.android_binding_state


@pytest.mark.parametrize(
    "raw",
    [
        # http + public host: credential leak risk, rejected
        "http://api.example.com",
        "http://api.zen70.cn:8000",
        "http://10.0.0.5",
        # missing scheme
        "api.example.com",
        # must be an origin, not an UploadLink path or redirect target
        "https://api.example.com/u/upl_secret",
        "https://api.example.com?next=/web",
        "https://api.example.com#fragment",
        # no credentials or malformed ports inside the origin
        "https://user:pass@api.example.com",
        "https://api.example.com:bad",
        # unsupported scheme
        "ftp://api.example.com",
        "file:///etc/passwd",
    ],
)
def test_resolver_rejects_downgrade_or_unscoped_values(raw: str) -> None:
    assert _resolve_public_base_url(raw) == ""


@pytest.mark.parametrize(
    "raw",
    [
        "https://127.1",
        "https://2130706433",
        "https://0177.0.0.1",
        "https://0x7f000001",
        "https://[::ffff:127.0.0.1]",
        "https://api.example.com:0",
    ],
)
def test_mobile_endpoint_rejects_ambiguous_loopback_or_unusable_port(raw: str) -> None:
    assert _resolve_public_base_url(raw) == raw
    assert configured_mobile_endpoint_url(raw) is None
    assert installation_mobile_capabilities(raw).mobile_endpoint_state == "local_only"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://family.cloudflareaccess.com", "https://family.cloudflareaccess.com"),
        (" https://family.cloudflareaccess.com/ ", "https://family.cloudflareaccess.com"),
    ],
)
def test_cloudflare_access_team_domain_accepts_cloudflare_origin(
    raw: str,
    expected: str,
) -> None:
    assert _resolve_cloudflare_access_team_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "http://family.cloudflareaccess.com",
        "https://family.cloudflareaccess.com/path",
        "https://family.cloudflareaccess.com?aud=x",
        "https://user:pass@family.cloudflareaccess.com",
        "https://family.cloudflareaccess.com:443",
        "https://family.cloudflareaccess.com:bad",
        "https://api.example.com",
    ],
)
def test_cloudflare_access_team_domain_rejects_non_origin_or_non_access_host(
    raw: str | None,
) -> None:
    assert _resolve_cloudflare_access_team_domain(raw) == ""
