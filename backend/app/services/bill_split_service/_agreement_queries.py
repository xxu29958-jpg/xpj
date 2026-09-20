"""Shared agreement and proposal views without either party's private ledger data."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitChangeProposal
from app.schemas._bill_split_change import (
    BillSplitAgreementResponse,
    BillSplitChangeProposalResponse,
    BillSplitSettlementPreviewResponse,
)
from app.services.bill_split_service._agreement_amounts import change_settlement_preview
from app.services.bill_split_service._agreement_context import (
    AgreementContext,
    agreement_amounts,
    agreement_context,
    latest_agreement_change,
    pending_repayment_debts,
)
from app.services.debt_service._query import get_participant_debt_response
from app.services.time_service import ensure_utc, now_utc


def change_proposal_response(
    context: AgreementContext, proposal: BillSplitChangeProposal, actor_account_id: int,
) -> BillSplitChangeProposalResponse:
    expired = proposal.status == "pending" and ensure_utc(proposal.expires_at) <= now_utc()
    return BillSplitChangeProposalResponse(public_id=proposal.public_id,
        original_debt_public_id=context.original.public_id,
        return_debt_public_id=context.returned.public_id if proposal.return_debt_id is not None else None,
        status="expired" if expired else proposal.status, proposed_by_you=proposal.proposed_by_account_id == actor_account_id,
        share_before_amount_cents=proposal.share_before_amount_cents, new_share_amount_cents=proposal.new_share_amount_cents,
        settlement_before_net_amount_cents=proposal.settlement_before_net_amount_cents,
        settlement_net_amount_cents=proposal.settlement_net_amount_cents,
        original_paid_amount_cents=proposal.original_paid_amount_cents, return_paid_amount_cents=proposal.return_paid_amount_cents,
        original_forgiven_amount_cents=proposal.original_forgiven_amount_cents,
        return_forgiven_amount_cents=proposal.return_forgiven_amount_cents,
        original_debt_row_version=proposal.original_debt_row_version, return_debt_row_version=proposal.return_debt_row_version,
        reason=proposal.reason, created_at=proposal.created_at, expires_at=proposal.expires_at, resolved_at=proposal.resolved_at)


def get_bill_split_change_proposal(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, proposal_public_id: str,
) -> BillSplitChangeProposalResponse:
    context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
    proposal = db.scalar(select(BillSplitChangeProposal).where(BillSplitChangeProposal.public_id == proposal_public_id,
        BillSplitChangeProposal.invitation_id == context.invitation.id))
    if proposal is None:
        raise AppError("split_change_not_found", status_code=404)
    return change_proposal_response(context, proposal, actor_account_id)


def get_bill_split_agreement(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, new_share_amount_cents: int | None = None,
) -> BillSplitAgreementResponse:
    context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
    amounts = agreement_amounts(db, context)
    latest = latest_agreement_change(db, context)
    share = latest.new_share_amount_cents if latest else context.invitation.amount_cents
    previous = db.get(BillSplitChangeProposal, latest.proposal_id) if latest else None
    custom = previous is not None and previous.settlement_net_amount_cents != (
        previous.new_share_amount_cents - previous.original_paid_amount_cents + previous.return_paid_amount_cents)
    new_share = share if new_share_amount_cents is None else new_share_amount_cents
    preview = change_settlement_preview(new_share_amount_cents=new_share, amounts=amounts,
        previous_custom_settlement=custom)
    pending = db.scalar(select(BillSplitChangeProposal).where(
        BillSplitChangeProposal.invitation_id == context.invitation.id, BillSplitChangeProposal.status == "pending",
        BillSplitChangeProposal.expires_at > now_utc()))
    original = get_participant_debt_response(db, public_id=context.original.public_id,
        ledger_id=tenant_id, account_id=actor_account_id)
    returned = get_participant_debt_response(db, public_id=context.returned.public_id,
        ledger_id=tenant_id, account_id=actor_account_id) if context.returned else None
    return BillSplitAgreementResponse(invitation_public_id=context.invitation.public_id,
        home_currency_code=original.home_currency_code, original_share_amount_cents=context.invitation.amount_cents,
        agreed_share_amount_cents=share, original_debt=original, return_debt=returned,
        viewer_is_party=actor_account_id in (context.invitation.sender_account_id, context.invitation.receiver_account_id),
        original_paid_amount_cents=amounts.original_paid, return_paid_amount_cents=amounts.return_paid,
        original_forgiven_amount_cents=amounts.original_forgiven, return_forgiven_amount_cents=amounts.return_forgiven,
        settlement_net_amount_cents=amounts.original_remaining - amounts.return_remaining,
        pending_repayment_debt_public_ids=pending_repayment_debts(db, context),
        pending_proposal=change_proposal_response(context, pending, actor_account_id) if pending else None,
        preview=BillSplitSettlementPreviewResponse(new_share_amount_cents=new_share,
            default_settlement_net_amount_cents=preview.default_settlement_net,
            cash_based_settlement_net_amount_cents=preview.cash_based_settlement_net,
            requires_explicit_settlement=preview.requires_explicit_settlement))
