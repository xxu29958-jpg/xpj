from __future__ import annotations

import os

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok, sealed_postgres_env
from ticketbox_lifecycle.runtime.postgres_connection import run_psql
from ticketbox_lifecycle.runtime.windows_security_native import (
    reject_reparse_components,
)
from ticketbox_lifecycle.runtime.windows_services import scm_query_state
from ticketbox_lifecycle.schemas import InstallRequest


def require_running_ticketbox_cluster(
    runner: CommandRunner,
    request: InstallRequest,
) -> None:
    if scm_query_state(runner, request.pg_service_name) != "RUNNING":
        raise LifecycleError(
            "postgres_service_not_running",
            "Ticketbox PostgreSQL service is not RUNNING",
        )
    require_ok(
        runner.run(
            [
                str(layout.tool(request, "pg_isready.exe")),
                "-h",
                "127.0.0.1",
                "-p",
                str(request.pg_port),
                "-d",
                "postgres",
            ],
            env=sealed_postgres_env(),
        ),
        code="postgres_not_ready",
    )
    online = require_ok(
        run_psql(
            runner,
            request,
            (
                "SELECT system_identifier::text || '|' || "
                "current_setting('data_checksums') || '|' || "
                "current_setting('data_directory') FROM pg_control_system()"
            ),
            database="postgres",
        ),
        code="postgres_identity_probe_failed",
    ).stdout.strip()
    parts = online.split("|")
    if len(parts) != 3 or not parts[0].isdigit():
        raise LifecycleError(
            "postgres_identity_probe_failed",
            "PostgreSQL system identifier probe returned an invalid result",
        )
    expected_data = os.path.normcase(os.path.abspath(layout.pgdata(request)))
    observed_data = os.path.normcase(os.path.abspath(parts[2]))
    if observed_data != expected_data:
        raise LifecycleError(
            "postgres_cluster_mismatch",
            "running PostgreSQL data directory does not match Ticketbox pgdata",
        )
    if parts[1] != "on":
        raise LifecycleError(
            "postgres_checksums_disabled",
            "running Ticketbox PostgreSQL cluster does not have data checksums enabled",
        )


def read_system_identifier(runner: CommandRunner, request: InstallRequest) -> str:
    reject_reparse_components(layout.pgdata(request))
    control = layout.tool(request, "pg_controldata.exe")
    if not control.is_file():
        raise LifecycleError(
            "missing_platform_binary",
            "postgresql/bin/pg_controldata.exe is not installed",
        )
    env = sealed_postgres_env()
    env["LC_ALL"] = "C"
    completed = require_ok(
        runner.run(
            [str(control), "-D", str(layout.pgdata(request))],
            env=env,
            timeout_s=30,
        ),
        code="pg_controldata_failed",
    )
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "Database system identifier":
            identifier = value.strip()
            if identifier.isdigit():
                return identifier
    raise LifecycleError(
        "pg_controldata_failed",
        "pg_controldata returned no valid database system identifier",
    )
