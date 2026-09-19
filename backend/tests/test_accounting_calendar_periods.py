"""Pure time-owner counterexamples; these probes do not validate persistence."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import Expense
from app.services.spending_contract_service import (
    calendar_month_bounds,
    confirmed_query,
    confirmed_stream_query,
    stat_month_label,
    stat_time,
)


@pytest.mark.parametrize("display_zone", ["UTC", "Asia/Shanghai", "America/Los_Angeles"])
def test_frozen_accounting_day_keeps_the_same_financial_month(display_zone: str) -> None:
    expense = Expense(
        status="confirmed",
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 2, 8, tzinfo=UTC),
    )
    # Supply the intended fact snapshot to the existing pure owner. These
    # in-memory values do not claim that the new fields are persisted yet.
    expense.accounting_date = date(2026, 5, 1)
    expense.calendar_revision = 1
    expense.time_precision = "unknown"
    expense.accounting_date_basis = "legacy_expense_time"

    assert stat_month_label(expense, display_zone) == "2026-05"
    assert expense.expense_time == datetime(2026, 4, 30, 16, 30, tzinfo=UTC)


@pytest.mark.parametrize("display_zone", ["UTC", "Asia/Shanghai", "America/Los_Angeles"])
def test_date_only_financial_month_is_not_the_confirmation_month(display_zone: str) -> None:
    expense = Expense(
        status="confirmed",
        expense_time=None,
        confirmed_at=datetime(2026, 5, 2, 8, tzinfo=UTC),
    )
    expense.accounting_date = date(2026, 4, 30)
    expense.user_local_date = date(2026, 4, 30)
    expense.calendar_revision = 1
    expense.time_precision = "date_only"

    assert stat_month_label(expense, display_zone) == "2026-04"


def test_date_only_does_not_present_confirmation_as_an_event_instant() -> None:
    expense = Expense(
        status="confirmed",
        expense_time=None,
        confirmed_at=datetime(2026, 5, 2, 8, tzinfo=UTC),
    )
    expense.accounting_date = date(2026, 4, 30)
    expense.time_precision = "date_only"

    assert stat_time(expense) is None


def test_exact_time_preserves_the_recorded_instant() -> None:
    instant = datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    expense = Expense(
        status="confirmed", expense_time=instant,
        confirmed_at=datetime(2026, 5, 2, 8, tzinfo=UTC),
    )
    expense.accounting_date = date(2026, 5, 1)
    expense.time_precision = "instant"

    assert stat_time(expense) == instant


@pytest.mark.parametrize("display_zone", ["UTC", "Asia/Shanghai", "America/Los_Angeles"])
def test_root_and_offset_month_predicates_use_the_same_saved_day(display_zone):
    root_query = confirmed_query(tenant_id="calendar-test", month="2026-05", timezone_name=display_zone)
    stream = confirmed_stream_query(tenant_id="calendar-test", month="2026-05", timezone_name=display_zone)
    statements = [root_query, select(stream)]
    for statement in statements:
        sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert "expenses.accounting_date >= '2026-05-01'" in sql
        assert "expenses.accounting_date < '2026-06-01'" in sql
        assert "timezone(" not in sql
        assert "expenses.expense_time >=" not in sql and "expenses.confirmed_at >=" not in sql
    assert "expense_offset_facts.accounting_date >= '2026-05-01'" in sql
    assert "expense_offset_facts.accounting_date < '2026-06-01'" in sql


def test_missing_saved_day_stays_unknown_instead_of_reinterpreting_old_time():
    expense = Expense(status="confirmed", expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC))
    assert stat_month_label(expense, "UTC") is None
    assert stat_month_label(expense, "Asia/Shanghai") is None


@pytest.mark.parametrize("display_zone", ["UTC", "Asia/Shanghai", "America/Los_Angeles"])
@pytest.mark.parametrize("granularity", ["day", "week", "month"])
def test_report_buckets_keep_recorded_dates_across_display_zones(display_zone, granularity):
    from app.services.reports_service._aggregation import _trend_buckets, _trend_points

    entries = [SimpleNamespace(stream_date=date(2026, 5, 1), amount_cents=10000),
        SimpleNamespace(stream_date=date(2026, 5, 1), amount_cents=-2000)]
    zone = ZoneInfo(display_zone)
    buckets = _trend_buckets(month="2026-05", granularity=granularity, timezone_name=display_zone, zone=zone)
    points = _trend_points(entries, buckets, zone)
    assert sum(point["amount_cents"] for point in points) == 8000
    assert sum(point["count"] for point in points) == 2
    expected_bucket = "2026-05" if granularity == "month" else "2026-04-27" if granularity == "week" else "2026-05-01"
    assert next(point for point in points if point["bucket"] == expected_bucket)["amount_cents"] == 8000


def test_recurring_candidates_count_date_only_months_without_fabricating_last_seen_instant():
    from app.services.insights_service import _candidate_from_entries, _group_recurring_entries

    expenses = [Expense(status="confirmed", merchant="Calendar subscription", amount_cents=10000,
        home_currency_code="CNY", accounting_date=day, time_precision="date_only", calendar_revision=1)
        for day in (date(2026, 4, 30), date(2026, 5, 1))]
    grouped = _group_recurring_entries(object(), expenses, tenant_id="calendar-test", home="CNY",
        timezone_name="UTC", formal_keys=set())
    candidate = _candidate_from_entries(next(iter(grouped.values())), timezone_name="America/Los_Angeles", min_occurrences=2)
    assert candidate["occurrence_count"] == 2
    assert candidate["amount_cents"] == 10000
    assert candidate["last_seen_at"] is None


def test_recurring_observation_period_uses_accounting_day_not_original_instant():
    from app.models import RecurringItem
    from app.services.recurring_service import _recurring_observation_groups

    item = RecurringItem(merchant_key="calendar subscription", merchant_name="Calendar subscription",
        baseline_amount_cents=10000, last_amount_cents=10000, home_currency_code="CNY")
    expense = Expense(tenant_id="calendar-test", status="confirmed", merchant=item.merchant_name,
        amount_cents=10000, home_currency_code="CNY", accounting_date=date(2026, 5, 1),
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC), calendar_revision=1)
    db = Mock(spec=Session)
    db.scalars.return_value = [expense]
    start, end = calendar_month_bounds("2026-05")
    history, current, missing = _recurring_observation_groups(db, tenant_id="calendar-test", items=[item], start=start, end=end)
    assert history[item.merchant_key] == [] and not missing
    assert current[item.merchant_key] == [(date(2026, 5, 1), 10000)]


def test_date_only_csv_keeps_the_financial_day_without_confirmation_as_event_time():
    from app.services.stats_service import _confirmed_stream_csv_row

    expense = Expense(id=1, public_id="calendar-root", status="confirmed", amount_cents=10000,
        original_currency_code="CNY", original_amount_minor=10000, home_currency_code="CNY", category="其他", source="手动记账",
        accounting_date=date(2026, 4, 30), time_precision="date_only", calendar_revision=1,
        confirmed_at=datetime(2026, 5, 2, tzinfo=UTC))
    entry = SimpleNamespace(root=expense, entry_kind="expense", stream_date=expense.accounting_date,
        stream_amount_cents=10000, lineage_status="normal", lineage_home_net_cents=10000)
    row = _confirmed_stream_csv_row(entry)
    assert row[13] == ""
    assert row[14] == "2026-05-02T00:00:00Z"
    assert row[24] == "2026-04-30"
