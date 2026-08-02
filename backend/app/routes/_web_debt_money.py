"""Exact money-input adapter for the Web debt write surfaces."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.errors import AppError
from app.money_carrier import parse_canonical_major_decimal
from app.services.currency_common import major_amount_to_minor, minor_unit_digits


def _major_amount_input_error(
    raw: str,
    *,
    currency_code: str,
    allow_negative: bool,
) -> str:
    """Map the strict money parser's stable error to actionable form copy.

    The service deliberately exposes one ``amount_invalid`` code for malformed,
    over-precise, and out-of-range money. A browser form still has enough exact
    input and currency metadata to tell the user which correction is required;
    collapsing those cases regresses the field-level error contract, especially
    for zero-fraction currencies.
    """

    code = currency_code.strip().upper()
    digits = minor_unit_digits(code)
    example = "120" if digits == 0 else "120.50"
    try:
        amount = parse_canonical_major_decimal(raw, allow_negative=True)
    except ValueError:
        return f"请填写正确的 {code} 金额，例如 {example}。"
    if amount < 0 and not allow_negative:
        return "金额必须大于 0；调整时可用负数减少账面。"
    quantum = Decimal(1).scaleb(-digits)
    try:
        exact = amount.quantize(quantum)
    except InvalidOperation:
        return f"{code} 金额超出当前版本可支持范围。"
    if exact != amount:
        if digits == 0:
            return f"{code} 金额只能填写整数。"
        return f"{code} 金额最多保留 {digits} 位小数。"
    return f"{code} 金额超出当前版本可支持范围。"


def parse_web_debt_major_minor(
    raw: str,
    *,
    currency_code: str,
    allow_negative: bool,
) -> int:
    """Parse one debt form amount without weakening the C07 money boundary."""

    text = raw or ""
    code = (currency_code or "").strip().upper()
    try:
        amount_minor = major_amount_to_minor(
            text,
            code,
            allow_negative=allow_negative,
        )
    except AppError as exc:
        if exc.error != "amount_invalid":
            raise
        raise AppError(
            "invalid_request",
            _major_amount_input_error(
                text,
                currency_code=code,
                allow_negative=allow_negative,
            ),
            status_code=422,
        ) from exc
    assert amount_minor is not None
    if (allow_negative and amount_minor == 0) or (not allow_negative and amount_minor <= 0):
        raise AppError(
            "debt_amount_invalid",
            "金额必须大于 0；调整时可用负数减少账面。",
            status_code=422,
        )
    return amount_minor


__all__ = ["parse_web_debt_major_minor"]
