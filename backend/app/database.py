from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
import secrets
import shutil
import sqlite3
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_ROOT, get_settings
from app.tenants import DEFAULT_TENANT_ID


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
    seed_identity_data()
    # v0.3.1-alpha2: do NOT auto-migrate legacy uploads on startup. Old image
    # paths remain readable through resolve_protected_image() after the route
    # has verified expense ownership. See docs/ROLLBACK.md.
    seed_runtime_data()


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
    from app.models import Budget, BudgetCategory, CategoryRule, DuplicateIgnore, Expense, ExpenseTag, Goal, MerchantAlias, RuleApplicationBatch, RuleApplicationChange, Tag
    from app.services.identity_service import ensure_identity_for_existing_ledger_ids, ensure_identity_seed

    with SessionLocal() as db:
        ensure_identity_seed(db)
        ids: set[str] = set()
        if inspect(engine).has_table("expenses"):
            ids.update(str(value) for value in db.scalars(select(Expense.tenant_id).distinct()) if value)
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
        if inspect(engine).has_table("goals"):
            ids.update(str(value) for value in db.scalars(select(Goal.tenant_id).distinct()) if value)
        if inspect(engine).has_table("rule_application_batches"):
            ids.update(str(value) for value in db.scalars(select(RuleApplicationBatch.tenant_id).distinct()) if value)
        if inspect(engine).has_table("rule_application_changes"):
            ids.update(str(value) for value in db.scalars(select(RuleApplicationChange.tenant_id).distinct()) if value)
        if ids:
            ensure_identity_for_existing_ledger_ids(db, ids)
        db.commit()


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


def migrate_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.begin() as connection:
        _validate_family_role_data(connection, table_names)

    if "expenses" not in table_names:
        return

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
        "image_deleted_at": "DATETIME",
        "thumbnail_deleted_at": "DATETIME",
    }

    with engine.begin() as connection:
        for name, ddl in required_columns.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE expenses ADD COLUMN {name} {ddl}"))

        connection.execute(
            text("UPDATE expenses SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
            {"tenant_id": DEFAULT_TENANT_ID},
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
