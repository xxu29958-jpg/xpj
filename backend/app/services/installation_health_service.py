"""Database readiness identity for the loopback installation probe."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
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
    """Low-cardinality deployment facts safe for the loopback Manager."""

    mobile_endpoint_state: Literal["local_only", "public_configured_unverified"]
    android_binding_state: Literal["setup_required", "configured_unverified"]
    iphone_upload_state: Literal["setup_required", "configured_unverified"]


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


def installation_mobile_capabilities(public_base_url: str) -> InstallationMobileCapabilities:
    """Project configured mobile access without claiming external reachability."""
    host = ""
    try:
        host = (urlsplit(public_base_url).hostname or "").casefold()
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = not host
    configured = bool(public_base_url) and bool(host) and not loopback
    if configured:
        return InstallationMobileCapabilities(
            mobile_endpoint_state="public_configured_unverified",
            android_binding_state="configured_unverified",
            iphone_upload_state="configured_unverified",
        )
    return InstallationMobileCapabilities(
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
