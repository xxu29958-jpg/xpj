"""Device-session identity and per-request ledger selection contracts."""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.services import ledger_service


def test_switch_ledger_preserves_session_and_is_safely_retryable(
    client: TestClient,
    *,
    identity,
) -> None:
    created = client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "家庭账本"},
    )
    assert created.status_code == 201, created.json()
    target_id = created.json()["ledger_id"]

    switched = client.post(
        f"/api/ledgers/{target_id}/switch",
        headers=identity.app_headers,
    )
    assert switched.status_code == 200, switched.json()
    body = switched.json()
    original_token = identity.app_headers["Authorization"].removeprefix("Bearer ")
    assert body["session_token"] == original_token
    assert body["ledger"]["ledger_id"] == target_id
    assert body["ledger"]["name"] == "家庭账本"
    assert body["ledger"]["is_default"] is False

    retried = client.post(
        f"/api/ledgers/{target_id}/switch",
        headers=identity.app_headers,
    )
    assert retried.status_code == 200, retried.json()
    assert retried.json()["session_token"] == original_token

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    assert pending.json() == []

    selected = client.get("/api/auth/check", headers=identity.app_headers)
    assert selected.status_code == 200
    assert selected.json()["ledger_name"] == "家庭账本"

    owner_check = client.get(
        "/api/auth/check",
        headers={**identity.app_headers, "X-Ticketbox-Ledger-ID": "owner"},
    )
    assert owner_check.status_code == 200
    assert owner_check.json()["ledger_id"] == "owner"


def test_selected_ledger_header_cannot_bypass_membership(
    client: TestClient,
    *,
    identity,
) -> None:
    response = client.get(
        "/api/auth/check",
        headers={
            **identity.app_headers,
            "X-Ticketbox-Ledger-ID": "ledger_does_not_exist",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_active_session_counts_follow_membership_not_token_default(
    client: TestClient,
    *,
    identity,
) -> None:
    created = client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "统计账本"},
    )
    assert created.status_code == 201
    ledger_id = created.json()["ledger_id"]

    with SessionLocal() as db:
        counts = ledger_service.ledger_member_counts(db, ledger_id=ledger_id)

    assert counts["active_devices"] >= 1
    assert counts["active_tokens"] >= 1
