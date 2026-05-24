"""State transitions: accept / reject / cancel / expire (+ _mark_expired)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitInvitation, Expense
from app.services.bill_split_service._common import (
    SPLIT_RECEIVED_SOURCE,
    _audit,
    _load_writer_member,
)
from app.services.bill_split_service._query import get_invitation
from app.services.time_service import ensure_utc, now_utc


def accept_invitation(
    db: Session,
    *,
    public_id: str,
    accepting_account_id: int,
    target_ledger_id: str,
) -> tuple[BillSplitInvitation, Expense]:
    """Receiver accepts; service creates the decoupled Expense in the
    receiver's chosen ledger and binds the invitation."""
    inv = get_invitation(db, public_id)

    # Identity check first — don't leak any other state if caller isn't
    # the receiver.
    if accepting_account_id != inv.receiver_account_id:
        raise AppError("invitation_not_yours", status_code=403)

    # Idempotent: re-accepting returns the already-created expense.
    if inv.status == "accepted":
        if inv.received_expense_id is None or inv.receiver_ledger_id is None:
            # Should be impossible (UNIQUE constraint), but guard anyway.
            raise AppError("server_error", status_code=500)
        existing = db.scalar(
            select(Expense)
            .where(Expense.id == inv.received_expense_id)
            .where(Expense.tenant_id == inv.receiver_ledger_id)
        )
        if existing is None:
            raise AppError("server_error", status_code=500)
        return inv, existing
    if inv.status != "invited":
        raise AppError("invitation_not_acceptable", status_code=409)

    # Expiry check (do not silently auto-expire here — if exactly at TTL,
    # let the caller see a clear "expired" error then run the sweeper).
    # SQLite returns naive datetimes; coerce both sides to UTC-aware.
    if ensure_utc(inv.expires_at) <= now_utc():
        _mark_expired(db, inv)
        raise AppError("invitation_expired", status_code=410)

    # Target ledger constraints.
    if target_ledger_id == inv.sender_ledger_id:
        raise AppError(
            "ledger_forbidden",
            "不能接受到 sender 的同一个账本。",
            status_code=403,
        )
    target_member = _load_writer_member(db, target_ledger_id, accepting_account_id)

    # Build the receiver-side expense from the snapshot.
    now = now_utc()
    received = Expense(
        tenant_id=target_ledger_id,
        amount_cents=inv.amount_cents,
        home_currency_code=inv.home_currency_code,
        original_currency_code=inv.original_currency_code,
        original_amount_minor=inv.original_amount_minor,
        exchange_rate_to_cny=inv.exchange_rate_to_cny,
        exchange_rate_source=inv.exchange_rate_source,
        merchant=inv.merchant_snapshot,
        category=inv.category_suggestion or "其他",
        note=None,
        source=SPLIT_RECEIVED_SOURCE,
        status="confirmed",
        expense_time=inv.expense_time_snapshot,
        created_at=now,
        updated_at=now,
        confirmed_at=now,
        split_origin_invitation_id=inv.public_id,
    )
    db.add(received)
    try:
        db.flush()  # need received.id for invitation.received_expense_id
    except IntegrityError as exc:  # noqa: BLE001
        db.rollback()
        raise AppError("server_error", status_code=500) from exc

    inv.status = "accepted"
    inv.accepted_at = now
    inv.received_expense_id = received.id
    inv.receiver_ledger_id = target_ledger_id
    inv.receiver_member_id = target_member.id

    _audit(db, target_ledger_id, "bill_split_accepted",
           actor_account_id=accepting_account_id,
           target_account_id=inv.sender_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
    db.refresh(inv)
    db.refresh(received)
    return inv, received


def reject_invitation(
    db: Session, *, public_id: str, rejecting_account_id: int
) -> BillSplitInvitation:
    inv = get_invitation(db, public_id)
    if rejecting_account_id != inv.receiver_account_id:
        raise AppError("invitation_not_yours", status_code=403)
    if inv.status != "invited":
        raise AppError("invitation_not_acceptable", status_code=409)
    inv.status = "rejected"
    inv.rejected_at = now_utc()
    _audit(db, inv.sender_ledger_id, "bill_split_rejected",
           actor_account_id=rejecting_account_id,
           target_account_id=inv.sender_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
    db.refresh(inv)
    return inv


def cancel_invitation(
    db: Session, *, public_id: str, sender_account_id: int
) -> BillSplitInvitation:
    inv = get_invitation(db, public_id)
    if sender_account_id != inv.sender_account_id:
        raise AppError("invitation_not_yours", status_code=403)
    if inv.status != "invited":
        # Already terminal — accepted invitations CANNOT be cancelled
        # because the receiver already has a real expense.
        raise AppError("invitation_not_cancellable", status_code=409)
    inv.status = "cancelled"
    inv.cancelled_at = now_utc()
    _audit(db, inv.sender_ledger_id, "bill_split_cancelled",
           actor_account_id=sender_account_id,
           target_account_id=inv.receiver_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
    db.refresh(inv)
    return inv


def expire_invitations(db: Session) -> int:
    """Sweeper: anything ``invited`` with ``expires_at < now`` → expired.

    Returns count of newly-expired rows. Intended to be called from a
    scheduled background task ([[ADR-0030]] handler) or on demand."""
    now = now_utc()
    # SQLAlchemy comparison with TZ-aware datetime on SQLite works for
    # the WHERE clause (server-side string compare is timezone-blind);
    # the values it compares against are stored as naive strings. As long
    # as both we and the DB serialize to ISO-with-Z this is fine.
    pending = list(
        db.scalars(
            select(BillSplitInvitation)
            .where(BillSplitInvitation.status == "invited")
            .where(BillSplitInvitation.expires_at <= now)
        )
    )
    for inv in pending:
        inv.status = "expired"
        inv.expired_at = now
        _audit(db, inv.sender_ledger_id, "bill_split_expired",
               actor_account_id=None,
               target_account_id=inv.receiver_account_id,
               invitation_public_id=inv.public_id)
    if pending:
        db.commit()
    return len(pending)


def _mark_expired(db: Session, inv: BillSplitInvitation) -> None:
    inv.status = "expired"
    inv.expired_at = now_utc()
    _audit(db, inv.sender_ledger_id, "bill_split_expired",
           actor_account_id=None,
           target_account_id=inv.receiver_account_id,
           invitation_public_id=inv.public_id)
    db.commit()
