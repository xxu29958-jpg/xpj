"""History charts and largest-expense links compare projected, recorded money."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from test_period_report_projection import StreamRows, entry

from app.services import money_projection_service as money
from app.services.reports_service import _history


def test_budget_line_uses_its_recorded_currency_and_target_month_date(monkeypatch):
    lookups = []

    def rate(*args, **kwargs):
        lookups.append((kwargs["currency_code"], kwargs["rate_date"]))
        return Decimal("20"), None, None, None

    monkeypatch.setattr(money, "resolve_payload_rate", rate)
    monkeypatch.setattr(_history, "now_utc", lambda: datetime(2026, 9, 9, tzinfo=UTC))
    monkeypatch.setattr(_history, "_get_budget", lambda *a, **kw: SimpleNamespace(
        home_currency_code="CNY", total_amount_cents=10000, rollover_amount_cents=2000) if kw["month"] == "2026-08" else None)
    rows = _history.six_month_summary(StreamRows([entry(300, day=date(2026, 8, 7))]),
        anchor_month="2026-09", tenant_id="owner", currency_code="JPY", timezone_name="UTC")
    august = next(row for row in rows if row["month"] == "2026-08")
    assert august["home_currency_code"] == "JPY"
    assert (august["amount_cents"], august["budget_cents"], august["budget_major_text"]) == (300, 2400, "2400")
    assert august["missing_rates"] == ()
    assert lookups == [("CNY", date(2026, 8, 31))]


def test_unknown_budget_line_does_not_become_zero_or_erase_known_spending(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    monkeypatch.setattr(money, "resolve_valuation_rate", lambda *a, **kw: (None, None, None, None))
    monkeypatch.setattr(_history, "now_utc", lambda: datetime(2026, 9, 9, tzinfo=UTC))
    monkeypatch.setattr(_history, "_get_budget", lambda *a, **kw: SimpleNamespace(
        home_currency_code="CNY", total_amount_cents=10000, rollover_amount_cents=0))
    rows = _history.six_month_summary(StreamRows([entry(300)]), anchor_month="2026-09", tenant_id="owner",
        currency_code="JPY", timezone_name="UTC")
    assert rows[-1]["amount_cents"] == 300
    assert rows[-1]["budget_cents"] is None
    assert rows[-1]["budget_yuan"] is None
    assert rows[-1]["missing_rates"] == (money.ProjectionGap("CNY", "JPY", date(2026, 9, 9)),)


def test_largest_expense_compares_target_currency_and_retains_fact_link(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (Decimal("20"), None, None, None))
    db = StreamRows([entry(1000, id=1), entry(2000, "CNY", id=2)])
    records = [SimpleNamespace(id=2, public_id="cny-fact"), SimpleNamespace(id=1, public_id="jpy-fact")]
    db.scalars = lambda statement: records
    result = _history.top_expenses_for_month(db, tenant_id="owner", month="2026-09", home_currency_code="JPY", timezone_name="UTC")
    assert result.home_currency_code == "JPY"
    assert [(item.expense.public_id, item.amount_cents) for item in result.items] == [("jpy-fact", 1000), ("cny-fact", 400)]
    assert result.missing_rates == ()


def test_largest_expense_missing_rate_prevents_false_top_five(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (None, None, None, None))
    result = _history.top_expenses_for_month(StreamRows([entry(1000), entry(2000, "CNY", id=2)]),
        tenant_id="owner", month="2026-09", home_currency_code="JPY", timezone_name="UTC", limit=1)
    assert result.items == ()
    assert result.missing_rates == (money.ProjectionGap("CNY", "JPY", date(2026, 9, 7)),)


def test_budget_line_reads_only_recorded_limit_not_unrelated_spending_calculations(monkeypatch):
    def unrelated(*args, **kwargs):
        raise AssertionError("The full budget view requires unrelated spending and recurring inputs")

    monkeypatch.setattr(_history, "get_monthly_budget", unrelated, raising=False)
    monkeypatch.setattr(_history, "_get_budget", lambda *a, **kw: SimpleNamespace(
        home_currency_code="JPY", total_amount_cents=1000, rollover_amount_cents=200), raising=False)
    rows = _history.six_month_summary(StreamRows([]), anchor_month="2026-09", tenant_id="owner",
        currency_code="JPY", timezone_name="UTC")
    assert all((row["budget_cents"], row["amount_cents"]) == (1200, 0) for row in rows)
