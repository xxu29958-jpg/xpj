from __future__ import annotations

from hmac import compare_digest

from fastapi import Header

from app.config import get_settings
from app.errors import AppError
from app.tenants import AdminContext, Tenant, admin_context, tenant_from_app_token, tenant_from_upload_token


def _matches(actual: str | None, expected: str) -> bool:
    if not actual:
        return False
    return compare_digest(actual, expected)


def get_current_upload_tenant(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> Tenant:
    return tenant_from_upload_token(upload_token)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)
    return authorization.removeprefix("Bearer ").strip()


def get_current_app_tenant(authorization: str | None = Header(default=None)) -> Tenant:
    return tenant_from_app_token(_bearer_token(authorization))


def get_current_admin_context(authorization: str | None = Header(default=None)) -> AdminContext:
    settings = get_settings()
    token = _bearer_token(authorization)
    if not _matches(token, settings.admin_token):
        raise AppError("invalid_token", status_code=401)
    return admin_context()


def verify_upload_token(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> None:
    get_current_upload_tenant(upload_token)


def verify_app_token(authorization: str | None = Header(default=None)) -> None:
    get_current_app_tenant(authorization)


def verify_admin_token(authorization: str | None = Header(default=None)) -> None:
    get_current_admin_context(authorization)
