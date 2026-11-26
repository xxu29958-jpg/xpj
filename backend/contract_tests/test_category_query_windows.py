"""Check the PostgreSQL query shape without opening a database connection."""

from unittest.mock import Mock

from sqlalchemy.dialects import postgresql

from app.services.category_service import (
    CATEGORY_OPTION_LIMIT,
    list_ledger_category_options,
    list_uncategorized_pending,
)


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_option_queries_limit_both_sources_and_pin_selection_inside_window():
    db = Mock()
    history = [f"item-{index:04}" for index in range(CATEGORY_OPTION_LIMIT)]
    db.scalars.side_effect = [history, ["item-preference"], []]
    options = list_ledger_category_options(db, tenant_id="owner", query="item-", selected="selected")
    assert len(options) == CATEGORY_OPTION_LIMIT
    assert options[:-1] == history[:CATEGORY_OPTION_LIMIT - 1]
    assert options[-1] == "selected"
    for call in db.scalars.call_args_list[:2]:
        sql = _sql(call.args[0])
        assert "ORDER BY" in sql and f"LIMIT {CATEGORY_OPTION_LIMIT}" in sql and "LIKE" in sql


def test_pending_task_filters_before_its_only_bounded_query():
    db = Mock()
    db.scalars.return_value = []
    assert list_uncategorized_pending(db, tenant_id="owner") == []
    db.scalars.assert_called_once()
    sql = _sql(db.scalars.call_args.args[0])
    assert "DISTINCT" not in sql and "btrim(" in sql
    assert "ORDER BY expenses.created_at DESC, expenses.id DESC" in sql
    assert "LIMIT 200" in sql
