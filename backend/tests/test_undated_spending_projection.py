"""Unknown accounting dates stay recoverable and cannot imply a complete zero."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.models import Expense, Goal
from app.schemas import ExpenseResponse
from app.schemas._expense_stream import ConfirmedExpenseStreamItem, ConfirmedOffsetStreamProjection
from app.services import budget_service, goal_spending_response, monthly_report_service, stats_service
from app.services.expense_service._query import _stream_entry
from app.services.reports_service import _api, _history, _ranking
from app.services.spending_contract_service import count_undated_expenses


class ProjectionRows:
    def __init__(self, *, undated=(("餐饮", 1),), entries=()):
        self.undated, self.entries, self.statements = undated, entries, []

    def execute(self, statement):
        self.statements.append(statement)
        names = [column.name for column in statement.selected_columns]
        if names == ["category", "count"]:
            return iter(self.undated)
        return iter([*self.entries, *(SimpleNamespace(entry_kind="expense", stream_date=None, category=category)
            for category, count in self.undated for _ in range(count))])

    def scalars(self, statement):
        return iter(())


def test_undated_count_is_scoped_before_periods_and_aliases_are_not_lost():
    db = ProjectionRows(undated=(("餐饮", 2), ("吃饭", 1), ("数码", 4)))
    assert count_undated_expenses(db, tenant_id="selected", category="餐饮", tag="reimbursement") == 3
    sql = str(db.statements[-1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "expenses.tenant_id = 'selected'" in sql
    assert "expenses.status = 'confirmed'" in sql and "expenses.accounting_date IS NULL" in sql
    assert "tags.key = 'reimbursement'" in sql
    assert "accounting_date >=" not in sql
    assert count_undated_expenses(db, tenant_id="selected", category="交通") == 0


def test_unknown_root_stream_and_csv_keep_money_and_blank_date_but_offsets_require_date():
    root = Expense(id=9, tenant_id="owner", status="confirmed", amount_cents=1234,
        original_amount_minor=1234, original_currency_code="CNY", home_currency_code="CNY")
    response = ExpenseResponse.model_construct(id=9, public_id="unknown-root", amount_cents=1234,
        home_currency="CNY", original_currency_code="CNY", original_amount_minor=1234,
        exchange_rate_to_cny=None, exchange_rate_date=None, exchange_rate_source=None,
        merchant="Original", category="餐饮", note="", source="manual", expense_time=None,
        confirmed_at=None, tags=None, value_score=None, regret_score=None, accounting_time=None)
    entry = _stream_entry(root, response, [], offset=None, stream_date=None,
        stream_sort_time=datetime(2026, 5, 20, tzinfo=UTC), stream_sort_id=9)
    row = stats_service._confirmed_stream_csv_row(entry)
    assert entry.stream_date is None and entry.stream_amount_cents == 1234
    assert row[13:15] == ["", ""] and row[24] == "" and row[25] == 1234
    offset = ConfirmedOffsetStreamProjection(public_id="refund", kind="refund", amount_cents=1,
        original_amount_minor=1, original_currency_code="CNY", home_currency_code="CNY", category="餐饮")
    with pytest.raises(ValidationError, match="accounting date"):
        ConfirmedExpenseStreamItem(**{**entry.model_dump(), "root": response, "entry_kind": "offset", "offset": offset})


def test_monthly_and_report_totals_are_unknown_without_fake_fx_gaps(monkeypatch):
    db = ProjectionRows()
    monthly = stats_service.monthly_stats(db, "2026-05", "owner", home_currency_code="CNY")
    assert (monthly["undated_expense_count"], monthly["total_amount_cents"], monthly["missing_rates"]) == (1, None, ())
    assert len(db.statements) == 1  # A correction cannot commit between the period and gap reads.
    assert "confirmed_stream.stream_date IS NULL" in str(db.statements[0])
    monkeypatch.setattr(_api, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    monkeypatch.setattr(_ranking, "enabled_merchant_display_map", lambda *a, **kw: {})
    report = _api.reports_overview(db, month="2026-05", tenant_id="owner", home_currency_code="CNY")
    assert report["undated_expense_count"] == 1 and report["missing_rates"] == ()
    assert report["total_amount_cents"] is report["previous_total_amount_cents"] is None
    assert report["year_over_year_delta_amount_cents"] is report["year_over_year_delta_count"] is None
    assert all(row["amount_cents"] is None for row in report["trend"])
    assert report["category_comparison"][0]["delta_amount_cents"] is None
    assert report["merchant_ranking"] == []
    composed = monthly_report_service.compose_monthly_report(db, tenant_id="owner", year_month="2026-05", home_currency_code="CNY")
    assert composed.undated_expense_count == 1 and composed.total_cents is None
    assert composed.delta_vs_previous_cents is None and composed.missing_rates == ()
    monkeypatch.setattr(_history, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    monkeypatch.setattr(_history, "_get_budget", lambda *a, **kw: None)
    history = _history.six_month_summary(db, anchor_month="2026-05", tenant_id="owner", currency_code="CNY")
    assert all(item["amount_cents"] is None and item["undated_expense_count"] == 1 for item in history)


def test_budget_and_goal_preserve_unaffected_category_capability(monkeypatch):
    db = ProjectionRows()
    budget = SimpleNamespace(home_currency_code="CNY", excluded_categories="[]", total_amount_cents=5000,
        rollover_amount_cents=0, non_monthly_amount_cents=0, row_version=1, updated_at=None)
    monkeypatch.setattr(budget_service, "_get_budget", lambda *a, **kw: budget)
    monkeypatch.setattr(budget_service, "_list_category_budgets", lambda *a, **kw: [
        SimpleNamespace(category="餐饮", amount_cents=3000), SimpleNamespace(category="数码", amount_cents=2000)])
    monkeypatch.setattr(budget_service, "_fixed_amount_cents_for_month", lambda *a, **kw: 0)
    result = budget_service.get_monthly_budget(db, tenant_id="owner", month="2026-05")
    assert result.undated_expense_count == 1 and result.missing_currency_codes == []
    assert result.spent_amount_cents is result.remaining_amount_cents is result.overspent_amount_cents is None
    by_category = {item.category: item for item in result.category_budgets}
    assert by_category["餐饮"].remaining_amount_cents is None
    assert by_category["数码"].remaining_amount_cents == 2000
    totals = goal_spending_response.month_spend_totals(db, tenant_id="owner", month="2026-05", home_currency_code="CNY")
    now = datetime(2026, 5, 1, tzinfo=UTC)
    goal = Goal(public_id="goal", tenant_id="owner", name="Limit", goal_type="spending_limit", period="monthly",
        home_currency_code="CNY", month="2026-05", category="餐饮", target_amount_cents=3000,
        status="active", created_at=now, updated_at=now, row_version=1)
    affected = goal_spending_response.goal_response(goal, totals)
    assert affected.undated_expense_count == 1 and affected.progress_state == "unavailable"
    assert affected.remaining_amount_cents is affected.progress_percent is None
    goal.category = "数码"
    unaffected = goal_spending_response.goal_response(goal, totals)
    assert unaffected.undated_expense_count == 0 and unaffected.remaining_amount_cents == 3000
    budget.excluded_categories = '["餐饮"]'
    excluded = budget_service.get_monthly_budget(db, tenant_id="owner", month="2026-05")
    assert excluded.remaining_amount_cents == 5000 and excluded.excluded_amount_cents is None


def test_quantile_does_not_train_on_false_zero_months_and_keeps_other_categories(monkeypatch):
    from app.services.learning_service import _budget_quantile as quantiles

    monkeypatch.setattr(quantiles, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    for category, expected_count in (("餐饮", 1), ("数码", 0)):
        db = ProjectionRows()
        result = quantiles.compute_budget_quantile_suggestion(db, tenant_id="owner", category=category,
            home_currency_code="CNY", now=datetime(2026, 5, 1, tzinfo=UTC))
        assert result.undated_expense_count == expected_count and result.missing_rates == ()
        assert result.p50_cents is None if expected_count else result.p50_cents == 0
        assert len(db.statements) == 1
