"""One proposal response owner for commands, pending work and bounded history."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Debt, MemberRepaymentProposal, Repayment
from app.money_contract import projection_sum_to_int
from app.schemas import MemberRepaymentProposalResponse


def _public_ids(db: Session, model: type, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.execute(select(model.id, model.public_id).where(model.id.in_(ids))).all())


def proposal_responses(
    db: Session, proposals: Sequence[MemberRepaymentProposal],
) -> list[MemberRepaymentProposalResponse]:
    """Resolve public links in batches, without one query per history item."""
    debts = _public_ids(db, Debt, {proposal.debt_id for proposal in proposals})
    prior = _public_ids(db, MemberRepaymentProposal, {
        proposal.supersedes_proposal_id for proposal in proposals
        if proposal.supersedes_proposal_id is not None
    })
    repayments = _public_ids(db, Repayment, {
        proposal.committed_repayment_id for proposal in proposals
        if proposal.committed_repayment_id is not None
    })
    return [
        MemberRepaymentProposalResponse(
            public_id=proposal.public_id,
            debt_public_id=debts[proposal.debt_id],
            status=proposal.status,
            proposed_amount_cents=projection_sum_to_int(
                proposal.proposed_amount_cents, label="debt_proposal.response_proposed_amount",
            ),
            confirmed_amount_cents=(
                projection_sum_to_int(
                    proposal.confirmed_amount_cents, label="debt_proposal.response_confirmed_amount",
                )
                if proposal.confirmed_amount_cents is not None else None
            ),
            home_currency_code=proposal.home_currency_code,
            original_currency_code=proposal.original_currency_code,
            original_amount_minor=proposal.original_amount_minor,
            paid_at=proposal.paid_at,
            note=proposal.note,
            expires_at=proposal.expires_at,
            created_at=proposal.created_at,
            resolved_at=proposal.resolved_at,
            supersedes_proposal_public_id=prior.get(proposal.supersedes_proposal_id),
            committed_repayment_public_id=repayments.get(proposal.committed_repayment_id),
        )
        for proposal in proposals
    ]


def proposal_response(db: Session, proposal: MemberRepaymentProposal) -> MemberRepaymentProposalResponse:
    return proposal_responses(db, [proposal])[0]
