from __future__ import annotations

from pathlib import Path
from uuid import UUID

import app.database as database
from sqlalchemy import inspect, text

from app.database import BACKEND_ROOT, Base, engine, init_db, migrate_upload_paths_to_tenant_dirs
from conftest import PNG_BYTES, TEST_UPLOAD_DIR


def _reset_empty_database() -> None:
    Base.metadata.drop_all(bind=engine)


def _expense_columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("expenses")}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def _create_v01_expenses_table() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS expenses"))
        connection.execute(
            text(
                """
                CREATE TABLE expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount_cents INTEGER,
                    merchant VARCHAR(255),
                    category VARCHAR(64) NOT NULL DEFAULT '其他',
                    note TEXT,
                    source VARCHAR(64) NOT NULL DEFAULT 'iPhone截图',
                    image_path VARCHAR(500),
                    image_hash VARCHAR(128),
                    raw_text TEXT,
                    confidence FLOAT,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    expense_time DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    confirmed_at DATETIME,
                    rejected_at DATETIME
                )
                """
            )
        )


def _insert_legacy_expense(
    *,
    amount_cents: int | None = None,
    merchant: str | None = "老商家",
    category: str = "吃饭",
    status: str = "pending",
    image_path: str | None = None,
    thumbnail_path: str | None = None,
    tenant_id: str | None = None,
    public_id: str | None = None,
) -> int:
    columns = _expense_columns()
    values = {
        "amount_cents": amount_cents,
        "merchant": merchant,
        "category": category,
        "note": "旧备注",
        "source": "iPhone截图",
        "image_path": image_path,
        "image_hash": "legacy-hash",
        "raw_text": "",
        "confidence": None,
        "status": status,
        "expense_time": "2026-05-04 08:00:00",
        "created_at": "2026-05-04 08:00:00",
        "updated_at": "2026-05-04 08:00:00",
        "confirmed_at": "2026-05-04 08:10:00" if status == "confirmed" else None,
        "rejected_at": None,
    }
    if "thumbnail_path" in columns:
        values["thumbnail_path"] = thumbnail_path
    if "tenant_id" in columns and tenant_id is not None:
        values["tenant_id"] = tenant_id
    if "public_id" in columns:
        values["public_id"] = public_id

    keys = [key for key in values if key in columns]
    placeholders = ", ".join(f":{key}" for key in keys)
    sql = f"INSERT INTO expenses ({', '.join(keys)}) VALUES ({placeholders})"
    with engine.begin() as connection:
        result = connection.execute(text(sql), {key: values[key] for key in keys})
        return int(result.lastrowid)


def _fetch_expense(expense_id: int) -> dict[str, object]:
    with engine.begin() as connection:
        row = connection.execute(text("SELECT * FROM expenses WHERE id = :id"), {"id": expense_id}).mappings().one()
    return dict(row)


def test_empty_database_initializes_schema_and_runtime_data() -> None:
    _reset_empty_database()

    init_db()

    inspector = inspect(engine)
    assert "expenses" in inspector.get_table_names()
    assert "category_rules" in inspector.get_table_names()
    assert "duplicate_ignores" in inspector.get_table_names()
    assert {"tenant_id", "public_id", "thumbnail_path", "duplicate_status"}.issubset(_expense_columns())
    with engine.begin() as connection:
        owner_rules = connection.execute(
            text("SELECT COUNT(*) FROM category_rules WHERE tenant_id = 'owner'")
        ).scalar_one()
        tester_rules = connection.execute(
            text("SELECT COUNT(*) FROM category_rules WHERE tenant_id = 'tester_1'")
        ).scalar_one()
    assert owner_rules > 0
    assert tester_rules > 0


def test_v01_schema_migrates_without_losing_expense_data() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    expense_id = _insert_legacy_expense(amount_cents=3680, status="confirmed")

    init_db()

    migrated = _fetch_expense(expense_id)
    assert migrated["amount_cents"] == 3680
    assert migrated["merchant"] == "老商家"
    assert migrated["tenant_id"] == "owner"
    UUID(str(migrated["public_id"]))
    assert migrated["duplicate_status"] == "none"
    assert {"tenant_id", "public_id", "thumbnail_path", "tags", "image_deleted_at"}.issubset(_expense_columns())
    assert "ix_expenses_public_id" in _indexes("expenses")


def test_pre_v03_backup_is_not_recreated_after_identity_migration() -> None:
    backup_dir = BACKEND_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_pattern = "pytest_test-pre-v0.3-*.db"
    for backup_file in backup_dir.glob(backup_pattern):
        backup_file.unlink()

    _reset_empty_database()
    _create_v01_expenses_table()
    _insert_legacy_expense(amount_cents=3680, status="confirmed")

    try:
        database._sqlite_backup_done = False
        init_db()
        first_backups = sorted(backup_dir.glob(backup_pattern))
        assert len(first_backups) == 1

        database._sqlite_backup_done = False
        init_db()
        second_backups = sorted(backup_dir.glob(backup_pattern))
        assert second_backups == first_backups
    finally:
        for backup_file in backup_dir.glob(backup_pattern):
            backup_file.unlink()


def test_missing_public_id_backfills_unique_values() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN public_id VARCHAR(36)"))
    first_id = _insert_legacy_expense(public_id=None, tenant_id="owner")
    second_id = _insert_legacy_expense(public_id="", tenant_id="owner")

    init_db()

    first = _fetch_expense(first_id)
    second = _fetch_expense(second_id)
    UUID(str(first["public_id"]))
    UUID(str(second["public_id"]))
    assert first["public_id"] != second["public_id"]
    assert "ix_expenses_public_id" in _indexes("expenses")


def test_missing_tenant_id_backfills_owner_for_expenses_rules_and_duplicate_ignores() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    expense_id = _insert_legacy_expense()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE category_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword VARCHAR(255) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO category_rules (keyword, category, enabled, priority, created_at, updated_at) "
                "VALUES ('老规则', '生活', 1, 1, '2026-05-04 08:00:00', '2026-05-04 08:00:00')"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE duplicate_ignores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id INTEGER NOT NULL,
                    duplicate_of_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO duplicate_ignores (expense_id, duplicate_of_id, created_at) "
                "VALUES (1, 2, '2026-05-04 08:00:00')"
            )
        )

    init_db()

    assert _fetch_expense(expense_id)["tenant_id"] == "owner"
    with engine.begin() as connection:
        rule_tenant = connection.execute(text("SELECT tenant_id FROM category_rules WHERE keyword = '老规则'")).scalar_one()
        ignore = connection.execute(text("SELECT tenant_id, kind FROM duplicate_ignores WHERE expense_id = 1")).mappings().one()
    assert rule_tenant == "owner"
    assert ignore["tenant_id"] == "owner"
    assert ignore["kind"] == "manual"


def test_legacy_upload_paths_migrate_to_tenant_directory_and_missing_files_stay_reference_only() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
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
    existing_id = _insert_legacy_expense(
        image_path=legacy_file.relative_to(BACKEND_ROOT).as_posix(),
        thumbnail_path=legacy_thumb.relative_to(BACKEND_ROOT).as_posix(),
        tenant_id="owner",
    )
    missing_id = _insert_legacy_expense(
        image_path="uploads/pytest_test/2026/05/missing.png",
        thumbnail_path=None,
        tenant_id="owner",
    )

    init_db()

    migrated = _fetch_expense(existing_id)
    assert str(migrated["image_path"]).startswith("uploads/pytest_test/owner/2026/05/")
    assert str(migrated["thumbnail_path"]).startswith("uploads/pytest_test/owner/2026/05/thumbs/")
    assert (BACKEND_ROOT / str(migrated["image_path"])).is_file()
    assert (BACKEND_ROOT / str(migrated["thumbnail_path"])).is_file()
    assert not legacy_file.exists()
    assert not legacy_thumb.exists()

    missing = _fetch_expense(missing_id)
    assert missing["image_path"] == "uploads/pytest_test/2026/05/missing.png"


def test_legacy_upload_migration_rename_failure_keeps_original_file_and_database_path(monkeypatch) -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN public_id VARCHAR(36)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN thumbnail_path VARCHAR(500)"))
    legacy_dir = TEST_UPLOAD_DIR / "2026" / "05"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / "rename-fails.png"
    legacy_file.write_bytes(PNG_BYTES)
    legacy_path = legacy_file.relative_to(BACKEND_ROOT).as_posix()
    expense_id = _insert_legacy_expense(image_path=legacy_path, tenant_id="owner")

    def fail_rename(self: Path, target: Path) -> Path:
        raise OSError("simulated move failure")

    monkeypatch.setattr(Path, "rename", fail_rename)

    migrate_upload_paths_to_tenant_dirs()

    assert legacy_file.is_file()
    assert _fetch_expense(expense_id)["image_path"] == legacy_path
