from __future__ import annotations

from pathlib import Path
from uuid import UUID

import app.database as database
import pytest
from sqlalchemy import inspect, text

from app.database import BACKEND_ROOT, Base, engine, init_db, migrate_upload_paths_to_tenant_dirs
from conftest import PNG_BYTES, TEST_DB_PATH, TEST_UPLOAD_DIR, TEST_UPLOAD_RELATIVE


def _reset_empty_database() -> None:
    Base.metadata.drop_all(bind=engine)


def _expense_columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("expenses")}


def _table_columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


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


def _table_create_sql(table_name: str) -> str:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table_name},
        ).one()
    return str(row[0])


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
    tags: str | None = None,
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
    if "tags" in columns:
        values["tags"] = tags

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
    assert "ledger_audit_logs" in inspector.get_table_names()
    assert "merchant_aliases" in inspector.get_table_names()
    assert "tags" in inspector.get_table_names()
    assert "expense_tags" in inspector.get_table_names()
    assert "expense_items" in inspector.get_table_names()
    assert "expense_splits" in inspector.get_table_names()
    assert "csv_import_batches" in inspector.get_table_names()
    assert "csv_import_rows" in inspector.get_table_names()
    assert "recurring_items" in inspector.get_table_names()
    assert "budgets" in inspector.get_table_names()
    assert "budget_categories" in inspector.get_table_names()
    assert "goals" in inspector.get_table_names()
    assert "exchange_rates" in inspector.get_table_names()
    assert "fx_rates" in inspector.get_table_names()
    assert "dashboard_card_preferences" in inspector.get_table_names()
    assert "rule_application_batches" in inspector.get_table_names()
    assert "rule_application_changes" in inspector.get_table_names()
    assert "schema_migrations" in inspector.get_table_names()
    assert {
        "tenant_id",
        "public_id",
        "thumbnail_path",
        "duplicate_status",
        "draft_idempotency_key",
        "original_currency_code",
        "original_amount_minor",
        "exchange_rate_to_cny",
        "exchange_rate_date",
        "exchange_rate_source",
    }.issubset(_expense_columns())
    assert "ix_ledger_audit_logs_ledger_created_at" in _indexes("ledger_audit_logs")
    assert "ix_expenses_tenant_draft_idempotency_key" in _indexes("expenses")
    assert "ix_expenses_tenant_status_merchant_expense_time" in _indexes("expenses")
    assert "ix_expenses_tenant_status_merchant_confirmed_at" in _indexes("expenses")
    assert "ix_merchant_aliases_tenant_alias_key" in _indexes("merchant_aliases")
    assert "ix_merchant_aliases_tenant_canonical" in _indexes("merchant_aliases")
    assert "ix_tags_tenant_key" in _indexes("tags")
    assert "ix_expense_tags_tenant_expense" in _indexes("expense_tags")
    assert "ix_expense_tags_tenant_tag" in _indexes("expense_tags")
    assert "ix_expense_items_tenant_expense_position" in _indexes("expense_items")
    assert "ix_expense_items_tenant_public_id" in _indexes("expense_items")
    assert "ix_expense_items_tenant_category" in _indexes("expense_items")
    assert "ix_expense_splits_tenant_expense_position" in _indexes("expense_splits")
    assert "ix_expense_splits_tenant_public_id" in _indexes("expense_splits")
    assert "ix_expense_splits_tenant_member" in _indexes("expense_splits")
    assert "ix_csv_import_batches_tenant_public_id" in _indexes("csv_import_batches")
    assert "ix_csv_import_batches_tenant_status_created_at" in _indexes("csv_import_batches")
    assert "ix_csv_import_rows_tenant_batch_line" in _indexes("csv_import_rows")
    assert "ix_csv_import_rows_tenant_batch_status" in _indexes("csv_import_rows")
    assert "ix_recurring_items_tenant_status_next" in _indexes("recurring_items")
    assert "ix_budgets_tenant_month" in _indexes("budgets")
    assert "ix_budget_categories_tenant_month" in _indexes("budget_categories")
    assert "ix_budget_categories_tenant_category" in _indexes("budget_categories")
    assert "ix_goals_tenant_month_status" in _indexes("goals")
    assert "ix_goals_tenant_category_month" in _indexes("goals")
    assert "ix_goals_tenant_public_id" in _indexes("goals")
    assert "ix_exchange_rates_tenant_currency_date" in _indexes("exchange_rates")
    assert "ix_fx_rates_source_home_currency_date" in _indexes("fx_rates")
    assert "ix_expenses_tenant_original_currency_date" in _indexes("expenses")
    assert "ix_dashboard_cards_tenant_surface_position" in _indexes(
        "dashboard_card_preferences"
    )
    assert "ix_dashboard_cards_tenant_surface_key" in _indexes(
        "dashboard_card_preferences"
    )
    assert "ix_rule_application_batches_tenant_created_at" in _indexes("rule_application_batches")
    assert "ix_rule_application_batches_tenant_status" in _indexes("rule_application_batches")
    assert "uq_rule_application_batches_id_tenant_id" in _indexes("rule_application_batches")
    assert "ix_rule_application_changes_tenant_batch" in _indexes("rule_application_changes")
    assert "ix_rule_application_changes_tenant_expense" in _indexes("rule_application_changes")
    rule_changes_sql = _table_create_sql("rule_application_changes")
    assert "fk_rule_application_changes_batch_tenant" in rule_changes_sql
    assert "fk_rule_application_changes_expense_tenant" in rule_changes_sql
    assert {
        "amount_min_cents",
        "amount_max_cents",
        "source_contains",
        "tag_contains",
    }.issubset(_table_columns("category_rules"))
    assert "ix_category_rules_tenant_enabled_priority" in _indexes("category_rules")
    merchant_alias_sql = _table_create_sql("merchant_aliases")
    assert "uq_merchant_aliases_tenant_alias_key" in merchant_alias_sql
    tags_sql = _table_create_sql("tags")
    assert "uq_tags_tenant_key" in tags_sql
    assert "uq_tags_id_tenant_id" in tags_sql
    expense_tags_sql = _table_create_sql("expense_tags")
    assert "fk_expense_tags_expense_tenant" in expense_tags_sql
    assert "fk_expense_tags_tag_tenant" in expense_tags_sql
    assert "uq_expense_tags_tenant_expense_tag" in expense_tags_sql
    expenses_sql = _table_create_sql("expenses")
    assert "uq_expenses_id_tenant_id" in expenses_sql
    assert "ck_expenses_amount_non_negative" in expenses_sql
    assert "ck_expenses_status_valid" in expenses_sql
    assert "ck_expenses_duplicate_status_valid" in expenses_sql
    expense_items_sql = _table_create_sql("expense_items")
    assert "ck_expense_items_position_non_negative" in expense_items_sql
    assert "ck_expense_items_amount_non_negative" in expense_items_sql
    assert "fk_expense_items_expense_tenant" in expense_items_sql
    assert "uq_expense_items_tenant_expense_position" in expense_items_sql
    expense_splits_sql = _table_create_sql("expense_splits")
    assert "ck_expense_splits_position_non_negative" in expense_splits_sql
    assert "ck_expense_splits_amount_non_negative" in expense_splits_sql
    assert "fk_expense_splits_expense_tenant" in expense_splits_sql
    assert "fk_expense_splits_member_tenant" in expense_splits_sql
    assert "uq_expense_splits_tenant_expense_position" in expense_splits_sql
    assert "uq_expense_splits_tenant_expense_member" in expense_splits_sql
    csv_import_batches_sql = _table_create_sql("csv_import_batches")
    assert "ck_csv_import_batches_status_valid" in csv_import_batches_sql
    assert "uq_csv_import_batches_id_tenant_id" in csv_import_batches_sql
    csv_import_rows_sql = _table_create_sql("csv_import_rows")
    assert "ck_csv_import_rows_status_valid" in csv_import_rows_sql
    assert "fk_csv_import_rows_batch_tenant" in csv_import_rows_sql
    assert "fk_csv_import_rows_expense_tenant" in csv_import_rows_sql
    assert "uq_csv_import_rows_tenant_batch_line" in csv_import_rows_sql
    recurring_sql = _table_create_sql("recurring_items")
    assert "ck_recurring_items_frequency_valid" in recurring_sql
    assert "ck_recurring_items_status_valid" in recurring_sql
    budget_sql = _table_create_sql("budgets")
    assert "ck_budgets_total_non_negative" in budget_sql
    assert "uq_budgets_tenant_month" in budget_sql
    budget_categories_sql = _table_create_sql("budget_categories")
    assert "ck_budget_categories_amount_non_negative" in budget_categories_sql
    assert "uq_budget_categories_tenant_month_category" in budget_categories_sql
    goals_sql = _table_create_sql("goals")
    assert "ck_goals_type_valid" in goals_sql
    assert "ck_goals_period_valid" in goals_sql
    assert "ck_goals_status_valid" in goals_sql
    assert "ck_goals_target_positive" in goals_sql
    assert "uq_goals_active_total_scope" in _indexes("goals")
    assert "uq_goals_active_category_scope" in _indexes("goals")
    exchange_rates_sql = _table_create_sql("exchange_rates")
    assert "uq_exchange_rates_tenant_currency_date" in exchange_rates_sql
    assert "ck_exchange_rates_rate_positive" in exchange_rates_sql
    fx_rates_sql = _table_create_sql("fx_rates")
    assert "uq_fx_rates_source_home_currency_date" in fx_rates_sql
    assert "ck_fx_rates_rate_positive" in fx_rates_sql
    dashboard_cards_sql = _table_create_sql("dashboard_card_preferences")
    assert "ck_dashboard_cards_surface_valid" in dashboard_cards_sql
    assert "ck_dashboard_cards_position_non_negative" in dashboard_cards_sql
    assert "uq_dashboard_cards_tenant_surface_key" in dashboard_cards_sql
    with engine.begin() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        owner_rules = connection.execute(
            text("SELECT COUNT(*) FROM category_rules WHERE tenant_id = 'owner'")
        ).scalar_one()
        tester_rules = connection.execute(
            text("SELECT COUNT(*) FROM category_rules WHERE tenant_id = 'tester_1'")
        ).scalar_one()
    assert owner_rules > 0
    assert tester_rules > 0
    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE name = 'baseline-v0.9.0a1'")
        ).scalar_one()
    assert migration_count == 1


def test_schema_migration_marker_query_is_safe_before_init() -> None:
    _reset_empty_database()

    assert database.is_schema_migration_applied("baseline-v0.9.0a1") is False

    init_db()

    assert database.is_schema_migration_applied("baseline-v0.9.0a1") is True
    database.record_schema_migration("baseline-v0.9.0a1", note="repeat")
    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE name = 'baseline-v0.9.0a1'")
        ).scalar_one()
    assert migration_count == 1


def test_new_database_enforces_family_role_constraints() -> None:
    _reset_empty_database()

    init_db()

    ledger_member_sql = _table_create_sql("ledger_members")
    invitation_sql = _table_create_sql("invitations")
    assert "ck_ledger_members_role_valid" in ledger_member_sql
    assert "uq_ledger_members_id_ledger_id" in ledger_member_sql
    assert "role IN ('owner', 'member', 'viewer')" in ledger_member_sql
    assert "ck_invitations_role_invitable" in invitation_sql
    assert "role IN ('member', 'viewer')" in invitation_sql


def test_legacy_database_with_cross_ledger_expense_splits_fails_startup() -> None:
    _reset_empty_database()
    init_db()

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            owner_member_id = connection.execute(
                text("SELECT id FROM ledger_members WHERE ledger_id = 'owner' LIMIT 1")
            ).scalar_one()
            result = connection.execute(
                text(
                    """
                    INSERT INTO expenses (
                        tenant_id, public_id, amount_cents, merchant, category,
                        original_currency_code, original_amount_minor, exchange_rate_to_cny,
                        exchange_rate_date, exchange_rate_source, note, source, status,
                        duplicate_status, created_at, updated_at
                    )
                    VALUES (
                        'owner', '11111111-1111-1111-1111-111111111111',
                        1000, '坏数据', '其他', 'CNY', 1000, 1,
                        '2026-05-04', 'base', '', 'pytest', 'confirmed', 'none',
                        '2026-05-04 08:00:00', '2026-05-04 08:00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO expense_splits (
                        public_id, tenant_id, expense_id, member_id, position,
                        amount_cents, created_at, updated_at
                    )
                    VALUES (
                        '22222222-2222-2222-2222-222222222222',
                        'tester_1', :expense_id, :member_id, 0,
                        1000, '2026-05-04 08:00:00', '2026-05-04 08:00:00'
                    )
                    """
                ),
                {"expense_id": int(result.lastrowid), "member_id": owner_member_id},
            )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")

        with pytest.raises(RuntimeError, match="expense_splits"):
            database.validate_sqlite_data_integrity()
    finally:
        _reset_empty_database()


def test_legacy_database_with_invalid_family_roles_fails_startup() -> None:
    _reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ledger_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    account_id INTEGER NOT NULL,
                    role VARCHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO ledger_members (ledger_id, account_id, role) "
                "VALUES ('owner', 1, 'admin')"
            )
        )

    database._sqlite_backup_done = True
    try:
        with pytest.raises(RuntimeError, match="ledger_members.role"):
            init_db()
    finally:
        database._sqlite_backup_done = False


def test_legacy_database_with_invalid_invitation_role_fails_startup() -> None:
    _reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ledger_id VARCHAR(64) NOT NULL,
                    token_hash VARCHAR(64) NOT NULL,
                    role VARCHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO invitations (ledger_id, token_hash, role) "
                "VALUES ('owner', 'hash', 'owner')"
            )
        )

    database._sqlite_backup_done = True
    try:
        with pytest.raises(RuntimeError, match="invitations.role"):
            init_db()
    finally:
        database._sqlite_backup_done = False


@pytest.mark.parametrize(
    ("setup_sql", "message"),
    [
        (
            "UPDATE expenses SET amount_cents = -1",
            "expenses.amount_cents",
        ),
        (
            "UPDATE expenses SET status = 'archived'",
            "expenses.status",
        ),
        (
            "ALTER TABLE expenses ADD COLUMN duplicate_status VARCHAR(32) NOT NULL DEFAULT 'duplicate'",
            "expenses.duplicate_status",
        ),
    ],
)
def test_legacy_database_with_invalid_expense_core_data_fails_startup(
    setup_sql: str,
    message: str,
) -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    _insert_legacy_expense(amount_cents=3680, status="confirmed")
    with engine.begin() as connection:
        connection.execute(text(setup_sql))

    database._sqlite_backup_done = True
    try:
        with pytest.raises(RuntimeError, match=message):
            init_db()
    finally:
        database._sqlite_backup_done = False
        _reset_empty_database()


def test_v01_schema_migrates_without_losing_expense_data() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    expense_id = _insert_legacy_expense(amount_cents=3680, status="confirmed")

    init_db()

    migrated = _fetch_expense(expense_id)
    assert migrated["amount_cents"] == 3680
    assert migrated["merchant"] == "老商家"
    assert migrated["tenant_id"] == "owner"
    assert migrated["home_currency_code"] == "CNY"
    assert migrated["original_currency_code"] == "CNY"
    assert migrated["original_amount_minor"] == 3680
    assert str(migrated["exchange_rate_to_cny"]) in {"1", "1.0", "1.00000000"}
    assert migrated["exchange_rate_source"] == "base"
    assert str(migrated["exchange_rate_date"]).startswith("2026-05-04")
    assert migrated["fx_status"] == "ready"
    UUID(str(migrated["public_id"]))
    assert migrated["duplicate_status"] == "none"
    assert {"tenant_id", "public_id", "thumbnail_path", "tags", "image_deleted_at"}.issubset(_expense_columns())
    assert "ix_expenses_public_id" in _indexes("expenses")
    assert "ledger_audit_logs" in inspect(engine).get_table_names()


def test_legacy_foreign_expense_without_rate_migrates_to_fx_pending() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN original_currency_code VARCHAR(3)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN original_amount_minor INTEGER"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN exchange_rate_to_cny NUMERIC(18, 8)"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN exchange_rate_source VARCHAR(32)"))

    expense_id = _insert_legacy_expense(amount_cents=12345, status="pending")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE expenses
                SET original_currency_code = 'USD',
                    original_amount_minor = 12345,
                    exchange_rate_to_cny = NULL,
                    exchange_rate_source = NULL
                WHERE id = :id
                """
            ),
            {"id": expense_id},
        )

    init_db()

    migrated = _fetch_expense(expense_id)
    assert migrated["home_currency_code"] == "CNY"
    assert migrated["original_currency_code"] == "USD"
    assert migrated["original_amount_minor"] == 12345
    assert migrated["amount_cents"] is None
    assert migrated["exchange_rate_to_cny"] is None
    assert migrated["exchange_rate_source"] is None
    assert migrated["fx_status"] == "pending"


def test_legacy_expense_tags_backfill_normalized_relation_rows() -> None:
    _reset_empty_database()
    _create_v01_expenses_table()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'owner'"))
        connection.execute(text("ALTER TABLE expenses ADD COLUMN tags TEXT"))
    expense_id = _insert_legacy_expense(
        amount_cents=3680,
        status="confirmed",
        tenant_id="owner",
        tags="  真香，AI，真香 ",
    )

    init_db()

    migrated = _fetch_expense(expense_id)
    assert migrated["tags"] == "真香, AI"
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT tags.name FROM tags "
                "JOIN expense_tags ON expense_tags.tag_id = tags.id "
                "WHERE tags.tenant_id = 'owner' AND expense_tags.expense_id = :expense_id "
                "ORDER BY tags.name"
            ),
            {"expense_id": expense_id},
        ).all()
    assert {str(row[0]) for row in rows} == {"真香", "AI"}


def test_pre_v03_backup_is_not_recreated_after_identity_migration() -> None:
    backup_dir = BACKEND_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_pattern = f"{TEST_DB_PATH.stem}-pre-v0.3-*.db"
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
    assert {
        "amount_min_cents",
        "amount_max_cents",
        "source_contains",
        "tag_contains",
    }.issubset(_table_columns("category_rules"))
    assert "ix_category_rules_tenant_enabled_priority" in _indexes("category_rules")
    assert ignore["tenant_id"] == "owner"
    assert ignore["kind"] == "manual"


def test_legacy_upload_paths_migrate_to_tenant_directory_and_missing_files_stay_reference_only() -> None:
    """v0.3.1-alpha2: ``init_db`` no longer auto-moves legacy uploads. The
    opt-in helper ``migrate_upload_paths_to_tenant_dirs`` must still move
    on-disk legacy files into the tenant directory when invoked explicitly,
    and must leave database-only references (files that never existed on
    disk) untouched.
    """

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
    missing_path = f"{TEST_UPLOAD_RELATIVE}/2026/05/missing.png"
    missing_id = _insert_legacy_expense(
        image_path=missing_path,
        thumbnail_path=None,
        tenant_id="owner",
    )

    # init_db must NOT move the legacy files (Phase 2 P0 contract).
    init_db()
    untouched = _fetch_expense(existing_id)
    assert str(untouched["image_path"]) == legacy_file.relative_to(BACKEND_ROOT).as_posix()
    assert legacy_file.is_file()

    # The opt-in helper still works when explicitly invoked.
    migrate_upload_paths_to_tenant_dirs()

    migrated = _fetch_expense(existing_id)
    assert str(migrated["image_path"]).startswith(f"{TEST_UPLOAD_RELATIVE}/owner/2026/05/")
    assert str(migrated["thumbnail_path"]).startswith(f"{TEST_UPLOAD_RELATIVE}/owner/2026/05/thumbs/")
    assert (BACKEND_ROOT / str(migrated["image_path"])).is_file()
    assert (BACKEND_ROOT / str(migrated["thumbnail_path"])).is_file()
    assert not legacy_file.exists()
    assert not legacy_thumb.exists()

    missing = _fetch_expense(missing_id)
    assert missing["image_path"] == missing_path


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
