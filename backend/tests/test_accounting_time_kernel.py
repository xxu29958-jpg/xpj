"""Pure accounting-date, precision and DST counterexamples; no database fixture."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from app.errors import AppError
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.accounting_time_service import (
    accounting_time_snapshot,
    apply_accounting_time,
    legacy_accounting_time,
    resolve_accounting_time,
)
from app.services.time_service import resolve_local_datetime


def _instant(**changes):
    return AccountingTimeInput.model_validate({
        "precision": "instant", "calendar_revision": 1,
        "user_local_date": "2026-05-01", "instant_utc": "2026-04-30T16:30:00Z",
        "source_timezone": "Asia/Shanghai", "source_utc_offset_seconds": 28800,
        **changes,
    })


def test_frozen_rule_resolves_day_without_global_settings(monkeypatch):
    monkeypatch.setenv("OCR_DEFAULT_TIMEZONE", "America/Los_Angeles")
    result = resolve_accounting_time(_instant(), ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert result.accounting_date == date(2026, 5, 1)
    assert result.instant_utc == datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    assert result.user_local_date == date(2026, 5, 1)
    assert result.basis == "instant_calendar"
    assert result.model_dump(mode="json")["instant_utc"] == "2026-04-30T16:30:00Z"


def test_explicit_accounting_day_keeps_original_source_evidence():
    result = resolve_accounting_time(_instant(accounting_date="2026-04-30"),
        ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert (result.accounting_date, result.user_local_date, result.basis) == (
        date(2026, 4, 30), date(2026, 5, 1), "user_selected")


@pytest.mark.parametrize("changes", [
    {"user_local_date": "2026-04-30"},
    {"source_utc_offset_seconds": 0},
    {"source_timezone": "Not/A_Zone"},
    {"source_timezone": None, "source_utc_offset_seconds": None},
])
def test_contradictory_or_missing_exact_source_evidence_is_rejected(changes):
    with pytest.raises(AppError):
        resolve_accounting_time(_instant(**changes), ledger_timezone="Asia/Shanghai", calendar_revision=1)


def test_offset_only_source_does_not_invent_an_iana_zone():
    result = resolve_accounting_time(_instant(source_timezone=None),
        ledger_timezone="UTC", calendar_revision=1)
    assert result.source_timezone is None
    assert result.source_utc_offset_seconds == 28800
    assert result.accounting_date == date(2026, 4, 30)


def test_known_source_zone_derives_actual_offset_from_the_saved_instant():
    result = resolve_accounting_time(_instant(source_utc_offset_seconds=None),
        ledger_timezone="UTC", calendar_revision=1)
    assert (result.source_timezone, result.source_utc_offset_seconds) == ("Asia/Shanghai", 28800)
    assert (result.accounting_date, result.user_local_date) == (date(2026, 4, 30), date(2026, 5, 1))


@pytest.mark.parametrize("changes", [
    {"instant_utc": "2026-04-30T16:30:00"},
    {"instant_utc": 1777566600},
    {"calendar_revision": 0},
    {"calendar_revision": True},
    {"source_utc_offset_seconds": 86400},
    {"user_local_date": "2026-05-01T00:00:00Z"},
])
def test_new_wire_rejects_ambiguous_or_coerced_evidence(changes):
    with pytest.raises(ValidationError):
        _instant(**changes)


def test_captured_revision_must_match_the_explicit_resolved_rule():
    with pytest.raises(AppError) as caught:
        resolve_accounting_time(_instant(calendar_revision=2), ledger_timezone="UTC", calendar_revision=1)
    assert caught.value.error == "calendar_revision_conflict"


def test_date_only_never_acquires_instant_or_offset():
    value = AccountingTimeInput(precision="date_only", calendar_revision=1, user_local_date=date(2026, 4, 30))
    result = resolve_accounting_time(value, ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert (result.accounting_date, result.instant_utc, result.source_utc_offset_seconds) == (
        date(2026, 4, 30), None, None)
    assert result.precision == "date_only"
    with pytest.raises(ValidationError):
        AccountingTimeInput(**{**value.model_dump(), "instant_utc": "2026-04-30T00:00:00Z"})
    with pytest.raises(ValidationError):
        AccountingTimeInput(**{**value.model_dump(), "source_utc_offset_seconds": 0})


def test_foreign_date_only_requires_explicit_financial_day():
    value = AccountingTimeInput(precision="date_only", calendar_revision=1,
        user_local_date=date(2026, 4, 30), source_timezone="America/New_York")
    with pytest.raises(AppError) as caught:
        resolve_accounting_time(value, ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert caught.value.error == "accounting_date_required"
    result = resolve_accounting_time(value.model_copy(update={"accounting_date": date(2026, 5, 1)}),
        ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert (result.accounting_date, result.instant_utc, result.basis) == (date(2026, 5, 1), None, "user_selected")


@pytest.mark.parametrize("use_expense_time", [True, False])
def test_legacy_adoption_keeps_unknown_evidence_and_confirmation_distinct(use_expense_time):
    stored = datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    result = legacy_accounting_time(expense_time=stored if use_expense_time else None,
        confirmed_at=stored, ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert result.accounting_date == date(2026, 5, 1)
    assert result.instant_utc == (stored if use_expense_time else None)
    assert (result.precision, result.user_local_date, result.source_timezone,
        result.source_utc_offset_seconds) == ("unknown", None, None, None)
    assert result.basis == ("legacy_expense_time" if use_expense_time else "legacy_confirmed_at")


def test_missing_legacy_evidence_does_not_use_now():
    result = legacy_accounting_time(expense_time=None, ledger_timezone="Asia/Shanghai", calendar_revision=1)
    assert result.accounting_date is None and result.instant_utc is None
    assert result.basis == "legacy_unknown"


def test_apply_date_only_and_read_snapshot_leave_money_and_occ_unchanged():
    expense = SimpleNamespace(expense_time=datetime(2026, 5, 2, tzinfo=UTC), amount_cents=10000, row_version=3)
    value = AccountingTimeInput(precision="date_only", calendar_revision=1, user_local_date=date(2026, 4, 30))
    snapshot = resolve_accounting_time(value, ledger_timezone="UTC", calendar_revision=1)
    apply_accounting_time(expense, snapshot)
    assert expense.expense_time is None
    assert (expense.amount_cents, expense.row_version) == (10000, 3)
    assert accounting_time_snapshot(expense) == snapshot
    assert accounting_time_snapshot(SimpleNamespace(expense_time=datetime(2026, 5, 2, tzinfo=UTC))) is None


def test_optional_wire_value_preserves_old_absence_null_and_unknown_receipts():
    class Receipt(BaseModel):
        accounting_time: AccountingTimeSnapshot | None = None

    assert Receipt.model_validate({}).model_dump(exclude_unset=True) == {}
    assert Receipt.model_validate({"accounting_time": None}).model_dump(exclude_unset=True) == {"accounting_time": None}
    assert AccountingTimeSnapshot.model_validate({}).precision == "unknown"


@pytest.mark.parametrize("offset", [None, -18000, -14400])
def test_spring_gap_is_never_silently_normalized(offset):
    with pytest.raises(AppError) as caught:
        resolve_local_datetime(datetime(2026, 3, 8, 2, 30), "America/New_York", utc_offset_seconds=offset)
    assert caught.value.error == "local_time_nonexistent"


def test_fall_fold_requires_choice_and_preserves_both_actual_instants():
    local = datetime(2026, 11, 1, 1, 30)
    with pytest.raises(AppError) as caught:
        resolve_local_datetime(local, "America/New_York")
    assert caught.value.error == "local_time_ambiguous"
    assert caught.value.details == {"utc_offset_seconds_options": [-14400, -18000]}
    assert resolve_local_datetime(local, "America/New_York", utc_offset_seconds=-14400) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert resolve_local_datetime(local, "America/New_York", utc_offset_seconds=-18000) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_exact_fold_instant_retains_its_offset_and_mismatch_is_rejected():
    known = datetime.fromisoformat("2026-11-01T01:30:00-05:00")
    assert resolve_local_datetime(known, "America/New_York") == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    with pytest.raises(AppError):
        resolve_local_datetime(known, "America/New_York", utc_offset_seconds=-14400)


def test_ordinary_local_time_resolves_and_invalid_rule_never_becomes_utc():
    assert resolve_local_datetime(datetime(2026, 5, 1, 0, 30), "Asia/Shanghai") == datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    with pytest.raises(AppError) as caught:
        resolve_accounting_time(_instant(), ledger_timezone="Not/A_Zone", calendar_revision=1)
    assert caught.value.error == "accounting_timezone_invalid"
