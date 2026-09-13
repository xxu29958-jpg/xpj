"""Income estimates use a common unit and leave unavailable totals unknown."""

from datetime import date
from types import SimpleNamespace

from app.services.income_plan_service._forecast import forecast_from_revisions


def _revision(plan_id, code, amount, pay_day=1):
    return SimpleNamespace(
        plan_id=plan_id, revision_number=1, effective_month=date(2026, 9, 1),
        intent_month=date(2026, 9, 1), change_kind="create", amount_cents=amount,
        home_currency_code=code, frequency="monthly", income_month=None,
        status="active", pay_day=pay_day,
    )


def test_unconverted_income_does_not_become_a_mislabelled_total():
    rows = [_revision(1, "CNY", 100), _revision(2, "JPY", 1200, pay_day=20)]
    forecast = forecast_from_revisions(rows, period=date(2026, 9, 1), today=date(2026, 9, 9), home_currency_code="CNY")
    assert forecast.home_currency_code == "CNY"
    assert forecast.expected_amount_cents is None
    assert forecast.scheduled_amount_cents == 100
    assert forecast.missing_currency_codes == ("JPY",)
    assert [(row.home_currency_code, row.amount_cents) for row in forecast.entries] == [("CNY", 100), ("JPY", 1200)]


def test_conversion_changes_only_the_projection_and_keeps_original_income_rows():
    rows = [_revision(1, "CNY", 100), _revision(2, "JPY", 1200)]
    forecast = forecast_from_revisions(
        rows, period=date(2026, 9, 1), today=date(2026, 9, 9), home_currency_code="CNY",
        project_amount=lambda amount, code: amount if code == "CNY" else 6000,
    )
    assert forecast.expected_amount_cents == forecast.scheduled_amount_cents == 6100
    assert forecast.missing_currency_codes == ()
    assert rows[1].home_currency_code == "JPY" and rows[1].amount_cents == 1200
