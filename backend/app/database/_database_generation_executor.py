"""Run one build-declared generation inside a caller-owned transaction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from datetime import UTC, datetime
from types import ModuleType
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.app_meta_observation import MANAGED_UPGRADE_ATTESTATION_KEY
from app.database._database_generation_program import (
    ALEMBIC_PROGRAM_ATTRIBUTE,
    BASE_SOURCE,
    DatabaseGenerationProgram,
    DatabaseGenerationProgramError,
    DatabaseGenerationRevision,
)
from app.database._release_schema_readiness import (
    ReleaseHeadVerificationError,
    assert_release_head,
)
from app.database._runtime_authority_privileges import (
    seal_runtime_authority_tables,
    seal_upgrade_attestation_guard,
)

_MANAGED_JSON_PROTOCOL_ATTRIBUTE = "ticketbox_managed_migration_json_protocol_v1"
_DATASET_AUTHORITY_REVISION = "20260821_0001"
UPGRADE_ATTESTATION_META_KEY = MANAGED_UPGRADE_ATTESTATION_KEY
UPGRADE_ATTESTATION_SCHEMA = "ticketbox-managed-upgrade-attestation-v1"
_ATTESTATION_KEYS = frozenset({
    "schema",
    "operation_id",
    "dataset_id",
    "restore_epoch",
    "source_revision",
    "target_revision",
    "backup_archive_sha256",
})
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_LIFECYCLE_OPERATION_ID = re.compile(r"(?:fresh|restore|upgrade)-[0-9a-f]{64}\Z")


class DatabaseGenerationExecutionError(RuntimeError):
    """The declared generation could not be executed or verified."""


def validate_generation_operation_id(operation_id: str) -> str:
    if not isinstance(operation_id, str) or not operation_id:
        raise DatabaseGenerationExecutionError("generation operation id is invalid")
    if _LIFECYCLE_OPERATION_ID.fullmatch(operation_id) is not None:
        return operation_id
    try:
        parsed = UUID(operation_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatabaseGenerationExecutionError("generation operation id is invalid") from exc
    if parsed.int == 0 or str(parsed) != operation_id:
        raise DatabaseGenerationExecutionError("generation operation id is not canonical")
    return operation_id


def _load_revision(revision: DatabaseGenerationRevision) -> ModuleType:
    try:
        payload = revision.module_path.read_bytes()
    except OSError as exc:
        raise DatabaseGenerationExecutionError(
            "generation revision is unavailable"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != revision.module_sha256:
        raise DatabaseGenerationExecutionError("generation revision bytes changed")
    spec = importlib.util.spec_from_file_location(
        f"_ticketbox_generation_{revision.revision}", revision.module_path
    )
    if spec is None or spec.loader is None:
        raise DatabaseGenerationExecutionError("generation revision cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        getattr(module, "revision", None) != revision.revision
        or getattr(module, "down_revision", None) != revision.down_revision
        or not callable(getattr(module, "upgrade", None))
        or (
            revision.postcondition is not None
            and not callable(getattr(module, revision.postcondition, None))
        )
    ):
        raise DatabaseGenerationExecutionError("generation revision metadata changed")
    return module


def _current_revision(connection: Connection) -> str | None:
    heads = tuple(
        str(value)
        for value in MigrationContext.configure(
            connection, opts={"version_table_schema": "public"}
        ).get_current_heads()
    )
    if len(heads) > 1:
        raise DatabaseGenerationExecutionError(
            "generation database has multiple Alembic revisions"
        )
    return heads[0] if heads else None


def _assert_postcondition(
    connection: Connection,
    revision: DatabaseGenerationRevision,
) -> None:
    if revision.postcondition is None:
        return
    if revision.postcondition != "assert_postcondition":
        raise DatabaseGenerationExecutionError("generation postcondition is unsupported")
    _load_revision(revision).assert_postcondition(connection)


def _alembic_config(
    connection: Connection,
    program: DatabaseGenerationProgram,
) -> Config:
    root = program.revisions[0].module_path.parents[2]
    if any(revision.module_path.parents[2] != root for revision in program.revisions):
        raise DatabaseGenerationExecutionError("generation program spans multiple roots")
    try:
        ini_path = (root / "alembic.ini").resolve(strict=True)
        script_path = (root / "migrations").resolve(strict=True)
    except OSError as exc:
        raise DatabaseGenerationExecutionError(
            "generation Alembic environment is unavailable"
        ) from exc
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(script_path))
    config.attributes["connection"] = connection
    config.attributes[_MANAGED_JSON_PROTOCOL_ATTRIBUTE] = True
    config.attributes[ALEMBIC_PROGRAM_ATTRIBUTE] = program
    return config


def _read_dataset_identity(
    connection: Connection,
    *,
    required: bool,
    expected_dataset_id: str | None = None,
    expected_restore_epoch: int | None = None,
    expected_installation_id: str | None = None,
    expected_schema_revision: str | None = None,
) -> tuple[str | None, int]:
    has_table = connection.scalar(text("SELECT to_regclass('public.dataset_authority')")) is not None
    if not has_table:
        if (
            required
            or expected_dataset_id is not None
            or expected_restore_epoch is not None
            or expected_installation_id is not None
        ):
            raise DatabaseGenerationExecutionError("dataset_authority is missing")
        return None, 0
    rows = connection.execute(
        text(
            "SELECT dataset_id, client_generation, restore_epoch, schema_revision "
            "FROM public.dataset_authority WHERE singleton_id = 1"
        )
    ).mappings().all()
    if len(rows) != 1:
        raise DatabaseGenerationExecutionError("dataset_authority singleton row is missing")
    row = rows[0]
    dataset_id = str(row["dataset_id"])
    client_generation = str(row["client_generation"])
    restore_epoch = int(row["restore_epoch"])
    schema_revision = str(row["schema_revision"])
    if expected_dataset_id is not None and dataset_id != expected_dataset_id:
        raise DatabaseGenerationExecutionError("live dataset_id does not match upgrade identity")
    if expected_installation_id is not None and client_generation != expected_installation_id:
        raise DatabaseGenerationExecutionError("live installation_id does not match upgrade identity")
    if expected_restore_epoch is not None and restore_epoch != expected_restore_epoch:
        raise DatabaseGenerationExecutionError("live restore_epoch does not match upgrade identity")
    if expected_schema_revision is not None and schema_revision != expected_schema_revision:
        raise DatabaseGenerationExecutionError("live dataset_authority schema_revision drifted")
    return dataset_id, restore_epoch


def _validate_backup_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise DatabaseGenerationExecutionError("backup_archive_sha256 is invalid")
    return value


def _build_attestation(
    *,
    operation_id: str,
    dataset_id: str | None,
    restore_epoch: int,
    source_revision: str,
    target_revision: str,
    backup_archive_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "schema": UPGRADE_ATTESTATION_SCHEMA,
        "operation_id": operation_id,
        "dataset_id": dataset_id,
        "restore_epoch": restore_epoch,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "backup_archive_sha256": backup_archive_sha256,
    }


def _is_valid_optional_sha256(value: object) -> bool:
    return value is None or (isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None)


def _validate_upgrade_attestation_shape(decoded: object) -> dict[str, object]:
    if not isinstance(decoded, dict) or set(decoded) != _ATTESTATION_KEYS:
        raise DatabaseGenerationExecutionError("managed upgrade attestation shape is invalid")
    restore_epoch = decoded.get("restore_epoch")
    dataset_id = decoded.get("dataset_id")
    if (
        decoded.get("schema") != UPGRADE_ATTESTATION_SCHEMA
        or type(restore_epoch) is not int
        or restore_epoch < 0
        or not isinstance(decoded.get("source_revision"), str)
        or not isinstance(decoded.get("target_revision"), str)
        or (dataset_id is not None and not isinstance(dataset_id, str))
        or not _is_valid_optional_sha256(decoded.get("backup_archive_sha256"))
    ):
        raise DatabaseGenerationExecutionError("managed upgrade attestation shape is invalid")
    return decoded


def _read_upgrade_attestation(connection: Connection) -> dict[str, object] | None:
    raw = connection.scalar(
        text("SELECT value FROM public.app_meta WHERE key = :key"),
        {"key": UPGRADE_ATTESTATION_META_KEY},
    )
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise DatabaseGenerationExecutionError("managed upgrade attestation is invalid")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatabaseGenerationExecutionError("managed upgrade attestation is invalid") from exc
    attestation = _validate_upgrade_attestation_shape(decoded)
    validate_generation_operation_id(str(attestation.get("operation_id") or ""))
    return attestation


def _write_upgrade_attestation(
    connection: Connection,
    attestation: dict[str, object],
) -> None:
    encoded = json.dumps(
        attestation,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    connection.execute(
        text(
            "INSERT INTO public.app_meta (key, value, updated_at) "
            "VALUES (:key, :value, :updated_at) "
            "ON CONFLICT (key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
        ),
        {
            "key": UPGRADE_ATTESTATION_META_KEY,
            "value": encoded,
            "updated_at": datetime.now(UTC),
        },
    )


def _seal_if_requested(connection: Connection, *, seal_runtime_authority: bool) -> None:
    if not seal_upgrade_attestation_guard(connection):
        raise DatabaseGenerationExecutionError("upgrade attestation guard could not be sealed")
    if seal_runtime_authority and not seal_runtime_authority_tables(connection):
        raise DatabaseGenerationExecutionError("runtime authority tables are not read-only")


def _execute_same_schema(
    connection: Connection,
    *,
    current: str | None,
    target_step: DatabaseGenerationRevision,
    source_revision: str,
    target_revision: str,
    operation_id: str,
    authority_required: bool,
    expected_dataset_id: str | None,
    expected_restore_epoch: int | None,
    expected_installation_id: str | None,
    seal_runtime_authority: bool,
    backup_archive_sha256: str | None,
) -> bool:
    if current != target_revision:
        raise DatabaseGenerationExecutionError(
            "generation live revision is outside the declared suffix"
        )
    try:
        assert_release_head(connection, expected_revision=target_revision)
    except ReleaseHeadVerificationError as exc:
        raise DatabaseGenerationExecutionError(
            "Alembic did not reach the build-authorized target"
        ) from exc
    _assert_postcondition(connection, target_step)
    dataset_id, restore_epoch = _read_dataset_identity(
        connection,
        required=authority_required,
        expected_dataset_id=expected_dataset_id,
        expected_restore_epoch=expected_restore_epoch,
        expected_installation_id=expected_installation_id,
        expected_schema_revision=target_revision,
    )
    expected = _build_attestation(
        operation_id=operation_id,
        dataset_id=dataset_id,
        restore_epoch=restore_epoch,
        source_revision=source_revision,
        target_revision=target_revision,
        backup_archive_sha256=backup_archive_sha256,
    )
    existing = _read_upgrade_attestation(connection)
    if existing == expected:
        _seal_if_requested(connection, seal_runtime_authority=seal_runtime_authority)
        return False
    if existing is not None and existing["operation_id"] == operation_id:
        raise DatabaseGenerationExecutionError(
            "managed upgrade attestation conflicts with active operation"
        )
    _seal_if_requested(connection, seal_runtime_authority=seal_runtime_authority)
    _write_upgrade_attestation(connection, expected)
    return True


def _verify_interrupted_cross_revision(
    connection: Connection,
    *,
    suffix: tuple[DatabaseGenerationRevision, ...],
    source_revision: str,
    target_revision: str,
    operation_id: str,
    authority_required: bool,
    expected_dataset_id: str | None,
    expected_restore_epoch: int | None,
    expected_installation_id: str | None,
    seal_runtime_authority: bool,
    backup_archive_sha256: str | None,
) -> bool:
    try:
        assert_release_head(connection, expected_revision=target_revision)
    except ReleaseHeadVerificationError as exc:
        raise DatabaseGenerationExecutionError(
            "Alembic did not reach the build-authorized target"
        ) from exc
    for revision in suffix:
        _assert_postcondition(connection, revision)
    dataset_id, restore_epoch = _read_dataset_identity(
        connection,
        required=authority_required,
        expected_dataset_id=expected_dataset_id,
        expected_restore_epoch=expected_restore_epoch,
        expected_installation_id=expected_installation_id,
        expected_schema_revision=target_revision,
    )
    expected = _build_attestation(
        operation_id=operation_id,
        dataset_id=dataset_id,
        restore_epoch=restore_epoch,
        source_revision=source_revision,
        target_revision=target_revision,
        backup_archive_sha256=backup_archive_sha256,
    )
    existing = _read_upgrade_attestation(connection)
    if existing != expected:
        raise DatabaseGenerationExecutionError(
            "target revision lacks matching managed upgrade attestation"
        )
    _seal_if_requested(connection, seal_runtime_authority=seal_runtime_authority)
    return False


def execute_database_generation(
    connection: Connection,
    *,
    program: DatabaseGenerationProgram,
    source_revision: str,
    target_revision: str,
    operation_id: str,
    expected_dataset_id: str | None = None,
    expected_restore_epoch: int | None = None,
    expected_installation_id: str | None = None,
    seal_runtime_authority: bool = False,
    backup_archive_sha256: str | None = None,
) -> bool:
    """Apply the build target through Alembic; return whether work was run."""

    bound_operation_id = validate_generation_operation_id(operation_id)
    bound_backup_sha = _validate_backup_sha256(backup_archive_sha256)
    try:
        suffix = program.suffix(source_revision, target_revision)
        target_step = program.revision(target_revision)
        authority_required = program.revision_includes(
            target_revision,
            _DATASET_AUTHORITY_REVISION,
        )
    except DatabaseGenerationProgramError as exc:
        raise DatabaseGenerationExecutionError(
            "generation suffix is outside the build program"
        ) from exc
    if not connection.in_transaction():
        raise DatabaseGenerationExecutionError(
            "generation execution requires an active caller transaction"
        )
    current = _current_revision(connection)
    if (
        expected_dataset_id is not None
        or expected_restore_epoch is not None
        or expected_installation_id is not None
    ):
        _read_dataset_identity(
            connection,
            required=True,
            expected_dataset_id=expected_dataset_id,
            expected_restore_epoch=expected_restore_epoch,
            expected_installation_id=expected_installation_id,
        )
    if source_revision == target_revision:
        return _execute_same_schema(
            connection,
            current=current,
            target_step=target_step,
            source_revision=source_revision,
            target_revision=target_revision,
            operation_id=bound_operation_id,
            authority_required=authority_required,
            expected_dataset_id=expected_dataset_id,
            expected_restore_epoch=expected_restore_epoch,
            expected_installation_id=expected_installation_id,
            seal_runtime_authority=seal_runtime_authority,
            backup_archive_sha256=bound_backup_sha,
        )
    if current == target_revision:
        return _verify_interrupted_cross_revision(
            connection,
            suffix=suffix,
            source_revision=source_revision,
            target_revision=target_revision,
            operation_id=bound_operation_id,
            authority_required=authority_required,
            expected_dataset_id=expected_dataset_id,
            expected_restore_epoch=expected_restore_epoch,
            expected_installation_id=expected_installation_id,
            seal_runtime_authority=seal_runtime_authority,
            backup_archive_sha256=bound_backup_sha,
        )
    if current != (None if source_revision == BASE_SOURCE else source_revision):
        raise DatabaseGenerationExecutionError(
            "generation live revision is outside the declared suffix"
        )
    config = _alembic_config(connection, program)
    try:
        command.upgrade(config, target_revision)
        assert_release_head(connection, expected_revision=target_revision)
    except (CommandError, ReleaseHeadVerificationError) as exc:
        raise DatabaseGenerationExecutionError(
            "Alembic did not reach the build-authorized target"
        ) from exc
    for revision in suffix:
        _assert_postcondition(connection, revision)
    dataset_id, restore_epoch = _read_dataset_identity(
        connection,
        required=authority_required,
        expected_dataset_id=expected_dataset_id,
        expected_restore_epoch=expected_restore_epoch,
        expected_installation_id=expected_installation_id,
        expected_schema_revision=target_revision,
    )
    _seal_if_requested(connection, seal_runtime_authority=seal_runtime_authority)
    _write_upgrade_attestation(
        connection,
        _build_attestation(
            operation_id=bound_operation_id,
            dataset_id=dataset_id,
            restore_epoch=restore_epoch,
            source_revision=source_revision,
            target_revision=target_revision,
            backup_archive_sha256=bound_backup_sha,
        ),
    )
    return True


__all__ = [
    "DatabaseGenerationExecutionError",
    "UPGRADE_ATTESTATION_META_KEY",
    "UPGRADE_ATTESTATION_SCHEMA",
    "execute_database_generation",
    "validate_generation_operation_id",
]
