from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.fx_constants import ECB_PROVIDER_BASE_CURRENCY, FX_SOURCE_ECB
from app.models import FxRate
from app.services.currency_common import (
    RATE_QUANT,
    format_decimal_rate,
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.currency_common import (
    home_currency_code as current_home_currency_code,
)
from app.services.time_service import now_utc

FETCH_TIMEOUT_SECONDS = 10
# This machine's network intermittently terminates outbound TLS handshakes
# ("UNEXPECTED_EOF_WHILE_READING") — the same flakiness that hits Maven/gradle.
# A single blip used to fail the whole daily sync until the next scheduled run
# (hours later, leaving rates stale). Retry a few times with linear backoff so a
# transient handshake drop recovers within one cycle.
FETCH_RETRIES = 3
FETCH_BACKOFF_SECONDS = 2.0
logger = logging.getLogger(__name__)


class FxFetchError(Exception):
    """ECB rates could not be fetched after retries (transient network / TLS).

    Distinct from parse / data errors so the scheduler can log a transient
    network drop at WARNING (rates degrade gracefully to last-known, next
    cycle retries) instead of spamming ERROR tracebacks.
    """


@dataclass(frozen=True)
class EcbDailyRates:
    rate_date: date
    rates_per_eur: dict[str, Decimal]


def parse_ecb_daily_rates(xml_text: str) -> EcbDailyRates:
    root = ElementTree.fromstring(xml_text)
    day_cube = None
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "Cube" and "time" in element.attrib:
            day_cube = element
            break
    if day_cube is None:
        raise ValueError("ECB daily XML missing rate date")

    rates: dict[str, Decimal] = {ECB_PROVIDER_BASE_CURRENCY: Decimal("1")}
    for element in day_cube:
        currency = element.attrib.get("currency")
        rate = element.attrib.get("rate")
        if not currency or not rate:
            continue
        try:
            rates[currency.strip().upper()] = Decimal(rate)
        except InvalidOperation as exc:
            raise ValueError(f"ECB daily XML has invalid rate for {currency}") from exc

    return EcbDailyRates(rate_date=date.fromisoformat(day_cube.attrib["time"]), rates_per_eur=rates)


def parse_frankfurter_rates(json_text: str) -> EcbDailyRates:
    """Parse Frankfurter's JSON into the same EUR-based reference-rate shape.

    Frankfurter redistributes the ECB daily reference set, so the data is
    identical to :func:`parse_ecb_daily_rates`; only the wire format differs
    (``{"base":"EUR","date":"YYYY-MM-DD","rates":{"CNY":7.8,...}}``). The base
    currency is re-inserted at 1.0 because Frankfurter omits it from ``rates``.
    """
    try:
        # parse_float=Decimal keeps full precision — going through float64 (the
        # json default) would silently truncate, unlike the ECB XML path which
        # builds Decimals straight from the string attribute.
        payload = json.loads(json_text, parse_float=Decimal)
    except (ValueError, TypeError) as exc:
        raise ValueError("Frankfurter response is not valid JSON") from exc
    raw_date = payload.get("date")
    raw_rates = payload.get("rates")
    if not raw_date or not isinstance(raw_rates, dict):
        raise ValueError("Frankfurter response missing date/rates")
    base = str(payload.get("base") or ECB_PROVIDER_BASE_CURRENCY).strip().upper()
    rates: dict[str, Decimal] = {base: Decimal("1")}
    for code, value in raw_rates.items():
        try:
            rates[str(code).strip().upper()] = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Frankfurter response has invalid rate for {code}") from exc
    try:
        rate_date = date.fromisoformat(str(raw_date))
    except ValueError as exc:
        raise ValueError("Frankfurter response has invalid date") from exc
    return EcbDailyRates(rate_date=rate_date, rates_per_eur=rates)


def _http_get_text(target: str) -> str:
    """GET ``target`` as UTF-8 text, retrying transient network/TLS failures.

    ``URLError`` (urllib's wrapper) and ``OSError`` (covers ssl.SSLError,
    ConnectionError, TimeoutError) are the transient family worth retrying;
    everything else propagates. After [FETCH_RETRIES] attempts we raise
    [FxFetchError] so the caller can degrade gracefully. Used by both the ECB
    (XML) and Frankfurter (JSON) transports.
    """
    request = Request(target, headers={"User-Agent": "xiaopiaojia-fx-sync/1.0"})
    last_exc: Exception | None = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8")
        except (URLError, OSError) as exc:
            last_exc = exc
            if attempt < FETCH_RETRIES:
                _time.sleep(FETCH_BACKOFF_SECONDS * attempt)
    raise FxFetchError(
        f"FX rate fetch failed after {FETCH_RETRIES} attempts: "
        f"{type(last_exc).__name__}: {last_exc}"
    ) from last_exc


def fetch_ecb_daily_rates(url: str | None = None) -> EcbDailyRates:
    settings = get_settings()
    target = url or settings.fx_rate_ecb_url
    return parse_ecb_daily_rates(_http_get_text(target))


def fetch_frankfurter_daily_rates(url: str | None = None) -> EcbDailyRates:
    settings = get_settings()
    target = url or settings.fx_rate_frankfurter_url
    return parse_frankfurter_rates(_http_get_text(target))


def fetch_reference_rates() -> EcbDailyRates:
    """Fetch EUR-based reference rates from the configured transport.

    Default is Frankfurter (``FX_RATE_SOURCE=frankfurter``): key-free and
    reachable from mainland China without a proxy, where europa.eu intermittently
    drops the outbound TLS handshake. Both transports yield the ECB reference set
    (Frankfurter redistributes it), so ``source='ecb'`` still describes the data
    provenance. Set ``FX_RATE_SOURCE=ecb`` to fetch europa.eu directly. See
    ADR-0027.
    """
    settings = get_settings()
    if (settings.fx_rate_source or "frankfurter").strip().lower() == "ecb":
        return fetch_ecb_daily_rates()
    return fetch_frankfurter_daily_rates()


def cross_rate_to_home(
    rates_per_eur: dict[str, Decimal],
    *,
    currency_code: str,
    home_currency_code: str | None = None,
) -> Decimal:
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code or current_home_currency_code())
    if currency == home:
        return Decimal("1").quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    try:
        home_per_eur = rates_per_eur[home]
        currency_per_eur = rates_per_eur[currency]
    except KeyError as exc:
        raise ValueError(f"ECB daily XML missing {exc.args[0]} rate") from exc
    if home_per_eur <= 0 or currency_per_eur <= 0:
        raise ValueError("ECB daily XML contains non-positive rate")
    return (home_per_eur / currency_per_eur).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)


def get_fx_rate(
    db: Session,
    *,
    currency_code: str,
    rate_date: date,
    home_currency_code: str | None = None,
    source: str = FX_SOURCE_ECB,
) -> FxRate | None:
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code or current_home_currency_code())
    if currency == home:
        return None
    return db.scalar(
        select(FxRate)
        .where(FxRate.source == source)
        .where(FxRate.home_currency_code == home)
        .where(FxRate.currency_code == currency)
        .where(FxRate.rate_date == rate_date)
    )


def get_fx_rate_on_or_before(
    db: Session,
    *,
    currency_code: str,
    rate_date: date,
    home_currency_code: str | None = None,
    source: str = FX_SOURCE_ECB,
) -> FxRate | None:
    """Most recent fetched rate effective on ``rate_date`` (``rate_date <= D``).

    ECB / Frankfurter only publish on TARGET working days, so an expense dated on
    a weekend or holiday has no exact-date row. The rate in effect that day is the
    last published one — markets carry Friday's rate through the weekend — so we
    fall back to the newest row at or before the requested date instead of leaving
    the expense ``pending``. Returns an exact-date row when one exists.
    """
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code or current_home_currency_code())
    if currency == home:
        return None
    return db.scalar(
        select(FxRate)
        .where(FxRate.source == source)
        .where(FxRate.home_currency_code == home)
        .where(FxRate.currency_code == currency)
        .where(FxRate.rate_date <= rate_date)
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )


def upsert_fx_rate(
    db: Session,
    *,
    currency_code: str,
    rate_date: date,
    rate_to_home: Decimal,
    home_currency_code: str | None = None,
    source: str = FX_SOURCE_ECB,
    provider_base_currency: str = ECB_PROVIDER_BASE_CURRENCY,
    provider_rate: Decimal | None = None,
) -> FxRate:
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code or current_home_currency_code())
    if currency == home:
        raise ValueError("base currency does not need fx rate")
    rate = format_decimal_rate(rate_to_home)
    if rate is None:
        raise ValueError("fx rate is required")
    now = now_utc()
    existing = get_fx_rate(
        db,
        currency_code=currency,
        rate_date=rate_date,
        home_currency_code=home,
        source=source,
    )
    if existing is None:
        existing = FxRate(
            source=source,
            home_currency_code=home,
            currency_code=currency,
            rate_date=rate_date,
            rate_to_home=rate,
            provider_base_currency=provider_base_currency,
            provider_rate=provider_rate,
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
    else:
        existing.rate_to_home = rate
        existing.provider_base_currency = provider_base_currency
        existing.provider_rate = provider_rate
        existing.fetched_at = now
        existing.updated_at = now
    return existing


def refresh_ecb_fx_rates(
    db: Session,
    *,
    home_currency_code: str | None = None,
    currencies: set[str] | None = None,
    url: str | None = None,
) -> list[FxRate]:
    # ``url`` forces the ECB XML transport (tests / explicit override); the
    # default path dispatches on FX_RATE_SOURCE (Frankfurter by default).
    daily = fetch_ecb_daily_rates(url) if url is not None else fetch_reference_rates()
    home = normalize_currency_code(home_currency_code or current_home_currency_code())
    target_currencies = currencies or supported_currency_codes()
    rows: list[FxRate] = []
    for raw_code in sorted(target_currencies):
        code = normalize_currency_code(raw_code)
        if code == home:
            continue
        try:
            rate_to_home = cross_rate_to_home(
                daily.rates_per_eur,
                currency_code=code,
                home_currency_code=home,
            )
        except ValueError:
            logger.warning("ECB daily FX sync skipped unsupported currency %s", code)
            continue
        rows.append(
            upsert_fx_rate(
                db,
                currency_code=code,
                rate_date=daily.rate_date,
                rate_to_home=rate_to_home,
                home_currency_code=home,
                provider_rate=daily.rates_per_eur.get(code),
            )
        )
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows
