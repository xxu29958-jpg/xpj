"""ADR-0049 §3.4 / §3.5 void facts: undo a repayment, or void an entire Debt.

Both are append-only corrections that never delete or rewrite history:

- :func:`void_repayment` (§3.4) inserts a ``RepaymentVoid`` that excludes the
  original repayment from the fold (the repayment row stays). A repayment may be
  voided at most once (``uq_repayment_voids_repayment`` backs the pre-check). If
  the resulting ``remaining > 0`` the Debt reopens — ``derive_status`` does that
  latch from the recomputed fold.
- :func:`void_debt` (§3.5) inserts a ``DebtVoid`` and latches the Debt to
  ``voided`` (``uq_debt_voids_debt`` backs the pre-check). A voided Debt no
  longer contributes to open totals/goals but stays visible in audit/history.

Slice 2 opens direct voids for manual/external Debt only; bill-split-sourced
Debt voiding needs the same adverse-interest confirmation as member adjustment
(§3.5 / §5.2) and is deferred to slice 3/4 — :func:`_guards.guard_direct_fact_writable`
refuses it here. The §2.1 parent-Debt serialization (FOR UPDATE + bump) lives in
:func:`~app.services.debt_service._serialize.lock_and_fold`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, DebtVoid, Repayment, RepaymentVoid
from app.schemas import DebtVoidCreateRequest, RepaymentVoidCreateRequest
from app.services.debt_service._guards import guard_direct_fact_writable
from app.services.debt_service._serialize import lock_and_fold


def void_repayment(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: RepaymentVoidCreateRequest,
    actor_account_id: int,
    idempotency_key: str,
    commit: bool = False,
) -> Debt:
    """Void one repayment on the Debt and return the fold-updated parent.

    The parent Debt is the §2.1 serialization anchor (``public_id``); the target
    repayment is identified by ``repayment_public_id`` in the body. The original
    repayment row is never deleted — the fold excludes it via NOT EXISTS.
    """
    reason = (payload.reason or "").strip()
    if not reason:
        raise AppError("debt_reason_required", status_code=422)
    repayment_public_id = payload.repayment_public_id

    def _mutate(debt: Debt, remaining_before: int) -> None:
        guard_direct_fact_writable(debt)
        # The repayment must belong to THIS Debt (locked above); otherwise hide
        # existence as not-found.
        repayment = db.scalar(
            select(Repayment)
            .where(Repayment.public_id == repayment_public_id)
            .where(Repayment.debt_id == debt.id)
            .limit(1)
        )
        if repayment is None:
            raise AppError("repayment_not_found", status_code=404)
        # One repayment may be voided at most once. The pre-check gives a precise
        # 409; ``uq_repayment_voids_repayment`` is the concurrency backstop (a
        # racing duplicate would IntegrityError, but the parent row lock already
        # serializes voids on this Debt).
        already_voided = db.scalar(
            select(RepaymentVoid.id)
            .where(RepaymentVoid.repayment_id == repayment.id)
            .limit(1)
        )
        if already_voided is not None:
            raise AppError("repayment_already_voided", status_code=409)
        db.add(
            RepaymentVoid(
                repayment_id=repayment.id,
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


def void_debt(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtVoidCreateRequest,
    actor_account_id: int,
    idempotency_key: str,
    commit: bool = False,
) -> Debt:
    """Void an entire Debt and return the (now ``voided``) parent.

    The ``DebtVoid`` insert latches ``status='voided'``; ``derive_status`` keeps
    it voided regardless of the fold. ``uq_debt_voids_debt`` is the backstop, but
    the parent row lock plus the ``status == 'voided'`` guard in
    :func:`lock_and_fold` already prevent a double void.
    """
    reason = (payload.reason or "").strip()
    if not reason:
        raise AppError("debt_reason_required", status_code=422)

    def _mutate(debt: Debt, remaining_before: int) -> None:
        guard_direct_fact_writable(debt)
        db.add(
            DebtVoid(
                debt_id=debt.id,
                reason=reason,
                actor_account_id=actor_account_id,
                idempotency_key=idempotency_key,
            )
        )
        # §3.5: latch the lifecycle to voided; derive_status keeps it there.
        debt.status = "voided"

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
