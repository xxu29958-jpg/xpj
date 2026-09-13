"""Real native form, command receipt and budget read return through PostgreSQL."""

from datetime import UTC, datetime
from unittest.mock import Mock

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ExchangeRate, Expense, LedgerMember
from app.services import spending_contract_service
from app.services.budget_advisor_service import _runner
from tests._web_native_form_support import hidden_post_forms

ACTION = "/web/budget-advise/rates"
TASK = {"ledger_id": "owner", "month": "2026-09", "home_currency_code": "JPY",
    "savings_target_yuan": "12", "reserved_buffer_yuan": "3", "currency_code": "CNY", "rate_date": "2026-09-05"}


def _rate_form(client):
    response = client.get(ACTION, params=TASK)
    assert response.status_code == 200, response.text
    fields = hidden_post_forms(response.text)[ACTION]
    return {**fields, "currency_code": TASK["currency_code"], "rate_date": TASK["rate_date"], "rate_to_cny": "20"}


def test_native_save_and_lost_ack_replay_return_original_month_with_current_projection(web_client, identity, monkeypatch):
    when = datetime(2026, 9, 5, 12, tzinfo=UTC)
    with SessionLocal() as db:
        expense = Expense(tenant_id="owner", status="confirmed", category="餐饮", amount_cents=300,
            home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=300,
            expense_time=when, confirmed_at=when)
        db.add(expense)
        db.commit()
        expense_id = expense.id
    provider = Mock(side_effect=AssertionError("rate recovery must not generate paid advice"))
    monkeypatch.setattr(_runner, "get_budget_advisor", provider)
    missing = web_client.get("/web/budget-advise", params=TASK)
    assert missing.status_code == 200 and "待补汇率" in missing.text
    original = _rate_form(web_client)
    monkeypatch.setattr(spending_contract_service, "current_month", lambda _tz: "2026-10")
    accepted = web_client.post(ACTION, data=original)
    assert accepted.status_code == 200, accepted.text
    budget_form = hidden_post_forms(accepted.text)["/web/budget-advise"]
    assert budget_form["home_currency_code"] == "JPY"
    assert 'name="month" value="2026-09"' in accepted.text
    assert 'value="12"' in accepted.text and 'value="3"' in accepted.text
    assert "待补汇率" not in accepted.text and "− ¥60" in accepted.text
    # Correction stays reachable after the original gap has disappeared.
    assert "人工汇率" in accepted.text
    current = _rate_form(web_client)
    assert current["expected_row_version"] == "1"
    assert current["idempotency_key"] != original["idempotency_key"]
    corrected = web_client.post(ACTION, data={**current, "rate_to_cny": "25"})
    assert corrected.status_code == 200, corrected.text
    replay = web_client.post(ACTION, data=original)
    assert replay.status_code == 200, replay.text
    assert "− ¥75" in replay.text and "− ¥60" not in replay.text
    assert 'name="month" value="2026-09"' in replay.text
    provider.assert_not_called()
    with SessionLocal() as db:
        saved = db.scalar(select(ExchangeRate))
        assert (saved.rate_to_cny, saved.row_version) == (25, 2)
        fact = db.get(Expense, expense_id)
        assert (fact.home_currency_code, fact.amount_cents, fact.original_amount_minor) == ("CNY", 300, 300)


def test_native_viewer_reads_rates_but_cannot_submit(web_client, identity):
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        member.role = "viewer"
        db.commit()
    page = web_client.get(ACTION, params=TASK)
    assert page.status_code == 200, page.text
    assert "保存汇率" not in page.text and "当前身份可查看汇率" in page.text
    fields = _rate_form(web_client)
    refused = web_client.post(ACTION, data=fields)
    assert refused.status_code == 403, refused.text
    with SessionLocal() as db:
        assert db.scalar(select(ExchangeRate)) is None
