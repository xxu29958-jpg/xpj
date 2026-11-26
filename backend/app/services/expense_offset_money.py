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
from app.services.exchange_rate_service import (
    ImportedCurrencyPayload,
    calculate_cny_cents,
    resolve_payload_rate,
    validate_imported_currency_snapshot,
)


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


def _missing_rate(expense: Expense, requested_date: date) -> AppError:
    return AppError("exchange_rate_pending", status_code=409, details={
        "currency_code": expense.original_currency_code,
        "home_currency_code": expense.home_currency_code,
        "rate_date": requested_date.isoformat(),
    })


def _validate_imported_offset_snapshot(snapshot: ImportedCurrencyPayload, expense: Expense) -> None:
    """Validate frozen file money and its currency relationship to the root."""
    validate_imported_currency_snapshot(snapshot)
    if (snapshot.home_currency_code != expense.home_currency_code
            or snapshot.original_currency_code != expense.original_currency_code):
        raise AppError("currency_snapshot_invalid", "文件与所选原单的币种不一致，请核对原单。", status_code=422)


def _validate_imported_offset_amount(
    snapshot: ImportedCurrencyPayload, expense: Expense, payload: ExpenseOffsetCreateRequest,
) -> None:
    """The file must represent the requested refund or the complete root reversal."""
    if payload.kind == "reversal":
        if any(getattr(snapshot, field) != getattr(expense, field)
               for field in ("original_amount_minor", "amount_cents", "exchange_rate_to_cny", "exchange_rate_date")):
            raise AppError("currency_snapshot_invalid", "冲正必须对应所选原单的完整金额与冻结汇率。", status_code=422)
    elif snapshot.original_amount_minor != int(payload.original_amount_minor or 0):
        raise AppError("currency_snapshot_invalid", "文件原币金额与本次复核金额不一致，请核对后继续。", status_code=422)


def _has_currency_drift(expense: Expense, offsets: list[ExpenseOffsetFact]) -> bool:
    return any(item.original_currency_code != expense.original_currency_code for item in offsets)


def _resolve_reversal_offset_money(
    db: Session,
    *,
    expense: Expense,
    gross_original: int,
    active_refunded: int,
    payload: ExpenseOffsetCreateRequest,
    imported_snapshot: ImportedCurrencyPayload | None,
) -> OffsetMoney:
    if active_refunded:
        db.rollback()
        raise AppError("expense_refund_exists", status_code=409)
    if imported_snapshot is not None:
        _validate_imported_offset_amount(imported_snapshot, expense, payload)
    return OffsetMoney(
        original_amount_minor=gross_original,
        amount_cents=int(expense.amount_cents or 0),
        exchange_rate_to_cny=expense.exchange_rate_to_cny,
        exchange_rate_date=expense.exchange_rate_date,
        exchange_rate_source=expense.exchange_rate_source,
    )


def _resolve_rate_for_offset(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    accounting_date: date,
    rollback_on_error: bool,
) -> tuple[Decimal, date, str]:
    rate, source, status, effective_date = resolve_payload_rate(
        db,
        tenant_id=tenant_id,
        home_currency_code=expense.home_currency_code,
        currency_code=expense.original_currency_code,
        rate_date=accounting_date,
    )
    if status != FX_STATUS_READY or rate is None:
        if rollback_on_error:
            db.rollback()
        raise _missing_rate(expense, accounting_date)
    return rate, effective_date, source


def _calculate_offset_amount_cents(
    db: Session,
    *,
    expense: Expense,
    original_amount_minor: int,
    rate: Decimal | None,
    rollback_on_error: bool,
) -> int:
    amount_cents = calculate_cny_cents(
        home_currency_code=expense.home_currency_code,
        original_currency_code=expense.original_currency_code,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=rate,
    )
    if amount_cents is None or amount_cents <= 0:
        if rollback_on_error:
            db.rollback()
        raise AppError("exchange_rate_required", status_code=409)
    return amount_cents


def resolve_offset_money(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    offsets: list[ExpenseOffsetFact],
    payload: ExpenseOffsetCreateRequest,
    imported_snapshot: ImportedCurrencyPayload | None = None,
) -> OffsetMoney:
    gross_original = gross_original_minor(expense)
    refunds = [offset for offset in offsets if offset.kind != "reversal"]
    active_refunded = sum(offset.original_amount_minor for offset in refunds)
    if imported_snapshot is not None:
        _validate_imported_offset_snapshot(imported_snapshot, expense)
    if payload.kind == "reversal":
        return _resolve_reversal_offset_money(
            db,
            expense=expense,
            gross_original=gross_original,
            active_refunded=active_refunded,
            payload=payload,
            imported_snapshot=imported_snapshot,
        )
    if _has_currency_drift(expense, refunds):
        db.rollback()
        raise AppError(
            "expense_refund_exists",
            "已有生效退款的币种与原消费不一致，请先将原消费币种核对一致后再登记退款。",
            status_code=409,
        )
    original_amount_minor = int(payload.original_amount_minor or 0)
    if original_amount_minor > gross_original - active_refunded:
        db.rollback()
        raise AppError("expense_refund_exceeds_remaining", status_code=409)
    if imported_snapshot is not None:
        _validate_imported_offset_amount(imported_snapshot, expense, payload)
        return OffsetMoney(
            original_amount_minor=original_amount_minor,
            amount_cents=imported_snapshot.amount_cents,
            exchange_rate_to_cny=imported_snapshot.exchange_rate_to_cny,
            exchange_rate_date=imported_snapshot.exchange_rate_date,
            exchange_rate_source="imported",
        )
    rate, effective_date, source = _resolve_rate_for_offset(
        db,
        tenant_id=tenant_id,
        expense=expense,
        accounting_date=payload.accounting_date,
        rollback_on_error=True,
    )
    amount_cents = _calculate_offset_amount_cents(
        db,
        expense=expense,
        original_amount_minor=original_amount_minor,
        rate=rate,
        rollback_on_error=True,
    )
    return OffsetMoney(
        original_amount_minor=original_amount_minor,
        amount_cents=amount_cents,
        exchange_rate_to_cny=rate,
        exchange_rate_date=effective_date,
        exchange_rate_source=source,
    )


def _resolve_corrected_reversal_money(
    offset: ExpenseOffsetFact,
    payload: ExpenseOffsetCorrectionRequest,
) -> OffsetMoney:
    if payload.original_amount_minor is not None:
        raise AppError("expense_reversal_amount_server_owned", status_code=422)
    return OffsetMoney(
        original_amount_minor=offset.original_amount_minor,
        amount_cents=offset.amount_cents,
        exchange_rate_to_cny=offset.exchange_rate_to_cny,
        exchange_rate_date=offset.exchange_rate_date,
        exchange_rate_source=offset.exchange_rate_source,
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
        return _resolve_corrected_reversal_money(offset, payload)
    if payload.original_amount_minor is None:
        raise AppError("amount_required", status_code=409)
    refunds = [item for item in active_offsets if item.kind != "reversal"]
    if _has_currency_drift(expense, [offset, *refunds]):
        raise AppError(
            "expense_refund_exists",
            "退款记录与原消费币种不一致，请先将原消费币种核对一致后再更正退款。",
            status_code=409,
        )
    original_amount_minor = int(payload.original_amount_minor)
    other_refunded = sum(item.original_amount_minor for item in refunds if item.id != offset.id)
    if original_amount_minor > gross_original_minor(expense) - other_refunded:
        raise AppError("expense_refund_exceeds_remaining", status_code=409)
    if payload.accounting_date == offset.accounting_date:
        rate, effective_date, source = (
            offset.exchange_rate_to_cny,
            offset.exchange_rate_date,
            offset.exchange_rate_source,
        )
    else:
        rate, effective_date, source = _resolve_rate_for_offset(
            db,
            tenant_id=tenant_id,
            expense=expense,
            accounting_date=payload.accounting_date,
            rollback_on_error=False,
        )
    amount_cents = _calculate_offset_amount_cents(
        db,
        expense=expense,
        original_amount_minor=original_amount_minor,
        rate=rate,
        rollback_on_error=False,
    )
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
