from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
logger = logging.getLogger(__name__)


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


def fetch_ecb_daily_rates(url: str | None = None) -> EcbDailyRates:
    settings = get_settings()
    request = Request(
        url or settings.fx_rate_ecb_url,
        headers={"User-Agent": "xiaopiaojia-fx-sync/1.0"},
    )
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        xml_text = response.read().decode("utf-8")
    return parse_ecb_daily_rates(xml_text)


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
    daily = fetch_ecb_daily_rates(url)
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
