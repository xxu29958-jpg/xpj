"""Isolated-restore evidence validation for C07 production."""

from __future__ import annotations

import hashlib

from app.database._c07_production_authority import (
    _parse_host_envelope,
    _parse_recovery_envelope,
    _validate_artifact_paths,
    _validate_freeze_payload,
)
from app.database._c07_production_contract import (
    _GENERATION_DATABASE_FIELDS,
    _RESTORE_EVIDENCE_FIELDS,
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    DATABASE_NAME,
    ISOLATED_RESTORE_EVIDENCE_SCHEMA,
    RECOVERY_INTEGRITY_SCOPE,
    C07ProductionMigrationError,
    ProductionMigrationContext,
    ValidatedProductionArtifacts,
    _require_decimal_string,
    _require_exact_fields,
    _require_lower_sha,
    _require_utc,
    _require_uuid,
)
from app.database._c07_production_recovery import (
    _capacity_fields,
    _validate_generation_payload,
)


def _validate_restore_evidence(
    payload: dict[str, object],
    declared_sha256: str,
    *,
    context: ProductionMigrationContext,
    generation: ValidatedProductionArtifacts,
    generation_payload: dict[str, object],
) -> None:
    _require_exact_fields(
        payload,
        _RESTORE_EVIDENCE_FIELDS,
        label="isolated restore evidence",
    )
    database, asset_inventory, original_copies, capacity = _restore_sources(generation_payload)
    restore_oid = _require_decimal_string(
        payload.get("restore_database_oid"),
        label="isolated restore database OID",
        minimum=1,
        maximum=(2**32) - 1,
    )
    if _restore_binding_is_invalid(
        payload,
        context=context,
        generation=generation,
        asset_inventory=asset_inventory,
        original_copies=original_copies,
        capacity=capacity,
        restore_oid=restore_oid,
        declared_sha256=declared_sha256,
    ):
        raise C07ProductionMigrationError("isolated restore evidence does not bind the READY generation")
    _validate_restore_scalar_evidence(payload)
    if database.get("name") != DATABASE_NAME:
        raise C07ProductionMigrationError("isolated restore evidence refers to the wrong source database")


def _restore_sources(
    generation_payload: dict[str, object],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    database = _require_exact_fields(
        generation_payload.get("database"),
        _GENERATION_DATABASE_FIELDS,
        label="recovery database",
    )
    asset_inventory = _require_exact_fields(
        generation_payload.get("asset_inventory"),
        frozenset({"file", "sha256", "size_bytes", "row_count"}),
        label="recovery asset inventory",
    )
    original_copies = _require_exact_fields(
        generation_payload.get("original_copies"),
        frozenset({"file", "sha256", "size_bytes", "row_count", "asset_directory"}),
        label="recovery original copies",
    )
    capacity = _require_exact_fields(
        generation_payload.get("capacity"),
        _capacity_fields(generation_payload.get("capacity")),
        label="recovery capacity",
    )
    return database, asset_inventory, original_copies, capacity


def _restore_binding_is_invalid(
    payload: dict[str, object],
    *,
    context: ProductionMigrationContext,
    generation: ValidatedProductionArtifacts,
    asset_inventory: dict[str, object],
    original_copies: dict[str, object],
    capacity: dict[str, object],
    restore_oid: int,
    declared_sha256: str,
) -> bool:
    restore_create_attempt_id = _require_uuid(
        payload.get("restore_create_attempt_id"),
        label="isolated restore create attempt",
    )
    expected_restore_name = _restore_database_name(
        operation_id=context.source_recovery_operation_id,
        create_attempt_id=restore_create_attempt_id,
    )
    return (
        payload.get("schema") != ISOLATED_RESTORE_EVIDENCE_SCHEMA
        or payload.get("operation_id") != context.source_recovery_operation_id
        or payload.get("operation_kind") != context.operation_kind
        or payload.get("target_alembic_revision") != context.target_alembic_revision
        or payload.get("revision_manifest_sha256") != context.source_recovery_revision_manifest_sha256
        or payload.get("installation_id") != generation.installation_id
        or payload.get("generation_payload_sha256") != generation.generation_payload_sha256
        or payload.get("source_cluster_system_identifier") != generation.cluster_system_identifier
        or payload.get("source_database_oid") != generation.database_oid
        or payload.get("restore_database") != expected_restore_name
        or restore_oid == int(generation.database_oid)
        or payload.get("logical_server_id") != generation.logical_server_id
        or payload.get("logical_data_generation") != generation.logical_data_generation
        or payload.get("asset_inventory_sha256") != asset_inventory.get("sha256")
        or payload.get("money_facts_sha256") != generation.money_facts_sha256
        or _require_decimal_string(
            payload.get("asset_inventory_rows"),
            label="isolated restore inventory rows",
        )
        != _require_decimal_string(
            asset_inventory.get("row_count"),
            label="recovery asset inventory rows",
        )
        or _require_decimal_string(
            payload.get("original_copies_verified"),
            label="isolated restore original copies",
        )
        != _require_decimal_string(
            original_copies.get("row_count"),
            label="recovery original copy rows",
        )
        or _require_decimal_string(
            payload.get("isolated_asset_bytes"),
            label="isolated restore asset bytes",
        )
        != _require_decimal_string(
            capacity.get("asset_isolated_restore_bytes"),
            label="recovery isolated asset bytes",
        )
        or payload.get("thumbnails") != "audited_rebuildable_not_copied"
        or payload.get("forward_replay_source_revision") != C07_SOURCE_REVISION
        or payload.get("forward_replay_target_revision") != C07_TARGET_REVISION
        or payload.get("forward_replay_result") != "isolated_forward_replay_verified"
        or payload.get("result") != "isolated_restore_reconciled"
        or payload.get("integrity_scope") != RECOVERY_INTEGRITY_SCOPE
        or declared_sha256.upper() != context.isolated_restore_evidence_sha256
    )


def _restore_database_name(
    *,
    operation_id: str,
    create_attempt_id: str,
) -> str:
    binding = f"ticketbox-c07-restore-attempt-v1|{operation_id}|{create_attempt_id}"
    digest = hashlib.sha256(binding.encode("utf-8")).hexdigest()
    return f"ticketbox_c07_restore_{digest[:40]}"


def _validate_restore_scalar_evidence(payload: dict[str, object]) -> None:
    _require_uuid(
        payload.get("restore_create_attempt_id"),
        label="isolated restore create attempt",
    )
    _require_lower_sha(
        payload.get("restore_create_authority_sha256"),
        label="isolated restore create authority",
    )
    _require_lower_sha(
        payload.get("generation_payload_sha256"),
        label="isolated restore generation payload",
    )
    _require_lower_sha(
        payload.get("asset_inventory_sha256"),
        label="isolated restore asset inventory",
    )
    _require_lower_sha(
        payload.get("target_shape_sha256"),
        label="isolated restore target shape",
    )
    _require_lower_sha(
        payload.get("money_facts_sha256"),
        label="isolated restore canonical money facts",
    )
    _require_utc(
        payload.get("verified_at_utc"),
        label="isolated restore verified_at_utc",
    )


def validate_production_migration_artifact_bytes(
    context: ProductionMigrationContext,
    *,
    writer_freeze_proof: bytes,
    recovery_manifest: bytes,
    isolated_restore_evidence: bytes,
) -> ValidatedProductionArtifacts:
    freeze_binding_sequence = _validate_artifact_paths(context)
    freeze_payload, freeze_sha256 = _parse_host_envelope(
        writer_freeze_proof,
        expected_kind="freeze_proof",
    )
    _validate_freeze_payload(
        freeze_payload,
        freeze_sha256,
        context=context,
        freeze_binding_sequence=freeze_binding_sequence,
    )
    generation_payload, generation_sha256 = _parse_recovery_envelope(
        recovery_manifest,
        label="recovery manifest",
    )
    generation = _validate_generation_payload(
        generation_payload,
        generation_sha256,
        context=context,
    )
    restore_payload, restore_sha256 = _parse_recovery_envelope(
        isolated_restore_evidence,
        label="isolated restore evidence",
    )
    _validate_restore_evidence(
        restore_payload,
        restore_sha256,
        context=context,
        generation=generation,
        generation_payload=generation_payload,
    )
    return generation
