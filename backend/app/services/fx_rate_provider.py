from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
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

    return _parse_ecb_day(day_cube)


def _parse_ecb_day(day_cube: ElementTree.Element) -> EcbDailyRates:
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


def _parse_ecb_rates_for_date(xml_text: str, requested_date: date) -> EcbDailyRates:
    root = ElementTree.fromstring(xml_text)
    days = [element for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "Cube" and "time" in element.attrib]
    applicable = [element for element in days if date.fromisoformat(element.attrib["time"]) <= requested_date]
    if not applicable:
        raise ValueError("ECB history has no rate on or before the requested date")
    return _parse_ecb_day(max(applicable, key=lambda element: element.attrib["time"]))


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


def _frankfurter_dated_url(configured_url: str, requested_date: date) -> str:
    parts = urlsplit(configured_url)
    prefix, _, endpoint = parts.path.rstrip("/").rpartition("/")
    if endpoint != "latest":
        try:
            date.fromisoformat(endpoint)
        except ValueError as exc:
            raise ValueError("Configured Frankfurter URL must end in latest or an ISO date") from exc
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key not in {"base", "amount"}]
    query.extend((("base", ECB_PROVIDER_BASE_CURRENCY), ("amount", "1")))
    return urlunsplit(parts._replace(path=f"{prefix}/{requested_date.isoformat()}", query=urlencode(query), fragment=""))


def _ecb_history_url(configured_url: str) -> str:
    parts = urlsplit(configured_url)
    prefix, _, endpoint = parts.path.rpartition("/")
    if endpoint not in {"eurofxref-daily.xml", "eurofxref-hist-90d.xml", "eurofxref-hist.xml"}:
        raise ValueError("Configured ECB URL cannot prove historical coverage")
    return urlunsplit(parts._replace(path=f"{prefix}/eurofxref-hist.xml", fragment=""))


def _validate_dated_rates(daily: EcbDailyRates, requested_date: date) -> None:
    if daily.rate_date > requested_date:
        raise ValueError("Reference rate publication is after the requested date")
    if daily.rates_per_eur.get(ECB_PROVIDER_BASE_CURRENCY) != Decimal("1"):
        raise ValueError("Reference rates must use one EUR as the provider base")
    if any(not value.is_finite() or value <= 0 for value in daily.rates_per_eur.values()):
        raise ValueError("Reference rates must be finite and positive")


def fetch_reference_rates_for_date(requested_date: date) -> EcbDailyRates:
    """Fetch the actual reference published on/before D without changing D."""
    if requested_date > now_utc().date():
        raise ValueError("A future provider date cannot be fetched as historical coverage")
    settings = get_settings()
    if (settings.fx_rate_source or "frankfurter").strip().lower() == "ecb":
        daily = _parse_ecb_rates_for_date(_http_get_text(_ecb_history_url(settings.fx_rate_ecb_url)), requested_date)
    else:
        target = _frankfurter_dated_url(settings.fx_rate_frankfurter_url, requested_date)
        daily = parse_frankfurter_rates(_http_get_text(target))
    _validate_dated_rates(daily, requested_date)
    return daily


def cross_rate_to_home(
    rates_per_eur: dict[str, Decimal],
    *,
    currency_code: str,
    home_currency_code: str,
) -> Decimal:
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code)
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
    home_currency_code: str,
    source: str = FX_SOURCE_ECB,
) -> FxRate | None:
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code)
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
    home_currency_code: str,
    source: str = FX_SOURCE_ECB,
) -> FxRate | None:
    """Latest known quote for an explicit current valuation, with its real date.

    This lookup does not prove historical coverage of the requested date.
    """
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code)
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


def get_covered_fx_rate(
    db: Session,
    *,
    currency_code: str,
    rate_date: date,
    home_currency_code: str,
    source: str = FX_SOURCE_ECB,
) -> FxRate | None:
    """An exact publication or a prior quote verified through the requested day."""
    quote = get_fx_rate_on_or_before(
        db, currency_code=currency_code, rate_date=rate_date, home_currency_code=home_currency_code, source=source,
    )
    if quote is not None and (quote.rate_date == rate_date or (
        quote.verified_through is not None and quote.verified_through >= rate_date
    )):
        return quote
    return None


def upsert_fx_rate(
    db: Session,
    *,
    currency_code: str,
    rate_date: date,
    rate_to_home: Decimal,
    home_currency_code: str,
    source: str = FX_SOURCE_ECB,
    provider_base_currency: str = ECB_PROVIDER_BASE_CURRENCY,
    provider_rate: Decimal | None = None,
    verified_through: date | None = None,
) -> FxRate:
    currency = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code)
    if currency == home:
        raise ValueError("base currency does not need fx rate")
    rate = format_decimal_rate(rate_to_home)
    if rate is None:
        raise ValueError("fx rate is required")
    now = now_utc()
    if verified_through is not None and (verified_through < rate_date or verified_through >= now.date()):
        raise ValueError("Reference coverage must end on a closed date on/after publication")
    statement = insert(FxRate).values(
        source=source, home_currency_code=home, currency_code=currency, rate_date=rate_date,
        rate_to_home=rate, provider_base_currency=provider_base_currency, provider_rate=provider_rate,
        verified_through=verified_through, fetched_at=now, created_at=now, updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_fx_rates_source_home_currency_date",
        set_={
            "rate_to_home": statement.excluded.rate_to_home,
            "provider_base_currency": statement.excluded.provider_base_currency,
            "provider_rate": statement.excluded.provider_rate,
            "verified_through": func.greatest(FxRate.verified_through, statement.excluded.verified_through),
            "fetched_at": now, "updated_at": now,
        },
    ).returning(FxRate)
    return db.scalars(statement, execution_options={"populate_existing": True}).one()


def cache_reference_rates_for_date(
    db: Session, daily: EcbDailyRates, *, requested_date: date,
    home_currency_code: str, currencies: set[str] | None = None,
) -> list[FxRate]:
    """Cache one validated response inside the caller's transaction, without IO.

    A current response remains usable by that caller, but only closed UTC dates
    extend persistent coverage. The household date may be ahead of the UTC date.
    """
    _validate_dated_rates(daily, requested_date)
    home = normalize_currency_code(home_currency_code)
    covered_through = requested_date if requested_date < now_utc().date() else None
    target_currencies = supported_currency_codes() if currencies is None else currencies
    quotes = [(normalize_currency_code(code), cross_rate_to_home(
        daily.rates_per_eur, currency_code=code, home_currency_code=home,
    )) for code in sorted(target_currencies) if normalize_currency_code(code) != home]
    return [upsert_fx_rate(
        db, currency_code=code, rate_date=daily.rate_date, rate_to_home=rate,
        home_currency_code=home, provider_rate=daily.rates_per_eur.get(code), verified_through=covered_through,
    ) for code, rate in quotes]


def refresh_ecb_fx_rates(
    db: Session,
    *,
    home_currency_code: str,
    currencies: set[str] | None = None,
    url: str | None = None,
) -> list[FxRate]:
    # Write callers pass the configured home code explicitly so fetch and
    # persistence use one minor-unit interpretation throughout this command.
    home = normalize_currency_code(home_currency_code)
    # ``url`` forces the ECB XML transport (tests / explicit override); the
    # default path dispatches on FX_RATE_SOURCE (Frankfurter by default).
    daily = fetch_ecb_daily_rates(url) if url is not None else fetch_reference_rates()
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
