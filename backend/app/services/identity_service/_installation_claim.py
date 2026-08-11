"""Shared state rules for the Windows installation-owner claim."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    Device,
    InstallationOwnerClaim,
    Ledger,
    LedgerMember,
    PairingCode,
)
from app.services.identity_service._models import (
    DEFAULT_ACCOUNT_NAME,
    DEFAULT_BOOTSTRAP_DEVICE_NAME,
    PAIRING_CODE_TTL_MINUTES,
    InstallationOwnerBootstrapResult,
)
from app.services.identity_service._seed import _clean_name
from app.services.session_lifecycle_service import (
    PAIRING_CODE_DIGITS,
    derive_bootstrap_digest,
    hash_pairing_code,
    hash_secret,
)
from app.services.time_service import ensure_utc, now_utc, to_iso
from app.tenants import DEFAULT_TENANT_NAME

INSTALLATION_OWNER_CONTRACT = "ticketbox-installation-owner-pairing-v1"
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PAIRING_DERIVATION_LIMIT = 64
_PAIRING_CODE_CONTEXT = b"ticketbox/installation-owner/v1/pairing-code"


def identifier(value: str, *, field: str) -> str:
    canonical = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(canonical):
        raise AppError(
            "invalid_request",
            f"{field} 必须是 1 到 128 位安全标识符。",
            status_code=422,
        )
    return canonical


def canonical_request(
    *,
    account_name: str | None,
    ledger_name: str | None,
    device_name: str | None,
) -> tuple[str, str, str, str]:
    account = _clean_name(account_name, DEFAULT_ACCOUNT_NAME)
    ledger = _clean_name(ledger_name, DEFAULT_TENANT_NAME)
    device = _clean_name(device_name, DEFAULT_BOOTSTRAP_DEVICE_NAME)
    payload = json.dumps(
        {
            "account_name": account,
            "contract": INSTALLATION_OWNER_CONTRACT,
            "device_name": device,
            "ledger_name": ledger,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return account, ledger, device, hashlib.sha256(payload).hexdigest()


def derive_pairing_code(secret: str, derivation_index: int = 0) -> str:
    """Derive one bounded child without changing the installation operation."""

    if not 0 <= derivation_index < _PAIRING_DERIVATION_LIMIT:
        raise ValueError("installation pairing derivation index is out of range")
    digest = derive_bootstrap_digest(
        secret,
        context=_PAIRING_CODE_CONTEXT + bytes([derivation_index]),
    )
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return f"{value % (10**PAIRING_CODE_DIGITS):0{PAIRING_CODE_DIGITS}d}"


def pairing_candidate(db: Session, *, secret: str) -> tuple[str, int]:
    candidates = tuple(
        (
            code := derive_pairing_code(secret, index),
            index,
            hash_pairing_code(code),
        )
        for index in range(_PAIRING_DERIVATION_LIMIT)
    )
    occupied_hashes = set(
        db.scalars(
            select(PairingCode.code_hash).where(
                PairingCode.code_hash.in_(candidate[2] for candidate in candidates)
            )
        )
    )
    for code, index, code_hash in candidates:
        if code_hash not in occupied_hashes:
            return code, index
    raise AppError(
        "installation_pairing_collision",
        "无法分配首次桌面绑定码；安装事务保持可重试。",
        status_code=503,
    )


def validated_bindings(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    secret: str,
    operation_id: str,
    installation_id: str,
    request_fingerprint: str,
) -> tuple[Account, Device, Ledger, PairingCode, str]:
    secret_hash = hash_secret(secret)
    if not (
        hmac.compare_digest(claim.operation_id, operation_id)
        and hmac.compare_digest(claim.installation_id, installation_id)
        and hmac.compare_digest(claim.request_fingerprint, request_fingerprint)
        and hmac.compare_digest(claim.active_secret_hash, secret_hash)
    ):
        raise AppError("invalid_bootstrap_secret", status_code=401)

    account = db.get(Account, claim.account_id)
    device = db.get(Device, claim.device_id)
    ledger = db.scalar(
        select(Ledger).where(Ledger.ledger_id == claim.ledger_id).limit(1)
    )
    membership = db.scalar(
        select(LedgerMember)
        .where(LedgerMember.ledger_id == claim.ledger_id)
        .where(LedgerMember.account_id == claim.account_id)
        .limit(1)
    )
    pairing = db.get(PairingCode, claim.pairing_code_id, with_for_update=True)
    code = derive_pairing_code(secret, claim.pairing_derivation_index)
    if (
        account is None
        or device is None
        or ledger is None
        or membership is None
        or pairing is None
        or account.disabled_at is not None
        or device.revoked_at is not None
        or device.account_id != account.id
        or ledger.archived_at is not None
        or ledger.owner_account_id != account.id
        or membership.disabled_at is not None
        or membership.role != "owner"
        or pairing.account_id != account.id
        or pairing.ledger_id != ledger.ledger_id
        or pairing.created_by_device_id != device.id
        or pairing.revoked_at is not None
        or pairing.used_at is not None
        or not hmac.compare_digest(pairing.code_hash, hash_pairing_code(code))
    ):
        raise AppError("invalid_bootstrap_secret", status_code=401)
    return account, device, ledger, pairing, code


def result_from_bindings(
    *,
    claim: InstallationOwnerClaim,
    account: Account,
    device: Device,
    ledger: Ledger,
    pairing: PairingCode,
    code: str,
) -> InstallationOwnerBootstrapResult:
    return InstallationOwnerBootstrapResult(
        contract=INSTALLATION_OWNER_CONTRACT,
        operation_id=claim.operation_id,
        installation_id=claim.installation_id,
        account_name=account.display_name,
        ledger_id=ledger.ledger_id,
        ledger_name=ledger.name,
        device_name=device.device_name,
        pairing_code=code,
        pairing_expires_at=to_iso(pairing.expires_at) or "",
        pairing_derivation_index=claim.pairing_derivation_index,
        claim_generation=claim.generation,
    )


def claim_result(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    secret: str,
    operation_id: str,
    installation_id: str,
    request_fingerprint: str,
) -> InstallationOwnerBootstrapResult:
    account, device, ledger, pairing, code = validated_bindings(
        db,
        claim=claim,
        secret=secret,
        operation_id=operation_id,
        installation_id=installation_id,
        request_fingerprint=request_fingerprint,
    )
    expiration = ensure_utc(pairing.expires_at)
    if expiration is None or expiration <= now_utc():
        raise AppError("invalid_bootstrap_secret", status_code=401)
    return result_from_bindings(
        claim=claim,
        account=account,
        device=device,
        ledger=ledger,
        pairing=pairing,
        code=code,
    )


def replace_expired_pairing(
    db: Session,
    *,
    claim: InstallationOwnerClaim,
    secret: str,
    account: Account,
    device: Device,
    ledger: Ledger,
    expired_pairing: PairingCode,
    replaced_at,
) -> InstallationOwnerBootstrapResult:
    if expired_pairing.revoked_at is not None or expired_pairing.used_at is not None:
        raise AppError("invalid_bootstrap_secret", status_code=401)
    expired_pairing.revoked_at = replaced_at
    old_expiration = ensure_utc(expired_pairing.expires_at)
    if old_expiration is None or old_expiration > replaced_at:
        expired_pairing.expires_at = replaced_at

    code, derivation_index = pairing_candidate(db, secret=secret)
    replacement = PairingCode(
        code_hash=hash_pairing_code(code),
        ledger_id=claim.ledger_id,
        account_id=claim.account_id,
        created_by_device_id=claim.device_id,
        device_name_hint=expired_pairing.device_name_hint,
        expires_at=replaced_at + timedelta(minutes=PAIRING_CODE_TTL_MINUTES),
        created_at=replaced_at,
    )
    db.add(replacement)
    db.flush()
    claim.pairing_code_id = replacement.id
    claim.pairing_derivation_index = derivation_index
    claim.generation += 1
    claim.updated_at = replaced_at
    db.flush()
    return result_from_bindings(
        claim=claim,
        account=account,
        device=device,
        ledger=ledger,
        pairing=replacement,
        code=code,
    )
