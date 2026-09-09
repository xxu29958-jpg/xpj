"""PostgreSQL/API qualification for historical FX recovery; collect locally only."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

from app.database import SessionLocal
from app.models import Expense
from app.services.budget_advisor_service import _runner


def test_historical_rate_recovery_rereads_inputs_before_explicit_generation(client, identity, monkeypatch):
    when = datetime(2026, 8, 15, 12, tzinfo=UTC)
    with SessionLocal() as db:
        history = Expense(tenant_id="owner", status="confirmed", category="餐饮", amount_cents=500,
            home_currency_code="JPY", original_currency_code="JPY", original_amount_minor=500,
            expense_time=when, confirmed_at=when)
        current = Expense(tenant_id="owner", status="confirmed", category="餐饮", amount_cents=300,
            home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=300,
            expense_time=datetime(2026, 9, 3, 12, tzinfo=UTC), confirmed_at=when)
        db.add_all([history, current])
        db.commit()
        history_id = history.id
    provider = Mock(side_effect=AssertionError("missing history must block before provider construction"))
    monkeypatch.setattr(_runner, "get_budget_advisor", provider)
    path = "/api/budget/advisor/inputs?month=2026-09&timezone=UTC"
    before = client.get(path, headers=identity.app_headers)
    assert before.status_code == 200, before.text
    assert before.json()["breakdown"]["spent_amount_cents"] == 300
    assert before.json()["missing_rates"] == [{
        "source_currency_code": "JPY", "home_currency_code": "CNY", "rate_date": "2026-08-15",
    }]
    blocked = client.post("/api/budget/advise", headers=identity.app_headers,
        json={"month": "2026-09", "timezone": "UTC"})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"] == "money_projection_unavailable"
    provider.assert_not_called()
    saved = client.put("/api/exchange-rates/JPY/2026-08-15",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "expected_row_version": 0, "home_currency_code": "CNY", "currency_code": "JPY",
            "rate_date": "2026-08-15", "rate_to_cny": "0.05", "source": "manual",
        })
    assert saved.status_code == 200, saved.text
    after = client.get(path, headers=identity.app_headers)
    assert after.status_code == 200, after.text
    assert after.json()["missing_rates"] == []
    provider.assert_not_called()
    with SessionLocal() as db:
        original = db.get(Expense, history_id)
        assert (original.home_currency_code, original.amount_cents, original.original_amount_minor) == ("JPY", 500, 500)
    advisor = Mock()
    advisor.advise.return_value = None
    provider.side_effect = None
    provider.return_value = advisor
    generated = client.post("/api/budget/advise", headers=identity.app_headers,
        json={"month": "2026-09", "timezone": "UTC"})
    assert generated.status_code == 200, generated.text
    provider.assert_called_once()
    assert advisor.advise.call_args.args[0].home_currency == "CNY"
