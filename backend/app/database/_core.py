"""Engine, session, Base, and shared low-level SQLite helpers.

Everything in this module is loaded by every other ``app.database`` submodule.
Keep it small and side-effect-light: no validation, no migration, no seeding.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_ROOT, get_settings


__all__ = [
    "BACKEND_ROOT",
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "settings",
    "_sqlite_column_names",
]


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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


def _sqlite_column_names(connection, table_name: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    }
