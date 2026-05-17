"""Shared helpers for family-ledger invitation/member services."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import LedgerMember


INVITATION_TTL_DAYS = 7
INVITATION_TOKEN_PREFIX = "inv_"
AUDIT_INVITATION_CREATED = "invitation_created"
AUDIT_INVITATION_ACCEPTED = "invitation_accepted"
AUDIT_INVITATION_REVOKED = "invitation_revoked"
AUDIT_MEMBER_ROLE_CHANGED = "member_role_changed"
AUDIT_MEMBER_DISABLED = "member_disabled"
AUDIT_OWNER_TRANSFERRED = "owner_transferred"


def new_invite_token() -> str:
    return f"{INVITATION_TOKEN_PREFIX}{secrets.token_urlsafe(24)}"


def clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 80:
        raise AppError("invitation_note_too_long", status_code=422)
    return cleaned


def active_member_for_account(
    db: Session, *, ledger_id: str, account_id: int
) -> LedgerMember | None:
    return db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )


def require_active_owner(
    db: Session, *, ledger_id: str, account_id: int
) -> LedgerMember:
    member = active_member_for_account(
        db, ledger_id=ledger_id, account_id=account_id
    )
    if member is None or member.role != "owner":
        raise AppError("permission_denied", status_code=403)
    return member


def active_member_by_id(
    db: Session, *, ledger_id: str, member_id: int
) -> LedgerMember | None:
    return db.scalar(
        select(LedgerMember)
        .where(LedgerMember.id == member_id)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )


__all__ = [
    "AUDIT_INVITATION_ACCEPTED",
    "AUDIT_INVITATION_CREATED",
    "AUDIT_INVITATION_REVOKED",
    "AUDIT_MEMBER_DISABLED",
    "AUDIT_MEMBER_ROLE_CHANGED",
    "AUDIT_OWNER_TRANSFERRED",
    "INVITATION_TOKEN_PREFIX",
    "INVITATION_TTL_DAYS",
    "active_member_by_id",
    "active_member_for_account",
    "clean_note",
    "new_invite_token",
    "require_active_owner",
]
