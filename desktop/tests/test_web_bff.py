"""Security matrix for the Manager same-origin Web BFF."""

from __future__ import annotations

import pytest

from backend_manager.web_bff import (
    SESSION_COOKIE,
    allowed_target,
    browser_session_valid,
    same_origin_request,
)


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("GET", "/web"),
        ("HEAD", "/web/confirmed?month=2026-07"),
        ("POST", "/web/expenses/new"),
        ("PUT", "/api/me/ui-preferences"),
        ("GET", "/static/web/product/shell.css"),
        ("HEAD", "/static/shared/tokens.css"),
    ],
)
def test_web_bff_allows_only_product_surface(method: str, target: str) -> None:
    assert allowed_target(target, method) is not None


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("GET", "/web/auth"),
        ("GET", "/web/auth/pair"),
        ("GET", "/owner"),
        ("GET", "/desktop"),
        ("GET", "/api/expenses"),
        ("GET", "/api/admin"),
        ("GET", "/api/me/ui-preferences"),
        ("POST", "/api/me/ui-preferences"),
        ("PUT", "/api/me/ui-preferences/"),
        ("PUT", "/api/me/ui-preferences?scope=desktop"),
        ("PUT", "/api/me/ui-preferences/extra"),
        ("GET", "/static/owner/app.css"),
        ("POST", "/static/web/app.js"),
        ("PUT", "/web/confirmed"),
        ("GET", "http://127.0.0.1/web"),
        ("GET", "//127.0.0.1/web"),
        ("GET", "/web/%2e%2e/api"),
        ("GET", "/web/%252e%252e/api"),
        ("GET", r"/web\..\api"),
        ("GET", "/web/%5c../api"),
    ],
)
def test_web_bff_rejects_privileged_and_ambiguous_targets(
    method: str,
    target: str,
) -> None:
    assert allowed_target(target, method) is None


def test_web_bff_session_and_same_origin_matrix() -> None:
    secret = "high-entropy-process-session"
    origin = "http://127.0.0.1:8799"
    assert browser_session_valid(f"{SESSION_COOKIE}={secret}; ui_theme=mono", secret)
    assert not browser_session_valid(f"{SESSION_COOKIE}=wrong", secret)
    assert same_origin_request(
        method="POST",
        origin=origin,
        referer=None,
        sec_fetch_site="same-origin",
        manager_origin=origin,
    )
    assert same_origin_request(
        method="PUT",
        origin=origin,
        referer=None,
        sec_fetch_site="same-origin",
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="POST",
        origin="https://attacker.invalid",
        referer=None,
        sec_fetch_site="cross-site",
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="POST",
        origin=None,
        referer=None,
        sec_fetch_site=None,
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="PUT",
        origin="https://attacker.invalid",
        referer=None,
        sec_fetch_site="cross-site",
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="PUT",
        origin=None,
        referer=None,
        sec_fetch_site=None,
        manager_origin=origin,
    )
