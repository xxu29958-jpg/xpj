"""Relationship-owner settlement for a source Expense financial change."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillSplitInvitation
from app.services.bill_split_service._common import _audit
from app.services.bill_split_service._query import (
    AcceptedSourceRelationship,
    list_accepted_source_relationships,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc

_SUPPORTED_REASONS = frozenset(
    {"source_refunded", "source_chargeback", "source_reversed"}
)


@dataclass(frozen=True)
class SourceFinancialChangeImpacts:
    cancelled_public_ids: tuple[str, ...]
    accepted_relationships: tuple[AcceptedSourceRelationship, ...]


def settle_source_financial_change(
    db: Session,
    *,
    sender_ledger_id: str,
    sender_expense_id: int,
    reason_code: str,
    actor_account_id: int,
) -> SourceFinancialChangeImpacts:
    """Cancel still-pending invitations in the caller's offset transaction."""

    if reason_code not in _SUPPORTED_REASONS:
        raise ValueError("unsupported source financial change reason")
    resolve_write_capability(db)
    invitations = list(
        db.scalars(
            select(BillSplitInvitation)
            .where(BillSplitInvitation.sender_ledger_id == sender_ledger_id)
            .where(BillSplitInvitation.sender_expense_id == sender_expense_id)
            .where(BillSplitInvitation.status == "invited")
            .order_by(BillSplitInvitation.created_at, BillSplitInvitation.id)
            .with_for_update()
        )
    )
    settled_at = now_utc()
    for invitation in invitations:
        invitation.status = "cancelled"
        invitation.cancelled_at = settled_at
        invitation.cancellation_reason_code = reason_code
        _audit(
            db,
            invitation.sender_ledger_id,
            "bill_split_cancelled",
            actor_account_id=actor_account_id,
            target_account_id=invitation.receiver_account_id,
            invitation_public_id=invitation.public_id,
        )
    return SourceFinancialChangeImpacts(
        cancelled_public_ids=tuple(invitation.public_id for invitation in invitations),
        accepted_relationships=list_accepted_source_relationships(
            db,
            sender_ledger_id=sender_ledger_id,
            sender_expense_id=sender_expense_id,
        ),
    )


__all__ = ["SourceFinancialChangeImpacts", "settle_source_financial_change"]
