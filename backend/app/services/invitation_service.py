"""Family-ledger invitation service.

Owner mints a one-time ``Invitation`` bound to ``(ledger_id, role)``. The
plain ``invite_token`` is returned to the caller exactly once and is only
persisted as ``sha256(token)``. Acceptance flow consumes the token, writes
``LedgerMember``, and issues an app-scoped ``AuthToken`` for the joining
account/device — analogous to ``pair_device`` but for a *different* ledger
than the caller's existing identity.

Failure reasons (expired / used / revoked / unknown) collapse to a single
``invitation_invalid`` AppError to avoid side-channel leaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import secrets

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Invitation, Ledger, LedgerAuditLog, LedgerMember
from app.services import permission_service
from app.services.identity_service import (
    _create_auth_token,
    _ensure_device,
    _ensure_membership,
    _ledger_by_id,
    hash_secret,
    new_session_token,  # noqa: F401  (exposed for tests that re-mint)
)
from app.services.time_service import ensure_utc, now_utc, to_iso


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


@dataclass(frozen=True)
class InvitationSummary:
    public_id: str
    ledger_id: str
    role: str
    note: str | None
    created_at: str | None
    expires_at: str | None
    used_at: str | None
    revoked_at: str | None
    used_by_account_name: str | None


@dataclass(frozen=True)
class CreateInvitationResult:
    invite_token: str  # plain, returned once
    summary: InvitationSummary


@dataclass(frozen=True)
class AcceptInvitationResult:
    session_token: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


@dataclass(frozen=True)
class InvitationPreviewResult:
    ledger_id: str
    ledger_name: str
    role: str
    expires_at: str | None


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


def _summary(invitation: Invitation, used_by_name: str | None) -> InvitationSummary:
    return InvitationSummary(
        public_id=invitation.public_id,
        ledger_id=invitation.ledger_id,
        role=invitation.role,
        note=invitation.note,
        created_at=to_iso(invitation.created_at),
        expires_at=to_iso(invitation.expires_at),
        used_at=to_iso(invitation.used_at),
        revoked_at=to_iso(invitation.revoked_at),
        used_by_account_name=used_by_name,
    )


def _clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > 80:
        raise AppError("invitation_note_too_long", status_code=422)
    return cleaned


def _active_member_for_account(db: Session, *, ledger_id: str, account_id: int) -> LedgerMember | None:
    return db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.account_id == account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )


def _require_active_owner(db: Session, *, ledger_id: str, account_id: int) -> LedgerMember:
    member = _active_member_for_account(db, ledger_id=ledger_id, account_id=account_id)
    if member is None or member.role != "owner":
        raise AppError("permission_denied", status_code=403)
    return member


def _active_member_by_id(db: Session, *, ledger_id: str, member_id: int) -> LedgerMember | None:
    return db.scalar(
        select(LedgerMember)
        .where(LedgerMember.id == member_id)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )


def _clean_detail(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:500]


def _add_audit_log(
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
            detail=_clean_detail(detail),
        )
    )


def _account_identity(db: Session, account_id: int | None) -> tuple[str | None, str | None]:
    if account_id is None:
        return None, None
    account = db.get(Account, account_id)
    if account is None:
        return None, None
    return account.public_id, account.display_name


def _audit_summary(db: Session, row: LedgerAuditLog) -> LedgerAuditSummary:
    actor_public_id, actor_name = _account_identity(db, row.actor_account_id)
    target_public_id, target_name = _account_identity(db, row.target_account_id)
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


def list_audit_logs(db: Session, *, ledger_id: str, limit: int = 100) -> list[LedgerAuditSummary]:
    capped_limit = max(1, min(limit, 200))
    rows = list(
        db.scalars(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.ledger_id == ledger_id)
            .order_by(LedgerAuditLog.created_at.desc(), LedgerAuditLog.id.desc())
            .limit(capped_limit)
        )
    )
    return [_audit_summary(db, row) for row in rows]


def create_invitation(
    db: Session,
    *,
    ledger_id: str,
    role: str,
    created_by_account_id: int,
    note: str | None = None,
    ttl_days: int = INVITATION_TTL_DAYS,
) -> CreateInvitationResult:
    if not permission_service.is_invitable_role(role):
        raise AppError("invitation_role_invalid", status_code=422)
    ledger = _ledger_by_id(db, ledger_id)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("ledger_not_found", status_code=404)
    _require_active_owner(db, ledger_id=ledger.ledger_id, account_id=created_by_account_id)
    ttl = max(1, min(ttl_days, 30))
    expires_at = now_utc() + timedelta(days=ttl)
    # Loop until unique token (collisions astronomically unlikely)
    while True:
        token = new_invite_token()
        token_hash = hash_secret(token)
        if db.scalar(select(Invitation.id).where(Invitation.token_hash == token_hash).limit(1)) is None:
            break
    cleaned_note = _clean_note(note)
    invitation = Invitation(
        ledger_id=ledger.ledger_id,
        token_hash=token_hash,
        role=role,
        created_by_account_id=created_by_account_id,
        note=cleaned_note,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.flush()
    _add_audit_log(
        db,
        ledger_id=ledger.ledger_id,
        action=AUDIT_INVITATION_CREATED,
        actor_account_id=created_by_account_id,
        invitation_public_id=invitation.public_id,
        new_role=role,
    )
    db.commit()
    db.refresh(invitation)
    return CreateInvitationResult(
        invite_token=token,
        summary=_summary(invitation, used_by_name=None),
    )


def list_invitations(db: Session, *, ledger_id: str) -> list[InvitationSummary]:
    rows = list(
        db.scalars(
            select(Invitation)
            .where(Invitation.ledger_id == ledger_id)
            .order_by(Invitation.created_at.desc())
        )
    )
    summaries: list[InvitationSummary] = []
    for inv in rows:
        used_name: str | None = None
        if inv.used_by_account_id is not None:
            acc = db.get(Account, inv.used_by_account_id)
            used_name = acc.display_name if acc is not None else None
        summaries.append(_summary(inv, used_name))
    return summaries


def revoke_invitation(
    db: Session,
    *,
    ledger_id: str,
    public_id: str,
    actor_account_id: int | None = None,
) -> InvitationSummary:
    if actor_account_id is not None:
        _require_active_owner(db, ledger_id=ledger_id, account_id=actor_account_id)
    invitation = db.scalar(
        select(Invitation)
        .where(Invitation.ledger_id == ledger_id)
        .where(Invitation.public_id == public_id)
        .limit(1)
    )
    if invitation is None:
        raise AppError("invitation_invalid", status_code=404)
    if invitation.revoked_at is None and invitation.used_at is None:
        invitation.revoked_at = now_utc()
        _add_audit_log(
            db,
            ledger_id=ledger_id,
            action=AUDIT_INVITATION_REVOKED,
            actor_account_id=actor_account_id,
            invitation_public_id=invitation.public_id,
            previous_role=invitation.role,
        )
        db.commit()
        db.refresh(invitation)
    used_name: str | None = None
    if invitation.used_by_account_id is not None:
        acc = db.get(Account, invitation.used_by_account_id)
        used_name = acc.display_name if acc is not None else None
    return _summary(invitation, used_name)


def _resolve_active_invitation(db: Session, invite_token: str) -> Invitation:
    token_hash = hash_secret(invite_token.strip())
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == token_hash).limit(1)
    )
    if invitation is None:
        raise AppError("invitation_invalid", status_code=400)
    if invitation.used_at is not None or invitation.revoked_at is not None:
        raise AppError("invitation_invalid", status_code=400)
    if (ensure_utc(invitation.expires_at) or invitation.expires_at) <= now_utc():
        raise AppError("invitation_invalid", status_code=400)
    return invitation


def preview_invitation(db: Session, *, invite_token: str) -> InvitationPreviewResult:
    """Resolve an active invitation without consuming it.

    This endpoint exists so clients can show the target ledger and role before
    replacing the local binding. All invalid states intentionally collapse to
    ``invitation_invalid`` just like accept.
    """

    invitation = _resolve_active_invitation(db, invite_token)
    if not permission_service.is_invitable_role(invitation.role):
        raise AppError("invitation_invalid", status_code=400)
    ledger = _ledger_by_id(db, invitation.ledger_id)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invitation_invalid", status_code=400)
    return InvitationPreviewResult(
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        role=invitation.role,
        expires_at=to_iso(invitation.expires_at),
    )


def accept_invitation(
    db: Session,
    *,
    invite_token: str,
    account_name: str,
    device_name: str,
    platform: str,
) -> AcceptInvitationResult:
    """Unauthenticated accept: creates a new ``Account``, ``Device``,
    ``LedgerMember`` and app-scoped ``AuthToken`` in one transaction.

    Each accept creates a fresh ``Account`` for the joining device — owners
    of multiple personal ledgers are out of scope for v0.4-beta1. The
    invitee can later switch to other ledgers they own/join via the normal
    ``switch`` flow once they accept more invites or are paired by other
    owners.
    """
    invitation = _resolve_active_invitation(db, invite_token)
    if not permission_service.is_invitable_role(invitation.role):
        raise AppError("invitation_invalid", status_code=400)
    ledger = _ledger_by_id(db, invitation.ledger_id)
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invitation_invalid", status_code=400)

    cleaned_account_name = (account_name or "").strip() or "家庭成员"
    cleaned_device_name = (device_name or "").strip() or "未命名设备"
    cleaned_platform = (platform or "unknown").strip() or "unknown"

    # Atomic mark-used; if another request claimed it first, fail.
    used_at = now_utc()
    account = Account(display_name=cleaned_account_name[:120])
    db.add(account)
    db.flush()

    result = db.execute(
        update(Invitation)
        .where(Invitation.id == invitation.id)
        .where(Invitation.used_at.is_(None))
        .where(Invitation.revoked_at.is_(None))
        .values(used_at=used_at, used_by_account_id=account.id)
    )
    if result.rowcount != 1:
        db.rollback()
        raise AppError("invitation_invalid", status_code=400)

    _ensure_membership(db, ledger.ledger_id, account.id, invitation.role)
    device = _ensure_device(db, account.id, cleaned_device_name, cleaned_platform)
    token = _create_auth_token(
        db,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
    )
    _add_audit_log(
        db,
        ledger_id=ledger.ledger_id,
        action=AUDIT_INVITATION_ACCEPTED,
        actor_account_id=account.id,
        target_account_id=account.id,
        invitation_public_id=invitation.public_id,
        new_role=invitation.role,
    )
    db.commit()

    return AcceptInvitationResult(
        session_token=token,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=invitation.role,
    )


@dataclass(frozen=True)
class MemberSummary:
    member_id: int
    account_public_id: str
    account_name: str
    role: str
    created_at: str | None
    disabled_at: str | None
    is_self: bool


def list_members(db: Session, *, ledger_id: str, requester_account_id: int) -> list[MemberSummary]:
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
            MemberSummary(
                member_id=row.id,
                account_public_id=acc.public_id,
                account_name=acc.display_name,
                role=row.role,
                created_at=to_iso(row.created_at),
                disabled_at=to_iso(row.disabled_at),
                is_self=(row.account_id == requester_account_id),
            )
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
    _require_active_owner(db, ledger_id=ledger_id, account_id=requester_account_id)
    if member.role == "owner":
        raise AppError("member_cannot_disable_owner", status_code=409)
    if member.account_id == requester_account_id:
        raise AppError("member_cannot_disable_self", status_code=409)
    # Revoke active tokens for that account in this ledger so they can't keep using it.
    disabled_at = now_utc()
    member.disabled_at = disabled_at
    db.execute(
        update(AuthToken)
        .where(AuthToken.account_id == member.account_id)
        .where(AuthToken.ledger_id == ledger_id)
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=disabled_at)
    )
    _add_audit_log(
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
    return MemberSummary(
        member_id=member.id,
        account_public_id=acc.public_id if acc else "",
        account_name=acc.display_name if acc else "",
        role=member.role,
        created_at=to_iso(member.created_at),
        disabled_at=to_iso(member.disabled_at),
        is_self=False,
    )


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
    _require_active_owner(db, ledger_id=ledger_id, account_id=requester_account_id)
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
    _add_audit_log(
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
    return MemberSummary(
        member_id=member.id,
        account_public_id=acc.public_id if acc else "",
        account_name=acc.display_name if acc else "",
        role=member.role,
        created_at=to_iso(member.created_at),
        disabled_at=to_iso(member.disabled_at),
        is_self=(member.account_id == requester_account_id),
    )


@dataclass(frozen=True)
class OwnerTransferResult:
    previous_owner: MemberSummary
    new_owner: MemberSummary


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

    ledger = db.scalar(
        select(Ledger)
        .where(Ledger.ledger_id == ledger_id)
        .where(Ledger.archived_at.is_(None))
        .limit(1)
    )
    if ledger is None:
        raise AppError("ledger_not_found", status_code=404)

    current_owner = _require_active_owner(
        db, ledger_id=ledger_id, account_id=requester_account_id
    )
    if ledger.owner_account_id != requester_account_id:
        raise AppError("owner_transfer_requires_owner", status_code=409)

    target = _active_member_by_id(db, ledger_id=ledger_id, member_id=member_id)
    if target is None:
        raise AppError("member_not_found", status_code=404)
    if target.account_id == requester_account_id:
        raise AppError("owner_transfer_self", status_code=409)
    if target.role == "owner":
        raise AppError("owner_transfer_target_invalid", status_code=409)
    target_account = db.get(Account, target.account_id)
    if target_account is None or target_account.disabled_at is not None:
        raise AppError("member_not_found", status_code=404)

    previous_target_role = target.role
    active_owners = list(
        db.scalars(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.role == "owner")
            .where(LedgerMember.disabled_at.is_(None))
        )
    )
    for owner_member in active_owners:
        if owner_member.id != target.id:
            owner_member.role = "member"
    target.role = "owner"
    ledger.owner_account_id = target.account_id
    _add_audit_log(
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
        previous_owner=MemberSummary(
            member_id=current_owner.id,
            account_public_id=previous_owner_account.public_id if previous_owner_account else "",
            account_name=previous_owner_account.display_name if previous_owner_account else "",
            role=current_owner.role,
            created_at=to_iso(current_owner.created_at),
            disabled_at=to_iso(current_owner.disabled_at),
            is_self=True,
        ),
        new_owner=MemberSummary(
            member_id=target.id,
            account_public_id=target_account.public_id,
            account_name=target_account.display_name,
            role=target.role,
            created_at=to_iso(target.created_at),
            disabled_at=to_iso(target.disabled_at),
            is_self=False,
        ),
    )
