"""Primitive strict contracts for the C07 production migration.

The Windows lifecycle coordinator owns writer fencing, recovery generation,
isolated restore, role provisioning, readiness, and the durable host receipt.
This module consumes the coordinator's frozen migration context and performs
only the transactional Alembic upgrade plus target-shape verification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

PRODUCTION_MIGRATION_CONTEXT_SCHEMA = "ticketbox-c07-production-migration-context-v5"
PRODUCTION_MIGRATION_EVIDENCE_SCHEMA = "ticketbox-c07-migration-evidence-v1"
HOST_ENVELOPE_SCHEMA = "ticketbox-c07-host-envelope-v2"
FREEZE_PROOF_SCHEMA = "ticketbox-c07-writers-frozen-proof-v5"
RECOVERY_ENVELOPE_SCHEMA = "ticketbox-c07-recovery-envelope-v1"
RECOVERY_GENERATION_SCHEMA = "ticketbox-c07-recovery-generation-v3"
TARGET_RECOVERY_GENERATION_SCHEMA = "ticketbox-c07-target-recovery-generation-v2"
ISOLATED_RESTORE_EVIDENCE_SCHEMA = "ticketbox-c07-isolated-restore-evidence-v2"
RECOVERY_INTEGRITY_SCOPE = "acl_hash_only"
DATABASE_AUTHORITY_SCHEMA = "ticketbox-c07-live-database-authority-v1"

MIGRATOR_ROLE = "ticketbox_migrator"
SCHEMA_OWNER_ROLE = "ticketbox_owner"
DATABASE_NAME = "ticketbox"
MAX_CONTEXT_BYTES = 64 * 1024
MAX_AUTHORITY_ARTIFACT_BYTES = 1024 * 1024
MAINTENANCE_WINDOW_SECONDS = 20 * 60
C07_SOURCE_REVISION = "20260722_0001"
C07_TARGET_REVISION = "20260729_0001"
C07_CEREMONY_MODE_GUC = "ticketbox.c07_ceremony_mode"
C07_CEREMONY_ID_GUC = "ticketbox.c07_ceremony_id"
C07_STATEMENT_TIMEOUT_GUC = "ticketbox.c07_statement_timeout_ms"
C07_MIGRATION_HELPER_RELATIVE_PATH = "ticketbox-c07-migrator.exe"

_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CANONICAL_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_UNSIGNED_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")

_CONTEXT_FIELDS = (
    "schema",
    "operation_id",
    "release_fingerprint",
    "migration_helper_relative_path",
    "migration_helper_size",
    "migration_helper_sha256",
    "database_binding_sha256",
    "upload_root_binding_sha256",
    "recovery_epoch_id",
    "coordinator_binding_sha256",
    "coordinator_binding_sequence",
    "heartbeat_sequence",
    "operation_kind",
    "target_alembic_revision",
    "revision_manifest_sha256",
    "successor_mode",
    "successor_intent_sha256",
    "predecessor_operation_id",
    "predecessor_terminal_authority_chain_sha256",
    "source_recovery_operation_id",
    "source_recovery_release_fingerprint",
    "source_recovery_revision_manifest_sha256",
    "source_recovery_freeze_proof_sha256",
    "maintenance_deadline_utc",
    "maintenance_remaining_ceiling_ms",
    "maintenance_authority_sha256",
    "writer_freeze_proof_path",
    "writer_freeze_proof_sha256",
    "recovery_manifest_path",
    "recovery_manifest_sha256",
    "isolated_restore_evidence_path",
    "isolated_restore_evidence_sha256",
    "lifecycle_root_authority_chain_sha256",
)
_HOST_ENVELOPE_FIELDS = frozenset({"schema", "artifact_kind", "payload_sha256", "payload_json"})
_FREEZE_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "descriptor_sha256",
        "operation_kind",
        "target_alembic_revision",
        "revision_manifest_sha256",
        "release_fingerprint",
        "database_binding_sha256",
        "recovery_epoch_id",
        "writer_fence_intent_sha256",
        "coordinator_binding_sha256",
        "coordinator_pid",
        "coordinator_started_filetime_high",
        "coordinator_started_filetime_low",
        "lifecycle_owner_pid",
        "lifecycle_owner_started_filetime_high",
        "lifecycle_owner_started_filetime_low",
        "heartbeat_sequence",
        "backend_service_state",
        "backend_service_start_policy",
        "backend_service_pid",
        "backend_listener_pid_count",
        "runtime_process_count",
        "database_client_session_count",
        "database_client_sessions",
        "database_public_connect",
        "database_role_capability_count",
        "database_role_capabilities",
        "database_authority_role",
        "database_authority_scope",
        "database_max_prepared_transactions",
        "database_prepared_transaction_count",
        "database_logical_subscription_count",
        "database_logical_apply_worker_count",
        "database_unexpected_worker_count",
        "database_advisory_fence_available",
        "writers_frozen_at_utc",
    }
)
_RECOVERY_ENVELOPE_FIELDS = frozenset({"schema", "payload_sha256", "payload_base64"})
_GENERATION_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "generation_id",
        "release",
        "lifecycle",
        "integrity",
        "barrier",
        "database",
        "asset_inventory",
        "original_copies",
        "thumbnail_policy",
        "capacity",
        "completion",
    }
)
_GENERATION_INTEGRITY_FIELDS = frozenset({"scope", "malicious_writer_resistance", "upload_root_binding_sha256"})
_GENERATION_RELEASE_FIELDS = frozenset(
    {
        "fingerprint",
        "installation_id",
        "build_manifest_sha256",
        "backend_version",
    }
)
_GENERATION_LIFECYCLE_FIELDS = frozenset(
    {
        "stage",
        "operation_kind",
        "target_alembic_revision",
        "revision_manifest_sha256",
        "authority_chain_sha256",
        "freeze_proof_sha256",
        "freeze_heartbeat_sequence",
    }
)
_GENERATION_DATABASE_FIELDS = frozenset(
    {
        "name",
        "cluster_system_identifier",
        "source_database_oid",
        "server_version_num",
        "server_id",
        "data_generation",
        "alembic_heads",
        "dump_file",
        "dump_sha256",
        "dump_size_bytes",
        "restore_list_sha256",
        "money_facts_sha256",
    }
)
_RESTORE_EVIDENCE_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "operation_kind",
        "target_alembic_revision",
        "revision_manifest_sha256",
        "installation_id",
        "generation_payload_sha256",
        "source_cluster_system_identifier",
        "source_database_oid",
        "restore_database",
        "restore_database_oid",
        "restore_create_attempt_id",
        "restore_create_authority_sha256",
        "logical_server_id",
        "logical_data_generation",
        "asset_inventory_sha256",
        "asset_inventory_rows",
        "original_copies_verified",
        "isolated_asset_bytes",
        "thumbnails",
        "forward_replay_source_revision",
        "forward_replay_target_revision",
        "forward_replay_result",
        "target_shape_sha256",
        "money_facts_sha256",
        "result",
        "integrity_scope",
        "verified_at_utc",
    }
)


class C07ProductionMigrationError(RuntimeError):
    """The production migration action cannot safely execute."""


@dataclass(frozen=True)
class ProductionMigrationContext:
    operation_id: str
    release_fingerprint: str
    migration_helper_relative_path: str
    migration_helper_size: int
    migration_helper_sha256: str
    database_binding_sha256: str
    upload_root_binding_sha256: str
    recovery_epoch_id: str
    coordinator_binding_sha256: str
    coordinator_binding_sequence: int
    heartbeat_sequence: int
    operation_kind: str
    target_alembic_revision: str
    revision_manifest_sha256: str
    successor_mode: str
    successor_intent_sha256: str
    predecessor_operation_id: str
    predecessor_terminal_authority_chain_sha256: str
    source_recovery_operation_id: str
    source_recovery_release_fingerprint: str
    source_recovery_revision_manifest_sha256: str
    source_recovery_freeze_proof_sha256: str
    maintenance_deadline_utc: datetime
    maintenance_remaining_ceiling_ms: int
    maintenance_authority_sha256: str
    writer_freeze_proof_path: Path
    writer_freeze_proof_sha256: str
    recovery_manifest_path: Path
    recovery_manifest_sha256: str
    isolated_restore_evidence_path: Path
    isolated_restore_evidence_sha256: str
    lifecycle_root_authority_chain_sha256: str


@dataclass(frozen=True)
class ValidatedProductionArtifacts:
    installation_id: str
    cluster_system_identifier: str
    database_oid: str
    logical_server_id: str
    logical_data_generation: str
    generation_payload_sha256: str
    money_facts_sha256: str


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _parse_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        text_value = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text_value,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise C07ProductionMigrationError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise C07ProductionMigrationError(f"{label} must be a JSON object")
    return value


def _require_exact_fields(
    value: object,
    expected: frozenset[str] | tuple[str, ...],
    *,
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise C07ProductionMigrationError(f"{label} does not match its frozen field set")
    return value


def _require_string(
    value: object,
    *,
    label: str,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise C07ProductionMigrationError(f"{label} must be a string")
    return value


def _require_exact_string(
    value: object,
    *,
    expected: str,
    label: str,
) -> str:
    parsed = _require_string(value, label=label)
    if parsed != expected:
        raise C07ProductionMigrationError(f"{label} does not match the frozen release contract")
    return parsed


def _require_int(
    value: object,
    *,
    label: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise C07ProductionMigrationError(f"{label} is outside its bounds")
    return value


def _require_bool(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise C07ProductionMigrationError(f"{label} must be boolean")
    return value


def _require_upper_sha(value: object, *, label: str) -> str:
    text_value = _require_string(value, label=label)
    if _UPPER_SHA256.fullmatch(text_value) is None or text_value == ("0" * 64):
        raise C07ProductionMigrationError(f"{label} must be canonical non-zero uppercase SHA-256")
    return text_value


def _require_lower_sha(value: object, *, label: str) -> str:
    text_value = _require_string(value, label=label)
    if _LOWER_SHA256.fullmatch(text_value) is None or text_value == ("0" * 64):
        raise C07ProductionMigrationError(f"{label} must be canonical non-zero lowercase SHA-256")
    return text_value


def _require_uuid(value: object, *, label: str) -> str:
    text_value = _require_string(value, label=label)
    if _CANONICAL_UUID.fullmatch(text_value) is None:
        raise C07ProductionMigrationError(f"{label} must be a canonical lowercase UUID")
    try:
        parsed = UUID(text_value)
    except ValueError as exc:
        raise C07ProductionMigrationError(f"{label} is not a UUID") from exc
    if parsed.int == 0 or str(parsed) != text_value:
        raise C07ProductionMigrationError(f"{label} must be a canonical non-zero UUID")
    return text_value


def _require_decimal_string(
    value: object,
    *,
    label: str,
    minimum: int = 0,
    maximum: int = (2**64) - 1,
) -> int:
    text_value = _require_string(value, label=label)
    if _UNSIGNED_DECIMAL.fullmatch(text_value) is None:
        raise C07ProductionMigrationError(f"{label} must be a canonical unsigned decimal")
    parsed = int(text_value)
    if not minimum <= parsed <= maximum:
        raise C07ProductionMigrationError(f"{label} is outside its bounds")
    return parsed


def _require_utc(value: object, *, label: str) -> datetime:
    text_value = _require_string(value, label=label)
    if not text_value.endswith("Z"):
        raise C07ProductionMigrationError(f"{label} must use canonical UTC Z notation")
    try:
        parsed = datetime.fromisoformat(text_value[:-1] + "+00:00")
    except ValueError as exc:
        raise C07ProductionMigrationError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo != UTC:
        raise C07ProductionMigrationError(f"{label} must be UTC")
    return parsed


def _require_absolute_path(value: object, *, label: str) -> Path:
    text_value = _require_string(value, label=label)
    if "\x00" in text_value:
        raise C07ProductionMigrationError(f"{label} contains NUL")
    path = Path(text_value)
    if not path.is_absolute():
        raise C07ProductionMigrationError(f"{label} must be absolute")
    return path
