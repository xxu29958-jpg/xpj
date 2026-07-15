"""Recoverable invitation-acceptance transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, Invitation, Ledger, LedgerMember
from app.services import permission_service
from app.services.identity_service import (
    _create_auth_token,
    _create_device,
    _ensure_membership,
    hash_secret,
    lock_bootstrap_owner_transaction,
)
from app.services.identity_service._enrollment import (
    EnrollmentProof,
    enrollment_attempt_proves_source,
    load_enrollment_attempt,
    prepare_enrollment_proof,
    record_enrollment_attempt,
    recover_enrollment_identity,
)
from app.services.invitation_audit import add_audit_log
from app.services.invitation_common import (
    AUDIT_INVITATION_ACCEPTED,
    active_member_for_account,
)
from app.services.session_credential_lock import lock_and_revalidate_session_principal
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    app_token_soft_refresh_after,
)
from app.services.time_service import ensure_utc, now_utc, to_iso
from app.tenants import SessionPrincipal


@dataclass(frozen=True)
class AcceptInvitationResult:
    session_token: str
    enrollment_attempt_id: str | None
    account_public_id: str
    device_public_id: str
    expires_at: str | None
    soft_refresh_after: str | None
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


def _load_invitation_acceptance(
    db: Session,
    *,
    invite_token: str,
) -> tuple[Invitation, Ledger]:
    invitation = db.scalar(
        select(Invitation)
        .where(Invitation.token_hash == hash_secret(invite_token.strip()))
        .with_for_update()
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if (
        invitation is None
        or invitation.revoked_at is not None
        or not permission_service.is_invitable_role(invitation.role)
    ):
        raise AppError("invitation_invalid", status_code=400)
    ledger = db.scalar(
        select(Ledger)
        .where(Ledger.ledger_id == invitation.ledger_id)
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if ledger is None or ledger.archived_at is not None:
        raise AppError("invitation_invalid", status_code=400)
    if invitation.used_at is None and (ensure_utc(invitation.expires_at) or invitation.expires_at) <= now_utc():
        raise AppError("invitation_invalid", status_code=400)
    return invitation, ledger


def _claim_invitation(
    db: Session,
    *,
    invitation: Invitation,
    account_id: int,
    used_at: datetime,
) -> None:
    result = db.execute(
        update(Invitation)
        .where(Invitation.id == invitation.id)
        .where(Invitation.used_at.is_(None))
        .where(Invitation.revoked_at.is_(None))
        .where(Invitation.expires_at > used_at)
        .values(used_at=used_at, used_by_account_id=account_id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise AppError("invitation_invalid", status_code=400)


def _activate_invited_membership(
    db: Session,
    *,
    invitation: Invitation,
    account_id: int,
) -> LedgerMember:
    membership = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == invitation.ledger_id)
        .where(LedgerMember.account_id == account_id)
        .with_for_update()
        .limit(1)
    )
    if membership is None:
        return _ensure_membership(
            db,
            invitation.ledger_id,
            account_id,
            invitation.role,
        )
    if membership.disabled_at is None:
        raise AppError(
            "invitation_already_joined",
            "你已经是这个账本的成员，无需再次接受邀请。",
            status_code=409,
        )
    membership.disabled_at = None
    membership.role = invitation.role
    db.flush()
    return membership


def _accepted_result(
    *,
    session_token: str,
    enrollment_attempt_id: str | None,
    account: Account,
    device: Device,
    ledger: Ledger,
    role: str,
    expires_at: datetime | None,
    soft_refresh_after: datetime | None,
) -> AcceptInvitationResult:
    return AcceptInvitationResult(
        session_token=session_token,
        enrollment_attempt_id=enrollment_attempt_id,
        account_public_id=account.public_id,
        device_public_id=device.public_id,
        expires_at=to_iso(expires_at),
        soft_refresh_after=to_iso(soft_refresh_after),
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        role=role,
    )


def _accept_for_existing_session(
    db: Session,
    *,
    invitation: Invitation,
    ledger: Ledger,
    principal: SessionPrincipal,
    session_token: str,
) -> AcceptInvitationResult:
    account = db.get(Account, principal.account_id)
    device = db.get(Device, principal.device_id)
    if account is None or device is None or device.account_id != account.id:
        raise AppError("invalid_token", status_code=401)
    token = db.get(AuthToken, principal.credential_id)
    if (
        token is None
        or token.token_hash != hash_secret(session_token)
        or token.account_id != account.id
        or token.device_id != device.id
        or token.scope != "app"
    ):
        raise AppError("invalid_token", status_code=401)

    accepted_at = now_utc()
    if invitation.used_at is not None:
        if invitation.used_by_account_id != account.id:
            raise AppError("invitation_invalid", status_code=400)
        membership = active_member_for_account(
            db,
            ledger_id=ledger.ledger_id,
            account_id=account.id,
        )
        if membership is None:
            raise AppError("invitation_invalid", status_code=400)
    else:
        membership = _activate_invited_membership(
            db,
            invitation=invitation,
            account_id=account.id,
        )
        _claim_invitation(
            db,
            invitation=invitation,
            account_id=account.id,
            used_at=accepted_at,
        )
        add_audit_log(
            db,
            ledger_id=ledger.ledger_id,
            action=AUDIT_INVITATION_ACCEPTED,
            actor_account_id=account.id,
            target_account_id=account.id,
            invitation_public_id=invitation.public_id,
            new_role=membership.role,
        )
    token.ledger_id = ledger.ledger_id
    device.last_seen_at = accepted_at
    db.commit()
    token_expires_at = ensure_utc(token.expires_at)
    return _accepted_result(
        session_token=session_token,
        enrollment_attempt_id=None,
        account=account,
        device=device,
        ledger=ledger,
        role=membership.role,
        expires_at=token_expires_at,
        soft_refresh_after=app_token_soft_refresh_after(token_expires_at),
    )


def _enrollment_proof(
    attempt_id: str | None,
    attempt_secret: str | None,
) -> EnrollmentProof:
    if attempt_id is None or attempt_secret is None:
        raise AppError(
            "client_upgrade_required",
            "当前客户端无法安全恢复中断的邀请，请升级后重试。",
            status_code=422,
        )
    return prepare_enrollment_proof(attempt_id, attempt_secret)


def _recover_used_invitation(
    db: Session,
    *,
    invitation: Invitation,
    proof: EnrollmentProof,
    issued_at: datetime,
) -> AcceptInvitationResult:
    attempt = load_enrollment_attempt(db, public_id=proof.public_id)
    if (
        attempt is None
        or not enrollment_attempt_proves_source(
            attempt,
            proof,
            invitation_id=invitation.id,
        )
        or invitation.used_by_account_id != attempt.account_id
    ):
        raise AppError("invitation_invalid", status_code=400)
    identity = recover_enrollment_identity(
        db,
        attempt=attempt,
        proof=proof,
        expired_error="invitation_attempt_expired",
        closed_error="invitation_attempt_closed",
    )
    attempt.last_issued_at = issued_at
    db.commit()
    return _accepted_result(
        session_token=proof.session_token,
        enrollment_attempt_id=attempt.public_id,
        account=identity.account,
        device=identity.device,
        ledger=identity.ledger,
        role=identity.role,
        expires_at=attempt.session_expires_at,
        soft_refresh_after=attempt.session_soft_refresh_after,
    )


def _create_invited_session(
    db: Session,
    *,
    invitation: Invitation,
    ledger: Ledger,
    proof: EnrollmentProof,
    account_name: str,
    device_name: str,
    platform: str,
    issued_at: datetime,
) -> AcceptInvitationResult:
    if load_enrollment_attempt(db, public_id=proof.public_id) is not None:
        raise AppError("invitation_invalid", status_code=400)
    account = Account(display_name=((account_name or "").strip() or "家庭成员")[:120])
    db.add(account)
    db.flush()
    _claim_invitation(
        db,
        invitation=invitation,
        account_id=account.id,
        used_at=issued_at,
    )
    membership = _activate_invited_membership(
        db,
        invitation=invitation,
        account_id=account.id,
    )
    cleaned_device_name = (device_name or "").strip() or "未命名设备"
    cleaned_platform = (platform or "unknown").strip() or "unknown"
    device = _create_device(db, account.id, cleaned_device_name, cleaned_platform)
    expiry = app_token_expiry_window(issued_at)
    _create_auth_token(
        db,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
        expires_at=expiry.expires_at,
        token_value=proof.session_token,
    )
    attempt = record_enrollment_attempt(
        db,
        proof=proof,
        invitation_id=invitation.id,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        issued_at=issued_at,
        session_expires_at=expiry.expires_at,
        session_soft_refresh_after=expiry.soft_refresh_after,
    )
    add_audit_log(
        db,
        ledger_id=ledger.ledger_id,
        action=AUDIT_INVITATION_ACCEPTED,
        actor_account_id=account.id,
        target_account_id=account.id,
        invitation_public_id=invitation.public_id,
        new_role=membership.role,
    )
    db.commit()
    return _accepted_result(
        session_token=proof.session_token,
        enrollment_attempt_id=attempt.public_id,
        account=account,
        device=device,
        ledger=ledger,
        role=membership.role,
        expires_at=expiry.expires_at,
        soft_refresh_after=expiry.soft_refresh_after,
    )


def _accept_for_new_session(
    db: Session,
    *,
    invitation: Invitation,
    ledger: Ledger,
    account_name: str,
    device_name: str,
    platform: str,
    enrollment_attempt_id: str | None,
    enrollment_attempt_secret: str | None,
) -> AcceptInvitationResult:
    proof = _enrollment_proof(enrollment_attempt_id, enrollment_attempt_secret)
    issued_at = now_utc()
    if invitation.used_at is not None:
        return _recover_used_invitation(
            db,
            invitation=invitation,
            proof=proof,
            issued_at=issued_at,
        )
    return _create_invited_session(
        db,
        invitation=invitation,
        ledger=ledger,
        proof=proof,
        account_name=account_name,
        device_name=device_name,
        platform=platform,
        issued_at=issued_at,
    )


def accept_invitation(
    db: Session,
    *,
    invite_token: str,
    account_name: str,
    device_name: str,
    platform: str,
    session_token: str | None = None,
    principal: SessionPrincipal | None = None,
    enrollment_attempt_id: str | None = None,
    enrollment_attempt_secret: str | None = None,
) -> AcceptInvitationResult:
    """Join a ledger without changing an already authenticated identity."""

    if principal is None:
        if session_token is not None:
            raise AppError("invalid_token", status_code=401)
        lock_bootstrap_owner_transaction(db)
    else:
        if session_token is None:
            raise AppError("invalid_token", status_code=401)
        locked_principal = lock_and_revalidate_session_principal(db, principal)
        if locked_principal is None:
            raise AppError("invalid_token", status_code=401)
        principal = locked_principal
    invitation, ledger = _load_invitation_acceptance(db, invite_token=invite_token)
    if principal is not None:
        return _accept_for_existing_session(
            db,
            invitation=invitation,
            ledger=ledger,
            principal=principal,
            session_token=session_token,
        )
    return _accept_for_new_session(
        db,
        invitation=invitation,
        ledger=ledger,
        account_name=account_name,
        device_name=device_name,
        platform=platform,
        enrollment_attempt_id=enrollment_attempt_id,
        enrollment_attempt_secret=enrollment_attempt_secret,
    )


__all__ = ["AcceptInvitationResult", "accept_invitation"]
