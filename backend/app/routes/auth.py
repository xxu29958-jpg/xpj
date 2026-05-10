from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import AuthCheckResponse, PairRequest, PairResponse
from app.services.identity_service import pair_device
from app.tenants import AuthContext


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/check", response_model=AuthCheckResponse)
def check_auth(auth: AuthContext = Depends(get_current_app_context)) -> AuthCheckResponse:
    return AuthCheckResponse(
        account_name=auth.account_name,
        ledger_id=auth.ledger_id,
        ledger_name=auth.ledger_name,
        device_name=auth.device_name,
        role=auth.role,
        scope=auth.scope,
    )


@router.post("/pair", response_model=PairResponse)
def pair(payload: PairRequest, request: Request, db: Session = Depends(get_db)) -> PairResponse:
    remote_id = request.client.host if request.client is not None else None
    result = pair_device(
        db,
        pairing_code=payload.pairing_code,
        device_name=payload.device_name,
        platform=payload.platform,
        remote_id=remote_id,
    )
    return PairResponse(
        session_token=result.session_token,
        account_name=result.account_name,
        ledger_id=result.ledger_id,
        ledger_name=result.ledger_name,
        device_name=result.device_name,
        role=result.role,
    )
