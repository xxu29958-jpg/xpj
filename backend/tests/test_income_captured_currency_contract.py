"""An income amount must retain its currency in the command and revision."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.schemas import IncomePlanCreateRequest
from app.services.income_plan_service._history import append_income_revision


def _create_body():
    return {"intent_month": "2026-09", "label": "Salary", "amount_cents": 1200, "pay_day": 10}


def test_new_income_requires_the_currency_in_which_the_user_entered_the_amount():
    with pytest.raises(ValidationError, match="home_currency_code"):
        IncomePlanCreateRequest.model_validate(_create_body())


def test_new_income_accepts_an_explicit_currency_without_reinterpreting_its_units():
    request = IncomePlanCreateRequest.model_validate({**_create_body(), "home_currency_code": "JPY"})
    assert request.home_currency_code == "JPY"
    assert request.amount_cents == 1200


def test_an_income_revision_carries_the_plans_amount_currency():
    plan = SimpleNamespace(
        tenant_id="owner", id=7, row_version=2, label="Salary", source_type="salary",
        frequency="monthly", income_month=None, amount_cents=1200, home_currency_code="JPY",
        pay_day=10, status="active",
    )
    db = Mock()
    append_income_revision(
        db, plan, period=date(2026, 9, 1), intent_period=date(2026, 9, 1),
        change_kind="edit", actor_account_id=1, when=datetime(2026, 9, 9, tzinfo=UTC),
    )
    revision = db.add.call_args.args[0]
    assert revision.home_currency_code == "JPY"
    assert revision.amount_cents == 1200


def test_income_api_response_preserves_the_records_currency():
    from app.models import MonthlyIncomePlan
    from app.routes.income_plans import _to_response

    when = datetime(2026, 9, 9, tzinfo=UTC)
    plan = MonthlyIncomePlan(public_id="plan", label="Salary", source_type="salary", frequency="monthly",
        amount_cents=1200, home_currency_code="JPY", pay_day=1, status="active", row_version=1,
        created_at=when, updated_at=when)
    response = _to_response(plan)
    assert response.home_currency_code == "JPY"
    assert response.amount_cents == 1200


def test_recycle_bin_income_keeps_its_record_currency():
    from app.services.recycle_bin_service import _income_detail

    plan = SimpleNamespace(frequency="monthly", home_currency_code="JPY", amount_cents=1200, pay_day=10)
    assert "1,200" in _income_detail(plan)
    assert "12.00" not in _income_detail(plan)
