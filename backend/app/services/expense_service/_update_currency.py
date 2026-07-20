"""Currency-snapshot handling for expense updates.

``_apply_update_currency`` centralizes the two update modes: the normal
payload-driven FX application, and the preserve mode used when money was
edited but the frozen FX snapshot must be kept (recompute home from the
frozen rate instead of re-resolving).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseUpdateRequest
from app.services.exchange_rate_service import apply_currency_payload, calculate_cny_cents


def _apply_update_currency(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    payload: ExpenseUpdateRequest,
    updates: dict,
    preserve_currency_snapshot: bool,
) -> None:
    frozen_snapshot = (
        (
            expense.home_currency_code,
            expense.original_currency_code,
            expense.exchange_rate_to_cny,
            expense.exchange_rate_date,
            expense.exchange_rate_source,
            expense.fx_status,
        )
        if preserve_currency_snapshot
        else None
    )
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit="amount_cents" in updates,
    )
    if frozen_snapshot is None:
        return
    original_amount_minor = updates.get("original_amount_minor")
    if original_amount_minor is None:
        raise AppError("amount_invalid", status_code=422)
    (
        expense.home_currency_code,
        expense.original_currency_code,
        expense.exchange_rate_to_cny,
        expense.exchange_rate_date,
        expense.exchange_rate_source,
        expense.fx_status,
    ) = frozen_snapshot
    expense.original_amount_minor = original_amount_minor
    expense.amount_cents = calculate_cny_cents(
        original_currency_code=expense.original_currency_code,
        original_amount_minor=expense.original_amount_minor,
        exchange_rate_to_cny=expense.exchange_rate_to_cny,
    )
