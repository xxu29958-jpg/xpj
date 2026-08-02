"""Authoritative currency-snapshot handling for expense updates.

An already-resolved expense owns a frozen accounting snapshot.  Metadata and
same-currency amount corrections must not make that snapshot drift to a newer
mutable rate.  A genuinely changed transaction time or currency is an explicit
fact correction that starts a new backend-authoritative snapshot.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_READY
from app.models import Expense
from app.schemas import ExpenseUpdateRequest
from app.services.currency_binding_service import assert_currency_binding_consistent
from app.services.currency_common import normalize_currency_code
from app.services.exchange_rate_service import (
    amount_major_to_minor,
    apply_currency_payload,
    calculate_cny_cents,
)

_ORIGINAL_AMOUNT_FIELDS = {"original_amount", "original_amount_minor"}
_ORIGINAL_CURRENCY_FIELDS = {"original_currency", "original_currency_code"}
_CURRENCY_RELEVANT_FIELDS = _ORIGINAL_AMOUNT_FIELDS | _ORIGINAL_CURRENCY_FIELDS | {
    "amount_cents",
    "spent_at",
    "expense_time",
}


def _current_currency(expense: Expense) -> str:
    return normalize_currency_code(
        expense.original_currency_code or expense.home_currency_code
    )


def _submitted_currency(expense: Expense, updates: dict) -> str:
    submitted = updates.get("original_currency") or updates.get(
        "original_currency_code"
    )
    return normalize_currency_code(submitted or _current_currency(expense))


def _has_frozen_snapshot(expense: Expense) -> bool:
    return (
        expense.fx_status == FX_STATUS_READY
        and expense.exchange_rate_to_cny is not None
        and bool(expense.original_currency_code)
        and bool(expense.home_currency_code)
    )


def _submitted_original_amount(
    payload: ExpenseUpdateRequest,
    updates: dict,
    *,
    currency_code: str,
) -> int | None:
    if "original_amount_minor" in updates:
        return updates["original_amount_minor"]
    if "original_amount" in updates:
        return amount_major_to_minor(payload.original_amount, currency_code)
    return None


def _apply_frozen_snapshot_update(
    db: Session,
    *,
    expense: Expense,
    payload: ExpenseUpdateRequest,
    updates: dict,
) -> None:
    """Apply a same-currency correction without consulting mutable FX rows."""

    current_currency = _current_currency(expense)
    submitted_currency = _submitted_currency(expense, updates)
    if submitted_currency != current_currency:
        raise AppError("currency_snapshot_immutable", status_code=422)

    has_original_amount = bool(_ORIGINAL_AMOUNT_FIELDS & updates.keys())
    has_legacy_home_amount = "amount_cents" in updates
    if not has_original_amount and not has_legacy_home_amount:
        # Metadata edits are not a request to re-price an already-resolved
        # accounting snapshot.  Time corrections are routed around this helper.
        return

    if has_original_amount:
        original_amount_minor = _submitted_original_amount(
            payload,
            updates,
            currency_code=current_currency,
        )
        if original_amount_minor is None:
            return
    else:
        if current_currency != expense.home_currency_code:
            # A legacy home-only client cannot safely reinterpret a foreign
            # expense as home currency.  It must refetch and send original facts.
            raise AppError("currency_snapshot_immutable", status_code=422)
        original_amount_minor = updates.get("amount_cents")

    assert_currency_binding_consistent(db, expense.home_currency_code)
    expense.original_amount_minor = original_amount_minor
    expense.amount_cents = calculate_cny_cents(
        original_currency_code=current_currency,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=expense.exchange_rate_to_cny,
    )


def _apply_update_currency(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    payload: ExpenseUpdateRequest,
    updates: dict,
) -> None:
    if not (_CURRENCY_RELEVANT_FIELDS & updates.keys()):
        return
    if _has_frozen_snapshot(expense):
        current_currency = _current_currency(expense)
        time_changed = bool({"spent_at", "expense_time"} & updates.keys())
        if (
            _submitted_currency(expense, updates) == current_currency
            and not time_changed
        ):
            _apply_frozen_snapshot_update(
                db,
                expense=expense,
                payload=payload,
                updates=updates,
            )
            return
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit="amount_cents" in updates,
    )
