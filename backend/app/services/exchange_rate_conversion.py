"""Read-only amount suggestions from the existing dated, ledger-scoped FX owner."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas._exchange import AmountConversionResponse, ReferenceRateResponse
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import (
    major_amount_to_minor,
    minor_amount_value,
    minor_unit_digits,
    normalize_currency_code,
)
from app.services.exchange_rate_service import get_exchange_rate, resolve_payload_rate


def _pair(db, tenant_id, source, target, day, *, manual_only):
    if source == target:
        return Decimal(1), []
    for currency, home, inverse in ((source, target, False), (target, source, True)):
        if manual_only:
            stored = get_exchange_rate(db, tenant_id=tenant_id, currency_code=currency,
                home_currency_code=home, rate_date=day)
            if stored is None:
                continue
            rate, provider, published = Decimal(stored.rate_to_cny), stored.source, stored.rate_date
        else:
            rate, provider, _, published = resolve_payload_rate(db, tenant_id=tenant_id, currency_code=currency,
                home_currency_code=home, rate_date=day)
        if rate is not None:
            reference = ReferenceRateResponse(currency_code=currency, home_currency_code=home,
                rate_date=published, rate_to_home=rate, source=provider)
            return (Decimal(1) / rate if inverse else rate), [reference]
    return None, []


def _pivot_rate(db, tenant_id, source, target, pivot, day):
    source_rate, source_refs = _pair(db, tenant_id, source, pivot, day, manual_only=True)
    target_rate, target_refs = _pair(db, tenant_id, target, pivot, day, manual_only=True)
    uses_ledger_rate = source_rate is not None or target_rate is not None
    if source_rate is None:
        source_rate, source_refs = _pair(db, tenant_id, source, pivot, day, manual_only=False)
    if target_rate is None:
        target_rate, target_refs = _pair(db, tenant_id, target, pivot, day, manual_only=False)
    if source_rate is None or target_rate is None:
        return None, [], False
    return source_rate / target_rate, source_refs + target_refs, uses_ledger_rate


def _conversion_rate(db, tenant_id, source, target, pivot, day):
    rate, references = _pair(db, tenant_id, source, target, day, manual_only=True)
    if rate is not None:
        return rate, references
    cross_rate, cross_refs = None, []
    if pivot not in (source, target):
        cross_rate, cross_refs, uses_ledger_rate = _pivot_rate(db, tenant_id, source, target, pivot, day)
        if uses_ledger_rate:
            return cross_rate, cross_refs
    # A complete path containing a ledger override wins over a wholly public direct quote.
    rate, references = _pair(db, tenant_id, source, target, day, manual_only=False)
    return (rate, references) if rate is not None else (cross_rate, cross_refs)


def convert_reference_amount(db: Session, *, tenant_id: str, currency_code: str, home_currency_code: str,
                             amount: str, rate_date: date) -> AmountConversionResponse:
    pivot = require_runtime_home_currency_code(db)
    source, target = normalize_currency_code(currency_code), normalize_currency_code(home_currency_code)
    original = major_amount_to_minor(amount, source)
    if source == target or original == 0:
        return AmountConversionResponse(converted_amount=minor_amount_value(original, target))
    rate, references = _conversion_rate(db, tenant_id, source, target, pivot, rate_date)
    if rate is None:
        return AmountConversionResponse(converted_amount=None)
    try:
        converted = (Decimal(amount) * rate).quantize(Decimal(1).scaleb(-minor_unit_digits(target)), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise AppError("amount_invalid", status_code=422) from exc
    minor = major_amount_to_minor(converted, target)
    if minor == 0:
        return AmountConversionResponse(converted_amount=None, references=references)
    return AmountConversionResponse(converted_amount=minor_amount_value(minor, target), references=references)
