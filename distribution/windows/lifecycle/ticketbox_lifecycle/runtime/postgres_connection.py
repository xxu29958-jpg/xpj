from __future__ import annotations

from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, MIGRATOR_ROLE
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    CompletedCommand,
    sealed_pg_env,
)
from ticketbox_lifecycle.schemas import InstallRequest


def maintenance_database_url(request: InstallRequest) -> str:
    return (
        f"postgresql+psycopg://{MIGRATOR_ROLE}@127.0.0.1:{request.pg_port}/{DATABASE_NAME}"
        "?require_auth=scram-sha-256"
    )


def run_psql(
    runner: CommandRunner,
    request: InstallRequest,
    sql: str,
    *,
    database: str,
    user: str = "postgres",
) -> CompletedCommand:
    return runner.run(
        [
            str(layout.tool(request, "psql.exe")),
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            "127.0.0.1",
            "-p",
            str(request.pg_port),
            "-U",
            user,
            "-d",
            database,
            "-tA",
            "-f",
            "-",
        ],
        env=sealed_pg_env(str(layout.pg_passfile(request))),
        input_text=sql,
    )
