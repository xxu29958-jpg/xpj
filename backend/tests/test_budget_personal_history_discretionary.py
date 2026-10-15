"""Real confirmed-history quantiles and current discretionary arithmetic."""

from __future__ import annotations

from datetime import datetime

from app.database import SessionLocal
from app.models import Expense
from app.services.budget_baseline_service import (
    DiscretionaryBreakdown,
    compute_monthly_discretionary,
)
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.learning_service import compute_budget_quantile_suggestion
from app.services.time_service import now_utc


def test_personal_baseline_empty_when_no_confirmed_expenses(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        baseline = compute_budget_quantile_suggestion(db, tenant_id="owner", category="餐饮",
            home_currency_code="CNY", include_zero_months=False)
    assert baseline is None


def test_personal_baseline_aggregates_per_month_per_category(identity) -> None:  # noqa: ARG001
    base = datetime(2026, 3, 15, tzinfo=now_utc().tzinfo)
    with SessionLocal() as db:
        # 3 months: Jan, Feb, Mar 2026. 餐饮 across all 3 months,
        # 交通 only Feb. Each row counts as one confirmed expense.
        rows = [
            (datetime(2026, 1, 10, tzinfo=base.tzinfo), "餐饮", 100_00),
            (datetime(2026, 1, 20, tzinfo=base.tzinfo), "餐饮", 50_00),
            (datetime(2026, 2, 5, tzinfo=base.tzinfo), "餐饮", 200_00),
            (datetime(2026, 2, 10, tzinfo=base.tzinfo), "交通", 40_00),
            (datetime(2026, 3, 1, tzinfo=base.tzinfo), "餐饮", 300_00),
        ]
        for spent_at, category, amount in rows:
            _calendar_expense = Expense(
                tenant_id="owner",
                status="confirmed",
                amount_cents=amount,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=amount,
                category=category,
                expense_time=spent_at,
                confirmed_at=spent_at,
                created_at=spent_at,
                updated_at=spent_at,
            )
            refresh_legacy_expense_time(db, _calendar_expense)
            db.add(_calendar_expense)
        db.commit()
        baseline = compute_budget_quantile_suggestion(
            db, tenant_id="owner", category="餐饮", home_currency_code="CNY", include_zero_months=False,
            now=datetime(2026, 4, 1, tzinfo=base.tzinfo),
        )

    assert baseline.sample_months == 3
    # 餐饮 monthly totals: Jan=150, Feb=200, Mar=300 → median 200, P75 250.
    assert baseline.p50_cents == 200_00
    assert baseline.p75_cents == 250_00


def test_personal_baseline_excludes_pending_and_rejected(identity) -> None:  # noqa: ARG001
    base = datetime(2026, 3, 15, tzinfo=now_utc().tzinfo)
    with SessionLocal() as db:
        # Mix of confirmed + pending + rejected; only confirmed should count.
        for status, amount in [
            ("confirmed", 100_00),
            ("pending", 999_00),
            ("rejected", 888_00),
        ]:
            _calendar_expense = Expense(
                tenant_id="owner",
                status=status,
                amount_cents=amount,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=amount,
                category="餐饮",
                expense_time=base,
                confirmed_at=base if status == "confirmed" else None,
                created_at=base,
                updated_at=base,
            )
            if _calendar_expense.status == "confirmed":
                refresh_legacy_expense_time(db, _calendar_expense)
            db.add(_calendar_expense)
        db.commit()
        baseline = compute_budget_quantile_suggestion(
            db, tenant_id="owner", category="餐饮", home_currency_code="CNY", include_zero_months=False, min_months=1,
            now=datetime(2026, 4, 1, tzinfo=base.tzinfo),
        )
    # Only 100_00 from the confirmed row should appear.
    assert baseline.p50_cents == 100_00


# ---------------------------------------------------------------------------
# compute_monthly_discretionary
# ---------------------------------------------------------------------------


def test_discretionary_basic_subtraction() -> None:
    b = compute_monthly_discretionary(
        monthly_income_cents=1_000_000_00,
        fixed_expenses_cents=400_000_00,
        spent_amount_cents=100_000_00,
        savings_target_cents=200_000_00,
    )
    assert b.discretionary_cents == 300_000_00
    assert b.monthly_income_cents == 1_000_000_00
    assert b.fixed_expenses_cents == 400_000_00
    assert b.spent_amount_cents == 100_000_00


def test_discretionary_with_buffer() -> None:
    b = compute_monthly_discretionary(
        monthly_income_cents=500_000_00,
        fixed_expenses_cents=200_000_00,
        savings_target_cents=100_000_00,
        reserved_buffer_cents=50_000_00,
    )
    assert b.discretionary_cents == 150_000_00


def test_discretionary_floors_at_zero_when_underwater() -> None:
    # User is already overcommitted; surface zero spendable, not negative.
    b = compute_monthly_discretionary(
        monthly_income_cents=500_000_00,
        fixed_expenses_cents=600_000_00,
        savings_target_cents=0,
    )
    assert b.discretionary_cents == 0
    assert b.monthly_income_cents == 500_000_00  # input still inspectable


def test_discretionary_breakdown_is_inspectable_dataclass() -> None:
    b: DiscretionaryBreakdown = compute_monthly_discretionary(
        monthly_income_cents=1_000_000_00,
        fixed_expenses_cents=300_000_00,
    )
    assert b.spent_amount_cents == 0
    assert b.savings_target_cents == 0
    assert b.reserved_buffer_cents == 0
    assert b.discretionary_cents == 700_000_00


def test_discretionary_no_subtractions_returns_full_income() -> None:
    b = compute_monthly_discretionary(monthly_income_cents=800_000_00)
    assert b.discretionary_cents == 800_000_00
