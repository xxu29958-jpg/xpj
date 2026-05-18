from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.services.identity_service import (
    authenticate_session_token,
    is_legacy_app_token,
    is_legacy_upload_token,
)
from app.tenants import AuthContext


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise AppError("invalid_token", status_code=401)
    return token


def _raise_legacy_app_removed() -> None:
    raise AppError("legacy_auth_removed", "请使用新版绑定方式。", status_code=401)


def _raise_legacy_upload_removed() -> None:
    raise AppError("legacy_auth_removed", "请使用新版 iOS 上传链接。", status_code=401)


def get_current_app_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    return authenticate_session_token(db, token, {"app"})


def get_current_admin_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    return authenticate_session_token(db, token, {"admin"})


def get_current_owner_or_admin_context(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    token = _bearer_token(authorization)
    if is_legacy_app_token(token):
        _raise_legacy_app_removed()
    auth = authenticate_session_token(db, token, {"app", "admin"})
    if auth.scope != "admin" and auth.role != "owner":
        raise AppError("invalid_token", status_code=403)
    return auth


def get_current_ledger_app_context(
    ledger_id: str,
    auth: AuthContext = Depends(get_current_app_context),
) -> AuthContext:
    """App token for the ledger named in the route path.

    Use this for ``/api/ledgers/{ledger_id}/...`` routes so the path ledger
    check is a reusable auth guard instead of repeated route-body logic.
    """
    if auth.ledger_id != ledger_id:
        raise AppError("ledger_not_found", status_code=404)
    return auth


def get_current_member_manager_context(
    auth: AuthContext = Depends(get_current_ledger_app_context),
) -> AuthContext:
    """App token for the path ledger with member-management permission."""
    from app.services import permission_service

    permission_service.require_manage_members(auth)
    return auth


def get_current_writer_context(
    auth: AuthContext = Depends(get_current_app_context),
) -> AuthContext:
    """v0.4-beta1: app token with write permission (owner/member). Viewer 403."""
    from app.services import permission_service

    permission_service.require_write_expense(auth)
    return auth


def get_current_owner_app_context(
    auth: AuthContext = Depends(get_current_app_context),
) -> AuthContext:
    """v0.4-beta1: app token owned by the ledger's owner role.

    Unlike ``get_current_owner_or_admin_context`` this rejects admin-scoped
    tokens — used for endpoints (e.g. invitation create) that must be
    initiated by the actual owner account through their app session.
    """
    from app.services import permission_service

    permission_service.require_manage_members(auth)
    return auth


def get_removed_upload_context(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> AuthContext:
    if is_legacy_upload_token(upload_token):
        _raise_legacy_upload_removed()
    raise AppError("invalid_token", status_code=401)


def verify_upload_token(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> AuthContext:
    return get_removed_upload_context(upload_token)


def verify_app_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    return get_current_app_context(authorization, db)


def verify_admin_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    return get_current_admin_context(authorization, db)
