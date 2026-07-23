from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest
from psycopg.sql import Composed
from sqlalchemy.engine import make_url

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.write_test_postgres_env import render_environment
from tests._infra import worker_db

_CLUSTER_IDENTITY = TEST_POSTGRES_CONTRACT.require_database_identity(
    os.environ.get("XPJ_TEST_CLUSTER_IDENTITY")
)
_ENVIRONMENT = render_environment(
    host="localhost",
    port=TEST_POSTGRES_CONTRACT.ports.local,
    admin_user="postgres",
    application_user=TEST_POSTGRES_CONTRACT.application_role,
    passfile=None,
    cluster_identity=_CLUSTER_IDENTITY,
    authentication="none",
)
_BASE_URL = _ENVIRONMENT["XPJ_TEST_DATABASE_URL"]
_ADMIN_URL = _ENVIRONMENT["XPJ_TEST_ADMIN_URL"]


@dataclass
class _Result:
    row: tuple[object, ...] | None
    rows: list[tuple[object, ...]] = field(default_factory=list)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


@dataclass
class _Connection:
    databases: set[str] = field(
        default_factory=lambda: {TEST_POSTGRES_CONTRACT.base_database}
    )
    comments: dict[str, str | None] = field(
        default_factory=lambda: {
            TEST_POSTGRES_CONTRACT.base_database: _CLUSTER_IDENTITY
        }
    )
    lock_acquired: bool = True
    stale_rows: list[tuple[object, ...]] = field(default_factory=list)
    calls: list[tuple[object, object]] = field(default_factory=list)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        if isinstance(statement, str) and "shobj_description" in statement:
            if "datname LIKE %s" in statement:
                return _Result(None, self.stale_rows)
            name = params[0]
            if name not in self.databases:
                return _Result(None)
            return _Result((self.comments.get(name),))
        if (
            isinstance(statement, str)
            and statement.startswith("SELECT 1 FROM")
            and "pg_database" in statement
        ):
            return _Result((1,) if params[0] in self.databases else None)
        if isinstance(statement, str) and "pg_try_advisory_lock" in statement:
            return _Result((self.lock_acquired,))
        return _Result((True,))


def _patch_connection(monkeypatch: pytest.MonkeyPatch, connection: _Connection) -> None:
    def connect(conninfo: str, *, autocommit: bool):
        parsed = make_url(conninfo)
        assert parsed.database == "postgres"
        assert parsed.username == "postgres"
        assert parsed.query["hostaddr"] in {"127.0.0.1", "::1"}
        assert parsed.query["sslmode"] == "disable"
        assert parsed.query["require_auth"] == "none"
        assert parsed.password is None
        assert autocommit is True
        return connection

    monkeypatch.setattr(worker_db.psycopg, "connect", connect)


def test_worker_database_derives_stable_isolated_url() -> None:
    database = worker_db.worker_database(_BASE_URL, _ADMIN_URL, "gw2", "run-123")

    assert database.name.startswith(f"{TEST_POSTGRES_CONTRACT.base_database}_")
    assert database.name.endswith("_gw2")
    parsed = make_url(database.database_url)
    assert parsed.database == database.name
    assert parsed.query["hostaddr"] in {"127.0.0.1", "::1"}
    assert parsed.query["options"] == "-csearch_path=public,pg_catalog"
    assert parsed.password is None
    assert database.owner_marker.startswith(TEST_POSTGRES_CONTRACT.worker_marker_prefix)
    assert database == worker_db.worker_database(
        _BASE_URL, _ADMIN_URL, "gw2", "run-123"
    )
    assert database.name != worker_db.worker_database(
        _BASE_URL, _ADMIN_URL, "gw3", "run-123"
    ).name


@pytest.mark.parametrize(
    "url, worker_id",
    [
        (f"sqlite:///{TEST_POSTGRES_CONTRACT.base_database}", "gw0"),
        (
            f"postgresql+psycopg://postgres@localhost:{TEST_POSTGRES_CONTRACT.ports.local}/"
            "not_test?require_auth=none",
            "gw0",
        ),
        (
            f"postgresql+psycopg://postgres@example.com:{TEST_POSTGRES_CONTRACT.ports.local}/"
            f"{TEST_POSTGRES_CONTRACT.base_database}?require_auth=none",
            "gw0",
        ),
        (
            f"postgresql+psycopg://postgres:secret@localhost:{TEST_POSTGRES_CONTRACT.ports.local}/"
            f"{TEST_POSTGRES_CONTRACT.base_database}?require_auth=none",
            "gw0",
        ),
        (_BASE_URL, "worker-0"),
    ],
)
def test_worker_database_rejects_unsafe_authority(url: str, worker_id: str) -> None:
    with pytest.raises(ValueError):
        worker_db.worker_database(url, _ADMIN_URL, worker_id, "run-123")


def test_worker_database_rejects_unsafe_query_parameter_routing() -> None:
    for query in (
        "host=prod.example.com",
        "hostaddr=203.0.113.10",
        "port=5432",
        "dbname=postgres",
        "service=production",
        "sslmode=require",
        "require_auth=password",
    ):
        with pytest.raises(ValueError):
            unsafe_url = make_url(_BASE_URL).update_query_string(query).render_as_string(
                hide_password=False
            )
            worker_db.worker_database(unsafe_url, _ADMIN_URL, "gw0", "run-123")


def test_worker_database_accepts_and_preserves_sealed_scram_contract() -> None:
    scram_url = make_url(_BASE_URL).update_query_dict(
        {"require_auth": "scram-sha-256"}
    ).render_as_string(hide_password=False)
    sealed = worker_db.sealed_test_database_url(scram_url)
    parsed = make_url(sealed)

    assert parsed.query["require_auth"] == "scram-sha-256"
    assert parsed.query["hostaddr"] in {"127.0.0.1", "::1"}


def test_worker_database_explicit_route_ignores_libpq_environment_pollution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOST", "production.example")
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.9")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGDATABASE", "ticketbox")
    parsed = make_url(worker_db.sealed_test_database_url(_BASE_URL))

    assert parsed.host == "localhost"
    assert parsed.port == TEST_POSTGRES_CONTRACT.ports.local
    assert parsed.database == TEST_POSTGRES_CONTRACT.base_database
    assert parsed.query["hostaddr"] in {"127.0.0.1", "::1"}


def test_worker_database_environment_requires_complete_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.delenv("PYTEST_XDIST_TESTRUNUID", raising=False)

    with pytest.raises(ValueError, match="incomplete"):
        worker_db.worker_database_from_environment(_BASE_URL, _ADMIN_URL)


def test_worker_database_rejects_reserved_or_implicit_host_ports() -> None:
    reserved_port = next(iter(TEST_POSTGRES_CONTRACT.forbidden_host_ports))
    url = (
        f"postgresql+psycopg://{TEST_POSTGRES_CONTRACT.application_role}"
        f"@localhost:{reserved_port}/"
        f"{TEST_POSTGRES_CONTRACT.base_database}?require_auth=scram-sha-256"
    )
    with pytest.raises(ValueError, match="reserved"):
        worker_db.worker_database(url, _ADMIN_URL, "gw0", "run-123")

    implicit = (
        f"postgresql+psycopg://{TEST_POSTGRES_CONTRACT.application_role}@localhost/"
        f"{TEST_POSTGRES_CONTRACT.base_database}?require_auth=scram-sha-256"
    )
    with pytest.raises(ValueError, match="explicit port"):
        worker_db.worker_database(implicit, _ADMIN_URL, "gw0", "run-123")


def test_cluster_authority_rejects_unmarked_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(comments={TEST_POSTGRES_CONTRACT.base_database: None})
    _patch_connection(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="not marked"):
        worker_db.verify_test_cluster_authority(_ADMIN_URL)


def test_mark_existing_database_sets_cluster_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(comments={TEST_POSTGRES_CONTRACT.base_database: None})
    _patch_connection(monkeypatch, connection)

    worker_db.mark_existing_test_database(_ADMIN_URL)

    composed = [statement for statement, _params in connection.calls if isinstance(statement, Composed)]
    assert len(composed) == 1


def test_mark_existing_database_refuses_missing_or_marked_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for connection, message in (
        (_Connection(databases=set(), comments={}), "missing"),
        (_Connection(), "refusing to adopt"),
    ):
        _patch_connection(monkeypatch, connection)

        with pytest.raises(RuntimeError, match=message):
            worker_db.mark_existing_test_database(_ADMIN_URL)

        assert not any(isinstance(statement, Composed) for statement, _params in connection.calls)


def test_provision_refuses_preexisting_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = worker_db.worker_database(_BASE_URL, _ADMIN_URL, "gw0", "run-123")
    connection = _Connection(
        databases={TEST_POSTGRES_CONTRACT.base_database, database.name},
        comments={
            TEST_POSTGRES_CONTRACT.base_database: _CLUSTER_IDENTITY
        },
    )
    _patch_connection(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="already exists"):
        worker_db.provision_worker_database(database)

    assert len(connection.calls) == 2
    assert not any(isinstance(statement, Composed) for statement, _params in connection.calls)


def test_provision_and_drop_use_identifier_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection()
    _patch_connection(monkeypatch, connection)
    database = worker_db.worker_database(_BASE_URL, _ADMIN_URL, "gw0", "run-123")

    worker_db.provision_worker_database(database)
    connection.databases.add(database.name)
    connection.comments[database.name] = database.owner_marker
    assert worker_db.drop_worker_database(database) is True

    composed = [statement for statement, _params in connection.calls if isinstance(statement, Composed)]
    assert len(composed) == 3


def test_drop_refuses_database_owned_by_another_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = worker_db.worker_database(_BASE_URL, _ADMIN_URL, "gw0", "run-123")
    connection = _Connection(
        databases={TEST_POSTGRES_CONTRACT.base_database, database.name},
        comments={
            TEST_POSTGRES_CONTRACT.base_database: _CLUSTER_IDENTITY,
            database.name: (
                f"{TEST_POSTGRES_CONTRACT.worker_marker_prefix}another-run:gw0"
            ),
        },
    )
    _patch_connection(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="does not own"):
        worker_db.drop_worker_database(database)

    assert not any(isinstance(statement, Composed) for statement, _params in connection.calls)


def test_serial_database_lease_fails_fast_on_competing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(lock_acquired=False)
    _patch_connection(monkeypatch, connection)

    with (
        pytest.raises(RuntimeError, match="another serial pytest session"),
        worker_db.serial_database_lease(_ADMIN_URL, cleanup_runtime=lambda _runtime: None),
    ):
        raise AssertionError("lease body must not execute")


def test_serial_database_lease_recovers_only_marked_stale_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marked = worker_db.worker_database(
        _BASE_URL, _ADMIN_URL, "gw0", "stale-marked"
    )
    unmarked = worker_db.worker_database(
        _BASE_URL, _ADMIN_URL, "gw1", "stale-unmarked"
    )
    connection = _Connection(
        stale_rows=[
            (marked.name, marked.owner_marker),
            (unmarked.name, None),
            (f"{TEST_POSTGRES_CONTRACT.base_database}_foreign", None),
        ]
    )
    _patch_connection(monkeypatch, connection)

    cleaned: list[str] = []
    with worker_db.serial_database_lease(_ADMIN_URL, cleanup_runtime=cleaned.append):
        pass

    assert cleaned == [marked.runtime_id, unmarked.runtime_id]
    drops = [statement for statement, _params in connection.calls if isinstance(statement, Composed)]
    assert len(drops) == 2


def test_serial_database_lease_rejects_foreign_reserved_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = worker_db.worker_database(
        _BASE_URL, _ADMIN_URL, "gw0", "foreign-run"
    )
    connection = _Connection(stale_rows=[(reserved.name, "foreign-owner")])
    _patch_connection(monkeypatch, connection)

    with (
        pytest.raises(RuntimeError, match="foreign ownership"),
        worker_db.serial_database_lease(_ADMIN_URL, cleanup_runtime=lambda _runtime: None),
    ):
        pass

    assert not any(isinstance(statement, Composed) for statement, _params in connection.calls)


def test_serial_database_lease_keeps_database_anchor_when_file_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = worker_db.worker_database(_BASE_URL, _ADMIN_URL, "gw0", "stale-run")
    connection = _Connection(stale_rows=[(stale.name, stale.owner_marker)])
    _patch_connection(monkeypatch, connection)

    def fail_cleanup(_runtime_id: str) -> None:
        raise PermissionError("runtime is still open")

    with (
        pytest.raises(PermissionError, match="still open"),
        worker_db.serial_database_lease(_ADMIN_URL, cleanup_runtime=fail_cleanup),
    ):
        pass

    drops = [statement for statement, _params in connection.calls if isinstance(statement, Composed)]
    assert drops == []
