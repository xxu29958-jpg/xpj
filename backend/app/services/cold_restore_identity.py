"""Rebind one isolated cold dataset; never rewrite financial facts or receipts."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    DatasetAuthorityRecord,
    DesktopActivationAttempt,
    Device,
    DeviceEnrollmentAttempt,
    InstallationOwnerClaim,
    Invitation,
    Ledger,
    LedgerMember,
    PairingCode,
    SessionRefreshAttempt,
    UploadLink,
)
from app.services.identity_service import _installation_claim as claims
from app.services.identity_service._models import PAIRING_CODE_TTL_MINUTES, InstallationOwnerBootstrapResult
from app.services.session_lifecycle_service import hash_pairing_code, hash_secret
from app.services.time_service import now_utc


def rebind_cold_dataset(db: Session, *, source: dict, installation_id: str, backup_id: str,
                       operation_id: str, bootstrap_secret: str, recovery_secret: str) -> InstallationOwnerBootstrapResult:
    """The maintenance owner commits this together with the new dataset generation."""
    authority = db.get(DatasetAuthorityRecord, 1, with_for_update=True)
    rows = list(db.scalars(select(InstallationOwnerClaim).with_for_update().limit(2)))
    if authority is None or len(rows) != 1:
        raise AppError("restore_identity_missing", "冷备缺少完整的数据集与安装身份；恢复候选保持关闭。", status_code=409)
    claim = rows[0]
    fingerprint = hashlib.sha256((operation_id + "\0" + backup_id).encode()).hexdigest()
    if authority.client_generation == installation_id and authority.restored_from_backup_id == backup_id:
        return claims.claim_result(db, claim=claim, secret=bootstrap_secret, operation_id=operation_id,
            installation_id=installation_id, request_fingerprint=fingerprint)
    _require_source_authority(authority, claim, source, installation_id)
    account = _authorized_owner(db, claim, recovery_secret)
    return _publish_restored_identity(db, authority, claim, account, installation_id=installation_id,
        backup_id=backup_id, operation_id=operation_id, bootstrap_secret=bootstrap_secret, fingerprint=fingerprint)


def _require_source_authority(authority, claim, source, installation_id) -> None:
    if (
        authority.dataset_id != source["dataset_id"]
        or authority.client_generation != source["install_id"]
        or authority.restore_epoch != source["restore_epoch"]
        or authority.schema_revision != source["schema_revision"]
        or authority.semantic_revision != "ticketbox-dataset-semantics-v1"
        or claim.installation_id != source["install_id"]
        or installation_id == source["install_id"]
    ):
        raise AppError("restore_identity_mismatch", "冷备身份与所选恢复点不匹配；恢复候选保持关闭。", status_code=409)


def _authorized_owner(db: Session, claim: InstallationOwnerClaim, recovery_secret: str) -> Account:
    recovery_hash = hash_secret(recovery_secret)
    if (not hmac.compare_digest(claim.active_secret_hash, recovery_hash)
            or db.get(BootstrapSecretConsumption, recovery_hash) is None):
        raise AppError("restore_recovery_unauthorized", "恢复材料无法证明原安装的业务身份授权。", status_code=403)
    account = db.get(Account, claim.account_id)
    ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == claim.ledger_id))
    member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == claim.ledger_id,
        LedgerMember.account_id == claim.account_id))
    if (account is None or account.disabled_at is not None or ledger is None or ledger.archived_at is not None
            or ledger.owner_account_id != account.id or member is None
            or member.disabled_at is not None or member.role != "owner"):
        raise AppError("restore_owner_unavailable", "原安装的 Owner 身份或账本角色不可用；无法签发恢复配对。", status_code=409)
    return account


def _publish_restored_identity(db: Session, authority, claim, account, *, installation_id: str,
                              backup_id: str, operation_id: str, bootstrap_secret: str,
                              fingerprint: str) -> InstallationOwnerBootstrapResult:
    timestamp = now_utc()
    # Preserve credential history, but no credential recovered from the snapshot
    # (including a refresh/enrollment response) can regain access to the new host.
    db.execute(update(AuthToken).where(AuthToken.revoked_at.is_(None)).values(revoked_at=timestamp))
    db.execute(update(Device).where(Device.revoked_at.is_(None)).values(revoked_at=timestamp))
    db.execute(update(PairingCode).where(PairingCode.revoked_at.is_(None)).values(revoked_at=timestamp))
    db.execute(update(UploadLink).where(UploadLink.revoked_at.is_(None)).values(revoked_at=timestamp))
    db.execute(update(Invitation).where(Invitation.revoked_at.is_(None)).values(revoked_at=timestamp))
    db.execute(update(AuthToken).values(grace_until=None))
    db.execute(update(DeviceEnrollmentAttempt).values(expires_at=timestamp))
    db.execute(update(DesktopActivationAttempt).values(expires_at=timestamp))
    db.execute(update(SessionRefreshAttempt).values(expires_at=timestamp))
    device = Device(account_id=account.id, device_name="Windows 恢复来源", platform="windows")
    db.add(device)
    db.flush()
    code, index = claims.pairing_candidate(db, secret=bootstrap_secret)
    pairing = PairingCode(code_hash=hash_pairing_code(code), ledger_id=claim.ledger_id, account_id=account.id,
        created_by_device_id=device.id, device_name_hint="小票夹 Desktop",
        expires_at=timestamp + timedelta(minutes=PAIRING_CODE_TTL_MINUTES), created_at=timestamp)
    secret_hash = hash_secret(bootstrap_secret)
    db.add(BootstrapSecretConsumption(secret_hash=secret_hash, consumed_at=timestamp))
    db.add(pairing)
    db.flush()
    claim.operation_id = operation_id
    claim.installation_id = installation_id
    claim.request_fingerprint = fingerprint
    claim.active_secret_hash = secret_hash
    claim.device_id = device.id
    claim.pairing_code_id = pairing.id
    claim.pairing_derivation_index = index
    claim.generation += 1
    claim.updated_at = timestamp
    authority.client_generation = installation_id
    authority.restore_epoch += 1
    authority.restored_from_backup_id = backup_id
    # Same-environment recovery preserves database signing/audit identity.
    # Every recovered bearer and one-shot grant above is nevertheless revoked.
    db.flush()
    return claims.claim_result(db, claim=claim, secret=bootstrap_secret, operation_id=operation_id,
        installation_id=installation_id, request_fingerprint=fingerprint)
