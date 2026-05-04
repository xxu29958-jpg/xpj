from __future__ import annotations

from collections.abc import Generator

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
    from app.services.classify_service import seed_default_rules

    with SessionLocal() as db:
        seed_default_rules(db)


def migrate_sqlite_schema() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "expenses" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("expenses")}
    required_columns = {
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

        if "duplicate_ignores" in inspector.get_table_names():
            duplicate_ignore_columns = {column["name"] for column in inspector.get_columns("duplicate_ignores")}
            if "kind" not in duplicate_ignore_columns:
                connection.execute(text("ALTER TABLE duplicate_ignores ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'manual'"))
