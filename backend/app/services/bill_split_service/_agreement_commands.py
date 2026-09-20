"""Bilateral accepted-split changes; append facts in the caller's transaction."""

from datetime import timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitAgreementChange, BillSplitChangeProposal, Debt, DebtAdjustment
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest, BillSplitChangeCreateRequest
from app.services.bill_split_service._agreement_amounts import settlement_targets
from app.services.bill_split_service._agreement_context import (
    AgreementContext,
    agreement_amounts,
    agreement_context,
    latest_agreement_change,
    pending_repayment_debts,
    require_agreement_party,
)
from app.services.bill_split_service._create import ensure_changed_share_capacity
from app.services.currency_binding_service import resolve_write_capability
from app.services.debt_service._fold import compute_remaining_for_write, derive_status
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import ensure_utc, now_utc


def _validate_basis(db: Session, context: AgreementContext, original_version: int, return_version: int | None) -> None:
    original, returned = context.original, context.returned
    if original.status == "voided" or (returned is not None and returned.status == "voided"):
        raise AppError("debt_already_voided", status_code=409)
    if original.row_version != original_version or (returned.row_version if returned else None) != return_version:
        raise AppError("state_conflict", status_code=409)
    if pending_repayment_debts(db, context):
        raise AppError("split_change_repayment_pending", status_code=409)


def _latch(db: Session, proposal: BillSplitChangeProposal, status: str, actor_account_id: int) -> None:
    result = db.execute(update(BillSplitChangeProposal).where(BillSplitChangeProposal.id == proposal.id,
        BillSplitChangeProposal.status == "pending").values(status=status, resolved_at=now_utc(),
        resolved_by_account_id=actor_account_id))
    if result.rowcount != 1:
        raise AppError("split_change_not_pending", status_code=409)
    db.expire(proposal)


def _replace_pending(
    db: Session, context: AgreementContext, payload: BillSplitChangeCreateRequest, actor_account_id: int,
) -> None:
    pending = db.scalar(select(BillSplitChangeProposal).where(
        BillSplitChangeProposal.invitation_id == context.invitation.id, BillSplitChangeProposal.status == "pending"))
    if pending is None:
        if payload.supersedes_proposal_public_id is not None:
            raise AppError("state_conflict", status_code=409)
        return
    if ensure_utc(pending.expires_at) <= now_utc():
        _latch(db, pending, "expired", actor_account_id)
        return
    if payload.supersedes_proposal_public_id != pending.public_id:
        raise AppError("split_change_pending", status_code=409)
    _latch(db, pending, "superseded", actor_account_id)


def create_bill_split_change(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, payload: BillSplitChangeCreateRequest,
) -> BillSplitChangeProposal:
    resolve_write_capability(db)
    context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id, lock=True)
    require_agreement_party(context, actor_account_id)
    _validate_basis(db, context, payload.expected_row_version, payload.expected_return_row_version)
    _replace_pending(db, context, payload, actor_account_id)
    amounts = agreement_amounts(db, context)
    latest = latest_agreement_change(db, context)
    now = now_utc()
    proposal = BillSplitChangeProposal(invitation_id=context.invitation.id, proposed_by_account_id=actor_account_id,
        original_debt_id=context.original.id, original_debt_row_version=context.original.row_version,
        return_debt_id=context.returned.id if context.returned else None,
        return_debt_row_version=context.returned.row_version if context.returned else None,
        share_before_amount_cents=latest.new_share_amount_cents if latest else context.invitation.amount_cents,
        new_share_amount_cents=payload.new_share_amount_cents, settlement_net_amount_cents=payload.settlement_net_amount_cents,
        settlement_before_net_amount_cents=amounts.original_remaining - amounts.return_remaining,
        original_paid_amount_cents=amounts.original_paid, return_paid_amount_cents=amounts.return_paid,
        original_forgiven_amount_cents=amounts.original_forgiven, return_forgiven_amount_cents=amounts.return_forgiven,
        reason=payload.reason, status="pending", created_at=now, expires_at=now + timedelta(days=30))
    db.add(proposal)
    db.flush()
    return proposal


def _proposal_for_context(db: Session, context: AgreementContext, proposal_public_id: str) -> BillSplitChangeProposal:
    proposal = db.scalar(select(BillSplitChangeProposal).where(BillSplitChangeProposal.public_id == proposal_public_id,
        BillSplitChangeProposal.invitation_id == context.invitation.id))
    if proposal is None:
        raise AppError("split_change_not_found", status_code=404)
    if proposal.status != "pending":
        raise AppError("split_change_not_pending", status_code=409)
    if ensure_utc(proposal.expires_at) <= now_utc():
        raise AppError("split_change_expired", status_code=410)
    return proposal


def _adjust_to_target(
    db: Session, debt: Debt, target: int, *, actor_account_id: int, reason: str, idempotency_key: str,
) -> DebtAdjustment | None:
    delta = target - compute_remaining_for_write(db, debt)
    adjustment = None
    if delta:
        adjustment = DebtAdjustment(debt_id=debt.id, amount_cents=delta, reason=reason,
            actor_account_id=actor_account_id, idempotency_key=idempotency_key)
        db.add(adjustment)
        db.flush()
    # Even an unchanged balance has a new shared agreement to refresh and fence.
    bump_row_version(debt)
    debt.updated_at = now_utc()
    debt.status = derive_status(debt, target)
    return adjustment


def _create_return(db: Session, context: AgreementContext, target: int, actor_account_id: int) -> Debt:
    original = context.original
    debt = Debt(tenant_id=original.tenant_id, owner_account_id=original.owner_account_id,
        created_by_account_id=actor_account_id, direction="owed_to_me", counterparty_type="member",
        counterparty_account_id=original.counterparty_account_id, counterparty_label=original.counterparty_label,
        principal_amount_cents=target, home_currency_code=original.home_currency_code, status="open",
        source_type="bill_split_return", source_id=original.source_id)
    db.add(debt)
    db.flush()
    return debt


def accept_bill_split_change(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, proposal_public_id: str,
    payload: BillSplitChangeAcceptRequest, idempotency_key: str,
) -> BillSplitAgreementChange:
    resolve_write_capability(db)
    context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id, lock=True)
    require_agreement_party(context, actor_account_id)
    proposal = _proposal_for_context(db, context, proposal_public_id)
    if proposal.proposed_by_account_id == actor_account_id:
        raise AppError("split_change_other_party_only", status_code=403)
    if (payload.expected_row_version, payload.expected_return_row_version) != (
        proposal.original_debt_row_version, proposal.return_debt_row_version
    ):
        raise AppError("state_conflict", status_code=409)
    _validate_basis(db, context, proposal.original_debt_row_version, proposal.return_debt_row_version)
    ensure_changed_share_capacity(db, invitation=context.invitation,
        previous_share=proposal.share_before_amount_cents, new_share=proposal.new_share_amount_cents)
    original_target, return_target = settlement_targets(proposal.settlement_net_amount_cents)
    original_adjustment = _adjust_to_target(db, context.original, original_target, actor_account_id=actor_account_id,
        reason=proposal.reason, idempotency_key=idempotency_key)
    returned, return_adjustment = context.returned, None
    if returned is not None:
        return_adjustment = _adjust_to_target(db, returned, return_target, actor_account_id=actor_account_id,
            reason=proposal.reason, idempotency_key=idempotency_key)
    elif return_target:
        returned = _create_return(db, context, return_target, actor_account_id)
    change = BillSplitAgreementChange(proposal_id=proposal.id, invitation_id=context.invitation.id,
        share_before_amount_cents=proposal.share_before_amount_cents, new_share_amount_cents=proposal.new_share_amount_cents,
        settlement_net_amount_cents=proposal.settlement_net_amount_cents, original_debt_id=context.original.id,
        return_debt_id=returned.id if returned else None,
        original_adjustment_id=original_adjustment.id if original_adjustment else None,
        return_adjustment_id=return_adjustment.id if return_adjustment else None,
        proposed_by_account_id=proposal.proposed_by_account_id, accepted_by_account_id=actor_account_id)
    db.add(change)
    _latch(db, proposal, "accepted", actor_account_id)
    db.flush()
    return change


def resolve_bill_split_change(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, proposal_public_id: str,
    resolution: Literal["rejected", "withdrawn"],
) -> BillSplitChangeProposal:
    resolve_write_capability(db)
    context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id, lock=True)
    require_agreement_party(context, actor_account_id)
    proposal = _proposal_for_context(db, context, proposal_public_id)
    own = proposal.proposed_by_account_id == actor_account_id
    if resolution == "withdrawn" and not own:
        raise AppError("split_change_proposer_only", status_code=403)
    if resolution == "rejected" and own:
        raise AppError("split_change_other_party_only", status_code=403)
    _latch(db, proposal, resolution, actor_account_id)
    return proposal
