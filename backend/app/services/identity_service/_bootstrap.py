"""First-time owner bootstrap: account + ledger + device + token + upload + pairing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    InstallationOwnerClaim,
    Ledger,
    LedgerMember,
    PairingCode,
    UploadLink,
)
from app.services.identity_service._device import (
    _create_auth_token,
    _create_device,
    _create_pairing_code,
    _create_upload_link,
)
from app.services.identity_service._models import (
    DEFAULT_ACCOUNT_NAME,
    DEFAULT_BOOTSTRAP_DEVICE_NAME,
    PAIRING_CODE_TTL_MINUTES,
    BootstrapResult,
)
from app.services.identity_service._seed import (
    _clean_name,
    _ensure_ledger,
    _owner_account,
    auth_token_count,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import (
    derive_bootstrap_admin_token,
    derive_bootstrap_pairing_code,
    derive_bootstrap_upload_key,
    hash_pairing_code,
    hash_secret,
)
from app.services.time_service import ensure_utc, now_utc, to_iso
from app.tenants import DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME


@dataclass(frozen=True)
class _BootstrapCredentials:
    admin_token: str
    upload_key: str
    pairing_code: str


def is_bootstrap_secret_consumed(db: Session, *, secret_hash: str) -> bool:
    """Has this one-shot bootstrap secret hash already been recorded?"""
    return (
        db.scalar(
            select(BootstrapSecretConsumption.secret_hash)
            .where(BootstrapSecretConsumption.secret_hash == secret_hash)
            .limit(1)
        )
        is not None
    )


def record_bootstrap_secret_consumption(db: Session, *, secret_hash: str) -> bool:
    """Mark a one-shot bootstrap secret as consumed.

    Returns ``True`` if this call recorded the consumption, ``False`` if
    a concurrent caller already recorded the same hash. The insert is done
    before identity creation, so the primary-key row serializes concurrent
    requests for one secret while remaining in the same rollback boundary.
    Non-UNIQUE ``IntegrityError`` (real schema bug) is re-raised.
    """
    try:
        db.add(BootstrapSecretConsumption(secret_hash=secret_hash))
        db.flush()
    except IntegrityError:
        db.rollback()
        if is_bootstrap_secret_consumed(db, secret_hash=secret_hash):
            return False
        raise
    return True


def _load_completed_bootstrap_credentials(
    db: Session,
    *,
    admin_token: str,
    upload_key: str,
    pairing_code: str,
) -> tuple[AuthToken, UploadLink, PairingCode] | None:
    # Lock pairing first so consumption cannot race the recovery validity check.
    # All remaining checks are MVCC reads, avoiding a Device -> AuthToken ->
    # recovery lock cycle during concurrent revocation.
    pairing = db.scalar(
        select(PairingCode)
        .where(PairingCode.code_hash == hash_pairing_code(pairing_code))
        .with_for_update()
        .limit(1)
    )
    admin = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == hash_secret(admin_token))
        .limit(1)
    )
    upload = db.scalar(
        select(UploadLink)
        .where(UploadLink.token_hash == hash_secret(upload_key))
        .limit(1)
    )
    if (
        admin is None
        or upload is None
        or pairing is None
        or admin.scope != "admin"
    ):
        return None

    principal = (admin.account_id, admin.device_id, admin.ledger_id)
    if (upload.account_id, upload.device_id, upload.ledger_id) != principal:
        return None
    if (pairing.account_id, pairing.ledger_id) != (
        admin.account_id,
        admin.ledger_id,
    ):
        return None
    return admin, upload, pairing


def _load_completed_bootstrap_identity(
    db: Session,
    *,
    admin: AuthToken,
) -> tuple[Account, Device, Ledger] | None:

    account = db.scalar(select(Account).where(Account.id == admin.account_id).limit(1))
    device = db.scalar(select(Device).where(Device.id == admin.device_id).limit(1))
    ledger = db.scalar(
        select(Ledger).where(Ledger.ledger_id == admin.ledger_id).limit(1)
    )
    owner_membership = db.scalar(
        select(LedgerMember.id)
        .where(LedgerMember.ledger_id == admin.ledger_id)
        .where(LedgerMember.account_id == admin.account_id)
        .where(LedgerMember.role == "owner")
        .where(LedgerMember.disabled_at.is_(None))
        .limit(1)
    )
    if (
        account is None
        or device is None
        or ledger is None
        or device.account_id != account.id
        or ledger.owner_account_id != account.id
        or owner_membership is None
    ):
        return None
    return account, device, ledger


def _bootstrap_recovery_principal_is_active(
    *,
    admin: AuthToken,
    upload: UploadLink,
    account: Account,
    device: Device,
    ledger: Ledger,
    recovered_at: datetime,
) -> bool:
    admin_expiration = ensure_utc(admin.expires_at)
    upload_expiration = ensure_utc(upload.expires_at)
    return not (
        account.disabled_at is not None
        or device.revoked_at is not None
        or ledger.archived_at is not None
        or admin.revoked_at is not None
        or (admin_expiration is not None and admin_expiration <= recovered_at)
        or upload.revoked_at is not None
        or upload_expiration is None
        or upload_expiration <= recovered_at
    )


def _pairing_expiration_for_recovery(
    pairing: PairingCode,
    *,
    issuer_device_id: int,
    recovered_at: datetime,
) -> str | None:

    if pairing.revoked_at is not None:
        # The schema migration revokes legacy unused codes because their issuer
        # cannot be proven from old rows. The exact deterministic bootstrap
        # credential triple supplies that missing proof on retry. Codes with a
        # known issuer remain intentionally revoked and must not be resurrected.
        if pairing.used_at is not None or pairing.created_by_device_id is not None:
            return None
        pairing.created_by_device_id = issuer_device_id
        pairing.revoked_at = None
        pairing.expires_at = recovered_at + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)

    pairing_expiration = ensure_utc(pairing.expires_at)
    if pairing_expiration is None:
        return None
    if pairing.used_at is None and pairing_expiration <= recovered_at:
        return None
    return to_iso(pairing.expires_at)


def _completed_bootstrap_result(
    db: Session,
    *,
    admin_token: str,
    upload_key: str,
    pairing_code: str,
) -> BootstrapResult | None:
    credentials = _load_completed_bootstrap_credentials(
        db,
        admin_token=admin_token,
        upload_key=upload_key,
        pairing_code=pairing_code,
    )
    if credentials is None:
        return None
    admin, upload, pairing = credentials

    identity = _load_completed_bootstrap_identity(db, admin=admin)
    if identity is None:
        return None
    account, device, ledger = identity

    recovered_at = now_utc()
    if not _bootstrap_recovery_principal_is_active(
        admin=admin,
        upload=upload,
        account=account,
        device=device,
        ledger=ledger,
        recovered_at=recovered_at,
    ):
        return None

    pairing_expires_at = _pairing_expiration_for_recovery(
        pairing,
        issuer_device_id=admin.device_id,
        recovered_at=recovered_at,
    )
    if pairing_expires_at is None:
        return None
    return BootstrapResult(
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        admin_token=admin_token,
        upload_key=upload_key,
        upload_url_path=f"/u/{upload_key}",
        pairing_code=pairing_code,
        pairing_expires_at=pairing_expires_at,
    )


def _recover_completed_bootstrap(
    db: Session,
    *,
    credentials: _BootstrapCredentials,
) -> BootstrapResult:
    result = _completed_bootstrap_result(
        db,
        admin_token=credentials.admin_token,
        upload_key=credentials.upload_key,
        pairing_code=credentials.pairing_code,
    )
    if result is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    return result


def _derive_bootstrap_credentials(secret: str) -> _BootstrapCredentials:
    return _BootstrapCredentials(
        admin_token=derive_bootstrap_admin_token(secret),
        upload_key=derive_bootstrap_upload_key(secret),
        pairing_code=derive_bootstrap_pairing_code(secret),
    )


def _claim_bootstrap_secret(
    db: Session,
    secret: str,
) -> tuple[_BootstrapCredentials, BootstrapResult | None]:
    credentials = _derive_bootstrap_credentials(secret)
    secret_hash = hash_secret(secret)
    consumed = is_bootstrap_secret_consumed(
        db,
        secret_hash=secret_hash,
    ) or not record_bootstrap_secret_consumption(db, secret_hash=secret_hash)
    if consumed:
        return credentials, _recover_completed_bootstrap(
            db,
            credentials=credentials,
        )
    return credentials, None


def bootstrap_owner(
    db: Session,
    *,
    account_name: str | None = None,
    ledger_name: str | None = None,
    device_name: str | None = None,
    default_timezone: str | None = None,
    bootstrap_secret: str | None = None,
    commit: bool = True,
) -> BootstrapResult:
    # Different one-shot secrets still compete for one global owner identity.
    # The transaction-scoped PostgreSQL lock spans claim, identity checks, and
    # the caller's commit, preventing two empty-database bootstraps from racing.
    lock_bootstrap_owner_transaction(db)
    credentials = None
    if bootstrap_secret is not None:
        credentials, recovered = _claim_bootstrap_secret(db, bootstrap_secret)
        if recovered is not None:
            if commit:
                db.commit()
            return recovered

    installation_claim_exists = db.scalar(
        select(InstallationOwnerClaim.operation_id).limit(1)
    )
    if installation_claim_exists is not None or auth_token_count(db) > 0:
        raise AppError("bootstrap_already_initialized", status_code=409)

    owner = _owner_account(db, _clean_name(account_name, DEFAULT_ACCOUNT_NAME))
    if account_name and owner.display_name == DEFAULT_ACCOUNT_NAME:
        owner.display_name = _clean_name(account_name, DEFAULT_ACCOUNT_NAME)
    default_ledger = _ensure_ledger(
        db,
        ledger_id=DEFAULT_TENANT_ID,
        name=_clean_name(ledger_name, DEFAULT_TENANT_NAME),
        owner_account=owner,
    )
    bootstrap_device = _create_device(
        db,
        owner.id,
        _clean_name(device_name, DEFAULT_BOOTSTRAP_DEVICE_NAME),
        "windows",
    )
    admin_token = _create_auth_token(
        db,
        account_id=owner.id,
        device_id=bootstrap_device.id,
        ledger_id=default_ledger.ledger_id,
        scope="admin",
        token_value=credentials.admin_token if credentials else None,
    )
    upload_key = _create_upload_link(
        db,
        account_id=owner.id,
        device_id=bootstrap_device.id,
        ledger_id=default_ledger.ledger_id,
        default_timezone=default_timezone or get_settings().ocr_default_timezone,
        upload_key_value=credentials.upload_key if credentials else None,
    )
    pairing = _create_pairing_code(
        db,
        ledger_id=default_ledger.ledger_id,
        account_id=owner.id,
        created_by_device_id=bootstrap_device.id,
        device_name_hint="Android",
        pairing_code_value=credentials.pairing_code if credentials else None,
    )
    if commit:
        db.commit()
    return BootstrapResult(
        account_name=owner.display_name,
        ledger_id=default_ledger.ledger_id,
        ledger_name=default_ledger.name,
        device_name=bootstrap_device.device_name,
        admin_token=admin_token,
        upload_key=upload_key,
        upload_url_path=f"/u/{upload_key}",
        pairing_code=pairing.pairing_code,
        pairing_expires_at=pairing.expires_at,
    )
