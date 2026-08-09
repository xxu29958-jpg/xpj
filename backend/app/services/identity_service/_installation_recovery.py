"""Recover an exposed installation-owner child under its original claim."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    DeviceEnrollmentAttempt,
    InstallationOwnerClaim,
    PairingCode,
)
from app.services.identity_service import _installation_claim as installation_claim
from app.services.identity_service._bootstrap import is_bootstrap_secret_consumed
from app.services.identity_service._models import (
    PAIRING_CODE_TTL_MINUTES,
    InstallationOwnerBootstrapResult,
    ReplacementCredentialCollisionError,
)
from app.services.session_lifecycle_service import hash_pairing_code, hash_secret
from app.services.time_service import ensure_utc, now_utc


def _revoke_pairing_descendant(
    db: Session,
    *,
    pairing: PairingCode,
    revoked_at,
) -> None:
    attempt = db.scalar(
        select(DeviceEnrollmentAttempt)
        .where(DeviceEnrollmentAttempt.pairing_code_id == pairing.id)
        .limit(1)
    )
    if attempt is None:
        return
    if attempt.account_id != pairing.account_id or attempt.ledger_id != pairing.ledger_id:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    device = db.get(Device, attempt.device_id)
    if device is None or device.account_id != pairing.account_id:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    if device.revoked_at is None:
        device.revoked_at = revoked_at
    for token in db.scalars(
        select(AuthToken).where(AuthToken.device_id == device.id).with_for_update()
    ):
        if token.revoked_at is None:
            token.revoked_at = revoked_at
        token.grace_until = None


def _publish_replacement_pairing(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    previous: PairingCode,
    replacement_secret: str,
    replacement_hash: str,
    rotated_at,
) -> None:
    code, derivation_index = installation_claim.pairing_candidate(
        db,
        secret=replacement_secret,
    )
    replacement = PairingCode(
        code_hash=hash_pairing_code(code),
        ledger_id=claim.ledger_id,
        account_id=claim.account_id,
        created_by_device_id=claim.device_id,
        device_name_hint=previous.device_name_hint,
        expires_at=rotated_at + timedelta(minutes=PAIRING_CODE_TTL_MINUTES),
        created_at=rotated_at,
    )
    db.add(replacement)
    db.add(BootstrapSecretConsumption(secret_hash=replacement_hash))
    db.flush()
    claim.active_secret_hash = replacement_hash
    claim.pairing_code_id = replacement.id
    claim.pairing_derivation_index = derivation_index
    claim.generation += 1
    claim.updated_at = rotated_at
    db.flush()


def _result_for_replacement(
    db: Session,
    *,
    replacement_hash: str,
    replacement_secret: str,
) -> InstallationOwnerBootstrapResult | None:
    claim = db.scalar(
        select(InstallationOwnerClaim)
        .where(InstallationOwnerClaim.active_secret_hash == replacement_hash)
        .with_for_update()
        .limit(1)
    )
    if claim is None:
        return None
    return installation_claim.claim_result(
        db,
        claim=claim,
        secret=replacement_secret,
        operation_id=claim.operation_id,
        installation_id=claim.installation_id,
        request_fingerprint=claim.request_fingerprint,
    )


def rotate_installation_owner_claim(
    db: Session,
    *,
    exposed_secret: str,
    replacement_secret: str,
) -> tuple[bool, InstallationOwnerBootstrapResult | None]:
    """Rotate only the child; the installation operation remains unchanged."""

    exposed_hash = hash_secret(exposed_secret)
    replacement_hash = hash_secret(replacement_secret)
    replay = _result_for_replacement(
        db,
        replacement_hash=replacement_hash,
        replacement_secret=replacement_secret,
    )
    if replay is not None:
        return True, replay

    claim = db.scalar(
        select(InstallationOwnerClaim)
        .where(InstallationOwnerClaim.active_secret_hash == exposed_hash)
        .with_for_update()
        .limit(1)
    )
    if claim is None:
        return False, None
    if db.get(BootstrapSecretConsumption, exposed_hash) is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    if is_bootstrap_secret_consumed(db, secret_hash=replacement_hash):
        raise ReplacementCredentialCollisionError

    old_pairing = db.get(PairingCode, claim.pairing_code_id, with_for_update=True)
    if old_pairing is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    rotated_at = now_utc()
    _revoke_pairing_descendant(db, pairing=old_pairing, revoked_at=rotated_at)
    if old_pairing.revoked_at is None:
        old_pairing.revoked_at = rotated_at
    old_expiration = ensure_utc(old_pairing.expires_at)
    if old_expiration is None or old_expiration > rotated_at:
        old_pairing.expires_at = rotated_at
    _publish_replacement_pairing(
        db,
        claim=claim,
        previous=old_pairing,
        replacement_secret=replacement_secret,
        replacement_hash=replacement_hash,
        rotated_at=rotated_at,
    )
    result = _result_for_replacement(
        db,
        replacement_hash=replacement_hash,
        replacement_secret=replacement_secret,
    )
    if result is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    return True, result
