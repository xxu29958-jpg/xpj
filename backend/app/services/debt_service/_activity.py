"""Bounded relationship history over existing facts and proposal resolutions.

The query projects retained records and locates a page. It is not an event
store or a balance fold; nested facts and proposals keep their response owners.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Select, Text, cast, func, literal, null, select, union_all
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Subquery

from app.errors import AppError
from app.models import (
    Account,
    BillSplitAgreementChange,
    BillSplitChangeProposal,
    BillSplitInvitation,
    Debt,
    DebtAdjustment,
    DebtForgiveness,
    DebtVoid,
    MemberRepaymentProposal,
    Repayment,
    RepaymentVoid,
)
from app.money_contract import projection_sum_to_int
from app.schemas import (
    DebtActivityListResponse,
    DebtActivityResponse,
    MemberRepaymentProposalResponse,
    RepaymentFactResponse,
)
from app.schemas._bill_split_change import BillSplitChangeProposalResponse
from app.services.debt_service._proposal_response import proposal_responses
from app.services.debt_service._query import resolve_debt_for_participant
from app.services.debt_service._repayment_activity import repayment_fact_response


def _index_select(
    model: type, kind: str, order: int, recorded_at: ColumnElement[datetime], actor_id: ColumnElement[int],
    *, amount: ColumnElement[int] | None = None, reason: ColumnElement[str] | None = None,
    repayment_id: ColumnElement[int] | None = None, proposal_id: ColumnElement[int] | None = None,
    split_proposal_id: ColumnElement[int] | None = None,
) -> Select:
    # SQL casts matter here: PostgreSQL resolves leading NULL-only UNION arms
    # as text before reaching later integer repayment/proposal references.
    return select(
        literal(kind).label("kind"), literal(order).label("kind_order"),
        model.id.label("row_id"), model.public_id.label("public_id"),
        recorded_at.label("recorded_at"), actor_id.label("actor_id"),
        (amount if amount is not None else cast(null(), BigInteger)).label("amount"),
        (reason if reason is not None else cast(null(), Text)).label("reason"),
        (repayment_id if repayment_id is not None else cast(null(), BigInteger)).label("repayment_id"),
        (proposal_id if proposal_id is not None else cast(null(), BigInteger)).label("proposal_id"),
        (split_proposal_id if split_proposal_id is not None else cast(null(), BigInteger)).label("split_proposal_id"),
    )


def _split_index(debt: Debt) -> list[Select]:
    if debt.source_type not in {"bill_split", "bill_split_return"}:
        return []
    proposal, change = BillSplitChangeProposal, BillSplitAgreementChange
    invitation_id = select(BillSplitInvitation.id).where(BillSplitInvitation.public_id == debt.source_id).scalar_subquery()
    return [
        _index_select(proposal, "split_change_proposed", 8, proposal.created_at, proposal.proposed_by_account_id,
                      reason=proposal.reason, split_proposal_id=proposal.id).where(proposal.invitation_id == invitation_id),
        _index_select(proposal, "split_change_resolved", 9, proposal.resolved_at, proposal.resolved_by_account_id,
                      reason=proposal.reason, split_proposal_id=proposal.id)
        .where(proposal.invitation_id == invitation_id, proposal.resolved_at.is_not(None), proposal.status != "accepted"),
        _index_select(change, "split_agreement_changed", 10, change.created_at, change.accepted_by_account_id,
                      reason=proposal.reason, split_proposal_id=change.proposal_id)
        .join(proposal, proposal.id == change.proposal_id).where(change.invitation_id == invitation_id),
    ]


def _activity_index(debt: Debt) -> Subquery:
    debt_id = debt.id
    proposal = MemberRepaymentProposal
    return union_all(
        _index_select(Debt, "created", 0, Debt.created_at, Debt.created_by_account_id,
                      amount=Debt.principal_amount_cents, reason=Debt.note).where(Debt.id == debt_id),
        _index_select(proposal, "proposal_created", 1, proposal.created_at, proposal.proposed_by_account_id,
                      proposal_id=proposal.id)
        .where(proposal.debt_id == debt_id),
        _index_select(DebtAdjustment, "adjustment", 2, DebtAdjustment.created_at, DebtAdjustment.actor_account_id,
                      amount=DebtAdjustment.amount_cents, reason=DebtAdjustment.reason)
        .where(DebtAdjustment.debt_id == debt_id),
        _index_select(Repayment, "repayment", 3, Repayment.created_at, Repayment.actor_account_id,
                      repayment_id=Repayment.id).where(Repayment.debt_id == debt_id),
        _index_select(RepaymentVoid, "repayment_void", 4, RepaymentVoid.created_at, RepaymentVoid.actor_account_id,
                      reason=RepaymentVoid.reason, repayment_id=RepaymentVoid.repayment_id)
        .join(Repayment, Repayment.id == RepaymentVoid.repayment_id).where(Repayment.debt_id == debt_id),
        _index_select(DebtForgiveness, "forgiveness", 5, DebtForgiveness.created_at, DebtForgiveness.actor_account_id,
                      amount=DebtForgiveness.amount_cents).where(DebtForgiveness.debt_id == debt_id),
        _index_select(DebtVoid, "debt_void", 6, DebtVoid.created_at, DebtVoid.actor_account_id,
                      reason=DebtVoid.reason).where(DebtVoid.debt_id == debt_id),
        _index_select(proposal, "proposal_resolved", 7, proposal.resolved_at, proposal.resolved_by_account_id,
                      proposal_id=proposal.id)
        .where(proposal.debt_id == debt_id, proposal.resolved_at.is_not(None)),
        *_split_index(debt),
    ).subquery()


def _activity_page(
    db: Session, index: Subquery, *, page: int, page_size: int, focus_repayment: str | None,
) -> list[Row]:
    # Locate and select in one statement. A concurrent new fact must not move
    # the focused repayment to another page between a rank query and a list query.
    ranked = select(
        index,
        func.row_number().over(order_by=(
            index.c.recorded_at.desc(), index.c.kind_order.desc(), index.c.row_id.desc(),
        )).label("position"),
        func.count().over().label("total"),
    ).cte("ranked_debt_activity")
    start = (page - 1) * page_size + 1
    if focus_repayment is not None:
        target = select(ranked.c.position).where(
            ranked.c.kind == "repayment", ranked.c.public_id == focus_repayment,
        ).scalar_subquery()
        start = target - ((target - 1) % page_size)
    events = db.execute(
        select(ranked, Account.display_name.label("actor_display_name"))
        .outerjoin(Account, Account.id == ranked.c.actor_id)
        .where(ranked.c.position >= start, ranked.c.position < start + page_size)
        .order_by(ranked.c.position),
    ).all()
    if focus_repayment is not None and not events:
        raise AppError("repayment_not_found", status_code=404)
    return events


def _repayments_for_events(db: Session, events: list[Row]) -> dict[int, RepaymentFactResponse]:
    ids = {event.repayment_id for event in events if event.repayment_id is not None}
    if not ids:
        return {}
    rows = db.execute(
        select(Repayment, RepaymentVoid)
        .outerjoin(RepaymentVoid, RepaymentVoid.repayment_id == Repayment.id)
        .where(Repayment.id.in_(ids)),
    ).all()
    return {repayment.id: repayment_fact_response(repayment, void) for repayment, void in rows}


def _proposals_for_events(db: Session, events: list[Row]) -> dict[int, MemberRepaymentProposalResponse]:
    ids = {event.proposal_id for event in events if event.proposal_id is not None}
    if not ids:
        return {}
    proposals = list(db.scalars(select(MemberRepaymentProposal).where(MemberRepaymentProposal.id.in_(ids))))
    return dict(zip((proposal.id for proposal in proposals), proposal_responses(db, proposals), strict=True))


def _response(
    event: Row, *, actor_account_id: int | None, repayments: dict[int, RepaymentFactResponse],
    proposals: dict[int, MemberRepaymentProposalResponse],
    split_proposals: dict[int, BillSplitChangeProposalResponse],
) -> DebtActivityResponse:
    return DebtActivityResponse(
        kind=event.kind, public_id=event.public_id, recorded_at=event.recorded_at,
        actor_display_name=event.actor_display_name,
        actor_is_you=actor_account_id is not None and event.actor_id == actor_account_id,
        amount_cents=(projection_sum_to_int(event.amount, label="debt_activity.amount") if event.amount is not None else None),
        reason=event.reason, repayment=repayments.get(event.repayment_id), proposal=proposals.get(event.proposal_id),
        split_change=split_proposals.get(event.split_proposal_id),
    )


def _split_proposals_for_events(
    db: Session, events: list[Row], *, tenant_id: str, actor_account_id: int, public_id: str,
) -> dict[int, BillSplitChangeProposalResponse]:
    from app.services.bill_split_service._agreement_context import agreement_context
    from app.services.bill_split_service._agreement_queries import change_proposal_response

    ids = {event.split_proposal_id for event in events if event.split_proposal_id is not None}
    if not ids:
        return {}
    context = agreement_context(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
    proposals = db.scalars(select(BillSplitChangeProposal).where(BillSplitChangeProposal.id.in_(ids)))
    return {proposal.id: change_proposal_response(context, proposal, actor_account_id) for proposal in proposals}


def list_debt_activity(
    db: Session, *, tenant_id: str, actor_account_id: int | None, public_id: str,
    page: int, page_size: int, focus_repayment: str | None = None,
) -> DebtActivityListResponse:
    debt, _ = resolve_debt_for_participant(
        db, public_id=public_id, ledger_id=tenant_id, account_id=actor_account_id,
    )
    index = _activity_index(debt)
    events = _activity_page(db, index, page=page, page_size=page_size, focus_repayment=focus_repayment)
    total = int(events[0].total) if events else int(db.scalar(select(func.count()).select_from(index)) or 0)
    if focus_repayment is not None:
        page = (int(events[0].position) - 1) // page_size + 1
    repayments = _repayments_for_events(db, events)
    proposals = _proposals_for_events(db, events)
    split_proposals = _split_proposals_for_events(db, events, tenant_id=tenant_id,
        actor_account_id=actor_account_id, public_id=public_id)
    return DebtActivityListResponse(
        debt_public_id=debt.public_id, home_currency_code=debt.home_currency_code,
        page=page, page_size=page_size, total=total,
        items=[_response(
            event, actor_account_id=actor_account_id,
            repayments=repayments, proposals=proposals, split_proposals=split_proposals,
        ) for event in events],
    )
