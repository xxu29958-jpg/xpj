"""Income creation, reporting and native editing retain each amount's denomination."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.routes.web_app import _require_local as _web_require_local
from app.services import income_plan_service, spending_contract_service
from app.services.budget_advisor_service._inputs_builder import _income_plan
from tests._web_native_form_support import hidden_post_forms


@pytest.fixture()
def income_browser(client, monkeypatch):
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: datetime(2026, 9, 9, tzinfo=UTC))
    monkeypatch.setattr(spending_contract_service, "current_month", lambda _timezone: "2026-09")
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create(client, identity, currency, amount):
    response = client.post("/api/income-plans", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
        "intent_month": "2026-09", "label": f"{currency} plan", "source_type": "salary",
        "frequency": "monthly", "amount_cents": amount, "pay_day": 1, "home_currency_code": currency,
    })
    assert response.status_code == 201, response.json()
    assert (response.json()["home_currency_code"], response.json()["amount_cents"]) == (currency, amount)
    return response.json()


def _forecast(client, identity):
    response = client.get("/api/income-plans?month=2026-09", headers=identity.app_headers)
    assert response.status_code == 200, response.json()
    return response.json()


def test_mixed_income_has_no_false_total_and_manual_fx_does_not_rewrite_history(income_browser, identity):
    client = income_browser
    jpy = _create(client, identity, "JPY", 1200)
    cny = _create(client, identity, "CNY", 100)
    forecast = _forecast(client, identity)
    assert forecast["home_currency_code"] == "CNY"
    assert forecast["missing_currency_codes"] == ["JPY"]
    assert all(forecast[field] is None for field in (
        "expected_amount_cents", "scheduled_amount_cents", "total_active_amount_cents",
    ))
    page = client.get("/web/income-plans?ledger_id=owner")
    assert page.status_code == 200
    assert "待补汇率" in page.text and "JPY" in page.text
    with SessionLocal() as db, pytest.raises(AppError, match="汇率"):
        _income_plan(db, tenant_id="owner", month="2026-09")
    rate = client.put("/api/exchange-rates/JPY/2026-09-09", headers=identity.app_headers, json={
        "home_currency_code": "CNY", "currency_code": "JPY", "rate_date": "2026-09-09",
        "rate_to_cny": "0.05", "source": "manual",
    })
    assert rate.status_code == 200, rate.json()
    converted = _forecast(client, identity)
    assert converted["missing_currency_codes"] == []
    assert converted["expected_amount_cents"] == converted["scheduled_amount_cents"] == 6100
    with SessionLocal() as db:
        assert sorted(row.amount_cents for row in _income_plan(db, tenant_id="owner", month="2026-09")) == [100, 6000]
        for record, expected in ((jpy, ("JPY", 1200)), (cny, ("CNY", 100))):
            plan = db.scalar(select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == record["public_id"]))
            history = db.scalars(select(IncomePlanRevision).where(IncomePlanRevision.plan_id == plan.id)).all()
            assert (plan.home_currency_code, plan.amount_cents) == expected
            assert [(row.home_currency_code, row.amount_cents) for row in history] == [expected]


def test_native_income_edit_and_repeated_save_use_the_record_currency(income_browser, identity):
    client = income_browser
    plan = _create(client, identity, "JPY", 1200)
    action = f"/web/income-plans/{plan['public_id']}/edit"
    editor = client.get(action, params={"ledger_id": "owner", "intent_month": "2026-09"})
    assert editor.status_code == 200
    assert 'name="amount_yuan" value="1200"' in editor.text
    fields = hidden_post_forms(editor.text)[action]
    fields.update(label="Changed JPY plan", source_type="salary", frequency="monthly",
        amount_yuan="2000", pay_day="1", income_month="")
    for _ in range(2):
        saved = client.post(action, data=fields, follow_redirects=False)
        assert saved.status_code == 303, saved.text
    with SessionLocal() as db:
        stored = db.scalar(select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == plan["public_id"]))
        assert (stored.home_currency_code, stored.amount_cents, stored.row_version) == ("JPY", 2000, plan["row_version"] + 1)
        revisions = db.scalars(select(IncomePlanRevision).where(IncomePlanRevision.plan_id == stored.id)
            .order_by(IncomePlanRevision.revision_number)).all()
        assert [(row.home_currency_code, row.amount_cents) for row in revisions] == [("JPY", 1200), ("JPY", 2000)]


def test_native_create_retains_the_form_currency_under_a_different_default(income_browser, identity):
    client = income_browser
    page = client.get("/web/income-plans?ledger_id=owner")
    fields = hidden_post_forms(page.text)["/web/income-plans/create"]
    assert fields["home_currency_code"] == "CNY"
    fields.update(home_currency_code="JPY", label="Captured JPY draft", source_type="salary", frequency="monthly",
        amount_yuan="1200", pay_day="1", income_month="")
    response = client.post("/web/income-plans/create", data=fields, follow_redirects=False)
    assert response.status_code == 303, response.text
    row = _forecast(client, identity)["items"][0]
    assert (row["home_currency_code"], row["amount_cents"]) == ("JPY", 1200)
