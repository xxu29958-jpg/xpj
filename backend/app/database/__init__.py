"""Database package facade.

Public API is unchanged from the pre-split monolithic ``app.database`` module:
external callers still import ``Base``, ``SessionLocal``, ``engine``,
``get_db``, ``init_db`` (and a few legacy re-exports like ``BACKEND_ROOT``)
from ``app.database``. Internals are split across private submodules by
responsibility — see each ``_*.py`` for what lives where.

Nothing here does work at import time except materialising the engine via
``_core``. ``init_db`` is the only function that coordinates startup; the
other public symbols are direct re-exports.
"""

from __future__ import annotations

from app.database._backup import backup_sqlite_database_once, reset_sqlite_backup_state
from app.database._core import (
    BACKEND_ROOT,
    Base,
    SessionLocal,
    engine,
    get_db,
    settings,
)
from app.database._migrations import (
    BASELINE_MIGRATION_NAME,
    is_schema_migration_applied,
    migrate_sqlite_schema,
    record_schema_migration,
)
from app.database._seed import seed_identity_data, seed_runtime_data
from app.database._uploads import migrate_upload_paths_to_tenant_dirs
from app.database._validate import validate_sqlite_data_integrity
from app.version import BACKEND_VERSION

__all__ = [
    "BACKEND_ROOT",
    "BASELINE_MIGRATION_NAME",
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
    "is_schema_migration_applied",
    "migrate_sqlite_schema",
    "migrate_upload_paths_to_tenant_dirs",
    "record_schema_migration",
    "reset_sqlite_backup_state",
    "seed_identity_data",
    "seed_runtime_data",
    "settings",
    "validate_sqlite_data_integrity",
]


def init_db() -> None:
    from app import models  # noqa: F401

    backup_sqlite_database_once()
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema()
    record_schema_migration(
        BASELINE_MIGRATION_NAME,
        backend_version=BACKEND_VERSION,
        note="legacy hand-written migrate_sqlite_schema baseline",
    )
    _stamp_alembic_baseline_if_needed()
    seed_identity_data()
    validate_sqlite_data_integrity()
    # v0.3.1-alpha2: do NOT auto-migrate legacy uploads on startup. Old image
    # paths remain readable through resolve_protected_image() after the route
    # has verified expense ownership. See docs/runbook/ROLLBACK.md.
    seed_runtime_data()


def _stamp_alembic_baseline_if_needed() -> None:
    """Mark the DB as being at the v1.1 baseline revision when no
    alembic_version row exists yet.

    The legacy idempotent migrator already produced the v1.1 schema for
    existing DBs; we stamp the baseline so future ``alembic upgrade
    head`` calls don't try to replay revisions whose effects are already
    in the schema. Doing this inside ``init_db`` keeps the dev / prod
    flow identical: no separate ``alembic stamp`` step.
    """
    from pathlib import Path

    from sqlalchemy import inspect, text

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError:
        return

    backend_root = Path(__file__).resolve().parents[2]
    ini_path = backend_root / "alembic.ini"
    if not ini_path.is_file():
        return

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    try:
        head = ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return
    if head is None:
        return

    with engine.begin() as connection:
        has_table = "alembic_version" in set(inspect(connection).get_table_names())
        if not has_table:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) PRIMARY KEY)"
                )
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": head},
            )
