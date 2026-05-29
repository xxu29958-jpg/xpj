from __future__ import annotations

from datetime import timedelta

from api_contract_helpers import (
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AuthToken, Device
from app.network_boundary import require_admin_network_boundary
from app.services.identity_service import hash_secret
from app.services.time_service import now_utc


def test_admin_maintenance_requires_admin_token(client: TestClient, *, identity) -> None:
    response = client.post("/api/maintenance/cleanup-images", headers=identity.app_headers)
    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"

    response = client.post("/api/maintenance/cleanup-images", headers=identity.admin_headers)
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_admin_maintenance_rejects_missing_token(client: TestClient) -> None:
    for path in (
        "/api/maintenance/cleanup-images",
        "/api/maintenance/cleanup-devices",
    ):
        response = client.post(path)
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"


def test_admin_cleanup_ai_advisor_audit_runs(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/maintenance/cleanup-ai-advisor-audit",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["deleted_rows"] >= 0


def test_admin_cleanup_devices_prunes_old_revoked_rows(
    client: TestClient, *, identity
) -> None:
    old = now_utc() - timedelta(days=30)
    with SessionLocal() as db:
        base = db.query(AuthToken).filter(AuthToken.token_hash == hash_secret(identity.app_token)).one()
        device = Device(
            account_id=base.account_id,
            device_name="old revoked",
            platform="android",
            created_at=old,
            revoked_at=old,
        )
        db.add(device)
        db.flush()
        token = AuthToken(
            token_hash="old-cleanup-token",
            account_id=base.account_id,
            device_id=device.id,
            ledger_id=base.ledger_id,
            scope="app",
            created_at=old,
            revoked_at=old,
        )
        db.add(token)
        db.commit()
        device_id = device.id

    response = client.post(
        "/api/maintenance/cleanup-devices?retention_days=0",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted_devices"] == 1
    assert body["deleted_tokens"] == 1

    with SessionLocal() as db:
        assert db.get(Device, device_id) is None


def test_maintenance_rejects_public_host_even_with_admin_token(client: TestClient, *, identity) -> None:
    app.dependency_overrides.pop(require_admin_network_boundary, None)
    try:
        response = client.post(
            "/api/maintenance/cleanup-images",
            headers={**identity.admin_headers, "host": "api.example.com"},
        )
    finally:
        app.dependency_overrides[require_admin_network_boundary] = lambda: None

    assert response.status_code == 403
    assert response.json()["error"] == "admin_api_local_only"


def test_server_settings_snapshot_does_not_expose_paths_or_tokens(
    client: TestClient,
    *,
    identity,
) -> None:
    upload_png(client, identity=identity)
    response = client.get("/api/settings/server", headers=identity.app_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["account_name"] == "我"
    assert payload["ledger_id"] == "owner"
    assert payload["ledger_name"] == "我的小票夹"
    assert payload["ledger_is_default"] is True
    assert payload["device_name"] == "pytest-android"
    assert payload["role"] == "owner"
    assert payload["status"] == "ok"
    assert payload["storage_status"] == "normal"
    assert payload["pending_count"] == 1
    assert payload["upload_storage_bytes"] > 0
    assert payload["latest_upload_at"].endswith("Z")
    assert "ocr_provider" not in payload
    assert "max_upload_size_mb" not in payload
    assert "delete_image_after_confirm" not in payload
    assert "token" not in str(payload).lower()
    assert "path" not in str(payload).lower()
    assert "E:\\" not in str(payload)


def test_server_settings_storage_metric_counts_external_upload_dir(
    client: TestClient,
    external_upload_dir,
    *,
    identity,
) -> None:
    del external_upload_dir  # fixture side-effect: monkeypatched upload_dir

    upload_png(client, identity=identity)

    response = client.get("/api/settings/server", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json()["upload_storage_bytes"] > 0
