"""Persisted installation currency authority for the cross-ADR C02 slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.currency_binding_contract import (
    CURRENCY_BINDING_ACTIVE,
    CURRENCY_BINDING_ADOPTION_REQUIRED,
    CURRENCY_BINDING_EMPTY,
    CURRENCY_CONTRACT_VERSION,
    CURRENCY_WRITER_GUC,
    INITIAL_BINDING_REVISION,
    MINIMUM_WRITABLE_CURRENCY_CONTRACT,
)
from app.database._currency_writer import (
    set_currency_writer_proof,
)
from app.errors import AppError
from app.fx_constants import (
    DEFAULT_HOME_CURRENCY_CODE,
)
from app.models import (
    InstallationCurrencyBinding,
)
from app.runtime_compatibility_contract import (
    CURRENT_API_VERSION,
    RUNTIME_COMPATIBILITY_SESSION_KEY,
    RuntimeCompatibilityRequest,
    parse_currency_binding,
)

CurrencyBindingState = Literal["EMPTY", "ADOPTION_REQUIRED", "ACTIVE"]
CurrencyBindingHealth = Literal[
    "empty",
    "adoption_required",
    "active_match",
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
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)

    state = _state(binding.state)
    if state == CURRENCY_BINDING_EMPTY:
        health: CurrencyBindingHealth = "empty"
    elif state == CURRENCY_BINDING_ADOPTION_REQUIRED:
        health = "adoption_required"
    elif binding.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        health = "migration_required"
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
        initialization_offer=None,
    )


def _runtime_home_currency_from_capability(
    capability: CurrencyCapability,
) -> str | None:
    if capability.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        return None
    if capability.state == CURRENCY_BINDING_ACTIVE:
        return capability.home_currency_code
    return None


def runtime_home_currency_code(db: Session) -> str | None:
    """Return the product currency a current server consumer may render.

    Only a confirmed persisted binding supplies money meaning. An unchosen
    installation and an unknown currency-contract version have no money basis.
    """

    return _runtime_home_currency_from_capability(get_capability(db))


def require_runtime_home_currency_code(db: Session) -> str:
    """Resolve the product currency or fail before an amount can be mislabeled."""

    capability = get_capability(db)
    code = _runtime_home_currency_from_capability(capability)
    if code is not None:
        return code
    if capability.state in {CURRENCY_BINDING_EMPTY, CURRENCY_BINDING_ADOPTION_REQUIRED}:
        raise AppError("currency_adoption_required", status_code=409)
    if capability.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        raise AppError("client_upgrade_required", status_code=409)
    raise AppError("currency_binding_corrupt", status_code=503)


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


@dataclass(frozen=True)
class _CurrencyWriteExpectation:
    mode: Literal["internal", "legacy_http", "negotiated"]
    contract_version: int | None = None
    binding_revision: int | None = None
    home_currency_code: str | None = None


def _http_runtime_request(db: Session) -> RuntimeCompatibilityRequest | None:
    value = db.info.get(RUNTIME_COMPATIBILITY_SESSION_KEY)
    if value is None:
        return None
    if not isinstance(value, RuntimeCompatibilityRequest):
        raise AppError("client_upgrade_required", status_code=409)
    return value


def _required_http_currency_binding(db: Session, request: RuntimeCompatibilityRequest) -> str:
    if request.api_version != CURRENT_API_VERSION:
        raise AppError("client_upgrade_required", status_code=409)
    if request.currency_binding is not None:
        return request.currency_binding
    binding = _load_binding(db)
    if binding is not None and binding.state in {CURRENCY_BINDING_EMPTY, CURRENCY_BINDING_ADOPTION_REQUIRED}:
        raise AppError("currency_adoption_required", status_code=409)
    raise AppError("client_upgrade_required", status_code=409)


def _currency_write_expectation(
    db: Session,
    *,
    expected_contract_version: int | None,
    expected_revision: int | None,
) -> _CurrencyWriteExpectation:
    request = _http_runtime_request(db)
    if request is not None and request.origin == "server_runtime":
        return _CurrencyWriteExpectation(mode="internal")
    if expected_contract_version is not None or expected_revision is not None:
        contract_version = expected_contract_version or CURRENCY_CONTRACT_VERSION
        if expected_revision is None:
            raise AppError("client_upgrade_required", status_code=409)
        if request is not None:
            if request.is_legacy:
                raise AppError("client_upgrade_required", status_code=409)
            try:
                header_contract, header_revision, header_currency = parse_currency_binding(
                    request.currency_binding or ""
                )
            except ValueError:
                raise AppError("client_upgrade_required", status_code=409) from None
            if (
                request.api_version != CURRENT_API_VERSION
                or header_contract != contract_version
                or header_revision != expected_revision
            ):
                raise AppError("client_upgrade_required", status_code=409)
        return _CurrencyWriteExpectation(
            mode="negotiated",
            contract_version=contract_version,
            binding_revision=expected_revision,
            home_currency_code=header_currency if request is not None else None,
        )
    if request is None:
        return _CurrencyWriteExpectation(mode="internal")
    if request.is_legacy:
        return _CurrencyWriteExpectation(mode="legacy_http")
    request_binding = _required_http_currency_binding(db, request)
    try:
        contract_version, binding_revision, binding_currency = parse_currency_binding(
            request_binding
        )
    except ValueError:
        raise AppError("client_upgrade_required", status_code=409) from None
    return _CurrencyWriteExpectation(
        mode="negotiated",
        contract_version=contract_version,
        binding_revision=binding_revision,
        home_currency_code=binding_currency,
    )


def _assert_write_expectation(
    binding: InstallationCurrencyBinding,
    expectation: _CurrencyWriteExpectation,
) -> None:
    if expectation.mode == "negotiated":
        if expectation.contract_version != binding.currency_contract_version:
            raise AppError("client_upgrade_required", status_code=409)
        if (
            expectation.home_currency_code is not None
            and expectation.home_currency_code != binding.home_currency_code
        ):
            raise AppError("currency_binding_revision_conflict", status_code=409)
        if expectation.binding_revision != binding.binding_revision:
            raise AppError("currency_binding_revision_conflict", status_code=409)
    elif expectation.mode == "legacy_http" and (
        binding.home_currency_code != DEFAULT_HOME_CURRENCY_CODE
        or binding.binding_revision != INITIAL_BINDING_REVISION
    ):
        raise AppError("client_upgrade_required", status_code=409)


def resolve_write_capability(
    db: Session,
    *,
    expected_contract_version: int | None = None,
    expected_revision: int | None = None,
) -> CurrencyCapability:
    expectation = _currency_write_expectation(
        db,
        expected_contract_version=expected_contract_version,
        expected_revision=expected_revision,
    )
    binding = _load_binding(db)
    if binding is None:
        raise AppError("currency_binding_corrupt", status_code=503)
    state = _state(binding.state)
    if state in {CURRENCY_BINDING_EMPTY, CURRENCY_BINDING_ADOPTION_REQUIRED}:
        raise AppError("currency_adoption_required", status_code=409)
    if binding.state != CURRENCY_BINDING_ACTIVE:
        raise AppError("currency_binding_corrupt", status_code=503)
    if binding.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        raise AppError("client_upgrade_required", status_code=409)
    _assert_write_expectation(binding, expectation)
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
        # Keep a pure category-rule write and a concurrent owner choice from
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
    capability = resolve_write_capability(db)
    if home != capability.home_currency_code:
        raise AppError("currency_binding_revision_conflict", status_code=409)
