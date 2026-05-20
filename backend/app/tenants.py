from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hmac import compare_digest
import json
import re
from typing import Any

from app.config import get_settings
from app.errors import AppError


DEFAULT_TENANT_ID = "owner"
DEFAULT_TENANT_NAME = "我的小票夹"
TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    upload_token: str
    app_token: str


@dataclass(frozen=True)
class AdminContext:
    tenants: tuple[Tenant, ...]
    default_tenant: Tenant


@dataclass(frozen=True)
class AuthContext:
    account_id: int
    account_name: str
    ledger_id: str
    ledger_name: str
    device_id: int
    device_name: str
    role: str
    scope: str

    @property
    def tenant_id(self) -> str:
        return self.ledger_id

    @property
    def tenant_name(self) -> str:
        return self.ledger_name

    @property
    def token_type(self) -> str:
        return self.scope


def _clean_tenant_id(value: str) -> str:
    tenant_id = value.strip()
    if not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise AppError("server_error", status_code=500)
    return tenant_id


def _clean_tenant_name(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned or DEFAULT_TENANT_NAME


def _tenant_from_mapping(raw: dict[str, Any]) -> Tenant:
    return Tenant(
        id=_clean_tenant_id(str(raw.get("id") or "")),
        name=_clean_tenant_name(str(raw.get("name") or "")),
        upload_token=str(raw.get("upload_token") or "").strip(),
        app_token=str(raw.get("app_token") or "").strip(),
    )


def _legacy_tenant() -> Tenant:
    settings = get_settings()
    return Tenant(
        id=DEFAULT_TENANT_ID,
        name=DEFAULT_TENANT_NAME,
        upload_token=settings.upload_token,
        app_token=settings.app_token,
    )


def reset_tenant_cache() -> None:
    """Drop the cached tenants snapshot.

    Mirrors ``app.config.reset_settings_cache`` — production doesn't use
    this (TENANTS_JSON is immutable for the process lifetime). Tests
    and dev tooling that change tenant config between runs call it
    explicitly.
    """
    configured_tenants.cache_clear()


@lru_cache
def configured_tenants() -> tuple[Tenant, ...]:
    settings = get_settings()
    if not settings.tenants_json:
        return (_legacy_tenant(),)

    try:
        parsed = json.loads(settings.tenants_json)
    except json.JSONDecodeError as exc:
        raise AppError("server_error", status_code=500) from exc

    if not isinstance(parsed, list):
        raise AppError("server_error", status_code=500)

    tenants = tuple(_tenant_from_mapping(item) for item in parsed if isinstance(item, dict))
    if not tenants:
        raise AppError("server_error", status_code=500)

    ids = [tenant.id for tenant in tenants]
    if len(ids) != len(set(ids)):
        raise AppError("server_error", status_code=500)
    return tenants


def default_tenant() -> Tenant:
    tenants = configured_tenants()
    for tenant in tenants:
        if tenant.id == DEFAULT_TENANT_ID:
            return tenant
    return tenants[0]


def tenant_from_upload_token(upload_token: str | None) -> Tenant:
    if not upload_token:
        raise AppError("invalid_token", status_code=401)
    for tenant in configured_tenants():
        if compare_digest(upload_token, tenant.upload_token):
            return tenant
    raise AppError("invalid_token", status_code=401)


def tenant_from_app_token(app_token: str | None) -> Tenant:
    if not app_token:
        raise AppError("invalid_token", status_code=401)
    for tenant in configured_tenants():
        if compare_digest(app_token, tenant.app_token):
            return tenant
    raise AppError("invalid_token", status_code=401)


def admin_context() -> AdminContext:
    return AdminContext(tenants=configured_tenants(), default_tenant=default_tenant())
