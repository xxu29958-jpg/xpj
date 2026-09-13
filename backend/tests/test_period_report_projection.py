"""Period reports publish one currency, including uncertain comparisons and CSV."""

import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest

from app.services import money_projection_service as money
from app.services.reports_service import _ranking, export_reports_overview_csv, reports_overview


class StreamRows:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return iter(self.rows)


def entry(amount, currency="JPY", *, day=date(2026, 9, 7), merchant="JPY shop", category="餐饮", kind="expense", id=1):
    return SimpleNamespace(entry_id=id, root_expense_id=id, entry_kind=kind,
        stream_date=day, stream_amount_cents=amount, home_currency_code=currency,
        merchant=merchant, category=category)


@pytest.fixture(autouse=True)
def aliases(monkeypatch):
    monkeypatch.setattr(_ranking, "enabled_merchant_display_map", lambda *a, **kw: {})


def read(db, **kwargs):
    return reports_overview(db, month="2026-09", tenant_id="owner", timezone_name="UTC",
        home_currency_code="JPY", **kwargs)


def test_merchant_ranking_converts_before_comparing_and_aggregating(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (Decimal("20"), None, None, None))
    db = StreamRows([entry(1000), entry(2000, "CNY", merchant="CNY shop", id=2)])
    result = read(db)
    assert result["home_currency_code"] == "JPY"
    assert result["total_amount_cents"] == 1400
    assert result["count"] == 2
    assert [(row["merchant"], row["amount_cents"]) for row in result["merchant_ranking"]] == [
        ("JPY shop", 1000), ("CNY shop", 400)]
    assert result["trend"][6]["amount_cents"] == 1400
    assert result["missing_rates"] == ()
    assert len(db.statements) == 1


def test_missing_rate_keeps_counts_and_unknown_amounts_without_a_false_ranking(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    rows = [entry(1000), entry(2000, "CNY", merchant="CNY shop", category="交通", id=2)]
    result = read(StreamRows(rows))
    assert result["total_amount_cents"] is None
    assert result["year_over_year_delta_amount_cents"] is None
    assert result["count"] == 2
    assert result["trend"][6] == {"bucket": "2026-09-07", "label": "09-07", "amount_cents": None, "count": 2}
    assert result["merchant_ranking"] == []
    assert result["missing_rates"] == (money.ProjectionGap("CNY", "JPY", date(2026, 9, 7)),)
    counted = read(StreamRows(rows), ranking_metric="count")
    assert {row["merchant"]: (row["count"], row["amount_cents"]) for row in counted["merchant_ranking"]} == {
        "JPY shop": (1, 1000), "CNY shop": (1, None)}


def test_previous_gap_does_not_erase_current_total_or_rank(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    result = read(StreamRows([entry(1000), entry(2000, "CNY", day=date(2026, 8, 7))]))
    assert result["total_amount_cents"] == 1000
    assert result["previous_total_amount_cents"] is None
    assert result["category_comparison"][0]["delta_amount_cents"] is None
    assert result["merchant_ranking"][0]["amount_cents"] == 1000


def test_unknown_record_currency_stays_unknown_without_runtime_relabelling(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An unknown source cannot select an exchange-rate pair")

    monkeypatch.setattr(money, "resolve_payload_rate", forbidden)
    result = read(StreamRows([entry(1000, None)]))
    assert result["total_amount_cents"] is None
    assert result["count"] == 1
    assert result["merchant_ranking"] == []
    assert result["missing_rates"] == (money.ProjectionGap(None, "JPY", date(2026, 9, 7)),)


def test_signed_offset_uses_its_own_date_and_rounds_before_sum(monkeypatch):
    lookups = []

    def rate(*args, **kwargs):
        lookups.append(kwargs["rate_date"])
        return Decimal("20") if kwargs["rate_date"].day == 7 else Decimal("30"), None, None, None

    monkeypatch.setattr(money, "resolve_payload_rate", rate)
    result = read(StreamRows([entry(101, "CNY"), entry(-102, "CNY", day=date(2026, 9, 8), kind="offset", id=2)]))
    assert result["total_amount_cents"] == -11
    assert result["count"] == 2
    assert result["trend"][6]["amount_cents"] == 20
    assert result["trend"][7]["amount_cents"] == -31
    assert lookups == [date(2026, 9, 7), date(2026, 9, 8)]


def test_csv_carries_projection_home_and_gap_without_publishing_unknown_as_zero(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    content = export_reports_overview_csv(StreamRows([entry(2000, "CNY")]),
        month="2026-09", tenant_id="owner", timezone_name="UTC", home_currency_code="JPY")
    rows = list(csv.reader(StringIO(content)))
    assert ["summary", "home_currency_code", "JPY"] in rows
    assert ["summary", "total_amount_cents", ""] in rows
    assert ["missing_rates", "CNY", "JPY", "2026-09-07"] in rows
    assert not any(row[0] == "merchant_ranking" for row in rows if row)


@pytest.mark.parametrize("value", [Decimal("20"), None])
def test_rate_cache_is_per_read_including_missing_rates_and_each_amount_rounds(monkeypatch, value):
    lookups = []

    def rate(*args, **kwargs):
        lookups.append((kwargs["currency_code"], kwargs["home_currency_code"], kwargs["rate_date"]))
        return value, None, None, None

    monkeypatch.setattr(money, "resolve_payload_rate", rate)
    rows = [entry(102, "CNY"), entry(102, "CNY", id=2)]
    first = read(StreamRows(rows))
    assert first["total_amount_cents"] == (40 if value is not None else None)
    assert len(lookups) == 1
    read(StreamRows(rows))
    assert len(lookups) == 2


def test_category_alias_and_merchant_filter_preserve_global_totals(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (Decimal("20"), None, None, None))
    monkeypatch.setattr(_ranking, "enabled_merchant_display_map", lambda *a, **kw: {"alias": "Canonical"})
    result = read(StreamRows([entry(1000, merchant="alias", category="吃饭"),
        entry(2000, "CNY", merchant="Canonical"), entry(5000, category="交通")]), merchant_category="吃饭")
    assert result["total_amount_cents"] == 6400
    assert result["count"] == 3
    assert result["merchant_category"] == "餐饮"
    assert result["merchant_ranking"] == [{"merchant": "Canonical", "amount_cents": 1400, "count": 2}]
    assert next(row for row in result["category_comparison"] if row["category"] == "餐饮")["amount_cents"] == 1400
