from __future__ import annotations

from app.currency_catalog import CURRENCY_CATALOG

DEFAULT_HOME_CURRENCY_CODE = "CNY"
DEFAULT_SUPPORTED_CURRENCY_CODES = frozenset(CURRENCY_CATALOG)
CURRENCY_MINOR_UNIT_DIGITS = {code: value[3] for code, value in CURRENCY_CATALOG.items()}
NO_FRACTION_CURRENCY_CODES = frozenset(code for code, digits in CURRENCY_MINOR_UNIT_DIGITS.items() if digits == 0)
CURRENCY_SYMBOLS = {code: value[1] for code, value in CURRENCY_CATALOG.items()}

FX_SOURCE_BASE = "base"
FX_SOURCE_ECB = "ecb"
FX_SOURCE_FRANKFURTER = "frankfurter"
FX_SOURCE_MANUAL = "manual"
FX_STATUS_READY = "ready"
FX_STATUS_PENDING = "pending"

ECB_PROVIDER_BASE_CURRENCY = "EUR"

FX_DEFAULT_URLS = {
    "frankfurter_v2": "https://api.frankfurter.dev/v2/rates",
    "frankfurter": "https://api.frankfurter.dev/v1/latest?base=EUR",
    "ecb": "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
}
