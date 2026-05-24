"""SQLite PRAGMA foreign_key_check wrapper — fail-fast on violations."""

from __future__ import annotations

from sqlalchemy import text

from app.errors import DataIntegrityError


def _validate_sqlite_foreign_keys(connection) -> None:
    try:
        violations = list(connection.execute(text("PRAGMA foreign_key_check")).mappings())
    except Exception as exc:
        raise DataIntegrityError("Invalid legacy data: SQLite foreign_key_check could not run") from exc
    if not violations:
        return
    samples = ", ".join(
        f"{row['table']} rowid={row['rowid']} parent={row['parent']}"
        for row in violations[:3]
    )
    raise DataIntegrityError(f"Invalid legacy data: SQLite foreign_key_check failed: {samples}")
