"""Pure currency-code + rate helpers shared between exchange_rate_service
and fx_rate_provider.

Extracted to break the exchange_rate_service ↔ fx_rate_provider import
cycle: fx_rate_provider used these symbols at module load time, while
exchange_rate_service's hot path lazy-imported get_fx_rate. With both
sides depending on this module (and this module depending on neither),
the cycle goes away.

None of these functions touch the database; they are configuration +
arithmetic only. The Session-aware logic (rate lookups, snapshot
writes, FX-aware amount calculation) stays in exchange_rate_service.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.config import get_settings
from app.errors import AppError
from app.fx_constants import (
    DEFAULT_HOME_CURRENCY_CODE,
    DEFAULT_SUPPORTED_CURRENCY_CODES,
)

__all__ = [
    "RATE_QUANT",
    "format_decimal_rate",
    "home_currency_code",
    "normalize_currency_code",
    "supported_currency_codes",
]

RATE_QUANT = Decimal("0.00000001")


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
