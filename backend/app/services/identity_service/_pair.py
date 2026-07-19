"""Pair a device using a pairing code → issue session token."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    Device,
    DeviceEnrollmentAttempt,
    Ledger,
    PairingCode,
    UploadLink,
)
from app.services.identity_service._auth import _role_for
from app.services.identity_service._device import _create_auth_token, _create_device
from app.services.identity_service._enrollment import (
    EnrollmentProof,
    enrollment_attempt_proves_source,
    load_enrollment_attempt,
    prepare_enrollment_proof,
    record_enrollment_attempt,
    recover_enrollment_identity,
)
from app.services.identity_service._models import (
    WEB_SESSION_TTL_SECONDS,
    PairingResult,
)
from app.services.identity_service._pairing_throttle import (
    _check_pairing_attempt_limit,
    _clear_pairing_failures,
    _reject_pairing,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import (
    app_token_expiry_window,
    consume_pairing_code,
    hash_pairing_code,
)
from app.services.time_service import ensure_utc, now_utc


@dataclass(frozen=True)
class PairingCompletion:
    ledger: Ledger
    account: Account
    device: Device
    role: str
    attempt: DeviceEnrollmentAttempt


def _load_pairing_code(
    db: Session,
    *,
    code_hash: str,
    remote_id: str | None,
) -> PairingCode:
    pairing = db.scalar(
        select(PairingCode)
        .where(PairingCode.code_hash == code_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if pairing is None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    return pairing


def _load_new_pairing_identity(
    db: Session,
    *,
    pairing: PairingCode,
    remote_id: str | None,
) -> tuple[Ledger, Account, Device | None, str]:
    if pairing.used_at is not None or pairing.revoked_at is not None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    if (ensure_utc(pairing.expires_at) or pairing.expires_at) <= now_utc():
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)

    ledger = db.scalar(
        select(Ledger).where(Ledger.ledger_id == pairing.ledger_id).execution_options(populate_existing=True).limit(1)
    )
    if ledger is None or ledger.archived_at is not None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    account_id = pairing.account_id or ledger.owner_account_id
    account = db.scalar(
        select(Account).where(Account.id == account_id).execution_options(populate_existing=True).limit(1)
    )
    if account is None or account.disabled_at is not None:
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    recovery_device: Device | None = None
    if pairing.recovery_device_id is not None:
        recovery_device = db.scalar(
            select(Device)
            .where(Device.id == pairing.recovery_device_id)
            .where(Device.account_id == account.id)
            .with_for_update()
            .execution_options(populate_existing=True)
            .limit(1)
        )
        if recovery_device is None:
            _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    return ledger, account, recovery_device, _role_for(db, ledger.ledger_id, account.id)


def _recover_or_create_device(
    db: Session,
    *,
    account: Account,
    recovery_device: Device | None,
    device_name: str,
    platform: str,
    replaced_at: datetime,
) -> Device:
    if recovery_device is None:
        return _create_device(db, account.id, device_name, platform)

    requested_platform = (platform or "unknown").strip().lower()[:32] or "unknown"
    if recovery_device.platform != requested_platform:
        raise AppError("device_recovery_platform_mismatch", status_code=409)

    db.execute(
        update(AuthToken)
        .where(AuthToken.device_id == recovery_device.id)
        .where(AuthToken.revoked_at.is_(None))
        .values(revoked_at=replaced_at, grace_until=None)
    )
    db.execute(
        update(UploadLink)
        .where(UploadLink.device_id == recovery_device.id)
        .where(UploadLink.revoked_at.is_(None))
        .values(revoked_at=replaced_at)
    )
    recovery_device.revoked_at = None
    recovery_device.device_name = (device_name or "").strip()[:120] or recovery_device.device_name
    db.flush()
    return recovery_device


def _close_sibling_recovery_pairing_codes(
    db: Session,
    *,
    device_id: int,
    consumed_pairing_id: int,
    closed_at: datetime,
) -> None:
    """Close every other unused recovery capability for the recovered Device."""

    db.execute(
        update(PairingCode)
        .where(PairingCode.recovery_device_id == device_id)
        .where(PairingCode.id != consumed_pairing_id)
        .where(PairingCode.used_at.is_(None))
        .values(
            revoked_at=func.coalesce(PairingCode.revoked_at, closed_at),
            recovery_device_id=None,
        )
        .execution_options(synchronize_session=False)
    )


def _session_window(
    *,
    platform: str,
    issued_at: datetime,
) -> tuple[datetime | None, datetime | None]:
    if platform == "web":
        return issued_at + timedelta(seconds=WEB_SESSION_TTL_SECONDS), None
    expiry = app_token_expiry_window(issued_at)
    return expiry.expires_at, expiry.soft_refresh_after


def _create_pairing_completion(
    db: Session,
    *,
    pairing: PairingCode,
    proof: EnrollmentProof,
    device_name: str,
    platform: str,
    remote_id: str | None,
    issued_at: datetime,
) -> PairingCompletion:
    ledger, account, recovery_device, role = _load_new_pairing_identity(
        db,
        pairing=pairing,
        remote_id=remote_id,
    )
    consume_result = consume_pairing_code(
        db,
        pairing_id=pairing.id,
        expected_code_hash=pairing.code_hash,
        used_at=issued_at,
    )
    if consume_result != "consumed":
        db.rollback()
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    device = _recover_or_create_device(
        db,
        account=account,
        recovery_device=recovery_device,
        device_name=device_name,
        platform=platform,
        replaced_at=issued_at,
    )
    if recovery_device is not None:
        # The target protects an unconsumed recovery command from device
        # cleanup. Recovery makes one enrollment attempt authoritative, so all
        # sibling one-shot capabilities must close in this same transaction.
        _close_sibling_recovery_pairing_codes(
            db,
            device_id=recovery_device.id,
            consumed_pairing_id=pairing.id,
            closed_at=issued_at,
        )
        # The durable DeviceEnrollmentAttempt is now the replay receipt;
        # retaining the consumed code's FK would make that Device undeletable
        # forever under the intentional RESTRICT constraint.
        pairing.recovery_device_id = None
    token_expires_at, soft_refresh_after = _session_window(
        platform=device.platform,
        issued_at=issued_at,
    )
    _create_auth_token(
        db,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        scope="app",
        expires_at=token_expires_at,
        token_value=proof.session_token,
    )
    attempt = record_enrollment_attempt(
        db,
        proof=proof,
        pairing_code_id=pairing.id,
        account_id=account.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        issued_at=issued_at,
        session_expires_at=token_expires_at,
        session_soft_refresh_after=soft_refresh_after,
    )
    return PairingCompletion(ledger, account, device, role, attempt)


def _recover_pairing_completion(
    db: Session,
    *,
    pairing: PairingCode,
    proof: EnrollmentProof,
    attempt: DeviceEnrollmentAttempt,
    remote_id: str | None,
    issued_at: datetime,
) -> PairingCompletion:
    if not enrollment_attempt_proves_source(
        attempt,
        proof,
        pairing_code_id=pairing.id,
    ):
        _reject_pairing(db, remote_id, "invalid_pairing_code", 401)
    identity = recover_enrollment_identity(
        db,
        attempt=attempt,
        proof=proof,
        expired_error="pairing_attempt_expired",
        closed_error="pairing_attempt_closed",
    )
    attempt.last_issued_at = issued_at
    return PairingCompletion(
        identity.ledger,
        identity.account,
        identity.device,
        identity.role,
        attempt,
    )


def _pairing_result(proof: EnrollmentProof, completion: PairingCompletion) -> PairingResult:
    return PairingResult(
        session_token=proof.session_token,
        pairing_attempt_id=completion.attempt.public_id,
        account_public_id=completion.account.public_id,
        device_public_id=completion.device.public_id,
        account_name=completion.account.display_name,
        ledger_id=completion.ledger.ledger_id,
        ledger_name=completion.ledger.name,
        device_name=completion.device.device_name,
        role=completion.role,
        expires_at=completion.attempt.session_expires_at,
        soft_refresh_after=completion.attempt.session_soft_refresh_after,
    )


def pair_device(
    db: Session,
    *,
    pairing_code: str,
    pairing_attempt_id: str,
    pairing_attempt_secret: str,
    device_name: str,
    platform: str,
    remote_id: str | None = None,
) -> PairingResult:
    lock_bootstrap_owner_transaction(db)
    _check_pairing_attempt_limit(db, remote_id)
    proof = prepare_enrollment_proof(pairing_attempt_id, pairing_attempt_secret)
    code_hash = hash_pairing_code(pairing_code.strip())
    pairing = _load_pairing_code(
        db,
        code_hash=code_hash,
        remote_id=remote_id,
    )

    used_at = now_utc()
    attempt = load_enrollment_attempt(db, public_id=proof.public_id)
    if attempt is None:
        completion = _create_pairing_completion(
            db,
            pairing=pairing,
            proof=proof,
            device_name=device_name,
            platform=platform,
            remote_id=remote_id,
            issued_at=used_at,
        )
    else:
        completion = _recover_pairing_completion(
            db,
            pairing=pairing,
            proof=proof,
            attempt=attempt,
            remote_id=remote_id,
            issued_at=used_at,
        )

    _clear_pairing_failures(db, remote_id)
    db.commit()
    return _pairing_result(proof, completion)
