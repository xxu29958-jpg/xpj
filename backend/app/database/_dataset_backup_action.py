"""One-shot adapter from the frozen maintenance helper to the H2 backup owner."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.database._managed_postgres_contract import (
    BACKUP_ROLE,
    DATABASE_NAME,
)
from app.database._managed_postgres_migration_runtime import (
    _create_engine,
    _temporary_pgpass_environment,
)
from app.database._managed_postgres_url import validated_local_role_url
from app.database._postgres_operation_failures import (
    close_postgres_owner_resources,
    raise_postgres_operation_failures,
)
from app.services.backup_service import (
    CompleteBackupRequest,
    create_complete_backup_generation,
)
from app.services.dataset_backup_contract import MANIFEST_NAME, read_manifest, sha256_file
from app.services.secure_file import hold_protected_file_for_read

RESULT_FIELDS = (
    "schema",
    "backup_id",
    "generation",
    "dataset_id",
    "restore_epoch",
    "size_bytes",
)
INSPECTION_FIELDS = (
    "schema",
    "backup_id",
    "generation",
    "dataset_id",
    "restore_epoch",
    "schema_revision",
    "release_id",
    "manifest_sha256",
    "original_count",
)


def inspect_complete_dataset_backup_action(generation: Path) -> dict[str, object]:
    manifest = read_manifest(generation, verify_files=True)
    return {
        "schema": "ticketbox-complete-dataset-backup-inspection-v1",
        "backup_id": manifest.backup_id,
        "generation": generation.name,
        "dataset_id": manifest.authority.dataset_id,
        "restore_epoch": manifest.authority.restore_epoch,
        "schema_revision": manifest.authority.schema_revision,
        "release_id": manifest.release_id,
        "manifest_sha256": sha256_file(generation / MANIFEST_NAME),
        "original_count": len(manifest.originals),
    }


def run_complete_dataset_backup_action(request: CompleteBackupRequest) -> dict[str, object]:
    parsed_url = validated_local_role_url(
        request.database_url,
        database_name=DATABASE_NAME,
        role=BACKUP_ROLE,
        purpose="complete dataset backup",
    )
    engine = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    entered: list[AbstractContextManager[Any]] = []
    result: dict[str, object] | None = None
    try:
        protected = hold_protected_file_for_read(request.passfile)
        protected_passfile = protected.__enter__()
        entered.append(protected)
        environment = _temporary_pgpass_environment(protected_passfile)
        environment.__enter__()
        entered.append(environment)
        engine = _create_engine(parsed_url)
        connection_context = engine.connect()
        connection = connection_context.__enter__()
        entered.append(connection_context)
        session_context = Session(bind=connection, future=True)
        db = session_context.__enter__()
        entered.append(session_context)
        entry = create_complete_backup_generation(request, db=db)
        result = {
            "schema": "ticketbox-complete-dataset-backup-result-v1",
            "backup_id": entry.backup_id,
            "generation": entry.file_name,
            "dataset_id": entry.dataset_id,
            "restore_epoch": entry.restore_epoch,
            "size_bytes": entry.size_bytes,
        }
    except BaseException as exc:  # noqa: BLE001 - owner boundary preserves primary failure
        primary = exc
    finally:
        primary = close_postgres_owner_resources(
            contexts=entered,
            engine=engine,
            primary=primary,
            cleanup=cleanup,
        )
    raise_postgres_operation_failures(
        primary=primary,
        cleanup=cleanup,
        message="complete dataset backup action failed",
    )
    if result is None:
        raise RuntimeError("complete dataset backup action returned no result")
    return result


__all__ = [
    "INSPECTION_FIELDS",
    "RESULT_FIELDS",
    "inspect_complete_dataset_backup_action",
    "run_complete_dataset_backup_action",
]
