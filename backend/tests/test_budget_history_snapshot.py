"""Small real serializer probes; these do not stand in for PG transaction tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from app.models import Budget, BudgetCategory
from app.routes.web_budgets import _history_money
from app.services.budget_history_service import record_budget_revision


def test_snapshot_keeps_original_money_and_categories_after_current_rows_change():
    budget = Budget(id=7, tenant_id="owner", month="2026-09", home_currency_code="JPY",
        total_amount_cents=1200, non_monthly_amount_cents=100, rollover_amount_cents=-20,
        excluded_categories='["旅行"]', row_version=4, archived_at=None)
    category = BudgetCategory(category="餐饮", amount_cents=300)
    db = Mock()
    db.scalars.return_value.all.return_value = [category]
    record_budget_revision(db, budget, change_kind="edit", actor_account_id=3)
    recorded = db.add.call_args.args[0]
    budget.total_amount_cents = 5000
    budget.archived_at = datetime.now(UTC)
    category.amount_cents = 1
    assert recorded.snapshot == {"home_currency_code": "JPY", "total_amount_cents": 1200,
        "non_monthly_amount_cents": 100, "rollover_amount_cents": -20,
        "excluded_categories": ["旅行"], "archived": False,
        "category_budgets": [{"category": "餐饮", "amount_cents": 300}]}
    assert (recorded.row_version, recorded.tenant_id, recorded.budget_id, recorded.actor_account_id) == (4, "owner", 7, 3)
    db.commit.assert_not_called()


def test_recorded_money_never_uses_the_current_ledger_currency_or_guesses_unknown_units():
    assert _history_money(1200, "JPY") == "¥1,200"
    assert _history_money(1200, "USD") == "$12.00"
    assert _history_money(1200, None) == "1200 最小单位（原币种未记录）"


def test_web_history_renders_saved_arrangements_and_escaped_category_without_requiring_javascript():
    from jinja2 import DictLoader

    from app.routes.web_common import templates
    from app.schemas._budget_history import BudgetHistoryResponse, BudgetRevisionResponse, BudgetSnapshot

    env = templates.env.overlay(loader=DictLoader({"base.html": "{% block content %}{% endblock %}"}))
    source = templates.env.loader.get_source(templates.env, "budget_history.html")[0]
    history = BudgetHistoryResponse(ledger_id="owner", month="2026-09", next_before_version=4,
        items=[BudgetRevisionResponse(row_version=4, change_kind="baseline", recorded_at=datetime.now(UTC),
            snapshot=BudgetSnapshot(home_currency_code="JPY", total_amount_cents=1200,
                non_monthly_amount_cents=100, rollover_amount_cents=-20, excluded_categories=[], archived=True,
                category_budgets=[{"category": "<script>evil</script>", "amount_cents": 300}]))])
    rendered = env.from_string(source).render(history=history, month="2026-09", selected_ledger_id="owner",
        before_version=None, history_money=_history_money, request=SimpleNamespace())
    assert "¥1,200" in rendered and "更早的修改没有记录" in rendered and "已归档" in rendered
    assert "&lt;script&gt;evil&lt;/script&gt;" in rendered and "<script>evil</script>" not in rendered
    assert "before_version=4" in rendered
