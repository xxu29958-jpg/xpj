"""Owner-only adoption ceremony for an existing installation's currency."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import RFC_4122, UUID

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.currency_adoption_evidence import currency_adoption_evidence
from app.currency_binding_contract import (
    CURRENCY_BINDING_ACTIVE,
    CURRENCY_BINDING_ADOPTION_REQUIRED,
    CURRENCY_EVIDENCE_TABLES,
    CURRENCY_ROUNDING_MODE,
    INITIAL_BINDING_REVISION,
    INSTALLATION_ADOPTION_OPERATION,
    INSTALLATION_IDEMPOTENCY_TTL_HOURS,
)
from app.database._currency_writer import lock_currency_evidence_tables
from app.errors import AppError
from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS, DEFAULT_SUPPORTED_CURRENCY_CODES
from app.models import (
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
    InstallationIdempotencyKey,
)
from app.services import permission_service
from app.services.currency_binding_service import (
    CurrencyBindingState,
    _configured_home_or_none,
    _load_binding,
    _snapshot,
    _state,
)
from app.services.session_credential_lock import lock_and_revalidate_credential_mint_context
from app.services.time_service import now_utc
from app.tenants import AuthContext


@dataclass(frozen=True)
class CurrencyAdoptionPreview:
    state: CurrencyBindingState
    binding_revision: int
    currency_contract_version: int
    evidence_sha256: str
    configured_home_currency_code: str | None
    allowed_home_currency_codes: tuple[str, ...]
    evidence_health: Literal["adoptable", "conflict"]


@dataclass(frozen=True)
class CurrencyAdoptionReceipt:
    operation: str
    event_id: str
    state: Literal["ACTIVE"]
    home_currency_code: str
    minor_unit_exponent: int
    rounding_mode: str
    currency_contract_version: int
    binding_revision: int
    evidence_sha256: str
    activated_at: str


def adoption_preview(db: Session) -> CurrencyAdoptionPreview:
    binding = _load_binding(db)
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    evidence = currency_adoption_evidence(db.connection())
    return CurrencyAdoptionPreview(
        state=_state(binding.state),
        binding_revision=binding.binding_revision,
        currency_contract_version=binding.currency_contract_version,
        evidence_sha256=evidence.sha256,
        configured_home_currency_code=_configured_home_or_none(),
        allowed_home_currency_codes=evidence.allowed_home_currency_codes,
        evidence_health=("conflict" if evidence.has_conflict else "adoptable"),
    )


def _fingerprint_request(
    *,
    expected_contract_version: int,
    home_code: str,
    expected_state: str,
    expected_revision: int,
    expected_evidence_sha256: str,
    reason: str,
) -> str:
    payload = {
        "currency_contract_version": expected_contract_version,
        "expected_binding_revision": expected_revision,
        "expected_evidence_sha256": expected_evidence_sha256,
        "expected_state": expected_state,
        "home_currency_code": home_code,
        "operation": INSTALLATION_ADOPTION_OPERATION,
        "reason": reason,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_uuid4(value: UUID) -> str:
    if value.version != 4 or value.variant != RFC_4122:
        raise AppError("invalid_request", status_code=422)
    return str(value)


def _claim_idempotency_key(
    db: Session,
    *,
    key: str,
    fingerprint: str,
) -> InstallationIdempotencyKey | CurrencyAdoptionReceipt:
    existing = db.get(InstallationIdempotencyKey, key)
    if existing is None:
        now = now_utc()
        candidate = InstallationIdempotencyKey(
            idempotency_key=key,
            operation=INSTALLATION_ADOPTION_OPERATION,
            request_fingerprint=fingerprint,
            status="in_progress",
            receipt=None,
            created_at=now,
            completed_at=None,
            expires_at=now + timedelta(hours=INSTALLATION_IDEMPOTENCY_TTL_HOURS),
        )
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
        except IntegrityError as exc:
            existing = db.get(InstallationIdempotencyKey, key, populate_existing=True)
            if existing is None:
                raise AppError("currency_binding_corrupt", status_code=503) from exc
        else:
            return candidate
    if existing is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    if existing.operation != INSTALLATION_ADOPTION_OPERATION or existing.request_fingerprint != fingerprint:
        raise AppError("idempotency_key_reused", status_code=422)
    if existing.status == "in_progress":
        raise AppError("idempotency_key_in_progress", status_code=409)
    if existing.status != "succeeded" or not isinstance(existing.receipt, dict):
        raise AppError("currency_binding_corrupt", status_code=503)
    try:
        return CurrencyAdoptionReceipt(**existing.receipt)
    except TypeError as exc:
        raise AppError("currency_binding_corrupt", status_code=503) from exc


def _normalize_code(value: str) -> str:
    code = value.strip().upper()
    if code not in DEFAULT_SUPPORTED_CURRENCY_CODES:
        raise AppError("currency_not_supported", status_code=422)
    return code


def _adopt_in_transaction(
    db: Session,
    *,
    auth: AuthContext,
    idempotency_key: UUID,
    expected_contract_version: int,
    code: str,
    expected_state: str,
    expected_revision: int,
    expected_evidence_sha256: str,
    cleaned_reason: str,
    fingerprint: str,
) -> CurrencyAdoptionReceipt:
    locked_auth = lock_and_revalidate_credential_mint_context(db, auth)
    if locked_auth is None:
        raise AppError("invalid_token", status_code=401)
    permission_service.require_admin_maintenance(locked_auth)
    claimed = _claim_idempotency_key(db, key=_canonical_uuid4(idempotency_key), fingerprint=fingerprint)
    if isinstance(claimed, CurrencyAdoptionReceipt):
        db.rollback()
        return claimed

    binding = _load_binding(db, for_update=True)
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    if binding.currency_contract_version != expected_contract_version:
        raise AppError("client_upgrade_required", status_code=409)
    if binding.state == CURRENCY_BINDING_ACTIVE:
        raise AppError("currency_binding_already_active", status_code=409)
    if binding.state != expected_state or binding.binding_revision != expected_revision:
        raise AppError("currency_binding_state_conflict", status_code=409)
    if binding.state != CURRENCY_BINDING_ADOPTION_REQUIRED:
        raise AppError("currency_binding_state_conflict", status_code=409)

    lock_currency_evidence_tables(db, CURRENCY_EVIDENCE_TABLES)
    evidence = currency_adoption_evidence(db.connection())
    if evidence.sha256 != expected_evidence_sha256:
        raise AppError("currency_binding_evidence_changed", status_code=409)
    if evidence.has_conflict or code not in evidence.allowed_home_currency_codes:
        raise AppError("currency_adoption_currency_conflict", status_code=409)

    before = _snapshot(binding)
    activated_at = now_utc()
    event = InstallationCurrencyAuditLog(
        action="OWNER_ADOPTION",
        actor_account_public_id=locked_auth.account_public_id,
        actor_device_public_id=locked_auth.device_public_id,
        before_snapshot=before,
        after_snapshot={},
        reason=cleaned_reason,
        created_at=activated_at,
    )
    _activate_binding(binding, code=code, evidence_sha256=evidence.sha256, activated_at=activated_at)
    event.after_snapshot = _snapshot(binding)
    db.add(event)
    db.flush()

    receipt = _receipt(binding, event, evidence_sha256=evidence.sha256, activated_at=activated_at)
    claimed.status = "succeeded"
    claimed.receipt = asdict(receipt)
    claimed.completed_at = activated_at
    db.commit()
    return receipt


def _activate_binding(
    binding: InstallationCurrencyBinding,
    *,
    code: str,
    evidence_sha256: str,
    activated_at: datetime,
) -> None:
    binding.state = CURRENCY_BINDING_ACTIVE
    binding.home_currency_code = code
    binding.minor_unit_exponent = CURRENCY_MINOR_UNIT_DIGITS[code]
    binding.rounding_mode = CURRENCY_ROUNDING_MODE
    binding.binding_revision = INITIAL_BINDING_REVISION
    binding.provenance = "OWNER_ADOPTION"
    binding.evidence_sha256 = evidence_sha256
    binding.updated_at = activated_at
    binding.activated_at = activated_at


def _receipt(
    binding: InstallationCurrencyBinding,
    event: InstallationCurrencyAuditLog,
    *,
    evidence_sha256: str,
    activated_at: datetime,
) -> CurrencyAdoptionReceipt:
    return CurrencyAdoptionReceipt(
        operation=INSTALLATION_ADOPTION_OPERATION,
        event_id=event.event_id,
        state=CURRENCY_BINDING_ACTIVE,
        home_currency_code=str(binding.home_currency_code),
        minor_unit_exponent=int(binding.minor_unit_exponent),
        rounding_mode=str(binding.rounding_mode),
        currency_contract_version=binding.currency_contract_version,
        binding_revision=binding.binding_revision,
        evidence_sha256=evidence_sha256,
        activated_at=activated_at.isoformat(),
    )


def adopt_currency_binding(
    db: Session,
    *,
    auth: AuthContext,
    idempotency_key: UUID,
    expected_contract_version: int,
    home_code: str,
    expected_state: str,
    expected_revision: int,
    expected_evidence_sha256: str,
    reason: str,
) -> CurrencyAdoptionReceipt:
    code = _normalize_code(home_code)
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise AppError("invalid_request", status_code=422)
    fingerprint = _fingerprint_request(
        expected_contract_version=expected_contract_version,
        home_code=code,
        expected_state=expected_state,
        expected_revision=expected_revision,
        expected_evidence_sha256=expected_evidence_sha256,
        reason=cleaned_reason,
    )
    try:
        return _adopt_in_transaction(
            db,
            auth=auth,
            idempotency_key=idempotency_key,
            expected_contract_version=expected_contract_version,
            code=code,
            expected_state=expected_state,
            expected_revision=expected_revision,
            expected_evidence_sha256=expected_evidence_sha256,
            cleaned_reason=cleaned_reason,
            fingerprint=fingerprint,
        )
    except AppError:
        db.rollback()
        raise
    except DBAPIError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise AppError("currency_binding_state_conflict", status_code=409) from None
        raise
