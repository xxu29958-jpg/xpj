"""Shared preparation for the existing managed postgres consumers."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

from app.database._database_generation_program import (
    DatabaseGenerationProgram,
    load_database_generation_program,
)
from app.database._managed_postgres_contract import MIGRATION_LEASE_LABEL
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeV1,
    ManagedPostgresRuntimeContractV1,
)
from app.database._release_schema_readiness import read_release_head
from app.services.secure_file import write_protected_file_exclusive
from scripts.build_database_generation_program import write_program
from tests._infra.alembic_runtime import alembic_config_for_test as _alembic_config
from tests._infra.alembic_runtime import run_alembic_for_test
from tests._infra.env import ADMIN_TEST_DATABASE_URL
from tests._infra.postgres_topology_cleanup import assert_database_schema_owners, cleanup_postgres_topology

_C07_TARGET_REVISION = "20260729_0001"


_C02_TARGET_REVISION = "20260802_0001"


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


def _revision(url: URL) -> str:
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as connection:
            return read_release_head(connection)
    finally:
        engine.dispose()


@dataclass(frozen=True)
class _ManagedTopology:
    admin: psycopg.Connection
    database: str
    owner: str
    migrator: str
    runtime_role: str
    owner_url: URL
    admin_database_url: URL
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
    target_admin_url = topology.admin_database_url.set(drivername="postgresql")
    with psycopg.connect(
        target_admin_url.render_as_string(hide_password=False),
        autocommit=True,
    ) as target_admin:
        target_admin.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                sql.Identifier(topology.owner)
            )
        )
        assert_database_schema_owners(
            target_admin,
            expected_owner=topology.owner,
        )


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
    admin_database_url = make_url(ADMIN_TEST_DATABASE_URL).set(
        drivername="postgresql+psycopg",
        database=database,
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
        admin_database_url=admin_database_url,
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
    primary: BaseException | None = None
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
        topology.admin.execute(
            sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(
                sql.Identifier(topology.owner)
            )
        )
        write_protected_file_exclusive(
            topology.pgpass,
            (
                f"127.0.0.1:{topology.migrator_url.port}:"
                f"{topology.database}:{topology.migrator}:{_MIGRATOR_PASSWORD}\n"
            ),
        )
        monkeypatch.delenv("PGPASSWORD", raising=False)
        yield topology
    except BaseException as exc:  # noqa: BLE001 - retain body plus teardown failures
        primary = exc
    cleanup_error: BaseException | None = None
    try:
        cleanup_postgres_topology(
            admin=topology.admin, database=topology.database,
            roles=(topology.runtime_role, topology.migrator, topology.owner),
        )
    except BaseException as exc:  # noqa: BLE001 - leaked test objects must fail
        cleanup_error = exc
    if primary is not None and cleanup_error is not None:
        raise BaseExceptionGroup(
            "managed topology body and cleanup failed",
            [primary, cleanup_error],
        )
    if primary is not None:
        raise primary
    if cleanup_error is not None:
        raise cleanup_error
