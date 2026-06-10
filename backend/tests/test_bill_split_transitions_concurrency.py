"""Bill split transition concurrency + expiry-path tests.

The 2026-06-10 audit found ``reject_invitation`` / ``cancel_invitation`` /
``_mark_expired`` / the ``expire_invitations`` sweeper were read-modify-write
(plain ORM assignment), while ``accept_invitation`` already used the
ADR-0038 PR-C atomic claim (``UPDATE … WHERE status='invited'`` + rowcount).
A stale-read transition racing a committed accept could clobber the
'accepted' row, contradicting the receiver's already-confirmed expense.
These tests pin the guarded-flip behaviour for every non-accept transition,
plus the previously untested expiry path (TTL 410 / sweeper).

The ``test_two_sessions_*`` names opt into ``real_db`` via the conftest
naming convention — the races need real cross-connection commits.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.database import SessionLocal
from app.errors import AppError
from app.models import BillSplitInvitation, Expense, LedgerAuditLog
from app.services import bill_split_service as bsplit
from app.services.bill_split_service._transitions import _mark_expired
from app.services.time_service import now_utc
from tests.test_bill_split import (
    _make_expense_for_owner,
    _owner_account_id,
    _seed_receiver,
)


def _backdate_expiry(public_id: str) -> None:
    """Force an invitation's TTL into the past directly in the DB."""
    with SessionLocal() as db:
        db.execute(
            update(BillSplitInvitation)
            .where(BillSplitInvitation.public_id == public_id)
            .values(expires_at=now_utc() - timedelta(days=1))
        )
        db.commit()


def _create_invitation_for_race(
    *, receiver_account_id: int, amount_cents: int = 2500
) -> str:
    expense_id = _make_expense_for_owner(amount_cents=5000)
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=amount_cents,
        )
        return inv.public_id


def test_two_sessions_reject_vs_accept_race_does_not_clobber_accepted(*, identity) -> None:
    """session_b holds a stale 'invited' read of an invitation; session_a
    accepts and commits; session_b's reject must lose to the guarded flip
    (409) instead of overwriting the accepted row — the receiver's confirmed
    expense and the invitation status stay consistent."""
    receiver_account_id = _seed_receiver(name="B-rejrace", ledger_id="receiver_rejrace")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_b = session_b.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert row_b is not None and row_b.status == "invited"

        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_rejrace",
        )

        with pytest.raises(AppError) as exc:
            bsplit.reject_invitation(
                session_b,
                public_id=public_id,
                rejecting_account_id=receiver_account_id,
            )
        assert exc.value.error == "invitation_not_acceptable"
        assert exc.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.rejected_at is None
        received = db.scalar(
            select(Expense).where(Expense.split_origin_invitation_id == public_id)
        )
        assert received is not None and received.status == "confirmed"


def test_two_sessions_cancel_vs_accept_race_does_not_clobber_accepted(*, identity) -> None:
    """The audited defect: sender cancel racing receiver accept. Once the
    accept claim lands, the receiver holds a confirmed expense whose money
    fields are frozen — a stale-read cancel overwriting status to 'cancelled'
    would leave debt the sender believes was withdrawn. The guarded flip must
    make the cancel lose with 409."""
    receiver_account_id = _seed_receiver(name="B-canrace", ledger_id="receiver_canrace")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_b = session_b.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert row_b is not None and row_b.status == "invited"

        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_canrace",
        )

        with pytest.raises(AppError) as exc:
            bsplit.cancel_invitation(
                session_b,
                public_id=public_id,
                sender_account_id=_owner_account_id(),
            )
        assert exc.value.error == "invitation_not_cancellable"
        assert exc.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.cancelled_at is None


def test_two_sessions_mark_expired_loses_to_settled_invitation(*, identity) -> None:
    """``_mark_expired`` only flips rows still 'invited': against a stale
    snapshot of a row that has since been accepted it reports ``False`` and
    writes nothing (no status clobber, no bill_split_expired audit row)."""
    receiver_account_id = _seed_receiver(name="B-exprace", ledger_id="receiver_exprace")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_b = session_b.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert row_b is not None and row_b.status == "invited"

        bsplit.accept_invitation(
            session_a,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_exprace",
        )

        assert _mark_expired(session_b, row_b) is False
    finally:
        session_a.close()
        session_b.close()

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.expired_at is None
        expired_audit = list(
            db.scalars(
                select(LedgerAuditLog)
                .where(LedgerAuditLog.invitation_public_id == public_id)
                .where(LedgerAuditLog.action == "bill_split_expired")
            )
        )
        assert expired_audit == []


def test_accept_after_ttl_marks_expired_and_returns_410(*, identity) -> None:
    receiver_account_id = _seed_receiver(name="B-ttl", ledger_id="receiver_ttl")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    _backdate_expiry(public_id)

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_ttl",
        )
    assert exc.value.error == "invitation_expired"
    assert exc.value.status_code == 410

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "expired"
        assert inv.expired_at is not None


def test_expire_sweeper_expires_overdue_invited_invitation(*, identity) -> None:
    receiver_account_id = _seed_receiver(name="B-sweep", ledger_id="receiver_sweep")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    _backdate_expiry(public_id)

    with SessionLocal() as db:
        assert bsplit.expire_invitations(db) == 1

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "expired"
        assert inv.expired_at is not None
        expired_audit = list(
            db.scalars(
                select(LedgerAuditLog)
                .where(LedgerAuditLog.invitation_public_id == public_id)
                .where(LedgerAuditLog.action == "bill_split_expired")
            )
        )
        assert len(expired_audit) == 1


def test_expire_sweeper_does_not_clobber_accepted_row_past_ttl(*, identity) -> None:
    """An accepted invitation whose TTL has since lapsed must survive the
    sweeper untouched — the guarded UPDATE only matches 'invited' rows."""
    receiver_account_id = _seed_receiver(name="B-sweepacc", ledger_id="receiver_sweepacc")
    public_id = _create_invitation_for_race(receiver_account_id=receiver_account_id)
    with SessionLocal() as db:
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_sweepacc",
        )
    _backdate_expiry(public_id)

    with SessionLocal() as db:
        assert bsplit.expire_invitations(db) == 0

    with SessionLocal() as db:
        inv = db.scalar(
            select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
        )
        assert inv is not None
        assert inv.status == "accepted"
        assert inv.expired_at is None
