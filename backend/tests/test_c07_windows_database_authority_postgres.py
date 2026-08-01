"""PostgreSQL 17 behavior proof for the Windows C07 database authority SQL."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from tests._infra.c07_windows_authority_database import (
    activate_restore_database,
    create_registered_restore_database,
    install_source_schema,
    verify_privilege_sql_rejects_foreign_acl,
)
from tests._infra.c07_windows_authority_privileges import (
    open_authority_connections,
    retire_migrator,
    verify_future_objects_are_narrow,
    verify_runtime_business_acl,
    verify_runtime_financial_facts,
)
from tests._infra.c07_windows_authority_roles import (
    AuthorityScenario,
    verify_exact_role_replay,
    verify_foreign_memberships_rejected,
    verify_role_bootstrap,
)
from tests._infra.env import ADMIN_TEST_DATABASE_URL

pytestmark = pytest.mark.real_db

_DATABASE_SCRIPT = (
    Path(__file__).resolve().parents[1] / "packaging" / "windows_c07_database.ps1"
)
_RUNTIME_PASSWORD = "RuntimeC07AuthorityPassword000001"
_MIGRATOR_PASSWORD = "MigratorC07AuthorityPassword0001"
_FOREIGN_RUNTIME_PASSWORD = "ForeignRuntimeCredentialPassword01"
_FOREIGN_MIGRATOR_PASSWORD = "ForeignMigratorCredentialPassword1"


def _restore_database_name(operation_id: str, create_attempt_id: str) -> str:
    binding = (
        "ticketbox-c07-restore-attempt-v1"
        f"|{operation_id}|{create_attempt_id}"
    )
    digest = hashlib.sha256(binding.encode("utf-8")).hexdigest()
    return f"ticketbox_c07_restore_{digest[:40]}"


def _ps_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _run_pwsh(tmp_path: Path, name: str, source: str) -> str:
    executable = shutil.which("pwsh")
    assert executable is not None, "the C07 PostgreSQL lane requires PowerShell 7"
    harness = tmp_path / f"{name}.ps1"
    harness.write_text(source, encoding="utf-8-sig")
    result = subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            harness,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    return result.stdout.strip()


def _authority_sql_source(
    *,
    owner: str,
    migrator: str,
    runtime: str,
    database: str,
    operation_id: str,
    conflicting_operation_id: str,
) -> str:
    return f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(_DATABASE_SCRIPT)}'
function Escape-SqlLiteral([string]$Value) {{ return $Value.Replace("'", "''") }}
$script:TicketboxC07OwnerRole = '{_ps_literal(owner)}'
$script:TicketboxC07MigratorRole = '{_ps_literal(migrator)}'
$script:TicketboxC07RuntimeRole = '{_ps_literal(runtime)}'
$script:TicketboxC07LegacyRuntimeRole = 'c07_legacy_absent'
$script:TicketboxC07DatabaseName = '{_ps_literal(database)}'
$runtimePassword = ConvertTo-SecureString `
    '{_ps_literal(_RUNTIME_PASSWORD)}' -AsPlainText -Force
$migratorPassword = ConvertTo-SecureString `
    '{_ps_literal(_MIGRATOR_PASSWORD)}' -AsPlainText -Force
$foreignRuntimePassword = ConvertTo-SecureString `
    '{_ps_literal(_FOREIGN_RUNTIME_PASSWORD)}' -AsPlainText -Force
$foreignMigratorPassword = ConvertTo-SecureString `
    '{_ps_literal(_FOREIGN_MIGRATOR_PASSWORD)}' -AsPlainText -Force
$runtimeVerifier = ConvertTo-TicketboxC07ScramVerifier $runtimePassword
$migratorVerifier = ConvertTo-TicketboxC07ScramVerifier $migratorPassword
$foreignRuntimeVerifier = ConvertTo-TicketboxC07ScramVerifier $foreignRuntimePassword
$foreignMigratorVerifier = ConvertTo-TicketboxC07ScramVerifier $foreignMigratorPassword
$validUntil = [DateTime]::UtcNow.AddMinutes(30)
$renewedValidUntil = [DateTime]::UtcNow.AddMinutes(50)
$payload = [ordered]@{{
    role = Get-TicketboxC07RoleBootstrapSql `
        -RuntimeVerifier $runtimeVerifier `
        -MigratorVerifier $migratorVerifier `
        -MigratorValidUntilUtc $validUntil `
        -OperationId '{_ps_literal(operation_id)}' `
        -Mode 'fresh_install'
    renewed_role = Get-TicketboxC07RoleBootstrapSql `
        -RuntimeVerifier $runtimeVerifier `
        -MigratorVerifier $migratorVerifier `
        -MigratorValidUntilUtc $renewedValidUntil `
        -OperationId '{_ps_literal(operation_id)}' `
        -Mode 'fresh_install'
    conflicting_role = Get-TicketboxC07RoleBootstrapSql `
        -RuntimeVerifier $runtimeVerifier `
        -MigratorVerifier $migratorVerifier `
        -MigratorValidUntilUtc $validUntil `
        -OperationId '{_ps_literal(conflicting_operation_id)}' `
        -Mode 'fresh_install'
    credential_drift_role = Get-TicketboxC07RoleBootstrapSql `
        -RuntimeVerifier $foreignRuntimeVerifier `
        -MigratorVerifier $foreignMigratorVerifier `
        -MigratorValidUntilUtc $validUntil `
        -OperationId '{_ps_literal(operation_id)}' `
        -Mode 'fresh_install'
    privilege = Get-TicketboxC07DatabasePrivilegeSql
    retirement = Get-TicketboxC07MigratorRetirementSql
    retirement_verification = Get-TicketboxC07MigratorRetirementVerificationSql
    restore_create = Get-TicketboxC07RestoreDatabaseCreateSql `
        '{_ps_literal(database)}'
}}
$payload | ConvertTo-Json -Compress
"""


def _authority_sql(
    tmp_path: Path,
    *,
    owner: str,
    migrator: str,
    runtime: str,
    database: str,
    operation_id: str,
    conflicting_operation_id: str,
) -> dict[str, str]:
    output = _run_pwsh(
        tmp_path,
        "generate-c07-authority-sql",
        _authority_sql_source(
            owner=owner,
            migrator=migrator,
            runtime=runtime,
            database=database,
            operation_id=operation_id,
            conflicting_operation_id=conflicting_operation_id,
        ),
    )
    payload = json.loads(output)
    assert set(payload) == {
        "role",
        "renewed_role",
        "conflicting_role",
        "credential_drift_role",
        "privilege",
        "retirement",
        "retirement_verification",
        "restore_create",
    }
    return payload


def _restore_open_sql(
    tmp_path: Path,
    *,
    owner: str,
    migrator: str,
    runtime: str,
    database: str,
    marker: str,
) -> str:
    return _run_pwsh(
        tmp_path,
        "generate-c07-restore-open-sql",
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(_DATABASE_SCRIPT)}'
$script:TicketboxC07OwnerRole = '{_ps_literal(owner)}'
$script:TicketboxC07MigratorRole = '{_ps_literal(migrator)}'
$script:TicketboxC07RuntimeRole = '{_ps_literal(runtime)}'
Get-TicketboxC07RestoreDatabaseOpenSql `
    -Database '{_ps_literal(database)}' `
    -ActiveMarker '{_ps_literal(marker)}'
""",
    )


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




def _cleanup_scenario(scenario: AuthorityScenario) -> None:
    _close(scenario.runtime_connection)
    _close(scenario.migrator_connection)
    _close(scenario.database_admin)
    with suppress(Exception):
        scenario.admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s OR usename = ANY(%s)",
            (scenario.database, [scenario.migrator, scenario.runtime]),
        )
    with suppress(Exception):
        scenario.admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(scenario.database)
            )
        )
    with suppress(Exception):
        scenario.admin.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(scenario.owner),
                sql.Identifier(scenario.migrator),
            )
        )
    with suppress(Exception):
        scenario.admin.execute(
            sql.SQL("DROP ROLE IF EXISTS {}, {}, {}, {}, {}").format(
                sql.Identifier(scenario.outsider),
                sql.Identifier(scenario.outsider_member),
                sql.Identifier(scenario.runtime),
                sql.Identifier(scenario.migrator),
                sql.Identifier(scenario.owner),
            )
        )
    scenario.admin.close()


def test_c07_database_authority_is_crash_safe_narrow_and_retires_migrator(
    tmp_path: Path,
) -> None:
    operation_id = str(uuid4())
    restore_attempt_id = str(uuid4())
    conflicting_operation_id = str(uuid4())
    suffix = operation_id.replace("-", "")[:12]
    owner, migrator, runtime = (f"c07o_{suffix}", f"c07m_{suffix}", f"c07r_{suffix}")
    database = _restore_database_name(operation_id, restore_attempt_id)
    scenario = AuthorityScenario(
        tmp_path=tmp_path,
        operation_id=operation_id,
        restore_attempt_id=restore_attempt_id,
        owner=owner,
        migrator=migrator,
        runtime=runtime,
        outsider=f"c07x_{suffix}",
        outsider_member=f"c07y_{suffix}",
        database=database,
        generated=_authority_sql(
            tmp_path,
            owner=owner,
            migrator=migrator,
            runtime=runtime,
            database=database,
            operation_id=operation_id,
            conflicting_operation_id=conflicting_operation_id,
        ),
        admin=psycopg.connect(_conninfo(database="postgres"), autocommit=True),
        conninfo=_conninfo,
        restore_open_sql=_restore_open_sql,
        migrator_password=_MIGRATOR_PASSWORD,
        runtime_password=_RUNTIME_PASSWORD,
        foreign_migrator_password=_FOREIGN_MIGRATOR_PASSWORD,
        foreign_runtime_password=_FOREIGN_RUNTIME_PASSWORD,
    )
    try:
        verify_role_bootstrap(scenario)
        verify_exact_role_replay(scenario)
        verify_foreign_memberships_rejected(scenario)
        create_registered_restore_database(scenario)
        activate_restore_database(scenario)
        install_source_schema(scenario)
        verify_privilege_sql_rejects_foreign_acl(scenario)
        open_authority_connections(scenario)
        verify_runtime_business_acl(scenario)
        verify_runtime_financial_facts(scenario)
        verify_future_objects_are_narrow(scenario)
        retire_migrator(scenario)
    finally:
        _cleanup_scenario(scenario)


def test_pg17_transaction_timeout_must_be_armed_before_begin_and_rolls_back() -> None:
    table = f"c07_timeout_probe_{uuid4().hex[:16]}"
    test_database = make_url(ADMIN_TEST_DATABASE_URL).database
    assert test_database is not None
    admin_url = _conninfo(database=test_database)
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        server_version = int(admin.execute("SHOW server_version_num").fetchone()[0])
        assert server_version >= 170000
        admin.execute(
            sql.SQL("CREATE TABLE {} (probe integer PRIMARY KEY)").format(
                sql.Identifier(table)
            )
        )

        old_design = psycopg.connect(admin_url, autocommit=True)
        try:
            old_design.execute("SET statement_timeout = 0")
            old_design.execute("SET idle_in_transaction_session_timeout = 0")
            old_design.execute("SET transaction_timeout = '5s'")
            old_design.execute("BEGIN")
            old_design.execute("SET transaction_timeout = '1s'")
            started = time.monotonic()
            old_design.execute("SELECT pg_sleep(1.25)")
            assert time.monotonic() - started >= 1.0
            old_design.execute("ROLLBACK")
        finally:
            _close(old_design)

        prearmed = psycopg.connect(admin_url, autocommit=True)
        try:
            prearmed.execute("SET statement_timeout = 0")
            prearmed.execute("SET idle_in_transaction_session_timeout = 0")
            prearmed.execute("SET transaction_timeout = '1s'")
            prearmed.execute("BEGIN")
            prearmed.execute(
                sql.SQL("INSERT INTO {} (probe) VALUES (1)").format(
                    sql.Identifier(table)
                )
            )
            started = time.monotonic()
            with pytest.raises(psycopg.errors.TransactionTimeout) as exc_info:
                prearmed.execute("SELECT pg_sleep(5)")
            assert exc_info.value.sqlstate == "25P04"
            elapsed = time.monotonic() - started
            assert 0.65 <= elapsed < 4.0
        finally:
            _close(prearmed)

        persisted = admin.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()[0]
        assert persisted == 0
    finally:
        with suppress(Exception):
            admin.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table))
            )
        admin.close()
