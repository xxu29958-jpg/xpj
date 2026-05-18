from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
import secrets
import shutil
import sqlite3
from uuid import uuid4

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_ROOT, get_settings
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE, FX_SOURCE_BASE, FX_STATUS_PENDING, FX_STATUS_READY
from app.tenants import DEFAULT_TENANT_ID, TENANT_ID_PATTERN


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
_sqlite_backup_done = False
V03_IDENTITY_TABLES = {
    "accounts",
    "ledgers",
    "ledger_members",
    "devices",
    "auth_tokens",
    "upload_links",
    "pairing_codes",
}


class Base(DeclarativeBase):
    pass


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    backup_sqlite_database_once()
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
    record_schema_migration("baseline-v0.9.0a1", note="legacy hand-written migrate_sqlite_schema baseline")
    seed_identity_data()
    validate_sqlite_data_integrity()
    # v0.3.1-alpha2: do NOT auto-migrate legacy uploads on startup. Old image
    # paths remain readable through resolve_protected_image() after the route
    # has verified expense ownership. See docs/runbook/ROLLBACK.md.
    seed_runtime_data()


def record_schema_migration(name: str, *, note: str | None = None) -> None:
    """Record that the named migration step has been applied.

    Idempotent: subsequent calls with the same ``name`` are no-ops. Future
    incremental migrations should call this *after* their DDL succeeds so that
    repeated boots skip already-applied steps once that gating logic lands.
    Today the legacy migrator is itself idempotent, so this is informational.
    """

    from app.version import BACKEND_VERSION

    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name VARCHAR(128) PRIMARY KEY, "
                "applied_at DATETIME NOT NULL, "
                "backend_version VARCHAR(32), "
                "note TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT OR IGNORE INTO schema_migrations (name, applied_at, backend_version, note) "
                "VALUES (:name, :applied_at, :backend_version, :note)"
            ),
            {
                "name": name,
                "applied_at": datetime.now(UTC),
                "backend_version": BACKEND_VERSION,
                "note": note,
            },
        )


def is_schema_migration_applied(name: str) -> bool:
    """Return True if a named migration step has previously been recorded."""

    if not settings.database_url.startswith("sqlite"):
        return False
    if "schema_migrations" not in set(inspect(engine).get_table_names()):
        return False
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :name LIMIT 1"),
            {"name": name},
        ).first()
    return row is not None


def _sqlite_database_path() -> Path | None:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    raw_path = settings.database_url[len(prefix):]
    if raw_path in {"", ":memory:"}:
        return None
    return Path(raw_path)


def backup_sqlite_database_once() -> Path | None:
    global _sqlite_backup_done
    if _sqlite_backup_done:
        return None
    _sqlite_backup_done = True

    db_path = _sqlite_database_path()
    if db_path is None or not db_path.is_file():
        return None
    if not _needs_pre_v03_backup(db_path):
        return None

    backup_dir = BACKEND_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = f"{db_path.stem}-pre-v0.3-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    backup_path = (backup_dir / backup_name).resolve()
    try:
        backup_path.relative_to(backup_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("SQLite backup target escaped backup directory") from exc
    shutil.copy2(db_path, backup_path)
    return backup_path


def _needs_pre_v03_backup(db_path: Path) -> bool:
    try:
        with sqlite3.connect(db_path) as connection:
            table_rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"SQLite database cannot be inspected before migration: {db_path}") from exc
    table_names = {str(row[0]) for row in table_rows}
    if not table_names:
        return False
    return not V03_IDENTITY_TABLES.issubset(table_names)


def seed_identity_data() -> None:
    from app.models import (
        Budget,
        BudgetCategory,
        CategoryRule,
        CsvImportBatch,
        CsvImportRow,
        DashboardCardPreference,
        DuplicateIgnore,
        Expense,
        ExpenseItem,
        ExpenseSplit,
        ExpenseTag,
        ExchangeRate,
        Goal,
        MerchantAlias,
        RuleApplicationBatch,
        RuleApplicationChange,
        Tag,
    )
    from app.services.identity_service import ensure_identity_for_existing_ledger_ids, ensure_identity_seed

    with SessionLocal() as db:
        ensure_identity_seed(db)
        ids: set[str] = set()
        if inspect(engine).has_table("expenses"):
            ids.update(str(value) for value in db.scalars(select(Expense.tenant_id).distinct()) if value)
        if inspect(engine).has_table("expense_items"):
            ids.update(str(value) for value in db.scalars(select(ExpenseItem.tenant_id).distinct()) if value)
        if inspect(engine).has_table("expense_splits"):
            ids.update(str(value) for value in db.scalars(select(ExpenseSplit.tenant_id).distinct()) if value)
        if inspect(engine).has_table("csv_import_batches"):
            ids.update(str(value) for value in db.scalars(select(CsvImportBatch.tenant_id).distinct()) if value)
        if inspect(engine).has_table("csv_import_rows"):
            ids.update(str(value) for value in db.scalars(select(CsvImportRow.tenant_id).distinct()) if value)
        if inspect(engine).has_table("category_rules"):
            ids.update(str(value) for value in db.scalars(select(CategoryRule.tenant_id).distinct()) if value)
        if inspect(engine).has_table("merchant_aliases"):
            ids.update(str(value) for value in db.scalars(select(MerchantAlias.tenant_id).distinct()) if value)
        if inspect(engine).has_table("tags"):
            ids.update(str(value) for value in db.scalars(select(Tag.tenant_id).distinct()) if value)
        if inspect(engine).has_table("expense_tags"):
            ids.update(str(value) for value in db.scalars(select(ExpenseTag.tenant_id).distinct()) if value)
        if inspect(engine).has_table("duplicate_ignores"):
            ids.update(str(value) for value in db.scalars(select(DuplicateIgnore.tenant_id).distinct()) if value)
        if inspect(engine).has_table("budgets"):
            ids.update(str(value) for value in db.scalars(select(Budget.tenant_id).distinct()) if value)
        if inspect(engine).has_table("budget_categories"):
            ids.update(str(value) for value in db.scalars(select(BudgetCategory.tenant_id).distinct()) if value)
        if inspect(engine).has_table("exchange_rates"):
            ids.update(str(value) for value in db.scalars(select(ExchangeRate.tenant_id).distinct()) if value)
        if inspect(engine).has_table("goals"):
            ids.update(str(value) for value in db.scalars(select(Goal.tenant_id).distinct()) if value)
        if inspect(engine).has_table("dashboard_card_preferences"):
            ids.update(
                str(value)
                for value in db.scalars(
                    select(DashboardCardPreference.tenant_id).distinct()
                )
                if value
            )
        if inspect(engine).has_table("rule_application_batches"):
            ids.update(str(value) for value in db.scalars(select(RuleApplicationBatch.tenant_id).distinct()) if value)
        if inspect(engine).has_table("rule_application_changes"):
            ids.update(str(value) for value in db.scalars(select(RuleApplicationChange.tenant_id).distinct()) if value)
        _validate_legacy_tenant_ids(ids, source="tenant-scoped tables")
        if ids:
            ensure_identity_for_existing_ledger_ids(db, ids)
        db.commit()


def _validate_legacy_tenant_ids(tenant_ids: set[str], *, source: str) -> None:
    invalid = sorted(tenant_id for tenant_id in tenant_ids if not TENANT_ID_PATTERN.fullmatch(tenant_id))
    if invalid:
        sample = ", ".join(invalid[:3])
        raise RuntimeError(f"Invalid legacy data: {source} contains unsupported tenant_id values: {sample}")


def seed_runtime_data() -> None:
    from app.services.category_service import normalize_existing_expense_categories
    from app.services.classify_service import seed_default_rules
    from app.services.identity_service import ledger_ids
    from app.services.tag_service import backfill_expense_tags

    with SessionLocal() as db:
        for ledger_id in ledger_ids(db):
            normalize_existing_expense_categories(db, ledger_id)
            backfill_expense_tags(db, ledger_id)
            seed_default_rules(db, ledger_id)


def _is_tenant_scoped_upload(path: Path, tenant_ids: set[str]) -> bool:
    try:
        first_part = path.relative_to(settings.upload_dir).parts[0]
    except (IndexError, ValueError):
        return False
    return first_part in tenant_ids


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    while True:
        candidate = path.with_name(f"{stem}-{secrets.token_hex(4)}{suffix}")
        if not candidate.exists():
            return candidate


def _move_legacy_upload_path(relative_path: str | None, tenant_id: str, tenant_ids: set[str]) -> str | None:
    if not relative_path:
        return relative_path

    source = (BACKEND_ROOT / relative_path).resolve()
    try:
        upload_relative = source.relative_to(settings.upload_dir)
    except ValueError:
        return relative_path
    if _is_tenant_scoped_upload(source, tenant_ids) or not source.is_file():
        return relative_path

    target = _unique_destination(settings.upload_dir / tenant_id / upload_relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.rename(target)
    except OSError:
        return relative_path
    return target.relative_to(BACKEND_ROOT).as_posix()


def migrate_upload_paths_to_tenant_dirs() -> None:
    from app.services.identity_service import ledger_ids
    from app.tenants import configured_tenants

    if inspect(engine).has_table("ledgers"):
        with SessionLocal() as db:
            tenant_ids = set(ledger_ids(db))
    else:
        tenant_ids = {tenant.id for tenant in configured_tenants()}
    _validate_legacy_tenant_ids(tenant_ids, source="ledgers")
    if not tenant_ids or not settings.upload_dir.exists():
        return

    with engine.begin() as connection:
        for tenant_id in tenant_ids:
            rows = connection.execute(
                text(
                    "SELECT id, image_path, thumbnail_path FROM expenses "
                    "WHERE tenant_id = :tenant_id "
                    "AND (image_path IS NOT NULL OR thumbnail_path IS NOT NULL)"
                ),
                {"tenant_id": tenant_id},
            ).mappings()
            for row in rows:
                image_path = _move_legacy_upload_path(row["image_path"], tenant_id, tenant_ids)
                thumbnail_path = _move_legacy_upload_path(row["thumbnail_path"], tenant_id, tenant_ids)
                if image_path != row["image_path"] or thumbnail_path != row["thumbnail_path"]:
                    connection.execute(
                        text(
                            "UPDATE expenses SET image_path = :image_path, thumbnail_path = :thumbnail_path "
                            "WHERE id = :id AND tenant_id = :tenant_id"
                        ),
                        {
                            "id": row["id"],
                            "tenant_id": tenant_id,
                            "image_path": image_path,
                            "thumbnail_path": thumbnail_path,
                        },
                    )


def validate_sqlite_data_integrity() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    table_names = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        _validate_expense_core_data(connection, table_names)
        _validate_expense_split_integrity(connection, table_names)
        _validate_tenant_child_integrity(connection, table_names)


def _validate_expense_core_data(connection, table_names: set[str]) -> None:
    """Reject legacy expense rows that would bypass CHECK constraints."""

    if "expenses" not in table_names:
        return

    invalid_amounts = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expenses "
                "WHERE amount_cents IS NOT NULL AND amount_cents < 0"
            )
        ).scalar_one()
    )
    if invalid_amounts:
        raise RuntimeError("Invalid legacy data: expenses.amount_cents contains negative values")

    invalid_statuses = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expenses "
                "WHERE status IS NULL OR status NOT IN ('pending', 'confirmed', 'rejected')"
            )
        ).scalar_one()
    )
    if invalid_statuses:
        raise RuntimeError("Invalid legacy data: expenses.status contains unsupported values")

    columns = {column["name"] for column in inspect(engine).get_columns("expenses")}
    if "duplicate_status" not in columns:
        return
    invalid_duplicate_statuses = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expenses "
                "WHERE duplicate_status IS NULL OR duplicate_status NOT IN ('none', 'suspected')"
            )
        ).scalar_one()
    )
    if invalid_duplicate_statuses:
        raise RuntimeError("Invalid legacy data: expenses.duplicate_status contains unsupported values")


def _validate_family_role_data(connection, table_names: set[str]) -> None:
    """Reject legacy SQLite rows that would bypass role CHECK constraints.

    SQLite cannot add CHECK constraints to an existing table with ALTER TABLE.
    Older valid databases stay compatible; malformed rows fail fast on startup
    instead of producing undefined permission behavior.
    """

    if "ledger_members" in table_names:
        invalid_members = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM ledger_members "
                    "WHERE role NOT IN ('owner', 'member', 'viewer')"
                )
            ).scalar_one()
        )
        if invalid_members:
            raise RuntimeError("Invalid legacy data: ledger_members.role contains unsupported values")
    if "invitations" in table_names:
        invalid_invitations = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM invitations "
                    "WHERE role NOT IN ('member', 'viewer')"
                )
            ).scalar_one()
        )
        if invalid_invitations:
            raise RuntimeError("Invalid legacy data: invitations.role contains unsupported values")


def _validate_expense_split_integrity(connection, table_names: set[str]) -> None:
    """Reject split rows whose expense/member belongs to another ledger."""

    required = {"expense_splits", "expenses", "ledger_members"}
    if not required.issubset(table_names):
        return

    invalid_expense_refs = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expense_splits AS split "
                "LEFT JOIN expenses AS expense "
                "ON expense.id = split.expense_id "
                "AND expense.tenant_id = split.tenant_id "
                "WHERE expense.id IS NULL"
            )
        ).scalar_one()
    )
    if invalid_expense_refs:
        raise RuntimeError(
            "Invalid legacy data: expense_splits contains cross-ledger expense references"
        )

    invalid_member_refs = int(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM expense_splits AS split "
                "LEFT JOIN ledger_members AS member "
                "ON member.id = split.member_id "
                "AND member.ledger_id = split.tenant_id "
                "WHERE member.id IS NULL"
            )
        ).scalar_one()
    )
    if invalid_member_refs:
        raise RuntimeError(
            "Invalid legacy data: expense_splits contains cross-ledger member references"
        )


def _validate_tenant_child_integrity(connection, table_names: set[str]) -> None:
    """Reject tenant-scoped child rows whose parent belongs to another ledger."""

    if {"expense_items", "expenses"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expense_items AS item "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = item.expense_id "
                    "AND expense.tenant_id = item.tenant_id "
                    "WHERE expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise RuntimeError("Invalid legacy data: expense_items contains cross-ledger expense references")

    if {"csv_import_rows", "csv_import_batches"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM csv_import_rows AS row "
                    "LEFT JOIN csv_import_batches AS batch "
                    "ON batch.id = row.batch_id "
                    "AND batch.tenant_id = row.tenant_id "
                    "WHERE batch.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise RuntimeError("Invalid legacy data: csv_import_rows contains cross-ledger batch references")

    if {"csv_import_rows", "expenses"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM csv_import_rows AS row "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = row.expense_id "
                    "AND expense.tenant_id = row.tenant_id "
                    "WHERE row.expense_id IS NOT NULL AND expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise RuntimeError("Invalid legacy data: csv_import_rows contains cross-ledger expense references")

    if {"budget_categories", "budgets"}.issubset(table_names):
        invalid = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM budget_categories AS category "
                    "LEFT JOIN budgets AS budget "
                    "ON budget.tenant_id = category.tenant_id "
                    "AND budget.month = category.month "
                    "WHERE budget.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid:
            raise RuntimeError("Invalid legacy data: budget_categories contains rows without parent budgets")

    if {"expense_tags", "expenses", "tags"}.issubset(table_names):
        invalid_expenses = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expense_tags AS link "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = link.expense_id "
                    "AND expense.tenant_id = link.tenant_id "
                    "WHERE expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_expenses:
            raise RuntimeError("Invalid legacy data: expense_tags contains cross-ledger expense references")
        invalid_tags = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM expense_tags AS link "
                    "LEFT JOIN tags AS tag "
                    "ON tag.id = link.tag_id "
                    "AND tag.tenant_id = link.tenant_id "
                    "WHERE tag.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_tags:
            raise RuntimeError("Invalid legacy data: expense_tags contains cross-ledger tag references")

    if {"rule_application_changes", "rule_application_batches", "expenses"}.issubset(table_names):
        invalid_batches = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM rule_application_changes AS change "
                    "LEFT JOIN rule_application_batches AS batch "
                    "ON batch.id = change.batch_id "
                    "AND batch.tenant_id = change.tenant_id "
                    "WHERE batch.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_batches:
            raise RuntimeError("Invalid legacy data: rule_application_changes contains cross-ledger batch references")
        invalid_expenses = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM rule_application_changes AS change "
                    "LEFT JOIN expenses AS expense "
                    "ON expense.id = change.expense_id "
                    "AND expense.tenant_id = change.tenant_id "
                    "WHERE expense.id IS NULL"
                )
            ).scalar_one()
        )
        if invalid_expenses:
            raise RuntimeError("Invalid legacy data: rule_application_changes contains cross-ledger expense references")


def _validate_goal_unique_scopes(connection, table_names: set[str]) -> None:
    """Reject duplicate active goals before SQLite creates partial UNIQUE indexes."""

    if "goals" not in table_names:
        return

    duplicate_total = connection.execute(
        text(
            "SELECT tenant_id, month, goal_type, period, COUNT(*) AS count "
            "FROM goals "
            "WHERE status = 'active' AND category IS NULL "
            "GROUP BY tenant_id, month, goal_type, period "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).mappings().first()
    if duplicate_total is not None:
        raise RuntimeError(
            "Invalid legacy data: goals contains duplicate active total goals "
            f"for tenant={duplicate_total['tenant_id']} month={duplicate_total['month']}"
        )

    duplicate_category = connection.execute(
        text(
            "SELECT tenant_id, month, goal_type, period, category, COUNT(*) AS count "
            "FROM goals "
            "WHERE status = 'active' AND category IS NOT NULL "
            "GROUP BY tenant_id, month, goal_type, period, category "
            "HAVING COUNT(*) > 1 "
            "LIMIT 1"
        )
    ).mappings().first()
    if duplicate_category is not None:
        raise RuntimeError(
            "Invalid legacy data: goals contains duplicate active category goals "
            f"for tenant={duplicate_category['tenant_id']} month={duplicate_category['month']} "
            f"category={duplicate_category['category']}"
        )


def migrate_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        _validate_family_role_data(connection, table_names)

    if "expenses" not in table_names:
        return

    default_home = DEFAULT_HOME_CURRENCY_CODE
    source_base = FX_SOURCE_BASE
    status_ready = FX_STATUS_READY
    status_pending = FX_STATUS_PENDING
    existing_columns = {column["name"] for column in inspector.get_columns("expenses")}
    required_columns = {
        "tenant_id": f"VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'",
        "public_id": "VARCHAR(36)",
        "thumbnail_path": "VARCHAR(500)",
        "duplicate_status": "VARCHAR(32) NOT NULL DEFAULT 'none'",
        "duplicate_of_id": "INTEGER",
        "duplicate_reason": "VARCHAR(500)",
        "tags": "TEXT",
        "value_score": "INTEGER",
        "regret_score": "INTEGER",
        "ocr_draft_fields": "TEXT",
        "draft_idempotency_key": "VARCHAR(128)",
        "home_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
        "original_amount_minor": "INTEGER",
        "exchange_rate_to_cny": "NUMERIC(18, 8)",
        "exchange_rate_date": "DATE",
        "exchange_rate_source": f"VARCHAR(32) DEFAULT '{source_base}'",
        "fx_status": f"VARCHAR(32) NOT NULL DEFAULT '{status_ready}'",
        "image_deleted_at": "DATETIME",
        "thumbnail_deleted_at": "DATETIME",
    }

    with engine.begin() as connection:
        for name, ddl in required_columns.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE expenses ADD COLUMN {name} {ddl}"))

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_expenses_id_tenant_id "
                "ON expenses (id, tenant_id)"
            )
        )
        connection.execute(
            text("UPDATE expenses SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
            {"tenant_id": DEFAULT_TENANT_ID},
        )
        connection.execute(
            text("UPDATE expenses SET original_currency_code = :home WHERE original_currency_code IS NULL OR original_currency_code = ''"),
            {"home": default_home},
        )
        connection.execute(
            text("UPDATE expenses SET home_currency_code = :home WHERE home_currency_code IS NULL OR home_currency_code = ''"),
            {"home": default_home},
        )
        connection.execute(
            text(
                "UPDATE expenses SET original_amount_minor = amount_cents "
                "WHERE original_amount_minor IS NULL "
                "AND amount_cents IS NOT NULL "
                "AND original_currency_code = :home"
            ),
            {"home": default_home},
        )
        connection.execute(
            text(
                "UPDATE expenses SET exchange_rate_to_cny = 1 "
                "WHERE exchange_rate_to_cny IS NULL "
                "AND amount_cents IS NOT NULL "
                "AND original_currency_code = :home"
            ),
            {"home": default_home},
        )
        connection.execute(
            text(
                "UPDATE expenses SET amount_cents = NULL "
                "WHERE original_currency_code != :home "
                "AND original_amount_minor IS NOT NULL "
                "AND exchange_rate_to_cny IS NULL"
            ),
            {"home": default_home},
        )
        connection.execute(
            text(
                "UPDATE expenses SET exchange_rate_source = NULL "
                "WHERE original_currency_code != :home "
                "AND amount_cents IS NULL "
                "AND exchange_rate_to_cny IS NULL"
            ),
            {"home": default_home},
        )
        connection.execute(
            text(
                "UPDATE expenses SET exchange_rate_source = :source_base "
                "WHERE exchange_rate_source IS NULL AND original_currency_code = :home"
            ),
            {"source_base": source_base, "home": default_home},
        )
        connection.execute(
            text(
                "UPDATE expenses SET exchange_rate_date = date(COALESCE(expense_time, confirmed_at, created_at)) "
                "WHERE exchange_rate_date IS NULL AND amount_cents IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE expenses SET fx_status = :pending "
                "WHERE amount_cents IS NULL "
                "AND original_amount_minor IS NOT NULL "
                "AND original_currency_code != :home"
            ),
            {"home": default_home, "pending": status_pending},
        )
        connection.execute(
            text(
                "UPDATE expenses SET fx_status = :ready "
                "WHERE fx_status IS NULL OR fx_status = ''"
            ),
            {"ready": status_ready},
        )
        public_id_rows = connection.execute(
            text("SELECT id FROM expenses WHERE public_id IS NULL OR public_id = ''")
        ).mappings()
        for row in public_id_rows:
            connection.execute(
                text("UPDATE expenses SET public_id = :public_id WHERE id = :id"),
                {"public_id": str(uuid4()), "id": row["id"]},
            )
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_expenses_public_id ON expenses (public_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_status_created_at ON expenses (status, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_category_status ON expenses (category, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_status_expense_time ON expenses (status, expense_time)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_status_confirmed_at ON expenses (status, confirmed_at)"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_status_category_expense_time "
                "ON expenses (status, category, expense_time)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_status_category_confirmed_at "
                "ON expenses (status, category, confirmed_at)"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_expenses_status_amount_merchant ON expenses (status, amount_cents, merchant)")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_status_merchant_expense_time "
                "ON expenses (status, merchant, expense_time)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_status_merchant_confirmed_at "
                "ON expenses (status, merchant, confirmed_at)"
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_status ON expenses (duplicate_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_of_id ON expenses (duplicate_of_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_image_hash ON expenses (image_hash)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_created_at ON expenses (tenant_id, status, created_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_category_status ON expenses (tenant_id, category, status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_expense_time ON expenses (tenant_id, status, expense_time)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_confirmed_at ON expenses (tenant_id, status, confirmed_at)"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_category_expense_time "
                "ON expenses (tenant_id, status, category, expense_time)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_category_confirmed_at "
                "ON expenses (tenant_id, status, category, confirmed_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_amount_merchant "
                "ON expenses (tenant_id, status, amount_cents, merchant)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_merchant_expense_time "
                "ON expenses (tenant_id, status, merchant, expense_time)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_status_merchant_confirmed_at "
                "ON expenses (tenant_id, status, merchant, confirmed_at)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_expenses_tenant_draft_idempotency_key "
                "ON expenses (tenant_id, draft_idempotency_key)"
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_image_hash ON expenses (tenant_id, image_hash)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_duplicate_status ON expenses (tenant_id, duplicate_status)")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_original_currency_date "
                "ON expenses (tenant_id, original_currency_code, exchange_rate_date)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_expenses_tenant_fx_status "
                "ON expenses (tenant_id, fx_status)"
            )
        )

        if "category_rules" in table_names:
            category_rule_columns = {column["name"] for column in inspector.get_columns("category_rules")}
            if "tenant_id" not in category_rule_columns:
                connection.execute(
                    text(f"ALTER TABLE category_rules ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'")
                )
            category_rule_additions = {
                "amount_min_cents": "INTEGER",
                "amount_max_cents": "INTEGER",
                "source_contains": "VARCHAR(64)",
                "tag_contains": "VARCHAR(64)",
            }
            for column_name, column_type in category_rule_additions.items():
                if column_name not in category_rule_columns:
                    connection.execute(
                        text(f"ALTER TABLE category_rules ADD COLUMN {column_name} {column_type}")
                    )
            connection.execute(
                text("UPDATE category_rules SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
                {"tenant_id": DEFAULT_TENANT_ID},
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_priority_id "
                    "ON category_rules (tenant_id, priority, id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_rules_tenant_enabled_priority "
                    "ON category_rules (tenant_id, enabled, priority, id)"
                )
            )

        if "rule_application_batches" in table_names:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rule_application_batches_id_tenant_id "
                    "ON rule_application_batches (id, tenant_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_rule_application_batches_tenant_created_at "
                    "ON rule_application_batches (tenant_id, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_rule_application_batches_tenant_status "
                    "ON rule_application_batches (tenant_id, status)"
                )
            )

        if "rule_application_changes" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_rule_application_changes_tenant_batch "
                    "ON rule_application_changes (tenant_id, batch_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_rule_application_changes_tenant_expense "
                    "ON rule_application_changes (tenant_id, expense_id)"
                )
            )

        if "merchant_aliases" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_canonical "
                    "ON merchant_aliases (tenant_id, canonical_key)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_merchant_aliases_tenant_alias_key "
                    "ON merchant_aliases (tenant_id, alias_key)"
                )
            )

        if "tags" in table_names:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_id_tenant_id "
                    "ON tags (id, tenant_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_tenant_key "
                    "ON tags (tenant_id, key)"
                )
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_key ON tags (tenant_id, key)")
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_name ON tags (tenant_id, name)")
            )

        if "csv_import_batches" in table_names:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_csv_import_batches_id_tenant_id "
                    "ON csv_import_batches (id, tenant_id)"
                )
            )

        if "expense_tags" in table_names:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_tags_tenant_expense_tag "
                    "ON expense_tags (tenant_id, expense_id, tag_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_expense "
                    "ON expense_tags (tenant_id, expense_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_tag "
                    "ON expense_tags (tenant_id, tag_id)"
                )
            )

        if "csv_import_rows" in table_names:
            csv_row_columns = {column["name"] for column in inspector.get_columns("csv_import_rows")}
            csv_row_additions = {
                "apply_token": "VARCHAR(36)",
                "original_currency_code": f"VARCHAR(3) NOT NULL DEFAULT '{default_home}'",
                "original_amount_minor": "INTEGER",
                "exchange_rate_to_cny": "NUMERIC(18, 8)",
                "exchange_rate_date": "DATE",
                "exchange_rate_source": "VARCHAR(32)",
            }
            for column_name, column_type in csv_row_additions.items():
                if column_name not in csv_row_columns:
                    connection.execute(
                        text(f"ALTER TABLE csv_import_rows ADD COLUMN {column_name} {column_type}")
                    )
            connection.execute(
                text(
                    "UPDATE csv_import_rows SET original_currency_code = :home "
                    "WHERE original_currency_code IS NULL OR original_currency_code = ''"
                ),
                {"home": default_home},
            )
            connection.execute(
                text(
                    "UPDATE csv_import_rows SET original_amount_minor = amount_cents "
                    "WHERE original_amount_minor IS NULL "
                    "AND amount_cents IS NOT NULL "
                    "AND original_currency_code = :home"
                ),
                {"home": default_home},
            )
            connection.execute(
                text(
                    "UPDATE csv_import_rows SET exchange_rate_to_cny = 1 "
                    "WHERE exchange_rate_to_cny IS NULL "
                    "AND amount_cents IS NOT NULL "
                    "AND original_currency_code = :home"
                ),
                {"home": default_home},
            )
            connection.execute(
                text(
                    "UPDATE csv_import_rows SET exchange_rate_source = :source_base "
                    "WHERE exchange_rate_source IS NULL AND original_currency_code = :home"
                ),
                {"source_base": source_base, "home": default_home},
            )

        if "csv_import_batches" in table_names:
            csv_batch_columns = {column["name"] for column in inspector.get_columns("csv_import_batches")}
            if "apply_token" not in csv_batch_columns:
                connection.execute(text("ALTER TABLE csv_import_batches ADD COLUMN apply_token VARCHAR(36)"))

        if "duplicate_ignores" in table_names:
            duplicate_ignore_columns = {column["name"] for column in inspector.get_columns("duplicate_ignores")}
            if "tenant_id" not in duplicate_ignore_columns:
                connection.execute(
                    text(f"ALTER TABLE duplicate_ignores ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'")
                )
            if "kind" not in duplicate_ignore_columns:
                connection.execute(text("ALTER TABLE duplicate_ignores ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'manual'"))
            connection.execute(
                text("UPDATE duplicate_ignores SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
                {"tenant_id": DEFAULT_TENANT_ID},
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_duplicate_ignore_pair_kind "
                    "ON duplicate_ignores (expense_id, duplicate_of_id, kind)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_duplicate_ignore_tenant_pair_kind "
                    "ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_duplicate_ignores_tenant_pair_kind "
                    "ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)"
                )
            )

        if "goals" in table_names:
            _validate_goal_unique_scopes(connection, table_names)
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_active_total_scope "
                    "ON goals (tenant_id, month, goal_type, period) "
                    "WHERE status = 'active' AND category IS NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_active_category_scope "
                    "ON goals (tenant_id, month, goal_type, period, category) "
                    "WHERE status = 'active' AND category IS NOT NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_goals_tenant_month_status "
                    "ON goals (tenant_id, month, status)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_goals_tenant_category_month "
                    "ON goals (tenant_id, category, month)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_goals_tenant_public_id "
                    "ON goals (tenant_id, public_id)"
                )
            )

        # v0.3.1-alpha2: backfill upload_links.public_id for rows created
        # before the column existed.
        if "upload_links" in table_names:
            upload_link_columns = {
                column["name"] for column in inspector.get_columns("upload_links")
            }
            if "public_id" not in upload_link_columns:
                connection.execute(
                    text("ALTER TABLE upload_links ADD COLUMN public_id VARCHAR(36)")
                )
            empty_rows = connection.execute(
                text(
                    "SELECT id FROM upload_links WHERE public_id IS NULL OR public_id = ''"
                )
            ).mappings()
            for row in empty_rows:
                connection.execute(
                    text("UPDATE upload_links SET public_id = :public_id WHERE id = :id"),
                    {"public_id": str(uuid4()), "id": row["id"]},
                )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_upload_links_public_id "
                    "ON upload_links (public_id)"
                )
            )
