"""Reference-rate acquisition and presentation for the existing rate and money owners."""

from xml.etree.ElementTree import ParseError

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.schemas._exchange import ReferenceRateRequest, ReferenceRateResponse, ReferenceRatesResponse
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.exchange_rate_service import resolve_payload_rate
from app.services.fx_rate_provider import (
    FxFetchError,
    cache_reference_rates_for_date,
    fetch_reference_rates_for_date,
    list_reference_rates,
    refresh_ecb_fx_rates,
)
from app.services.fx_rate_scheduler import fx_rate_sync_status


def read_reference_rates(db: Session, *, tenant_id: str, request: ReferenceRateRequest) -> ReferenceRatesResponse:
    require_runtime_home_currency_code(db)
    home = normalize_currency_code(request.home_currency_code)
    currency = normalize_currency_code(request.currency_code) if request.currency_code else None
    rows = list_reference_rates(db, home_currency_code=home, currency_code=currency, rate_date=request.rate_date)
    effective = None
    if currency and request.rate_date:
        rate, source, _, published = resolve_payload_rate(db, tenant_id=tenant_id, currency_code=currency,
            home_currency_code=home, rate_date=request.rate_date)
        if rate is not None:
            effective = ReferenceRateResponse(currency_code=currency, home_currency_code=home,
                rate_date=published, rate_to_home=rate, source=source)
    cfg, sync = get_settings(), fx_rate_sync_status()
    state = "error" if sync.last_error else "ready" if rows else "waiting"
    if not cfg.fx_rate_auto_sync_enabled:
        state = "paused"
    return ReferenceRatesResponse(provider=cfg.fx_rate_source, auto_enabled=cfg.fx_rate_auto_sync_enabled,
        sync_state=state, requested_date=request.rate_date, effective=effective, items=rows)


def acquire_reference_rates(db: Session, *, tenant_id: str, request: ReferenceRateRequest) -> ReferenceRatesResponse:
    """Fetch a quote, never a manual override or a financial command; retry is safe."""
    require_runtime_home_currency_code(db)
    home = normalize_currency_code(request.home_currency_code)
    currency = normalize_currency_code(request.currency_code) if request.currency_code else None
    try:
        if request.rate_date:
            daily = fetch_reference_rates_for_date(request.rate_date, home_currency_code=home)
            cache_reference_rates_for_date(db, daily, requested_date=request.rate_date, home_currency_code=home,
                currencies={currency} if currency else None)
            db.commit()
        else:
            refresh_ecb_fx_rates(db, home_currency_code=home, currencies={currency} if currency else None)
    except (FxFetchError, ValueError, ParseError) as exc:
        db.rollback()
        raise AppError("dependency_unavailable", "暂未取得该币种和日期的参考汇率。已有汇率和原操作已保留；可重试，或自行补录。", status_code=502) from exc
    return read_reference_rates(db, tenant_id=tenant_id, request=request)
