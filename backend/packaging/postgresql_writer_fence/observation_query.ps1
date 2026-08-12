#Requires -Version 5.1

function New-TicketboxPostgresqlWriterFenceObservationSql {
    param(
        [Parameter(Mandatory = $true)][string]$ManagedSchemaName,
        [Parameter(Mandatory = $true)][string]$AdvisoryLockLabel,
        [Parameter(Mandatory = $true)][string]$ApplicationName,
        [ValidateRange(1, 3600000)][int]$StatementTimeoutMilliseconds,
        [ValidateRange(1, 3600000)][int]$LockTimeoutMilliseconds
    )

    Assert-TicketboxPostgresqlWriterFenceIdentifier `
        $ManagedSchemaName `
        "managed schema"
    $schema = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $ManagedSchemaName
    $lease = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $AdvisoryLockLabel
    $application = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $ApplicationName
    $relationWriteAuthority =
        New-TicketboxPostgresqlWriterFenceRelationWriteAuthoritySql `
            -RoleOidSql "role.oid"
    $executableRelationScope =
        New-TicketboxPostgresqlWriterFenceExecutableRelationScopeSql `
            -ManagedSchemaSql $schema `
            -RoleOidSql "role.oid"
    $userNamespace =
        New-TicketboxPostgresqlWriterFenceUserNamespacePredicateSql `
            -NamespaceAlias "namespace"
    return @"
SET application_name = $application;
SET statement_timeout = '$($StatementTimeoutMilliseconds)ms';
SET lock_timeout = '$($LockTimeoutMilliseconds)ms';
SELECT pg_stat_clear_snapshot();
WITH database_record AS (
    SELECT oid, datacl, datdba
    FROM pg_database
    WHERE datname = current_database()
),
advisory_acquire AS MATERIALIZED (
    SELECT pg_try_advisory_lock(
        hashtext(current_database()),
        hashtext($lease)
    ) AS held
),
user_roles AS MATERIALIZED (
    SELECT
        role.oid,
        role.rolname,
        role.rolcanlogin,
        role.rolconnlimit,
        role.rolsuper,
        role.rolcreatedb,
        role.rolcreaterole,
        role.rolreplication,
        role.rolbypassrls,
        role.oid = database_record.datdba AS is_database_owner,
        EXISTS (
            SELECT 1 FROM pg_namespace AS namespace
            WHERE namespace.nspname = $schema
              AND namespace.nspowner = role.oid
        ) AS owns_managed_schema,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = $schema
              AND relation.relkind IN ('r', 'p', 'f', 'S', 'v')
              AND relation.relowner = role.oid
        ) AS owns_managed_relations,
        EXISTS (
            SELECT 1
            FROM pg_proc AS routine
            JOIN pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            WHERE $userNamespace
              AND routine.prosecdef
              AND routine.proowner = role.oid
        ) AS owns_security_definer_routines,
        EXISTS (
            SELECT 1
            FROM pg_proc AS routine
            JOIN pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            WHERE $userNamespace
              AND routine.prosecdef
              AND routine.proowner <> role.oid
              AND has_schema_privilege(role.oid, namespace.oid, 'USAGE')
              AND has_function_privilege(role.oid, routine.oid, 'EXECUTE')
        ) AS can_execute_unowned_security_definer_routines,
        EXISTS (
            SELECT 1
            FROM aclexplode(
                COALESCE(
                    database_record.datacl,
                    acldefault('d', database_record.datdba)
                )
            ) AS privilege
            WHERE privilege.grantee = role.oid
              AND privilege.privilege_type = 'CONNECT'
        ) AS direct_connect,
        has_database_privilege(
            role.oid, database_record.oid, 'CONNECT'
        ) AS effective_connect,
        has_database_privilege(
            role.oid, database_record.oid, 'CREATE'
        ) AS can_database_create,
        has_schema_privilege(
            role.oid, $schema, 'CREATE'
        ) AS can_managed_schema_create,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE ($executableRelationScope)
              AND ($relationWriteAuthority)
        ) AS can_table_write,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = $schema
              AND relation.relkind = 'S'
              AND (
                  has_sequence_privilege(role.oid, relation.oid, 'USAGE')
                  OR has_sequence_privilege(role.oid, relation.oid, 'UPDATE')
              )
        ) AS can_sequence_write,
        EXISTS (
            SELECT 1
            FROM (
                SELECT database_record.datdba AS owner_oid
                UNION
                SELECT namespace.nspowner
                FROM pg_namespace AS namespace
                WHERE namespace.nspname = $schema
                UNION
                SELECT relation.relowner
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = $schema
                  AND relation.relkind IN ('r', 'p', 'f', 'S', 'v')
                UNION
                SELECT routine.proowner
                FROM pg_proc AS routine
                JOIN pg_namespace AS namespace
                  ON namespace.oid = routine.pronamespace
                WHERE $userNamespace
                  AND routine.prosecdef
            ) AS write_owner
            WHERE write_owner.owner_oid <> role.oid
              AND pg_has_role(role.oid, write_owner.owner_oid, 'SET')
        ) AS can_assume_write_owner,
        COALESCE(
            (
                SELECT json_agg(predefined.rolname ORDER BY predefined.rolname)
                FROM pg_roles AS predefined
                WHERE predefined.rolname ~ '^pg_'
                  AND pg_has_role(role.oid, predefined.oid, 'USAGE')
            ),
            '[]'::json
        ) AS predefined_role_usage,
        COALESCE(
            (
                SELECT json_agg(predefined.rolname ORDER BY predefined.rolname)
                FROM pg_roles AS predefined
                WHERE predefined.rolname ~ '^pg_'
                  AND pg_has_role(role.oid, predefined.oid, 'SET')
            ),
            '[]'::json
        ) AS predefined_role_set
    FROM pg_roles AS role
    CROSS JOIN database_record
    CROSS JOIN advisory_acquire
    WHERE role.rolname !~ '^pg_'
      AND advisory_acquire.held
),
public_privilege AS MATERIALIZED (
    SELECT EXISTS (
        SELECT 1
        FROM database_record
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                database_record.datacl,
                acldefault('d', database_record.datdba)
            )
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type = 'CONNECT'
    ) AS direct_connect
    FROM advisory_acquire
    WHERE advisory_acquire.held
),
session_observation AS MATERIALIZED (
    SELECT
        count(*) AS session_count,
        COALESCE(
            json_agg(
                json_build_object(
                    'pid', pid,
                    'role', usename,
                    'application_name', application_name,
                    'state', state
                ) ORDER BY pid
            ),
            '[]'::json
        ) AS sessions
    FROM pg_stat_activity
    CROSS JOIN advisory_acquire
    WHERE datid = (SELECT oid FROM database_record)
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      AND advisory_acquire.held
),
writer_catalog_observation AS MATERIALIZED (
    SELECT
        current_setting('max_prepared_transactions')::bigint
            AS max_prepared_transactions,
        (
            SELECT count(*) FROM pg_prepared_xacts
            WHERE database = current_database()
        ) AS prepared_transaction_count,
        (
            SELECT count(*) FROM pg_subscription
            WHERE subdbid = (SELECT oid FROM database_record)
        ) AS logical_subscription_count,
        (
            SELECT count(*) FROM pg_stat_activity
            WHERE datid = (SELECT oid FROM database_record)
              AND pid <> pg_backend_pid()
              AND backend_type = 'logical replication worker'
        ) AS logical_apply_worker_count,
        (
            SELECT count(*) FROM pg_stat_activity
            WHERE datid = (SELECT oid FROM database_record)
              AND pid <> pg_backend_pid()
              AND backend_type NOT IN (
                  'client backend', 'autovacuum worker', 'parallel worker'
              )
        ) AS unexpected_database_worker_count
    FROM advisory_acquire
    WHERE advisory_acquire.held
),
advisory_release AS MATERIALIZED (
    SELECT CASE
        WHEN held
          AND (SELECT count(*) FROM user_roles) >= 0
          AND (SELECT count(*) FROM public_privilege) = 1
          AND (SELECT session_count FROM session_observation) >= 0
          AND (SELECT count(*) FROM writer_catalog_observation) = 1
        THEN pg_advisory_unlock(
            hashtext(current_database()),
            hashtext($lease)
        )
        ELSE false
    END AS released
    FROM advisory_acquire
)
SELECT json_build_object(
    'public_connect', (SELECT direct_connect FROM public_privilege),
    'client_session_count', (SELECT session_count FROM session_observation),
    'client_sessions', (SELECT sessions FROM session_observation),
    'max_prepared_transactions', (
        SELECT max_prepared_transactions FROM writer_catalog_observation
    ),
    'prepared_transaction_count', (
        SELECT prepared_transaction_count FROM writer_catalog_observation
    ),
    'logical_subscription_count', (
        SELECT logical_subscription_count FROM writer_catalog_observation
    ),
    'logical_apply_worker_count', (
        SELECT logical_apply_worker_count FROM writer_catalog_observation
    ),
    'unexpected_database_worker_count', (
        SELECT unexpected_database_worker_count
        FROM writer_catalog_observation
    ),
    'advisory_available', (SELECT held FROM advisory_acquire),
    'advisory_released', (SELECT released FROM advisory_release),
    'roles', COALESCE(
        (
            SELECT json_agg(
                json_build_object(
                    'name', rolname,
                    'oid', oid::bigint,
                    'can_login', rolcanlogin,
                    'connection_limit', rolconnlimit,
                    'is_superuser', rolsuper,
                    'can_create_db', rolcreatedb,
                    'can_create_role', rolcreaterole,
                    'can_replicate', rolreplication,
                    'can_bypass_rls', rolbypassrls,
                    'is_database_owner', is_database_owner,
                    'owns_managed_schema', owns_managed_schema,
                    'owns_managed_relations', owns_managed_relations,
                    'owns_security_definer_routines',
                        owns_security_definer_routines,
                    'can_execute_unowned_security_definer_routines',
                        can_execute_unowned_security_definer_routines,
                    'direct_connect', direct_connect,
                    'effective_connect', effective_connect,
                    'can_database_create', can_database_create,
                    'can_managed_schema_create', can_managed_schema_create,
                    'can_table_write', can_table_write,
                    'can_sequence_write', can_sequence_write,
                    'can_assume_write_owner', can_assume_write_owner,
                    'predefined_role_usage', predefined_role_usage,
                    'predefined_role_set', predefined_role_set
                ) ORDER BY rolname
            ) FROM user_roles
        ),
        '[]'::json
    )
);
"@
}
