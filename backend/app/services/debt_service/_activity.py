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
from app.services.debt_service._proposal_response import proposal_responses
from app.services.debt_service._query import resolve_debt_for_participant
from app.services.debt_service._repayment_activity import repayment_fact_response


def _index_select(
    model: type, kind: str, order: int, recorded_at: ColumnElement[datetime], actor_id: ColumnElement[int],
    *, amount: ColumnElement[int] | None = None, reason: ColumnElement[str] | None = None,
    repayment_id: ColumnElement[int] | None = None, proposal_id: ColumnElement[int] | None = None,
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
    )


def _activity_index(debt_id: int) -> Subquery:
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
    event: Row, *, actor_account_id: int, repayments: dict[int, RepaymentFactResponse],
    proposals: dict[int, MemberRepaymentProposalResponse],
) -> DebtActivityResponse:
    return DebtActivityResponse(
        kind=event.kind, public_id=event.public_id, recorded_at=event.recorded_at,
        actor_display_name=event.actor_display_name, actor_is_you=event.actor_id == actor_account_id,
        amount_cents=(projection_sum_to_int(event.amount, label="debt_activity.amount") if event.amount is not None else None),
        reason=event.reason, repayment=repayments.get(event.repayment_id), proposal=proposals.get(event.proposal_id),
    )


def list_debt_activity(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str,
    page: int, page_size: int, focus_repayment: str | None = None,
) -> DebtActivityListResponse:
    debt, _ = resolve_debt_for_participant(
        db, public_id=public_id, ledger_id=tenant_id, account_id=actor_account_id,
    )
    index = _activity_index(debt.id)
    events = _activity_page(db, index, page=page, page_size=page_size, focus_repayment=focus_repayment)
    total = int(events[0].total) if events else int(db.scalar(select(func.count()).select_from(index)) or 0)
    if focus_repayment is not None:
        page = (int(events[0].position) - 1) // page_size + 1
    repayments = _repayments_for_events(db, events)
    proposals = _proposals_for_events(db, events)
    return DebtActivityListResponse(
        debt_public_id=debt.public_id, home_currency_code=debt.home_currency_code,
        page=page, page_size=page_size, total=total,
        items=[_response(
            event, actor_account_id=actor_account_id,
            repayments=repayments, proposals=proposals,
        ) for event in events],
    )
