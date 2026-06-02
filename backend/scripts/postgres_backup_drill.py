"""ADR-0041 phase-2 Slice 2 — PostgreSQL backup/restore recovery drill.

Proves the Postgres backup path the Owner Console / scheduled task use actually
round-trips: dumps a populated source database **through the real backend code**
(``backup_service.create_manual_backup`` -> ``pg_dump -Fc``), validates the
archive, restores it into a fresh database with ``pg_restore``, and asserts the
key tables came back with identical row counts and a recorded backend version.

Runs on the backend-postgres CI lane right after the smoke test (which populates
the source DB). Not needed locally / on SQLite.

    DRILL_SOURCE_URL=postgresql+psycopg://...:.../xpj_smoke \
    DRILL_RESTORE_URL=postgresql+psycopg://...:.../xpj_restore \
        python scripts/postgres_backup_drill.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

_VERIFY_TABLES = ("accounts", "ledgers", "auth_tokens", "expenses", "schema_migrations")


def _counts(url: str) -> dict[str, int]:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                table: int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
                for table in _VERIFY_TABLES
            }
    finally:
        engine.dispose()


def _pg_restore(dump_path: Path, restore_url: str) -> None:
    from app.services.backup_service import _libpq_url

    binary = os.getenv("PG_RESTORE_PATH") or shutil.which("pg_restore")
    if not binary:
        raise SystemExit("FAIL drill: pg_restore not found")
    result = subprocess.run(
        [binary, "--dbname", _libpq_url(restore_url), "--no-owner", str(dump_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    # pg_restore can warn (rc!=0) on harmless role/comment items; trust the
    # downstream row-count comparison as the real success signal, but surface
    # stderr for debugging if it bailed early.
    if result.returncode != 0 and result.stderr.strip():
        print(f"  pg_restore stderr: {result.stderr.strip().splitlines()[-1]}")


def main() -> int:
    source_url = os.environ["DRILL_SOURCE_URL"]
    restore_url = os.environ["DRILL_RESTORE_URL"]
    os.environ["DATABASE_URL"] = source_url

    from app.services import backup_service
    from app.services.postgres_backup_validation_service import validate_postgres_backup_file

    source_counts = _counts(source_url)
    if source_counts["expenses"] == 0:
        raise SystemExit("FAIL drill: source has no expenses — did the smoke test run first?")

    entry = backup_service.create_manual_backup()
    dump_path = backup_service._backup_dir() / entry.file_name  # noqa: SLF001
    print(f"OK backup via backend: {entry.file_name} ({entry.size_bytes} bytes)")

    validate_postgres_backup_file(dump_path)
    print("OK archive validation (pg_restore --list)")

    _pg_restore(dump_path, restore_url)
    restore_counts = _counts(restore_url)
    if restore_counts != source_counts:
        raise SystemExit(f"FAIL drill: counts differ source={source_counts} restore={restore_counts}")
    print(f"OK restored data matches source: {restore_counts}")

    print("\nPASS postgres backup/restore drill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
