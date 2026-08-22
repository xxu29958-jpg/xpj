"""Sanitized backup inventory and bounded-retention contracts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.errors import AppError
from app.services.dataset_authority_service import DatasetAuthority
from app.services.dataset_backup_contract import (
    DATABASE_ARCHIVE_NAME,
    MANIFEST_NAME,
    DatabaseArtifact,
    DatasetBackupManifest,
    encode_manifest,
)

_EXPECTED_DATASET_ID = "5895e71e-1c87-4a59-b1c7-04f68817795e"
_EXPECTED_RESTORE_EPOCH = 3
_EXPECTED_SCHEMA_REVISION = "20260821_0001"
_EXPECTED_WRITER_FENCE_SHA256 = "b" * 64
_EXPECTED_INSTALLATION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _write_complete_generation(
    root: Path,
    *,
    backup_id: str,
    created_at: datetime,
) -> Path:
    generation = root / f"ticketbox-backup-{backup_id}"
    generation.mkdir()
    database = generation / DATABASE_ARCHIVE_NAME
    database.write_bytes(f"database-{backup_id}".encode())
    manifest = DatasetBackupManifest(
        backup_id=backup_id,
        operation_id=backup_id,
        backup_kind="manual",
        created_at=created_at,
        release_id="release-fixture",
        source_installation_id=_EXPECTED_INSTALLATION_ID,
        writer_fence_sha256=_EXPECTED_WRITER_FENCE_SHA256,
        authority=DatasetAuthority(
            dataset_id=_EXPECTED_DATASET_ID,
            client_generation="bf70f3b2-f2fe-41d9-a694-c0e33208d2b5",
            restore_epoch=_EXPECTED_RESTORE_EPOCH,
            schema_revision=_EXPECTED_SCHEMA_REVISION,
            schema_min_compatible="1.2.0",
            semantic_revision="ticketbox-dataset-semantics-v1",
            created_at=created_at,
            restored_from_backup_id=None,
        ),
        database=DatabaseArtifact(
            size_bytes=database.stat().st_size,
            sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        ),
        originals=(),
    )
    (generation / MANIFEST_NAME).write_bytes(encode_manifest(manifest))
    return generation


def test_verified_publication_prunes_only_after_new_generation_and_projects_inventory(
    tmp_path: Path,
) -> None:
    from app.services.dataset_backup_inventory import (
        list_published_backup_records,
        reconcile_published_backup_inventory,
    )

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    inventory_path = tmp_path / "app" / "backup-inventory.json"
    inventory_path.parent.mkdir()
    created = datetime(2026, 8, 21, tzinfo=UTC)
    ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    )
    for index, backup_id in enumerate(ids):
        _write_complete_generation(
            backup_root,
            backup_id=backup_id,
            created_at=created + timedelta(minutes=index),
        )

    reconcile_published_backup_inventory(
        backup_root=backup_root,
        inventory_path=inventory_path,
        required_generation=f"ticketbox-backup-{ids[-1]}",
    )

    assert not (backup_root / f"ticketbox-backup-{ids[0]}").exists()
    assert all((backup_root / f"ticketbox-backup-{item}").is_dir() for item in ids[1:])
    entries = list_published_backup_records(inventory_path=inventory_path)
    assert [entry.backup_id for entry in entries] == list(reversed(ids[1:]))
    projection = inventory_path.read_text(encoding="utf-8")
    assert str(backup_root) not in projection
    assert "database.dump" not in projection


def test_corrupt_new_generation_cannot_trigger_retention(tmp_path: Path) -> None:
    from app.services.dataset_backup_inventory import reconcile_published_backup_inventory

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    inventory_path = tmp_path / "app" / "backup-inventory.json"
    inventory_path.parent.mkdir()
    created = datetime(2026, 8, 21, tzinfo=UTC)
    old_ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    for index, backup_id in enumerate(old_ids):
        _write_complete_generation(
            backup_root,
            backup_id=backup_id,
            created_at=created + timedelta(minutes=index),
        )
    corrupt = backup_root / "ticketbox-backup-44444444-4444-4444-8444-444444444444"
    corrupt.mkdir()
    (corrupt / DATABASE_ARCHIVE_NAME).write_bytes(b"unbound")

    with pytest.raises(AppError):
        reconcile_published_backup_inventory(
            backup_root=backup_root,
            inventory_path=inventory_path,
            required_generation=corrupt.name,
        )

    assert all((backup_root / f"ticketbox-backup-{item}").is_dir() for item in old_ids)
    assert not inventory_path.exists()


def test_corrupt_retained_generation_does_not_block_new_verified_publication(
    tmp_path: Path,
) -> None:
    from app.services.dataset_backup_inventory import (
        list_published_backup_records,
        reconcile_published_backup_inventory,
    )

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    inventory_path = tmp_path / "app" / "backup-inventory.json"
    inventory_path.parent.mkdir()
    created = datetime(2026, 8, 21, tzinfo=UTC)
    old_id = "11111111-1111-4111-8111-111111111111"
    required_id = "22222222-2222-4222-8222-222222222222"
    corrupt = _write_complete_generation(backup_root, backup_id=old_id, created_at=created)
    (corrupt / DATABASE_ARCHIVE_NAME).write_bytes(b"corrupt-old-payload")
    required = _write_complete_generation(
        backup_root,
        backup_id=required_id,
        created_at=created + timedelta(minutes=1),
    )

    reconcile_published_backup_inventory(
        backup_root=backup_root,
        inventory_path=inventory_path,
        required_generation=required.name,
    )

    assert [item.backup_id for item in list_published_backup_records(inventory_path=inventory_path)] == [required_id]
    assert corrupt.is_dir()


def test_inventory_must_publish_before_any_retention_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_backup_inventory

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    inventory_path = tmp_path / "app" / "backup-inventory.json"
    inventory_path.parent.mkdir()
    created = datetime(2026, 8, 21, tzinfo=UTC)
    ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    )
    for index, backup_id in enumerate(ids):
        _write_complete_generation(
            backup_root,
            backup_id=backup_id,
            created_at=created + timedelta(minutes=index),
        )

    def fail_publication(*_args, **_kwargs) -> None:
        raise OSError("inventory publication failed")

    monkeypatch.setattr(dataset_backup_inventory, "_write_inventory", fail_publication)
    with pytest.raises(OSError, match="inventory publication failed"):
        dataset_backup_inventory.reconcile_published_backup_inventory(
            backup_root=backup_root,
            inventory_path=inventory_path,
            required_generation=f"ticketbox-backup-{ids[-1]}",
        )

    assert all((backup_root / f"ticketbox-backup-{item}").is_dir() for item in ids)


def test_partial_retention_delete_leaves_retryable_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_backup_inventory

    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    inventory_path = tmp_path / "app" / "backup-inventory.json"
    inventory_path.parent.mkdir()
    created = datetime(2026, 8, 21, tzinfo=UTC)
    ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    )
    for index, backup_id in enumerate(ids):
        _write_complete_generation(
            backup_root,
            backup_id=backup_id,
            created_at=created + timedelta(minutes=index),
        )

    real_rmtree = dataset_backup_inventory.shutil.rmtree
    failed = False

    def fail_after_partial_delete(path: Path) -> None:
        nonlocal failed
        if not failed:
            failed = True
            (Path(path) / DATABASE_ARCHIVE_NAME).unlink()
            raise OSError("partial retention failure")
        real_rmtree(path)

    monkeypatch.setattr(dataset_backup_inventory.shutil, "rmtree", fail_after_partial_delete)
    with pytest.raises(AppError):
        dataset_backup_inventory.reconcile_published_backup_inventory(
            backup_root=backup_root,
            inventory_path=inventory_path,
            required_generation=f"ticketbox-backup-{ids[-1]}",
        )

    assert not (backup_root / f"ticketbox-backup-{ids[0]}").exists()
    tombstones = tuple(backup_root.glob(".ticketbox-retired-backup-*"))
    assert len(tombstones) == 1

    dataset_backup_inventory.reconcile_published_backup_inventory(
        backup_root=backup_root,
        inventory_path=inventory_path,
        required_generation=f"ticketbox-backup-{ids[-1]}",
    )
    assert not tombstones[0].exists()


def test_inventory_publication_preserves_primary_and_cleanup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_backup_inventory

    primary = OSError("inventory write failed")
    cleanup = OSError("inventory cleanup failed")

    def fail_open(*_args, **_kwargs):
        raise primary

    def fail_unlink(*_args, **_kwargs):
        raise cleanup

    monkeypatch.setattr(Path, "open", fail_open)
    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(BaseExceptionGroup) as caught:
        dataset_backup_inventory._write_inventory(tmp_path / "inventory.json", ())

    assert caught.value.exceptions == (primary, cleanup)


def test_inventory_publication_preserves_a_lone_primary_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_backup_inventory

    primary = OSError("inventory write failed")

    def fail_open(*_args, **_kwargs):
        raise primary

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(OSError) as caught:
        dataset_backup_inventory._write_inventory(tmp_path / "inventory.json", ())

    assert caught.value is primary
