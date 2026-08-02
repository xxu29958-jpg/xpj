"""Cross-ADR installation currency capability and adoption contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CurrencyCode = Literal["CNY", "USD", "EUR", "GBP", "JPY", "HKD", "KRW"]
RuntimeCompatibilityConclusion = Literal[
    "compatible",
    "client_upgrade_required",
    "owner_action_required",
    "configuration_required",
    "server_upgrade_required",
]


class CurrencyCapabilityResponse(BaseModel):
    state: Literal["EMPTY", "ADOPTION_REQUIRED", "ACTIVE"]
    home_currency_code: CurrencyCode | None
    minor_unit_exponent: int | None
    rounding_mode: Literal["ROUND_HALF_UP"] | None
    currency_contract_version: int
    binding_revision: int
    minimum_writable_currency_contract: int
    health: Literal[
        "empty",
        "adoption_required",
        "active_match",
        "configuration_drift",
        "migration_required",
    ]
    initialization_offer: CurrencyCode | None


class RuntimeCurrencyCapabilityResponse(BaseModel):
    home_currency_code: CurrencyCode | None
    minor_unit_exponent: int | None
    rounding_mode: Literal["ROUND_HALF_UP"] | None
    contract_version: int = Field(ge=1)
    binding_revision: int = Field(ge=0)
    request_binding: str = Field(pattern=r"^[1-9][0-9]*:(?:0|[1-9][0-9]*)$")
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


class CurrencyAdoptionPreviewResponse(BaseModel):
    state: Literal["EMPTY", "ADOPTION_REQUIRED", "ACTIVE"]
    binding_revision: int
    currency_contract_version: int
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configured_home_currency_code: CurrencyCode | None
    allowed_home_currency_codes: list[CurrencyCode]
    evidence_health: Literal["adoptable", "conflict"]


class CurrencyAdoptionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency_contract_version: int = Field(ge=1)
    home_currency_code: CurrencyCode
    expected_state: Literal["ADOPTION_REQUIRED"]
    expected_binding_revision: int = Field(ge=0)
    expected_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


class CurrencyAdoptionReceiptResponse(BaseModel):
    operation: Literal["currency_binding_adoption"]
    event_id: str
    state: Literal["ACTIVE"]
    home_currency_code: CurrencyCode
    minor_unit_exponent: int
    rounding_mode: Literal["ROUND_HALF_UP"]
    currency_contract_version: int
    binding_revision: int
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    activated_at: str
