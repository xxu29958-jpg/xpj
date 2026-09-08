"""Budget summaries keep record currency and leave missing calculations visible."""

from types import SimpleNamespace

from app.routes.web_budgets import _budget_view
from app.routes.web_common import _dashboard_budget_goals_block
from app.schemas import BudgetCategoryResponse, BudgetMonthlyResponse
from app.services.owner_console_service import _index


def _budget(*, spent=100, remaining=1100):
    return BudgetMonthlyResponse(ledger_id="owner", home_currency_code="JPY", month="2026-09",
        configured=True, row_version=1, total_amount_cents=1200, rollover_amount_cents=0,
        non_monthly_amount_cents=0, fixed_amount_cents=0, flex_budget_cents=1200,
        spent_amount_cents=spent, excluded_amount_cents=0, remaining_amount_cents=remaining,
        overspent_amount_cents=0 if spent is not None else None,
        excluded_categories=[], excluded_breakdown=[],
        category_budgets=[BudgetCategoryResponse(category="餐饮", amount_cents=1200, spent_amount_cents=spent,
            remaining_amount_cents=remaining, overspent_amount_cents=0 if spent is not None else None)],
        missing_currency_codes=[] if spent is not None else ["CNY"])


def test_overview_uses_budget_currency_independently_of_goal_reporting_currency():
    result = _dashboard_budget_goals_block(_budget(), [], currency_code="CNY")
    assert result["budget_home_currency_code"] == "JPY"
    assert result["budget_total_yuan"] == "1200"
    assert result["budget_remaining_yuan"] == "1100"


def test_missing_conversion_has_no_fake_budget_progress_or_available_amount():
    budget = _budget(spent=None, remaining=None)
    overview = _dashboard_budget_goals_block(budget, [], currency_code="CNY")
    page = _budget_view(budget, currency_code="JPY")
    assert overview["budget_remaining_cents"] is None
    assert overview["budget_top"][0]["percent"] is None
    assert not page["has_progress_basis"]
    assert page["missing_currency_codes"] == ["CNY"]
    assert page["form_total_yuan"] == "1200"


def test_owner_budget_summary_preserves_jpy_and_missing_fx(monkeypatch):
    monkeypatch.setattr(_index, "get_monthly_budget", lambda *args, **kw: _budget(spent=None, remaining=None))
    status = _index._budget_status_for_primary_ledger(object(), SimpleNamespace(ledger_id="owner", name="Owner"))
    assert status.total_amount_yuan == "1200"
    assert status.spent_amount_cents is None and status.spent_percent is None
    assert status.missing_currency_codes == ["CNY"]
