"""H2 restore identity, attachment, and sanitation contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.services.dataset_authority_service import (
    DATASET_SEMANTIC_REVISION,
    DatasetAuthority,
    read_dataset_authority,
)
from app.services.dataset_backup_contract import (
    DATABASE_ARCHIVE_NAME,
    MANIFEST_NAME,
    DatabaseArtifact,
    DatasetBackupManifest,
    OriginalArtifact,
    encode_manifest,
)
from app.services.dataset_restore_service import (
    finalize_restored_dataset,
    materialize_restored_originals,
    resolve_restored_dataset_plan,
)


def _manifest(tmp_path: Path, *, authority) -> tuple[Path, DatasetBackupManifest]:
    generation = tmp_path / "ticketbox-backup-0b5de24e-bf77-4d7a-814a-5ce680091ff2"
    original = generation / "originals" / "owner" / "2026" / "08" / "receipt.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"restored-original")
    database = generation / DATABASE_ARCHIVE_NAME
    database.write_bytes(b"database-archive")
    manifest = DatasetBackupManifest(
        backup_id="0b5de24e-bf77-4d7a-814a-5ce680091ff2",
        operation_id="79bf3956-69c1-4996-a011-d7a4fc74fa41",
        backup_kind="manual",
        created_at=datetime(2026, 8, 21, 3, 4, 5, tzinfo=UTC),
        release_id="restore-fixture",
        writer_fence_sha256="c" * 64,
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        ),
        originals=(
            OriginalArtifact(
                storage_key="originals/owner/2026/08/receipt.png",
                size_bytes=original.stat().st_size,
                sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                tenant_ids=("owner",),
            ),
        ),
    )
    (generation / MANIFEST_NAME).write_bytes(encode_manifest(manifest))
    return generation, manifest


def _authority() -> DatasetAuthority:
    return DatasetAuthority(
        dataset_id="5895e71e-1c87-4a59-b1c7-04f68817795e",
        restore_epoch=3,
        schema_revision="20260821_0001",
        schema_min_compatible="1.0.0",
        semantic_revision=DATASET_SEMANTIC_REVISION,
        created_at=datetime(2026, 8, 21, 3, 4, 5, tzinfo=UTC),
        restored_from_backup_id=None,
    )


def test_restore_epoch_advances_and_explicit_clone_gets_new_identity(tmp_path: Path) -> None:
    authority = _authority()
    _generation, manifest = _manifest(tmp_path, authority=authority)

    restored = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=authority.dataset_id,
        active_restore_epoch=authority.restore_epoch + 4,
        target_schema_revision=authority.schema_revision,
    )
    assert restored.dataset_id == authority.dataset_id
    assert restored.restore_epoch == authority.restore_epoch + 5
    assert restored.restored_from_backup_id == manifest.backup_id

    cloned = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=authority.dataset_id,
        active_restore_epoch=authority.restore_epoch,
        target_schema_revision=authority.schema_revision,
        clone_dataset_id="cbcaf752-29be-4e5e-be4d-4588d84c5a78",
    )
    assert cloned.dataset_id == "cbcaf752-29be-4e5e-be4d-4588d84c5a78"
    assert cloned.restore_epoch == 0


def test_restore_materializes_originals_into_absent_candidate_root(tmp_path: Path) -> None:
    authority = _authority()
    generation, manifest = _manifest(tmp_path, authority=authority)
    target = tmp_path / "candidate" / "uploads"
    target.parent.mkdir()

    observed = materialize_restored_originals(
        generation,
        target_upload_root=target,
    )

    assert observed == manifest
    assert (target / "owner/2026/08/receipt.png").read_bytes() == b"restored-original"

    retried = materialize_restored_originals(
        generation,
        target_upload_root=target,
    )
    assert retried == manifest


def test_restore_rebuilds_exact_interrupted_originals_staging(tmp_path: Path) -> None:
    authority = _authority()
    generation, manifest = _manifest(tmp_path, authority=authority)
    target = tmp_path / "candidate" / "uploads"
    target.parent.mkdir()
    staging = target.parent / f".uploads-restore-{manifest.backup_id}.staging"
    staging.mkdir()
    (staging / "partial").write_bytes(b"interrupted")

    materialize_restored_originals(generation, target_upload_root=target)

    assert not staging.exists()
    assert (target / "owner/2026/08/receipt.png").read_bytes() == b"restored-original"


@pytest.mark.real_db
def test_restore_finalization_revokes_host_credentials_without_deleting_business_rows(
    tmp_path: Path,
) -> None:
    with SessionLocal() as db:
        authority = read_dataset_authority(db)
    _generation, manifest = _manifest(tmp_path, authority=authority)
    plan = resolve_restored_dataset_plan(
        manifest,
        active_dataset_id=authority.dataset_id,
        active_restore_epoch=authority.restore_epoch,
        target_schema_revision=authority.schema_revision,
    )

    with engine.begin() as connection:
        expense_count = connection.scalar(text("SELECT count(*) FROM expenses"))
        connection.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) VALUES "
                "('csrf_signing_key', 'host-secret', CURRENT_TIMESTAMP), "
                "('database_generation_binding', 'stale-binding', CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
        )
        finalize_restored_dataset(connection, source=manifest, plan=plan)
        finalize_restored_dataset(connection, source=manifest, plan=plan)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM expenses")) == expense_count
        assert connection.scalar(text("SELECT count(*) FROM auth_tokens")) == 0
        assert connection.scalar(text("SELECT count(*) FROM upload_links")) == 0
        assert connection.scalar(text("SELECT count(*) FROM pairing_codes")) == 0
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app_meta WHERE key IN ('csrf_signing_key', 'database_generation_binding')")
            )
            == 0
        )
        restored = (
            connection.execute(
                text(
                    "SELECT dataset_id, restore_epoch, restored_from_backup_id "
                    "FROM dataset_authority WHERE singleton_id = 1"
                )
            )
            .mappings()
            .one()
        )
    assert dict(restored) == {
        "dataset_id": plan.dataset_id,
        "restore_epoch": plan.restore_epoch,
        "restored_from_backup_id": manifest.backup_id,
    }
