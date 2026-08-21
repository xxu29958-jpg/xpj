#Requires -Version 5.1

function ConvertTo-TicketboxDatabaseAclValuesSql {
    param([Parameter(Mandatory = $true)][object[]]$Specifications)

    $rows = @(
        foreach ($specification in $Specifications) {
            $privileges = @(
                foreach ($privilege in @($specification.Privileges)) {
                    ConvertTo-TicketboxPostgresqlSqlLiteral ([string]$privilege)
                }
            )
            "(" +
                (ConvertTo-TicketboxPostgresqlSqlLiteral ([string]$specification.Table)) +
                ", ARRAY[" + ($privileges -join ", ") + "]::text[])"
        }
    )
    return $rows -join ",`n        "
}

function New-TicketboxDatabaseAclObjectSql {
    param(
        [Parameter(Mandatory = $true)][object]$Policy,
        [Parameter(Mandatory = $true)][object[]]$Specifications,
        [Parameter(Mandatory = $true)][string[]]$SequenceConsumerTables
    )

    $valuesSql = ConvertTo-TicketboxDatabaseAclValuesSql $Specifications
    $sequenceConsumers = ConvertTo-TicketboxPostgresqlSqlTextArray `
        $SequenceConsumerTables
    return @"
DO `$ticketbox_acl`$
DECLARE
    object_record record;
    specification record;
    owner_name text;
    privilege_sql text;
    sequence_consumer_tables text[] := $sequenceConsumers;
BEGIN
    FOR object_record IN
        SELECT relation.oid, relation.relkind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    LOOP
        IF object_record.relkind = 'S' THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM PUBLIC, %I, %I, %I',
                object_record.oid::regclass,
                '$($Policy.RuntimeRole)',
                '$($Policy.MigratorRole)',
                '$($Policy.BackupRole)'
            );
            EXECUTE format(
                'GRANT SELECT ON SEQUENCE %s TO %I',
                object_record.oid::regclass,
                '$($Policy.BackupRole)'
            );
        ELSE
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON TABLE %s FROM PUBLIC, %I, %I, %I',
                object_record.oid::regclass,
                '$($Policy.RuntimeRole)',
                '$($Policy.MigratorRole)',
                '$($Policy.BackupRole)'
            );
            EXECUTE format(
                'GRANT SELECT ON TABLE %s TO %I',
                object_record.oid::regclass,
                '$($Policy.BackupRole)'
            );
        END IF;
    END LOOP;

    FOR specification IN
        SELECT table_name, privileges
        FROM (VALUES
            $valuesSql
        ) AS expected(table_name, privileges)
    LOOP
        SELECT pg_get_userbyid(relation.relowner)
        INTO owner_name
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = specification.table_name
          AND relation.relkind IN ('r', 'p');
        IF NOT FOUND THEN
            CONTINUE;
        END IF;
        IF owner_name <> '$($Policy.OwnerRole)' THEN
            RAISE EXCEPTION 'Ticketbox allowlisted table % has wrong owner %',
                specification.table_name, owner_name;
        END IF;
        privilege_sql := array_to_string(specification.privileges, ', ');
        EXECUTE format(
            'GRANT %s ON TABLE public.%I TO %I',
            privilege_sql,
            specification.table_name,
            '$($Policy.RuntimeRole)'
        );
    END LOOP;

    FOR object_record IN
        SELECT DISTINCT sequence.oid
        FROM pg_class AS sequence
        JOIN pg_depend AS dependency
          ON dependency.objid = sequence.oid
         AND dependency.classid = 'pg_class'::regclass
         AND dependency.refclassid = 'pg_class'::regclass
         AND dependency.deptype IN ('a', 'i')
        JOIN pg_class AS owner_table ON owner_table.oid = dependency.refobjid
        JOIN pg_namespace AS namespace ON namespace.oid = owner_table.relnamespace
        WHERE namespace.nspname = 'public'
          AND sequence.relkind = 'S'
          AND owner_table.relname = ANY(sequence_consumer_tables)
    LOOP
        EXECUTE format(
            'GRANT USAGE, SELECT ON SEQUENCE %s TO %I',
            object_record.oid::regclass,
            '$($Policy.RuntimeRole)'
        );
    END LOOP;
END
`$ticketbox_acl`$;
"@
}

function New-TicketboxDatabaseDefaultPrivilegeSql {
    param([Parameter(Mandatory = $true)][object]$Policy)

    return @"
DO `$ticketbox_defaults`$
DECLARE creator_role text;
BEGIN
    FOREACH creator_role IN ARRAY ARRAY[
        'postgres', '$($Policy.OwnerRole)', '$($Policy.MigratorRole)',
        '$($Policy.RuntimeRole)', '$($Policy.BackupRole)', '$($Policy.RetiredLegacyRole)'
    ] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = creator_role) THEN
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON TABLES FROM PUBLIC, %I',
                creator_role, '$($Policy.RuntimeRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON TABLES FROM %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON SEQUENCES FROM PUBLIC, %I',
                creator_role, '$($Policy.RuntimeRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE ALL ON SEQUENCES FROM %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE EXECUTE ON ROUTINES FROM PUBLIC, %I',
                creator_role, '$($Policy.RuntimeRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE EXECUTE ON ROUTINES FROM %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, %I',
                creator_role, '$($Policy.RuntimeRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON TABLES FROM %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, %I',
                creator_role, '$($Policy.RuntimeRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE EXECUTE ON ROUTINES FROM PUBLIC, %I',
                creator_role, '$($Policy.RuntimeRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE EXECUTE ON ROUTINES FROM %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO %I',
                creator_role, '$($Policy.BackupRole)');
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON SEQUENCES TO %I',
                creator_role, '$($Policy.BackupRole)');
        END IF;
    END LOOP;
END
`$ticketbox_defaults`$;
"@
}

function New-TicketboxDatabaseForeignAclGuardSql {
    param([Parameter(Mandatory = $true)][object]$Policy)

    return @"
DO `$ticketbox_guard`$
DECLARE
    owner_oid oid := (SELECT oid FROM pg_roles WHERE rolname = '$($Policy.OwnerRole)');
    migrator_oid oid := (SELECT oid FROM pg_roles WHERE rolname = '$($Policy.MigratorRole)');
    runtime_oid oid := (SELECT oid FROM pg_roles WHERE rolname = '$($Policy.RuntimeRole)');
    backup_oid oid := (SELECT oid FROM pg_roles WHERE rolname = '$($Policy.BackupRole)');
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_database AS database,
             LATERAL aclexplode(COALESCE(database.datacl, acldefault('d', database.datdba))) AS acl
        WHERE database.datname = '$($Policy.DatabaseName)'
          AND (acl.grantee NOT IN (owner_oid, migrator_oid, runtime_oid, backup_oid)
               OR (acl.grantee IN (migrator_oid, runtime_oid, backup_oid)
                   AND acl.privilege_type <> 'CONNECT'))
    ) THEN RAISE EXCEPTION 'Ticketbox database has a foreign or excessive ACL grantee'; END IF;
    IF EXISTS (
        SELECT 1 FROM pg_namespace AS namespace,
             LATERAL aclexplode(COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))) AS acl
        WHERE namespace.nspname = 'public'
          AND (acl.grantee NOT IN (owner_oid, runtime_oid, backup_oid)
               OR (acl.grantee IN (runtime_oid, backup_oid) AND acl.privilege_type <> 'USAGE'))
    ) THEN RAISE EXCEPTION 'Ticketbox public schema has a foreign or excessive ACL grantee'; END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(
            relation.relacl,
            acldefault(CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END, relation.relowner)
        )) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND (acl.grantee NOT IN (owner_oid, runtime_oid, backup_oid)
               OR (acl.grantee = backup_oid AND acl.privilege_type <> 'SELECT'))
    ) THEN RAISE EXCEPTION 'Ticketbox public relation has a foreign ACL grantee'; END IF;
    IF EXISTS (
        SELECT 1 FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(routine.proacl, acldefault('f', routine.proowner))) AS acl
        WHERE namespace.nspname = 'public' AND acl.grantee <> owner_oid
    ) THEN RAISE EXCEPTION 'Ticketbox public routine has a foreign ACL grantee'; END IF;
    IF EXISTS (
        SELECT 1 FROM pg_default_acl AS defaults
        JOIN pg_roles AS creator ON creator.oid = defaults.defaclrole
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS acl
        WHERE creator.rolname IN (
            'postgres', '$($Policy.OwnerRole)', '$($Policy.MigratorRole)',
            '$($Policy.RuntimeRole)', '$($Policy.BackupRole)', '$($Policy.RetiredLegacyRole)')
          AND acl.grantee <> defaults.defaclrole
          AND NOT (
              acl.grantee = backup_oid AND acl.privilege_type = 'SELECT'
              AND defaults.defaclobjtype IN ('r', 'S')
          )
    ) THEN RAISE EXCEPTION 'Ticketbox creator default privileges retain a foreign grantee'; END IF;
END
`$ticketbox_guard`$;
"@
}

function New-TicketboxDatabaseRuntimeAclSql {
    param(
        [switch]$IncludeManagedSchemaCurrencyAuthority,
        [switch]$PreserveRuntimeFence
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $specifications = @(Get-TicketboxDatabaseRuntimePrivilegeSpecifications `
        -IncludeManagedSchemaCurrencyAuthority:$IncludeManagedSchemaCurrencyAuthority)
    $sequenceConsumers = @(Get-TicketboxDatabaseSequenceConsumerTables `
        -IncludeManagedSchemaCurrencyAuthority:$IncludeManagedSchemaCurrencyAuthority)
    $connectSql = if ($PreserveRuntimeFence) {
        "GRANT CONNECT ON DATABASE `"$($policy.DatabaseName)`" TO `"$($policy.MigratorRole)`", `"$($policy.BackupRole)`";`n" +
        "ALTER ROLE `"$($policy.RuntimeRole)`" NOLOGIN CONNECTION LIMIT 0;"
    }
    else {
        "GRANT CONNECT ON DATABASE `"$($policy.DatabaseName)`" " +
            "TO `"$($policy.RuntimeRole)`", `"$($policy.MigratorRole)`", `"$($policy.BackupRole)`";"
    }
    $objectSql = New-TicketboxDatabaseAclObjectSql `
        -Policy $policy `
        -Specifications $specifications `
        -SequenceConsumerTables $sequenceConsumers
    $defaultSql = New-TicketboxDatabaseDefaultPrivilegeSql $policy
    $guardSql = New-TicketboxDatabaseForeignAclGuardSql $policy
    return @"
BEGIN;
ALTER DATABASE "$($policy.DatabaseName)" OWNER TO "$($policy.OwnerRole)";
REVOKE ALL ON DATABASE "$($policy.DatabaseName)" FROM PUBLIC;
REVOKE ALL ON DATABASE "$($policy.DatabaseName)" FROM "$($policy.RuntimeRole)";
REVOKE ALL ON DATABASE "$($policy.DatabaseName)" FROM "$($policy.MigratorRole)";
REVOKE ALL ON DATABASE "$($policy.DatabaseName)" FROM "$($policy.BackupRole)";
$connectSql
ALTER SCHEMA public OWNER TO "$($policy.OwnerRole)";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM "$($policy.RuntimeRole)";
REVOKE ALL ON SCHEMA public FROM "$($policy.MigratorRole)";
REVOKE ALL ON SCHEMA public FROM "$($policy.BackupRole)";
GRANT USAGE ON SCHEMA public TO "$($policy.RuntimeRole)", "$($policy.BackupRole)";
$objectSql
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM "$($policy.RuntimeRole)";
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM "$($policy.MigratorRole)";
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM "$($policy.BackupRole)";
REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system()
    FROM PUBLIC, "$($policy.MigratorRole)", "$($policy.RuntimeRole)", "$($policy.BackupRole)";
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system()
    TO "$($policy.OwnerRole)", "$($policy.RuntimeRole)";
$defaultSql
$guardSql
ALTER ROLE "$($policy.RuntimeRole)" RESET ALL;
ALTER ROLE "$($policy.MigratorRole)" RESET ALL;
ALTER ROLE "$($policy.BackupRole)" RESET ALL;
ALTER ROLE "$($policy.RuntimeRole)" IN DATABASE "$($policy.DatabaseName)" RESET ALL;
ALTER ROLE "$($policy.MigratorRole)" IN DATABASE "$($policy.DatabaseName)" RESET ALL;
ALTER ROLE "$($policy.BackupRole)" IN DATABASE "$($policy.DatabaseName)" RESET ALL;
ALTER ROLE "$($policy.RuntimeRole)" SET search_path = pg_catalog, public;
ALTER ROLE "$($policy.MigratorRole)" SET search_path = pg_catalog, public;
ALTER ROLE "$($policy.BackupRole)" SET search_path = pg_catalog, public;
COMMIT;
"@
}

function New-TicketboxDatabaseRuntimeAclObservationSql {
    param(
        [Parameter(Mandatory = $true)][object[]]$Specifications,
        [Parameter(Mandatory = $true)][string[]]$SequenceConsumerTables,
        [Parameter(Mandatory = $true)][object]$Policy,
        [switch]$PreserveRuntimeFence
    )

    $valuesSql = ConvertTo-TicketboxDatabaseAclValuesSql $Specifications
    $sequenceConsumers = ConvertTo-TicketboxPostgresqlSqlTextArray $SequenceConsumerTables
    $runtimeConnectPredicate = if ($PreserveRuntimeFence) {
        "NOT has_database_privilege('$($Policy.RuntimeRole)', current_database(), 'CONNECT')"
    }
    else { "has_database_privilege('$($Policy.RuntimeRole)', current_database(), 'CONNECT')" }
    return @"
WITH expected(table_name, expected_privileges) AS (
    VALUES $valuesSql
), relation AS (
    SELECT expected.table_name, expected.expected_privileges, catalog_relation.oid,
           pg_get_userbyid(catalog_relation.relowner) AS owner_name
    FROM expected
    LEFT JOIN pg_class AS catalog_relation
      ON catalog_relation.relname = expected.table_name
     AND catalog_relation.relnamespace = 'public'::regnamespace
     AND catalog_relation.relkind IN ('r', 'p')
), privilege_name(privilege) AS (
    VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
           ('TRUNCATE'), ('REFERENCES'), ('TRIGGER'), ('MAINTAIN')
), sequence_contract AS (
    SELECT sequence.oid, owner_table.relname = ANY($sequenceConsumers) AS is_consumer
    FROM pg_class AS sequence
    JOIN pg_namespace AS namespace ON namespace.oid = sequence.relnamespace
    LEFT JOIN pg_depend AS dependency
      ON dependency.objid = sequence.oid
     AND dependency.classid = 'pg_class'::regclass
     AND dependency.refclassid = 'pg_class'::regclass
     AND dependency.deptype IN ('a', 'i')
    LEFT JOIN pg_class AS owner_table ON owner_table.oid = dependency.refobjid
    WHERE namespace.nspname = 'public' AND sequence.relkind = 'S'
)
SELECT
    (SELECT count(*) = count(oid) FROM relation)::text || E'\t' ||
    COALESCE((SELECT bool_and(owner_name = '$($Policy.OwnerRole)') FROM relation), false)::text || E'\t' ||
    COALESCE((SELECT bool_and(
        has_table_privilege('$($Policy.RuntimeRole)', relation.oid, privilege_name.privilege) =
        (privilege_name.privilege = ANY(relation.expected_privileges)))
        FROM relation CROSS JOIN privilege_name WHERE relation.oid IS NOT NULL), false)::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1 FROM pg_class AS catalog_relation
        JOIN pg_namespace AS namespace ON namespace.oid = catalog_relation.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(catalog_relation.relacl, acldefault('r', catalog_relation.relowner))) AS acl
        LEFT JOIN pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE namespace.nspname = 'public' AND catalog_relation.relkind IN ('r', 'p')
          AND COALESCE(grantee.rolname, 'PUBLIC') NOT IN (
              '$($Policy.OwnerRole)', '$($Policy.RuntimeRole)', '$($Policy.MigratorRole)', '$($Policy.BackupRole)'))
    )::text || E'\t' ||
    ($runtimeConnectPredicate
     AND NOT has_database_privilege('$($Policy.RuntimeRole)', current_database(), 'CREATE')
     AND NOT has_database_privilege('$($Policy.RuntimeRole)', current_database(), 'TEMPORARY')
     AND has_schema_privilege('$($Policy.RuntimeRole)', 'public', 'USAGE')
     AND NOT has_schema_privilege('$($Policy.RuntimeRole)', 'public', 'CREATE'))::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1 FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public'
          AND has_function_privilege('$($Policy.RuntimeRole)', routine.oid, 'EXECUTE'))
    )::text || E'\t' ||
    COALESCE((SELECT bool_and(CASE WHEN is_consumer THEN
        has_sequence_privilege('$($Policy.RuntimeRole)', oid, 'USAGE')
        AND has_sequence_privilege('$($Policy.RuntimeRole)', oid, 'SELECT')
        AND NOT has_sequence_privilege('$($Policy.RuntimeRole)', oid, 'UPDATE')
    ELSE
        NOT has_sequence_privilege('$($Policy.RuntimeRole)', oid, 'USAGE')
        AND NOT has_sequence_privilege('$($Policy.RuntimeRole)', oid, 'SELECT')
        AND NOT has_sequence_privilege('$($Policy.RuntimeRole)', oid, 'UPDATE')
    END) FROM sequence_contract), true)::text || E'\t' ||
    (has_database_privilege('$($Policy.BackupRole)', current_database(), 'CONNECT')
     AND NOT has_database_privilege('$($Policy.BackupRole)', current_database(), 'CREATE')
     AND NOT has_database_privilege('$($Policy.BackupRole)', current_database(), 'TEMPORARY')
     AND has_schema_privilege('$($Policy.BackupRole)', 'public', 'USAGE')
     AND NOT has_schema_privilege('$($Policy.BackupRole)', 'public', 'CREATE')
     AND NOT EXISTS (
         SELECT 1 FROM pg_class AS relation
         JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'public'
           AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND NOT has_table_privilege('$($Policy.BackupRole)', relation.oid, 'SELECT'))
     AND NOT EXISTS (
         SELECT 1 FROM pg_class AS sequence
         JOIN pg_namespace AS namespace ON namespace.oid = sequence.relnamespace
         WHERE namespace.nspname = 'public' AND sequence.relkind = 'S'
           AND (NOT has_sequence_privilege('$($Policy.BackupRole)', sequence.oid, 'SELECT')
                OR has_sequence_privilege('$($Policy.BackupRole)', sequence.oid, 'USAGE')
                OR has_sequence_privilege('$($Policy.BackupRole)', sequence.oid, 'UPDATE')))
     AND NOT EXISTS (
         SELECT 1 FROM pg_proc AS routine
         JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
         WHERE namespace.nspname = 'public'
           AND has_function_privilege('$($Policy.BackupRole)', routine.oid, 'EXECUTE'))
    )::text || E'\t' ||
    has_function_privilege('$($Policy.RuntimeRole)', 'pg_catalog.pg_control_system()', 'EXECUTE')::text;
"@
}

function Assert-TicketboxDatabaseRuntimeAcl {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [switch]$IncludeManagedSchemaCurrencyAuthority,
        [switch]$PreserveRuntimeFence
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $specifications = @(Get-TicketboxDatabaseRuntimePrivilegeSpecifications `
        -IncludeManagedSchemaCurrencyAuthority:$IncludeManagedSchemaCurrencyAuthority)
    $sequenceConsumers = @(Get-TicketboxDatabaseSequenceConsumerTables `
        -IncludeManagedSchemaCurrencyAuthority:$IncludeManagedSchemaCurrencyAuthority)
    $sql = New-TicketboxDatabaseRuntimeAclObservationSql `
        -Specifications $specifications `
        -SequenceConsumerTables $sequenceConsumers `
        -Policy $policy `
        -PreserveRuntimeFence:$PreserveRuntimeFence
    $output = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database $policy.DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "Ticketbox structured runtime ACL attestation" `
        -Sql $sql
    try {
        $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
            -Output $output `
            -FieldCount 9 `
            -Label "Ticketbox structured runtime ACL attestation"
    }
    catch {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox structured runtime ACL attestation shape is invalid." `
            -FailureCode "runtime_acl_invariant_failed" `
            -InnerException $_.Exception)
    }
    if (@($fields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox runtime ACL does not satisfy the release contract." `
            -FailureCode "runtime_acl_invariant_failed")
    }
}

function Set-TicketboxDatabaseRuntimeAcl {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [switch]$PreserveRuntimeFence
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database $policy.DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (New-TicketboxDatabaseRuntimeAclSql `
            -IncludeManagedSchemaCurrencyAuthority `
            -PreserveRuntimeFence:$PreserveRuntimeFence) `
        -Label "Ticketbox managed-schema runtime ACL application" | Out-Null
    Assert-TicketboxDatabaseRuntimeAcl `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -IncludeManagedSchemaCurrencyAuthority `
        -PreserveRuntimeFence:$PreserveRuntimeFence
}

function Get-TicketboxDatabaseRuntimeAclEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $evidence = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database $policy.DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "Ticketbox runtime ACL canonical evidence" `
        -Sql @"
WITH acl_rows AS (
    SELECT 'database'::text AS kind, database.datname AS object_name,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC') AS grantee,
           acl.privilege_type, acl.is_grantable
    FROM pg_database AS database,
         LATERAL aclexplode(COALESCE(database.datacl, acldefault('d'::"char", database.datdba))) AS acl
    WHERE database.datname = current_database()
    UNION ALL
    SELECT 'schema', namespace.nspname, COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'),
           acl.privilege_type, acl.is_grantable
    FROM pg_namespace AS namespace,
         LATERAL aclexplode(COALESCE(namespace.nspacl, acldefault('n'::"char", namespace.nspowner))) AS acl
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT CASE WHEN relation.relkind = 'S' THEN 'sequence' ELSE 'relation' END,
           namespace.nspname || '.' || relation.relname,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'), acl.privilege_type, acl.is_grantable
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(COALESCE(
        relation.relacl,
        acldefault(CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END, relation.relowner)
    )) AS acl
    WHERE namespace.nspname = 'public' AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    UNION ALL
    SELECT 'routine', namespace.nspname || '.' || routine.oid::regprocedure::text,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'), acl.privilege_type, acl.is_grantable
    FROM pg_proc AS routine
    JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL aclexplode(COALESCE(routine.proacl, acldefault('f'::"char", routine.proowner))) AS acl
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT 'routine', namespace.nspname || '.' || routine.oid::regprocedure::text,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'), acl.privilege_type, acl.is_grantable
    FROM pg_proc AS routine
    JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL aclexplode(COALESCE(routine.proacl, acldefault('f'::"char", routine.proowner))) AS acl
    WHERE routine.oid = 'pg_catalog.pg_control_system()'::regprocedure
)
SELECT kind || E'\t' || object_name || E'\t' || grantee || E'\t' ||
       privilege_type || E'\t' || is_grantable::text
FROM acl_rows
WHERE NOT (
    kind = 'database' AND object_name = current_database()
    AND grantee IN ('$($policy.RuntimeRole)', '$($policy.MigratorRole)')
    AND privilege_type = 'CONNECT' AND NOT is_grantable)
ORDER BY kind, object_name, grantee, privilege_type, is_grantable;
"@
    $canonicalEvidence = (([string]$evidence).Trim() -replace "`r`n", "`n") -replace "`r", "`n"
    return $canonicalEvidence
}
