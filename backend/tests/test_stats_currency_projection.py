"""Monthly and lifestyle statistics read recorded money before grouping."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import money_projection_service as money
from app.services import stats_service as stats


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

    def execute(self, statement):
        self.statements.append(statement)
        columns = [column.name for column in statement.selected_columns]
        if columns == ["expense_id", "name"]:
            return iter(self.tags)
        assert "home_currency_code" in columns
        return iter(self.rows)

    def scalars(self, statement):
        self.statements.append(statement)
        return iter(self.records)


@pytest.fixture(autouse=True)
def current_context(monkeypatch):
    monkeypatch.setattr(stats, "require_runtime_home_currency_code", lambda db: "JPY", raising=False)
    monkeypatch.setattr(stats, "enabled_merchant_display_map", lambda *a, **kw: {})
    monkeypatch.setattr(stats, "now_utc", lambda: datetime(2026, 9, 9, 12, tzinfo=UTC))
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (Decimal("20"), None, None, None))


def monthly(db, **kwargs):
    return stats.monthly_stats(db, "2026-09", "owner", timezone_name="UTC", **kwargs)


def lifestyle(db):
    return stats.lifestyle_stats(db, "2026-09", "owner", timezone_name="UTC")


def test_month_category_and_tags_sum_projected_amounts_and_signed_offsets(monkeypatch):
    def rate(*args, **kwargs):
        return Decimal("30" if kwargs["rate_date"].day == 8 else "20"), None, None, None

    monkeypatch.setattr(money, "resolve_payload_rate", rate)
    rows = [entry(10000, "CNY", category="吃饭"), entry(3000, id=2, category="餐饮"),
        entry(-102, "CNY", id=3, root_id=1, kind="offset", day=date(2026, 9, 8), category="餐饮")]
    result = monthly(StatsRows(rows, tags=[(1, "旅行"), (1, "咖啡"), (2, "旅行")]))
    assert result["total_amount_cents"] == 4969
    assert result["count"] == 3
    assert result["home_currency_code"] == "JPY"
    assert result["missing_rates"] == ()
    assert result["by_category"] == [{"category": "餐饮", "amount_cents": 4969, "count": 3}]
    assert {item["tag"]: (item["amount_cents"], item["count"]) for item in result["by_tag"]} == {
        "旅行": (4969, 3), "咖啡": (1969, 2)}


def test_unknown_rate_keeps_counts_known_categories_and_tag_gaps(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    result = monthly(StatsRows([entry(10000, "CNY"), entry(3000, id=2, category="交通")],
        tags=[(1, "旅行"), (2, "旅行")]))
    assert result["total_amount_cents"] is None
    assert result["count"] == 2
    assert {item["category"]: item["amount_cents"] for item in result["by_category"]} == {"数码": None, "交通": 3000}
    assert result["by_tag"] == [{"tag": "旅行", "amount_cents": None, "count": 2}]
    assert result["missing_rates"] == (money.ProjectionGap("CNY", "JPY", date(2026, 9, 9)),)


def test_lifestyle_ranks_common_amount_but_keeps_original_fact_currency():
    rows = [entry(10000, "CNY", merchant="CNY shop"), entry(3000, id=2)]
    result = lifestyle(StatsRows(rows))
    assert result["max_expense"].id == 2
    assert result["digital_amount_cents"] == 5000
    assert result["recent_7_days_amount_cents"] == 5000
    assert [(item["merchant"], item["amount_cents"]) for item in result["frequent_merchants"]] == [
        ("JPY shop", 3000), ("CNY shop", 2000)]
    assert [item.id for item in result["best_value_expenses"]] == [2, 1]
    assert [item.id for item in result["most_regretted_expenses"]] == [2, 1]
    assert result["best_value_expenses"][1].home_currency_code == "CNY"
    assert result["best_value_expenses"][1].amount_cents == 10000


def test_missing_rate_keeps_score_order_without_claiming_an_amount_tie_break(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    rows = [entry(10000, "CNY"), entry(3000, id=2)]
    result = lifestyle(StatsRows(rows))
    assert result["max_expense"] is None
    assert result["frequent_merchants"] == [{"merchant": "JPY shop", "amount_cents": None, "count": 2}]
    assert [item.id for item in result["best_value_expenses"]] == [2, 1]
    assert [item.id for item in result["most_regretted_expenses"]] == [2, 1]
    assert result["digital_amount_cents"] is None
    assert result["recent_7_days_amount_cents"] is None
    # Different scores need no currency-based tie-break and retain their facts.
    ranked = lifestyle(StatsRows(rows, records=[fact(rows[0], score=4), fact(rows[1], score=5)]))
    assert [item.id for item in ranked["best_value_expenses"]] == [2, 1]


def test_missing_rate_keeps_merchant_counts_without_ranking_partial_amounts(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    rows = [entry(10000, "CNY", merchant="Frequent"),
        entry(20, id=2, merchant="Frequent"), entry(90000, id=3, merchant="Large known")]
    result = lifestyle(StatsRows(rows))
    assert result["frequent_merchants"] == [
        {"merchant": "Frequent", "amount_cents": None, "count": 2},
        {"merchant": "Large known", "amount_cents": 90000, "count": 1}]


def test_reversed_root_does_not_win_highest_while_event_count_remains():
    rows = [entry(0), entry(100, id=2)]
    reversed_fact = fact(rows[0])
    reversed_fact.amount_cents = 10000
    result = lifestyle(StatsRows(rows, records=[reversed_fact, fact(rows[1])]))
    assert result["max_expense"].id == 2
    assert monthly(StatsRows(rows))["count"] == 2


def test_missing_rate_without_merchant_still_uses_the_announced_count_order(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    rows = [entry(10000, "CNY", merchant=None), entry(20, id=2, merchant="Frequent"),
        entry(30, id=3, merchant="Frequent"), entry(90000, id=4, merchant="Large known")]
    assert lifestyle(StatsRows(rows))["frequent_merchants"] == [
        {"merchant": "Frequent", "amount_cents": 50, "count": 2},
        {"merchant": "Large known", "amount_cents": 90000, "count": 1}]


def test_recent_seven_calendar_days_exclude_eighth_date_and_future():
    rows = [entry(500, day=date(2026, 9, 2)), entry(-100, id=2, kind="offset", day=date(2026, 9, 3)),
        entry(300, id=3), entry(900, id=4, day=date(2026, 9, 10))]
    assert lifestyle(StatsRows(rows))["recent_7_days_amount_cents"] == 200


def test_explicit_task_home_does_not_follow_changed_runtime():
    result = monthly(StatsRows([entry(10000, "CNY")]), home_currency_code="CNY")
    assert result["home_currency_code"] == "CNY"
    assert result["total_amount_cents"] == 10000


def test_empty_month_is_known_zero_not_missing_projection():
    result = monthly(StatsRows([]))
    assert (result["total_amount_cents"], result["count"], result["missing_rates"]) == (0, 0, ())
    assert lifestyle(StatsRows([]))["max_expense"] is None
