"""Currency-context validation and conversion for receipt amount parsing."""

from __future__ import annotations

import re

from app.errors import AppError
from app.services.currency_common import major_amount_to_minor, minor_unit_digits

_GROUPED_MAJOR_AMOUNT = re.compile(
    r"-?(?:[1-9][0-9]{0,2})(?:,[0-9]{3})+(?:\.[0-9]{1,2})?\Z"
)
_EXPLICIT_CURRENCY_MARKERS = {
    "CNY": ("CNY", "RMB", "人民币"),
    "JPY": ("JPY", "日元", "円"),
    "KRW": ("KRW", "韩元", "韓元", "₩", "원"),
    "USD": ("USD", "US$", "美元"),
    "EUR": ("EUR", "€", "欧元", "歐元"),
    "GBP": ("GBP", "£", "英镑", "英鎊"),
    "HKD": ("HKD", "HK$", "港币", "港幣"),
}


def validated_money_context(
    currency_code: str | None,
    minor_unit_exponent: int | None,
) -> tuple[str, int] | None:
    code = (currency_code or "").strip().upper()
    if not code or type(minor_unit_exponent) is not int:
        return None
    try:
        expected_exponent = minor_unit_digits(code)
    except AppError:
        return None
    if minor_unit_exponent != expected_exponent:
        return None
    return code, minor_unit_exponent


def text_currency_matches_context(text: str, currency_code: str) -> bool:
    upper_text = text.upper()
    declared_codes: set[str] = set()
    for code, markers in _EXPLICIT_CURRENCY_MARKERS.items():
        for marker in markers:
            upper_marker = marker.upper()
            if upper_marker.isascii() and upper_marker.isalpha():
                pattern = rf"(?<![A-Z]){re.escape(upper_marker)}(?![A-Z])"
                present = re.search(pattern, upper_text) is not None
            else:
                present = upper_marker in upper_text
            if present:
                declared_codes.add(code)
                break
    return not declared_codes or declared_codes == {currency_code}


def amount_plausibility_score(amount_minor: int, minor_unit_exponent: int) -> int:
    scale = 10**minor_unit_exponent
    if amount_minor < max(1, scale // 2):
        return -8
    if amount_minor <= 2_000 * scale:
        return 8
    if amount_minor <= 10_000 * scale:
        return 2
    return -4


def money_to_minor(
    value: str,
    *,
    currency_code: str | None,
    minor_unit_exponent: int | None,
) -> int | None:
    context_pair = validated_money_context(currency_code, minor_unit_exponent)
    if context_pair is None:
        return None
    code, exponent = context_pair
    normalized = value.strip()
    if "," in normalized:
        if _GROUPED_MAJOR_AMOUNT.fullmatch(normalized) is None:
            return None
        normalized = normalized.replace(",", "")
    if exponent == 0 and "." in normalized:
        return None
    try:
        return major_amount_to_minor(normalized, code, allow_negative=True)
    except AppError:
        return None


__all__ = [
    "amount_plausibility_score",
    "money_to_minor",
    "text_currency_matches_context",
    "validated_money_context",
]
