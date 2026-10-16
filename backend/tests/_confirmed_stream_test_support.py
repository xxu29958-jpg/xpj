from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any


def confirmed_expense_roots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Project expense roots from the root-always confirmed stream envelope."""

    return [
        item["root"]
        for item in payload["items"]
        if item["entry_kind"] == "expense"
    ]


def entry(amount, currency="JPY", *, id=1, category="数码", merchant="JPY shop",
    day=date(2026, 9, 9), kind="expense", root_id=None):
    return SimpleNamespace(entry_id=id, root_expense_id=root_id or id, entry_kind=kind,
        stream_date=day, stream_amount_cents=amount, home_currency_code=currency,
        category=category, merchant=merchant)


def fact(row, *, score=5):
    moment = datetime.combine(row.stream_date, datetime.min.time(), tzinfo=UTC)
    return SimpleNamespace(id=row.root_expense_id, amount_cents=row.stream_amount_cents,
        home_currency_code=row.home_currency_code, expense_time=moment, confirmed_at=moment,
        value_score=score, regret_score=score, public_id=f"fact-{row.root_expense_id}")


class StatsRows:
    """Controlled database results; actual owners, FX conversion and grouping run."""

    def __init__(self, rows, *, tags=(), records=None):
        self.rows, self.tags = rows, list(tags)
        self.records = records if records is not None else [fact(row) for row in rows if row.entry_kind == "expense"]
        self.statements = []

    def scalar(self, statement):
        assert "ledger_calendar_revisions" in str(statement)
        return SimpleNamespace(timezone_name="UTC")

    def execute(self, statement):
        self.statements.append(statement)
        columns = [column.name for column in statement.selected_columns]
        if columns == ["category", "count"]:
            return iter(())
        if columns == ["expense_id", "name"]:
            return iter(self.tags)
        assert "home_currency_code" in columns
        return iter(self.rows)

    def scalars(self, statement):
        self.statements.append(statement)
        return iter(self.records)
