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

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, Repayment
from app.schemas import RepaymentCreateRequest
from app.services.debt_service._guards import guard_direct_fact_writable
from app.services.debt_service._money import freeze_home_amount
from app.services.debt_service._serialize import lock_and_fold
from app.services.time_service import now_utc


def record_repayment(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int,
    payload: RepaymentCreateRequest,
    idempotency_key: str,
    commit: bool = False,
) -> Debt:
    """Record one committed repayment and return the fold-updated parent Debt.

    ``commit=False`` lets the route commit the Repayment insert + parent bump +
    [[0042]] idempotency-success record in one transaction.
    """
    paid_at = payload.paid_at or now_utc()
    money = freeze_home_amount(
        db,
        tenant_id=tenant_id,
        amount_cents=payload.amount_cents,
        original_currency=payload.original_currency,
        original_amount=payload.original_amount,
        event_time=paid_at,
        amount_error="debt_amount_invalid",
    )
    # The Repayment table has no home_currency_code column (that lives on the
    # parent Debt); drop it from the freeze result.
    money.pop("home_currency_code", None)
    amount_cents = money.pop("amount_cents")

    def _mutate(debt: Debt, remaining_before: int) -> None:
        # §5.2 / §3.5 adverse-interest guard: slice 2 only records committed
        # repayments directly for manual/external Debt (owner-side bookkeeping).
        # Member-Debt debtor "I paid" is a slice-3 proposal.
        guard_direct_fact_writable(debt)
        # §3.1 / F8: a repayment that would push remaining below 0 is rejected
        # inside the serialized section, never silently clamped.
        if amount_cents > remaining_before:
            raise AppError("debt_overpay_rejected", status_code=422)
        db.add(
            Repayment(
                debt_id=debt.id,
                amount_cents=amount_cents,
                paid_at=paid_at,
                actor_account_id=actor_account_id,
                proposal_id=None,
                idempotency_key=idempotency_key,
                **money,
            )
        )

    debt, _ = lock_and_fold(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        mutate=_mutate,
    )
    if commit:
        db.commit()
        db.refresh(debt)
    return debt
