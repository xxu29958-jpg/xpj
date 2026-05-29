"""v1.2 P3 — monthly report + budget explanation contract."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database import SessionLocal
from app.models import Expense
from app.services.monthly_report_service import (
    compose_budget_explanation,
    compose_monthly_report,
)


def _seed(
    *,
    tenant_id: str = "owner",
    category: str = "餐饮",
    amount_cents: int = 5000,
    confirmed: datetime,
) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=tenant_id,
                amount_cents=amount_cents,
                merchant="m",
                category=category,
                source="pytest",
                raw_text="",
                status="confirmed",
                expense_time=confirmed,
                confirmed_at=confirmed,
            )
        )
        db.commit()


def _seed_with_times(
    *,
    tenant_id: str = "owner",
    category: str = "餐饮",
    amount_cents: int = 5000,
    expense_time: datetime | None,
    confirmed_at: datetime | None,
) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=tenant_id,
                amount_cents=amount_cents,
                merchant="m",
                category=category,
                source="pytest",
                raw_text="",
                status="confirmed",
                expense_time=expense_time,
                confirmed_at=confirmed_at,
            )
        )
        db.commit()


def test_monthly_report_aggregates_total_and_top_categories(*, identity) -> None:
    _seed(category="餐饮", amount_cents=3000, confirmed=datetime(2026, 5, 5, tzinfo=UTC))
    _seed(category="餐饮", amount_cents=2000, confirmed=datetime(2026, 5, 20, tzinfo=UTC))
    _seed(category="购物", amount_cents=8000, confirmed=datetime(2026, 5, 25, tzinfo=UTC))
    with SessionLocal() as db:
        report = compose_monthly_report(
            db, tenant_id="owner", year_month="2026-05"
        )
        assert report.total_cents == 13000
        assert report.expense_count == 3
        assert report.top_categories[0].category == "购物"
        assert report.top_categories[0].amount_cents == 8000
        assert report.top_categories[1].category == "餐饮"
        assert report.top_categories[1].amount_cents == 5000


def test_monthly_report_delta_vs_previous(*, identity) -> None:
    _seed(amount_cents=10000, confirmed=datetime(2026, 4, 10, tzinfo=UTC))
    _seed(amount_cents=12000, confirmed=datetime(2026, 5, 10, tzinfo=UTC))
    with SessionLocal() as db:
        report = compose_monthly_report(
            db, tenant_id="owner", year_month="2026-05"
        )
        assert report.delta_vs_previous_cents == 2000
        assert report.delta_pct is not None
        assert round(report.delta_pct, 1) == 20.0


def test_monthly_report_handles_zero_previous(*, identity) -> None:
    _seed(amount_cents=5000, confirmed=datetime(2026, 5, 10, tzinfo=UTC))
    with SessionLocal() as db:
        report = compose_monthly_report(
            db, tenant_id="owner", year_month="2026-05"
        )
        assert report.delta_vs_previous_cents == 5000
        assert report.delta_pct is None  # no baseline → undefined


def test_budget_explanation_over_p75_verdict(*, identity) -> None:
    # 5 months baseline at 1000, 2000, 3000, 4000, 5000
    for month, amount in enumerate([1000, 2000, 3000, 4000, 5000], start=1):
        _seed(
            amount_cents=amount,
            confirmed=datetime(2026, month, 10, tzinfo=UTC),
        )
    # June spend of 10000 — way above the trailing P75.
    _seed(amount_cents=10000, confirmed=datetime(2026, 6, 5, tzinfo=UTC))
    with SessionLocal() as db:
        explanation = compose_budget_explanation(
            db, tenant_id="owner", category="餐饮", year_month="2026-06"
        )
        assert explanation.verdict == "over_p75"
        assert explanation.actual_cents == 10000
        assert explanation.delta_vs_p75_cents > 0


def test_budget_explanation_on_track_when_below_p75(*, identity) -> None:
    for month, amount in enumerate([1000, 2000, 3000, 4000, 5000], start=1):
        _seed(
            amount_cents=amount,
            confirmed=datetime(2026, month, 10, tzinfo=UTC),
        )
    # June spend of 3500 stays below the trailing P75.
    _seed(amount_cents=3500, confirmed=datetime(2026, 6, 5, tzinfo=UTC))
    with SessionLocal() as db:
        explanation = compose_budget_explanation(
            db, tenant_id="owner", category="餐饮", year_month="2026-06"
        )
        assert explanation.verdict in ("on_track", "under")


def test_budget_explanation_no_history(*, identity) -> None:
    _seed(amount_cents=1500, confirmed=datetime(2026, 5, 10, tzinfo=UTC))
    with SessionLocal() as db:
        explanation = compose_budget_explanation(
            db, tenant_id="owner", category="餐饮", year_month="2026-05"
        )
        assert explanation.verdict == "no_history"
        assert explanation.p75_cents is None


def test_budget_explanation_aggregates_legacy_category_alias(*, identity) -> None:
    """'吃饭' is a legacy alias of '餐饮'; actual + baseline must fold both so a
    tenant with un-normalized legacy rows still gets one coherent explanation."""
    # Trailing baseline split across the canonical name and its legacy alias.
    for month, (cat, amount) in enumerate(
        [("餐饮", 1000), ("吃饭", 2000), ("餐饮", 3000), ("吃饭", 4000), ("餐饮", 5000)],
        start=1,
    ):
        _seed(
            category=cat,
            amount_cents=amount,
            confirmed=datetime(2026, month, 10, tzinfo=UTC),
        )
    # Current-month spend recorded under the legacy alias only.
    _seed(category="吃饭", amount_cents=3500, confirmed=datetime(2026, 6, 5, tzinfo=UTC))

    with SessionLocal() as db:
        explanation = compose_budget_explanation(
            db, tenant_id="owner", category="餐饮", year_month="2026-06"
        )
    # Exact-match would report 0 here; alias aggregation counts the 吃饭 spend.
    assert explanation.actual_cents == 3500
    assert explanation.p75_cents is not None


def test_monthly_report_tenant_isolation(*, identity) -> None:
    _seed(tenant_id="owner", amount_cents=5000, confirmed=datetime(2026, 5, 5, tzinfo=UTC))
    with SessionLocal() as db:
        owner = compose_monthly_report(
            db, tenant_id="owner", year_month="2026-05"
        )
        tester = compose_monthly_report(
            db, tenant_id="tester_1", year_month="2026-05"
        )
        assert owner.total_cents == 5000
        assert tester.total_cents == 0


def test_monthly_report_uses_expense_time_and_accounting_timezone(
    *, identity,
) -> None:
    _seed_with_times(
        category="timezone-cat",
        amount_cents=1000,
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
    )
    _seed_with_times(
        category="timezone-cat",
        amount_cents=2000,
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 45, tzinfo=UTC),
    )

    with SessionLocal() as db:
        shanghai = compose_monthly_report(
            db,
            tenant_id="owner",
            year_month="2026-05",
            timezone_name="Asia/Shanghai",
        )
        utc = compose_monthly_report(
            db,
            tenant_id="owner",
            year_month="2026-05",
            timezone_name="UTC",
        )

    assert shanghai.total_cents == 3000
    assert utc.total_cents == 0
