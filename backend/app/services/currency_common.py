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
    CURRENCY_MINOR_UNIT_DIGITS,
    CURRENCY_SYMBOLS,
    DEFAULT_SUPPORTED_CURRENCY_CODES,
)
from app.money_carrier import parse_canonical_major_decimal
from app.money_contract import (
    MoneySign,
    ensure_money_minor,
    projection_sum_to_int,
    round_minor_ratio_half_up,
)

__all__ = [
    "MAX_STORED_EXCHANGE_RATE",
    "RATE_QUANT",
    "average_minor_amount",
    "currency_input_metadata",
    "currency_symbol",
    "format_decimal_rate",
    "major_amount_to_minor",
    "minor_amount_label",
    "minor_amount_major_number",
    "minor_amount_value",
    "minor_unit_digits",
    "normalize_currency_code",
    "supported_currency_codes",
]

RATE_QUANT = Decimal("0.00000001")
MAX_STORED_EXCHANGE_RATE = Decimal("9999999999.99999999")


def average_minor_amount(total_minor: int, count: int) -> int:
    """Return a financial half-up average at the integer-minor boundary."""

    if type(count) is not int:
        raise TypeError("count must be an exact int")
    if count <= 0:
        return 0
    total = projection_sum_to_int(
        total_minor,
        label="currency.average_total",
    )
    return round_minor_ratio_half_up(
        total,
        count,
        label="currency.average",
    )


def _clean_currency_code(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if not code:
        return None
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        return None
    return code


def _require_currency_code(value: str | None) -> str:
    code = _clean_currency_code(value)
    if code is None:
        raise AppError("currency_not_supported", status_code=422)
    return code


def minor_unit_digits(currency_code: str | None) -> int:
    """Return the explicit ISO 4217/CLDR fraction digits supported by this product.

    This is deliberately a closed product contract, not an attempt to infer
    arbitrary ISO currencies from a default exponent. Frozen historical rows
    may ignore the deployment allowlist, but their code must still be one of the
    product currencies with explicit minor-unit metadata.
    """

    code = _require_currency_code(currency_code)
    try:
        return CURRENCY_MINOR_UNIT_DIGITS[code]
    except KeyError as exc:
        raise AppError("currency_not_supported", status_code=422) from exc


def currency_symbol(currency_code: str | None) -> str:
    code = _require_currency_code(currency_code)
    try:
        return CURRENCY_SYMBOLS[code]
    except KeyError as exc:
        raise AppError("currency_not_supported", status_code=422) from exc


def currency_input_metadata(currency_code: str | None) -> dict[str, object]:
    """HTML major-unit input metadata derived from the currency fraction digits."""

    code = _require_currency_code(currency_code)
    digits = minor_unit_digits(code)
    zero_fraction = digits == 0
    return {
        "currency_code": code,
        "currency_symbol": currency_symbol(code),
        "minor_unit_digits": digits,
        "amount_step": "1" if zero_fraction else "0.01",
        "positive_amount_min": "1" if zero_fraction else "0.01",
        "amount_placeholder": "0" if zero_fraction else "0.00",
        "amount_example": "1200" if zero_fraction else "12.34",
        "inputmode": "numeric" if zero_fraction else "decimal",
        "amount_input_hint": "仅支持整数" if zero_fraction else "最多两位小数",
    }


def minor_amount_value(amount_minor: int | None, currency_code: str | None) -> str:
    """Format stored minor units as a major-unit value without a symbol."""

    if amount_minor is None:
        return ""
    amount = projection_sum_to_int(
        amount_minor,
        label="currency.minor_amount_value",
    )
    digits = minor_unit_digits(currency_code)
    scale = 10**digits
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), scale)
    if digits == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:0{digits}d}"


def minor_amount_label(amount_minor: int | None, currency_code: str | None) -> str:
    """Format stored minor units with the product currency symbol and grouping."""

    if amount_minor is None:
        return ""
    amount = projection_sum_to_int(
        amount_minor,
        label="currency.minor_amount_label",
    )
    digits = minor_unit_digits(currency_code)
    scale = 10**digits
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), scale)
    suffix = "" if digits == 0 else f".{fraction:0{digits}d}"
    return f"{sign}{currency_symbol(currency_code)}{whole:,}{suffix}"


def minor_amount_major_number(
    amount_minor: int | None,
    currency_code: str | None,
) -> int | float | None:
    """Return a JSON/chart-friendly major-unit number.

    Display copy should use :func:`minor_amount_value`; this numeric projection
    exists only for chart geometry and legacy ``*_yuan`` payload keys.
    """

    if amount_minor is None:
        return None
    amount = projection_sum_to_int(
        amount_minor,
        label="currency.minor_amount_major_geometry",
    )
    digits = minor_unit_digits(currency_code)
    if digits == 0:
        return amount
    # Geometry-only scalar. User-visible text must use minor_amount_value/label.
    return float(Decimal(amount) / (Decimal(10) ** digits))


def major_amount_to_minor(
    value: Decimal | str | int | None,
    currency_code: str | None,
    *,
    allow_negative: bool = False,
) -> int | None:
    """Parse major units into stored minor units using currency fraction digits."""

    if value is None:
        return None
    try:
        amount = parse_canonical_major_decimal(
            value,
            allow_negative=allow_negative,
        )
    except ValueError as exc:
        raise AppError("amount_invalid", status_code=422) from exc
    digits = minor_unit_digits(currency_code)
    quant = Decimal(1).scaleb(-digits)
    try:
        exact = amount.quantize(quant)
    except InvalidOperation as exc:
        raise AppError("amount_invalid", status_code=422) from exc
    if exact != amount:
        raise AppError("amount_invalid", status_code=422)
    scale = Decimal(10) ** digits
    return ensure_money_minor(
        int(exact * scale),
        sign=MoneySign.SIGNED if allow_negative else MoneySign.NONNEGATIVE,
        label="currency_common.major_amount_to_minor",
    )


def supported_currency_codes() -> set[str]:
    raw_parts = get_settings().fx_supported_currency_codes.split(",")
    configured: set[str] = set()
    for part in raw_parts:
        if not part.strip():
            continue
        code = _clean_currency_code(part)
        if code is None or code not in DEFAULT_SUPPORTED_CURRENCY_CODES:
            raise AppError("currency_not_supported", status_code=422)
        configured.add(code)
    if not configured:
        configured = set(DEFAULT_SUPPORTED_CURRENCY_CODES)
    return configured


def normalize_currency_code(value: str | None) -> str:
    code = _require_currency_code(value)
    if code not in DEFAULT_SUPPORTED_CURRENCY_CODES:
        raise AppError("currency_not_supported", status_code=422)
    return code


def format_decimal_rate(
    value: Decimal | str | int | None,
) -> Decimal | None:
    """Validate an exact rate carrier and quantize it for NUMERIC(18, 8)."""

    if value is None:
        return None
    try:
        exact = parse_canonical_major_decimal(value)
        rate = exact.quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise AppError("exchange_rate_invalid", status_code=422) from exc
    if rate <= 0:
        raise AppError("exchange_rate_invalid", status_code=422)
    if rate != exact:
        raise AppError("exchange_rate_invalid", status_code=422)
    if rate > MAX_STORED_EXCHANGE_RATE:
        raise AppError("exchange_rate_out_of_range", status_code=422)
    return rate
