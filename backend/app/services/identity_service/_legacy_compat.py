"""Legacy app_token / upload_token recognizers (pre-v0.3 tenant config)."""

from __future__ import annotations

from hmac import compare_digest

from app.config import get_settings
from app.tenants import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    Tenant,
    configured_tenants,
)


def _legacy_token_values(kind: str) -> set[str]:
    settings = get_settings()
    values: set[str] = set()
    if kind == "app" and settings.app_token:
        values.add(settings.app_token)
    if kind == "upload" and settings.upload_token:
        values.add(settings.upload_token)
    for tenant in configured_tenants():
        if kind == "app" and tenant.app_token:
            values.add(tenant.app_token)
        if kind == "upload" and tenant.upload_token:
            values.add(tenant.upload_token)
    return values


def is_legacy_app_token(token: str | None) -> bool:
    return _matches_any(token, _legacy_token_values("app"))


def is_legacy_upload_token(token: str | None) -> bool:
    return _matches_any(token, _legacy_token_values("upload"))


def _matches_any(token: str | None, values: set[str]) -> bool:
    if not token:
        return False
    return any(compare_digest(token, value) for value in values if value)


def _legacy_ledgers_from_config() -> list[Tenant]:
    tenants = list(configured_tenants())
    return tenants or [Tenant(id=DEFAULT_TENANT_ID, name=DEFAULT_TENANT_NAME, upload_token="", app_token="")]
