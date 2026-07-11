"""Credential rotation after a bootstrap listener exposure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    Invitation,
    Ledger,
    LedgerMember,
    PairingCode,
    UploadLink,
)
from app.services.identity_service._bootstrap import (
    _BootstrapCredentials,
    _completed_bootstrap_result,
    _derive_bootstrap_credentials,
    _load_completed_bootstrap_credentials,
    is_bootstrap_secret_consumed,
)
from app.services.identity_service._models import PAIRING_CODE_TTL_MINUTES, BootstrapResult
from app.services.identity_service._seed import auth_token_count
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import (
    hash_pairing_code,
    hash_secret,
    upload_link_expires_at,
)
from app.services.time_service import ensure_utc, now_utc


@dataclass(frozen=True)
class _BootstrapPrincipalIdentity:
    account: Account
    device: Device
    ledger: Ledger
    membership: LedgerMember


class ReplacementCredentialCollisionError(ValueError):
    """A deterministic replacement credential already exists in history."""


def _load_recoverable_bootstrap_identity(
    db: Session,
    *,
    admin: AuthToken,
) -> _BootstrapPrincipalIdentity | None:
    """Load the deterministic principal without trusting mutable owner state."""
    account = db.get(Account, admin.account_id)
    device = db.get(Device, admin.device_id)
    ledger = db.scalar(
        select(Ledger).where(Ledger.ledger_id == admin.ledger_id).limit(1)
    )
    membership = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == admin.ledger_id)
        .where(LedgerMember.account_id == admin.account_id)
        .limit(1)
    )
    if (
        account is None
        or device is None
        or ledger is None
        or membership is None
        or device.account_id != account.id
    ):
        return None
    return _BootstrapPrincipalIdentity(
        account=account,
        device=device,
        ledger=ledger,
        membership=membership,
    )


def _set_revoked_once(record: AuthToken | UploadLink | Device, at: datetime) -> None:
    if record.revoked_at is None:
        record.revoked_at = at


def _set_disabled_once(record: Account | LedgerMember, at: datetime) -> None:
    if record.disabled_at is None:
        record.disabled_at = at


def _assert_replacement_credentials_available(
    db: Session,
    *,
    credentials: _BootstrapCredentials,
    secret_hash: str,
) -> None:
    admin_token_hash = hash_secret(credentials.admin_token)
    upload_key_hash = hash_secret(credentials.upload_key)
    pairing_code_hash = hash_pairing_code(credentials.pairing_code)
    if is_bootstrap_secret_consumed(db, secret_hash=secret_hash):
        raise ReplacementCredentialCollisionError
    if db.scalar(select(AuthToken.id).where(AuthToken.token_hash == admin_token_hash).limit(1)):
        raise ReplacementCredentialCollisionError
    if db.scalar(select(UploadLink.id).where(UploadLink.token_hash == upload_key_hash).limit(1)):
        raise ReplacementCredentialCollisionError
    if db.scalar(select(PairingCode.id).where(PairingCode.code_hash == pairing_code_hash).limit(1)):
        raise ReplacementCredentialCollisionError


def _exposure_invitation_descendant_ids(
    db: Session,
    *,
    identity: _BootstrapPrincipalIdentity,
    exposure_started_at: datetime,
    rotated_at: datetime,
) -> tuple[int, ...]:
    """Follow every invitation-derived principal created during exposure.

    Invitation acceptance always creates a fresh account, so the stored
    ``created_by -> used_by`` edges are a provenance graph rather than a fuzzy
    name/time heuristic. Traverse it across ledgers: an exposed owner can create
    another ledger, transfer ownership to a first-generation invitee, and let
    that account mint the next invitation.
    """

    root_account_id = identity.account.id
    edges: dict[int, set[int]] = {}
    for creator_id, used_by_id in db.execute(
        select(Invitation.created_by_account_id, Invitation.used_by_account_id)
        .where(Invitation.used_at.is_not(None))
        .where(Invitation.used_at >= exposure_started_at)
        .where(Invitation.used_at <= rotated_at)
        .where(Invitation.used_by_account_id.is_not(None))
    ):
        edges.setdefault(int(creator_id), set()).add(int(used_by_id))
    descendants: set[int] = set()
    frontier = {root_account_id}
    while frontier:
        discovered = {
            account_id
            for creator_id in frontier
            for account_id in edges.get(creator_id, ())
        }
        discovered.discard(root_account_id)
        discovered.difference_update(descendants)
        if not discovered:
            break
        descendants.update(discovered)
        frontier = discovered
    return tuple(sorted(descendants))


def _revoke_invited_principals(
    db: Session,
    *,
    account_ids: tuple[int, ...],
    rotated_at: datetime,
) -> None:
    if not account_ids:
        return
    for token in db.scalars(
        select(AuthToken)
        .where(AuthToken.account_id.in_(account_ids))
    ):
        _set_revoked_once(token, rotated_at)
        token.grace_until = None
    for link in db.scalars(
        select(UploadLink).where(UploadLink.account_id.in_(account_ids))
    ):
        _set_revoked_once(link, rotated_at)
    for device in db.scalars(
        select(Device).where(Device.account_id.in_(account_ids))
    ):
        _set_revoked_once(device, rotated_at)
    for pairing in db.scalars(
        select(PairingCode).where(PairingCode.account_id.in_(account_ids))
    ):
        current_expiration = ensure_utc(pairing.expires_at)
        if current_expiration is None or current_expiration > rotated_at:
            pairing.expires_at = rotated_at
    for membership in db.scalars(
        select(LedgerMember).where(LedgerMember.account_id.in_(account_ids))
    ):
        _set_disabled_once(membership, rotated_at)
    for invitation in db.scalars(
        select(Invitation)
        .where(Invitation.created_by_account_id.in_(account_ids))
        .where(Invitation.used_at.is_(None))
        .where(Invitation.revoked_at.is_(None))
    ):
        invitation.revoked_at = rotated_at
    for invited_account in db.scalars(select(Account).where(Account.id.in_(account_ids))):
        _set_disabled_once(invited_account, rotated_at)


def _quarantine_exposure_ledgers(
    db: Session,
    *,
    identity: _BootstrapPrincipalIdentity,
    descendant_account_ids: tuple[int, ...],
    exposure_started_at: datetime,
    rotated_at: datetime,
) -> None:
    possible_owner_ids = (identity.account.id, *descendant_account_ids)
    for ledger in db.scalars(
        select(Ledger)
        .where(Ledger.ledger_id != identity.ledger.ledger_id)
        .where(Ledger.owner_account_id.in_(possible_owner_ids))
        .where(Ledger.created_at >= exposure_started_at)
        .where(Ledger.created_at <= rotated_at)
    ):
        if ledger.archived_at is None:
            ledger.archived_at = rotated_at


def _revoke_bootstrap_principal_derivatives(
    db: Session,
    *,
    identity: _BootstrapPrincipalIdentity,
    records: tuple[AuthToken, UploadLink, PairingCode],
    exposure_started_at: datetime,
    rotated_at: datetime,
) -> None:
    account = identity.account
    bootstrap_device = identity.device
    admin, upload, pairing = records
    for token in db.scalars(
        select(AuthToken).where(AuthToken.account_id == account.id).where(AuthToken.id != admin.id)
    ):
        _set_revoked_once(token, rotated_at)
        token.grace_until = None
    for link in db.scalars(
        select(UploadLink).where(UploadLink.account_id == account.id).where(UploadLink.id != upload.id)
    ):
        _set_revoked_once(link, rotated_at)
    for device in db.scalars(
        select(Device).where(Device.account_id == account.id).where(Device.id != bootstrap_device.id)
    ):
        _set_revoked_once(device, rotated_at)
    for other_pairing in db.scalars(
        select(PairingCode)
        .where(PairingCode.account_id == account.id)
        .where(PairingCode.id != pairing.id)
    ):
        current_expiration = ensure_utc(other_pairing.expires_at)
        if current_expiration is None or current_expiration > rotated_at:
            other_pairing.expires_at = rotated_at
    for invitation in db.scalars(
        select(Invitation)
        .where(Invitation.created_by_account_id == account.id)
        .where(Invitation.created_at >= exposure_started_at)
        .where(Invitation.created_at <= rotated_at)
        .where(Invitation.used_at.is_(None))
        .where(Invitation.revoked_at.is_(None))
        .where(Invitation.expires_at > rotated_at)
    ):
        invitation.revoked_at = rotated_at


def _revoke_exposure_window_credentials(
    db: Session,
    *,
    identity: _BootstrapPrincipalIdentity,
    records: tuple[AuthToken, UploadLink, PairingCode],
    exposure_started_at: datetime,
    rotated_at: datetime,
) -> None:
    invitation_account_ids = _exposure_invitation_descendant_ids(
        db,
        identity=identity,
        exposure_started_at=exposure_started_at,
        rotated_at=rotated_at,
    )
    _revoke_invited_principals(
        db,
        account_ids=invitation_account_ids,
        rotated_at=rotated_at,
    )
    _quarantine_exposure_ledgers(
        db,
        identity=identity,
        descendant_account_ids=invitation_account_ids,
        exposure_started_at=exposure_started_at,
        rotated_at=rotated_at,
    )
    _revoke_bootstrap_principal_derivatives(
        db,
        identity=identity,
        records=records,
        exposure_started_at=exposure_started_at,
        rotated_at=rotated_at,
    )


def _restore_bootstrap_principal(
    db: Session,
    *,
    identity: _BootstrapPrincipalIdentity,
) -> None:
    """Restore only the principal anchored by the deterministic credentials."""
    account = identity.account
    device = identity.device
    ledger = identity.ledger
    membership = identity.membership
    account.disabled_at = None
    device.revoked_at = None
    ledger.archived_at = None
    ledger.owner_account_id = account.id
    membership.disabled_at = None
    membership.role = "owner"
    for other_owner in db.scalars(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == ledger.ledger_id)
        .where(LedgerMember.role == "owner")
        .where(LedgerMember.id != membership.id)
    ):
        other_owner.role = "member"


def _replace_credentials(
    db: Session,
    *,
    records: tuple[AuthToken, UploadLink, PairingCode],
    credentials: _BootstrapCredentials,
    secret_hash: str,
    rotated_at: datetime,
) -> None:
    admin, upload, pairing = records
    admin.token_hash = hash_secret(credentials.admin_token)
    admin.revoked_at = None
    admin.grace_until = None
    upload.token_hash = hash_secret(credentials.upload_key)
    upload.revoked_at = None
    upload.expires_at = upload_link_expires_at(rotated_at)
    pairing.code_hash = hash_pairing_code(credentials.pairing_code)
    pairing.used_at = None
    pairing.expires_at = rotated_at + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)
    db.add(BootstrapSecretConsumption(secret_hash=secret_hash))
    db.flush()


def _recover_completed_rotation(
    db: Session,
    *,
    credentials: _BootstrapCredentials,
) -> BootstrapResult | None:
    records = _load_completed_bootstrap_credentials(
        db,
        admin_token=credentials.admin_token,
        upload_key=credentials.upload_key,
        pairing_code=credentials.pairing_code,
    )
    if records is None:
        return None
    _admin, upload, _pairing = records
    if upload.revoked_at is not None:
        return None

    return _completed_bootstrap_result(
        db,
        admin_token=credentials.admin_token,
        upload_key=credentials.upload_key,
        pairing_code=credentials.pairing_code,
    )


def rotate_exposed_bootstrap_credentials(
    db: Session,
    *,
    exposed_secret: str,
    replacement_secret: str,
    commit: bool = True,
) -> BootstrapResult | None:
    """Invalidate a possibly exposed secret while preserving owner recovery.

    ``None`` means the exposed request never committed an owner identity; the
    replacement secret can perform the normal first bootstrap after restart.
    """
    if exposed_secret == replacement_secret:
        raise ValueError("replacement bootstrap secret must differ")
    exposed = _derive_bootstrap_credentials(exposed_secret)
    replacement = _derive_bootstrap_credentials(replacement_secret)
    replacement_secret_hash = hash_secret(replacement_secret)
    exposed_secret_hash = hash_secret(exposed_secret)

    lock_bootstrap_owner_transaction(db)
    records = _load_completed_bootstrap_credentials(
        db,
        admin_token=exposed.admin_token,
        upload_key=exposed.upload_key,
        pairing_code=exposed.pairing_code,
    )
    if records is None:
        if is_bootstrap_secret_consumed(db, secret_hash=replacement_secret_hash):
            result = _recover_completed_rotation(db, credentials=replacement)
            if result is None:
                raise AppError("invalid_bootstrap_secret", status_code=401)
            if commit:
                db.commit()
            return result
        if auth_token_count(db) > 0:
            raise AppError("invalid_bootstrap_secret", status_code=401)
        return None

    admin, _upload, _pairing = records
    identity = _load_recoverable_bootstrap_identity(db, admin=admin)
    if identity is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    exposed_consumption = db.get(BootstrapSecretConsumption, exposed_secret_hash)
    if exposed_consumption is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    exposure_started_at = ensure_utc(exposed_consumption.consumed_at)
    if exposure_started_at is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    _assert_replacement_credentials_available(
        db,
        credentials=replacement,
        secret_hash=replacement_secret_hash,
    )
    rotated_at = now_utc()
    _revoke_exposure_window_credentials(
        db,
        identity=identity,
        records=records,
        exposure_started_at=exposure_started_at,
        rotated_at=rotated_at,
    )
    _restore_bootstrap_principal(db, identity=identity)
    _replace_credentials(
        db,
        records=records,
        credentials=replacement,
        secret_hash=replacement_secret_hash,
        rotated_at=rotated_at,
    )
    result = _completed_bootstrap_result(
        db,
        admin_token=replacement.admin_token,
        upload_key=replacement.upload_key,
        pairing_code=replacement.pairing_code,
    )
    if result is None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    if commit:
        db.commit()
    return result
