"""Pre-v0.3 SQLite snapshot taken once per process start.

Only runs when the SQLite file pre-dates the v0.3 identity schema (i.e. is
missing the new identity tables). Anything past that point is the
:mod:`app.services.backup_service` rolling backup.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.config import DATA_ROOT
from app.database._core import settings
from app.errors import DataIntegrityError, PathTraversalError

__all__ = [
    "V03_IDENTITY_TABLES",
    "backup_sqlite_database_once",
    "reset_sqlite_backup_state",
]


V03_IDENTITY_TABLES = {
    "accounts",
    "ledgers",
    "ledger_members",
    "devices",
    "auth_tokens",
    "upload_links",
    "pairing_codes",
}


_sqlite_backup_done = False


def _sqlite_database_path() -> Path | None:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    raw_path = settings.database_url[len(prefix):]
    if raw_path in {"", ":memory:"}:
        return None
    return Path(raw_path)


def reset_sqlite_backup_state(*, done: bool = False) -> None:
    """Reset the once-per-process pre-v0.3 backup guard.

    Test-only hook. Production code never needs to flip this — the flag is
    set exactly once on first ``init_db()`` call. Tests that re-run
    ``init_db()`` against scratch databases use this to either re-arm the
    backup (``done=False``) or pretend it already ran (``done=True``).
    """

    global _sqlite_backup_done
    _sqlite_backup_done = done


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

    backup_dir = DATA_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = f"{db_path.stem}-pre-v0.3-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"
    backup_path = (backup_dir / backup_name).resolve()
    try:
        backup_path.relative_to(backup_dir.resolve())
    except ValueError as exc:
        raise PathTraversalError("SQLite backup target escaped backup directory") from exc
    shutil.copy2(db_path, backup_path)
    return backup_path


def _needs_pre_v03_backup(db_path: Path) -> bool:
    try:
        with sqlite3.connect(db_path) as connection:
            table_rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    except sqlite3.DatabaseError as exc:
        raise DataIntegrityError(f"SQLite database cannot be inspected before migration: {db_path}") from exc
    table_names = {str(row[0]) for row in table_rows}
    if not table_names:
        return False
    return not V03_IDENTITY_TABLES.issubset(table_names)
