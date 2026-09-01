"""Database readiness identity for the loopback installation probe."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import Account, Ledger, LedgerMember


class InstallationDatabaseIdentityError(RuntimeError):
    """The connected database does not match this backend's configured store."""


@dataclass(frozen=True)
class InstallationMobileCapabilities:
    """Bounded deployment facts safe for the loopback Manager."""

    public_origin: str | None
    mobile_endpoint_state: Literal["local_only", "public_configured_unverified"]
    android_binding_state: Literal["setup_required", "configured_unverified"]
    iphone_upload_state: Literal["setup_required", "configured_unverified"]


_OWNER_RECOVERY_MESSAGES = MappingProxyType({
    "development": "服务未初始化，请先运行 bootstrap_dev_owner.ps1。",
    "managed_host": "当前安装缺少可用拥有者身份。普通修复不会重建身份，请先导出诊断包交给维护者处理。",
    "operator": "服务未初始化，请联系部署管理员完成初始化。",
})


def owner_recovery_message(owner_recovery_channel: str) -> str:
    """Return the recovery instruction declared by the deployment authority."""
    return _OWNER_RECOVERY_MESSAGES[owner_recovery_channel]


def _looks_like_legacy_ipv4_literal(host: str) -> bool:
    """Reject numeric host spellings that URL stacks may reinterpret as IPv4."""
    parts = host.split(".")
    return bool(parts) and all(
        part.isdecimal()
        or (
            part.casefold().startswith("0x")
            and len(part) > 2
            and all(char in "0123456789abcdef" for char in part[2:].casefold())
        )
        for part in parts
    )


def _canonical_mobile_endpoint_host(host: str) -> str | None:
    """Normalize one host before applying phone-endpoint safety policy."""
    candidate = host[:-1] if host.endswith(".") else host
    if not candidate or candidate.endswith(".") or "%" in candidate:
        return None

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        # Python and OkHttp use different IDNA profiles. Keep the authority
        # byte-stable across pairing/upload consumers until one shared profile
        # is an explicit protocol dependency.
        if not candidate.isascii():
            return None
        candidate = candidate.casefold()
        if not candidate or len(candidate) > 253:
            return None
        labels = candidate.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in label)
            for label in labels
        ):
            return None
        if _looks_like_legacy_ipv4_literal(candidate):
            return None
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return candidate

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return None
    if address.is_loopback or address.is_unspecified:
        return None
    return address.compressed


def installation_runtime_access_state(
    scope: Mapping[str, object],
) -> Literal["available", "repair_required"]:
    """Read the host adapter's request-scoped maintenance projection."""
    state = scope.get("state")
    if not isinstance(state, Mapping):
        return "available"
    value = state.get("ticketbox_runtime_access_state")
    if value is None:
        return "available"
    return "available" if value == "available" else "repair_required"


def installation_owner_state(db: Session) -> Literal["configured", "recovery_required"]:
    """Report whether an active ledger owner can still anchor local administration."""
    owner_id = db.scalar(
        select(LedgerMember.id)
        .join(Ledger, Ledger.ledger_id == LedgerMember.ledger_id)
        .join(Account, Account.id == LedgerMember.account_id)
        .where(LedgerMember.role == "owner")
        .where(LedgerMember.disabled_at.is_(None))
        .where(Ledger.owner_account_id == Account.id)
        .where(Ledger.archived_at.is_(None))
        .where(Account.disabled_at.is_(None))
        .limit(1)
    )
    return "configured" if owner_id is not None else "recovery_required"


def configured_mobile_endpoint_url(public_base_url: str) -> str | None:
    """Return one phone-usable HTTPS origin, without claiming reachability."""
    value = public_base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        return None
    canonical_host = _canonical_mobile_endpoint_host(host)
    if canonical_host is None:
        return None
    if canonical_host == "localhost" or canonical_host.endswith(".localhost"):
        return None
    authority = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    if port not in {None, 443}:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def installation_mobile_capabilities(public_base_url: str) -> InstallationMobileCapabilities:
    """Project configured mobile access without claiming external reachability."""
    public_origin = configured_mobile_endpoint_url(public_base_url)
    if public_origin is not None:
        return InstallationMobileCapabilities(
            public_origin=public_origin,
            mobile_endpoint_state="public_configured_unverified",
            android_binding_state="configured_unverified",
            iphone_upload_state="configured_unverified",
        )
    return InstallationMobileCapabilities(
        public_origin=None,
        mobile_endpoint_state="local_only",
        android_binding_state="setup_required",
        iphone_upload_state="setup_required",
    )


def assert_installation_database_ready(db: Session, *, database_url: str) -> None:
    """Prove connectivity, configured DB/role identity, and initialized schema."""
    db.execute(select(func.set_config("statement_timeout", "1500ms", True)))
    database_name, role_name, schema_ready = db.execute(
        select(
            func.current_database(),
            func.current_user(),
            func.to_regclass("public.accounts").is_not(None),
        )
    ).one()
    configured = make_url(database_url)
    if (
        database_name != configured.database
        or role_name != configured.username
        or schema_ready is not True
    ):
        raise InstallationDatabaseIdentityError
