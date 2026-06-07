"""Public /web security layers: Cloudflare Access, CSRF, headers."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import reset_settings_cache
from app.main import app
from app.middleware import cloudflare_access as cloudflare_access_middleware
from app.services import cloudflare_access_service

PUBLIC_HOST = "api.example.com"


def _public_client() -> TestClient:
    return TestClient(
        app,
        base_url=f"https://{PUBLIC_HOST}",
        client=("203.0.113.10", 50001),
    )


@contextmanager
def _access_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    team_domain: str = "https://family.cloudflareaccess.com",
    aud: str = "access-aud",
) -> Iterator[None]:
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN", team_domain)
    monkeypatch.setenv("CLOUDFLARE_ACCESS_AUD", aud)
    reset_settings_cache()
    try:
        yield
    finally:
        monkeypatch.delenv("CLOUDFLARE_ACCESS_REQUIRED", raising=False)
        monkeypatch.delenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_ACCESS_AUD", raising=False)
        reset_settings_cache()


def _csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


def test_cloudflare_access_required_blocks_public_web_before_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _access_env(monkeypatch):
        pub = _public_client()
        resp = pub.get("/web", follow_redirects=False)

    assert resp.status_code == 403
    assert resp.json()["error"] == "cloudflare_access_required"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]


def test_cloudflare_access_required_blocks_static_web_asset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _access_env(monkeypatch):
        pub = _public_client()
        resp = pub.get("/static/web/web.css")

    assert resp.status_code == 403
    assert resp.json()["error"] == "cloudflare_access_required"


def test_valid_cloudflare_access_jwt_reaches_next_web_session_layer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _verify(token: str, *, team_domain: str, audience: str) -> dict[str, str]:
        assert token == "good-jwt"
        assert team_domain == "https://family.cloudflareaccess.com"
        assert audience == "access-aud"
        return {"sub": "family@example.com"}

    monkeypatch.setattr(cloudflare_access_middleware, "verify_cloudflare_access_jwt", _verify)
    with _access_env(monkeypatch):
        pub = _public_client()
        resp = pub.get(
            "/web",
            headers={"Cf-Access-Jwt-Assertion": "good-jwt"},
            follow_redirects=False,
        )
        login = pub.get(
            "/web/auth/login",
            headers={"Cf-Access-Jwt-Assertion": "good-jwt"},
        )
        asset = pub.get(
            "/static/web/web.css",
            headers={"Cf-Access-Jwt-Assertion": "good-jwt"},
        )

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/auth/login")
    assert login.status_code == 200
    assert asset.status_code == 200


def test_cloudflare_access_required_without_config_is_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _access_env(monkeypatch, team_domain="", aud=""):
        pub = _public_client()
        resp = pub.get("/web/auth/login")

    assert resp.status_code == 503
    assert resp.json()["error"] == "server_error"


def test_cloudflare_access_does_not_gate_true_loopback_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _access_env(monkeypatch, team_domain="", aud=""):
        local = TestClient(
            app,
            base_url="http://127.0.0.1:8000",
            client=("127.0.0.1", 50001),
        )
        resp = local.get("/web/auth/login")
        local.close()

    assert resp.status_code == 200


def test_public_web_login_post_requires_csrf_token(client: TestClient) -> None:
    pub = _public_client()
    form = pub.get("/web/auth/login")
    assert form.status_code == 200
    resp = pub.post(
        "/web/auth/login",
        data={"pairing_code": "00000000", "device_name": "browser"},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_request"


def test_public_web_csrf_secret_missing_fails_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-0045: "missing" now means BOTH no real operator secret (env blank /
    # placeholder) AND no app_meta-persisted key. The persisted key normally covers
    # the placeholder env, so clear it too to reach the genuine fail-closed path.
    from app.middleware import csrf as csrf_mw

    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", "")
    monkeypatch.setenv("APP_TOKEN", "")
    reset_settings_cache()
    saved_key = csrf_mw._persisted_csrf_key
    csrf_mw.set_persisted_csrf_key(None)
    try:
        pub = _public_client()
        resp = pub.get("/web/auth/login")
    finally:
        csrf_mw._persisted_csrf_key = saved_key
        reset_settings_cache()

    assert resp.status_code == 500
    assert resp.json()["error"] == "server_error"


def test_public_web_csrf_persisted_key_covers_placeholder_env(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-0045: with the env secret left at the PUBLIC placeholder default, the
    # per-install app_meta key takes over so /web still renders a CSRF token (no 500).
    from app.config import PLACEHOLDER_ADMIN_TOKEN
    from app.middleware import csrf as csrf_mw

    monkeypatch.setenv("ADMIN_TOKEN", PLACEHOLDER_ADMIN_TOKEN)
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", "")
    monkeypatch.setenv("APP_TOKEN", "")
    reset_settings_cache()
    saved_key = csrf_mw._persisted_csrf_key
    csrf_mw.set_persisted_csrf_key("per-install-csrf-key")
    try:
        pub = _public_client()
        resp = pub.get("/web/auth/login")
    finally:
        csrf_mw._persisted_csrf_key = saved_key
        reset_settings_cache()

    assert resp.status_code == 200
    assert _csrf_token(resp.text)  # a real token rendered from the persisted key


def test_public_web_login_post_requires_same_origin_even_with_csrf(client: TestClient) -> None:
    pub = _public_client()
    form = pub.get("/web/auth/login")
    token = _csrf_token(form.text)
    resp = pub.post(
        "/web/auth/login",
        data={"pairing_code": "00000000", "device_name": "browser", "csrf_token": token},
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_request"


def test_public_web_login_post_with_csrf_reaches_pairing_validation(
    client: TestClient,
) -> None:
    pub = _public_client()
    form = pub.get("/web/auth/login")
    token = _csrf_token(form.text)
    resp = pub.post(
        "/web/auth/login",
        data={"pairing_code": "00000000", "device_name": "browser", "csrf_token": token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=invalid_pairing_code" in resp.headers["location"]


def test_public_web_and_api_security_headers(client: TestClient) -> None:
    pub = _public_client()
    web = pub.get("/web/auth/login")
    health = pub.get("/api/health")

    assert web.headers["X-Frame-Options"] == "DENY"
    assert web.headers["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in web.headers["Content-Security-Policy"]
    assert web.headers["Cache-Control"] == "no-store"
    assert web.headers["Strict-Transport-Security"].startswith("max-age=")

    assert health.json() == {"status": "ok"}
    assert health.headers["X-Frame-Options"] == "DENY"
    assert "object-src 'none'" in health.headers["Content-Security-Policy"]


def test_cloudflare_access_service_validates_rs256_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    token = jwt.encode(
        {
            "sub": "family@example.com",
            "aud": "access-aud",
            "iss": "https://family.cloudflareaccess.com",
        },
        private_key,
        algorithm="RS256",
    )

    monkeypatch.setattr(
        cloudflare_access_service,
        "_jwk_client",
        lambda _certs_url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
        ),
    )

    claims = cloudflare_access_service.verify_cloudflare_access_jwt(
        token,
        team_domain="https://family.cloudflareaccess.com",
        audience="access-aud",
    )
    assert claims["sub"] == "family@example.com"

    with pytest.raises(cloudflare_access_service.CloudflareAccessVerificationError):
        cloudflare_access_service.verify_cloudflare_access_jwt(
            token,
            team_domain="https://family.cloudflareaccess.com",
            audience="wrong-aud",
        )


def test_public_web_csrf_rejects_oversize_body_before_buffering(
    client: TestClient,
) -> None:
    """codex P1 #2: CSRF 中间件 fallback 到 body 解析时不能整包 await request.body(),
    认证用户可超大 multipart 打内存。修后:Content-Length 声明超过 max_upload_size +
    1MB 直接 413, 不进 body 缓冲。"""
    from app.config import get_settings

    pub = _public_client()
    cap = get_settings().max_upload_size_bytes + 1 * 1024 * 1024
    oversize = cap + 1  # 触发 Content-Length 检查

    resp = pub.post(
        "/web/auth/login",
        # 故意不带 X-CSRF-Token header, 也不带 csrf_token form 字段, 强制 CSRF
        # 中间件 fallback 到 body 解析路径。
        headers={
            "Origin": f"https://{PUBLIC_HOST}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(oversize),
        },
        content=b"x",  # 实际 body 比声明小, 但 Content-Length 阶段已拒。
        follow_redirects=False,
    )
    assert resp.status_code == 413
    assert resp.json()["error"] == "file_too_large"
