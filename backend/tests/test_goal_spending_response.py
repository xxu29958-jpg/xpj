"""Unit tests for the spending-limit goal serializer.

Split out of ``goal_service`` (ADR-0051 recycle-bin slice — file-LOC gate), so
``goal_spending_response`` is now an independently-testable unit. These pin the
serializer's branch selection with synthetic totals — sharper isolation than the
goal API integration tests, which can't hand-craft a multi-category spend blob.
"""

from __future__ import annotations

from app.models import Goal
from app.services.goal_spending_response import GoalSpendTotals, goal_response
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
        status="active",
        created_at=now,
        updated_at=now,
        row_version=1,
    )


def test_goal_response_category_goal_counts_only_its_category() -> None:
    totals = GoalSpendTotals(total_amount_cents=10000, by_category={"餐饮": 1200, "交通": 3000})
    response = goal_response(_spending_goal(category="餐饮", target_amount_cents=2000), totals)
    # The 餐饮 goal sees only 餐饮 spend — not the 10000 total, not 交通's 3000.
    assert response.spent_amount_cents == 1200
    assert response.remaining_amount_cents == 800
    assert response.progress_percent == 60
    assert response.progress_state == "on_track"


def test_goal_response_total_goal_uses_total_and_marks_over_limit() -> None:
    totals = GoalSpendTotals(total_amount_cents=5200, by_category={"餐饮": 1200})
    response = goal_response(_spending_goal(category=None, target_amount_cents=5000), totals)
    # A category-less (total) goal aggregates everything and trips over_limit.
    assert response.spent_amount_cents == 5200
    assert response.progress_state == "over_limit"
