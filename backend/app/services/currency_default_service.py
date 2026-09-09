"""Installation Owner changes the default; recorded money keeps its own currency."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.currency_binding_contract import CURRENCY_CONTRACT_VERSION
from app.errors import AppError
from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS, DEFAULT_SUPPORTED_CURRENCY_CODES
from app.models import InstallationCurrencyAuditLog, InstallationOwnerClaim
from app.services.currency_adoption_service import (
    _canonical_uuid4,
    _claim_idempotency_key,
    _normalize_code,
    revalidate_currency_adoption_owner,
)
from app.services.currency_binding_service import CurrencyBindingState, _load_binding, _snapshot, _state
from app.services.time_service import now_utc
from app.tenants import AuthContext

_OPERATION = "currency_default_change"


def is_installation_currency_owner(db: Session, account_id: int) -> bool:
    """Read-only entry visibility; the command still revalidates the live credential and claim."""
    return list(db.scalars(select(InstallationOwnerClaim.account_id).limit(2))) == [account_id]


@dataclass(frozen=True)
class CurrencyDefaultPreview:
    state: CurrencyBindingState
    binding_revision: int
    currency_contract_version: int
    home_currency_code: str | None
    allowed_home_currency_codes: tuple[str, ...]


@dataclass(frozen=True)
class CurrencyDefaultChangeReceipt:
    operation: str
    event_id: str
    state: Literal["ACTIVE"]
    home_currency_code: str
    minor_unit_exponent: int
    rounding_mode: str
    currency_contract_version: int
    binding_revision: int
    changed_at: str
    source_home_currency_code: str


def currency_change_preview(db: Session, *, auth: AuthContext) -> CurrencyDefaultPreview:
    revalidate_currency_adoption_owner(db, auth)
    binding = _load_binding(db)
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    return CurrencyDefaultPreview(_state(binding.state), binding.binding_revision,
        binding.currency_contract_version, binding.home_currency_code, tuple(DEFAULT_SUPPORTED_CURRENCY_CODES))


def change_currency_binding_for_installation_owner(
    db: Session, *, auth: AuthContext, idempotency_key: UUID, expected_contract_version: int,
    home_code: str, expected_revision: int, reason: str,
) -> CurrencyDefaultChangeReceipt:
    code = _normalize_code(home_code)
    cleaned_reason = reason.strip()
    if not 1 <= len(cleaned_reason) <= 500:
        raise AppError("invalid_request", status_code=422)
    fingerprint = hashlib.sha256(json.dumps({
        "operation": _OPERATION, "currency_contract_version": expected_contract_version,
        "expected_binding_revision": expected_revision, "home_currency_code": code, "reason": cleaned_reason,
    }, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    try:
        locked_auth = revalidate_currency_adoption_owner(db, auth)
        claimed = _claim_idempotency_key(db, key=_canonical_uuid4(idempotency_key), fingerprint=fingerprint,
            operation=_OPERATION, receipt_type=CurrencyDefaultChangeReceipt)
        if isinstance(claimed, CurrencyDefaultChangeReceipt):
            db.rollback()
            return claimed
        binding = _load_binding(db, for_update=True)
        if binding is None:
            raise AppError("currency_binding_corrupt", status_code=503)
        if binding.currency_contract_version != expected_contract_version or expected_contract_version != CURRENCY_CONTRACT_VERSION:
            raise AppError("client_upgrade_required", status_code=409)
        if binding.state != "ACTIVE" or binding.binding_revision != expected_revision:
            raise AppError("currency_binding_state_conflict", status_code=409)
        if binding.home_currency_code == code:
            raise AppError("invalid_request", "已在使用这个默认币种。", status_code=422)
        changed_at = now_utc()
        event = InstallationCurrencyAuditLog(action="OWNER_DEFAULT_CHANGE",
            actor_account_public_id=locked_auth.account_public_id, actor_device_public_id=locked_auth.device_public_id,
            before_snapshot=_snapshot(binding), after_snapshot={}, reason=cleaned_reason, created_at=changed_at)
        binding.home_currency_code = code
        binding.minor_unit_exponent = CURRENCY_MINOR_UNIT_DIGITS[code]
        binding.binding_revision += 1
        binding.provenance = "OWNER_DEFAULT_CHANGE"
        binding.updated_at = changed_at
        event.after_snapshot = _snapshot(binding)
        db.add(event)
        db.flush()
        receipt = CurrencyDefaultChangeReceipt(_OPERATION, event.event_id, "ACTIVE", code,
            binding.minor_unit_exponent, binding.rounding_mode, binding.currency_contract_version,
            binding.binding_revision, changed_at.isoformat(), event.before_snapshot["home_currency_code"])
        claimed.status, claimed.receipt, claimed.completed_at = "succeeded", asdict(receipt), changed_at
        db.commit()
        return receipt
    except (AppError, DBAPIError) as error:
        db.rollback()
        if isinstance(error, DBAPIError) and getattr(error.orig, "sqlstate", None) == "55P03":
            raise AppError("currency_binding_state_conflict", status_code=409) from None
        raise
