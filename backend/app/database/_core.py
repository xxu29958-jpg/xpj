"""Engine, session, Base, and shared low-level SQLite helpers.

Everything in this module is loaded by every other ``app.database`` submodule.
Keep it small and side-effect-light: no validation, no migration, no seeding.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
_is_sqlite = settings.database_url.startswith("sqlite")
_is_memory_sqlite = _is_sqlite and (":memory:" in settings.database_url or settings.database_url == "sqlite://")
# PostgreSQL (ADR-0041): pin every session to UTC at connection startup via the
# libpq ``options`` string. The app stores all timestamps as UTC, and
# ``optimistic_concurrency.updated_at_predicate`` compares a naive-UTC value
# against a ``timestamptz`` column — PostgreSQL interprets the naive literal in
# the session's TimeZone, so a non-UTC session (the home-server runs
# Asia/Shanghai) would offset every OCC comparison by 8h and fail every guarded
# mutate. Setting it through ``options`` (not a transactional ``SET TIME ZONE``)
# means it can't be rolled back with a later transaction. No effect on SQLite.
connect_args = {"check_same_thread": False} if _is_sqlite else {"options": "-c timezone=utc"}
engine_kwargs: dict = {"connect_args": connect_args, "future": True}
# In-memory SQLite needs StaticPool: every new connection otherwise opens a
# fresh empty DB, so schema / data created via one session vanishes when the
# next session connects. StaticPool pins a single underlying sqlite handle
# so all sessions in the process see the same in-memory DB.
#
# Note: under StaticPool, any ``inspect(engine)`` call shares the underlying
# sqlite handle but is wrapped in its own logical SQLAlchemy connection,
# whose release path issues a rollback that wipes any concurrent
# transaction's writes. Migrations / seed code must therefore use
# ``inspect(connection)`` (the same connection that holds the begin block)
# instead of ``inspect(engine)`` — see _migrations.py and _seed.py.
if _is_memory_sqlite:
    engine_kwargs["poolclass"] = StaticPool

engine = create_engine(settings.database_url, **engine_kwargs)
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
