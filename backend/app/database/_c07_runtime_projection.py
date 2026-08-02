"""Strict SYSTEM runtime projection decoding for C07 startup."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.database._c07_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    C07ReceiptRepairRequiredError,
)
from app.services.secure_file import hold_system_runtime_projection_for_read

_HOST_ENVELOPE_SCHEMA = "ticketbox-c07-host-envelope-v2"
_PROJECTION_SCHEMA = "ticketbox-c07-runtime-projection-v6"
_PROJECTION_FILE_NAME = "c07-lifecycle-projection.json"
_PROJECTION_DIRECTORY_NAME = "c07-runtime-projection"
_TICKETBOX_MACHINE_DIRECTORY_NAME = "Ticketbox"
_CSIDL_COMMON_PROGRAM_FILES = 0x002B
_OPERATION_KIND = "c07_money_minor_bigint_v1"
_SHA256_LOWER = re.compile(r"[0-9a-f]{64}\Z")
_SHA256_UPPER = re.compile(r"[0-9A-F]{64}\Z")
_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{7}Z\Z"
)
_ZERO_SHA256 = "0" * 64
_OUTER_FIELDS = frozenset(
    {"schema", "artifact_kind", "payload_sha256", "payload_json"}
)
_PROJECTION_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "installation_id",
        "stage",
        "terminal",
        "ready",
        "database_binding_sha256",
        "logical_server_id",
        "data_generation",
        "recovery_epoch_id",
        "operation_kind",
        "source_alembic_revision",
        "alembic_target",
        "recovery_manifest_sha256",
        "migration_evidence_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "live_postconditions_sha256",
        "money_facts_sha256",
        "money_shape_sha256",
        "heartbeat_sequence_at_publish",
        "updated_at_utc",
    }
)


@dataclass(frozen=True)
class RuntimeProjection:
    operation_id: str
    installation_id: str
    database_binding_sha256: str
    logical_server_id: str
    data_generation: str
    recovery_epoch_id: str
    source_revision: str
    target_revision: str
    recovery_manifest_sha256: str
    migration_evidence_sha256: str
    role_authority_sha256: str
    runtime_acl_sha256: str
    live_postconditions_sha256: str
    money_facts_sha256: str
    money_shape_sha256: str


def _strict_json_object(value: str, *, label: str) -> dict[str, object]:
    def reject_duplicate_pairs(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, item in pairs:
            if key in parsed:
                raise ValueError(f"{label} contains a duplicate field")
            parsed[key] = item
        return parsed

    try:
        parsed = json.loads(
            value,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"{label} contains non-finite JSON: {item}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            f"C07 {label} is not strict JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise C07ReceiptRepairRequiredError(
            f"C07 {label} must be a JSON object"
        )
    return parsed


def _canonical_uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise C07ReceiptRepairRequiredError(f"C07 {label} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise C07ReceiptRepairRequiredError(
            f"C07 {label} must be a canonical UUID"
        ) from exc
    if parsed.int == 0 or str(parsed) != value:
        raise C07ReceiptRepairRequiredError(
            f"C07 {label} must be a canonical non-zero UUID"
        )
    return value


def _required_sha256(
    value: object,
    *,
    label: str,
    uppercase: bool,
) -> str:
    pattern = _SHA256_UPPER if uppercase else _SHA256_LOWER
    if (
        not isinstance(value, str)
        or pattern.fullmatch(value) is None
        or value.lower() == _ZERO_SHA256
    ):
        raise C07ReceiptRepairRequiredError(
            f"C07 {label} must be a non-zero canonical SHA-256"
        )
    return value


def _common_program_files() -> Path:
    if os.name != "nt":
        raise OSError("Common Program Files authority is Windows-only")
    buffer = ctypes.create_unicode_buffer(32768)
    get_folder_path = ctypes.WinDLL(
        "shell32",
        use_last_error=True,
    ).SHGetFolderPathW
    get_folder_path.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    )
    get_folder_path.restype = ctypes.c_long
    result = get_folder_path(
        None,
        _CSIDL_COMMON_PROGRAM_FILES,
        None,
        0,
        buffer,
    )
    if result != 0 or not buffer.value:
        raise OSError(
            result,
            "SHGetFolderPathW(CSIDL_COMMON_PROGRAM_FILES) failed",
        )
    return Path(os.path.abspath(buffer.value))


def c07_runtime_projection_path() -> Path:
    return (
        _common_program_files()
        / _TICKETBOX_MACHINE_DIRECTORY_NAME
        / _PROJECTION_DIRECTORY_NAME
        / _PROJECTION_FILE_NAME
    )


def _read_projection_bytes(path: Path) -> bytes:
    try:
        with hold_system_runtime_projection_for_read(path) as protected:
            return protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 SYSTEM runtime projection is unavailable or has an invalid ACL"
        ) from exc


def _decode_projection_envelope(payload: bytes) -> dict[str, object]:
    try:
        raw = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 runtime projection is not UTF-8"
        ) from exc
    if (
        raw.startswith("\ufeff")
        or "\r" in raw
        or not raw.endswith("\n")
        or raw.count("\n") != 1
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 runtime projection does not use the exact no-BOM single-LF format"
        )
    envelope = _strict_json_object(
        raw[:-1],
        label="runtime projection envelope",
    )
    if set(envelope) != _OUTER_FIELDS:
        raise C07ReceiptRepairRequiredError(
            "C07 runtime projection envelope fields are invalid"
        )
    payload_json = envelope.get("payload_json")
    payload_sha256 = envelope.get("payload_sha256")
    if (
        envelope.get("schema") != _HOST_ENVELOPE_SCHEMA
        or envelope.get("artifact_kind") != "runtime_projection"
        or not isinstance(payload_json, str)
        or not isinstance(payload_sha256, str)
        or _SHA256_UPPER.fullmatch(payload_sha256) is None
        or hashlib.sha256(payload_json.encode("utf-8")).hexdigest().upper()
        != payload_sha256
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 runtime projection envelope binding is invalid"
        )
    projection = _strict_json_object(
        payload_json,
        label="runtime projection payload",
    )
    if set(projection) != _PROJECTION_FIELDS:
        raise C07ReceiptRepairRequiredError(
            "C07 runtime projection payload fields are invalid"
        )
    return projection


def _assert_ready_projection_shape(projection: dict[str, object]) -> None:
    if (
        projection.get("schema") != _PROJECTION_SCHEMA
        or projection.get("stage") != "ready"
        or projection.get("terminal") is not True
        or projection.get("ready") is not True
        or projection.get("operation_kind") != _OPERATION_KIND
        or projection.get("source_alembic_revision")
        != C07_SOURCE_REVISION
        or projection.get("alembic_target") != C07_TARGET_REVISION
        or not isinstance(
            projection.get("heartbeat_sequence_at_publish"),
            int,
        )
        or isinstance(
            projection.get("heartbeat_sequence_at_publish"),
            bool,
        )
        or int(projection["heartbeat_sequence_at_publish"]) < 1
        or not isinstance(projection.get("updated_at_utc"), str)
        or _UTC_TIMESTAMP.fullmatch(str(projection["updated_at_utc"]))
        is None
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 runtime projection is not an exact C07 READY authority"
        )
    for field in (
        "database_binding_sha256",
        "recovery_manifest_sha256",
        "migration_evidence_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "live_postconditions_sha256",
        "money_facts_sha256",
        "money_shape_sha256",
    ):
        _required_sha256(
            projection.get(field),
            label=f"runtime projection {field}",
            uppercase=True,
        )


def _runtime_projection(
    projection: dict[str, object],
) -> RuntimeProjection:
    _assert_ready_projection_shape(projection)
    return RuntimeProjection(
        operation_id=_canonical_uuid(
            projection.get("operation_id"),
            label="runtime projection operation_id",
        ),
        installation_id=_canonical_uuid(
            projection.get("installation_id"),
            label="runtime projection installation_id",
        ),
        database_binding_sha256=str(
            projection["database_binding_sha256"]
        ),
        logical_server_id=_canonical_uuid(
            projection.get("logical_server_id"),
            label="runtime projection logical_server_id",
        ),
        data_generation=_canonical_uuid(
            projection.get("data_generation"),
            label="runtime projection data_generation",
        ),
        recovery_epoch_id=_canonical_uuid(
            projection.get("recovery_epoch_id"),
            label="runtime projection recovery_epoch_id",
        ),
        source_revision=str(projection["source_alembic_revision"]),
        target_revision=str(projection["alembic_target"]),
        recovery_manifest_sha256=str(
            projection["recovery_manifest_sha256"]
        ),
        migration_evidence_sha256=str(
            projection["migration_evidence_sha256"]
        ),
        role_authority_sha256=str(
            projection["role_authority_sha256"]
        ),
        runtime_acl_sha256=str(projection["runtime_acl_sha256"]),
        live_postconditions_sha256=str(
            projection["live_postconditions_sha256"]
        ),
        money_facts_sha256=str(projection["money_facts_sha256"]),
        money_shape_sha256=str(projection["money_shape_sha256"]),
    )


def read_c07_runtime_projection(
    path: Path | None = None,
) -> RuntimeProjection:
    projection_path = path or c07_runtime_projection_path()
    return _runtime_projection(
        _decode_projection_envelope(
            _read_projection_bytes(projection_path)
        )
    )
