from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import AuthToken, PairingCode, UploadLink
from app.routes import bootstrap as bootstrap_route
from app.services.identity_service import hash_secret
from app.services.time_service import now_utc
from conftest import (
    PNG_BYTES,
    TEST_APP_TOKEN,
    TEST_UPLOAD_TOKEN,
    admin_headers,
    app_headers,
)


def test_health_and_auth_contract(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body["status"] == "ok"
    # v0.3.1-alpha2: health surfaces version + identity schema info but must
    # not leak absolute filesystem paths.
    assert health_body["backend_version"] == "0.9.0a1"
    assert health_body["identity_schema"] == "v0.3"
    assert health_body["database_status"] in {"ok", "missing"}
    assert health_body["upload_dir_status"] in {"ok", "missing"}
    for value in health_body.values():
        if isinstance(value, str):
            assert ":\\" not in value, value
            assert not value.startswith("/"), value

    response = client.get("/api/auth/check", headers=app_headers())
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "account_name": "我",
        "ledger_id": "owner",
        "ledger_name": "我的小票夹",
        "device_name": "pytest-android",
        "role": "owner",
        "scope": "app",
    }

    response = client.get(
        "/api/auth/check", headers={"Authorization": f"Bearer {TEST_APP_TOKEN}"}
    )
    assert response.status_code == 401
    assert response.json()["error"] == "legacy_auth_removed"
    assert response.json()["message"]


def test_tokens_are_hashed_and_legacy_tokens_are_rejected(client: TestClient) -> None:
    with SessionLocal() as db:
        assert (
            db.query(AuthToken).filter(AuthToken.token_hash == TEST_APP_TOKEN).count()
            == 0
        )
        assert (
            db.query(UploadLink)
            .filter(UploadLink.token_hash == TEST_UPLOAD_TOKEN)
            .count()
            == 0
        )
        assert (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(TEST_APP_TOKEN))
            .count()
            == 0
        )
        assert (
            db.query(UploadLink)
            .filter(UploadLink.token_hash == hash_secret(TEST_UPLOAD_TOKEN))
            .count()
            == 0
        )

    app_response = client.get(
        "/api/auth/check", headers={"Authorization": f"Bearer {TEST_APP_TOKEN}"}
    )
    assert app_response.status_code == 401
    assert app_response.json()["error"] == "legacy_auth_removed"

    upload_response = client.post(
        "/api/upload-screenshot",
        headers={"Upload-Token": TEST_UPLOAD_TOKEN, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert upload_response.status_code == 401
    assert upload_response.json()["error"] == "legacy_auth_removed"


def test_bootstrap_owner_disabled_by_default(client: TestClient) -> None:
    # Default config has ENABLE_HTTP_BOOTSTRAP=false. Public callers (including
    # Cloudflare Tunnel traffic that arrives via loopback) must be rejected.
    response = client.post("/api/bootstrap/owner", json={})
    assert response.status_code == 404
    assert response.json()["error"] == "bootstrap_disabled"

    with TestClient(app, client=("203.0.113.10", 50000)) as remote_client:
        remote_response = remote_client.post("/api/bootstrap/owner", json={})
    assert remote_response.status_code == 404
    assert remote_response.json()["error"] == "bootstrap_disabled"


@pytest.fixture
def http_bootstrap_enabled(monkeypatch: pytest.MonkeyPatch):
    secret = "unit-test-bootstrap-secret"
    monkeypatch.setenv("ENABLE_HTTP_BOOTSTRAP", "true")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", secret)
    get_settings.cache_clear()
    bootstrap_route._CONSUMED_BOOTSTRAP_SECRETS.clear()
    try:
        yield secret
    finally:
        bootstrap_route._CONSUMED_BOOTSTRAP_SECRETS.clear()
        get_settings.cache_clear()


def test_bootstrap_owner_enabled_requires_secret_header(
    client: TestClient, http_bootstrap_enabled: str
) -> None:
    response = client.post("/api/bootstrap/owner", json={})
    assert response.status_code == 401
    assert response.json()["error"] == "bootstrap_secret_required"


def test_bootstrap_owner_enabled_rejects_wrong_secret(
    client: TestClient, http_bootstrap_enabled: str
) -> None:
    response = client.post(
        "/api/bootstrap/owner",
        headers={"X-Bootstrap-Secret": "wrong-secret"},
        json={},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_bootstrap_secret"


def test_bootstrap_owner_secret_is_one_shot(
    client: TestClient, http_bootstrap_enabled: str
) -> None:
    # The HTTP route normally returns bootstrap_already_initialized in this
    # test session because conftest seeds an owner via the service layer. Mark
    # the secret as consumed directly so we can verify that, even without an
    # already-initialized owner, a previously consumed secret is rejected.
    bootstrap_route._mark_secret_consumed(http_bootstrap_enabled)

    response = client.post(
        "/api/bootstrap/owner",
        headers={"X-Bootstrap-Secret": http_bootstrap_enabled},
        json={"account_name": "我", "ledger_name": "我的小票夹"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_bootstrap_secret"


def test_bootstrap_owner_accepts_valid_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End-to-end: with a fresh database and a valid secret, the HTTP endpoint
    # must succeed. A second call with the same secret must be rejected as a
    # consumed one-shot secret. We bypass the conftest `client` fixture so the
    # database starts empty (no pre-seeded owner).
    from app.database import Base, engine, init_db

    secret = "e2e-bootstrap-secret"
    monkeypatch.setenv("ENABLE_HTTP_BOOTSTRAP", "true")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", secret)
    get_settings.cache_clear()
    bootstrap_route._CONSUMED_BOOTSTRAP_SECRETS.clear()

    Base.metadata.drop_all(bind=engine)
    init_db()

    try:
        with TestClient(app) as fresh_client:
            first = fresh_client.post(
                "/api/bootstrap/owner",
                headers={"X-Bootstrap-Secret": secret},
                json={"account_name": "我", "ledger_name": "我的小票夹"},
            )
            assert first.status_code == 200, first.text
            assert "admin_token" in first.json()

            second = fresh_client.post(
                "/api/bootstrap/owner",
                headers={"X-Bootstrap-Secret": secret},
                json={},
            )
            assert second.status_code == 401
            assert second.json()["error"] == "invalid_bootstrap_secret"
    finally:
        bootstrap_route._CONSUMED_BOOTSTRAP_SECRETS.clear()
        get_settings.cache_clear()


def test_upload_check_contract(client: TestClient) -> None:
    response = client.get(
        "/api/upload/check", headers={"Upload-Token": TEST_UPLOAD_TOKEN}
    )
    assert response.status_code == 401
    assert response.json()["error"] == "legacy_auth_removed"

    response = client.get("/api/upload/check", headers={"Upload-Token": "bad"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_owner_can_create_pairing_code_and_android_can_pair_once(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=admin_headers(),
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 200
    pairing = response.json()
    assert pairing["ledger_name"] == "我的小票夹"
    assert pairing["pairing_code"].isdigit()
    assert len(pairing["pairing_code"]) == 6

    paired = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": pairing["pairing_code"],
            "device_name": "小米 15 Pro",
            "platform": "android",
        },
    )
    assert paired.status_code == 200
    payload = paired.json()
    assert payload["session_token"].startswith("tbx_")
    assert payload["account_name"] == "我"
    assert payload["ledger_name"] == "我的小票夹"
    assert payload["device_name"] == "小米 15 Pro"
    assert payload["role"] == "owner"

    check = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {payload['session_token']}"},
    )
    assert check.status_code == 200
    assert check.json()["device_name"] == "小米 15 Pro"

    reused = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": pairing["pairing_code"],
            "device_name": "小米 15 Pro",
            "platform": "android",
        },
    )
    assert reused.status_code == 409
    assert reused.json()["error"] == "pairing_code_used"


def test_pairing_code_expires(client: TestClient) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes", headers=admin_headers(), json={"ttl_minutes": 1}
    )
    assert response.status_code == 200
    code = response.json()["pairing_code"]
    with SessionLocal() as db:
        pairing = (
            db.query(PairingCode)
            .filter(PairingCode.code_hash == hash_secret(code))
            .one()
        )
        pairing.expires_at = now_utc() - timedelta(minutes=1)
        db.commit()

    expired = client.post(
        "/api/auth/pair",
        json={"pairing_code": code, "device_name": "过期设备", "platform": "android"},
    )
    assert expired.status_code == 410
    assert expired.json()["error"] == "pairing_code_expired"


def test_framework_errors_use_uniform_chinese_shape(client: TestClient) -> None:
    response = client.get("/api/not-exists", headers=app_headers())
    assert response.status_code == 404
    assert response.json() == {"error": "route_not_found", "message": "没有找到这个功能入口。"}

    response = client.post("/api/health")
    assert response.status_code == 405
    assert response.json() == {
        "error": "method_not_allowed",
        "message": "这个入口不支持当前操作。",
    }
