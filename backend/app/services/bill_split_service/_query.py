"""Read-only invitation lookups: list_sent / list_inbox / get_invitation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitInvitation

_INVITATION_STATUSES = frozenset({"invited", "accepted", "rejected", "cancelled", "expired"})


def list_sent(
    db: Session, *, sender_account_id: int, sender_ledger_id: str, limit: int = 50
) -> list[BillSplitInvitation]:
    """Sender view — ledger-scoped (sender_ledger_id is sender's current
    ledger, not invitation.receiver_ledger_id)."""
    rows = db.scalars(
        select(BillSplitInvitation)
        .where(BillSplitInvitation.sender_account_id == sender_account_id)
        .where(BillSplitInvitation.sender_ledger_id == sender_ledger_id)
        .order_by(BillSplitInvitation.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def list_inbox(
    db: Session, *, receiver_account_id: int, status: str | None = None, limit: int = 50
) -> list[BillSplitInvitation]:
    """Receiver view — **account-scoped, NOT ledger-scoped**. Receiver's
    inbox is the same no matter which ledger they're currently viewing,
    because invitations are not yet bound to a target ledger when they
    arrive."""
    statement = select(BillSplitInvitation).where(
        BillSplitInvitation.receiver_account_id == receiver_account_id
    )
    if status is not None:
        status_value = status.strip().lower()
        if status_value not in _INVITATION_STATUSES:
            raise AppError("invalid_request", "Unsupported invitation status.", status_code=400)
        statement = statement.where(BillSplitInvitation.status == status_value)
    rows = db.scalars(statement.order_by(BillSplitInvitation.created_at.desc()).limit(limit))
    return list(rows)


def get_invitation(db: Session, public_id: str) -> BillSplitInvitation:
    inv = db.scalar(
        select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
    )
    if inv is None:
        raise AppError("invitation_not_found", status_code=404)
    return inv
