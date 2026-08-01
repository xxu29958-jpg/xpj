"""Live identity, principal, and writer-fence checks before C07 DDL."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.database._c07_production_connection import _database_binding_sha256
from app.database._c07_production_contract import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
    C07ProductionMigrationError,
    ProductionMigrationContext,
    ValidatedProductionArtifacts,
)


def _assert_connected_database(
    connection: Any,
    *,
    context: ProductionMigrationContext,
    generation: ValidatedProductionArtifacts,
) -> None:
    row = connection.execute(
        text(
            "SELECT control.system_identifier::text, "
            "database.oid::text, current_database(), "
            "(SELECT value FROM public.app_meta WHERE key = 'server_id'), "
            "(SELECT value FROM public.app_meta WHERE key = 'data_generation') "
            "FROM pg_control_system() AS control "
            "JOIN pg_database AS database ON database.datname = current_database()"
        )
    ).one()
    actual = tuple(str(item) if item is not None else "" for item in row)
    expected = (
        generation.cluster_system_identifier,
        generation.database_oid,
        DATABASE_NAME,
        generation.logical_server_id,
        generation.logical_data_generation,
    )
    if actual != expected:
        raise C07ProductionMigrationError(
            "connected PostgreSQL identity does not match the recovery generation"
        )
    binding = _database_binding_sha256(
        installation_id=generation.installation_id,
        cluster_system_identifier=actual[0],
        database_oid=actual[1],
        logical_server_id=actual[3],
        logical_data_generation=actual[4],
    )
    if binding != context.database_binding_sha256:
        raise C07ProductionMigrationError(
            "connected PostgreSQL identity does not match the lifecycle binding"
        )


def _assert_migrator_principal(connection: Any) -> None:
    principal = connection.execute(
        text("SELECT session_user, current_user, current_database()")
    ).one()
    if tuple(str(value) for value in principal) != (
        MIGRATOR_ROLE,
        MIGRATOR_ROLE,
        DATABASE_NAME,
    ):
        raise C07ProductionMigrationError(
            "production connection did not authenticate as the migrator"
        )


def _require_zero(value: object, message: str) -> None:
    if int(value or 0) != 0:
        raise C07ProductionMigrationError(message)


def _assert_no_client_or_role_writers(connection: Any) -> None:
    other_clients = connection.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
            "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
        )
    )
    _require_zero(other_clients, "C07 production DDL observed another client backend")
    public_connect = connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_database AS d "
            "CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) AS acl "
            "WHERE d.datname = current_database() AND acl.grantee = 0 "
            "AND acl.privilege_type = 'CONNECT')"
        )
    )
    _require_zero(public_connect, "C07 production DDL observed PUBLIC CONNECT")
    unfenced_login = connection.scalar(
        text(
            "SELECT count(*) FROM pg_roles WHERE rolname !~ '^pg_' "
            "AND rolname NOT IN ('postgres', :migrator) AND rolcanlogin"
        ),
        {"migrator": MIGRATOR_ROLE},
    )
    _require_zero(
        unfenced_login,
        "C07 production DDL observed an unfenced login role",
    )
    external_elevated = connection.scalar(
        text(
            "SELECT count(*) FROM pg_roles WHERE rolname <> 'postgres' "
            "AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)"
        )
    )
    _require_zero(
        external_elevated,
        "C07 production DDL observed external elevated authority",
    )


def _assert_no_deferred_writers(connection: Any) -> None:
    values = (
        connection.scalar(
            text("SELECT current_setting('max_prepared_transactions')::bigint")
        ),
        connection.scalar(
            text(
                "SELECT count(*) FROM pg_prepared_xacts "
                "WHERE database = current_database()"
            )
        ),
        connection.scalar(
            text(
                "SELECT count(*) FROM pg_subscription "
                "WHERE subdbid = (SELECT oid FROM pg_database "
                "WHERE datname = current_database())"
            )
        ),
        connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datid = (SELECT oid FROM pg_database "
                "WHERE datname = current_database()) AND pid <> pg_backend_pid() "
                "AND backend_type NOT IN "
                "('client backend', 'autovacuum worker', 'parallel worker')"
            )
        ),
    )
    if any(int(value or 0) != 0 for value in values):
        raise C07ProductionMigrationError(
            "C07 production DDL observed prepared/logical/background writer"
        )


def _assert_production_writer_fence(connection: Any) -> None:
    """Re-observe the live database fence immediately before any C07 DDL."""

    connection.execute(text("SELECT pg_stat_clear_snapshot()"))
    _assert_no_client_or_role_writers(connection)
    _assert_no_deferred_writers(connection)


def _assume_schema_owner(connection: Any) -> None:
    connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
    effective = connection.execute(
        text("SELECT session_user, current_user")
    ).one()
    if tuple(str(value) for value in effective) != (
        MIGRATOR_ROLE,
        SCHEMA_OWNER_ROLE,
    ):
        raise C07ProductionMigrationError(
            "migrator could not assume the schema owner role"
        )
