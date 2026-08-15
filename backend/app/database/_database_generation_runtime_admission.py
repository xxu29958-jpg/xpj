"""Read the sole installed database-generation CURRENT and its live DB binding."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
_CURRENT_FIELDS = (
    "schema",
    "operation_id",
    "installation_id",
    "intent_sha256",
    "candidate_sha256",
    "committed_revision",
    "generation_program_sha256",
    "database_binding_sha256",
    "expected_predecessor_sha256",
)
_BINDING_FIELDS = (
    "schema",
    "operation_id",
    "installation_id",
    "intent_sha256",
    "source_binding_sha256",
    "target_revision",
    "generation_program_sha256",
    "execution_authority_sha256",
    "role_authority_sha256",
    "runtime_acl_sha256",
    "post_migration_writer_fence_sha256",
    "target_recovery_evidence_sha256",
)


class DatabaseGenerationAdmissionError(RuntimeError):
    """Installed runtime CURRENT or its live database binding is not exact."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    if tuple(payload) != _CURRENT_FIELDS:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT fields are not closed")
    payload_sha = _lower_sha(envelope.get("payload_sha256"), "CURRENT payload")
    if _sha256(_canonical_json(payload)) != payload_sha:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT digest changed")
    return payload, payload_sha


def assert_database_generation_runtime_admission(
    engine: object,
    program: object,
    *,
    current_path: Path | None = None,
) -> None:
    current, _current_sha = _read_current(
        current_path or database_generation_runtime_current_path()
    )
    operation_id = _canonical_uuid(current["operation_id"], "CURRENT operation_id")
    installation_id = _canonical_uuid(
        current["installation_id"], "CURRENT installation_id"
    )
    intent_sha = _lower_sha(current["intent_sha256"], "CURRENT intent")
    _lower_sha(current["candidate_sha256"], "CURRENT candidate")
    binding_sha = _lower_sha(
        current["database_binding_sha256"], "CURRENT database binding"
    )
    program_sha = _lower_sha(
        current["generation_program_sha256"], "CURRENT generation program"
    )
    revision = current["committed_revision"]
    if (
        not isinstance(revision, str)
        or _REVISION.fullmatch(revision) is None
        or current["schema"] != "ticketbox-current-database-generation-v1"
        or current["expected_predecessor_sha256"] != ""
        or revision != getattr(program, "target_revision", None)
        or program_sha != getattr(program, "payload_sha256", None)
    ):
        raise DatabaseGenerationAdmissionError("CURRENT does not bind the installed program")

    try:
        with engine.connect() as connection:  # type: ignore[union-attr]
            binding_json = connection.scalar(
                text("SELECT value FROM public.app_meta WHERE key = :key"),
                {"key": _BINDING_KEY},
            )
            revisions = tuple(
                str(value)
                for value in connection.scalars(
                    text("SELECT version_num FROM public.alembic_version")
                )
            )
    except (OSError, RuntimeError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database binding is unavailable") from exc
    if not isinstance(binding_json, str) or _sha256(binding_json) != binding_sha:
        raise DatabaseGenerationAdmissionError("live database binding digest changed")
    try:
        binding = json.loads(binding_json)
    except json.JSONDecodeError as exc:
        raise DatabaseGenerationAdmissionError("live database binding is not JSON") from exc
    if (
        not isinstance(binding, dict)
        or tuple(binding) != _BINDING_FIELDS
        or binding_json != _canonical_json(binding)
        or binding["schema"] != "ticketbox-database-generation-database-binding-v1"
        or binding["operation_id"] != operation_id
        or binding["installation_id"] != installation_id
        or binding["intent_sha256"] != intent_sha
        or binding["target_revision"] != revision
        or binding["generation_program_sha256"] != program_sha
        or revisions != (revision,)
    ):
        raise DatabaseGenerationAdmissionError(
            "live database binding does not match the sole CURRENT"
        )
    for field in _BINDING_FIELDS[4:]:
        if field in {"target_revision", "schema"}:
            continue
        _lower_sha(binding[field], f"database binding {field}")


def assert_database_generation_startup_ready(engine: object, program: object) -> None:
    """Translate the installed CURRENT admission contract into startup refusal."""

    try:
        assert_database_generation_runtime_admission(engine, program)
    except DatabaseGenerationAdmissionError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放数据库 writer:Generation CURRENT 或 live binding 未完成({exc})。"
        ) from exc


def assert_legacy_c07_startup_ready(
    engine: object,
    alembic_config: object,
    *,
    production_authority_required: bool,
    expected_release_revision: str,
) -> None:
    """Keep source/dev C07 admission outside the runtime database facade."""

    from app.database._c07_ceremony import (
        C07ReceiptRepairRequiredError,
        assert_c07_lifecycle_ready,
    )

    try:
        assert_c07_lifecycle_ready(
            engine,
            alembic_config=alembic_config,
            production_authority_required=production_authority_required,
            expected_release_revision=expected_release_revision,
        )
    except C07ReceiptRepairRequiredError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放数据库 writer:C07 生命周期回执未完成({exc})。"
        ) from exc


__all__ = [
    "DatabaseGenerationAdmissionError",
    "assert_database_generation_runtime_admission",
    "assert_database_generation_startup_ready",
    "assert_legacy_c07_startup_ready",
    "database_generation_runtime_current_path",
]
