"""A current-period default follows the ledger; captured periods never move."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import Expense, LedgerCalendarRevision
from app.routes import recurring, reports, web_reports
from app.routes._web_expense_return_context import ExpenseReturnContext
from app.services import ledger_calendar_service, spending_contract_service, time_service


@pytest.fixture
def boundary(monkeypatch):
    instant = datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    monkeypatch.setattr(time_service, "now_utc", lambda: instant)
    monkeypatch.setattr(ledger_calendar_service, "now_utc", lambda: instant)
    monkeypatch.setattr(spending_contract_service, "get_settings", lambda:
        SimpleNamespace(ocr_default_timezone="UTC"))
    db = Mock(spec=Session)
    db.scalar.return_value = LedgerCalendarRevision(
        ledger_id="household", revision=2, timezone_name="Asia/Shanghai")
    return db, SimpleNamespace(tenant_id="household")


@pytest.mark.parametrize("requested,expected", [("current", date(2026, 5, 1)), ("2026-03", date(2026, 3, 1))])
def test_current_occurrence_uses_ledger_calendar_and_keeps_chosen_period(boundary, monkeypatch, requested, expected):
    db, auth = boundary
    monkeypatch.setattr(recurring, "get_recurring_item", lambda *_a, **_kw: SimpleNamespace(tenant_id=auth.tenant_id))
    monkeypatch.setattr(recurring, "occurrence_response", lambda _db, *, item, period: period)
    assert recurring.get_recurring_occurrence("series", requested, auth, db) == expected
    if requested != "current":
        db.scalar.assert_not_called()


@pytest.mark.parametrize("display_zone", ["UTC", "America/Los_Angeles"])
@pytest.mark.parametrize("requested,expected", [(None, "2026-05"), ("2026-03", "2026-03")])
def test_report_export_default_and_filename_do_not_follow_display_zone(boundary, monkeypatch, display_zone, requested, expected):
    db, auth = boundary
    export = Mock(return_value="category,amount\n")
    monkeypatch.setattr(reports, "export_reports_overview_csv", export)
    response = reports.get_reports_overview_csv(month=requested, timezone=display_zone, auth=auth, db=db,
        home_currency_code="CNY", top_n=8, merchant_category=None)
    assert export.call_args.kwargs["month"] == expected
    assert f"{expected}-day.csv" in response.headers["content-disposition"]
    if requested is not None:
        db.scalar.assert_not_called()


@pytest.mark.parametrize("instant", [None, datetime(2026, 4, 30, 16, 30, tzinfo=UTC)])
def test_report_ranked_expense_displays_saved_day_even_without_clock(monkeypatch, instant):
    expense = Expense(id=7, merchant="subscription", amount_cents=10000,
        expense_time=instant, accounting_date=date(2026, 5, 1))
    monkeypatch.setattr(web_reports, "top_expenses_for_month", lambda *_a, **_kw:
        SimpleNamespace(items=[SimpleNamespace(expense=expense, amount_cents=10000)],
            home_currency_code="CNY", missing_rates=[]))
    view = web_reports._top_expenses_view(object(), tenant_id="household", month="2026-05",
        timezone_name="America/Los_Angeles", presentation_currency_code="CNY",
        return_context=ExpenseReturnContext())
    assert view["top_expenses"][0]["expense_time"] == "2026-05-01"
