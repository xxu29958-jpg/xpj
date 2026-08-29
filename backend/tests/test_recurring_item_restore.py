"""Recurring-item recycle restore and stale-intent behavior."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def _create_manual_item(client: TestClient, *, identity) -> dict:
    response = client.post(
        "/api/recurring/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "宽带",
            "baseline_amount_cents": 12_000,
            "next_expected_date": "2026-09-08",
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _archive(client: TestClient, *, identity, public_id: str) -> dict:
    response = client.post(
        f"/api/recurring/items/{public_id}/archive",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "archived"
    return response.json()


def test_recurring_item_restore_reactivates_archived(client: TestClient, *, identity) -> None:
    item = _create_manual_item(client, identity=identity)
    archived = _archive(client, identity=identity, public_id=item["public_id"])

    restored = client.post(
        f"/api/recurring/items/{item['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": archived["row_version"]},
    )

    assert restored.status_code == 200, restored.json()
    assert restored.json()["status"] == "active"
    assert restored.json()["archived_at"] is None
    assert restored.json()["paused_at"] is None
    listed = client.get("/api/recurring/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert [entry["public_id"] for entry in listed.json()["items"]] == [item["public_id"]]


def test_recurring_item_restore_stale_token_returns_409(client: TestClient, *, identity) -> None:
    item = _create_manual_item(client, identity=identity)
    _archive(client, identity=identity, public_id=item["public_id"])

    stale = client.post(
        f"/api/recurring/items/{item['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": item["row_version"]},
    )

    assert stale.status_code == 409, stale.json()
    assert stale.json()["error"] == "state_conflict"


def test_recurring_item_restore_replay_cannot_claim_a_later_pause_succeeded(
    client: TestClient,
    *,
    identity,
) -> None:
    item = _create_manual_item(client, identity=identity)
    archived = _archive(client, identity=identity, public_id=item["public_id"])
    restore_token = archived["row_version"]
    restored = client.post(
        f"/api/recurring/items/{item['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": restore_token},
    )
    assert restored.status_code == 200, restored.json()
    paused = client.post(
        f"/api/recurring/items/{item['public_id']}/pause",
        headers=identity.app_headers,
        json={"expected_row_version": restored.json()["row_version"]},
    )
    assert paused.status_code == 200, paused.json()
    assert paused.json()["status"] == "paused"

    stale_restore = client.post(
        f"/api/recurring/items/{item['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": restore_token},
    )

    assert stale_restore.status_code == 409, stale_restore.json()
    assert stale_restore.json()["error"] == "state_conflict"
    current = client.get(
        f"/api/recurring/items/{item['public_id']}",
        headers=identity.app_headers,
    )
    assert current.status_code == 200, current.json()
    assert current.json()["status"] == "paused"


def test_recurring_item_restore_without_token_returns_422(client: TestClient, *, identity) -> None:
    item = _create_manual_item(client, identity=identity)
    _archive(client, identity=identity, public_id=item["public_id"])

    response = client.post(
        f"/api/recurring/items/{item['public_id']}/restore",
        headers=identity.app_headers,
        json={},
    )

    assert response.status_code == 422, response.json()
