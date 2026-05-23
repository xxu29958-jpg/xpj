"""Coverage for ``app.config._resolve_public_base_url``.

Owner Console writes PUBLIC_BASE_URL through the form path (validated by
runtime_settings_service); the env-loading path goes through the bare
resolver here. Both paths must refuse public ``http://`` because the
UploadLink URL embeds a credential in the path.
"""

from __future__ import annotations

import pytest

from app.config import _resolve_cloudflare_access_team_domain, _resolve_public_base_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        # https any host: accepted
        ("https://api.example.com", "https://api.example.com"),
        ("https://api.zen70.cn:8443", "https://api.zen70.cn:8443"),
        # http loopback: accepted (local dev)
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://localhost", "http://localhost"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        # trailing slash stripped
        ("https://api.example.com/", "https://api.example.com"),
        # whitespace stripped
        ("  https://api.example.com  ", "https://api.example.com"),
        # empty / None
        (None, ""),
        ("", ""),
        ("   ", ""),
    ],
)
def test_resolver_accepts_safe_values(raw: str | None, expected: str) -> None:
    assert _resolve_public_base_url(raw) == expected


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
