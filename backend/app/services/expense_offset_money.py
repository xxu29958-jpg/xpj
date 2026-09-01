"""Money freeze for refund, chargeback, and full reversal facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_READY
from app.models import Expense, ExpenseOffsetFact
from app.schemas import ExpenseOffsetCorrectionRequest, ExpenseOffsetCreateRequest
from app.services.exchange_rate_service import calculate_cny_cents, resolve_payload_rate


@dataclass(frozen=True)
class OffsetMoney:
    original_amount_minor: int
    amount_cents: int
    exchange_rate_to_cny: Decimal | None
    exchange_rate_date: date | None
    exchange_rate_source: str | None


def gross_original_minor(expense: Expense) -> int:
    if expense.original_amount_minor is not None:
        return expense.original_amount_minor
    if expense.amount_cents is not None:
        return expense.amount_cents
    raise AppError("amount_required", status_code=409)


def resolve_offset_money(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    offsets: list[ExpenseOffsetFact],
    payload: ExpenseOffsetCreateRequest,
) -> OffsetMoney:
    gross_original = gross_original_minor(expense)
    active_refunded = sum(offset.original_amount_minor for offset in offsets if offset.kind != "reversal")
    if payload.kind == "reversal":
        if active_refunded:
            db.rollback()
            raise AppError("expense_refund_exists", status_code=409)
        return OffsetMoney(
            original_amount_minor=gross_original,
            amount_cents=int(expense.amount_cents or 0),
            exchange_rate_to_cny=expense.exchange_rate_to_cny,
            exchange_rate_date=expense.exchange_rate_date,
            exchange_rate_source=expense.exchange_rate_source,
        )

    original_amount_minor = int(payload.original_amount_minor or 0)
    if original_amount_minor > gross_original - active_refunded:
        db.rollback()
        raise AppError("expense_refund_exceeds_remaining", status_code=409)
    rate, source, status, effective_date = resolve_payload_rate(
        db,
        tenant_id=tenant_id,
        currency_code=expense.original_currency_code,
        rate_date=payload.accounting_date,
    )
    amount_cents = calculate_cny_cents(
        original_currency_code=expense.original_currency_code,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=rate,
    )
    if status != FX_STATUS_READY or rate is None or amount_cents is None or amount_cents <= 0:
        db.rollback()
        raise AppError("exchange_rate_required", status_code=409)
    return OffsetMoney(
        original_amount_minor=original_amount_minor,
        amount_cents=amount_cents,
        exchange_rate_to_cny=rate,
        exchange_rate_date=effective_date,
        exchange_rate_source=source,
    )


def resolve_corrected_offset_money(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    offset: ExpenseOffsetFact,
    active_offsets: list[ExpenseOffsetFact],
    payload: ExpenseOffsetCorrectionRequest,
) -> OffsetMoney:
    if offset.kind == "reversal":
        if payload.original_amount_minor is not None:
            raise AppError("expense_reversal_amount_server_owned", status_code=422)
        return OffsetMoney(
            original_amount_minor=offset.original_amount_minor,
            amount_cents=offset.amount_cents,
            exchange_rate_to_cny=offset.exchange_rate_to_cny,
            exchange_rate_date=offset.exchange_rate_date,
            exchange_rate_source=offset.exchange_rate_source,
        )

    if payload.original_amount_minor is None:
        raise AppError("amount_required", status_code=409)
    original_amount_minor = int(payload.original_amount_minor)
    other_refunded = sum(
        item.original_amount_minor
        for item in active_offsets
        if item.id != offset.id and item.kind != "reversal"
    )
    if original_amount_minor > gross_original_minor(expense) - other_refunded:
        raise AppError("expense_refund_exceeds_remaining", status_code=409)

    if payload.accounting_date == offset.accounting_date:
        rate = offset.exchange_rate_to_cny
        effective_date = offset.exchange_rate_date
        source = offset.exchange_rate_source
    else:
        rate, source, status, effective_date = resolve_payload_rate(
            db,
            tenant_id=tenant_id,
            currency_code=expense.original_currency_code,
            rate_date=payload.accounting_date,
        )
        if status != FX_STATUS_READY or rate is None:
            raise AppError("exchange_rate_required", status_code=409)

    amount_cents = calculate_cny_cents(
        original_currency_code=expense.original_currency_code,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=rate,
    )
    if amount_cents is None or amount_cents <= 0:
        raise AppError("exchange_rate_required", status_code=409)
    return OffsetMoney(
        original_amount_minor=original_amount_minor,
        amount_cents=amount_cents,
        exchange_rate_to_cny=rate,
        exchange_rate_date=effective_date,
        exchange_rate_source=source,
    )


__all__ = [
    "OffsetMoney",
    "gross_original_minor",
    "resolve_corrected_offset_money",
    "resolve_offset_money",
]
