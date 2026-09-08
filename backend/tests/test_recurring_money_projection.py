"""Recurring reads compare money only after projecting its captured currency."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.routes._web_recurring_presenter import apply_form_draft, item_view
from app.services import insights_service, recurring_service


def test_candidate_groups_projected_money_instead_of_equal_unlabelled_integers(monkeypatch):
    times = [datetime(2026, month, 1, tzinfo=UTC) for month in (7, 8)]
    expenses = [SimpleNamespace(merchant="Subscription", expense_time=when, confirmed_at=when,
        amount_cents=amount, home_currency_code=code) for when, amount, code in zip(times, (10000, 2000), ("CNY", "JPY"), strict=True)]
    monkeypatch.setattr(insights_service, "_confirmed_expenses_for_recurring", lambda *args, **kwargs: expenses)
    db = SimpleNamespace(scalars=lambda *args: SimpleNamespace(all=lambda: []))
    # Existing FX owner is the boundary: the CNY observation projects to 2000 JPY.
    monkeypatch.setattr("app.services.money_projection_service.resolve_payload_rate", lambda *args, **kwargs: (20, None, None, None))
    candidates = insights_service.recurring_candidates(db, tenant_id="owner", home_currency_code="JPY")
    assert len(candidates) == 1
    assert candidates[0]["home_currency_code"] == "JPY"
    assert candidates[0]["amount_cents"] == 2000


def test_candidate_missing_currency_cannot_be_reported_as_no_candidates(monkeypatch):
    when = datetime(2026, 8, 1, tzinfo=UTC)
    expense = SimpleNamespace(merchant="Subscription", expense_time=when, confirmed_at=when,
        amount_cents=100, home_currency_code=None)
    monkeypatch.setattr(insights_service, "_confirmed_expenses_for_recurring", lambda *args, **kwargs: [expense])
    db = SimpleNamespace(scalars=lambda *args: SimpleNamespace(all=lambda: []))
    with pytest.raises(AppError) as rejected:
        insights_service.recurring_candidates(db, tenant_id="owner", home_currency_code="JPY")
    assert rejected.value.error == "recurring_projection_unavailable"


def test_item_card_and_editor_use_recorded_currency():
    item = SimpleNamespace(public_id="item", merchant_name="Subscription", home_currency_code="JPY",
        baseline_amount_cents=1200, last_amount_cents=1300, occurrence_count=2,
        last_seen_at=None, next_expected_date=None, status="active", source="candidate", row_version=4)
    view = item_view(item, recurring_service.RecurringAmountAnomaly(), due_date=None)
    assert view["baseline_amount_yuan"] == "1200"
    assert view["home_currency_code"] == "JPY"
    assert view["edit_form"]["home_currency_code"] == "JPY"


def test_review_cannot_rebase_raw_draft_onto_another_currency():
    current_form = {"home_currency_code": "JPY", "baseline_amount_yuan": "1200"}
    item = {"public_id": "item", "status": "active", "row_version": 4,
        "home_currency_code": "JPY", "edit_form": current_form}
    ctx = {"items": [item], "suggested_next_date": "2026-10-01", "home_currency_code": "JPY"}
    draft = {"public_id": "item", "home_currency_code": "CNY", "baseline_amount_yuan": "1200.50",
        "idempotency_key": "original", "expected_row_version": "3", "review_required": True}
    apply_form_draft(ctx, draft, prepare_review=True)
    assert item["edit_form"]["home_currency_code"] == "CNY"
    assert item["edit_form"]["baseline_amount_yuan"] == "1200.50"
    assert item["edit_form"]["idempotency_key"] == "original"
    assert item["edit_form"]["review_required"]
    assert item["current_edit_form"] == current_form


@pytest.mark.parametrize("source, expected", [("CNY", 4000), (None, None)])
def test_recurring_total_projects_each_record_and_never_publishes_partial_sum(monkeypatch, source, expected):
    items = [SimpleNamespace(home_currency_code=source, baseline_amount_cents=10000),
        SimpleNamespace(home_currency_code="JPY", baseline_amount_cents=2000)]
    monkeypatch.setattr("app.services.money_projection_service.resolve_payload_rate", lambda *args, **kwargs: (20, None, None, None))
    total = recurring_service.recurring_monthly_total(None, tenant_id="owner", items=items,
        home_currency_code="JPY", month="2026-08")
    assert total == expected


@pytest.mark.parametrize("source, expected_status", [("CNY", "higher_than_average"), (None, "unavailable")])
def test_anomaly_compares_observations_in_the_plan_currency(monkeypatch, source, expected_status):
    item = SimpleNamespace(public_id="item", merchant_key="subscription", merchant_name="Subscription",
        home_currency_code="JPY", status="active", baseline_amount_cents=1500, last_amount_cents=1500)
    times = [datetime(2026, month, 1, tzinfo=UTC) for month in (8, 9)]
    expenses = [SimpleNamespace(merchant="Subscription", expense_time=when, confirmed_at=when,
        amount_cents=amount, home_currency_code=source) for when, amount in zip(times, (7500, 10000), strict=True)]
    db = SimpleNamespace(scalars=lambda *args: expenses)
    monkeypatch.setattr("app.services.money_projection_service.resolve_payload_rate", lambda *args, **kwargs: (20, None, None, None))
    anomalies = recurring_service.recurring_amount_anomalies(db, tenant_id="owner", items=[item], month="2026-09")
    assert anomalies["item"].anomaly_status == expected_status
    if source:
        assert anomalies["item"].current_month_amount_cents == 2000
        assert anomalies["item"].historical_average_amount_cents == 1500
        assert anomalies["item"].amount_delta_percent == 33
    else:
        assert anomalies["item"].current_month_amount_cents is None
