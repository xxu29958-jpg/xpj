"""Real read owners preserve captured currency and unavailable historical values."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import money_projection_service as money
from app.services.budget_baseline_service import compute_monthly_discretionary
from app.services.learning_service import _budget_quantile as quantiles
from app.services.monthly_report_service import compose_budget_explanation, compose_monthly_report


class Rows:
    def __init__(self, *batches):
        self.batches = iter(batches)

    def execute(self, statement):
        return iter(next(self.batches))


def spending(amount, currency="CNY", day=date(2026, 8, 12), category="餐饮"):
    return SimpleNamespace(amount_cents=amount, home_currency_code=currency, stream_date=day, category=category)


def rate(monkeypatch, value):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *args, **kwargs: (value, None, None, None))


def test_report_projects_each_offset_at_its_own_currency_and_date(monkeypatch):
    requested = []

    def resolve(*args, **kwargs):
        requested.append((kwargs["currency_code"], kwargs["rate_date"]))
        return Decimal("20"), None, None, None

    monkeypatch.setattr(money, "resolve_payload_rate", resolve)
    report = compose_monthly_report(
        Rows([spending(10_000), spending(-500, "JPY", date(2026, 8, 20))], []),
        tenant_id="owner", year_month="2026-08", home_currency_code="JPY",
    )
    assert (report.total_cents, report.expense_count) == (1500, 2)
    assert report.top_categories[0].amount_cents == 1500
    assert report.home_currency_code == "JPY"
    assert requested == [("CNY", date(2026, 8, 12))]
    assert report.missing_rates == ()


def test_unknown_previous_month_prevents_comparison_not_current_total(monkeypatch):
    rate(monkeypatch, None)
    report = compose_monthly_report(
        Rows([spending(300, "JPY")], [spending(10_000, day=date(2026, 7, 10))]),
        tenant_id="owner", year_month="2026-08", home_currency_code="JPY",
    )
    assert report.total_cents == 300
    assert report.delta_vs_previous_cents is None
    assert report.delta_pct is None
    assert report.missing_rates == (money.ProjectionGap("CNY", "JPY", date(2026, 7, 10)),)


def test_unknown_current_category_keeps_count_and_marks_total_unknown(monkeypatch):
    rate(monkeypatch, None)
    report = compose_monthly_report(
        Rows([spending(300, "JPY"), spending(1000)], []),
        tenant_id="owner", year_month="2026-08", home_currency_code="JPY",
    )
    assert report.total_cents is None
    assert report.top_categories[0].amount_cents is None
    assert report.top_categories[0].count == report.expense_count == 2


def test_historical_fx_gap_is_not_insufficient_history(monkeypatch):
    rate(monkeypatch, None)
    row = (date(2026, 7, 10), 10_000, "CNY")
    suggestion = quantiles.compute_budget_quantile_suggestion(
        Rows([row]), tenant_id="owner", category="餐饮", home_currency_code="JPY",
        now=datetime(2026, 8, 1, tzinfo=UTC), timezone_name="UTC",
    )
    assert suggestion is not None
    assert suggestion.p50_cents is suggestion.p75_cents is None
    assert suggestion.missing_rates == (money.ProjectionGap("CNY", "JPY", date(2026, 7, 10)),)
    explanation = compose_budget_explanation(
        Rows([spending(300, "JPY")], [row]), tenant_id="owner", category="餐饮",
        year_month="2026-08", home_currency_code="JPY", timezone_name="UTC",
    )
    assert explanation.verdict == "projection_unavailable"
    assert explanation.actual_cents == 300
    assert explanation.delta_vs_p75_cents is None
    assert explanation.missing_rates == suggestion.missing_rates


@pytest.mark.parametrize("field", ["monthly_income_cents", "fixed_expenses_cents", "spent_amount_cents"])
def test_discretionary_preserves_unknown_component(field):
    values = {"monthly_income_cents": 10_000, "fixed_expenses_cents": 1000, "spent_amount_cents": 2000}
    values[field] = None
    result = compute_monthly_discretionary(**values)
    assert getattr(result, field) is None
    assert result.discretionary_cents is None


def test_gap_retains_unknown_source_and_date_without_inventing_fx_pair():
    missing = set()
    assert money.project_recorded_amount(
        object(), tenant_id="owner", amount_minor=100, source_currency=None,
        home_currency="JPY", rate_date=None, missing_rates=missing,
    ) is None
    assert missing == {money.ProjectionGap(None, "JPY", None)}


def test_month_only_report_does_not_read_unused_comparison(monkeypatch):
    rate(monkeypatch, Decimal("20"))
    report = compose_monthly_report(Rows([spending(10_000), spending(-500, "JPY")]),
        tenant_id="owner", year_month="2026-08", home_currency_code="JPY", compare_previous=False)
    assert report.total_cents == 1500
    assert report.missing_rates == ()
    assert report.delta_vs_previous_cents is report.delta_pct is None


def test_income_query_reuses_effective_date_and_captured_currency(monkeypatch):
    from app.services.income_plan_service._forecast import query_income_forecast

    rate(monkeypatch, None)
    rows = [SimpleNamespace(plan_id=1, revision_number=1, effective_month=date(2026, 7, 1),
        intent_month=date(2026, 7, 1), change_kind="create", amount_cents=100,
        home_currency_code="CNY", frequency="monthly", income_month=None, status="active", pay_day=1)]
    gaps = set()
    forecast = query_income_forecast(SimpleNamespace(scalars=lambda query: rows), tenant_id="owner",
        period=date(2026, 8, 1), today=date(2026, 9, 9), home_currency_code="JPY", missing_rates=gaps)
    assert forecast.home_currency_code == "JPY"
    assert forecast.expected_amount_cents is None
    assert gaps == {money.ProjectionGap("CNY", "JPY", date(2026, 8, 31))}
    assert rows[0].home_currency_code == "CNY" and rows[0].amount_cents == 100


def test_recurring_query_preserves_paid_filter_and_unknown_reservation(monkeypatch):
    from app.services import recurring_occurrence_query as recurring

    rate(monkeypatch, None)
    items = [SimpleNamespace(id=1, home_currency_code="CNY", baseline_amount_cents=1000),
        SimpleNamespace(id=2, home_currency_code="JPY", baseline_amount_cents=500)]
    monkeypatch.setattr(recurring, "fulfilled_periods", lambda *args, **kwargs: {1: {date(2026, 8, 1)}})
    gaps = set()
    db = SimpleNamespace(scalars=lambda query: items)
    assert recurring.total_outstanding_recurring_cents(db, tenant_id="owner", month="2026-08",
        home_currency_code="JPY", missing_rates=gaps) == 500
    assert gaps == set()  # A paid series adds no fixed reservation and needs no reservation FX.
    monkeypatch.setattr(recurring, "fulfilled_periods", lambda *args, **kwargs: {})
    assert recurring.total_outstanding_recurring_cents(db, tenant_id="owner", month="2026-08",
        home_currency_code="JPY", missing_rates=gaps) is None
    assert gaps == {money.ProjectionGap("CNY", "JPY", date(2026, 8, 31))}


def test_explanation_aggregates_the_full_anonymous_category_group(monkeypatch):
    rate(monkeypatch, None)
    explanation = compose_budget_explanation(Rows([
        spending(200, "JPY", category="legacy-a"), spending(300, "JPY", category="legacy-b"),
        spending(999, "JPY", category="餐饮"),
    ], [(date(2026, 7, 10), 10_000, "CNY")]), tenant_id="owner", category="其他",
        categories={"legacy-a", "legacy-b"}, year_month="2026-08", timezone_name="UTC", home_currency_code="JPY")
    assert explanation.actual_cents == 500
    assert explanation.verdict == "projection_unavailable"
    assert explanation.missing_rates == (money.ProjectionGap("CNY", "JPY", date(2026, 7, 10)),)
