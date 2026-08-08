"""Protected isolated and Windows host evidence parsing for C07."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.database._c07_contract import (
    C07_TARGET_REVISION,
    MAX_FREEZE_WINDOW,
    C07CeremonyError,
    HostFreezeEvidence,
    canonical_uuid,
    parse_utc,
    sha256_bytes,
)
from app.database._c07_host_evidence_helpers import (
    _parse_json_object as _parse_json_object,
)
from app.database._c07_host_evidence_helpers import (
    _read_isolated_host_evidence as _read_isolated_host_evidence,
)
from app.database._c07_host_evidence_helpers import (
    _read_windows_process_identity as _read_windows_process_identity,
)
from app.database._c07_host_evidence_helpers import (
    _required_host_sha as _required_host_sha,
)
from app.database._c07_host_evidence_helpers import (
    _required_int as _required_int,
)
from app.services.secure_file import (
    hold_system_authority_file_for_read,
    windows_process_start_filetime,
)

ISOLATED_FREEZE_SCHEMA = "ticketbox-c07-isolated-freeze-v1"
HOST_ENVELOPE_SCHEMA = "ticketbox-c07-host-envelope-v2"
WINDOWS_FREEZE_SCHEMA = "ticketbox-c07-writers-frozen-proof-v5"
MAX_HOST_ARTIFACT_BYTES = 1024 * 1024
HOST_SHA256_PATTERN = re.compile(r"[0-9A-F]{64}\Z")
ISOLATED_FREEZE_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "release_identity",
        "mode",
        "authority_digest",
        "lifecycle_lock_held",
        "backend_service_state",
        "runtime_process_count",
        "listener_pid_count",
        "coordinator_pid",
        "recorded_at_utc",
        "expires_at_utc",
    }
)
HOST_ENVELOPE_FIELDS = frozenset(
    {"schema", "artifact_kind", "payload_sha256", "payload_json"}
)
WINDOWS_FREEZE_FIELDS = frozenset(
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
WINDOWS_ROLE_CAPABILITY_FIELDS = frozenset(
    {
        "name", "oid", "disposition", "can_login", "connection_limit",
        "is_superuser", "can_create_db", "can_create_role", "can_replicate",
        "can_bypass_rls", "is_database_owner", "owns_public_schema",
        "owns_user_relations", "direct_connect", "effective_connect",
        "can_database_create", "can_public_schema_create", "can_table_write",
        "can_sequence_write", "can_assume_write_owner",
    }
)
WINDOWS_ROLE_BOOL_FIELDS = WINDOWS_ROLE_CAPABILITY_FIELDS - {
    "name",
    "oid",
    "disposition",
    "connection_limit",
}
WINDOWS_ROLE_ELEVATED_FIELDS = {
    "is_superuser",
    "can_create_db",
    "can_create_role",
    "can_replicate",
    "can_bypass_rls",
}


def _read_windows_freeze_payload(
    path: Path,
) -> tuple[dict[str, object], str]:
    operation_path = re.fullmatch(
        (
            r"operation-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}-freeze-proof"
            r"(?:-binding-[1-9][0-9]*)?\.json"
        ),
        path.name,
    )
    if operation_path is None or path.parent.name != "c07-lifecycle":
        raise C07CeremonyError(
            "writer-freeze proof path is outside the lifecycle authority layout"
        )
    try:
        with hold_system_authority_file_for_read(path) as protected:
            raw = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07CeremonyError(
            "writer-freeze proof is not an exact SYSTEM host authority file"
        ) from exc
    if (
        not 0 < len(raw) <= MAX_HOST_ARTIFACT_BYTES
        or raw.startswith(b"\xef\xbb\xbf")
        or not raw.endswith(b"\n")
        or raw.endswith(b"\n\n")
        or b"\r" in raw
    ):
        raise C07CeremonyError("writer-freeze envelope encoding is invalid")
    envelope = _parse_json_object(raw, label="writer-freeze envelope")
    if (
        set(envelope) != HOST_ENVELOPE_FIELDS
        or envelope.get("schema") != HOST_ENVELOPE_SCHEMA
        or envelope.get("artifact_kind") != "freeze_proof"
    ):
        raise C07CeremonyError("writer-freeze envelope schema is invalid")
    declared = envelope.get("payload_sha256")
    payload_json = envelope.get("payload_json")
    if (
        not isinstance(declared, str)
        or HOST_SHA256_PATTERN.fullmatch(declared) is None
        or not isinstance(payload_json, str)
        or not payload_json.startswith("{")
        or not payload_json.endswith("}")
        or "\r" in payload_json
        or "\n" in payload_json
        or sha256_bytes(payload_json.encode("utf-8")).upper() != declared
    ):
        raise C07CeremonyError(
            "writer-freeze envelope payload digest is invalid"
        )
    payload = _parse_json_object(
        payload_json.encode("utf-8"),
        label="writer-freeze payload",
    )
    if (
        set(payload) != WINDOWS_FREEZE_FIELDS
        or payload.get("schema") != WINDOWS_FREEZE_SCHEMA
    ):
        raise C07CeremonyError("writer-freeze payload schema is invalid")
    return payload, declared


def _valid_windows_role(
    role: dict[str, object], *, role_names: set[str], role_oids: set[int]
) -> bool:
    role_name = role.get("name")
    role_oid = role.get("oid")
    connection_limit = role.get("connection_limit")
    disposition = role.get("disposition")
    elevated = any(role.get(field) is True for field in WINDOWS_ROLE_ELEVATED_FIELDS)
    identity_valid = (
        isinstance(role_name, str)
        and 0 < len(role_name) <= 63
        and isinstance(role_oid, int)
        and not isinstance(role_oid, bool)
        and role_oid >= 1
        and isinstance(connection_limit, int)
        and not isinstance(connection_limit, bool)
        and connection_limit >= -1
        and role_name not in role_names
        and role_oid not in role_oids
    )
    authority_valid = (
        disposition != "database_authority"
        or (
            role_name == "postgres"
            and role.get("can_login") is True
            and role.get("is_superuser") is True
        )
    )
    migration_valid = (
        disposition != "migration_authority"
        or (
            role_name == "ticketbox_migrator"
            and role.get("can_login") is True
            and not elevated
        )
    )
    owner_valid = (
        disposition != "nologin_owner"
        or (
            role_name == "ticketbox_owner"
            and role.get("can_login") is False
            and not elevated
        )
    )
    runtime_valid = (
        disposition != "fenced_runtime"
        or (
            role_name in {"ticketbox", "ticketbox_runtime"}
            and role.get("can_login") is False
            and connection_limit == 0
            and role.get("direct_connect") is False
            and (
                role.get("effective_connect") is False
                or role.get("is_database_owner") is True
            )
            and not elevated
        )
    )
    inert_valid = (
        disposition != "inert_unregistered"
        or not any(role.get(field) is True for field in WINDOWS_ROLE_BOOL_FIELDS)
    )
    return (
        all(isinstance(role.get(field), bool) for field in WINDOWS_ROLE_BOOL_FIELDS)
        and identity_valid
        and disposition in {
            "database_authority",
            "migration_authority",
            "nologin_owner",
            "fenced_runtime",
            "inert_unregistered",
        }
        and authority_valid
        and migration_valid
        and owner_valid
        and runtime_valid
        and inert_valid
    )


def _windows_role_dispositions(
    payload: dict[str, object],
    *,
    role_count: int,
) -> list[object] | None:
    roles = payload.get("database_role_capabilities")
    if (
        not isinstance(roles, list)
        or len(roles) != role_count
        or not all(
            isinstance(role, dict) and set(role) == WINDOWS_ROLE_CAPABILITY_FIELDS
            for role in roles
        )
    ):
        return None
    role_names: set[str] = set()
    role_oids: set[int] = set()
    dispositions: list[object] = []
    for role in roles:
        if not _valid_windows_role(role, role_names=role_names, role_oids=role_oids):
            return None
        role_names.add(str(role["name"]))
        role_oids.add(int(role["oid"]))
        dispositions.append(role["disposition"])
    return dispositions


def _assert_windows_writer_fence(payload: dict[str, object]) -> int:
    heartbeat_sequence = _required_int(payload, "heartbeat_sequence", minimum=1)
    role_count = _required_int(
        payload,
        "database_role_capability_count",
        minimum=2,
        maximum=128,
    )
    dispositions = _windows_role_dispositions(payload, role_count=role_count)
    invalid = (
        payload.get("backend_service_state") != "stopped"
        or payload.get("backend_service_start_policy") != "disabled"
        or payload.get("backend_service_pid") != 0
        or payload.get("backend_listener_pid_count") != 0
        or payload.get("runtime_process_count") != 0
        or payload.get("database_client_session_count") != 0
        or payload.get("database_client_sessions") != []
        or payload.get("database_public_connect") is not False
        or dispositions is None
        or dispositions.count("database_authority") != 1
        or dispositions.count("fenced_runtime") < 1
        or payload.get("database_authority_role") != "postgres"
        or payload.get("database_authority_scope")
        != "process_local_secret_same_session_advisory_cut"
        or payload.get("database_max_prepared_transactions") != 0
        or payload.get("database_prepared_transaction_count") != 0
        or payload.get("database_logical_subscription_count") != 0
        or payload.get("database_logical_apply_worker_count") != 0
        or payload.get("database_unexpected_worker_count") != 0
        or payload.get("database_advisory_fence_available") is not True
    )
    if invalid:
        raise C07CeremonyError(
            "writer-freeze proof does not show the durable writer fence"
        )
    return heartbeat_sequence


def _windows_identity_binding(
    payload: dict[str, object],
    *,
    path: Path,
    expected_release_identity: str,
) -> tuple[str, str]:
    _required_host_sha(payload, "revision_manifest_sha256")
    if (
        payload.get("operation_kind") != "c07_money_minor_bigint_v1"
        or payload.get("target_alembic_revision") != C07_TARGET_REVISION
    ):
        raise C07CeremonyError(
            "writer-freeze capability/revision binding is invalid"
        )
    operation_id = canonical_uuid(payload.get("operation_id"), label="operation_id")
    canonical_uuid(payload.get("recovery_epoch_id"), label="recovery_epoch_id")
    expected_name = (
        rf"operation-{re.escape(operation_id)}-freeze-proof"
        r"(?:-binding-[1-9][0-9]*)?\.json"
    )
    if re.fullmatch(expected_name, path.name) is None:
        raise C07CeremonyError(
            "writer-freeze proof path does not match operation identity"
        )
    release_identity = payload.get("release_fingerprint")
    if (
        release_identity != expected_release_identity
        or not isinstance(release_identity, str)
        or HOST_SHA256_PATTERN.fullmatch(release_identity) is None
    ):
        raise C07CeremonyError("writer-freeze proof release identity mismatch")
    return operation_id, release_identity


def _windows_freeze_times(
    payload: dict[str, object],
) -> tuple[datetime, datetime]:
    recorded_at = parse_utc(
        payload.get("writers_frozen_at_utc"),
        label="writers_frozen_at_utc",
    )
    expires_at = recorded_at + MAX_FREEZE_WINDOW
    now = datetime.now(UTC)
    if recorded_at > now + timedelta(seconds=5) or expires_at <= now:
        raise C07CeremonyError("writer-freeze proof is stale")
    return recorded_at, expires_at


def _windows_host_evidence(
    payload: dict[str, object],
    *,
    operation_id: str,
    release_identity: str,
    payload_sha256: str,
    process_identity: tuple[int, int, int, int, int, int],
    heartbeat_sequence: int,
) -> HostFreezeEvidence:
    coordinator_pid, coordinator_high, coordinator_low, owner_pid, owner_high, owner_low = process_identity
    recorded_at, expires_at = _windows_freeze_times(payload)
    return HostFreezeEvidence(
        operation_id=operation_id,
        release_identity=release_identity,
        mode="windows_lifecycle_lock",
        authority_digest=_required_host_sha(payload, "descriptor_sha256"),
        coordinator_pid=coordinator_pid,
        recorded_at_utc=recorded_at,
        expires_at_utc=expires_at,
        evidence_sha256=payload_sha256,
        database_binding_sha256=_required_host_sha(payload, "database_binding_sha256"),
        writer_fence_intent_sha256=_required_host_sha(payload, "writer_fence_intent_sha256"),
        coordinator_binding_sha256=_required_host_sha(payload, "coordinator_binding_sha256"),
        coordinator_started_filetime_high=coordinator_high,
        coordinator_started_filetime_low=coordinator_low,
        lifecycle_owner_pid=owner_pid,
        lifecycle_owner_started_filetime_high=owner_high,
        lifecycle_owner_started_filetime_low=owner_low,
        heartbeat_sequence=heartbeat_sequence,
    )


def _read_windows_host_evidence(
    path: Path,
    *,
    expected_release_identity: str,
    expected_parent_pid: int | None,
) -> HostFreezeEvidence:
    if expected_parent_pid is None:
        raise C07CeremonyError(
            "production writer-freeze proof requires its coordinator parent"
        )
    payload, payload_sha256 = _read_windows_freeze_payload(path)
    operation_id, release_identity = _windows_identity_binding(
        payload,
        path=path,
        expected_release_identity=expected_release_identity,
    )
    process_identity = _read_windows_process_identity(
        payload,
        expected_parent_pid=expected_parent_pid,
        process_start_reader=windows_process_start_filetime,
    )
    return _windows_host_evidence(
        payload,
        operation_id=operation_id,
        release_identity=release_identity,
        payload_sha256=payload_sha256,
        process_identity=process_identity,
        heartbeat_sequence=_assert_windows_writer_fence(payload),
    )


def read_host_freeze_evidence(
    path: Path,
    *,
    expected_release_identity: str,
    expected_parent_pid: int | None,
    allow_isolated_test: bool = False,
) -> HostFreezeEvidence:
    """Read one protected host proof and reject stale or unverifiable claims."""

    if not path.is_absolute():
        raise C07CeremonyError("writer-freeze proof path must be absolute")
    if allow_isolated_test:
        return _read_isolated_host_evidence(
            path,
            expected_release_identity=expected_release_identity,
            expected_parent_pid=expected_parent_pid,
        )
    return _read_windows_host_evidence(
        path,
        expected_release_identity=expected_release_identity,
        expected_parent_pid=expected_parent_pid,
    )
