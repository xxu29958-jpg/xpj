"""PostgreSQL ownership for pytest-xdist workers and serial test sessions."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT

_BASE_DATABASE = TEST_POSTGRES_CONTRACT.base_database
_WORKER_ID = re.compile(r"gw\d+")
_WORKER_DATABASE_NAME = re.compile(
    rf"{re.escape(_BASE_DATABASE)}_(?P<run_hash>[0-9a-f]{{10}})_(?P<worker_id>gw\d+)"
)
_WORKER_COMMENT = re.compile(
    rf"{re.escape(TEST_POSTGRES_CONTRACT.worker_marker_prefix)}"
    r"(?P<run_digest>[0-9a-f]{64}):(?P<worker_id>gw\d+)"
)
_SERIAL_LOCK_ID = 0x58504A5F54455354
_TEST_CLUSTER_COMMENT = TEST_POSTGRES_CONTRACT.require_database_identity(
    os.environ.get("XPJ_TEST_CLUSTER_IDENTITY")
)
_WORKER_COMMENT_PREFIX = TEST_POSTGRES_CONTRACT.worker_marker_prefix
_SEALED_QUERY_VALUES = {
    "connect_timeout": "5",
    "options": "-csearch_path=public,pg_catalog",
    "sslmode": "disable",
}
_ALLOWED_AUTH_METHODS = {"none", "scram-sha-256"}


@dataclass(frozen=True)
class WorkerDatabase:
    base_url: str
    admin_url: str
    database_url: str
    name: str
    owner_marker: str
    run_hash: str
    worker_id: str

    @property
    def runtime_id(self) -> str:
        return f"xdist_{self.run_hash}_{self.worker_id}"


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validated_url(
    raw_url: str,
    *,
    expected_database: str,
    expected_user: str,
) -> URL:
    url = make_url(raw_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("pytest worker databases require postgresql+psycopg")
    query = dict(url.query)
    unknown = set(query) - {*_SEALED_QUERY_VALUES, "hostaddr", "require_auth"}
    if unknown:
        raise ValueError("pytest worker database URL contains unsupported query parameters")
    for key, expected in _SEALED_QUERY_VALUES.items():
        if key in query and query[key] != expected:
            raise ValueError(f"pytest worker database URL has an unsafe {key} value")
    if "hostaddr" in query:
        try:
            if not ipaddress.ip_address(query["hostaddr"]).is_loopback:
                raise ValueError("pytest worker database hostaddr must be loopback")
        except ValueError as exc:
            raise ValueError("pytest worker database hostaddr must be loopback") from exc
    if query.get("require_auth") not in _ALLOWED_AUTH_METHODS:
        raise ValueError("pytest worker database requires an explicit authentication contract")
    if url.database != expected_database:
        raise ValueError(f"pytest PostgreSQL database must be {expected_database}")
    if url.username != expected_user:
        raise ValueError(f"pytest PostgreSQL user must be {expected_user}")
    if url.password is not None:
        raise ValueError("pytest worker database credentials must come from a passfile")
    if not _is_loopback(url.host):
        raise ValueError("pytest worker databases require a loopback PostgreSQL host")
    port = url.port
    if port is None:
        raise ValueError("pytest worker database URL requires an explicit port")
    TEST_POSTGRES_CONTRACT.require_allowed_host_port(port)
    return url


def _validated_base_url(raw_url: str) -> URL:
    return _validated_url(
        raw_url,
        expected_database=_BASE_DATABASE,
        expected_user=TEST_POSTGRES_CONTRACT.application_role,
    )


def _validated_admin_url(raw_url: str) -> URL:
    return _validated_url(
        raw_url,
        expected_database="postgres",
        expected_user="postgres",
    )


def _loopback_hostaddr(host: str, port: int) -> str:
    """Resolve once, reject non-loopback answers, and pin libpq to that address."""
    try:
        addresses = {
            ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
            for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        }
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve pytest PostgreSQL loopback host: {host}") from exc
    if not addresses or any(not address.is_loopback for address in addresses):
        raise ValueError("pytest PostgreSQL host did not resolve exclusively to loopback")
    return str(min(addresses, key=lambda address: (address.version != 4, int(address))))


def _sealed_base_url(raw_url: str) -> URL:
    """Return a complete libpq route so PG* environment cannot redirect it."""
    url = _validated_base_url(raw_url)
    port = url.port
    if port is None:  # guarded by _validated_base_url; keeps the type explicit.
        raise ValueError("pytest worker database URL requires an explicit port")
    query = {
        **_SEALED_QUERY_VALUES,
        "hostaddr": _loopback_hostaddr(url.host or "", port),
    }
    query["require_auth"] = url.query["require_auth"]
    return url.set(
        port=port,
        query=query,
    )


def _sealed_admin_url(raw_url: str) -> URL:
    url = _validated_admin_url(raw_url)
    port = url.port
    if port is None:
        raise ValueError("pytest admin database URL requires an explicit port")
    return url.set(
        port=port,
        query={
            **_SEALED_QUERY_VALUES,
            "hostaddr": _loopback_hostaddr(url.host or "", port),
            "require_auth": url.query["require_auth"],
        },
    )


def sealed_test_database_url(raw_url: str) -> str:
    return _sealed_base_url(raw_url).render_as_string(hide_password=False)


def worker_database(
    base_url: str,
    admin_url: str,
    worker_id: str,
    run_uid: str,
) -> WorkerDatabase:
    """Derive one collision-resistant database from an xdist worker identity."""
    url = _sealed_base_url(base_url)
    if _WORKER_ID.fullmatch(worker_id) is None:
        raise ValueError(f"invalid pytest-xdist worker id: {worker_id!r}")
    if not run_uid:
        raise ValueError("pytest-xdist run uid is required")
    run_digest = hashlib.sha256(run_uid.encode("utf-8")).hexdigest()
    run_hash = run_digest[:10]
    name = f"{_BASE_DATABASE}_{run_hash}_{worker_id}"
    database_url = url.set(database=name).render_as_string(hide_password=False)
    owner_marker = f"{_WORKER_COMMENT_PREFIX}{run_digest}:{worker_id}"
    return WorkerDatabase(
        base_url,
        _sealed_admin_url(admin_url).render_as_string(hide_password=False),
        database_url,
        name,
        owner_marker,
        run_hash,
        worker_id,
    )


def worker_database_from_environment(
    base_url: str,
    admin_url: str,
) -> WorkerDatabase | None:
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    run_uid = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if worker_id is None and run_uid is None:
        _sealed_base_url(base_url)
        _sealed_admin_url(admin_url)
        return None
    if worker_id is None or run_uid is None:
        raise ValueError("incomplete pytest-xdist worker identity")
    return worker_database(base_url, admin_url, worker_id, run_uid)


def _maintenance_conninfo(admin_url: str) -> str:
    url = _sealed_admin_url(admin_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _database_comment(conn, database_name: str) -> str | None:
    row = conn.execute(
        """
        SELECT pg_catalog.shobj_description(oid, 'pg_database')
        FROM pg_catalog.pg_database
        WHERE datname = %s
        """,
        (database_name,),
    ).fetchone()
    return None if row is None else row[0]


def _comment_database(conn, database_name: str, comment: str) -> None:
    conn.execute(
        sql.SQL("COMMENT ON DATABASE {} IS {}").format(
            sql.Identifier(database_name),
            sql.Literal(comment),
        )
    )


def mark_existing_test_database(admin_url: str) -> None:
    """Mark a pre-created ephemeral xpj_test database as test-owned."""
    _validated_admin_url(admin_url)
    with psycopg.connect(_maintenance_conninfo(admin_url), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (_BASE_DATABASE,),
        ).fetchone()
        if exists is None:
            raise RuntimeError(f"pre-created test database is missing: {_BASE_DATABASE}")
        if _database_comment(conn, _BASE_DATABASE) is not None:
            raise RuntimeError(f"refusing to adopt a marked test database: {_BASE_DATABASE}")
        _comment_database(conn, _BASE_DATABASE, _TEST_CLUSTER_COMMENT)


def verify_test_cluster_authority(admin_url: str) -> None:
    """Reject destructive test operations unless xpj_test carries our marker."""
    with psycopg.connect(_maintenance_conninfo(admin_url), autocommit=True) as conn:
        if _database_comment(conn, _BASE_DATABASE) != _TEST_CLUSTER_COMMENT:
            raise RuntimeError("PostgreSQL cluster is not marked as an XPJ test cluster")


def _verify_worker_database(conn, database: WorkerDatabase) -> None:
    comment = _database_comment(conn, database.name)
    if comment != database.owner_marker:
        raise RuntimeError(f"pytest does not own worker database: {database.name}")


def verify_worker_database(database: WorkerDatabase) -> None:
    """Prove the controller-created worker DB belongs to this exact run."""
    with psycopg.connect(_maintenance_conninfo(database.admin_url), autocommit=True) as conn:
        _verify_worker_database(conn, database)


def provision_worker_database(database: WorkerDatabase) -> None:
    """Create a worker database, refusing to adopt pre-existing state."""
    with psycopg.connect(_maintenance_conninfo(database.admin_url), autocommit=True) as conn:
        if _database_comment(conn, _BASE_DATABASE) != _TEST_CLUSTER_COMMENT:
            raise RuntimeError("PostgreSQL cluster is not marked as an XPJ test cluster")
        exists = conn.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (database.name,),
        ).fetchone()
        if exists is not None:
            raise RuntimeError(f"pytest worker database already exists: {database.name}")
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database.name),
                sql.Identifier(TEST_POSTGRES_CONTRACT.application_role),
            )
        )
        try:
            _comment_database(conn, database.name, database.owner_marker)
        except (psycopg.Error, KeyboardInterrupt, SystemExit):
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database.name)))
            raise


def drop_worker_database(database: WorkerDatabase) -> bool:
    """Drop only a worker database proven to belong to this exact run."""
    with psycopg.connect(_maintenance_conninfo(database.admin_url), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (database.name,),
        ).fetchone()
        if exists is None:
            return False
        _verify_worker_database(conn, database)
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database.name)))
        return True


def _stale_worker_runtime_id(name: str, comment: object) -> str | None:
    name_match = _WORKER_DATABASE_NAME.fullmatch(name)
    if name_match is None:
        if isinstance(comment, str) and comment.startswith(_WORKER_COMMENT_PREFIX):
            raise RuntimeError(f"invalid XPJ worker database ownership marker: {name}")
        return None
    runtime_id = f"xdist_{name_match.group('run_hash')}_{name_match.group('worker_id')}"
    if comment is None:
        # Exact worker-shaped names are reserved by the marked XPJ test cluster.
        # A missing comment is the recoverable CREATE DATABASE -> COMMENT crash window.
        return runtime_id
    if not isinstance(comment, str):
        raise RuntimeError(f"invalid worker database comment: {name}")
    comment_match = _WORKER_COMMENT.fullmatch(comment)
    if (
        comment_match is None
        or comment_match.group("worker_id") != name_match.group("worker_id")
        or not comment_match.group("run_digest").startswith(name_match.group("run_hash"))
    ):
        raise RuntimeError(f"reserved worker database has foreign ownership: {name}")
    return runtime_id


def _cleanup_stale_worker_databases(
    conn,
    cleanup_runtime: Callable[[str], None],
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT datname, pg_catalog.shobj_description(oid, 'pg_database')
        FROM pg_catalog.pg_database
        WHERE datname LIKE %s
        ORDER BY datname
        """,
        (f"{_BASE_DATABASE}_%",),
    ).fetchall()
    stale_runtime_ids: list[str] = []
    for name, comment in rows:
        runtime_id = _stale_worker_runtime_id(name, comment)
        if runtime_id is None:
            continue
        cleanup_runtime(runtime_id)
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        stale_runtime_ids.append(runtime_id)
    return tuple(stale_runtime_ids)


@contextmanager
def serial_database_lease(
    admin_url: str,
    *,
    cleanup_runtime: Callable[[str], None],
) -> Iterator[tuple[str, ...]]:
    """Own the test cluster for one suite and recover proven stale workers."""
    with psycopg.connect(_maintenance_conninfo(admin_url), autocommit=True) as conn:
        if _database_comment(conn, _BASE_DATABASE) != _TEST_CLUSTER_COMMENT:
            raise RuntimeError("PostgreSQL cluster is not marked as an XPJ test cluster")
        acquired = conn.execute(
            "SELECT pg_catalog.pg_try_advisory_lock(%s)",
            (_SERIAL_LOCK_ID,),
        ).fetchone()
        if acquired is None or acquired[0] is not True:
            raise RuntimeError("another serial pytest session owns xpj_test")
        try:
            yield _cleanup_stale_worker_databases(conn, cleanup_runtime)
        finally:
            conn.execute("SELECT pg_catalog.pg_advisory_unlock(%s)", (_SERIAL_LOCK_ID,))
