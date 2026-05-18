from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import ExchangeRateListResponse, ExchangeRateRequest, ExchangeRateResponse
from app.services.exchange_rate_service import list_exchange_rates, upsert_exchange_rate
from app.tenants import AuthContext


router = APIRouter(prefix="/api/exchange-rates", tags=["exchange-rates"])


@router.get("", response_model=ExchangeRateListResponse)
def get_rates(
    currency_code: str | None = None,
    limit: int = Query(default=90, ge=1, le=365),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExchangeRateListResponse:
    return ExchangeRateListResponse(
        items=list_exchange_rates(
            db,
            tenant_id=auth.tenant_id,
            currency_code=currency_code,
            limit=limit,
        )
    )


@router.put("/{currency_code}/{rate_date}", response_model=ExchangeRateResponse)
def put_rate(
    currency_code: str,
    rate_date: date,
    payload: ExchangeRateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExchangeRateResponse:
    code = payload.currency_code.strip().upper()
    if code != currency_code.strip().upper():
        raise AppError("invalid_request", "路径币种与请求体币种不一致。", status_code=422)
    if payload.rate_date != rate_date:
        raise AppError("invalid_request", "路径日期与请求体日期不一致。", status_code=422)
    return upsert_exchange_rate(
        db,
        tenant_id=auth.tenant_id,
        currency_code=code,
        rate_date=rate_date,
        rate_to_cny=payload.rate_to_cny,
        source=payload.source,
    )
