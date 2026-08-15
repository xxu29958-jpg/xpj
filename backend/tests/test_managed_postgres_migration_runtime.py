"""Real PostgreSQL proof for the C02 managed-migration runtime boundary."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.pool import NullPool

from app.database import _managed_postgres_migration_runtime as managed_runtime
from app.database import _managed_schema_upgrade as managed_schema
from app.database._database_generation_program import (
    DatabaseGenerationProgram,
    load_database_generation_program,
)
from app.database._managed_postgres_contract import MIGRATION_LEASE_LABEL
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
    ManagedPostgresMigrationRuntimeV1,
    ManagedPostgresRuntimeContractV1,
)
from app.database._release_schema_readiness import read_release_head
from app.services.secure_file import write_protected_file_exclusive
from scripts.build_database_generation_program import write_program
from tests._infra.c07_alembic import run_alembic_for_test
from tests._infra.env import ADMIN_TEST_DATABASE_URL

pytestmark = pytest.mark.real_db

_C07_TARGET_REVISION = "20260729_0001"
_C02_TARGET_REVISION = "20260802_0001"
_RELEASE_HEAD_REVISION = "20260809_0001"
_OWNER_PASSWORD = "ManagedOwnerRuntimePassword0001"
_MIGRATOR_PASSWORD = "ManagedMigratorRuntimePassword01"
_RUNTIME_PASSWORD = "ManagedApplicationRuntimePassword1"


def _connection_url(
    *,
    database: str,
    username: str,
    password: str | None,
    require_auth: bool,
) -> URL:
    admin = make_url(ADMIN_TEST_DATABASE_URL)
    query = {"require_auth": "scram-sha-256"} if require_auth else {}
    return admin.set(
        drivername="postgresql+psycopg",
        username=username,
        password=password,
        host="127.0.0.1",
        database=database,
        query=query,
    )


def _conninfo(
    *,
    database: str,
    username: str,
    password: str,
) -> str:
    return (
        _connection_url(
            database=database,
            username=username,
            password=password,
            require_auth=True,
        )
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )


def _alembic_config() -> Config:
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    return config


def _revision(url: URL) -> str:
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as connection:
            return read_release_head(connection)
    finally:
        engine.dispose()


def _migrator_sessions(admin: psycopg.Connection, *, database: str, role: str) -> int:
    return int(
        admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND usename = %s",
            (database, role),
        ).fetchone()[0]
    )


@dataclass(frozen=True)
class _ManagedTopology:
    admin: psycopg.Connection
    database: str
    owner: str
    migrator: str
    runtime_role: str
    owner_url: URL
    migrator_url: URL
    pgpass: Path
    previous_pgpass: str | None
    program: DatabaseGenerationProgram
    program_path: Path
    operation_id: str
    contract: ManagedPostgresRuntimeContractV1
    runtime: ManagedPostgresMigrationRuntimeV1


def _create_roles_and_database(topology: _ManagedTopology) -> None:
    for role, password in (
        (topology.owner, _OWNER_PASSWORD),
        (topology.migrator, _MIGRATOR_PASSWORD),
        (topology.runtime_role, _RUNTIME_PASSWORD),
    ):
        topology.admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    topology.admin.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
            sql.Identifier(topology.owner),
            sql.Identifier(topology.migrator),
        )
    )
    topology.admin.execute(
        sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(topology.database),
            sql.Identifier(topology.owner),
        )
    )


def _cleanup_topology(topology: _ManagedTopology) -> None:
    with suppress(psycopg.Error):
        topology.admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s OR usename = ANY(%s)",
            (
                topology.database,
                [topology.owner, topology.migrator, topology.runtime_role],
            ),
        )
    with suppress(psycopg.Error):
        topology.admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(topology.database))
        )
    with suppress(psycopg.Error):
        topology.admin.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(topology.owner),
                sql.Identifier(topology.migrator),
            )
        )
    with suppress(psycopg.Error):
        topology.admin.execute(
            sql.SQL("DROP ROLE IF EXISTS {}, {}, {}").format(
                sql.Identifier(topology.runtime_role),
                sql.Identifier(topology.migrator),
                sql.Identifier(topology.owner),
            )
        )
    topology.admin.close()


def _new_managed_topology(tmp_path: Path) -> _ManagedTopology:
    suffix = uuid4().hex[:12]
    owner = f"mm_owner_{suffix}"
    migrator = f"mm_migrator_{suffix}"
    runtime_role = f"mm_runtime_{suffix}"
    database = f"mm_c02_{suffix}"
    admin_url = make_url(ADMIN_TEST_DATABASE_URL).set(
        drivername="postgresql",
        database="postgres",
    )
    admin = psycopg.connect(
        admin_url.render_as_string(hide_password=False),
        autocommit=True,
    )
    owner_url = _connection_url(
        database=database,
        username=owner,
        password=_OWNER_PASSWORD,
        require_auth=True,
    )
    migrator_url = _connection_url(
        database=database,
        username=migrator,
        password=None,
        require_auth=True,
    )
    contract = ManagedPostgresRuntimeContractV1(
        database_name=database,
        migrator_role=migrator,
        schema_owner_role=owner,
        lease_label=MIGRATION_LEASE_LABEL,
        transaction_timeout_ms=20 * 60 * 1000,
    )
    port = migrator_url.port
    assert port is not None
    pgpass = (tmp_path / f".managed-pgpass-{suffix}").resolve()
    program_path = (tmp_path / "DATABASE_GENERATION_PROGRAM.json").resolve()
    program_sha256 = write_program(
        backend_root=Path(__file__).resolve().parents[1],
        output=program_path,
    )
    return _ManagedTopology(
        admin=admin,
        database=database,
        owner=owner,
        migrator=migrator,
        runtime_role=runtime_role,
        owner_url=owner_url,
        migrator_url=migrator_url,
        pgpass=pgpass,
        previous_pgpass=os.environ.get("PGPASSFILE"),
        program=load_database_generation_program(
            path=program_path,
            expected_sha256=program_sha256,
        ),
        program_path=program_path,
        operation_id=str(uuid4()),
        contract=contract,
        runtime=ManagedPostgresMigrationRuntimeV1(contract),
    )


@contextmanager
def _managed_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[_ManagedTopology]:
    topology = _new_managed_topology(tmp_path)
    try:
        _create_roles_and_database(topology)
        owner_engine = create_engine(topology.owner_url, poolclass=NullPool, future=True)
        config = _alembic_config()
        try:
            run_alembic_for_test(
                owner_engine,
                config,
                command.upgrade,
                _C07_TARGET_REVISION,
            )
        finally:
            owner_engine.dispose()
        write_protected_file_exclusive(
            topology.pgpass,
            (
                f"127.0.0.1:{topology.migrator_url.port}:"
                f"{topology.database}:{topology.migrator}:{_MIGRATOR_PASSWORD}\n"
            ),
        )
        monkeypatch.delenv("PGPASSWORD", raising=False)
        yield topology
    finally:
        _cleanup_topology(topology)


def _assert_lease_contention(topology: _ManagedTopology) -> None:
    blocker = create_engine(topology.owner_url, poolclass=NullPool, future=True)
    try:
        with blocker.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(current_database()), hashtext(:label))"),
                {"label": topology.contract.lease_label},
            )
            with pytest.raises(
                ManagedPostgresMigrationRuntimeError,
                match="lease is busy",
            ):
                topology.runtime.run(
                    database_url=topology.migrator_url.render_as_string(hide_password=False),
                    pgpassfile=topology.pgpass,
                    program=topology.program,
                    source_revision=_C07_TARGET_REVISION,
                    target_revision=_RELEASE_HEAD_REVISION,
                    generation_operation_id=topology.operation_id,
                )
    finally:
        blocker.dispose()
    assert _revision(topology.owner_url) == _C07_TARGET_REVISION
    assert (
        _migrator_sessions(
            topology.admin,
            database=topology.database,
            role=topology.migrator,
        )
        == 0
    )


def _reject_postcondition(
    connection: Connection,
    *,
    expected_timeout_ms: int,
) -> None:
    timeout_ms = connection.scalar(
        text("SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name = 'transaction_timeout'")
    )
    assert int(timeout_ms) == expected_timeout_ms
    raise RuntimeError("injected C02 postcondition failure")


def _assert_rollback_retry_and_replay(
    topology: _ManagedTopology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_execute = managed_runtime.execute_database_generation

    def fail_after_execution(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        _reject_postcondition(
            args[0],
            expected_timeout_ms=topology.contract.transaction_timeout_ms,
        )
        return result

    monkeypatch.setattr(
        managed_runtime,
        "execute_database_generation",
        fail_after_execution,
    )
    with pytest.raises(
        ManagedPostgresMigrationRuntimeError,
        match="managed PostgreSQL migration failed",
    ):
        topology.runtime.run(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            program=topology.program,
            source_revision=_C07_TARGET_REVISION,
            target_revision=_RELEASE_HEAD_REVISION,
            generation_operation_id=topology.operation_id,
        )
    monkeypatch.setattr(
        managed_runtime,
        "execute_database_generation",
        original_execute,
    )
    assert _revision(topology.owner_url) == _C07_TARGET_REVISION
    owner_probe = create_engine(topology.owner_url, poolclass=NullPool, future=True)
    try:
        with owner_probe.connect() as connection:
            assert "installation_currency_bindings" not in inspect(connection).get_table_names(schema="public")
    finally:
        owner_probe.dispose()

    arguments = {
        "database_url": topology.migrator_url.render_as_string(hide_password=False),
        "pgpassfile": topology.pgpass,
        "program": topology.program,
        "source_revision": _C07_TARGET_REVISION,
        "target_revision": _RELEASE_HEAD_REVISION,
        "generation_operation_id": topology.operation_id,
    }
    assert topology.runtime.run(**arguments) == "target_committed"
    assert _revision(topology.owner_url) == _RELEASE_HEAD_REVISION
    assert topology.runtime.run(**arguments) == "target_observed_after_interruption"
    monkeypatch.setattr(managed_schema, "DATABASE_NAME", topology.database)
    monkeypatch.setattr(managed_schema, "MIGRATOR_ROLE", topology.migrator)
    monkeypatch.setattr(managed_schema, "SCHEMA_OWNER_ROLE", topology.owner)
    noop_result = managed_schema.run_managed_schema_upgrade_action(
        database_url=topology.migrator_url.render_as_string(hide_password=False),
        pgpassfile=topology.pgpass,
        generation_program_path=topology.program_path,
        expected_generation_program_sha256=topology.program.payload_sha256,
        source_revision=_RELEASE_HEAD_REVISION,
        target_revision=_RELEASE_HEAD_REVISION,
        generation_operation_id=topology.operation_id,
    )
    assert noop_result["result"] == "target_observed_after_interruption"
    assert noop_result["alembic_revision"] == _RELEASE_HEAD_REVISION
    assert (
        _migrator_sessions(
            topology.admin,
            database=topology.database,
            role=topology.migrator,
        )
        == 0
    )
    assert os.environ.get("PGPASSFILE") == topology.previous_pgpass


def _grant_runtime_access(topology: _ManagedTopology) -> None:
    target_admin = psycopg.connect(
        make_url(ADMIN_TEST_DATABASE_URL)
        .set(drivername="postgresql", database=topology.database)
        .render_as_string(hide_password=False),
        autocommit=True,
    )
    try:
        statements = (
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(topology.database), sql.Identifier(topology.runtime_role)
            ),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(topology.runtime_role)),
            sql.SQL("GRANT SELECT, UPDATE ON public.installation_currency_bindings TO {}").format(
                sql.Identifier(topology.runtime_role)
            ),
            sql.SQL("GRANT SELECT, INSERT, UPDATE ON public.installation_idempotency_keys TO {}").format(
                sql.Identifier(topology.runtime_role)
            ),
            sql.SQL("GRANT INSERT ON public.installation_currency_audit_log TO {}").format(
                sql.Identifier(topology.runtime_role)
            ),
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(topology.runtime_role)),
        )
        for statement in statements:
            target_admin.execute(statement)
    finally:
        target_admin.close()


def _assert_runtime_restart_and_migrator_retirement(
    topology: _ManagedTopology,
) -> None:
    runtime_conninfo = _conninfo(
        database=topology.database,
        username=topology.runtime_role,
        password=_RUNTIME_PASSWORD,
    )
    for _restart in range(2):
        runtime_connection = psycopg.connect(runtime_conninfo, autocommit=True)
        try:
            assert (
                runtime_connection.execute(
                    "SELECT state FROM public.installation_currency_bindings WHERE singleton_id = 1"
                ).fetchone()[0]
                == "EMPTY"
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime_connection.execute(
                    "ALTER TABLE public.installation_currency_bindings ADD COLUMN forbidden integer"
                )
        finally:
            runtime_connection.close()

    topology.admin.execute(sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(topology.migrator)))
    assert (
        _migrator_sessions(
            topology.admin,
            database=topology.database,
            role=topology.migrator,
        )
        == 0
    )
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            _conninfo(
                database=topology.database,
                username=topology.migrator,
                password=_MIGRATOR_PASSWORD,
            ),
            connect_timeout=3,
        )


def test_c02_runtime_uses_one_migrator_transaction_and_retires_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _managed_topology(tmp_path, monkeypatch) as topology:
        _assert_lease_contention(topology)
        _assert_rollback_retry_and_replay(topology, monkeypatch)
        _grant_runtime_access(topology)
        _assert_runtime_restart_and_migrator_retirement(topology)
