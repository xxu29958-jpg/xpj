"""Plan and materialize one isolated H2 dataset restore candidate."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

from app.errors import AppError
from app.services.dataset_authority_service import DATASET_SEMANTIC_REVISION
from app.services.dataset_backup_contract import DatasetBackupManifest, read_manifest, sha256_file
from app.services.path_entry_safety import is_link_or_reparse


@dataclass(frozen=True)
class RestoredDatasetPlan:
    dataset_id: str
    client_generation: str
    restore_epoch: int
    schema_revision: str
    schema_min_compatible: str
    semantic_revision: str
    restored_from_backup_id: str


@dataclass(frozen=True)
class CompleteRestoreRequest:
    backup_generation: Path
    target_upload_root: Path
    database_url: str
    passfile: Path
    pg_restore_binary: Path
    active_dataset_id: str
    active_restore_epoch: int
    target_schema_revision: str
    restore_role: str


def resolve_restored_dataset_plan(
    manifest: DatasetBackupManifest,
    *,
    active_dataset_id: str,
    active_restore_epoch: int,
    target_schema_revision: str,
) -> RestoredDatasetPlan:
    """Pure identity policy for an in-place restore of the same dataset."""

    active_dataset_id = _canonical_uuid(active_dataset_id)
    if active_restore_epoch < 0 or not target_schema_revision:
        raise AppError("backup_incomplete", status_code=500)
    if manifest.authority.semantic_revision != DATASET_SEMANTIC_REVISION:
        raise AppError("backup_incomplete", status_code=409)
    if active_dataset_id != manifest.authority.dataset_id:
        raise AppError("backup_incomplete", status_code=409)
    dataset_id = manifest.authority.dataset_id
    previous_epoch = max(manifest.authority.restore_epoch, active_restore_epoch)
    restore_epoch = previous_epoch + 1
    return RestoredDatasetPlan(
        dataset_id=dataset_id,
        client_generation=str(
            uuid5(
                UUID(dataset_id),
                f"ticketbox-restore-generation:{restore_epoch}",
            )
        ),
        restore_epoch=restore_epoch,
        schema_revision=target_schema_revision,
        schema_min_compatible=manifest.authority.schema_min_compatible,
        semantic_revision=manifest.authority.semantic_revision,
        restored_from_backup_id=manifest.backup_id,
    )


def materialize_restored_originals(
    backup_generation: Path,
    *,
    target_upload_root: Path,
) -> DatasetBackupManifest:
    """Publish verified original bytes into an absent candidate upload root."""

    manifest = read_manifest(backup_generation, verify_files=True)
    parent = target_upload_root.parent.resolve(strict=True)
    target = Path(os.path.abspath(target_upload_root))
    try:
        target.relative_to(parent)
    except ValueError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if target.parent != parent:
        raise AppError("backup_incomplete", status_code=409)
    if target.exists():
        verify_restored_originals(manifest, backup_generation, target)
        return manifest
    staging = parent / f".uploads-restore-{manifest.backup_id}.staging"
    if staging.exists():
        if not staging.is_dir() or is_link_or_reparse(staging):
            raise AppError("backup_incomplete", status_code=409)
        _remove_staging(staging, parent)
    staging.mkdir()
    try:
        for artifact in manifest.originals:
            relative = Path(*Path(artifact.storage_key).parts[1:])
            source = backup_generation / artifact.storage_key
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination, follow_symlinks=False)
            if destination.stat().st_size != artifact.size_bytes or sha256_file(destination) != artifact.sha256:
                raise AppError("backup_incomplete", status_code=500)
        os.rename(staging, target)
    except BaseException as primary:  # noqa: BLE001 - preserve primary and cleanup truth
        try:
            _remove_staging(staging, parent)
        except BaseException as cleanup:  # noqa: BLE001 - cleanup must not replace primary
            raise BaseExceptionGroup(
                "restored originals materialization and cleanup failed",
                [primary, cleanup],
            ) from primary
        raise
    return manifest


def _canonical_uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if canonical != value:
        raise AppError("backup_incomplete", status_code=500)
    return canonical


def verify_restored_originals(
    manifest: DatasetBackupManifest,
    backup_generation: Path,
    target: Path,
) -> None:
    if not target.is_dir() or is_link_or_reparse(target):
        raise AppError("backup_incomplete", status_code=409)
    expected: set[Path] = set()
    for artifact in manifest.originals:
        relative = Path(*Path(artifact.storage_key).parts[1:])
        expected.add(relative)
        restored = target / relative
        if (
            not restored.is_file()
            or is_link_or_reparse(restored)
            or restored.stat().st_size != artifact.size_bytes
            or sha256_file(restored) != artifact.sha256
            or sha256_file(backup_generation / artifact.storage_key) != artifact.sha256
        ):
            raise AppError("backup_incomplete", status_code=409)
    try:
        entries = tuple(target.rglob("*"))
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=409) from exc
    if any(is_link_or_reparse(path) or not (path.is_file() or path.is_dir()) for path in entries):
        raise AppError("backup_incomplete", status_code=409)
    observed = {path.relative_to(target) for path in entries if path.is_file()}
    if observed != expected:
        raise AppError("backup_incomplete", status_code=409)


def _remove_staging(path: Path, parent: Path) -> None:
    lexical = Path(os.path.abspath(path))
    if lexical.parent != parent or not lexical.name.startswith(".uploads-restore-"):
        raise AppError("backup_incomplete", status_code=500)
    if not lexical.exists():
        return
    try:
        shutil.rmtree(lexical)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if lexical.exists():
        raise AppError("backup_incomplete", status_code=500)
