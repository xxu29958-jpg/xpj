"""Small command-boundary probes; PostgreSQL qualification remains separate."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import (
    Account,
    BillSplitInvitation,
    CsvImportBatch,
    CsvImportRow,
    Expense,
    ExpenseOffsetFact,
    LedgerCalendarRevision,
)
from app.schemas import (
    ConfirmedExpenseStreamItem,
    ExpenseFactBundleResponse,
    ExpenseOffsetCorrectionRequest,
    ExpenseOffsetCreateRequest,
    ExpenseResponse,
)
from app.schemas._accounting_time import AccountingTimeSnapshot
from app.schemas._bill_split import BillSplitSentResponse
from app.schemas._expense_offset import ExpenseOffsetResponse
from app.services import expense_offset_lifecycle_service as offset_lifecycle
from app.services import expense_offset_service, import_service, stats_service
from app.services.bill_split_service import _create as split_create
from app.services.bill_split_service import _transitions as split_transitions
from app.services.csv_import_batch_service import _apply as csv_apply
from app.services.csv_import_batch_service._csv_io import _error_csv_values, _row_from_parsed
from app.services.csv_import_batch_service._events import _matches_fact, _same_source_row, freeze_csv_expense_time
from app.services.expense_service import _ocr_facts
from app.services.expense_service._query import _offset_stream_projection
from app.services.ocr_service import OcrResult, apply_ocr_result


def _rule(revision=3, zone="Asia/Shanghai"):
    return LedgerCalendarRevision(ledger_id="target", revision=revision, timezone_name=zone)


def _parsed(raw, zone="Asia/Shanghai"):
    return import_service.parse_csv_row(["amount_cents", "expense_time"], ["100", raw],
        line_number=2, home_currency="CNY", timezone_name=zone, calendar_revision=3)


def test_ordinary_csv_date_only_and_raw_cell_survive_staging():
    parsed = _parsed("2026-04-30")
    assert parsed.is_valid and parsed.expense_time is None
    assert parsed.time_input["precision"] == "date_only"
    row = _row_from_parsed(CsvImportBatch(id=1, tenant_id="target", calendar_revision=3), parsed)
    assert row.time_input["user_local_date"] == "2026-04-30"
    assert _error_csv_values(row)["expense_time"] == "2026-04-30"


@pytest.mark.parametrize("raw", ["2026-03-08 02:30:00", "2026-11-01 01:30:00"])
def test_csv_dst_gap_and_repeat_remain_repairable_error_rows(raw):
    parsed = _parsed(raw, "America/New_York")
    assert not parsed.is_valid and parsed.expense_time is None and parsed.time_input is None
    row = _row_from_parsed(CsvImportBatch(id=1, tenant_id="target"), parsed)
    assert row.status == "error" and _error_csv_values(row)["expense_time"] == raw


def test_csv_naive_input_captures_rule_but_aware_input_keeps_original_offset():
    naive = _parsed("2026-05-01 00:30:00")
    assert naive.time_input["source_timezone"] == "Asia/Shanghai"
    assert naive.expense_time == datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    aware = _parsed("2026-04-30T16:30:00+00:00")
    assert aware.time_input["source_timezone"] is None
    assert aware.time_input["source_utc_offset_seconds"] == 0
    assert aware.time_input["user_local_date"] == "2026-04-30"
    assert aware.exchange_rate_date == date(2026, 4, 30)


def test_csv_apply_freezes_time_before_fx_and_uses_staged_revision(monkeypatch):
    db = Mock(spec=Session)
    db.get.return_value = _rule()
    batch = CsvImportBatch(id=1, tenant_id="target", public_id="batch", calendar_revision=3)
    row = _row_from_parsed(batch, _parsed("2026-04-30"))
    row.id = 2
    monkeypatch.setattr(csv_apply, "_refresh_claimed_csv_import_row", lambda *_a, **_k: True)
    monkeypatch.setattr(csv_apply, "_existing_csv_import_expense_id", lambda *_a, **_k: None)
    observed = []
    monkeypatch.setattr(csv_apply, "apply_currency_payload", lambda *_a, **kw: observed.append(
        (kw["expense"].expense_time, kw["expense"].accounting_date)))
    expense = csv_apply._process_csv_import_apply_row(db, row=row, batch=batch, tenant_id="target",
        apply_token="claim", now=datetime.now(UTC))
    assert observed == [(None, date(2026, 4, 30))]
    assert expense.calendar_revision == 3
    assert db.get.call_args.args[1] == ("target", 3)


def _native_row(snapshot=None):
    return CsvImportRow(tenant_id="target", entry_kind="expense", accounting_date=date(2026, 5, 1),
        expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC), merchant="Train", category="其他",
        home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=100,
        amount_cents=100, exchange_rate_to_cny=Decimal("1"), exchange_rate_date=date(2026, 4, 30),
        event_input={"accounting_time": json.dumps(snapshot)} if snapshot else {})


def test_legacy_native_csv_preserves_day_without_promoting_old_display_fallback():
    db = Mock(spec=Session)
    db.get.return_value = _rule()
    row = _native_row()
    expense = Expense(tenant_id="target", expense_time=row.expense_time)
    freeze_csv_expense_time(db, row=row, batch=CsvImportBatch(calendar_revision=3), expense=expense)
    assert expense.expense_time is None and expense.user_local_date is None
    assert expense.time_precision == "unknown" and expense.accounting_date == date(2026, 5, 1)
    assert expense.accounting_date_basis == "recorded_date"
    for name in ("amount_cents", "home_currency_code", "original_currency_code", "original_amount_minor",
                 "exchange_rate_to_cny", "exchange_rate_date", "merchant", "category"):
        setattr(expense, name, getattr(row, name))
    expense.status = "pending"
    assert _matches_fact(row, expense)
    changed = _native_row()
    changed.accounting_date = date(2026, 4, 30)
    assert not _same_source_row(row, changed)


def test_native_snapshot_keeps_original_precision_and_rebinds_only_target_rule():
    db = Mock(spec=Session)
    db.get.return_value = _rule()
    source = AccountingTimeSnapshot(precision="instant", instant_utc=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
        user_local_date=date(2026, 4, 30), source_timezone="UTC", source_utc_offset_seconds=0,
        accounting_date=date(2026, 5, 1), calendar_revision=99, basis="user_selected")
    row = _native_row(source.model_dump(mode="json"))
    expense = Expense(tenant_id="target")
    freeze_csv_expense_time(db, row=row, batch=CsvImportBatch(calendar_revision=3), expense=expense)
    assert expense.calendar_revision == 3 and expense.accounting_date_basis == "recorded_date"
    assert expense.expense_time == source.instant_utc and expense.user_local_date == source.user_local_date
    assert json.loads(row.event_input["accounting_time"])["calendar_revision"] == 99


def test_split_snapshot_keeps_date_after_source_changes_and_target_uses_own_rule(monkeypatch):
    source = Expense(tenant_id="sender", id=1, amount_cents=100, home_currency_code="CNY",
        original_currency_code="CNY", original_amount_minor=100, time_precision="date_only",
        user_local_date=date(2026, 4, 30), accounting_date=date(2026, 5, 1), calendar_revision=99, accounting_date_basis="user_selected")
    inv = split_create._build_invitation(sender_account_id=1, sender_ledger_id="sender", sender_member_id=1,
        expense=source, sender=Account(display_name="A"), receiver=Account(display_name="B"),
        receiver_account_id=2, amount_cents=50)
    source.accounting_date = date(2026, 6, 1)
    received = split_transitions._build_received_expense(inv, target_ledger_id="target", accepted_at=datetime.now(UTC))
    monkeypatch.setattr(split_transitions, "current_calendar", lambda *_a, **_k: _rule())
    split_transitions._freeze_received_time(Mock(), inv, received)
    assert received.expense_time is None and received.accounting_date == date(2026, 5, 1)
    assert received.user_local_date == date(2026, 4, 30) and received.exchange_rate_date == date(2026, 4, 30)
    assert received.calendar_revision == 3 and inv.accounting_time_snapshot["calendar_revision"] == 99


def test_legacy_split_uses_only_original_invitation_evidence(monkeypatch):
    inv = BillSplitInvitation(amount_cents=50, home_currency_code="CNY", expense_time_snapshot=None)
    accepted = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    received = split_transitions._build_received_expense(inv, target_ledger_id="target", accepted_at=accepted)
    monkeypatch.setattr(split_transitions, "calendar_revision", lambda *_a, **_k: _rule(1))
    split_transitions._freeze_received_time(Mock(), inv, received)
    assert received.expense_time is None and received.user_local_date is None
    assert received.accounting_date_basis == "legacy_confirmed_at"
    assert inv.accounting_time_snapshot is None


def test_offset_date_only_and_accepted_replay_do_not_reinterpret_current_calendar(monkeypatch):
    monkeypatch.setattr(expense_offset_service, "current_calendar", lambda *_a, **_k: _rule())
    values = expense_offset_service.offset_accounting_values(Mock(), tenant_id="target", accounting_date=date(2026, 4, 30))
    assert values["time_precision"] == "date_only" and values["user_local_date"] == date(2026, 4, 30)
    receipt = ExpenseFactBundleResponse.model_construct()
    monkeypatch.setattr(expense_offset_service, "_claim_offset_command", lambda *_a, **_k: receipt)
    monkeypatch.setattr(expense_offset_service, "offset_accounting_values", lambda *_a, **_k: pytest.fail("reinterpreted replay"))
    assert expense_offset_service.create_expense_offset(Mock(), tenant_id="target", expense_id=1,
        payload=ExpenseOffsetCreateRequest(kind="refund", original_amount_minor=1, accounting_date=date(2026, 4, 30),
            reason="refund", expected_row_version=1), effective_expected_row_version=1,
        actor_account_id=1, actor_device_public_id=None, actor_device_name=None, idempotency_key="original") is receipt


def test_ocr_cannot_replace_user_date_only_even_when_old_draft_marker_exists():
    expense = Expense(status="pending", amount_cents=100, home_currency_code="CNY", original_currency_code="CNY",
        time_precision="date_only", user_local_date=date(2026, 4, 30), accounting_date=date(2026, 5, 1),
        calendar_revision=3, ocr_draft_fields='["expense_time"]')
    apply_ocr_result(expense, OcrResult(raw_text="", confidence=0.9, expense_time=datetime(2026, 6, 1, tzinfo=UTC)))
    assert expense.expense_time is None and expense.user_local_date == date(2026, 4, 30)
    assert expense.exchange_rate_date == date(2026, 4, 30)


def test_persistent_ocr_refreshes_legacy_day_before_fx_and_fact(monkeypatch):
    db = Mock(spec=Session)
    db.get.return_value = _rule(1)
    expense = Expense(tenant_id="target", status="pending", amount_cents=100,
        home_currency_code="CNY", original_currency_code="CNY")
    monkeypatch.setattr("app.services.expense_split_service.current_expense_split_total_amount", lambda *_a, **_k: 0)
    observed = []
    monkeypatch.setattr(_ocr_facts, "append_ocr_fact", lambda *_a, **_k: observed.append(
        (expense.accounting_date, expense.exchange_rate_date)))
    _ocr_facts.apply_ocr_result_and_append_fact(db, expense=expense,
        result=OcrResult(raw_text="", confidence=0.9, expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC)), provider_name="mock")
    assert observed == [(date(2026, 5, 1), date(2026, 5, 1))]


@pytest.mark.parametrize("kind", ["expense", "offset"])
def test_real_stream_dto_export_import_preserves_complete_source_time(monkeypatch, kind):
    source = AccountingTimeSnapshot(precision="date_only", user_local_date=date(2026, 4, 30),
        accounting_date=date(2026, 5, 1), calendar_revision=99, basis="user_selected")
    root = ExpenseResponse.model_construct(id=1, public_id="11d98b2e-1c28-4e4c-8243-e81c07d6c6b4", amount_cents=100,
        home_currency="CNY", original_currency_code="CNY", original_amount_minor=100,
        exchange_rate_to_cny=Decimal("1"), exchange_rate_date=date(2026, 4, 30), exchange_rate_source="base",
        category="其他", merchant=None, note=None, source="manual", tags=None, value_score=None,
        regret_score=None, expense_time=None, confirmed_at=None, accounting_time=source)
    offset = ExpenseOffsetFact(public_id="3930a010-e387-43e5-9e65-772d9b09c699", kind="refund",
        amount_cents=30, original_amount_minor=30, original_currency_code="CNY", home_currency_code="CNY",
        category="其他", exchange_rate_to_cny=Decimal("1"), exchange_rate_date=date(2026, 4, 30),
        exchange_rate_source="base", time_precision="date_only", user_local_date=source.user_local_date,
        accounting_date=source.accounting_date, calendar_revision=99, accounting_date_basis="user_selected")
    entry = ConfirmedExpenseStreamItem(root=root, entry_kind=kind, stream_date=date(2026, 5, 1),
        stream_sort_time=datetime(2026, 5, 1, tzinfo=UTC), stream_sort_id=1,
        offset=_offset_stream_projection(offset) if kind == "offset" else None,
        stream_amount_cents=-30 if kind == "offset" else 100,
        lineage_status="partially_refunded" if kind == "offset" else "confirmed", lineage_home_net_cents=70)
    monkeypatch.setattr(stats_service, "filtered_confirmed_stream", lambda *_a, **_k: [entry])
    csv = stats_service.export_confirmed_csv(Mock(), tenant_id="target")
    parsed = import_service.parse_csv_preview(csv, home_currency="CNY").rows[0]
    assert parsed.is_valid, parsed.error
    assert parsed.expense_time is None
    assert json.loads(parsed.event_input["accounting_time"]) == source.model_dump(mode="json")


def test_imported_offset_uses_frozen_batch_rule_and_preserves_original_date(monkeypatch):
    source = AccountingTimeSnapshot(precision="date_only", user_local_date=date(2026, 4, 30),
        accounting_date=date(2026, 5, 1), calendar_revision=99, basis="user_selected")
    imported = expense_offset_service.ReviewedOffsetImport(money=Mock(), category="其他",
        calendar_revision=3, accounting_time=source)
    db = Mock(spec=Session)
    db.get.return_value = _rule()
    monkeypatch.setattr(expense_offset_service, "current_calendar", lambda *_a, **_k: pytest.fail("read current rule"))
    values = expense_offset_service.offset_accounting_values(db, tenant_id="target",
        accounting_date=date(2026, 5, 1), imported=imported)
    assert values["calendar_revision"] == 3 and values["user_local_date"] == date(2026, 4, 30)
    assert values["accounting_date_basis"] == "recorded_date" and source.calendar_revision == 99
    assert db.get.call_args.args[1] == ("target", 3)


@pytest.mark.parametrize("changed", [False, True])
def test_offset_correction_freezes_changed_date_before_money_but_preserves_unchanged_evidence(monkeypatch, changed):
    old_day, new_day = date(2026, 4, 30), date(2026, 5, 1)
    offset = ExpenseOffsetFact(row_version=7, accounting_date=old_day)
    payload = ExpenseOffsetCorrectionRequest(original_amount_minor=30,
        accounting_date=new_day if changed else old_day, category="其他", offset_reason="refund",
        correction_reason="correct date", expected_row_version=7)
    monkeypatch.setattr(offset_lifecycle, "_claim_correction", lambda *_a, **_k: Mock())
    monkeypatch.setattr(offset_lifecycle, "authorize_currency_metadata_write", lambda *_a: None)
    monkeypatch.setattr(offset_lifecycle, "_locked_lifecycle_rows", lambda *_a, **_k: (Mock(), offset, [offset]))
    seen = []
    def freeze(*_a, **_k):
        seen.append("date")
        return {"calendar_revision": 3, "time_precision": "date_only", "user_local_date": new_day}
    monkeypatch.setattr(offset_lifecycle, "offset_accounting_values", freeze)
    def money(*_a, **_k):
        assert seen == (["date"] if changed else [])
        return SimpleNamespace(original_amount_minor=30, amount_cents=30, exchange_rate_to_cny=Decimal("1"),
            exchange_rate_date=payload.accounting_date, exchange_rate_source="base")
    monkeypatch.setattr(offset_lifecycle, "resolve_corrected_offset_money", money)
    monkeypatch.setattr(offset_lifecycle, "_offset_snapshot", lambda _o: {"old": "evidence"})
    def persist(*_a, **kw):
        assert kw["expected_row_version"] == 7
        assert ("calendar_revision" in kw["set_values"]) == changed
        return offset
    monkeypatch.setattr(offset_lifecycle, "_persist_offset_update", persist)
    monkeypatch.setattr(offset_lifecycle, "_complete_lifecycle_command", lambda *_a, **kw: kw["before"])
    assert offset_lifecycle.correct_expense_offset(Mock(), tenant_id="target", expense_id=1,
        offset_public_id="offset", payload=payload, actor_account_id=1, actor_device_public_id=None,
        actor_device_name=None, idempotency_key="correction") == {"old": "evidence"}


@pytest.mark.parametrize("changes", [
    {"accounting_date": "2026-04-30"},
    {"instant_utc": "2026-04-30T17:30:00Z"},
    {"source_utc_offset_seconds": 28800},
])
def test_contradictory_native_time_stays_error_with_original_json(changes):
    snapshot = {"precision": "instant", "instant_utc": "2026-04-30T16:30:00Z",
        "user_local_date": "2026-04-30", "source_timezone": "UTC", "source_utc_offset_seconds": 0,
        "accounting_date": "2026-05-01", "calendar_revision": 99, "basis": "user_selected", **changes}
    source_id = "11d98b2e-1c28-4e4c-8243-e81c07d6c6b4"
    cells = {"entry_kind": "expense", "public_id": source_id, "root_expense_public_id": source_id,
        "amount_cents": "100", "home_currency_code": "CNY", "original_currency_code": "CNY",
        "original_amount_minor": "100", "exchange_rate_to_cny": "1", "exchange_rate_date": "2026-04-30",
        "exchange_rate_source": "base", "stream_date": "2026-05-01", "stream_amount_cents": "100",
        "lineage_status": "confirmed", "lineage_home_net_cents": "100", "expense_time": "2026-04-30T16:30:00Z",
        "accounting_time": json.dumps(snapshot)}
    parsed = import_service.parse_csv_row(list(cells), list(cells.values()), line_number=2,
        timezone_name="Asia/Shanghai", home_currency="CNY", calendar_revision=3)
    assert not parsed.is_valid and "accounting_time" in parsed.error
    staged = _row_from_parsed(CsvImportBatch(id=1, tenant_id="target"), parsed)
    assert _error_csv_values(staged)["accounting_time"] == cells["accounting_time"]


def test_old_offset_and_invitation_response_omit_absent_time_evidence():
    offset = ExpenseOffsetResponse.model_construct(kind="refund", amount_cents=1)
    assert "accounting_time" not in offset.model_dump(mode="json")
    assert offset.model_copy(update={"accounting_time": None}).model_dump(mode="json")["accounting_time"] is None
    invitation = BillSplitSentResponse.model_construct()
    assert "accounting_time_snapshot" not in invitation.model_dump(mode="json")
