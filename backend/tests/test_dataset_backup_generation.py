"""H2 complete-dataset backup contracts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
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

_EXPECTED_DATASET_ID = "5895e71e-1c87-4a59-b1c7-04f68817795e"
_EXPECTED_RESTORE_EPOCH = 3
_EXPECTED_SCHEMA_REVISION = "20260821_0001"
_EXPECTED_CURRENT_SHA256 = "c" * 64
_EXPECTED_INSTALLATION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_EXPECTED_WRITER_FENCE_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "schema": "ticketbox-dataset-backup-writer-barrier-v1",
            "current_sha256": _EXPECTED_CURRENT_SHA256,
            "dataset_id": _EXPECTED_DATASET_ID,
            "restore_epoch": _EXPECTED_RESTORE_EPOCH,
            "schema_revision": _EXPECTED_SCHEMA_REVISION,
            "backend_service_state": "stopped",
            "other_client_session_count": 0,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


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
    orphan.write_bytes(b"orphan")
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


@pytest.mark.parametrize("expected_sha256", [None, "not-a-sha256"])
def test_complete_originals_require_a_closed_database_digest(
    tmp_path: Path,
    expected_sha256: str | None,
) -> None:
    uploads = tmp_path / "uploads"
    original = uploads / "owner" / "receipt.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original")
    destination = tmp_path / "generation" / "originals"
    destination.parent.mkdir()

    with pytest.raises(AppError) as rejected:
        copy_complete_originals(
            upload_root=uploads.resolve(),
            destination=destination,
            references=(
                OriginalReference(
                    tenant_id="owner",
                    storage_reference="uploads/owner/receipt.png",
                    expected_sha256=expected_sha256,
                ),
            ),
        )
    assert rejected.value.error == "backup_incomplete"


def test_manifest_is_closed_canonical_and_binds_every_byte(tmp_path: Path) -> None:
    generation = tmp_path / "ticketbox-backup-38ed55ba-1dc0-43a4-87b3-b29982958399"
    generation.mkdir()
    database = generation / DATABASE_ARCHIVE_NAME
    database.write_bytes(b"postgres-custom-archive")
    authority = DatasetAuthority(
        dataset_id=_EXPECTED_DATASET_ID,
        client_generation="bf70f3b2-f2fe-41d9-a694-c0e33208d2b5",
        restore_epoch=_EXPECTED_RESTORE_EPOCH,
        schema_revision=_EXPECTED_SCHEMA_REVISION,
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
        source_installation_id=_EXPECTED_INSTALLATION_ID,
        writer_fence_sha256=_EXPECTED_WRITER_FENCE_SHA256,
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
        source_installation_id=_EXPECTED_INSTALLATION_ID,
        writer_fence_sha256=_EXPECTED_WRITER_FENCE_SHA256,
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
        inventory_path=(tmp_path / "backup-inventory.json").resolve(),
        upload_root=(tmp_path / "uploads").resolve(),
        database_url="postgresql+psycopg://ticketbox_backup@localhost:5432/ticketbox",
        passfile=(tmp_path / "pgpass").resolve(),
        pg_dump_binary=(tmp_path / "pg_dump.exe").resolve(),
        pg_restore_binary=(tmp_path / "pg_restore.exe").resolve(),
        operation_id=operation_id,
        backup_id=backup_id,
        release_id="release-fixture",
        backup_kind="manual",
        writer_fence_sha256=_EXPECTED_WRITER_FENCE_SHA256,
        expected_current_sha256=_EXPECTED_CURRENT_SHA256,
        expected_installation_id=_EXPECTED_INSTALLATION_ID,
        expected_dataset_id=authority.dataset_id,
        expected_restore_epoch=authority.restore_epoch,
        expected_schema_revision=authority.schema_revision,
    )

    entry = create_complete_backup_generation(request, db=object())  # type: ignore[arg-type]

    assert entry.file_name == generation.name
    assert entry.backup_id == backup_id

    with pytest.raises(AppError) as drifted:
        create_complete_backup_generation(
            replace(request, expected_restore_epoch=authority.restore_epoch + 1),
            db=object(),  # type: ignore[arg-type]
        )
    assert drifted.value.error == "backup_incomplete"
    assert drifted.value.status_code == 409

    with pytest.raises(AppError) as wrong_current:
        create_complete_backup_generation(
            replace(request, expected_current_sha256="d" * 64),
            db=object(),  # type: ignore[arg-type]
        )
    assert wrong_current.value.error == "backup_incomplete"
    assert wrong_current.value.status_code == 409


def test_backup_root_rejects_a_direct_directory_symlink_before_resolving() -> None:
    from app.services.backup_service import _prepare_backup_root

    class DirectDirectorySymlink:
        def is_absolute(self) -> bool:
            return True

        def is_symlink(self) -> bool:
            return True

    with pytest.raises(AppError) as rejected:
        _prepare_backup_root(DirectDirectorySymlink())  # type: ignore[arg-type]

    assert rejected.value.error == "backup_incomplete"


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS directory junction contract")
def test_backup_root_rejects_a_directory_junction_before_resolving(tmp_path: Path) -> None:
    from app.services.backup_service import _prepare_backup_root

    target = tmp_path / "junction-target"
    junction = tmp_path / "backup-root"
    target.mkdir()
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        with pytest.raises(AppError) as rejected:
            _prepare_backup_root(Path(os.path.abspath(junction)))
    finally:
        if os.path.lexists(junction):
            os.rmdir(junction)

    assert rejected.value.error == "backup_incomplete"


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
        inventory_path=(tmp_path / "backup-inventory.json").resolve(),
        upload_root=(tmp_path / "uploads").resolve(),
        database_url="postgresql+psycopg://ticketbox_backup@localhost:5432/ticketbox",
        passfile=(tmp_path / "pgpass").resolve(),
        pg_dump_binary=(tmp_path / "pg_dump.exe").resolve(),
        pg_restore_binary=(tmp_path / "pg_restore.exe").resolve(),
        operation_id="7db00670-2a24-4013-b57f-c6bbff739bf3",
        backup_id="38ed55ba-1dc0-43a4-87b3-b29982958399",
        release_id="release-fixture",
        backup_kind="manual",
        writer_fence_sha256=_EXPECTED_WRITER_FENCE_SHA256,
        expected_current_sha256=_EXPECTED_CURRENT_SHA256,
        expected_installation_id=_EXPECTED_INSTALLATION_ID,
        expected_dataset_id=_EXPECTED_DATASET_ID,
        expected_restore_epoch=_EXPECTED_RESTORE_EPOCH,
        expected_schema_revision=_EXPECTED_SCHEMA_REVISION,
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        create_complete_backup_generation(request, db=object())  # type: ignore[arg-type]
    assert caught.value.exceptions == (primary, cleanup)


def test_backup_preserves_primary_staging_and_baseexception_lease_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import backup_service

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    primary = RuntimeError("backup body failed")
    staging_cleanup = OSError("staging cleanup failed")
    lease_cleanup = KeyboardInterrupt("lease cleanup interrupted")

    class Lease:
        def release(self) -> None:
            raise lease_cleanup

    def fail_build(*_args, **_kwargs):
        raise primary

    def fail_staging_cleanup(_path: Path, _root: Path) -> None:
        raise staging_cleanup

    monkeypatch.setattr(backup_service, "acquire_backup_job_lease", lambda _path: Lease())
    monkeypatch.setattr(backup_service, "_build_staged_generation", fail_build)
    monkeypatch.setattr(backup_service, "_remove_staging", fail_staging_cleanup)
    request = CompleteBackupRequest(
        backup_root=backup_root,
        inventory_path=(tmp_path / "backup-inventory.json").resolve(),
        upload_root=(tmp_path / "uploads").resolve(),
        database_url="postgresql+psycopg://ticketbox_backup@localhost:5432/ticketbox",
        passfile=(tmp_path / "pgpass").resolve(),
        pg_dump_binary=(tmp_path / "pg_dump.exe").resolve(),
        pg_restore_binary=(tmp_path / "pg_restore.exe").resolve(),
        operation_id="7db00670-2a24-4013-b57f-c6bbff739bf3",
        backup_id="38ed55ba-1dc0-43a4-87b3-b29982958399",
        release_id="release-fixture",
        backup_kind="manual",
        writer_fence_sha256=_EXPECTED_WRITER_FENCE_SHA256,
        expected_current_sha256=_EXPECTED_CURRENT_SHA256,
        expected_installation_id=_EXPECTED_INSTALLATION_ID,
        expected_dataset_id=_EXPECTED_DATASET_ID,
        expected_restore_epoch=_EXPECTED_RESTORE_EPOCH,
        expected_schema_revision=_EXPECTED_SCHEMA_REVISION,
    )

    with pytest.raises(BaseExceptionGroup) as caught:
        create_complete_backup_generation(request, db=object())  # type: ignore[arg-type]
    assert caught.value.exceptions == (primary, staging_cleanup, lease_cleanup)


def test_complete_backup_request_requires_structured_dataset_authority_binding() -> None:
    assert {
        "inventory_path",
        "expected_current_sha256",
        "expected_dataset_id",
        "expected_restore_epoch",
        "expected_schema_revision",
    } <= set(CompleteBackupRequest.__dataclass_fields__)
