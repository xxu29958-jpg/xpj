"""The monthly obligation must reconcile with an explicitly selected payment."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient


def _create_series(client: TestClient, identity) -> dict:
    response = client.post(
        "/api/recurring/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "房租",
            "baseline_amount_cents": 10_000,
            "next_expected_date": "2026-09-05",
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _payment(client: TestClient, identity) -> dict:
    when = datetime(2026, 9, 5, 12, tzinfo=UTC)
    expense_id = insert_confirmed_expense(
        amount_cents=10_000,
        merchant="房租",
        category="居住",
        expense_time=when,
        confirmed_at=when,
    )
    response = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert response.status_code == 200, response.json()
    return response.json()


def test_recurring_payment_reconciles_reservation_and_replays_once(
    client: TestClient, *, identity,
) -> None:
    series = _create_series(client, identity)
    payment = _payment(client, identity)
    path = f"/api/recurring/items/{series['public_id']}/occurrences/2026-09"
    initial = client.get(path, headers=identity.app_headers)
    assert initial.status_code == 200, initial.json()
    assert initial.json()["state"] == "unfulfilled"
    assert initial.json()["reserved_amount_cents"] == 10_000

    key = str(uuid4())
    payload = {
        "expense_public_id": payment["public_id"],
        "expected_expense_row_version": payment["row_version"],
        "expected_row_version": initial.json()["row_version"],
        "expected_series_row_version": series["row_version"],
    }
    headers = {**identity.app_headers, "Idempotency-Key": key}
    fulfilled = client.put(path, headers=headers, json=payload)
    assert fulfilled.status_code == 200, fulfilled.json()
    assert fulfilled.json()["state"] == "fulfilled"
    assert fulfilled.json()["reserved_amount_cents"] == 0
    assert fulfilled.json()["expense_public_id"] == payment["public_id"]
    assert fulfilled.json()["next_due_date"] == "2026-10-05"

    replay = client.put(path, headers=headers, json=payload)
    assert replay.status_code == 200, replay.json()
    assert replay.json() == fulfilled.json()
    after = client.get(f"/api/expenses/{payment['id']}", headers=identity.app_headers)
    assert after.json() == payment

    breakdown = client.get(
        "/api/budget/discretionary?month=2026-09&timezone=UTC",
        headers=identity.app_headers,
    )
    assert breakdown.status_code == 200, breakdown.json()
    assert breakdown.json()["spent_amount_cents"] == 10_000
    assert breakdown.json()["fixed_expenses_cents"] == 0
