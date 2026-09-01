"""Read-only invitation lookups: list_sent / list_inbox / get_invitation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitInvitation, Debt, ExpenseOffsetFact

_INVITATION_STATUSES = frozenset({"invited", "accepted", "rejected", "cancelled", "expired"})


@dataclass(frozen=True)
class AcceptedSourceRelationship:
    invitation_public_id: str
    receiver_display_name: str | None
    agreed_share_home_minor: int
    debt_public_id: str | None


def list_accepted_source_relationships(
    db: Session,
    *,
    sender_ledger_id: str,
    sender_expense_id: int,
) -> tuple[AcceptedSourceRelationship, ...]:
    """Read accepted split snapshots and their canonical Debt links in two queries."""

    invitations = list(
        db.scalars(
            select(BillSplitInvitation)
            .where(BillSplitInvitation.sender_ledger_id == sender_ledger_id)
            .where(BillSplitInvitation.sender_expense_id == sender_expense_id)
            .where(BillSplitInvitation.status == "accepted")
            .order_by(BillSplitInvitation.created_at, BillSplitInvitation.id)
        )
    )
    if not invitations:
        return ()
    public_ids = [invitation.public_id for invitation in invitations]
    debt_by_source = dict(
        db.execute(
            select(Debt.source_id, Debt.public_id)
            .where(Debt.source_type == "bill_split")
            .where(Debt.source_id.in_(public_ids))
        ).all()
    )
    return tuple(
        AcceptedSourceRelationship(
            invitation_public_id=invitation.public_id,
            receiver_display_name=invitation.receiver_display_name_snapshot,
            agreed_share_home_minor=invitation.amount_cents,
            debt_public_id=debt_by_source.get(invitation.public_id),
        )
        for invitation in invitations
    )


def source_impact_pending_invitation_ids(
    db: Session,
    *,
    sender_ledger_id: str,
    invitations: list[BillSplitInvitation],
) -> frozenset[str]:
    """Return accepted sent rows whose source Expense has an active offset."""

    accepted = [invitation for invitation in invitations if invitation.status == "accepted"]
    if not accepted:
        return frozenset()
    expense_ids = {invitation.sender_expense_id for invitation in accepted}
    affected_expense_ids = set(
        db.scalars(
            select(ExpenseOffsetFact.expense_id)
            .where(ExpenseOffsetFact.tenant_id == sender_ledger_id)
            .where(ExpenseOffsetFact.expense_id.in_(expense_ids))
            .where(ExpenseOffsetFact.status == "active")
            .distinct()
        )
    )
    return frozenset(
        invitation.public_id
        for invitation in accepted
        if invitation.sender_expense_id in affected_expense_ids
    )


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


def list_sent_for_expense(
    db: Session, *, sender_account_id: int, expense_id: int, limit: int = 50
) -> list[BillSplitInvitation]:
    """Invitations this sender created from one specific source expense.

    Used by the /web edit-page 发起卡 to list the invitations already sent
    *from this bill* (``list_sent`` is ledger-scoped over every expense).
    Sender-account-scoped so it cannot surface another account's rows.
    """
    rows = db.scalars(
        select(BillSplitInvitation)
        .where(BillSplitInvitation.sender_account_id == sender_account_id)
        .where(BillSplitInvitation.sender_expense_id == expense_id)
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
            raise AppError("split_status_invalid", "Unsupported invitation status.", status_code=400)
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
