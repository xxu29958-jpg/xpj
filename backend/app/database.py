from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings
from app.tenants import DEFAULT_TENANT_ID, configured_tenants


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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

    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
    seed_runtime_data()


def seed_runtime_data() -> None:
    from app.services.category_service import normalize_existing_expense_categories
    from app.services.classify_service import seed_default_rules

    with SessionLocal() as db:
        normalize_existing_expense_categories(db)
        for tenant in configured_tenants():
            seed_default_rules(db, tenant.id)


def migrate_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "expenses" not in inspector.get_table_names():
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
        "image_deleted_at": "DATETIME",
        "thumbnail_deleted_at": "DATETIME",
    }

    with engine.begin() as connection:
        for name, ddl in required_columns.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE expenses ADD COLUMN {name} {ddl}"))

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
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_status ON expenses (duplicate_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_duplicate_of_id ON expenses (duplicate_of_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_image_hash ON expenses (image_hash)"))
        connection.execute(text("UPDATE expenses SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"), {"tenant_id": DEFAULT_TENANT_ID})
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
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_image_hash ON expenses (tenant_id, image_hash)"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_expenses_tenant_duplicate_status ON expenses (tenant_id, duplicate_status)")
        )

        if "category_rules" in inspector.get_table_names():
            category_rule_columns = {column["name"] for column in inspector.get_columns("category_rules")}
            if "tenant_id" not in category_rule_columns:
                connection.execute(
                    text(f"ALTER TABLE category_rules ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'")
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

        if "duplicate_ignores" in inspector.get_table_names():
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
