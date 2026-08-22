"""Read the sole installed database-generation CURRENT and its live DB binding."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database._database_generation_runtime_queries import (
    LIVE_DATABASE_QUERY,
    RUNTIME_ACL_EVIDENCE_QUERY,
)
from app.database._lifecycle import DatabaseMigrationPreflightError
from app.services.secure_file import hold_system_runtime_projection_for_read

_CURRENT_DIRECTORY = "database-generation-runtime"
_CURRENT_FILE = "current-generation.json"
_MACHINE_DIRECTORY = "Ticketbox"
_COMMON_PROGRAM_FILES = 0x002B
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
_BINDING_KEY = "database_generation_binding"
_ENVELOPE_FIELDS = ("schema", "kind", "payload_sha256", "payload")
_CURRENT_FIELD_ORDER = (
    "schema operation_id installation_id intent_sha256 candidate_sha256 "
    "committed_revision generation_program_sha256 database_binding_sha256 "
    "terminal_state_sha256 expected_predecessor_sha256"
)
_BINDING_FIELD_ORDER = (
    "schema operation_id installation_id intent_sha256 source_binding_sha256 "
    "target_revision generation_program_sha256 cluster_system_identifier database_oid "
    "database_name runtime_role dataset_id restore_epoch schema_revision "
    "schema_min_compatible semantic_revision "
    "execution_authority_sha256 role_authority_sha256 runtime_acl_sha256 "
    "post_migration_writer_fence_sha256 target_recovery_evidence_sha256"
)
_BINDING_SHA_FIELD_ORDER = (
    "source_binding_sha256 generation_program_sha256 execution_authority_sha256 "
    "role_authority_sha256 runtime_acl_sha256 post_migration_writer_fence_sha256 "
    "target_recovery_evidence_sha256"
)
class DatabaseGenerationAdmissionError(RuntimeError):
    """Installed runtime CURRENT or its live database binding is not exact."""


@dataclass(frozen=True)
class _ExpectedBinding:
    operation_id: str
    installation_id: str
    intent_sha256: str
    program_sha256: str
    revision: str
    candidate_sha256: str


@dataclass(frozen=True)
class _LiveDatabaseIdentity:
    cluster_identifier: object
    database_oid: object
    database_name: object
    session_user: object
    dataset_id: object
    restore_epoch: object
    schema_revision: object
    schema_min_compatible: object
    semantic_revision: object
    bootstrap_retirement: object
    runtime_capabilities: tuple[object, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _runtime_acl_sha256(evidence: tuple[str, ...]) -> str:
    return _sha256("\n".join(evidence))


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DatabaseGenerationAdmissionError(f"{label} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise DatabaseGenerationAdmissionError(f"{label} must be a UUID") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise DatabaseGenerationAdmissionError(f"{label} must be a canonical UUID")
    return value


def _lower_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DatabaseGenerationAdmissionError(f"{label} must be a lower SHA-256")
    return value


def _positive_decimal(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise DatabaseGenerationAdmissionError(f"{label} must be a positive decimal")
    return value


def _database_oid(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 0xFFFFFFFF:
        raise DatabaseGenerationAdmissionError(f"{label} must be a positive database OID")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DatabaseGenerationAdmissionError(f"{label} must be a non-negative integer")
    return value


def _common_program_files() -> Path:
    if os.name != "nt":
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT is Windows-only")
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(  # type: ignore[attr-defined]
        None,
        _COMMON_PROGRAM_FILES,
        None,
        0,
        buffer,
    )
    if result != 0 or not buffer.value:
        raise DatabaseGenerationAdmissionError("Common Program Files is unavailable")
    return Path(os.path.abspath(buffer.value))


def database_generation_runtime_current_path() -> Path:
    return _common_program_files() / _MACHINE_DIRECTORY / _CURRENT_DIRECTORY / _CURRENT_FILE


def _read_current(path: Path) -> tuple[dict[str, object], str]:
    try:
        with hold_system_runtime_projection_for_read(path) as protected:
            raw = protected.read_bytes().decode("utf-8")
        envelope = json.loads(raw)
    except (OSError, PermissionError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT is unavailable") from exc
    if (
        raw.startswith("\ufeff")
        or "\r" in raw
        or "\n" in raw
        or not isinstance(envelope, dict)
        or tuple(envelope) != _ENVELOPE_FIELDS
        or raw != _canonical_json(envelope)
        or envelope.get("schema") != "ticketbox-database-generation-envelope-v1"
        or envelope.get("kind") != "current"
        or not isinstance(envelope.get("payload"), dict)
    ):
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT is not canonical")
    payload = envelope["payload"]
    assert isinstance(payload, dict)
    if " ".join(payload) != _CURRENT_FIELD_ORDER:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT fields are not closed")
    payload_sha = _lower_sha(envelope.get("payload_sha256"), "CURRENT payload")
    if _sha256(_canonical_json(payload)) != payload_sha:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT digest changed")
    return payload, payload_sha


def _validate_current(current: dict[str, object], program: object) -> tuple[str, str, str, str, str, str, str]:
    operation_id = _canonical_uuid(current["operation_id"], "CURRENT operation_id")
    installation_id = _canonical_uuid(current["installation_id"], "CURRENT installation_id")
    intent_sha = _lower_sha(current["intent_sha256"], "CURRENT intent")
    candidate_sha = _lower_sha(current["candidate_sha256"], "CURRENT candidate")
    binding_sha = _lower_sha(current["database_binding_sha256"], "CURRENT database binding")
    program_sha = _lower_sha(current["generation_program_sha256"], "CURRENT generation program")
    _lower_sha(current["terminal_state_sha256"], "CURRENT terminal state")
    revision = current["committed_revision"]
    if (
        not isinstance(revision, str)
        or _REVISION.fullmatch(revision) is None
        or current["schema"] != "ticketbox-current-database-generation-v1"
        or (
            current["expected_predecessor_sha256"] != ""
            and _SHA256.fullmatch(str(current["expected_predecessor_sha256"])) is None
        )
        or revision != getattr(program, "target_revision", None)
        or program_sha != getattr(program, "payload_sha256", None)
    ):
        raise DatabaseGenerationAdmissionError("CURRENT does not bind the installed program")
    return (
        operation_id,
        installation_id,
        intent_sha,
        binding_sha,
        program_sha,
        revision,
        candidate_sha,
    )


def _observe_live_database(
    engine: object,
) -> tuple[object, tuple[str, ...], object, str]:
    try:
        with engine.connect() as connection:  # type: ignore[union-attr]
            binding_json = connection.scalar(
                text("SELECT value FROM public.app_meta WHERE key = :key"),
                {"key": _BINDING_KEY},
            )
            revisions = tuple(
                str(value) for value in connection.scalars(text("SELECT version_num FROM public.alembic_version"))
            )
            live_identity = connection.execute(LIVE_DATABASE_QUERY).one()
            runtime_acl_evidence = tuple(str(value) for value in connection.scalars(RUNTIME_ACL_EVIDENCE_QUERY))
    except (OSError, RuntimeError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database binding is unavailable") from exc
    return (
        binding_json,
        revisions,
        live_identity,
        _runtime_acl_sha256(runtime_acl_evidence),
    )


def _load_binding(binding_json: object, binding_sha: str) -> dict[str, object]:
    if not isinstance(binding_json, str) or _sha256(binding_json) != binding_sha:
        raise DatabaseGenerationAdmissionError("live database binding digest changed")
    try:
        binding = json.loads(binding_json)
    except json.JSONDecodeError as exc:
        raise DatabaseGenerationAdmissionError("live database binding is not JSON") from exc
    if not isinstance(binding, dict):
        raise DatabaseGenerationAdmissionError("live database binding is not an object")
    return binding


def _assert_runtime_capability(values: tuple[object, ...]) -> None:
    if len(values) != 14 or any(value is not True for value in values):
        raise DatabaseGenerationAdmissionError(
            "live runtime or backup capability escaped its closed contract"
        )


def _assert_live_binding(
    binding: dict[str, object],
    binding_json: str,
    revisions: tuple[str, ...],
    live_identity: object,
    live_runtime_acl_sha256: str,
    expected: _ExpectedBinding,
) -> None:
    live = _decode_live_identity(live_identity)
    _assert_binding_control(binding, binding_json, revisions, live, expected)
    _assert_binding_database(binding, live, live_runtime_acl_sha256, expected)
    if binding["database_name"] != "ticketbox" or binding["runtime_role"] != "ticketbox_runtime":
        raise DatabaseGenerationAdmissionError("database binding runtime target is not closed")
    for field in _BINDING_SHA_FIELD_ORDER.split():
        _lower_sha(binding[field], f"database binding {field}")


def _decode_live_identity(value: object) -> _LiveDatabaseIdentity:
    try:
        (
            cluster_identifier,
            database_oid,
            database_name,
            session_user,
            dataset_id,
            restore_epoch,
            schema_revision,
            schema_min_compatible,
            semantic_revision,
            bootstrap_retirement,
            *runtime_capabilities,
        ) = value  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database identity is incomplete") from exc
    _assert_runtime_capability(tuple(runtime_capabilities))
    return _LiveDatabaseIdentity(
        cluster_identifier=cluster_identifier,
        database_oid=database_oid,
        database_name=database_name,
        session_user=session_user,
        dataset_id=dataset_id,
        restore_epoch=restore_epoch,
        schema_revision=schema_revision,
        schema_min_compatible=schema_min_compatible,
        semantic_revision=semantic_revision,
        bootstrap_retirement=bootstrap_retirement,
        runtime_capabilities=tuple(runtime_capabilities),
    )


def _assert_binding_control(
    binding: dict[str, object],
    binding_json: str,
    revisions: tuple[str, ...],
    live: _LiveDatabaseIdentity,
    expected: _ExpectedBinding,
) -> None:
    expected_bootstrap_retirement = _canonical_json(
        {
            "schema": "ticketbox-database-generation-bootstrap-retirement-v1",
            "operation_id": expected.operation_id,
            "intent_sha256": expected.intent_sha256,
            "candidate_sha256": expected.candidate_sha256,
            "committed_revision": expected.revision,
        }
    )
    if (
        " ".join(binding) != _BINDING_FIELD_ORDER
        or binding_json != _canonical_json(binding)
        or binding["schema"] != "ticketbox-database-generation-database-binding-v1"
        or binding["operation_id"] != expected.operation_id
        or binding["installation_id"] != expected.installation_id
        or binding["intent_sha256"] != expected.intent_sha256
        or binding["target_revision"] != expected.revision
        or binding["generation_program_sha256"] != expected.program_sha256
        or revisions != (expected.revision,)
        or live.bootstrap_retirement != expected_bootstrap_retirement
    ):
        raise DatabaseGenerationAdmissionError("live database binding does not match the sole CURRENT")


def _assert_binding_database(
    binding: dict[str, object],
    live: _LiveDatabaseIdentity,
    live_runtime_acl_sha256: str,
    expected: _ExpectedBinding,
) -> None:
    try:
        canonical_live_database_oid = _database_oid(int(live.database_oid), "live database OID")
    except (TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database OID is invalid") from exc
    if (
        _positive_decimal(
            binding["cluster_system_identifier"],
            "database binding cluster identity",
        )
        != str(live.cluster_identifier)
        or _database_oid(binding["database_oid"], "database binding database OID") != canonical_live_database_oid
        or binding["database_name"] != live.database_name
        or binding["runtime_role"] != live.session_user
        or _lower_sha(
            binding["runtime_acl_sha256"],
            "database binding runtime ACL",
        )
        != live_runtime_acl_sha256
        or _canonical_uuid(binding["dataset_id"], "database binding dataset_id")
        != _canonical_uuid(live.dataset_id, "live dataset_id")
        or _nonnegative_integer(binding["restore_epoch"], "database binding restore_epoch")
        != _nonnegative_integer(live.restore_epoch, "live restore_epoch")
        or binding["schema_revision"] != live.schema_revision
        or binding["schema_revision"] != expected.revision
        or not isinstance(binding["schema_min_compatible"], str)
        or not binding["schema_min_compatible"]
        or binding["schema_min_compatible"] != live.schema_min_compatible
        or binding["semantic_revision"] != live.semantic_revision
        or live.semantic_revision != "ticketbox-dataset-semantics-v1"
    ):
        raise DatabaseGenerationAdmissionError("live database binding does not match the sole CURRENT")


def assert_database_generation_runtime_admission(
    engine: object,
    program: object,
    *,
    current_path: Path | None = None,
) -> None:
    current, _current_sha = _read_current(current_path or database_generation_runtime_current_path())
    current_contract = _validate_current(current, program)
    binding_json, revisions, live_identity, live_runtime_acl_sha256 = _observe_live_database(engine)
    binding = _load_binding(binding_json, current_contract[3])
    assert isinstance(binding_json, str)
    _assert_live_binding(
        binding,
        binding_json,
        revisions,
        live_identity,
        live_runtime_acl_sha256,
        _ExpectedBinding(
            operation_id=current_contract[0],
            installation_id=current_contract[1],
            intent_sha256=current_contract[2],
            program_sha256=current_contract[4],
            revision=current_contract[5],
            candidate_sha256=current_contract[6],
        ),
    )


def assert_database_generation_startup_ready(engine: object, program: object) -> None:
    """Translate the installed CURRENT admission contract into startup refusal."""

    try:
        assert_database_generation_runtime_admission(engine, program)
    except DatabaseGenerationAdmissionError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放数据库 writer:Generation CURRENT 或 live binding 未完成({exc})。"
        ) from exc


__all__ = [
    "DatabaseGenerationAdmissionError",
    "assert_database_generation_runtime_admission",
    "assert_database_generation_startup_ready",
    "database_generation_runtime_current_path",
]
