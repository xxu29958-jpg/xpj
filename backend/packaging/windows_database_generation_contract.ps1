#Requires -Version 5.1

$script:TicketboxDatabaseGenerationRootName = "database-generation"
$script:TicketboxDatabaseGenerationActiveIntentName = "active-intent.json"
$script:TicketboxDatabaseGenerationCurrentName = "current-generation.json"
$script:TicketboxDatabaseGenerationRuntimeDirectoryName = "database-generation-runtime"
$script:TicketboxDatabaseGenerationBackendServiceName = "TicketboxBackend"
$script:TicketboxDatabaseGenerationRuntimeAccount =
    "NT SERVICE\$script:TicketboxDatabaseGenerationBackendServiceName"
$script:TicketboxDatabaseGenerationBindingKey = "database_generation_binding"
$script:TicketboxDatabaseGenerationProgramRelativePath =
    "DATABASE_GENERATION_PROGRAM.json"
$script:TicketboxDatabaseMaintenanceHelperRelativePath =
    "ticketbox-database-maintenance.exe"
$script:TicketboxDatabaseGenerationAclAccounts = @(
    "SYSTEM",
    "BUILTIN\Administrators"
)
$script:TicketboxDatabaseGenerationOwnerAccount = "SYSTEM"

function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {
    param([Parameter(Mandatory = $true)][object]$Value)
    return $Value | ConvertTo-Json -Depth 12 -Compress
}

function Get-TicketboxDatabaseGenerationTextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Assert-TicketboxDatabaseGenerationLowerSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch '^[0-9a-f]{64}$') {
        throw "$Label 不是规范 lowercase SHA-256。"
    }
}

function Assert-TicketboxDatabaseGenerationUpperSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch '^[0-9A-F]{64}$') {
        throw "$Label 不是规范 uppercase SHA-256。"
    }
}

function Assert-TicketboxDatabaseGenerationExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$ExpectedNames,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) {
        throw "$Label 字段集合不是闭合合同。"
    }
}

function New-TicketboxDatabaseGenerationHostContract {
    param(
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$PgCtlPath,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$PgDumpPath,
        [Parameter(Mandatory = $true)][long]$PgDumpSize,
        [Parameter(Mandatory = $true)][string]$PgDumpSha256,
        [Parameter(Mandatory = $true)][string]$PgRestorePath,
        [Parameter(Mandatory = $true)][long]$PgRestoreSize,
        [Parameter(Mandatory = $true)][string]$PgRestoreSha256,
        [Parameter(Mandatory = $true)][object]$ReleaseConfig
    )
    $expectedPgDumpPath = Join-Path $InstallDir "pg\bin\pg_dump.exe"
    $expectedPgRestorePath = Join-Path $InstallDir "pg\bin\pg_restore.exe"
    if (
        -not (Test-TicketboxPathEquals $PgDumpPath $expectedPgDumpPath) -or
        -not (Test-TicketboxPathEquals $PgRestorePath $expectedPgRestorePath) -or
        $PgDumpSize -lt 1 -or
        $PgRestoreSize -lt 1 -or
        $PgDumpSha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $PgRestoreSha256 -cnotmatch '^[0-9a-f]{64}$'
    ) {
        throw "database generation PostgreSQL tool build identity 无效。"
    }
    return [pscustomobject][ordered]@{
        backend_service_name = $BackendServiceName
        data_root = $DataRoot
        install_dir = $InstallDir
        pg_ctl_path = $PgCtlPath
        pg_service_name = $PgServiceName
        pg_dump_path = $expectedPgDumpPath
        pg_dump_size = $PgDumpSize
        pg_dump_sha256 = $PgDumpSha256
        pg_restore_path = $expectedPgRestorePath
        pg_restore_size = $PgRestoreSize
        pg_restore_sha256 = $PgRestoreSha256
        release_config = $ReleaseConfig
    }
}

function New-TicketboxDatabaseGenerationProjectionContract {
    param(
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$EnvPath,
        [Parameter(Mandatory = $true)][int]$StopTimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$PgBin,
        [Parameter(Mandatory = $true)][string]$Timezone,
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$PgData,
        [Parameter(Mandatory = $true)][int]$DatabaseToolTimeoutMilliseconds
    )
    if ($BackendServiceName -cne $script:TicketboxDatabaseGenerationBackendServiceName) {
        throw "database generation backend service identity 不是唯一产品合同。"
    }
    return [pscustomobject][ordered]@{
        backend_service_name = $BackendServiceName
        env_path = $EnvPath
        stop_timeout_ms = $StopTimeoutMilliseconds
        backend_port = $BackendPort
        pg_bin = $PgBin
        timezone = $Timezone
        psql_path = $PsqlPath
        pg_data = $PgData
        database_tool_timeout_ms = $DatabaseToolTimeoutMilliseconds
    }
}

function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {
    param([Parameter(Mandatory = $true)][object]$ProjectionContract)

    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $ProjectionContract `
        -ExpectedNames @(
            "backend_service_name", "env_path", "stop_timeout_ms", "backend_port",
            "pg_bin", "timezone", "psql_path", "pg_data",
            "database_tool_timeout_ms"
        ) `
        -Label "database generation projection contract"
    $authority = [ordered]@{
        schema = "ticketbox-database-generation-projection-authority-v1"
        backend_service_name = [string]$ProjectionContract.backend_service_name
        env_path = [string]$ProjectionContract.env_path
        stop_timeout_ms = [int]$ProjectionContract.stop_timeout_ms
        backend_port = [int]$ProjectionContract.backend_port
        pg_bin = [string]$ProjectionContract.pg_bin
        timezone = [string]$ProjectionContract.timezone
        psql_path = [string]$ProjectionContract.psql_path
        pg_data = [string]$ProjectionContract.pg_data
        database_tool_timeout_ms =
            [int]$ProjectionContract.database_tool_timeout_ms
    }
    return Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $authority
    )
}

function Get-TicketboxDatabaseGenerationRuntimeCurrentPath {
    $machineRoot = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    $runtimeRoot = Join-Path `
        $machineRoot `
        $script:TicketboxDatabaseGenerationRuntimeDirectoryName
    return Join-Path $runtimeRoot $script:TicketboxDatabaseGenerationCurrentName
}
