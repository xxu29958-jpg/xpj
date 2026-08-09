from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import get_current_admin_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.network_boundary import require_admin_network_boundary
from app.schemas import (
    BootstrapOwnerRequest,
    BootstrapOwnerResponse,
    InstallationOwnerBootstrapRequest,
    InstallationOwnerBootstrapResponse,
    PairingCodeCreateRequest,
    PairingCodeResponse,
)
from app.services.admin_scope_service import require_admin_manages_current_ledger
from app.services.identity_service import (
    bootstrap_installation_owner,
    bootstrap_owner,
    create_pairing_code,
)
from app.services.session_lifecycle_service import BOOTSTRAP_SECRET_MIN_BYTES
from app.tenants import AuthContext

router = APIRouter(prefix="/api/bootstrap", tags=["bootstrap"])


# Bootstrap secret consumption is persisted by secret hash. Loopback / IP
# heuristics are intentionally not used here: under Cloudflare Tunnel the
# apparent client host is local loopback, so loopback cannot be trusted as a
# privilege check.
def _bootstrap_disabled_error() -> AppError:
    return AppError(
        "bootstrap_disabled",
        "Bootstrap 接口默认禁用，需要显式开启 ENABLE_HTTP_BOOTSTRAP 并配置一次性 secret。",
        status_code=404,
    )


def require_http_bootstrap_secret(
    request: Request,
) -> str:
    settings = get_settings()
    if not settings.enable_http_bootstrap:
        raise _bootstrap_disabled_error()

    expected = (settings.http_bootstrap_secret or "").strip()
    if not expected or len(expected.encode("utf-8")) < BOOTSTRAP_SECRET_MIN_BYTES:
        # Fail closed: enabled without a secret is treated as disabled.
        raise _bootstrap_disabled_error()

    provided = request.headers.get("X-Bootstrap-Secret", "")
    if not provided:
        raise AppError(
            "bootstrap_secret_required",
            "缺少 X-Bootstrap-Secret 请求头。",
            status_code=401,
        )

    if not hmac.compare_digest(provided, expected):
        raise AppError(
            "invalid_bootstrap_secret",
            "Bootstrap secret 无效或已使用。",
            status_code=401,
        )

    return expected


@router.post("/owner", response_model=BootstrapOwnerResponse)
def post_bootstrap_owner(
    payload: BootstrapOwnerRequest,
    secret: str = Depends(require_http_bootstrap_secret),
    db: Session = Depends(get_db),
) -> BootstrapOwnerResponse:
    committed = False
    try:
        result = bootstrap_owner(
            db,
            account_name=payload.account_name,
            ledger_name=payload.ledger_name,
            device_name=payload.device_name,
            default_timezone=payload.default_timezone,
            bootstrap_secret=secret,
            commit=False,
        )
        db.commit()
        committed = True
    finally:
        if not committed:
            # Bootstrap identity rows and secret consumption share one
            # transaction; no failed attempt may burn the recovery key.
            db.rollback()
    return BootstrapOwnerResponse(**result.__dict__)


@router.post(
    "/installation-owner",
    response_model=InstallationOwnerBootstrapResponse,
)
def post_installation_owner_bootstrap(
    payload: InstallationOwnerBootstrapRequest,
    secret: str = Depends(require_http_bootstrap_secret),
    db: Session = Depends(get_db),
) -> InstallationOwnerBootstrapResponse:
    committed = False
    try:
        result = bootstrap_installation_owner(
            db,
            operation_id=payload.operation_id,
            installation_id=payload.installation_id,
            account_name=payload.account_name,
            ledger_name=payload.ledger_name,
            device_name=payload.device_name,
            bootstrap_secret=secret,
            commit=False,
        )
        db.commit()
        committed = True
    finally:
        if not committed:
            db.rollback()
    return InstallationOwnerBootstrapResponse(**result.__dict__)


@router.post(
    "/pairing-codes",
    response_model=PairingCodeResponse,
    # admin token alone is not enough — Cloudflare Tunnel forwards public
    # requests to 127.0.0.1, so without this guard a leaked admin token would
    # let an attacker mint pairing codes from the public internet. Owner
    # workflow always hits Owner Console on loopback, so this is purely a
    # defense-in-depth tightening. Mirrors admin.py / maintenance.py which
    # both attach the same guard at router level. See ENGINEERING_RULES §14
    # "暴露面与边界".
    dependencies=[Depends(require_admin_network_boundary)],
)
def post_pairing_code(
    payload: PairingCodeCreateRequest,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> PairingCodeResponse:
    require_admin_manages_current_ledger(db, auth)
    result = create_pairing_code(
        db,
        ledger_id=auth.ledger_id,
        account_id=auth.account_id,
        device_name_hint=payload.device_name_hint,
        ttl_minutes=payload.ttl_minutes,
        auth=auth,
    )
    return PairingCodeResponse(
        pairing_code=result.pairing_code,
        ledger_name=result.ledger_name,
        expires_at=result.expires_at,
    )
