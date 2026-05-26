"""Suspected-duplicate listing and manual override."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.services.duplicate_service import (
    ACTIVE_DUPLICATE_IGNORE_KINDS,
    _remember_duplicate_ignore,
    list_suspected_duplicates,
)
from app.services.expense_service._helpers import EDITABLE_STATUSES
from app.services.expense_service._query import get_expense
from app.services.time_service import ensure_utc, now_utc

__all__ = ["list_duplicate_expenses", "mark_expense_not_duplicate"]


def list_duplicate_expenses(db: Session, tenant_id: str) -> list[Expense]:
    return list_suspected_duplicates(db, tenant_id)


def mark_expense_not_duplicate(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_updated_at: datetime,
) -> Expense:
    """ADR-0038 PR-2b: claim-then-apply mark-not-duplicate.

    Atomic ``UPDATE WHERE id, tenant_id, status ∈ EDITABLE, updated_at =
    expected`` clears duplicate flags and bumps ``updated_at`` in one
    statement. The pre-claim read captures the row's ``duplicate_of_id``
    so we can record the "ignore" memory after the claim succeeds.
    Idempotent when already cleared (token still required to prevent
    stale clients from undoing a freshly-reapplied flag).
    """
    # Snapshot duplicate_of_id before clearing — _remember_duplicate_ignore
    # needs it. The atomic UPDATE rejects stale snapshots anyway, so a
    # value read here can't survive into the post-claim phase unless the
    # claim succeeded.
    pre_claim = db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
    )
    duplicate_of_id = pre_claim.duplicate_of_id if pre_claim is not None else None

    expected_predicate = ensure_utc(expected_updated_at).replace(tzinfo=None)
    now = now_utc()
    result = db.execute(
        update(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .where(Expense.status.in_(EDITABLE_STATUSES))
        .where(Expense.updated_at == expected_predicate)
        .values(
            duplicate_status="none",
            duplicate_of_id=None,
            duplicate_reason=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire_all()
        current = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)
        )
        if current is None or current.status not in EDITABLE_STATUSES:
            raise AppError("expense_not_found", status_code=404)
        raise AppError("state_conflict", status_code=409)

    if duplicate_of_id is not None:
        for kind in ACTIVE_DUPLICATE_IGNORE_KINDS:
            _remember_duplicate_ignore(db, tenant_id, expense_id, duplicate_of_id, kind)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    db.commit()
    db.refresh(expense)
    return expense
