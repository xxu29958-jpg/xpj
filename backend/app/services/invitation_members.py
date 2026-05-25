"""Family-ledger member management service."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Ledger, LedgerMember
from app.services import permission_service
from app.services.invitation_audit import add_audit_log
from app.services.invitation_common import (
    AUDIT_MEMBER_DISABLED,
    AUDIT_MEMBER_ROLE_CHANGED,
    AUDIT_OWNER_TRANSFERRED,
    active_member_by_id,
    require_active_owner,
)
from app.services.session_lifecycle_service import revoke_active_tokens
from app.services.time_service import now_utc, to_iso


@dataclass(frozen=True)
class MemberSummary:
    member_id: int
    account_public_id: str
    account_name: str
    role: str
    created_at: str | None
    disabled_at: str | None
    is_self: bool


@dataclass(frozen=True)
class OwnerTransferResult:
    previous_owner: MemberSummary
    new_owner: MemberSummary


def member_summary(
    member: LedgerMember,
    account: Account | None,
    *,
    requester_account_id: int,
) -> MemberSummary:
    return MemberSummary(
        member_id=member.id,
        account_public_id=account.public_id if account else "",
        account_name=account.display_name if account else "",
        role=member.role,
        created_at=to_iso(member.created_at),
        disabled_at=to_iso(member.disabled_at),
        is_self=(member.account_id == requester_account_id),
    )


def list_members(
    db: Session, *, ledger_id: str, requester_account_id: int
) -> list[MemberSummary]:
    rows = list(
        db.scalars(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .order_by(LedgerMember.created_at.asc())
        )
    )
    summaries: list[MemberSummary] = []
    for row in rows:
        acc = db.get(Account, row.account_id)
        if acc is None:
            continue
        summaries.append(
            member_summary(row, acc, requester_account_id=requester_account_id)
        )
    return summaries


def disable_member(
    db: Session,
    *,
    ledger_id: str,
    member_id: int,
    requester_account_id: int,
) -> MemberSummary:
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.id == member_id)
        .where(LedgerMember.ledger_id == ledger_id)
        .limit(1)
    )
    if member is None:
        raise AppError("member_not_found", status_code=404)
    if member.disabled_at is not None:
        raise AppError("member_not_found", status_code=404)
    require_active_owner(db, ledger_id=ledger_id, account_id=requester_account_id)
    if member.role == "owner":
        raise AppError("member_cannot_disable_owner", status_code=409)
    if member.account_id == requester_account_id:
        raise AppError("member_cannot_disable_self", status_code=409)
    # Revoke active tokens for that account in this ledger so they can't keep using it.
    disabled_at = now_utc()
    member.disabled_at = disabled_at
    revoke_active_tokens(
        db,
        account_id=member.account_id,
        ledger_id=ledger_id,
        revoked_at=disabled_at,
    )
    add_audit_log(
        db,
        ledger_id=ledger_id,
        action=AUDIT_MEMBER_DISABLED,
        actor_account_id=requester_account_id,
        target_account_id=member.account_id,
        target_member_id=member.id,
        previous_role=member.role,
    )
    db.commit()
    db.refresh(member)
    acc = db.get(Account, member.account_id)
    return member_summary(member, acc, requester_account_id=0)


def update_member_role(
    db: Session,
    *,
    ledger_id: str,
    member_id: int,
    requester_account_id: int,
    role: str,
) -> MemberSummary:
    """Change an active non-owner member between member/viewer.

    Owner transfer uses ``transfer_ledger_owner`` so this endpoint cannot
    create a second owner. Existing auth tokens pick up the new role on the
    next request because ``AuthContext.role`` is read from ``LedgerMember``
    during token authentication.
    """

    if not permission_service.is_invitable_role(role):
        raise AppError("member_role_invalid", status_code=422)
    require_active_owner(db, ledger_id=ledger_id, account_id=requester_account_id)
    member = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.id == member_id)
        .where(LedgerMember.ledger_id == ledger_id)
        .limit(1)
    )
    if member is None or member.disabled_at is not None:
        raise AppError("member_not_found", status_code=404)
    if member.role == "owner":
        raise AppError("member_cannot_change_owner_role", status_code=409)
    previous_role = member.role
    member.role = role
    add_audit_log(
        db,
        ledger_id=ledger_id,
        action=AUDIT_MEMBER_ROLE_CHANGED,
        actor_account_id=requester_account_id,
        target_account_id=member.account_id,
        target_member_id=member.id,
        previous_role=previous_role,
        new_role=role,
    )
    db.commit()
    db.refresh(member)
    acc = db.get(Account, member.account_id)
    return member_summary(member, acc, requester_account_id=requester_account_id)


def _validate_owner_transfer(
    db: Session,
    *,
    ledger_id: str,
    member_id: int,
    requester_account_id: int,
) -> tuple[Ledger, LedgerMember, LedgerMember, Account]:
    """Resolve and validate every actor a transfer touches.

    Returns ``(ledger, current_owner, target, target_account)`` or
    raises the matching ``AppError`` — ledger missing/archived,
    requester not the active owner, target missing / self / already
    owner / account disabled. Doing all five checks here keeps the
    transaction body in :func:`transfer_ledger_owner` focused on the
    actual mutation + commit.
    """
    ledger = db.scalar(
        select(Ledger)
        .where(Ledger.ledger_id == ledger_id)
        .where(Ledger.archived_at.is_(None))
        .limit(1)
    )
    if ledger is None:
        raise AppError("ledger_not_found", status_code=404)
    current_owner = require_active_owner(
        db, ledger_id=ledger_id, account_id=requester_account_id
    )
    if ledger.owner_account_id != requester_account_id:
        raise AppError("owner_transfer_requires_owner", status_code=409)
    target = active_member_by_id(db, ledger_id=ledger_id, member_id=member_id)
    if target is None:
        raise AppError("member_not_found", status_code=404)
    if target.account_id == requester_account_id:
        raise AppError("owner_transfer_self", status_code=409)
    if target.role == "owner":
        raise AppError("owner_transfer_target_invalid", status_code=409)
    target_account = db.get(Account, target.account_id)
    if target_account is None or target_account.disabled_at is not None:
        raise AppError("member_not_found", status_code=404)
    return ledger, current_owner, target, target_account


def transfer_ledger_owner(
    db: Session,
    *,
    ledger_id: str,
    member_id: int,
    requester_account_id: int,
) -> OwnerTransferResult:
    """Transfer a ledger to one active non-owner member in one transaction.

    The project intentionally keeps a single owner. The target becomes
    ``owner`` and every existing active owner membership is demoted to
    ``member`` in the same commit as the audit row and
    ``Ledger.owner_account_id`` update.
    """
    ledger, current_owner, target, target_account = _validate_owner_transfer(
        db,
        ledger_id=ledger_id,
        member_id=member_id,
        requester_account_id=requester_account_id,
    )

    previous_target_role = target.role
    active_owners = list(
        db.scalars(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.role == "owner")
            .where(LedgerMember.disabled_at.is_(None))
        )
    )
    transferred_at = now_utc()
    demoted_owner_account_ids: list[int] = []
    for owner_member in active_owners:
        if owner_member.id != target.id:
            owner_member.role = "member"
            demoted_owner_account_ids.append(owner_member.account_id)
    target.role = "owner"
    ledger.owner_account_id = target.account_id
    if demoted_owner_account_ids:
        revoke_active_tokens(
            db,
            account_ids=demoted_owner_account_ids,
            ledger_id=ledger_id,
            scope="admin",
            revoked_at=transferred_at,
        )
    add_audit_log(
        db,
        ledger_id=ledger_id,
        action=AUDIT_OWNER_TRANSFERRED,
        actor_account_id=requester_account_id,
        target_account_id=target.account_id,
        target_member_id=target.id,
        previous_role=previous_target_role,
        new_role="owner",
        detail="previous_owner_demoted_to_member",
    )
    db.commit()
    db.refresh(current_owner)
    db.refresh(target)

    previous_owner_account = db.get(Account, current_owner.account_id)
    return OwnerTransferResult(
        previous_owner=member_summary(
            current_owner,
            previous_owner_account,
            requester_account_id=requester_account_id,
        ),
        new_owner=member_summary(
            target,
            target_account,
            requester_account_id=requester_account_id,
        ),
    )


__all__ = [
    "MemberSummary",
    "OwnerTransferResult",
    "disable_member",
    "list_members",
    "member_summary",
    "transfer_ledger_owner",
    "update_member_role",
]
