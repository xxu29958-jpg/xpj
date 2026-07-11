"""Block destructive identity changes while HTTP bootstrap is exposed."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import AuthToken, UploadLink
from app.services.session_lifecycle_service import (
    BOOTSTRAP_SECRET_MIN_BYTES,
    derive_bootstrap_admin_token,
    hash_secret,
)


@dataclass(frozen=True)
class _BootstrapPrincipal:
    account_id: int
    device_id: int
    ledger_id: str


def _configured_bootstrap_principal(db: Session) -> _BootstrapPrincipal | None:
    settings = get_settings()
    secret = settings.http_bootstrap_secret
    if (
        not settings.enable_http_bootstrap
        or len(secret.encode("utf-8")) < BOOTSTRAP_SECRET_MIN_BYTES
    ):
        return None
    token = db.scalar(
        select(AuthToken)
        .where(
            AuthToken.token_hash
            == hash_secret(derive_bootstrap_admin_token(secret)),
            AuthToken.scope == "admin",
        )
        .limit(1)
    )
    if token is None:
        return None
    return _BootstrapPrincipal(
        account_id=token.account_id,
        device_id=token.device_id,
        ledger_id=token.ledger_id,
    )


def _device_reaches_ledger(db: Session, *, device_id: int, ledger_id: str) -> bool:
    token_binding = exists().where(
        AuthToken.device_id == device_id,
        AuthToken.ledger_id == ledger_id,
    )
    upload_binding = exists().where(
        UploadLink.device_id == device_id,
        UploadLink.ledger_id == ledger_id,
    )
    return bool(db.scalar(select(token_binding | upload_binding)))


def assert_bootstrap_sensitive_mutation_allowed(
    db: Session,
    *,
    actor_account_id: int | None = None,
    ledger_ids: set[str] | None = None,
    target_device_id: int | None = None,
) -> None:
    """Reject identity mutations that could make exposure recovery permanent.

    The deterministic admin credential identifies the installation principal
    without adding mutable schema state. While that high-entropy credential is
    configured on the HTTP bootstrap surface, neither that account nor its
    bootstrap ledger/device graph may perform destructive identity changes.
    The offline maintenance recovery does not call this guard.
    """

    principal = _configured_bootstrap_principal(db)
    if principal is None:
        return
    blocked = actor_account_id == principal.account_id
    if ledger_ids is not None:
        blocked = blocked or principal.ledger_id in ledger_ids
    if target_device_id is not None:
        blocked = blocked or _device_reaches_ledger(
            db,
            device_id=target_device_id,
            ledger_id=principal.ledger_id,
        )
    if blocked:
        raise AppError(
            "bootstrap_recovery_required",
            "初始化凭据仍在安全确认中，请先完成安装修复。",
            status_code=409,
        )
