"""Single owner for complete Ticketbox dataset backup generations.

Creation is an offline maintenance action. The caller must stop runtime
writers, establish the PostgreSQL writer fence, and pass all tools and
credentials explicitly. HTTP routes are read-only consumers of published
manifests and cannot create a backup from inside the backend service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.database._dataset_backup_snapshot import (
    assert_dataset_database_binding,
    assert_dataset_writers_drained,
    begin_dataset_backup_snapshot,
    read_original_reference_rows,
)
from app.errors import AppError
from app.services.backup_job_lease import acquire_backup_job_lease
from app.services.dataset_authority_service import read_dataset_authority
from app.services.dataset_backup_contract import (
    BACKUP_KINDS,
    DATABASE_ARCHIVE_NAME,
    MANIFEST_NAME,
    ORIGINALS_DIRECTORY_NAME,
    DatabaseArtifact,
    DatasetBackupManifest,
    encode_manifest,
    read_manifest,
    sha256_file,
)
from app.services.dataset_backup_inventory import BackupEntry
from app.services.dataset_backup_inventory_writer import reconcile_published_backup_inventory
from app.services.dataset_originals_adapter import (
    OriginalReference,
    copy_complete_originals,
)
from app.services.durable_publication import publish_durable_tree
from app.services.path_entry_safety import is_link_or_reparse
from app.services.postgres_backup_adapter import write_postgres_archive
from app.services.time_service import now_utc

_GENERATION_PREFIX = "ticketbox-backup-"
_STAGING_PREFIX = ".ticketbox-backup-"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CompleteBackupRequest:
    backup_root: Path
    inventory_path: Path
    upload_root: Path
    database_url: str
    passfile: Path
    pg_dump_binary: Path
    pg_restore_binary: Path
    operation_id: str
    backup_id: str
    release_id: str
    backup_kind: str
    writer_fence_sha256: str
    expected_current_sha256: str
    expected_installation_id: str
    expected_dataset_id: str
    expected_restore_epoch: int
    expected_schema_revision: str


def create_complete_backup_generation(
    request: CompleteBackupRequest,
    *,
    db: Session,
) -> BackupEntry:
    """Publish one all-or-nothing database plus original-attachment generation."""

    validated = _validate_request(request)
    backup_id = validated.backup_id
    generation_name = f"{_GENERATION_PREFIX}{backup_id}"
    staging = validated.backup_root / f"{_STAGING_PREFIX}{backup_id}.staging"
    target = validated.backup_root / generation_name
    lock_path = validated.backup_root / ".backup.lock"
    lease = acquire_backup_job_lease(lock_path)
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    entry: BackupEntry | None = None
    try:
        if staging.exists():
            _remove_staging(staging, validated.backup_root)
        if staging.exists():
            raise AppError("backup_incomplete", status_code=500)
        if target.exists():
            manifest = read_manifest(target, verify_files=True)
            _assert_published_request(manifest, validated)
            entry = _entry(generation_name, manifest)
        else:
            staging.mkdir()
            manifest = _build_staged_generation(
                validated,
                db=db,
                backup_id=backup_id,
                staging=staging,
            )
            (staging / MANIFEST_NAME).write_bytes(encode_manifest(manifest))
            read_manifest(staging, verify_files=True)
            publish_durable_tree(staging, target)
            entry = _entry(generation_name, manifest)
        reconcile_published_backup_inventory(
            backup_root=validated.backup_root,
            inventory_path=validated.inventory_path,
            required_generation=generation_name,
        )
    except BaseException as exc:  # noqa: BLE001 - preserve primary and cleanup truth
        primary = exc
    finally:
        if staging.exists():
            try:
                _remove_staging(staging, validated.backup_root)
            except BaseException as exc:  # noqa: BLE001 - cleanup must not replace primary
                if primary is None:
                    primary = exc
                else:
                    cleanup.append(exc)
        try:
            lease.release()
        except BaseException as exc:  # noqa: BLE001 - cleanup must not replace primary
            if primary is None:
                primary = exc
            else:
                cleanup.append(exc)
    if primary is not None and cleanup:
        raise BaseExceptionGroup(
            "complete dataset backup and cleanup failed",
            [primary, *cleanup],
        ) from primary
    if primary is not None:
        raise primary
    if entry is None:
        raise AppError("backup_incomplete", status_code=500)
    return entry


def _build_staged_generation(
    request: CompleteBackupRequest,
    *,
    db: Session,
    backup_id: str,
    staging: Path,
) -> DatasetBackupManifest:
    synchronized_snapshot = begin_dataset_backup_snapshot(db)
    assert_dataset_database_binding(db, request.database_url)
    assert_dataset_writers_drained(db)
    authority = read_dataset_authority(db)
    if (
        authority.dataset_id != request.expected_dataset_id
        or authority.restore_epoch != request.expected_restore_epoch
        or authority.schema_revision != request.expected_schema_revision
    ):
        raise AppError("backup_incomplete", status_code=409)
    references = tuple(
        OriginalReference(
            tenant_id=tenant_id,
            storage_reference=storage_reference,
            expected_sha256=expected_sha256,
        )
        for tenant_id, storage_reference, expected_sha256 in read_original_reference_rows(db)
    )

    database_path = staging / DATABASE_ARCHIVE_NAME
    write_postgres_archive(
        database_url=request.database_url,
        passfile=request.passfile,
        pg_dump_binary=request.pg_dump_binary,
        pg_restore_binary=request.pg_restore_binary,
        target=database_path,
        synchronized_snapshot=synchronized_snapshot,
    )
    originals = copy_complete_originals(
        upload_root=request.upload_root,
        destination=staging / ORIGINALS_DIRECTORY_NAME,
        references=references,
    )
    assert_dataset_writers_drained(db)
    database_stat = database_path.stat()
    return DatasetBackupManifest(
        backup_id=backup_id,
        operation_id=request.operation_id,
        backup_kind=request.backup_kind,
        created_at=now_utc(),
        release_id=request.release_id,
        source_installation_id=request.expected_installation_id,
        writer_fence_sha256=request.writer_fence_sha256,
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=int(database_stat.st_size),
            sha256=sha256_file(database_path),
        ),
        originals=originals,
    )


def _validate_request(request: CompleteBackupRequest) -> CompleteBackupRequest:
    if (
        request.backup_kind not in BACKUP_KINDS
        or _canonical_uuid(request.operation_id) is None
        or _canonical_uuid(request.backup_id) is None
        or not _plain_text(request.release_id, limit=128)
        or _SHA256.fullmatch(request.writer_fence_sha256) is None
        or _SHA256.fullmatch(request.expected_current_sha256) is None
        or _canonical_uuid(request.expected_installation_id) is None
        or _canonical_uuid(request.expected_dataset_id) is None
        or not isinstance(request.expected_restore_epoch, int)
        or isinstance(request.expected_restore_epoch, bool)
        or request.expected_restore_epoch < 0
        or not _plain_text(request.expected_schema_revision, limit=128)
    ):
        raise AppError("backup_incomplete", status_code=500)
    expected_barrier = hashlib.sha256(
        json.dumps(
            {
                "schema": "ticketbox-dataset-backup-writer-barrier-v1",
                "current_sha256": request.expected_current_sha256,
                "dataset_id": request.expected_dataset_id,
                "restore_epoch": request.expected_restore_epoch,
                "schema_revision": request.expected_schema_revision,
                "backend_service_state": "stopped",
                "other_client_session_count": 0,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if request.writer_fence_sha256 != expected_barrier:
        raise AppError("backup_incomplete", status_code=409)
    backup_root = _prepare_backup_root(request.backup_root)
    for path in (
        request.inventory_path,
        request.upload_root,
        request.passfile,
        request.pg_dump_binary,
        request.pg_restore_binary,
    ):
        if not path.is_absolute():
            raise AppError("backup_incomplete", status_code=500)
    return CompleteBackupRequest(
        backup_root=backup_root,
        inventory_path=request.inventory_path,
        upload_root=request.upload_root,
        database_url=request.database_url,
        passfile=request.passfile,
        pg_dump_binary=request.pg_dump_binary,
        pg_restore_binary=request.pg_restore_binary,
        operation_id=request.operation_id,
        backup_id=request.backup_id,
        release_id=request.release_id,
        backup_kind=request.backup_kind,
        writer_fence_sha256=request.writer_fence_sha256,
        expected_current_sha256=request.expected_current_sha256,
        expected_installation_id=request.expected_installation_id,
        expected_dataset_id=request.expected_dataset_id,
        expected_restore_epoch=request.expected_restore_epoch,
        expected_schema_revision=request.expected_schema_revision,
    )


def _assert_published_request(
    manifest: DatasetBackupManifest,
    request: CompleteBackupRequest,
) -> None:
    if (
        manifest.backup_id != request.backup_id
        or manifest.operation_id != request.operation_id
        or manifest.backup_kind != request.backup_kind
        or manifest.release_id != request.release_id
        or manifest.writer_fence_sha256 != request.writer_fence_sha256
        or manifest.source_installation_id != request.expected_installation_id
        or manifest.authority.dataset_id != request.expected_dataset_id
        or manifest.authority.restore_epoch != request.expected_restore_epoch
        or manifest.authority.schema_revision != request.expected_schema_revision
    ):
        raise AppError("backup_incomplete", status_code=409)


def _prepare_backup_root(path: Path) -> Path:
    if not path.is_absolute() or is_link_or_reparse(path):
        raise AppError("backup_incomplete", status_code=500)
    try:
        parent = path.parent.resolve(strict=True)
        if path.exists():
            resolved = path.resolve(strict=True)
            if not resolved.is_dir() or is_link_or_reparse(resolved):
                raise OSError
        else:
            path.mkdir()
            resolved = path.resolve(strict=True)
        resolved.relative_to(parent)
    except (OSError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    return resolved


def _remove_staging(staging: Path, backup_root: Path) -> None:
    try:
        resolved_root = backup_root.resolve(strict=True)
        lexical = Path(os.path.abspath(staging))
        lexical.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if lexical.parent != resolved_root or not lexical.name.startswith(_STAGING_PREFIX):
        raise AppError("backup_incomplete", status_code=500)
    try:
        shutil.rmtree(lexical)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if lexical.exists():
        raise AppError("backup_incomplete", status_code=500)


def _entry(file_name: str, manifest: DatasetBackupManifest) -> BackupEntry:
    return BackupEntry(
        file_name=file_name,
        backup_id=manifest.backup_id,
        dataset_id=manifest.authority.dataset_id,
        restore_epoch=manifest.authority.restore_epoch,
        size_bytes=manifest.total_size_bytes,
        created_at=manifest.created_at,
        kind=manifest.backup_kind,
    )


def _canonical_uuid(value: str) -> str | None:
    try:
        canonical = str(UUID(value))
    except (ValueError, AttributeError):
        return None
    return canonical if canonical == value else None


def _plain_text(value: str, *, limit: int) -> bool:
    return bool(value) and len(value) <= limit and not any(char in value for char in "\x00\r\n")
