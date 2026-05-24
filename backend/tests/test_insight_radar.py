"""v1.2 P2 — cashflow radar + subscription radar contract."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database import SessionLocal
from app.models import Expense, MonthlyIncomePlan
from app.services.insight_radar_service import (
    cashflow_radar,
    subscription_radar,
)


def _add_expense(
    *,
    tenant_id: str = "owner",
    merchant: str = "x",
    amount_cents: int = 1000,
    confirmed: datetime,
) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=tenant_id,
                amount_cents=amount_cents,
                merchant=merchant,
                category="餐饮",
                source="pytest",
                raw_text="",
                status="confirmed",
                expense_time=confirmed,
                confirmed_at=confirmed,
            )
        )
        db.commit()


def _add_expense_with_times(
    *,
    tenant_id: str = "owner",
    merchant: str = "x",
    amount_cents: int = 1000,
    expense_time: datetime | None,
    confirmed_at: datetime | None,
) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=tenant_id,
                amount_cents=amount_cents,
                merchant=merchant,
                category="餐饮",
                source="pytest",
                raw_text="",
                status="confirmed",
                expense_time=expense_time,
                confirmed_at=confirmed_at,
            )
        )
        db.commit()


def _add_income_plan(*, tenant_id: str = "owner", amount_cents: int) -> None:
    with SessionLocal() as db:
        db.add(
            MonthlyIncomePlan(
                tenant_id=tenant_id,
                label="pytest",
                source_type="salary",
                amount_cents=amount_cents,
                pay_day=10,
                status="active",
            )
        )
        db.commit()


def test_cashflow_radar_emits_one_row_per_month(*, identity) -> None:
    _add_income_plan(amount_cents=10000)
    _add_expense(amount_cents=2000, confirmed=datetime(2026, 5, 1, tzinfo=UTC))
    _add_expense(amount_cents=3000, confirmed=datetime(2026, 5, 15, tzinfo=UTC))
    _add_expense(amount_cents=4000, confirmed=datetime(2026, 6, 1, tzinfo=UTC))
    now = datetime(2026, 6, 20, tzinfo=UTC)
    with SessionLocal() as db:
        rows = cashflow_radar(
            db, tenant_id="owner", look_back_months=2, now=now
        )
        assert len(rows) == 2
        by_month = {r.year_month: r for r in rows}
        assert by_month["2026-05"].income_cents == 10000
        assert by_month["2026-05"].expense_cents == 5000
        assert by_month["2026-05"].net_cents == 5000
        assert by_month["2026-06"].expense_cents == 4000


def test_subscription_radar_detects_regular_charges(*, identity) -> None:
    # Same merchant, ~same amount, distinct months → subscription.
    for month in (1, 2, 3, 4):
        _add_expense(
            merchant="Netflix",
            amount_cents=4500,
            confirmed=datetime(2026, month, 5, tzinfo=UTC),
        )
    now = datetime(2026, 4, 30, tzinfo=UTC)
    with SessionLocal() as db:
        candidates = subscription_radar(
            db, tenant_id="owner", look_back_months=6, now=now
        )
        merchants = {c.merchant for c in candidates}
        assert "Netflix" in merchants
        netflix = next(c for c in candidates if c.merchant == "Netflix")
        assert netflix.months_covered == 4
        assert netflix.typical_amount_cents == 4500
        assert netflix.last_seen_month == "2026-04"


def test_subscription_radar_rejects_irregular_amounts(*, identity) -> None:
    # Same merchant 4 months but the last month is double the
    # typical — falls outside ±10% tolerance.
    for month, amount in [
        (1, 4500),
        (2, 4500),
        (3, 4500),
        (4, 9000),
    ]:
        _add_expense(
            merchant="Highly Variable",
            amount_cents=amount,
            confirmed=datetime(2026, month, 5, tzinfo=UTC),
        )
    now = datetime(2026, 4, 30, tzinfo=UTC)
    with SessionLocal() as db:
        candidates = subscription_radar(
            db, tenant_id="owner", look_back_months=6, now=now
        )
        assert all(c.merchant != "Highly Variable" for c in candidates)


def test_subscription_radar_under_min_occurrences_skipped(
    *, identity,
) -> None:
    # Same merchant twice — below default min_occurrences (3).
    _add_expense(
        merchant="Sometimes",
        amount_cents=2000,
        confirmed=datetime(2026, 1, 5, tzinfo=UTC),
    )
    _add_expense(
        merchant="Sometimes",
        amount_cents=2000,
        confirmed=datetime(2026, 2, 5, tzinfo=UTC),
    )
    now = datetime(2026, 3, 30, tzinfo=UTC)
    with SessionLocal() as db:
        candidates = subscription_radar(
            db, tenant_id="owner", look_back_months=6, now=now
        )
        assert all(c.merchant != "Sometimes" for c in candidates)


def test_subscription_radar_tenant_isolation(*, identity) -> None:
    for month in (1, 2, 3, 4):
        _add_expense(
            tenant_id="owner",
            merchant="Cloud Sub",
            amount_cents=999,
            confirmed=datetime(2026, month, 5, tzinfo=UTC),
        )
    now = datetime(2026, 4, 30, tzinfo=UTC)
    with SessionLocal() as db:
        owner = subscription_radar(db, tenant_id="owner", now=now)
        tester = subscription_radar(db, tenant_id="tester_1", now=now)
        assert any(c.merchant == "Cloud Sub" for c in owner)
        assert tester == []


def test_cashflow_radar_uses_expense_time_and_accounting_timezone(
    *, identity,
) -> None:
    _add_expense_with_times(
        amount_cents=1000,
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
    )
    _add_expense_with_times(
        amount_cents=2000,
        expense_time=None,
        confirmed_at=datetime(2026, 4, 30, 16, 45, tzinfo=UTC),
    )
    now = datetime(2026, 6, 20, tzinfo=UTC)

    with SessionLocal() as db:
        shanghai = cashflow_radar(
            db,
            tenant_id="owner",
            look_back_months=2,
            now=now,
            timezone_name="Asia/Shanghai",
        )
        utc = cashflow_radar(
            db,
            tenant_id="owner",
            look_back_months=2,
            now=now,
            timezone_name="UTC",
        )

    shanghai_by_month = {row.year_month: row for row in shanghai}
    utc_by_month = {row.year_month: row for row in utc}
    assert shanghai_by_month["2026-05"].expense_cents == 3000
    assert utc_by_month["2026-05"].expense_cents == 0


def test_subscription_radar_groups_by_expense_time_not_confirmation_time(
    *, identity,
) -> None:
    for month in (1, 2, 3):
        _add_expense_with_times(
            merchant="Same Confirmed Batch",
            amount_cents=3000,
            expense_time=datetime(2026, month, 5, tzinfo=UTC),
            confirmed_at=datetime(2026, 4, 20, tzinfo=UTC),
        )
    now = datetime(2026, 4, 30, tzinfo=UTC)

    with SessionLocal() as db:
        candidates = subscription_radar(
            db,
            tenant_id="owner",
            look_back_months=4,
            now=now,
            timezone_name="UTC",
        )

    assert any(c.merchant == "Same Confirmed Batch" for c in candidates)
