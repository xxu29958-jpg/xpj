"""ADR-0049 §3.1 Repayment: record one committed repayment fact.

Records a *committed* repayment — the creditor's "I received payment" or an
external/owner-side direct entry — and reduces the derived ``remaining`` once
(§3.1 / F6). The debtor's "I paid" path for member Debt is a pending
``MemberRepaymentProposal`` (§3.2 / §5.2 / F5) and is slice 3; this service does
NOT accept ``proposal_id`` and only writes a directly-committable repayment.

Currency (§2.2): a foreign-currency repayment freezes its home ``amount_cents``
from the [[0027]] snapshot for ``paid_at`` (``exchange_rate_pending`` → 409),
sharing the §2.2 freeze with Debt creation via :mod:`_money`.

The §2.1 parent-Debt serialization (FOR UPDATE + bump) and the over-remaining
check (F8) live in the :func:`~app.services.debt_service._serialize.lock_and_fold`
mutate callback, so the overpay check runs from authoritative facts under the
lock.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, Repayment
from app.schemas import RepaymentCreateRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.debt_service._guards import guard_direct_fact_writable
from app.services.debt_service._money import (
    freeze_home_amount,
    validate_home_amount_command,
)
from app.services.debt_service._serialize import lock_and_fold
from app.services.time_service import now_utc


@dataclass
class RecordedRepayment:
    debt: Debt
    repayment_public_id: str


def get_repayment_public_id_for_idempotency(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    idempotency_key: str,
) -> str:
    """Return the committed repayment id for a successful replay."""
    repayment_public_id = db.scalar(
        select(Repayment.public_id)
        .join(Debt, Repayment.debt_id == Debt.id)
        .where(Debt.tenant_id == tenant_id)
        .where(Debt.public_id == public_id)
        .where(Repayment.idempotency_key == idempotency_key)
        .limit(1)
    )
    if repayment_public_id is None:
        raise AppError("repayment_not_found", status_code=404)
    return repayment_public_id


def record_repayment(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int,
    payload: RepaymentCreateRequest,
    idempotency_key: str,
    commit: bool = False,
) -> RecordedRepayment:
    """Record one committed repayment and return the fold-updated parent Debt.

    ``commit=False`` lets the route commit the Repayment insert + parent bump +
    [[0042]] idempotency-success record in one transaction.
    """
    validate_home_amount_command(
        amount_cents=payload.amount_cents,
        original_currency=payload.original_currency,
        original_amount=payload.original_amount,
    )
    resolve_write_capability(db)
    paid_at = payload.paid_at or now_utc()

    def _mutate(debt: Debt, remaining_before: int) -> Repayment:
        # §5.2 / §3.5 adverse-interest guard: slice 2 only records committed
        # repayments directly for external/manual Debt (owner-side bookkeeping).
        # Member-Debt repayment stays behind the slice-3 confirmation flow.
        guard_direct_fact_writable(debt)
        money = freeze_home_amount(
            db, tenant_id=tenant_id, home_currency_code=debt.home_currency_code,
            amount_cents=payload.amount_cents, original_currency=payload.original_currency,
            original_amount=payload.original_amount, event_time=paid_at, amount_error="debt_amount_invalid",
        )
        # Repayments inherit the currency of this locked parent.
        money.pop("home_currency_code")
        amount_cents = money.pop("amount_cents")
        # §3.1 / F8: a repayment that would push remaining below 0 is rejected
        # inside the serialized section, never silently clamped.
        if amount_cents > remaining_before:
            raise AppError("debt_overpay_rejected", status_code=422)
        repayment = Repayment(
            debt_id=debt.id,
            amount_cents=amount_cents,
            paid_at=paid_at,
            actor_account_id=actor_account_id,
            proposal_id=None,
            idempotency_key=idempotency_key,
            **money,
        )
        db.add(repayment)
        return repayment

    debt, repayment = lock_and_fold(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        mutate=_mutate,
    )
    if commit:
        db.commit()
        db.refresh(debt)
    return RecordedRepayment(debt=debt, repayment_public_id=repayment.public_id)
