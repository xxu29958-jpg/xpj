"""Native create preserves the rendered command through refusal and calendar rollover."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.routes.web_app import _require_local
from app.services import income_plan_service, spending_contract_service
from tests._web_native_form_support import hidden_post_forms

ACTION = "/web/income-plans/create"


@pytest.fixture()
def income_form(client, monkeypatch):
    clock = {"month": "2026-09", "now": datetime(2026, 9, 5, tzinfo=UTC)}
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: clock["now"])
    monkeypatch.setattr(spending_contract_service, "current_month", lambda _tz: clock["month"])
    app.dependency_overrides[_require_local] = lambda: None
    try:
        page = client.get("/web/income-plans?ledger_id=owner")
        assert page.status_code == 200, page.text
        fields = hidden_post_forms(page.text)[ACTION]
        assert fields["intent_month"] == "2026-09" and fields["idempotency_key"]
        fields.update(label="原计划", source_type="salary", frequency="monthly", amount_yuan="1200", pay_day="10",
            income_month_year="2026", income_month_number="9")
        yield client, fields, clock
    finally:
        app.dependency_overrides.pop(_require_local, None)


@pytest.mark.parametrize("frequency", ["monthly", "one_time"])
def test_original_create_month_currency_and_single_revision_survive_replay(income_form, frequency):
    client, fields, clock = income_form
    fields.update(frequency=frequency, home_currency_code="JPY")
    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    for _ in range(2):
        response = client.post(ACTION, data=fields, follow_redirects=False)
        assert response.status_code == 303, response.text
    with SessionLocal() as db:
        plans = list(db.scalars(select(MonthlyIncomePlan)))
        assert len(plans) == 1
        plan = plans[0]
        assert (plan.home_currency_code, plan.amount_cents) == ("JPY", 1200)
        assert plan.income_month == ("2026-09" if frequency == "one_time" else None)
        revision = db.scalar(select(IncomePlanRevision).where(IncomePlanRevision.plan_id == plan.id))
        assert revision.intent_month.isoformat() == "2026-09-01"
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1


def test_invalid_raw_input_survives_refusal_with_original_identity(income_form):
    client, fields, clock = income_form
    fields.update(home_currency_code="JPY", amount_yuan=" 001200.50 ", pay_day="32")
    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    refused = client.post(ACTION, data=fields, follow_redirects=False)
    assert refused.status_code == 422, refused.text
    retained = hidden_post_forms(refused.text)[ACTION]
    for name in ("home_currency_code", "intent_month", "idempotency_key", "ledger_id"):
        assert retained[name] == fields[name]
    assert 'value=" 001200.50 "' in refused.text and 'value="32"' in refused.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0


def test_reused_key_requires_explicit_nonwriting_preparation_for_new_plan(income_form):
    client, fields, _ = income_form
    assert client.post(ACTION, data=fields, follow_redirects=False).status_code == 303
    fields.update(label="准备另一计划", amount_yuan="2400")
    refused = client.post(ACTION, data=fields, follow_redirects=False)
    assert refused.status_code == 422, refused.text
    assert 'name="review_new"' in refused.text
    assert hidden_post_forms(refused.text)[ACTION]["idempotency_key"] == fields["idempotency_key"]
    prepared = client.post(ACTION, data={**fields, "review_new": "true"}, follow_redirects=False)
    assert prepared.status_code == 200, prepared.text
    next_fields = hidden_post_forms(prepared.text)[ACTION]
    assert next_fields["idempotency_key"] != fields["idempotency_key"]
    assert next_fields["home_currency_code"] == fields["home_currency_code"]
    assert next_fields["intent_month"] == fields["intent_month"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 1
    next_fields.update(label=fields["label"], amount_yuan=fields["amount_yuan"], source_type="salary", frequency="monthly", pay_day="10")
    assert client.post(ACTION, data=next_fields, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 2
