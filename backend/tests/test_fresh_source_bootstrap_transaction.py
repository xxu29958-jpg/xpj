"""Real PostgreSQL rollback proof for the installed fresh-source action."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.database import _c07_fresh_source_bootstrap as fresh_source
from app.database._release_schema_readiness import read_release_head
from app.services.secure_file import write_protected_file_exclusive
from scripts.build_database_generation_program import write_program
from tests._infra.env import ADMIN_TEST_DATABASE_URL

pytestmark = pytest.mark.real_db

_OWNER_PASSWORD = "FreshOwnerTransactionPassword0001"
_MIGRATOR_PASSWORD = "FreshMigratorTransactionPassword01"


def _role_url(*, database: str, role: str, password: str | None) -> URL:
    return make_url(ADMIN_TEST_DATABASE_URL).set(
        drivername="postgresql+psycopg",
        username=role,
        password=password,
        host="127.0.0.1",
        database=database,
        query={"require_auth": "scram-sha-256"},
    )


def _create_database_authority(
    admin: psycopg.Connection,
    *,
    owner: str,
    migrator: str,
    database: str,
) -> None:
    for role, password in ((owner, _OWNER_PASSWORD), (migrator, _MIGRATOR_PASSWORD)):
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    admin.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
            sql.Identifier(owner), sql.Identifier(migrator)
        )
    )
    admin.execute(
        sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(database), sql.Identifier(owner)
        )
    )
    target_admin = psycopg.connect(
        make_url(ADMIN_TEST_DATABASE_URL)
        .set(drivername="postgresql", database=database)
        .render_as_string(hide_password=False),
        autocommit=True,
    )
    try:
        target_admin.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(owner))
        )
    finally:
        target_admin.close()


def _create_fresh_topology(tmp_path: Path) -> SimpleNamespace:
    suffix = uuid4().hex[:12]
    owner = f"fresh_owner_{suffix}"
    migrator = f"fresh_migrator_{suffix}"
    database = f"fresh_source_{suffix}"
    admin = psycopg.connect(
        make_url(ADMIN_TEST_DATABASE_URL)
        .set(drivername="postgresql", database="postgres")
        .render_as_string(hide_password=False),
        autocommit=True,
    )
    _create_database_authority(
        admin,
        owner=owner,
        migrator=migrator,
        database=database,
    )
    program_path = (tmp_path / "DATABASE_GENERATION_PROGRAM.json").resolve()
    program_sha256 = write_program(
        backend_root=Path(__file__).resolve().parents[1],
        output=program_path,
    )
    secrets = tmp_path / "TicketboxInstallerSecrets"
    secrets.mkdir()
    pgpass = (secrets / f".ticketbox-pgpass-1-{uuid4().hex}").resolve()
    migrator_url = _role_url(database=database, role=migrator, password=None)
    write_protected_file_exclusive(
        pgpass,
        f"127.0.0.1:{migrator_url.port}:{database}:{migrator}:{_MIGRATOR_PASSWORD}\n",
    )
    return SimpleNamespace(
        admin=admin,
        database=database,
        owner=owner,
        migrator=migrator,
        owner_url=_role_url(database=database, role=owner, password=_OWNER_PASSWORD),
        migrator_url=migrator_url,
        pgpass=pgpass,
        program_path=program_path,
        program_sha256=program_sha256,
        operation_id=str(uuid4()),
    )


def _drop_fresh_topology(topology: SimpleNamespace) -> None:
    with suppress(psycopg.Error):
        topology.admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s OR usename = ANY(%s)",
            (topology.database, [topology.owner, topology.migrator]),
        )
    with suppress(psycopg.Error):
        topology.admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(topology.database)
            )
        )
    with suppress(psycopg.Error):
        topology.admin.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(topology.owner), sql.Identifier(topology.migrator)
            )
        )
    with suppress(psycopg.Error):
        topology.admin.execute(
            sql.SQL("DROP ROLE IF EXISTS {}, {}").format(
                sql.Identifier(topology.migrator), sql.Identifier(topology.owner)
            )
        )
    topology.admin.close()


@contextmanager
def _fresh_topology(tmp_path: Path) -> Iterator[SimpleNamespace]:
    topology = _create_fresh_topology(tmp_path)
    try:
        yield topology
    finally:
        _drop_fresh_topology(topology)


def test_fresh_source_action_keeps_generation_in_one_postgres_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PGPASSWORD", raising=False)
    with _fresh_topology(tmp_path) as topology:
        monkeypatch.setattr(fresh_source, "DATABASE_NAME", topology.database)
        monkeypatch.setattr(fresh_source, "MIGRATOR_ROLE", topology.migrator)
        monkeypatch.setattr(fresh_source, "SCHEMA_OWNER_ROLE", topology.owner)
        original_run = fresh_source._run_fresh_source_with_connection  # noqa: SLF001

        def fail_after_generation(*args, **kwargs):
            original_run(*args, **kwargs)
            raise SQLAlchemyError("injected failure after fresh generation")

        monkeypatch.setattr(fresh_source, "_run_fresh_source_with_connection", fail_after_generation)
        arguments = {
            "database_url": topology.migrator_url.render_as_string(hide_password=False),
            "pgpassfile": topology.pgpass,
            "generation_program_path": topology.program_path,
            "expected_generation_program_sha256": topology.program_sha256,
            "generation_operation_id": topology.operation_id,
            "source_revision": fresh_source.C07_SOURCE_REVISION,
            "target_revision": fresh_source.C07_TARGET_REVISION,
        }
        with pytest.raises(
            fresh_source.C07FreshSourceBootstrapError,
            match="fresh-source PostgreSQL bootstrap failed",
        ):
            fresh_source.run_fresh_source_bootstrap_action(**arguments)

        probe = create_engine(topology.owner_url, poolclass=NullPool, future=True)
        try:
            with probe.connect() as connection:
                assert connection.scalar(text("SELECT to_regclass('public.alembic_version')")) is None
                assert inspect(connection).get_table_names(schema="public") == []
        finally:
            probe.dispose()

        monkeypatch.setattr(fresh_source, "_run_fresh_source_with_connection", original_run)
        result = fresh_source.run_fresh_source_bootstrap_action(**arguments)
        assert result["alembic_revision"] == fresh_source.C07_SOURCE_REVISION
        verify = create_engine(topology.owner_url, poolclass=NullPool, future=True)
        try:
            with verify.connect() as connection:
                assert read_release_head(connection) == fresh_source.C07_SOURCE_REVISION
        finally:
            verify.dispose()
