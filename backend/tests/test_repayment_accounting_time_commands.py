"""Payment-time intent at the existing command owners; no database emulation."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, LedgerCalendarRevision, MemberRepaymentProposal, Repayment
from app.schemas import MemberRepaymentProposalCreateRequest, RepaymentCreateRequest
from app.services.debt_service import _money, _proposal, _repayment


def _command(monkeypatch, kind, time_input, **extra):
    db = MagicMock(spec=Session)
    db.get.return_value = LedgerCalendarRevision(
        ledger_id="original-ledger", revision=3, timezone_name="Pacific/Honolulu",
    )
    debt = Debt(id=4, public_id="original-debt", tenant_id="original-ledger",
        home_currency_code="CNY", counterparty_type="external", row_version=7)
    monkeypatch.setattr(_repayment, "resolve_write_capability", lambda _db: None)
    monkeypatch.setattr(_proposal, "resolve_write_capability", lambda _db: None)
    rates = []

    def rate(_db, **values):
        rates.append(values["rate_date"])
        return Decimal("7"), "manual", "ready", values["rate_date"]

    monkeypatch.setattr(_money, "resolve_payload_rate", rate)
    if kind == "direct":
        monkeypatch.setattr(_repayment, "guard_direct_fact_writable", lambda _debt: None)
        monkeypatch.setattr(_repayment, "lock_and_fold", lambda _db, **kw: (debt, kw["mutate"](debt, 100000)))
        payload = RepaymentCreateRequest(original_currency="USD", original_amount="10.00",
            expected_row_version=7, time_input=time_input, **extra)
        _repayment.record_repayment(db, tenant_id="original-ledger", public_id=debt.public_id,
            actor_account_id=2, payload=payload, idempotency_key="original-key")
    else:
        monkeypatch.setattr(_proposal, "_lock_creatable_member_debt", lambda *_a, **_k: debt)
        monkeypatch.setattr(_proposal, "proposal_debtor_creditor", lambda _debt: (2, 5))
        monkeypatch.setattr(_proposal, "_resolve_superseded_pending", lambda *_a, **_k: None)
        monkeypatch.setattr(_proposal, "proposal_response", lambda _db, proposal: proposal)
        payload = MemberRepaymentProposalCreateRequest(original_currency_code="USD",
            original_amount="10.00", time_input=time_input, **extra)
        _proposal.create_repayment_proposal(db, tenant_id="original-ledger", public_id=debt.public_id,
            actor_account_id=2, payload=payload, idempotency_key="original-key", commit=False)
    return db.add.call_args.args[0], rates, db


@pytest.mark.parametrize("kind", ["direct", "proposal"])
def test_date_only_payment_keeps_original_day_and_fx_without_a_midnight_instant(monkeypatch, kind):
    row, rates, db = _command(monkeypatch, kind, {
        "precision": "date_only", "calendar_revision": 3, "user_local_date": "2026-04-30",
        "accounting_date": "2026-05-01",
    })
    assert row.paid_at is None
    assert row.accounting_time_snapshot == {
        "precision": "date_only", "instant_utc": None, "user_local_date": "2026-04-30",
        "source_timezone": None, "source_utc_offset_seconds": None,
        "accounting_date": "2026-05-01", "calendar_revision": 3, "basis": "user_selected",
    }
    assert rates == [date(2026, 4, 30)]
    assert row.original_amount_minor == 1000 and row.exchange_rate_to_cny == Decimal("7")
    assert row.idempotency_key == "original-key" and row.debt_id == 4
    assert db.get.call_args.args[1] == ("original-ledger", 3)


@pytest.mark.parametrize("kind", ["direct", "proposal"])
def test_payment_instant_keeps_input_day_separate_from_ledger_day(monkeypatch, kind):
    row, rates, _ = _command(monkeypatch, kind, {
        "precision": "instant", "calendar_revision": 3, "user_local_date": "2026-05-01",
        "instant_utc": "2026-04-30T16:30:00Z", "source_timezone": "Asia/Shanghai",
        "source_utc_offset_seconds": 28800,
    })
    assert row.paid_at == datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    assert row.accounting_time_snapshot["accounting_date"] == "2026-04-30"
    assert row.accounting_time_snapshot["user_local_date"] == "2026-05-01"
    assert row.accounting_time_snapshot["source_utc_offset_seconds"] == 28800
    assert rates == [date(2026, 5, 1)]


@pytest.mark.parametrize("amount", [7000, 3000])
def test_member_confirmation_copies_the_proposed_time_without_reinterpreting_it(monkeypatch, amount):
    proposal, _, _ = _command(monkeypatch, "proposal", {
        "precision": "date_only", "calendar_revision": 3, "user_local_date": "2026-04-30",
    })
    assert isinstance(proposal, MemberRepaymentProposal)
    proposal.id = 9
    db = MagicMock(spec=Session)
    db.get.side_effect = AssertionError("confirmation must not resolve a new calendar")
    monkeypatch.setattr(_proposal, "_latch_proposal_resolution", lambda *_a, **_k: None)
    _proposal._commit_confirmation(db, proposal=proposal, debt_id=4, amount=amount,
        actor_account_id=5, idempotency_key="confirm-key")
    repayment = db.add.call_args.args[0]
    assert isinstance(repayment, Repayment) and repayment.paid_at is None
    assert repayment.accounting_time_snapshot == proposal.accounting_time_snapshot
    assert repayment.proposal_id == 9 and repayment.amount_cents == amount
    assert repayment.exchange_rate_to_cny == (Decimal("7") if amount == 7000 else None)


@pytest.mark.parametrize("kind", ["direct", "proposal"])
def test_legacy_payment_keeps_its_instant_without_inventing_source_evidence(monkeypatch, kind):
    original = datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    row, _, _ = _command(monkeypatch, kind, None, paid_at=original)
    assert row.paid_at == original and row.accounting_time_snapshot is None


@pytest.mark.parametrize("kind", ["direct", "proposal"])
def test_a_date_only_payment_cannot_silently_override_a_different_legacy_instant(monkeypatch, kind):
    with pytest.raises(AppError) as error:
        _command(monkeypatch, kind, {
            "precision": "date_only", "calendar_revision": 3, "user_local_date": "2026-04-30",
        }, paid_at=datetime(2026, 5, 1, tzinfo=UTC))
    assert error.value.error == "accounting_time_invalid"


def test_notification_capture_keeps_its_offset_and_calendar_before_review(monkeypatch):
    from app.services.debt_service import _repayment_time as payment_time

    monkeypatch.setattr(payment_time, "current_calendar", lambda *_a, **_k:
        LedgerCalendarRevision(ledger_id="original-ledger", revision=3, timezone_name="Pacific/Honolulu"))
    snapshot = payment_time.capture_repayment_time(MagicMock(spec=Session), ledger_id="original-ledger",
        captured_at=datetime.fromisoformat("2026-05-01T00:30:00+08:00"))
    assert snapshot.user_local_date == date(2026, 5, 1)
    assert snapshot.accounting_date == date(2026, 4, 30) and snapshot.calendar_revision == 3
    assert snapshot.source_utc_offset_seconds == 28800


def test_human_review_date_drives_the_repayment_and_fx_without_rewriting_capture(monkeypatch):
    from app.models import RepaymentDraft
    from app.schemas import RepaymentDraftConfirmRequest
    from app.services.debt_service import _repayment_draft_confirm as confirm

    original_time = {"precision": "instant", "instant_utc": "2026-05-02T00:00:00Z",
        "user_local_date": "2026-05-02", "accounting_date": "2026-05-01", "calendar_revision": 2}
    draft = RepaymentDraft(public_id="capture", status="pending", home_currency_code="CNY",
        original_currency_code="USD", original_amount_minor=1000, amount_cents=None,
        captured_at=datetime(2026, 5, 2, tzinfo=UTC), accounting_time_snapshot=original_time.copy())
    request = RepaymentDraftConfirmRequest(target_debt_public_id="debt", expected_row_version=7,
        time_input={"precision": "date_only", "calendar_revision": 3, "user_local_date": "2026-04-30"})
    db = MagicMock(spec=Session)
    db.scalar.return_value = "CNY"
    db.get.return_value = LedgerCalendarRevision(ledger_id="original-ledger", revision=3, timezone_name="Pacific/Honolulu")
    debt = Debt(id=4, tenant_id="original-ledger", home_currency_code="CNY")
    rates = []
    def rate(_db, **values):
        rates.append(values["rate_date"])
        return Decimal("7"), "manual", "ready", values["rate_date"]
    monkeypatch.setattr(confirm, "_lock_pending_draft", lambda *_a, **_k: draft)
    monkeypatch.setattr(_repayment, "resolve_write_capability", lambda _db: None)
    monkeypatch.setattr(_repayment, "guard_direct_fact_writable", lambda _debt: None)
    monkeypatch.setattr(_repayment, "lock_and_fold", lambda _db, **kw: (debt, kw["mutate"](debt, 10000)))
    monkeypatch.setattr(_money, "resolve_payload_rate", rate)
    confirm.confirm_repayment_draft(db, tenant_id="original-ledger", actor_account_id=2,
        public_id=draft.public_id, idempotency_key="original-review", time_input=request.time_input,
        **request.model_dump(exclude={"time_input"}))
    payment = db.add.call_args.args[0]
    assert payment.paid_at is None and payment.amount_cents == 7000
    assert payment.accounting_time_snapshot["user_local_date"] == "2026-04-30"
    assert payment.accounting_time_snapshot["calendar_revision"] == 3
    assert rates == [date(2026, 4, 30)]
    assert draft.accounting_time_snapshot == original_time and draft.captured_at == datetime(2026, 5, 2, tzinfo=UTC)
    assert draft.original_amount_minor == 1000 and draft.status == "confirmed"


def test_repayment_history_reads_frozen_days_without_current_display_timezone(monkeypatch):
    from app.routes._web_debt_activity import _repayment_view
    from app.services.debt_service._repayment_activity import repayment_fact_response

    row, _, _ = _command(monkeypatch, "direct", {
        "precision": "date_only", "calendar_revision": 3, "user_local_date": "2026-04-30",
        "accounting_date": "2026-05-01",
    })
    row.public_id, row.created_at = "repayment", datetime(2026, 5, 5, tzinfo=UTC)
    # The database stores the frozen rate date in its existing timestamptz column.
    row.exchange_rate_date = datetime(2026, 4, 30, tzinfo=UTC)
    fact = repayment_fact_response(row, None)
    assert fact.model_dump(mode="json")["paid_at"] is None
    for zone in ("Asia/Shanghai", "America/Los_Angeles"):
        assert _repayment_view(fact, "CNY", zone)["date_text"] == "2026-04-30 · 账务归属 2026-05-01"


@pytest.mark.parametrize("kind", ["direct", "proposal"])
def test_naive_payment_time_is_not_silently_treated_as_utc(monkeypatch, kind):
    with pytest.raises(AppError) as error:
        _command(monkeypatch, kind, None, paid_at=datetime(2026, 5, 1, 12, 30))
    assert error.value.error == "accounting_time_invalid"
