"""Legacy upload-path → tenant-directory move (opt-in helper)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.database import (
    BACKEND_ROOT,
    engine,
    init_db,
    migrate_upload_paths_to_tenant_dirs,
)
from tests._infra.assets import PNG_BYTES
from tests._infra.env import TEST_UPLOAD_DIR, TEST_UPLOAD_RELATIVE
from tests._infra.migration_helpers import (
    create_v01_expenses_table,
    fetch_expense,
    insert_legacy_expense,
    reset_empty_database,
)


def test_legacy_upload_paths_migrate_to_tenant_directory_and_missing_files_stay_reference_only() -> None:
    """v0.3.1-alpha2: ``init_db`` no longer auto-moves legacy uploads. The
    opt-in helper ``migrate_upload_paths_to_tenant_dirs`` must still move
    on-disk legacy files into the tenant directory when invoked explicitly,
    and must leave database-only references (files that never existed on
    disk) untouched.
    """

    reset_empty_database()
    create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN public_id VARCHAR(36)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN thumbnail_path VARCHAR(500)"))

    legacy_dir = TEST_UPLOAD_DIR / "2026" / "05"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / "legacy.png"
    legacy_thumb = legacy_dir / "thumbs" / "legacy.jpg"
    legacy_thumb.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_bytes(PNG_BYTES)
    legacy_thumb.write_bytes(b"\xff\xd8\xff\xe0thumb")
    existing_id = insert_legacy_expense(
        image_path=legacy_file.relative_to(BACKEND_ROOT).as_posix(),
        thumbnail_path=legacy_thumb.relative_to(BACKEND_ROOT).as_posix(),
        tenant_id="owner",
    )
    missing_path = f"{TEST_UPLOAD_RELATIVE}/2026/05/missing.png"
    missing_id = insert_legacy_expense(
        image_path=missing_path,
        thumbnail_path=None,
        tenant_id="owner",
    )

    # init_db must NOT move the legacy files (Phase 2 P0 contract).
    init_db()
    untouched = fetch_expense(existing_id)
    assert str(untouched["image_path"]) == legacy_file.relative_to(BACKEND_ROOT).as_posix()
    assert legacy_file.is_file()

    # The opt-in helper still works when explicitly invoked.
    migrate_upload_paths_to_tenant_dirs()

    migrated = fetch_expense(existing_id)
    assert str(migrated["image_path"]).startswith(f"{TEST_UPLOAD_RELATIVE}/owner/2026/05/")
    assert str(migrated["thumbnail_path"]).startswith(f"{TEST_UPLOAD_RELATIVE}/owner/2026/05/thumbs/")
    assert (BACKEND_ROOT / str(migrated["image_path"])).is_file()
    assert (BACKEND_ROOT / str(migrated["thumbnail_path"])).is_file()
    assert not legacy_file.exists()
    assert not legacy_thumb.exists()

    missing = fetch_expense(missing_id)
    assert missing["image_path"] == missing_path


def test_legacy_upload_migration_rename_failure_keeps_original_file_and_database_path(monkeypatch) -> None:
    reset_empty_database()
    create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN public_id VARCHAR(36)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN thumbnail_path VARCHAR(500)"))
    legacy_dir = TEST_UPLOAD_DIR / "2026" / "05"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / "rename-fails.png"
    legacy_file.write_bytes(PNG_BYTES)
    legacy_path = legacy_file.relative_to(BACKEND_ROOT).as_posix()
    expense_id = insert_legacy_expense(image_path=legacy_path, tenant_id="owner")

    def fail_rename(self: Path, target: Path) -> Path:
        raise OSError("simulated move failure")

    monkeypatch.setattr(Path, "rename", fail_rename)

    migrate_upload_paths_to_tenant_dirs()

    assert legacy_file.is_file()
    assert fetch_expense(expense_id)["image_path"] == legacy_path
