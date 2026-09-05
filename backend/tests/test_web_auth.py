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
    PAIRING_ATTEMPT_COOKIE_NAME,
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


def _pairing_attempt_cookie_header(client: TestClient) -> dict[str, str]:
    form = client.get("/web/auth/login")
    assert form.status_code == 200
    attempt = form.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME)
    assert attempt is not None
    return {"Cookie": f"{PAIRING_ATTEMPT_COOKIE_NAME}={attempt}"}


def test_login_form_renders(client: TestClient) -> None:
    resp = client.get("/web/auth/login")
    assert resp.status_code == 200
    assert "连接小票夹" in resp.text
    assert "连接码" in resp.text
    assert "设备名称（可选）" in resp.text
    assert ">连接</button>" in resp.text
    assert "连接码只授权这台设备" in resp.text
    assert "APP_TOKEN" not in resp.text
    assert 'type="password"' not in resp.text
    assert 'action="/web/auth/login"' in resp.text
    # 品牌 mark 单 img SSR: 只渲染当前 colorway 一枚 (双 img 的 display:none
    # 仍会双下载); theme.js 运行时只从受信任资产映射切换。
    # login 无主题开关, 只消费 SSR。
    assert resp.text.count('class="brand-mark-img"') == 1
    assert 'src="/static/web/product/brand/brand-mark.png"' in resp.text
    assert "data-src-" not in resp.text
    # 外观 bootstrap 是 CSP 合规的外部脚本 (inline 在 script-src 'self' 下必死),
    # login 与 app 页共享, 首屏前恢复 ui-texture / ui-accent 本地偏好。
    assert '<script src="/static/web/appearance-bootstrap.js' in resp.text
    cookie_header = resp.headers.get("set-cookie", "")
    assert PAIRING_ATTEMPT_COOKIE_NAME in cookie_header
    assert "Secure" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/web/auth" in cookie_header
    assert "samesite=strict" in cookie_header.lower()


def test_login_routes_family_invites_to_the_native_join_flow(
    client: TestClient,
) -> None:
    response = client.get("/web/auth/login")

    assert response.status_code == 200
    assert "连接当前已有身份的一台设备" in response.text
    assert 'href="/web/auth/join"' in response.text
    assert "收到家庭邀请" in response.text
    assert "每位家庭成员需要单独的码" not in response.text


def test_login_form_ssr_theme_respects_cookie_under_strict_csp(client: TestClient) -> None:
    response = client.get(
        "/web/auth/login",
        headers={"Cookie": "ui_theme=midnight"},
    )

    assert response.status_code == 200
    assert '<html lang="zh-CN" data-theme="midnight">' in response.text
    # midnight SSR 直出单 img 玄夜色款 (无双下载)。
    assert response.text.count('class="brand-mark-img"') == 1
    assert 'src="/static/web/product/brand/brand-mark-midnight.png"' in response.text
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "document.cookie.match" not in response.text


def test_login_form_shows_error_param(client: TestClient) -> None:
    resp = client.get("/web/auth/login?error=invalid_pairing_code")
    assert resp.status_code == 200
    assert "连接码不正确" in resp.text


def test_login_form_maps_closed_attempt_and_unknown_error_without_leaking_code(
    client: TestClient,
) -> None:
    closed = client.get("/web/auth/login?error=pairing_attempt_closed")
    assert closed.status_code == 200
    assert "这次连接已经结束，请重新获取连接码" in closed.text

    unknown = client.get("/web/auth/login?error=private_backend_detail")
    assert unknown.status_code == 200
    assert "暂时无法连接，请重新获取连接码后再试" in unknown.text
    assert "private_backend_detail" not in unknown.text


def test_valid_pairing_code_sets_secure_session_cookie(client: TestClient, *, identity) -> None:
    before = now_utc()
    attempt_headers = _pairing_attempt_cookie_header(client)
    code = _request_pairing_code(client, identity=identity)
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "我的笔记本"},
        headers=attempt_headers,
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

    replay = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "我的笔记本"},
        headers=attempt_headers,
        follow_redirects=False,
    )
    assert replay.status_code == 303
    assert _extract_session_cookie(replay) == token


def test_blank_browser_name_stores_a_consumer_friendly_device_fact(
    client: TestClient,
    *,
    identity,
) -> None:
    attempt_headers = _pairing_attempt_cookie_header(client)
    attempt_headers["User-Agent"] = "Mozilla/5.0 Raw Browser Runtime Detail"
    code = _request_pairing_code(client, identity=identity)

    response = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": ""},
        headers=attempt_headers,
        follow_redirects=False,
    )

    assert response.status_code == 303
    token = _extract_session_cookie(response)
    with SessionLocal() as db:
        auth_token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token))
        )
        assert auth_token is not None
        device = db.get(Device, auth_token.device_id)
        assert device is not None
        assert device.device_name == "浏览器"


def test_closed_pairing_attempt_cookie_is_cleared_before_next_login(
    client: TestClient,
    *,
    identity,
) -> None:
    attempt_headers = _pairing_attempt_cookie_header(client)
    stale_attempt = attempt_headers["Cookie"].split("=", 1)[1]
    code = _request_pairing_code(client, identity=identity)
    paired = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "浏览器"},
        headers=attempt_headers,
        follow_redirects=False,
    )
    token = _extract_session_cookie(paired)
    with SessionLocal() as db:
        row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert row is not None
        row.revoked_at = now_utc()
        db.commit()

    closed = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "浏览器"},
        headers=attempt_headers,
        follow_redirects=False,
    )

    assert closed.status_code == 303
    assert "error=pairing_attempt_closed" in closed.headers["location"]
    clear_cookie = closed.headers.get("set-cookie", "")
    assert PAIRING_ATTEMPT_COOKIE_NAME in clear_cookie
    assert "Max-Age=0" in clear_cookie
    fresh = client.get("/web/auth/login")
    fresh_attempt = fresh.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME)
    assert fresh_attempt is not None
    assert fresh_attempt != stale_attempt


def test_login_redirects_to_safe_next_only(client: TestClient, *, identity) -> None:
    attempt_headers = _pairing_attempt_cookie_header(client)
    code = _request_pairing_code(client, identity=identity)
    # External URL is rejected → falls back to /web
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "next": "https://evil.example.com"},
        headers=attempt_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web"


def test_login_honors_internal_next(client: TestClient, *, identity) -> None:
    attempt_headers = _pairing_attempt_cookie_header(client)
    code = _request_pairing_code(client, identity=identity)
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "next": "/web/pending"},
        headers=attempt_headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/pending"


def test_invalid_pairing_code_redirects_with_error(client: TestClient) -> None:
    attempt_headers = _pairing_attempt_cookie_header(client)
    resp = client.post(
        "/web/auth/login",
        data={"pairing_code": "00000000"},
        headers=attempt_headers,
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
    attempt_headers = _pairing_attempt_cookie_header(client)
    code = _request_pairing_code(client, identity=identity)
    login = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "PyTest 浏览器"},
        headers=attempt_headers,
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
    attempt_headers = _pairing_attempt_cookie_header(client)
    code = _request_pairing_code(client, identity=identity)
    login = client.post(
        "/web/auth/login",
        data={"pairing_code": code, "device_name": "PyTest 浏览器"},
        headers=attempt_headers,
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
    attempt_headers = _pairing_attempt_cookie_header(client)
    code = _request_pairing_code(client, identity=identity)
    login = client.post(
        "/web/auth/login",
        data={"pairing_code": code},
        headers=attempt_headers,
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
