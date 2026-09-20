"""Resolve one accepted split and its existing debt facts under participant scope."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitAgreementChange, BillSplitInvitation, Debt, MemberRepaymentProposal
from app.services.bill_split_service._agreement_amounts import SettlementAmounts
from app.services.debt_service._fold import _forgiveness_total, compute_paid, compute_remaining
from app.services.debt_service._query import resolve_debt_for_participant
from app.services.debt_service._serialize import lock_debt_for_intent
from app.services.time_service import now_utc


@dataclass(frozen=True)
class AgreementContext:
    invitation: BillSplitInvitation
    original: Debt
    returned: Debt | None


def return_debt(db: Session, original: Debt) -> Debt | None:
    return db.scalar(select(Debt).where(Debt.source_type == "bill_split_return", Debt.source_id == original.source_id))


def agreement_context(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, lock: bool = False,
) -> AgreementContext:
    visible, _ = resolve_debt_for_participant(db, public_id=public_id,
        ledger_id=tenant_id, account_id=actor_account_id)
    if visible.source_type not in {"bill_split", "bill_split_return"}:
        raise AppError("split_change_unavailable", status_code=409)
    original = visible if visible.source_type == "bill_split" else db.scalar(select(Debt).where(
        Debt.source_type == "bill_split", Debt.source_id == visible.source_id))
    invitation = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == visible.source_id))
    if original is None or invitation is None or invitation.status != "accepted":
        raise AppError("split_change_unavailable", status_code=409)
    if lock:
        # Every paired mutation anchors on the original first. Existing ordinary
        # repayment/forgiveness writers take one leg and never request the other.
        original = lock_debt_for_intent(db, tenant_id=tenant_id, account_id=actor_account_id,
            public_id=original.public_id)
    returned = return_debt(db, original)
    if lock and returned is not None:
        returned = lock_debt_for_intent(db, tenant_id=tenant_id, account_id=actor_account_id,
            public_id=returned.public_id)
    return AgreementContext(invitation, original, returned)


def require_agreement_party(context: AgreementContext, actor_account_id: int) -> None:
    if actor_account_id not in (context.invitation.sender_account_id, context.invitation.receiver_account_id):
        raise AppError("split_change_party_only", status_code=403)


def agreement_amounts(db: Session, context: AgreementContext) -> SettlementAmounts:
    original, returned = context.original, context.returned
    return SettlementAmounts(original_remaining=compute_remaining(db, original),
        return_remaining=compute_remaining(db, returned) if returned else 0,
        original_paid=compute_paid(db, original), return_paid=compute_paid(db, returned) if returned else 0,
        original_forgiven=_forgiveness_total(db, original.id),
        return_forgiven=_forgiveness_total(db, returned.id) if returned else 0)


def latest_agreement_change(db: Session, context: AgreementContext) -> BillSplitAgreementChange | None:
    return db.scalar(select(BillSplitAgreementChange).where(
        BillSplitAgreementChange.invitation_id == context.invitation.id)
        .order_by(BillSplitAgreementChange.id.desc()).limit(1))


def pending_repayment_debts(db: Session, context: AgreementContext) -> list[str]:
    ids = [context.original.id, *([context.returned.id] if context.returned else [])]
    return list(db.scalars(select(Debt.public_id).join(MemberRepaymentProposal,
        MemberRepaymentProposal.debt_id == Debt.id).where(Debt.id.in_(ids),
        MemberRepaymentProposal.status == "pending", MemberRepaymentProposal.expires_at > now_utc())
        .order_by(Debt.id)))
