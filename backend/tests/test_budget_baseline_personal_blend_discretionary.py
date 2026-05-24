"""v1.1 PR-5: personal P50/P75 + blend + discretionary formula.

Invariants:

- Personal baseline only counts confirmed expenses (pending / rejected
  excluded) within the rolling window.
- Blend weight is linear, capped at 6 months — "fully trust personal"
  after 6 months of data.
- Categories with no personal data fall back to default verbatim
  (no zero blend that would imply "you spend 0 in this category").
- Discretionary formula floors at zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import Expense
from app.services.budget_baseline_service import (
    CategoryBaseline,
    DefaultBaseline,
    DiscretionaryBreakdown,
    FrameworkShares,
    PersonalBaseline,
    blend_baselines,
    compute_monthly_discretionary,
    compute_personal_baseline,
    personal_trust_weight,
)
from app.services.time_service import now_utc

# ---------------------------------------------------------------------------
# personal_trust_weight
# ---------------------------------------------------------------------------


def test_trust_weight_starts_at_zero() -> None:
    assert personal_trust_weight(0) == 0.0


def test_trust_weight_caps_at_one_after_six_months() -> None:
    assert personal_trust_weight(6) == 1.0
    assert personal_trust_weight(12) == 1.0  # no overshoot


def test_trust_weight_is_linear_between_zero_and_six() -> None:
    assert personal_trust_weight(3) == 0.5
    assert personal_trust_weight(2) == pytest_approx_third()


def pytest_approx_third() -> float:
    return 1 / 3  # exact compute-then-compare so test stays deterministic


def test_trust_weight_defensive_against_negative() -> None:
    assert personal_trust_weight(-5) == 0.0


# ---------------------------------------------------------------------------
# blend_baselines
# ---------------------------------------------------------------------------


def _default_fixture() -> DefaultBaseline:
    """Hand-rolled default so tests don't depend on BLS shares drift."""
    return DefaultBaseline(
        income_quintile="q3",
        monthly_income_cents=1_000_000_00,
        framework=FrameworkShares(
            needs_permille=500, wants_permille=300, savings_permille=200
        ),
        categories=(
            CategoryBaseline(category="餐饮", median_cents=200_00, p75_cents=260_00),
            CategoryBaseline(category="住房", median_cents=500_00, p75_cents=650_00),
            CategoryBaseline(category="交通", median_cents=100_00, p75_cents=130_00),
        ),
    )


def test_blend_with_no_personal_data_returns_default_verbatim() -> None:
    default = _default_fixture()
    personal = PersonalBaseline(months_observed=0, categories=())
    blended = blend_baselines(default=default, personal=personal)
    by_cat = {row.category: row for row in blended}
    for default_row in default.categories:
        assert by_cat[default_row.category] == default_row


def test_blend_at_six_months_fully_trusts_personal() -> None:
    default = _default_fixture()
    personal = PersonalBaseline(
        months_observed=6,
        categories=(
            CategoryBaseline(category="餐饮", median_cents=400_00, p75_cents=500_00),
            CategoryBaseline(category="住房", median_cents=700_00, p75_cents=800_00),
            CategoryBaseline(category="交通", median_cents=150_00, p75_cents=180_00),
        ),
    )
    blended = blend_baselines(default=default, personal=personal)
    by_cat = {row.category: row for row in blended}
    assert by_cat["餐饮"].median_cents == 400_00
    assert by_cat["住房"].median_cents == 700_00


def test_blend_at_three_months_is_half_default_half_personal() -> None:
    default = _default_fixture()
    personal = PersonalBaseline(
        months_observed=3,
        categories=(
            CategoryBaseline(category="餐饮", median_cents=400_00, p75_cents=520_00),
        ),
    )
    blended = blend_baselines(default=default, personal=personal)
    by_cat = {row.category: row for row in blended}
    # 0.5 weight: (400 * 0.5 + 200 * 0.5) = 300
    assert by_cat["餐饮"].median_cents == 300_00


def test_blend_keeps_default_for_categories_without_personal_data() -> None:
    default = _default_fixture()
    personal = PersonalBaseline(
        months_observed=6,
        categories=(
            CategoryBaseline(category="餐饮", median_cents=400_00, p75_cents=500_00),
            # No 住房, no 交通
        ),
    )
    blended = blend_baselines(default=default, personal=personal)
    by_cat = {row.category: row for row in blended}
    assert by_cat["住房"].median_cents == 500_00  # default unchanged
    assert by_cat["交通"].median_cents == 100_00  # default unchanged


def test_blend_carries_over_personal_only_categories() -> None:
    default = _default_fixture()
    personal = PersonalBaseline(
        months_observed=6,
        categories=(
            CategoryBaseline(category="宠物", median_cents=80_00, p75_cents=110_00),
        ),
    )
    blended = blend_baselines(default=default, personal=personal)
    by_cat = {row.category: row for row in blended}
    # Default categories carried as-is, plus new category.
    assert "宠物" in by_cat
    assert by_cat["宠物"].median_cents == 80_00


def test_blend_p75_never_below_median() -> None:
    default = _default_fixture()
    # Edge case: personal P75 below default median; blended P75 could
    # mathematically be < blended median if not clamped — verify clamp.
    personal = PersonalBaseline(
        months_observed=6,
        categories=(
            CategoryBaseline(category="餐饮", median_cents=300_00, p75_cents=290_00),
        ),
    )
    blended = blend_baselines(default=default, personal=personal)
    by_cat = {row.category: row for row in blended}
    assert by_cat["餐饮"].p75_cents >= by_cat["餐饮"].median_cents


# ---------------------------------------------------------------------------
# compute_personal_baseline (touches DB; uses identity fixture)
# ---------------------------------------------------------------------------


def test_personal_baseline_empty_when_no_confirmed_expenses(identity) -> None:  # noqa: ARG001
    with SessionLocal() as db:
        baseline = compute_personal_baseline(db, tenant_id="owner")
    assert baseline.months_observed == 0
    assert baseline.categories == ()


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
            db.add(
                Expense(
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
            )
        db.commit()
        baseline = compute_personal_baseline(
            db, tenant_id="owner", months_window=6, now=base + timedelta(days=10)
        )

    assert baseline.months_observed >= 3
    by_cat = {row.category: row for row in baseline.categories}
    # 餐饮 monthly totals: Jan=150, Feb=200, Mar=300 → median 200, P75 250.
    assert by_cat["餐饮"].median_cents == 200_00


def test_personal_baseline_excludes_pending_and_rejected(identity) -> None:  # noqa: ARG001
    base = datetime(2026, 3, 15, tzinfo=now_utc().tzinfo)
    with SessionLocal() as db:
        # Mix of confirmed + pending + rejected; only confirmed should count.
        for status, amount in [
            ("confirmed", 100_00),
            ("pending", 999_00),
            ("rejected", 888_00),
        ]:
            db.add(
                Expense(
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
            )
        db.commit()
        baseline = compute_personal_baseline(
            db, tenant_id="owner", months_window=6, now=base + timedelta(days=1)
        )
    by_cat = {row.category: row for row in baseline.categories}
    # Only 100_00 from the confirmed row should appear.
    assert by_cat["餐饮"].median_cents == 100_00


# ---------------------------------------------------------------------------
# compute_monthly_discretionary
# ---------------------------------------------------------------------------


def test_discretionary_basic_subtraction() -> None:
    b = compute_monthly_discretionary(
        monthly_income_cents=1_000_000_00,
        fixed_expenses_cents=400_000_00,
        savings_target_cents=200_000_00,
    )
    assert b.discretionary_cents == 400_000_00
    assert b.monthly_income_cents == 1_000_000_00
    assert b.fixed_expenses_cents == 400_000_00


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
    assert b.savings_target_cents == 0
    assert b.reserved_buffer_cents == 0
    assert b.discretionary_cents == 700_000_00


def test_discretionary_no_subtractions_returns_full_income() -> None:
    b = compute_monthly_discretionary(monthly_income_cents=800_000_00)
    assert b.discretionary_cents == 800_000_00
