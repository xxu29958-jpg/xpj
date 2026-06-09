"""Engine, session, and Base for the PostgreSQL store.

Everything in this module is loaded by every other ``app.database`` submodule.
Keep it small and side-effect-light: no validation, no migration, no seeding.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_ROOT, get_settings

__all__ = [
    "BACKEND_ROOT",
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "settings",
]


settings = get_settings()
# PostgreSQL (ADR-0041): pin every session to UTC at connection startup via the
# libpq ``options`` string. The app stores all timestamps as UTC and binds
# naive-UTC values into queries against ``timestamptz`` columns (date-range
# filters, ``COALESCE(expense_time, confirmed_at)`` stats, soft-delete windows).
# PostgreSQL interprets a naive literal in the session's TimeZone, so a non-UTC
# session (the home-server runs Asia/Shanghai) would offset every such
# comparison by 8h. (ADR-0041 also moved the OCC CAS off ``updated_at`` onto the
# integer ``row_version``, so OCC no longer depends on this — but the time-range
# queries still do.) Setting it through ``options`` (not a transactional
# ``SET TIME ZONE``) means it can't be rolled back with a later transaction.
#
# Guarded on the ``postgresql`` dialect only so the libpq-specific ``options``
# arg is not handed to the never-connected ``sqlite://`` engine the OpenAPI
# contract dump (``scripts/check_api_contract.py``) spins up purely to
# introspect the schema without a database server.
connect_args = {"options": "-c timezone=utc"} if settings.database_url.startswith("postgresql") else {}
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
