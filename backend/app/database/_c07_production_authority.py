"""Host authority envelopes and writer-freeze validation for C07 production."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import PureWindowsPath

from app.database._c07_production_contract import (
    _FREEZE_FIELDS,
    _HOST_ENVELOPE_FIELDS,
    _RECOVERY_ENVELOPE_FIELDS,
    FREEZE_PROOF_SCHEMA,
    HOST_ENVELOPE_SCHEMA,
    MAX_AUTHORITY_ARTIFACT_BYTES,
    RECOVERY_ENVELOPE_SCHEMA,
    C07ProductionMigrationError,
    ProductionMigrationContext,
    _parse_json_object,
    _require_bool,
    _require_exact_fields,
    _require_int,
    _require_lower_sha,
    _require_operation_id,
    _require_string,
    _require_upper_sha,
    _require_utc,
    _require_uuid,
)

_ROLE_CAPABILITY_FIELDS = frozenset(
    {
        "name",
        "oid",
        "disposition",
        "can_login",
        "connection_limit",
        "is_superuser",
        "can_create_db",
        "can_create_role",
        "can_replicate",
        "can_bypass_rls",
        "is_database_owner",
        "owns_public_schema",
        "owns_user_relations",
        "direct_connect",
        "effective_connect",
        "can_database_create",
        "can_public_schema_create",
        "can_table_write",
        "can_sequence_write",
        "can_assume_write_owner",
    }
)
_ROLE_BOOL_FIELDS = _ROLE_CAPABILITY_FIELDS - {
    "name",
    "oid",
    "disposition",
    "connection_limit",
}
_ROLE_ELEVATED_FIELDS = {
    "is_superuser",
    "can_create_db",
    "can_create_role",
    "can_replicate",
    "can_bypass_rls",
}


def _validate_artifact_encoding(raw: bytes, *, label: str) -> bytes:
    if (
        not 0 < len(raw) <= MAX_AUTHORITY_ARTIFACT_BYTES
        or raw.startswith(b"\xef\xbb\xbf")
        or not raw.endswith(b"\n")
        or raw.endswith(b"\n\n")
        or b"\r" in raw
    ):
        raise C07ProductionMigrationError(f"{label} encoding is not canonical UTF-8 plus one LF")
    return raw[:-1]


def _parse_host_envelope(
    raw: bytes,
    *,
    expected_kind: str,
) -> tuple[dict[str, object], str]:
    body = _validate_artifact_encoding(raw, label=expected_kind)
    envelope = _require_exact_fields(
        _parse_json_object(body, label=f"{expected_kind} envelope"),
        _HOST_ENVELOPE_FIELDS,
        label=f"{expected_kind} envelope",
    )
    if envelope.get("schema") != HOST_ENVELOPE_SCHEMA or envelope.get("artifact_kind") != expected_kind:
        raise C07ProductionMigrationError(f"{expected_kind} host envelope is unsupported")
    declared = _require_upper_sha(
        envelope.get("payload_sha256"),
        label=f"{expected_kind} payload_sha256",
    )
    payload_json = _require_string(
        envelope.get("payload_json"),
        label=f"{expected_kind} payload_json",
    )
    if (
        not payload_json.startswith("{")
        or not payload_json.endswith("}")
        or "\r" in payload_json
        or "\n" in payload_json
        or hashlib.sha256(payload_json.encode("utf-8")).hexdigest().upper() != declared
    ):
        raise C07ProductionMigrationError(f"{expected_kind} payload digest/encoding is invalid")
    payload = _parse_json_object(
        payload_json.encode("utf-8"),
        label=f"{expected_kind} payload",
    )
    return payload, declared


def _parse_recovery_envelope(
    raw: bytes,
    *,
    label: str,
) -> tuple[dict[str, object], str]:
    body = _validate_artifact_encoding(raw, label=label)
    envelope = _require_exact_fields(
        _parse_json_object(body, label=f"{label} envelope"),
        _RECOVERY_ENVELOPE_FIELDS,
        label=f"{label} envelope",
    )
    if envelope.get("schema") != RECOVERY_ENVELOPE_SCHEMA:
        raise C07ProductionMigrationError(f"{label} recovery envelope is unsupported")
    declared = _require_lower_sha(
        envelope.get("payload_sha256"),
        label=f"{label} payload_sha256",
    )
    payload_base64 = _require_string(
        envelope.get("payload_base64"),
        label=f"{label} payload_base64",
    )
    try:
        payload_bytes = base64.b64decode(payload_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise C07ProductionMigrationError(f"{label} payload is not canonical base64") from exc
    if (
        not payload_bytes
        or len(payload_bytes) > MAX_AUTHORITY_ARTIFACT_BYTES
        or base64.b64encode(payload_bytes).decode("ascii") != payload_base64
        or hashlib.sha256(payload_bytes).hexdigest() != declared
    ):
        raise C07ProductionMigrationError(f"{label} payload digest/base64 is invalid")
    return _parse_json_object(payload_bytes, label=f"{label} payload"), declared


def _validate_artifact_paths(
    context: ProductionMigrationContext,
) -> int:
    freeze = context.writer_freeze_proof_path
    manifest = context.recovery_manifest_path
    restore = context.isolated_restore_evidence_path
    freeze_match = re.fullmatch(
        (
            rf"operation-{re.escape(context.operation_id)}-freeze-proof"
            r"(?:-binding-([1-9][0-9]*))?\.json"
        ),
        freeze.name,
    )
    if freeze_match is None or freeze.parent.name != "c07-lifecycle":
        raise C07ProductionMigrationError("writer-freeze proof path is outside its frozen host layout")
    binding_sequence = 0 if freeze_match.group(1) is None else int(freeze_match.group(1))
    generation_root = manifest.parent
    if (
        manifest.name != "manifest.json"
        or generation_root.name != f"operation-{context.source_recovery_operation_id}.ready"
        or generation_root.parent.name != "recovery-generations"
        or restore.name != "isolated-restore-evidence.json"
        or not _same_path(restore.parent, generation_root)
        or not _same_path(generation_root.parent.parent, freeze.parent)
    ):
        raise C07ProductionMigrationError("recovery artifacts are outside the operation READY layout")
    if binding_sequence > context.coordinator_binding_sequence:
        raise C07ProductionMigrationError("writer-freeze binding is newer than the migration context")
    return binding_sequence


def _same_path(left: PureWindowsPath, right: PureWindowsPath) -> bool:
    return left == right


def _validate_freeze_payload(
    payload: dict[str, object],
    declared_sha256: str,
    *,
    context: ProductionMigrationContext,
    freeze_binding_sequence: int,
) -> None:
    _require_exact_fields(payload, _FREEZE_FIELDS, label="writer-freeze payload")
    heartbeat = _validate_freeze_field_shapes(payload)
    _validate_freeze_binding(
        payload,
        declared_sha256=declared_sha256,
        context=context,
        heartbeat=heartbeat,
        freeze_binding_sequence=freeze_binding_sequence,
    )


def _validate_freeze_role_disposition(
    item: dict[str, object],
    *,
    role_name: str,
    disposition: str,
) -> None:
    elevated = any(item.get(field) is True for field in _ROLE_ELEVATED_FIELDS)
    error: str | None = None
    if disposition == "database_authority" and (
        role_name != "postgres" or item.get("can_login") is not True or item.get("is_superuser") is not True
    ):
        error = "writer-freeze database authority role is invalid"
    if disposition == "migration_authority" and (
        role_name != "ticketbox_migrator" or item.get("can_login") is not True or elevated
    ):
        error = "writer-freeze migration authority role is invalid"
    if disposition == "nologin_owner" and (
        role_name != "ticketbox_owner" or item.get("can_login") is not False or elevated
    ):
        error = "writer-freeze no-login owner role is invalid"
    if disposition == "fenced_runtime" and (
        role_name not in {"ticketbox", "ticketbox_runtime"}
        or item.get("can_login") is not False
        or item.get("connection_limit") != 0
        or item.get("direct_connect") is not False
        or (item.get("effective_connect") is True and item.get("is_database_owner") is not True)
        or elevated
    ):
        error = "writer-freeze runtime role is not durably fenced"
    if disposition == "inert_unregistered" and any(item.get(field) is True for field in _ROLE_BOOL_FIELDS):
        error = "writer-freeze contains an unregistered effective writer"
    if error is not None:
        raise C07ProductionMigrationError(error)


def _validate_freeze_role_capability(
    role: object,
    *,
    role_names: set[str],
    role_oids: set[int],
) -> str:
    item = _require_exact_fields(
        role,
        _ROLE_CAPABILITY_FIELDS,
        label="writer-freeze role capability",
    )
    role_name = _require_string(
        item.get("name"),
        label="writer-freeze role name",
    )
    role_oid = _require_int(
        item.get("oid"),
        label="writer-freeze role oid",
        minimum=1,
    )
    if len(role_name) > 63 or role_name in role_names or role_oid in role_oids:
        raise C07ProductionMigrationError("writer-freeze role identity set is invalid")
    role_names.add(role_name)
    role_oids.add(role_oid)
    _require_int(
        item.get("connection_limit"),
        label="writer-freeze role connection_limit",
        minimum=-1,
    )
    disposition = _require_string(
        item.get("disposition"),
        label="writer-freeze role disposition",
    )
    if disposition not in {
        "database_authority",
        "migration_authority",
        "nologin_owner",
        "fenced_runtime",
        "inert_unregistered",
    }:
        raise C07ProductionMigrationError("writer-freeze role disposition is unsupported")
    for field in _ROLE_BOOL_FIELDS:
        _require_bool(item.get(field), label=f"writer-freeze role {field}")
    _validate_freeze_role_disposition(
        item,
        role_name=role_name,
        disposition=disposition,
    )
    return disposition


def _validate_freeze_role_set(roles: list[object], *, role_count: int) -> None:
    if len(roles) != role_count:
        raise C07ProductionMigrationError("writer-freeze role capability set/count mismatch")
    dispositions: list[str] = []
    role_names: set[str] = set()
    role_oids: set[int] = set()
    for role in roles:
        dispositions.append(
            _validate_freeze_role_capability(
                role,
                role_names=role_names,
                role_oids=role_oids,
            )
        )
    if dispositions.count("database_authority") != 1 or (dispositions.count("fenced_runtime") < 1):
        raise C07ProductionMigrationError("writer-freeze role authority set is incomplete")


def _validate_freeze_field_shapes(payload: dict[str, object]) -> int:
    host_sha_fields = (
        "descriptor_sha256",
        "release_fingerprint",
        "database_binding_sha256",
        "writer_fence_intent_sha256",
        "coordinator_binding_sha256",
        "revision_manifest_sha256",
    )
    for field in host_sha_fields:
        _require_upper_sha(payload.get(field), label=f"writer-freeze {field}")
    heartbeat = _require_int(
        payload.get("heartbeat_sequence"),
        label="writer-freeze heartbeat_sequence",
        minimum=1,
    )
    for field in ("coordinator_pid", "lifecycle_owner_pid"):
        _require_int(payload.get(field), label=f"writer-freeze {field}", minimum=1)
    role_count = _require_int(
        payload.get("database_role_capability_count"),
        label="writer-freeze database_role_capability_count",
        minimum=2,
        maximum=128,
    )
    for field in (
        "coordinator_started_filetime_high",
        "coordinator_started_filetime_low",
        "lifecycle_owner_started_filetime_high",
        "lifecycle_owner_started_filetime_low",
    ):
        _require_int(
            payload.get(field),
            label=f"writer-freeze {field}",
            maximum=(2**32) - 1,
        )
    for field in (
        "backend_service_pid",
        "backend_listener_pid_count",
        "runtime_process_count",
        "database_client_session_count",
        "database_max_prepared_transactions",
        "database_prepared_transaction_count",
        "database_logical_subscription_count",
        "database_logical_apply_worker_count",
        "database_unexpected_worker_count",
    ):
        if _require_int(payload.get(field), label=f"writer-freeze {field}") != 0:
            raise C07ProductionMigrationError(f"writer-freeze {field} must be zero")
    if payload.get("database_client_sessions") != []:
        raise C07ProductionMigrationError("writer-freeze database_client_sessions must be the measured empty set")
    roles = payload.get("database_role_capabilities")
    if not isinstance(roles, list):
        raise C07ProductionMigrationError("writer-freeze role capability set/count mismatch")
    _validate_freeze_role_set(roles, role_count=role_count)
    return heartbeat


def _validate_freeze_binding(
    payload: dict[str, object],
    *,
    declared_sha256: str,
    context: ProductionMigrationContext,
    heartbeat: int,
    freeze_binding_sequence: int,
) -> None:
    if (
        payload.get("schema") != FREEZE_PROOF_SCHEMA
        or payload.get("operation_id") != context.operation_id
        or payload.get("operation_kind") != context.operation_kind
        or payload.get("target_alembic_revision") != context.target_alembic_revision
        or payload.get("revision_manifest_sha256") != context.revision_manifest_sha256
        or payload.get("release_fingerprint") != context.release_fingerprint
        or payload.get("database_binding_sha256") != context.database_binding_sha256
        or payload.get("recovery_epoch_id") != context.recovery_epoch_id
        or declared_sha256 != context.writer_freeze_proof_sha256
        or heartbeat > context.heartbeat_sequence
        or payload.get("backend_service_state") != "stopped"
        or payload.get("backend_service_start_policy") != "disabled"
        or payload.get("database_authority_role") != "postgres"
        or payload.get("database_authority_scope") != "process_local_secret_same_session_advisory_cut"
        or _require_bool(
            payload.get("database_public_connect"),
            label="writer-freeze database_public_connect",
        )
        or not _require_bool(
            payload.get("database_advisory_fence_available"),
            label="writer-freeze database_advisory_fence_available",
        )
    ):
        raise C07ProductionMigrationError("writer-freeze proof does not bind the stopped production writer")
    _require_operation_id(
        payload.get("operation_id"),
        label="writer-freeze operation_id",
    )
    _require_uuid(
        payload.get("recovery_epoch_id"),
        label="writer-freeze recovery_epoch_id",
    )
    _require_utc(
        payload.get("writers_frozen_at_utc"),
        label="writer-freeze writers_frozen_at_utc",
    )
    if (
        freeze_binding_sequence == context.coordinator_binding_sequence
        and payload.get("coordinator_binding_sha256") != context.coordinator_binding_sha256
    ):
        raise C07ProductionMigrationError("writer-freeze proof does not bind the current coordinator")
