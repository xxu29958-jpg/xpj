"""Product-facing runtime compatibility projection.

This service translates internal currency authority state into stable client
conclusions.  It deliberately does not query or serialize migration names,
Alembic revisions, installer receipts, or historical C07 evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app import runtime_compatibility_contract as protocol
from app.currency_binding_contract import (
    CURRENCY_CONTRACT_VERSION,
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
    min_read_client_version: str
    min_write_client_version: str
    read_compatibility: CompatibilityConclusion
    write_compatibility: CompatibilityConclusion
    legacy_write_compatibility: Literal["compatible", "client_upgrade_required"]
    upload_original_receipt_version: int
    accounting_time_input_version: int
    repayment_time_input_version: int
    original_attachment_version: int
    original_attachment_create_version: int
    debt_activity_read_version: int
    debt_bill_source_version: int
    expense_confirmation_version: int
    notification_batch_version: int
    currency: RuntimeCurrencyCapability

    @property
    def supported_payload_revisions(self) -> dict[str, list[int]]:
        """Wire payload families use independent revisions; Room journal formats are local."""
        return {
            "accounting_time_input": [self.accounting_time_input_version],
            "repayment_time_input": [self.repayment_time_input_version],
            "original_attachment_create": [self.original_attachment_create_version],
            "debt_bill_source": [self.debt_bill_source_version],
            "expense_confirmation": [self.expense_confirmation_version],
            "notification_batch": [self.notification_batch_version],
        }


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
        contract=protocol.RUNTIME_COMPATIBILITY_CONTRACT,
        observed_at=to_iso(now_utc()) or "",
        api_version=protocol.CURRENT_API_VERSION,
        api_version_header=protocol.TICKETBOX_API_VERSION_HEADER,
        min_read_client_version=protocol.MIN_READ_CLIENT_VERSION,
        min_write_client_version=protocol.MIN_WRITE_CLIENT_VERSION,
        read_compatibility=read_compatibility,
        write_compatibility=write_compatibility,
        legacy_write_compatibility="client_upgrade_required",
        upload_original_receipt_version=protocol.UPLOAD_ORIGINAL_RECEIPT_VERSION,
        accounting_time_input_version=protocol.ACCOUNTING_TIME_INPUT_VERSION,
        repayment_time_input_version=protocol.REPAYMENT_TIME_INPUT_VERSION,
        original_attachment_version=protocol.ORIGINAL_ATTACHMENT_VERSION,
        original_attachment_create_version=protocol.ORIGINAL_ATTACHMENT_CREATE_VERSION,
        debt_activity_read_version=protocol.DEBT_ACTIVITY_READ_VERSION,
        debt_bill_source_version=protocol.DEBT_BILL_SOURCE_VERSION,
        expense_confirmation_version=protocol.EXPENSE_CONFIRMATION_VERSION,
        notification_batch_version=protocol.NOTIFICATION_BATCH_VERSION,
        currency=RuntimeCurrencyCapability(
            home_currency_code=product_home_currency,
            minor_unit_exponent=capability.minor_unit_exponent,
            rounding_mode=capability.rounding_mode,
            contract_version=capability.currency_contract_version,
            binding_revision=capability.binding_revision,
            request_binding=(
                protocol.format_currency_binding(
                    contract_version=capability.currency_contract_version,
                    binding_revision=capability.binding_revision,
                    home_currency_code=product_home_currency,
                )
                if product_home_currency is not None
                else None
            ),
            request_binding_header=protocol.TICKETBOX_CURRENCY_BINDING_HEADER,
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
