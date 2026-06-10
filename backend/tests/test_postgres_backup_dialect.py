"""ADR-0041 phase-2 Slice 2 — PG backup helpers + dump validation.

The PostgreSQL backup *path* itself (real ``pg_dump``/``pg_restore``) is exercised
end-to-end by the recovery drill on the backend-postgres CI lane. These tests
cover the lighter-weight logic: URL normalisation, binary discovery errors, and
the file-level validator's reject paths (which hold whether or not ``pg_restore``
is installed on the runner).
"""

from __future__ import annotations

import shutil

import pytest

import app.services.postgres_backup_validation_service as pgval
from app.errors import AppError
from app.services import backup_service


def test_libpq_url_strips_driver_tag() -> None:
    assert backup_service._libpq_url("postgresql+psycopg://u:p@h:5432/db") == (  # noqa: SLF001
        "postgresql://u:p@h:5432/db"
    )
    # An already-bare libpq URL is left untouched.
    assert backup_service._libpq_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"  # noqa: SLF001


def test_pg_dump_binary_missing_raises_app_error(monkeypatch) -> None:
    # Discovery is the shared find_pg_binary chain (env → PATH → install glob);
    # all three exhausted -> AppError, regardless of what this machine has installed.
    monkeypatch.setattr(backup_service, "find_pg_binary", lambda *_args: None)
    with pytest.raises(AppError) as excinfo:
        backup_service._pg_dump_binary()  # noqa: SLF001
    assert excinfo.value.status_code == 500


def test_find_pg_binary_windows_install_glob_fallback(tmp_path, monkeypatch) -> None:
    # env override and PATH both absent -> fall back to the newest
    # C:\Program Files\PostgreSQL\<ver>\bin install (mirrors backup_database.ps1).
    # This was the nightly-backup gap: the .ps1 globs for pg_dump, but validation
    # runs in Python where pg_restore previously had no such fallback.
    monkeypatch.delenv("PG_RESTORE_PATH", raising=False)
    monkeypatch.setattr(pgval.shutil, "which", lambda _name: None)
    fake_root = tmp_path / "PostgreSQL"
    newest = fake_root / "17" / "bin" / "pg_restore.exe"
    older = fake_root / "16" / "bin" / "pg_restore.exe"
    for binary in (newest, older):
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"")
    monkeypatch.setattr(pgval, "_PG_INSTALL_ROOT", fake_root)
    assert pgval.find_pg_binary("pg_restore", "PG_RESTORE_PATH") == str(newest)
    monkeypatch.setattr(pgval, "_PG_INSTALL_ROOT", tmp_path / "empty")
    assert pgval.find_pg_binary("pg_restore", "PG_RESTORE_PATH") is None


def test_postgres_backup_validation_rejects_missing_file(tmp_path) -> None:
    missing = tmp_path / "ticketbox-nope.dump"
    assert pgval.is_postgres_backup_valid(missing) is False
    with pytest.raises(pgval.PostgresBackupValidationError, match="does not exist"):
        pgval.validate_postgres_backup_file(missing)


def test_postgres_backup_validation_rejects_non_archive(tmp_path) -> None:
    # A plain text file is not a pg_dump archive — invalid whether pg_restore is
    # absent ("not found") or present ("--list failed"); either way -> False.
    bogus = tmp_path / "ticketbox-bogus.dump"
    bogus.write_text("this is not a pg_dump archive")
    assert pgval.is_postgres_backup_valid(bogus) is False


@pytest.mark.skipif(shutil.which("pg_restore") is None, reason="pg_restore not installed")
def test_postgres_backup_validation_reports_pg_restore_failure(tmp_path) -> None:
    bogus = tmp_path / "ticketbox-bogus.dump"
    bogus.write_text("not an archive")
    with pytest.raises(pgval.PostgresBackupValidationError, match="--list failed"):
        pgval.validate_postgres_backup_file(bogus)
