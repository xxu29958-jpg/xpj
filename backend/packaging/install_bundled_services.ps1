#Requires -Version 5.1
<#
.SYNOPSIS
  Install the bundled Ticketbox Windows services for a fresh empty source.

.DESCRIPTION
  This is the script run by the Inno installer after files have been copied to
  Program Files. It keeps mutable data in ProgramData, registers the bundled
  PostgreSQL service plus the frozen backend service, and executes the unique
  database Generation Owner. The current closed path accepts only a fresh empty
  source; upgrade, preserved-data repair/reinstall, and operator restore remain
  fail-closed and are not qualified by this script.

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
    [string]$LifecycleFinalizationAttemptId = "",
    [string]$PublicFailurePath = "",
    [string]$DiagnosticLogPath = "",
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
$PgServiceLogonAccount = Get-TicketboxReleaseServiceLogonAccount `
    -Config $ReleaseConfig `
    -ServiceName $PgServiceName
$BackendServiceLogonAccount = Get-TicketboxReleaseServiceLogonAccount `
    -Config $ReleaseConfig `
    -ServiceName $BackendServiceName
$TargetServiceSidType = Get-TicketboxReleaseServiceSidType $ReleaseConfig
$StopTimeoutMs = [int]$ReleaseConfig.stop_timeout_ms
$RestartDelayMs = [int]$ReleaseConfig.restart_delay_ms
$PreviousStopTimeoutMs = [int]$PreviousReleaseConfig.stop_timeout_ms
$PreviousRestartDelayMs = [int]$PreviousReleaseConfig.restart_delay_ms
$ServiceIdentityLifecycleReceipt = $null
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
$InitdbExe = Join-Path $PgBin "initdb.exe"
$PgReady = Join-Path $PgBin "pg_isready.exe"
$Psql = Join-Path $PgBin "psql.exe"
$PgDump = Join-Path $PgBin "pg_dump.exe"
$PgRestore = Join-Path $PgBin "pg_restore.exe"
$PgData = Join-Path $DataRoot "pgdata"
$AppData = Join-Path $DataRoot "app"
$DefaultUploadRoot = Join-Path $AppData "uploads"
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
$C07MigrationHelper = Join-Path $ProgramDir "ticketbox-c07-migrator.exe"
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
$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"
if (-not (Test-Path -LiteralPath $DatabaseSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 数据库安全脚本：$DatabaseSafetyScript"
}
. $DatabaseSafetyScript
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
    param(
        [switch]$RequireBinding,
        [switch]$RequireBackendMarkerReadExecute
    )

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
    $dataRootMarkerAclPhase = if ($RequireBackendMarkerReadExecute) {
        "backend_read_required"
    }
    else {
        "backend_read_optional"
    }
    $binding = Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $RuntimeDataBindingServiceAccounts `
        -DataRootMarkerAclPhase $dataRootMarkerAclPhase `
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
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
if (-not (Test-Path -LiteralPath $LockScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期锁脚本：$LockScript"
}
. $LockScript
$InitdbPasswordPath = Get-TicketboxInitdbPasswordPath $DataRoot
$InitdbServiceReceiptPath = Get-TicketboxInitdbServiceReceiptPath
$InstallerState = Get-TicketboxInstallerStateDirectory
$OwnerHandoffPath = Join-Path $InstallerState "installation-owner-handoff-v2.txt"
$RetiredOwnerBootstrapPath = Join-Path $InstallerState "owner-bootstrap.txt"
$RetiredOwnerHandoffPendingPath = Join-Path $InstallerState "owner-handoff-pending"
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
$DatabaseScript = Join-Path $ScriptDir "windows_bundled_database.ps1"
if (-not (Test-Path -LiteralPath $DatabaseScript -PathType Leaf)) {
    throw "缺少 Windows bundled database 脚本：$DatabaseScript"
}
. $DatabaseScript
function Resolve-TicketboxInstallPublicFailurePath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    if ($InstallerLockOwnerProcessId -le 0) {
        throw "公开安装失败回执缺少当前 Inno owner。"
    }
    if (-not [Environment]::Is64BitProcess) {
        throw "公开安装失败回执只允许由 64 位安装宿主发布。"
    }
    $commonProgramFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonProgramFiles
    )
    if ([string]::IsNullOrWhiteSpace($commonProgramFiles)) {
        throw "无法定位受信任的 Common Program Files。"
    }
    $bootstrapRoot = [IO.Path]::GetFullPath(
        (Join-Path `
            $commonProgramFiles `
            "Ticketbox-Installer-Bootstrap-$InstallerLockOwnerProcessId")
    )
    $expected = [IO.Path]::GetFullPath(
        (Join-Path $bootstrapRoot "installer-public-failure-v3.txt")
    )
    $actual = [IO.Path]::GetFullPath($Path)
    if (-not [string]::Equals(
        $actual,
        $expected,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "公开安装失败回执路径未绑定当前 lifecycle bootstrap。"
    }
    $bootstrapKind = Get-TicketboxPathEntryKindNoFollow $bootstrapRoot
    if ($bootstrapKind -cne "Directory") {
        throw "公开安装失败回执 lifecycle bootstrap 不是受信任目录。"
    }
    Assert-TicketboxProtectedDirectoryAcl $bootstrapRoot
    $kind = Get-TicketboxPathEntryKindNoFollow $actual
    if ($kind -notin @("Missing", "File")) {
        throw "公开安装失败回执路径不是普通文件。"
    }
    if ($kind -ceq "File") {
        Assert-TicketboxExactFileAcl `
            -Path $actual `
            -Accounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM"
    }
    return $actual
}

function Resolve-TicketboxInstallDiagnosticLogPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "正式安装缺少受保护的诊断日志路径。"
    }
    if (
        $Path.Length -gt 1024 -or
        $Path.Contains("`r") -or
        $Path.Contains("`n")
    ) {
        throw "正式安装诊断日志路径格式无效。"
    }
    if (-not [Environment]::Is64BitProcess) {
        throw "正式安装诊断日志只允许由 64 位安装宿主发布。"
    }
    $commonProgramFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonProgramFiles
    )
    if ([string]::IsNullOrWhiteSpace($commonProgramFiles)) {
        throw "无法定位受信任的 Common Program Files。"
    }
    $logRoot = [IO.Path]::GetFullPath(
        (Join-Path $commonProgramFiles "Ticketbox\installer-logs")
    )
    $actual = [IO.Path]::GetFullPath($Path)
    if (
        -not [string]::Equals(
            [IO.Path]::GetDirectoryName($actual),
            $logRoot,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        [IO.Path]::GetFileName($actual) -cnotmatch
            '^installer-[0-9]{8}-[0-9]{6}-[0-9]+-[0-9]+\.log$'
    ) {
        throw "正式安装诊断日志路径未绑定受保护的 installer log 根。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $logRoot) -cne "Directory") {
        throw "正式安装诊断日志根不是受信任目录。"
    }
    Assert-TicketboxProtectedDirectoryAcl $logRoot
    if ((Get-TicketboxPathEntryKindNoFollow $actual) -cne "File") {
        throw "正式安装诊断日志不是普通文件。"
    }
    Assert-TicketboxExactFileAcl `
        -Path $actual `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    return $actual
}

function Assert-TicketboxInstallPublicGuid {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Field
    )

    $parsed = [guid]::Empty
    if (
        -not [guid]::TryParseExact($Value, "D", [ref]$parsed) -or
        $parsed -eq [guid]::Empty -or
        $parsed.ToString("D") -cne $Value
    ) {
        throw "公开安装失败回执 $Field 不是规范非零 UUID。"
    }
}

function Publish-TicketboxInstallPublicFailureReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId,
        [Parameter(Mandatory = $true)][string]$InstallationOperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("not_assigned", "assigned")]
        [string]$InstallationIdState,
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$InstallationId,
        [Parameter(Mandatory = $true)][string]$LifecycleStage,
        [Parameter(Mandatory = $true)][string]$ProtectedLogPath,
        [Parameter(Mandatory = $true)][Exception]$Failure,
        [Parameter(Mandatory = $true)]
        [ValidateSet("not_started", "started_or_possible")]
        [string]$DatabaseMutationState
    )

    $canonicalPath = Resolve-TicketboxInstallPublicFailurePath $Path
    if ($canonicalPath.Length -eq 0) { return }
    $canonicalLogPath = Resolve-TicketboxInstallDiagnosticLogPath $ProtectedLogPath
    Assert-TicketboxInstallPublicGuid `
        -Value $FinalizationAttemptId `
        -Field "FINALIZATION_ATTEMPT_ID"
    Assert-TicketboxInstallPublicGuid `
        -Value $InstallationOperationId `
        -Field "INSTALLATION_OPERATION_ID"
    if ($InstallationIdState -ceq "assigned") {
        Assert-TicketboxInstallPublicGuid `
            -Value $InstallationId `
            -Field "INSTALLATION_ID"
    }
    elseif ($InstallationId.Length -ne 0) {
        throw "公开安装失败回执未分配 installation ID 时不得携带伪造值。"
    }
    if ($LifecycleStage -cnotmatch '^[a-z][a-z0-9_]{0,63}$') {
        throw "公开安装失败回执 LIFECYCLE_STAGE 不是受支持 token。"
    }
    $ownerIdentity = $LifecycleLock.ExternalOwnerIdentity
    if ($null -eq $ownerIdentity -or [int]$ownerIdentity.ProcessId -lt 1) {
        throw "公开安装失败回执缺少 Inno owner identity。"
    }
    $failureCode = "unclassified_service_install_failure"
    if ($Failure.Data.Contains("TicketboxInstallPublicFailureCode")) {
        $candidate = [string]$Failure.Data["TicketboxInstallPublicFailureCode"]
        if ($candidate -in @(
            "backend_payload_manifest_order_invalid",
            "postgres_cluster_initialization_failed",
            "installation_identity_recovery_failed",
            "installation_owner_binding_failed",
            "postgres_host_authority_validation_failed"
        )) {
            $failureCode = $candidate
        }
    }
    if ($failureCode -ceq "backend_payload_manifest_order_invalid") {
        $supportCode = "TBX-INSTALL-PROVENANCE-ORDER"
    }
    elseif ($failureCode -ceq "postgres_cluster_initialization_failed") {
        $supportCode = "TBX-INSTALL-INITDB"
    }
    elseif ($failureCode -ceq "installation_identity_recovery_failed") {
        $supportCode = "TBX-INSTALL-IDENTITY"
    }
    elseif ($failureCode -ceq "installation_owner_binding_failed") {
        $supportCode = "TBX-INSTALL-OWNER-BINDING"
    }
    elseif ($failureCode -ceq "postgres_host_authority_validation_failed") {
        $supportCode = "TBX-INSTALL-POSTGRES-HOST"
    }
    else {
        $supportCode = "TBX-INSTALL-UNKNOWN"
    }
    if ($failureCode -ceq "backend_payload_manifest_order_invalid") {
        $retryClass = "replace_package_then_retry_no_cleanup"
    }
    elseif (
        $failureCode -ceq "installation_identity_recovery_failed" -or
        $failureCode -ceq "installation_owner_binding_failed"
    ) {
        $retryClass = "retry_same_operation_no_cleanup"
    }
    elseif (
        $failureCode -ceq "postgres_cluster_initialization_failed" -or
        $failureCode -ceq "postgres_host_authority_validation_failed"
    ) {
        $retryClass = "retry_no_cleanup"
    }
    else {
        $retryClass = "manual_review_preserve_state"
    }
    $text = @(
        "SCHEMA=ticketbox-install-public-failure-v3",
        "INSTALLER_OWNER_PID=$([uint32]$ownerIdentity.ProcessId)",
        "INSTALLER_OWNER_STARTED_FILETIME_HIGH=$([uint32]$ownerIdentity.StartedFileTimeHigh)",
        "INSTALLER_OWNER_STARTED_FILETIME_LOW=$([uint32]$ownerIdentity.StartedFileTimeLow)",
        "FINALIZATION_ATTEMPT_ID=$FinalizationAttemptId",
        "INSTALLATION_OPERATION_ID=$InstallationOperationId",
        "INSTALLATION_ID_STATE=$InstallationIdState",
        "INSTALLATION_ID=$InstallationId",
        "LIFECYCLE_STAGE=$LifecycleStage",
        "CONTEXT=service_installation",
        "FAILURE_CODE=$failureCode",
        "RETRY_CLASS=$retryClass",
        "DATABASE_MUTATION_STATE=$DatabaseMutationState",
        "SUPPORT_CODE=$supportCode",
        "PROTECTED_LOG_PATH=$canonicalLogPath",
        "PUBLIC_RECEIPT_PATH=$canonicalPath"
    ) -join "`r`n"
    $text += "`r`n"
    if ([Text.UTF8Encoding]::new($false).GetByteCount($text) -gt 4096) {
        throw "公开安装失败回执超过大小上限。"
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $canonicalPath `
        -Text $text `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting
}
$DatabaseGenerationProgramAdapterScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_program_adapter.ps1"
if (-not (Test-Path -LiteralPath $DatabaseGenerationProgramAdapterScript -PathType Leaf)) {
    throw "缺少 Windows database generation program adapter：$DatabaseGenerationProgramAdapterScript"
}
. $DatabaseGenerationProgramAdapterScript
$DatabaseGenerationScript = Join-Path `
    $ScriptDir `
    "windows_database_generation.ps1"
if (-not (Test-Path -LiteralPath $DatabaseGenerationScript -PathType Leaf)) {
    throw "缺少 Windows database generation owner：$DatabaseGenerationScript"
}
. $DatabaseGenerationScript
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

function New-TicketboxInstallCompensationAggregateFailure {
    param(
        [Parameter(Mandatory = $true)][Exception]$InstallFailure,
        [Parameter(Mandatory = $true)][Exception]$CompensationFailure
    )

    [Exception[]]$causes = @($InstallFailure)
    if ($CompensationFailure -is [AggregateException]) {
        $causes += @($CompensationFailure.InnerExceptions)
    }
    else {
        $causes += $CompensationFailure
    }
    $aggregateFailure = [AggregateException]::new(
        (
            "安装动作失败，且安装失败补偿未完整完成；" +
            "全部原始异常均已保留。"
        ),
        $causes
    )
    $aggregateFailure.Data["TicketboxInstallCompensationFailed"] = $true
    $aggregateFailure.Data["TicketboxInstallPublicFailureCode"] =
        "unclassified_service_install_failure"
    if ($InstallFailure.Data.Contains("TicketboxC07FailureCode")) {
        $aggregateFailure.Data["TicketboxC07FailureCode"] =
            $InstallFailure.Data["TicketboxC07FailureCode"]
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

function New-TicketboxInstallFinalizationAggregateFailure {
    param(
        [AllowNull()][Exception]$OperationFailure,
        [Parameter(Mandatory = $true)][Exception[]]$FinalizationFailures
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
    $causes += @($FinalizationFailures)
    if ($causes.Count -eq 0) {
        throw "安装 finalization 聚合器缺少原始异常。"
    }
    $aggregateFailure = [AggregateException]::new(
        (
            "安装动作或其补偿已失败，且 payload lease / 生命周期锁" +
            "收尾未完整完成；全部原始异常均已保留。"
        ),
        $causes
    )
    $aggregateFailure.Data["TicketboxInstallFinalizationFailed"] = $true
    if ($null -ne $OperationFailure) {
        foreach ($key in @(
            "TicketboxC07FailureCode",
            "TicketboxC07FailureCodes",
            "TicketboxInstallCompensationFailed",
            "TicketboxInstallPublicFailureCode"
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
        [object]$ExpectedReleaseConfig = $ReleaseConfig,
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowLegacyRuntimeDataContract,
        [switch]$AllowMissingOwnerRecoveryChannel
    )
    if (-not (Service-Exists $Name)) {
        return
    }
    Assert-TicketboxServiceOwnership -Name $Name -ExpectedExecutable (Get-ExpectedServiceExecutable $Name) | Out-Null
    $allowTargetSidTypePending =
        $null -ne $ServiceIdentityLifecycleReceipt -and
        (Test-TicketboxLifecycleReceiptAuthorizesServiceSidPending `
            -Receipt $ServiceIdentityLifecycleReceipt `
            -ServiceName $Name)
    Assert-TicketboxReleaseServiceIdentity `
        -Name $Name `
        -InstalledConfig $ExpectedReleaseConfig `
        -TargetConfig $ReleaseConfig `
        -AllowTargetSidTypePending:$allowTargetSidTypePending | Out-Null
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
        [object]$ExpectedReleaseConfig = $ReleaseConfig,
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowLegacyRuntimeDataContract,
        [switch]$AllowMissingOwnerRecoveryChannel
    )
    Assert-ExpectedServiceConfiguration `
        -Name $Name `
        -ExpectedStopTimeoutMs $ExpectedStopTimeoutMs `
        -ExpectedRestartDelayMs $ExpectedRestartDelayMs `
        -ExpectedReleaseConfig $ExpectedReleaseConfig `
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

function Get-TicketboxInitdbReceiptOwnerProcessId {
    if ($InstallerLockOwnerProcessId -gt 0) {
        return $InstallerLockOwnerProcessId
    }
    return $PID
}

function Read-TicketboxCurrentInitdbServiceReceipt {
    param([switch]$AllowPreviousInstallerOwnerProcessId)

    return Read-TicketboxInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -ServiceName $PgServiceName `
        -PgMajor $TargetPgMajor `
        -StopTimeoutMs $StopTimeoutMs `
        -InstallerOwnerProcessId (Get-TicketboxInitdbReceiptOwnerProcessId) `
        -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId
}

function Set-TicketboxCurrentInitdbServiceReceiptPhase {
    param(
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][ValidateSet(
            "registered",
            "start_authorized",
            "initdb_succeeded",
            "converted_to_pgctl"
        )][string]$Phase
    )

    Set-TicketboxInitdbServiceReceiptPhase `
        -Path $InitdbServiceReceiptPath `
        -Receipt $Receipt `
        -InstallerOwnerProcessId (Get-TicketboxInitdbReceiptOwnerProcessId) `
        -Phase $Phase
    return Read-TicketboxCurrentInitdbServiceReceipt
}

function Assert-TicketboxInitdbPasswordFileSecurity {
    Assert-TicketboxInitdbPasswordFileAcl `
        -Path $InitdbPasswordPath `
        -ServiceName $PgServiceName
}

function Write-TicketboxInitdbPasswordFile([string]$SuperuserPassword) {
    Assert-PostgresBootstrapPasswordValue `
        $SuperuserPassword `
        "superuser_password"
    Write-TicketboxInitdbPasswordFileAtomically `
        -Path $InitdbPasswordPath `
        -Text $SuperuserPassword `
        -ServiceName $PgServiceName
    Assert-TicketboxInitdbPasswordFileSecurity
}

function Remove-TicketboxInitdbPasswordFileIfPresent([object]$Receipt = $null) {
    $allowPreAuthorizationAcl =
        $null -ne $Receipt -and
        [string]$Receipt.phase -in @("intent_written", "registered")
    Remove-TicketboxInitdbPasswordFileExact `
        -Path $InitdbPasswordPath `
        -ServiceName $PgServiceName `
        -AllowServiceReadMissing:$allowPreAuthorizationAcl
}

function Assert-TicketboxInitdbServiceConfiguration {
    param(
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][ValidateSet("Disabled", "Manual")][string]$StartMode
    )

    Assert-TicketboxServiceOwnership `
        -Name $PgServiceName `
        -ExpectedExecutable $ShawlExe | Out-Null
    $targetIdentityShape = @(Get-TicketboxReleaseServiceIdentityShapes `
        -InstalledConfig $ReleaseConfig `
        -TargetConfig $ReleaseConfig `
        -ServiceName $PgServiceName)[0]
    Assert-TicketboxServiceIdentityShape `
        -Name $PgServiceName `
        -AllowedShapes @(Get-TicketboxInitdbReceiptServiceIdentityShapes `
            -Receipt $Receipt `
            -ServiceName $PgServiceName `
            -TargetShape $targetIdentityShape `
            -AllowCurrentSidTypePending:([string]$Receipt.phase -ceq "intent_written")) | Out-Null
    Assert-TicketboxInitdbServiceCommand `
        -Name $PgServiceName `
        -ExpectedShawl $ShawlExe `
        -ExpectedServiceName $PgServiceName `
        -ExpectedWorkingDirectory $PgBin `
        -ExpectedInitdb $InitdbExe `
        -ExpectedDataRoot $PgData `
        -ExpectedPasswordFile $InitdbPasswordPath `
        -ExpectedStopTimeoutMs $StopTimeoutMs `
        -ExpectedImagePath ([string]$Receipt.image_path)
    Assert-TicketboxServiceStartMode `
        -Name $PgServiceName `
        -ExpectedStartMode $StartMode
    Assert-TicketboxServiceHasNoFailureActions $PgServiceName
}

function Assert-TicketboxFreshPgClusterComplete {
    $pgVersionPath = Join-Path $PgData "PG_VERSION"
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        throw "initdb 未发布 PG_VERSION。"
    }
    $actualMajor = (Get-Content -LiteralPath $pgVersionPath -Raw -Encoding ASCII).Trim()
    if ($actualMajor -cne [string]$TargetPgMajor) {
        throw "initdb 数据簇主版本不匹配。"
    }
    foreach ($requiredPath in @(
        (Join-Path $PgData "global\pg_control"),
        (Join-Path $PgData "postgresql.conf"),
        (Join-Path $PgData "pg_hba.conf")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "initdb 数据簇缺少必要文件。"
        }
    }
    if (
        -not (Test-Path -LiteralPath (Join-Path $PgData "base") -PathType Container) -or
        (Test-Path -LiteralPath (Join-Path $PgData "postmaster.pid"))
    ) {
        throw "initdb 数据簇结构或停止状态不可信。"
    }
    Assert-NoTicketboxReparsePoints $PgData
}

function New-TicketboxInstallServiceCompensationAuthority {
    return [pscustomobject][ordered]@{
        BackendService = "none"
        PostgresService = "none"
    }
}

function Assert-TicketboxInstallServiceCompensationAuthority([object]$Authority) {
    if ($null -eq $Authority) {
        throw "安装服务补偿 authority 缺失。"
    }
    $propertyNames = @($Authority.PSObject.Properties.Name | Sort-Object)
    if (
        $propertyNames.Count -ne 2 -or
        $propertyNames[0] -cne "BackendService" -or
        $propertyNames[1] -cne "PostgresService"
    ) {
        throw "安装服务补偿 authority 结构无效。"
    }
    foreach ($propertyName in $propertyNames) {
        if ([string]$Authority.$propertyName -notin @(
            "none",
            "validated_preexisting",
            "created_by_installer"
        )) {
            throw "安装服务补偿 authority 状态无效：$propertyName。"
        }
    }
}

function Grant-TicketboxInstallServiceCompensationAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][ValidateSet(
            "BackendService",
            "PostgresService"
        )][string]$Service,
        [Parameter(Mandatory = $true)][ValidateSet(
            "validated_preexisting",
            "created_by_installer"
        )][string]$Grant
    )

    Assert-TicketboxInstallServiceCompensationAuthority $Authority
    $current = [string]$Authority.$Service
    if ($current -cne "none" -and $current -cne $Grant) {
        throw "安装服务补偿 authority 拒绝越权转换：$Service $current -> $Grant。"
    }
    $Authority.$Service = $Grant
    Assert-TicketboxInstallServiceCompensationAuthority $Authority
}

function Disable-TicketboxInitdbServiceIfPresent([object]$Receipt) {
    if (-not (Service-Exists $PgServiceName)) { return }
    $actualStartMode = Get-TicketboxServiceStartMode $PgServiceName
    if ($actualStartMode -notin @("Disabled", "Manual")) {
        throw "initdb one-shot 服务启动模式越界：$actualStartMode"
    }
    Assert-TicketboxInitdbServiceConfiguration `
        -Receipt $Receipt `
        -StartMode $actualStartMode
    Stop-TicketboxOwnedServiceIfExists `
        -Name $PgServiceName `
        -ExpectedExecutable $ShawlExe `
        -ExpectedRuntimeExecutables @($ShawlExe, $InitdbExe) `
        @ServiceWaitArguments
    Invoke-ScChecked @("config", $PgServiceName, "start=", "disabled") | Out-Null
    Assert-TicketboxInitdbServiceConfiguration `
        -Receipt $Receipt `
        -StartMode "Disabled"
}

function Invoke-TicketboxServiceOwnedInitdb {
    param(
        [Parameter(Mandatory = $true)][object]$BootstrapState,
        [Parameter(Mandatory = $true)][object]$CompensationAuthority
    )

    Assert-TicketboxInstallServiceCompensationAuthority $CompensationAuthority
    $imagePath = New-TicketboxInitdbServiceImagePath `
        -ShawlPath $ShawlExe `
        -ServiceName $PgServiceName `
        -WorkingDirectory $PgBin `
        -InitdbPath $InitdbExe `
        -DataRoot $PgData `
        -PasswordFile $InitdbPasswordPath `
        -StopTimeoutMs $StopTimeoutMs
    if (Service-Exists $PgServiceName) {
        throw "PostgreSQL 同名服务在 fresh initdb create-only 边界已存在。"
    }
    Write-TicketboxInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -ServiceName $PgServiceName `
        -ServiceLogonAccount $PgServiceLogonAccount `
        -ServiceSidType $TargetServiceSidType `
        -ImagePath $imagePath `
        -PgMajor $TargetPgMajor `
        -StopTimeoutMs $StopTimeoutMs `
        -InstallerOwnerProcessId (Get-TicketboxInitdbReceiptOwnerProcessId) `
        -Phase "intent_written"
    $receipt = Read-TicketboxCurrentInitdbServiceReceipt
    $operationFailure = $null
    $createdByThisInvocation = $false
    try {
        Invoke-ScChecked @(
            "create", $PgServiceName,
            "binPath=", $imagePath,
            "start=", "disabled",
            "obj=", $PgServiceLogonAccount
        ) | Out-Null
        $createdByThisInvocation = $true
        Grant-TicketboxInstallServiceCompensationAuthority `
            -Authority $CompensationAuthority `
            -Service "PostgresService" `
            -Grant "created_by_installer"
        Set-TicketboxServiceIdentityContract `
            -Name $PgServiceName `
            -LogonAccount $PgServiceLogonAccount `
            -SidType $TargetServiceSidType
        Assert-TicketboxInitdbServiceConfiguration `
            -Receipt $receipt `
            -StartMode "Disabled"
        $receipt = Set-TicketboxCurrentInitdbServiceReceiptPhase `
            -Receipt $receipt `
            -Phase "registered"
        Set-TicketboxAcl `
            -IncludePgService $true `
            -IncludeBackendService $false
        Write-TicketboxInitdbPasswordFile `
            ([string]$BootstrapState.SuperuserPassword)
        $receipt = Set-TicketboxCurrentInitdbServiceReceiptPhase `
            -Receipt $receipt `
            -Phase "start_authorized"
        Invoke-ScChecked @("config", $PgServiceName, "start=", "demand") | Out-Null
        Assert-TicketboxInitdbServiceConfiguration `
            -Receipt $receipt `
            -StartMode "Manual"
        $snapshot = Invoke-TicketboxOwnedOneShotService `
            -Name $PgServiceName `
            -ExpectedExecutable $ShawlExe `
            -ExpectedRuntimeExecutables @($ShawlExe, $InitdbExe) `
            @ServiceWaitArguments
        Invoke-ScChecked @("config", $PgServiceName, "start=", "disabled") | Out-Null
        Assert-TicketboxInitdbServiceConfiguration `
            -Receipt $receipt `
            -StartMode "Disabled"
        if (
            [uint32]$snapshot.ExitCode -ne 0 -or
            [uint32]$snapshot.ServiceSpecificExitCode -ne 0
        ) {
            $nativeExit = if ([uint32]$snapshot.ServiceSpecificExitCode -ne 0) {
                [uint64]([uint32]$snapshot.ServiceSpecificExitCode)
            } else {
                [uint64]([uint32]$snapshot.ExitCode)
            }
            throw (New-TicketboxInitdbFailure `
                -FailureKind "service_process_failed" `
                -ExitCode $nativeExit)
        }
        Assert-TicketboxFreshPgClusterComplete
        Remove-TicketboxInitdbPasswordFileIfPresent $receipt
        [void](Repair-PostgresBootstrapRecoveryFileAcl)
        [void](Read-PostgresBootstrapRecoveryState -Path (Get-PostgresBootstrapRecoveryPath))
        $receipt = Set-TicketboxCurrentInitdbServiceReceiptPhase `
            -Receipt $receipt `
            -Phase "initdb_succeeded"
        return [pscustomobject]@{
            ExitCode = 0
            StandardOutput = ""
            StandardError = ""
        }
    }
    catch {
        $operationFailure = $_.Exception
        $cleanupFailure = $null
        try {
            if ($createdByThisInvocation) {
                Disable-TicketboxInitdbServiceIfPresent $receipt
            }
            Remove-TicketboxInitdbPasswordFileIfPresent $receipt
            [void](Repair-PostgresBootstrapRecoveryFileAcl)
            [void](Read-PostgresBootstrapRecoveryState -Path (Get-PostgresBootstrapRecoveryPath))
            if (
                -not $createdByThisInvocation -and
                (Get-TicketboxPathEntryKindNoFollow $InitdbServiceReceiptPath) -ceq "File"
            ) {
                Remove-TicketboxAbortedInitdbServiceReceipt `
                    -Path $InitdbServiceReceiptPath `
                    -Receipt $receipt
            }
        }
        catch {
            $cleanupFailure = $_.Exception
        }
        if ($null -ne $cleanupFailure) {
            throw (New-TicketboxInstallCompensationAggregateFailure `
                -InstallFailure $operationFailure `
                -CompensationFailure $cleanupFailure)
        }
        if (
            $createdByThisInvocation -and
            -not $operationFailure.Data.Contains("TicketboxInstallPublicFailureCode")
        ) {
            $operationFailure.Data["TicketboxInstallPublicFailureCode"] =
                "postgres_cluster_initialization_failed"
        }
        throw $operationFailure
    }
}

function Register-PgService {
    param(
        [switch]$RuntimeBindingTransition,
        [Parameter(Mandatory = $true)][object]$CompensationAuthority
    )

    Write-Step "注册 PostgreSQL 服务 $PgServiceName"
    Assert-TicketboxInstallServiceCompensationAuthority $CompensationAuthority
    $convertedInitdbReceipt = $null
    $pgImagePath = New-TicketboxPgServiceImagePath `
        -PgCtlPath $PgCtl `
        -ServiceName $PgServiceName `
        -DataRoot $ServicePgData
    if (Service-Exists $PgServiceName) {
        if ([string]$CompensationAuthority.PostgresService -ceq "none") {
            throw "PostgreSQL 同名服务在预分类后出现；拒绝把竞争服务当作安装事务所有。"
        }
        $actualExecutable = Get-TicketboxServiceExecutablePath $PgServiceName
        if (Test-TicketboxPathEquals $actualExecutable $ShawlExe) {
            if (-not $RuntimeBindingTransition) {
                throw "initdb one-shot 服务只能在 runtime binding 原子切换阶段转为正式服务。"
            }
            $convertedInitdbReceipt = Read-TicketboxCurrentInitdbServiceReceipt
            if ([string]$convertedInitdbReceipt.phase -cne "initdb_succeeded") {
                throw "initdb one-shot 服务尚未达到可提交阶段。"
            }
            Assert-TicketboxInitdbServiceConfiguration `
                -Receipt $convertedInitdbReceipt `
                -StartMode "Disabled"
            Assert-TicketboxFreshPgClusterComplete
            if ((Get-TicketboxPathEntryKindNoFollow $InitdbPasswordPath) -cne "Missing") {
                throw "initdb 临时密码文件尚未退役，拒绝提交正式服务。"
            }
            [void](Repair-PostgresBootstrapRecoveryFileAcl)
            [void](Read-PostgresBootstrapRecoveryState -Path (Get-PostgresBootstrapRecoveryPath))
            Invoke-ScChecked @(
                "config", $PgServiceName,
                "start=", "disabled",
                "binPath=", $pgImagePath
            ) | Out-Null
            Set-TicketboxServiceIdentityContract `
                -Name $PgServiceName `
                -LogonAccount $PgServiceLogonAccount `
                -SidType $TargetServiceSidType
            Assert-TicketboxServiceOwnership `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl | Out-Null
            Assert-TicketboxReleaseServiceIdentity `
                -Name $PgServiceName `
                -InstalledConfig $ReleaseConfig `
                -TargetConfig $ReleaseConfig | Out-Null
            Assert-TicketboxPgServiceCommand `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                -ExpectedServiceName $PgServiceName `
                -ExpectedDataRoot $ServicePgData
            Assert-TicketboxServiceStartMode `
                -Name $PgServiceName `
                -ExpectedStartMode "Disabled"
        }
        elseif (Test-TicketboxPathEquals $actualExecutable $PgCtl) {
            Assert-TicketboxServiceOwnership `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl | Out-Null
            if (-not $RuntimeBindingTransition) {
                Assert-ExpectedServiceConfiguration `
                    -Name $PgServiceName `
                    -ExpectedReleaseConfig $PreviousReleaseConfig
            }
        }
        else {
            throw "拒绝转换 executable 不匹配的同名 PostgreSQL 服务。"
        }
        Invoke-ScChecked @("config", $PgServiceName, "start=", "demand") | Out-Null
    }
    else {
        Invoke-ScChecked @(
            "create", $PgServiceName,
            "binPath=", $pgImagePath,
            "start=", "demand",
            "obj=", $PgServiceLogonAccount
        ) | Out-Null
        Grant-TicketboxInstallServiceCompensationAuthority `
            -Authority $CompensationAuthority `
            -Service "PostgresService" `
            -Grant "created_by_installer"
        Set-TicketboxServiceIdentityContract `
            -Name $PgServiceName `
            -LogonAccount $PgServiceLogonAccount `
            -SidType $TargetServiceSidType
    }
    Invoke-ScChecked @("config", $PgServiceName, "start=", "demand") | Out-Null
    Invoke-ScChecked @("config", $PgServiceName, "binPath=", $pgImagePath) | Out-Null
    Set-TicketboxServiceIdentityContract `
        -Name $PgServiceName `
        -LogonAccount $PgServiceLogonAccount `
        -SidType $TargetServiceSidType
    Invoke-ScChecked @(
        "failure", $PgServiceName, "reset=", [string]$ScmFailureResetSeconds, "actions=", $ScmRestartActions
    ) | Out-Null
    Assert-ExpectedServiceConfiguration $PgServiceName
    Assert-TicketboxServiceStartMode -Name $PgServiceName -ExpectedStartMode "Manual"
    Assert-TicketboxServiceFailurePolicy `
        -Name $PgServiceName `
        -ExpectedResetSeconds $ScmFailureResetSeconds `
        -ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)
    if ($null -ne $convertedInitdbReceipt) {
        $convertedInitdbReceipt = Set-TicketboxCurrentInitdbServiceReceiptPhase `
            -Receipt $convertedInitdbReceipt `
            -Phase "converted_to_pgctl"
        Remove-TicketboxInitdbServiceReceipt `
            -Path $InitdbServiceReceiptPath `
            -Receipt $convertedInitdbReceipt
        if (Test-Path -LiteralPath $InitdbServiceReceiptPath) {
            throw "initdb one-shot 回执未能在正式服务验证后退役。"
        }
    }
    Write-Ok "PG 服务已以 demand-start 和独立服务 SID 注册。"
}

function Register-BackendService {
    param([Parameter(Mandatory = $true)][object]$CompensationAuthority)

    Write-Step "注册后端服务 $BackendServiceName"
    Assert-TicketboxInstallServiceCompensationAuthority $CompensationAuthority
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
        if ([string]$CompensationAuthority.BackendService -ceq "none") {
            throw "后端同名服务在预分类后出现；拒绝把竞争服务当作安装事务所有。"
        }
        Assert-TicketboxServiceOwnership -Name $BackendServiceName -ExpectedExecutable $ShawlExe | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "start=", "disabled") | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "binPath=", $backendImagePath) | Out-Null
        Invoke-ScChecked @("config", $BackendServiceName, "depend=", $PgServiceName) | Out-Null
    }
    else {
        Invoke-ScChecked @(
            "create", $BackendServiceName,
            "binPath=", $backendImagePath,
            "start=", "disabled",
            "depend=", $PgServiceName,
            "obj=", $BackendServiceLogonAccount
        ) | Out-Null
        Grant-TicketboxInstallServiceCompensationAuthority `
            -Authority $CompensationAuthority `
            -Service "BackendService" `
            -Grant "created_by_installer"
    }
    Set-TicketboxServiceIdentityContract `
        -Name $BackendServiceName `
        -LogonAccount $BackendServiceLogonAccount `
        -SidType $TargetServiceSidType
    Invoke-ScChecked @(
        "failure", $BackendServiceName, "reset=", [string]$ScmFailureResetSeconds, "actions=", $ScmRestartActions
    ) | Out-Null
    Assert-ExpectedServiceConfiguration $BackendServiceName
    Assert-TicketboxServiceStartMode -Name $BackendServiceName -ExpectedStartMode "Disabled"
    Assert-TicketboxServiceFailurePolicy `
        -Name $BackendServiceName `
        -ExpectedResetSeconds $ScmFailureResetSeconds `
        -ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)
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
    [bool]$IncludeBackendService = $true,
    [string[]]$PrivilegedAccounts = @("SYSTEM", "BUILTIN\Administrators"),
    [string]$OwnerAccount = "SYSTEM"
) {
    Write-Step "收紧 ProgramData ACL"
    New-Item -ItemType Directory -Force -Path `
        $DataRoot, `
        $PgData, `
        $AppData, `
        $DefaultUploadRoot, `
        $LogDir, `
        $BackupDir | Out-Null

    $systemAndAdmins = @($PrivilegedAccounts)
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
        -ReadExecuteAccounts $rootReadAccounts `
        -OwnerAccount $OwnerAccount
    Set-TicketboxExactDirectoryAcl `
        -Path $PgData `
        -Accounts $pgAccounts `
        -OwnerAccount $OwnerAccount `
        -Recurse
    Set-TicketboxExactDirectoryAcl `
        -Path $AppData `
        -Accounts $appAccounts `
        -OwnerAccount $OwnerAccount `
        -Recurse
    [void](Protect-PostgresBootstrapRecoveryFileAfterAclNormalization `
        -ParentFullControlAccounts $appAccounts)
    Initialize-TicketboxInstallerStateDirectory $InstallerState | Out-Null
    if (Test-Path -LiteralPath $BootstrapExposureRecoveryGuardPath -PathType Leaf) {
        Set-TicketboxExactFileAcl `
            -Path $BootstrapExposureRecoveryGuardPath `
            -Accounts $systemAndAdmins `
            -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
            -OwnerAccount $OwnerAccount
    }
    if (Test-Path -LiteralPath $InstallerRuntimeRecoveryGuardPath -PathType Leaf) {
        Set-TicketboxExactFileAcl `
            -Path $InstallerRuntimeRecoveryGuardPath `
            -Accounts $systemAndAdmins `
            -ReadExecuteAccounts @("NT SERVICE\$BackendServiceName") `
            -OwnerAccount $OwnerAccount
    }
    Set-TicketboxExactFileAcl `
        -Path (Get-TicketboxDataRootMarkerPath $DataRoot) `
        -Accounts $systemAndAdmins `
        -ReadExecuteAccounts $markerReadAccounts `
        -OwnerAccount $OwnerAccount
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
    Initialize-TicketboxInstallerStateDirectory -Path $InstallerState | Out-Null
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $LegacyRecoveryRequiredPath `
        -CurrentPath $RecoveryRequiredPath
    Inspect-TicketboxRetiredOwnerHandoffArtifacts `
        -InstallerStatePath $InstallerState `
        -LegacyOwnerBootstrapPath $LegacyOwnerBootstrapPath `
        -LegacyOwnerHandoffPendingPath $LegacyOwnerHandoffPendingPath `
        -RetiredOwnerBootstrapPath $RetiredOwnerBootstrapPath `
        -RetiredOwnerHandoffPendingPath $RetiredOwnerHandoffPendingPath
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

function Invoke-TicketboxInstallFailureCompensation {
    param(
        [Parameter(Mandatory = $true)][string]$Reason,
        [Parameter(Mandatory = $true)][object]$ServiceCompensationAuthority
    )

    Assert-TicketboxInstallServiceCompensationAuthority `
        $ServiceCompensationAuthority
    [Exception[]]$failures = @()
    try {
        if ([string]$ServiceCompensationAuthority.BackendService -ceq "none") {
            if (Service-Exists $BackendServiceName) {
                throw "后端同名服务不属于当前安装事务；拒绝执行失败补偿 mutation。"
            }
            Assert-TicketboxRuntimeAbsent `
                -Name $BackendServiceName `
                -RuntimePort $BackendPort `
                -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)
        }
        else {
            Disable-TicketboxOwnedServiceIfExists `
                -Name $BackendServiceName `
                -ExpectedExecutable $ShawlExe `
                -BackendPort $BackendPort `
                -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
                @ServiceWaitArguments
        }
    }
    catch {
        $compensationFailure = $_.Exception
        $compensationFailure.Data["TicketboxInstallCompensationStep"] =
            "backend_disable"
        $failures += $compensationFailure
    }
    try {
        if ([string]$ServiceCompensationAuthority.PostgresService -ceq "none") {
            if (Service-Exists $PgServiceName) {
                throw "PostgreSQL 同名服务不属于当前安装事务；拒绝执行失败补偿 mutation。"
            }
            Assert-TicketboxRuntimeAbsent `
                -Name $PgServiceName `
                -RuntimePort $PgPort `
                -ExpectedRuntimeExecutables @(
                    $PgCtl,
                    (Join-Path $PgBin "postgres.exe"),
                    $ShawlExe,
                    $InitdbExe
                )
        }
        elseif (-not (Service-Exists $PgServiceName)) {
            Assert-TicketboxRuntimeAbsent `
                -Name $PgServiceName `
                -RuntimePort $PgPort `
                -ExpectedRuntimeExecutables @(
                    $PgCtl,
                    (Join-Path $PgBin "postgres.exe"),
                    $ShawlExe,
                    $InitdbExe
                )
        }
        else {
            $actualPgExecutable = Get-TicketboxServiceExecutablePath $PgServiceName
            if (Test-TicketboxPathEquals $actualPgExecutable $PgCtl) {
                Disable-TicketboxOwnedServiceIfExists `
                    -Name $PgServiceName `
                    -ExpectedExecutable $PgCtl `
                    -ExpectedRuntimeExecutables @(
                        $PgCtl,
                        (Join-Path $PgBin "postgres.exe")
                    ) `
                    @ServiceWaitArguments
            }
            elseif (Test-TicketboxPathEquals $actualPgExecutable $ShawlExe) {
                if ((Get-TicketboxPathEntryKindNoFollow $InitdbServiceReceiptPath) -cne "File") {
                    throw "检测到 initdb one-shot 服务但缺少受保护回执，拒绝推断归属。"
                }
                $initdbReceipt = Read-TicketboxCurrentInitdbServiceReceipt
                Disable-TicketboxInitdbServiceIfPresent $initdbReceipt
                Remove-TicketboxInitdbPasswordFileIfPresent $initdbReceipt
                [void](Repair-PostgresBootstrapRecoveryFileAcl)
                [void](Read-PostgresBootstrapRecoveryState -Path (Get-PostgresBootstrapRecoveryPath))
            }
            else {
                throw "拒绝补偿 executable 不匹配的同名 PostgreSQL 服务。"
            }
        }
    }
    catch {
        $compensationFailure = $_.Exception
        $compensationFailure.Data["TicketboxInstallCompensationStep"] =
            "postgres_disable"
        $failures += $compensationFailure
    }
    try {
        Assert-TicketboxPgClusterStoppedAfterFailure
    }
    catch {
        $compensationFailure = $_.Exception
        $compensationFailure.Data["TicketboxInstallCompensationStep"] =
            "cluster_stopped_assertion"
        $failures += $compensationFailure
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
        $compensationFailure = $_.Exception
        $compensationFailure.Data["TicketboxInstallCompensationStep"] =
            "recovery_marker"
        $failures += $compensationFailure
    }
    if ($failures.Count -gt 0) {
        $aggregateFailure = [AggregateException]::new(
            "安装失败补偿不完整；全部原始异常均已保留。",
            $failures
        )
        $aggregateFailure.Data["TicketboxInstallCompensationFailed"] = $true
        $failureCodes = @(
            $failures |
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
        throw $aggregateFailure
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
Assert-File $C07MigrationHelper "ticketbox-c07-migrator.exe"
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
    Assert-TicketboxReleaseServiceIdentity `
        -Name $PgServiceName `
        -InstalledConfig $ReleaseConfig `
        -TargetConfig $ReleaseConfig | Out-Null
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
        $PgServiceLogonAccount
    ) | Out-Null
    Set-TicketboxServiceIdentityContract `
        -Name $PgServiceName `
        -LogonAccount $PgServiceLogonAccount `
        -SidType $TargetServiceSidType
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

function Resolve-TicketboxRecoverableFreshInstallPendingIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][object]$LifecycleReceipt
    )

    Assert-TicketboxInstallationIdentityBaseMatches $Identity $Candidate
    if (
        [string]$Identity.State -cne "PENDING" -or
        -not (Test-TicketboxInstallationIdentityReleaseMatches $Identity $Candidate)
    ) {
        throw "PENDING installation identity 不属于当前安装包；构建验证阶段拒绝跨 release 续接。"
    }
    $receiptOperationId =
        [string]$LifecycleReceipt.database_generation_operation_id
    if (
        -not [string]::IsNullOrEmpty($receiptOperationId) -and
        $receiptOperationId -cne [string]$Identity.OperationId
    ) {
        throw "PENDING installation identity 与生命周期回执 operation 不一致。"
    }
    return [pscustomobject]@{
        Identity = $Identity
        RecoveryStage = "same_release"
    }
}

if ($ValidateInstalledServicesOnly) {
    Assert-Admin
    Assert-DesktopManagerExpectedServiceNames
    Set-TicketboxRuntimeServiceContractFromBinding `
        -RequireBinding `
        -RequireBackendMarkerReadExecute
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
        Assert-TicketboxProtectedDirectoryAcl $InstallerState
        $handoffInstallationIdentity =
            Read-TicketboxPersistentInstallationIdentity -DataRoot $DataRoot
        Complete-TicketboxOwnerBootstrapHandoff `
            -ExpectedOperationId ([string]$handoffInstallationIdentity.OperationId) `
            -ExpectedInstallationId ([string]$handoffInstallationIdentity.InstallationId)
        Write-Host "Installation owner pairing handoff artifacts removed OK。" -ForegroundColor Green
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
$parsedLifecycleFinalizationAttemptId = [guid]::Empty
if (
    -not [guid]::TryParseExact(
        $LifecycleFinalizationAttemptId,
        "D",
        [ref]$parsedLifecycleFinalizationAttemptId
    ) -or
    $parsedLifecycleFinalizationAttemptId -eq [guid]::Empty -or
    $parsedLifecycleFinalizationAttemptId.ToString("D") -cne
        $LifecycleFinalizationAttemptId
) {
    throw "正式安装或升级缺少当前 Inno 运行态绑定的 finalization attempt。"
}
$operationLock = Enter-TicketboxLifecycleLock `
    -ExternalOwnerProcessId $InstallerLockOwnerProcessId
$mutationStarted = $false
$serviceCompensationAuthority =
    New-TicketboxInstallServiceCompensationAuthority
$DeferredPreservedDataBackup = $false
$installedC07PayloadLease = $null
$resolvedPublicFailurePath = ""
$resolvedDiagnosticLogPath = ""
$receiptInstallationOperationId = $LifecycleFinalizationAttemptId
$receiptInstallationId = ""
$receiptInstallationIdState = "not_assigned"
$databaseMutationState = "not_started"
$installLifecycleStage = "service_preflight"
$operationFailure = $null
$lifecycleExitFailureProjection = $null
$lifecycleExitProjectionPreparationFailure = $null
$lifecycleExitVetoProjection = $null
$lifecycleExitVetoPreparationFailure = $null
try {
    Assert-Admin
    $resolvedPublicFailurePath =
        Resolve-TicketboxInstallPublicFailurePath $PublicFailurePath
    if ($resolvedPublicFailurePath.Length -eq 0) {
        throw "正式安装缺少受保护的 lifecycle bootstrap 失败回执路径。"
    }
    $resolvedDiagnosticLogPath =
        Resolve-TicketboxInstallDiagnosticLogPath $DiagnosticLogPath
    $installLifecycleStage = "package_provenance"
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
        $PreviousReleaseConfig = $lifecycleReceipt.installed_release_config
        $ServiceIdentityLifecycleReceipt = $lifecycleReceipt
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

    Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir | Out-Null
    Assert-PortAvailableForMissingServices
    $preExistingPgService = Service-Exists $PgServiceName
    $preExistingBackendService = Service-Exists $BackendServiceName
    $allowTargetPolicyFallbackBeforeMutation =
        $FilesMayHaveBeenReplaced -or
        (
            $null -ne $lifecycleReceipt -and
            [string]$lifecycleReceipt.preparation_stage -eq "prepared"
        )
    Assert-ExpectedServiceConfiguration `
        -Name $BackendServiceName `
        -ExpectedStopTimeoutMs $PreviousStopTimeoutMs `
        -ExpectedRestartDelayMs $PreviousRestartDelayMs `
        -ExpectedReleaseConfig $PreviousReleaseConfig `
        -AllowTargetPolicyFallback:$allowTargetPolicyFallbackBeforeMutation `
        -AllowMissingInstallerRecoveryGuard:$preExistingBackendService `
        -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent `
        -AllowMissingOwnerRecoveryChannel:$preExistingBackendService
    Assert-ExpectedServiceConfiguration `
        -Name $PgServiceName `
        -ExpectedStopTimeoutMs $PreviousStopTimeoutMs `
        -ExpectedRestartDelayMs $PreviousRestartDelayMs `
        -ExpectedReleaseConfig $PreviousReleaseConfig `
        -AllowTargetPolicyFallback:$allowTargetPolicyFallbackBeforeMutation `
        -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent
    foreach ($existingServiceName in @(
        $(if ($preExistingPgService) { $PgServiceName }),
        $(if ($preExistingBackendService) { $BackendServiceName })
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$existingServiceName)) { continue }
        $existingStartMode = Get-TicketboxServiceStartMode $existingServiceName
        if ($existingStartMode -notin @("Disabled", "Manual", "Automatic")) {
            throw "既有服务 $existingServiceName 的启动模式不受支持：$existingStartMode"
        }
        Assert-TicketboxServiceFailurePolicy `
            -Name $existingServiceName `
            -ExpectedResetSeconds ([int]$PreviousReleaseConfig.scm_failure_reset_seconds) `
            -ExpectedRestartDelaysMs @($PreviousReleaseConfig.scm_restart_delays_ms)
    }
    if ($preExistingPgService) {
        Grant-TicketboxInstallServiceCompensationAuthority `
            -Authority $serviceCompensationAuthority `
            -Service "PostgresService" `
            -Grant "validated_preexisting"
    }
    if ($preExistingBackendService) {
        Grant-TicketboxInstallServiceCompensationAuthority `
            -Authority $serviceCompensationAuthority `
            -Service "BackendService" `
            -Grant "validated_preexisting"
    }
    $serviceReadAccounts = @()
    if ($preExistingPgService) {
        $serviceReadAccounts += "NT SERVICE\$PgServiceName"
    }
    if ($preExistingBackendService) {
        $serviceReadAccounts += "NT SERVICE\$BackendServiceName"
    }
    Initialize-TicketboxSecureInstallRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $serviceReadAccounts | Out-Null
    $installedC07PayloadLease =
        Enter-TicketboxInstalledC07PayloadAuthorityLease `
            -InstallDir $InstallDir `
            -InstallerManifestPath $InstalledBuildManifestPath `
            -ExpectedPgMajor $TargetPgMajor
    $installedBuildManifest =
        $installedC07PayloadLease.InstalledBuildManifest
    $installLifecycleStage = "host_preparation"
    if ($InstallerLockOwnerProcessId -gt 0) {
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
    }

    $hadExistingPgService = $preExistingPgService
    $hadExistingBackendService = $preExistingBackendService

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
        -InstallDir $InstallDir `
        -AclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName

    $installLifecycleStage = "data_root_preparation"
    $mutationStarted = $true
    if ($hadExistingBackendService) {
        Stop-ServiceIfExists `
            -Name $BackendServiceName `
            -ExpectedStopTimeoutMs $PreviousStopTimeoutMs `
            -ExpectedRestartDelayMs $PreviousRestartDelayMs `
            -ExpectedReleaseConfig $PreviousReleaseConfig `
            -AllowTargetPolicyFallback:$FilesMayHaveBeenReplaced `
            -AllowMissingInstallerRecoveryGuard `
            -AllowLegacyRuntimeDataContract:$RuntimeDataBindingPresent `
            -AllowMissingOwnerRecoveryChannel
    }
    else {
        Assert-TicketboxRuntimeAbsent `
            -Name $BackendServiceName `
            -RuntimePort $BackendPort `
            -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)
    }
    if (-not $hadExistingPgService) {
        Initialize-TicketboxSecureDataRoot `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -Accounts @("SYSTEM", "BUILTIN\Administrators") `
            -DataRootMarkerAclPhase backend_read_optional `
            -ExpectedBackendServiceName $BackendServiceName
    }
    New-Item -ItemType Directory -Force -Path `
        $AppData, `
        $DefaultUploadRoot, `
        $LogDir, `
        $BackupDir | Out-Null
    Initialize-TicketboxInstallerStateArtifacts
    if ($hadExistingPgService) {
        Set-TicketboxAcl `
            -IncludePgService $true `
            -IncludeBackendService $hadExistingBackendService
    }
    $serviceLayerBackupRequired =
        -not $PreUpgradeBackupAlreadyCompleted -and
        (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION") -PathType Leaf) -and
        (Test-Path -LiteralPath $EnvPath -PathType Leaf)
    if ($serviceLayerBackupRequired -and -not $hadExistingPgService) {
        Register-PgService `
            -CompensationAuthority $serviceCompensationAuthority
        Set-TicketboxAcl -IncludePgService $true -IncludeBackendService $false
    }
    Invoke-PreUpgradeBackupIfNeeded

    $databaseGenerationHostContract =
        New-TicketboxDatabaseGenerationHostContract `
            -BackendServiceName $BackendServiceName `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -PgCtlPath $PgCtl `
            -PgServiceName $PgServiceName `
            -PgDumpPath $PgDump `
            -PgDumpSize ([int64]$installedBuildManifest.PgDump.Size) `
            -PgDumpSha256 ([string]$installedBuildManifest.PgDump.Sha256) `
            -PgRestorePath $PgRestore `
            -PgRestoreSize ([int64]$installedBuildManifest.PgRestore.Size) `
            -PgRestoreSha256 ([string]$installedBuildManifest.PgRestore.Sha256) `
            -ReleaseConfig $ReleaseConfig
    $databaseGenerationProjectionContract =
        New-TicketboxDatabaseGenerationProjectionContract `
            -BackendServiceName $BackendServiceName `
            -EnvPath $EnvPath `
            -StopTimeoutMilliseconds $StopTimeoutMs `
            -BackendPort $BackendPort `
            -PgBin $PgBin `
            -Timezone $Timezone `
            -PublicBaseUrl $PublicBaseUrl `
            -PsqlPath $Psql `
            -PgData $PgData `
            -DatabaseToolTimeoutMilliseconds $DatabaseToolTimeoutMs
    $databaseGenerationIntentContext =
        Read-TicketboxDatabaseGenerationIntentContext `
            -InstallerState $InstallerState `
            -LifecycleLock $operationLock `
            -HostContract $databaseGenerationHostContract `
            -ProjectionContract $databaseGenerationProjectionContract
    $databaseGenerationIntent = $databaseGenerationIntentContext.Artifact

    $installLifecycleStage = "installation_identity"
    $c07PendingIdentityPath =
        Get-TicketboxPendingInstallationIdentityPath $DataRoot
    $c07InstallationReleaseCandidate =
        Get-TicketboxInstallationReleaseCandidate `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -PgServiceName $PgServiceName `
            -BackendServiceName $BackendServiceName `
            -BuildManifestPath $InstalledBuildManifestPath
    try {
        $c07InstallationIdentity = if (
            Test-Path -LiteralPath $c07PendingIdentityPath
        ) {
            Repair-TicketboxRecoverableInstallationIdentityAcl `
                -Candidate $c07InstallationReleaseCandidate `
                -Pending | Out-Null
            Read-TicketboxPersistentInstallationIdentity `
                -DataRoot $DataRoot `
                -Pending
        }
        else {
            Initialize-TicketboxPendingInstallationIdentity `
                -DataRoot $DataRoot `
                -InstallDir $InstallDir `
                -PgPort $PgPort `
                -BackendPort $BackendPort `
                -PgServiceName $PgServiceName `
                -BackendServiceName $BackendServiceName `
                -BuildManifestPath $InstalledBuildManifestPath `
                -ExpectedOperationId (
                    [string]$databaseGenerationIntent.Payload.operation_id
                ) `
                -ExpectedInstallationId (
                    [string]$databaseGenerationIntent.Payload.installation_id
                )
        }
        $c07PendingIdentityResolution =
            Resolve-TicketboxRecoverableFreshInstallPendingIdentity `
                -Candidate $c07InstallationReleaseCandidate `
                -Identity $c07InstallationIdentity `
                -LifecycleReceipt $lifecycleReceipt
        $c07InstallationIdentity = $c07PendingIdentityResolution.Identity
        if (
            [string]$c07InstallationIdentity.OperationId -cne
                [string]$databaseGenerationIntent.Payload.operation_id -or
            [string]$c07InstallationIdentity.InstallationId -cne
                [string]$databaseGenerationIntent.Payload.installation_id
        ) {
            throw "PENDING installation identity 与 preinstall generation intent 漂移。"
        }
    }
    catch {
        $identityFailure = [InvalidOperationException]::new(
            "安装身份恢复或前数据库换包未通过安全验证。",
            $_.Exception
        )
        $identityFailure.Data["TicketboxInstallPublicFailureCode"] =
            "installation_identity_recovery_failed"
        throw $identityFailure
    }
    $receiptInstallationOperationId =
        [string]$c07InstallationIdentity.OperationId
    $receiptInstallationId = [string]$c07InstallationIdentity.InstallationId
    $receiptInstallationIdState = "assigned"
    $installLifecycleStage = "owner_handoff_adoption"
    try {
        $handoffDisposition = Adopt-TicketboxOwnerBootstrapHandoff `
            -ExpectedOperationId ([string]$c07InstallationIdentity.OperationId) `
            -ExpectedInstallationId ([string]$c07InstallationIdentity.InstallationId)
        if ($handoffDisposition -ceq "pending") {
            Write-Ok "已接管上次中断的 installation owner 短期配对交付。"
        }
        elseif ($handoffDisposition -ceq "cleaned_confirmed") {
            Write-Ok "已清理上次确认完成的 installation owner 配对交付残留。"
        }
    }
    catch {
        $ownerBindingFailure = [InvalidOperationException]::new(
            "installation owner 绑定状态未通过安全验证。",
            $_.Exception
        )
        $ownerBindingFailure.Data["TicketboxInstallPublicFailureCode"] =
            "installation_owner_binding_failed"
        $ownerBindingFailure.Data["TicketboxInstallationOperationId"] =
            [string]$c07InstallationIdentity.OperationId
        $ownerBindingFailure.Data["TicketboxInstallationId"] =
            [string]$c07InstallationIdentity.InstallationId
        throw $ownerBindingFailure
    }
    if ($c07InstallationIdentity.State -ceq "PENDING") {
        Set-TicketboxLifecycleReceiptDatabaseGenerationOperation `
            -Path $LifecycleReceiptPath `
            -Receipt $lifecycleReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -OperationId $c07InstallationIdentity.OperationId
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
            [string]$lifecycleReceipt.database_generation_operation_id -cne
                [string]$c07InstallationIdentity.OperationId
        ) {
            throw "安装事务未原子绑定 database generation operation。"
        }
    }
    $databaseGenerationReleaseContract =
        New-TicketboxDatabaseGenerationReleaseContract `
            -InstallationIdentity $c07InstallationIdentity `
            -ReleaseCandidate $c07InstallationReleaseCandidate
    $installLifecycleStage = "database_cluster"
    $databaseMutationState = "started_or_possible"
    [void](Initialize-PgClusterIfNeeded -InitdbInvoker {
        param($BootstrapState)
        Invoke-TicketboxServiceOwnedInitdb `
            -BootstrapState $BootstrapState `
            -CompensationAuthority $serviceCompensationAuthority
    })
    Initialize-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $RuntimeDataBindingServiceAccounts `
        -DataRootMarkerAclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName | Out-Null
    Set-TicketboxRuntimeServiceContractFromBinding -RequireBinding
    $installLifecycleStage = "service_registration"
    Register-PgService `
        -RuntimeBindingTransition `
        -CompensationAuthority $serviceCompensationAuthority
    Register-BackendService `
        -CompensationAuthority $serviceCompensationAuthority
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
    $installLifecycleStage = "schema_migration"
    Write-Step "收敛 release schema 到 frozen head"
    $databaseGeneration = Invoke-TicketboxInstalledDatabaseGeneration `
        -IntentContext $databaseGenerationIntentContext `
        -ReleaseIdentity $databaseGenerationReleaseContract `
        -LifecycleLock $operationLock `
        -HostContract $databaseGenerationHostContract `
        -ProjectionContract $databaseGenerationProjectionContract `
        -BootstrapRecoveryPath (Get-PostgresBootstrapRecoveryPath)
    $databaseUrl = [string]$databaseGeneration.DatabaseUrl
    Write-Ok "release schema exact head: $($databaseGeneration.CommittedRevision)"
    Set-TicketboxLifecycleReceiptDatabaseGenerationEvidence `
        -Path $LifecycleReceiptPath `
        -Receipt $lifecycleReceipt `
        -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
        -OperationId ([string]$c07InstallationIdentity.OperationId) `
        -CurrentSha256 ([string]$databaseGeneration.CurrentSha256)
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
        $installLifecycleStage = "installation_owner_claim"
        try {
            Complete-FirstOwnerBootstrapIfEnabled `
                -DatabaseUrl $databaseUrl `
                -InstallationOperationId ([string]$c07InstallationIdentity.OperationId) `
                -InstallationId ([string]$c07InstallationIdentity.InstallationId)
        }
        catch {
            $ownerBindingFailure = [InvalidOperationException]::new(
                "installation owner 短期配对未完成。",
                $_.Exception
            )
            $ownerBindingFailure.Data["TicketboxInstallPublicFailureCode"] =
                "installation_owner_binding_failed"
            $ownerBindingFailure.Data["TicketboxInstallationOperationId"] =
                [string]$c07InstallationIdentity.OperationId
            $ownerBindingFailure.Data["TicketboxInstallationId"] =
                [string]$c07InstallationIdentity.InstallationId
            throw $ownerBindingFailure
        }
    }

    Write-Host ""
    Write-Host "========== 服务初始化完成，等待安装器最终提交 ==========" -ForegroundColor Green
    Write-Host "安装目录 : $InstallDir"
    Write-Host "数据目录 : $DataRoot"
    Write-Host "后端地址 : http://127.0.0.1:$BackendPort"
    Write-Host "首次配对: $OwnerHandoffPath（首次安装时生成，短期有效）"
    Write-Host "======================================================" -ForegroundColor Green
}
catch {
    $failure = $_.Exception
    if ($mutationStarted) {
        try {
            Invoke-TicketboxInstallFailureCompensation `
                -Reason $failure.Message `
                -ServiceCompensationAuthority $serviceCompensationAuthority
        }
        catch {
            $compensationFailure = $_.Exception
            $failure = New-TicketboxInstallCompensationAggregateFailure `
                -InstallFailure $failure `
                -CompensationFailure $compensationFailure
        }
    }
    try {
        Publish-TicketboxInstallPublicFailureReceipt `
            -Path $resolvedPublicFailurePath `
            -LifecycleLock $operationLock `
            -FinalizationAttemptId $LifecycleFinalizationAttemptId `
            -InstallationOperationId $receiptInstallationOperationId `
            -InstallationIdState $receiptInstallationIdState `
            -InstallationId $receiptInstallationId `
            -LifecycleStage $installLifecycleStage `
            -ProtectedLogPath $resolvedDiagnosticLogPath `
            -Failure $failure `
            -DatabaseMutationState $databaseMutationState
    }
    catch {
        Write-Warning (
            "无法发布公开安装失败回执；保留受保护原始日志。" +
            $_.Exception.Message
        )
    }
    $operationFailure = $failure
}
finally {
    [Exception[]]$finalizationFailures = @()
    try {
        Close-TicketboxInstalledC07PayloadAuthorityLease `
            $installedC07PayloadLease
    }
    catch {
        $finalizationFailure = $_.Exception
        $finalizationFailure.Data["TicketboxInstallFinalizationStep"] =
            "payload_lease_close"
        $finalizationFailures += $finalizationFailure
    }
    try {
        Exit-TicketboxLifecycleLock $operationLock
    }
    catch {
        $finalizationFailure = $_.Exception
        $finalizationFailure.Data["TicketboxInstallFinalizationStep"] =
            "lifecycle_lock_exit"
        $finalizationFailures += $finalizationFailure
    }
    if ($finalizationFailures.Count -gt 0) {
        throw (New-TicketboxInstallFinalizationAggregateFailure `
            -OperationFailure $operationFailure `
            -FinalizationFailures $finalizationFailures)
    }
}
if ($null -ne $operationFailure) {
    throw $operationFailure
}
