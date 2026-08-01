"""Recovery-generation validation for the C07 production migration."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.database._c07_production_connection import _database_binding_sha256
from app.database._c07_production_contract import (
    _GENERATION_DATABASE_FIELDS,
    _GENERATION_FIELDS,
    _GENERATION_INTEGRITY_FIELDS,
    _GENERATION_LIFECYCLE_FIELDS,
    _GENERATION_RELEASE_FIELDS,
    C07_SOURCE_REVISION,
    DATABASE_NAME,
    RECOVERY_GENERATION_SCHEMA,
    RECOVERY_INTEGRITY_SCOPE,
    TARGET_RECOVERY_GENERATION_SCHEMA,
    C07ProductionMigrationError,
    ProductionMigrationContext,
    ValidatedProductionArtifacts,
    _require_bool,
    _require_decimal_string,
    _require_exact_fields,
    _require_lower_sha,
    _require_string,
    _require_upper_sha,
    _require_utc,
    _require_uuid,
)


@dataclass(frozen=True)
class _GenerationSections:
    release: dict[str, object]
    lifecycle: dict[str, object]
    integrity: dict[str, object]
    barrier: dict[str, object]
    database: dict[str, object]
    asset_inventory: dict[str, object]
    original_copies: dict[str, object]
    thumbnail: dict[str, object]
    completion: dict[str, object]


def _generation_sections(payload: dict[str, object]) -> _GenerationSections:
    _require_exact_fields(payload, _GENERATION_FIELDS, label="recovery generation")
    section_specs = (
        ("release", _GENERATION_RELEASE_FIELDS, "recovery release"),
        ("lifecycle", _GENERATION_LIFECYCLE_FIELDS, "recovery lifecycle"),
        (
            "integrity",
            _GENERATION_INTEGRITY_FIELDS,
            "recovery integrity",
        ),
        (
            "barrier",
            frozenset({"mode", "exported_snapshot_id", "captured_at_utc"}),
            "recovery barrier",
        ),
        ("database", _GENERATION_DATABASE_FIELDS, "recovery database"),
        (
            "asset_inventory",
            frozenset({"file", "sha256", "size_bytes", "row_count"}),
            "recovery asset inventory",
        ),
        (
            "original_copies",
            frozenset({"file", "sha256", "size_bytes", "row_count", "asset_directory"}),
            "recovery original copies",
        ),
        (
            "thumbnail_policy",
            frozenset({"authority", "copied", "references_audited"}),
            "recovery thumbnail policy",
        ),
        (
            "completion",
            frozenset({"state", "created_by", "created_at_utc"}),
            "recovery completion",
        ),
    )
    sections = [_require_exact_fields(payload.get(key), fields, label=label) for key, fields, label in section_specs]
    return _GenerationSections(*sections)


def _upload_root_binding_sha256(sections: _GenerationSections) -> str:
    return _require_lower_sha(
        sections.integrity.get("upload_root_binding_sha256"),
        label="recovery configured upload-root binding",
    )


def validate_recovery_generation_upload_root_binding(
    payload: dict[str, object],
    *,
    context: ProductionMigrationContext,
) -> str:
    schema = payload.get("schema")
    if schema not in {
        RECOVERY_GENERATION_SCHEMA,
        TARGET_RECOVERY_GENERATION_SCHEMA,
    }:
        raise C07ProductionMigrationError("recovery generation upload-root schema is unsupported")
    integrity = _require_exact_fields(
        payload.get("integrity"),
        _GENERATION_INTEGRITY_FIELDS,
        label="recovery generation integrity",
    )
    binding = _require_lower_sha(
        integrity.get("upload_root_binding_sha256"),
        label="recovery configured upload-root binding",
    )
    if binding != context.upload_root_binding_sha256:
        raise C07ProductionMigrationError("recovery generation upload-root authority/binding is invalid")
    return binding


def _generation_identity(
    sections: _GenerationSections,
    *,
    declared_sha256: str,
) -> tuple[ValidatedProductionArtifacts, int]:
    _upload_root_binding_sha256(sections)
    _require_upper_sha(
        sections.release.get("fingerprint"),
        label="recovery release fingerprint",
    )
    _require_upper_sha(
        sections.release.get("build_manifest_sha256"),
        label="recovery build manifest",
    )
    _require_string(
        sections.release.get("backend_version"),
        label="recovery backend version",
    )
    for field in ("authority_chain_sha256", "freeze_proof_sha256"):
        _require_upper_sha(
            sections.lifecycle.get(field),
            label=f"recovery lifecycle {field}",
        )
    heartbeat = _require_decimal_string(
        sections.lifecycle.get("freeze_heartbeat_sequence"),
        label="recovery freeze heartbeat sequence",
        minimum=1,
        maximum=(2**63) - 1,
    )
    cluster = _require_string(
        sections.database.get("cluster_system_identifier"),
        label="recovery cluster system identifier",
    )
    if re.fullmatch(r"[0-9]{10,32}", cluster) is None:
        raise C07ProductionMigrationError("recovery cluster system identifier is invalid")
    database_oid = str(
        _require_decimal_string(
            sections.database.get("source_database_oid"),
            label="recovery source database OID",
            minimum=1,
            maximum=(2**32) - 1,
        )
    )
    artifacts = ValidatedProductionArtifacts(
        installation_id=_require_uuid(
            sections.release.get("installation_id"),
            label="recovery installation_id",
        ),
        cluster_system_identifier=cluster,
        database_oid=database_oid,
        logical_server_id=_require_uuid(
            sections.database.get("server_id"),
            label="recovery logical server_id",
        ),
        logical_data_generation=_require_uuid(
            sections.database.get("data_generation"),
            label="recovery logical data_generation",
        ),
        generation_payload_sha256=declared_sha256,
        money_facts_sha256=_require_lower_sha(
            sections.database.get("money_facts_sha256"),
            label="recovery canonical money facts",
        ),
    )
    if sections.database.get("alembic_heads") != [C07_SOURCE_REVISION]:
        raise C07ProductionMigrationError("recovery generation is not bound to the C07 source revision")
    return artifacts, heartbeat


def _validate_generation_assets(sections: _GenerationSections) -> None:
    for value, label in (
        (sections.database.get("dump_sha256"), "recovery database dump"),
        (sections.database.get("restore_list_sha256"), "recovery restore list"),
        (sections.asset_inventory.get("sha256"), "recovery asset inventory"),
        (sections.original_copies.get("sha256"), "recovery original copies"),
    ):
        _require_lower_sha(value, label=label)
    inventory_rows = _require_decimal_string(
        sections.asset_inventory.get("row_count"),
        label="recovery asset inventory rows",
    )
    copy_rows = _require_decimal_string(
        sections.original_copies.get("row_count"),
        label="recovery original copy rows",
    )
    for value, label, minimum in (
        (sections.database.get("dump_size_bytes"), "recovery dump size", 1),
        (
            sections.asset_inventory.get("size_bytes"),
            "recovery asset inventory size",
            0,
        ),
        (
            sections.original_copies.get("size_bytes"),
            "recovery copies inventory size",
            0,
        ),
    ):
        _require_decimal_string(
            value,
            label=label,
            minimum=minimum,
            maximum=(2**63) - 1,
        )
    if copy_rows > inventory_rows:
        raise C07ProductionMigrationError("recovery original copies exceed the asset inventory")


def _validate_generation_binding(
    payload: dict[str, object],
    sections: _GenerationSections,
    *,
    context: ProductionMigrationContext,
    declared_sha256: str,
    heartbeat: int,
) -> None:
    validate_recovery_generation_upload_root_binding(payload, context=context)
    source_is_current = context.source_recovery_operation_id == context.operation_id
    invalid = (
        payload.get("schema") != RECOVERY_GENERATION_SCHEMA
        or payload.get("operation_id") != context.source_recovery_operation_id
        or payload.get("generation_id") != context.source_recovery_operation_id
        or sections.release.get("fingerprint") != context.source_recovery_release_fingerprint
        or sections.lifecycle.get("stage") != "writers_frozen"
        or sections.lifecycle.get("operation_kind") != context.operation_kind
        or sections.lifecycle.get("target_alembic_revision") != context.target_alembic_revision
        or sections.lifecycle.get("revision_manifest_sha256") != context.source_recovery_revision_manifest_sha256
        or sections.lifecycle.get("authority_chain_sha256") != context.lifecycle_root_authority_chain_sha256
        or sections.lifecycle.get("freeze_proof_sha256") != context.source_recovery_freeze_proof_sha256
        or (source_is_current and heartbeat > context.heartbeat_sequence)
        or sections.integrity.get("scope") != RECOVERY_INTEGRITY_SCOPE
        or _require_bool(
            sections.integrity.get("malicious_writer_resistance"),
            label="recovery malicious_writer_resistance",
        )
        or not _valid_generation_layout(sections)
        or declared_sha256.upper() != context.recovery_manifest_sha256
    )
    if invalid:
        raise C07ProductionMigrationError("recovery generation authority/binding is invalid")
    _require_utc(
        sections.barrier.get("captured_at_utc"),
        label="recovery captured_at_utc",
    )
    _require_utc(
        sections.completion.get("created_at_utc"),
        label="recovery created_at_utc",
    )


def _valid_generation_layout(sections: _GenerationSections) -> bool:
    snapshot = sections.barrier.get("exported_snapshot_id")
    return (
        sections.barrier.get("mode") == "bounded_quiesce_plus_pg_export_snapshot"
        and isinstance(snapshot, str)
        and re.fullmatch(
            r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}",
            snapshot,
        )
        is not None
        and sections.database.get("name") == DATABASE_NAME
        and sections.database.get("dump_file") == "database.dump"
        and sections.asset_inventory.get("file") == "asset-inventory.jsonl"
        and sections.original_copies.get("file") == "asset-copies.jsonl"
        and sections.original_copies.get("asset_directory") == "assets"
        and sections.thumbnail.get("authority") == "derived_rebuildable_cache"
        and not _require_bool(
            sections.thumbnail.get("copied"),
            label="thumbnail copied",
        )
        and _require_bool(
            sections.thumbnail.get("references_audited"),
            label="thumbnail references_audited",
        )
        and sections.completion.get("state") == "generation_ready"
        and sections.completion.get("created_by") == "windows_c07_recovery_generation"
    )


def _validate_generation_payload(
    payload: dict[str, object],
    declared_sha256: str,
    *,
    context: ProductionMigrationContext,
) -> ValidatedProductionArtifacts:
    sections = _generation_sections(payload)
    artifacts, heartbeat = _generation_identity(
        sections,
        declared_sha256=declared_sha256,
    )
    _validate_generation_assets(sections)
    _validate_capacity(payload.get("capacity"))
    _validate_generation_binding(
        payload,
        sections,
        context=context,
        declared_sha256=declared_sha256,
        heartbeat=heartbeat,
    )
    actual_binding = _database_binding_sha256(
        installation_id=artifacts.installation_id,
        cluster_system_identifier=artifacts.cluster_system_identifier,
        database_oid=artifacts.database_oid,
        logical_server_id=artifacts.logical_server_id,
        logical_data_generation=artifacts.logical_data_generation,
    )
    if actual_binding != context.database_binding_sha256:
        raise C07ProductionMigrationError("recovery generation does not reproduce the live database binding")
    return artifacts


def _validate_capacity(value: object) -> None:
    capacity = _require_exact_fields(
        value,
        _capacity_fields(value),
        label="recovery capacity",
    )
    if capacity.get("schema") != "ticketbox-c07-recovery-capacity-v1" or capacity.get("headroom_percent") != 20:
        raise C07ProductionMigrationError("recovery capacity schema/headroom is invalid")
    numeric_fields = set(capacity) - {
        "schema",
        "volume_mode",
        "headroom_percent",
    }
    numbers = {
        field: _require_decimal_string(
            capacity.get(field),
            label=f"recovery capacity {field}",
        )
        for field in numeric_fields
    }
    if (
        numbers["database_size_bytes"] == 0
        or numbers["dump_estimate_bytes"] != numbers["database_size_bytes"]
        or numbers["isolated_restore_estimate_bytes"] != numbers["database_size_bytes"]
        or numbers["rewrite_index_estimate_bytes"] != numbers["database_size_bytes"]
        or numbers["asset_generation_copy_bytes"] != numbers["asset_isolated_restore_bytes"]
        or numbers["wal_reserve_bytes"] < numbers["database_size_bytes"]
        or numbers["wal_reserve_bytes"] < numbers["observed_wal_bytes"]
        or numbers["manifest_inventory_reserve_bytes"] == 0
    ):
        raise C07ProductionMigrationError("recovery capacity components are inconsistent")
    if capacity.get("volume_mode") == "shared":
        if numbers["free_bytes_at_preflight"] < numbers["required_with_headroom_bytes"]:
            raise C07ProductionMigrationError("recovery shared-volume capacity is insufficient")
    elif (
        numbers["database_free_bytes_at_preflight"] < numbers["database_required_with_headroom_bytes"]
        or numbers["generation_free_bytes_at_preflight"] < numbers["generation_required_with_headroom_bytes"]
    ):
        raise C07ProductionMigrationError("recovery split-volume capacity is insufficient")


def _capacity_fields(value: object) -> frozenset[str]:
    if not isinstance(value, dict):
        raise C07ProductionMigrationError("recovery capacity must be an object")
    common = {
        "schema",
        "volume_mode",
        "database_size_bytes",
        "dump_estimate_bytes",
        "isolated_restore_estimate_bytes",
        "rewrite_index_estimate_bytes",
        "observed_wal_bytes",
        "wal_reserve_bytes",
        "asset_generation_copy_bytes",
        "asset_isolated_restore_bytes",
        "manifest_inventory_reserve_bytes",
        "headroom_percent",
    }
    if value.get("volume_mode") == "shared":
        return frozenset(common | {"required_with_headroom_bytes", "free_bytes_at_preflight"})
    if value.get("volume_mode") == "split":
        return frozenset(
            common
            | {
                "database_required_with_headroom_bytes",
                "database_free_bytes_at_preflight",
                "generation_required_with_headroom_bytes",
                "generation_free_bytes_at_preflight",
            }
        )
    raise C07ProductionMigrationError("recovery capacity volume_mode is invalid")
