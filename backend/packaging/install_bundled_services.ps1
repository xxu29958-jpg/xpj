#Requires -Version 5.1
<#
.SYNOPSIS
  ADR-0047 Slice 4: install or upgrade the bundled Ticketbox Windows services.

.DESCRIPTION
  This is the script run by the Inno installer after files have been copied to
  Program Files. It keeps mutable data in ProgramData, registers the bundled
  PostgreSQL service plus the frozen backend service, and preserves existing data
  on upgrades. Existing databases are snapshotted with pg_dump before the new
  backend is allowed to start and run migrations.

  PowerShell 5.1 file encoding must be UTF-8 with BOM. The generated .env is
  deliberately UTF-8 without BOM.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
    [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
    [ValidateRange(0, 99)][int]$TargetPgMajor = 0,
    [Parameter(Mandatory = $true)][string]$TargetBackendVersion,
    [string]$AccountName = "",
    [string]$LedgerName = "",
    [string]$DeviceName = "",
    [string]$Timezone = "",
    [string]$PublicBaseUrl = "",
    [string]$ReleaseConfigPath = "",
    [string]$LifecycleReceiptPath = "",
    [switch]$SkipServiceStart,
    [int]$InstallerLockOwnerProcessId = 0,
    [switch]$ValidateOnly,
    [string]$ExpectedBackendServiceName = "",
    [string]$ExpectedPgServiceName = "",
    [switch]$ValidateInstalledServicesOnly,
    [switch]$ValidateBackendRuntimeStoppedOnly,
    [switch]$CompleteOwnerHandoffOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($InstallDir.Trim().Length -eq 0) {
    $InstallDir = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
}
$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"
if (-not (Test-Path -LiteralPath $ReleaseConfigScript -PathType Leaf)) {
    throw "缺少 Windows release config 解析脚本：$ReleaseConfigScript"
}
. $ReleaseConfigScript
if ($ReleaseConfigPath.Trim().Length -eq 0) {
    $ReleaseConfigPath = Join-Path $ScriptDir "windows-release-config.json"
}
$ReleaseConfig = Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath
$PreviousReleaseConfig = $ReleaseConfig | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$PgServiceName = [string]$ReleaseConfig.pg_service_name
$BackendServiceName = [string]$ReleaseConfig.backend_service_name
$StopTimeoutMs = [int]$ReleaseConfig.stop_timeout_ms
$RestartDelayMs = [int]$ReleaseConfig.restart_delay_ms
$PreviousStopTimeoutMs = [int]$PreviousReleaseConfig.stop_timeout_ms
$PreviousRestartDelayMs = [int]$PreviousReleaseConfig.restart_delay_ms
$ServiceWaitArguments = @{
    TimeoutMilliseconds = [int]$ReleaseConfig.service_state_timeout_ms
    PollMilliseconds = [int]$ReleaseConfig.service_poll_interval_ms
}
$PostgresReadyTimeoutMs = [int]$ReleaseConfig.postgres_ready_timeout_ms
$PostgresReadyPollIntervalMs = [int]$ReleaseConfig.postgres_ready_poll_interval_ms
$BackendReadyTimeoutMs = [int]$ReleaseConfig.backend_ready_timeout_ms
$BackendReadyPollIntervalMs = [int]$ReleaseConfig.backend_ready_poll_interval_ms
$BackendHealthRequestTimeoutMs = [int]$ReleaseConfig.backend_health_request_timeout_ms
$BootstrapRequestTimeoutMs = [int]$ReleaseConfig.bootstrap_request_timeout_ms
$DatabaseToolTimeoutMs = [int]$ReleaseConfig.database_tool_timeout_ms
$SecretByteCount = [int]$ReleaseConfig.secret_byte_count
$ScmFailureResetSeconds = [int]$ReleaseConfig.scm_failure_reset_seconds
$ScmRestartActions = @($ReleaseConfig.scm_restart_delays_ms | ForEach-Object { "restart/$([int]$_)" }) -join "/"
$DbName = [string]$ReleaseConfig.db_name
$DbRole = [string]$ReleaseConfig.db_role
$OwnerRecoveryChannel = [string]$ReleaseConfig.owner_recovery_channel
if ($AccountName.Trim().Length -eq 0) { $AccountName = [string]$ReleaseConfig.bootstrap_account_name }
if ($LedgerName.Trim().Length -eq 0) { $LedgerName = [string]$ReleaseConfig.bootstrap_ledger_name }
if ($DeviceName.Trim().Length -eq 0) { $DeviceName = [string]$ReleaseConfig.bootstrap_device_name }
if ($Timezone.Trim().Length -eq 0) { $Timezone = [string]$ReleaseConfig.default_timezone }

$PgHome = Join-Path $InstallDir "pg"
$PgBin = Join-Path $PgHome "bin"
$PgCtl = Join-Path $PgBin "pg_ctl.exe"
$PgReady = Join-Path $PgBin "pg_isready.exe"
$Psql = Join-Path $PgBin "psql.exe"
$PgDump = Join-Path $PgBin "pg_dump.exe"
$PgRestore = Join-Path $PgBin "pg_restore.exe"
$PgData = Join-Path $DataRoot "pgdata"
$AppData = Join-Path $DataRoot "app"
$LogDir = Join-Path $AppData "logs"
$BootstrapExposureRecoveryResultPath = Join-Path `
    $LogDir `
    "bootstrap-exposure-recovery-result.json"
$BackupDir = Join-Path $AppData "backups"
$InstallerBackupDir = Join-Path $DataRoot "installer-backups"
$EnvPath = Join-Path $AppData ".env"
$LegacyOwnerBootstrapPath = Join-Path $AppData "owner-bootstrap.txt"
$LegacyOwnerHandoffPendingPath = Join-Path $AppData "owner-handoff-pending"
$BootstrapExposureRecoveryGuardPath = Join-Path $DataRoot "bootstrap-exposure-recovery-pending"
$LegacyRecoveryRequiredPath = Join-Path $AppData "installer-recovery-required.json"
$ProgramDir = Join-Path $InstallDir "program\ticketbox-backend"
$BackendExe = Join-Path $ProgramDir "ticketbox-backend.exe"
$ShawlExe = Join-Path $InstallDir "shawl\shawl.exe"
$InstalledBuildManifestPath = Join-Path $ScriptDir "BUILD_PROVENANCE.json"
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
$InstallerRuntimeRecoveryGuardPath = Get-TicketboxInstallerRuntimeRecoveryGuardPath
$RuntimeDataBindingServiceAccounts = @(
    (Get-TicketboxServiceSid $PgServiceName),
    (Get-TicketboxServiceSid $BackendServiceName)
)
$RuntimeDataBindingPresent = $false
$RuntimeDataRoot = Get-TicketboxRuntimeDataRootPath
$ServicePgData = $PgData
$ServiceAppData = $AppData
$ServiceLogDir = $LogDir
$ServiceDataRootMarkerPath = Join-Path $RuntimeDataRoot $script:TicketboxDataRootMarkerName
$ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
$ServiceDataVolumeIdentity = ""
$AllowMissingRuntimeDataAuthority = $true

function Set-TicketboxRuntimeServiceContractFromBinding {
    param([switch]$RequireBinding)

    $bindingDirectory = Get-TicketboxRuntimeDataBindingDirectory
    $bindingKind = Get-TicketboxPathEntryKindNoFollow $bindingDirectory
    if ($bindingKind -ceq "Missing") {
        if ($RequireBinding) {
            throw "正式服务缺少 machine-owned runtime DataRoot binding。"
        }
        $script:ServicePgData = $PgData
        $script:ServiceAppData = $AppData
        $script:ServiceLogDir = $LogDir
        $script:ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
        $script:ServiceDataVolumeIdentity = ""
        $script:AllowMissingRuntimeDataAuthority = $true
        $script:RuntimeDataBindingPresent = $false
        return
    }
    $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath
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
            -InheritableReadExecuteAccounts $RuntimeDataBindingServiceAccounts `
            -OwnerAccount "SYSTEM"
        if (@(Get-ChildItem -LiteralPath $validatedBindingDirectory -Force).Count -ne 0) {
            throw "runtime DataRoot binding provisioning 断点含有未知 artifact。"
        }
        if ($RequireBinding) {
            throw "正式服务缺少完整 runtime DataRoot junction。"
        }
        $script:ServicePgData = $PgData
        $script:ServiceAppData = $AppData
        $script:ServiceLogDir = $LogDir
        $script:ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
        $script:ServiceDataVolumeIdentity = ""
        $script:AllowMissingRuntimeDataAuthority = $true
        $script:RuntimeDataBindingPresent = $false
        return
    }
    $binding = Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $RuntimeDataBindingServiceAccounts
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
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
if (-not (Test-Path -LiteralPath $LockScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期锁脚本：$LockScript"
}
. $LockScript
$InstallerState = Get-TicketboxInstallerStateDirectory
$OwnerBootstrapPath = Join-Path $InstallerState "owner-bootstrap.txt"
$OwnerHandoffPendingPath = Join-Path $InstallerState "owner-handoff-pending"
$RecoveryRequiredPath = Join-Path $InstallerState "installer-recovery-required.json"
$BootstrapExposureRecoveryPath = Join-Path `
    (Split-Path -Parent (Get-TicketboxLifecycleLockPath)) `
    "bootstrap-exposure-recovery.env"
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
$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"
if (-not (Test-Path -LiteralPath $DatabaseSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 数据库安全脚本：$DatabaseSafetyScript"
}
. $DatabaseSafetyScript
$DatabaseScript = Join-Path $ScriptDir "windows_bundled_database.ps1"
if (-not (Test-Path -LiteralPath $DatabaseScript -PathType Leaf)) {
    throw "缺少 Windows bundled database 脚本：$DatabaseScript"
}
. $DatabaseScript
$BackendBootstrapScript = Join-Path $ScriptDir "windows_backend_bootstrap.ps1"
if (-not (Test-Path -LiteralPath $BackendBootstrapScript -PathType Leaf)) {
    throw "缺少 Windows 后端就绪/bootstrap 脚本：$BackendBootstrapScript"
}
. $BackendBootstrapScript
$BootstrapExposureRecoveryScript = Join-Path $ScriptDir "windows_bootstrap_exposure_recovery.ps1"
if (-not (Test-Path -LiteralPath $BootstrapExposureRecoveryScript -PathType Leaf)) {
    throw "缺少 bootstrap 暴露恢复脚本：$BootstrapExposureRecoveryScript"
}
. $BootstrapExposureRecoveryScript
function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn2([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Assert-Admin {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator
    )
    if (-not $admin) {
        throw "需要管理员权限运行安装脚本。"
    }
}

function Assert-SimpleIdentifier([string]$Value, [string]$Name) {
    if ($Value -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "$Name 只能包含字母、数字、下划线，且不能以数字开头：$Value"
    }
}

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 $Label：$Path"
    }
}

function Assert-Dir([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "缺少 $Label：$Path"
    }
}

function Service-Exists([string]$Name) {
    return Test-TicketboxServiceExists $Name
}

function Invoke-ScChecked([string[]]$ScArgs) {
    return Invoke-TicketboxScChecked $ScArgs
}

function Get-ExpectedServiceExecutable([string]$Name) {
    if ($Name -eq $PgServiceName) {
        return Join-Path $PgBin "pg_ctl.exe"
    }
    if ($Name -eq $BackendServiceName) {
        return $ShawlExe
    }
    throw "未知 Ticketbox 服务：$Name"
}

function Assert-TicketboxServiceRuntimeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedPgData,
        [Parameter(Mandatory = $true)][string]$ExpectedAppData,
        [Parameter(Mandatory = $true)][string]$ExpectedLogDir,
        [string]$ExpectedDataRootMarkerPath = "",
        [string]$ExpectedDataVolumeIdentity = "",
        [int]$ExpectedStopTimeoutMs = $StopTimeoutMs,
        [int]$ExpectedRestartDelayMs = $RestartDelayMs,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowMissingRuntimeDataAuthority,
        [switch]$AllowMissingOwnerRecoveryChannel
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
        -ExpectedPgDumpPath (Join-Path $PgBin "pg_dump.exe") `
        -ExpectedPgRestorePath (Join-Path $PgBin "pg_restore.exe") `
        -ExpectedBootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath `
        -ExpectedInstallerRecoveryGuardPath $InstallerRuntimeRecoveryGuardPath `
        -ExpectedDataRootMarkerPath $ExpectedDataRootMarkerPath `
        -ExpectedDataVolumeIdentity $ExpectedDataVolumeIdentity `
        -ExpectedOwnerRecoveryChannel $OwnerRecoveryChannel `
        -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
        -ExpectedRestartDelayMs $ExpectedRestartDelayMs `
        -AllowMissingInstallerRecoveryGuard:$AllowMissingInstallerRecoveryGuard `
        -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority `
        -AllowMissingOwnerRecoveryChannel:$AllowMissingOwnerRecoveryChannel
}

function Assert-ExpectedServiceConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$ExpectedStopTimeoutMs = $StopTimeoutMs,
        [int]$ExpectedRestartDelayMs = $RestartDelayMs,
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowLegacyRuntimeDataContract,
        [switch]$AllowMissingOwnerRecoveryChannel
    )
    if (-not (Service-Exists $Name)) {
        return
    }
    Assert-TicketboxServiceOwnership -Name $Name -ExpectedExecutable (Get-ExpectedServiceExecutable $Name) | Out-Null
    Assert-TicketboxServiceAccount -Name $Name -ExpectedAccount "NT SERVICE\$Name"
    $targetError = $null
    try {
        Assert-TicketboxServiceRuntimeCommand `
            -Name $Name `
            -ExpectedPgData $ServicePgData `
            -ExpectedAppData $ServiceAppData `
            -ExpectedLogDir $ServiceLogDir `
            -ExpectedDataRootMarkerPath $ServiceDataRootMarkerPath `
            -ExpectedDataVolumeIdentity $ServiceDataVolumeIdentity `
            -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
            -ExpectedRestartDelayMs $ExpectedRestartDelayMs `
            -AllowMissingInstallerRecoveryGuard:$AllowMissingInstallerRecoveryGuard `
            -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority `
            -AllowMissingOwnerRecoveryChannel:$AllowMissingOwnerRecoveryChannel
        return
    }
    catch {
        $targetError = $_
    }
    if ($AllowTargetPolicyFallback -and $Name -eq $BackendServiceName) {
        try {
            Assert-TicketboxServiceRuntimeCommand `
                -Name $Name `
                -ExpectedPgData $ServicePgData `
                -ExpectedAppData $ServiceAppData `
                -ExpectedLogDir $ServiceLogDir `
                -ExpectedDataRootMarkerPath $ServiceDataRootMarkerPath `
                -ExpectedDataVolumeIdentity $ServiceDataVolumeIdentity `
                -ExpectedStopTimeoutMs $StopTimeoutMs `
                -ExpectedRestartDelayMs $RestartDelayMs `
                -AllowMissingInstallerRecoveryGuard:$AllowMissingInstallerRecoveryGuard `
                -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority `
                -AllowMissingOwnerRecoveryChannel:$AllowMissingOwnerRecoveryChannel
            return
        }
        catch { }
    }
    if (-not $AllowLegacyRuntimeDataContract -or -not $RuntimeDataBindingPresent) {
        throw $targetError
    }
    $legacyError = $null
    try {
        Assert-TicketboxServiceRuntimeCommand `
            -Name $Name `
            -ExpectedPgData $PgData `
            -ExpectedAppData $AppData `
            -ExpectedLogDir $LogDir `
            -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
            -ExpectedRestartDelayMs $ExpectedRestartDelayMs `
            -AllowMissingInstallerRecoveryGuard:$AllowMissingInstallerRecoveryGuard `
            -AllowMissingRuntimeDataAuthority `
            -AllowMissingOwnerRecoveryChannel:$AllowMissingOwnerRecoveryChannel
        return
    }
    catch {
        $legacyError = $_
    }
    if ($AllowTargetPolicyFallback -and $Name -eq $BackendServiceName) {
        try {
            Assert-TicketboxServiceRuntimeCommand `
                -Name $Name `
                -ExpectedPgData $PgData `
                -ExpectedAppData $AppData `
                -ExpectedLogDir $LogDir `
                -ExpectedStopTimeoutMs $StopTimeoutMs `
                -ExpectedRestartDelayMs $RestartDelayMs `
                -AllowMissingInstallerRecoveryGuard:$AllowMissingInstallerRecoveryGuard `
                -AllowMissingRuntimeDataAuthority `
                -AllowMissingOwnerRecoveryChannel:$AllowMissingOwnerRecoveryChannel
            return
        }
        catch { }
    }
    throw "Windows 服务 $Name 不匹配 runtime binding 迁移允许的任一精确合同。target=$($targetError.Exception.Message); legacy=$($legacyError.Exception.Message)"
}

function Stop-ServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$ExpectedStopTimeoutMs = $StopTimeoutMs,
        [int]$ExpectedRestartDelayMs = $RestartDelayMs,
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowLegacyRuntimeDataContract,
        [switch]$AllowMissingOwnerRecoveryChannel
    )
    Assert-ExpectedServiceConfiguration `
        -Name $Name `
        -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
        -ExpectedRestartDelayMs $ExpectedRestartDelayMs `
        -AllowTargetPolicyFallback:$AllowTargetPolicyFallback `
        -AllowMissingInstallerRecoveryGuard:$AllowMissingInstallerRecoveryGuard `
        -AllowLegacyRuntimeDataContract:$AllowLegacyRuntimeDataContract `
        -AllowMissingOwnerRecoveryChannel:$AllowMissingOwnerRecoveryChannel
    $backendStopPort = if ($Name -eq $BackendServiceName) { $BackendPort } else { 0 }
    $runtimeExecutables = if ($Name -eq $BackendServiceName) {
        @($BackendExe, $ShawlExe)
    }
    else {
        @($PgCtl, (Join-Path $PgBin "postgres.exe"))
    }
    Stop-TicketboxOwnedServiceIfExists `
        -Name $Name `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $Name) `
        -BackendPort $backendStopPort `
        -ExpectedRuntimeExecutables $runtimeExecutables `
        @ServiceWaitArguments
}

function Remove-ServiceIfExists {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$ExpectedStopTimeoutMs = $StopTimeoutMs,
        [int]$ExpectedRestartDelayMs = $RestartDelayMs
    )
    Assert-ExpectedServiceConfiguration `
        -Name $Name `
        -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
        -ExpectedRestartDelayMs $ExpectedRestartDelayMs
    $backendStopPort = if ($Name -eq $BackendServiceName) { $BackendPort } else { 0 }
    $runtimeExecutables = if ($Name -eq $BackendServiceName) {
        @($BackendExe, $ShawlExe)
    }
    else {
        @($PgCtl, (Join-Path $PgBin "postgres.exe"))
    }
    Remove-TicketboxOwnedServiceIfExists `
        -Name $Name `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $Name) `
        -BackendPort $backendStopPort `
        -ExpectedRuntimeExecutables $runtimeExecutables `
        @ServiceWaitArguments
}

function Register-PgService {
    param([switch]$RuntimeBindingTransition)

    Write-Step "注册 PostgreSQL 服务 $PgServiceName"
    $pgImagePath = New-TicketboxPgServiceImagePath `
        -PgCtlPath $PgCtl `
        -ServiceName $PgServiceName `
        -DataRoot $ServicePgData
    if (Service-Exists $PgServiceName) {
        Assert-TicketboxServiceOwnership -Name $PgServiceName -ExpectedExecutable $PgCtl | Out-Null
        if (-not $RuntimeBindingTransition) {
            Assert-ExpectedServiceConfiguration $PgServiceName
        }
        Invoke-ScChecked @("config", $PgServiceName, "start=", "demand") | Out-Null
    }
    else {
        Invoke-ScChecked @(
            "create", $PgServiceName,
            "binPath=", $pgImagePath,
            "start=", "demand",
            "obj=", "NT SERVICE\$PgServiceName"
        ) | Out-Null
        Assert-ExpectedServiceConfiguration $PgServiceName
    }
    Invoke-ScChecked @("config", $PgServiceName, "start=", "demand") | Out-Null
    Invoke-ScChecked @("config", $PgServiceName, "binPath=", $pgImagePath) | Out-Null
    Invoke-ScChecked @("config", $PgServiceName, "obj=", "NT SERVICE\$PgServiceName") | Out-Null
    Invoke-ScChecked @(
        "failure", $PgServiceName, "reset=", [string]$ScmFailureResetSeconds, "actions=", $ScmRestartActions
    ) | Out-Null
    Assert-ExpectedServiceConfiguration $PgServiceName
    Assert-TicketboxServiceStartMode -Name $PgServiceName -ExpectedStartMode "Manual"
    Write-Ok "PG 服务已以 demand-start 注册为虚拟账户 NT SERVICE\$PgServiceName。"
}

function Register-BackendService {
    Write-Step "注册后端服务 $BackendServiceName"
    $backendImagePath = New-TicketboxShawlServiceImagePath `
        -ShawlPath $ShawlExe `
        -ServiceName $BackendServiceName `
        -WorkingDirectory $ServiceAppData `
        -LogDirectory $ServiceLogDir `
        -BackendPath $BackendExe `
        -PgDumpPath $PgDump `
        -PgRestorePath $PgRestore `
        -BootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath `
        -InstallerRecoveryGuardPath $InstallerRuntimeRecoveryGuardPath `
        -DataRootMarkerPath $ServiceDataRootMarkerPath `
        -DataVolumeIdentity $ServiceDataVolumeIdentity `
        -OwnerRecoveryChannel $OwnerRecoveryChannel `
        -StopTimeoutMs $StopTimeoutMs `
        -RestartDelayMs $RestartDelayMs
    if (Service-Exists $BackendServiceName) {
        Assert-TicketboxServiceOwnership -Name $BackendServiceName -ExpectedExecutable $ShawlExe | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "start=", "disabled") | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "binPath=", $backendImagePath) | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "depend=", $PgServiceName) | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "obj=", "NT SERVICE\$BackendServiceName") | Out-Null
    }
    else {
        Invoke-ScChecked @(
            "create", $BackendServiceName,
            "binPath=", $backendImagePath,
            "start=", "disabled",
            "depend=", $PgServiceName,
            "obj=", "NT SERVICE\$BackendServiceName"
        ) | Out-Null
    }
    Invoke-ScChecked @(
        "failure", $BackendServiceName, "reset=", [string]$ScmFailureResetSeconds, "actions=", $ScmRestartActions
    ) | Out-Null
    Assert-ExpectedServiceConfiguration $BackendServiceName
    Assert-TicketboxServiceStartMode -Name $BackendServiceName -ExpectedStartMode "Disabled"
    Write-Ok "后端服务已以 disabled 注册；runtime recovery guard 发布前不可启动。"
}

function Invoke-IcaclsChecked([string[]]$Arguments) {
    if ($Arguments.Count -lt 2) {
        throw "icacls 包装器至少需要目标路径和一个参数。"
    }
    $icaclsArguments = @($Arguments[1..($Arguments.Count - 1)])
    Invoke-TicketboxIcaclsChecked -Path $Arguments[0] -Arguments $icaclsArguments
}

function Set-TicketboxAcl(
    [bool]$IncludePgService = $true,
    [bool]$IncludeBackendService = $true
) {
    Write-Step "收紧 ProgramData ACL"
    New-Item -ItemType Directory -Force -Path $DataRoot, $PgData, $AppData, $LogDir, $BackupDir | Out-Null

    $systemAndAdmins = @("SYSTEM", "BUILTIN\Administrators")
    $rootReadAccounts = @()
    $pgAccounts = @($systemAndAdmins)
    $appAccounts = @($systemAndAdmins)
    $markerReadAccounts = @()
    if ($IncludePgService) {
        $rootReadAccounts += "NT SERVICE\$PgServiceName"
        $pgAccounts += "NT SERVICE\$PgServiceName"
    }
    if ($IncludeBackendService) {
        $rootReadAccounts += "NT SERVICE\$BackendServiceName"
        $appAccounts += "NT SERVICE\$BackendServiceName"
        $markerReadAccounts += "NT SERVICE\$BackendServiceName"
    }
    Set-TicketboxExactDirectoryAcl `
        -Path $DataRoot `
        -Accounts $systemAndAdmins `
        -ReadExecuteAccounts $rootReadAccounts
    Set-TicketboxExactDirectoryAcl `
        -Path $PgData `
        -Accounts $pgAccounts `
        -Recurse
    Set-TicketboxExactDirectoryAcl `
        -Path $AppData `
        -Accounts $appAccounts `
        -Recurse
    Initialize-TicketboxInstallerStateDirectory $InstallerState | Out-Null
    if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath -PathType Leaf) {
        Set-TicketboxExactFileAcl `
            -Path $BootstrapExposureRecoveryGuardPath `
            -Accounts $systemAndAdmins `
            -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
            -OwnerAccount "SYSTEM"
    }
    if (Test-Path -LiteralPath $InstallerRuntimeRecoveryGuardPath -PathType Leaf) {
        Set-TicketboxExactFileAcl `
            -Path $InstallerRuntimeRecoveryGuardPath `
            -Accounts $systemAndAdmins `
            -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
            -OwnerAccount "SYSTEM"
    }
    Set-TicketboxExactFileAcl `
        -Path (Get-TicketboxDataRootMarkerPath $DataRoot) `
        -Accounts $systemAndAdmins `
        -ReadExecuteAccounts $markerReadAccounts `
        -OwnerAccount "SYSTEM"
    if ($IncludeBackendService) {
        Invoke-IcaclsChecked @($ProgramDir, "/grant", "NT SERVICE\${BackendServiceName}:(OI)(CI)RX")
    }
    if ($IncludePgService) {
        Invoke-IcaclsChecked @($PgHome, "/grant", "NT SERVICE\${PgServiceName}:(OI)(CI)RX")
    }
    Write-Ok "数据根已限制为 SYSTEM / Administrators / Ticketbox 服务账户。"
}

function Initialize-TicketboxInstallerStateArtifacts {
    Assert-TicketboxDataRootMarker -DataRoot $DataRoot -InstallDir $InstallDir
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $LegacyRecoveryRequiredPath `
        -CurrentPath $RecoveryRequiredPath
    Move-TicketboxLegacyOwnerHandoffArtifacts `
        -InstallerStatePath $InstallerState `
        -LegacyOwnerBootstrapPath $LegacyOwnerBootstrapPath `
        -LegacyOwnerHandoffPendingPath $LegacyOwnerHandoffPendingPath
}

function Assert-PortAvailableForMissingServices {
    foreach ($entry in @(
        @{
            Name = $PgServiceName
            Port = $PgPort
            Executables = @($PgCtl, (Join-Path $PgBin "postgres.exe"))
        },
        @{
            Name = $BackendServiceName
            Port = $BackendPort
            Executables = @($BackendExe, $ShawlExe)
        }
    )) {
        if (Service-Exists $entry.Name) {
            continue
        }
        Assert-TicketboxRuntimeAbsent `
            -Name ([string]$entry.Name) `
            -RuntimePort ([int]$entry.Port) `
            -ExpectedRuntimeExecutables @($entry.Executables)
    }
}

function Assert-TicketboxPgClusterStoppedAfterFailure {
    if (-not (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION") -PathType Leaf)) {
        return
    }
    $statusResult = Invoke-TicketboxBoundedNativeProcess `
        -FilePath $PgCtl `
        -Arguments @('status', '-D', $PgData) `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs `
        -Label 'pg_ctl install-compensation verification'
    $rc = $statusResult.ExitCode
    if ($rc -eq 0) {
        throw "安装失败补偿后 PostgreSQL 数据簇仍在运行。"
    }
    if ($rc -ne 3) {
        throw "安装失败补偿无法确认 PostgreSQL 已停止（exit=$rc）。"
    }
}

function Invoke-TicketboxInstallFailureCompensation([string]$Reason) {
    $failures = @()
    foreach ($service in @(
        @{
            Name = $BackendServiceName
            Executable = $ShawlExe
            BackendPort = $BackendPort
            RuntimeExecutables = @($BackendExe, $ShawlExe)
        },
        @{
            Name = $PgServiceName
            Executable = $PgCtl
            BackendPort = 0
            RuntimeExecutables = @($PgCtl, (Join-Path $PgBin "postgres.exe"))
        }
    )) {
        try {
            Disable-TicketboxOwnedServiceIfExists `
                -Name $service.Name `
                -ExpectedExecutable $service.Executable `
                -BackendPort ([int]$service.BackendPort) `
                -ExpectedRuntimeExecutables @($service.RuntimeExecutables) `
                @ServiceWaitArguments
        }
        catch {
            $failures += $_.Exception.Message
        }
    }
    try {
        Assert-TicketboxPgClusterStoppedAfterFailure
    }
    catch {
        $failures += $_.Exception.Message
    }
    try {
        Ensure-TicketboxInstallerRecoveryMarkerAfterFailure `
            -InstallerStatePath $InstallerState `
            -LegacyPath $LegacyRecoveryRequiredPath `
            -CurrentPath $RecoveryRequiredPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -Reason $Reason
    }
    catch {
        $failures += $_.Exception.Message
    }
    if ($failures.Count -gt 0) {
        throw "安装失败补偿不完整：$($failures -join '；')"
    }
}

Write-Host "=== 小票夹 Inno 安装器服务配置 ===" -ForegroundColor Cyan
if ($PgPort -eq $BackendPort) {
    throw "PostgreSQL 服务端口和后端 API 端口不能相同。"
}
Assert-SimpleIdentifier $DbName "DbName"
Assert-SimpleIdentifier $DbRole "DbRole"

Write-Step "校验安装输入"
Assert-Dir $InstallDir "安装目录"
Assert-File (Join-Path $PgBin "initdb.exe") "initdb.exe"
Assert-File (Join-Path $PgBin "postgres.exe") "postgres.exe"
Assert-File (Join-Path $PgBin "pg_ctl.exe") "pg_ctl.exe"
Assert-File (Join-Path $PgBin "psql.exe") "psql.exe"
Assert-File (Join-Path $PgBin "pg_dump.exe") "pg_dump.exe"
Assert-File (Join-Path $PgBin "pg_restore.exe") "pg_restore.exe"
Assert-File $BackendExe "ticketbox-backend.exe"
Assert-File $ShawlExe "shawl.exe"
$installedBuildManifest = Read-TicketboxInstalledBuildManifest `
    -Path $InstalledBuildManifestPath `
    -ExpectedPgMajor $TargetPgMajor
if ($TargetPgMajor -eq 0) {
    $TargetPgMajor = $installedBuildManifest.PgMajor
}
Write-Ok "安装输入齐备。"

if ($ValidateOnly) {
    Write-Host ""
    Write-Host "ValidateOnly OK。" -ForegroundColor Green
    return
}

function Assert-TicketboxDeferredPreservedPgServiceConfiguration {
    Assert-TicketboxServiceOwnership `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl | Out-Null
    Assert-TicketboxServiceAccount `
        -Name $PgServiceName `
        -ExpectedAccount "NT SERVICE\$PgServiceName"
    Assert-TicketboxPgServiceCommand `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedServiceName $PgServiceName `
        -ExpectedDataRoot $PgData
}

function Register-TicketboxDeferredPreservedPgService {
    if (Service-Exists $PgServiceName) {
        throw "preserved-data 临时 PostgreSQL 服务在注册前已存在。"
    }
    $imagePath = New-TicketboxPgServiceImagePath `
        -PgCtlPath $PgCtl `
        -ServiceName $PgServiceName `
        -DataRoot $PgData
    Invoke-ScChecked @(
        "create",
        $PgServiceName,
        "binPath=",
        $imagePath,
        "start=",
        "demand",
        "obj=",
        "NT SERVICE\$PgServiceName"
    ) | Out-Null
    Assert-TicketboxDeferredPreservedPgServiceConfiguration
}

function Remove-TicketboxDeferredPreservedPgServiceIfExists {
    if (-not (Service-Exists $PgServiceName)) { return }
    Assert-TicketboxDeferredPreservedPgServiceConfiguration
    Remove-TicketboxOwnedServiceIfExists `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
        @ServiceWaitArguments
}

function Assert-DesktopManagerExpectedServiceNames {
    if (
        $ExpectedBackendServiceName.Trim().Length -eq 0 -or
        $ExpectedPgServiceName.Trim().Length -eq 0 -or
        -not [string]::Equals(
            $ExpectedBackendServiceName,
            $BackendServiceName,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        -not [string]::Equals(
            $ExpectedPgServiceName,
            $PgServiceName,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "桌面管理器登记的服务名与安装 release config 不一致。"
    }
}

if ($ValidateInstalledServicesOnly) {
    Assert-Admin
    Assert-DesktopManagerExpectedServiceNames
    Set-TicketboxRuntimeServiceContractFromBinding -RequireBinding
    if (-not (Service-Exists $BackendServiceName) -or -not (Service-Exists $PgServiceName)) {
        throw "正式安装服务不完整，拒绝桌面管理器执行 SCM 变更。"
    }
    Assert-ExpectedServiceConfiguration $PgServiceName
    Assert-ExpectedServiceConfiguration $BackendServiceName
    Assert-TicketboxServiceFailurePolicy `
        -Name $PgServiceName `
        -ExpectedResetSeconds $ScmFailureResetSeconds `
        -ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)
    Assert-TicketboxServiceFailurePolicy `
        -Name $BackendServiceName `
        -ExpectedResetSeconds $ScmFailureResetSeconds `
        -ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)
    Assert-TicketboxServiceDelayedAutoStart $PgServiceName
    Assert-TicketboxServiceDelayedAutoStart $BackendServiceName
    Write-Host "Installed service contract OK。" -ForegroundColor Green
    return
}

if ($ValidateBackendRuntimeStoppedOnly) {
    Assert-Admin
    Assert-DesktopManagerExpectedServiceNames
    Wait-TicketboxBackendRuntimeStopped `
        -Name $BackendServiceName `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments
    Write-Host "Installed backend runtime stopped OK。" -ForegroundColor Green
    return
}

if ($CompleteOwnerHandoffOnly) {
    if ($InstallerLockOwnerProcessId -le 0) {
        throw "首次绑定交付清理只允许由当前安装器生命周期调用。"
    }
    Assert-Admin
    $handoffLock = Enter-TicketboxLifecycleLock `
        -ExternalOwnerProcessId $InstallerLockOwnerProcessId
    try {
        Assert-TicketboxDataRootMarker -DataRoot $DataRoot -InstallDir $InstallDir
        if (
            (Test-Path -LiteralPath $LegacyOwnerBootstrapPath) -or
            (Test-Path -LiteralPath $LegacyOwnerHandoffPendingPath)
        ) {
            throw "完成页清理不迁移 legacy owner handoff；请重新运行 repair 安装。"
        }
        Assert-TicketboxProtectedDirectoryAcl $InstallerState
        Complete-TicketboxOwnerBootstrapHandoff
        Write-Host "Owner bootstrap handoff artifacts removed OK。" -ForegroundColor Green
    }
    finally {
        Exit-TicketboxLifecycleLock $handoffLock
    }
    return
}

if ($InstallerLockOwnerProcessId -le 0) {
    throw "正式安装或升级只能由持有生命周期锁和回执的 Inno 安装器调用。"
}
if ($LifecycleReceiptPath.Trim().Length -eq 0) {
    throw "正式安装或升级缺少生命周期回执路径。"
}

$operationLock = Enter-TicketboxLifecycleLock `
    -ExternalOwnerProcessId $InstallerLockOwnerProcessId
$mutationStarted = $false
$DeferredPreservedDataBackup = $false
try {
    Assert-Admin
    Set-TicketboxRuntimeServiceContractFromBinding
    if ($InstallerLockOwnerProcessId -gt 0) {
        if ($LifecycleReceiptPath.Trim().Length -eq 0) {
            throw "Inno 安装缺少受保护的生命周期回执。"
        }
        $lifecycleReceipt = Read-TicketboxLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $ReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        if (
            [string]$lifecycleReceipt.preparation_stage -eq "program_files_installed_backup_pending" -and
            [string]$lifecycleReceipt.mode -eq "preserved_data_reinstall" -and
            [bool]$lifecycleReceipt.backup_required -and
            -not [bool]$lifecycleReceipt.backup_completed
        ) {
            $DeferredPreservedDataBackup = $true
        }
        elseif ([string]$lifecycleReceipt.preparation_stage -eq "prepared") {
            Set-TicketboxLifecycleReceiptFilesMayHaveBeenReplaced `
                -Path $LifecycleReceiptPath `
                -Receipt $lifecycleReceipt `
                -InstallerOwnerProcessId $InstallerLockOwnerProcessId
            $lifecycleReceipt.preparation_stage = "files_may_have_been_replaced"
            $lifecycleReceipt.files_may_have_been_replaced = $true
        }
        elseif ([string]$lifecycleReceipt.preparation_stage -ne "files_may_have_been_replaced") {
            throw "安装生命周期回执不允许服务安装阶段继续：$($lifecycleReceipt.preparation_stage)。"
        }
        $PreviousReleaseConfig = $lifecycleReceipt.installed_release_config
        $PreviousStopTimeoutMs = [int]$PreviousReleaseConfig.stop_timeout_ms
        $PreviousRestartDelayMs = [int]$PreviousReleaseConfig.restart_delay_ms
        $PreUpgradeBackupAlreadyCompleted = [bool]$lifecycleReceipt.backup_completed
        $FilesMayHaveBeenReplaced = [bool]$lifecycleReceipt.files_may_have_been_replaced
    }
    else {
        if ($LifecycleReceiptPath.Trim().Length -gt 0) {
            throw "直接运行安装脚本不能提交或伪造 Inno 生命周期回执。"
        }
        $lifecycleReceipt = $null
        $PreUpgradeBackupAlreadyCompleted = $false
        $FilesMayHaveBeenReplaced = $false
    }

    $preExistingPgService = Service-Exists $PgServiceName
    $preExistingBackendService = Service-Exists $BackendServiceName
    $serviceReadAccounts = @()
    if ($preExistingPgService) { $serviceReadAccounts += "NT SERVICE\$PgServiceName" }
    if ($preExistingBackendService) { $serviceReadAccounts += "NT SERVICE\$BackendServiceName" }
    Initialize-TicketboxSecureInstallRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $serviceReadAccounts | Out-Null
    Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir | Out-Null
    Assert-PortAvailableForMissingServices
    $hadExistingPgService = Service-Exists $PgServiceName
    $hadExistingBackendService = Service-Exists $BackendServiceName
    Assert-ExpectedServiceConfiguration `
        -Name $BackendServiceName `
        -ExpectedStopTimeoutMs $PreviousStopTimeoutMs `
        -ExpectedRestartDelayMs $PreviousRestartDelayMs `
        -AllowTargetPolicyFallback:$FilesMayHaveBeenReplaced `
        -AllowMissingInstallerRecoveryGuard:$hadExistingBackendService `
        -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent `
        -AllowMissingOwnerRecoveryChannel:$hadExistingBackendService
    Assert-ExpectedServiceConfiguration `
        -Name $PgServiceName `
        -ExpectedStopTimeoutMs $PreviousStopTimeoutMs `
        -ExpectedRestartDelayMs $PreviousRestartDelayMs `
        -AllowTargetPolicyFallback:$FilesMayHaveBeenReplaced `
        -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent

    if ($DeferredPreservedDataBackup) {
        Assert-TicketboxLegacyPreservedDataLayout `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -EnvPath $EnvPath `
            -PgData $PgData `
            -ExpectedPgMajor $TargetPgMajor | Out-Null
        Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending `
            -Path $LifecycleReceiptPath `
            -Receipt $lifecycleReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -CleanupPending $true
        $lifecycleReceipt.temporary_pg_service_cleanup_pending = $true
        $deferredBackupFailure = $null
        $deferredBackupPath = ""
        try {
            Register-TicketboxDeferredPreservedPgService
            Start-TicketboxOwnedServiceIfExists `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                @ServiceWaitArguments | Out-Null
            $deferredBackupPath = Invoke-TicketboxPreservedDataReinstallBackup `
                -TargetDirectory (Get-TicketboxDeferredBackupRoot) `
                -ExpectedPgMajor $TargetPgMajor
        }
        catch {
            $deferredBackupFailure = $_.Exception
        }
        finally {
            try {
                Remove-TicketboxDeferredPreservedPgServiceIfExists
                Set-TicketboxLifecycleReceiptTemporaryPgServiceCleanupPending `
                    -Path $LifecycleReceiptPath `
                    -Receipt $lifecycleReceipt `
                    -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
                    -CleanupPending $false
                $lifecycleReceipt.temporary_pg_service_cleanup_pending = $false
            }
            catch {
                if ($null -eq $deferredBackupFailure) {
                    $deferredBackupFailure = $_.Exception
                }
                else {
                    $deferredBackupFailure = New-Object System.InvalidOperationException(
                        "$($deferredBackupFailure.Message) 临时 PostgreSQL SCM 服务清理失败：$($_.Exception.Message)"
                    )
                }
            }
        }
        if ($null -ne $deferredBackupFailure) { throw $deferredBackupFailure }
        Set-TicketboxLifecycleReceiptDeferredBackupCompleted `
            -Path $LifecycleReceiptPath `
            -Receipt $lifecycleReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -BackupPath $deferredBackupPath
        $lifecycleReceipt.preparation_stage = "files_may_have_been_replaced"
        $lifecycleReceipt.backup_completed = $true
        $lifecycleReceipt.backup_path = $deferredBackupPath
        $lifecycleReceipt.files_may_have_been_replaced = $true
        $PreUpgradeBackupAlreadyCompleted = $true
        $FilesMayHaveBeenReplaced = $true
        Write-Ok "legacy 保留数据已在服务/应用变更前完成可验证备份。"
    }

    if ($hadExistingPgService) {
        Assert-NoTicketboxAncestorReparsePoints $DataRoot
        Assert-NoTicketboxReparsePoints $DataRoot
    }
    Initialize-TicketboxDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir

    $mutationStarted = $true
    Stop-ServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedStopTimeoutMs $PreviousStopTimeoutMs `
        -ExpectedRestartDelayMs $PreviousRestartDelayMs `
        -AllowTargetPolicyFallback:$FilesMayHaveBeenReplaced `
        -AllowMissingInstallerRecoveryGuard:$hadExistingBackendService `
        -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent `
        -AllowMissingOwnerRecoveryChannel:$hadExistingBackendService
    if (-not $hadExistingPgService) {
        Initialize-TicketboxSecureDataRoot `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -Accounts @("SYSTEM", "BUILTIN\Administrators")
    }
    New-Item -ItemType Directory -Force -Path $AppData, $LogDir, $BackupDir | Out-Null
    Initialize-TicketboxInstallerStateArtifacts
    $handoffDisposition = Adopt-TicketboxOwnerBootstrapHandoff
    if ($handoffDisposition -ceq "pending") {
        Write-Ok "已接管上次中断的 owner 绑定交付。"
    }
    elseif ($handoffDisposition -ceq "cleaned_confirmed") {
        Write-Ok "已清理上次确认完成的 owner 绑定交付残留。"
    }
    if ($hadExistingPgService) {
        Set-TicketboxAcl `
            -IncludePgService $true `
            -IncludeBackendService $hadExistingBackendService
    }
    $serviceLayerBackupRequired =
        -not $PreUpgradeBackupAlreadyCompleted -and
        (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION") -PathType Leaf) -and
        (Test-Path -LiteralPath $EnvPath -PathType Leaf)
    if ($serviceLayerBackupRequired -and -not (Service-Exists $PgServiceName)) {
        Register-PgService
        Set-TicketboxAcl -IncludePgService $true -IncludeBackendService $false
    }
    Invoke-PreUpgradeBackupIfNeeded

    $superPassword = Initialize-PgClusterIfNeeded
    Initialize-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $RuntimeDataBindingServiceAccounts | Out-Null
    Set-TicketboxRuntimeServiceContractFromBinding -RequireBinding
    Register-PgService -RuntimeBindingTransition
    Register-BackendService
    Write-TicketboxInstallerRuntimeRecoveryGuard `
        -Path $InstallerRuntimeRecoveryGuardPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName
    Set-TicketboxAcl
    Read-TicketboxInstallerRuntimeRecoveryGuard `
        -Path $InstallerRuntimeRecoveryGuardPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName | Out-Null
    Set-TicketboxOwnedServiceDemandStartIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable $ShawlExe
    Assert-TicketboxServiceStartMode -Name $BackendServiceName -ExpectedStartMode "Manual"

    Write-Step "启动 PostgreSQL"
    Start-TicketboxOwnedServiceIfExists `
        -Name $PgServiceName `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $PgServiceName) `
        @ServiceWaitArguments | Out-Null
    Wait-PgReady
    $databaseUrl = Prepare-DatabaseIfNeeded $superPassword
    $resumedBootstrapSecret = Resolve-TicketboxBootstrapExposureRecoveryIntent `
        -DatabaseUrl $databaseUrl `
        -StartBackendAfterRecovery:(-not $SkipServiceStart)
    if (-not [string]::IsNullOrWhiteSpace([string]$resumedBootstrapSecret)) {
        Write-Warn2 "已完成上次中断的 bootstrap 暴露恢复。"
    }

    if ($SkipServiceStart) {
        Write-Warn2 "SkipServiceStart 已设置，服务已注册但未启动后端。"
    }
    else {
        Write-Step "启动后端服务"
        Start-TicketboxOwnedServiceIfExists `
            -Name $BackendServiceName `
            -ExpectedExecutable (Get-ExpectedServiceExecutable $BackendServiceName) `
            @ServiceWaitArguments | Out-Null
        Wait-BackendHealth
        Complete-FirstOwnerBootstrapIfEnabled $databaseUrl
    }

    Write-Host ""
    Write-Host "================ 安装完成 ================" -ForegroundColor Green
    Write-Host "安装目录 : $InstallDir"
    Write-Host "数据目录 : $DataRoot"
    Write-Host "后端地址 : http://127.0.0.1:$BackendPort"
    Write-Host "owner 凭证: $OwnerBootstrapPath（首次安装时生成）"
    Write-Host "=========================================" -ForegroundColor Green
}
catch {
    $failure = $_.Exception
    if ($mutationStarted) {
        try {
            Invoke-TicketboxInstallFailureCompensation $failure.Message
        }
        catch {
            throw "$($failure.Message) 同时安装失败补偿未完整完成：$($_.Exception.Message)"
        }
    }
    throw $failure
}
finally {
    Exit-TicketboxLifecycleLock $operationLock
}
