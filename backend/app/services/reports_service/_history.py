"""Projected history charts and links to the largest recorded expense facts."""

from datetime import timedelta

from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.services.budget_service import _get_budget
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import minor_amount_major_number, minor_amount_value, normalize_currency_code
from app.services.money_projection_service import (
    ordered_projection_gaps,
    project_recorded_amount,
    sum_projected_amounts,
)
from app.services.reports_service._aggregation import (
    _amount_count,
    _entries_in_range,
)
from app.services.reports_service._models import ExpenseRanking, RankedExpense
from app.services.reports_service._time import _month_bounds, _month_labels_ending_at, _resolve_timezone
from app.services.spending_projection_service import entry_gaps, read_projected_entries
from app.services.time_service import now_utc


def _history_row(db, *, tenant_id, month, period, entries, home, zone, today, rate_cache):
    rows = _entries_in_range(entries, period, zone)
    gaps = set(entry_gaps(rows))
    amount, count = _amount_count(rows)
    budget = _get_budget(db, tenant_id=tenant_id, month=month)
    limit = 0
    if budget is not None:
        rate_date = min(today, period[1].astimezone(zone).date() - timedelta(days=1))
        limit = sum_projected_amounts((project_recorded_amount(db, tenant_id=tenant_id,
            amount_minor=value, source_currency=budget.home_currency_code, home_currency=home,
            rate_date=rate_date, missing_rates=gaps, rate_cache=rate_cache)
            for value in (budget.total_amount_cents, budget.rollover_amount_cents)), label="reports.budget_available")
    return {"month": month, "home_currency_code": home, "missing_rates": ordered_projection_gaps(gaps),
        "amount_cents": amount, "count": count, "budget_cents": limit,
        "amount_yuan": None if amount is None else minor_amount_major_number(amount, home),
        "amount_major_text": None if amount is None else minor_amount_value(amount, home),
        "budget_yuan": None if limit is None else minor_amount_major_number(limit, home),
        "budget_major_text": None if limit is None else minor_amount_value(limit, home)}


def six_month_summary(db, *, anchor_month, tenant_id, timezone_name=None, currency_code=None):
    timezone_key, zone = _resolve_timezone(timezone_name)
    home = normalize_currency_code(currency_code or require_runtime_home_currency_code(db))
    months = _month_labels_ending_at(anchor_month, 6)
    periods = [_month_bounds(month, timezone_key) for month in months]
    entries = read_projected_entries(db, tenant_id=tenant_id, ranges=periods, timezone_name=timezone_key, home=home)
    rate_cache = {}
    today = now_utc().astimezone(zone).date()
    return [_history_row(db, tenant_id=tenant_id, month=month, period=period, entries=entries,
        home=home, zone=zone, today=today, rate_cache=rate_cache)
        for month, period in zip(months, periods, strict=True)]


def top_expenses_for_month(db, *, tenant_id, month=None, tag=None, timezone_name=None, limit=5, home_currency_code=None):
    timezone_key, zone = _resolve_timezone(timezone_name)
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    target_month = month or now_utc().astimezone(zone).strftime("%Y-%m")
    entries = read_projected_entries(db, tenant_id=tenant_id, ranges=[_month_bounds(target_month, timezone_key)],
        timezone_name=timezone_key, home=home, tag=tag)
    roots = [entry for entry in entries if entry.entry_kind == "expense"]
    gaps = entry_gaps(roots)
    if gaps:
        return ExpenseRanking(home, (), gaps)
    ranked = sorted(roots, key=lambda entry: (-entry.amount_cents, -entry.entry_id))[:limit]
    if not ranked:
        return ExpenseRanking(home, (), ())
    records = {expense.id: expense for expense in db.scalars(ledger_scoped_select(Expense, tenant_id).where(
        Expense.id.in_([entry.root_expense_id for entry in ranked])))}
    items = tuple(RankedExpense(records[entry.root_expense_id], entry.amount_cents)
        for entry in ranked if entry.root_expense_id in records)
    return ExpenseRanking(home, items, ())
