"""Read-only repayment facts for one Debt.

This is a bounded read model over the canonical append-only ``Repayment`` and
``RepaymentVoid`` rows. It never reads ``Debt.status`` or a client cache to
decide whether a repayment is effective: the presence of the unique
``RepaymentVoid`` fact is the only void signal (ADR-0049 §3.4, ADR-0060 C01).

Visibility reuses the existing ADR-0049 §5.2 participant resolver:

- an active member of the Debt's ledger may read it (including ``viewer``);
- the member counterparty may read it from another ledger, with no ledger id in
  this response;
- every other cross-ledger request receives the same existence-hiding 404 as a
  missing Debt.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Repayment, RepaymentVoid
from app.schemas import (
    RepaymentFactListResponse,
    RepaymentFactResponse,
    RepaymentVoidFactResponse,
)
from app.services.debt_service._query import resolve_debt_for_participant


def list_repayment_facts(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    page: int,
    page_size: int,
) -> RepaymentFactListResponse:
    """Return newest-first repayment facts for one authorized Debt.

    Pagination is deliberately bounded by the route schema. The stable
    ``created_at DESC, id DESC`` order prevents equal-timestamp facts from
    moving between pages.
    """
    debt, _ = resolve_debt_for_participant(
        db,
        public_id=public_id,
        ledger_id=tenant_id,
        account_id=actor_account_id,
    )
    total = int(
        db.scalar(
            select(func.count(Repayment.id)).where(Repayment.debt_id == debt.id)
        )
        or 0
    )
    rows = db.execute(
        select(Repayment, RepaymentVoid)
        .outerjoin(
            RepaymentVoid,
            RepaymentVoid.repayment_id == Repayment.id,
        )
        .where(Repayment.debt_id == debt.id)
        .order_by(Repayment.created_at.desc(), Repayment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items: list[RepaymentFactResponse] = []
    for repayment, repayment_void in rows:
        void_fact = (
            RepaymentVoidFactResponse(
                public_id=repayment_void.public_id,
                reason=repayment_void.reason,
                created_at=repayment_void.created_at,
            )
            if repayment_void is not None
            else None
        )
        items.append(
            RepaymentFactResponse(
                public_id=repayment.public_id,
                amount_cents=int(repayment.amount_cents),
                original_currency_code=repayment.original_currency_code,
                original_amount_minor=repayment.original_amount_minor,
                exchange_rate_to_cny=repayment.exchange_rate_to_cny,
                exchange_rate_date=repayment.exchange_rate_date,
                exchange_rate_source=repayment.exchange_rate_source,
                paid_at=repayment.paid_at,
                created_at=repayment.created_at,
                status="voided" if void_fact is not None else "active",
                void_fact=void_fact,
            )
        )

    return RepaymentFactListResponse(
        debt_public_id=debt.public_id,
        home_currency_code=debt.home_currency_code,
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )
