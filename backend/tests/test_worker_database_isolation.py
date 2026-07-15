from __future__ import annotations

from threading import Event

import psycopg
import pytest
from sqlalchemy.engine import make_url

from scripts import test_pg_contract
from scripts.test_pg_contract import configured_test_database_url
from tests._infra import db as db_infra
from tests._infra import worker_db as worker_db_infra
from tests._infra.worker_db import (
    new_worker_run_uid,
    worker_database_lifecycle,
    worker_database_url,
)


def test_database_url_override_requires_explicit_cluster_confirmation() -> None:
    override = "postgresql+psycopg://postgres@localhost:5432/xpj_test"

    with pytest.raises(RuntimeError, match="XPJ_TEST_CLUSTER_CONFIRMED=1"):
        configured_test_database_url({"XPJ_TEST_DATABASE_URL": override})

    assert configured_test_database_url({}) == (
        "postgresql+psycopg://postgres@localhost:5438/xpj_test"
    )
    assert configured_test_database_url(
        {
            "XPJ_TEST_DATABASE_URL": override,
            "XPJ_TEST_CLUSTER_CONFIRMED": "1",
        }
    ) == override

    with pytest.raises(ValueError, match="xpj_test base"):
        configured_test_database_url(
            {
                "XPJ_TEST_DATABASE_URL": (
                    "postgresql+psycopg://postgres@localhost:5432/xpj_testimony"
                ),
                "XPJ_TEST_CLUSTER_CONFIRMED": "1",
            }
        )

    with pytest.raises(ValueError, match="reserved worker namespace"):
        configured_test_database_url(
            {
                "XPJ_TEST_DATABASE_URL": (
                    "postgresql+psycopg://postgres@localhost:5432/"
                    "xpj_test_0123456789abcdef_gw0"
                ),
                "XPJ_TEST_CLUSTER_CONFIRMED": "1",
            }
        )

    for query_database in ("ticketbox", "xpj_test"):
        with pytest.raises(ValueError, match="dbname query"):
            configured_test_database_url(
                {
                    "XPJ_TEST_DATABASE_URL": (
                        "postgresql+psycopg://postgres@localhost:5432/"
                        f"xpj_test?dbname={query_database}"
                    ),
                    "XPJ_TEST_CLUSTER_CONFIRMED": "1",
                }
            )


def test_worker_database_url_preserves_connection_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_db_infra.secrets, "token_hex", lambda _size: "owned")
    assert new_worker_run_uid("gw0") == "owned"
    assert new_worker_run_uid(None) is None

    result = worker_database_url(
        "postgresql+psycopg://tester:secret@localhost:5438/xpj_test?sslmode=disable",
        "gw3",
        "run-alpha",
    )
    other_run = worker_database_url(
        "postgresql+psycopg://tester:secret@localhost:5438/xpj_test?sslmode=disable",
        "gw3",
        "run-beta",
    )

    parsed = make_url(result)
    assert parsed.database is not None
    assert parsed.database.startswith("xpj_test_")
    assert parsed.database.endswith("_gw3")
    assert parsed.database != make_url(other_run).database
    assert parsed.username == "tester"
    assert parsed.password == "secret"
    assert parsed.port == 5438
    assert parsed.query["sslmode"] == "disable"


@pytest.mark.parametrize("worker_id", ["master", "gw", "gw-1", "gw1_extra"])
def test_worker_database_url_rejects_invalid_worker_id(worker_id: str) -> None:
    with pytest.raises(ValueError, match="worker id"):
        worker_database_url(
            "postgresql+psycopg://postgres@localhost:5438/xpj_test",
            worker_id,
            "run-alpha",
        )


def test_worker_database_url_refuses_non_test_database() -> None:
    for database_name in ("ticketbox", "xpj_testimony"):
        with pytest.raises(ValueError, match="xpj_test base"):
            worker_database_url(
                f"postgresql+psycopg://postgres@localhost:5432/{database_name}",
                "gw0",
                "run-alpha",
            )

    with pytest.raises(ValueError, match="reserved worker namespace"):
        worker_database_url(
            "postgresql+psycopg://postgres@localhost:5432/"
            "xpj_test_0123456789abcdef_gw0",
            "gw0",
            "run-alpha",
        )


def test_worker_database_url_refuses_non_postgresql_engine() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        worker_database_url("sqlite:///xpj_test", "gw0", "run-alpha")


def test_worker_lifecycle_refuses_non_worker_database() -> None:
    current_run = "run-alpha"
    worker_id = "gw0"
    with (
        pytest.raises(ValueError, match="current xpj_test_<run>_gwN"),
        worker_database_lifecycle(
            "postgresql+psycopg://postgres@localhost:5432/ticketbox",
            worker_id=worker_id,
            run_uid=current_run,
        ),
    ):
        pass

    another_run_url = worker_database_url(
        "postgresql+psycopg://postgres@localhost:5438/xpj_test",
        worker_id,
        "run-beta",
    )
    with (
        pytest.raises(ValueError, match="current xpj_test_<run>_gwN"),
        worker_database_lifecycle(
            another_run_url,
            worker_id=worker_id,
            run_uid=current_run,
        ),
    ):
        pass


def test_orphan_quarantine_restores_connections_for_a_late_lease() -> None:
    events: list[str] = []

    class FakeResult:
        def __init__(self, row: tuple[bool] | None = None) -> None:
            self.row = row

        def fetchone(self) -> tuple[bool] | None:
            return self.row

    class FakeConnection:
        def execute(self, statement, parameters=()):
            rendered = str(statement)
            events.append(rendered)
            if "pg_stat_activity" in rendered:
                return FakeResult((True,))
            if "pg_database" in rendered:
                return FakeResult((True,))
            return FakeResult()

    worker_db_infra._quarantine_and_drop_orphan(
        FakeConnection(),
        "xpj_test_0123456789abcdef_gw0",
    )

    assert any("ALLOW_CONNECTIONS false" in event for event in events)
    assert any("ALLOW_CONNECTIONS true" in event for event in events)
    assert not any("DROP DATABASE" in event for event in events)


@pytest.mark.parametrize("database_name", ["ticketbox", "xpj_testimony"])
def test_schema_reset_refuses_non_test_database(
    monkeypatch: pytest.MonkeyPatch,
    database_name: str,
) -> None:
    class ProductionEngineStub:
        url = make_url(
            f"postgresql+psycopg://postgres@localhost:5432/{database_name}"
        )

    monkeypatch.setattr(db_infra, "engine", ProductionEngineStub())

    with pytest.raises(RuntimeError, match="non-test PostgreSQL"):
        db_infra.reset_db_state()


def _lock_environment() -> dict[str, str]:
    return {
        "XPJ_TEST_DATABASE_URL": (
            "postgresql+psycopg://tester:secret@authority.example:5432/"
            "xpj_test?host=query.example&port=5544&sslmode=require"
        ),
        "XPJ_TEST_CLUSTER_CONFIRMED": "1",
    }


def _fake_lock_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []

    class FakeResult:
        def fetchone(self) -> tuple[bool]:
            return (True,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            events.append(("closed", None))

        def execute(self, statement: str, parameters: tuple[str | int, ...]):
            events.append((statement, parameters))
            return FakeResult()

    def fake_connect(**arguments):
        events.append(("connect", arguments))
        return FakeConnection()

    monkeypatch.setattr(test_pg_contract.psycopg, "connect", fake_connect)
    return events


def test_exclusive_cluster_lock_releases_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _fake_lock_events(monkeypatch)

    with (
        pytest.raises(ZeroDivisionError),
        test_pg_contract.test_cluster_lock(
            _lock_environment(),
            exclusive=True,
        ),
    ):
        events.append(("body", None))
        raise ZeroDivisionError

    assert events[0] == (
        "connect",
        {
            "autocommit": True,
            "dbname": "postgres",
            "host": "query.example",
            "port": "5544",
            "user": "tester",
            "password": "secret",
            "sslmode": "require",
        },
    )
    event_names = [event[0] for event in events]
    assert event_names == [
        "connect",
        "SELECT set_config('idle_session_timeout', %s, false)",
        "SELECT set_config('statement_timeout', %s, false)",
        "SELECT pg_advisory_lock(%s)",
        "body",
        "SELECT pg_advisory_unlock(%s)",
        "closed",
    ]


def test_shared_cluster_lock_and_query_target_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _fake_lock_events(monkeypatch)

    with test_pg_contract.test_cluster_lock(
        _lock_environment(),
        exclusive=False,
    ):
        events.append(("body", None))
    assert [event[0] for event in events] == [
        "connect",
        "SELECT set_config('idle_session_timeout', %s, false)",
        "SELECT set_config('statement_timeout', %s, false)",
        "SELECT pg_advisory_lock_shared(%s)",
        "body",
        "SELECT pg_advisory_unlock_shared(%s)",
        "closed",
    ]

    query_only = test_pg_contract.admin_connection_args(
        make_url(
            "postgresql+psycopg:///xpj_test?host=query-only.example&port=5545"
        )
    )
    assert query_only == {
        "dbname": "postgres",
        "host": "query-only.example",
        "port": "5545",
    }


def test_authority_watchdog_fails_closed_when_connection_disappears() -> None:
    aborted = Event()
    messages: list[str] = []

    class LostConnection:
        def execute(self, statement: str, parameters: tuple[object, ...]):
            raise psycopg.OperationalError("server connection was terminated")

    def record_abort(message: str) -> None:
        messages.append(message)
        aborted.set()

    with (
        pytest.raises(RuntimeError, match="Lost PostgreSQL worker lease"),
        test_pg_contract.authority_connection_watchdog(
            LostConnection(),
            label="worker lease",
            heartbeat_seconds=0.001,
            abort_process=record_abort,
        ),
    ):
        assert aborted.wait(timeout=1)

    assert messages == [
        "Lost PostgreSQL worker lease; aborting this test process."
    ]
