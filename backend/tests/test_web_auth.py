"""/web/auth/* — browser login + logout via pairing code (PR-3 infra).

This PR adds the cookie session infrastructure. PR-4 is what flips other
/web routes to consume the cookie; until then loopback Owner Console
keeps working unchanged.

The tests below verify:
- The login form renders.
- A valid pairing code yields a __Host-session cookie with the right
  security attributes.
- Bad / expired / used codes redirect back to the login page with an
  error query param (no cookie set).
- whoami round-trips: setting the cookie lets the protected endpoint
  return the bound account/ledger; clearing it yields 401.
- Logout revokes the underlying AuthToken row (defense-in-depth: cookie
  replay also dies server-side).
- next= open-redirect: only same-site /web/... allowed.
"""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, Device
from app.routes.web_auth import (
    SESSION_COOKIE_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    _safe_next_url,
)
from app.routes.web_common import _safe_same_site_redirect_path, _with_ledger
from app.services.identity_service import hash_secret
from app.services.time_service import ensure_utc, now_utc


def _request_pairing_code(client: TestClient, *, identity) -> str:
    resp = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["pairing_code"]


def test_login_form_renders(client: TestClient) -> None:
    resp = client.get("/web/auth/login")
    assert resp.status_code == 200
    assert "绑定码" in resp.text
    assert 'action="/web/auth/login"' in resp.text


def test_login_form_shows_error_param(client: TestClient) -> None:
    resp = client.get("/web/auth/login?error=invalid_pairing_code")
    assert resp.status_code == 200
    assert "绑定码不正确" in resp.text


def test_valid_pairing_code_sets_secure_session_cookie(client: TestClient, *, identity) -> None:
    before = now_utc()
    code = _request_pairing_code(client, identity=identity)
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "我的笔记本"},
        follow_redirects=False,
    )
    after = now_utc()
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web"
    cookie_header = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in cookie_header, cookie_header
    # __Host- prefix requires Secure + Path=/, no Domain.
    assert "Secure" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/" in cookie_header
    assert "samesite=strict" in cookie_header.lower()
    assert "Domain=" not in cookie_header
    token = _extract_session_cookie(resp)
    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token))
        )
        assert row is not None
        expires_at = ensure_utc(row.expires_at)
        assert expires_at is not None
        assert expires_at >= before + timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS)
        assert expires_at <= after + timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS)


def test_login_redirects_to_safe_next_only(client: TestClient, *, identity) -> None:
    code = _request_pairing_code(client, identity=identity)
    # External URL is rejected → falls back to /web
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "next": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web"


def test_login_honors_internal_next(client: TestClient, *, identity) -> None:
    code = _request_pairing_code(client, identity=identity)
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "next": "/web/pending"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/pending"


def test_invalid_pairing_code_redirects_with_error(client: TestClient) -> None:
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": "00000000"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=invalid_pairing_code" in resp.headers["location"]
    assert SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")


def test_non_8_digit_code_rejected_before_call(client: TestClient) -> None:
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": "abc"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=invalid_pairing_code" in resp.headers["location"]


def test_whoami_returns_401_without_cookie(client: TestClient) -> None:
    resp = client.get("/web/auth/whoami")
    assert resp.status_code == 401


def test_whoami_rejects_android_app_token_in_web_cookie_without_revoking(
    client: TestClient, *, identity
) -> None:
    resp = client.get(
        "/web/auth/whoami",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={identity.app_token}"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token))
        )
        assert row is not None
        device = db.get(Device, row.device_id)
        assert device is not None
        assert device.platform == "android"
        assert row.revoked_at is None


def _extract_session_cookie(response) -> str:
    set_cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie, set_cookie
    # Header format: "__Host-session=<token>; HttpOnly; Max-Age=...; ..."
    return set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]


def test_whoami_round_trips_after_login(client: TestClient, *, identity) -> None:
    # TestClient.base_url is http://, which means it won't preserve a
    # Secure cookie across requests. Extract the value from Set-Cookie
    # and pass it back as an explicit Cookie header so we exercise the
    # real read path. (Real browsers see api.zen70.cn over HTTPS and
    # preserve the cookie automatically — this is a testclient quirk.)
    code = _request_pairing_code(client, identity=identity)
    login = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "PyTest 浏览器"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    token = _extract_session_cookie(login)
    resp = client.get(
        "/web/auth/whoami",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 200, resp.text
    body = json.loads(resp.text)
    assert body["account_name"] == "我"
    assert body["ledger_id"] == "owner"
    assert body["role"] == "owner"


def test_whoami_rejects_server_side_expired_cookie(client: TestClient, *, identity) -> None:
    code = _request_pairing_code(client, identity=identity)
    login = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "PyTest 浏览器"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    token = _extract_session_cookie(login)

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token))
        )
        assert row is not None
        expired = now_utc() - timedelta(seconds=SESSION_COOKIE_MAX_AGE_SECONDS + 1)
        row.created_at = expired
        row.expires_at = expired
        row.last_used_at = expired
        db.commit()

    resp = client.get(
        "/web/auth/whoami",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token))
        )
        assert row is not None
        assert row.revoked_at is not None


def test_logout_revokes_auth_token_server_side(client: TestClient, *, identity) -> None:
    code = _request_pairing_code(client, identity=identity)
    login = client.post(
        "/web/auth/login",
        data={"pairing_code": code},
        follow_redirects=False,
    )
    assert login.status_code == 303
    token_value = _extract_session_cookie(login)

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value))
        )
        assert row is not None
        assert row.revoked_at is None

    logout = client.post(
        "/web/auth/logout",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token_value}"},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/web/auth/login"

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value))
        )
        assert row is not None
        assert row.revoked_at is not None

    # And the protected endpoint refuses the now-revoked cookie.
    resp = client.get(
        "/web/auth/whoami",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token_value}"},
    )
    assert resp.status_code == 401


def test_logout_ignores_android_app_token_in_web_cookie(client: TestClient, *, identity) -> None:
    logout = client.post(
        "/web/auth/logout",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={identity.app_token}"},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/web/auth/login"
    set_cookie = logout.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "Max-Age=0" in set_cookie or set_cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].startswith(";")

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token))
        )
        assert row is not None
        assert row.revoked_at is None


def test_safe_next_url_helper() -> None:
    # Allowed
    assert _safe_next_url("/web") == "/web"
    assert _safe_next_url("/web/pending") == "/web/pending"
    assert _safe_next_url("  /web/confirmed  ") == "/web/confirmed"
    # Rejected
    assert _safe_next_url(None) == ""
    assert _safe_next_url("") == ""
    assert _safe_next_url("https://evil.example.com") == ""
    assert _safe_next_url("//evil.example.com/path") == ""
    assert _safe_next_url("/web//evil.example.com") == ""
    assert _safe_next_url("/api/admin/devices") == ""
    assert _safe_next_url("/web\nLocation: evil") == ""
    assert _safe_next_url("/web:8000") == ""
    assert _safe_next_url("https:/evil.example.com") == ""
    assert _safe_next_url("/web/%5c%5cevil.example.com") == ""


def test_web_redirect_helpers_keep_locations_same_site() -> None:
    target = _with_ledger("/web/pending", "owner", msg="已保存。")
    assert target == "/web/pending?ledger_id=owner&msg=%E5%B7%B2%E4%BF%9D%E5%AD%98%E3%80%82"
    assert _safe_same_site_redirect_path("//evil.example.com", fallback="/web") == "/web"
    assert _safe_same_site_redirect_path("https:/evil.example.com", fallback="/web") == "/web"
    assert _safe_same_site_redirect_path("/web/%5c%5cevil.example.com", fallback="/web") == "/web"
