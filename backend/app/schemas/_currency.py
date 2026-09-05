"""Cross-ADR installation currency capability and adoption contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CurrencyCode = Literal["CNY", "USD", "EUR", "GBP", "JPY", "HKD", "KRW"]
RuntimeCompatibilityConclusion = Literal[
    "compatible",
    "client_upgrade_required",
    "owner_action_required",
    "configuration_required",
    "server_upgrade_required",
]


class RuntimeCurrencyCapabilityResponse(BaseModel):
    home_currency_code: CurrencyCode | None
    minor_unit_exponent: int | None
    rounding_mode: Literal["ROUND_HALF_UP"] | None
    contract_version: int = Field(ge=1)
    binding_revision: int = Field(ge=0)
    request_binding: str | None = Field(
        pattern=r"^[1-9][0-9]*:(?:0|[1-9][0-9]*):[A-Z]{3}$"
    )
    request_binding_header: Literal["Ticketbox-Currency-Binding"]
    initialization_offer: CurrencyCode | None
    read_compatibility: RuntimeCompatibilityConclusion
    write_compatibility: RuntimeCompatibilityConclusion


class RuntimeProductCapabilitiesResponse(BaseModel):
    currency: RuntimeCurrencyCapabilityResponse


class RuntimeCompatibilitySnapshotResponse(BaseModel):
    contract: Literal["ticketbox-runtime-compatibility-v1"]
    observed_at: str
    api_version: str
    api_version_header: Literal["Ticketbox-Api-Version"]
    read_compatibility: RuntimeCompatibilityConclusion
    write_compatibility: RuntimeCompatibilityConclusion
    legacy_write_compatibility: Literal[
        "compatible",
        "client_upgrade_required",
    ]
    capabilities: RuntimeProductCapabilitiesResponse
