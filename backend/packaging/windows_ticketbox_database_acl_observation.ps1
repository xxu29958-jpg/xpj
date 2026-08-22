#Requires -Version 5.1

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
