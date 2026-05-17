"""Ledger audit-log helpers for invitation and member management."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, LedgerAuditLog
from app.services.time_service import to_iso


@dataclass(frozen=True)
class LedgerAuditSummary:
    public_id: str
    ledger_id: str
    action: str
    actor_account_public_id: str | None
    actor_account_name: str | None
    target_account_public_id: str | None
    target_account_name: str | None
    target_member_id: int | None
    invitation_public_id: str | None
    previous_role: str | None
    new_role: str | None
    result: str
    detail: str | None
    created_at: str | None


def clean_detail(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:500]


def add_audit_log(
    db: Session,
    *,
    ledger_id: str,
    action: str,
    actor_account_id: int | None,
    target_account_id: int | None = None,
    target_member_id: int | None = None,
    invitation_public_id: str | None = None,
    previous_role: str | None = None,
    new_role: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        LedgerAuditLog(
            ledger_id=ledger_id,
            action=action,
            actor_account_id=actor_account_id,
            target_account_id=target_account_id,
            target_member_id=target_member_id,
            invitation_public_id=invitation_public_id,
            previous_role=previous_role,
            new_role=new_role,
            result="success",
            detail=clean_detail(detail),
        )
    )


def account_identity(
    db: Session, account_id: int | None
) -> tuple[str | None, str | None]:
    if account_id is None:
        return None, None
    account = db.get(Account, account_id)
    if account is None:
        return None, None
    return account.public_id, account.display_name


def audit_summary(db: Session, row: LedgerAuditLog) -> LedgerAuditSummary:
    actor_public_id, actor_name = account_identity(db, row.actor_account_id)
    target_public_id, target_name = account_identity(db, row.target_account_id)
    return LedgerAuditSummary(
        public_id=row.public_id,
        ledger_id=row.ledger_id,
        action=row.action,
        actor_account_public_id=actor_public_id,
        actor_account_name=actor_name,
        target_account_public_id=target_public_id,
        target_account_name=target_name,
        target_member_id=row.target_member_id,
        invitation_public_id=row.invitation_public_id,
        previous_role=row.previous_role,
        new_role=row.new_role,
        result=row.result,
        detail=row.detail,
        created_at=to_iso(row.created_at),
    )


def list_audit_logs(
    db: Session, *, ledger_id: str, limit: int = 100
) -> list[LedgerAuditSummary]:
    capped_limit = max(1, min(limit, 200))
    rows = list(
        db.scalars(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.ledger_id == ledger_id)
            .order_by(LedgerAuditLog.created_at.desc(), LedgerAuditLog.id.desc())
            .limit(capped_limit)
        )
    )
    return [audit_summary(db, row) for row in rows]


__all__ = [
    "LedgerAuditSummary",
    "account_identity",
    "add_audit_log",
    "audit_summary",
    "clean_detail",
    "list_audit_logs",
]
