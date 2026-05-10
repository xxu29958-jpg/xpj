from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import get_current_owner_or_admin_context
from app.config import get_settings
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


# Process-local set of bootstrap secrets that have already been consumed by a
# successful owner initialization. Loopback / IP heuristics are intentionally
# not used here: under Cloudflare Tunnel the apparent client host is the local
# loopback address, so loopback cannot be trusted as a privilege check.
_CONSUMED_BOOTSTRAP_SECRETS: set[str] = set()


def _bootstrap_disabled_error() -> AppError:
    return AppError(
        "bootstrap_disabled",
        "Bootstrap 接口默认禁用，需要显式开启 ENABLE_HTTP_BOOTSTRAP 并配置一次性 secret。",
        status_code=404,
    )


def require_http_bootstrap_secret(request: Request) -> str:
    settings = get_settings()
    if not settings.enable_http_bootstrap:
        raise _bootstrap_disabled_error()

    expected = (settings.http_bootstrap_secret or "").strip()
    if not expected:
        # Fail closed: enabled without a secret is treated as disabled.
        raise _bootstrap_disabled_error()

    provided = request.headers.get("X-Bootstrap-Secret", "")
    if not provided:
        raise AppError(
            "bootstrap_secret_required",
            "缺少 X-Bootstrap-Secret 请求头。",
            status_code=401,
        )

    if expected in _CONSUMED_BOOTSTRAP_SECRETS or not hmac.compare_digest(
        provided, expected
    ):
        raise AppError(
            "invalid_bootstrap_secret",
            "Bootstrap secret 无效或已使用。",
            status_code=401,
        )

    return expected


def _mark_secret_consumed(secret: str) -> None:
    if secret:
        _CONSUMED_BOOTSTRAP_SECRETS.add(secret)


@router.post("/owner", response_model=BootstrapOwnerResponse)
def post_bootstrap_owner(
    payload: BootstrapOwnerRequest,
    secret: str = Depends(require_http_bootstrap_secret),
    db: Session = Depends(get_db),
) -> BootstrapOwnerResponse:
    result = bootstrap_owner(
        db,
        account_name=payload.account_name,
        ledger_name=payload.ledger_name,
        device_name=payload.device_name,
        default_timezone=payload.default_timezone,
    )
    _mark_secret_consumed(secret)
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
