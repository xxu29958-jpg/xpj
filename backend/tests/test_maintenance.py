from __future__ import annotations


from fastapi.testclient import TestClient

from api_contract_helpers import (
    upload_png,
)
from conftest import (
    admin_headers,
    app_headers,
)


def test_admin_maintenance_requires_admin_token(client: TestClient) -> None:
    response = client.post("/api/maintenance/cleanup-images", headers=app_headers())
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"

    response = client.post("/api/maintenance/cleanup-images", headers=admin_headers())
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_server_settings_snapshot_does_not_expose_paths_or_tokens(
    client: TestClient,
) -> None:
    upload_png(client)
    response = client.get("/api/settings/server", headers=app_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["account_name"] == "我"
    assert payload["ledger_name"] == "我的小票夹"
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
