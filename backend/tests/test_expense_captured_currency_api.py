"""The public correction owner preserves a saved expense's money basis."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from app.database import SessionLocal
from app.models import Expense
from app.services.currency_binding_service import resolve_write_capability


def test_original_amount_correction_and_replay_keep_the_records_frozen_currency(client, identity):
    with SessionLocal() as db:
        assert resolve_write_capability(db).home_currency_code == "CNY"
        expense = Expense(tenant_id="owner", status="confirmed", merchant="Recorded foreign expense",
            category="餐饮", home_currency_code="JPY", original_currency_code="USD",
            original_amount_minor=100, amount_cents=150, exchange_rate_to_cny=Decimal("150"),
            exchange_rate_date=date(2026, 9, 8), exchange_rate_source="manual", fx_status="ready",
            expense_time=datetime(2026, 9, 8, 2, tzinfo=UTC),
            confirmed_at=datetime(2026, 9, 8, 2, tzinfo=UTC))
        db.add(expense)
        db.commit()
        expense_id, version = expense.id, expense.row_version

    url = f"/api/expenses/{expense_id}/corrections"
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    body = {"expected_row_version": version, "original_amount_minor": 200, "reason": "Correct original amount"}
    accepted = client.post(url, headers=headers, json=body)
    assert accepted.status_code == 201, accepted.text
    result = accepted.json()
    assert (result["expense"]["home_currency"], result["expense"]["original_currency_code"],
        result["expense"]["original_amount_minor"], result["expense"]["amount_cents"]) == ("JPY", "USD", 200, 300)
    assert Decimal(result["expense"]["exchange_rate_to_cny"]) == Decimal("150")
    assert result["revision"]["before"]["amount_cents"] == 150
    assert result["revision"]["after"]["amount_cents"] == 300
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["revision"] == result["revision"]
    assert replay.json()["expense"]["row_version"] == result["expense"]["row_version"]
    with SessionLocal() as db:
        saved = db.get(Expense, expense_id)
        assert (saved.home_currency_code, saved.original_currency_code, saved.original_amount_minor,
            saved.amount_cents, saved.exchange_rate_to_cny) == ("JPY", "USD", 200, 300, Decimal("150"))
