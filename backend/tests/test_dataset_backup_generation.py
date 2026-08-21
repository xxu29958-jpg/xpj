"""H2 complete-dataset backup contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.errors import AppError
from app.services.backup_service import (
    CompleteBackupRequest,
    create_complete_backup_generation,
)
from app.services.dataset_authority_service import DatasetAuthority
from app.services.dataset_backup_contract import (
    DATABASE_ARCHIVE_NAME,
    MANIFEST_NAME,
    DatabaseArtifact,
    DatasetBackupManifest,
    encode_manifest,
    read_manifest,
)
from app.services.dataset_originals_adapter import (
    OriginalReference,
    copy_complete_originals,
)


def test_missing_referenced_original_cannot_become_a_complete_generation(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    staging = tmp_path / "generation"
    staging.mkdir()

    with pytest.raises(AppError) as excinfo:
        copy_complete_originals(
            upload_root=uploads.resolve(),
            destination=staging / "originals",
            references=(
                OriginalReference(
                    tenant_id="owner",
                    storage_reference="uploads/owner/2026/08/missing.png",
                    expected_sha256="0" * 64,
                ),
            ),
        )

    assert excinfo.value.error == "backup_incomplete"
    assert not (staging / MANIFEST_NAME).exists()


def test_complete_originals_copy_user_bytes_and_omit_derived_thumbnails(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    original = uploads / "owner" / "2026" / "08" / "receipt.png"
    thumbnail = uploads / "owner" / "2026" / "08" / "thumbs" / "receipt.jpg"
    original.parent.mkdir(parents=True)
    thumbnail.parent.mkdir(parents=True)
    original.write_bytes(b"original-ticketbox-receipt")
    thumbnail.write_bytes(b"derived-cache")
    expected = hashlib.sha256(original.read_bytes()).hexdigest()
    staging = tmp_path / "generation"
    staging.mkdir()

    artifacts = copy_complete_originals(
        upload_root=uploads.resolve(),
        destination=staging / "originals",
        references=(
            OriginalReference(
                tenant_id="owner",
                storage_reference="uploads/owner/2026/08/receipt.png",
                expected_sha256=expected,
            ),
        ),
    )

    assert [item.storage_key for item in artifacts] == ["originals/owner/2026/08/receipt.png"]
    assert artifacts[0].tenant_ids == ("owner",)
    assert (staging / artifacts[0].storage_key).read_bytes() == original.read_bytes()
    assert not (staging / "originals/owner/2026/08/thumbs/receipt.jpg").exists()


def test_complete_originals_reject_corrupt_and_orphan_user_bytes(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    original = uploads / "owner" / "receipt.png"
    orphan = uploads / "owner" / "orphan.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"actual")
    orphan.write_bytes(b"orphan")
    staging = tmp_path / "generation"
    staging.mkdir()

    with pytest.raises(AppError) as corrupt:
        copy_complete_originals(
            upload_root=uploads.resolve(),
            destination=staging / "corrupt-originals",
            references=(
                OriginalReference(
                    tenant_id="owner",
                    storage_reference="uploads/owner/receipt.png",
                    expected_sha256=hashlib.sha256(b"expected").hexdigest(),
                ),
            ),
        )
    assert corrupt.value.error == "backup_incomplete"

    original.write_bytes(b"expected")
    with pytest.raises(AppError) as orphaned:
        copy_complete_originals(
            upload_root=uploads.resolve(),
            destination=staging / "orphan-originals",
            references=(
                OriginalReference(
                    tenant_id="owner",
                    storage_reference="uploads/owner/receipt.png",
                    expected_sha256=hashlib.sha256(b"expected").hexdigest(),
                ),
            ),
        )
    assert orphaned.value.error == "backup_incomplete"


def test_manifest_is_closed_canonical_and_binds_every_byte(tmp_path: Path) -> None:
    generation = tmp_path / "ticketbox-backup-38ed55ba-1dc0-43a4-87b3-b29982958399"
    generation.mkdir()
    database = generation / DATABASE_ARCHIVE_NAME
    database.write_bytes(b"postgres-custom-archive")
    authority = DatasetAuthority(
        dataset_id="5895e71e-1c87-4a59-b1c7-04f68817795e",
        client_generation="bf70f3b2-f2fe-41d9-a694-c0e33208d2b5",
        restore_epoch=3,
        schema_revision="20260821_0001",
        schema_min_compatible="1.2.0",
        semantic_revision="ticketbox-dataset-semantics-v1",
        created_at=datetime(2026, 8, 21, 1, 2, 3, tzinfo=UTC),
        restored_from_backup_id=None,
    )
    manifest = DatasetBackupManifest(
        backup_id="38ed55ba-1dc0-43a4-87b3-b29982958399",
        operation_id="7db00670-2a24-4013-b57f-c6bbff739bf3",
        backup_kind="manual",
        created_at=datetime(2026, 8, 21, 2, 3, 4, tzinfo=UTC),
        release_id="release-fixture",
        writer_fence_sha256="a" * 64,
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        ),
        originals=(),
    )
    encoded = encode_manifest(manifest)
    (generation / MANIFEST_NAME).write_bytes(encoded)

    assert encode_manifest(read_manifest(generation, verify_files=True)) == encoded

    (generation / "unbound-byte.txt").write_bytes(b"not in the manifest")
    with pytest.raises(AppError) as excinfo:
        read_manifest(generation, verify_files=True)
    assert excinfo.value.error == "backup_incomplete"
    (generation / "unbound-byte.txt").unlink()

    database.write_bytes(b"tampered")
    with pytest.raises(AppError) as excinfo:
        read_manifest(generation, verify_files=True)
    assert excinfo.value.error == "backup_incomplete"


def test_published_generation_is_idempotent_for_its_durable_request(tmp_path: Path) -> None:
    backup_id = "38ed55ba-1dc0-43a4-87b3-b29982958399"
    operation_id = "7db00670-2a24-4013-b57f-c6bbff739bf3"
    backup_root = tmp_path / "backups"
    generation = backup_root / f"ticketbox-backup-{backup_id}"
    generation.mkdir(parents=True)
    database = generation / DATABASE_ARCHIVE_NAME
    database.write_bytes(b"postgres-custom-archive")
    authority = DatasetAuthority(
        dataset_id="5895e71e-1c87-4a59-b1c7-04f68817795e",
        client_generation="bf70f3b2-f2fe-41d9-a694-c0e33208d2b5",
        restore_epoch=3,
        schema_revision="20260821_0001",
        schema_min_compatible="1.2.0",
        semantic_revision="ticketbox-dataset-semantics-v1",
        created_at=datetime(2026, 8, 21, 1, 2, 3, tzinfo=UTC),
        restored_from_backup_id=None,
    )
    manifest = DatasetBackupManifest(
        backup_id=backup_id,
        operation_id=operation_id,
        backup_kind="manual",
        created_at=datetime(2026, 8, 21, 2, 3, 4, tzinfo=UTC),
        release_id="release-fixture",
        writer_fence_sha256="a" * 64,
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        ),
        originals=(),
    )
    (generation / MANIFEST_NAME).write_bytes(encode_manifest(manifest))
    request = CompleteBackupRequest(
        backup_root=backup_root,
        upload_root=(tmp_path / "uploads").resolve(),
        database_url="postgresql+psycopg://ticketbox_backup@localhost:5432/ticketbox",
        passfile=(tmp_path / "pgpass").resolve(),
        pg_dump_binary=(tmp_path / "pg_dump.exe").resolve(),
        pg_restore_binary=(tmp_path / "pg_restore.exe").resolve(),
        operation_id=operation_id,
        backup_id=backup_id,
        release_id="release-fixture",
        backup_kind="manual",
        writer_fence_sha256="a" * 64,
    )

    entry = create_complete_backup_generation(request, db=object())  # type: ignore[arg-type]

    assert entry.file_name == generation.name
    assert entry.backup_id == backup_id


def test_backup_preserves_primary_and_lease_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_service

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    generation = backup_root / "ticketbox-backup-38ed55ba-1dc0-43a4-87b3-b29982958399"
    generation.mkdir()
    primary = AppError("backup_incomplete", status_code=500)
    cleanup = RuntimeError("lease cleanup failed")

    class Lease:
        def release(self) -> None:
            raise cleanup

    monkeypatch.setattr(backup_service, "acquire_backup_job_lease", lambda _path: Lease())
    monkeypatch.setattr(backup_service, "read_manifest", lambda *_args, **_kwargs: (_ for _ in ()).throw(primary))
    request = CompleteBackupRequest(
        backup_root=backup_root,
        upload_root=(tmp_path / "uploads").resolve(),
        database_url="postgresql+psycopg://ticketbox_backup@localhost:5432/ticketbox",
        passfile=(tmp_path / "pgpass").resolve(),
        pg_dump_binary=(tmp_path / "pg_dump.exe").resolve(),
        pg_restore_binary=(tmp_path / "pg_restore.exe").resolve(),
        operation_id="7db00670-2a24-4013-b57f-c6bbff739bf3",
        backup_id="38ed55ba-1dc0-43a4-87b3-b29982958399",
        release_id="release-fixture",
        backup_kind="manual",
        writer_fence_sha256="a" * 64,
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        create_complete_backup_generation(request, db=object())  # type: ignore[arg-type]
    assert caught.value.exceptions == (primary, cleanup)
