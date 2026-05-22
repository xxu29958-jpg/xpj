from __future__ import annotations


from fastapi.testclient import TestClient

from api_contract_helpers import (
    upload_png,
)
from app.main import app
from app.network_boundary import require_admin_network_boundary

def test_admin_maintenance_requires_admin_token(client: TestClient, *, identity) -> None:
    response = client.post("/api/maintenance/cleanup-images", headers=identity.app_headers)
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"

    response = client.post("/api/maintenance/cleanup-images", headers=identity.admin_headers)
    assert response.status_code == 200
    assert response.json()["enabled"] is False


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
    client: TestClient, *, identity,
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
    client: TestClient, monkeypatch, tmp_path, *, identity,
) -> None:
    from dataclasses import replace

    from app.services import file_service, thumb_service

    external_upload_dir = (tmp_path / "external-uploads").resolve()
    external_settings = replace(file_service.get_settings(), upload_dir=external_upload_dir)
    monkeypatch.setattr(file_service, "get_settings", lambda: external_settings)
    monkeypatch.setattr(thumb_service, "get_settings", lambda: external_settings)

    upload_png(client, identity=identity)

    response = client.get("/api/settings/server", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json()["upload_storage_bytes"] > 0
