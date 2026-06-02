"""ADR-0041 phase-2 Slice 2 — backup dialect dispatch + PG dump validation.

The PostgreSQL backup *path* itself (real ``pg_dump``/``pg_restore``) is exercised
end-to-end by the recovery drill on the backend-postgres CI lane. These tests
cover the dialect-independent logic: URL normalisation, binary discovery errors,
dispatch routing, and the file-level validator's reject paths (which hold whether
or not ``pg_restore`` is installed on the runner).
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


def test_backup_suffix_follows_dialect(monkeypatch) -> None:
    monkeypatch.setattr(backup_service, "_is_postgres", lambda: True)
    assert backup_service._backup_suffix() == ".dump"  # noqa: SLF001
    monkeypatch.setattr(backup_service, "_is_postgres", lambda: False)
    assert backup_service._backup_suffix() == ".db"  # noqa: SLF001


def test_pg_dump_binary_missing_raises_app_error(monkeypatch) -> None:
    monkeypatch.delenv("PG_DUMP_PATH", raising=False)
    monkeypatch.setattr(backup_service.shutil, "which", lambda _: None)
    with pytest.raises(AppError) as excinfo:
        backup_service._pg_dump_binary()  # noqa: SLF001
    assert excinfo.value.status_code == 500


def test_create_backup_dispatches_by_dialect(monkeypatch) -> None:
    sqlite_marker = object()
    postgres_marker = object()
    monkeypatch.setattr(backup_service, "_create_sqlite_backup", lambda **_: sqlite_marker)
    monkeypatch.setattr(backup_service, "_create_postgres_backup", lambda **_: postgres_marker)

    monkeypatch.setattr(backup_service, "_is_postgres", lambda: False)
    assert backup_service._create_backup(prefix="ticketbox-manual", kind="manual") is sqlite_marker  # noqa: SLF001

    monkeypatch.setattr(backup_service, "_is_postgres", lambda: True)
    assert (
        backup_service._create_backup(prefix="ticketbox-manual", kind="manual")  # noqa: SLF001
        is postgres_marker
    )


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
