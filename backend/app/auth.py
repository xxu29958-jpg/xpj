from __future__ import annotations

from hmac import compare_digest

from fastapi import Header

from app.config import get_settings
from app.errors import AppError
from app.tenants import AuthContext, Tenant, admin_context, tenant_from_app_token, tenant_from_upload_token


def _matches(actual: str | None, expected: str) -> bool:
    if not actual:
        return False
    return compare_digest(actual, expected)


def _auth_context(tenant: Tenant, token_type: str) -> AuthContext:
    return AuthContext(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        token_type=token_type,
    )


def get_current_upload_context(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> AuthContext:
    return _auth_context(tenant_from_upload_token(upload_token), "upload")


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)
    return authorization.removeprefix("Bearer ").strip()


def get_current_app_context(authorization: str | None = Header(default=None)) -> AuthContext:
    return _auth_context(tenant_from_app_token(_bearer_token(authorization)), "app")


def get_current_admin_context(authorization: str | None = Header(default=None)) -> AuthContext:
    settings = get_settings()
    token = _bearer_token(authorization)
    if not _matches(token, settings.admin_token):
        raise AppError("invalid_token", status_code=401)
    return _auth_context(admin_context().default_tenant, "admin")


def verify_upload_token(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> AuthContext:
    return get_current_upload_context(upload_token)


def verify_app_token(authorization: str | None = Header(default=None)) -> AuthContext:
    return get_current_app_context(authorization)


def verify_admin_token(authorization: str | None = Header(default=None)) -> AuthContext:
    return get_current_admin_context(authorization)
