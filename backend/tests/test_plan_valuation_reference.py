"""Current estimates may use a dated latest quote; past facts require coverage."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.routes import income_plans
from app.services import exchange_rate_service as rates
from app.services import money_projection_service as money
from app.services import recurring_service
from app.services.income_plan_service._forecast import query_income_forecast
from app.services.reports_service import _history

TODAY = date(2026, 9, 12)
PUBLISHED = date(2026, 9, 11)


@pytest.fixture
def latest_quote(monkeypatch):
    monkeypatch.setattr(rates, "get_exchange_rate", lambda *a, **kw: None)
    monkeypatch.setattr(rates, "get_covered_fx_rate", lambda *a, **kw: None)
    lookups = []

    def latest(*args, **kwargs):
        lookups.append(kwargs["rate_date"])
        return SimpleNamespace(rate_to_home=Decimal(7), source="ecb", rate_date=PUBLISHED)

    monkeypatch.setattr(rates, "get_fx_rate_on_or_before", latest)
    monkeypatch.setattr(recurring_service, "now_utc", lambda: datetime(2026, 9, 12, 4, tzinfo=UTC))
    return lookups


@pytest.mark.parametrize("month", [9, 10])
def test_income_estimate_uses_latest_actual_reference_without_claiming_coverage(latest_quote, monkeypatch, month):
    revision = SimpleNamespace(plan_id=1, revision_number=1, effective_month=date(2026, 8, 1),
        intent_month=date(2026, 8, 1), change_kind="create", amount_cents=1000,
        home_currency_code="USD", frequency="monthly", income_month=None, status="active", pay_day=1)
    db = SimpleNamespace(scalars=lambda *_args: [revision])
    result = query_income_forecast(db, tenant_id="owner", period=date(2026, month, 1), today=TODAY,
        home_currency_code="CNY")
    assert result.expected_amount_cents == 7000
    assert result.scheduled_amount_cents == (7000 if month == 9 else 0)
    assert result.reference_rates == (money.ProjectionReference("USD", "CNY", PUBLISHED),)
    monkeypatch.setattr(income_plans, "list_income_plans", lambda *a, **kw: [])
    monkeypatch.setattr(income_plans, "income_forecast", lambda *a, **kw: result)
    response = income_plans.list_plans(status="active", month=f"2026-{month:02d}",
        auth=SimpleNamespace(tenant_id="owner"), db=db).model_dump(mode="json")
    assert response["reference_rates"] == [{"source_currency_code": "USD", "home_currency_code": "CNY",
        "rate_date": PUBLISHED.isoformat()}]
    assert latest_quote == [TODAY]
    historical = query_income_forecast(db, tenant_id="owner", period=date(2026, 8, 1), today=TODAY,
        home_currency_code="CNY")
    assert historical.expected_amount_cents is None
    assert latest_quote == [TODAY], "Past forecasts must not borrow the current estimate lookup"


@pytest.mark.parametrize("month", ["2026-09", "2026-10"])
def test_current_recurring_reservation_remains_usable_and_explains_quote_date(latest_quote, month):
    items = [SimpleNamespace(home_currency_code="USD", baseline_amount_cents=1000)]
    # Existing actual query must establish a value before the new metadata assertion.
    value = recurring_service.recurring_monthly_total(None, tenant_id="owner", items=items,
        home_currency_code="CNY", month=month)
    assert value == 7000
    references = set()
    assert recurring_service.recurring_monthly_total(None, tenant_id="owner", items=items,
        home_currency_code="CNY", month=month, reference_rates=references) == 7000
    assert references == {money.ProjectionReference("USD", "CNY", PUBLISHED)}
    assert recurring_service.recurring_monthly_total(None, tenant_id="owner", items=items,
        home_currency_code="CNY", month="2026-08") is None
    assert latest_quote == [TODAY, TODAY]


def test_current_budget_history_limit_is_an_estimate_but_recorded_spending_stays_strict(latest_quote, monkeypatch):
    monkeypatch.setattr(_history, "_get_budget", lambda *a, **kw: SimpleNamespace(
        home_currency_code="USD", total_amount_cents=1000, rollover_amount_cents=200))
    result = _history._history_row(None, tenant_id="owner", month="2026-09",
        period=(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
        entries=[], home="CNY", zone=UTC, today=TODAY, rate_cache={})
    assert result["budget_cents"] == 8400
    assert result["reference_rates"] == (money.ProjectionReference("USD", "CNY", PUBLISHED),)
    assert latest_quote == [TODAY]


def test_one_read_cache_cannot_promote_current_estimate_to_historical_fact(latest_quote):
    cache, references = {}, set()
    arguments = {"tenant_id": "owner", "amount_minor": 1000, "source_currency": "USD", "home_currency": "CNY",
        "rate_date": TODAY, "rate_cache": cache, "reference_rates": references}
    assert money.project_valuation_amount(None, **arguments) == 7000
    assert money.project_recorded_amount(None, **arguments) is None
    assert money.project_valuation_amount(None, **arguments) == 7000
    assert references == {money.ProjectionReference("USD", "CNY", PUBLISHED)}
    assert latest_quote == [TODAY]
    missing = set()
    assert money.project_recorded_amount(None, tenant_id="owner", amount_minor=1000, source_currency="USD",
        home_currency="CNY", rate_date=TODAY, missing_rates=missing) is None
    assert missing == {money.ProjectionGap("USD", "CNY", TODAY)}
    assert latest_quote == [TODAY]
