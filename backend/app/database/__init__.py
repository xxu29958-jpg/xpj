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
        "baseline-v0.9.0a1",
        backend_version=BACKEND_VERSION,
        note="legacy hand-written migrate_sqlite_schema baseline",
    )
    seed_identity_data()
    validate_sqlite_data_integrity()
    # v0.3.1-alpha2: do NOT auto-migrate legacy uploads on startup. Old image
    # paths remain readable through resolve_protected_image() after the route
    # has verified expense ownership. See docs/runbook/ROLLBACK.md.
    seed_runtime_data()
