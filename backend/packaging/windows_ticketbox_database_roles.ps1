#Requires -Version 5.1

function Get-TicketboxDatabaseRoleOid {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$RoleName
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    if ($RoleName -cnotin @(
        $policy.OwnerRole, $policy.MigratorRole, $policy.RuntimeRole,
        $policy.BackupRole
    )) {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox role OID request is outside the policy." `
            -FailureCode "role_authority_invariant_failed")
    }
    $roleLiteral = ConvertTo-TicketboxPostgresqlSqlLiteral $RoleName
    $output = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "Ticketbox role OID observation" `
        -Sql "SELECT oid::text FROM pg_roles WHERE rolname = $roleLiteral;"
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $output `
        -FieldCount 1 `
        -Label "Ticketbox role OID observation"
    $oid = 0L
    if (-not [long]::TryParse($fields[0], [ref]$oid) -or $oid -lt 1 -or $oid -gt [uint32]::MaxValue) {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox role OID observation is invalid." `
            -FailureCode "role_authority_invariant_failed")
    }
    return [uint32]$oid
}

function New-TicketboxDatabaseActiveRoleObservationSql {
    param(
        [Parameter(Mandatory = $true)][object]$Policy,
        [Parameter(Mandatory = $true)][ValidateSet("fenced", "active")][string]$Phase
    )

    $runtimeLogin = if ($Phase -ceq "fenced") {
        "NOT rolcanlogin AND rolconnlimit = 0"
    }
    else { "rolcanlogin AND rolconnlimit = -1" }
    $backupLogin = if ($Phase -ceq "fenced") {
        "NOT rolcanlogin AND rolconnlimit = 0"
    }
    else { "rolcanlogin AND rolconnlimit = 1" }
    $runtimeConnect = if ($Phase -ceq "fenced") {
        "NOT has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'CONNECT')"
    }
    else {
        "has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'CONNECT')"
    }
    return @"
SELECT
    COALESCE((SELECT NOT rolcanlogin AND NOT rolinherit
      AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      AND rolconnlimit = -1
      FROM pg_roles WHERE rolname = '$($Policy.OwnerRole)'), false)::text || E'\t' ||
    COALESCE((SELECT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      AND rolconnlimit = 1 AND rolvaliduntil IS NOT NULL
      AND rolvaliduntil > clock_timestamp()
      AND rolvaliduntil <= clock_timestamp() + interval '1 hour'
      AND rolpassword IS NOT NULL
      FROM pg_authid WHERE rolname = '$($Policy.MigratorRole)'), false)::text || E'\t' ||
    COALESCE((SELECT $runtimeLogin AND rolinherit AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      FROM pg_roles WHERE rolname = '$($Policy.RuntimeRole)'), false)::text || E'\t' ||
    COALESCE((SELECT $backupLogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      AND rolpassword IS NOT NULL
      FROM pg_authid WHERE rolname = '$($Policy.BackupRole)'), false)::text || E'\t' ||
    (SELECT count(*) = 1 FROM pg_auth_members AS membership
      JOIN pg_roles AS granted ON granted.oid = membership.roleid
      JOIN pg_roles AS member ON member.oid = membership.member
      WHERE granted.rolname = '$($Policy.OwnerRole)'
        AND member.rolname = '$($Policy.MigratorRole)'
        AND NOT membership.admin_option AND NOT membership.inherit_option
        AND membership.set_option)::text || E'\t' ||
    (SELECT count(*) = 0 FROM pg_auth_members AS membership
      JOIN pg_roles AS granted ON granted.oid = membership.roleid
      JOIN pg_roles AS member ON member.oid = membership.member
      WHERE (granted.rolname IN ('$($Policy.OwnerRole)', '$($Policy.MigratorRole)', '$($Policy.RuntimeRole)', '$($Policy.BackupRole)')
             OR member.rolname IN ('$($Policy.OwnerRole)', '$($Policy.MigratorRole)', '$($Policy.RuntimeRole)', '$($Policy.BackupRole)'))
        AND NOT (granted.rolname = '$($Policy.OwnerRole)'
                 AND member.rolname = '$($Policy.MigratorRole)'
                 AND NOT membership.admin_option AND NOT membership.inherit_option
                 AND membership.set_option))::text || E'\t' ||
    COALESCE((SELECT COALESCE(role.rolconfig = ARRAY['search_path=pg_catalog, public']::text[], false)
      AND NOT EXISTS (
          SELECT 1 FROM pg_db_role_setting AS setting
          JOIN pg_database AS database ON database.oid = setting.setdatabase
          WHERE setting.setrole = role.oid AND database.datname = '$($Policy.DatabaseName)')
      FROM pg_roles AS role WHERE role.rolname = '$($Policy.RuntimeRole)'), false)::text || E'\t' ||
    COALESCE((SELECT COALESCE(role.rolconfig = ARRAY['search_path=pg_catalog, public']::text[], false)
      AND NOT EXISTS (
          SELECT 1 FROM pg_db_role_setting AS setting
          JOIN pg_database AS database ON database.oid = setting.setdatabase
          WHERE setting.setrole = role.oid AND database.datname = '$($Policy.DatabaseName)')
      FROM pg_roles AS role WHERE role.rolname = '$($Policy.MigratorRole)'), false)::text || E'\t' ||
    COALESCE((SELECT COALESCE(role.rolconfig = ARRAY['search_path=pg_catalog, public']::text[], false)
      AND NOT EXISTS (
          SELECT 1 FROM pg_db_role_setting AS setting
          JOIN pg_database AS database ON database.oid = setting.setdatabase
          WHERE setting.setrole = role.oid AND database.datname = '$($Policy.DatabaseName)')
      FROM pg_roles AS role WHERE role.rolname = '$($Policy.BackupRole)'), false)::text || E'\t' ||
    COALESCE((SELECT pg_get_userbyid(datdba) = '$($Policy.OwnerRole)'
      FROM pg_database WHERE datname = '$($Policy.DatabaseName)'), false)::text || E'\t' ||
    COALESCE((SELECT pg_get_userbyid(nspowner) = '$($Policy.OwnerRole)'
      FROM pg_namespace WHERE nspname = 'public'), false)::text || E'\t' ||
    (($runtimeConnect)
      AND has_database_privilege('$($Policy.MigratorRole)', '$($Policy.DatabaseName)', 'CONNECT'))::text || E'\t' ||
    (NOT has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'CREATE'))::text || E'\t' ||
    (NOT has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'TEMPORARY'))::text || E'\t' ||
    has_schema_privilege('$($Policy.RuntimeRole)', 'public', 'USAGE')::text || E'\t' ||
    (NOT has_schema_privilege('$($Policy.RuntimeRole)', 'public', 'CREATE'))::text || E'\t' ||
    (has_database_privilege('$($Policy.BackupRole)', '$($Policy.DatabaseName)', 'CONNECT')
      AND NOT has_database_privilege('$($Policy.BackupRole)', '$($Policy.DatabaseName)', 'CREATE')
      AND NOT has_database_privilege('$($Policy.BackupRole)', '$($Policy.DatabaseName)', 'TEMPORARY')
      AND has_schema_privilege('$($Policy.BackupRole)', 'public', 'USAGE')
      AND NOT has_schema_privilege('$($Policy.BackupRole)', 'public', 'CREATE')
      AND NOT EXISTS (
          SELECT 1 FROM pg_class AS relation
          JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
          WHERE namespace.nspname = 'public'
            AND pg_get_userbyid(relation.relowner) = '$($Policy.BackupRole)')
      AND NOT EXISTS (
          SELECT 1 FROM pg_proc AS routine
          JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
          WHERE namespace.nspname = 'public'
            AND pg_get_userbyid(routine.proowner) = '$($Policy.BackupRole)'))::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1 FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(relation.relowner) = '$($Policy.RuntimeRole)')
     AND NOT EXISTS (
        SELECT 1 FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(routine.proowner) = '$($Policy.RuntimeRole)')
     AND NOT EXISTS (
        SELECT 1 FROM pg_type AS type
        JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(type.typowner) = '$($Policy.RuntimeRole)'))::text;
"@
}

function New-TicketboxDatabaseRetiredRoleObservationSql {
    param([Parameter(Mandatory = $true)][object]$Policy)

    return @"
SELECT
    COALESCE((SELECT NOT rolcanlogin AND NOT rolinherit
      AND NOT rolsuper AND NOT rolcreatedb
      AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      AND rolconnlimit = -1
      FROM pg_roles WHERE rolname = '$($Policy.OwnerRole)'), false)::text || E'\t' ||
    COALESCE((SELECT NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
      AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
      AND NOT rolbypassrls AND rolconnlimit = 1 AND rolpassword IS NULL
      FROM pg_authid WHERE rolname = '$($Policy.MigratorRole)'), false)::text || E'\t' ||
    COALESCE((SELECT rolcanlogin AND rolinherit AND NOT rolsuper
      AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
      AND NOT rolbypassrls AND rolconnlimit = -1 AND rolpassword IS NOT NULL
      FROM pg_authid WHERE rolname = '$($Policy.RuntimeRole)'), false)::text || E'\t' ||
    COALESCE((SELECT rolcanlogin AND NOT rolinherit AND NOT rolsuper
      AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
      AND NOT rolbypassrls AND rolconnlimit = 1 AND rolpassword IS NOT NULL
      FROM pg_authid WHERE rolname = '$($Policy.BackupRole)'), false)::text || E'\t' ||
    (SELECT count(*) = 0 FROM pg_auth_members AS membership
      JOIN pg_roles AS granted ON granted.oid = membership.roleid
      JOIN pg_roles AS member ON member.oid = membership.member
      WHERE granted.rolname IN ('$($Policy.OwnerRole)', '$($Policy.MigratorRole)', '$($Policy.RuntimeRole)', '$($Policy.BackupRole)', '$($Policy.RetiredLegacyRole)')
         OR member.rolname IN ('$($Policy.OwnerRole)', '$($Policy.MigratorRole)', '$($Policy.RuntimeRole)', '$($Policy.BackupRole)', '$($Policy.RetiredLegacyRole)'))::text || E'\t' ||
    COALESCE((SELECT COALESCE(role.rolconfig = ARRAY['search_path=pg_catalog, public']::text[], false)
      AND NOT EXISTS (
          SELECT 1 FROM pg_db_role_setting AS setting
          JOIN pg_database AS database ON database.oid = setting.setdatabase
          WHERE setting.setrole = role.oid AND database.datname = '$($Policy.DatabaseName)')
      FROM pg_roles AS role WHERE role.rolname = '$($Policy.RuntimeRole)'), false)::text || E'\t' ||
    COALESCE((SELECT COALESCE(role.rolconfig = ARRAY['search_path=pg_catalog, public']::text[], false)
      AND NOT EXISTS (
          SELECT 1 FROM pg_db_role_setting AS setting
          JOIN pg_database AS database ON database.oid = setting.setdatabase
          WHERE setting.setrole = role.oid AND database.datname = '$($Policy.DatabaseName)')
      FROM pg_roles AS role WHERE role.rolname = '$($Policy.MigratorRole)'), false)::text || E'\t' ||
    COALESCE((SELECT COALESCE(role.rolconfig = ARRAY['search_path=pg_catalog, public']::text[], false)
      AND NOT EXISTS (
          SELECT 1 FROM pg_db_role_setting AS setting
          JOIN pg_database AS database ON database.oid = setting.setdatabase
          WHERE setting.setrole = role.oid AND database.datname = '$($Policy.DatabaseName)')
      FROM pg_roles AS role WHERE role.rolname = '$($Policy.BackupRole)'), false)::text || E'\t' ||
    COALESCE((SELECT pg_get_userbyid(datdba) = '$($Policy.OwnerRole)'
      FROM pg_database WHERE datname = '$($Policy.DatabaseName)'), false)::text || E'\t' ||
    COALESCE((SELECT pg_get_userbyid(nspowner) = '$($Policy.OwnerRole)'
      FROM pg_namespace WHERE nspname = 'public'), false)::text || E'\t' ||
    has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'CONNECT')::text || E'\t' ||
    (NOT has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'CREATE'))::text || E'\t' ||
    (NOT has_database_privilege('$($Policy.RuntimeRole)', '$($Policy.DatabaseName)', 'TEMPORARY'))::text || E'\t' ||
    (NOT has_database_privilege('$($Policy.MigratorRole)', '$($Policy.DatabaseName)', 'CONNECT'))::text || E'\t' ||
    has_schema_privilege('$($Policy.RuntimeRole)', 'public', 'USAGE')::text || E'\t' ||
    (NOT has_schema_privilege('$($Policy.RuntimeRole)', 'public', 'CREATE'))::text || E'\t' ||
    (has_database_privilege('$($Policy.BackupRole)', '$($Policy.DatabaseName)', 'CONNECT')
      AND NOT has_database_privilege('$($Policy.BackupRole)', '$($Policy.DatabaseName)', 'CREATE')
      AND NOT has_database_privilege('$($Policy.BackupRole)', '$($Policy.DatabaseName)', 'TEMPORARY')
      AND has_schema_privilege('$($Policy.BackupRole)', 'public', 'USAGE')
      AND NOT has_schema_privilege('$($Policy.BackupRole)', 'public', 'CREATE')
      AND NOT EXISTS (
          SELECT 1 FROM pg_class AS relation
          JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
          WHERE namespace.nspname = 'public'
            AND pg_get_userbyid(relation.relowner) = '$($Policy.BackupRole)')
      AND NOT EXISTS (
          SELECT 1 FROM pg_proc AS routine
          JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
          WHERE namespace.nspname = 'public'
            AND pg_get_userbyid(routine.proowner) = '$($Policy.BackupRole)'))::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1 FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(relation.relowner) = '$($Policy.RuntimeRole)')
     AND NOT EXISTS (
        SELECT 1 FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(routine.proowner) = '$($Policy.RuntimeRole)')
     AND NOT EXISTS (
        SELECT 1 FROM pg_type AS type
        JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(type.typowner) = '$($Policy.RuntimeRole)'))::text;
"@
}

function Assert-TicketboxDatabaseRolePolicy {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][ValidateSet("fenced", "active", "retired")][string]$Phase
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $sql = if ($Phase -ceq "retired") {
        New-TicketboxDatabaseRetiredRoleObservationSql $policy
    }
    else {
        New-TicketboxDatabaseActiveRoleObservationSql -Policy $policy -Phase $Phase
    }
    $output = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database $policy.DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "Ticketbox $Phase role policy verification" `
        -Sql $sql
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $output `
        -FieldCount 18 `
        -Label "Ticketbox $Phase role policy verification"
    if (@($fields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox $Phase role policy does not satisfy the release contract." `
            -FailureCode "role_authority_invariant_failed")
    }
}

function Assert-TicketboxDatabaseCredential {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [Parameter(Mandatory = $true)][ValidateSet("migrator", "runtime", "backup")][string]$CredentialKind
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $role = switch ($CredentialKind) {
        "migrator" { $policy.MigratorRole }
        "runtime" { $policy.RuntimeRole }
        "backup" { $policy.BackupRole }
    }
    $output = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database $policy.DatabaseName `
        -Role $role `
        -Password $Password `
        -Label "Ticketbox $CredentialKind credential authority probe" `
        -Sql "SELECT current_user || E'\t' || current_setting('search_path');"
    $fields = ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $output `
        -FieldCount 2 `
        -Label "Ticketbox $CredentialKind credential authority probe"
    if ($fields[0] -cne $role -or $fields[1] -cne "pg_catalog, public") {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox $CredentialKind credential/search_path authority is invalid." `
            -FailureCode "role_authority_invariant_failed")
    }
}

function Get-TicketboxDatabaseRoleAuthorityEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $evidence = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "Ticketbox role authority canonical evidence" `
        -Sql @"
SELECT 'role' || E'\t' || rolname || E'\t' || oid::text || E'\t' ||
       rolcanlogin::text || E'\t' || rolinherit::text || E'\t' ||
       rolsuper::text || E'\t' || rolcreatedb::text || E'\t' ||
       rolcreaterole::text || E'\t' || rolreplication::text || E'\t' ||
       rolbypassrls::text || E'\t' || rolconnlimit::text || E'\t' ||
       (rolpassword IS NOT NULL)::text || E'\t' ||
       COALESCE(array_to_string(rolconfig, ','), '') || E'\t' ||
       COALESCE(shobj_description(oid, 'pg_authid'), '')
FROM pg_authid
WHERE rolname IN ('$($policy.OwnerRole)', '$($policy.MigratorRole)', '$($policy.RuntimeRole)', '$($policy.BackupRole)', '$($policy.RetiredLegacyRole)')
UNION ALL
SELECT 'membership' || E'\t' || granted.rolname || E'\t' || member.rolname || E'\t' ||
       membership.admin_option::text || E'\t' || membership.inherit_option::text || E'\t' || membership.set_option::text
FROM pg_auth_members AS membership
JOIN pg_roles AS granted ON granted.oid = membership.roleid
JOIN pg_roles AS member ON member.oid = membership.member
WHERE granted.rolname IN ('$($policy.OwnerRole)', '$($policy.MigratorRole)', '$($policy.RuntimeRole)', '$($policy.BackupRole)', '$($policy.RetiredLegacyRole)')
   OR member.rolname IN ('$($policy.OwnerRole)', '$($policy.MigratorRole)', '$($policy.RuntimeRole)', '$($policy.BackupRole)', '$($policy.RetiredLegacyRole)')
ORDER BY 1;
"@
    return (([string]$evidence).Trim() -replace "`r`n", "`n") -replace "`r", "`n"
}

function Get-TicketboxDatabaseMigratorRetirementSql {
    $policy = Get-TicketboxDatabaseAuthorizationContract
    return @"
BEGIN;
REVOKE CONNECT ON DATABASE "$($policy.DatabaseName)" FROM "$($policy.MigratorRole)";
DO `$ticketbox_membership`$
DECLARE
    migrator_oid oid := (SELECT oid FROM pg_roles WHERE rolname = '$($policy.MigratorRole)');
    membership_record record;
BEGIN
    FOR membership_record IN
        SELECT granted.rolname AS granted_name, member.rolname AS member_name
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE membership.roleid = migrator_oid OR membership.member = migrator_oid
    LOOP
        EXECUTE format('REVOKE %I FROM %I', membership_record.granted_name, membership_record.member_name);
    END LOOP;
END
`$ticketbox_membership`$;
ALTER ROLE "$($policy.MigratorRole)" NOLOGIN PASSWORD NULL;
COMMIT;
SELECT pg_terminate_backend(pid, 5000)
FROM pg_stat_activity
WHERE usename = '$($policy.MigratorRole)' AND pid <> pg_backend_pid();
"@
}

function Get-TicketboxDatabaseMigratorRetirementVerificationSql {
    $policy = Get-TicketboxDatabaseAuthorizationContract
    return @"
DO `$ticketbox`$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE granted.rolname = '$($policy.MigratorRole)'
           OR member.rolname = '$($policy.MigratorRole)'
    ) THEN RAISE EXCEPTION 'migrator still has a role membership'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_authid
        WHERE rolname = '$($policy.MigratorRole)'
          AND NOT rolcanlogin AND rolpassword IS NULL
    ) THEN RAISE EXCEPTION 'migrator credential was not retired'; END IF;
    IF EXISTS (
        SELECT 1 FROM pg_stat_activity
        WHERE usename = '$($policy.MigratorRole)' AND pid <> pg_backend_pid()
    ) THEN RAISE EXCEPTION 'migrator sessions remain active'; END IF;
    IF has_database_privilege('$($policy.MigratorRole)', '$($policy.DatabaseName)', 'CONNECT')
    THEN RAISE EXCEPTION 'migrator still has database CONNECT'; END IF;
END
`$ticketbox`$;
"@
}
