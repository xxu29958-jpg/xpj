from __future__ import annotations

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok, sealed_pg_env
from ticketbox_lifecycle.runtime.postgres_connection import run_psql
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
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
            env=sealed_pg_env(str(layout.pg_passfile(request))),
        ),
        code="postgres_not_ready",
    )
    offline_id = read_system_identifier(runner, request)
    online = require_ok(
        run_psql(
            runner,
            request,
            (
                "SELECT system_identifier::text || '|' || "
                "current_setting('data_checksums') FROM pg_control_system()"
            ),
            database="postgres",
        ),
        code="postgres_identity_probe_failed",
    ).stdout.strip()
    parts = online.split("|")
    if len(parts) != 2 or not parts[0].isdigit():
        raise LifecycleError(
            "postgres_identity_probe_failed",
            "PostgreSQL system identifier probe returned an invalid result",
        )
    if parts[0] != offline_id:
        raise LifecycleError(
            "postgres_cluster_mismatch",
            "running PostgreSQL system identifier does not match Ticketbox pgdata",
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
    env = sealed_pg_env(str(layout.pg_passfile(request)))
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
