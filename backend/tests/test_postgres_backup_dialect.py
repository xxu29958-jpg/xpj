"""ADR-0041 phase-2 Slice 2 — PG backup helpers + dump validation.

The PostgreSQL backup *path* itself (real ``pg_dump``/``pg_restore``) is exercised
end-to-end by the recovery drill on the backend-postgres CI lane. These tests
cover the lighter-weight logic: URL normalisation, binary discovery errors, and
the file-level validator's reject paths (which hold whether or not ``pg_restore``
is installed on the runner).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.postgres_backup_validation_service as pgval
from app.errors import AppError
from app.services import backup_service
from scripts import postgres_backup_drill


def _assert_pg_restore_password_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    encoded_password: str,
    decoded_password: str,
) -> None:
    observed: dict[str, object] = {}

    def fake_restore(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if arguments[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout="pg_restore (PostgreSQL) 17.10\n",
                stderr="",
            )
        observed["arguments"] = arguments
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(pgval, "find_pg_binary", lambda *_args: "pg_restore-probe")
    monkeypatch.setattr(postgres_backup_drill.subprocess, "run", fake_restore)
    postgres_backup_drill._pg_restore(tmp_path / "archive.dump", database_url)  # noqa: SLF001
    arguments = observed["arguments"]
    environment = observed["environment"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert decoded_password not in arguments
    assert encoded_password not in " ".join(arguments)
    assert environment["PGPASSWORD"] == decoded_password
    assert environment["PGREQUIREAUTH"] == "scram-sha-256"

    monkeypatch.setattr(
        postgres_backup_drill.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            1,
            stdout=database_url,
            stderr=f"connection failed for password={decoded_password}",
        ),
    )
    with pytest.raises(SystemExit) as restore_error:
        postgres_backup_drill._pg_restore(tmp_path / "archive.dump", database_url)  # noqa: SLF001
    assert decoded_password not in str(restore_error.value)
    assert encoded_password not in str(restore_error.value)


def test_pg_tools_keep_password_out_of_process_arguments(tmp_path, monkeypatch, caplog) -> None:
    encoded_password = "p%40ss%3Aword%2F%3F%23%25"
    decoded_password = "p@ss:word/?#%"
    database_url = (
        f"postgresql+psycopg://ticketbox:{encoded_password}@localhost:5432/ticketbox"
        "?sslmode=require"
    )
    connection = backup_service._pg_tool_connection(database_url)  # noqa: SLF001
    assert connection.database_url == (
        "postgresql://ticketbox@localhost:5432/ticketbox?sslmode=require"
    )
    assert connection.password == decoded_password
    with pytest.raises(AppError) as query_password_error:
        backup_service._pg_tool_connection(  # noqa: SLF001
            "postgresql://ticketbox@localhost/ticketbox?password=query-secret"
        )
    assert "query-secret" not in str(query_password_error.value)

    observed: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        observed["arguments"] = arguments
        observed["environment"] = kwargs["env"]
        Path(arguments[arguments.index("--file") + 1]).write_bytes(b"probe")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup_service, "get_settings", lambda: SimpleNamespace(database_url=database_url))
    monkeypatch.setattr(backup_service, "_pg_dump_binary", lambda: "pg_dump-probe")
    monkeypatch.setattr(backup_service, "is_postgres_backup_valid", lambda _path: True)
    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)
    monkeypatch.setenv("PGPASSWORD", "parent-password")

    backup_service._run_pg_dump(prefix="ticketbox-manual", kind="manual")  # noqa: SLF001
    arguments = observed["arguments"]
    environment = observed["environment"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert decoded_password not in arguments
    assert encoded_password not in " ".join(arguments)
    assert environment["PGPASSWORD"] == decoded_password
    assert environment["PGREQUIREAUTH"] == "scram-sha-256"
    assert os.environ["PGPASSWORD"] == "parent-password"
    assert "PGPASSWORD" not in backup_service._pg_tool_environment(None)  # noqa: SLF001
    assert os.environ["PGPASSWORD"] == "parent-password"

    def failed_run(arguments, **_kwargs):
        return subprocess.CompletedProcess(
            arguments,
            1,
            stdout=database_url,
            stderr=f"connection failed for password={decoded_password}",
        )

    monkeypatch.setattr(backup_service.subprocess, "run", failed_run)
    with caplog.at_level(logging.WARNING), pytest.raises(AppError):
        backup_service._run_pg_dump(prefix="ticketbox-manual", kind="manual")  # noqa: SLF001
    assert decoded_password not in caplog.text
    assert encoded_password not in caplog.text
    assert database_url not in caplog.text
    assert os.environ["PGPASSWORD"] == "parent-password"

    _assert_pg_restore_password_isolated(
        tmp_path,
        monkeypatch,
        database_url,
        encoded_password,
        decoded_password,
    )


def test_pg_dump_binary_missing_raises_app_error(monkeypatch) -> None:
    # Discovery is the shared find_pg_binary chain (env → PATH → install glob);
    # all three exhausted -> AppError, regardless of what this machine has installed.
    monkeypatch.setattr(backup_service, "find_pg_binary", lambda *_args: None)
    with pytest.raises(AppError) as excinfo:
        backup_service._pg_dump_binary()  # noqa: SLF001
    assert excinfo.value.status_code == 500


def test_find_pg_binary_windows_install_glob_fallback(tmp_path, monkeypatch) -> None:
    # env override and PATH both absent -> fall back to the newest
    # OS Program Files/PostgreSQL/<ver>/bin install (mirrors backup_database.ps1).
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


def test_find_pg_binary_prefers_numerically_newest_install(tmp_path, monkeypatch) -> None:
    # codex review P3 #8: a plain string sort on the glob results picks 9.x
    # over 17 ("9" > "1" lexicographically) when an old client lingers next to
    # the current install — the backup would silently run with the old tools.
    monkeypatch.delenv("PG_RESTORE_PATH", raising=False)
    monkeypatch.setattr(pgval.shutil, "which", lambda _name: None)
    fake_root = tmp_path / "PostgreSQL"
    modern = fake_root / "17" / "bin" / "pg_restore.exe"
    legacy = fake_root / "9.6" / "bin" / "pg_restore.exe"
    junk = fake_root / "scratch" / "bin" / "pg_restore.exe"
    for binary in (modern, legacy, junk):
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"")
    monkeypatch.setattr(pgval, "_PG_INSTALL_ROOT", fake_root)
    assert pgval.find_pg_binary("pg_restore", "PG_RESTORE_PATH") == str(modern)


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


@pytest.mark.skipif(
    # Same discovery chain the validator itself uses (env -> PATH -> Program
    # Files glob): a PATH-only check skipped this on hosts where the glob
    # finds pg_restore and the validator would actually run.
    pgval.find_pg_binary("pg_restore", "PG_RESTORE_PATH") is None,
    reason="pg_restore not found anywhere",
)
def test_postgres_backup_validation_reports_pg_restore_failure(tmp_path) -> None:
    bogus = tmp_path / "ticketbox-bogus.dump"
    bogus.write_text("not an archive")
    with pytest.raises(pgval.PostgresBackupValidationError, match="--list failed"):
        pgval.validate_postgres_backup_file(bogus)
