#Requires -Version 5.1
<#
.SYNOPSIS
  Prepare an existing Ticketbox installation before Inno replaces program files.

.DESCRIPTION
  Verifies that same-name Windows services belong to this InstallDir, stops the
  backend, creates and validates a pg_dump snapshot with the currently installed
  PostgreSQL tools, then stops PostgreSQL. Any failure restores the prior running
  state while the old program files are still intact and aborts the upgrade.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
    [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
    [Parameter(Mandatory = $true)][ValidateRange(1, 99)][int]$TargetPgMajor,
    [Parameter(Mandatory = $true)][string]$TargetBackendVersion,
    [string]$ReleaseConfigPath = "",
    [string]$InstalledReleaseConfigPath = "",
    [Parameter(Mandatory = $true)][string]$LifecycleReceiptPath,
    [int]$InstallerLockOwnerProcessId = 0,
    [switch]$RecoverPreparedInstall,
    [switch]$FilesReplaced,
    [switch]$CommitCompletedInstall,
    [switch]$MarkProgramFilesInstalledBackupPending,
    [switch]$PersistDatabaseGenerationIntentOnly,
    [string]$DatabaseGenerationProgramPath = "",
    [string]$DatabaseGenerationProgramSha256 = "",
    [long]$DatabaseGenerationMigrationHelperSize = 0,
    [string]$DatabaseGenerationMigrationHelperSha256 = "",
    [long]$DatabaseGenerationPgDumpSize = 0,
    [string]$DatabaseGenerationPgDumpSha256 = "",
    [long]$DatabaseGenerationPgRestoreSize = 0,
    [string]$DatabaseGenerationPgRestoreSha256 = "",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"
if (-not (Test-Path -LiteralPath $ReleaseConfigScript -PathType Leaf)) {
    throw "缺少 Windows release config 解析脚本：$ReleaseConfigScript"
}
. $ReleaseConfigScript
if ($ReleaseConfigPath.Trim().Length -eq 0) {
    $ReleaseConfigPath = Join-Path $ScriptDir "windows-release-config.json"
}
$TargetReleaseConfig = Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath
$DatabaseToolTimeoutMs = [int]$TargetReleaseConfig.database_tool_timeout_ms
$HasPersistedInstalledReleaseConfig = $false
$InstalledReleaseConfig = $TargetReleaseConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$PreparedServiceIdentityLifecycleReceipt = $null
$script:TicketboxPreparedRuntimeDatabaseRole = "ticketbox_runtime"

function Set-TicketboxInstalledReleaseConfiguration([object]$Config, [bool]$Persisted) {
    $script:InstalledReleaseConfig = $Config
    $script:HasPersistedInstalledReleaseConfig = $Persisted
    $script:PgServiceName = [string]$Config.pg_service_name
    $script:PgRecoveryServiceName = [string]$Config.pg_recovery_service_name
    $script:BackendServiceName = [string]$Config.backend_service_name
    $script:DbName = [string]$Config.db_name
    $script:DbRole = [string]$Config.db_role
    $script:OwnerRecoveryChannel = [string]$Config.owner_recovery_channel
    $script:InstalledStopTimeoutMs = [int]$Config.stop_timeout_ms
    $script:InstalledRestartDelayMs = [int]$Config.restart_delay_ms
}

function Initialize-TicketboxInstalledReleaseConfiguration {
    if (
        $InstalledReleaseConfigPath.Trim().Length -gt 0 -and
        (Test-Path -LiteralPath $InstalledReleaseConfigPath -PathType Leaf)
    ) {
        $installedConfig = Read-TicketboxWindowsReleaseConfig `
            $InstalledReleaseConfigPath `
            -AllowLegacyMissingOwnerRecoveryChannel
        Assert-TicketboxReleaseIdentityCompatible `
            -InstalledConfig $installedConfig `
            -TargetConfig $TargetReleaseConfig
        Set-TicketboxInstalledReleaseConfiguration -Config $installedConfig -Persisted $true
        return
    }
    $targetClone = $TargetReleaseConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    Set-TicketboxInstalledReleaseConfiguration -Config $targetClone -Persisted $false
}

function Get-TicketboxPreparedServiceIdentityShapes {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$AllowTargetSidTypePending
    )

    return [object[]]@(Get-TicketboxReleaseServiceIdentityShapes `
        -InstalledConfig $InstalledReleaseConfig `
        -TargetConfig $TargetReleaseConfig `
        -ServiceName $Name `
        -AllowTargetSidTypePending:$AllowTargetSidTypePending)
}

function Assert-TicketboxPreparedServiceIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$AllowTargetSidTypePending
    )

    $receiptAuthorizesPending =
        $null -ne $PreparedServiceIdentityLifecycleReceipt -and
        (Test-TicketboxLifecycleReceiptAuthorizesServiceSidPending `
            -Receipt $PreparedServiceIdentityLifecycleReceipt `
            -ServiceName $Name)
    return Assert-TicketboxServiceIdentityShape `
        -Name $Name `
        -AllowedShapes @(Get-TicketboxPreparedServiceIdentityShapes `
            -Name $Name `
            -AllowTargetSidTypePending:($AllowTargetSidTypePending -or $receiptAuthorizesPending))
}

function Assert-TicketboxPreparedDataRootAuthorityGate {
    param(
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $markerPath = Get-TicketboxDataRootMarkerPath $DataRoot
    $markerKind = Get-TicketboxPathEntryKindNoFollow $markerPath
    if ($markerKind -ceq "File") {
        if ($Mode -ceq "fresh_install") {
            Repair-TicketboxRecoverableDataRootMarkerAcl `
                -DataRoot $DataRoot `
                -InstallDir $InstallDir `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount | Out-Null
            Assert-TicketboxProtectedDataRootMarker `
                -DataRoot $DataRoot `
                -InstallDir $InstallDir `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
        }
        else {
            # Preserved/repair modes prove legacy authority below before mutation.
            Assert-TicketboxDataRootMarker `
                -DataRoot $DataRoot `
                -InstallDir $InstallDir `
                -AllowLegacyV1
        }
        return
    }
    if ($markerKind -cne "Missing") {
        throw "DataRoot marker 不是普通文件或缺失路径，拒绝安装准备。"
    }
    if ($Mode -ceq "fresh_install") {
        throw "fresh install 只接受 holder 已发布权威 marker 的新 DataRoot；拒绝收编非空 markerless 目录。"
    }
    throw "既有 DataRoot 缺少 v1/v2 marker；普通安装器拒绝重新铸造权威，请使用独立隔离恢复/导入流程。"
}

function Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$ExpectedBackendServiceName,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $markerPath = Get-TicketboxDataRootMarkerPath $DataRoot
    $markerKind = Get-TicketboxPathEntryKindNoFollow $markerPath
    if ($markerKind -ceq "Missing") {
        return
    }
    if ($markerKind -cne "File") {
        throw "DataRoot marker 不是普通文件，拒绝安装生命周期恢复。"
    }
    if ((Get-TicketboxPathAcl $markerPath).AreAccessRulesProtected) {
        Assert-TicketboxProtectedDataRootMarker `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -FullControlAccounts $FullControlAccounts `
            -AclPhase backend_read_optional `
            -ExpectedBackendServiceName $ExpectedBackendServiceName `
            -OwnerAccount $OwnerAccount
        return
    }
    Repair-TicketboxRecoverableDataRootMarkerAcl `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount | Out-Null
}

Set-TicketboxInstalledReleaseConfiguration -Config $InstalledReleaseConfig -Persisted $false
$ServiceWaitArguments = @{
    TimeoutMilliseconds = [int]$TargetReleaseConfig.service_state_timeout_ms
    PollMilliseconds = [int]$TargetReleaseConfig.service_poll_interval_ms
}
$PreUpgradePostgresReadyTimeoutMs = [int]$TargetReleaseConfig.pre_upgrade_postgres_ready_timeout_ms
$PreUpgradePostgresReadyPollIntervalMs = [int]$TargetReleaseConfig.pre_upgrade_postgres_ready_poll_interval_ms
$LifecycleScript = Join-Path $ScriptDir "windows_service_lifecycle.ps1"
if (-not (Test-Path -LiteralPath $LifecycleScript -PathType Leaf)) {
    throw "缺少 Windows 服务生命周期脚本：$LifecycleScript"
}
. $LifecycleScript
$SafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"
if (-not (Test-Path -LiteralPath $SafetyScript -PathType Leaf)) {
    throw "缺少 Windows 安装安全脚本：$SafetyScript"
}
. $SafetyScript
$ReceiptScript = Join-Path $ScriptDir "windows_lifecycle_receipt.ps1"
if (-not (Test-Path -LiteralPath $ReceiptScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期回执脚本：$ReceiptScript"
}
. $ReceiptScript
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
if (-not (Test-Path -LiteralPath $LockScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期锁脚本：$LockScript"
}
. $LockScript
$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"
if (-not (Test-Path -LiteralPath $DatabaseSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 数据库安全脚本：$DatabaseSafetyScript"
}
. $DatabaseSafetyScript
$BuildProvenanceScript = Join-Path $ScriptDir "windows_build_provenance.ps1"
if (-not (Test-Path -LiteralPath $BuildProvenanceScript -PathType Leaf)) {
    throw "缺少 Windows build provenance 脚本：$BuildProvenanceScript"
}
. $BuildProvenanceScript
$PgRecoveryToolsScript = Join-Path $ScriptDir "windows_pg_recovery_tools.ps1"
if (-not (Test-Path -LiteralPath $PgRecoveryToolsScript -PathType Leaf)) {
    throw "缺少 Windows PostgreSQL 恢复工具脚本：$PgRecoveryToolsScript"
}
. $PgRecoveryToolsScript

$PgBin = Join-Path $InstallDir "pg\bin"
$PgData = Join-Path $DataRoot "pgdata"
$AppData = Join-Path $DataRoot "app"
$InstallerState = Get-TicketboxInstallerStateDirectory
$EnvPath = Join-Path $AppData ".env"
$BackupDir = Join-Path $DataRoot "installer-backups"
$LogDir = Join-Path $AppData "logs"
$PgCtl = Join-Path $PgBin "pg_ctl.exe"
$PgReady = Join-Path $PgBin "pg_isready.exe"
$PgDump = Join-Path $PgBin "pg_dump.exe"
$PgRestore = Join-Path $PgBin "pg_restore.exe"
$Psql = Join-Path $PgBin "psql.exe"
$InitdbExe = Join-Path $PgBin "initdb.exe"
$ShawlExe = Join-Path $InstallDir "shawl\shawl.exe"
$BackendExe = Join-Path $InstallDir "program\ticketbox-backend\ticketbox-backend.exe"
$BootstrapExposureRecoveryGuardPath = Join-Path $DataRoot "bootstrap-exposure-recovery-pending"
$InstallerRuntimeRecoveryGuardPath = Get-TicketboxInstallerRuntimeRecoveryGuardPath
$PgBootstrapRecoveryPath = Join-Path $AppData ".postgres-bootstrap-password"
$InitdbPasswordPath = Get-TicketboxInitdbPasswordPath $DataRoot
$InitdbServiceReceiptPath = Get-TicketboxInitdbServiceReceiptPath
$RecoveryRequiredPath = Join-Path $InstallerState "installer-recovery-required.json"
$LegacyRecoveryRequiredPath = Join-Path $AppData "installer-recovery-required.json"
$InstalledBuildManifestPath = Join-Path $InstallDir "installer\BUILD_PROVENANCE.json"
$RuntimeDataRoot = Get-TicketboxRuntimeDataRootPath
$ServicePgData = $PgData
$ServiceAppData = $AppData
$ServiceLogDir = $LogDir
$ServiceDataRootMarkerPath = Join-Path $RuntimeDataRoot $script:TicketboxDataRootMarkerName
$ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
$ServiceDataVolumeIdentity = ""
$AllowMissingRuntimeDataAuthority = $true
$RuntimeDataBindingPresent = $false

function Get-TicketboxInstalledDatabaseGenerationAuthorityPath {
    $path = Join-Path $InstallDir "installer\windows_database_generation.ps1"
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw "installed database generation authority 不是可信普通文件：$path"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    return $path
}

function Get-TicketboxBootstrapDatabaseGenerationAuthorityPath {
    $path = Join-Path $ScriptDir "windows_database_generation.ps1"
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw "bootstrap database generation authority 不是可信普通文件：$path"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    return $path
}

function Set-TicketboxPreparedRuntimeServiceContract {
    $bindingDirectory = Get-TicketboxRuntimeDataBindingDirectory
    $bindingKind = Get-TicketboxPathEntryKindNoFollow $bindingDirectory
    if ($bindingKind -ceq "Missing") {
        $script:ServicePgData = $PgData
        $script:ServiceAppData = $AppData
        $script:ServiceLogDir = $LogDir
        $script:ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
        $script:ServiceDataVolumeIdentity = ""
        $script:AllowMissingRuntimeDataAuthority = $true
        $script:RuntimeDataBindingPresent = $false
        return
    }
    $serviceAccounts = @(
        (Get-TicketboxServiceSid $PgServiceName),
        (Get-TicketboxServiceSid $BackendServiceName)
    )
    $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath
    # This runs under the installer lifecycle lock and recognizes only the
    # exact Volume-GUID junction emitted by the previous trusted package.
    Repair-TicketboxLegacyMalformedRuntimeDataBindingIfNeeded `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $serviceAccounts `
        -DataRootMarkerAclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName | Out-Null
    if (
        $bindingKind -ceq "Directory" -and
        (Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot) -ceq "Missing"
    ) {
        $validatedBindingDirectory = Assert-TicketboxRuntimeDataBindingDomain `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $validatedBindingDirectory `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -InheritableReadExecuteAccounts $serviceAccounts `
            -OwnerAccount "SYSTEM"
        if (@(Get-ChildItem -LiteralPath $validatedBindingDirectory -Force).Count -ne 0) {
            throw "runtime DataRoot binding provisioning 断点含有未知 artifact。"
        }
        # A failed exact legacy repair can leave this same protected, empty
        # provisioning boundary. Recreate the projection here, before service
        # contract recovery, so a service already bound to the stable runtime
        # path cannot strand every later installer retry.
        Initialize-TicketboxRuntimeDataBinding `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -ServiceReadExecuteAccounts $serviceAccounts `
            -DataRootMarkerAclPhase backend_read_optional `
            -ExpectedBackendServiceName $BackendServiceName | Out-Null
    }
    $binding = Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $serviceAccounts `
        -DataRootMarkerAclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName
    $script:ServicePgData = $binding.RuntimePgData
    $script:ServiceAppData = $binding.RuntimeAppData
    $script:ServiceLogDir = Join-Path $binding.RuntimeAppData "logs"
    $script:ServiceDataRootMarkerPath = Join-Path `
        $binding.RuntimeDataRoot `
        $script:TicketboxDataRootMarkerName
    $script:ServiceBootstrapExposureRecoveryGuardPath =
        Get-TicketboxRuntimeBootstrapRecoveryGuardPath $binding.RuntimeDataRoot
    $script:ServiceDataVolumeIdentity = $binding.DataVolumeIdentity
    $script:AllowMissingRuntimeDataAuthority = $false
    $script:RuntimeDataBindingPresent = $true
}

function Set-TicketboxActivePgTools([string]$PgHome) {
    $script:PgBin = Join-Path $PgHome "bin"
    $script:PgCtl = Join-Path $script:PgBin "pg_ctl.exe"
    $script:PgReady = Join-Path $script:PgBin "pg_isready.exe"
    $script:PgDump = Join-Path $script:PgBin "pg_dump.exe"
    $script:PgRestore = Join-Path $script:PgBin "pg_restore.exe"
    $script:Psql = Join-Path $script:PgBin "psql.exe"
}

$InstalledPgHome = Join-Path $InstallDir "pg"
Set-TicketboxActivePgTools $InstalledPgHome

function Assert-Admin {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator
    )
    if (-not $admin) {
        throw "需要管理员权限执行升级前检查。"
    }
}

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "既有安装缺少 $Label：$Path。请先修复旧版本，再执行升级。"
    }
}

function Assert-TicketboxTargetPgMajor {
    $pgVersionPath = Join-Path $PgData "PG_VERSION"
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        return
    }
    $versionText = (Get-Content -LiteralPath $pgVersionPath -Encoding ASCII -Raw).Trim()
    $installedMajor = 0
    if (-not [int]::TryParse($versionText, [ref]$installedMajor)) {
        throw "既有 PostgreSQL PG_VERSION 无效，复制前检查已中止：$pgVersionPath"
    }
    if ($installedMajor -ne $TargetPgMajor) {
        throw "既有 PostgreSQL major 为 $installedMajor，安装包目标 major 为 $TargetPgMajor；复制前检查已中止。PG major 升级需要独立迁移流程。"
    }
}

function Assert-TicketboxPortAvailableForMissingService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][bool]$HasService
    )
    if ($HasService) {
        return
    }
    $listeners = @(Get-TicketboxListeningProcessIds $Port)
    if ($listeners.Count -gt 0) {
        throw "Windows 服务 $Name 缺失，但对应端口 $Port 已被 PID $($listeners -join ',') 占用；复制前检查已中止。"
    }
}

function Repair-TicketboxPreflightInstallAcl([string[]]$ServiceReadAccounts) {
    Initialize-TicketboxSecureInstallRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $ServiceReadAccounts | Out-Null
}

function Repair-TicketboxInterruptedPayloadLeaseAcl {
    $serviceReadAccounts = @()
    if (Test-TicketboxServiceExists $PgServiceName) {
        $serviceReadAccounts += "NT SERVICE\$PgServiceName"
    }
    if (Test-TicketboxServiceExists $BackendServiceName) {
        $serviceReadAccounts += "NT SERVICE\$BackendServiceName"
    }
    Remove-TicketboxInterruptedInstalledPayloadMutationDeny `
        -InstallDir $InstallDir `
        -InstallerManifestPath $InstalledBuildManifestPath `
        -ExpectedPgMajor $TargetPgMajor `
        -ServiceReadExecuteAccounts $serviceReadAccounts | Out-Null
    Repair-TicketboxPreflightInstallAcl `
        -ServiceReadAccounts $serviceReadAccounts
}

function New-TicketboxPrepareAggregateFailure {
    param(
        [AllowNull()][Exception]$OperationFailure,
        [Parameter(Mandatory = $true)][Exception[]]$SecondaryFailures,
        [Parameter(Mandatory = $true)]
        [ValidateSet("compensation", "finalization")][string]$FailureKind
    )

    [Exception[]]$causes = @()
    if ($null -ne $OperationFailure) {
        if ($OperationFailure -is [AggregateException]) {
            $causes += @($OperationFailure.InnerExceptions)
        }
        else {
            $causes += $OperationFailure
        }
    }
    $causes += @($SecondaryFailures)
    if ($causes.Count -eq 0) {
        throw "安装预检异常聚合器缺少原始异常。"
    }
    $aggregateFailure = [AggregateException]::new(
        (
            "安装预检的 $FailureKind 阶段未完整完成；" +
            "全部原始异常均已保留。"
        ),
        $causes
    )
    $aggregateFailure.Data["TicketboxPrepareFailureKind"] = $FailureKind
    if ($FailureKind -ceq "compensation") {
        $aggregateFailure.Data["TicketboxPrepareCompensationFailed"] = $true
    }
    else {
        $aggregateFailure.Data["TicketboxPrepareFinalizationFailed"] = $true
    }
    if ($null -ne $OperationFailure) {
        foreach ($key in @(
            "TicketboxC07FailureCode",
            "TicketboxPrepareCompensationFailed"
        )) {
            if ($OperationFailure.Data.Contains($key)) {
                $aggregateFailure.Data[$key] = $OperationFailure.Data[$key]
            }
        }
    }
    $failureCodes = @(
        $causes |
            ForEach-Object {
                if ($_.Data.Contains("TicketboxC07FailureCode")) {
                    [string]$_.Data["TicketboxC07FailureCode"]
                }
            } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    if ($failureCodes.Count -gt 0) {
        $aggregateFailure.Data["TicketboxC07FailureCodes"] =
            $failureCodes -join ","
    }
    return $aggregateFailure
}

function Set-TicketboxPreparedServiceDemandStart([string]$Name, [string]$ExpectedExecutable) {
    Set-TicketboxOwnedServiceDemandStartIfExists `
        -Name $Name `
        -ExpectedExecutable $ExpectedExecutable
}

function Read-EnvMap([string]$Path) {
    $map = @{}
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split(@("="), 2, [System.StringSplitOptions]::None)
        $map[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $map
}

function Get-TicketboxPreparedApplicationDatabaseConnection {
    param([Parameter(Mandatory = $true)][string]$DatabaseUrl)

    $persistedDatabaseUrl = ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    $libpqUrl = Assert-TicketboxLocalDatabaseUrl `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort
    $builder = New-Object System.UriBuilder($libpqUrl)
    $role = [System.Uri]::UnescapeDataString($builder.UserName)
    if (
        $role -cne $DbRole -and
        $role -cne $script:TicketboxPreparedRuntimeDatabaseRole
    ) {
        throw "DATABASE_URL 的 PostgreSQL 角色不属于已登记的 legacy/runtime authority。"
    }
    $connection = Get-TicketboxLocalDatabaseConnection `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort `
        -ExpectedDatabase $DbName `
        -ExpectedRole $role
    return [pscustomobject]@{
        DatabaseUrl = $connection.DatabaseUrl
        PersistedDatabaseUrl = $connection.PersistedDatabaseUrl
        Password = $connection.Password
        Role = $role
    }
}

function Assert-TicketboxPreparedServiceRuntimeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedPgData,
        [Parameter(Mandatory = $true)][string]$ExpectedAppData,
        [Parameter(Mandatory = $true)][string]$ExpectedLogDir,
        [string]$ExpectedDataRootMarkerPath = "",
        [string]$ExpectedDataVolumeIdentity = "",
        [int]$ExpectedStopTimeoutMs = $InstalledStopTimeoutMs,
        [int]$ExpectedRestartDelayMs = $InstalledRestartDelayMs,
        [switch]$AllowMissingRuntimeDataAuthority
    )
    if ($Name -eq $PgServiceName) {
        Assert-TicketboxPgServiceCommand `
            -Name $Name `
            -ExpectedExecutable $PgCtl `
            -ExpectedServiceName $PgServiceName `
            -ExpectedDataRoot $ExpectedPgData
        return
    }
    Assert-TicketboxShawlServiceCommand `
        -Name $Name `
        -ExpectedExecutable $ShawlExe `
        -ExpectedServiceName $BackendServiceName `
        -ExpectedCwd $ExpectedAppData `
        -ExpectedPayload $BackendExe `
        -ExpectedDependency $PgServiceName `
        -ExpectedLogDir $ExpectedLogDir `
        -ExpectedPgDumpPath $PgDump `
        -ExpectedPgRestorePath $PgRestore `
        -ExpectedBootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath `
        -ExpectedInstallerRecoveryGuardPath $InstallerRuntimeRecoveryGuardPath `
        -ExpectedDataRootMarkerPath $ExpectedDataRootMarkerPath `
        -ExpectedDataVolumeIdentity $ExpectedDataVolumeIdentity `
        -ExpectedOwnerRecoveryChannel $OwnerRecoveryChannel `
        -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
        -ExpectedRestartDelayMs $ExpectedRestartDelayMs `
        -AllowMissingInstallerRecoveryGuard `
        -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority `
        -AllowMissingOwnerRecoveryChannel
}

function Assert-ExpectedServiceConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowLegacyRuntimeDataContract
    )
    if (-not (Test-TicketboxServiceExists $Name)) {
        return
    }
    $expectedExecutable = if ($Name -eq $PgServiceName) { $PgCtl } else { $ShawlExe }
    Assert-TicketboxServiceOwnership -Name $Name -ExpectedExecutable $expectedExecutable | Out-Null
    Assert-TicketboxPreparedServiceIdentity -Name $Name | Out-Null
    $targetError = $null
    try {
        Assert-TicketboxPreparedServiceRuntimeCommand `
            -Name $Name `
            -ExpectedPgData $ServicePgData `
            -ExpectedAppData $ServiceAppData `
            -ExpectedLogDir $ServiceLogDir `
            -ExpectedDataRootMarkerPath $ServiceDataRootMarkerPath `
            -ExpectedDataVolumeIdentity $ServiceDataVolumeIdentity `
            -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority
        return
    }
    catch {
        $targetError = $_
    }
    if ($AllowTargetPolicyFallback -and $Name -eq $BackendServiceName) {
        try {
            Assert-TicketboxPreparedServiceRuntimeCommand `
                -Name $Name `
                -ExpectedPgData $ServicePgData `
                -ExpectedAppData $ServiceAppData `
                -ExpectedLogDir $ServiceLogDir `
                -ExpectedDataRootMarkerPath $ServiceDataRootMarkerPath `
                -ExpectedDataVolumeIdentity $ServiceDataVolumeIdentity `
                -ExpectedStopTimeoutMs ([int]$TargetReleaseConfig.stop_timeout_ms) `
                -ExpectedRestartDelayMs ([int]$TargetReleaseConfig.restart_delay_ms) `
                -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority
            return
        }
        catch { }
    }
    if (-not $AllowLegacyRuntimeDataContract -or -not $RuntimeDataBindingPresent) {
        throw $targetError
    }
    $legacyError = $null
    try {
        Assert-TicketboxPreparedServiceRuntimeCommand `
            -Name $Name `
            -ExpectedPgData $PgData `
            -ExpectedAppData $AppData `
            -ExpectedLogDir $LogDir `
            -AllowMissingRuntimeDataAuthority
        return
    }
    catch {
        $legacyError = $_
    }
    if ($AllowTargetPolicyFallback -and $Name -eq $BackendServiceName) {
        try {
            Assert-TicketboxPreparedServiceRuntimeCommand `
                -Name $Name `
                -ExpectedPgData $PgData `
                -ExpectedAppData $AppData `
                -ExpectedLogDir $LogDir `
                -ExpectedStopTimeoutMs ([int]$TargetReleaseConfig.stop_timeout_ms) `
                -ExpectedRestartDelayMs ([int]$TargetReleaseConfig.restart_delay_ms) `
                -AllowMissingRuntimeDataAuthority
            return
        }
        catch { }
    }
    throw "Windows 服务 $Name 不匹配 runtime binding 恢复允许的任一精确合同。target=$($targetError.Exception.Message); legacy=$($legacyError.Exception.Message)"
}

function Get-TicketboxRecoveryServiceDataAclShape {
    param(
        [bool]$IncludeRecoveryService,
        [string]$RecoveryServiceSid = ""
    )

    $rootReadAccounts = @()
    $pgAccounts = @("SYSTEM", "BUILTIN\Administrators")
    if (Test-TicketboxServiceExists $PgServiceName) {
        $rootReadAccounts += "NT SERVICE\$PgServiceName"
        $pgAccounts += "NT SERVICE\$PgServiceName"
    }
    if (Test-TicketboxServiceExists $BackendServiceName) {
        $rootReadAccounts += "NT SERVICE\$BackendServiceName"
    }
    if ($IncludeRecoveryService) {
        if ([string]::IsNullOrWhiteSpace($RecoveryServiceSid)) {
            $RecoveryServiceSid = Get-TicketboxServiceSid $PgRecoveryServiceName
        }
        if ($RecoveryServiceSid -notmatch '^S-1-5-80-(?:[0-9]+-){4}[0-9]+$') {
            throw "PostgreSQL 恢复服务 SID 不是规范的每服务 SID。"
        }
        $rootReadAccounts += $RecoveryServiceSid
        $pgAccounts += $RecoveryServiceSid
    }
    return [pscustomobject]@{
        RootReadAccounts = @($rootReadAccounts)
        PgAccounts = @($pgAccounts)
        ToolReadAccounts = if ($IncludeRecoveryService) { @($RecoveryServiceSid) } else { @() }
    }
}

function Assert-TicketboxRecoveryServiceDataAcl {
    param(
        [bool]$IncludeRecoveryService,
        [string]$RecoveryServiceSid = ""
    )

    $shape = Get-TicketboxRecoveryServiceDataAclShape `
        -IncludeRecoveryService $IncludeRecoveryService `
        -RecoveryServiceSid $RecoveryServiceSid
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $DataRoot `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -ReadExecuteAccounts $shape.RootReadAccounts
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $PgData `
        -FullControlAccounts $shape.PgAccounts
    Assert-TicketboxPgRecoveryToolset `
        -ExpectedMajor $TargetPgMajor `
        -ReadExecuteAccounts $shape.ToolReadAccounts | Out-Null
}

function Assert-TicketboxRecoveryServiceAclTransition([string]$RecoveryServiceSid) {
    $clean = Get-TicketboxRecoveryServiceDataAclShape $false
    $transitional = Get-TicketboxRecoveryServiceDataAclShape `
        -IncludeRecoveryService $true `
        -RecoveryServiceSid $RecoveryServiceSid
    try {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $DataRoot `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -ReadExecuteAccounts $clean.RootReadAccounts
    }
    catch {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $DataRoot `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -ReadExecuteAccounts $transitional.RootReadAccounts
    }
    try {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $PgData `
            -FullControlAccounts $clean.PgAccounts
    }
    catch {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $PgData `
            -FullControlAccounts $transitional.PgAccounts
    }
    try {
        Assert-TicketboxPgRecoveryToolset -ExpectedMajor $TargetPgMajor | Out-Null
    }
    catch {
        Assert-TicketboxPgRecoveryToolset `
            -ExpectedMajor $TargetPgMajor `
            -ReadExecuteAccounts $transitional.ToolReadAccounts | Out-Null
    }
}

function Set-TicketboxRecoveryServiceDataAcl {
    param(
        [bool]$IncludeRecoveryService,
        [string]$RecoveryServiceSid = ""
    )

    $shape = Get-TicketboxRecoveryServiceDataAclShape `
        -IncludeRecoveryService $IncludeRecoveryService `
        -RecoveryServiceSid $RecoveryServiceSid
    Set-TicketboxExactDirectoryAcl `
        -Path $DataRoot `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -ReadExecuteAccounts $shape.RootReadAccounts
    Set-TicketboxExactDirectoryAcl `
        -Path $PgData `
        -Accounts $shape.PgAccounts `
        -Recurse
    Set-TicketboxPgRecoveryAcl -ReadExecuteAccounts $shape.ToolReadAccounts
    Assert-TicketboxRecoveryServiceDataAcl `
        -IncludeRecoveryService $IncludeRecoveryService `
        -RecoveryServiceSid $RecoveryServiceSid
}

function Assert-TicketboxRecoveryPgServiceConfiguration {
    $recoveryHome = Get-TicketboxPgRecoveryHome
    $recoveryPgCtl = Join-Path $recoveryHome "bin\pg_ctl.exe"
    Assert-TicketboxServiceOwnership `
        -Name $PgRecoveryServiceName `
        -ExpectedExecutable $recoveryPgCtl | Out-Null
    Assert-TicketboxPreparedServiceIdentity `
        -Name $PgRecoveryServiceName | Out-Null
    Assert-TicketboxPgServiceCommand `
        -Name $PgRecoveryServiceName `
        -ExpectedExecutable $recoveryPgCtl `
        -ExpectedServiceName $PgRecoveryServiceName `
        -ExpectedDataRoot $PgData
}

function Register-TicketboxRecoveryPgService {
    $recoveryHome = Get-TicketboxPgRecoveryHome
    $recoveryPgCtl = Join-Path $recoveryHome "bin\pg_ctl.exe"
    if (Test-TicketboxServiceExists $PgRecoveryServiceName) {
        Assert-TicketboxRecoveryPgServiceConfiguration
        return
    }
    $imagePath = New-TicketboxPgServiceImagePath `
        -PgCtlPath $recoveryPgCtl `
        -ServiceName $PgRecoveryServiceName `
        -DataRoot $PgData
    Invoke-TicketboxScChecked @(
        "create",
        $PgRecoveryServiceName,
        "binPath=",
        $imagePath,
        "start=",
        "demand",
        "obj=",
        (Get-TicketboxReleaseServiceLogonAccount `
            -Config $TargetReleaseConfig `
            -ServiceName $PgRecoveryServiceName)
    ) | Out-Null
    Set-TicketboxServiceIdentityContract `
        -Name $PgRecoveryServiceName `
        -LogonAccount (Get-TicketboxReleaseServiceLogonAccount `
            -Config $TargetReleaseConfig `
            -ServiceName $PgRecoveryServiceName) `
        -SidType (Get-TicketboxReleaseServiceSidType $TargetReleaseConfig)
    Set-TicketboxRecoveryServiceDataAcl $true
    Assert-TicketboxRecoveryPgServiceConfiguration
}

function Remove-TicketboxRecoveryPgServiceIfExists {
    $serviceExists = Test-TicketboxServiceExists $PgRecoveryServiceName
    $recoveryHome = Get-TicketboxPgRecoveryHome
    $recoveryRootKind = Get-TicketboxPathEntryKindNoFollow (Get-TicketboxPgRecoveryRoot)
    if (-not $serviceExists -and $recoveryRootKind -ceq "Missing") { return }
    $recoveryServiceSid = Get-TicketboxServiceSid $PgRecoveryServiceName
    Assert-TicketboxRecoveryServiceAclTransition $recoveryServiceSid
    $recoveryPgCtl = Join-Path $recoveryHome "bin\pg_ctl.exe"
    if ($serviceExists) {
        Assert-TicketboxRecoveryPgServiceConfiguration
        Remove-TicketboxOwnedServiceIfExists `
            -Name $PgRecoveryServiceName `
            -ExpectedExecutable $recoveryPgCtl `
            -ExpectedRuntimeExecutables @(
                $recoveryPgCtl,
                (Join-Path $recoveryHome "bin\postgres.exe")
            ) `
            @ServiceWaitArguments
    }
    Set-TicketboxRecoveryServiceDataAcl `
        -IncludeRecoveryService $false `
        -RecoveryServiceSid $recoveryServiceSid
}

function Assert-TicketboxDeferredPreservedPgServiceConfiguration {
    Assert-TicketboxServiceOwnership `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl | Out-Null
    Assert-TicketboxPreparedServiceIdentity -Name $PgServiceName | Out-Null
    Assert-TicketboxPgServiceCommand `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedServiceName $PgServiceName `
        -ExpectedDataRoot $PgData
}

function Remove-TicketboxDeferredPreservedPgServiceIfExists {
    if (-not (Test-TicketboxServiceExists $PgServiceName)) { return }
    Assert-TicketboxDeferredPreservedPgServiceConfiguration
    Remove-TicketboxOwnedServiceIfExists `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
        @ServiceWaitArguments
}

function Assert-TicketboxPreparedServiceContracts {
    param(
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowLegacyRuntimeDataContract
    )
    $hasPgService = Test-TicketboxServiceExists $PgServiceName
    $hasBackendService = Test-TicketboxServiceExists $BackendServiceName
    if (-not $hasPgService) {
        Assert-TicketboxRuntimeAbsent `
            -Name $PgServiceName `
            -RuntimePort $PgPort `
            -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe"))
    }
    if (-not $hasBackendService) {
        Assert-TicketboxRuntimeAbsent `
            -Name $BackendServiceName `
            -RuntimePort $BackendPort `
            -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)
    }
    if ($hasPgService) {
        Assert-ExpectedServiceConfiguration `
            -Name $PgServiceName `
            -AllowTargetPolicyFallback:$AllowTargetPolicyFallback `
            -AllowLegacyRuntimeDataContract:$AllowLegacyRuntimeDataContract
    }
    if ($hasBackendService) {
        Assert-ExpectedServiceConfiguration `
            -Name $BackendServiceName `
            -AllowTargetPolicyFallback:$AllowTargetPolicyFallback `
            -AllowLegacyRuntimeDataContract:$AllowLegacyRuntimeDataContract
    }
}

function Test-PgDataProcessReady([int]$ProbeTimeoutSeconds) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $probeTimeoutMilliseconds = [int][Math]::Min(
            [long]$DatabaseToolTimeoutMs,
            [long][Math]::Max(1000, $ProbeTimeoutSeconds * 1000)
        )
        $statusResult = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $PgCtl `
            -Arguments @('status', '-D', $PgData) `
            -TimeoutMilliseconds $probeTimeoutMilliseconds `
            -Label 'pg_ctl pre-upgrade readiness status'
        if ($statusResult.ExitCode -ne 0) {
            return $false
        }
        $pidLines = @(Get-Content -LiteralPath (Join-Path $PgData "postmaster.pid") -ErrorAction SilentlyContinue)
        if ($pidLines.Count -lt 4 -or $pidLines[3].Trim() -ne [string]$PgPort) {
            return $false
        }
        $readyResult = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $PgReady `
            -Arguments @('-h', '127.0.0.1', '-p', [string]$PgPort, '-q', '-t', [string]$ProbeTimeoutSeconds) `
            -TimeoutMilliseconds $probeTimeoutMilliseconds `
            -Label 'pg_isready pre-upgrade readiness probe'
        return $readyResult.ExitCode -eq 0
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

function Wait-PgReady {
    $deadline = New-TicketboxWaitDeadline $PreUpgradePostgresReadyTimeoutMs
    do {
        $remaining = [Math]::Max(1, $PreUpgradePostgresReadyTimeoutMs - $deadline.ElapsedMilliseconds)
        $probeBudget = [int][Math]::Min([long]$PreUpgradePostgresReadyPollIntervalMs, [long]$remaining)
        if (Test-PgDataProcessReady (ConvertTo-TicketboxTimeoutSeconds $probeBudget)) {
            return
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $PreUpgradePostgresReadyTimeoutMs `
        -PollMilliseconds $PreUpgradePostgresReadyPollIntervalMs)
    throw "既有 PostgreSQL 未在 $PreUpgradePostgresReadyTimeoutMs ms 内就绪，升级已取消。"
}

function Restore-PreviousServiceState {
    param(
        [Parameter(Mandatory = $true)][bool]$BackendWasRunning,
        [Parameter(Mandatory = $true)][bool]$PgWasRunning,
        [Parameter(Mandatory = $true)][ValidateSet(
            "absent",
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )][string]$BackendStartPolicy,
        [Parameter(Mandatory = $true)][ValidateSet(
            "absent",
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )][string]$PgStartPolicy
    )

    $restartFailure = $null
    try {
        if ($PgStartPolicy -ne "absent") {
            $pgPolicyForRestart = if (
                ($PgWasRunning -or $BackendWasRunning) -and $PgStartPolicy -eq "disabled"
            ) { "manual" } else { $PgStartPolicy }
            Set-TicketboxOwnedServiceStartPolicyIfExists `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                -StartPolicy $pgPolicyForRestart
        }
        if ($BackendStartPolicy -ne "absent") {
            $backendPolicyForRestart = if (
                $BackendWasRunning -and $BackendStartPolicy -eq "disabled"
            ) { "manual" } else { $BackendStartPolicy }
            Set-TicketboxOwnedServiceStartPolicyIfExists `
                -Name $BackendServiceName `
                -ExpectedExecutable $ShawlExe `
                -StartPolicy $backendPolicyForRestart
        }
        if ($PgWasRunning -or $BackendWasRunning) {
            Start-TicketboxOwnedServiceIfExists `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                @ServiceWaitArguments | Out-Null
            Wait-PgReady
        }
        if ($BackendWasRunning) {
            Start-TicketboxOwnedServiceIfExists `
                -Name $BackendServiceName `
                -ExpectedExecutable $ShawlExe `
                @ServiceWaitArguments | Out-Null
        }
    }
    catch {
        $restartFailure = $_.Exception.Message
    }

    $policyFailures = @()
    foreach ($policy in @(
        @{ Name = $PgServiceName; Executable = $PgCtl; Value = $PgStartPolicy },
        @{ Name = $BackendServiceName; Executable = $ShawlExe; Value = $BackendStartPolicy }
    )) {
        if ($policy.Value -eq "absent") { continue }
        try {
            Set-TicketboxOwnedServiceStartPolicyIfExists `
                -Name $policy.Name `
                -ExpectedExecutable $policy.Executable `
                -StartPolicy $policy.Value
        }
        catch {
            $policyFailures += "$($policy.Name)：$($_.Exception.Message)"
        }
    }
    if ($null -ne $restartFailure -or $policyFailures.Count -gt 0) {
        throw "恢复旧服务失败：restart=$restartFailure；policy=$($policyFailures -join '；')"
    }
}

function Initialize-LegacyInstalledServicePolicy([bool]$HasBackendService) {
    if ($HasPersistedInstalledReleaseConfig -or -not $HasBackendService) {
        return
    }
    Assert-TicketboxServiceOwnership -Name $BackendServiceName -ExpectedExecutable $ShawlExe | Out-Null
    $stopText = Get-TicketboxServiceArgumentValue $BackendServiceName "--stop-timeout"
    $restartText = Get-TicketboxServiceArgumentValue $BackendServiceName "--restart-delay"
    $stopValue = 0
    $restartValue = 0
    if (
        -not [int]::TryParse($stopText, [ref]$stopValue) -or
        -not [int]::TryParse($restartText, [ref]$restartValue) -or
        $stopValue -lt 1000 -or $stopValue -gt 300000 -or
        $restartValue -lt 1000 -or $restartValue -gt 300000
    ) {
        throw "无法从既有 Shawl 服务安全恢复 N-1 stop/restart 策略。"
    }
    $InstalledReleaseConfig.stop_timeout_ms = $stopValue
    $InstalledReleaseConfig.restart_delay_ms = $restartValue
    $script:InstalledStopTimeoutMs = $stopValue
    $script:InstalledRestartDelayMs = $restartValue
}

function Assert-TicketboxPgClusterStopped {
    if (-not (Test-Path -LiteralPath $PgCtl -PathType Leaf)) {
        throw "缺少 pg_ctl.exe，无法确认 PostgreSQL 已真正停止。"
    }
    $statusResult = Invoke-TicketboxBoundedNativeProcess `
        -FilePath $PgCtl `
        -Arguments @('status', '-D', $PgData) `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs `
        -Label 'pg_ctl stopped-state verification'
    $rc = $statusResult.ExitCode
    if ($rc -eq 0) {
        throw "Windows 服务已停止，但 PostgreSQL 数据簇进程仍在运行。"
    }
    if ($rc -ne 3) {
        throw "pg_ctl 无法确认 PostgreSQL 已停止（exit=$rc）。"
    }
}

function Write-TicketboxRecoveryRequiredMarker([string]$Reason) {
    Write-TicketboxInstallerRecoveryMarker `
        -Path $RecoveryRequiredPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -Reason $Reason
}

function Initialize-TicketboxRecoveryStateArtifact {
    $installerStateExists = Test-Path -LiteralPath $InstallerState
    $legacyRecoveryExists = Test-Path -LiteralPath $LegacyRecoveryRequiredPath
    if ($installerStateExists) {
        Initialize-TicketboxInstallerStateDirectory $InstallerState | Out-Null
    }
    if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
        if ($installerStateExists -and @(Get-ChildItem -LiteralPath $InstallerState -Force).Count -gt 0) {
            throw "installer-state 含有状态但数据根不存在，拒绝继续恢复。"
        }
        return
    }
    $dataRootMarkerPath = Get-TicketboxDataRootMarkerPath $DataRoot
    if (-not (Test-Path -LiteralPath $dataRootMarkerPath -PathType Leaf)) {
        if ($installerStateExists -and @(Get-ChildItem -LiteralPath $InstallerState -Force).Count -gt 0) {
            throw "installer-state 含有状态但数据根权威标记缺失，拒绝继续恢复。"
        }
        if ($legacyRecoveryExists) {
            throw "legacy recovery 状态存在但数据根权威标记缺失，拒绝继续恢复。"
        }
        return
    }
    Assert-TicketboxDataRootMarker -DataRoot $DataRoot -InstallDir $InstallDir
    if (-not $installerStateExists -and -not $legacyRecoveryExists) {
        return
    }
    if (-not $installerStateExists) {
        Initialize-TicketboxInstallerStateDirectory $InstallerState | Out-Null
    }
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $LegacyRecoveryRequiredPath `
        -CurrentPath $RecoveryRequiredPath
}

function Assert-TicketboxPgStoppedForFailSafeRecovery {
    if (Test-Path -LiteralPath $PgCtl -PathType Leaf) {
        Assert-TicketboxPgClusterStopped
        return
    }
    $listeners = @(Get-TicketboxListeningProcessIds $PgPort)
    if ($listeners.Count -gt 0) {
        throw "缺少 pg_ctl.exe，且 PostgreSQL 端口 $PgPort 仍被 PID $($listeners -join ',') 监听。"
    }
}

function Invoke-TicketboxPreparedInstallRecovery([object]$Receipt, [bool]$ProgramFilesWereReplaced) {
    Assert-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -AclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    if (-not $ProgramFilesWereReplaced) {
        Restore-PreviousServiceState `
            -BackendWasRunning ([string]$Receipt.previous_backend_state -eq "running") `
            -PgWasRunning ([string]$Receipt.previous_pg_state -eq "running") `
            -BackendStartPolicy ([string]$Receipt.previous_backend_start_policy) `
            -PgStartPolicy ([string]$Receipt.previous_pg_start_policy)
        return
    }

    Disable-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable $ShawlExe `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments
    Disable-TicketboxOwnedServiceIfExists `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
        @ServiceWaitArguments
    if (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION") -PathType Leaf) {
        Assert-TicketboxPgStoppedForFailSafeRecovery
    }
    if (
        [string]$Receipt.mode -eq "fresh_install" -and
        -not (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION") -PathType Leaf) -and
        -not (Test-TicketboxServiceExists $PgServiceName) -and
        -not (Test-TicketboxServiceExists $BackendServiceName)
    ) {
        Remove-TicketboxInstallerRecoveryMarker -Path $RecoveryRequiredPath -InstallDir $InstallDir -DataRoot $DataRoot
        return
    }
    Initialize-TicketboxRecoveryStateArtifact
    Write-TicketboxRecoveryRequiredMarker `
        "安装文件可能已替换；服务将保持禁用。请重新运行安装器完成可重复修复。未执行自动二进制或数据库回滚。"
}

function Read-TicketboxPreparedInitdbServiceReceipt {
    param([switch]$AllowPreviousInstallerOwnerProcessId)

    return Read-TicketboxBoundInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -ServiceName $PgServiceName `
        -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
        -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId
}

function Remove-TicketboxPreparedInitdbPasswordFile([object]$Receipt) {
    $allowPreAuthorizationAcl =
        [string]$Receipt.phase -in @("intent_written", "registered")
    Remove-TicketboxInitdbPasswordFileExact `
        -Path $InitdbPasswordPath `
        -ServiceName $PgServiceName `
        -AllowServiceReadMissing:$allowPreAuthorizationAcl
}

function Assert-TicketboxInterruptedInitdbRecoveryFile {
    $kind = Get-TicketboxPathEntryKindNoFollow $PgBootstrapRecoveryPath
    if ($kind -ceq "Missing") { return $false }
    if ($kind -cne "File") {
        throw "中断 initdb 的原始凭据恢复路径不是普通文件。"
    }
    Assert-TicketboxExactFileAcl `
        -Path $PgBootstrapRecoveryPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    return $true
}

function Assert-TicketboxInterruptedInitdbClusterComplete([object]$Receipt) {
    $pgVersionPath = Join-Path $PgData "PG_VERSION"
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        throw "中断 initdb 回执声明成功，但 PG_VERSION 缺失。"
    }
    $actualMajor = (Get-Content -LiteralPath $pgVersionPath -Raw -Encoding ASCII).Trim()
    if ($actualMajor -cne [string]$Receipt.pg_major) {
        throw "中断 initdb 数据簇主版本不匹配。"
    }
    foreach ($requiredPath in @(
        (Join-Path $PgData "global\pg_control"),
        (Join-Path $PgData "postgresql.conf"),
        (Join-Path $PgData "pg_hba.conf")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "中断 initdb 数据簇缺少必要文件。"
        }
    }
    if (
        -not (Test-Path -LiteralPath (Join-Path $PgData "base") -PathType Container) -or
        (Test-Path -LiteralPath (Join-Path $PgData "postmaster.pid"))
    ) {
        throw "中断 initdb 数据簇结构或停止状态不可信。"
    }
    Assert-NoTicketboxReparsePoints $PgData
}

function Get-TicketboxInterruptedInitdbServiceShape([object]$Receipt) {
    if (-not (Test-TicketboxServiceExists $PgServiceName)) {
        return "absent"
    }
    $actualExecutable = Get-TicketboxServiceExecutablePath $PgServiceName
    $startMode = Get-TicketboxServiceStartMode $PgServiceName
    if ($startMode -notin @("Disabled", "Manual")) {
        throw "中断 initdb 服务启动模式越界：$startMode"
    }
    $targetIdentityShape = @(Get-TicketboxReleaseServiceIdentityShapes `
        -InstalledConfig $TargetReleaseConfig `
        -TargetConfig $TargetReleaseConfig `
        -ServiceName $PgServiceName)[0]
    Assert-TicketboxServiceIdentityShape `
        -Name $PgServiceName `
        -AllowedShapes @(Get-TicketboxInitdbReceiptServiceIdentityShapes `
            -Receipt $Receipt `
            -ServiceName $PgServiceName `
            -TargetShape $targetIdentityShape `
            -AllowCurrentSidTypePending:([string]$Receipt.phase -ceq "intent_written")) | Out-Null
    Assert-TicketboxServiceDependencies `
        -Name $PgServiceName `
        -ExpectedDependencies @()
    if (Test-TicketboxPathEquals $actualExecutable $ShawlExe) {
        Assert-TicketboxInitdbServiceCommand `
            -Name $PgServiceName `
            -ExpectedShawl $ShawlExe `
            -ExpectedServiceName $PgServiceName `
            -ExpectedWorkingDirectory $PgBin `
            -ExpectedInitdb $InitdbExe `
            -ExpectedDataRoot $PgData `
            -ExpectedPasswordFile $InitdbPasswordPath `
            -ExpectedStopTimeoutMs ([int]$Receipt.stop_timeout_ms) `
            -ExpectedImagePath ([string]$Receipt.image_path)
        Assert-TicketboxServiceHasNoFailureActions $PgServiceName
        return "initdb_one_shot"
    }
    if (Test-TicketboxPathEquals $actualExecutable $PgCtl) {
        Assert-TicketboxPgServiceCommand `
            -Name $PgServiceName `
            -ExpectedExecutable $PgCtl `
            -ExpectedServiceName $PgServiceName `
            -ExpectedDataRoot $ServicePgData
        $actualFailurePolicy = Get-TicketboxServiceFailurePolicy $PgServiceName
        $expectedFailurePolicy = Get-TicketboxExpectedServiceFailurePolicy `
            -ResetSeconds ([int]$InstalledReleaseConfig.scm_failure_reset_seconds) `
            -RestartDelaysMs @($InstalledReleaseConfig.scm_restart_delays_ms)
        if ($actualFailurePolicy -notin @("0|", $expectedFailurePolicy)) {
            throw "中断 initdb 的正式 PostgreSQL 服务 failure policy 不属于可恢复状态。"
        }
        return "formal_pg_ctl"
    }
    throw "中断 initdb 回执对应的同名 PostgreSQL 服务 executable 不匹配。"
}

function Complete-TicketboxInterruptedInitdbServiceCommit([object]$Receipt) {
    $pgImagePath = New-TicketboxPgServiceImagePath `
        -PgCtlPath $PgCtl `
        -ServiceName $PgServiceName `
        -DataRoot $ServicePgData
    Invoke-TicketboxScChecked @(
        "config", $PgServiceName,
        "start=", "disabled",
        "binPath=", $pgImagePath
    ) | Out-Null
    Set-TicketboxServiceIdentityContract `
        -Name $PgServiceName `
        -LogonAccount (Get-TicketboxReleaseServiceLogonAccount `
            -Config $TargetReleaseConfig `
            -ServiceName $PgServiceName) `
        -SidType (Get-TicketboxReleaseServiceSidType $TargetReleaseConfig)
    Assert-TicketboxServiceOwnership `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl | Out-Null
    Assert-TicketboxPreparedServiceIdentity -Name $PgServiceName | Out-Null
    Assert-TicketboxPgServiceCommand `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedServiceName $PgServiceName `
        -ExpectedDataRoot $ServicePgData
    Assert-TicketboxServiceStartMode `
        -Name $PgServiceName `
        -ExpectedStartMode "Disabled"
    $scmRestartActions = @(
        $InstalledReleaseConfig.scm_restart_delays_ms |
            ForEach-Object { "restart/$([int]$_)" }
    ) -join "/"
    Invoke-TicketboxScChecked @(
        "failure", $PgServiceName,
        "reset=", [string]$InstalledReleaseConfig.scm_failure_reset_seconds,
        "actions=", $scmRestartActions
    ) | Out-Null
    Assert-TicketboxServiceFailurePolicy `
        -Name $PgServiceName `
        -ExpectedResetSeconds ([int]$InstalledReleaseConfig.scm_failure_reset_seconds) `
        -ExpectedRestartDelaysMs @($InstalledReleaseConfig.scm_restart_delays_ms)
    if ([string]$Receipt.phase -ceq "initdb_succeeded") {
        Set-TicketboxInitdbServiceReceiptPhase `
            -Path $InitdbServiceReceiptPath `
            -Receipt $Receipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -Phase "converted_to_pgctl"
        $Receipt = Read-TicketboxPreparedInitdbServiceReceipt
    }
    if ([string]$Receipt.phase -cne "converted_to_pgctl") {
        throw "中断 initdb 服务未达到正式 pg_ctl 提交阶段。"
    }
    Remove-TicketboxInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -Receipt $Receipt
}

function Remove-TicketboxAbortedInitdbPgData([object]$Receipt) {
    Remove-TicketboxInterruptedInitdbPgDataExact `
        -Receipt $Receipt `
        -PgData $PgData `
        -EnvPath $EnvPath `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceName $PgServiceName `
        -RuntimePort $PgPort `
        -ExpectedRuntimeExecutables @(
            $PgCtl,
            (Join-Path $PgBin "postgres.exe"),
            $ShawlExe,
            $InitdbExe
        )
}

function Invoke-TicketboxInterruptedInitdbServiceRecovery {
    $receiptKind = Get-TicketboxPathEntryKindNoFollow $InitdbServiceReceiptPath
    if ($receiptKind -ceq "Missing") { return }
    if ($receiptKind -cne "File") {
        throw "initdb one-shot 回执路径形态不可信。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $EnvPath) -cne "Missing") {
        throw "initdb one-shot 回执与应用 .env 同时存在，拒绝自动恢复。"
    }
    $receipt = Read-TicketboxPreparedInitdbServiceReceipt `
        -AllowPreviousInstallerOwnerProcessId
    $shape = Get-TicketboxInterruptedInitdbServiceShape $receipt
    $phase = [string]$receipt.phase

    if ($phase -in @("initdb_succeeded", "converted_to_pgctl")) {
        if ($shape -ceq "absent") {
            if ($phase -ceq "converted_to_pgctl") {
                throw "initdb 回执已提交但正式 PostgreSQL 服务缺失。"
            }
        }
        elseif ($shape -ceq "initdb_one_shot") {
            if ($phase -cne "initdb_succeeded") {
                throw "已提交回执仍指向 initdb one-shot 服务。"
            }
            Disable-TicketboxOwnedServiceIfExists `
                -Name $PgServiceName `
                -ExpectedExecutable $ShawlExe `
                -ExpectedRuntimeExecutables @($ShawlExe, $InitdbExe) `
                @ServiceWaitArguments
            Remove-TicketboxPreparedInitdbPasswordFile $receipt
            if (-not (Assert-TicketboxInterruptedInitdbRecoveryFile)) {
                throw "成功 initdb 缺少原始凭据恢复材料。"
            }
            Assert-TicketboxInterruptedInitdbClusterComplete $receipt
            Complete-TicketboxInterruptedInitdbServiceCommit $receipt
            Write-Host "已完成中断的 initdb -> pg_ctl 原子提交。" -ForegroundColor Yellow
            return
        }
        elseif ($shape -ceq "formal_pg_ctl") {
            Disable-TicketboxOwnedServiceIfExists `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
                @ServiceWaitArguments
            if ((Get-TicketboxPathEntryKindNoFollow $InitdbPasswordPath) -cne "Missing") {
                throw "正式 pg_ctl 提交边界仍残留 initdb 临时密码文件。"
            }
            if (-not (Assert-TicketboxInterruptedInitdbRecoveryFile)) {
                throw "成功 initdb 缺少原始凭据恢复材料。"
            }
            Assert-TicketboxInterruptedInitdbClusterComplete $receipt
            Complete-TicketboxInterruptedInitdbServiceCommit $receipt
            Write-Host "已确认并退役中断的 initdb 提交回执。" -ForegroundColor Yellow
            return
        }
    }

    if ($shape -ceq "formal_pg_ctl") {
        throw "未提交的 initdb 回执却已指向正式 pg_ctl 服务，拒绝自动推断。"
    }
    if ($shape -ceq "initdb_one_shot") {
        Disable-TicketboxOwnedServiceIfExists `
            -Name $PgServiceName `
            -ExpectedExecutable $ShawlExe `
            -ExpectedRuntimeExecutables @($ShawlExe, $InitdbExe) `
            @ServiceWaitArguments
        Remove-TicketboxPreparedInitdbPasswordFile $receipt
        Remove-TicketboxOwnedServiceIfExists `
            -Name $PgServiceName `
            -ExpectedExecutable $ShawlExe `
            -ExpectedRuntimeExecutables @($ShawlExe, $InitdbExe) `
            @ServiceWaitArguments
    }
    else {
        Assert-TicketboxRuntimeAbsent `
            -Name $PgServiceName `
            -RuntimePort $PgPort `
            -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe"), $ShawlExe, $InitdbExe)
        Remove-TicketboxPreparedInitdbPasswordFile $receipt
    }
    [void](Assert-TicketboxInterruptedInitdbRecoveryFile)
    Remove-TicketboxAbortedInitdbPgData $receipt
    Remove-TicketboxAbortedInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -Receipt $receipt
    Write-Host "已精确清理未提交的 initdb one-shot 状态；正式首装可安全重试。" -ForegroundColor Yellow
}

if ($PgPort -eq $BackendPort) {
    throw "PostgreSQL 服务端口和后端 API 端口不能相同。"
}
if ($ValidateOnly) {
    Assert-TicketboxTargetPgMajor
    Write-Host "ValidateOnly OK。" -ForegroundColor Green
    return
}

$operationLock = Enter-TicketboxLifecycleLock `
    -ExternalOwnerProcessId $InstallerLockOwnerProcessId
$prepareOperationFailure = $null
try {
    Assert-Admin
    Initialize-TicketboxInstalledReleaseConfiguration
    if ($InstallerLockOwnerProcessId -le 0) {
        throw "升级预检只能由持有生命周期锁的 Inno 安装器调用。"
    }
    if ($PersistDatabaseGenerationIntentOnly) {
        if (
            $DatabaseGenerationProgramPath.Trim().Length -eq 0 -or
            $DatabaseGenerationProgramSha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $DatabaseGenerationMigrationHelperSize -lt 1 -or
            $DatabaseGenerationMigrationHelperSha256 -cnotmatch
                '^[0-9a-f]{64}$' -or
            $DatabaseGenerationPgDumpSize -lt 1 -or
            $DatabaseGenerationPgDumpSha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $DatabaseGenerationPgRestoreSize -lt 1 -or
            $DatabaseGenerationPgRestoreSha256 -cnotmatch '^[0-9a-f]{64}$'
        ) {
            throw "database generation preinstall evidence 不完整。"
        }
        . (Get-TicketboxBootstrapDatabaseGenerationAuthorityPath)
        $generationStateRoot = Get-TicketboxDatabaseGenerationStateRoot $InstallerState
        $lifecycleEvidence = [pscustomobject][ordered]@{
            schema = "ticketbox-database-generation-lifecycle-evidence-v1"
            receipt_present = $false
            install_completed = $false
            operation_id = ""
            current_sha256 = ""
        }
        $lifecycleReceiptKind = Get-TicketboxPathEntryKindNoFollow $LifecycleReceiptPath
        if ($lifecycleReceiptKind -ceq "File") {
            $observedLifecycleReceipt = Read-TicketboxLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -TargetReleaseConfig $TargetReleaseConfig `
                -CurrentTargetBackendVersion $TargetBackendVersion `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                -AllowPreviousInstallerOwnerProcessId
            try {
                $lifecycleEvidence.receipt_present = $true
                $lifecycleEvidence.install_completed =
                    [bool]$observedLifecycleReceipt.install_completed
                $lifecycleEvidence.operation_id =
                    [string]$observedLifecycleReceipt.database_generation_operation_id
                $lifecycleEvidence.current_sha256 =
                    [string]$observedLifecycleReceipt.database_generation_current_sha256
            }
            finally {
                Close-TicketboxLifecycleBackupGuard $observedLifecycleReceipt
            }
        }
        elseif ($lifecycleReceiptKind -cne "Missing") {
            throw "安装生命周期回执不是普通文件或缺失路径。"
        }
        $preinstallFacts = [pscustomobject][ordered]@{
            BackendServiceName = $BackendServiceName
            ExistingPathFacts = @(
                [pscustomobject][ordered]@{ Path = (Join-Path $PgData "PG_VERSION"); Label = "PG_VERSION" }
                [pscustomobject][ordered]@{ Path = $EnvPath; Label = "runtime .env" }
                [pscustomobject][ordered]@{ Path = $LifecycleReceiptPath; Label = "lifecycle receipt" }
                [pscustomobject][ordered]@{ Path = $InstalledBuildManifestPath; Label = "installed build manifest" }
                [pscustomobject][ordered]@{ Path = $BackendExe; Label = "installed backend executable" }
                [pscustomobject][ordered]@{ Path = $PgBootstrapRecoveryPath; Label = "PostgreSQL bootstrap recovery" }
                [pscustomobject][ordered]@{ Path = $InitdbServiceReceiptPath; Label = "initdb receipt" }
                [pscustomobject][ordered]@{ Path = $RecoveryRequiredPath; Label = "installer recovery latch" }
                [pscustomobject][ordered]@{ Path = $LegacyRecoveryRequiredPath; Label = "legacy recovery latch" }
                [pscustomobject][ordered]@{ Path = $InstallerRuntimeRecoveryGuardPath; Label = "runtime recovery guard" }
            )
            HasPersistedInstalledReleaseConfig = $HasPersistedInstalledReleaseConfig
            LifecycleEvidence = $lifecycleEvidence
            PgServiceName = $PgServiceName
            StateRoot = $generationStateRoot
        }
        $programContract = Read-TicketboxDatabaseGenerationProgramContract `
            -Path $DatabaseGenerationProgramPath `
            -ExpectedSha256 $DatabaseGenerationProgramSha256
        $hostContract = New-TicketboxDatabaseGenerationHostContract `
            -BackendServiceName ([string]$TargetReleaseConfig.backend_service_name) `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -PgCtlPath (Join-Path $InstallDir "pg\bin\pg_ctl.exe") `
            -PgServiceName ([string]$TargetReleaseConfig.pg_service_name) `
            -PgDumpPath (Join-Path $InstallDir "pg\bin\pg_dump.exe") `
            -PgDumpSize $DatabaseGenerationPgDumpSize `
            -PgDumpSha256 $DatabaseGenerationPgDumpSha256 `
            -PgRestorePath (Join-Path $InstallDir "pg\bin\pg_restore.exe") `
            -PgRestoreSize $DatabaseGenerationPgRestoreSize `
            -PgRestoreSha256 $DatabaseGenerationPgRestoreSha256 `
            -ReleaseConfig $TargetReleaseConfig
        $projectionContract = New-TicketboxDatabaseGenerationProjectionContract `
            -BackendServiceName ([string]$TargetReleaseConfig.backend_service_name) `
            -EnvPath (Join-Path (Join-Path $DataRoot "app") ".env") `
            -StopTimeoutMilliseconds ([int]$TargetReleaseConfig.stop_timeout_ms) `
            -BackendPort $BackendPort `
            -PgBin (Join-Path $InstallDir "pg\bin") `
            -Timezone ([string]$TargetReleaseConfig.default_timezone) `
            -PublicBaseUrl "" `
            -PsqlPath (Join-Path $InstallDir "pg\bin\psql.exe") `
            -PgData (Join-Path $DataRoot "pgdata") `
            -DatabaseToolTimeoutMilliseconds (
                [int]$TargetReleaseConfig.database_tool_timeout_ms
            )
        $intentContext = Start-TicketboxDatabaseGenerationIntent `
            -InstallerState $InstallerState `
            -LifecycleLock $operationLock `
            -PreinstallFacts $preinstallFacts `
            -TargetBackendVersion $TargetBackendVersion `
            -MigrationHelperSize $DatabaseGenerationMigrationHelperSize `
            -MigrationHelperSha256 $DatabaseGenerationMigrationHelperSha256 `
            -ProgramContract $programContract `
            -HostContract $hostContract `
            -ProjectionContract $projectionContract
        Write-Host (
            "database generation intent persisted: operation={0} installation={1}" -f `
                [string]$intentContext.Artifact.Payload.operation_id,
                [string]$intentContext.Artifact.Payload.installation_id
        ) -ForegroundColor Green
        return
    }
    # A trusted older installer could leave the v2 marker with the exact
    # inheritance-only ACL shape before it persisted a stale lifecycle receipt.
    # Normalize only that known residual before any receipt reader requires the
    # protected marker; all authority facts are checked before the ACL write.
    Repair-TicketboxInterruptedInstallerMarkerAclIfNeeded `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ExpectedBackendServiceName $BackendServiceName
    Set-TicketboxPreparedRuntimeServiceContract
    Invoke-TicketboxInterruptedInitdbServiceRecovery
    Assert-TicketboxTargetPgMajor
    if ($MarkProgramFilesInstalledBackupPending) {
        $receipt = Read-TicketboxLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        if ([string]$receipt.preparation_stage -eq "backup_deferred_until_program_files_installed") {
            Set-TicketboxLifecycleReceiptProgramFilesInstalledBackupPending `
                -Path $LifecycleReceiptPath `
                -Receipt $receipt `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        }
        elseif ([string]$receipt.preparation_stage -eq "prepared") {
            Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced `
                -Path $LifecycleReceiptPath `
                -Receipt $receipt `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        }
        elseif ([string]$receipt.preparation_stage -notin @(
            "program_files_installed_backup_pending",
            "files_may_have_been_replaced"
        )) {
            throw "程序文件复制边界与 preserved-data 生命周期回执阶段不一致。"
        }
        Close-TicketboxLifecycleBackupGuard $receipt
        $receipt = Read-TicketboxLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        Set-TicketboxLifecycleReceiptTargetVersionFloor `
            -Path $LifecycleReceiptPath `
            -Receipt $receipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -TargetBackendVersionFloor $TargetBackendVersion
        $receipt = Read-TicketboxLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        if (
            (Compare-TicketboxLifecycleVersions `
                -Left $TargetBackendVersion `
                -Right ([string]$receipt.target_backend_version_floor)) -ne 0
        ) {
            throw "程序文件复制边界未持久化当前安装器目标版本下限。"
        }
        Close-TicketboxLifecycleBackupGuard $receipt
        return
    }
    if ($RecoverPreparedInstall) {
        $receipt = Read-TicketboxLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        $PreparedServiceIdentityLifecycleReceipt = $receipt
        $recoveryStage = [string]$receipt.preparation_stage
        if ([bool]$receipt.temporary_pg_service_cleanup_pending) {
            Remove-TicketboxDeferredPreservedPgServiceIfExists
            Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending `
                -Path $LifecycleReceiptPath `
                -Receipt $receipt `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                -CleanupPending $false
            $receipt.temporary_pg_service_cleanup_pending = $false
        }
        Remove-TicketboxRecoveryPgServiceIfExists
        Set-TicketboxInstalledReleaseConfiguration `
            -Config $receipt.installed_release_config `
            -Persisted $true
        Assert-TicketboxPreparedServiceContracts `
            -AllowTargetPolicyFallback `
            -AllowLegacyRuntimeDataContract:($RuntimeDataBindingPresent -and $recoveryStage -in @(
                "prepared",
                "program_files_installed_backup_pending",
                "files_may_have_been_replaced"
            ))
        $isDeferredPreservedBackup =
            [string]$receipt.mode -eq "preserved_data_reinstall" -and
            $recoveryStage -in @(
                "backup_deferred_until_program_files_installed",
                "program_files_installed_backup_pending"
            ) -and
            [bool]$receipt.backup_required -and
            -not [bool]$receipt.backup_completed
        if ($isDeferredPreservedBackup) {
            $programFilesWereReplaced =
                $recoveryStage -eq "program_files_installed_backup_pending"
            Invoke-TicketboxPreparedInstallRecovery `
                -Receipt $receipt `
                -ProgramFilesWereReplaced $programFilesWereReplaced
            if ($programFilesWereReplaced) {
                Write-Host `
                    "保留数据重装在备份提交前中断；数据根保持不变，请重新运行修复安装。" `
                    -ForegroundColor Yellow
            }
            else {
                Remove-TicketboxLifecycleReceipt -Path $LifecycleReceiptPath
                Write-Host "保留数据重装在复制前中断；已清理捕获回执。" -ForegroundColor Yellow
            }
            return
        }
        if (
            ($FilesReplaced -and $recoveryStage -notin @("prepared", "files_may_have_been_replaced")) -or
            (-not $FilesReplaced -and $recoveryStage -ne "prepared")
        ) {
            throw "故障恢复参数与生命周期回执阶段不一致。"
        }
        Invoke-TicketboxPreparedInstallRecovery `
            -Receipt $receipt `
            -ProgramFilesWereReplaced ([bool]$FilesReplaced)
        if ($FilesReplaced) {
            if ([string]$receipt.preparation_stage -eq "prepared") {
                Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced `
                    -Path $LifecycleReceiptPath `
                    -Receipt $receipt `
                    -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            }
            Write-Host "文件替换后的故障隔离已完成；请重新运行安装器修复。未执行自动二进制或数据库回滚。" -ForegroundColor Yellow
        }
        else {
            Remove-TicketboxLifecycleReceipt -Path $LifecycleReceiptPath
            Write-Host "复制前失败的旧服务状态补偿已完成。" -ForegroundColor Yellow
        }
        return
    }

    if ($CommitCompletedInstall) {
        . (Get-TicketboxInstalledDatabaseGenerationAuthorityPath)
        Complete-TicketboxInstalledLifecycleTransaction `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -TargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -BuildManifestPath $InstalledBuildManifestPath `
            -RecoveryRequiredPath $RecoveryRequiredPath `
            -RuntimeRecoveryGuardPath $InstallerRuntimeRecoveryGuardPath `
            -LifecycleLock $operationLock
        return
    }

    if (Test-Path -LiteralPath $LifecycleReceiptPath -PathType Leaf) {
        $staleReceipt = Read-TicketboxCompatibleLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $TargetReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -AllowPreviousInstallerOwnerProcessId
        $PreparedServiceIdentityLifecycleReceipt = $staleReceipt
        if ([bool]$staleReceipt.install_completed) {
            Set-TicketboxInstalledReleaseConfiguration `
                -Config $staleReceipt.installed_release_config `
                -Persisted $true
            Remove-TicketboxRecoveryPgServiceIfExists
            Assert-TicketboxPreparedServiceContracts `
                -AllowTargetPolicyFallback `
                -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent
            Close-TicketboxLifecycleBackupGuard $staleReceipt
            $staleReceipt = ConvertTo-TicketboxCurrentLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -TargetReleaseConfig $TargetReleaseConfig `
                -CurrentTargetBackendVersion $TargetBackendVersion `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                -AllowPreviousInstallerOwnerProcessId
            $PreparedServiceIdentityLifecycleReceipt = $staleReceipt
            Set-TicketboxLifecycleReceiptInstallerOwner `
                -Path $LifecycleReceiptPath `
                -Receipt $staleReceipt `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            . (Get-TicketboxInstalledDatabaseGenerationAuthorityPath)
            Complete-TicketboxInstalledLifecycleTransaction `
                -Path $LifecycleReceiptPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -TargetReleaseConfig $TargetReleaseConfig `
                -TargetBackendVersion $TargetBackendVersion `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                -BuildManifestPath $InstalledBuildManifestPath `
                -RecoveryRequiredPath $RecoveryRequiredPath `
                -RuntimeRecoveryGuardPath $InstallerRuntimeRecoveryGuardPath `
                -LifecycleLock $operationLock
            $staleReceipt = Read-TicketboxLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -TargetReleaseConfig $TargetReleaseConfig `
                -CurrentTargetBackendVersion $TargetBackendVersion `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            $PreparedServiceIdentityLifecycleReceipt = $staleReceipt
            Remove-TicketboxCompletedLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $staleReceipt
            Write-Host "已补完上次中断的安装提交并退役旧回执；本次将重新执行复制前备份。" -ForegroundColor Yellow
        }
        elseif ([string]$staleReceipt.preparation_stage -in @(
            "captured",
            "backup_deferred_until_program_files_installed"
        )) {
            Set-TicketboxInstalledReleaseConfiguration `
                -Config $staleReceipt.installed_release_config `
                -Persisted $true
            Remove-TicketboxRecoveryPgServiceIfExists
            Assert-TicketboxPreparedServiceContracts
            Invoke-TicketboxPreparedInstallRecovery `
                -Receipt $staleReceipt `
                -ProgramFilesWereReplaced $false
            Remove-TicketboxLifecycleReceipt -Path $LifecycleReceiptPath
            Write-Host "检测到复制前 prepare 中断；已按预先持久化的原始状态完成补偿，本次重新预检。" -ForegroundColor Yellow
        }
        elseif ([string]$staleReceipt.preparation_stage -eq "program_files_installed_backup_pending") {
            Set-TicketboxInstalledReleaseConfiguration `
                -Config $staleReceipt.installed_release_config `
                -Persisted $true
            Repair-TicketboxInterruptedPayloadLeaseAcl
            Remove-TicketboxRecoveryPgServiceIfExists
            if ([bool]$staleReceipt.temporary_pg_service_cleanup_pending) {
                Remove-TicketboxDeferredPreservedPgServiceIfExists
            }
            Assert-TicketboxPreparedServiceContracts `
                -AllowTargetPolicyFallback `
                -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent
            Close-TicketboxLifecycleBackupGuard $staleReceipt
            $staleReceipt = ConvertTo-TicketboxCurrentLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -TargetReleaseConfig $TargetReleaseConfig `
                -CurrentTargetBackendVersion $TargetBackendVersion `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                -AllowPreviousInstallerOwnerProcessId
            $PreparedServiceIdentityLifecycleReceipt = $staleReceipt
            if ([bool]$staleReceipt.temporary_pg_service_cleanup_pending) {
                Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending `
                    -Path $LifecycleReceiptPath `
                    -Receipt $staleReceipt `
                    -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                    -CleanupPending $false
                $staleReceipt.temporary_pg_service_cleanup_pending = $false
            }
            Invoke-TicketboxPreparedInstallRecovery `
                -Receipt $staleReceipt `
                -ProgramFilesWereReplaced $true
            Set-TicketboxLifecycleReceiptInstallerOwner `
                -Path $LifecycleReceiptPath `
                -Receipt $staleReceipt `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            Write-Host "检测到 preserved-data 备份前文件复制中断；已精确清理临时服务并保持 post-copy 隔离。" -ForegroundColor Yellow
            return
        }
        else {
            Set-TicketboxInstalledReleaseConfiguration `
                -Config $staleReceipt.installed_release_config `
                -Persisted $true
            Repair-TicketboxInterruptedPayloadLeaseAcl
            Remove-TicketboxRecoveryPgServiceIfExists
            Assert-TicketboxPreparedServiceContracts `
                -AllowTargetPolicyFallback `
                -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent
            Close-TicketboxLifecycleBackupGuard $staleReceipt
            $staleReceipt = ConvertTo-TicketboxCurrentLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -TargetReleaseConfig $TargetReleaseConfig `
                -CurrentTargetBackendVersion $TargetBackendVersion `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                -AllowPreviousInstallerOwnerProcessId
            $PreparedServiceIdentityLifecycleReceipt = $staleReceipt
            Invoke-TicketboxPreparedInstallRecovery `
                -Receipt $staleReceipt `
                -ProgramFilesWereReplaced $true
            if ([string]$staleReceipt.preparation_stage -eq "prepared") {
                Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced `
                    -Path $LifecycleReceiptPath `
                    -Receipt $staleReceipt `
                    -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            }
            else {
                Set-TicketboxLifecycleReceiptInstallerOwner `
                    -Path $LifecycleReceiptPath `
                    -Receipt $staleReceipt `
                    -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            }
            Write-Host "检测到上次中断的安装；已保留原运行态与备份证据，并进入 files-may-have-been-replaced 修复模式。" -ForegroundColor Yellow
            return
        }
    }

    $hasPgService = Test-TicketboxServiceExists $PgServiceName
    $hasBackendService = Test-TicketboxServiceExists $BackendServiceName
    $hasPgData = Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION") -PathType Leaf
    $hasEnv = Test-Path -LiteralPath $EnvPath -PathType Leaf
    $hasPgBootstrapRecovery = Test-Path -LiteralPath $PgBootstrapRecoveryPath -PathType Leaf
    $mode = Get-TicketboxPreparedInstallMode `
        -HasPgService $hasPgService `
        -HasBackendService $hasBackendService `
        -HasPgData $hasPgData `
        -HasEnv $hasEnv `
        -HasPgBootstrapRecovery $hasPgBootstrapRecovery

    $serviceReadAccounts = @()
    if ($hasPgService) { $serviceReadAccounts += "NT SERVICE\$PgServiceName" }
    if ($hasBackendService) { $serviceReadAccounts += "NT SERVICE\$BackendServiceName" }
    Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir | Out-Null
    Assert-TicketboxPreparedDataRootAuthorityGate `
        -Mode $mode `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir
    Initialize-LegacyInstalledServicePolicy -HasBackendService $hasBackendService
    if ($hasPgService) {
        Assert-ExpectedServiceConfiguration -Name $PgServiceName
    }
    if ($hasBackendService) {
        Assert-ExpectedServiceConfiguration -Name $BackendServiceName
    }
    if ($mode -eq "preserved_data_reinstall") {
        Assert-TicketboxLegacyPreservedDataLayout `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -EnvPath $EnvPath `
            -PgData $PgData `
            -ExpectedPgMajor $TargetPgMajor | Out-Null
        $legacyEnvironment = Read-EnvMap $EnvPath
        if (-not $legacyEnvironment.ContainsKey("DATABASE_URL")) {
            throw "legacy 保留数据的 .env 缺少 DATABASE_URL。"
        }
        Get-TicketboxPreparedApplicationDatabaseConnection `
            -DatabaseUrl $legacyEnvironment["DATABASE_URL"] | Out-Null
    }
    elseif ($mode -ne "fresh_install") {
        Assert-TicketboxRegisteredDataRootBinding -DataRoot $DataRoot
        Assert-NoTicketboxReparsePoints $DataRoot
    }
    if ($mode -ne "fresh_install") {
        Initialize-TicketboxDataRootMarker `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -AllowLegacyV1Migration `
            -AclPhase backend_read_optional `
            -ExpectedBackendServiceName $BackendServiceName
    }

    Remove-TicketboxRecoveryPgServiceIfExists
    Assert-TicketboxPortAvailableForMissingService `
        -Name $PgServiceName `
        -Port $PgPort `
        -HasService $hasPgService
    Assert-TicketboxPortAvailableForMissingService `
        -Name $BackendServiceName `
        -Port $BackendPort `
        -HasService $hasBackendService

    $backendState = if ($hasBackendService) {
        Wait-TicketboxServiceSettledState -Name $BackendServiceName @ServiceWaitArguments
    }
    else { "absent" }
    $pgState = if ($hasPgService) {
        Wait-TicketboxServiceSettledState -Name $PgServiceName @ServiceWaitArguments
    }
    else { "absent" }
    $backendStartPolicy = if ($hasBackendService) {
        Get-TicketboxServiceStartPolicy $BackendServiceName
    }
    else { "absent" }
    $pgStartPolicy = if ($hasPgService) {
        Get-TicketboxServiceStartPolicy $PgServiceName
    }
    else { "absent" }
    if ($backendState -eq "running" -and $pgState -ne "running") {
        throw "既有服务状态不一致：后端运行但 PostgreSQL 未运行。"
    }

    $backupRequired = $hasPgData -and $hasEnv
    $deferredPreservedBackup =
        $mode -eq "preserved_data_reinstall" -and $backupRequired
    $usingRecoveryPgService =
        $backupRequired -and -not $hasPgService -and -not $deferredPreservedBackup
    if ($backupRequired -and -not $hasPgService) {
        if ($mode -eq "repair_install") {
            Save-TicketboxPgRecoveryToolset `
                -SourcePgHome $InstalledPgHome `
                -BuildManifestPath $InstalledBuildManifestPath `
                -ExpectedMajor $TargetPgMajor | Out-Null
        }
        elseif ($mode -ne "preserved_data_reinstall") {
            throw "检测到需保留的 PostgreSQL 数据和 .env，但正式 PostgreSQL 服务缺失且安装状态不能安全取得复制前备份。"
        }
        if (-not $deferredPreservedBackup) {
            Assert-TicketboxPgRecoveryToolset -ExpectedMajor $TargetPgMajor | Out-Null
            Set-TicketboxActivePgTools (Get-TicketboxPgRecoveryHome)
        }
    }
    $backupCompleted = $false
    $backupPath = ""
    . (Get-TicketboxBootstrapDatabaseGenerationAuthorityPath)
    $capturedGenerationStateRoot =
        Get-TicketboxDatabaseGenerationStateRoot $InstallerState
    $capturedGenerationIntent = Read-TicketboxDatabaseGenerationActiveIntent `
        $capturedGenerationStateRoot
    $capturedGenerationOperationId =
        [string]$capturedGenerationIntent.Payload.operation_id
    Write-TicketboxLifecycleReceipt `
        -Path $LifecycleReceiptPath `
        -Mode $mode `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -InstalledReleaseConfig $InstalledReleaseConfig `
        -TargetBackendVersionFloor $TargetBackendVersion `
        -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
        -DatabaseGenerationOperationId $capturedGenerationOperationId `
        -PreviousPgState $pgState `
        -PreviousBackendState $backendState `
        -PreviousPgStartPolicy $pgStartPolicy `
        -PreviousBackendStartPolicy $backendStartPolicy `
        -BackupRequired $backupRequired `
        -BackupCompleted $false `
        -PreparationStage "captured"
    $capturedReceipt = Read-TicketboxLifecycleReceipt `
        -Path $LifecycleReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -TargetReleaseConfig $TargetReleaseConfig `
        -CurrentTargetBackendVersion $TargetBackendVersion `
        -InstallerOwnerProcessId $InstallerLockOwnerProcessId
    $PreparedServiceIdentityLifecycleReceipt = $capturedReceipt
    if ($deferredPreservedBackup) {
        Set-TicketboxLifecycleReceiptDeferredBackup `
            -Path $LifecycleReceiptPath `
            -Receipt $capturedReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        Write-Host `
            "legacy 保留数据只读预检完成；复制目标 PG 工具后、任何服务/数据变更前执行备份。" `
            -ForegroundColor Green
        return
    }
    $installAclMutationStarted = $false
    try {
        $installAclMutationStarted = $true
        Repair-TicketboxPreflightInstallAcl -ServiceReadAccounts $serviceReadAccounts
        if ($hasBackendService) {
            Disable-TicketboxOwnedServiceIfExists `
                -Name $BackendServiceName `
                -ExpectedExecutable $ShawlExe `
                -BackendPort $BackendPort `
                -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
                @ServiceWaitArguments
        }
        if ($usingRecoveryPgService) {
            Register-TicketboxRecoveryPgService
        }
        if ($backupRequired) {
            Assert-File $PgCtl "pg_ctl.exe"
            Assert-File $PgReady "pg_isready.exe"
            Assert-File $PgDump "pg_dump.exe"
            Assert-File $PgRestore "pg_restore.exe"
            Assert-File $Psql "psql.exe"
            $envMap = Read-EnvMap $EnvPath
            if (-not $envMap.ContainsKey("DATABASE_URL")) {
                throw "既有 .env 缺少 DATABASE_URL，拒绝无备份升级。"
            }
            $connection = Get-TicketboxPreparedApplicationDatabaseConnection `
                -DatabaseUrl $envMap["DATABASE_URL"]
            if ($hasPgService -and $pgStartPolicy -eq "disabled") {
                Set-TicketboxPreparedServiceDemandStart `
                    -Name $PgServiceName `
                    -ExpectedExecutable $PgCtl
            }
            $backupServiceName = if ($usingRecoveryPgService) {
                $PgRecoveryServiceName
            }
            else {
                $PgServiceName
            }
            Start-TicketboxOwnedServiceIfExists `
                -Name $backupServiceName `
                -ExpectedExecutable $PgCtl `
                @ServiceWaitArguments | Out-Null
            Wait-PgReady
            Assert-TicketboxConnectedPostgresDataRoot `
                -PsqlPath $Psql `
                -DatabaseUrl $connection.DatabaseUrl `
                -ExpectedDataRoot $PgData `
                -ExpectedPort $PgPort `
                -Password $connection.Password `
                -TimeoutMilliseconds $DatabaseToolTimeoutMs

            New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
            Set-TicketboxExactDirectoryAcl `
                -Path $BackupDir `
                -Accounts @("SYSTEM", "BUILTIN\Administrators")
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $target = Join-Path $BackupDir "ticketbox-pre-upgrade-installer-$stamp.dump"
            $temp = "$target.tmp"
            $dumpResult = Invoke-TicketboxPgDumpCustom `
                -PgDumpPath $PgDump `
                -DatabaseUrl $connection.DatabaseUrl `
                -OutputPath $temp `
                -Password $connection.Password `
                -TimeoutMilliseconds $DatabaseToolTimeoutMs
            if ($dumpResult -ne 0) {
                Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
                throw "升级前 pg_dump 失败，旧程序保持不变。"
            }
            Sync-TicketboxFileDurable $temp
            Set-TicketboxExactFileAcl `
                -Path $temp `
                -Accounts @("SYSTEM", "BUILTIN\Administrators")
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $restoreRc = Invoke-TicketboxPgRestoreList `
                    -PgRestorePath $PgRestore `
                    -ArchivePath $temp `
                    -TimeoutMilliseconds $DatabaseToolTimeoutMs
            }
            finally {
                $ErrorActionPreference = $previousPreference
            }
            if ($restoreRc -ne 0) {
                Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
                throw "升级前备份校验失败，旧程序保持不变。"
            }
            Move-TicketboxFileDurable $temp $target
            Set-TicketboxExactFileAcl `
                -Path $target `
                -Accounts @("SYSTEM", "BUILTIN\Administrators")
            $backupCompleted = $true
            $backupPath = $target
        }
        if ($usingRecoveryPgService) {
            Remove-TicketboxRecoveryPgServiceIfExists
            Set-TicketboxActivePgTools $InstalledPgHome
        }
        if ($hasPgService) {
            Disable-TicketboxOwnedServiceIfExists `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
                @ServiceWaitArguments
            Assert-TicketboxPgClusterStopped
        }
        Set-TicketboxLifecycleReceiptPrepared `
            -Path $LifecycleReceiptPath `
            -Receipt $capturedReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -BackupCompleted $backupCompleted `
            -BackupPath $backupPath
        Write-Host "安装预检完成：$mode" -ForegroundColor Green
    }
    catch {
        $failure = $_.Exception
        [Exception[]]$compensationFailures = @()
        if ($usingRecoveryPgService) {
            try {
                Remove-TicketboxRecoveryPgServiceIfExists
                Set-TicketboxActivePgTools $InstalledPgHome
            }
            catch {
                $compensationFailure = $_.Exception
                $compensationFailure.Data["TicketboxPrepareCompensationStep"] =
                    "recovery_pg_cleanup"
                $compensationFailures += $compensationFailure
            }
        }
        if ($installAclMutationStarted) {
            try {
                Repair-TicketboxPreflightInstallAcl -ServiceReadAccounts $serviceReadAccounts
            }
            catch {
                $compensationFailure = $_.Exception
                $compensationFailure.Data["TicketboxPrepareCompensationStep"] =
                    "install_acl_restore"
                $compensationFailures += $compensationFailure
            }
        }
        try {
            Restore-PreviousServiceState `
                -BackendWasRunning ($backendState -eq "running") `
                -PgWasRunning ($pgState -eq "running") `
                -BackendStartPolicy $backendStartPolicy `
                -PgStartPolicy $pgStartPolicy
        }
        catch {
            $compensationFailure = $_.Exception
            $compensationFailure.Data["TicketboxPrepareCompensationStep"] =
                "service_state_restore"
            $compensationFailures += $compensationFailure
        }
        if (
            $compensationFailures.Count -eq 0 -and
            (Test-Path -LiteralPath $LifecycleReceiptPath -PathType Leaf)
        ) {
            try {
                Remove-TicketboxLifecycleReceipt -Path $LifecycleReceiptPath
            }
            catch {
                $compensationFailure = $_.Exception
                $compensationFailure.Data["TicketboxPrepareCompensationStep"] =
                    "receipt_retire"
                $compensationFailures += $compensationFailure
            }
        }
        if ($compensationFailures.Count -gt 0) {
            throw (New-TicketboxPrepareAggregateFailure `
                -OperationFailure $failure `
                -SecondaryFailures $compensationFailures `
                -FailureKind "compensation")
        }
        throw $failure
    }
}
catch {
    $prepareOperationFailure = $_.Exception
}
finally {
    try {
        Exit-TicketboxLifecycleLock $operationLock
    }
    catch {
        throw (New-TicketboxPrepareAggregateFailure `
            -OperationFailure $prepareOperationFailure `
            -SecondaryFailures ([Exception[]]@($_.Exception)) `
            -FailureKind "finalization")
    }
}
if ($null -ne $prepareOperationFailure) {
    throw $prepareOperationFailure
}
