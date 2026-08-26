"""One live observation for installed runtime and dataset authority."""

from sqlalchemy import text

from app.database._managed_postgres_contract import (
    MIGRATOR_ROLE,
    RUNTIME_ROLE,
    SCHEMA_OWNER_ROLE,
)

RUNTIME_AUTHORITY_FIELDS = (
    "session_user",
    "current_user",
    "current_database",
    "runtime_role_ready",
    "runtime_role_isolated",
    "runtime_database_ready",
    "runtime_schema_ready",
    "runtime_tables_ready",
    "runtime_sequences_ready",
    "dataset_id",
    "client_generation",
    "restore_epoch",
    "schema_revision",
    "schema_min_compatible",
    "semantic_revision",
    "restored_from_backup_id",
)

RUNTIME_AUTHORITY_QUERY = text(
    f"""
    WITH runtime_role AS (
        SELECT oid, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
               rolcreaterole, rolreplication, rolbypassrls
        FROM pg_catalog.pg_roles
        WHERE rolname = '{RUNTIME_ROLE}'
    )
    SELECT
        session_user AS session_user,
        current_user AS current_user,
        current_database() AS current_database,
        COALESCE((
            SELECT rolcanlogin AND NOT rolinherit AND NOT rolsuper
                   AND NOT rolcreatedb AND NOT rolcreaterole
                   AND NOT rolreplication AND NOT rolbypassrls
            FROM runtime_role
        ), FALSE) AS runtime_role_ready,
        (
            NOT pg_has_role(session_user, '{SCHEMA_OWNER_ROLE}', 'SET')
            AND NOT pg_has_role(session_user, '{MIGRATOR_ROLE}', 'SET')
        ) AS runtime_role_isolated,
        (
            has_database_privilege(session_user, current_database(), 'CONNECT')
            AND NOT has_database_privilege(session_user, current_database(), 'CREATE')
            AND NOT has_database_privilege(session_user, current_database(), 'TEMPORARY')
        ) AS runtime_database_ready,
        (
            has_schema_privilege(session_user, 'public', 'USAGE')
            AND NOT has_schema_privilege(session_user, 'public', 'CREATE')
        ) AS runtime_schema_ready,
        (
            SELECT COALESCE(bool_and(
                relation.relowner <> runtime_role.oid
                AND has_table_privilege(session_user, relation.oid, 'SELECT')
                AND has_table_privilege(session_user, relation.oid, 'INSERT')
                AND has_table_privilege(session_user, relation.oid, 'UPDATE')
                AND has_table_privilege(session_user, relation.oid, 'DELETE')
                AND NOT has_table_privilege(session_user, relation.oid, 'TRUNCATE')
                AND NOT has_table_privilege(session_user, relation.oid, 'REFERENCES')
                AND NOT has_table_privilege(session_user, relation.oid, 'TRIGGER')
                AND NOT has_table_privilege(session_user, relation.oid, 'MAINTAIN')
            ), FALSE)
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN runtime_role
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
        ) AS runtime_tables_ready,
        (
            SELECT COALESCE(bool_and(
                relation.relowner <> runtime_role.oid
                AND has_sequence_privilege(session_user, relation.oid, 'USAGE')
                AND has_sequence_privilege(session_user, relation.oid, 'SELECT')
                AND NOT has_sequence_privilege(session_user, relation.oid, 'UPDATE')
            ), TRUE)
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN runtime_role
            WHERE namespace.nspname = 'public'
              AND relation.relkind = 'S'
        ) AS runtime_sequences_ready,
        dataset_id, client_generation, restore_epoch, schema_revision,
        schema_min_compatible, semantic_revision, restored_from_backup_id
    FROM public.dataset_authority
    WHERE singleton_id = 1
    """
)

__all__ = ["RUNTIME_AUTHORITY_FIELDS", "RUNTIME_AUTHORITY_QUERY"]
