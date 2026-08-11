"""Canonical decoding of the frozen C07 production migration context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.database._c07_production_contract_types import (
    _CONTEXT_FIELDS,
    C07_MIGRATION_HELPER_RELATIVE_PATH,
    C07_TARGET_REVISION,
    MAINTENANCE_WINDOW_SECONDS,
    MAX_CONTEXT_BYTES,
    PRODUCTION_MIGRATION_CONTEXT_SCHEMA,
    C07ProductionMigrationError,
    ProductionMigrationContext,
    _parse_json_object,
    _require_absolute_path,
    _require_exact_string,
    _require_int,
    _require_lower_sha,
    _require_operation_id,
    _require_string,
    _require_upper_sha,
    _require_utc,
    _require_uuid,
)

_SUCCESSOR_MODES = frozenset({"", "pre_ddl", "forward_repair"})


def _optional_operation_id(value: object, *, label: str) -> str:
    text = _require_string(value, label=label, allow_empty=True)
    if not text:
        return ""
    return _require_operation_id(text, label=label)


def _optional_upper_sha(value: object, *, label: str) -> str:
    text = _require_string(value, label=label, allow_empty=True)
    if not text:
        return ""
    return _require_upper_sha(text, label=label)


def _identity_fields(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "operation_id": _require_operation_id(
            payload.get("operation_id"), label="context operation_id"
        ),
        "release_fingerprint": _require_upper_sha(
            payload.get("release_fingerprint"), label="context release_fingerprint"
        ),
        "migration_helper_relative_path": _require_exact_string(
            payload.get("migration_helper_relative_path"),
            expected=C07_MIGRATION_HELPER_RELATIVE_PATH,
            label="context migration_helper_relative_path",
        ),
        "migration_helper_size": _require_int(
            payload.get("migration_helper_size"), label="context migration_helper_size", minimum=1
        ),
        "migration_helper_sha256": _require_upper_sha(
            payload.get("migration_helper_sha256"), label="context migration_helper_sha256"
        ),
        "database_binding_sha256": _require_upper_sha(
            payload.get("database_binding_sha256"), label="context database_binding_sha256"
        ),
        "upload_root_binding_sha256": _require_lower_sha(
            payload.get("upload_root_binding_sha256"),
            label="context upload_root_binding_sha256",
        ),
        "recovery_epoch_id": _require_uuid(payload.get("recovery_epoch_id"), label="context recovery_epoch_id"),
        "coordinator_binding_sha256": _require_upper_sha(
            payload.get("coordinator_binding_sha256"), label="context coordinator_binding_sha256"
        ),
        "coordinator_binding_sequence": _require_int(
            payload.get("coordinator_binding_sequence"), label="context coordinator_binding_sequence", minimum=1
        ),
        "heartbeat_sequence": _require_int(
            payload.get("heartbeat_sequence"), label="context heartbeat_sequence", minimum=1
        ),
    }


def _lifecycle_fields(payload: Mapping[str, object]) -> dict[str, object]:
    successor_mode = _require_string(
        payload.get("successor_mode"),
        label="context successor_mode",
        allow_empty=True,
    )
    if successor_mode not in _SUCCESSOR_MODES:
        raise C07ProductionMigrationError("context successor_mode is outside the frozen lifecycle contract")
    successor_intent_sha256 = _optional_upper_sha(
        payload.get("successor_intent_sha256"),
        label="context successor_intent_sha256",
    )
    predecessor_operation_id = _optional_operation_id(
        payload.get("predecessor_operation_id"),
        label="context predecessor_operation_id",
    )
    predecessor_terminal_authority_chain_sha256 = _optional_upper_sha(
        payload.get("predecessor_terminal_authority_chain_sha256"),
        label="context predecessor_terminal_authority_chain_sha256",
    )
    return {
        "operation_kind": _require_exact_string(
            payload.get("operation_kind"),
            expected="c07_money_minor_bigint_v1",
            label="context operation_kind",
        ),
        "target_alembic_revision": _require_exact_string(
            payload.get("target_alembic_revision"),
            expected=C07_TARGET_REVISION,
            label="context target_alembic_revision",
        ),
        "revision_manifest_sha256": _require_upper_sha(
            payload.get("revision_manifest_sha256"), label="context revision_manifest_sha256"
        ),
        "successor_mode": successor_mode,
        "successor_intent_sha256": successor_intent_sha256,
        "predecessor_operation_id": predecessor_operation_id,
        "predecessor_terminal_authority_chain_sha256": predecessor_terminal_authority_chain_sha256,
        "maintenance_deadline_utc": _require_utc(
            payload.get("maintenance_deadline_utc"), label="context maintenance_deadline_utc"
        ),
        "maintenance_remaining_ceiling_ms": _require_int(
            payload.get("maintenance_remaining_ceiling_ms"),
            label="context maintenance_remaining_ceiling_ms",
            minimum=1,
            maximum=MAINTENANCE_WINDOW_SECONDS * 1000,
        ),
        "maintenance_authority_sha256": _require_upper_sha(
            payload.get("maintenance_authority_sha256"), label="context maintenance_authority_sha256"
        ),
    }


def _source_recovery_fields(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "source_recovery_operation_id": _require_operation_id(
            payload.get("source_recovery_operation_id"),
            label="context source_recovery_operation_id",
        ),
        "source_recovery_release_fingerprint": _require_upper_sha(
            payload.get("source_recovery_release_fingerprint"),
            label="context source_recovery_release_fingerprint",
        ),
        "source_recovery_revision_manifest_sha256": _require_upper_sha(
            payload.get("source_recovery_revision_manifest_sha256"),
            label="context source_recovery_revision_manifest_sha256",
        ),
        "source_recovery_freeze_proof_sha256": _require_upper_sha(
            payload.get("source_recovery_freeze_proof_sha256"),
            label="context source_recovery_freeze_proof_sha256",
        ),
    }


def _artifact_fields(payload: Mapping[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name in (
        "writer_freeze_proof",
        "recovery_manifest",
        "isolated_restore_evidence",
    ):
        fields[f"{name}_path"] = _require_absolute_path(
            payload.get(f"{name}_path"),
            label=f"context {name}_path",
        )
        fields[f"{name}_sha256"] = _require_upper_sha(
            payload.get(f"{name}_sha256"),
            label=f"context {name}_sha256",
        )
    fields["lifecycle_root_authority_chain_sha256"] = _require_upper_sha(
        payload.get("lifecycle_root_authority_chain_sha256"),
        label="context lifecycle_root_authority_chain_sha256",
    )
    return fields


def _validate_lineage(
    *,
    identity: Mapping[str, object],
    lifecycle: Mapping[str, object],
    source_recovery: Mapping[str, object],
    artifacts: Mapping[str, object],
) -> None:
    successor_mode = lifecycle["successor_mode"]
    successor_fields = (
        lifecycle["successor_intent_sha256"],
        lifecycle["predecessor_operation_id"],
        lifecycle["predecessor_terminal_authority_chain_sha256"],
    )
    if successor_mode == "":
        if any(successor_fields):
            raise C07ProductionMigrationError("base C07 context cannot carry successor/predecessor authority")
    elif not all(successor_fields):
        raise C07ProductionMigrationError("successor C07 context requires exact predecessor authority")

    operation_id = identity["operation_id"]
    predecessor_operation_id = lifecycle["predecessor_operation_id"]
    if predecessor_operation_id and predecessor_operation_id == operation_id:
        raise C07ProductionMigrationError("successor C07 context cannot name itself as predecessor")

    current_recovery_binding = (
        operation_id,
        identity["release_fingerprint"],
        lifecycle["revision_manifest_sha256"],
        artifacts["writer_freeze_proof_sha256"],
    )
    source_recovery_binding = (
        source_recovery["source_recovery_operation_id"],
        source_recovery["source_recovery_release_fingerprint"],
        source_recovery["source_recovery_revision_manifest_sha256"],
        source_recovery["source_recovery_freeze_proof_sha256"],
    )
    if successor_mode == "forward_repair":
        if source_recovery["source_recovery_operation_id"] != predecessor_operation_id:
            raise C07ProductionMigrationError("forward-repair recovery must bind the predecessor operation")
    elif source_recovery_binding != current_recovery_binding:
        raise C07ProductionMigrationError("base/pre-DDL recovery must bind the current operation")


def parse_production_migration_context(
    payload: Mapping[str, object],
) -> ProductionMigrationContext:
    """Parse the lifecycle coordinator's exact frozen migration context."""

    if not isinstance(payload, dict) or tuple(payload) != _CONTEXT_FIELDS:
        raise C07ProductionMigrationError("production migration context fields/order are not exact")
    if payload.get("schema") != PRODUCTION_MIGRATION_CONTEXT_SCHEMA:
        raise C07ProductionMigrationError("production migration context schema is unsupported")
    identity = _identity_fields(payload)
    lifecycle = _lifecycle_fields(payload)
    source_recovery = _source_recovery_fields(payload)
    artifacts = _artifact_fields(payload)
    _validate_lineage(
        identity=identity,
        lifecycle=lifecycle,
        source_recovery=source_recovery,
        artifacts=artifacts,
    )
    return ProductionMigrationContext(
        **identity,
        **lifecycle,
        **source_recovery,
        **artifacts,
    )


def parse_production_migration_context_bytes(raw: bytes) -> ProductionMigrationContext:
    if (
        not 0 < len(raw) <= MAX_CONTEXT_BYTES
        or raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in raw
        or b"\n" in raw
        or not raw.startswith(b"{")
        or not raw.endswith(b"}")
    ):
        raise C07ProductionMigrationError("production migration context encoding is not exact")
    return parse_production_migration_context(_parse_json_object(raw, label="production migration context"))


def read_production_migration_context(source: Any) -> ProductionMigrationContext:
    raw = source.read(MAX_CONTEXT_BYTES + 1)
    if not isinstance(raw, bytes):
        raise C07ProductionMigrationError("production migration context input must be binary")
    return parse_production_migration_context_bytes(raw)
