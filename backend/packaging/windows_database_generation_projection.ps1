# Installed runtime projection of an already-published Generation CURRENT.

#Requires -Version 5.1

function New-TicketboxDatabaseGenerationRuntimeDatabaseUrl {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword
    )
    return Invoke-TicketboxC07WithPlainSecret -Secret $RuntimePassword -Action {
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
        [Parameter(Mandatory = $true)][object]$ProjectionContract
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
    $recovery = Read-PostgresBootstrapRecoveryState
    $lines += @(
        "ENABLE_HTTP_BOOTSTRAP=true",
        "HTTP_BOOTSTRAP_SECRET=$($recovery.HttpBootstrapSecret)"
    )
    Write-EnvNoBom -Path ([string]$ProjectionContract.env_path) -Lines $lines
}

function Write-TicketboxDatabaseGenerationRuntimeCurrent {
    param(
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$ProjectionContract
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $serviceName = [string]$ProjectionContract.backend_service_name
    if ($serviceName -cnotmatch "^[A-Za-z0-9_.-]{1,128}$") {
        throw "database generation runtime service identity 无效。"
    }
    $runtimeAccount = "NT SERVICE\$serviceName"
    $path = Get-TicketboxDatabaseGenerationRuntimeCurrentPath
    $root = Split-Path -Parent $path
    [void](Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $root `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount)
    $envelope = [ordered]@{
        schema = "ticketbox-database-generation-envelope-v1"
        kind = "current"
        payload_sha256 = [string]$Current.PayloadSha256
        payload = $Current.Payload
    }
    $text = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $text `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount `
        -ReplaceExisting
    $observed = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    if ([string]$observed.Text -cne $text) {
        throw "database generation runtime CURRENT 未通过原字节复读。"
    }
}

function Read-TicketboxDatabaseGenerationRuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Current.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Current.Payload.committed_revision -cne [string]$Intent.Payload.target_revision
    ) {
        throw "runtime projection 拒绝非 exact CURRENT。"
    }
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $serviceName = [string]$ProjectionContract.backend_service_name
    if ($serviceName -cnotmatch "^[A-Za-z0-9_.-]{1,128}$") {
        throw "database generation runtime service identity 无效。"
    }
    $runtimeAccount = "NT SERVICE\$serviceName"
    $envelope = [ordered]@{
        schema = "ticketbox-database-generation-envelope-v1"
        kind = "current"
        payload_sha256 = [string]$Current.PayloadSha256
        payload = $Current.Payload
    }
    $expectedCurrent = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope
    $observedCurrent = Read-TicketboxProtectedUtf8Artifact `
        -Path (Get-TicketboxDatabaseGenerationRuntimeCurrentPath) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    if ([string]$observedCurrent.Text -cne $expectedCurrent) {
        throw "database generation runtime CURRENT 与 durable CURRENT 不一致。"
    }
    $environment = Read-EnvMap ([string]$ProjectionContract.env_path)
    if (-not $environment.ContainsKey("DATABASE_URL")) {
        throw "CURRENT 已发布但 credential 已清理且 runtime projection 缺失。"
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
    return [pscustomobject]@{
        OperationId = [string]$Intent.Payload.operation_id
        CurrentSha256 = [string]$Current.PayloadSha256
        CommittedRevision = [string]$Current.Payload.committed_revision
        DatabaseUrl = [string]$connection.PersistedDatabaseUrl
    }
}

function Complete-TicketboxDatabaseGenerationRuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Current,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$SuperuserCapability,
        [Parameter(Mandatory = $true)][object]$ProjectionContract,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Current.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Current.Payload.committed_revision -cne [string]$Intent.Payload.target_revision
    ) {
        throw "runtime projection 拒绝非 exact CURRENT。"
    }
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $null = Assert-TicketboxC07SuperuserCapability `
        $SuperuserCapability $operationId $LifecycleLock
    $superuserPassword = $SuperuserCapability.Secret
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
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
    Assert-TicketboxC07RuntimeCredential $HostAuthority $Credentials.RuntimePassword
    Assert-TicketboxC07RoleCatalog $HostAuthority $SuperuserPassword
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $HostAuthority `
        -SuperuserPassword $SuperuserPassword `
        -IncludeManagedSchemaCurrencyAuthority
    $databaseUrl = New-TicketboxDatabaseGenerationRuntimeDatabaseUrl `
        $HostAuthority $Credentials.RuntimePassword
    Write-TicketboxDatabaseGenerationRuntimeEnvironment $databaseUrl $ProjectionContract
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
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation migrator retirement" `
        -Sql (Get-TicketboxC07MigratorRetirementSql) | Out-Null
    Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "database generation migrator retirement verification" `
        -Sql (Get-TicketboxC07MigratorRetirementVerificationSql) | Out-Null
    Assert-TicketboxC07RetiredRoleCatalog $HostAuthority $SuperuserPassword
    Write-TicketboxDatabaseGenerationRuntimeCurrent `
        -Current $Current `
        -LifecycleLock $LifecycleLock `
        -ProjectionContract $ProjectionContract
    return [pscustomobject]@{
        OperationId = [string]$Intent.Payload.operation_id
        CurrentSha256 = [string]$Current.PayloadSha256
        CommittedRevision = [string]$Current.Payload.committed_revision
        DatabaseUrl = [string]$connection.PersistedDatabaseUrl
    }
}
