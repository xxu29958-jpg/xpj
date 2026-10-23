"""v1.2 P2 — budget P50/P75 quantile suggestion contract."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Expense
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.learning_service import (
    BudgetQuantileSuggestion,
    compute_budget_quantile_suggestion,
)


def _seed(
    *,
    tenant_id: str = "owner",
    category: str = "餐饮",
    confirmed_year: int = 2026,
    confirmed_month: int = 5,
    confirmed_day: int = 15,
    amount_cents: int = 5000,
    expense_time: datetime | None = None,
    confirmed_at: datetime | None = None,
) -> None:
    confirmed = datetime(
        confirmed_year,
        confirmed_month,
        confirmed_day,
        12,
        0,
        tzinfo=UTC,
    )
    if expense_time is None:
        expense_time = confirmed
    if confirmed_at is None:
        confirmed_at = confirmed
    with SessionLocal() as db:
        _calendar_expense = Expense(
            tenant_id=tenant_id,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_cents,
            amount_cents=amount_cents,
            merchant="x",
            category=category,
            source="pytest",
            raw_text="",
            status="confirmed",
            expense_time=expense_time,
            confirmed_at=confirmed_at,
        )
        refresh_legacy_expense_time(db, _calendar_expense)
        db.add(_calendar_expense)
        db.commit()


def test_returns_p50_p75_with_sufficient_history(*, identity) -> None:
    # 6 months of "餐饮" history within the default look-back window.
    # Anchor `now` at 2026-07-15 so 2026-01 .. 2026-06 are in range.
    for month, amount in enumerate(
        [1000, 2000, 3000, 4000, 5000, 6000], start=1
    ):
        _seed(
            confirmed_year=2026,
            confirmed_month=month,
            confirmed_day=10,
            amount_cents=amount,
        )

    now = datetime(2026, 7, 15, tzinfo=UTC)
    with SessionLocal() as db:
        result = compute_budget_quantile_suggestion(
            db, tenant_id="owner", category="餐饮", now=now,
        )
        assert isinstance(result, BudgetQuantileSuggestion)
        # P50 of [1000,2000,3000,4000,5000,6000] = 3500
        # P75 = 4750
        assert result.p50_cents == 3500
        assert result.p75_cents == 4750
        assert result.sample_months == 6
        assert result.algorithm_version == "budget-quantile-v2"


@pytest.mark.parametrize("recorded_months", [0, 1, 2])
def test_under_min_months_returns_none(*, client, identity, recorded_months) -> None:
    from app.services.monthly_report_service import compose_budget_explanation

    for month in range(5, 5 + recorded_months):
        _seed(confirmed_year=2026, confirmed_month=month, amount_cents=5000)
    if recorded_months == 0:
        planned = client.put("/api/budgets/monthly/2026-06?timezone=UTC",
            headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"home_currency_code": "CNY", "expected_row_version": None, "total_amount_cents": 50000,
                "non_monthly_amount_cents": 0, "rollover_amount_cents": 0, "excluded_categories": [],
                "category_budgets": [{"category": "餐饮", "amount_cents": 50000}]})
        assert planned.status_code == 200, planned.json()
    now = datetime(2026, 7, 1, tzinfo=UTC)
    with SessionLocal() as db:
        # The ordinary six-month window must not manufacture history from padding.
        result = compute_budget_quantile_suggestion(db, tenant_id="owner", category="餐饮", now=now)
        assert result is None
        explanation = compose_budget_explanation(db, tenant_id="owner", category="餐饮", year_month="2026-07")
        assert explanation.verdict == "no_history" and explanation.p75_cents is None


@pytest.mark.parametrize("established", [False, True])
def test_zero_padding_reflects_actual_cadence(*, identity, established) -> None:
    # Records begin in February. Other categories establish the known months;
    # this category's zeroes do not invent December/January history.
    for month in (2, 3, 5):
        _seed(category="交通", confirmed_year=2026, confirmed_month=month, amount_cents=100)
    if established:
        _seed(category="交通", confirmed_year=2025, confirmed_month=10, amount_cents=100)
    _seed(confirmed_year=2026, confirmed_month=4, amount_cents=600)
    now = datetime(2026, 6, 30, tzinfo=UTC)
    with SessionLocal() as db:
        result = compute_budget_quantile_suggestion(
            db,
            tenant_id="owner",
            category="餐饮",
            look_back_months=6,
            min_months=3,
            now=now,
        )
        assert result is not None
        assert result.p50_cents == 0
        # P75 of [0, 0, 0, 600] interpolates between the third and fourth values.
        assert result.p75_cents == (0 if established else 150)
        assert result.sample_months == (6 if established else 4)


def test_include_zero_months_false_drops_empty_months(*, identity) -> None:
    # Same as above but ask for non-zero months only.
    _seed(confirmed_year=2026, confirmed_month=4, amount_cents=600)
    now = datetime(2026, 6, 30, tzinfo=UTC)
    with SessionLocal() as db:
        result = compute_budget_quantile_suggestion(
            db,
            tenant_id="owner",
            category="餐饮",
            look_back_months=6,
            include_zero_months=False,
            min_months=1,
            now=now,
        )
        assert result is not None
        # Only one non-zero month: median == that value.
        assert result.p50_cents == 600
        assert result.sample_months == 1


def test_tenant_isolation(*, identity) -> None:
    for month, amount in enumerate([1000, 2000, 3000, 4000, 5000], start=1):
        _seed(
            tenant_id="owner",
            confirmed_year=2026,
            confirmed_month=month,
            confirmed_day=10,
            amount_cents=amount,
        )
    now = datetime(2026, 6, 30, tzinfo=UTC)
    with SessionLocal() as db:
        owner = compute_budget_quantile_suggestion(
            db,
            tenant_id="owner",
            category="餐饮",
            now=now,
            include_zero_months=False,
            min_months=1,
        )
        tester = compute_budget_quantile_suggestion(
            db,
            tenant_id="tester_1",
            category="餐饮",
            now=now,
            include_zero_months=False,
            min_months=1,
        )
        assert owner is not None
        assert tester is None


def test_other_categories_ignored(*, identity) -> None:
    for month, amount in enumerate([1000, 2000, 3000, 4000], start=1):
        _seed(
            category="餐饮",
            confirmed_year=2026,
            confirmed_month=month,
            confirmed_day=10,
            amount_cents=amount,
        )
    # Noise in a different category should not affect 餐饮 stats.
    for month, amount in enumerate([9000, 9000, 9000], start=1):
        _seed(
            category="购物",
            confirmed_year=2026,
            confirmed_month=month,
            confirmed_day=10,
            amount_cents=amount,
        )
    now = datetime(2026, 5, 30, tzinfo=UTC)
    with SessionLocal() as db:
        result = compute_budget_quantile_suggestion(
            db,
            tenant_id="owner",
            category="餐饮",
            now=now,
            include_zero_months=False,
            min_months=1,
        )
        assert result is not None
        # Median of [1000, 2000, 3000, 4000] = 2500.
        assert result.p50_cents == 2500


def test_quantile_preserves_adopted_date_across_query_timezones(
    *, identity,
) -> None:
    _seed(
        category="timezone-cat",
        amount_cents=777,
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
    )
    now = datetime(2026, 6, 15, tzinfo=UTC)

    with SessionLocal() as db:
        shanghai = compute_budget_quantile_suggestion(
            db,
            tenant_id="owner",
            category="timezone-cat",
            look_back_months=1,
            include_zero_months=False,
            min_months=1,
            now=now,
            timezone_name="Asia/Shanghai",
        )
        utc = compute_budget_quantile_suggestion(
            db,
            tenant_id="owner",
            category="timezone-cat",
            look_back_months=1,
            include_zero_months=False,
            min_months=1,
            now=now,
            timezone_name="UTC",
        )

    assert shanghai is not None
    assert shanghai.p50_cents == 777
    assert utc is not None
    assert utc.p50_cents == 777
