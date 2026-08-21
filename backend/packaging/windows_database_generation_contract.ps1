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
        [Parameter(Mandatory = $true)][object]$LifecycleEvidence,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$ExistingPathFacts
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationExactProperties `
        $LifecycleEvidence `
        @("current_sha256", "install_completed", "operation_id", "receipt_present", "schema") `
        "database generation lifecycle evidence"
    if (
        [string]$LifecycleEvidence.schema -cne
            "ticketbox-database-generation-lifecycle-evidence-v1" -or
        $LifecycleEvidence.receipt_present -isnot [bool] -or
        $LifecycleEvidence.install_completed -isnot [bool] -or
        (
            -not [bool]$LifecycleEvidence.receipt_present -and
            (
                [bool]$LifecycleEvidence.install_completed -or
                -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.operation_id) -or
                -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256)
            )
        ) -or
        (
            [bool]$LifecycleEvidence.receipt_present -and
            (
                ([guid][string]$LifecycleEvidence.operation_id).ToString("D") -cne
                    [string]$LifecycleEvidence.operation_id -or
                (
                    -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256) -and
                    [string]$LifecycleEvidence.current_sha256 -cnotmatch '^[0-9a-f]{64}$'
                )
            )
        )
    ) {
        throw "database generation lifecycle evidence 不是闭合合同。"
    }
    if ([bool]$LifecycleEvidence.install_completed) {
        throw "尚未实现 repair/reinstall；completed install 不得进入 fresh-only generation。"
    }
    $activeIntent = Read-TicketboxDatabaseGenerationActiveIntent `
        $StateRoot -AllowAbsent
    $current = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
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
    else {
        if (
            [bool]$LifecycleEvidence.receipt_present -and
            [string]$LifecycleEvidence.operation_id -cne
                [string]$activeIntent.Payload.operation_id
        ) {
            throw "lifecycle receipt 不属于现有 active intent。"
        }
        if ($null -ne $current) {
            if (
                [string]$current.Payload.operation_id -cne
                    [string]$activeIntent.Payload.operation_id -or
                [string]$current.Payload.intent_sha256 -cne
                    [string]$activeIntent.PayloadSha256
            ) {
                throw "database generation CURRENT 不属于现有 active intent。"
            }
            if (-not [bool]$LifecycleEvidence.receipt_present) {
                throw "CURRENT 缺少未完成 lifecycle receipt，拒绝猜测恢复。"
            }
            if (
                -not [string]::IsNullOrEmpty([string]$LifecycleEvidence.current_sha256) -and
                [string]$LifecycleEvidence.current_sha256 -cne
                    [string]$current.PayloadSha256
            ) {
                throw "lifecycle receipt 绑定了其他 database generation CURRENT。"
            }
        }
        elseif (
            -not [string]::IsNullOrEmpty(
                [string]$LifecycleEvidence.current_sha256
            )
        ) {
            throw "lifecycle receipt 声明了缺失的 database generation CURRENT。"
        }
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

function Get-TicketboxDatabaseGenerationHostAuthoritySha256 {
    param([Parameter(Mandatory = $true)][object]$HostAuthority)
    Assert-TicketboxDatabaseGenerationExactProperties `
        $HostAuthority `
        @(
            "DataVolumeIdentity", "PgCtlPath", "PgData", "PhysicalPgData",
            "Port", "PostmasterProcessId", "PsqlPath", "Schema",
            "ServiceName", "ServiceProcessId", "UsesRuntimeBinding"
        ) `
        "PostgreSQL host authority"
    if (
        [string]$HostAuthority.Schema -cne
            "ticketbox-postgresql-host-authority-v1" -or
        [int]$HostAuthority.ServiceProcessId -lt 1 -or
        [int]$HostAuthority.PostmasterProcessId -lt 1 -or
        [int]$HostAuthority.Port -lt 1 -or
        [int]$HostAuthority.Port -gt 65535
    ) {
        throw "PostgreSQL host authority shape 无效。"
    }
    return Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $HostAuthority
    )
}

function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationExactProperties `
        $Authority `
        @(
            "Closed", "HostAuthoritySha256", "IntentSha256", "OperationId",
            "Schema", "Secret"
        ) `
        "database generation maintenance authority"
    if (
        [string]$Authority.Schema -cne
            "ticketbox-database-generation-maintenance-authority-v1" -or
        [string]$Authority.OperationId -cne
            ([guid][string]$Intent.Payload.operation_id).ToString("D") -or
        [string]$Authority.IntentSha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Authority.HostAuthoritySha256 -cne
            (Get-TicketboxDatabaseGenerationHostAuthoritySha256 $HostAuthority) -or
        [bool]$Authority.Closed
    ) {
        throw "database generation maintenance authority 已关闭或绑定漂移。"
    }
    Assert-TicketboxPostgresqlSecureString `
        $Authority.Secret `
        "database generation maintenance authority"
    return $Authority
}

function Assert-TicketboxDatabaseGenerationReleaseBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity
    )
    $program = Get-TicketboxInstalledDatabaseGenerationProgram `
        -ReleaseIdentity $ReleaseIdentity
    if (
        [string]$Intent.Payload.operation_id -cne
            ([guid][string]$ReleaseIdentity.InstallationOperationId).ToString("D") -or
        [string]$Intent.Payload.installation_id -cne
            ([guid][string]$ReleaseIdentity.InstallationId).ToString("D") -or
        [string]$Intent.Payload.target_backend_version -cne
            [string]$ReleaseIdentity.BackendVersionFloor -or
        [string]$Intent.Payload.migration_helper_relative_path -cne
            [string]$ReleaseIdentity.MigrationHelperRelativePath -or
        [int64]$Intent.Payload.migration_helper_size -ne
            [int64]$ReleaseIdentity.MigrationHelperSize -or
        [string]$Intent.Payload.migration_helper_sha256 -cne
            ([string]$ReleaseIdentity.MigrationHelperSha256).ToLowerInvariant() -or
        [string]$Intent.Payload.generation_program_relative_path -cne
            [string]$ReleaseIdentity.DatabaseGenerationProgramRelativePath -or
        [int64]$Intent.Payload.generation_program_size -ne
            [int64]$ReleaseIdentity.DatabaseGenerationProgramSize -or
        [string]$Intent.Payload.generation_program_sha256 -cne
            ([string]$ReleaseIdentity.DatabaseGenerationProgramSha256).ToLowerInvariant() -or
        [string]$Intent.Payload.target_revision -cne
            [string]$program.target_revision
    ) {
        throw "database generation intent 与 installed release evidence 漂移。"
    }
}

function Throw-TicketboxDatabaseGenerationOperationFailure {
    param(
        [AllowNull()][object]$Primary,
        [AllowNull()][object]$Cleanup
    )
    if ($null -ne $Primary -and $null -ne $Cleanup) {
        $aggregate = [AggregateException]::new(
            "database generation primary operation and maintenance authority cleanup failed",
            @($Primary.Exception, $Cleanup.Exception)
        )
        foreach ($key in @("TicketboxC07FailureCode", "TicketboxC07FailureCodes")) {
            if ($Primary.Exception.Data.Contains($key)) {
                $aggregate.Data[$key] = $Primary.Exception.Data[$key]
            }
        }
        throw $aggregate
    }
    if ($null -ne $Primary) { throw $Primary }
    if ($null -ne $Cleanup) { throw $Cleanup }
}
