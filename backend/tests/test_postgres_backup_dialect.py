"""Bounded PostgreSQL archive adapter and complete-generation CI drill."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

import app.services.postgres_backup_adapter as postgres_adapter
import app.services.postgres_backup_validation_service as pgval
from app.errors import AppError
from app.services.secure_file import write_protected_file_exclusive
from scripts import postgres_backup_drill

_DATABASE_URL = "postgresql+psycopg://ticketbox@localhost:5432/ticketbox?require_auth=scram-sha-256&sslmode=require"


def _tool(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"tool-probe")
    return path.resolve(strict=True)


def _passfile(tmp_path: Path) -> Path:
    path = tmp_path / "ticketbox.pgpass"
    write_protected_file_exclusive(
        path,
        "localhost:5432:ticketbox:ticketbox:protected-secret\n",
    )
    return path.resolve(strict=True)


def test_recovery_drill_uses_complete_dataset_generation_and_bounded_restore() -> None:
    source = Path(postgres_backup_drill.__file__).read_text(encoding="utf-8")

    assert "CompleteBackupRequest" in source
    assert "create_complete_backup_generation" in source
    assert "run_isolated_dataset_restore_action" in source
    assert "restored-originals" in source
    assert "create_manual_backup" not in source
    assert "_pg_tool_connection" not in source
    assert "_pg_tool_environment" not in source


def test_restore_uses_explicit_passfile_and_single_transaction(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}
    archive = tmp_path / "database.dump"
    archive.write_bytes(b"archive-probe")
    binary = _tool(tmp_path, "pg_restore-probe")
    passfile = _passfile(tmp_path)

    def fake_restore(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        observed["arguments"] = arguments
        observed["environment"] = environment
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["timeout"] == postgres_adapter._PG_RESTORE_TIMEOUT_SECONDS  # noqa: SLF001
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(postgres_adapter, "validate_postgres_backup_file_with_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(postgres_adapter.subprocess, "run", fake_restore)
    postgres_adapter.restore_postgres_archive(
        database_url=_DATABASE_URL,
        passfile=passfile,
        pg_restore_binary=binary,
        archive=archive,
        restore_role="ticketbox_owner",
    )

    arguments = observed["arguments"]
    environment = observed["environment"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert "--no-password" in arguments
    assert "--single-transaction" in arguments
    assert "--exit-on-error" in arguments
    assert "--no-owner" in arguments
    assert "--no-privileges" in arguments
    assert arguments[arguments.index("--role") + 1] == "ticketbox_owner"
    assert "protected-secret" not in " ".join(arguments)
    assert environment["PGPASSFILE"] == str(passfile)
    assert "PGPASSWORD" not in environment
    assert passfile.exists()


def test_restore_failures_are_bounded_and_sanitized(tmp_path, monkeypatch, caplog) -> None:
    archive = tmp_path / "database.dump"
    archive.write_bytes(b"archive-probe")
    binary = _tool(tmp_path, "pg_restore-probe")
    passfile = _passfile(tmp_path)
    monkeypatch.setattr(postgres_adapter, "validate_postgres_backup_file_with_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        postgres_adapter.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            1,
            stdout="postgresql://secret@example.invalid/db",
            stderr="password=protected-secret",
        ),
    )

    with caplog.at_level(logging.WARNING), pytest.raises(AppError) as failed:
        postgres_adapter.restore_postgres_archive(
            database_url=_DATABASE_URL,
            passfile=passfile,
            pg_restore_binary=binary,
            archive=archive,
            restore_role="ticketbox_owner",
        )
    assert failed.value.error == "backup_incomplete"
    assert "protected-secret" not in caplog.text
    assert "example.invalid" not in caplog.text

    def timeout_restore(arguments: list[str], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr(postgres_adapter.subprocess, "run", timeout_restore)
    with pytest.raises(AppError) as timed_out:
        postgres_adapter.restore_postgres_archive(
            database_url=_DATABASE_URL,
            passfile=passfile,
            pg_restore_binary=binary,
            archive=archive,
            restore_role="ticketbox_owner",
        )
    assert timed_out.value.error == "backup_incomplete"


def test_pg_tool_connection_rejects_credentials_and_unsafe_routes() -> None:
    connection = postgres_adapter._pg_tool_connection(_DATABASE_URL)  # noqa: SLF001
    assert connection.database_url == (
        "postgresql://ticketbox@localhost:5432/ticketbox?connect_timeout=5&require_auth=scram-sha-256&sslmode=require"
    )
    assert connection.username == "ticketbox"

    unsafe_urls = (
        "postgresql://ticketbox:secret@localhost/ticketbox?require_auth=scram-sha-256",
        "postgresql://ticketbox@localhost/ticketbox?password=query-secret&require_auth=scram-sha-256",
        "postgresql://ticketbox@localhost/ticketbox?passfile=other.pgpass&require_auth=scram-sha-256",
        "postgresql://ticketbox@localhost/ticketbox?service=production&require_auth=scram-sha-256",
        "postgresql://ticketbox@localhost/ticketbox?hostaddr=203.0.113.7&require_auth=scram-sha-256",
        "postgresql://ticketbox@localhost/ticketbox?connect_timeout=0&require_auth=scram-sha-256",
    )
    for url in unsafe_urls:
        with pytest.raises(AppError):
            postgres_adapter._pg_tool_connection(url)  # noqa: SLF001


def test_dump_uses_explicit_passfile_and_cleans_partial(tmp_path, monkeypatch, caplog) -> None:
    observed: dict[str, object] = {}
    target = tmp_path / "database.dump"
    dump_binary = _tool(tmp_path, "pg_dump-probe")
    restore_binary = _tool(tmp_path, "pg_restore-probe")
    passfile = _passfile(tmp_path)

    def fake_dump(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        observed["arguments"] = arguments
        observed["environment"] = environment
        Path(arguments[arguments.index("--file") + 1]).write_bytes(b"archive-probe")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(postgres_adapter, "validate_postgres_backup_file_with_tool", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(postgres_adapter.subprocess, "run", fake_dump)
    poisoned = {
        "DATABASE_URL": "postgresql://ambient-secret@production.example/finance",
        "PGHOST": "production.example",
        "PGPASSWORD": "parent-password",
        "PGSERVICE": "production",
    }
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)

    postgres_adapter.write_postgres_archive(
        database_url=_DATABASE_URL,
        passfile=passfile,
        pg_dump_binary=dump_binary,
        pg_restore_binary=restore_binary,
        target=target,
        synchronized_snapshot="00000003-0000001B-1",
    )
    arguments = observed["arguments"]
    environment = observed["environment"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert "--no-password" in arguments
    assert "--format=custom" in arguments
    assert "--lock-wait-timeout=30000" in arguments
    assert "--snapshot=00000003-0000001B-1" in arguments
    assert not set(poisoned) & set(environment)
    assert target.read_bytes() == b"archive-probe"
    assert passfile.exists()
    assert all(os.environ[key] == value for key, value in poisoned.items())

    failed_target = tmp_path / "failed.dump"
    monkeypatch.setattr(
        postgres_adapter.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            1,
            stdout=_DATABASE_URL,
            stderr="password=protected-secret",
        ),
    )
    with caplog.at_level(logging.WARNING), pytest.raises(AppError):
        postgres_adapter.write_postgres_archive(
            database_url=_DATABASE_URL,
            passfile=passfile,
            pg_dump_binary=dump_binary,
            pg_restore_binary=restore_binary,
            target=failed_target,
            synchronized_snapshot="00000003-0000001B-1",
        )
    assert not failed_target.exists()
    assert not (tmp_path / ".failed.dump.partial").exists()
    assert "protected-secret" not in caplog.text


def test_explicit_missing_binary_or_passfile_fails_closed(tmp_path) -> None:
    target = tmp_path / "database.dump"
    with pytest.raises(AppError):
        postgres_adapter.write_postgres_archive(
            database_url=_DATABASE_URL,
            passfile=tmp_path / "missing.pgpass",
            pg_dump_binary=tmp_path / "missing-pg-dump",
            pg_restore_binary=tmp_path / "missing-pg-restore",
            target=target,
            synchronized_snapshot="00000003-0000001B-1",
        )
    assert not target.exists()


def test_archive_preserves_primary_and_partial_cleanup_baseexceptions(tmp_path, monkeypatch) -> None:
    target = tmp_path / "database.dump"
    passfile = _passfile(tmp_path)
    dump_binary = _tool(tmp_path, "pg_dump.exe")
    restore_binary = _tool(tmp_path, "pg_restore.exe")
    primary = KeyboardInterrupt("pg_dump interrupted")
    cleanup = SystemExit("partial cleanup interrupted")
    original_unlink = Path.unlink

    def interrupting_run(arguments, **_kwargs):
        partial = Path(arguments[arguments.index("--file") + 1])
        partial.write_bytes(b"partial")
        raise primary

    def interrupting_unlink(path: Path, *args, **kwargs):
        if path.name == ".database.dump.partial":
            raise cleanup
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(postgres_adapter.subprocess, "run", interrupting_run)
    monkeypatch.setattr(Path, "unlink", interrupting_unlink)

    with pytest.raises(BaseExceptionGroup) as caught:
        postgres_adapter.write_postgres_archive(
            database_url=_DATABASE_URL,
            passfile=passfile,
            pg_dump_binary=dump_binary,
            pg_restore_binary=restore_binary,
            target=target,
            synchronized_snapshot="00000003-0000001B-1",
        )
    assert caught.value.exceptions == (primary, cleanup)


def test_find_pg_binary_windows_install_glob_fallback(tmp_path, monkeypatch) -> None:
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


def test_postgres_backup_validation_rejects_missing_or_invalid_file(tmp_path) -> None:
    missing = tmp_path / "ticketbox-nope.dump"
    assert pgval.is_postgres_backup_valid(missing) is False
    with pytest.raises(pgval.PostgresBackupValidationError, match="does not exist"):
        pgval.validate_postgres_backup_file(missing)

    bogus = tmp_path / "ticketbox-bogus.dump"
    bogus.write_text("this is not a pg_dump archive")
    assert pgval.is_postgres_backup_valid(bogus) is False


@pytest.mark.skipif(
    pgval.find_pg_binary("pg_restore", "PG_RESTORE_PATH") is None,
    reason="pg_restore not found anywhere",
)
def test_postgres_backup_validation_reports_pg_restore_failure(tmp_path) -> None:
    bogus = tmp_path / "ticketbox-bogus.dump"
    bogus.write_text("not an archive")
    with pytest.raises(pgval.PostgresBackupValidationError, match="--list failed"):
        pgval.validate_postgres_backup_file(bogus)
