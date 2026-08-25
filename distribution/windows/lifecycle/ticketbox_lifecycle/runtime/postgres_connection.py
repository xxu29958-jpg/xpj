from __future__ import annotations

from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, MIGRATOR_ROLE
from ticketbox_lifecycle.schemas import InstallRequest


def maintenance_database_url(request: InstallRequest) -> str:
    return (
        f"postgresql+psycopg://{MIGRATOR_ROLE}@127.0.0.1:{request.pg_port}/{DATABASE_NAME}"
        "?require_auth=scram-sha-256"
    )
