#Requires -Version 5.1

$script:TicketboxDatabaseGenerationRootName = "database-generation"
$script:TicketboxDatabaseGenerationActiveIntentName = "active-intent.json"
$script:TicketboxDatabaseGenerationCurrentName = "current-generation.json"
$script:TicketboxDatabaseGenerationRuntimeDirectoryName = "database-generation-runtime"
$script:TicketboxDatabaseGenerationBindingKey = "database_generation_binding"
$script:TicketboxDatabaseGenerationProgramRelativePath =
    "DATABASE_GENERATION_PROGRAM.json"
$script:TicketboxDatabaseGenerationMigrationHelperRelativePath =
    "ticketbox-c07-migrator.exe"
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

function Assert-TicketboxDatabaseGenerationPreinstallEligibility {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][bool]$HasPersistedInstalledReleaseConfig,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$ExistingPathFacts
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $activeIntent = Read-TicketboxDatabaseGenerationActiveIntent `
        $StateRoot -AllowAbsent
    $current = Read-TicketboxDatabaseGenerationCurrent $StateRoot -AllowAbsent
    if ($null -eq $activeIntent) {
        $existingFacts = @()
        if ($null -ne $current) {
            $existingFacts += "database generation CURRENT"
        }
        if (Test-TicketboxServiceExists $PgServiceName) {
            $existingFacts += "PostgreSQL service"
        }
        if (Test-TicketboxServiceExists $BackendServiceName) {
            $existingFacts += "backend service"
        }
        if ($HasPersistedInstalledReleaseConfig) {
            $existingFacts += "installed release config"
        }
        foreach ($fact in $ExistingPathFacts) {
            Assert-TicketboxDatabaseGenerationExactProperties `
                $fact @("Label", "Path") "preinstall path fact"
            if ((Get-TicketboxPathEntryKindNoFollow ([string]$fact.Path)) -cne "Missing") {
                $existingFacts += [string]$fact.Label
            }
        }
        if ($existingFacts.Count -gt 0) {
            throw (
                "尚未实现既有安装 successor；首笔 generation intent 前已发现：" +
                ($existingFacts -join ", ")
            )
        }
    }
    elseif (
        $null -ne $current -and
        (
            [string]$current.Payload.operation_id -cne
                [string]$activeIntent.Payload.operation_id -or
            [string]$current.Payload.intent_sha256 -cne
                [string]$activeIntent.PayloadSha256
        )
    ) {
        throw "database generation CURRENT 不属于现有 active intent。"
    }
}

function Read-TicketboxDatabaseGenerationProgramContract {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        $ExpectedSha256 `
        "database generation program"
    $canonicalPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $bytes = [TicketboxExactTreeDeleteNativeMethods]::ReadExactFileBytes(
        $canonicalPath,
        16777216
    )
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actualSha256 = (
            [BitConverter]::ToString($sha.ComputeHash($bytes))
        ).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    if ($actualSha256 -cne $ExpectedSha256) {
        throw "database generation program 与安装器 build evidence 不一致。"
    }
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $program = $utf8.GetString($bytes) | ConvertFrom-Json
    }
    catch {
        throw "database generation program 不是 canonical JSON。"
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $program `
        @("revisions", "schema", "source_revision", "target_revision") `
        "database generation program"
    if (
        [string]$program.schema -cne
            "ticketbox-database-generation-program-v1" -or
        [string]$program.source_revision -cne "base" -or
        [string]$program.target_revision -cnotmatch
            '^[0-9]{8}_[0-9a-z_]+$' -or
        @($program.revisions).Count -lt 1
    ) {
        throw "database generation program root contract 无效。"
    }
    return [pscustomobject][ordered]@{
        RelativePath = $script:TicketboxDatabaseGenerationProgramRelativePath
        Size = [int64]$bytes.Length
        Sha256 = $actualSha256
        TargetRevision = [string]$program.target_revision
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

function New-TicketboxDatabaseGenerationReleaseContract {
    param(
        [Parameter(Mandatory = $true)][object]$InstallationIdentity,
        [Parameter(Mandatory = $true)][object]$ReleaseCandidate
    )
    if (
        [string]$InstallationIdentity.State -cne "PENDING" -or
        -not (Test-TicketboxInstallationIdentityReleaseMatches `
            $InstallationIdentity $ReleaseCandidate)
    ) {
        throw "database generation release contract 与 PENDING installation identity 不一致。"
    }
    return [pscustomobject][ordered]@{
        InstallationOperationId = [string]$InstallationIdentity.OperationId
        InstallationId = [string]$InstallationIdentity.InstallationId
        BackendVersionFloor = [string]$InstallationIdentity.BackendVersionFloor
        MigrationHelperPath = [string]$ReleaseCandidate.MigrationHelperPath
        MigrationHelperRelativePath =
            [string]$ReleaseCandidate.MigrationHelperRelativePath
        MigrationHelperSize = [int64]$ReleaseCandidate.MigrationHelperSize
        MigrationHelperSha256 = [string]$ReleaseCandidate.MigrationHelperSha256
        DatabaseGenerationProgramPath =
            [string]$ReleaseCandidate.DatabaseGenerationProgramPath
        DatabaseGenerationProgramRelativePath =
            [string]$ReleaseCandidate.DatabaseGenerationProgramRelativePath
        DatabaseGenerationProgramSize =
            [int64]$ReleaseCandidate.DatabaseGenerationProgramSize
        DatabaseGenerationProgramSha256 =
            [string]$ReleaseCandidate.DatabaseGenerationProgramSha256
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
        [AllowEmptyString()][string]$PublicBaseUrl,
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$PgData,
        [Parameter(Mandatory = $true)][int]$DatabaseToolTimeoutMilliseconds
    )
    if ($BackendServiceName -cnotmatch "^[A-Za-z0-9_.-]{1,128}$") {
        throw "database generation backend service name 无效。"
    }
    return [pscustomobject][ordered]@{
        backend_service_name = $BackendServiceName
        env_path = $EnvPath
        stop_timeout_ms = $StopTimeoutMilliseconds
        backend_port = $BackendPort
        pg_bin = $PgBin
        timezone = $Timezone
        public_base_url = $PublicBaseUrl
        psql_path = $PsqlPath
        pg_data = $PgData
        database_tool_timeout_ms = $DatabaseToolTimeoutMilliseconds
    }
}

function Get-TicketboxDatabaseGenerationRuntimeCurrentPath {
    $machineRoot = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    $runtimeRoot = Join-Path `
        $machineRoot `
        $script:TicketboxDatabaseGenerationRuntimeDirectoryName
    return Join-Path $runtimeRoot $script:TicketboxDatabaseGenerationCurrentName
}
