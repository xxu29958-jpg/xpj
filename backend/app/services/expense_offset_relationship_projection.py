"""Read-only relationship impacts derived from Expense offset facts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import ExpenseOffsetFact
from app.schemas import ExpenseFinancialSummary, ExpenseRelationshipImpacts
from app.services.bill_split_service import (
    AcceptedSourceRelationship,
    list_accepted_source_relationships,
)

_REASON_BY_KIND = {
    "refund": "source_refunded",
    "chargeback": "source_chargeback",
    "reversal": "source_reversed",
}


def source_relationship_reason(kind: str) -> str:
    return _REASON_BY_KIND[kind]


def _suggested_share(
    *,
    agreed_share: int,
    remaining_original: int,
    gross_original: int,
) -> int:
    if gross_original <= 0 or remaining_original <= 0:
        return 0
    suggested = int(
        (Decimal(agreed_share) * Decimal(remaining_original) / Decimal(gross_original)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return min(max(suggested, 0), agreed_share)


def relationship_impacts(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    offsets: list[ExpenseOffsetFact],
    summary: ExpenseFinancialSummary,
    accepted_relationships: tuple[AcceptedSourceRelationship, ...] | None = None,
    cancelled_public_ids: tuple[str, ...] = (),
    cancellation_reason_code: str | None = None,
) -> ExpenseRelationshipImpacts:
    accepted = accepted_relationships
    if accepted is None:
        accepted = list_accepted_source_relationships(
            db,
            sender_ledger_id=tenant_id,
            sender_expense_id=expense_id,
        )
    accepted_impacts: list[dict[str, object]] = []
    if offsets and accepted:
        latest = max(offsets, key=lambda offset: (offset.accounting_date, offset.id))
        source_reason_code = source_relationship_reason(latest.kind)
        accepted_impacts = [
            {
                "invitation_public_id": relationship.invitation_public_id,
                "source_reason_code": source_reason_code,
                "receiver_display_name": relationship.receiver_display_name,
                "debt_public_id": relationship.debt_public_id,
                "original_agreed_share_home_minor": relationship.agreed_share_home_minor,
                "suggested_net_share_home_minor": _suggested_share(
                    agreed_share=relationship.agreed_share_home_minor,
                    remaining_original=summary.remaining_refundable_original_minor,
                    gross_original=summary.gross_original_minor,
                ),
                "suggested_action": "review_split",
            }
            for relationship in accepted
        ]
    pending_receipts: list[dict[str, str]] = []
    if cancellation_reason_code is not None:
        pending_receipts = [
            {
                "invitation_public_id": public_id,
                "cancellation_reason_code": cancellation_reason_code,
            }
            for public_id in cancelled_public_ids
        ]
    return ExpenseRelationshipImpacts(
        pending_invites_cancelled=pending_receipts,
        accepted_impacts=accepted_impacts,
    )


__all__ = ["relationship_impacts", "source_relationship_reason"]
