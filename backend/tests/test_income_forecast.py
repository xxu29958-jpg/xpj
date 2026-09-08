"""Pure month semantics used by the real revision query owner."""

from datetime import date
from types import SimpleNamespace

import pytest


def _revision(number, month, amount=100_00, *, status="active", pay_day=1):
    return SimpleNamespace(
        plan_id=1, revision_number=number, effective_month=month,
        intent_month=month, change_kind="create" if number == 1 else "edit",
        amount_cents=amount, home_currency_code="CNY", frequency="monthly", income_month=None,
        status=status, pay_day=pay_day,
    )


def test_income_forecast_selects_the_months_revision() -> None:
    from app.services.income_plan_service._forecast import forecast_from_revisions

    revisions = [
        _revision(1, date(2026, 8, 1)),
        _revision(2, date(2026, 9, 1), 120_00),
        _revision(3, date(2026, 10, 1), 120_00, status="archived"),
        _revision(4, date(2026, 11, 1), 120_00),
    ]
    amounts = [forecast_from_revisions(
        revisions, period=date(2026, month, 1), today=date(2026, 12, 2),
    home_currency_code="CNY").expected_amount_cents for month in range(7, 12)]
    assert amounts == [0, 100_00, 120_00, 0, 120_00]


def test_full_month_forecast_and_scheduled_to_date_are_distinct() -> None:
    from app.services.income_plan_service._forecast import forecast_from_revisions

    revisions = [_revision(1, date(2026, 1, 1), pay_day=31)]
    future = forecast_from_revisions(revisions, period=date(2026, 2, 1), today=date(2026, 1, 2), home_currency_code="CNY")
    assert (future.expected_amount_cents, future.scheduled_amount_cents) == (100_00, 0)
    before = forecast_from_revisions(revisions, period=date(2026, 2, 1), today=date(2026, 2, 27), home_currency_code="CNY")
    last_day = forecast_from_revisions(revisions, period=date(2026, 2, 1), today=date(2026, 2, 28), home_currency_code="CNY")
    assert before.scheduled_amount_cents == 0
    assert last_day.scheduled_amount_cents == 100_00


def test_income_list_preserves_the_legacy_scheduled_total_before_payday(monkeypatch) -> None:
    from app.routes import income_plans
    from app.services.income_plan_service._forecast import forecast_from_revisions

    forecast = forecast_from_revisions(
        [_revision(1, date(2026, 2, 1), pay_day=28)],
        period=date(2026, 2, 1), today=date(2026, 2, 27),
    home_currency_code="CNY")
    monkeypatch.setattr(income_plans, "list_income_plans", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(income_plans, "income_forecast", lambda *_args, **_kwargs: forecast)

    body = income_plans.list_plans(
        status="active", month="2026-02", auth=SimpleNamespace(tenant_id="owner"), db=None,
    ).model_dump()

    # N-1 APKs use this field for "scheduled through today" and ignore additions.
    assert body["total_active_amount_cents"] == 0
    assert body["scheduled_amount_cents"] == 0
    assert body["expected_amount_cents"] == 100_00


def test_undated_baseline_cannot_fabricate_historical_income() -> None:
    from app.errors import AppError
    from app.services.income_plan_service._forecast import forecast_from_revisions

    revisions = [_revision(1, None)]
    with pytest.raises(AppError, match="历史计划"):
        forecast_from_revisions(revisions, period=date(2026, 8, 1), today=date(2026, 9, 2), home_currency_code="CNY")
    current = forecast_from_revisions(revisions, period=date(2026, 9, 1), today=date(2026, 9, 2), home_currency_code="CNY")
    assert current.expected_amount_cents == 100_00


def test_metadata_edits_do_not_turn_an_undated_single_month_estimate_into_known_history() -> None:
    from app.errors import AppError
    from app.services.income_plan_service._forecast import forecast_from_revisions

    baseline = _revision(1, None)
    baseline.change_kind = "baseline"
    renamed = _revision(2, date(2026, 8, 1))
    renamed.intent_month = date(2026, 9, 1)
    reclassified = _revision(3, date(2026, 8, 1))
    reclassified.intent_month = date(2026, 10, 1)
    for row, label, source in (
        (baseline, "旧名称", "salary"), (renamed, "新名称", "salary"), (reclassified, "新名称", "other"),
    ):
        row.frequency, row.income_month = "one_time", "2026-08"
        row.label, row.source_type = label, source

    for revisions in ([baseline, renamed], [baseline, renamed, reclassified]):
        with pytest.raises(AppError, match="历史计划") as error:
            forecast_from_revisions(revisions, period=date(2026, 8, 1), today=date(2026, 11, 2), home_currency_code="CNY")
        assert error.value.status_code == 422
        current = forecast_from_revisions(revisions, period=date(2026, 11, 1), today=date(2026, 11, 2), home_currency_code="CNY")
        assert current.expected_amount_cents == 0


@pytest.mark.parametrize(("field", "value", "target", "expected"), [
    ("amount_cents", 120_00, date(2026, 8, 1), 120_00),
    ("pay_day", 28, date(2026, 8, 1), 100_00),
    ("income_month", "2026-07", date(2026, 7, 1), 100_00),
])
def test_explicit_single_month_financial_correction_survives_a_later_rename(field, value, target, expected) -> None:
    from app.services.income_plan_service._forecast import forecast_from_revisions

    baseline = _revision(1, None)
    baseline.change_kind = "baseline"
    baseline.frequency, baseline.income_month = "one_time", "2026-08"
    corrected = SimpleNamespace(**vars(baseline))
    corrected.revision_number, corrected.change_kind = 2, "edit"
    corrected.effective_month, corrected.intent_month = min(target, date(2026, 8, 1)), date(2026, 9, 1)
    setattr(corrected, field, value)
    renamed = SimpleNamespace(**vars(corrected))
    renamed.revision_number, renamed.intent_month, renamed.label = 3, date(2026, 10, 1), "新名称"

    forecast = forecast_from_revisions(
        [baseline, corrected, renamed], period=target, today=date(2026, 11, 2),
    home_currency_code="CNY")
    assert (forecast.expected_amount_cents, forecast.scheduled_amount_cents) == (expected, expected)
    if field == "income_month":
        original_target = forecast_from_revisions(
            [baseline, corrected, renamed], period=date(2026, 8, 1), today=date(2026, 11, 2),
        home_currency_code="CNY")
        assert original_target.expected_amount_cents == 0


def test_metadata_edit_keeps_the_existing_dated_single_month_projection() -> None:
    from app.services.income_plan_service._forecast import forecast_from_revisions

    created = _revision(1, date(2026, 8, 1))
    created.frequency, created.income_month, created.label = "one_time", "2026-08", "旧名称"
    renamed = SimpleNamespace(**vars(created))
    renamed.revision_number, renamed.change_kind = 2, "edit"
    renamed.intent_month, renamed.label = date(2026, 9, 1), "新名称"

    forecast = forecast_from_revisions(
        [created, renamed], period=date(2026, 8, 1), today=date(2026, 10, 2),
    home_currency_code="CNY")
    assert forecast.expected_amount_cents == 100_00
    assert forecast.entries[0].label == "新名称"


def test_single_month_correction_does_not_erase_unrelated_monthly_history() -> None:
    from app.services.income_plan_service._forecast import forecast_from_revisions

    august = _revision(1, date(2026, 8, 1))
    converted = _revision(2, date(2026, 9, 1), 120_00)
    converted.frequency, converted.income_month = "one_time", "2026-11"
    corrected = _revision(3, date(2026, 6, 1), 130_00)
    corrected.frequency, corrected.income_month = "one_time", "2026-06"
    corrected.intent_month = date(2026, 12, 1)
    totals = [forecast_from_revisions(
        [august, converted, corrected], period=date(2026, month, 1), today=date(2026, 12, 2),
    home_currency_code="CNY").expected_amount_cents for month in (6, 8, 9, 11, 12)]
    assert totals == [130_00, 100_00, 0, 0, 0]
