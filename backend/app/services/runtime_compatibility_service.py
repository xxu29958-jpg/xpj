"""Product-facing runtime compatibility projection.

This service translates internal currency authority state into stable client
conclusions.  It deliberately does not query or serialize migration names,
Alembic revisions, installer receipts, or historical C07 evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.currency_binding_contract import (
    CURRENCY_CONTRACT_VERSION,
)
from app.runtime_compatibility_contract import (
    CURRENT_API_VERSION,
    RUNTIME_COMPATIBILITY_CONTRACT,
    TICKETBOX_API_VERSION_HEADER,
    TICKETBOX_CURRENCY_BINDING_HEADER,
    UPLOAD_ORIGINAL_RECEIPT_VERSION,
    format_currency_binding,
)
from app.services.currency_binding_service import CurrencyCapability, get_capability
from app.services.time_service import now_utc, to_iso

CompatibilityConclusion = Literal[
    "compatible",
    "client_upgrade_required",
    "owner_action_required",
    "configuration_required",
    "server_upgrade_required",
]


@dataclass(frozen=True)
class RuntimeCurrencyCapability:
    home_currency_code: str | None
    minor_unit_exponent: int | None
    rounding_mode: str | None
    contract_version: int
    binding_revision: int
    request_binding: str | None
    request_binding_header: str
    initialization_offer: str | None
    read_compatibility: CompatibilityConclusion
    write_compatibility: CompatibilityConclusion


@dataclass(frozen=True)
class RuntimeCompatibilitySnapshot:
    contract: str
    observed_at: str
    api_version: str
    api_version_header: str
    read_compatibility: CompatibilityConclusion
    write_compatibility: CompatibilityConclusion
    legacy_write_compatibility: Literal["compatible", "client_upgrade_required"]
    upload_original_receipt_version: int
    currency: RuntimeCurrencyCapability


def _currency_read_compatibility(
    capability: CurrencyCapability,
) -> CompatibilityConclusion:
    if capability.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        return "server_upgrade_required"
    if capability.state in {"EMPTY", "ADOPTION_REQUIRED"}:
        return "owner_action_required"
    return "compatible"


def _currency_write_compatibility(
    capability: CurrencyCapability,
) -> CompatibilityConclusion:
    if capability.currency_contract_version != CURRENCY_CONTRACT_VERSION:
        return "server_upgrade_required"
    if capability.state in {"EMPTY", "ADOPTION_REQUIRED"}:
        return "owner_action_required"
    if capability.health != "active_match":
        return "server_upgrade_required"
    return "compatible"


def runtime_compatibility_snapshot(db: Session) -> RuntimeCompatibilitySnapshot:
    capability = get_capability(db)
    read_compatibility = _currency_read_compatibility(capability)
    write_compatibility = _currency_write_compatibility(capability)
    product_home_currency = capability.home_currency_code
    return RuntimeCompatibilitySnapshot(
        contract=RUNTIME_COMPATIBILITY_CONTRACT,
        observed_at=to_iso(now_utc()) or "",
        api_version=CURRENT_API_VERSION,
        api_version_header=TICKETBOX_API_VERSION_HEADER,
        read_compatibility=read_compatibility,
        write_compatibility=write_compatibility,
        legacy_write_compatibility="client_upgrade_required",
        upload_original_receipt_version=UPLOAD_ORIGINAL_RECEIPT_VERSION,
        currency=RuntimeCurrencyCapability(
            home_currency_code=product_home_currency,
            minor_unit_exponent=capability.minor_unit_exponent,
            rounding_mode=capability.rounding_mode,
            contract_version=capability.currency_contract_version,
            binding_revision=capability.binding_revision,
            request_binding=(
                format_currency_binding(
                    contract_version=capability.currency_contract_version,
                    binding_revision=capability.binding_revision,
                    home_currency_code=product_home_currency,
                )
                if product_home_currency is not None
                else None
            ),
            request_binding_header=TICKETBOX_CURRENCY_BINDING_HEADER,
            initialization_offer=capability.initialization_offer,
            read_compatibility=read_compatibility,
            write_compatibility=write_compatibility,
        ),
    )


__all__ = [
    "RuntimeCompatibilitySnapshot",
    "RuntimeCurrencyCapability",
    "runtime_compatibility_snapshot",
]
