"""Native form time evidence, independent of PostgreSQL and worker clocks."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.routes._web_accounting_time import parse_web_accounting_time, time_form_values


def fields(**changes):
    return {"time_precision": "instant", "calendar_revision": "1",
        "source_timezone": "America/New_York", "source_utc_offset_seconds": "",
        "user_local_date": "2026-11-01", "accounting_date": "", **changes}


def test_date_only_never_manufactures_an_instant():
    value = parse_web_accounting_time("", fields(time_precision="date_only"))
    assert value.instant_utc is None
    assert value.user_local_date.isoformat() == "2026-11-01"
    assert value.source_utc_offset_seconds is None


@pytest.mark.parametrize("wall,error", [
    ("2026-03-08T02:30", "local_time_nonexistent"),
    ("2026-11-01T01:30", "local_time_ambiguous"),
])
def test_wall_time_cannot_silently_pick_gap_or_fold(wall, error):
    with pytest.raises(AppError) as caught:
        parse_web_accounting_time(wall, fields())
    assert caught.value.error == error


def test_later_fold_edit_keeps_exact_instant_and_subsecond_evidence():
    instant = datetime(2026, 11, 1, 6, 30, 15, 123456, tzinfo=UTC)
    expense = SimpleNamespace(expense_time=instant, time_precision="instant",
        source_timezone="America/New_York", source_utc_offset_seconds=-18000,
        calendar_revision=1, user_local_date=instant.date(), accounting_date=instant.date())
    view = time_form_values(expense, SimpleNamespace(timezone_name="Asia/Shanghai", revision=2))
    parsed = parse_web_accounting_time(view["wall_time"], view)
    assert parsed.instant_utc == instant
    assert parsed.calendar_revision == 1
    assert parsed.source_utc_offset_seconds == -18000


def test_old_form_without_time_evidence_remains_absent():
    assert parse_web_accounting_time("2026-11-01T01:30", None) is None


def test_offset_only_evidence_does_not_invent_iana_zone():
    parsed = parse_web_accounting_time("2026-11-01T01:30", fields(
        source_timezone="", source_utc_offset_seconds="-18000"))
    assert parsed.instant_utc == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert parsed.source_timezone is None


def expense_snapshot(**changes):
    return SimpleNamespace(expense_time=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
        source_timezone="America/New_York", source_utc_offset_seconds=-18000,
        calendar_revision=1, user_local_date=datetime(2026, 11, 1).date(),
        accounting_date=datetime(2026, 11, 1).date(), original_currency_code="CNY",
        home_currency_code="CNY", original_amount_minor=100, merchant="商家", category="餐饮",
        note="", tags="", **changes)


def prepare(monkeypatch, expense, raw, time_fields):
    from app.routes import _web_expense_edit_command as command

    monkeypatch.setattr(command, "get_expense", lambda *_: expense)
    monkeypatch.setattr(command, "current_calendar", lambda *_, **__: SimpleNamespace(
        timezone_name="America/New_York", revision=1))
    return command.prepare_web_expense_form(Mock(), expense_id=1, selected_ledger_id="owner",
        expected_row_version="7", idempotency_key="original-key", amount_yuan="1.00",
        original_currency="CNY", merchant="更正商家", category="餐饮", note="", tags="",
        expense_time=raw, time_fields=time_fields)


def test_unchanged_later_fold_edit_omits_time_mutation(monkeypatch):
    expense = expense_snapshot(time_precision="instant")
    view = time_form_values(expense, SimpleNamespace(timezone_name="America/New_York", revision=1))
    # Browsers normalize datetime-local by dropping zero seconds.
    payload, result = prepare(monkeypatch, expense, view.pop("wall_time").removesuffix(":00"), view)
    assert result.error is None
    assert payload.model_fields_set == {"expected_row_version", "merchant"}
    assert result.form_values["source_utc_offset_seconds"] == "-18000"


def test_date_only_edit_uses_value_object_without_legacy_timestamp(monkeypatch):
    payload, result = prepare(monkeypatch, expense_snapshot(time_precision="instant"), "",
        fields(time_precision="date_only", user_local_date="2026-10-31"))
    assert result.error is None
    assert payload.time_input.precision == "date_only"
    assert payload.time_input.instant_utc is None
    assert "expense_time" not in payload.model_fields_set


def test_failed_gap_keeps_original_raw_body_and_key(monkeypatch):
    raw_fields = fields(user_local_date="2026-03-08")
    payload, result = prepare(monkeypatch, expense_snapshot(time_precision="instant"),
        "2026-03-08T02:30", raw_fields)
    assert payload is None
    assert "不存在" in result.field_errors["expense_time"]
    assert result.form_values["expense_time"] == "2026-03-08T02:30"
    assert result.form_values["idempotency_key"] == "original-key"
    assert all(result.form_values[key] == value for key, value in raw_fields.items())


def test_manual_date_only_payload_does_not_add_legacy_alias():
    from app.routes.web_expense_create import _manual_expense_payload

    payload = _manual_expense_payload(amount_major="1.00", currency_code="CNY", merchant="商家",
        category="餐饮", note="", spent_at="", client_ref="a" * 32, home_currency="CNY",
        time_fields=fields(time_precision="date_only"))
    assert payload.time_input.instant_utc is None
    assert "spent_at" not in payload.model_fields_set


def test_correction_old_raw_fingerprint_does_not_gain_time_defaults():
    from app.routes._web_correction_form import CorrectionFormData, web_correction_idempotency_body
    from app.routes._web_expense_return_context import ExpenseReturnContext

    raw = {"reason": "更正", "amount_yuan": "1", "original_currency": "CNY", "merchant": "商家", "category": "餐饮",
        "note": "", "expense_time": None, "expense_time_present": False, "tags": "", "value_score": None,
        "value_score_present": False, "regret_score": None, "regret_score_present": False, "item_public_id": [],
        "item_name": [], "item_kind": [], "item_quantity": [], "item_unit_price_yuan": [], "item_amount_yuan": [],
        "item_category": [], "split_public_id": [], "split_member_id": [], "split_amount_yuan": [], "split_note": []}
    form = CorrectionFormData(**raw, expected_row_version="7", idempotency_key="original",
        return_context=ExpenseReturnContext())
    assert web_correction_idempotency_body(form) == {"web_form": raw}


def test_fold_failure_template_retains_input_and_offers_both_offsets():
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    from app.routes._web_accounting_time import time_form_projection

    env = Environment(autoescape=True, loader=FileSystemLoader(
        Path(__file__).parents[1] / "app/templates/web"))
    html = env.get_template("_accounting_time_fields.html").render(
        time_form=time_form_projection({**fields(), "wall_time": "2026-11-01T01:30"}),
        time_name="expense_time", time_prefix="test", time_disabled=False, field_errors={})
    assert 'value="2026-11-01T01:30"' in html
    assert 'value="-14400"' in html and 'value="-18000"' in html
    assert 'name="calendar_revision" value="1"' in html


def test_only_accounting_day_change_does_not_require_fx_repricing_preview(monkeypatch):
    from decimal import Decimal

    from app.routes import _web_expense_confirm_command as confirm
    from app.schemas import ExpenseUpdateRequest

    expense = expense_snapshot(time_precision="instant", exchange_rate_source="manual",
        exchange_rate_to_cny=Decimal("7"), fx_status="ready")
    monkeypatch.setattr(confirm, "get_expense", lambda *_: expense)
    value = parse_web_accounting_time("2026-11-01T01:30", fields(
        source_utc_offset_seconds="-18000", accounting_date="2026-10-31"))
    assert not confirm._manual_fx_submission_needs_preview(Mock(), expense_id=1,
        selected_ledger_id="owner", update_payload=ExpenseUpdateRequest(expected_row_version=7, time_input=value),
        form_values={})


def test_unchanged_date_only_edit_does_not_clear_the_date(monkeypatch):
    expense = expense_snapshot(time_precision="date_only")
    expense.expense_time = None
    expense.source_utc_offset_seconds = None
    view = time_form_values(expense, SimpleNamespace(timezone_name="America/New_York", revision=1))
    payload, result = prepare(monkeypatch, expense, view.pop("wall_time"), view)
    assert result.error is None
    assert "expense_time" not in payload.model_fields_set and "time_input" not in payload.model_fields_set


def test_blank_instant_pending_edit_keeps_legacy_no_change(monkeypatch):
    payload, result = prepare(monkeypatch, expense_snapshot(time_precision="instant"), "", fields())
    assert result.error is None
    assert "expense_time" not in payload.model_fields_set and "time_input" not in payload.model_fields_set
