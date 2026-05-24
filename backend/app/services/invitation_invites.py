"""Invitation token lifecycle service.

The plain invite token is returned only by ``create_invitation``. All later
operations use the stored SHA-256 hash and collapse invalid states to
``invitation_invalid``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, Invitation
from app.services import permission_service
from app.services.identity_service import (
    _create_auth_token,
    _ensure_device,
    _ensure_membership,
    _ledger_by_id,
    hash_secret,
)
from app.services.invitation_audit import add_audit_log
from app.services.invitation_common import (
    AUDIT_INVITATION_ACCEPTED,
    AUDIT_INVITATION_CREATED,
    AUDIT_INVITATION_REVOKED,
    INVITATION_TTL_DAYS,
    clean_note,
    new_invite_token,
    require_active_owner,
)
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    revoke_token_value,
)
from app.services.time_service import ensure_utc, now_utc, to_iso


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
    expires_at: str | None
    soft_refresh_after: str | None
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


def invitation_summary(invitation: Invitation, used_by_name: str | None) -> InvitationSummary:
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
    require_active_owner(db, ledger_id=ledger.ledger_id, account_id=created_by_account_id)
    ttl = max(1, min(ttl_days, 30))
    expires_at = now_utc() + timedelta(days=ttl)
    # Loop until unique token (collisions astronomically unlikely)
    while True:
        token = new_invite_token()
        token_hash = hash_secret(token)
        if db.scalar(select(Invitation.id).where(Invitation.token_hash == token_hash).limit(1)) is None:
            break
    cleaned_note = clean_note(note)
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
    add_audit_log(
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
        summary=invitation_summary(invitation, used_by_name=None),
    )


def list_invitations(db: Session, *, ledger_id: str) -> list[InvitationSummary]:
    rows = list(
        db.scalars(select(Invitation).where(Invitation.ledger_id == ledger_id).order_by(Invitation.created_at.desc()))
    )
    summaries: list[InvitationSummary] = []
    for inv in rows:
        used_name: str | None = None
        if inv.used_by_account_id is not None:
            acc = db.get(Account, inv.used_by_account_id)
            used_name = acc.display_name if acc is not None else None
        summaries.append(invitation_summary(inv, used_name))
    return summaries


def revoke_invitation(
    db: Session,
    *,
    ledger_id: str,
    public_id: str,
    actor_account_id: int | None = None,
) -> InvitationSummary:
    if actor_account_id is not None:
        require_active_owner(db, ledger_id=ledger_id, account_id=actor_account_id)
    invitation = db.scalar(
        select(Invitation).where(Invitation.ledger_id == ledger_id).where(Invitation.public_id == public_id).limit(1)
    )
    if invitation is None:
        raise AppError("invitation_invalid", status_code=404)
    if invitation.revoked_at is None and invitation.used_at is None:
        invitation.revoked_at = now_utc()
        add_audit_log(
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
    return invitation_summary(invitation, used_name)


def resolve_active_invitation(db: Session, invite_token: str) -> Invitation:
    token_hash = hash_secret(invite_token.strip())
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash).limit(1))
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

    invitation = resolve_active_invitation(db, invite_token)
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
    previous_session_token: str | None = None,
) -> AcceptInvitationResult:
    """Consume an invitation and issue a ledger-scoped app token."""

    invitation = resolve_active_invitation(db, invite_token)
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
        .where(Invitation.expires_at > used_at)
        .values(used_at=used_at, used_by_account_id=account.id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise AppError("invitation_invalid", status_code=400)

    _ensure_membership(db, ledger.ledger_id, account.id, invitation.role)
    device = _ensure_device(db, account.id, cleaned_device_name, cleaned_platform)
    expiry = app_token_expiry_window(used_at)
    token = _create_auth_token(
        db,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
        expires_at=expiry.expires_at,
    )
    if previous_session_token:
        revoke_token_value(
            db,
            token_value=previous_session_token,
            revoked_at=used_at,
            scope="app",
        )
    add_audit_log(
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
        expires_at=to_iso(expiry.expires_at),
        soft_refresh_after=to_iso(expiry.soft_refresh_after),
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=invitation.role,
    )


__all__ = [
    "AcceptInvitationResult",
    "CreateInvitationResult",
    "InvitationPreviewResult",
    "InvitationSummary",
    "accept_invitation",
    "create_invitation",
    "invitation_summary",
    "list_invitations",
    "preview_invitation",
    "resolve_active_invitation",
    "revoke_invitation",
]
