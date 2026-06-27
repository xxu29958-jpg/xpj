"""Engine, session, and Base for the PostgreSQL store.

Everything in this module is loaded by every other ``app.database`` submodule.
Keep it small and side-effect-light: no validation, no migration, no seeding.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_ROOT, get_settings

__all__ = [
    "BACKEND_ROOT",
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "settings",
    "wait_for_db",
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
if settings.database_url.startswith("postgresql"):
    # ``connect_timeout`` (libpq, seconds): a hung connect to a not-yet-ready PG
    # service fails fast and feeds wait_for_db's retry loop instead of blocking
    # startup indefinitely (ADR-0047: PG-as-Windows-service can be RUNNING before
    # it accepts connections).
    connect_args: dict[str, object] = {"options": "-c timezone=utc", "connect_timeout": 10}
else:
    connect_args = {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # ADR-0047: under the service model the PostgreSQL service can be bounced by
    # the SCM independently of the backend, staling every pooled connection.
    # pool_pre_ping revalidates a connection on checkout (a cheap SELECT 1) so the
    # next request transparently reconnects instead of raising OperationalError.
    # Harmless for the never-connected sqlite:// engine the OpenAPI contract dump
    # introspects (it pings sqlite fine if it ever checks out a connection).
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_db(
    *,
    db_engine: Engine | None = None,
    timeout_seconds: float | None = None,
    initial_interval: float = 0.5,
    max_interval: float = 5.0,
) -> None:
    """Block until the database accepts a connection, then return.

    ADR-0047 service deployment: the PostgreSQL Windows service can be reported
    RUNNING by the SCM *before* it actually accepts connections, so the backend
    service may boot into a not-yet-ready DB. Without this gate the first
    connection in ``init_db()`` raises ``OperationalError`` and uvicorn's lifespan
    aborts — the "die after 4 seconds" failure ADR-0047 §3 calls out. In dev/test
    the DB is already up, so the first ping succeeds and this is a no-op.

    Timeout defaults to ``TICKETBOX_DB_WAIT_TIMEOUT_SECONDS`` (60s). On exhaustion
    a clear ``TimeoutError`` is raised (chained to the last connect error) rather
    than the opaque per-attempt OperationalError.
    """
    import os
    import time

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    eng = db_engine if db_engine is not None else engine
    if timeout_seconds is None:
        timeout_seconds = float(os.getenv("TICKETBOX_DB_WAIT_TIMEOUT_SECONDS", "60"))

    deadline = time.monotonic() + timeout_seconds
    interval = initial_interval
    last_err: Exception | None = None
    while True:
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            last_err = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"PostgreSQL did not accept connections within "
                    f"{timeout_seconds:.0f}s (database service not running, or "
                    f"DATABASE_URL incorrect?)"
                ) from last_err
            time.sleep(min(interval, remaining))
            interval = min(interval * 2, max_interval)
