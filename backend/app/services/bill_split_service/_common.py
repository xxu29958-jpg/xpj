"""Shared constants + audit / member-load helpers for bill_split state machine."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Ledger, LedgerAuditLog, LedgerMember

INVITATION_TTL = timedelta(days=30)
WRITER_ROLES = frozenset({"owner", "member"})
SPLIT_RECEIVED_SOURCE = "bill_split_received"


def _display_name(account: Account) -> str:
    name = (account.display_name or "").strip()
    return name or f"account_{account.id}"


def _load_writer_member(
    db: Session, ledger_id: str, account_id: int
) -> LedgerMember:
    """Resolve LedgerMember + verify writer role. 403 if viewer / not member."""
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
    )
    if member is None:
        raise AppError(
            "ledger_forbidden",
            "你不在目标账本，无法操作。",
            status_code=403,
        )
    if member.role not in WRITER_ROLES:
        raise AppError(
            "ledger_forbidden",
            "请选择你有写权限的账本。",
            status_code=403,
        )
    archived_at = db.scalar(
        select(Ledger.archived_at).where(Ledger.ledger_id == ledger_id)
    )
    if archived_at is not None:
        # 归档账本「从 app 消失」(ledger lists/auth/invitations 都过滤 archived_at IS NULL);
        # bill-split 不能例外:归档账本既不能发起也不能接收分账。
        raise AppError("ledger_archived", "该账本已归档，无法操作。", status_code=409)
    return member


def _audit(
    db: Session,
    ledger_id: str,
    action: str,
    *,
    actor_account_id: int | None,
    target_account_id: int,
    invitation_public_id: str,
) -> None:
    db.add(LedgerAuditLog(
        ledger_id=ledger_id,
        action=action,
        actor_account_id=actor_account_id,
        target_account_id=target_account_id,
        invitation_public_id=invitation_public_id,
        result="success",
    ))
