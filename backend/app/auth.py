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
