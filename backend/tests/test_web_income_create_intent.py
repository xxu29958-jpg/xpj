"""The income create form keeps its captured money, month and original key."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.errors import AppError
from app.routes import web_income_plans
from app.services.currency_common import currency_input_metadata


def test_income_create_form_retains_raw_money_month_and_original_submission():
    loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app" / "templates" / "web")])
    html = Environment(loader=loader, autoescape=True).get_template("income_plans.html").render(
        can_write=True, plans_active=[], plans_archived=[], selected_ledger_id="owner",
        home_currency_code="CNY", currency_input=currency_input_metadata("CNY"),
        income_year_options=[2026, 2027], income_default_year="2027", income_default_month="1",
        intent_month="2027-01", income_form_currency=currency_input_metadata("JPY"),
        income_form_draft={"label": "原计划名称", "source_type": "bonus", "frequency": "monthly",
            "amount_yuan": " 001200.50 ", "home_currency_code": "JPY", "pay_day": "32",
            "intent_month": "2026-09", "income_month_year": "2026", "income_month_number": "9",
            "idempotency_key": "original-income-key"})
    assert 'name="idempotency_key" value="original-income-key"' in html
    assert 'name="home_currency_code" value="JPY"' in html
    assert 'name="intent_month" value="2026-09"' in html
    assert 'type="text" name="amount_yuan"' in html and 'value=" 001200.50 "' in html
    assert 'value="原计划名称"' in html and 'value="32"' in html
    assert 'value="monthly" selected' in html


@pytest.mark.parametrize("error", ["idempotency_key_reused", "idempotency_key_required"])
def test_income_create_refusal_renders_original_draft_without_rekeying(monkeypatch, error):
    monkeypatch.setattr(web_income_plans, "_list_ledger_options", lambda db: [])
    monkeypatch.setattr(web_income_plans, "_resolve_selected_ledger_id", lambda *a, **k: "owner")
    monkeypatch.setattr(web_income_plans, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(web_income_plans, "resolve_web_actor_account_id", lambda *a: 7)
    command = Mock(side_effect=AppError(error, status_code=422))
    monkeypatch.setattr(web_income_plans, "create_income_plan_idempotently", command, raising=False)
    render = Mock(return_value="retained")
    monkeypatch.setattr(web_income_plans, "_render_income_plans", render, raising=False)
    result = web_income_plans.post_create(Mock(), ledger_id="owner", label="原计划",
        source_type="salary", frequency="one_time", income_month=None,
        income_month_year="2026", income_month_number="9", amount_yuan="1200", home_currency_code="JPY",
        pay_day="10", intent_month="2026-09", idempotency_key="original-income-key",
        review_new=False, db=Mock(), _local=None)
    assert result == "retained"
    draft = render.call_args.kwargs["draft"]
    assert draft["amount_yuan"] == "1200" and draft["home_currency_code"] == "JPY"
    assert draft["intent_month"] == "2026-09" and draft["idempotency_key"] == "original-income-key"
    payload = command.call_args.kwargs["payload"]
    assert payload.amount_cents == 1200 and payload.income_month == "2026-09"
    assert command.call_args.kwargs["actor_account_id"] == 7
    assert render.call_args.kwargs["review"] is True
