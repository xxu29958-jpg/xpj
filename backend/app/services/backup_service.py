"""Single owner for complete Ticketbox dataset backup generations.

Creation is an offline maintenance action. The caller must stop runtime
writers, establish the PostgreSQL writer fence, and pass all tools and
credentials explicitly. HTTP routes are read-only consumers of published
manifests and cannot create a backup from inside the backend service.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from app.config import DATA_ROOT
from app.errors import AppError
from app.models import Expense
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
from app.services.dataset_originals_adapter import (
    OriginalReference,
    copy_complete_originals,
)
from app.services.postgres_backup_adapter import write_postgres_archive
from app.services.time_service import now_utc

_BACKUP_DIR = (
    DATA_ROOT.parent / "backups"
    if os.environ.get("TICKETBOX_DATA_ROOT_MARKER_PATH", "").strip()
    else DATA_ROOT / "backups"
)
_GENERATION_PREFIX = "ticketbox-backup-"
_STAGING_PREFIX = ".ticketbox-backup-"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CompleteBackupRequest:
    backup_root: Path
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


@dataclass(frozen=True)
class BackupEntry:
    file_name: str
    backup_id: str
    dataset_id: str
    restore_epoch: int
    size_bytes: int
    created_at: datetime
    kind: str


@dataclass(frozen=True)
class BackupHealth:
    latest: BackupEntry | None
    age_hours: int | None
    stale: bool


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
    try:
        if staging.exists():
            _remove_staging(staging, validated.backup_root)
        if staging.exists():
            raise AppError("backup_incomplete", status_code=500)
        if target.exists():
            manifest = read_manifest(target, verify_files=True)
            _assert_published_request(manifest, validated)
            return _entry(generation_name, manifest)
        staging.mkdir()
        try:
            manifest = _build_staged_generation(
                validated,
                db=db,
                backup_id=backup_id,
                staging=staging,
            )
            (staging / MANIFEST_NAME).write_bytes(encode_manifest(manifest))
            read_manifest(staging, verify_files=True)
            os.rename(staging, target)
        except Exception:
            _remove_staging(staging, validated.backup_root)
            raise
    finally:
        lease.release()
    return _entry(generation_name, manifest)


def list_backups() -> list[BackupEntry]:
    entries: list[BackupEntry] = []
    for path in _existing_backup_root().glob(f"{_GENERATION_PREFIX}*"):
        if not path.is_dir():
            continue
        try:
            manifest = read_manifest(path, verify_files=True)
        except AppError:
            continue
        entries.append(_entry(path.name, manifest))
    entries.sort(key=lambda item: item.created_at, reverse=True)
    return entries


def latest_backup() -> BackupEntry | None:
    entries = list_backups()
    return entries[0] if entries else None


def backup_health(*, stale_after_hours: int = 48) -> BackupHealth:
    entry = latest_backup()
    if entry is None:
        return BackupHealth(latest=None, age_hours=None, stale=True)
    age_hours = int((now_utc() - entry.created_at).total_seconds() // 3600)
    return BackupHealth(
        latest=entry,
        age_hours=age_hours,
        stale=age_hours >= stale_after_hours,
    )


def is_backup_valid(file_name: str) -> bool:
    if Path(file_name).name != file_name or not file_name.startswith(_GENERATION_PREFIX):
        return False
    try:
        read_manifest(_existing_backup_root() / file_name, verify_files=True)
    except AppError:
        return False
    return True


def backup_directory_label() -> str:
    return f"{_BACKUP_DIR.parent.name}\\{_BACKUP_DIR.name}"


def _build_staged_generation(
    request: CompleteBackupRequest,
    *,
    db: Session,
    backup_id: str,
    staging: Path,
) -> DatasetBackupManifest:
    _begin_read_only_snapshot(db)
    _assert_database_binding(db, request.database_url)
    _assert_writers_drained(db)
    authority = read_dataset_authority(db)
    references = _original_references(db)

    database_path = staging / DATABASE_ARCHIVE_NAME
    write_postgres_archive(
        database_url=request.database_url,
        passfile=request.passfile,
        pg_dump_binary=request.pg_dump_binary,
        pg_restore_binary=request.pg_restore_binary,
        target=database_path,
    )
    originals = copy_complete_originals(
        upload_root=request.upload_root,
        destination=staging / ORIGINALS_DIRECTORY_NAME,
        references=references,
    )
    _assert_writers_drained(db)
    database_stat = database_path.stat()
    return DatasetBackupManifest(
        backup_id=backup_id,
        operation_id=request.operation_id,
        backup_kind=request.backup_kind,
        created_at=now_utc(),
        release_id=request.release_id,
        writer_fence_sha256=request.writer_fence_sha256,
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=int(database_stat.st_size),
            sha256=sha256_file(database_path),
        ),
        originals=originals,
    )


def _begin_read_only_snapshot(db: Session) -> None:
    try:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE, READ ONLY, DEFERRABLE"))
    except Exception as exc:
        raise AppError("backup_incomplete", status_code=500) from exc


def _assert_writers_drained(db: Session) -> None:
    others = db.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND backend_type = 'client backend' "
            "AND pid <> pg_backend_pid()"
        )
    )
    if others != 0:
        raise AppError("backup_incomplete", status_code=409)


def _assert_database_binding(db: Session, database_url: str) -> None:
    try:
        expected = make_url(database_url).database
    except (ArgumentError, TypeError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not expected or db.scalar(text("SELECT current_database()")) != expected:
        raise AppError("backup_incomplete", status_code=500)


def _original_references(db: Session) -> tuple[OriginalReference, ...]:
    rows = db.execute(
        select(Expense.tenant_id, Expense.image_path, Expense.image_hash)
        .where(Expense.image_path.is_not(None))
        .where(Expense.image_deleted_at.is_(None))
        .order_by(Expense.tenant_id, Expense.image_path)
    ).all()
    return tuple(
        OriginalReference(
            tenant_id=str(row.tenant_id),
            storage_reference=str(row.image_path),
            expected_sha256=None if row.image_hash is None else str(row.image_hash),
        )
        for row in rows
    )


def _validate_request(request: CompleteBackupRequest) -> CompleteBackupRequest:
    if (
        request.backup_kind not in BACKUP_KINDS
        or _canonical_uuid(request.operation_id) is None
        or _canonical_uuid(request.backup_id) is None
        or not _plain_text(request.release_id, limit=128)
        or _SHA256.fullmatch(request.writer_fence_sha256) is None
    ):
        raise AppError("backup_incomplete", status_code=500)
    backup_root = _prepare_backup_root(request.backup_root)
    for path in (
        request.upload_root,
        request.passfile,
        request.pg_dump_binary,
        request.pg_restore_binary,
    ):
        if not path.is_absolute():
            raise AppError("backup_incomplete", status_code=500)
    return CompleteBackupRequest(
        backup_root=backup_root,
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
    ):
        raise AppError("backup_incomplete", status_code=409)


def _prepare_backup_root(path: Path) -> Path:
    if not path.is_absolute():
        raise AppError("backup_incomplete", status_code=500)
    try:
        parent = path.parent.resolve(strict=True)
        if path.exists():
            resolved = path.resolve(strict=True)
            if not resolved.is_dir() or resolved.is_symlink():
                raise OSError
        else:
            path.mkdir()
            resolved = path.resolve(strict=True)
        resolved.relative_to(parent)
    except (OSError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    return resolved


def _existing_backup_root() -> Path:
    try:
        if _BACKUP_DIR.is_dir() and not _BACKUP_DIR.is_symlink():
            return _BACKUP_DIR.resolve(strict=True)
    except OSError:
        pass
    return _BACKUP_DIR


def _remove_staging(staging: Path, backup_root: Path) -> None:
    try:
        resolved_root = backup_root.resolve(strict=True)
        lexical = Path(os.path.abspath(staging))
        lexical.relative_to(resolved_root)
    except (OSError, ValueError):
        return
    if lexical.parent != resolved_root or not lexical.name.startswith(_STAGING_PREFIX):
        return
    with contextlib.suppress(OSError):
        shutil.rmtree(lexical)


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
