"""Unit tests for the spending-limit goal serializer.

Split out of ``goal_service`` (ADR-0051 recycle-bin slice — file-LOC gate), so
``goal_spending_response`` is now an independently-testable unit. These pin the
serializer's branch selection with synthetic totals — sharper isolation than the
goal API integration tests, which can't hand-craft a multi-category spend blob.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.models import Goal
from app.money_contract import MONEY_AGGREGATE_MAX
from app.services.goal_spending_response import GoalSpendTotals, goal_response, month_spend_totals
from app.services.time_service import now_utc


def _spending_goal(*, category: str | None, target_amount_cents: int) -> Goal:
    now = now_utc()
    return Goal(
        public_id="goal-test-1",
        tenant_id="owner",
        name="测试目标",
        goal_type="spending_limit",
        period="monthly",
        month="2026-05",
        category=category,
        target_amount_cents=target_amount_cents,
        home_currency_code="CNY",
        status="active",
        created_at=now,
        updated_at=now,
        row_version=1,
    )


def test_goal_response_category_goal_counts_only_its_category() -> None:
    totals = GoalSpendTotals(home_currency_code="CNY", total_amount_cents=10000, by_category={"餐饮": 1200, "交通": 3000})
    response = goal_response(_spending_goal(category="餐饮", target_amount_cents=2000), totals)
    # The 餐饮 goal sees only 餐饮 spend — not the 10000 total, not 交通's 3000.
    assert response.spent_amount_cents == 1200
    assert response.remaining_amount_cents == 800
    assert response.progress_percent == 60
    assert response.progress_state == "on_track"


def test_goal_response_total_goal_uses_total_and_marks_over_limit() -> None:
    totals = GoalSpendTotals(home_currency_code="CNY", total_amount_cents=5200, by_category={"餐饮": 1200})
    response = goal_response(_spending_goal(category=None, target_amount_cents=5000), totals)
    # A category-less (total) goal aggregates everything and trips over_limit.
    assert response.spent_amount_cents == 5200
    assert response.progress_state == "over_limit"

    max_response = goal_response(
        _spending_goal(category=None, target_amount_cents=1),
        GoalSpendTotals(home_currency_code="CNY", total_amount_cents=MONEY_AGGREGATE_MAX, by_category={}),
    )
    assert max_response.progress_percent == 100
    assert max_response.progress_state == "over_limit"
    assert max_response.spent_amount_cents == MONEY_AGGREGATE_MAX


def test_missing_conversion_keeps_progress_unknown_instead_of_zero_or_success() -> None:
    totals = GoalSpendTotals(home_currency_code="CNY", total_amount_cents=None, by_category={"交通": None})
    response = goal_response(_spending_goal(category="交通", target_amount_cents=1200), totals)
    assert response.spent_amount_cents is None
    assert response.remaining_amount_cents is None
    assert response.progress_percent is None
    assert response.progress_state == "unavailable"


@pytest.mark.parametrize("source, expected", [("CNY", 4000), (None, None)])
def test_goal_projects_confirmed_spending_in_its_own_yen_units(monkeypatch, source, expected):
    rows = [SimpleNamespace(category="交通", amount_cents=amount, home_currency_code=currency, stream_date=date(2026, 9, 3))
            for amount, currency in [(10000, source), (2000, "JPY")]]
    db = SimpleNamespace(execute=lambda query: rows)
    monkeypatch.setattr("app.services.money_projection_service.resolve_payload_rate", lambda *args, **kw: (20, None, None, None))
    goal = _spending_goal(category="交通", target_amount_cents=5000)
    goal.home_currency_code = "JPY"
    totals = month_spend_totals(db, tenant_id="owner", month="2026-09", home_currency_code="JPY")
    result = goal_response(goal, totals)
    assert result.home_currency_code == "JPY"
    assert result.spent_amount_cents == expected
    assert result.remaining_amount_cents == (1000 if expected is not None else None)
    assert result.progress_percent == (80 if expected is not None else None)


def test_a_total_in_another_currency_cannot_describe_the_goal_progress():
    goal = _spending_goal(category=None, target_amount_cents=1200)
    goal.home_currency_code = "JPY"
    result = goal_response(goal, GoalSpendTotals(1200, {}, home_currency_code="CNY"))
    assert result.progress_state == "unavailable"
    assert result.spent_amount_cents is None
