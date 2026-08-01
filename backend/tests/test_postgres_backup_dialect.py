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
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.postgres_backup_validation_service as pgval
import app.services.secure_file as secure_file
from app.errors import AppError
from app.services import backup_service
from scripts import postgres_backup_drill

_ENCODED_PASSWORD = "p%40ss%3Aword%2F%3F%23%25"
_DECODED_PASSWORD = "p@ss:word/?#%"
_DATABASE_URL = (
    f"postgresql+psycopg://ticketbox:{_ENCODED_PASSWORD}@localhost:5432/ticketbox"
    "?require_auth=scram-sha-256&sslmode=require"
)


def _configure_pg_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: object,
) -> None:
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    monkeypatch.setattr(
        backup_service,
        "get_settings",
        lambda: SimpleNamespace(database_url=_DATABASE_URL),
    )
    monkeypatch.setattr(backup_service, "_pg_dump_binary", lambda: "pg_dump-probe")
    monkeypatch.setattr(backup_service, "is_postgres_backup_valid", lambda _path: True)
    monkeypatch.setattr(backup_service.subprocess, "run", runner)


def test_pg_restore_uses_an_ephemeral_passfile_and_bounds_failures(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_restore(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        passfile = Path(environment["PGPASSFILE"])
        observed["arguments"] = arguments
        observed["environment"] = environment
        observed["passfile"] = passfile
        observed["passfile_text"] = passfile.read_text(encoding="utf-8")
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["timeout"] == postgres_backup_drill._PG_RESTORE_TIMEOUT_SECONDS  # noqa: SLF001
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(pgval, "find_pg_binary", lambda *_args: "pg_restore-probe")
    monkeypatch.setattr(postgres_backup_drill.subprocess, "run", fake_restore)
    postgres_backup_drill._pg_restore(tmp_path / "archive.dump", _DATABASE_URL)  # noqa: SLF001
    arguments = observed["arguments"]
    environment = observed["environment"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert _DECODED_PASSWORD not in arguments
    assert _ENCODED_PASSWORD not in " ".join(arguments)
    assert "--no-password" in arguments
    assert "PGPASSWORD" not in environment
    assert observed["passfile_text"] == "localhost:5432:ticketbox:ticketbox:p@ss\\:word/?#%\n"
    assert not Path(observed["passfile"]).exists()

    monkeypatch.setattr(
        postgres_backup_drill.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(
            arguments,
            1,
            stdout=_DATABASE_URL,
            stderr=f"connection failed for password={_DECODED_PASSWORD}",
        ),
    )
    with pytest.raises(SystemExit) as restore_error:
        postgres_backup_drill._pg_restore(tmp_path / "archive.dump", _DATABASE_URL)  # noqa: SLF001
    assert _DECODED_PASSWORD not in str(restore_error.value)
    assert _ENCODED_PASSWORD not in str(restore_error.value)

    def timeout_restore(arguments, **kwargs):
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr(postgres_backup_drill.subprocess, "run", timeout_restore)
    with pytest.raises(SystemExit, match="could not complete"):
        postgres_backup_drill._pg_restore(tmp_path / "archive.dump", _DATABASE_URL)  # noqa: SLF001


def test_pg_tool_connection_removes_credentials_from_arguments() -> None:
    assert backup_service.write_protected_file_exclusive is secure_file.write_protected_file_exclusive
    connection = backup_service._pg_tool_connection(_DATABASE_URL)  # noqa: SLF001
    assert connection.database_url == (
        "postgresql://ticketbox@localhost:5432/ticketbox?connect_timeout=5&"
        "require_auth=scram-sha-256&sslmode=require"
    )
    assert connection.password == _DECODED_PASSWORD
    loopback_connection = backup_service._pg_tool_connection(  # noqa: SLF001
        "postgresql://ticketbox@localhost/ticketbox?"
        "hostaddr=127.0.0.1&require_auth=scram-sha-256"
    )
    assert "hostaddr=127.0.0.1" in loopback_connection.database_url
    exact_ip_connection = backup_service._pg_tool_connection(  # noqa: SLF001
        "postgresql://ticketbox@127.0.0.1/ticketbox?"
        "hostaddr=127.0.0.1&require_auth=scram-sha-256"
    )
    assert "hostaddr=127.0.0.1" in exact_ip_connection.database_url
    for unsafe_query in (
        "password=query-secret",
        "passfile=other.pgpass&require_auth=scram-sha-256",
        "service=production&require_auth=scram-sha-256",
        "hostaddr=203.0.113.7&require_auth=scram-sha-256",
        "hostaddr=127.0.0.2&require_auth=scram-sha-256",
        "connect_timeout=0&require_auth=scram-sha-256",
    ):
        with pytest.raises(AppError) as query_error:
            backup_service._pg_tool_connection(  # noqa: SLF001
                f"postgresql://ticketbox@localhost/ticketbox?{unsafe_query}"
            )
        assert "query-secret" not in str(query_error.value)
    with pytest.raises(AppError):
        backup_service._pg_tool_connection(  # noqa: SLF001
            "postgresql://ticketbox@db.example/ticketbox?"
            "hostaddr=203.0.113.7&require_auth=scram-sha-256"
        )


def test_pg_dump_uses_noninteractive_ephemeral_passfile(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        environment = kwargs["env"]
        passfile = Path(environment["PGPASSFILE"])
        observed["arguments"] = arguments
        observed["environment"] = environment
        observed["passfile"] = passfile
        observed["passfile_text"] = passfile.read_text(encoding="utf-8")
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["timeout"] == backup_service._PG_DUMP_TIMEOUT_SECONDS  # noqa: SLF001
        Path(arguments[arguments.index("--file") + 1]).write_bytes(b"probe")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    _configure_pg_dump(tmp_path, monkeypatch, fake_run)
    poisoned = {
        "DATABASE_URL": "postgresql://ambient-secret@production.example/finance",
        "PGHOST": "production.example",
        "PGHOSTADDR": "203.0.113.7",
        "PGPASSWORD": "parent-password",
        "PGPORT": "6543",
        "PGSERVICE": "production",
    }
    for key, value in poisoned.items():
        monkeypatch.setenv(key, value)

    backup_service._run_pg_dump(prefix="ticketbox-manual", kind="manual")  # noqa: SLF001
    arguments = observed["arguments"]
    environment = observed["environment"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert _DECODED_PASSWORD not in arguments
    assert _ENCODED_PASSWORD not in " ".join(arguments)
    assert "--no-password" in arguments
    assert "--lock-wait-timeout=30000" in arguments
    assert not set(poisoned) & set(environment)
    assert observed["passfile_text"] == "localhost:5432:ticketbox:ticketbox:p@ss\\:word/?#%\n"
    assert not Path(observed["passfile"]).exists()
    assert all(os.environ[key] == value for key, value in poisoned.items())


def test_c07_pg_dump_is_bound_to_the_exported_snapshot(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(arguments, **_kwargs):
        observed["arguments"] = arguments
        Path(arguments[arguments.index("--file") + 1]).write_bytes(b"c07-probe")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    _configure_pg_dump(tmp_path, monkeypatch, fake_run)
    snapshot = "00000003-0000001B-1"
    entry = backup_service.create_c07_pre_upgrade_backup(
        database_url=_DATABASE_URL,
        exported_snapshot=snapshot,
    )

    arguments = observed["arguments"]
    assert isinstance(arguments, list)
    assert f"--snapshot={snapshot}" in arguments
    assert arguments[arguments.index("--dbname") + 1].startswith(
        "postgresql://ticketbox@localhost:5432/ticketbox"
    )
    assert _DECODED_PASSWORD not in " ".join(arguments)
    assert entry.kind == "pre-upgrade"
    assert backup_service._classify(entry.file_name) == "pre-upgrade"  # noqa: SLF001


@pytest.mark.parametrize(
    "snapshot",
    [
        "",
        "../snapshot",
        "00000003-0000001b-1",
        "00000003-0000001B-0",
        "00000003-0000001B-12345678901",
        "snapshot;--file=elsewhere",
        "00000003-0000001B-1\n--file=elsewhere",
        "x" * 129,
    ],
)
def test_c07_pg_dump_rejects_a_non_postgresql_17_snapshot_id(
    snapshot,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        backup_service.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("pg_dump must not run"),
    )
    with pytest.raises(AppError, match="快照标识无效"):
        backup_service.create_c07_pre_upgrade_backup(
            database_url=_DATABASE_URL,
            exported_snapshot=snapshot,
        )


def test_passwordless_pg_tools_require_a_valid_inherited_passfile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PGPASSWORD", "parent-password")
    passwordless = backup_service._pg_tool_connection(  # noqa: SLF001
        "postgresql://ticketbox@localhost/ticketbox?require_auth=scram-sha-256"
    )
    inherited_passfile = tmp_path / "inherited.pgpass"
    inherited_passfile.write_text(
        "localhost:5432:ticketbox:ticketbox:inherited-secret\n",
        encoding="utf-8",
    )
    inherited_passfile.chmod(0o600)
    monkeypatch.setenv("PGPASSFILE", str(inherited_passfile.resolve()))
    if os.name == "nt":
        with (
            pytest.raises(AppError, match="凭据不可用"),
            backup_service._pg_tool_environment(passwordless),  # noqa: SLF001
        ):
            pass
        inherited_passfile.unlink()
        secure_file.write_protected_file_exclusive(
            inherited_passfile,
            "localhost:5432:ticketbox:ticketbox:protected-secret\n",
        )
    with backup_service._pg_tool_environment(passwordless) as passwordless_environment:  # noqa: SLF001
        assert "PGPASSWORD" not in passwordless_environment
        assert passwordless_environment["PGPASSFILE"] == str(inherited_passfile.resolve())
    assert inherited_passfile.exists()
    assert os.environ["PGPASSFILE"] == str(inherited_passfile.resolve())
    if os.name != "nt":
        effective_uid = os.geteuid()
        foreign_directory = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o755,
            st_uid=effective_uid + 1,
        )
        with pytest.raises(PermissionError, match="untrusted owner"):
            secure_file._validate_unix_directory_entry(  # noqa: SLF001
                foreign_directory,
                child_owner=effective_uid,
            )
        foreign_directory.st_mode = stat.S_IFDIR | stat.S_ISVTX | 0o777
        with pytest.raises(PermissionError, match="untrusted owner"):
            secure_file._validate_unix_directory_entry(  # noqa: SLF001
                foreign_directory,
                child_owner=effective_uid,
            )
        unsafe_directory = tmp_path / "other-user-mutable"
        unsafe_directory.mkdir()
        unsafe_directory.chmod(0o777)
        unsafe_passfile = unsafe_directory / "inherited.pgpass"
        unsafe_passfile.write_text("inherited-secret\n", encoding="utf-8")
        unsafe_passfile.chmod(0o600)
        monkeypatch.setenv("PGPASSFILE", str(unsafe_passfile.resolve()))
        with (
            pytest.raises(AppError, match="凭据不可用"),
            backup_service._pg_tool_environment(passwordless),  # noqa: SLF001
        ):
            pass
    monkeypatch.delenv("PGPASSFILE")
    with (
        pytest.raises(AppError, match="凭据不可用"),
        backup_service._pg_tool_environment(passwordless),  # noqa: SLF001
    ):
        pass
    assert os.environ["PGPASSWORD"] == "parent-password"


def test_pg_dump_failures_are_bounded_sanitized_and_cleaned(tmp_path, monkeypatch, caplog) -> None:
    def failed_run(arguments, **_kwargs):
        return subprocess.CompletedProcess(
            arguments,
            1,
            stdout=_DATABASE_URL,
            stderr=f"connection failed for password={_DECODED_PASSWORD}",
        )

    _configure_pg_dump(tmp_path, monkeypatch, failed_run)
    monkeypatch.setenv("PGPASSWORD", "parent-password")
    with caplog.at_level(logging.WARNING), pytest.raises(AppError):
        backup_service._run_pg_dump(prefix="ticketbox-manual", kind="manual")  # noqa: SLF001
    assert _DECODED_PASSWORD not in caplog.text
    assert _ENCODED_PASSWORD not in caplog.text
    assert _DATABASE_URL not in caplog.text
    assert os.environ["PGPASSWORD"] == "parent-password"

    def timeout_dump(arguments, **kwargs):
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr(backup_service.subprocess, "run", timeout_dump)
    with pytest.raises(AppError, match="安全时限"):
        backup_service._run_pg_dump(prefix="ticketbox-manual", kind="manual")  # noqa: SLF001
    assert not list(tmp_path.glob(".ticketbox-*.tmp-*"))
    assert not list(tmp_path.glob(".pgpass-*"))


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
