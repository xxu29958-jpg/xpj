"""Logical server and restored-data generation identity contracts."""

from uuid import UUID

from fastapi.testclient import TestClient

import app.services.server_identity_service as server_identity_service
from app.database import SessionLocal
from app.version import BACKEND_VERSION
from tests._infra.env import TEST_APP_TOKEN


def test_health_and_auth_contract(client: TestClient, *, identity) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    private_status_anon = client.get("/api/status/private")
    assert private_status_anon.status_code == 401
    assert private_status_anon.json()["error"] == "invalid_token"

    private_status = client.get("/api/status/private", headers=identity.app_headers)
    assert private_status.status_code == 200
    private_body = private_status.json()
    assert private_body["status"] == "ok"
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
    auth_body = response.json()
    expected_business_identity = {
        "status": "ok",
        "account_name": "我",
        "ledger_id": "owner",
        "ledger_name": "我的小票夹",
        "device_name": "pytest-android",
        "role": "owner",
        "scope": "app",
        "credential_state": "current",
    }
    assert {key: auth_body[key] for key in expected_business_identity} == expected_business_identity
    for identity_field in (
        "server_id",
        "data_generation",
        "account_public_id",
        "device_public_id",
    ):
        assert str(UUID(auth_body[identity_field])) == auth_body[identity_field]

    legacy = client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {TEST_APP_TOKEN}"},
    )
    assert legacy.status_code == 401
    assert legacy.json()["error"] == "legacy_auth_removed"
    assert legacy.json()["message"]


def test_server_data_identity_is_canonical_and_stable(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200

    with SessionLocal() as db:
        first = server_identity_service.read_server_data_identity(db)
        second = server_identity_service.read_server_data_identity(db)

    assert str(UUID(first.server_id)) == first.server_id
    assert str(UUID(first.data_generation)) == first.data_generation
    assert second == first
