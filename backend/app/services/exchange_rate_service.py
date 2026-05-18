from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.fx_constants import (
    DEFAULT_HOME_CURRENCY_CODE,
    DEFAULT_SUPPORTED_CURRENCY_CODES,
    FX_SOURCE_BASE,
    FX_SOURCE_MANUAL,
    FX_STATUS_PENDING,
    FX_STATUS_READY,
    NO_FRACTION_CURRENCY_CODES,
)
from app.ledger_scope import ledger_scoped_select
from app.models import ExchangeRate, Expense
from app.services.spending_contract_service import fx_rate_date_for_expense_time
from app.services.time_service import now_utc


BASE_CURRENCY_CODE = DEFAULT_HOME_CURRENCY_CODE
HOME_CURRENCY_CODE = DEFAULT_HOME_CURRENCY_CODE
SUPPORTED_CURRENCY_CODES = set(DEFAULT_SUPPORTED_CURRENCY_CODES)
RATE_QUANT = Decimal("0.00000001")


class CurrencyPayload(Protocol):
    amount_cents: int | None
    original_currency: str | None
    original_amount: Decimal | None
    spent_at: datetime | None
    original_currency_code: str | None
    original_amount_minor: int | None
    exchange_rate_to_cny: Decimal | None
    exchange_rate_date: date | None
    exchange_rate_source: str | None


def _clean_currency_code(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if not code:
        return None
    if len(code) != 3 or not code.isalpha():
        return None
    return code


def home_currency_code() -> str:
    return _clean_currency_code(get_settings().fx_home_currency_code) or DEFAULT_HOME_CURRENCY_CODE


def supported_currency_codes() -> set[str]:
    configured = {
        code
        for part in get_settings().fx_supported_currency_codes.split(",")
        if (code := _clean_currency_code(part)) is not None
    }
    if not configured:
        configured = set(DEFAULT_SUPPORTED_CURRENCY_CODES)
    configured.add(home_currency_code())
    return configured


def normalize_currency_code(value: str | None) -> str:
    code = _clean_currency_code(value) or home_currency_code()
    if code not in supported_currency_codes():
        raise AppError("currency_not_supported", status_code=422)
    return code


def minor_units_for_currency(currency_code: str) -> int:
    return 0 if normalize_currency_code(currency_code) in NO_FRACTION_CURRENCY_CODES else 2


def amount_major_to_minor(value: Decimal | None, currency_code: str) -> int | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AppError("amount_invalid", status_code=422) from exc
    if amount < 0:
        raise AppError("amount_invalid", status_code=422)
    units = minor_units_for_currency(currency_code)
    quant = Decimal("1") if units == 0 else Decimal("0.01")
    rounded = amount.quantize(quant, rounding=ROUND_HALF_UP)
    multiplier = Decimal(1) if units == 0 else Decimal(100)
    return int((rounded * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_decimal_rate(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        rate = Decimal(str(value)).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise AppError("exchange_rate_invalid", status_code=422) from exc
    if rate <= 0:
        raise AppError("exchange_rate_invalid", status_code=422)
    return rate


def calculate_cny_cents(
    *,
    original_currency_code: str,
    original_amount_minor: int | None,
    exchange_rate_to_cny: Decimal | None,
) -> int | None:
    """Convert original currency minor units → home currency minor units.

    The legacy name says "cny_cents" but the result is always expressed in the
    configured home currency's minor units. If `FX_HOME_CURRENCY_CODE` is a
    no-fraction currency (JPY/KRW), the multiplier collapses to 1 so that 1,000
    JPY persists as `amount_cents=1000` rather than 100,000.
    """
    if original_amount_minor is None:
        return None
    if original_amount_minor < 0:
        raise AppError("amount_invalid", status_code=422)
    currency_code = normalize_currency_code(original_currency_code)
    rate = Decimal("1") if currency_code == home_currency_code() else format_decimal_rate(exchange_rate_to_cny)
    if rate is None:
        return None
    divisor = Decimal(1) if minor_units_for_currency(currency_code) == 0 else Decimal(100)
    amount_major = Decimal(original_amount_minor) / divisor
    home_units = minor_units_for_currency(home_currency_code())
    home_multiplier = Decimal(1) if home_units == 0 else Decimal(100)
    return int((amount_major * rate * home_multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def default_rate_date(expense_time: datetime | None = None) -> date:
    return fx_rate_date_for_expense_time(expense_time)


def _payload_rate_date(payload: CurrencyPayload, expense_time: datetime | None) -> date:
    payload_time = _payload_attr(payload, "spent_at") or _payload_attr(payload, "expense_time")
    return default_rate_date(payload_time or expense_time)


def get_exchange_rate(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str,
    rate_date: date,
) -> ExchangeRate | None:
    code = normalize_currency_code(currency_code)
    if code == home_currency_code():
        return None
    return db.scalar(
        ledger_scoped_select(ExchangeRate, tenant_id)
        .where(ExchangeRate.currency_code == code)
        .where(ExchangeRate.rate_date == rate_date)
    )


def list_exchange_rates(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str | None = None,
    limit: int = 90,
) -> list[ExchangeRate]:
    query = ledger_scoped_select(ExchangeRate, tenant_id)
    if currency_code:
        query = query.where(ExchangeRate.currency_code == normalize_currency_code(currency_code))
    return list(
        db.scalars(
            query.order_by(ExchangeRate.rate_date.desc(), ExchangeRate.currency_code.asc()).limit(min(max(limit, 1), 365))
        )
    )


def upsert_exchange_rate(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str,
    rate_date: date,
    rate_to_cny: Decimal,
    source: str | None = None,
) -> ExchangeRate:
    code = normalize_currency_code(currency_code)
    if code == home_currency_code():
        raise AppError("exchange_rate_base_currency", status_code=422)
    rate = format_decimal_rate(rate_to_cny)
    assert rate is not None
    clean_source = (source or FX_SOURCE_MANUAL).strip()[:32] or FX_SOURCE_MANUAL
    existing = get_exchange_rate(db, tenant_id=tenant_id, currency_code=code, rate_date=rate_date)
    now = now_utc()
    if existing is None:
        existing = ExchangeRate(
            tenant_id=tenant_id,
            currency_code=code,
            rate_date=rate_date,
            rate_to_cny=rate,
            source=clean_source,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
    else:
        existing.rate_to_cny = rate
        existing.source = clean_source
        existing.updated_at = now
    db.commit()
    db.refresh(existing)
    return existing


def resolve_payload_rate(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str,
    rate_date: date,
) -> tuple[Decimal | None, str | None, str]:
    code = normalize_currency_code(currency_code)
    home = home_currency_code()
    if code == home:
        return Decimal("1"), FX_SOURCE_BASE, FX_STATUS_READY
    stored = get_exchange_rate(db, tenant_id=tenant_id, currency_code=code, rate_date=rate_date)
    if stored is not None:
        return Decimal(stored.rate_to_cny), stored.source, FX_STATUS_READY
    from app.services.fx_rate_provider import get_fx_rate

    global_rate = get_fx_rate(
        db,
        currency_code=code,
        rate_date=rate_date,
        home_currency_code=home,
    )
    if global_rate is not None:
        return Decimal(global_rate.rate_to_home), global_rate.source, FX_STATUS_READY
    return None, None, FX_STATUS_PENDING


def _payload_attr(payload: CurrencyPayload, name: str):
    return getattr(payload, name, None)


def _payload_original_currency(payload: CurrencyPayload, expense: Expense) -> str:
    return normalize_currency_code(
        _payload_attr(payload, "original_currency")
        or _payload_attr(payload, "original_currency_code")
        or expense.original_currency_code
        or home_currency_code()
    )


def _payload_original_amount_minor(
    payload: CurrencyPayload,
    *,
    currency_code: str,
    amount_was_explicit: bool,
) -> int | None:
    original_amount = amount_major_to_minor(_payload_attr(payload, "original_amount"), currency_code)
    if original_amount is not None:
        return original_amount
    original_amount_minor = _payload_attr(payload, "original_amount_minor")
    if original_amount_minor is not None:
        return int(original_amount_minor)
    amount_cents = _payload_attr(payload, "amount_cents")
    if amount_was_explicit and amount_cents is not None and currency_code == home_currency_code():
        return int(amount_cents)
    return None


def apply_currency_payload(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    payload: CurrencyPayload,
    amount_was_explicit: bool,
) -> None:
    has_original_fields = any(
        value is not None
        for value in (
            _payload_attr(payload, "original_currency"),
            _payload_attr(payload, "original_amount"),
            _payload_attr(payload, "spent_at"),
            _payload_attr(payload, "expense_time"),
            _payload_attr(payload, "original_currency_code"),
            _payload_attr(payload, "original_amount_minor"),
            _payload_attr(payload, "exchange_rate_to_cny"),
            _payload_attr(payload, "exchange_rate_date"),
        )
    )
    home = home_currency_code()
    if not has_original_fields:
        amount_cents = _payload_attr(payload, "amount_cents")
        if amount_was_explicit:
            expense.amount_cents = amount_cents
            expense.home_currency_code = home
            expense.original_currency_code = home
            expense.original_amount_minor = amount_cents
            expense.exchange_rate_to_cny = Decimal("1") if amount_cents is not None else None
            expense.exchange_rate_date = default_rate_date(expense.expense_time) if amount_cents is not None else None
            expense.exchange_rate_source = FX_SOURCE_BASE if amount_cents is not None else None
            expense.fx_status = FX_STATUS_READY
        return

    code = _payload_original_currency(payload, expense)
    original_amount = _payload_original_amount_minor(
        payload,
        currency_code=code,
        amount_was_explicit=amount_was_explicit,
    )
    if original_amount is None:
        original_amount = expense.original_amount_minor
    explicit_rate_date = _payload_attr(payload, "exchange_rate_date")
    time_changed = _payload_attr(payload, "spent_at") is not None or _payload_attr(payload, "expense_time") is not None
    rate_date = (
        explicit_rate_date
        or (_payload_rate_date(payload, expense.expense_time) if time_changed else None)
        or expense.exchange_rate_date
        or _payload_rate_date(payload, expense.expense_time)
    )
    explicit_rate = format_decimal_rate(_payload_attr(payload, "exchange_rate_to_cny"))
    if code == home:
        rate, source, fx_status = Decimal("1"), FX_SOURCE_BASE, FX_STATUS_READY
    elif explicit_rate is not None:
        rate = explicit_rate
        source = (_payload_attr(payload, "exchange_rate_source") or FX_SOURCE_MANUAL).strip()[:32] or FX_SOURCE_MANUAL
        fx_status = FX_STATUS_READY
    else:
        rate, source, fx_status = resolve_payload_rate(
            db,
            tenant_id=tenant_id,
            currency_code=code,
            rate_date=rate_date,
        )
    expense.home_currency_code = home
    expense.original_currency_code = code
    expense.original_amount_minor = original_amount
    expense.exchange_rate_to_cny = rate
    expense.exchange_rate_date = rate_date
    expense.exchange_rate_source = source
    expense.fx_status = fx_status
    expense.amount_cents = calculate_cny_cents(
        original_currency_code=code,
        original_amount_minor=original_amount,
        exchange_rate_to_cny=rate,
    )


def refresh_currency_snapshot(db: Session, *, tenant_id: str, expense: Expense) -> None:
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=expense,
        amount_was_explicit=False,
    )
