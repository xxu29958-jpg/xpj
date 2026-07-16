from __future__ import annotations

from pathlib import Path
from threading import Event

import psycopg
import pytest
from sqlalchemy.engine import make_url

from scripts import test_pg_contract
from scripts.test_pg_contract import configured_test_database_url
from scripts.test_pg_protected_file import (
    assert_protected_authority_file,
    write_protected_utf8_file,
)
from tests._infra import db as db_infra
from tests._infra import worker_db as worker_db_infra
from tests._infra.postgres_contract_fakes import (
    fake_lock_events as _fake_lock_events,
)
from tests._infra.postgres_contract_fakes import (
    owned_environment as _owned_environment,
)
from tests._infra.worker_db import (
    new_worker_run_uid,
    worker_database_url,
)


@pytest.mark.parallel_safe
def test_database_url_override_requires_explicit_cluster_authority() -> None:
    override = "postgresql+psycopg://postgres@localhost:5432/xpj_test"

    with pytest.raises(RuntimeError, match="explicit test-cluster authority"):
        configured_test_database_url({"XPJ_TEST_DATABASE_URL": override})

    assert configured_test_database_url({}) == ("postgresql+psycopg://postgres@localhost:5438/xpj_test")
    assert (
        configured_test_database_url(
            {
                "XPJ_TEST_DATABASE_URL": override,
                test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
                    test_pg_contract.OWNED_MARKER_AUTHORITY,
            }
        )
        == override
    )

    with pytest.raises(ValueError, match="xpj_test base"):
        configured_test_database_url(
            {
                "XPJ_TEST_DATABASE_URL": ("postgresql+psycopg://postgres@localhost:5432/xpj_testimony"),
                test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
                    test_pg_contract.OWNED_MARKER_AUTHORITY,
            }
        )

    with pytest.raises(ValueError, match="reserved worker namespace"):
        configured_test_database_url(
            {
                "XPJ_TEST_DATABASE_URL": ("postgresql+psycopg://postgres@localhost:5432/xpj_test_0123456789abcdef_gw0"),
                test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
                    test_pg_contract.OWNED_MARKER_AUTHORITY,
            }
        )

    for query_database in ("ticketbox", "xpj_test"):
        with pytest.raises(ValueError, match="query parameters"):
            configured_test_database_url(
                {
                    "XPJ_TEST_DATABASE_URL": (
                        f"postgresql+psycopg://postgres@localhost:5432/xpj_test?dbname={query_database}"
                    ),
                    test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
                        test_pg_contract.OWNED_MARKER_AUTHORITY,
                }
            )

    with pytest.raises(ValueError, match="loopback"):
        configured_test_database_url(
            {
                "XPJ_TEST_DATABASE_URL": (
                    "postgresql+psycopg://postgres@database.example:5432/xpj_test"
                ),
                test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
                    test_pg_contract.EPHEMERAL_SERVICE_AUTHORITY,
            }
        )


@pytest.mark.parallel_safe
def test_worker_database_url_preserves_connection_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_db_infra.secrets, "token_hex", lambda _size: "owned")
    assert new_worker_run_uid("gw0") == "owned"
    assert new_worker_run_uid(None) is None

    result = worker_database_url(
        "postgresql+psycopg://postgres@localhost:5438/xpj_test",
        "gw3",
        "run-alpha",
    )
    other_run = worker_database_url(
        "postgresql+psycopg://postgres@localhost:5438/xpj_test",
        "gw3",
        "run-beta",
    )

    parsed = make_url(result)
    assert parsed.database is not None
    assert parsed.database.startswith("xpj_test_")
    assert parsed.database.endswith("_gw3")
    assert parsed.database != make_url(other_run).database
    assert parsed.username == "postgres"
    assert parsed.password is None
    assert parsed.port == 5438
    assert not parsed.query


@pytest.mark.parametrize("worker_id", ["master", "gw", "gw-1", "gw1_extra"])
@pytest.mark.parallel_safe
def test_worker_database_url_rejects_invalid_worker_id(worker_id: str) -> None:
    with pytest.raises(ValueError, match="worker id"):
        worker_database_url(
            "postgresql+psycopg://postgres@localhost:5438/xpj_test",
            worker_id,
            "run-alpha",
        )


@pytest.mark.parallel_safe
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
            "postgresql+psycopg://postgres@localhost:5432/xpj_test_0123456789abcdef_gw0",
            "gw0",
            "run-alpha",
        )


@pytest.mark.parallel_safe
def test_worker_database_url_refuses_non_postgresql_engine() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        worker_database_url("sqlite:///xpj_test", "gw0", "run-alpha")


@pytest.mark.parallel_safe
def test_worker_lifecycle_refuses_non_worker_database() -> None:
    current_run = "run-alpha"
    worker_id = "gw0"
    with (
        pytest.raises(ValueError, match="current xpj_test_<run>_gwN"),
        worker_db_infra._validated_worker_url(
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
        worker_db_infra._validated_worker_url(
            another_run_url,
            worker_id=worker_id,
            run_uid=current_run,
        ),
    ):
        pass


@pytest.mark.real_db
@pytest.mark.stateful_serial
@pytest.mark.cluster_serial
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
@pytest.mark.parallel_safe
def test_schema_reset_refuses_non_test_database(
    monkeypatch: pytest.MonkeyPatch,
    database_name: str,
) -> None:
    class ProductionEngineStub:
        url = make_url(f"postgresql+psycopg://postgres@localhost:5432/{database_name}")

    monkeypatch.setattr(db_infra, "engine", ProductionEngineStub())

    with pytest.raises(RuntimeError, match="non-test PostgreSQL"):
        db_infra.reset_db_state()


@pytest.mark.parallel_safe
def test_test_database_url_rejects_libpq_target_overrides() -> None:
    for query in (
        "hostaddr=203.0.113.7",
        "host=localhost&port=5544",
        "service=foreign",
        "sslmode=disable",
    ):
        with pytest.raises(ValueError, match="query parameters"):
            test_pg_contract.validate_test_database_url(
                f"postgresql+psycopg://postgres@localhost:5438/xpj_test?{query}"
            )
    with pytest.raises(ValueError, match="must not contain a password"):
        test_pg_contract.validate_test_database_url(
            "postgresql+psycopg://postgres:secret@localhost:5438/xpj_test"
        )
    with pytest.raises(ValueError, match="managed postgres role"):
        test_pg_contract.validate_test_database_url(
            "postgresql+psycopg://tester@localhost:5438/xpj_test"
        )


@pytest.mark.parallel_safe
def test_managed_smoke_and_restore_urls_share_one_fixed_authority() -> None:
    base_url = "postgresql+psycopg://postgres@127.0.0.1:5544/xpj_test"
    smoke_url = test_pg_contract.managed_test_database_url(base_url, "xpj_smoke")
    restore_url = test_pg_contract.managed_test_database_url(base_url, "xpj_restore")

    source, restore = test_pg_contract.validate_backup_drill_database_urls(
        smoke_url,
        restore_url,
    )

    assert source.database == "xpj_smoke"
    assert restore.database == "xpj_restore"
    with pytest.raises(ValueError, match="must target xpj_smoke"):
        test_pg_contract.validate_backup_drill_database_urls(
            restore_url,
            smoke_url,
        )
    with pytest.raises(ValueError, match="share one PostgreSQL endpoint"):
        test_pg_contract.validate_backup_drill_database_urls(
            smoke_url,
            "postgresql+psycopg://postgres@127.0.0.1:5545/xpj_restore",
        )


@pytest.mark.parallel_safe
def test_owned_cluster_authority_matches_marker_to_live_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    database_url, environment = _owned_environment(tmp_path)
    marker_path = Path(environment[test_pg_contract.TEST_CLUSTER_MARKER_PATH_ENV])
    data_directory = marker_path.parent
    live_row = [
        "1234567890123456789",
        str(data_directory.resolve()),
        "5544",
        "127.0.0.1",
    ]

    class Result:
        def fetchone(self):
            return tuple(live_row)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, *_args):
            return Result()

    monkeypatch.setattr(
        test_pg_contract.psycopg,
        "connect",
        lambda **_arguments: Connection(),
    )
    with test_pg_contract.test_postgres_credential_environment(
        database_url,
        environment,
    ):
        test_pg_contract.assert_test_cluster_authority(database_url, environment)
        live_row[0] = "9876543210987654321"
        with pytest.raises(RuntimeError, match="system identifier"):
            test_pg_contract.assert_test_cluster_authority(database_url, environment)


@pytest.mark.parallel_safe
def test_credential_environment_scrubs_pollution_and_destroys_passfile(
    tmp_path: Path,
) -> None:
    database_url, environment = _owned_environment(tmp_path)
    environment.update(
        {
            "PGHOSTADDR": "203.0.113.9",
            "PGSERVICE": "foreign",
            "PGPASSWORD": "ambient-secret",
            "PGPASSFILE": "ambient-passfile",
            "PGREQUIREAUTH": "none",
        }
    )
    with test_pg_contract.test_postgres_credential_environment(
        database_url,
        environment,
    ) as passfile:
        assert {key for key in environment if key.startswith("PG")} == {
            "PGPASSFILE",
            "PGREQUIREAUTH",
        }
        assert environment["PGPASSFILE"] == str(passfile)
        assert environment["PGREQUIREAUTH"] == "scram-sha-256"
        assert passfile.read_text(encoding="utf-8") == (
            "127.0.0.1:5544:*:postgres:" + ("c" * 43) + "\n"
        )
        assert_protected_authority_file(
            passfile,
            label="Derived test PostgreSQL passfile",
        )
        insecure_passfile = tmp_path / "insecure-passfile"
        insecure_passfile.write_text("not-protected\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="permissions|protected-DACL|ACL entries"):
            assert_protected_authority_file(
                insecure_passfile,
                label="Insecure PostgreSQL passfile",
            )
    assert not passfile.exists()
    assert environment["PGHOSTADDR"] == "203.0.113.9"
    assert environment["PGSERVICE"] == "foreign"
    assert environment["PGPASSWORD"] == "ambient-secret"
    assert environment["PGPASSFILE"] == "ambient-passfile"
    assert environment["PGREQUIREAUTH"] == "none"


@pytest.mark.parallel_safe
def test_protected_writer_preserves_preexisting_collision(tmp_path: Path) -> None:
    target = (tmp_path / "preexisting-authority").resolve()
    target.write_text("original\n", encoding="utf-8")

    with pytest.raises(OSError):
        write_protected_utf8_file(
            target,
            "replacement\n",
            label="Collision test authority",
        )

    assert target.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parallel_safe
def test_ephemeral_cluster_authority_requires_ci_identity() -> None:
    database_url = "postgresql+psycopg://postgres@localhost:5432/xpj_test"
    with pytest.raises(RuntimeError, match="only inside CI"):
        test_pg_contract.assert_test_cluster_authority(
            database_url,
            {
                test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
                    test_pg_contract.EPHEMERAL_SERVICE_AUTHORITY,
            },
        )


@pytest.mark.parallel_safe
def test_exclusive_cluster_lock_releases_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events = _fake_lock_events(monkeypatch)
    database_url, environment = _owned_environment(tmp_path)

    with (
        test_pg_contract.test_postgres_credential_environment(
        database_url,
        environment,
    ), pytest.raises(ZeroDivisionError),
        test_pg_contract.test_cluster_lock(
            environment,
            exclusive=True,
        ),
    ):
        events.append(("body", None))
        raise ZeroDivisionError

    assert events[0][0] == "connect"
    connect_arguments = events[0][1]
    assert isinstance(connect_arguments, dict)
    assert connect_arguments["autocommit"] is True
    assert connect_arguments["dbname"] == "postgres"
    assert connect_arguments["host"] == "127.0.0.1"
    assert connect_arguments["port"] == 5544
    assert connect_arguments["user"] == "postgres"
    assert "password" not in connect_arguments
    assert Path(connect_arguments["passfile"]).name.startswith(".xpj-pgpass-")
    assert connect_arguments["require_auth"] == "scram-sha-256"
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


@pytest.mark.parallel_safe
def test_shared_cluster_lock_and_query_target_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events = _fake_lock_events(monkeypatch)
    database_url, environment = _owned_environment(tmp_path)

    with test_pg_contract.test_postgres_credential_environment(
        database_url,
        environment,
    ), test_pg_contract.test_cluster_lock(
        environment,
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

    with pytest.raises(ValueError, match="query parameters"):
        test_pg_contract.admin_connection_args(
            make_url("postgresql+psycopg:///xpj_test?host=localhost&port=5545")
        )


@pytest.mark.parallel_safe
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

    assert messages == ["Lost PostgreSQL worker lease; aborting this test process."]
