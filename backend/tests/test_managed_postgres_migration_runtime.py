"""Real PostgreSQL proof for the C02 managed-migration runtime boundary."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.pool import NullPool

from app.database import _managed_postgres_migration_runtime as managed_runtime
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
)
from tests._infra.env import ADMIN_TEST_DATABASE_URL
from tests.managed_postgres_test_support import (
    _C07_TARGET_REVISION,
    _MIGRATOR_PASSWORD,
    _RUNTIME_PASSWORD,
    _connection_url,
    _managed_topology,
    _ManagedTopology,
    _revision,
)

pytestmark = pytest.mark.real_db


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


def _migrator_sessions(admin: psycopg.Connection, *, database: str, role: str) -> int:
    return int(
        admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND usename = %s",
            (database, role),
        ).fetchone()[0]
    )


def _assert_lease_contention(topology: _ManagedTopology) -> None:
    blocker = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
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
                    target_revision=topology.program.target_revision,
                    generation_operation_id=topology.operation_id,
                )
    finally:
        blocker.dispose()
    assert _revision(topology.admin_database_url) == _C07_TARGET_REVISION
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
            target_revision=topology.program.target_revision,
            generation_operation_id=topology.operation_id,
        )
    monkeypatch.setattr(
        managed_runtime,
        "execute_database_generation",
        original_execute,
    )
    assert _revision(topology.admin_database_url) == _C07_TARGET_REVISION
    owner_probe = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
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
        "target_revision": topology.program.target_revision,
        "generation_operation_id": topology.operation_id,
    }
    assert topology.runtime.run(**arguments) == "target_committed"
    assert _revision(topology.admin_database_url) == topology.program.target_revision
    assert topology.runtime.run(**arguments) == "target_observed_after_interruption"
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
