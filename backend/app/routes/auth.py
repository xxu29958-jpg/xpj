from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.network_boundary import pairing_rate_limit_key
from app.schemas import (
    AuthCheckResponse,
    PairRequest,
    PairResponse,
    RefreshSessionResponse,
)
from app.services.identity_service import pair_device
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    rotate_app_token_for_ledger,
)
from app.services.time_service import to_iso
from app.tenants import AuthContext

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _bearer_token_value(authorization: str | None) -> str:
    if not authorization:
        raise AppError("invalid_token", status_code=401)
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AppError("invalid_token", status_code=401)
    return parts[1]


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
    remote_id = pairing_rate_limit_key(request)
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
        expires_at=to_iso(result.expires_at),
        soft_refresh_after=to_iso(result.soft_refresh_after),
    )


@router.post("/refresh", response_model=RefreshSessionResponse)
def refresh_session(
    authorization: str | None = Header(default=None),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RefreshSessionResponse:
    """v1.1 Batch 2: silently rotate the caller's app session token.

    Returns a fresh token (with a new ``expires_at``) and revokes the
    previous one. Clients call this from the background once their
    ``soft_refresh_after`` has passed, so the user never sees a forced
    re-pair. Web cookie sessions keep their own short TTL contract; only
    the ``app`` scope rotates here.
    """

    if auth.scope != "app":
        raise AppError("invalid_token", status_code=401)
    if get_settings().app_token_ttl_days <= 0:
        # When TTL is disabled, rotation is a no-op (still returns the
        # current token shape so clients can rely on the contract).
        return RefreshSessionResponse(
            session_token=_bearer_token_value(authorization),
            expires_at=None,
            soft_refresh_after=None,
            rotated=False,
        )
    current_token = _bearer_token_value(authorization)
    from app.services.time_service import now_utc as _now_utc

    rotated_at = _now_utc()
    expiry = app_token_expiry_window(rotated_at)
    new_token, _ = rotate_app_token_for_ledger(
        db,
        current_token_value=current_token,
        account_id=auth.account_id,
        device_id=auth.device_id,
        target_ledger_id=auth.ledger_id,
        rotated_at=rotated_at,
        expires_at=expiry.expires_at,
        allow_grace=True,
    )
    db.commit()
    return RefreshSessionResponse(
        session_token=new_token,
        expires_at=to_iso(expiry.expires_at),
        soft_refresh_after=to_iso(expiry.soft_refresh_after),
        rotated=True,
    )
