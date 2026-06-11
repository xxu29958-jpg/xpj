"""ADR-0041 phase-2 Slice 2 — PostgreSQL backup/restore recovery drill.

Proves the Postgres backup path the Owner Console / scheduled task use actually
round-trips: dumps a populated source database **through the real backend code**
(``backup_service.create_manual_backup`` -> ``pg_dump -Fc``), validates the
archive, restores it into a fresh database with ``pg_restore --exit-on-error``
(non-zero exit fails the drill — a half-restored database that happens to match
on row counts is NOT a usable backup), and asserts EVERY public table came back
with identical row counts.

Runs on the backend-postgres CI lane right after the smoke test (which populates
the source DB). Not needed locally.

    DRILL_SOURCE_URL=postgresql+psycopg://...:.../xpj_smoke \
    DRILL_RESTORE_URL=postgresql+psycopg://...:.../xpj_restore \
        python scripts/postgres_backup_drill.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _counts(url: str) -> dict[str, int]:
    """Row count per PUBLIC table — the whole schema, not a hand-kept list.

    Comparing every table catches a dump/restore that silently dropped a NEW
    table (the old fixed five-table list would have stayed green); comparing
    the table-name SETS catches a table that never came back at all.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
                )
            ]
            return {table: int(conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0) for table in tables}
    finally:
        engine.dispose()


def _pg_restore(dump_path: Path, restore_url: str) -> None:
    from app.services.backup_service import _libpq_url
    from app.services.postgres_backup_validation_service import find_pg_binary

    binary = find_pg_binary("pg_restore", "PG_RESTORE_PATH")
    if not binary:
        raise SystemExit("FAIL drill: pg_restore not found")
    # --exit-on-error: stop at the FIRST failed item instead of pg_restore's
    # default keep-going mode. The drill restores as the ephemeral cluster's
    # superuser into a fresh DB, so there are no benign ownership/extension
    # errors to tolerate — any non-zero exit means objects (indexes,
    # constraints, tables) did not come back and the backup is not proven
    # restorable, even if the row counts of the tables that DID land match.
    result = subprocess.run(
        [binary, "--dbname", _libpq_url(restore_url), "--no-owner", "--exit-on-error", str(dump_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        # Prefer the actual error line — pg_restore's last stderr line is
        # often a SQL continuation fragment, not the message.
        errors = [line for line in lines if "error" in line.lower()]
        detail = errors[-1] if errors else (lines[-1] if lines else "")
        suffix = f": {detail}" if detail else ""
        raise SystemExit(f"FAIL drill: pg_restore exited {result.returncode}{suffix}")


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
        missing = sorted(set(source_counts) - set(restore_counts))
        diffs = {
            table: (source_counts.get(table), restore_counts.get(table))
            for table in sorted(set(source_counts) | set(restore_counts))
            if source_counts.get(table) != restore_counts.get(table)
        }
        raise SystemExit(f"FAIL drill: counts differ missing_tables={missing} (source, restore)={diffs}")
    print(
        f"OK restored data matches source: {len(restore_counts)} tables, "
        f"{sum(restore_counts.values())} rows (incl. expenses={restore_counts.get('expenses', 0)})"
    )

    print("\nPASS postgres backup/restore drill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
