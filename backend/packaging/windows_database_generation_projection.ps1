# Installed runtime projection of an already-published Generation CURRENT.

#Requires -Version 5.1

function New-TicketboxDatabaseGenerationRuntimeDatabaseUrl {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword
    )
    return Invoke-TicketboxWithPlainPostgresqlSecret -Secret $RuntimePassword -Action {
        param([string]$PlainPassword)
        $role = [Uri]::EscapeDataString($script:TicketboxC07RuntimeRole)
        $password = [Uri]::EscapeDataString($PlainPassword)
        $database = [Uri]::EscapeDataString($script:TicketboxC07DatabaseName)
        return (
            "postgresql+psycopg://${role}:${password}@127.0.0.1:" +
            "$([int]$HostAuthority.Port)/${database}?require_auth=scram-sha-256"
        )
    }
}

function Write-TicketboxDatabaseGenerationRuntimeEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][string]$HttpBootstrapSecret
    )
    $shutdownSeconds = ConvertTo-TicketboxTimeoutSeconds ([int]$ProjectionContract.stop_timeout_ms)
    $lines = @(
        "DATABASE_URL=$DatabaseUrl",
        "TICKETBOX_HOST=127.0.0.1",
        "TICKETBOX_PORT=$([int]$ProjectionContract.backend_port)",
        "XPJ_EXTRA_LOOPBACK_HOSTS=127.0.0.1:$([int]$ProjectionContract.backend_port),localhost:$([int]$ProjectionContract.backend_port),[::1]:$([int]$ProjectionContract.backend_port)",
        "TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS=$shutdownSeconds",
        "PG_DUMP_PATH=$(Join-Path ([string]$ProjectionContract.pg_bin) 'pg_dump.exe')",
        "PG_RESTORE_PATH=$(Join-Path ([string]$ProjectionContract.pg_bin) 'pg_restore.exe')",
        "OCR_DEFAULT_TIMEZONE=$([string]$ProjectionContract.timezone)"
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$ProjectionContract.public_base_url)) {
        $lines += "PUBLIC_BASE_URL=$([string]$ProjectionContract.public_base_url)"
    }
    $lines += @(
        "ENABLE_HTTP_BOOTSTRAP=true",
        "HTTP_BOOTSTRAP_SECRET=$HttpBootstrapSecret"
    )
    Write-EnvNoBom -Path ([string]$ProjectionContract.env_path) -Lines $lines
}

function Read-TicketboxDatabaseGenerationRuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Candidate.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Candidate.Payload.target_revision -cne [string]$Intent.Payload.target_revision
    ) {
        throw "runtime projection 拒绝非 exact candidate。"
    }
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $environment = Read-EnvMap ([string]$ProjectionContract.env_path)
    if (-not $environment.ContainsKey("DATABASE_URL")) {
        throw "runtime projection 缺少 DATABASE_URL。"
    }
    $connection = Get-TicketboxLocalDatabaseConnection `
        -DatabaseUrl ([string]$environment["DATABASE_URL"]) `
        -PgPort ([int]$HostAuthority.Port) `
        -ExpectedDatabase $script:TicketboxC07DatabaseName `
        -ExpectedRole $script:TicketboxC07RuntimeRole
    Assert-TicketboxConnectedPostgresDataRoot `
        -PsqlPath ([string]$ProjectionContract.psql_path) `
        -DatabaseUrl $connection.DatabaseUrl `
        -ExpectedDataRoot ([string]$ProjectionContract.pg_data) `
        -ExpectedPort ([int]$HostAuthority.Port) `
        -Password $connection.Password `
        -TimeoutMilliseconds ([int]$ProjectionContract.database_tool_timeout_ms)
    $runtimePassword = ConvertTo-TicketboxPostgresqlSecureString `
        ([string]$connection.Password) `
        "database generation runtime projection password"
    try {
        if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
            $Intent $Candidate $HostAuthority $runtimePassword)) {
            throw "runtime projection 已存在但 bootstrap authority 尚未退役。"
        }
    }
    finally { $runtimePassword.Dispose() }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-runtime-projection-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        candidate_sha256 = [string]$Candidate.PayloadSha256
        committed_revision = [string]$Candidate.Payload.target_revision
        host_contract_sha256 = [string]$Intent.Payload.host_contract_sha256
        projection_contract_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $ProjectionContract
        )
        database_url_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            [string]$connection.PersistedDatabaseUrl
        )
    }
    return [pscustomobject]@{
        Payload = [pscustomobject]$payload
        PayloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
        )
        DatabaseUrl = [string]$connection.PersistedDatabaseUrl
    }
}

function Publish-TicketboxDatabaseGenerationRuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$RuntimeCredentials,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
        $Intent $Candidate $HostAuthority $RuntimeCredentials.RuntimePassword)) {
        throw "runtime admission 拒绝尚未退役的 bootstrap authority。"
    }
    $databaseUrl = New-TicketboxDatabaseGenerationRuntimeDatabaseUrl `
        $HostAuthority $RuntimeCredentials.RuntimePassword
    $capturedDatabaseUrl = $databaseUrl
    $capturedProjectionContract = $ProjectionContract
    Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $RuntimeCredentials.HttpBootstrapSecret `
        -Action ({
            param([string]$PlainSecret)
            Write-TicketboxDatabaseGenerationRuntimeEnvironment `
                $capturedDatabaseUrl $capturedProjectionContract $PlainSecret
        }) | Out-Null
    $environment = Read-EnvMap ([string]$ProjectionContract.env_path)
    $connection = Get-TicketboxLocalDatabaseConnection `
        -DatabaseUrl ([string]$environment["DATABASE_URL"]) `
        -PgPort ([int]$HostAuthority.Port) `
        -ExpectedDatabase $script:TicketboxC07DatabaseName `
        -ExpectedRole $script:TicketboxC07RuntimeRole
    Assert-TicketboxConnectedPostgresDataRoot `
        -PsqlPath ([string]$ProjectionContract.psql_path) `
        -DatabaseUrl $connection.DatabaseUrl `
        -ExpectedDataRoot ([string]$ProjectionContract.pg_data) `
        -ExpectedPort ([int]$HostAuthority.Port) `
        -Password $connection.Password `
        -TimeoutMilliseconds ([int]$ProjectionContract.database_tool_timeout_ms)
    return Read-TicketboxDatabaseGenerationRuntimeProjection `
        $Intent $Candidate $HostAuthority $ProjectionContract $LifecycleLock
}

function Get-TicketboxDatabaseGenerationMigratorAuthorityState {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $state = ([string](Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation migrator authority observation" `
        -Sql @"
WITH observed AS (
    SELECT
        EXISTS (
            SELECT 1 FROM pg_authid
            WHERE rolname = '$script:TicketboxC07MigratorRole'
              AND rolcanlogin AND NOT rolinherit AND NOT rolsuper
              AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
              AND NOT rolbypassrls AND rolconnlimit = 1
              AND rolvaliduntil IS NOT NULL AND rolvaliduntil > clock_timestamp()
              AND rolvaliduntil <= clock_timestamp() + interval '1 hour'
              AND rolpassword IS NOT NULL
        ) AS active_role,
        EXISTS (
            SELECT 1 FROM pg_authid
            WHERE rolname = '$script:TicketboxC07MigratorRole'
              AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
              AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
              AND NOT rolbypassrls AND rolconnlimit = 1
              AND rolpassword IS NULL
        ) AS retired_role,
        (
            SELECT count(*) = 1
            FROM pg_auth_members AS membership
            JOIN pg_roles AS granted ON granted.oid = membership.roleid
            JOIN pg_roles AS member ON member.oid = membership.member
            WHERE granted.rolname = '$script:TicketboxC07OwnerRole'
              AND member.rolname = '$script:TicketboxC07MigratorRole'
              AND NOT membership.admin_option
              AND NOT membership.inherit_option
              AND membership.set_option
        ) AS exact_owner_membership,
        (
            SELECT count(*)
            FROM pg_auth_members AS membership
            JOIN pg_roles AS granted ON granted.oid = membership.roleid
            JOIN pg_roles AS member ON member.oid = membership.member
            WHERE granted.rolname = '$script:TicketboxC07MigratorRole'
               OR member.rolname = '$script:TicketboxC07MigratorRole'
        ) AS membership_count,
        has_database_privilege(
            '$script:TicketboxC07MigratorRole',
            '$script:TicketboxC07DatabaseName',
            'CONNECT'
        ) AS has_connect,
        EXISTS (
            SELECT 1 FROM pg_stat_activity
            WHERE usename = '$script:TicketboxC07MigratorRole'
              AND pid <> pg_backend_pid()
        ) AS has_sessions
)
SELECT CASE
    WHEN active_role AND exact_owner_membership
         AND membership_count = 1 AND has_connect THEN 'active'
    WHEN retired_role AND membership_count = 0
         AND NOT has_connect AND has_sessions THEN 'retired_pending_sessions'
    WHEN retired_role AND membership_count = 0
         AND NOT has_connect AND NOT has_sessions THEN 'retired'
    ELSE 'invalid'
END
FROM observed;
"@)).Trim()
    if ($state -cnotin @("active", "retired_pending_sessions", "retired")) {
        throw "database generation migrator authority 是 partial/unknown 状态。"
    }
    return $state
}

function Prepare-TicketboxDatabaseGenerationRuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$RuntimeCredentials,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Candidate.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Candidate.Payload.target_revision -cne [string]$Intent.Payload.target_revision
    ) {
        throw "runtime projection 拒绝非 exact candidate。"
    }
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $null = Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $MaintenanceAuthority $Intent $HostAuthority $LifecycleLock
    $superuserPassword = $MaintenanceAuthority.Secret
    $migratorState = Get-TicketboxDatabaseGenerationMigratorAuthorityState `
        -HostAuthority $HostAuthority `
        -SuperuserPassword $superuserPassword
    if ($migratorState -ceq "retired_pending_sessions") {
        Invoke-TicketboxC07Sql `
            -Authority $HostAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuserPassword `
            -Label "database generation migrator retirement" `
            -Sql (Get-TicketboxC07MigratorRetirementSql) | Out-Null
        Invoke-TicketboxC07Sql `
            -Authority $HostAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuserPassword `
            -Label "database generation migrator retirement verification" `
            -Sql (Get-TicketboxC07MigratorRetirementVerificationSql) | Out-Null
        $migratorState = "retired"
    }
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation runtime admission" `
        -Sql @"
BEGIN;
ALTER ROLE "$script:TicketboxC07RuntimeRole"
    LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1;
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07RuntimeRole";
COMMIT;
"@ | Out-Null
    Assert-TicketboxC07RuntimeCredential `
        $HostAuthority $RuntimeCredentials.RuntimePassword
    if ($migratorState -ceq "active") {
        Assert-TicketboxC07RoleCatalog $HostAuthority $superuserPassword
    }
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $HostAuthority `
        -SuperuserPassword $superuserPassword `
        -IncludeManagedSchemaCurrencyAuthority
    if ($migratorState -ceq "active") {
        Invoke-TicketboxC07Sql `
            -Authority $HostAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $superuserPassword `
            -Label "database generation migrator retirement" `
            -Sql (Get-TicketboxC07MigratorRetirementSql) | Out-Null
    }
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $superuserPassword `
        -Label "database generation migrator retirement verification" `
        -Sql (Get-TicketboxC07MigratorRetirementVerificationSql) | Out-Null
    Assert-TicketboxC07RetiredRoleCatalog $HostAuthority $superuserPassword
    return [pscustomobject]@{
        Schema = "ticketbox-database-generation-projection-prepared-v1"
        OperationId = $operationId
        CandidateSha256 = [string]$Candidate.PayloadSha256
    }
}
