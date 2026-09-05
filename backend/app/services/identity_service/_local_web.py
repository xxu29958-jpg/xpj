"""Installed loopback Web identity preview.

The installation claim identifies an Account.  Network location and a
selected ledger never do.  Enrollment of the browser Device/session is added
by the command half of this module; the preview stays read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    Device,
    DeviceEnrollmentAttempt,
    InstallationOwnerClaim,
    Ledger,
    LedgerMember,
    PairingCode,
)
from app.services.identity_service._device import _create_pairing_code
from app.services.identity_service._enrollment import (
    load_enrollment_attempt,
    prepare_enrollment_proof,
)
from app.services.identity_service._models import PairingResult
from app.services.identity_service._pair import (
    _pairing_result,
    _recover_pairing_completion,
    pair_device,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.time_service import now_utc


@dataclass(frozen=True)
class LocalWebLedger:
    ledger_id: str
    name: str
    role: str
    is_installation_default: bool


@dataclass(frozen=True)
class LocalWebIdentityPreview:
    account_id: int
    account_public_id: str
    account_name: str
    ledgers: tuple[LocalWebLedger, ...]
    selected_ledger_id: str


def installation_web_identity_present(db: Session) -> bool:
    """Return whether this dataset carries an installation identity claim."""

    return db.scalar(select(InstallationOwnerClaim.operation_id).limit(1)) is not None


def _unique_installation_claim(
    db: Session,
    *,
    for_update: bool = False,
) -> InstallationOwnerClaim:
    statement = (
        select(InstallationOwnerClaim)
        .order_by(InstallationOwnerClaim.operation_id.asc())
        .limit(2)
    )
    if for_update:
        statement = statement.with_for_update()
    claims = list(db.scalars(statement))
    if len(claims) != 1:
        raise AppError(
            "installation_identity_recovery_required",
            "当前安装缺少唯一的本机身份，请先完成身份修复。",
            status_code=409,
        )
    return claims[0]


def _installation_identity(
    db: Session,
) -> tuple[InstallationOwnerClaim, Account]:
    claim = _unique_installation_claim(db)
    account = db.get(Account, claim.account_id)
    source_device = db.get(Device, claim.device_id)
    if (
        account is None
        or account.disabled_at is not None
        or source_device is None
        or source_device.account_id != claim.account_id
        or source_device.revoked_at is not None
    ):
        raise AppError(
            "installation_identity_recovery_required",
            "当前安装的本机身份不可用，请先完成身份修复。",
            status_code=409,
        )
    return claim, account


def resolve_installation_web_account_id(db: Session) -> int:
    """Resolve the live Account that an installed loopback browser must use."""

    _, account = _installation_identity(db)
    return account.id


def preview_installation_web_identity(db: Session) -> LocalWebIdentityPreview:
    """Resolve the one installation Account and its current live memberships."""

    claim, account = _installation_identity(db)

    rows = list(
        db.execute(
            select(Ledger, LedgerMember.role)
            .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
            .where(LedgerMember.account_id == account.id)
            .where(LedgerMember.disabled_at.is_(None))
            .where(Ledger.archived_at.is_(None))
            .order_by(Ledger.id.asc())
        ).all()
    )
    ledgers = tuple(
        LocalWebLedger(
            ledger_id=ledger.ledger_id,
            name=ledger.name,
            role=str(role),
            is_installation_default=ledger.ledger_id == claim.ledger_id,
        )
        for ledger, role in rows
    )
    if not ledgers:
        raise AppError(
            "installation_identity_recovery_required",
            "本机身份当前没有可访问的账本，请先完成身份修复。",
            status_code=409,
        )
    selected = next(
        (ledger.ledger_id for ledger in ledgers if ledger.is_installation_default),
        ledgers[0].ledger_id,
    )
    return LocalWebIdentityPreview(
        account_id=account.id,
        account_public_id=account.public_id,
        account_name=account.display_name,
        ledgers=ledgers,
        selected_ledger_id=selected,
    )


def _lock_installation_target(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    ledger_id: str,
) -> tuple[Account, Ledger, str]:
    account = db.scalar(
        select(Account)
        .where(Account.id == claim.account_id)
        .where(Account.disabled_at.is_(None))
        .with_for_update()
        .limit(1)
    )
    source_device = db.scalar(
        select(Device)
        .where(Device.id == claim.device_id)
        .where(Device.account_id == claim.account_id)
        .where(Device.revoked_at.is_(None))
        .with_for_update()
        .limit(1)
    )
    row = db.execute(
        select(Ledger, LedgerMember.role)
        .join(LedgerMember, LedgerMember.ledger_id == Ledger.ledger_id)
        .where(Ledger.ledger_id == ledger_id)
        .where(Ledger.archived_at.is_(None))
        .where(LedgerMember.account_id == claim.account_id)
        .where(LedgerMember.disabled_at.is_(None))
        .with_for_update()
        .limit(1)
    ).first()
    if account is None or source_device is None:
        raise AppError(
            "installation_identity_recovery_required",
            "当前安装的本机身份来源不可用，请先完成身份修复。",
            status_code=409,
        )
    if row is None:
        raise AppError(
            "local_identity_target_unavailable",
            "所选账本已不可用，请重新核对本机身份。",
            status_code=409,
        )
    return account, row[0], str(row[1])


def _recover_local_web_pairing(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    ledger: Ledger,
    attempt: DeviceEnrollmentAttempt,
    pairing_attempt_id: str,
    pairing_attempt_secret: str,
) -> PairingResult:
    pairing = db.scalar(
        select(PairingCode)
        .where(PairingCode.id == attempt.pairing_code_id)
        .with_for_update()
        .limit(1)
    )
    if (
        pairing is None
        or pairing.id == claim.pairing_code_id
        or pairing.created_by_device_id != claim.device_id
        or pairing.account_id != claim.account_id
        or pairing.ledger_id != ledger.ledger_id
        or attempt.account_id != claim.account_id
        or attempt.ledger_id != ledger.ledger_id
    ):
        raise AppError(
            "local_identity_target_changed",
            "这次确认已用于另一身份或账本，请刷新后重试。",
            status_code=409,
        )
    proof = prepare_enrollment_proof(pairing_attempt_id, pairing_attempt_secret)
    completion = _recover_pairing_completion(
        db,
        pairing=pairing,
        proof=proof,
        attempt=attempt,
        remote_id=None,
        issued_at=now_utc(),
    )
    db.commit()
    return _pairing_result(proof, completion)


def connect_installation_web_identity(
    db: Session,
    *,
    ledger_id: str,
    pairing_attempt_id: str,
    pairing_attempt_secret: str,
) -> PairingResult:
    """Create or recover one local browser Device/session in one transaction."""

    lock_bootstrap_owner_transaction(db)
    claim = _unique_installation_claim(db, for_update=True)
    account, ledger, _ = _lock_installation_target(
        db,
        claim=claim,
        ledger_id=ledger_id,
    )
    proof = prepare_enrollment_proof(pairing_attempt_id, pairing_attempt_secret)
    attempt = load_enrollment_attempt(db, public_id=proof.public_id)
    if attempt is not None:
        return _recover_local_web_pairing(
            db,
            claim=claim,
            ledger=ledger,
            attempt=attempt,
            pairing_attempt_id=pairing_attempt_id,
            pairing_attempt_secret=pairing_attempt_secret,
        )

    source = _create_pairing_code(
        db,
        ledger_id=ledger.ledger_id,
        account_id=account.id,
        created_by_device_id=claim.device_id,
        device_name_hint="本机浏览器",
    )
    # ``_create_pairing_code`` only flushes. ``pair_device`` consumes that
    # private source and commits Device + token + receipt together.
    return pair_device(
        db,
        pairing_code=source.pairing_code,
        pairing_attempt_id=pairing_attempt_id,
        pairing_attempt_secret=pairing_attempt_secret,
        device_name="本机浏览器",
        platform="web",
    )


__all__ = [
    "LocalWebIdentityPreview",
    "LocalWebLedger",
    "connect_installation_web_identity",
    "installation_web_identity_present",
    "preview_installation_web_identity",
    "resolve_installation_web_account_id",
]
