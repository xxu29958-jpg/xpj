from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import scripts.test_postgres_database as test_database
from app.database._core import _postgres_connect_args
from scripts.run_postgres_pytest_lane import child_environment, collection_environment
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import validated_test_postgres_conninfo
from scripts.write_test_postgres_env import existing_passfile, render_environment, write_passfile

_CLUSTER_IDENTITY = TEST_POSTGRES_CONTRACT.database_identity(
    "00000000-0000-0000-0000-000000000001"
)


class _FakeDatabaseConnection:
    def __init__(self, rows: list[object]) -> None:
        self.rows = iter(rows)
        self.statements: list[tuple[object, object]] = []

    def __enter__(self) -> _FakeDatabaseConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object, parameters: object = None) -> SimpleNamespace:
        self.statements.append((statement, parameters))
        row = next(self.rows, None)
        return SimpleNamespace(fetchone=lambda: row)


def _dedicated_database_url(tmp_path: Path, role: str) -> tuple[str, Path]:
    passfile = tmp_path / "pgpass"
    values = render_environment(
        host="localhost",
        port=TEST_POSTGRES_CONTRACT.ports.local,
        admin_user="postgres",
        application_user=TEST_POSTGRES_CONTRACT.application_role,
        passfile=passfile,
        cluster_identity=_CLUSTER_IDENTITY,
    )
    return values[role], passfile.resolve()


def _assert_ci_database_routes_are_sealed(values: dict[str, str]) -> None:
    base_url = values["XPJ_TEST_DATABASE_URL"]
    assert validated_test_postgres_conninfo(
        base_url,
        expected_database=TEST_POSTGRES_CONTRACT.base_database,
        expected_user=TEST_POSTGRES_CONTRACT.application_role,
    ).startswith("postgresql://")
    invalid_routes = {
        "remote host": base_url.replace("@localhost:", "@db.example:", 1),
        "embedded password": base_url.replace(
            f"{TEST_POSTGRES_CONTRACT.application_role}@",
            f"{TEST_POSTGRES_CONTRACT.application_role}:secret@",
            1,
        ),
        "wrong role": base_url.replace(f"{TEST_POSTGRES_CONTRACT.application_role}@", "ticketbox@", 1),
        "remote hostaddr": base_url.replace("hostaddr=127.0.0.1", "hostaddr=203.0.113.7", 1),
        "authentication downgrade": base_url.replace("scram-sha-256", "none", 1),
        "tls route": base_url.replace("sslmode=disable", "sslmode=require", 1),
        "extra option": base_url + "&application_name=xpj",
    }
    for candidate in invalid_routes.values():
        with pytest.raises(RuntimeError, match="test PostgreSQL URL"):
            validated_test_postgres_conninfo(
                candidate,
                expected_database=TEST_POSTGRES_CONTRACT.base_database,
                expected_user=TEST_POSTGRES_CONTRACT.application_role,
            )
    with pytest.raises(RuntimeError, match="unexpected database route"):
        validated_test_postgres_conninfo(
            base_url,
            expected_database="wrong_database",
            expected_user=TEST_POSTGRES_CONTRACT.application_role,
        )


def test_lane_runner_scrubs_ambient_libpq_routes_but_keeps_passfile() -> None:
    test_port = TEST_POSTGRES_CONTRACT.ports.local
    source = {
        "PGHOST": "production.example",
        "PGHOSTADDR": "203.0.113.7",
        "PGPORT": "5432",
        "PGDATABASE": "ticketbox",
        "PGUSER": "ticketbox",
        "PGSERVICE": "production",
        "PGREQUIREAUTH": "none",
        "PGPASSWORD": "ambient-secret",
        "TEST_POSTGRES_PASSWORD": "job-scoped-secret",
        "TEST_POSTGRES_APPLICATION_PASSWORD": "application-secret",
        "XPJ_TEST_APPLICATION_PASSWORD": "prepared-role-secret",
        "PGPASSFILE": "ephemeral-passfile",
        "XPJ_TEST_DATABASE_URL": (
            f"postgresql+psycopg://postgres@localhost:{test_port}/"
            f"{TEST_POSTGRES_CONTRACT.base_database}?require_auth=scram-sha-256"
        ),
        "XPJ_TEST_ADMIN_URL": (
            f"postgresql+psycopg://postgres@localhost:{test_port}/"
            "postgres?require_auth=scram-sha-256"
        ),
        "KEEP_ME": "yes",
        "PYTEST_ADDOPTS": "-k narrowed",
    }
    result = child_environment(source)
    assert result["PGPASSFILE"] == "ephemeral-passfile"
    assert result["KEEP_ME"] == "yes"
    assert result["PYTEST_ADDOPTS"] == ""
    assert not (
        {
            "PGHOST",
            "PGHOSTADDR",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGSERVICE",
            "PGPASSWORD",
            "TEST_POSTGRES_PASSWORD",
            "TEST_POSTGRES_APPLICATION_PASSWORD",
            "XPJ_TEST_APPLICATION_PASSWORD",
        }
        & result.keys()
    )
    assert source["PGHOST"] == "production.example"

    no_challenge = dict(source)
    no_challenge["XPJ_TEST_DATABASE_URL"] = source["XPJ_TEST_DATABASE_URL"].replace("scram-sha-256", "none")
    no_challenge["XPJ_TEST_ADMIN_URL"] = source["XPJ_TEST_ADMIN_URL"].replace("scram-sha-256", "none")
    assert "PGPASSFILE" not in child_environment(no_challenge)

    incomplete = dict(source)
    incomplete.pop("XPJ_TEST_ADMIN_URL")
    with pytest.raises(RuntimeError, match="and XPJ_TEST_ADMIN_URL together"):
        child_environment(incomplete)

    mismatched_authentication = dict(source)
    mismatched_authentication["XPJ_TEST_ADMIN_URL"] = source[
        "XPJ_TEST_ADMIN_URL"
    ].replace("scram-sha-256", "none")
    with pytest.raises(RuntimeError, match="same authentication"):
        child_environment(mismatched_authentication)

    collection = collection_environment(source)
    assert collection["KEEP_ME"] == "yes"
    assert collection["PYTEST_ADDOPTS"] == ""
    assert "PGPASSFILE" not in collection
    assert "TEST_POSTGRES_APPLICATION_PASSWORD" not in collection
    assert "XPJ_TEST_APPLICATION_PASSWORD" not in collection
    assert TEST_POSTGRES_CONTRACT.require_database_identity(
        collection["XPJ_TEST_CLUSTER_IDENTITY"]
    )
    assert "require_auth=scram-sha-256" in collection["XPJ_TEST_DATABASE_URL"]
    assert "require_auth=scram-sha-256" in collection["XPJ_TEST_ADMIN_URL"]


def test_ci_environment_uses_passwordless_scram_urls_and_private_passfile(tmp_path: Path) -> None:
    passfile = tmp_path / "pgpass"
    write_passfile(
        passfile,
        host="localhost",
        port=TEST_POSTGRES_CONTRACT.ports.local,
        admin_user="postgres",
        admin_password=r"ad:min\password",
        application_user=TEST_POSTGRES_CONTRACT.application_role,
        application_password=r"te:st\password",
    )
    values = render_environment(
        host="localhost",
        port=TEST_POSTGRES_CONTRACT.ports.local,
        admin_user="postgres",
        application_user=TEST_POSTGRES_CONTRACT.application_role,
        passfile=passfile,
        cluster_identity=_CLUSTER_IDENTITY,
    )

    assert existing_passfile(passfile) == passfile.resolve()
    assert values["PGPASSFILE"] == str(passfile.resolve())
    assert values["XPJ_TEST_BASE_DATABASE"] == TEST_POSTGRES_CONTRACT.base_database
    assert values["XPJ_TEST_SMOKE_DATABASE"] == TEST_POSTGRES_CONTRACT.smoke_database
    assert values["XPJ_TEST_RESTORE_DATABASE"] == TEST_POSTGRES_CONTRACT.restore_database
    assert values["XPJ_TEST_APPLICATION_ROLE"] == TEST_POSTGRES_CONTRACT.application_role
    for key in (
        "XPJ_TEST_ADMIN_URL",
        "XPJ_TEST_DATABASE_URL",
        "SMOKE_DATABASE_URL",
        "DRILL_SOURCE_URL",
        "DRILL_RESTORE_URL",
    ):
        url = values[key]
        parsed = urlsplit(url.replace("postgresql+psycopg", "postgresql", 1))
        assert parsed.password is None
        assert parsed.hostname == "localhost"
        assert parsed.port == TEST_POSTGRES_CONTRACT.ports.local
        query = parse_qs(parsed.query)
        assert query["require_auth"] == ["scram-sha-256"]
        assert query["sslmode"] == ["disable"]
        assert query["hostaddr"][0] in {"127.0.0.1", "::1"}
    if os.name != "nt":
        assert stat.S_IMODE(passfile.stat().st_mode) == 0o600
    assert passfile.read_text(encoding="utf-8") == (
        f"localhost:{TEST_POSTGRES_CONTRACT.ports.local}:*:postgres:ad\\:min\\\\password\n"
        f"localhost:{TEST_POSTGRES_CONTRACT.ports.local}:*:{TEST_POSTGRES_CONTRACT.application_role}:te\\:st\\\\password\n"
    )
    with pytest.raises(FileExistsError):
        write_passfile(
            passfile,
            host="localhost",
            port=TEST_POSTGRES_CONTRACT.ports.local,
            admin_user="postgres",
            admin_password="another-admin",
            application_user=TEST_POSTGRES_CONTRACT.application_role,
            application_password="another-app",
        )
    forbidden_port = next(iter(TEST_POSTGRES_CONTRACT.forbidden_host_ports))
    with pytest.raises(ValueError, match="reserved"):
        render_environment(
            host="localhost",
            port=forbidden_port,
            admin_user="postgres",
            application_user=TEST_POSTGRES_CONTRACT.application_role,
            passfile=passfile,
            cluster_identity=_CLUSTER_IDENTITY,
        )
    unsafe_url = values["XPJ_TEST_DATABASE_URL"].replace(
        f":{TEST_POSTGRES_CONTRACT.ports.local}/",
        f":{forbidden_port}/",
    )
    with pytest.raises(ValueError, match="reserved"):
        validated_test_postgres_conninfo(unsafe_url)

    _assert_ci_database_routes_are_sealed(values)


def test_application_connection_preserves_sealed_route_options(tmp_path: Path) -> None:
    database_url, _passfile = _dedicated_database_url(tmp_path, "SMOKE_DATABASE_URL")

    connect_args = _postgres_connect_args(database_url)

    assert connect_args == {
        "options": "-csearch_path=public,pg_catalog -c timezone=utc",
    }


def test_dedicated_database_lease_resets_schema_under_verified_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, passfile = _dedicated_database_url(tmp_path, "SMOKE_DATABASE_URL")
    authority = (
        TEST_POSTGRES_CONTRACT.smoke_database,
        TEST_POSTGRES_CONTRACT.application_role,
        False,
        True,
        _CLUSTER_IDENTITY,
    )
    connection = _FakeDatabaseConnection([authority, (True,), None, None, (True,)])
    observed: dict[str, object] = {}

    def connect(conninfo: str, **kwargs: object) -> _FakeDatabaseConnection:
        observed["conninfo"] = conninfo
        observed["kwargs"] = kwargs
        return connection

    monkeypatch.setattr(test_database.psycopg, "connect", connect)
    with test_database.dedicated_test_database_lease(
        database_url,
        expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
        reset=True,
        cluster_identity=_CLUSTER_IDENTITY,
        passfile=str(passfile),
    ):
        pass

    assert str(observed["conninfo"]).startswith("postgresql://")
    assert observed["kwargs"] == {"autocommit": True, "passfile": str(passfile)}
    assert "pg_try_advisory_lock" in str(connection.statements[1][0])
    assert "DROP SCHEMA" in str(connection.statements[2][0])
    assert "CREATE SCHEMA" in str(connection.statements[3][0])
    assert "pg_advisory_unlock" in str(connection.statements[4][0])

    foreign_authority = (*authority[:-1], TEST_POSTGRES_CONTRACT.database_identity(
        "00000000-0000-0000-0000-000000000002"
    ))
    foreign_connection = _FakeDatabaseConnection([foreign_authority])
    monkeypatch.setattr(
        test_database.psycopg,
        "connect",
        lambda *_args, **_kwargs: foreign_connection,
    )
    with (
        pytest.raises(RuntimeError, match="authority"),
        test_database.dedicated_test_database_lease(
            database_url,
            expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
            reset=True,
            cluster_identity=_CLUSTER_IDENTITY,
        ),
    ):
        pass


def test_dedicated_database_lease_rejects_a_competing_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, _passfile = _dedicated_database_url(tmp_path, "DRILL_RESTORE_URL")
    authority = (
        TEST_POSTGRES_CONTRACT.restore_database,
        TEST_POSTGRES_CONTRACT.application_role,
        False,
        True,
        _CLUSTER_IDENTITY,
    )
    connection = _FakeDatabaseConnection([authority, (False,)])
    monkeypatch.setattr(test_database.psycopg, "connect", lambda *_args, **_kwargs: connection)

    with (
        pytest.raises(RuntimeError, match="another process"),
        test_database.dedicated_test_database_lease(
            database_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=_CLUSTER_IDENTITY,
        ),
    ):
        pass
    assert len(connection.statements) == 2


def test_no_challenge_environment_is_sealed_without_a_passfile() -> None:
    values = render_environment(
        host="localhost",
        port=TEST_POSTGRES_CONTRACT.ports.gitea,
        admin_user="postgres",
        application_user=TEST_POSTGRES_CONTRACT.application_role,
        passfile=None,
        cluster_identity=_CLUSTER_IDENTITY,
        authentication="none",
    )

    assert "PGPASSFILE" not in values
    for key in (
        "XPJ_TEST_ADMIN_URL",
        "XPJ_TEST_DATABASE_URL",
        "SMOKE_DATABASE_URL",
        "DRILL_SOURCE_URL",
        "DRILL_RESTORE_URL",
    ):
        parsed = urlsplit(values[key].replace("postgresql+psycopg", "postgresql", 1))
        query = parse_qs(parsed.query)
        assert parsed.hostname == "localhost"
        assert parsed.port == TEST_POSTGRES_CONTRACT.ports.gitea
        assert parsed.password is None
        assert query["require_auth"] == ["none"]
        assert query["hostaddr"][0] in {"127.0.0.1", "::1"}


def test_ci_passfile_is_removed_when_durable_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    passfile = tmp_path / "pgpass"

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("simulated durable-write failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="durable-write"):
        write_passfile(
            passfile,
            host="localhost",
            port=TEST_POSTGRES_CONTRACT.ports.local,
            admin_user="postgres",
            admin_password="ephemeral-admin",
            application_user=TEST_POSTGRES_CONTRACT.application_role,
            application_password="ephemeral-app",
        )

    assert not passfile.exists()
