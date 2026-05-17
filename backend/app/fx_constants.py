from __future__ import annotations


DEFAULT_HOME_CURRENCY_CODE = "CNY"
DEFAULT_SUPPORTED_CURRENCY_CODES = frozenset({"CNY", "USD", "EUR", "GBP", "JPY", "HKD", "KRW"})
NO_FRACTION_CURRENCY_CODES = frozenset({"JPY", "KRW"})
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
