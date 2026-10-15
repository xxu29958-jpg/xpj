"""Health responses and installation attestation through the actual application."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_middleware_transparent_for_200(client: TestClient) -> None:
    """Middleware must not alter successful responses."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    installation_health_public = client.get("/api/health/installation")
    assert installation_health_public.status_code == 403
    assert installation_health_public.json()["error"] == "invalid_request"

    from app.main import app

    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
    ) as local_client:
        installation_health = local_client.get("/api/health/installation")
    assert installation_health.status_code == 200
    installation_body = installation_health.json()
    assert installation_body["status"] == "ok"
    assert installation_body["product"] == "ticketbox"
    assert installation_body["contract"] == "ticketbox-installation-health-v3"
    assert installation_body["backend_version"]
    assert installation_body["installation_id"]
    assert installation_body["runtime_access_state"] == "available"
    assert installation_body["owner_state"] == "configured"
    assert installation_body["owner_recovery_channel"] == "development"
    assert "X-Ticketbox-Health-Attestation" not in installation_health.headers
    assert installation_body["mobile_connectivity"] == {
        "public_origin": None,
        "mobile_endpoint_state": "local_only",
        "android_binding_state": "setup_required",
        "iphone_upload_state": "setup_required",
    }
    assert ":\\" not in installation_health.text


def test_installed_health_requires_and_signs_a_fresh_challenge(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    from app.main import app
    from app.services.installation_health_attestation import sign_health_challenge

    key = "a" * 64
    challenge = "b" * 64
    monkeypatch.setenv("TICKETBOX_HEALTH_ATTESTATION_KEY", key)
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
    ) as local_client:
        missing = local_client.get("/api/health/installation")
        attested = local_client.get(
            "/api/health/installation",
            headers={"X-Ticketbox-Health-Challenge": challenge},
        )

    assert missing.status_code == 400
    assert attested.status_code == 200
    assert attested.headers["X-Ticketbox-Health-Attestation"] == sign_health_challenge(key, challenge)


def test_installation_health_rejects_database_query_failure() -> None:
    from sqlalchemy.exc import OperationalError

    from app.database import get_db
    from app.main import app

    class UnavailableDatabase:
        def execute(self, *_args, **_kwargs):
            raise OperationalError("installation health", {}, OSError("database unavailable"))

    def unavailable_database():
        yield UnavailableDatabase()

    app.dependency_overrides[get_db] = unavailable_database
    try:
        with TestClient(
            app,
            base_url="http://127.0.0.1:8000",
            client=("127.0.0.1", 50000),
        ) as local_client:
            response = local_client.get("/api/health/installation")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"] == "invalid_request"
    assert payload["message"] == "Ticketbox database is not ready for installed-service traffic."
    assert payload["request_id"]


def test_installation_health_exposes_owner_recovery_as_a_distinct_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import app

    monkeypatch.setattr("app.main.installation_owner_state", lambda _db: "recovery_required")
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
    ) as local_client:
        response = local_client.get("/api/health/installation")

    assert response.status_code == 200
    assert response.json()["owner_state"] == "recovery_required"
