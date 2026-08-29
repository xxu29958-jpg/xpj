"""Recurring list filters and candidate-query error contracts."""

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import RecurringItem
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc


def test_recurring_status_filter_and_invalid_candidate_errors(
    client: TestClient,
    *,
    identity,
) -> None:
    now = now_utc()
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key="netflix",
                merchant_name="Netflix",
                frequency="monthly",
                baseline_amount_cents=6800,
                last_amount_cents=6800,
                occurrence_count=4,
                last_seen_at=now,
                status="paused",
                confidence="high",
                source="candidate",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    paused = client.get("/api/recurring/items?status=paused", headers=identity.app_headers)
    assert paused.status_code == 200, paused.json()
    assert [entry["merchant"] for entry in paused.json()["items"]] == ["Netflix"]

    invalid_status = client.get("/api/recurring/items?status=unknown", headers=identity.app_headers)
    assert invalid_status.status_code == 422, invalid_status.json()
    assert invalid_status.json()["error"] == "recurring_status_invalid"

    not_found = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "Not Monthly",
            "amount_cents": 1234,
            "occurrence_count": 1,
        },
    )
    assert not_found.status_code == 404, not_found.json()
    assert not_found.json()["error"] == "recurring_candidate_not_found"
