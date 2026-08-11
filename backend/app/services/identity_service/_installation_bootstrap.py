"""Create or replay a Windows installation-owner claim transaction."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.services.identity_service._installation_claim as installation_claim
from app.errors import AppError
from app.models import InstallationOwnerClaim, PairingCode
from app.services.identity_service._bootstrap import (
    is_bootstrap_secret_consumed,
    record_bootstrap_secret_consumption,
)
from app.services.identity_service._device import _create_device
from app.services.identity_service._models import (
    DEFAULT_ACCOUNT_NAME,
    PAIRING_CODE_TTL_MINUTES,
    InstallationOwnerBootstrapResult,
)
from app.services.identity_service._seed import (
    _ensure_ledger,
    _owner_account,
    auth_token_count,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import hash_pairing_code, hash_secret
from app.services.time_service import ensure_utc, now_utc
from app.tenants import DEFAULT_TENANT_ID


def _replay_claim(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    secret: str,
    operation_id: str,
    installation_id: str,
    request_fingerprint: str,
) -> InstallationOwnerBootstrapResult:
    account, device, ledger, pairing, code = installation_claim.validated_bindings(
        db,
        claim=claim,
        secret=secret,
        operation_id=operation_id,
        installation_id=installation_id,
        request_fingerprint=request_fingerprint,
    )
    expiration = ensure_utc(pairing.expires_at)
    checked_at = now_utc()
    if expiration is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    if expiration <= checked_at:
        return installation_claim.replace_expired_pairing(
            db,
            claim=claim,
            secret=secret,
            account=account,
            device=device,
            ledger=ledger,
            expired_pairing=pairing,
            replaced_at=checked_at,
        )
    return installation_claim.result_from_bindings(
        claim=claim,
        account=account,
        device=device,
        ledger=ledger,
        pairing=pairing,
        code=code,
    )


def _create_claim(
    db: Session,
    *,
    operation_id: str,
    installation_id: str,
    secret: str,
    account_label: str,
    ledger_label: str,
    device_label: str,
    request_fingerprint: str,
) -> InstallationOwnerBootstrapResult:
    secret_hash = hash_secret(secret)
    existing_claim = db.scalar(select(InstallationOwnerClaim.operation_id).limit(1))
    if existing_claim is not None or auth_token_count(db) > 0:
        raise AppError("bootstrap_already_initialized", status_code=409)
    if is_bootstrap_secret_consumed(db, secret_hash=secret_hash):
        raise AppError("invalid_bootstrap_secret", status_code=401)
    if not record_bootstrap_secret_consumption(db, secret_hash=secret_hash):
        raise AppError("invalid_bootstrap_secret", status_code=401)

    owner = _owner_account(db, account_label)
    if owner.display_name == DEFAULT_ACCOUNT_NAME:
        owner.display_name = account_label
    ledger = _ensure_ledger(
        db,
        ledger_id=DEFAULT_TENANT_ID,
        name=ledger_label,
        owner_account=owner,
    )
    device = _create_device(db, owner.id, device_label, "windows")
    code, derivation_index = installation_claim.pairing_candidate(db, secret=secret)
    created_at = now_utc()
    pairing = PairingCode(
        code_hash=hash_pairing_code(code),
        ledger_id=ledger.ledger_id,
        account_id=owner.id,
        created_by_device_id=device.id,
        device_name_hint="小票夹 Desktop",
        expires_at=created_at + timedelta(minutes=PAIRING_CODE_TTL_MINUTES),
        created_at=created_at,
    )
    db.add(pairing)
    db.flush()
    claim = InstallationOwnerClaim(
        operation_id=operation_id,
        installation_id=installation_id,
        request_fingerprint=request_fingerprint,
        active_secret_hash=secret_hash,
        account_id=owner.id,
        device_id=device.id,
        ledger_id=ledger.ledger_id,
        pairing_code_id=pairing.id,
        pairing_derivation_index=derivation_index,
        generation=1,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(claim)
    db.flush()
    return installation_claim.claim_result(
        db,
        claim=claim,
        secret=secret,
        operation_id=operation_id,
        installation_id=installation_id,
        request_fingerprint=request_fingerprint,
    )


def bootstrap_installation_owner(
    db: Session,
    *,
    operation_id: str,
    installation_id: str,
    bootstrap_secret: str,
    account_name: str | None = None,
    ledger_name: str | None = None,
    device_name: str | None = None,
    commit: bool = True,
) -> InstallationOwnerBootstrapResult:
    """Create or replay one machine claim without issuing user credentials."""

    operation = installation_claim.identifier(operation_id, field="operation_id")
    installation = installation_claim.identifier(
        installation_id,
        field="installation_id",
    )
    account, ledger, device, fingerprint = installation_claim.canonical_request(
        account_name=account_name,
        ledger_name=ledger_name,
        device_name=device_name,
    )
    lock_bootstrap_owner_transaction(db)
    claim = db.scalar(
        select(InstallationOwnerClaim)
        .where(InstallationOwnerClaim.operation_id == operation)
        .with_for_update()
        .limit(1)
    )
    if claim is None:
        result = _create_claim(
            db,
            operation_id=operation,
            installation_id=installation,
            secret=bootstrap_secret,
            account_label=account,
            ledger_label=ledger,
            device_label=device,
            request_fingerprint=fingerprint,
        )
    else:
        result = _replay_claim(
            db,
            claim=claim,
            secret=bootstrap_secret,
            operation_id=operation,
            installation_id=installation,
            request_fingerprint=fingerprint,
        )
    if commit:
        db.commit()
    return result
