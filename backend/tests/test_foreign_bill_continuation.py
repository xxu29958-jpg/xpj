"""Imported foreign bills need a dated conversion, then a separate human review."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BackgroundTask, Expense
from app.services.fx_rate_provider import upsert_fx_rate


def _import_foreign_bill(client: TestClient, identity) -> dict:
    content = (
        "home_currency_code,amount_cents,original_currency_code,original_amount_minor,expense_time,merchant,category\n"
        "CNY,,USD,12345,2026-05-03T16:30:00Z,Historical foreign receipt,交通\n"
    )
    created = client.post(
        "/api/imports/csv", headers=identity.app_headers,
        files={"csv_file": ("foreign.csv", content.encode(), "text/csv")},
    )
    assert created.status_code == 201, created.text
    batch = created.json()
    assert (batch["valid_rows"], batch["error_rows"]) == (1, 0)
    endpoint = f"/api/imports/csv/{batch['public_id']}"
    applied = client.post(f"{endpoint}/apply", headers=identity.app_headers, json={"batch_size": 1})
    assert applied.status_code == 200, applied.text
    assert applied.json()["inserted_count"] == 1
    rows = client.get(f"{endpoint}/rows", headers=identity.app_headers)
    assert rows.status_code == 200, rows.text
    row = rows.json()["items"][0]
    assert row["status"] == "applied"
    detail = client.get(f"/api/expenses/{row['expense_id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.text
    bill = detail.json()
    assert bill["status"] == "pending"
    assert (bill["home_currency"], bill["original_currency_code"], bill["original_amount_minor"]) == (
        "CNY", "USD", 12345,
    )
    assert bill["expense_time"] == "2026-05-03T16:30:00Z"
    assert bill["category"] == "交通"
    return bill


def test_csv_missing_historical_rate_has_a_durable_task_back_to_the_pending_bill(client: TestClient, identity):
    bill = _import_foreign_bill(client, identity)
    assert bill["fx_status"] == "pending"
    assert bill["amount_cents"] is None
    # The intended day is the household's spending day, not today's import day.
    assert bill["fx_rate_date"] == "2026-05-04"

    response = client.get("/api/tasks", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    continuations = [task for task in response.json()["items"] if task["source_expense_id"] == bill["id"]]
    assert len(continuations) == 1, "An applied CSV row still needs a discoverable historical conversion task"
    task = continuations[0]
    # The existing isolation fixture keeps the actual executor queued.
    assert task["status"] == "queued"
    with SessionLocal() as db:
        persisted = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == task["public_id"]))
        assert persisted is not None
        assert persisted.tenant_id == "owner"
        assert persisted.status == "queued"
        assert persisted.input_payload_json is not None
    other_ledger = client.get(f"/api/tasks/{task['public_id']}", headers=identity.gray_app_headers)
    assert other_ledger.status_code == 404


def test_csv_cannot_treat_an_unrelated_older_cache_row_as_historical_coverage(client: TestClient, identity):
    with SessionLocal() as db:
        upsert_fx_rate(
            db, currency_code="USD", home_currency_code="CNY",
            rate_date=date(2025, 5, 2), rate_to_home=Decimal("7"),
        )
        db.commit()

    bill = _import_foreign_bill(client, identity)
    assert bill["fx_status"] == "pending", "A prior cached quote does not prove the requested date was checked"
    assert bill["amount_cents"] is None
    assert bill["fx_rate"] is None
    assert bill["fx_rate_date"] == "2026-05-04"


def test_confirm_does_not_resolve_a_new_rate_and_accept_an_unreviewed_home_amount(client: TestClient, identity):
    bill = _import_foreign_bill(client, identity)
    assert (bill["fx_status"], bill["amount_cents"]) == ("pending", None)
    rate = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": 0, "home_currency_code": "CNY", "currency_code": "USD",
            "rate_date": "2026-05-04", "rate_to_cny": "7", "source": "manual",
        },
    )
    assert rate.status_code == 200, rate.text

    response = client.post(
        f"/api/expenses/{bill['id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": bill["row_version"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "exchange_rate_pending"
    with SessionLocal() as db:
        unchanged = db.get(Expense, bill["id"])
        assert unchanged is not None
        assert (unchanged.status, unchanged.fx_status, unchanged.amount_cents) == ("pending", "pending", None)
        assert unchanged.row_version == bill["row_version"]
        assert unchanged.confirmed_at is None
    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200, stats.text
    assert (stats.json()["count"], stats.json()["total_amount_cents"]) == (0, 0)
