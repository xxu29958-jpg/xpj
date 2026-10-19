from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import ExchangeRateListResponse, ExchangeRateRequest, ExchangeRateResponse
from app.schemas._exchange import AmountConversionResponse, ReferenceRateRequest, ReferenceRatesResponse
from app.services.exchange_rate_conversion import convert_reference_amount
from app.services.exchange_rate_reference_service import acquire_reference_rates, read_reference_rates
from app.services.exchange_rate_service import list_exchange_rates, set_exchange_rate_idempotently
from app.tenants import AuthContext

router = APIRouter(prefix="/api/exchange-rates", tags=["exchange-rates"])


@router.get("/conversion", response_model=AmountConversionResponse)
def get_amount_conversion(currency_code: str, home_currency_code: str, rate_date: date,
    amount: str = Query(max_length=32), auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db)) -> AmountConversionResponse:
    return convert_reference_amount(db, tenant_id=auth.tenant_id, currency_code=currency_code,
        home_currency_code=home_currency_code, amount=amount, rate_date=rate_date)


@router.get("/reference", response_model=ReferenceRatesResponse)
def get_reference_rates(home_currency_code: str = Query(min_length=3, max_length=3),
    currency_code: str | None = Query(default=None, min_length=3, max_length=3), rate_date: date | None = None,
    auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)) -> ReferenceRatesResponse:
    return read_reference_rates(db, tenant_id=auth.tenant_id, request=ReferenceRateRequest(
        currency_code=currency_code, home_currency_code=home_currency_code, rate_date=rate_date))


@router.post("/reference", response_model=ReferenceRatesResponse)
def fetch_reference_rates(payload: ReferenceRateRequest,
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db)) -> ReferenceRatesResponse:
    return acquire_reference_rates(db, tenant_id=auth.tenant_id, request=payload)


@router.get("", response_model=ExchangeRateListResponse)
def get_rates(
    currency_code: str | None = None,
    home_currency_code: str | None = None,
    rate_date: date | None = None,
    limit: int = Query(default=90, ge=1, le=365),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExchangeRateListResponse:
    return ExchangeRateListResponse(
        items=list_exchange_rates(
            db,
            tenant_id=auth.tenant_id,
            currency_code=currency_code,
            home_currency_code=home_currency_code,
            rate_date=rate_date,
            limit=limit,
        )
    )


@router.put("/{currency_code}/{rate_date}", response_model=ExchangeRateResponse)
def put_rate(
    currency_code: str,
    rate_date: date,
    payload: ExchangeRateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> ExchangeRateResponse:
    code = payload.currency_code.strip().upper()
    if code != currency_code.strip().upper():
        raise AppError("invalid_request", "路径币种与请求体币种不一致。", status_code=422)
    if payload.rate_date != rate_date:
        raise AppError("invalid_request", "路径日期与请求体日期不一致。", status_code=422)
    return set_exchange_rate_idempotently(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
