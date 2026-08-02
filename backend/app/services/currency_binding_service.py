"""Persisted installation currency authority for the cross-ADR C02 slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.currency_adoption_evidence import currency_adoption_evidence
from app.currency_binding_contract import (
    CURRENCY_BINDING_ACTIVE,
    CURRENCY_BINDING_ADOPTION_REQUIRED,
    CURRENCY_BINDING_EMPTY,
    CURRENCY_CONTRACT_VERSION,
    CURRENCY_EVIDENCE_TABLES,
    CURRENCY_ROUNDING_MODE,
    CURRENCY_WRITER_GUC,
    INITIAL_BINDING_REVISION,
    MINIMUM_WRITABLE_CURRENCY_CONTRACT,
)
from app.database._currency_writer import (
    lock_currency_evidence_tables,
    set_currency_writer_proof,
)
from app.errors import AppError
from app.fx_constants import (
    CURRENCY_MINOR_UNIT_DIGITS,
    DEFAULT_HOME_CURRENCY_CODE,
)
from app.models import (
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
)
from app.services.currency_common import home_currency_code
from app.services.time_service import now_utc

CurrencyBindingState = Literal["EMPTY", "ADOPTION_REQUIRED", "ACTIVE"]
CurrencyBindingHealth = Literal[
    "empty",
    "adoption_required",
    "active_match",
    "configuration_drift",
    "migration_required",
]


@dataclass(frozen=True)
class CurrencyCapability:
    state: CurrencyBindingState
    home_currency_code: str | None
    minor_unit_exponent: int | None
    rounding_mode: str | None
    currency_contract_version: int
    binding_revision: int
    minimum_writable_currency_contract: int
    health: CurrencyBindingHealth
    initialization_offer: str | None


def _configured_home_or_none() -> str | None:
    try:
        return home_currency_code()
    except AppError:
        return None


def _initialization_offer(configured: str | None) -> str | None:
    """Expose only a first-fact transition the current writer can execute."""

    if configured == DEFAULT_HOME_CURRENCY_CODE:
        return configured
    return None


def _load_binding(db: Session, *, for_update: bool = False) -> InstallationCurrencyBinding | None:
    statement = select(InstallationCurrencyBinding).where(InstallationCurrencyBinding.singleton_id == 1)
    if for_update:
        # The singleton may already be present in this Session's identity map
        # from the optimistic EMPTY read above.  PostgreSQL's FOR UPDATE waits
        # for a concurrent claimant and returns the winner's committed row, but
        # SQLAlchemy otherwise keeps the already-loaded attributes.  Refresh
        # them while taking the lock before re-evaluating the state.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


def _state(value: str) -> CurrencyBindingState:
    if value not in {
        CURRENCY_BINDING_EMPTY,
        CURRENCY_BINDING_ADOPTION_REQUIRED,
        CURRENCY_BINDING_ACTIVE,
    }:
        raise AppError("currency_binding_corrupt", status_code=503)
    return value  # type: ignore[return-value]


def get_capability(db: Session) -> CurrencyCapability:
    binding = _load_binding(db)
    configured = _configured_home_or_none()
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)

    state = _state(binding.state)
    if state == CURRENCY_BINDING_EMPTY:
        health: CurrencyBindingHealth = "empty"
    elif state == CURRENCY_BINDING_ADOPTION_REQUIRED:
        health = "adoption_required"
    elif binding.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        health = "migration_required"
    elif configured is None or configured != binding.home_currency_code:
        health = "configuration_drift"
    else:
        health = "active_match"
    return CurrencyCapability(
        state=state,
        home_currency_code=binding.home_currency_code,
        minor_unit_exponent=binding.minor_unit_exponent,
        rounding_mode=binding.rounding_mode,
        currency_contract_version=binding.currency_contract_version,
        binding_revision=binding.binding_revision,
        minimum_writable_currency_contract=MINIMUM_WRITABLE_CURRENCY_CONTRACT,
        health=health,
        initialization_offer=(
            _initialization_offer(configured)
            if state == CURRENCY_BINDING_EMPTY
            else None
        ),
    )


def readable_or_initialization_home_currency_code(db: Session) -> str | None:
    """Resolve the currency an existing debt client may safely present.

    ACTIVE installations expose their persisted authority even when runtime
    configuration has drifted, so historical facts remain interpretable.  A
    genuinely EMPTY installation has no persisted authority yet; the current
    client may nevertheless offer the one first-fact transition the writer
    contract accepts (CNY, revision 0).  Adoption, migration, and unsupported
    initialization states remain fail-closed.
    """

    capability = get_capability(db)
    if capability.state == CURRENCY_BINDING_ACTIVE:
        return capability.home_currency_code
    if (
        capability.state == CURRENCY_BINDING_EMPTY
        and capability.health == "empty"
        and capability.initialization_offer == DEFAULT_HOME_CURRENCY_CODE
        and capability.currency_contract_version == MINIMUM_WRITABLE_CURRENCY_CONTRACT
        and capability.binding_revision == 0
    ):
        return capability.initialization_offer
    return None


def _snapshot(binding: InstallationCurrencyBinding) -> dict[str, object]:
    return {
        "state": binding.state,
        "home_currency_code": binding.home_currency_code,
        "minor_unit_exponent": binding.minor_unit_exponent,
        "rounding_mode": binding.rounding_mode,
        "currency_contract_version": binding.currency_contract_version,
        "binding_revision": binding.binding_revision,
        "provenance": binding.provenance,
        "evidence_sha256": binding.evidence_sha256,
    }


def _set_writer_proof(db: Session, binding: InstallationCurrencyBinding) -> None:
    set_currency_writer_proof(
        db,
        guc_name=CURRENCY_WRITER_GUC,
        contract_version=binding.currency_contract_version,
        binding_revision=binding.binding_revision,
    )


def _claim_initial_cny_binding(
    db: Session,
    binding: InstallationCurrencyBinding,
) -> None:
    lock_currency_evidence_tables(db, CURRENCY_EVIDENCE_TABLES)
    evidence = currency_adoption_evidence(db.connection())
    if (
        evidence.has_conflict
        or DEFAULT_HOME_CURRENCY_CODE not in evidence.allowed_home_currency_codes
    ):
        raise AppError("currency_binding_corrupt", status_code=503)
    before = _snapshot(binding)
    activated_at = now_utc()
    binding.state = CURRENCY_BINDING_ACTIVE
    binding.home_currency_code = DEFAULT_HOME_CURRENCY_CODE
    binding.minor_unit_exponent = CURRENCY_MINOR_UNIT_DIGITS[DEFAULT_HOME_CURRENCY_CODE]
    binding.rounding_mode = CURRENCY_ROUNDING_MODE
    binding.binding_revision = INITIAL_BINDING_REVISION
    binding.provenance = "FIRST_FACT_CLAIM"
    binding.evidence_sha256 = evidence.sha256
    binding.updated_at = activated_at
    binding.activated_at = activated_at
    db.flush()
    db.add(
        InstallationCurrencyAuditLog(
            action="FIRST_FACT_CLAIM",
            actor_account_public_id=None,
            actor_device_public_id=None,
            before_snapshot=before,
            after_snapshot=_snapshot(binding),
            reason="first financial fact claimed the configured CNY binding",
            created_at=activated_at,
        )
    )
    db.flush()


def resolve_write_capability(
    db: Session,
    *,
    expected_revision: int | None = None,
) -> CurrencyCapability:
    configured = home_currency_code()
    binding = _load_binding(db)
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    state = _state(binding.state)
    if state == CURRENCY_BINDING_EMPTY:
        # ACTIVE bindings are immutable at the database layer, so ordinary writes
        # do not need to serialize on the installation singleton. Only the EMPTY
        # -> ACTIVE first-fact transition takes the row lock; the trigger still
        # rechecks the current contract/revision at the protected-table statement.
        binding = _load_binding(db, for_update=True)
        if binding is None:
            raise AppError("currency_binding_corrupt", status_code=503)
        state = _state(binding.state)
    if state == CURRENCY_BINDING_EMPTY:
        if configured != DEFAULT_HOME_CURRENCY_CODE or expected_revision not in {None, 0}:
            raise AppError("client_upgrade_required", status_code=409)
        _claim_initial_cny_binding(db, binding)
    elif state == CURRENCY_BINDING_ADOPTION_REQUIRED:
        raise AppError("currency_adoption_required", status_code=409)
    if binding.state != CURRENCY_BINDING_ACTIVE:
        raise AppError("currency_binding_corrupt", status_code=503)
    if binding.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        raise AppError("client_upgrade_required", status_code=409)
    if binding.home_currency_code != configured:
        raise AppError("currency_binding_configuration_drift", status_code=409)
    if expected_revision is not None and expected_revision != binding.binding_revision:
        raise AppError("currency_binding_revision_conflict", status_code=409)
    if expected_revision is None and (
        binding.home_currency_code != DEFAULT_HOME_CURRENCY_CODE or binding.binding_revision != INITIAL_BINDING_REVISION
    ):
        raise AppError("client_upgrade_required", status_code=409)
    _set_writer_proof(db, binding)
    return get_capability(db)


def authorize_currency_metadata_write(
    db: Session,
    *,
    allow_empty_category_rule: bool = False,
) -> None:
    binding = _load_binding(db)
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    state = _state(binding.state)
    if state == CURRENCY_BINDING_EMPTY and allow_empty_category_rule:
        # Keep a pure category-rule write and a concurrent first-fact claim from
        # crossing states between authorization and the row trigger.
        binding = _load_binding(db, for_update=True)
        if binding is None:
            raise AppError("currency_binding_corrupt", status_code=503)
        state = _state(binding.state)
        if state == CURRENCY_BINDING_EMPTY:
            return
    if state == CURRENCY_BINDING_ADOPTION_REQUIRED:
        raise AppError("currency_adoption_required", status_code=409)
    if state != CURRENCY_BINDING_ACTIVE:
        raise AppError("currency_binding_corrupt", status_code=503)
    if binding.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        raise AppError("client_upgrade_required", status_code=409)
    _set_writer_proof(db, binding)


def assert_currency_binding_consistent(db: Session, home: str) -> None:
    configured = home_currency_code()
    if home != configured:
        raise AppError("currency_binding_configuration_drift", status_code=409)
    resolve_write_capability(db)
