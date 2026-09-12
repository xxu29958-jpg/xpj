"""Resolve one original pending conversion, then publish a separately reviewable revision."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_SOURCE_ECB, FX_STATUS_READY
from app.models import Expense
from app.services.currency_binding_service import resolve_write_capability
from app.services.duplicate_service import mark_duplicate_status
from app.services.exchange_rate_service import apply_resolved_currency_rate, resolve_payload_rate
from app.services.expense_query import resolve_expense
from app.services.fx_rate_provider import (
    EcbDailyRates,
    cache_reference_rates_for_date,
    cross_rate_to_home,
    fetch_reference_rates,
    fetch_reference_rates_for_date,
)
from app.services.optimistic_concurrency import bump_row_version
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc


class PendingFxInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expense_id: int = Field(gt=0, strict=True)
    tenant_id: str
    expected_row_version: int = Field(gt=0, strict=True)
    home_currency_code: str
    original_currency_code: str
    original_amount_minor: int = Field(ge=0, strict=True)
    rate_date: date

    @classmethod
    def from_expense(cls, expense: Expense) -> "PendingFxInput | None":
        if (expense.status != "pending" or expense.fx_status != "pending"
                or expense.original_amount_minor is None or expense.exchange_rate_date is None
                or expense.home_currency_code == expense.original_currency_code):
            return None
        return cls(expense_id=expense.id, tenant_id=expense.tenant_id,
            expected_row_version=expense.row_version, home_currency_code=expense.home_currency_code,
            original_currency_code=expense.original_currency_code,
            original_amount_minor=expense.original_amount_minor, rate_date=expense.exchange_rate_date)


@dataclass(frozen=True)
class PendingFxResult:
    expense_id: int
    outcome: Literal["updated", "no_result", "not_pending", "conflict"]
    row_version: int | None


def check_pending_fx(
    db: Session, original: PendingFxInput, *, for_update: bool = False,
) -> Expense | PendingFxResult:
    expense = resolve_expense(db, original.tenant_id, original.expense_id, for_update=for_update)
    if for_update and expense is not None:
        db.refresh(expense)
    if expense is None or expense.status != "pending":
        return PendingFxResult(original.expense_id, "not_pending", expense.row_version if expense else None)
    if expense.row_version != original.expected_row_version:
        return PendingFxResult(expense.id, "conflict", expense.row_version)
    if expense.fx_status == "ready":
        return PendingFxResult(expense.id, "no_result", expense.row_version)
    if PendingFxInput.from_expense(expense) != original:
        return PendingFxResult(expense.id, "conflict", expense.row_version)
    return expense


def fetch_pending_fx_reference(original: PendingFxInput) -> EcbDailyRates:
    """Network-only stage; today's local date may be ahead of the provider's UTC day."""
    now = now_utc()
    if original.rate_date > now.astimezone(accounting_zone()).date():
        raise AppError("fx_date_not_available", "这笔账单日期尚未到来，请核对日期或填写本笔汇率。", status_code=409)
    if original.rate_date >= now.date():
        return fetch_reference_rates()
    return fetch_reference_rates_for_date(original.rate_date)


def apply_pending_fx(
    db: Session, original: PendingFxInput, daily: EcbDailyRates | None,
) -> PendingFxResult:
    """Caller commits the pending revision and its task result together."""
    current = check_pending_fx(db, original, for_update=True)
    if isinstance(current, PendingFxResult):
        return current
    resolve_write_capability(db)
    if daily is not None:
        cache_reference_rates_for_date(db, daily, requested_date=original.rate_date,
            home_currency_code=original.home_currency_code, currencies={original.original_currency_code})
        db.flush()
    rate, source, status, published = resolve_payload_rate(db, tenant_id=original.tenant_id,
        currency_code=original.original_currency_code, home_currency_code=original.home_currency_code,
        rate_date=original.rate_date)
    if rate is None and daily is not None and original.rate_date >= now_utc().date():
        # The fresh response proves this observation, without turning an unfinished
        # provider day into permanent historical cache coverage.
        rate = cross_rate_to_home(daily.rates_per_eur, currency_code=original.original_currency_code,
            home_currency_code=original.home_currency_code)
        source, status, published = FX_SOURCE_ECB, FX_STATUS_READY, daily.rate_date
    if rate is None:
        raise AppError("exchange_rate_pending", "仍未取得这笔账单日期的汇率，可重试或填写本笔汇率。", status_code=409)
    apply_resolved_currency_rate(current, rate=rate, source=source, fx_status=status, rate_date=published)
    mark_duplicate_status(db, current)
    bump_row_version(current)
    current.updated_at = now_utc()
    return PendingFxResult(current.id, "updated", current.row_version)
