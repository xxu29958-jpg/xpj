"""ADR-0049 §3.3 DebtAdjustment: record one signed correction fact.

A ``DebtAdjustment`` is an append-only signed home-currency delta that raises or
lowers ``remaining`` (e.g. a fee, a forgiven portion, or the §2.2 foreign
close-out drift correction ``reason=fx_closeout``). Incorrect adjustments are
corrected by another adjustment, never by rewriting history (§3.3).

Slice 2 records owner-side direct adjustments for manual/external Debt only. An
adjustment that increases another member's burden or reduces a creditor's
receivable needs that party's confirmation (§5.2) — that adverse-interest member
adjustment proposal is slice 3 (§10: if exposed it must mirror §3.2's fields /
lifecycle / one-pending invariant). The :func:`_guards.guard_direct_fact_writable`
admission refuses bill-split-sourced Debt here.

The §2.1 parent-Debt serialization (FOR UPDATE + bump) and the
``remaining < 0`` rejection live in the
:func:`~app.services.debt_service._serialize.lock_and_fold` mutate callback.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, DebtAdjustment
from app.schemas import DebtAdjustmentCreateRequest
from app.services.debt_service._guards import guard_direct_fact_writable
from app.services.debt_service._serialize import lock_and_fold


def record_adjustment(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    actor_account_id: int,
    payload: DebtAdjustmentCreateRequest,
    idempotency_key: str,
    commit: bool = False,
) -> Debt:
    """Record one signed adjustment and return the fold-updated parent Debt.

    ``commit=False`` lets the route commit the DebtAdjustment insert + parent
    bump + [[0042]] idempotency-success record in one transaction.
    """
    reason = (payload.reason or "").strip()
    if not reason:
        raise AppError("debt_reason_required", status_code=422)
    amount_cents = int(payload.amount_cents)
    if amount_cents == 0:
        # A zero-delta adjustment changes nothing; reject as invalid rather than
        # writing a no-op fact.
        raise AppError("debt_amount_invalid", status_code=422)

    def _mutate(debt: Debt, remaining_before: int) -> None:
        guard_direct_fact_writable(debt)
        # §3.3: an adjustment MUST NOT make remaining < 0.
        if remaining_before + amount_cents < 0:
            raise AppError("debt_adjustment_negative_remaining", status_code=422)
        db.add(
            DebtAdjustment(
                debt_id=debt.id,
                amount_cents=amount_cents,
                reason=reason,
                actor_account_id=actor_account_id,
                idempotency_key=idempotency_key,
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
