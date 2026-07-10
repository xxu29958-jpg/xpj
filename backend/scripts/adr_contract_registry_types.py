"""Shared value types for the executable ADR registry."""

from __future__ import annotations

from dataclasses import dataclass

from adr_contract_schema import AdrRelation


@dataclass(frozen=True)
class RegistryEntry:
    adr_id: str
    path: str
    title: str
    summary: str
    current_scope: str
    schema_version: int
    source_kind: str
    decision_status: str
    implementation_status: str
    verification_status: str
    decision_type: str
    risk_level: str
    confidence: str
    decision_owner: str
    implementation_owner: str
    verification_owner: str
    risk_owner: str
    relations: tuple[AdrRelation, ...]
    clause_ids: tuple[str, ...]
    reviewed_at: str | None
    reviewed_against_commit: str | None
    calibration_reason: str | None
    history_fingerprint: str | None = None


@dataclass(frozen=True)
class Registry:
    schema_version: int
    front_matter_schema_version: int
    portfolio_reviewed_at: str
    code_baseline: str
    baseline_scope: str
    entries: tuple[RegistryEntry, ...]
    bootstrap_base_commit: str = ""


class RegistryError(ValueError):
    """Raised when registry sources or generated views violate the contract."""
