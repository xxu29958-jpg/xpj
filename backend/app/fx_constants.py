from __future__ import annotations

DEFAULT_HOME_CURRENCY_CODE = "CNY"
DEFAULT_SUPPORTED_CURRENCY_CODES = frozenset({"CNY", "USD", "EUR", "GBP", "JPY", "HKD", "KRW"})
CURRENCY_MINOR_UNIT_DIGITS = {
    "CNY": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
    "HKD": 2,
    "KRW": 0,
}
NO_FRACTION_CURRENCY_CODES = frozenset(code for code, digits in CURRENCY_MINOR_UNIT_DIGITS.items() if digits == 0)
CURRENCY_SYMBOLS = {
    "CNY": "¥",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "HKD": "HK$",
    "KRW": "₩",
}

FX_SOURCE_BASE = "base"
FX_SOURCE_ECB = "ecb"
FX_SOURCE_MANUAL = "manual"
FX_STATUS_READY = "ready"
FX_STATUS_PENDING = "pending"

ECB_PROVIDER_BASE_CURRENCY = "EUR"
