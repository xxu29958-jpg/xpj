from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_admin_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.models import BootstrapSecretConsumption
from app.schemas import (
    BootstrapOwnerRequest,
    BootstrapOwnerResponse,
    PairingCodeCreateRequest,
    PairingCodeResponse,
)
from app.services.admin_scope_service import require_admin_manages_current_ledger
from app.services.identity_service import bootstrap_owner, create_pairing_code, hash_secret
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
    db: Session = Depends(get_db),
) -> str:
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

    secret_hash = hash_secret(expected)
    already_consumed = db.scalar(
        select(BootstrapSecretConsumption.secret_hash)
        .where(BootstrapSecretConsumption.secret_hash == secret_hash)
        .limit(1)
    )
    if already_consumed is not None or not hmac.compare_digest(provided, expected):
        raise AppError(
            "invalid_bootstrap_secret",
            "Bootstrap secret 无效或已使用。",
            status_code=401,
        )

    return expected


def _consume_secret(db: Session, secret: str) -> None:
    """Mark a one-shot bootstrap secret as consumed.

    Raises ``invalid_bootstrap_secret`` only when the failure is the expected
    one — another request consumed the same hash between the precheck in
    ``require_http_bootstrap_secret`` and this insert. All other integrity
    errors propagate so we never silently translate an unrelated schema
    failure into "secret already used".
    """

    if not secret:
        return
    secret_hash = hash_secret(secret)
    try:
        db.add(BootstrapSecretConsumption(secret_hash=secret_hash))
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        already_consumed = db.scalar(
            select(BootstrapSecretConsumption.secret_hash)
            .where(BootstrapSecretConsumption.secret_hash == secret_hash)
            .limit(1)
        )
        if already_consumed is not None:
            raise AppError(
                "invalid_bootstrap_secret",
                "Bootstrap secret is invalid or already used.",
                status_code=401,
            ) from exc
        raise


def _mark_secret_consumed(db: Session, secret: str) -> None:
    if secret:
        _consume_secret(db, secret)
        db.commit()


@router.post("/owner", response_model=BootstrapOwnerResponse)
def post_bootstrap_owner(
    payload: BootstrapOwnerRequest,
    secret: str = Depends(require_http_bootstrap_secret),
    db: Session = Depends(get_db),
) -> BootstrapOwnerResponse:
    try:
        result = bootstrap_owner(
            db,
            account_name=payload.account_name,
            ledger_name=payload.ledger_name,
            device_name=payload.device_name,
            default_timezone=payload.default_timezone,
            commit=False,
        )
        _consume_secret(db, secret)
        db.commit()
    except Exception:
        # AppError translation for the race-condition case is owned by
        # _consume_secret. Everything else (real schema bug, unexpected
        # IntegrityError, etc.) rolls back and propagates as-is so the
        # global handler surfaces a generic server_error rather than a
        # misleading "secret already used".
        db.rollback()
        raise
    return BootstrapOwnerResponse(**result.__dict__)


@router.post("/pairing-codes", response_model=PairingCodeResponse)
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
    )
    return PairingCodeResponse(
        pairing_code=result.pairing_code,
        ledger_name=result.ledger_name,
        expires_at=result.expires_at,
    )
