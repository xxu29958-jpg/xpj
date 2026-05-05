from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


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
        seed_default_rules(db)


def migrate_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "expenses" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("expenses")}
    required_columns = {
        "public_id": "VARCHAR(36)",
        "thumbnail_path": "VARCHAR(500)",
        "duplicate_status": "VARCHAR(32) NOT NULL DEFAULT 'none'",
        "duplicate_of_id": "INTEGER",
        "duplicate_reason": "VARCHAR(500)",
        "tags": "TEXT",
        "value_score": "INTEGER",
        "regret_score": "INTEGER",
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

        if "duplicate_ignores" in inspector.get_table_names():
            duplicate_ignore_columns = {column["name"] for column in inspector.get_columns("duplicate_ignores")}
            if "kind" not in duplicate_ignore_columns:
                connection.execute(text("ALTER TABLE duplicate_ignores ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'manual'"))
