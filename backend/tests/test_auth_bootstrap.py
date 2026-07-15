from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import (
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    DeviceEnrollmentAttempt,
    PairingCode,
    UploadLink,
)
from app.services.identity_service import hash_pairing_code, hash_secret
from app.services.time_service import ensure_utc, now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.bootstrap_recovery import (
    assert_expired_pairing_recovery_fails_closed,
    assert_failure_rolls_back_and_retries,
    assert_response_loss_recovery,
    assert_revoked_admin_recovery_fails_closed,
    assert_used_pairing_recovery_finalizes_existing_identity,
)
from tests._infra.env import TEST_APP_TOKEN, TEST_UPLOAD_TOKEN
from tests.pairing_test_support import pairing_payload


def test_tokens_are_hashed_and_legacy_tokens_are_rejected(client: TestClient) -> None:
    with SessionLocal() as db:
        assert db.query(AuthToken).filter(AuthToken.token_hash == TEST_APP_TOKEN).count() == 0
        assert db.query(UploadLink).filter(UploadLink.token_hash == TEST_UPLOAD_TOKEN).count() == 0
        assert db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(TEST_APP_TOKEN)).count() == 0
        assert db.query(UploadLink).filter(UploadLink.token_hash == hash_secret(TEST_UPLOAD_TOKEN)).count() == 0

    app_response = client.get("/api/auth/check", headers={"Authorization": f"Bearer {TEST_APP_TOKEN}"})
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
    secret = "unit-test-bootstrap-secret-with-32-byte-minimum"
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


def test_bootstrap_owner_rejects_weak_configured_secret(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_HTTP_BOOTSTRAP", "true")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", "human-password")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/bootstrap/owner",
            headers={"X-Bootstrap-Secret": "human-password"},
            json={},
        )
        assert response.status_code == 404
        assert response.json()["error"] == "bootstrap_disabled"
    finally:
        get_settings.cache_clear()


def test_bootstrap_owner_enabled_requires_secret_header(client: TestClient, http_bootstrap_enabled: str) -> None:
    response = client.post("/api/bootstrap/owner", json={})
    assert response.status_code == 401
    assert response.json()["error"] == "bootstrap_secret_required"


def test_bootstrap_owner_enabled_rejects_wrong_secret(client: TestClient, http_bootstrap_enabled: str) -> None:
    response = client.post(
        "/api/bootstrap/owner",
        headers={"X-Bootstrap-Secret": "wrong-secret"},
        json={},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_bootstrap_secret"

    # A valid but previously unused secret must still respect an owner that
    # came from another bootstrap path, and the rejected attempt must not burn it.
    existing_owner = client.post(
        "/api/bootstrap/owner",
        headers={"X-Bootstrap-Secret": http_bootstrap_enabled},
        json={},
    )
    assert existing_owner.status_code == 409
    assert existing_owner.json()["error"] == "bootstrap_already_initialized"
    with SessionLocal() as db:
        assert (
            db.query(BootstrapSecretConsumption)
            .filter(BootstrapSecretConsumption.secret_hash == hash_secret(http_bootstrap_enabled))
            .count()
            == 0
        )


def test_bootstrap_owner_secret_is_one_shot(client: TestClient, http_bootstrap_enabled: str) -> None:
    # A consumption row alone is not a recovery grant. The derived credential
    # hashes must prove that this exact secret completed the bootstrap ceremony.
    with SessionLocal() as db:
        db.add(BootstrapSecretConsumption(secret_hash=hash_secret(http_bootstrap_enabled)))
        db.commit()

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
    assert_response_loss_recovery(monkeypatch)


def test_bootstrap_owner_rolls_back_if_pairing_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_failure_rolls_back_and_retries(monkeypatch)


def test_bootstrap_owner_delayed_recovery_rejects_expired_pairing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_expired_pairing_recovery_fails_closed(monkeypatch)


def test_bootstrap_owner_recovery_finalizes_after_pairing_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_used_pairing_recovery_finalizes_existing_identity(monkeypatch)


def test_bootstrap_owner_recovery_rejects_revoked_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_revoked_admin_recovery_fails_closed(monkeypatch)


def test_bootstrap_owner_rejects_new_identity_after_all_tokens_revoked(
    client: TestClient,
    http_bootstrap_enabled: str,
) -> None:
    revoked_at = now_utc()
    with SessionLocal() as db:
        before = {
            "tokens": db.query(AuthToken).count(),
            "devices": db.query(Device).count(),
            "uploads": db.query(UploadLink).count(),
            "pairings": db.query(PairingCode).count(),
        }
        db.query(AuthToken).update({AuthToken.revoked_at: revoked_at})
        db.commit()

    response = client.post(
        "/api/bootstrap/owner",
        headers={"X-Bootstrap-Secret": http_bootstrap_enabled},
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "bootstrap_already_initialized"
    with SessionLocal() as db:
        assert db.query(AuthToken).count() == before["tokens"]
        assert db.query(Device).count() == before["devices"]
        assert db.query(UploadLink).count() == before["uploads"]
        assert db.query(PairingCode).count() == before["pairings"]
        assert (
            db.query(BootstrapSecretConsumption)
            .filter(BootstrapSecretConsumption.secret_hash == hash_secret(http_bootstrap_enabled))
            .count()
            == 0
        )


def test_upload_check_contract(client: TestClient) -> None:
    response = client.get("/api/upload/check", headers={"Upload-Token": TEST_UPLOAD_TOKEN})
    assert response.status_code == 401
    assert response.json()["error"] == "legacy_auth_removed"

    response = client.get("/api/upload/check", headers={"Upload-Token": "bad"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_owner_can_create_pairing_code_and_android_can_pair_once(
    client: TestClient,
    *,
    identity,
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

    request_payload = pairing_payload(
        pairing["pairing_code"],
        device_name="小米 15 Pro",
    )
    paired = client.post("/api/auth/pair", json=request_payload)
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

    replayed = client.post("/api/auth/pair", json=request_payload)
    assert replayed.status_code == 200
    assert replayed.json()["session_token"] == payload["session_token"]
    assert replayed.json()["device_public_id"] == payload["device_public_id"]

    different_attempt = client.post(
        "/api/auth/pair",
        json=pairing_payload(pairing["pairing_code"], device_name="小米 15 Pro"),
    )
    assert different_attempt.status_code == 401
    assert different_attempt.json()["error"] == "invalid_pairing_code"


def test_pairing_receipt_survives_past_24_hours_while_session_is_active(
    client: TestClient,
    *,
    identity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 200, response.text
    request = pairing_payload(
        response.json()["pairing_code"],
        device_name="long offline recovery",
    )
    first = client.post("/api/auth/pair", json=request)
    assert first.status_code == 200, first.text

    with SessionLocal() as db:
        attempt = db.query(DeviceEnrollmentAttempt).filter(
            DeviceEnrollmentAttempt.public_id == request["pairing_attempt_id"]
        ).one()
        token = db.query(AuthToken).filter(
            AuthToken.token_hash == hash_secret(first.json()["session_token"])
        ).one()
        assert ensure_utc(attempt.expires_at) == ensure_utc(token.expires_at)
        assert ensure_utc(attempt.expires_at) > now_utc() + timedelta(hours=25)

    future = now_utc() + timedelta(hours=25)
    monkeypatch.setattr(
        "app.services.identity_service._enrollment.now_utc",
        lambda: future,
    )
    replay = client.post("/api/auth/pair", json=request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["session_token"] == first.json()["session_token"]
    assert replay.json()["device_public_id"] == first.json()["device_public_id"]


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
        json=pairing_payload(code, device_name=name, platform=platform),
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]


def test_pairing_preserves_other_same_platform_device_sessions(client: TestClient, *, identity) -> None:
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
        assert old_row.revoked_at is None
        assert new_row.revoked_at is None


def test_pairing_preserves_other_unknown_platform_device_sessions(client: TestClient, *, identity) -> None:
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
        assert first_row.revoked_at is None
        assert second_row.revoked_at is None


def test_repair_preserves_cross_platform_tokens_and_web_ttl(client: TestClient, *, identity) -> None:
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
        assert old_android.revoked_at is None
        assert new_android.revoked_at is None


def test_app_owner_token_cannot_create_bootstrap_pairing_code(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.app_headers,
        json={"ttl_minutes": 15},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"


def test_pairing_codes_rejects_public_host_even_with_admin_token(
    client: TestClient,
    *,
    identity,
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
    response = client.post("/api/bootstrap/pairing-codes", headers=identity.admin_headers, json={"ttl_minutes": 1})
    assert response.status_code == 200
    code = response.json()["pairing_code"]
    with SessionLocal() as db:
        pairing = db.query(PairingCode).filter(PairingCode.code_hash == hash_pairing_code(code)).one()
        pairing.expires_at = now_utc() - timedelta(minutes=1)
        db.commit()

    expired = client.post(
        "/api/auth/pair",
        json=pairing_payload(code, device_name="过期设备"),
    )
    assert expired.status_code == 401
    assert expired.json()["error"] == "invalid_pairing_code"


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
