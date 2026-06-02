"""Shared PostgreSQL backup validation (ADR-0041 phase-2).

The PostgreSQL counterpart to :mod:`app.services.sqlite_backup_validation_service`.
After the SQLite→PostgreSQL cut-over the Owner Console and the scheduled task
produce ``pg_dump -Fc`` custom-format archives instead of SQLite snapshots; this
module is the single contract for "is this file a restorable Ticketbox dump".

File-level validation is deliberately shallow: ``pg_restore --list`` parses and
lists the archive's table of contents **without a running server**, so a
non-empty listing proves the file is a well-formed, readable pg_dump archive.
Deeper guarantees — every required table present, the rows actually load, the
recorded ``backend_version`` — require a real restore into a scratch database
and are the recovery drill's job (``scripts``/CI), not a file-level check.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


class PostgresBackupValidationError(RuntimeError):
    """Raised when a file is not a restorable Ticketbox pg_dump archive."""


def _pg_restore_binary() -> str:
    """Locate ``pg_restore`` (``PG_RESTORE_PATH`` override, else PATH)."""
    binary = os.getenv("PG_RESTORE_PATH") or shutil.which("pg_restore")
    if not binary:
        raise PostgresBackupValidationError(
            "pg_restore not found; install the PostgreSQL client tools or set PG_RESTORE_PATH"
        )
    return binary


def validate_postgres_backup_file(path: Path | str) -> None:
    """Raise :class:`PostgresBackupValidationError` unless ``path`` is a readable
    pg_dump custom-format archive (``pg_restore --list`` succeeds, non-empty)."""
    dump_path = Path(path)
    if not dump_path.is_file():
        raise PostgresBackupValidationError(f"backup file does not exist: {dump_path}")

    try:
        result = subprocess.run(  # noqa: S603 (binary resolved from PATH/override, fixed args)
            [_pg_restore_binary(), "--list", str(dump_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PostgresBackupValidationError(f"pg_restore could not run: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise PostgresBackupValidationError(
            "pg_restore --list failed: " + (detail[-1] if detail else f"exit {result.returncode}")
        )
    if not result.stdout.strip():
        raise PostgresBackupValidationError("pg_restore --list produced an empty table of contents")


def is_postgres_backup_valid(path: Path | str) -> bool:
    try:
        validate_postgres_backup_file(path)
    except PostgresBackupValidationError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a restorable Ticketbox pg_dump archive.")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    try:
        validate_postgres_backup_file(args.path)
    except PostgresBackupValidationError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
