"""Offline existing-dataset upgrade on a caller-owned PostgreSQL transaction."""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.database._database_generation_executor import (
    DatabaseGenerationExecutionError,
    validate_generation_operation_id,
)
from app.database._database_generation_program import (
    BASE_SOURCE,
    DatabaseGenerationProgram,
    DatabaseGenerationProgramError,
    DatabaseGenerationRevision,
    load_installed_database_generation_program,
)
from app.database._existing_dataset_upgrade_archive import _VerifiedBackupArchive
from app.database._existing_dataset_upgrade_archive_rules import (
    ExistingDatasetUpgradeError,
    _is_nonnegative_int,
    _require_sha256,
)
from app.database._existing_dataset_upgrade_originals import (
    _verify_snapshot_original,
    _verify_upgrade_originals,
)
from app.database._managed_postgres_contract import (
    DATABASE_NAME,
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
    ManagedPostgresMigrationRuntimeV1,
    ManagedPostgresRuntimeContractV1,
)

RESULT_SCHEMA = "ticketbox-existing-dataset-upgrade-result-v1"
_ALEMBIC_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
_TRANSACTION_TIMEOUT_MS = 20 * 60 * 1000


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ExistingDatasetUpgradeError(f"{label} is not a UUID") from exc
    if value != canonical:
        raise ExistingDatasetUpgradeError(f"{label} is not canonical")
    return canonical


def _require_revision(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _ALEMBIC_REVISION.fullmatch(value) is None:
        raise ExistingDatasetUpgradeError(f"{label} is not an Alembic revision")
    return value


def _postcondition(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ExistingDatasetUpgradeError(f"cannot parse migration {path.name}") from exc
    return (
        "assert_postcondition"
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "assert_postcondition"
            for node in tree.body
        )
        else None
    )


def _load_source_generation_program() -> DatabaseGenerationProgram:
    root = Path(__file__).resolve().parents[2].resolve(strict=True)
    versions_root = (root / "migrations" / "versions").resolve(strict=True)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    heads = tuple(scripts.get_heads())
    bases = tuple(scripts.get_bases())
    if len(heads) != 1 or len(bases) != 1:
        raise ExistingDatasetUpgradeError("source migrations do not have one base and head")
    target = heads[0]
    forward = tuple(reversed(tuple(scripts.iterate_revisions(target, "base"))))
    previous: str | None = None
    revisions: list[DatabaseGenerationRevision] = []
    digest = hashlib.sha256()
    for item in forward:
        module_path = Path(str(item.path)).resolve(strict=True)
        if module_path.parent != versions_root or item.down_revision != previous or item.dependencies is not None:
            raise ExistingDatasetUpgradeError("source migrations are not one linear chain")
        raw = module_path.read_bytes()
        module_sha = hashlib.sha256(raw).hexdigest()
        digest.update(f"{item.revision}:{module_sha}\n".encode("ascii"))
        revisions.append(
            DatabaseGenerationRevision(
                revision=str(item.revision),
                down_revision=previous,
                module_path=module_path,
                module_sha256=module_sha,
                postcondition=_postcondition(module_path),
            )
        )
        previous = str(item.revision)
    if not revisions or previous != target or revisions[-1].postcondition != "assert_postcondition":
        raise ExistingDatasetUpgradeError("source migrations do not end in a qualified head")
    return DatabaseGenerationProgram(
        path=root / "alembic.ini",
        payload_sha256=digest.hexdigest(),
        source_revision=BASE_SOURCE,
        target_revision=target,
        revisions=tuple(revisions),
    )


def _resolve_program(program: DatabaseGenerationProgram | None) -> DatabaseGenerationProgram:
    if program is not None:
        return program
    if getattr(sys, "frozen", False):
        try:
            return load_installed_database_generation_program()
        except DatabaseGenerationProgramError as exc:
            raise ExistingDatasetUpgradeError(str(exc)) from exc
    return _load_source_generation_program()


def _require_absolute_path(value: object, *, message: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ExistingDatasetUpgradeError(message)
    return value


def run_existing_dataset_upgrade_action(
    *,
    database_url: str,
    pgpassfile: Path,
    source_revision: str,
    target_revision: str,
    dataset_id: str,
    installation_id: str,
    expected_restore_epoch: int,
    operation_id: str,
    data_root: Path | None = None,
    backup_archive: Path | None = None,
    backup_archive_sha256: str | None = None,
    app_dir: Path | None = None,
    program: DatabaseGenerationProgram | None = None,
    contract: ManagedPostgresRuntimeContractV1 | None = None,
    seal_runtime_authority: bool = True,
    machine_secret: bool = True,
) -> dict[str, object]:
    bound_dataset_id = _canonical_uuid(dataset_id, label="dataset_id")
    bound_installation_id = _canonical_uuid(installation_id, label="installation_id")
    if not _is_nonnegative_int(expected_restore_epoch):
        raise ExistingDatasetUpgradeError("expected_restore_epoch is invalid")
    source = _require_revision(source_revision, label="source_revision")
    target = _require_revision(target_revision, label="target_revision")
    try:
        bound_operation_id = validate_generation_operation_id(operation_id)
    except DatabaseGenerationExecutionError as exc:
        raise ExistingDatasetUpgradeError(str(exc)) from exc
    bound_pgpass = _require_absolute_path(pgpassfile, message="pgpass path must be absolute")
    bound_data_root = _require_absolute_path(data_root, message="data_root must be an absolute path")
    bound_backup_archive = _require_absolute_path(backup_archive, message="backup_archive must be an absolute path")
    bound_app_dir = (
        _require_absolute_path(app_dir, message="app_dir must be an absolute path")
        if app_dir is not None
        else None
    )
    bound_backup_sha = _require_sha256(backup_archive_sha256, label="backup_archive_sha256")
    resolved_program = _resolve_program(program)
    if target != resolved_program.target_revision:
        raise ExistingDatasetUpgradeError("target_revision differs from the packaged generation program")
    effective_contract = contract or ManagedPostgresRuntimeContractV1(
        database_name=DATABASE_NAME,
        migrator_role=MIGRATOR_ROLE,
        schema_owner_role=SCHEMA_OWNER_ROLE,
        lease_label=MIGRATION_LEASE_LABEL,
        transaction_timeout_ms=_TRANSACTION_TIMEOUT_MS,
    )
    try:
        outcome = ManagedPostgresMigrationRuntimeV1(effective_contract).run(
            database_url=database_url,
            pgpassfile=bound_pgpass,
            program=resolved_program,
            source_revision=source,
            target_revision=target,
            generation_operation_id=bound_operation_id,
            expected_dataset_id=bound_dataset_id,
            expected_restore_epoch=expected_restore_epoch,
            expected_installation_id=bound_installation_id,
            seal_runtime_authority=seal_runtime_authority,
            machine_secret=machine_secret,
            backup_archive_sha256=bound_backup_sha,
            pre_migration_check=lambda connection: _verify_upgrade_originals(
                connection,
                data_root=bound_data_root,
                backup_archive=bound_backup_archive,
                backup_archive_sha256=bound_backup_sha,
                dataset_id=bound_dataset_id,
                installation_id=bound_installation_id,
                expected_restore_epoch=expected_restore_epoch,
                source_revision=source,
                app_dir=bound_app_dir,
            ),
        )
    except ManagedPostgresMigrationRuntimeError as exc:
        raise ExistingDatasetUpgradeError(str(exc)) from exc
    return {
        "schema": RESULT_SCHEMA,
        "operation_id": bound_operation_id,
        "dataset_id": bound_dataset_id,
        "installation_id": bound_installation_id,
        "restore_epoch": expected_restore_epoch,
        "source_revision": source,
        "target_revision": target,
        "alembic_revision": target,
        "backup_archive_sha256": bound_backup_sha,
        "result": outcome,
    }


__all__ = [
    "ExistingDatasetUpgradeError",
    "RESULT_SCHEMA",
    "_VerifiedBackupArchive",
    "_verify_snapshot_original",
    "_verify_upgrade_originals",
    "run_existing_dataset_upgrade_action",
]
