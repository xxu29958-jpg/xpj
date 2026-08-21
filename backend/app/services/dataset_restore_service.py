"""Plan and materialize one isolated H2 dataset restore candidate."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Connection, text

from app.errors import AppError
from app.services.dataset_authority_service import DATASET_SEMANTIC_REVISION
from app.services.dataset_backup_contract import DatasetBackupManifest, read_manifest, sha256_file

_SANITATION_TABLES = (
    "desktop_activation_attempts",
    "session_refresh_attempts",
    "auth_tokens",
    "device_enrollment_attempts",
    "installation_owner_claims",
    "bootstrap_secret_consumptions",
    "upload_link_daily_usage",
    "upload_link_remote_attempts",
    "upload_links",
    "pairing_attempt_failures",
    "pairing_codes",
    "invitations",
    "installation_idempotency_keys",
    "scheduler_leases",
    "budget_advisor_quota_locks",
    "ai_transaction_temp_id_map",
)


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
    clone_dataset_id: str | None = None


def resolve_restored_dataset_plan(
    manifest: DatasetBackupManifest,
    *,
    active_dataset_id: str,
    active_restore_epoch: int,
    target_schema_revision: str,
    clone_dataset_id: str | None = None,
) -> RestoredDatasetPlan:
    """Pure identity policy for restore versus explicit clone."""

    _canonical_uuid(active_dataset_id)
    if active_restore_epoch < 0 or not target_schema_revision:
        raise AppError("backup_incomplete", status_code=500)
    if manifest.authority.semantic_revision != DATASET_SEMANTIC_REVISION:
        raise AppError("backup_incomplete", status_code=409)
    if clone_dataset_id is not None:
        dataset_id = _canonical_uuid(clone_dataset_id)
        if dataset_id == manifest.authority.dataset_id:
            raise AppError("backup_incomplete", status_code=409)
        restore_epoch = 0
    else:
        dataset_id = manifest.authority.dataset_id
        previous_epoch = manifest.authority.restore_epoch
        if active_dataset_id == dataset_id:
            previous_epoch = max(previous_epoch, active_restore_epoch)
        restore_epoch = previous_epoch + 1
    return RestoredDatasetPlan(
        dataset_id=dataset_id,
        client_generation=str(
            uuid5(
                NAMESPACE_URL,
                f"https://ticketbox.local/dataset/{dataset_id}/restore/{restore_epoch}",
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
        _verify_restored_originals(manifest, backup_generation, target)
        return manifest
    staging = parent / f".uploads-restore-{manifest.backup_id}.staging"
    if staging.exists():
        if not staging.is_dir() or staging.is_symlink():
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


def assert_restored_dataset_candidate(
    connection: Connection,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> None:
    """Accept only the source snapshot or this request's finalized candidate."""

    observed = (
        connection.execute(
            text(
                "SELECT dataset_id, restore_epoch, schema_revision, "
                "client_generation, schema_min_compatible, semantic_revision, restored_from_backup_id "
                "FROM dataset_authority WHERE singleton_id = 1"
            )
        )
        .mappings()
        .one()
    )
    if dict(observed) not in (
        _source_authority_shape(source),
        _planned_authority_shape(plan),
    ):
        raise AppError("backup_incomplete", status_code=409)


def finalize_restored_dataset(
    connection: Connection,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> None:
    """Sanitize host credentials and publish Dataset Authority in one DB transaction."""

    alembic_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if alembic_revision != plan.schema_revision:
        raise AppError("backup_incomplete", status_code=409)
    observed = (
        connection.execute(
            text(
                "SELECT dataset_id, restore_epoch, schema_revision, "
                "client_generation, schema_min_compatible, semantic_revision, restored_from_backup_id "
                "FROM dataset_authority WHERE singleton_id = 1 FOR UPDATE"
            )
        )
        .mappings()
        .one()
    )
    if dict(observed) == _planned_authority_shape(plan):
        return
    if dict(observed) != _source_authority_shape(source):
        raise AppError("backup_incomplete", status_code=409)
    for table in _SANITATION_TABLES:
        connection.execute(text(f'DELETE FROM "{table}"'))
    connection.execute(
        text(
            "DELETE FROM app_meta WHERE key IN "
            "('csrf_signing_key', 'database_generation_binding', 'budget_advisor_audit_key')"
        )
    )
    connection.execute(
        text(
            "UPDATE dataset_authority SET dataset_id = :dataset_id, "
            "client_generation = :client_generation, restore_epoch = :restore_epoch, "
            "schema_revision = :schema_revision, "
            "schema_min_compatible = :schema_min_compatible, "
            "semantic_revision = :semantic_revision, "
            "restored_from_backup_id = :backup_id WHERE singleton_id = 1"
        ),
        {
            "dataset_id": plan.dataset_id,
            "client_generation": plan.client_generation,
            "restore_epoch": plan.restore_epoch,
            "schema_revision": plan.schema_revision,
            "schema_min_compatible": plan.schema_min_compatible,
            "semantic_revision": plan.semantic_revision,
            "backup_id": plan.restored_from_backup_id,
        },
    )


def _canonical_uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if canonical != value:
        raise AppError("backup_incomplete", status_code=500)
    return canonical


def _source_authority_shape(source: DatasetBackupManifest) -> dict[str, object]:
    authority = source.authority
    return {
        "dataset_id": authority.dataset_id,
        "client_generation": authority.client_generation,
        "restore_epoch": authority.restore_epoch,
        "schema_revision": authority.schema_revision,
        "schema_min_compatible": authority.schema_min_compatible,
        "semantic_revision": authority.semantic_revision,
        "restored_from_backup_id": authority.restored_from_backup_id,
    }


def _planned_authority_shape(plan: RestoredDatasetPlan) -> dict[str, object]:
    return {
        "dataset_id": plan.dataset_id,
        "client_generation": plan.client_generation,
        "restore_epoch": plan.restore_epoch,
        "schema_revision": plan.schema_revision,
        "schema_min_compatible": plan.schema_min_compatible,
        "semantic_revision": plan.semantic_revision,
        "restored_from_backup_id": plan.restored_from_backup_id,
    }


def _verify_restored_originals(
    manifest: DatasetBackupManifest,
    backup_generation: Path,
    target: Path,
) -> None:
    if not target.is_dir() or target.is_symlink():
        raise AppError("backup_incomplete", status_code=409)
    expected: set[Path] = set()
    for artifact in manifest.originals:
        relative = Path(*Path(artifact.storage_key).parts[1:])
        expected.add(relative)
        restored = target / relative
        if (
            not restored.is_file()
            or restored.is_symlink()
            or restored.stat().st_size != artifact.size_bytes
            or sha256_file(restored) != artifact.sha256
            or sha256_file(backup_generation / artifact.storage_key) != artifact.sha256
        ):
            raise AppError("backup_incomplete", status_code=409)
    try:
        entries = tuple(target.rglob("*"))
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=409) from exc
    if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in entries):
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
