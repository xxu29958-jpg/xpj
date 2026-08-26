"""PostgreSQL 17 proofs for the installed runtime authority query."""

from __future__ import annotations

from contextlib import suppress
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from app.database._database_generation_runtime_queries import RUNTIME_AUTHORITY_QUERY
from app.database._managed_postgres_contract import (
    MIGRATOR_ROLE,
    RUNTIME_ROLE,
    SCHEMA_OWNER_ROLE,
)
from tests._infra.env import ADMIN_TEST_DATABASE_URL

pytestmark = pytest.mark.real_db


def _conninfo(
    *,
    database: str,
    username: str | None = None,
    password: str | None = None,
) -> str:
    url = make_url(ADMIN_TEST_DATABASE_URL).set(
        drivername="postgresql",
        database=database,
    )
    if username is not None:
        url = url.set(username=username, password=password)
    return url.render_as_string(hide_password=False)


def _close(connection: psycopg.Connection | None) -> None:
    if connection is not None:
        with suppress(Exception):
            connection.close()


def _drop_database_and_roles(
    admin: psycopg.Connection,
    *,
    database: str,
    roles: tuple[str, ...],
) -> None:
    with suppress(psycopg.Error):
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database)
            )
        )
    for role in roles:
        with suppress(psycopg.Error):
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
    admin.close()


def test_pg17_owner_remains_authoritative_after_ordinary_privileges_are_revoked() -> None:
    suffix = uuid4().hex[:12]
    role = f"runtime_owner_probe_{suffix}"
    database = f"runtime_owner_probe_{suffix}"
    admin = psycopg.connect(_conninfo(database="postgres"), autocommit=True)
    target: psycopg.Connection | None = None
    try:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database),
                sql.Identifier(role),
            )
        )
        target = psycopg.connect(_conninfo(database=database), autocommit=True)
        target.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(role))
        )
        target.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC, {}").format(
                sql.Identifier(database),
                sql.Identifier(role),
            )
        )
        target.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database),
                sql.Identifier(role),
            )
        )
        target.execute(
            sql.SQL(
                "REVOKE ALL ON SCHEMA public FROM PUBLIC, pg_database_owner, {}"
            ).format(sql.Identifier(role))
        )
        target.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
        )
        probe = target.execute(
            sql.SQL(
                """
                SELECT
                    has_database_privilege({role}, {database}, 'CONNECT'),
                    NOT has_database_privilege({role}, {database}, 'CREATE'),
                    NOT has_database_privilege({role}, {database}, 'TEMPORARY'),
                    has_schema_privilege({role}, 'public', 'USAGE'),
                    NOT has_schema_privilege({role}, 'public', 'CREATE'),
                    (SELECT datdba = role.oid FROM pg_catalog.pg_database
                     WHERE datname = {database}),
                    (SELECT nspowner = role.oid FROM pg_catalog.pg_namespace
                     WHERE nspname = 'public')
                FROM pg_catalog.pg_roles AS role
                WHERE role.rolname = {role}
                """
            ).format(role=sql.Literal(role), database=sql.Literal(database))
        ).fetchone()

        assert probe == (True, True, True, True, True, True, True)
    finally:
        _close(target)
        _drop_database_and_roles(admin, database=database, roles=(role,))


def _create_runtime_roles_and_database(
    admin: psycopg.Connection,
    *,
    database: str,
    escape_role: str,
    runtime_password: str,
) -> None:
    statements = (
        sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(SCHEMA_OWNER_ROLE)),
        sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(MIGRATOR_ROLE)),
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(RUNTIME_ROLE), sql.Literal(runtime_password)),
        sql.SQL("CREATE ROLE {} NOLOGIN SUPERUSER").format(sql.Identifier(escape_role)),
        sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(database),
            sql.Identifier(SCHEMA_OWNER_ROLE),
        ),
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC, {}").format(
            sql.Identifier(database),
            sql.Identifier(RUNTIME_ROLE),
        ),
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database),
            sql.Identifier(RUNTIME_ROLE),
        ),
    )
    for statement in statements:
        admin.execute(statement)


def _configure_runtime_database(target: psycopg.Connection) -> None:
    target.execute(
        sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
            sql.Identifier(SCHEMA_OWNER_ROLE)
        )
    )
    target.execute(
        sql.SQL(
            "REVOKE ALL ON SCHEMA public FROM PUBLIC, pg_database_owner, {}"
        ).format(sql.Identifier(RUNTIME_ROLE))
    )
    target.execute(
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
            sql.Identifier(RUNTIME_ROLE)
        )
    )
    target.execute(
        """
        CREATE TABLE public.dataset_authority (
            singleton_id integer PRIMARY KEY,
            dataset_id text NOT NULL,
            client_generation text NOT NULL,
            restore_epoch integer NOT NULL,
            schema_revision text NOT NULL,
            schema_min_compatible text NOT NULL,
            semantic_revision text NOT NULL,
            restored_from_backup_id text
        )
        """
    )
    target.execute(
        sql.SQL("ALTER TABLE public.dataset_authority OWNER TO {}").format(
            sql.Identifier(SCHEMA_OWNER_ROLE)
        )
    )
    target.execute(
        """
        INSERT INTO public.dataset_authority VALUES (
            1,
            '22222222-2222-4222-8222-222222222222',
            '11111111-1111-4111-8111-111111111111',
            0,
            '20260821_0001',
            '1.2.0',
            'ticketbox-dataset-semantics-v1',
            NULL
        )
        """
    )
    target.execute(
        sql.SQL(
            "REVOKE ALL ON TABLE public.dataset_authority FROM PUBLIC, {}; "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            "public.dataset_authority TO {}"
        ).format(sql.Identifier(RUNTIME_ROLE), sql.Identifier(RUNTIME_ROLE))
    )


def test_product_query_rejects_any_runtime_role_membership() -> None:
    suffix = uuid4().hex[:12]
    database = f"runtime_membership_probe_{suffix}"
    escape_role = f"runtime_escape_probe_{suffix}"
    runtime_password = uuid4().hex + uuid4().hex
    exact_roles = (SCHEMA_OWNER_ROLE, MIGRATOR_ROLE, RUNTIME_ROLE)
    cleanup_roles: tuple[str, ...] = ()
    admin = psycopg.connect(_conninfo(database="postgres"), autocommit=True)
    target: psycopg.Connection | None = None
    runtime: psycopg.Connection | None = None
    try:
        existing = admin.execute(
            "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
            (list(exact_roles),),
        ).fetchall()
        assert existing == []
        cleanup_roles = (escape_role, *reversed(exact_roles))
        _create_runtime_roles_and_database(
            admin,
            database=database,
            escape_role=escape_role,
            runtime_password=runtime_password,
        )
        target = psycopg.connect(_conninfo(database=database), autocommit=True)
        _configure_runtime_database(target)
        admin.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                sql.Identifier(escape_role),
                sql.Identifier(RUNTIME_ROLE),
            )
        )
        runtime = psycopg.connect(
            _conninfo(
                database=database,
                username=RUNTIME_ROLE,
                password=runtime_password,
            ),
            autocommit=True,
            row_factory=dict_row,
        )
        observation = runtime.execute(str(RUNTIME_AUTHORITY_QUERY)).fetchone()

        assert observation is not None
        assert observation["runtime_role_ready"] is True
        assert observation["runtime_database_ready"] is True
        assert observation["runtime_schema_ready"] is True
        assert observation["runtime_tables_ready"] is True
        assert observation["runtime_sequences_ready"] is True
        assert observation["runtime_role_isolated"] is False
    finally:
        _close(runtime)
        _close(target)
        _drop_database_and_roles(admin, database=database, roles=cleanup_roles)
