"""v1.1 PR-4: cold-start baseline + 50/30/20 framework + quintile snap.

Invariants to lock in early so later PRs (personal stats + blend) can
build on a stable starting baseline shape:

- FrameworkShares always sum to 1000 permille (rule of construction).
- Default baseline category sum ≤ needs + wants (savings never dipped
  into).
- Quintile snap is monotonic in income.
- Per-category median <= p75 (P75 is the upper bound).
"""

from __future__ import annotations

import pytest

from app.services.budget_baseline_service import (
    FRAMEWORK_50_30_20,
    CategoryBaseline,
    DefaultBaseline,
    FrameworkShares,
    discretionary_cents,
    get_default_baseline,
    quintile_for_monthly_income,
)

# ---------------------------------------------------------------------------
# FrameworkShares contract
# ---------------------------------------------------------------------------


def test_framework_50_30_20_sums_to_1000() -> None:
    fw = FRAMEWORK_50_30_20
    assert fw.needs_permille + fw.wants_permille + fw.savings_permille == 1000
    assert fw.needs_permille == 500
    assert fw.wants_permille == 300
    assert fw.savings_permille == 200


def test_custom_framework_must_sum_to_1000() -> None:
    with pytest.raises(ValueError, match="1000 permille"):
        FrameworkShares(needs_permille=500, wants_permille=400, savings_permille=200)


def test_custom_framework_for_high_savers() -> None:
    # Some users want 50/20/30 (more savings). Should work as long as it
    # adds to 1000 permille — framework is not opinionated about which
    # share is biggest.
    fw = FrameworkShares(needs_permille=500, wants_permille=200, savings_permille=300)
    assert fw.savings_permille == 300


# ---------------------------------------------------------------------------
# get_default_baseline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quintile", ["q1", "q2", "q3", "q4", "q5"])
def test_default_baseline_emitted_for_every_quintile(quintile) -> None:
    baseline = get_default_baseline(income_quintile=quintile)
    assert baseline.income_quintile == quintile
    assert baseline.monthly_income_cents > 0
    assert baseline.framework == FRAMEWORK_50_30_20
    assert len(baseline.categories) > 0


def test_default_baseline_category_sum_does_not_exceed_spendable() -> None:
    # Categories cover needs + wants; savings is residual. The sum of
    # category medians must therefore stay at or below
    # income * (needs + wants) / 1000.
    baseline = get_default_baseline(income_quintile="q3")
    spendable = (
        baseline.monthly_income_cents
        * (baseline.framework.needs_permille + baseline.framework.wants_permille)
        // 1000
    )
    total_median = sum(c.median_cents for c in baseline.categories)
    assert total_median <= spendable, (
        f"category medians sum to {total_median} but spendable cap is {spendable}"
    )


def test_default_baseline_p75_is_at_least_median_per_category() -> None:
    baseline = get_default_baseline(income_quintile="q3")
    for cat in baseline.categories:
        assert cat.p75_cents >= cat.median_cents, (
            f"category {cat.category}: p75={cat.p75_cents} < median={cat.median_cents}"
        )


def test_default_baseline_includes_core_categories() -> None:
    baseline = get_default_baseline(income_quintile="q3")
    cat_names = {c.category for c in baseline.categories}
    # The project's category catalog covers these; baseline must too.
    assert "餐饮" in cat_names
    assert "住房" in cat_names
    assert "交通" in cat_names


def test_default_baseline_override_monthly_income() -> None:
    # User provided a precise income, use it instead of the quintile mid-point.
    custom = 800_000_00  # $8,000/mo
    baseline = get_default_baseline(
        income_quintile="q3", monthly_income_cents=custom
    )
    assert baseline.monthly_income_cents == custom


def test_default_baseline_scales_linearly_with_income() -> None:
    low = get_default_baseline(income_quintile="q3", monthly_income_cents=500_000_00)
    high = get_default_baseline(income_quintile="q3", monthly_income_cents=1_000_000_00)
    for low_cat, high_cat in zip(low.categories, high.categories, strict=True):
        # Doubling income should ~double each category median (allow ±1 cent
        # for integer division rounding).
        assert abs(high_cat.median_cents - 2 * low_cat.median_cents) <= 2


# ---------------------------------------------------------------------------
# discretionary_cents
# ---------------------------------------------------------------------------


def test_discretionary_is_wants_share_of_income() -> None:
    baseline = get_default_baseline(
        income_quintile="q3", monthly_income_cents=1_000_000_00
    )
    # 50/30/20 → 30% of income is "wants".
    assert discretionary_cents(baseline) == 300_000_00


def test_discretionary_respects_custom_framework() -> None:
    fw = FrameworkShares(needs_permille=600, wants_permille=200, savings_permille=200)
    baseline = get_default_baseline(
        income_quintile="q3",
        monthly_income_cents=1_000_000_00,
        framework=fw,
    )
    assert discretionary_cents(baseline) == 200_000_00


# ---------------------------------------------------------------------------
# quintile_for_monthly_income
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "monthly_cents,expected",
    [
        (100_000_00, "q1"),     # very low
        (290_000_00, "q1"),     # q1 mid
        (450_000_00, "q2"),     # q2 mid
        (700_000_00, "q3"),     # q3 mid
        (1_000_000_00, "q4"),   # q4 mid
        (1_950_000_00, "q5"),   # q5 mid
        (5_000_000_00, "q5"),   # well above q5 boundary
    ],
)
def test_quintile_snap_is_monotonic(monthly_cents: int, expected: str) -> None:
    assert quintile_for_monthly_income(monthly_cents) == expected


def test_quintile_snap_defensive_against_negative() -> None:
    assert quintile_for_monthly_income(-500_00) == "q1"


def test_quintile_snap_zero_income() -> None:
    assert quintile_for_monthly_income(0) == "q1"


# ---------------------------------------------------------------------------
# Dataclass shape lock (any downstream code can rely on these fields)
# ---------------------------------------------------------------------------


def test_default_baseline_dataclass_is_frozen() -> None:
    baseline = get_default_baseline(income_quintile="q1")
    with pytest.raises((AttributeError, TypeError)):
        # frozen dataclass → set raises FrozenInstanceError
        baseline.monthly_income_cents = 1  # type: ignore[misc]


def test_category_baseline_dataclass_is_frozen() -> None:
    cat = CategoryBaseline(category="餐饮", median_cents=100, p75_cents=130)
    with pytest.raises((AttributeError, TypeError)):
        cat.category = "other"  # type: ignore[misc]


def test_default_baseline_categories_is_tuple() -> None:
    baseline: DefaultBaseline = get_default_baseline(income_quintile="q1")
    assert isinstance(baseline.categories, tuple)
