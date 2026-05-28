from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import AuthToken, BootstrapSecretConsumption, Device, PairingCode, UploadLink
from app.routes import bootstrap as bootstrap_route
from app.services.identity_service import hash_pairing_code, hash_secret
from app.services.time_service import ensure_utc, now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import TEST_APP_TOKEN, TEST_UPLOAD_TOKEN


def test_health_and_auth_contract(client: TestClient, *, identity) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    health_body = health.json()
    assert health_body == {"status": "ok"}

    private_status_anon = client.get("/api/status/private")
    assert private_status_anon.status_code == 401
    assert private_status_anon.json()["error"] == "invalid_token"

    private_status = client.get("/api/status/private", headers=identity.app_headers)
    assert private_status.status_code == 200
    private_body = private_status.json()
    assert private_body["status"] == "ok"
    from app.version import BACKEND_VERSION
    assert private_body["backend_version"] == BACKEND_VERSION
    assert private_body["identity_schema"] == "v0.3"
    assert private_body["database_status"] in {"ok", "missing"}
    assert private_body["upload_dir_status"] in {"ok", "missing"}
    for value in private_body.values():
        if isinstance(value, str):
            assert ":\\" not in value, value
            assert not value.startswith("/"), value

    response = client.get("/api/auth/check", headers=identity.app_headers)
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
    try:
        yield secret
    finally:
        with SessionLocal() as db:
            db.query(BootstrapSecretConsumption).delete()
            db.commit()
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
    with SessionLocal() as db:
        bootstrap_route._mark_secret_consumed(db, http_bootstrap_enabled)

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
        get_settings.cache_clear()


def test_bootstrap_owner_rolls_back_if_pairing_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.identity_service as identity_service
    from app.database import Base, engine, init_db

    secret = "rollback-bootstrap-secret"
    monkeypatch.setenv("ENABLE_HTTP_BOOTSTRAP", "true")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", secret)
    get_settings.cache_clear()

    Base.metadata.drop_all(bind=engine)
    init_db()

    def fail_pairing_creation(*args, **kwargs):
        raise RuntimeError("pairing creation failed")

    # _bootstrap module imports _create_pairing_code from _device; patch the
    # bind site that bootstrap_owner actually reads to make the monkey-patch land.
    monkeypatch.setattr(identity_service._bootstrap, "_create_pairing_code", fail_pairing_creation)

    try:
        with TestClient(app) as fresh_client, pytest.raises(RuntimeError, match="pairing creation failed"):
            fresh_client.post(
                "/api/bootstrap/owner",
                headers={"X-Bootstrap-Secret": secret},
                json={"account_name": "owner", "ledger_name": "home"},
            )

        with SessionLocal() as db:
            assert db.query(AuthToken).count() == 0
            assert db.query(UploadLink).count() == 0
            assert db.query(PairingCode).count() == 0
            assert db.query(BootstrapSecretConsumption).count() == 0
    finally:
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
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 200
    pairing = response.json()
    assert pairing["ledger_name"] == "我的小票夹"
    assert pairing["pairing_code"].isdigit()
    assert len(pairing["pairing_code"]) == 8

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


def _new_pairing_code(client: TestClient, *, identity) -> str:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 200, response.text
    return response.json()["pairing_code"]


def _pair_token(client: TestClient, *, code: str, platform: str, name: str) -> str:
    response = client.post(
        "/api/auth/pair",
        json={"pairing_code": code, "device_name": name, "platform": platform},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]


def test_repair_revokes_old_same_platform_app_tokens(client: TestClient, *, identity) -> None:
    old_token = identity.app_token
    new_token = _pair_token(
        client,
        code=_new_pairing_code(client, identity=identity),
        platform="android",
        name="replacement android",
    )

    with SessionLocal() as db:
        old_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(old_token)).one()
        new_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(new_token)).one()
        assert old_row.revoked_at is not None
        assert new_row.revoked_at is None


def test_repair_revokes_blank_platform_tokens_by_stored_platform(client: TestClient, *, identity) -> None:
    first_token = _pair_token(
        client,
        code=_new_pairing_code(client, identity=identity),
        platform="   ",
        name="unknown platform first",
    )
    second_token = _pair_token(
        client,
        code=_new_pairing_code(client, identity=identity),
        platform="\t",
        name="unknown platform second",
    )

    with SessionLocal() as db:
        first_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(first_token)).one()
        second_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(second_token)).one()
        second_device = db.get(Device, second_row.device_id)
        assert second_device is not None
        assert second_device.platform == "unknown"
        assert first_row.revoked_at is not None
        assert second_row.revoked_at is None


def test_repair_preserves_cross_platform_tokens_and_web_ttl(
    client: TestClient, *, identity
) -> None:
    web_token = _pair_token(
        client,
        code=_new_pairing_code(client, identity=identity),
        platform="web",
        name="family browser",
    )
    android_token = identity.app_token
    with SessionLocal() as db:
        web_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(web_token)).one()
        android_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(android_token)).one()
        web_expires_at = ensure_utc(web_row.expires_at)
        assert web_expires_at is not None
        assert android_row.revoked_at is None

    replacement_android = _pair_token(
        client,
        code=_new_pairing_code(client, identity=identity),
        platform="android",
        name="replacement android",
    )

    with SessionLocal() as db:
        web_row = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(web_token)).one()
        old_android = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(android_token)).one()
        new_android = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(replacement_android)).one()
        assert web_row.revoked_at is None
        assert ensure_utc(web_row.expires_at) == web_expires_at
        assert old_android.revoked_at is not None
        assert new_android.revoked_at is None


def test_app_owner_token_cannot_create_bootstrap_pairing_code(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.app_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_pairing_codes_rejects_public_host_even_with_admin_token(
    client: TestClient, *, identity,
) -> None:
    # Even with a valid admin token, the pairing-code creation endpoint must
    # refuse requests forwarded from a public Host (e.g. through Cloudflare
    # Tunnel). Mirrors the guard already in place on /api/admin/* and
    # /api/maintenance/*. See ENGINEERING_RULES §14 暴露面与边界.
    from app.network_boundary import require_admin_network_boundary

    app.dependency_overrides.pop(require_admin_network_boundary, None)
    try:
        response = client.post(
            "/api/bootstrap/pairing-codes",
            headers={**identity.admin_headers, "host": "api.example.com"},
            json={"ttl_minutes": 15},
        )
    finally:
        app.dependency_overrides[require_admin_network_boundary] = lambda: None

    assert response.status_code == 403
    assert response.json()["error"] == "admin_api_local_only"


def test_pairing_code_expires(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes", headers=identity.admin_headers, json={"ttl_minutes": 1}
    )
    assert response.status_code == 200
    code = response.json()["pairing_code"]
    with SessionLocal() as db:
        pairing = (
            db.query(PairingCode)
            .filter(PairingCode.code_hash == hash_pairing_code(code))
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


def test_framework_errors_use_uniform_chinese_shape(client: TestClient, *, identity) -> None:
    response = client.get("/api/not-exists", headers=identity.app_headers)
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "route_not_found"
    assert body["message"] == "没有找到这个功能入口。"

    response = client.post("/api/health")
    assert response.status_code == 405
    body = response.json()
    assert body["error"] == "method_not_allowed"
    assert body["message"] == "这个入口不支持当前操作。"
