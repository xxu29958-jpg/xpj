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
    RefreshSessionRequest,
    RefreshSessionResponse,
)
from app.services.identity_service import authenticate_session_token, pair_device
from app.services.server_identity_service import read_server_data_identity
from app.services.session_refresh_service import (
    refresh_legacy_app_session,
    refresh_or_recover_app_session,
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
def check_auth(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> AuthCheckResponse:
    server = read_server_data_identity(db)
    return AuthCheckResponse(
        server_id=server.server_id,
        data_generation=server.data_generation,
        account_public_id=auth.account_public_id,
        device_public_id=auth.device_public_id,
        account_name=auth.account_name,
        ledger_id=auth.ledger_id,
        ledger_name=auth.ledger_name,
        device_name=auth.device_name,
        role=auth.role,
        scope=auth.scope,
    )


@router.post("/pair", response_model=PairResponse)
def pair(payload: PairRequest, request: Request, db: Session = Depends(get_db)) -> PairResponse:
    if payload.pairing_attempt_id is None or payload.pairing_attempt_secret is None:
        raise AppError(
            "client_upgrade_required",
            "当前 Android 客户端无法安全恢复中断的绑定，请升级后重试。",
            status_code=409,
        )
    remote_id = pairing_rate_limit_key(request)
    result = pair_device(
        db,
        pairing_code=payload.pairing_code,
        pairing_attempt_id=str(payload.pairing_attempt_id),
        pairing_attempt_secret=payload.pairing_attempt_secret,
        device_name=payload.device_name,
        platform=payload.platform,
        remote_id=remote_id,
    )
    server = read_server_data_identity(db)
    return PairResponse(
        session_token=result.session_token,
        pairing_attempt_id=result.pairing_attempt_id,
        server_id=server.server_id,
        data_generation=server.data_generation,
        account_public_id=result.account_public_id,
        device_public_id=result.device_public_id,
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
    payload: RefreshSessionRequest | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> RefreshSessionResponse:
    """Rotate an app token with a process-death-safe replay proof."""

    current_token = _bearer_token_value(authorization)
    if get_settings().app_token_ttl_days <= 0:
        authenticate_session_token(db, current_token, {"app"})
        return RefreshSessionResponse(
            session_token=current_token,
            expires_at=None,
            soft_refresh_after=None,
            rotated=False,
        )
    if payload is None:
        legacy = refresh_legacy_app_session(
            db,
            source_token_value=current_token,
        )
        db.commit()
        return RefreshSessionResponse(
            session_token=legacy.session_token,
            expires_at=to_iso(legacy.expires_at),
            soft_refresh_after=to_iso(legacy.soft_refresh_after),
            rotated=False,
        )
    result = refresh_or_recover_app_session(
        db,
        source_token_value=current_token,
        refresh_attempt_id=str(payload.refresh_attempt_id),
        refresh_attempt_secret=payload.refresh_attempt_secret,
    )
    db.commit()
    return RefreshSessionResponse(
        session_token=result.session_token,
        refresh_attempt_id=result.refresh_attempt_id,
        expires_at=to_iso(result.expires_at),
        soft_refresh_after=to_iso(result.soft_refresh_after),
        rotated=True,
    )
