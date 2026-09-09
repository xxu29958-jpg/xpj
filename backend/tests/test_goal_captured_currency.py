"""Spending targets require chosen units; debt-clearance goals carry no target money."""

import pytest
from pydantic import ValidationError

from app.schemas import GoalCreateRequest, GoalUpdateRequest


@pytest.mark.parametrize("schema, fields", [
    (GoalCreateRequest, {"name": "交通上限", "month": "2026-09", "target_amount_cents": 1200}),
    (GoalUpdateRequest, {"expected_row_version": 7, "target_amount_cents": 1200}),
])
def test_spending_target_cannot_silently_take_the_runtime_currency(schema, fields):
    with pytest.raises(ValidationError, match="home_currency_code"):
        schema(**fields)


@pytest.mark.parametrize("schema, fields", [
    (GoalCreateRequest, {"name": "交通上限", "month": "2026-09", "target_amount_cents": 1200}),
    (GoalUpdateRequest, {"expected_row_version": 7, "target_amount_cents": 1200}),
])
def test_spending_target_keeps_explicit_yen_minor_units(schema, fields):
    request = schema(**fields, home_currency_code="JPY")
    assert request.model_dump()["home_currency_code"] == "JPY"
    assert request.target_amount_cents == 1200


def test_debt_clearance_goal_does_not_invent_a_monetary_target():
    request = GoalCreateRequest(name="还清关联欠款", goal_type="debt_repayment", debt_public_ids=["debt-1"])
    assert request.target_amount_cents is None
    assert request.model_dump().get("home_currency_code") is None


def test_web_goal_uses_its_recorded_yen_and_does_not_draw_unknown_progress():
    from types import SimpleNamespace

    from app.routes.web_goals import _goal_view

    goal = SimpleNamespace(public_id="goal-yen", name="交通上限", month="2026-09", category=None,
        target_amount_cents=1200, home_currency_code="JPY", spent_amount_cents=None,
        remaining_amount_cents=None, progress_percent=None, progress_state="unavailable", status="active")
    view = _goal_view(goal)
    assert view["target_yuan"] == "1200"
    assert view["home_currency_code"] == "JPY"
    assert view["progress_percent"] is None and view["bar_percent"] is None
    assert view["spent_yuan"] == "" and view["remaining_yuan"] == ""
