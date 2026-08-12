#Requires -Version 5.1

function Invoke-TicketboxPostgresqlWriterFenceReconcile {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$AuthorityRole,
        [Parameter(Mandatory = $true)][string]$ManagedSchemaName,
        [Parameter(Mandatory = $true)][string]$AdvisoryLockLabel,
        [Parameter(Mandatory = $true)][string]$ApplicationName,
        [Parameter(Mandatory = $true)][string[]]$ManagedWriterRoles,
        [Parameter(Mandatory = $true)][string[]]$AuthorizedRoleNames,
        [Parameter(Mandatory = $true)][string[]]$AllowedLoginRolesAfterFence,
        [Parameter(Mandatory = $true)][string[]]$AllowedDatabaseOwnerRoles,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()]
        [string[]]$AllowedManagedWriterOwnerRoles,
        [Parameter(Mandatory = $true)][string[]]$AllowedDatabaseOwnerTransitionRoles,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 5000,
        [ValidateRange(1, 3600000)][int]$LockTimeoutMilliseconds = 1000,
        [ValidateRange(1, 3600000)][int]$TerminationTimeoutMilliseconds = 3000
    )

    Assert-TicketboxPostgresqlWriterFenceDependencies
    $policy = Resolve-TicketboxPostgresqlWriterFenceReconcilePolicy `
        -AuthorityRole $AuthorityRole `
        -ManagedSchemaName $ManagedSchemaName `
        -AdvisoryLockLabel $AdvisoryLockLabel `
        -ApplicationName $ApplicationName `
        -ManagedWriterRoles $ManagedWriterRoles `
        -AuthorizedRoleNames $AuthorizedRoleNames `
        -AllowedLoginRolesAfterFence $AllowedLoginRolesAfterFence `
        -AllowedDatabaseOwnerRoles $AllowedDatabaseOwnerRoles `
        -AllowedManagedWriterOwnerRoles $AllowedManagedWriterOwnerRoles `
        -AllowedDatabaseOwnerTransitionRoles $AllowedDatabaseOwnerTransitionRoles `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -LockTimeoutMilliseconds $LockTimeoutMilliseconds `
        -TerminationTimeoutMilliseconds $TerminationTimeoutMilliseconds
    $authority = $policy.Authority
    $schema = $policy.Schema
    $lease = $policy.Lease
    $application = $policy.Application; $managedRoles = $policy.ManagedRoles
    $authorizedRoles = $policy.AuthorizedRoles; $allowedLoginRoles = $policy.AllowedLoginRoles
    $allowedOwners = $policy.AllowedDatabaseOwnerRoles
    $allowedManagedOwners = $policy.AllowedManagedWriterOwnerRoles
    $versionGuard = New-TicketboxPostgresqlWriterFenceVersionGuardSql
    $predefinedCapabilityGuard = `
        New-TicketboxPostgresqlWriterFencePredefinedCapabilityGuardSql `
            -AuthorityRoleSql $authority `
            -AllowedOwnerTransitionRolesSql `
                $policy.AllowedDatabaseOwnerTransitionRoles
    $inheritedConnectGuard = New-TicketboxPostgresqlWriterFenceInheritedConnectGuardSql `
        -ManagedRolesSql $managedRoles
    $securityDefinerGuard = New-TicketboxPostgresqlWriterFenceSecurityDefinerGuardSql `
        -AuthorityRoleSql $authority `
        -AllowedOwnerRolesSql $allowedOwners
    $unregisteredWriterGuard = `
        New-TicketboxPostgresqlWriterFenceUnregisteredWriterGuardSql `
            -AuthorizedRolesSql $authorizedRoles `
            -ManagedSchemaSql $schema
    $sessionDrain = New-TicketboxPostgresqlWriterFenceSessionDrainSql `
        -ManagedRolesSql $managedRoles `
        -TerminationTimeoutMilliseconds $TerminationTimeoutMilliseconds
    $sql = @"
SET application_name = $application;
SET statement_timeout = '$($TimeoutMilliseconds)ms';
SET lock_timeout = '$($LockTimeoutMilliseconds)ms';
DO `$writer_fence`$
BEGIN
    IF NOT pg_try_advisory_lock(
        hashtext(current_database()),
        hashtext($lease)
    ) THEN
        RAISE EXCEPTION 'PostgreSQL writer-fence lease is busy';
    END IF;
END
`$writer_fence`$;
SELECT pg_stat_clear_snapshot();
DO `$writer_fence`$
BEGIN
$versionGuard
    IF session_user <> $authority OR current_user <> $authority THEN
        RAISE EXCEPTION 'Writer fence is not held by the authority session';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE datid = (
            SELECT oid FROM pg_database WHERE datname = current_database()
        )
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
          AND usename <> ALL($managedRoles)
    ) THEN
        RAISE EXCEPTION 'Unknown client session blocks writer fence';
    END IF;
    IF current_setting('max_prepared_transactions')::bigint <> 0
       OR EXISTS (
           SELECT 1 FROM pg_prepared_xacts
           WHERE database = current_database()
       )
       OR EXISTS (
           SELECT 1 FROM pg_subscription
           WHERE subdbid = (
               SELECT oid FROM pg_database WHERE datname = current_database()
           )
       )
       OR EXISTS (
           SELECT 1
           FROM pg_stat_activity
           WHERE datid = (
               SELECT oid FROM pg_database WHERE datname = current_database()
           )
             AND pid <> pg_backend_pid()
             AND backend_type NOT IN (
                 'client backend', 'autovacuum worker', 'parallel worker'
             )
       )
    THEN
        RAISE EXCEPTION 'Unsupported prepared, logical, or background writer exists';
    END IF;
$unregisteredWriterGuard
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname = ANY($authorizedRoles)
          AND role.rolname <> ALL($allowedLoginRoles)
          AND role.rolname <> ALL($managedRoles)
          AND role.rolcanlogin
    ) THEN
        RAISE EXCEPTION 'Authorized non-writer role has unexpected LOGIN';
    END IF;
    IF (
        SELECT pg_get_userbyid(datdba)
        FROM pg_database
        WHERE datname = current_database()
    ) <> ALL($allowedOwners) THEN
        RAISE EXCEPTION 'Database owner is outside the allowed authority policy';
    END IF;
$predefinedCapabilityGuard
$inheritedConnectGuard
$securityDefinerGuard
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname = ANY($managedRoles)
          AND role.rolname <> ALL($allowedManagedOwners)
          AND role.oid = (
              SELECT datdba FROM pg_database
              WHERE datname = current_database()
          )
    ) THEN
        RAISE EXCEPTION 'Managed writer role owns the database and cannot be fenced';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname <> $authority
          AND (
              role.rolsuper
              OR role.rolcreatedb
              OR role.rolcreaterole
              OR role.rolreplication
              OR role.rolbypassrls
          )
    ) THEN
        RAISE EXCEPTION 'Non-authority elevated role blocks writer fence';
    END IF;
END
`$writer_fence`$;
BEGIN;
DO `$writer_fence`$
DECLARE fence_role text;
BEGIN
    FOREACH fence_role IN ARRAY $managedRoles LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = fence_role) THEN
            EXECUTE format(
                'ALTER ROLE %I NOLOGIN CONNECTION LIMIT 0',
                fence_role
            );
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM %I',
                current_database(),
                fence_role
            );
        END IF;
    END LOOP;
    EXECUTE format(
        'REVOKE CONNECT ON DATABASE %I FROM PUBLIC',
        current_database()
    );
END
`$writer_fence`$;
COMMIT;
$sessionDrain
SELECT pg_stat_clear_snapshot();
DO `$writer_fence`$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE datid = (
            SELECT oid FROM pg_database WHERE datname = current_database()
        )
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
    ) THEN
        RAISE EXCEPTION 'Client session appeared before writer fence completed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_locks AS database_lock
        WHERE database_lock.pid IS NOT NULL
          AND database_lock.pid <> pg_backend_pid()
          AND database_lock.locktype = 'object'
          AND database_lock.mode = 'RowExclusiveLock'
          AND database_lock.classid = 'pg_database'::regclass::oid
          AND database_lock.objid = (
              SELECT oid FROM pg_database
              WHERE datname = current_database()
          )
          AND database_lock.objsubid = 0
          AND NOT EXISTS (
              SELECT 1
              FROM pg_stat_activity AS visible_activity
              WHERE visible_activity.pid = database_lock.pid
          )
    ) THEN
        RAISE EXCEPTION
            'Database startup backend appeared before writer fence completed';
    END IF;
    IF current_setting('max_prepared_transactions')::bigint <> 0
       OR EXISTS (
           SELECT 1 FROM pg_prepared_xacts
           WHERE database = current_database()
       )
       OR EXISTS (
           SELECT 1 FROM pg_subscription
           WHERE subdbid = (
               SELECT oid FROM pg_database WHERE datname = current_database()
           )
       )
       OR EXISTS (
           SELECT 1
           FROM pg_stat_activity
           WHERE datid = (
               SELECT oid FROM pg_database WHERE datname = current_database()
           )
             AND pid <> pg_backend_pid()
             AND backend_type NOT IN (
                 'client backend', 'autovacuum worker', 'parallel worker'
             )
       )
    THEN
        RAISE EXCEPTION 'Writer authority appeared during writer fence';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles AS role
        WHERE role.rolname !~ '^pg_'
          AND role.rolname <> ALL($allowedLoginRoles)
          AND role.rolcanlogin
    ) THEN
        RAISE EXCEPTION 'Role regained LOGIN before writer fence completed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles AS role
        WHERE role.rolname = ANY($managedRoles)
          AND (
              role.rolcanlogin
              OR role.rolconnlimit <> 0
               OR (
                   role.rolname <> ALL($allowedManagedOwners)
                   AND
                   has_database_privilege(
                       role.oid,
                       current_database(),
                       'CONNECT'
                   )
               )
          )
    ) THEN
        RAISE EXCEPTION
            'Durable writer admission fence is incomplete or inherited';
    END IF;
$securityDefinerGuard
END
`$writer_fence`$;
SELECT json_build_object(
    'advisory_released', pg_advisory_unlock(
        hashtext(current_database()),
        hashtext($lease)
    )
);
"@
    $output = Invoke-TicketboxPostgresqlWriterFenceSql `
        -PsqlPath $PsqlPath `
        -DatabaseUrl $DatabaseUrl `
        -Password $Password `
        -Sql $sql `
        -Label "PostgreSQL writer-fence reconcile" `
        -TimeoutMilliseconds $TimeoutMilliseconds
    return ConvertFrom-TicketboxPostgresqlWriterFenceReconcileJson $output
}
