#Requires -Version 5.1

function New-TicketboxPostgresqlWriterFenceVersionGuardSql {
    return @"
    IF current_setting('server_version_num')::integer < 170000 THEN
        RAISE EXCEPTION 'PostgreSQL writer fence requires PostgreSQL 17 or newer';
    END IF;
"@
}

function New-TicketboxPostgresqlWriterFenceInheritedConnectGuardSql {
    param([Parameter(Mandatory = $true)][string]$ManagedRolesSql)

    return @"
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        CROSS JOIN pg_roles AS inherited_role
        WHERE role.rolname = ANY($ManagedRolesSql)
          AND inherited_role.oid <> role.oid
          AND pg_has_role(role.oid, inherited_role.oid, 'USAGE')
          AND EXISTS (
              SELECT 1
              FROM pg_database AS database_record
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(
                      database_record.datacl,
                      acldefault('d', database_record.datdba)
                  )
              ) AS privilege
              WHERE database_record.datname = current_database()
                AND privilege.grantee = inherited_role.oid
                AND privilege.privilege_type = 'CONNECT'
          )
    ) THEN
        RAISE EXCEPTION 'Managed writer role has inherited CONNECT';
    END IF;
"@
}

function New-TicketboxPostgresqlWriterFencePredefinedCapabilityGuardSql {
    param(
        [Parameter(Mandatory = $true)][string]$AuthorityRoleSql,
        [Parameter(Mandatory = $true)][string]$AllowedOwnerTransitionRolesSql
    )

    return @"
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        CROSS JOIN pg_roles AS predefined
        WHERE role.rolname !~ '^pg_'
          AND role.rolname <> $AuthorityRoleSql
          AND predefined.rolname ~ '^pg_'
          AND (
              pg_has_role(role.oid, predefined.oid, 'USAGE')
              OR pg_has_role(role.oid, predefined.oid, 'SET')
          )
          AND NOT (
              predefined.rolname = 'pg_database_owner'
              AND (
                  role.oid = (
                      SELECT datdba FROM pg_database
                      WHERE datname = current_database()
                  )
                  OR (
                      role.rolname = ANY($AllowedOwnerTransitionRolesSql)
                      AND NOT pg_has_role(
                          role.oid,
                          predefined.oid,
                          'USAGE'
                      )
                      AND pg_has_role(
                          role.oid,
                          (
                              SELECT datdba FROM pg_database
                              WHERE datname = current_database()
                          ),
                          'SET'
                      )
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION 'Predefined PostgreSQL role capability blocks writer fence';
    END IF;
"@
}

function New-TicketboxPostgresqlWriterFenceSecurityDefinerGuardSql {
    param(
        [Parameter(Mandatory = $true)][string]$AuthorityRoleSql,
        [Parameter(Mandatory = $true)][string]$ManagedSchemaSql,
        [Parameter(Mandatory = $true)][string]$AllowedOwnerRolesSql
    )

    return @"
    IF EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        JOIN pg_roles AS owner_role ON owner_role.oid = routine.proowner
        WHERE namespace.nspname = $ManagedSchemaSql
          AND routine.prosecdef
          AND owner_role.rolname <> ALL($AllowedOwnerRolesSql)
    ) THEN
        RAISE EXCEPTION
            'SECURITY DEFINER routine owner is outside the allowed authority policy';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        JOIN pg_proc AS routine ON routine.proowner <> role.oid
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = $ManagedSchemaSql
          AND routine.prosecdef
          AND role.rolname <> $AuthorityRoleSql
          AND has_function_privilege(role.oid, routine.oid, 'EXECUTE')
    ) THEN
        RAISE EXCEPTION
            'Non-authority role can execute an unowned SECURITY DEFINER routine';
    END IF;
"@
}

function New-TicketboxPostgresqlWriterFenceUnregisteredWriterGuardSql {
    param(
        [Parameter(Mandatory = $true)][string]$AuthorizedRolesSql,
        [Parameter(Mandatory = $true)][string]$ManagedSchemaSql
    )

    return @"
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname !~ '^pg_'
          AND role.rolname <> ALL($AuthorizedRolesSql)
          AND (
              role.rolcanlogin OR role.rolsuper OR role.rolcreatedb
              OR role.rolcreaterole OR role.rolreplication OR role.rolbypassrls
              OR role.oid = (
                  SELECT datdba FROM pg_database
                  WHERE datname = current_database()
              )
              OR EXISTS (
                  SELECT 1 FROM pg_namespace AS namespace
                  WHERE namespace.nspname = $ManagedSchemaSql
                    AND namespace.nspowner = role.oid
              )
              OR EXISTS (
                  SELECT 1 FROM pg_class AS relation
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = $ManagedSchemaSql
                    AND relation.relkind IN ('r', 'p', 'f', 'S')
                    AND relation.relowner = role.oid
              )
              OR has_database_privilege(role.oid, current_database(), 'CREATE')
              OR has_schema_privilege(role.oid, $ManagedSchemaSql, 'CREATE')
              OR EXISTS (
                  SELECT 1 FROM pg_class AS relation
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = $ManagedSchemaSql
                    AND relation.relkind IN ('r', 'p', 'f')
                    AND (
                        has_table_privilege(role.oid, relation.oid, 'INSERT')
                        OR has_table_privilege(role.oid, relation.oid, 'UPDATE')
                        OR has_table_privilege(role.oid, relation.oid, 'DELETE')
                        OR has_table_privilege(role.oid, relation.oid, 'TRUNCATE')
                        OR has_table_privilege(role.oid, relation.oid, 'REFERENCES')
                        OR has_table_privilege(role.oid, relation.oid, 'TRIGGER')
                    )
              )
              OR EXISTS (
                  SELECT 1 FROM pg_class AS relation
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = $ManagedSchemaSql
                    AND relation.relkind = 'S'
                    AND (
                        has_sequence_privilege(role.oid, relation.oid, 'USAGE')
                        OR has_sequence_privilege(role.oid, relation.oid, 'UPDATE')
                    )
              )
              OR EXISTS (
                  SELECT 1 FROM pg_proc AS routine
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = routine.pronamespace
                  WHERE namespace.nspname = $ManagedSchemaSql
                    AND routine.prosecdef
                    AND (
                        routine.proowner = role.oid
                        OR (
                            routine.proowner <> role.oid
                            AND has_function_privilege(
                                role.oid, routine.oid, 'EXECUTE'
                            )
                        )
                    )
              )
          )
    ) THEN
        RAISE EXCEPTION 'Unregistered effective writer or owner role exists';
    END IF;
"@
}
