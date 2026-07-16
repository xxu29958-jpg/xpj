"""Destructive PostgreSQL test-target and test-lane lock contracts."""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
from sqlalchemy.engine import URL

from scripts.test_pg_client_contract import (
    assert_python_libpq_supports_required_auth,
)
from scripts.test_pg_protected_file import (
    assert_protected_authority_file,
    write_protected_utf8_file,
)
from scripts.test_pg_url_contract import (
    _LIBPQ_CONNECTION_ENVIRONMENT,
    EPHEMERAL_SERVICE_AUTHORITY,
    OWNED_MARKER_AUTHORITY,
    TEST_CLUSTER_AUTHORITY_ENV,
    TEST_CLUSTER_MARKER_PATH_ENV,
    TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV,
    TEST_POSTGRES_CREDENTIAL_FILE_ENV,
    _dialect_connection_args,
    _validate_test_consumer_database_url,
    configured_test_database_url,
    managed_test_database_url,
    sanitized_libpq_test_environment,
    scrub_libpq_test_environment,
    validate_backup_drill_database_urls,
    validate_managed_test_database_url,
    validate_test_base_database_name,
    validate_test_base_database_url,
    validate_test_database_name,
    validate_test_database_url,
)
from scripts.test_pg_windows_contract import (
    _abort_disposable_test_process,
    _assert_no_reparse_ancestors,
    _database_port,
    _windows_temp_directory,
    start_windows_parent_watchdog,
    test_postgres_consumer_lease,
)

__all__ = (
    "EPHEMERAL_SERVICE_AUTHORITY",
    "OWNED_MARKER_AUTHORITY",
    "TEST_CLUSTER_AUTHORITY_ENV",
    "TEST_CLUSTER_MARKER_PATH_ENV",
    "TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV",
    "TEST_POSTGRES_CREDENTIAL_FILE_ENV",
    "_windows_temp_directory",
    "admin_connection_args",
    "assert_managed_test_cluster_authority",
    "assert_test_cluster_authority",
    "authority_connection_watchdog",
    "configured_test_database_url",
    "managed_test_database_url",
    "sanitized_libpq_test_environment",
    "scrub_libpq_test_environment",
    "start_windows_parent_watchdog",
    "test_cluster_lock",
    "test_postgres_consumer_lease",
    "test_postgres_credential_environment",
    "validate_backup_drill_database_urls",
    "validate_managed_test_database_url",
    "validate_test_base_database_name",
    "validate_test_base_database_url",
    "validate_test_database_name",
    "validate_test_database_url",
)

_STATEFUL_LOCK_KEY = int.from_bytes(
    sha256(b"ticketbox:postgres-stateful-test-lane:v1").digest()[:8],
    byteorder="big",
    signed=True,
)
_STATEFUL_LOCK_TIMEOUT_MS = 15 * 60 * 1000
_AUTHORITY_HEARTBEAT_SECONDS = 1.0
_AUTHORITY_WATCHDOG_JOIN_SECONDS = 5.0
_OWNERSHIP_MARKER_NAME = ".xpj-test-cluster.json"
_OWNERSHIP_MARKER_KIND = "xiaopiaojia-test-postgres"
_CREDENTIAL_FILE_NAME = ".xpj-test-postgres-password"
_PGPASS_FILE_PREFIX = ".xpj-pgpass-"
_REQUIRED_AUTHENTICATION = "scram-sha-256"
_OWNED_CREDENTIAL = re.compile(r"[A-Za-z0-9_-]{43}")
_SYSTEM_IDENTIFIER = re.compile(r"\d{10,20}")


def _pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _assert_regular_authority_file(path: Path, *, label: str) -> Path:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RuntimeError(f"{label} is missing or not a regular absolute file: {path}")
    _assert_no_reparse_ancestors(path)
    return assert_protected_authority_file(path, label=label)


def _read_test_postgres_credential(path: Path, *, owned: bool) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Test PostgreSQL credential authority is unreadable: {path}") from exc
    if len(lines) != 1:
        raise RuntimeError("Test PostgreSQL credential authority must contain exactly one line")
    credential = lines[0]
    if (
        not 16 <= len(credential) <= 256
        or any(ord(character) < 33 or ord(character) > 126 for character in credential)
        or (owned and _OWNED_CREDENTIAL.fullmatch(credential) is None)
    ):
        raise RuntimeError("Test PostgreSQL credential authority has an invalid contract")
    return credential


def _test_postgres_credential_path(
    database_url: URL,
    environment: Mapping[str, str],
) -> tuple[Path, bool]:
    authority = environment.get(TEST_CLUSTER_AUTHORITY_ENV, "").strip()
    if not authority and not environment.get("XPJ_TEST_DATABASE_URL", "").strip():
        authority = OWNED_MARKER_AUTHORITY
    configured = environment.get(TEST_POSTGRES_CREDENTIAL_FILE_ENV, "").strip()
    if authority == OWNED_MARKER_AUTHORITY:
        data_directory, _ = _read_owned_cluster_marker(database_url, environment)
        expected = (data_directory / _CREDENTIAL_FILE_NAME).resolve()
        if configured and Path(configured).resolve() != expected:
            raise RuntimeError("Owned test PostgreSQL credential path does not match its marker")
        path = expected
        owned = True
    elif authority == EPHEMERAL_SERVICE_AUTHORITY:
        if str(environment.get("CI", "")).lower() != "true":
            raise RuntimeError("Ephemeral test PostgreSQL credentials are valid only inside CI")
        if not configured:
            raise RuntimeError("Ephemeral test PostgreSQL credential authority is missing")
        path = Path(configured)
        owned = False
    else:
        raise RuntimeError("Test PostgreSQL credential authority is missing or unsupported")
    return _assert_regular_authority_file(
        path,
        label="Test PostgreSQL credential authority",
    ), owned


def _expected_pgpass_content(
    database_url: URL,
    environment: Mapping[str, str],
) -> tuple[Path, str]:
    credential_path, owned = _test_postgres_credential_path(
        database_url,
        environment,
    )
    credential = _read_test_postgres_credential(credential_path, owned=owned)
    host = database_url.host or "localhost"
    port = database_url.port or 5432
    username = database_url.username or ""
    content = (
        f"{_pgpass_escape(host)}:{port}:*:{_pgpass_escape(username)}:"
        f"{_pgpass_escape(credential)}\n"
    )
    return credential_path, content


def _active_test_pgpassfile(
    database_url: URL,
    environment: Mapping[str, str],
) -> Path:
    configured = environment.get("PGPASSFILE", "").strip()
    if not configured:
        raise RuntimeError("Test PostgreSQL consumer is missing its derived passfile")
    if environment.get("PGREQUIREAUTH", "").strip() != _REQUIRED_AUTHENTICATION:
        raise RuntimeError("Test PostgreSQL consumer must require SCRAM authentication")
    passfile = _assert_regular_authority_file(
        Path(configured),
        label="Derived test PostgreSQL passfile",
    )
    credential_path, expected_content = _expected_pgpass_content(
        database_url,
        environment,
    )
    if passfile.parent != credential_path.parent or not passfile.name.startswith(
        _PGPASS_FILE_PREFIX
    ):
        raise RuntimeError("Derived test PostgreSQL passfile is outside its credential authority")
    try:
        actual_content = passfile.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("Derived test PostgreSQL passfile is unreadable") from exc
    if actual_content != expected_content:
        raise RuntimeError("Derived test PostgreSQL passfile does not match its credential authority")
    return passfile


@contextlib.contextmanager
def test_postgres_credential_environment(
    database_url: str | URL,
    environment: MutableMapping[str, str],
) -> Iterator[Path]:
    """Derive one short-lived libpq passfile from the verified credential authority."""

    assert_python_libpq_supports_required_auth()
    parsed = _validate_test_consumer_database_url(database_url)
    credential_path, content = _expected_pgpass_content(parsed, environment)
    previous = {
        key: value
        for key, value in environment.items()
        if key in _LIBPQ_CONNECTION_ENVIRONMENT or key.startswith("PG")
    }
    scrub_libpq_test_environment(environment)
    passfile = credential_path.parent / f"{_PGPASS_FILE_PREFIX}{os.getpid()}-{uuid4().hex}"
    try:
        write_protected_utf8_file(
            passfile,
            content,
            label="Derived test PostgreSQL passfile",
        )
        environment["PGPASSFILE"] = str(passfile)
        environment["PGREQUIREAUTH"] = _REQUIRED_AUTHENTICATION
        _active_test_pgpassfile(parsed, environment)
        yield passfile
    finally:
        scrub_libpq_test_environment(environment)
        environment.update(previous)
        passfile.unlink(missing_ok=True)


def _owned_marker_path(
    database_url: URL,
    environment: Mapping[str, str],
) -> Path:
    configured = environment.get(TEST_CLUSTER_MARKER_PATH_ENV, "").strip()
    if configured:
        marker_path = Path(configured)
    else:
        if os.name != "nt" or environment.get("XPJ_TEST_DATABASE_URL", "").strip():
            raise RuntimeError("Owned test-cluster authority requires its marker path")
        marker_path = (
            _windows_temp_directory()
            / f"xpj_pg_test{_database_port(database_url)}"
            / _OWNERSHIP_MARKER_NAME
        )
    return _assert_regular_authority_file(
        marker_path,
        label="Owned test-cluster marker",
    )


def _read_owned_cluster_marker(
    database_url: URL,
    environment: Mapping[str, str],
) -> tuple[Path, str]:
    marker_path = _owned_marker_path(database_url, environment)
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Owned test-cluster marker is unreadable: {marker_path}") from exc
    marker_port = payload.get("port")
    schema_version = payload.get("schema_version")
    system_identifier = str(payload.get("system_identifier", ""))
    if (
        schema_version != 3
        or payload.get("kind") != _OWNERSHIP_MARKER_KIND
        or payload.get("purpose") not in {"local", "ci"}
        or not isinstance(marker_port, int)
        or marker_port != _database_port(database_url)
        or _SYSTEM_IDENTIFIER.fullmatch(system_identifier) is None
        or payload.get("authentication") != "scram-sha-256"
    ):
        raise RuntimeError(f"Owned test-cluster marker is invalid: {marker_path}")
    return marker_path.parent, system_identifier


def _assert_parsed_test_cluster_authority(
    parsed: URL,
    environment: Mapping[str, str],
) -> None:
    authority = environment.get(TEST_CLUSTER_AUTHORITY_ENV, "").strip()
    expected_data_directory: Path | None = None
    if not authority and not environment.get("XPJ_TEST_DATABASE_URL", "").strip():
        authority = OWNED_MARKER_AUTHORITY
    if authority == OWNED_MARKER_AUTHORITY:
        expected_data_directory, expected_system_identifier = _read_owned_cluster_marker(
            parsed,
            environment,
        )
    elif authority == EPHEMERAL_SERVICE_AUTHORITY:
        if str(environment.get("CI", "")).lower() != "true":
            raise RuntimeError("Ephemeral test-cluster authority is valid only inside CI")
        expected_system_identifier = environment.get(
            TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV,
            "",
        ).strip()
        if _SYSTEM_IDENTIFIER.fullmatch(expected_system_identifier) is None:
            raise RuntimeError("Ephemeral test-cluster authority is missing its system identifier")
    else:
        raise RuntimeError("Test PostgreSQL cluster authority is missing or unsupported")

    with psycopg.connect(
        autocommit=True,
        **admin_connection_args(parsed, environment),
    ) as connection:
        row = connection.execute(
            """
            SELECT
                (SELECT system_identifier::text FROM pg_control_system()),
                current_setting('data_directory'),
                current_setting('port'),
                current_setting('listen_addresses')
            """,
            (),
        ).fetchone()
    if row is None or len(row) != 4:
        raise RuntimeError("Test PostgreSQL cluster did not return an identity record")
    actual_identifier, actual_data_directory, actual_port, listen_addresses = (
        str(value) for value in row
    )
    if actual_identifier != expected_system_identifier:
        raise RuntimeError("Test PostgreSQL system identifier does not match its authority")
    if int(actual_port) != _database_port(parsed):
        raise RuntimeError("Test PostgreSQL runtime port does not match its authority")
    if authority == OWNED_MARKER_AUTHORITY:
        assert expected_data_directory is not None
        if Path(actual_data_directory).resolve() != expected_data_directory:
            raise RuntimeError("Test PostgreSQL data directory does not match its authority")
        if listen_addresses != "127.0.0.1":
            raise RuntimeError("Owned test PostgreSQL must listen only on 127.0.0.1")


def assert_test_cluster_authority(
    database_url: str | URL,
    environment: Mapping[str, str],
) -> None:
    """Prove the live server is the exact disposable cluster authorized for tests."""

    _assert_parsed_test_cluster_authority(
        validate_test_base_database_url(database_url),
        environment,
    )


def assert_managed_test_cluster_authority(
    database_url: str | URL,
    environment: Mapping[str, str],
    *,
    expected_database: str,
) -> None:
    """Apply the same live authority proof to smoke and restore databases."""

    _assert_parsed_test_cluster_authority(
        validate_managed_test_database_url(
            database_url,
            expected_database=expected_database,
        ),
        environment,
    )


@contextlib.contextmanager
def authority_connection_watchdog(
    connection: psycopg.Connection,
    *,
    label: str,
    heartbeat_seconds: float = _AUTHORITY_HEARTBEAT_SECONDS,
    abort_process: Callable[[str], None] = _abort_disposable_test_process,
) -> Iterator[None]:
    """Abort a disposable pytest process if its authority session disappears."""

    stop = threading.Event()
    failures: list[BaseException] = []

    def monitor() -> None:
        while not stop.wait(heartbeat_seconds):
            try:
                connection.execute("SELECT 1", ()).fetchone()
            except psycopg.Error as exc:
                if stop.is_set():
                    return
                failures.append(exc)
                stop.set()
                abort_process(f"Lost PostgreSQL {label}; aborting this test process.")
                return

    thread = threading.Thread(
        target=monitor,
        name=f"postgres-{label}-watchdog",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=_AUTHORITY_WATCHDOG_JOIN_SECONDS)
        if thread.is_alive():
            message = f"PostgreSQL {label} watchdog did not stop; aborting this test process."
            abort_process(message)
            raise RuntimeError(message)
        if failures:
            raise RuntimeError(f"Lost PostgreSQL {label}") from failures[0]


@contextlib.contextmanager
def test_cluster_lock(
    environment: Mapping[str, str],
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Coordinate isolated workers and destructive sessions on one PG cluster."""

    parsed = validate_test_base_database_url(configured_test_database_url(environment))
    assert_test_cluster_authority(parsed, environment)
    lock_statement = "SELECT pg_advisory_lock(%s)" if exclusive else "SELECT pg_advisory_lock_shared(%s)"
    unlock_statement = "SELECT pg_advisory_unlock(%s)" if exclusive else "SELECT pg_advisory_unlock_shared(%s)"
    with psycopg.connect(
        autocommit=True,
        **admin_connection_args(parsed, environment),
    ) as connection:
        connection.execute(
            "SELECT set_config('idle_session_timeout', %s, false)",
            ("0",),
        )
        connection.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(_STATEFUL_LOCK_TIMEOUT_MS),),
        )
        connection.execute(lock_statement, (_STATEFUL_LOCK_KEY,))
        try:
            mode = "exclusive" if exclusive else "shared"
            with authority_connection_watchdog(
                connection,
                label=f"test-lane {mode} lock",
            ):
                yield
        finally:
            released = connection.execute(
                unlock_statement,
                (_STATEFUL_LOCK_KEY,),
            ).fetchone()
            if released != (True,):
                raise RuntimeError(f"PostgreSQL test-lane {mode} lock was not owned")


def admin_connection_args(
    database_url: URL,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Resolve the exact engine target and replace only its database name."""

    parsed = _validate_test_consumer_database_url(database_url)
    arguments = _dialect_connection_args(parsed)
    arguments["dbname"] = "postgres"
    arguments["passfile"] = str(
        _active_test_pgpassfile(
            parsed,
            os.environ if environment is None else environment,
        )
    )
    arguments["require_auth"] = _REQUIRED_AUTHENTICATION
    return arguments
