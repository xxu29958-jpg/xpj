"""Ledger management service.

This module owns the v0.4-alpha1 multi-ledger primitives consumed by the
``/api/ledgers`` routes and Owner Console. The HTTP layer must never inspect
SQLAlchemy models or build ledger queries directly; route handlers call into
the helpers exposed here so account/membership/role rules stay in one place.

Key invariants:

* Ledger ownership is decided server-side from ``AuthContext.account_id``;
  callers MUST NOT trust ``ledger_id`` taken from request bodies for cross
  ledger reads or writes.
* ``switch_ledger`` revokes the caller's previous app-scoped session token
  and issues a new ledger-scoped one for the same ``(account, device)`` pair
  to prevent old tokens from reading the previous ledger after a switch.
* Database-internal autoincrement IDs are never returned; only the public
  ``ledger_id`` string is surfaced.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.identity_service import (
    _ensure_membership,
)
from app.services.session_lifecycle_service import rotate_app_token_for_ledger
from app.services.time_service import to_iso
from app.tenants import DEFAULT_TENANT_ID

LEDGER_ID_PREFIX = "ledger_"
LEDGER_NAME_MAX_LEN = 60
LEDGER_ID_RANDOM_BYTES = 6  # 12 hex chars; ledger_id stays well under 64 chars.


@dataclass(frozen=True)
class LedgerSummary:
    ledger_id: str
    name: str
    role: str
    is_default: bool
    created_at: str | None
    archived_at: str | None


@dataclass(frozen=True)
class SwitchLedgerResult:
    session_token: str
    ledger_id: str
    ledger_name: str
    role: str
    is_default: bool
    created_at: str | None
    archived_at: str | None
    account_name: str
    device_name: str


def _normalize_ledger_name(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise AppError("ledger_name_required", status_code=422)
    if len(cleaned) > LEDGER_NAME_MAX_LEN:
        raise AppError("ledger_name_too_long", status_code=422)
    return cleaned


def _new_ledger_id(db: Session) -> str:
    """Generate a unique public ``ledger_id``. Retries on the rare collision."""
    for _ in range(8):
        candidate = f"{LEDGER_ID_PREFIX}{secrets.token_hex(LEDGER_ID_RANDOM_BYTES)}"
        if db.scalar(select(Ledger.id).where(Ledger.ledger_id == candidate).limit(1)) is None:
            return candidate
    raise AppError("server_error", status_code=500)


def _summary(ledger: Ledger, role: str) -> LedgerSummary:
    return LedgerSummary(
        ledger_id=ledger.ledger_id,
        name=ledger.name,
        role=role,
        is_default=(ledger.ledger_id == DEFAULT_TENANT_ID),
        created_at=to_iso(ledger.created_at),
        archived_at=to_iso(ledger.archived_at),
    )


def list_ledgers_for_account(db: Session, *, account_id: int) -> list[LedgerSummary]:
    """Return every active ledger the account is an active member of.

    Sort order keeps ``DEFAULT_TENANT_ID`` first (so UI defaults are stable),
    then by Ledger.id ascending. Archived ledgers and disabled memberships
    are excluded.
    """
    rows = list(
        db.execute(
            select(Ledger, LedgerMember.role)
            .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
            .where(LedgerMember.account_id == account_id)
            .where(LedgerMember.disabled_at.is_(None))
            .where(Ledger.archived_at.is_(None))
            .order_by(Ledger.id.asc())
        ).all()
    )
    summaries = [_summary(ledger, role) for ledger, role in rows]
    summaries.sort(key=lambda s: (0 if s.is_default else 1, s.ledger_id))
    return summaries


def list_managed_ledgers_for_account(db: Session, *, account_id: int) -> list[LedgerSummary]:
    """Return active ledgers where the account is the active owner.

    Use this for management surfaces. Plain visibility is broader than
    authority: a member/viewer can see a ledger, but must not mint pairing
    codes, manage upload links, or revoke devices for it.
    """

    return [
        summary
        for summary in list_ledgers_for_account(db, account_id=account_id)
        if summary.role == "owner"
    ]


def managed_ledger_ids_for_account(db: Session, *, account_id: int) -> set[str]:
    return {
        summary.ledger_id
        for summary in list_managed_ledgers_for_account(db, account_id=account_id)
    }


def get_ledger_for_account(
    db: Session, *, account_id: int, ledger_id: str
) -> tuple[Ledger, str]:
    """Return ``(ledger, role)`` if the account has active membership.

    Raises ``AppError("ledger_forbidden", 403)`` when the ledger is archived,
    missing, or the account is not an active member. The same error code is
    used for "missing" and "forbidden" so callers cannot probe the ledger
    namespace of other accounts.
    """
    row = db.execute(
        select(Ledger, LedgerMember.role)
        .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
        .where(Ledger.ledger_id == ledger_id)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    ).first()
    if row is None:
        raise AppError("ledger_forbidden", status_code=403)
    return row[0], row[1]


def create_ledger(db: Session, *, account_id: int, name: str) -> LedgerSummary:
    """Create a new ledger owned by ``account_id`` and return the summary.

    The caller's authorization (e.g. owner/admin scope) is enforced by the
    HTTP layer; this function only enforces server-side invariants:

    * ``name`` is normalized and length-checked.
    * A fresh public ``ledger_id`` is minted; collisions retry.
    * The creating account is recorded as ``owner`` member.
    """
    cleaned = _normalize_ledger_name(name)
    account = db.get(Account, account_id)
    if account is None or account.disabled_at is not None:
        raise AppError("invalid_token", status_code=401)

    ledger_id = _new_ledger_id(db)
    ledger = Ledger(ledger_id=ledger_id, name=cleaned, owner_account_id=account.id)
    db.add(ledger)
    db.flush()
    _ensure_membership(db, ledger.ledger_id, account.id, "owner")
    db.commit()
    db.refresh(ledger)
    return _summary(ledger, "owner")


def switch_ledger(
    db: Session,
    *,
    current_token_value: str,
    account_id: int,
    device_id: int,
    target_ledger_id: str,
) -> SwitchLedgerResult:
    """Switch the calling device to ``target_ledger_id`` and rotate the token.

    Steps (atomic per request):

    1. Verify the account is an active member of the target ledger.
    2. Revoke the caller's current app-scoped token so it cannot keep
       reading the previous ledger after the swap.
    3. Issue a new app-scoped ``AuthToken`` bound to ``(account, device,
       target_ledger_id)``.
    4. Commit. If any step fails, the transaction rolls back and the caller
       keeps their original token.
    """
    ledger, role = get_ledger_for_account(
        db, account_id=account_id, ledger_id=target_ledger_id
    )
    account = db.get(Account, account_id)
    device = db.get(Device, device_id)
    if account is None or device is None:
        raise AppError("invalid_token", status_code=401)

    new_token, switched_at = rotate_app_token_for_ledger(
        db,
        current_token_value=current_token_value,
        account_id=account.id,
        device_id=device.id,
        target_ledger_id=ledger.ledger_id,
    )
    device.last_seen_at = switched_at
    db.commit()

    return SwitchLedgerResult(
        session_token=new_token,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        role=role,
        is_default=(ledger.ledger_id == DEFAULT_TENANT_ID),
        created_at=to_iso(ledger.created_at),
        archived_at=to_iso(ledger.archived_at),
        account_name=account.display_name,
        device_name=device.device_name,
    )


def ledger_member_counts(db: Session, *, ledger_id: str) -> dict[str, int]:
    """Lightweight counters used by Owner Console ledger management page.

    Returns a dict with active device count and active session token count.
    Expense counts are intentionally not included here to keep the service
    focused; ``/owner/ledgers`` composes Expense counters via ``stats_service``
    or its own queries.
    """
    devices = int(
        db.scalar(
            select(func.count(func.distinct(AuthToken.device_id)))
            .where(AuthToken.ledger_id == ledger_id)
            .where(AuthToken.revoked_at.is_(None))
        )
        or 0
    )
    tokens = int(
        db.scalar(
            select(func.count())
            .select_from(AuthToken)
            .where(AuthToken.ledger_id == ledger_id)
            .where(AuthToken.revoked_at.is_(None))
        )
        or 0
    )
    return {"active_devices": devices, "active_tokens": tokens}


__all__ = [
    "LedgerSummary",
    "SwitchLedgerResult",
    "create_ledger",
    "get_ledger_for_account",
    "ledger_member_counts",
    "list_ledgers_for_account",
    "list_managed_ledgers_for_account",
    "managed_ledger_ids_for_account",
    "switch_ledger",
]
