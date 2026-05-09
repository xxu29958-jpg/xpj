from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import get_current_owner_or_admin_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    BootstrapOwnerRequest,
    BootstrapOwnerResponse,
    PairingCodeCreateRequest,
    PairingCodeResponse,
)
from app.services.identity_service import bootstrap_owner, create_pairing_code
from app.tenants import AuthContext


router = APIRouter(prefix="/api/bootstrap", tags=["bootstrap"])

LOCAL_BOOTSTRAP_HOSTS = {"localhost", "testclient"}


def require_local_bootstrap_request(request: Request) -> None:
    host = request.client.host if request.client is not None else ""
    if host in LOCAL_BOOTSTRAP_HOSTS:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise AppError("invalid_token", "Bootstrap owner 只能在后端本机执行。", status_code=403)


@router.post("/owner", response_model=BootstrapOwnerResponse)
def post_bootstrap_owner(
    payload: BootstrapOwnerRequest,
    _: None = Depends(require_local_bootstrap_request),
    db: Session = Depends(get_db),
) -> BootstrapOwnerResponse:
    result = bootstrap_owner(
        db,
        account_name=payload.account_name,
        ledger_name=payload.ledger_name,
        device_name=payload.device_name,
        default_timezone=payload.default_timezone,
    )
    return BootstrapOwnerResponse(**result.__dict__)


@router.post("/pairing-codes", response_model=PairingCodeResponse)
def post_pairing_code(
    payload: PairingCodeCreateRequest,
    auth: AuthContext = Depends(get_current_owner_or_admin_context),
    db: Session = Depends(get_db),
) -> PairingCodeResponse:
    result = create_pairing_code(
        db,
        ledger_id=auth.ledger_id,
        account_id=auth.account_id,
        device_name_hint=payload.device_name_hint,
        ttl_minutes=payload.ttl_minutes,
    )
    return PairingCodeResponse(
        pairing_code=result.pairing_code,
        ledger_name=result.ledger_name,
        expires_at=result.expires_at,
    )
