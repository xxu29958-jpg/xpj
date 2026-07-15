"""Shared response-loss contract for device enrollment commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hmac import compare_digest
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, AuthToken, Device, DeviceEnrollmentAttempt, Ledger
from app.services.identity_service._auth import _role_for
from app.services.session_lifecycle_service import (
    derive_enrollment_session_token,
    hash_enrollment_attempt_secret,
    hash_secret,
)
from app.services.time_service import ensure_utc, now_utc

# Browser proof storage is deliberately shorter than a DeviceSession. It is a
# cookie retention policy, not the server-side receipt lifetime.
ENROLLMENT_PROOF_COOKIE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class EnrollmentProof:
    public_id: str
    secret_hash: str
    session_token: str


@dataclass(frozen=True)
class EnrollmentIdentity:
    ledger: Ledger
    account: Account
    device: Device
    token: AuthToken
    role: str


def prepare_enrollment_proof(attempt_id: str, attempt_secret: str) -> EnrollmentProof:
    try:
        public_id = str(UUID(attempt_id))
        secret_hash = hash_enrollment_attempt_secret(attempt_secret)
        session_token = derive_enrollment_session_token(attempt_secret, public_id)
    except (ValueError, AttributeError) as exc:
        raise AppError("invalid_request", status_code=422) from exc
    return EnrollmentProof(
        public_id=public_id,
        secret_hash=secret_hash,
        session_token=session_token,
    )


def load_enrollment_attempt(
    db: Session,
    *,
    public_id: str,
) -> DeviceEnrollmentAttempt | None:
    return db.scalar(
        select(DeviceEnrollmentAttempt)
        .where(DeviceEnrollmentAttempt.public_id == public_id)
        .with_for_update()
        .execution_options(populate_existing=True)
        .limit(1)
    )


def enrollment_attempt_proves_source(
    attempt: DeviceEnrollmentAttempt,
    proof: EnrollmentProof,
    *,
    pairing_code_id: int | None = None,
    invitation_id: int | None = None,
) -> bool:
    return (
        attempt.pairing_code_id == pairing_code_id
        and attempt.invitation_id == invitation_id
        and compare_digest(attempt.secret_hash, proof.secret_hash)
    )


def recover_enrollment_identity(
    db: Session,
    *,
    attempt: DeviceEnrollmentAttempt,
    proof: EnrollmentProof,
    expired_error: str,
    closed_error: str,
) -> EnrollmentIdentity:
    attempt_expires_at = ensure_utc(attempt.expires_at)
    if attempt_expires_at is not None and attempt_expires_at <= now_utc():
        db.rollback()
        raise AppError(expired_error, status_code=409)

    account = db.get(Account, attempt.account_id)
    device = db.get(Device, attempt.device_id)
    ledger = db.scalar(
        select(Ledger).where(Ledger.ledger_id == attempt.ledger_id).execution_options(populate_existing=True).limit(1)
    )
    token = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == attempt.session_token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
        .limit(1)
    )
    expected_token_hash = hash_secret(proof.session_token)
    if (
        account is None
        or account.disabled_at is not None
        or device is None
        or device.account_id != account.id
        or device.revoked_at is not None
        or ledger is None
        or ledger.archived_at is not None
        or token is None
        or token.account_id != account.id
        or token.device_id != device.id
        or token.ledger_id != ledger.ledger_id
        or token.scope != "app"
        or token.revoked_at is not None
        or not compare_digest(token.token_hash, expected_token_hash)
        or (token.expires_at is not None and (ensure_utc(token.expires_at) or token.expires_at) <= now_utc())
    ):
        db.rollback()
        raise AppError(closed_error, status_code=409)
    return EnrollmentIdentity(
        ledger=ledger,
        account=account,
        device=device,
        token=token,
        role=_role_for(db, ledger.ledger_id, account.id),
    )


def record_enrollment_attempt(
    db: Session,
    *,
    proof: EnrollmentProof,
    account_id: int,
    device_id: int,
    ledger_id: str,
    issued_at: datetime,
    session_expires_at: datetime | None,
    session_soft_refresh_after: datetime | None,
    pairing_code_id: int | None = None,
    invitation_id: int | None = None,
) -> DeviceEnrollmentAttempt:
    attempt = DeviceEnrollmentAttempt(
        public_id=proof.public_id,
        pairing_code_id=pairing_code_id,
        invitation_id=invitation_id,
        account_id=account_id,
        device_id=device_id,
        ledger_id=ledger_id,
        secret_hash=proof.secret_hash,
        session_token_hash=hash_secret(proof.session_token),
        session_expires_at=session_expires_at,
        session_soft_refresh_after=session_soft_refresh_after,
        # The proof recovers the already-issued credential; it must remain
        # replayable for exactly that credential's lifetime. A fixed 24-hour
        # receipt stranded otherwise-valid 90-day Android sessions after a
        # long response-loss/offline interval. Non-expiring sessions retain
        # the receipt until explicit account/device/token revocation closes it.
        expires_at=session_expires_at,
        last_issued_at=issued_at,
        created_at=issued_at,
    )
    db.add(attempt)
    db.flush()
    return attempt


__all__ = [
    "ENROLLMENT_PROOF_COOKIE_SECONDS",
    "EnrollmentIdentity",
    "EnrollmentProof",
    "enrollment_attempt_proves_source",
    "load_enrollment_attempt",
    "prepare_enrollment_proof",
    "record_enrollment_attempt",
    "recover_enrollment_identity",
]
