"""Pure time-owner counterexamples; these probes do not validate persistence."""

from datetime import UTC, date, datetime

import pytest

from app.models import Expense
from app.services.spending_contract_service import stat_month_label, stat_time


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
