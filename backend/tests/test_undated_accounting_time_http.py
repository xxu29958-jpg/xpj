"""A supported legacy unknown day can be found, exported and explicitly corrected."""

import csv
import json
from datetime import date
from io import StringIO

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, ExpenseRevision
from app.services.currency_binding_service import resolve_write_capability
from app.services.ledger_calendar_service import current_calendar
from tests.expense_correction_support import idem

pytestmark = pytest.mark.real_db


def test_unknown_legacy_fact_found_exported_and_corrected_into_period(web_client, identity):
    client = web_client
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        rule = current_calendar(db, ledger_id="owner")
        expense = Expense(tenant_id="owner", status="confirmed", amount_cents=1234,
            original_amount_minor=1234, original_currency_code="CNY", home_currency_code="CNY",
            merchant="Unknown historical day", category="餐饮", source="manual", fx_status="ready",
            expense_time=None, confirmed_at=None, accounting_date=None, calendar_revision=rule.revision,
            time_precision="unknown", accounting_date_basis="legacy_unknown")
        db.add(expense)
        db.flush()
        expense_id, revision = expense.id, rule.revision

    headers = identity.app_headers
    found = client.get("/api/expenses/confirmed", headers=headers,
        params={"month": "2026-05", "missing_accounting_date": True})
    assert found.status_code == 200, found.text
    payload = found.json()
    assert payload["undated_expense_count"] == payload["total"] == 1
    item = payload["items"][0]
    assert item["root"]["id"] == expense_id and item["stream_date"] is None
    assert item["stream_amount_cents"] == 1234
    assert item["root"]["accounting_time"]["basis"] == "legacy_unknown"
    all_rows = client.get("/api/expenses/confirmed", headers=headers)
    assert all_rows.status_code == 200 and all_rows.json()["total"] == 1
    unrelated = client.get("/api/expenses/confirmed", headers=headers,
        params={"category": "数码", "missing_accounting_date": True})
    assert unrelated.status_code == 200 and unrelated.json()["undated_expense_count"] == 0
    other_ledger = client.get("/api/expenses/confirmed", headers=identity.gray_app_headers)
    assert other_ledger.status_code == 200 and other_ledger.json()["undated_expense_count"] == 0
    exported = client.get("/api/expenses/export.csv", headers=headers)
    assert exported.status_code == 200, exported.text
    original = list(csv.DictReader(StringIO(exported.text.lstrip("\ufeff"))))[0]
    assert original["stream_date"] == "" and original["stream_amount_cents"] == "1234"
    assert json.loads(original["accounting_time"])["basis"] == "legacy_unknown"
    before = client.get("/api/stats/monthly", headers=headers, params={"month": "2026-05"})
    assert before.status_code == 200, before.text
    assert before.json()["total_amount_cents"] is None
    assert before.json()["undated_expense_count"] == 1 and before.json()["missing_rates"] == []

    web_before = client.get("/web/confirmed?ledger_id=owner&filter=missing_accounting_date")
    assert web_before.status_code == 200, web_before.text
    assert "Unknown historical day" in web_before.text and "账务日期待核对" in web_before.text

    command = {"expected_row_version": item["root"]["row_version"], "reason": "原凭证确认了日期",
        "time_input": {"precision": "date_only", "calendar_revision": revision, "user_local_date": "2026-05-04"}}
    command_headers = idem(headers)
    correction = client.post(f"/api/expenses/{expense_id}/corrections", headers=command_headers, json=command)
    assert correction.status_code == 201, correction.text
    replay = client.post(f"/api/expenses/{expense_id}/corrections", headers=command_headers, json=command)
    assert replay.status_code == 201 and replay.json() == correction.json()
    after = client.get("/api/stats/monthly", headers=headers, params={"month": "2026-05"})
    assert after.status_code == 200, after.text
    assert (after.json()["total_amount_cents"], after.json()["undated_expense_count"]) == (1234, 0)
    recovered = client.get("/api/expenses/confirmed", headers=headers, params={"month": "2026-05"})
    assert recovered.status_code == 200 and recovered.json()["items"][0]["root"]["id"] == expense_id
    web_after = client.get("/web/confirmed?ledger_id=owner&filter=missing_accounting_date")
    assert web_after.status_code == 200 and "Unknown historical day" not in web_after.text
    with SessionLocal() as db:
        current = db.get(Expense, expense_id)
        assert current.accounting_date == current.user_local_date == date(2026, 5, 4)
        assert current.expense_time is None and current.confirmed_at is None
        assert current.amount_cents == 1234 and current.fact_revision == 2
        history = list(db.scalars(select(ExpenseRevision).where(ExpenseRevision.expense_id == expense_id)
            .order_by(ExpenseRevision.revision_number)))
        assert len(history) == 2
        assert history[0].after_snapshot["accounting_time"]["basis"] == "legacy_unknown"
        assert history[1].before_snapshot == history[0].after_snapshot
