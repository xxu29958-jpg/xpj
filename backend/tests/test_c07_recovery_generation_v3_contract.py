"""C07 v3 recovery consumer and extracted-module reference contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import app.c07_money_facts_contract as c07_money_facts_contract
import app.database._c07_app_meta as c07_app_meta
import app.database._c07_ceremony_document as c07_ceremony_document
import app.database._c07_commit_reconciliation as c07_commit_reconciliation
import app.database._c07_host_evidence_helpers as c07_host_evidence_helpers
import app.database._c07_maintenance_attestation as c07_maintenance_attestation
import app.database._c07_maintenance_common as c07_maintenance_common
import app.database._c07_maintenance_digest as c07_maintenance_digest
import app.database._c07_maintenance_upgrade_action as c07_maintenance_upgrade_action
import app.database._c07_production_authority as c07_production_authority
import app.database._c07_production_context as c07_production_context
import app.database._c07_production_contract_types as c07_contract_types
import app.database._c07_production_fence as c07_production_fence
import app.database._c07_production_migration as c07_production_migration
import app.database._c07_production_ready as c07_production_ready
import app.database._c07_production_recovery as c07_production_recovery
import app.database._c07_production_restore as c07_production_restore
import app.database._c07_receipt_validation as c07_receipt_validation
import app.database._c07_runtime_projection as c07_runtime_projection
import app.money_carrier as money_carrier
import app.money_contract_manifest as money_contract_manifest
import app.money_contract_types as money_contract_types
import app.routes._web_report_money_views as web_report_money_views
import app.services.backup_job_lease as backup_job_lease
import app.services.budget_money as budget_money
import app.services.import_money as import_money
import app.services.owner_console_service._recycle_bin_money as recycle_bin_money
import app.services.receipt_parse_money as receipt_parse_money
import app.services.rule_money as rule_money
import app.services.stats_money as stats_money

_DIRECTLY_REFERENCED_MODULES = (
    backup_job_lease,
    budget_money,
    c07_app_meta,
    c07_ceremony_document,
    c07_commit_reconciliation,
    c07_contract_types,
    c07_host_evidence_helpers,
    c07_maintenance_attestation,
    c07_maintenance_common,
    c07_maintenance_digest,
    c07_maintenance_upgrade_action,
    c07_money_facts_contract,
    c07_production_authority,
    c07_production_context,
    c07_production_fence,
    c07_production_migration,
    c07_production_ready,
    c07_production_recovery,
    c07_production_restore,
    c07_receipt_validation,
    c07_runtime_projection,
    import_money,
    money_carrier,
    money_contract_manifest,
    money_contract_types,
    receipt_parse_money,
    recycle_bin_money,
    rule_money,
    stats_money,
    web_report_money_views,
)

_CURRENT_OPERATION_ID = "11111111-1111-4111-8111-111111111111"
_PREDECESSOR_OPERATION_ID = "33333333-3333-4333-8333-333333333333"
_RESTORE_CREATE_ATTEMPT_ID = "44444444-4444-4444-8444-444444444444"
_CURRENT_RELEASE_FINGERPRINT = "A" * 64
_CURRENT_REVISION_MANIFEST_SHA256 = "B" * 64
_CURRENT_FREEZE_PROOF_SHA256 = "C" * 64
_SOURCE_RELEASE_FINGERPRINT = "D" * 64
_SOURCE_REVISION_MANIFEST_SHA256 = "E" * 64
_SOURCE_FREEZE_PROOF_SHA256 = "F" * 64
_LIFECYCLE_SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "windows_c07_lifecycle.ps1"


def _generation_payload(binding_sha256: object) -> dict[str, object]:
    return {
        "schema": c07_contract_types.RECOVERY_GENERATION_SCHEMA,
        "operation_id": "unused-by-section-parser",
        "generation_id": "unused-by-section-parser",
        "release": dict.fromkeys(c07_contract_types._GENERATION_RELEASE_FIELDS),
        "lifecycle": dict.fromkeys(c07_contract_types._GENERATION_LIFECYCLE_FIELDS),
        "integrity": {
            "scope": None,
            "malicious_writer_resistance": None,
            "upload_root_binding_sha256": binding_sha256,
        },
        "barrier": {
            "mode": None,
            "exported_snapshot_id": None,
            "captured_at_utc": None,
        },
        "database": dict.fromkeys(c07_contract_types._GENERATION_DATABASE_FIELDS),
        "asset_inventory": {
            "file": None,
            "sha256": None,
            "size_bytes": None,
            "row_count": None,
        },
        "original_copies": {
            "file": None,
            "sha256": None,
            "size_bytes": None,
            "row_count": None,
            "asset_directory": None,
        },
        "thumbnail_policy": {
            "authority": None,
            "copied": None,
            "references_audited": None,
        },
        "capacity": {},
        "completion": {
            "state": None,
            "created_by": None,
            "created_at_utc": None,
        },
    }


def _context_payload(
    binding_sha256: object,
    *,
    successor_mode: str = "",
) -> dict[str, object]:
    is_successor = successor_mode in {"pre_ddl", "forward_repair"}
    uses_predecessor_recovery = successor_mode == "forward_repair"
    source_operation_id = _PREDECESSOR_OPERATION_ID if uses_predecessor_recovery else _CURRENT_OPERATION_ID
    source_release_fingerprint = (
        _SOURCE_RELEASE_FINGERPRINT if uses_predecessor_recovery else _CURRENT_RELEASE_FINGERPRINT
    )
    source_revision_manifest_sha256 = (
        _SOURCE_REVISION_MANIFEST_SHA256 if uses_predecessor_recovery else _CURRENT_REVISION_MANIFEST_SHA256
    )
    source_freeze_proof_sha256 = (
        _SOURCE_FREEZE_PROOF_SHA256 if uses_predecessor_recovery else _CURRENT_FREEZE_PROOF_SHA256
    )
    host_root = "C:/ticketbox/c07-lifecycle"
    recovery_root = f"{host_root}/recovery-generations/operation-{source_operation_id}.ready"
    return {
        "schema": c07_contract_types.PRODUCTION_MIGRATION_CONTEXT_SCHEMA,
        "operation_id": _CURRENT_OPERATION_ID,
        "release_fingerprint": _CURRENT_RELEASE_FINGERPRINT,
        "migration_helper_relative_path": (c07_contract_types.C07_MIGRATION_HELPER_RELATIVE_PATH),
        "migration_helper_size": 1,
        "migration_helper_sha256": "1" * 64,
        "database_binding_sha256": "2" * 64,
        "upload_root_binding_sha256": binding_sha256,
        "recovery_epoch_id": "22222222-2222-4222-8222-222222222222",
        "coordinator_binding_sha256": "3" * 64,
        "coordinator_binding_sequence": 1,
        "heartbeat_sequence": 1,
        "operation_kind": "c07_money_minor_bigint_v1",
        "target_alembic_revision": c07_contract_types.C07_TARGET_REVISION,
        "revision_manifest_sha256": _CURRENT_REVISION_MANIFEST_SHA256,
        "successor_mode": successor_mode,
        "successor_intent_sha256": "4" * 64 if is_successor else "",
        "predecessor_operation_id": (_PREDECESSOR_OPERATION_ID if is_successor else ""),
        "predecessor_terminal_authority_chain_sha256": ("5" * 64 if is_successor else ""),
        "source_recovery_operation_id": source_operation_id,
        "source_recovery_release_fingerprint": source_release_fingerprint,
        "source_recovery_revision_manifest_sha256": (source_revision_manifest_sha256),
        "source_recovery_freeze_proof_sha256": source_freeze_proof_sha256,
        "maintenance_deadline_utc": "2026-08-02T00:00:00Z",
        "maintenance_remaining_ceiling_ms": 1,
        "maintenance_authority_sha256": "6" * 64,
        "writer_freeze_proof_path": (f"{host_root}/operation-{_CURRENT_OPERATION_ID}-freeze-proof-binding-1.json"),
        "writer_freeze_proof_sha256": _CURRENT_FREEZE_PROOF_SHA256,
        "recovery_manifest_path": f"{recovery_root}/manifest.json",
        "recovery_manifest_sha256": "7" * 64,
        "isolated_restore_evidence_path": (f"{recovery_root}/isolated-restore-evidence.json"),
        "isolated_restore_evidence_sha256": "8" * 64,
        "lifecycle_root_authority_chain_sha256": "9" * 64,
    }


def _bound_generation_authority(
    context: c07_contract_types.ProductionMigrationContext,
) -> dict[str, object]:
    heartbeat = 1 if context.source_recovery_operation_id == context.operation_id else 99
    return {
        "operation_id": context.source_recovery_operation_id,
        "generation_id": context.source_recovery_operation_id,
        "release": {
            "fingerprint": context.source_recovery_release_fingerprint,
            "installation_id": "55555555-5555-4555-8555-555555555555",
            "build_manifest_sha256": "A" * 64,
            "backend_version": "1.0.0",
        },
        "lifecycle": {
            "stage": "writers_frozen",
            "operation_kind": context.operation_kind,
            "target_alembic_revision": context.target_alembic_revision,
            "revision_manifest_sha256": context.source_recovery_revision_manifest_sha256,
            "authority_chain_sha256": context.lifecycle_root_authority_chain_sha256,
            "freeze_proof_sha256": context.source_recovery_freeze_proof_sha256,
            "freeze_heartbeat_sequence": str(heartbeat),
        },
        "integrity": {
            "scope": c07_contract_types.RECOVERY_INTEGRITY_SCOPE,
            "malicious_writer_resistance": False,
            "upload_root_binding_sha256": context.upload_root_binding_sha256,
        },
        "barrier": {
            "mode": "bounded_quiesce_plus_pg_export_snapshot",
            "exported_snapshot_id": "00000001-00000002-1",
            "captured_at_utc": "2026-08-02T00:00:00Z",
        },
        "database": {
            "name": c07_contract_types.DATABASE_NAME,
            "cluster_system_identifier": "1234567890",
            "source_database_oid": "42",
            "server_version_num": "170000",
            "server_id": "66666666-6666-4666-8666-666666666666",
            "data_generation": "77777777-7777-4777-8777-777777777777",
            "alembic_heads": [c07_contract_types.C07_SOURCE_REVISION],
            "dump_file": "database.dump",
            "dump_sha256": "a" * 64,
            "dump_size_bytes": "1",
            "restore_list_sha256": "b" * 64,
            "money_facts_sha256": "c" * 64,
        },
    }


def _bound_generation_assets() -> dict[str, object]:
    return {
        "asset_inventory": {
            "file": "asset-inventory.jsonl",
            "sha256": "d" * 64,
            "size_bytes": "1",
            "row_count": "2",
        },
        "original_copies": {
            "file": "asset-copies.jsonl",
            "sha256": "e" * 64,
            "size_bytes": "1",
            "row_count": "1",
            "asset_directory": "assets",
        },
        "thumbnail_policy": {
            "authority": "derived_rebuildable_cache",
            "copied": False,
            "references_audited": True,
        },
        "capacity": {
            "schema": "ticketbox-c07-recovery-capacity-v1",
            "volume_mode": "shared",
            "database_size_bytes": "1",
            "dump_estimate_bytes": "1",
            "isolated_restore_estimate_bytes": "1",
            "rewrite_index_estimate_bytes": "1",
            "observed_wal_bytes": "0",
            "wal_reserve_bytes": "1",
            "asset_generation_copy_bytes": "10",
            "asset_isolated_restore_bytes": "10",
            "manifest_inventory_reserve_bytes": "1",
            "headroom_percent": 20,
            "required_with_headroom_bytes": "20",
            "free_bytes_at_preflight": "20",
        },
        "completion": {
            "state": "generation_ready",
            "created_by": "windows_c07_recovery_generation",
            "created_at_utc": "2026-08-02T00:00:01Z",
        },
    }


def _bound_generation_payload(
    context: c07_contract_types.ProductionMigrationContext,
) -> dict[str, object]:
    payload = _generation_payload(context.upload_root_binding_sha256)
    payload.update(_bound_generation_authority(context))
    payload.update(_bound_generation_assets())
    return payload


def _validated_generation(
    context: c07_contract_types.ProductionMigrationContext,
) -> c07_contract_types.ValidatedProductionArtifacts:
    return c07_contract_types.ValidatedProductionArtifacts(
        installation_id="55555555-5555-4555-8555-555555555555",
        cluster_system_identifier="1234567890",
        database_oid="42",
        logical_server_id="66666666-6666-4666-8666-666666666666",
        logical_data_generation="77777777-7777-4777-8777-777777777777",
        generation_payload_sha256=context.recovery_manifest_sha256.lower(),
        money_facts_sha256="c" * 64,
    )


def _restore_evidence_payload(
    context: c07_contract_types.ProductionMigrationContext,
) -> dict[str, object]:
    generation = _validated_generation(context)
    return {
        "schema": c07_contract_types.ISOLATED_RESTORE_EVIDENCE_SCHEMA,
        "operation_id": context.source_recovery_operation_id,
        "operation_kind": context.operation_kind,
        "target_alembic_revision": context.target_alembic_revision,
        "revision_manifest_sha256": (context.source_recovery_revision_manifest_sha256),
        "installation_id": generation.installation_id,
        "generation_payload_sha256": generation.generation_payload_sha256,
        "source_cluster_system_identifier": (generation.cluster_system_identifier),
        "source_database_oid": generation.database_oid,
        "restore_database": c07_production_restore._restore_database_name(
            operation_id=context.source_recovery_operation_id,
            create_attempt_id=_RESTORE_CREATE_ATTEMPT_ID,
        ),
        "restore_database_oid": "43",
        "restore_create_attempt_id": _RESTORE_CREATE_ATTEMPT_ID,
        "restore_create_authority_sha256": "f" * 64,
        "logical_server_id": generation.logical_server_id,
        "logical_data_generation": generation.logical_data_generation,
        "asset_inventory_sha256": "d" * 64,
        "asset_inventory_rows": "2",
        "original_copies_verified": "1",
        "isolated_asset_bytes": "10",
        "thumbnails": "audited_rebuildable_not_copied",
        "forward_replay_source_revision": c07_contract_types.C07_SOURCE_REVISION,
        "forward_replay_target_revision": c07_contract_types.C07_TARGET_REVISION,
        "forward_replay_result": "isolated_forward_replay_verified",
        "target_shape_sha256": "1" * 64,
        "money_facts_sha256": generation.money_facts_sha256,
        "result": "isolated_restore_reconciled",
        "integrity_scope": c07_contract_types.RECOVERY_INTEGRITY_SCOPE,
        "verified_at_utc": "2026-08-02T00:00:02Z",
    }


def test_extracted_application_modules_remain_directly_importable() -> None:
    assert all(module.__name__.startswith("app.") for module in _DIRECTLY_REFERENCED_MODULES)


def test_recovery_generation_schema_versions_are_direction_specific() -> None:
    assert c07_contract_types.PRODUCTION_MIGRATION_CONTEXT_SCHEMA == "ticketbox-c07-production-migration-context-v5"
    assert c07_contract_types.RECOVERY_GENERATION_SCHEMA == "ticketbox-c07-recovery-generation-v3"
    assert c07_contract_types.TARGET_RECOVERY_GENERATION_SCHEMA == "ticketbox-c07-target-recovery-generation-v2"


@pytest.mark.parametrize("successor_mode", ["", "pre_ddl", "forward_repair"])
def test_v5_context_parses_coordinator_ordered_bytes(
    successor_mode: str,
) -> None:
    payload = _context_payload("a" * 64, successor_mode=successor_mode)
    assert tuple(payload) == c07_contract_types._CONTEXT_FIELDS

    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    context = c07_production_context.parse_production_migration_context_bytes(raw)

    assert context.successor_mode == successor_mode
    assert context.source_recovery_operation_id == payload["source_recovery_operation_id"]
    assert context.source_recovery_freeze_proof_sha256 == payload["source_recovery_freeze_proof_sha256"]


def test_v5_context_rejects_nonproducer_field_order() -> None:
    payload = _context_payload("a" * 64)
    pairs = list(payload.items())
    pairs[0], pairs[1] = pairs[1], pairs[0]
    raw = json.dumps(dict(pairs), separators=(",", ":")).encode("utf-8")

    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="fields/order are not exact",
    ):
        c07_production_context.parse_production_migration_context_bytes(raw)


@pytest.mark.parametrize(
    "host_root",
    [
        r"C:\Program Files\Ticketbox\c07-lifecycle",
        r"\\server\share\Ticketbox\c07-lifecycle",
    ],
)
def test_v5_context_parses_absolute_windows_artifact_paths(
    host_root: str,
) -> None:
    payload = _context_payload("a" * 64)
    recovery_root = (
        f"{host_root}\\recovery-generations\\"
        f"operation-{_CURRENT_OPERATION_ID}.ready"
    )
    payload["writer_freeze_proof_path"] = (
        f"{host_root}\\operation-{_CURRENT_OPERATION_ID}-freeze-proof-binding-1.json"
    )
    payload["recovery_manifest_path"] = f"{recovery_root}\\manifest.json"
    payload["isolated_restore_evidence_path"] = (
        f"{recovery_root}\\isolated-restore-evidence.json"
    )

    context = c07_production_context.parse_production_migration_context(payload)

    assert context.writer_freeze_proof_path.is_absolute()
    assert c07_production_authority._validate_artifact_paths(context) == 1


@pytest.mark.parametrize(
    "invalid_path",
    [
        "/var/lib/ticketbox/c07-lifecycle/freeze.json",
        r"C:ticketbox\c07-lifecycle\freeze.json",
        r"\ticketbox\c07-lifecycle\freeze.json",
        r"C:\ticketbox\c07-lifecycle\..\freeze.json",
    ],
)
def test_v5_context_rejects_nonabsolute_or_traversing_artifact_paths(
    invalid_path: str,
) -> None:
    payload = _context_payload("a" * 64)
    payload["writer_freeze_proof_path"] = invalid_path

    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="absolute Windows path|parent traversal",
    ):
        c07_production_context.parse_production_migration_context(payload)


@pytest.mark.parametrize(
    ("successor_mode", "field", "value"),
    [
        ("", "successor_intent_sha256", "4" * 64),
        ("invalid", "successor_intent_sha256", ""),
        ("pre_ddl", "successor_intent_sha256", ""),
        (
            "pre_ddl",
            "source_recovery_operation_id",
            _PREDECESSOR_OPERATION_ID,
        ),
        (
            "forward_repair",
            "source_recovery_operation_id",
            _CURRENT_OPERATION_ID,
        ),
        (
            "forward_repair",
            "predecessor_operation_id",
            _CURRENT_OPERATION_ID,
        ),
        (
            "forward_repair",
            "predecessor_terminal_authority_chain_sha256",
            "",
        ),
        (
            "forward_repair",
            "source_recovery_release_fingerprint",
            "d" * 64,
        ),
    ],
)
def test_v5_context_rejects_inconsistent_lineage(
    successor_mode: str,
    field: str,
    value: object,
) -> None:
    payload = _context_payload("a" * 64, successor_mode=successor_mode)
    payload[field] = value

    with pytest.raises(c07_contract_types.C07ProductionMigrationError):
        c07_production_context.parse_production_migration_context(payload)


@pytest.mark.parametrize("successor_mode", ["", "pre_ddl", "forward_repair"])
def test_artifact_paths_split_current_freeze_from_source_recovery(
    successor_mode: str,
) -> None:
    context = c07_production_context.parse_production_migration_context(
        _context_payload("a" * 64, successor_mode=successor_mode)
    )

    assert c07_production_authority._validate_artifact_paths(context) == 1


def test_forward_repair_rejects_current_operation_recovery_root() -> None:
    payload = _context_payload("a" * 64, successor_mode="forward_repair")
    payload["recovery_manifest_path"] = (
        f"C:/ticketbox/c07-lifecycle/recovery-generations/operation-{_CURRENT_OPERATION_ID}.ready/manifest.json"
    )
    payload["isolated_restore_evidence_path"] = (
        "C:/ticketbox/c07-lifecycle/recovery-generations/"
        f"operation-{_CURRENT_OPERATION_ID}.ready/"
        "isolated-restore-evidence.json"
    )
    context = c07_production_context.parse_production_migration_context(payload)

    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="operation READY layout",
    ):
        c07_production_authority._validate_artifact_paths(context)


@pytest.mark.parametrize("successor_mode", ["", "pre_ddl", "forward_repair"])
def test_generation_binding_uses_frozen_source_recovery_authority(
    successor_mode: str,
) -> None:
    context = c07_production_context.parse_production_migration_context(
        _context_payload("a" * 64, successor_mode=successor_mode)
    )
    payload = _bound_generation_payload(context)
    sections = c07_production_recovery._generation_sections(payload)
    lifecycle = payload["lifecycle"]
    assert isinstance(lifecycle, dict)

    c07_production_recovery._validate_generation_binding(
        payload,
        sections,
        context=context,
        declared_sha256=context.recovery_manifest_sha256.lower(),
        heartbeat=int(lifecycle["freeze_heartbeat_sequence"]),
    )


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "operation_id", _CURRENT_OPERATION_ID),
        ("release", "fingerprint", _CURRENT_RELEASE_FINGERPRINT),
        (
            "lifecycle",
            "revision_manifest_sha256",
            _CURRENT_REVISION_MANIFEST_SHA256,
        ),
        (
            "lifecycle",
            "freeze_proof_sha256",
            _CURRENT_FREEZE_PROOF_SHA256,
        ),
    ],
)
def test_forward_repair_generation_rejects_current_authority_substitution(
    section: str | None,
    field: str,
    value: object,
) -> None:
    context = c07_production_context.parse_production_migration_context(
        _context_payload("a" * 64, successor_mode="forward_repair")
    )
    payload = _bound_generation_payload(context)
    target = payload if section is None else payload[section]
    assert isinstance(target, dict)
    target[field] = value
    sections = c07_production_recovery._generation_sections(payload)

    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="recovery generation authority/binding is invalid",
    ):
        c07_production_recovery._validate_generation_binding(
            payload,
            sections,
            context=context,
            declared_sha256=context.recovery_manifest_sha256.lower(),
            heartbeat=99,
        )


def test_python_v5_context_fields_match_coordinator_producer_order() -> None:
    source = _LIFECYCLE_SCRIPT.read_text(encoding="utf-8-sig")
    marker = "$migrationContext = [pscustomobject][ordered]@{"
    block = source.split(marker, 1)[1].split("\n    }", 1)[0]
    producer_fields = tuple(re.findall(r"^        ([a-z][a-z0-9_]*)\s*=", block, re.MULTILINE))

    assert producer_fields == c07_contract_types._CONTEXT_FIELDS


@pytest.mark.parametrize("successor_mode", ["", "pre_ddl", "forward_repair"])
def test_restore_evidence_uses_source_operation_and_attempt_namespace(
    successor_mode: str,
) -> None:
    context = c07_production_context.parse_production_migration_context(
        _context_payload("a" * 64, successor_mode=successor_mode)
    )
    generation_payload = _bound_generation_payload(context)

    c07_production_restore._validate_restore_evidence(
        _restore_evidence_payload(context),
        context.isolated_restore_evidence_sha256.lower(),
        context=context,
        generation=_validated_generation(context),
        generation_payload=generation_payload,
    )


@pytest.mark.parametrize(
    ("field", "value_factory"),
    [
        ("operation_id", lambda context: context.operation_id),
        (
            "revision_manifest_sha256",
            lambda context: context.revision_manifest_sha256,
        ),
        (
            "restore_database",
            lambda context: c07_production_restore._restore_database_name(
                operation_id=context.operation_id,
                create_attempt_id=_RESTORE_CREATE_ATTEMPT_ID,
            ),
        ),
    ],
)
def test_forward_repair_restore_rejects_current_authority_substitution(
    field: str,
    value_factory,
) -> None:
    context = c07_production_context.parse_production_migration_context(
        _context_payload("a" * 64, successor_mode="forward_repair")
    )
    payload = _restore_evidence_payload(context)
    payload[field] = value_factory(context)

    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="does not bind the READY generation",
    ):
        c07_production_restore._validate_restore_evidence(
            payload,
            context.isolated_restore_evidence_sha256.lower(),
            context=context,
            generation=_validated_generation(context),
            generation_payload=_bound_generation_payload(context),
        )


def test_restore_rejects_legacy_operation_only_database_name() -> None:
    context = c07_production_context.parse_production_migration_context(_context_payload("a" * 64))
    payload = _restore_evidence_payload(context)
    payload["restore_database"] = "ticketbox_c07_restore_" + context.operation_id.replace("-", "")

    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="does not bind the READY generation",
    ):
        c07_production_restore._validate_restore_evidence(
            payload,
            context.isolated_restore_evidence_sha256.lower(),
            context=context,
            generation=_validated_generation(context),
            generation_payload=_bound_generation_payload(context),
        )


def test_context_freezes_canonical_upload_root_binding() -> None:
    context = c07_production_context.parse_production_migration_context(_context_payload("a" * 64))
    assert context.upload_root_binding_sha256 == "a" * 64


@pytest.mark.parametrize("mutation", ["missing", "extra", "uppercase", "type"])
def test_context_upload_root_binding_is_exact_and_lowercase(mutation: str) -> None:
    payload = _context_payload("a" * 64)
    if mutation == "missing":
        payload.pop("upload_root_binding_sha256")
    elif mutation == "extra":
        payload["unexpected"] = True
    elif mutation == "uppercase":
        payload["upload_root_binding_sha256"] = "A" * 64
    else:
        payload["upload_root_binding_sha256"] = 7
    with pytest.raises(c07_contract_types.C07ProductionMigrationError):
        c07_production_context.parse_production_migration_context(payload)


@pytest.mark.parametrize(
    "schema",
    [
        c07_contract_types.RECOVERY_GENERATION_SCHEMA,
        c07_contract_types.TARGET_RECOVERY_GENERATION_SCHEMA,
    ],
)
def test_source_and_target_manifests_bind_to_context_upload_root(schema: str) -> None:
    context = c07_production_context.parse_production_migration_context(_context_payload("a" * 64))
    payload = _generation_payload("a" * 64)
    payload["schema"] = schema
    assert (
        c07_production_recovery.validate_recovery_generation_upload_root_binding(
            payload,
            context=context,
        )
        == "a" * 64
    )


@pytest.mark.parametrize(
    "schema",
    [
        c07_contract_types.RECOVERY_GENERATION_SCHEMA,
        c07_contract_types.TARGET_RECOVERY_GENERATION_SCHEMA,
    ],
)
def test_different_valid_upload_root_digest_is_rejected(schema: str) -> None:
    context = c07_production_context.parse_production_migration_context(_context_payload("a" * 64))
    payload = _generation_payload("b" * 64)
    payload["schema"] = schema
    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="upload-root authority/binding is invalid",
    ):
        c07_production_recovery.validate_recovery_generation_upload_root_binding(
            payload,
            context=context,
        )


@pytest.mark.parametrize(
    ("schema", "mutation"),
    [
        (schema, mutation)
        for schema in (
            c07_contract_types.RECOVERY_GENERATION_SCHEMA,
            c07_contract_types.TARGET_RECOVERY_GENERATION_SCHEMA,
        )
        for mutation in ("missing", "extra", "uppercase", "type")
    ],
)
def test_source_and_target_manifest_integrity_is_exact(
    schema: str,
    mutation: str,
) -> None:
    context = c07_production_context.parse_production_migration_context(_context_payload("a" * 64))
    payload = _generation_payload("a" * 64)
    payload["schema"] = schema
    integrity = payload["integrity"]
    assert isinstance(integrity, dict)
    if mutation == "missing":
        integrity.pop("upload_root_binding_sha256")
    elif mutation == "extra":
        integrity["unexpected"] = True
    elif mutation == "uppercase":
        integrity["upload_root_binding_sha256"] = "A" * 64
    else:
        integrity["upload_root_binding_sha256"] = 7
    with pytest.raises(c07_contract_types.C07ProductionMigrationError):
        c07_production_recovery.validate_recovery_generation_upload_root_binding(
            payload,
            context=context,
        )


def test_v3_generation_requires_exact_upload_root_binding_field() -> None:
    for mutation in ("missing", "extra"):
        payload = _generation_payload("a" * 64)
        integrity = payload["integrity"]
        assert isinstance(integrity, dict)
        if mutation == "missing":
            integrity.pop("upload_root_binding_sha256")
        else:
            integrity["unexpected"] = True
        with pytest.raises(
            c07_contract_types.C07ProductionMigrationError,
            match="recovery integrity does not match its frozen field set",
        ):
            c07_production_recovery._generation_sections(payload)


def test_v3_generation_accepts_canonical_lowercase_upload_root_binding() -> None:
    sections = c07_production_recovery._generation_sections(_generation_payload("a" * 64))
    assert c07_production_recovery._upload_root_binding_sha256(sections) == "a" * 64


@pytest.mark.parametrize("binding", ["A" * 64, "0" * 64, "a" * 63, 7])
def test_v3_generation_rejects_noncanonical_upload_root_binding(
    binding: object,
) -> None:
    sections = c07_production_recovery._generation_sections(_generation_payload(binding))
    with pytest.raises(
        c07_contract_types.C07ProductionMigrationError,
        match="recovery configured upload-root binding",
    ):
        c07_production_recovery._upload_root_binding_sha256(sections)
