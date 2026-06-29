"""Bridge a confirmed Expense into the repayment-draft review flow.

This is deliberately a user-triggered bridge, not repayment auto-detection:
an already-confirmed ledger row remains an Expense until the user says "treat
this as a repayment". The bridge then creates a pending RepaymentDraft so the
existing repayment inbox, suggestion matcher, and learning fallback can do the
rest.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, RepaymentDraft
from app.services.expense_service._query import get_expense
from app.services.time_service import ensure_utc, now_utc

__all__ = ["create_repayment_draft_from_expense"]


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _expense_repayment_label(expense: Expense) -> str | None:
    """Return a generic label from the Expense, without platform keyword rules."""
    for value, is_category in (
        (expense.merchant, False),
        (expense.category, True),
        (expense.note, False),
    ):
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            continue
        if is_category and cleaned.casefold() in {"其他", "其它", "other"}:
            continue
        return cleaned[:255]
    return None


def _expense_repayment_draft_key(
    *, tenant_id: str, actor_account_id: int, expense_public_id: str
) -> str:
    material = "|".join(
        [
            "repayment_expense",
            tenant_id,
            str(actor_account_id),
            expense_public_id,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_repayment_draft_from_expense(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    expense_id: int,
    expected_row_version: int,
    commit: bool = True,
) -> RepaymentDraft:
    """Create or return the pending repayment draft for a confirmed Expense.

    The source Expense is not mutated. ``expected_row_version`` fences the user's
    intent against an amount/merchant/category snapshot that has changed since
    the edit page loaded. The resulting draft is account-scoped through its
    stable idempotency key, so repeated taps on the same Expense do not create
    twins but another member may still make their own review draft if needed.
    """
    expense = get_expense(db, expense_id, tenant_id)
    if expense.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)
    if expense.status != "confirmed":
        raise AppError("state_conflict", status_code=409)
    if expense.amount_cents is None or expense.amount_cents <= 0:
        raise AppError("amount_required", status_code=400)

    idempotency_key = _expense_repayment_draft_key(
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
        expense_public_id=expense.public_id,
    )
    existing = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id)
        .where(RepaymentDraft.created_by_account_id == actor_account_id)
        .where(RepaymentDraft.draft_idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing

    now = now_utc()
    captured_at = ensure_utc(expense.expense_time or expense.confirmed_at or expense.created_at)
    draft = RepaymentDraft(
        tenant_id=tenant_id,
        created_by_account_id=actor_account_id,
        source="other",
        amount_cents=expense.amount_cents,
        home_currency_code=expense.home_currency_code,
        merchant_label=_expense_repayment_label(expense),
        captured_at=captured_at,
        draft_idempotency_key=idempotency_key,
        status="pending",
        created_at=now,
    )
    db.add(draft)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            ledger_scoped_select(RepaymentDraft, tenant_id)
            .where(RepaymentDraft.created_by_account_id == actor_account_id)
            .where(RepaymentDraft.draft_idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        raise

    if commit:
        db.commit()
        db.refresh(draft)
    return draft
