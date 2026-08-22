"""Temporary PostgreSQL role topology for the complete restore drill."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import validated_test_postgres_conninfo


@dataclass(frozen=True)
class _TopologyContract:
    admin_conninfo: str
    admin_restore_conninfo: str
    database: str
    migrator: str
    owner: str
    passfile: Path


@dataclass
class _TopologyState:
    role_created: bool = False
    migrator_changed: bool = False


def _resolve_topology_contract(*, restore_url: str, passfile: Path) -> _TopologyContract:
    migrator = TEST_POSTGRES_CONTRACT.application_role
    database = TEST_POSTGRES_CONTRACT.restore_database
    validated_test_postgres_conninfo(
        restore_url,
        expected_database=database,
        expected_user=migrator,
    )
    admin_url = os.environ["XPJ_TEST_ADMIN_URL"]
    admin_conninfo = validated_test_postgres_conninfo(
        admin_url,
        expected_database="postgres",
        expected_user="postgres",
    )
    return _TopologyContract(
        admin_conninfo=admin_conninfo,
        admin_restore_conninfo=make_url(admin_url)
        .set(drivername="postgresql", database=database)
        .render_as_string(hide_password=False),
        database=database,
        migrator=migrator,
        owner=f"xpj_drill_owner_{uuid4().hex}",
        passfile=passfile,
    )


def _install_topology(contract: _TopologyContract, state: _TopologyState) -> None:
    with psycopg.connect(
        contract.admin_conninfo,
        autocommit=True,
        passfile=str(contract.passfile),
    ) as admin:
        migrator_state = admin.execute(
            "SELECT rolinherit FROM pg_catalog.pg_roles WHERE rolname = %s",
            (contract.migrator,),
        ).fetchone()
        if migrator_state is None:
            raise RuntimeError("test migrator role disappeared before restore drill")
        admin.execute(
            sql.SQL(
                "CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(contract.owner))
        )
        state.role_created = True
        if bool(migrator_state[0]):
            admin.execute(
                sql.SQL("ALTER ROLE {} NOINHERIT").format(sql.Identifier(contract.migrator))
            )
            state.migrator_changed = True
        admin.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                sql.Identifier(contract.owner),
                sql.Identifier(contract.migrator),
            )
        )
        admin.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(contract.database),
                sql.Identifier(contract.owner),
            )
        )
    with psycopg.connect(
        contract.admin_restore_conninfo,
        autocommit=True,
        passfile=str(contract.passfile),
    ) as admin_restore:
        admin_restore.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                sql.Identifier(contract.owner)
            )
        )


def _remove_owned_topology(contract: _TopologyContract) -> None:
    with psycopg.connect(
        contract.admin_restore_conninfo,
        autocommit=True,
        passfile=str(contract.passfile),
    ) as admin_restore:
        admin_restore.execute(
            sql.SQL("REASSIGN OWNED BY {} TO {}").format(
                sql.Identifier(contract.owner),
                sql.Identifier(contract.migrator),
            )
        )
        admin_restore.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                sql.Identifier(contract.migrator)
            )
        )
    with psycopg.connect(
        contract.admin_conninfo,
        autocommit=True,
        passfile=str(contract.passfile),
    ) as admin:
        admin.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(contract.database),
                sql.Identifier(contract.migrator),
            )
        )
        admin.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(contract.owner),
                sql.Identifier(contract.migrator),
            )
        )
        admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(contract.owner)))


def _cleanup_topology(
    contract: _TopologyContract,
    state: _TopologyState,
) -> list[BaseException]:
    failures: list[BaseException] = []
    if state.role_created:
        try:
            _remove_owned_topology(contract)
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup truth
            failures.append(exc)
    if state.migrator_changed:
        try:
            with psycopg.connect(
                contract.admin_conninfo,
                autocommit=True,
                passfile=str(contract.passfile),
            ) as admin:
                admin.execute(
                    sql.SQL("ALTER ROLE {} INHERIT").format(
                        sql.Identifier(contract.migrator)
                    )
                )
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup truth
            failures.append(exc)
    return failures


def _raise_topology_failures(
    primary: BaseException | None,
    cleanup: list[BaseException],
) -> None:
    if primary is not None and cleanup:
        raise BaseExceptionGroup(
            "PostgreSQL drill and role-topology cleanup failed",
            [primary, *cleanup],
        ) from primary
    if primary is not None:
        raise primary
    if len(cleanup) == 1:
        raise cleanup[0]
    if cleanup:
        raise BaseExceptionGroup("PostgreSQL drill role-topology cleanup failed", cleanup)


@contextmanager
def managed_restore_role_topology(
    *,
    restore_url: str,
    passfile: Path,
) -> Iterator[str]:
    """Yield one SET-only schema owner and then restore the test role topology."""

    contract = _resolve_topology_contract(restore_url=restore_url, passfile=passfile)
    state = _TopologyState()
    primary: BaseException | None = None
    try:
        _install_topology(contract, state)
        yield contract.owner
    except BaseException as exc:  # noqa: BLE001 - preserve drill failure
        primary = exc
    cleanup = _cleanup_topology(contract, state)
    _raise_topology_failures(primary, cleanup)


__all__ = ["managed_restore_role_topology"]
