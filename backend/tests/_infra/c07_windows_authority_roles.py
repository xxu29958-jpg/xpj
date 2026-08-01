"""Role-bootstrap phases for the real PostgreSQL C07 authority scenario."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import pytest
from psycopg import sql


@dataclass
class AuthorityScenario:
    tmp_path: Path
    operation_id: str
    restore_attempt_id: str
    owner: str
    migrator: str
    runtime: str
    outsider: str
    outsider_member: str
    database: str
    generated: dict[str, str]
    admin: psycopg.Connection
    conninfo: Callable[..., str]
    restore_open_sql: Callable[..., str]
    migrator_password: str
    runtime_password: str
    foreign_migrator_password: str
    foreign_runtime_password: str
    role_authority: dict[str, tuple[int, str]] = field(default_factory=dict)
    registered_marker: str = ""
    active_marker: str = ""
    database_admin: psycopg.Connection | None = None
    migrator_connection: psycopg.Connection | None = None
    runtime_connection: psycopg.Connection | None = None


def verify_role_bootstrap(scenario: AuthorityScenario) -> None:
    admin = scenario.admin
    assert int(admin.execute("SHOW server_version_num").fetchone()[0]) // 10_000 == 17
    admin.execute(scenario.generated["role"])
    original_verifier = admin.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s",
        (scenario.migrator,),
    ).fetchone()[0]
    admin.execute(
        sql.SQL("ALTER ROLE {} VALID UNTIL '2000-01-01T00:00:00Z'").format(
            sql.Identifier(scenario.migrator)
        )
    )
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            scenario.conninfo(
                database="postgres",
                username=scenario.migrator,
                password=scenario.migrator_password,
            ),
            connect_timeout=3,
        )
    admin.execute(scenario.generated["renewed_role"])
    renewed = admin.execute(
        "SELECT rolpassword, rolvaliduntil > now() "
        "FROM pg_authid WHERE rolname = %s",
        (scenario.migrator,),
    ).fetchone()
    assert renewed == (original_verifier, True)
    rows = admin.execute(
        "SELECT rolname, oid, shobj_description(oid, 'pg_authid') "
        "FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        ([scenario.owner, scenario.migrator, scenario.runtime],),
    ).fetchall()
    assert len(rows) == 3
    scenario.role_authority = {
        name: (role_oid, marker) for name, role_oid, marker in rows
    }
    for name, (role_oid, marker) in scenario.role_authority.items():
        assert marker == (
            f"ticketbox-c07-role-v2|{scenario.operation_id}|fresh_install|"
            f"roles_created|{role_oid}"
        ), name


def verify_exact_role_replay(scenario: AuthorityScenario) -> None:
    admin = scenario.admin
    for role in (scenario.outsider, scenario.outsider_member):
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
    admin.execute(scenario.generated["role"])
    rows = admin.execute(
        "SELECT rolname, oid, shobj_description(oid, 'pg_authid') "
        "FROM pg_roles WHERE rolname = ANY(%s)",
        ([scenario.owner, scenario.migrator, scenario.runtime],),
    ).fetchall()
    assert {name: (oid, marker) for name, oid, marker in rows} == (
        scenario.role_authority
    )
    admin.execute(scenario.generated["credential_drift_role"])
    with pytest.raises(psycopg.errors.RaiseException, match="marker mismatch"):
        admin.execute(scenario.generated["conflicting_role"])
    admin.execute("ROLLBACK")
    replayed = admin.execute(
        "SELECT rolname, oid, shobj_description(oid, 'pg_authid') "
        "FROM pg_roles WHERE rolname = ANY(%s)",
        ([scenario.owner, scenario.migrator, scenario.runtime],),
    ).fetchall()
    assert {name: (oid, marker) for name, oid, marker in replayed} == (
        scenario.role_authority
    )


def verify_foreign_memberships_rejected(scenario: AuthorityScenario) -> None:
    admin = scenario.admin
    for granted, member in (
        (scenario.outsider, scenario.migrator),
        (scenario.migrator, scenario.outsider),
    ):
        admin.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(granted),
                sql.Identifier(member),
            )
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="foreign C07 role membership residue",
        ):
            admin.execute(scenario.generated["role"])
        admin.execute("ROLLBACK")
        admin.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(granted),
                sql.Identifier(member),
            )
        )
