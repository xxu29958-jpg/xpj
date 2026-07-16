"""PostgreSQL test URL and ambient libpq environment contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping

from sqlalchemy.engine import URL, make_url

_SAFE_TEST_DATABASE = re.compile(r"xpj_test(?:_[a-z0-9]+)*")
_WORKER_TEST_DATABASE = re.compile(r"xpj_test(?:_[a-z0-9]+)*_[0-9a-f]{16}_gw[0-9]+")
_DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5438/xpj_test"
TEST_CLUSTER_AUTHORITY_ENV = "XPJ_TEST_CLUSTER_AUTHORITY"
TEST_CLUSTER_MARKER_PATH_ENV = "XPJ_TEST_CLUSTER_MARKER_PATH"
TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV = "XPJ_TEST_CLUSTER_SYSTEM_IDENTIFIER"
TEST_POSTGRES_CREDENTIAL_FILE_ENV = "XPJ_TEST_POSTGRES_CREDENTIAL_FILE"
OWNED_MARKER_AUTHORITY = "owned-marker"
EPHEMERAL_SERVICE_AUTHORITY = "ephemeral-service"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MANAGED_DATABASES = frozenset({"xpj_smoke", "xpj_restore"})
_LIBPQ_CONNECTION_ENVIRONMENT = frozenset(
    {
        "PGAPPNAME",
        "PGCHANNELBINDING",
        "PGCLIENTENCODING",
        "PGCONNECT_TIMEOUT",
        "PGDATABASE",
        "PGGSSENCMODE",
        "PGHOST",
        "PGHOSTADDR",
        "PGLOADBALANCEHOSTS",
        "PGOPTIONS",
        "PGPASSFILE",
        "PGPASSWORD",
        "PGPORT",
        "PGREQUIREAUTH",
        "PGREQUIREPEER",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGSSLCERT",
        "PGSSLCRL",
        "PGSSLCRLDIR",
        "PGSSLKEY",
        "PGSSLMODE",
        "PGSSLNEGOTIATION",
        "PGSSLROOTCERT",
        "PGSSLSNI",
        "PGTARGETSESSIONATTRS",
        "PGUSER",
    }
)


def configured_test_database_url(environment: Mapping[str, str]) -> str:
    """Resolve and validate the base test URL and any explicit override."""

    explicit = environment.get("XPJ_TEST_DATABASE_URL", "").strip()
    if not explicit:
        database_url = _DEFAULT_TEST_DATABASE_URL
    else:
        authority = environment.get(TEST_CLUSTER_AUTHORITY_ENV, "").strip()
        if authority not in {OWNED_MARKER_AUTHORITY, EPHEMERAL_SERVICE_AUTHORITY}:
            raise RuntimeError(
                "XPJ_TEST_DATABASE_URL overrides require an explicit test-cluster authority"
            )
        database_url = explicit
    validate_test_base_database_url(database_url)
    return database_url


def validate_test_database_name(database_name: str) -> str:
    """Require the complete destructive-test database naming contract."""

    if _SAFE_TEST_DATABASE.fullmatch(database_name) is None:
        raise ValueError("Test database must match the xpj_test base contract")
    return database_name


def validate_test_base_database_name(database_name: str) -> str:
    """Reserve worker-shaped names for process-owned disposable databases."""

    validate_test_database_name(database_name)
    if _WORKER_TEST_DATABASE.fullmatch(database_name) is not None:
        raise ValueError("Test base database uses the reserved worker namespace")
    return database_name


def validate_test_database_url(database_url: str | URL) -> URL:
    """Parse and validate one PostgreSQL test database URL."""

    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Test database URL must use PostgreSQL")
    if parsed.password is not None:
        raise ValueError("Test database URL must not contain a password")
    if parsed.query:
        raise ValueError("Test database URL must not use libpq query parameters")
    if parsed.username != "postgres":
        raise ValueError("Test database URL must use the managed postgres role")
    path_database = validate_test_database_name(parsed.database or "")
    connection_args = _dialect_connection_args(parsed)
    resolved_database = connection_args.get("dbname")
    if resolved_database != path_database:
        raise ValueError("Test database URL must not override its xpj_test path database")
    if str(connection_args.get("host", "")).lower() not in _LOOPBACK_HOSTS:
        raise ValueError("Test database URL must resolve to a loopback PostgreSQL host")
    return parsed


def validate_managed_test_database_url(
    database_url: str | URL,
    *,
    expected_database: str,
) -> URL:
    """Validate one fixed smoke or restore database on the test authority."""

    if expected_database not in _MANAGED_DATABASES:
        raise ValueError("Managed test database name is not supported")
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Managed test database URL must use PostgreSQL")
    if parsed.password is not None:
        raise ValueError("Managed test database URL must not contain a password")
    if parsed.query:
        raise ValueError("Managed test database URL must not use libpq query parameters")
    if parsed.username != "postgres":
        raise ValueError("Managed test database URL must use the managed postgres role")
    if parsed.database != expected_database:
        raise ValueError(f"Managed test database URL must target {expected_database}")
    connection_args = _dialect_connection_args(parsed)
    if connection_args.get("dbname") != expected_database:
        raise ValueError("Managed test database URL must not override its path database")
    if str(connection_args.get("host", "")).lower() not in _LOOPBACK_HOSTS:
        raise ValueError("Managed test database URL must resolve to a loopback PostgreSQL host")
    return parsed


def managed_test_database_url(
    base_database_url: str | URL,
    database_name: str,
) -> str:
    """Derive a managed database URL without reinterpreting its connection target."""

    parsed = validate_test_base_database_url(base_database_url)
    if database_name not in _MANAGED_DATABASES:
        raise ValueError("Managed test database name is not supported")
    return parsed.set(database=database_name).render_as_string(hide_password=True)


def validate_backup_drill_database_urls(
    source_url: str | URL,
    restore_url: str | URL,
) -> tuple[URL, URL]:
    """Require one authorized endpoint with distinct source and restore databases."""

    source = validate_managed_test_database_url(
        source_url,
        expected_database="xpj_smoke",
    )
    restore = validate_managed_test_database_url(
        restore_url,
        expected_database="xpj_restore",
    )
    source_target = _dialect_connection_args(source)
    restore_target = _dialect_connection_args(restore)
    source_target.pop("dbname", None)
    restore_target.pop("dbname", None)
    if source_target != restore_target:
        raise ValueError("Backup drill source and restore URLs must share one PostgreSQL endpoint")
    return source, restore


def validate_test_base_database_url(database_url: str | URL) -> URL:
    """Validate a configured base URL, excluding disposable worker names."""

    parsed = validate_test_database_url(database_url)
    validate_test_base_database_name(parsed.database or "")
    return parsed


def _validate_test_consumer_database_url(database_url: str | URL) -> URL:
    parsed = make_url(database_url)
    if parsed.database in _MANAGED_DATABASES:
        return validate_managed_test_database_url(
            parsed,
            expected_database=parsed.database,
        )
    return validate_test_database_url(parsed)


def scrub_libpq_test_environment(environment: MutableMapping[str, str]) -> None:
    """Remove ambient libpq inputs so the validated URL is the only target source."""

    for key in tuple(environment):
        if key in _LIBPQ_CONNECTION_ENVIRONMENT or key.startswith("PG"):
            environment.pop(key, None)


def sanitized_libpq_test_environment(
    environment: Mapping[str, str],
) -> dict[str, str]:
    sanitized = dict(environment)
    scrub_libpq_test_environment(sanitized)
    return sanitized


def _dialect_connection_args(database_url: URL) -> dict[str, object]:
    positional, keyword = database_url.get_dialect()().create_connect_args(database_url)
    if positional:
        raise ValueError("PostgreSQL test URLs must resolve without positional args")
    return dict(keyword)
