#Requires -Version 5.1
<#
.SYNOPSIS
  Install or upgrade the bundled Ticketbox Windows services.

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
$C07DatabaseScript = Join-Path $ScriptDir "windows_c07_database.ps1"
if (-not (Test-Path -LiteralPath $C07DatabaseScript -PathType Leaf)) {
    throw "缺少 Windows C07 数据库权威脚本：$C07DatabaseScript"
}
. $C07DatabaseScript
$C07SuperuserRecoveryScript = Join-Path `
    $ScriptDir `
    "windows_c07_superuser_recovery.ps1"
if (-not (Test-Path -LiteralPath $C07SuperuserRecoveryScript -PathType Leaf)) {
    throw "缺少 Windows C07 superuser recovery 脚本：$C07SuperuserRecoveryScript"
}
. $C07SuperuserRecoveryScript
$C07HeartbeatAuthorityScript = Join-Path `
    $ScriptDir `
    "windows_c07_heartbeat_authority.ps1"
if (-not (Test-Path -LiteralPath $C07HeartbeatAuthorityScript -PathType Leaf)) {
    throw "缺少 Windows C07 shared heartbeat authority module：$C07HeartbeatAuthorityScript"
}
$C07LifecycleScript = Join-Path $ScriptDir "windows_c07_lifecycle.ps1"
if (-not (Test-Path -LiteralPath $C07LifecycleScript -PathType Leaf)) {
    throw "缺少 Windows C07 生命周期脚本：$C07LifecycleScript"
}
. $C07LifecycleScript
$C07HeartbeatHelperScript = Join-Path `
    $ScriptDir `
    "windows_c07_heartbeat_helper.ps1"
if (-not (Test-Path -LiteralPath $C07HeartbeatHelperScript -PathType Leaf)) {
    throw "缺少 Windows C07 durable heartbeat helper：$C07HeartbeatHelperScript"
}
$C07FailureSummaryScript = Join-Path `
    $ScriptDir `
    "windows_c07_failure_summary.ps1"
if (-not (Test-Path -LiteralPath $C07FailureSummaryScript -PathType Leaf)) {
    throw "缺少 Windows C07 installer failure summary 脚本：$C07FailureSummaryScript"
}
. $C07FailureSummaryScript

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
        (Join-Path $bootstrapRoot "installer-public-failure-v2.txt")
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

function Assert-TicketboxInstallPublicIdentifier {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Field
    )

    if ($Value -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$') {
        throw "公开安装失败回执 $Field 不是安全标识符。"
    }
}

function Publish-TicketboxInstallPublicFailureReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId,
        [Parameter(Mandatory = $true)][string]$InstallationOperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][string]$LifecycleStage,
        [Parameter(Mandatory = $true)][string]$ProtectedLogPath,
        [Parameter(Mandatory = $true)][Exception]$Failure,
        [Parameter(Mandatory = $true)][bool]$MutationStarted
    )

    $canonicalPath = Resolve-TicketboxInstallPublicFailurePath $Path
    if ($canonicalPath.Length -eq 0) { return }
    $canonicalLogPath = Resolve-TicketboxInstallDiagnosticLogPath $ProtectedLogPath
    Assert-TicketboxInstallPublicIdentifier `
        -Value $FinalizationAttemptId `
        -Field "FINALIZATION_ATTEMPT_ID"
    Assert-TicketboxInstallPublicIdentifier `
        -Value $InstallationOperationId `
        -Field "INSTALLATION_OPERATION_ID"
    Assert-TicketboxInstallPublicIdentifier `
        -Value $InstallationId `
        -Field "INSTALLATION_ID"
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
    if ($MutationStarted) {
        $databaseMutationState = "started_or_possible"
    }
    else {
        $databaseMutationState = "not_started"
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
        "SCHEMA=ticketbox-install-public-failure-v2",
        "INSTALLER_OWNER_PID=$([uint32]$ownerIdentity.ProcessId)",
        "INSTALLER_OWNER_STARTED_FILETIME_HIGH=$([uint32]$ownerIdentity.StartedFileTimeHigh)",
        "INSTALLER_OWNER_STARTED_FILETIME_LOW=$([uint32]$ownerIdentity.StartedFileTimeLow)",
        "FINALIZATION_ATTEMPT_ID=$FinalizationAttemptId",
        "INSTALLATION_OPERATION_ID=$InstallationOperationId",
        "INSTALLATION_ID=$InstallationId",
        "LIFECYCLE_STAGE=$LifecycleStage",
        "CONTEXT=service_installation",
        "FAILURE_CODE=$failureCode",
        "RETRY_CLASS=$retryClass",
        "DATABASE_MUTATION_STATE=$databaseMutationState",
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
$C07RecoveryGenerationScript = Join-Path `
    $ScriptDir `
    "windows_c07_recovery_generation.ps1"
if (-not (Test-Path -LiteralPath $C07RecoveryGenerationScript -PathType Leaf)) {
    throw "缺少 Windows C07 恢复代际脚本：$C07RecoveryGenerationScript"
}
. $C07RecoveryGenerationScript
$C07PackagedMigrationScript = Join-Path `
    $ScriptDir `
    "windows_c07_packaged_migration.ps1"
if (-not (Test-Path -LiteralPath $C07PackagedMigrationScript -PathType Leaf)) {
    throw "缺少 Windows C07 frozen migration bridge：$C07PackagedMigrationScript"
}
. $C07PackagedMigrationScript
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

function Get-TicketboxC07InstalledMigrationHelperEvidence(
    [object]$ReleaseIdentity
) {
    return [pscustomobject][ordered]@{
        RelativePath = [string]$ReleaseIdentity.MigrationHelperRelativePath
        Size = [int64]$ReleaseIdentity.MigrationHelperSize
        Sha256 = [string]$ReleaseIdentity.MigrationHelperSha256
    }
}

function New-TicketboxC07InstalledLifecycleFailure {
    param([Parameter(Mandatory = $true)][object]$Lifecycle)

    $failureCode = [string]$Lifecycle.failure_code
    if ($failureCode -cnotmatch "^[a-z0-9_]{1,64}$") {
        throw "C07 installed lifecycle 返回了无效 failure terminal。"
    }
    $terminalFailure = [InvalidOperationException]::new(
        "C07 installed lifecycle failure_code=$failureCode"
    )
    $terminalFailure.Data["TicketboxC07FailureCode"] = $failureCode
    return $terminalFailure
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

function New-TicketboxInstallFailureSummaryAggregateFailure {
    param(
        [Parameter(Mandatory = $true)][Exception]$InstallFailure,
        [Parameter(Mandatory = $true)][Exception]$SummaryFailure
    )

    $aggregateFailure = [AggregateException]::new(
        (
            "安装动作失败，且受保护 C07 failure summary 无法可靠发布；" +
            "原始安装异常与摘要异常均已保留。"
        ),
        [Exception[]]@($InstallFailure, $SummaryFailure)
    )
    $aggregateFailure.Data["TicketboxC07FailureSummaryFailed"] = $true
    foreach ($key in @(
        "TicketboxC07FailureCode",
        "TicketboxC07FailureCodes",
        "TicketboxInstallCompensationFailed",
        "TicketboxInstallPublicFailureCode"
    )) {
        if ($InstallFailure.Data.Contains($key)) {
            $aggregateFailure.Data[$key] = $InstallFailure.Data[$key]
        }
    }
    return $aggregateFailure
}

function Write-TicketboxInstallC07FailureSummaryIfPresent {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId,
        [Parameter(Mandatory = $true)][Exception]$Failure
    )

    $c07AuthorityPath = Get-TicketboxC07AuthorityPath
    $c07AuthorityKind = Get-TicketboxPathEntryKindNoFollow $c07AuthorityPath
    if ($c07AuthorityKind -ceq "Missing") {
        return
    }
    if ($c07AuthorityKind -cne "File") {
        throw "C07 authority 路径不是受保护普通文件，拒绝生成 owner summary。"
    }
    Write-TicketboxC07InstallerFailureSummary `
        -DataRoot $DataRoot `
        -InstallerState $InstallerState `
        -LifecycleLock $LifecycleLock `
        -FinalizationAttemptId $FinalizationAttemptId `
        -Failure $Failure | Out-Null
}

function New-TicketboxInstallC07LifecycleExitFailureProjectionIfPresent {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId
    )

    $c07AuthorityPath = Get-TicketboxC07AuthorityPath
    $c07AuthorityKind = Get-TicketboxPathEntryKindNoFollow $c07AuthorityPath
    if ($c07AuthorityKind -ceq "Missing") {
        return $null
    }
    if ($c07AuthorityKind -cne "File") {
        throw "C07 authority 路径不是受保护普通文件，拒绝预授权 blocked summary。"
    }
    return New-TicketboxC07InstallerLifecycleExitFailureProjection `
        -DataRoot $DataRoot `
        -InstallerState $InstallerState `
        -LifecycleLock $LifecycleLock `
        -FinalizationAttemptId $FinalizationAttemptId
}

function New-TicketboxInstallC07LifecycleExitVetoIfPresent {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$FinalizationAttemptId
    )

    $c07AuthorityPath = Get-TicketboxC07AuthorityPath
    $c07AuthorityKind = Get-TicketboxPathEntryKindNoFollow $c07AuthorityPath
    if ($c07AuthorityKind -ceq "Missing") {
        return $null
    }
    if ($c07AuthorityKind -cne "File") {
        throw "C07 authority 路径不是受保护普通文件，拒绝生成 durable exit veto。"
    }
    return New-TicketboxC07InstallerLifecycleExitVeto `
        -DataRoot $DataRoot `
        -InstallerState $InstallerState `
        -LifecycleLock $LifecycleLock `
        -FinalizationAttemptId $FinalizationAttemptId
}

function Invoke-TicketboxC07InstalledMigrationAction {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][object]$MigrationContext
    )

    return Invoke-TicketboxC07PackagedMigrationAction `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -SourceRevision $SourceRevision `
        -TargetRevision $TargetRevision `
        -MigrationContext $MigrationContext `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -ReleaseIdentity $ReleaseIdentity
}

function Invoke-TicketboxC07InstalledFreshSourceBootstrapAction {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision
    )

    return Invoke-TicketboxC07PackagedFreshSourceBootstrapAction `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -SourceRevision $SourceRevision `
        -TargetRevision $TargetRevision `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath
}

function Invoke-TicketboxC07InstalledIsolatedReplayAction {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$RestoreDatabase,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$CreateAttemptId
    )

    return Invoke-TicketboxC07PackagedIsolatedReplayAction `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -RestoreDatabase $RestoreDatabase `
        -OperationId $OperationId `
        -SourceRevision $SourceRevision `
        -TargetRevision $TargetRevision `
        -RevisionManifestSha256 $RevisionManifestSha256 `
        -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
        -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
        -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -CreateAttemptId $CreateAttemptId
}

function Invoke-TicketboxC07InstalledMoneyFactsAction {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [AllowEmptyString()][string]$SnapshotId = "",
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [AllowEmptyString()][string]$CreateAttemptId = ""
    )
    return Invoke-TicketboxC07PackagedMoneyFactsAction `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -Database $Database `
        -OperationId $OperationId `
        -SnapshotId $SnapshotId `
        -ExpectedRevision $ExpectedRevision `
        -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
        -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
        -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -CreateAttemptId $CreateAttemptId
}

function Invoke-TicketboxC07InstalledTargetSemanticAction {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [AllowEmptyString()][string]$SnapshotId = "",
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [AllowEmptyString()][string]$CreateAttemptId = ""
    )
    return Invoke-TicketboxC07PackagedTargetSemanticAction `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -Database $Database `
        -OperationId $OperationId `
        -SnapshotId $SnapshotId `
        -SourceRevision $SourceRevision `
        -TargetRevision $TargetRevision `
        -RevisionManifestSha256 $RevisionManifestSha256 `
        -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
        -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
        -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -CreateAttemptId $CreateAttemptId
}

function Get-TicketboxC07InstalledUpgradePlan {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][string]$SourceRevision
    )

    return Get-TicketboxC07PackagedInstalledUpgradePlan `
        -SourceRevision $SourceRevision `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath
}

function Get-TicketboxInstalledManagedSchemaPlan {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][string]$SourceRevision
    )

    return Get-TicketboxPackagedManagedSchemaPlan `
        -SourceRevision $SourceRevision `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath
}

function Invoke-TicketboxInstalledManagedSchemaUpgradeAction {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][object]$Plan
    )

    return Invoke-TicketboxPackagedManagedSchemaUpgrade `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -Plan $Plan `
        -MigrationHelperPath $ReleaseIdentity.MigrationHelperPath `
        -MigrationHelperEvidence (
            Get-TicketboxC07InstalledMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath $ReleaseIdentity.MigrationHelperPath
}

$script:TicketboxC07InstallerSourceRevision = "20260722_0001"

function Get-TicketboxC07BootstrapCatalogDisposition {
    $recoveryState = Read-PostgresBootstrapRecoveryState
    $legacyRole = Escape-SqlLiteral $script:TicketboxC07LegacyRuntimeRole
    $database = Escape-SqlLiteral $script:TicketboxC07DatabaseName
    $ownerRole = Escape-SqlLiteral $script:TicketboxC07OwnerRole
    $migratorRole = Escape-SqlLiteral $script:TicketboxC07MigratorRole
    $runtimeRole = Escape-SqlLiteral $script:TicketboxC07RuntimeRole
    $catalog = Invoke-Psql "postgres" @"
SELECT
    (SELECT count(*)::text FROM pg_roles WHERE rolname = '$legacyRole')
    || E'\t' ||
    (
        SELECT count(*)::text
        FROM pg_roles
        WHERE rolname IN ('$ownerRole', '$migratorRole', '$runtimeRole')
    )
    || E'\t' ||
    COALESCE(
        (
            SELECT owner_role.rolname
            FROM pg_database AS db
            JOIN pg_roles AS owner_role ON owner_role.oid = db.datdba
            WHERE db.datname = '$database'
        ),
        '__missing__'
    );
"@ $recoveryState.SuperuserPassword
    $fields = @($catalog.Trim() -split "`t")
    if (
        $fields.Count -ne 3 -or
        $fields[0] -cnotmatch '^[01]$' -or
        $fields[1] -cnotmatch '^[0-3]$'
    ) {
        throw "C07 bootstrap catalog 返回未知 shape。"
    }
    if (
        $fields[0] -ceq "0" -and
        $fields[1] -ceq "0" -and
        $fields[2] -ceq "__missing__"
    ) {
        return "fresh_install"
    }
    if (
        $fields[0] -ceq "1" -and
        $fields[1] -ceq "0" -and
        $fields[2] -cin @("__missing__", $script:TicketboxC07LegacyRuntimeRole)
    ) {
        return "legacy_adoption"
    }
    throw (
        "C07 无 .env 的 bootstrap catalog 不是空 fresh，也不是可恢复 " +
        "legacy Prepare 断点；拒绝猜测 authority。"
    )
}

function Get-TicketboxC07InstallerDatabaseDisposition {
    $environment = Read-EnvMap $EnvPath
    $bootstrapRecoveryPath = Get-PostgresBootstrapRecoveryPath
    $freshIntentPath = Get-TicketboxC07FreshBootstrapIntentPath
    if (-not $environment.ContainsKey("DATABASE_URL")) {
        if (-not (Test-Path -LiteralPath $bootstrapRecoveryPath -PathType Leaf)) {
            throw (
                "C07 安装缺少 DATABASE_URL，且没有受保护的 PostgreSQL " +
                "bootstrap recovery；拒绝猜测 fresh/legacy 身份。"
            )
        }
        [void](Read-PostgresBootstrapRecoveryState)
        if (Test-Path -LiteralPath $freshIntentPath) {
            return "fresh_install"
        }
        return Get-TicketboxC07BootstrapCatalogDisposition
    }

    $persistedDatabaseUrl = ConvertTo-TicketboxRequiredDatabaseUrl (
        [string]$environment["DATABASE_URL"]
    )
    $libpqUrl = Assert-TicketboxLocalDatabaseUrl `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort
    $builder = New-Object System.UriBuilder($libpqUrl)
    $role = [Uri]::UnescapeDataString($builder.UserName)
    $database = [Uri]::UnescapeDataString($builder.Path.TrimStart("/"))
    if ($database -cne $script:TicketboxC07DatabaseName) {
        throw "C07 安装 DATABASE_URL 未绑定 ticketbox 数据库。"
    }
    if ($role -ceq $script:TicketboxC07RuntimeRole) {
        return "runtime_ready"
    }
    if ($role -ceq $script:TicketboxC07LegacyRuntimeRole) {
        if (Test-Path -LiteralPath $freshIntentPath) {
            throw "C07 fresh intent 与 legacy DATABASE_URL 同时存在，拒绝错误接管。"
        }
        return "legacy_adoption"
    }
    throw "C07 安装拒绝未登记的 DATABASE_URL role：$role"
}

function Get-TicketboxC07InstalledAlembicRevision {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )

    $exists = Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 installer Alembic table probe" `
        -Sql (
            "SELECT (to_regclass('public.alembic_version') " +
            "IS NOT NULL)::text;"
        )
    if ($exists.Trim() -ceq "false") {
        return ""
    }
    if ($exists.Trim() -cne "true") {
        throw "C07 installer Alembic table probe 返回未知状态。"
    }
    $revision = Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 installer Alembic revision probe" `
        -Sql @"
SELECT COALESCE(
    (
        SELECT CASE
            WHEN count(*) = 0 THEN ''
            WHEN count(*) = 1 THEN min(version_num)
            ELSE '__multiple__'
        END
        FROM public.alembic_version
    ),
    ''
);
"@
    $canonical = $revision.Trim()
    if ($canonical -ceq "__multiple__") {
        throw "C07 installer 拒绝多个 Alembic head。"
    }
    if (
        $canonical.Length -gt 0 -and
        $canonical -cnotmatch '^[0-9]{8}_[0-9]{4}$'
    ) {
        throw "C07 installer Alembic revision shape 无效。"
    }
    return $canonical
}

function Invoke-TicketboxC07InstalledReleaseMigration {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][object]$FreshIntent,
        [AllowNull()][object]$SuccessorIntent,
        [Parameter(Mandatory = $true)][string]$RecoveryArtifactPath
    )

    if ($Mode -ceq "fresh_install" -and $null -eq $FreshIntent) {
        throw "C07 fresh install 缺少 durable bootstrap intent。"
    }
    if ($Mode -ceq "legacy_adoption" -and $null -ne $FreshIntent) {
        throw "C07 legacy adoption 不接受 fresh bootstrap intent。"
    }
    if (
        [string]$ReleaseIdentity.InstallationIdentityState -cne "PENDING" -or
        [string]::IsNullOrEmpty(
            [string]$ReleaseIdentity.InstallationOperationId
        )
    ) {
        throw "C07 release migration 只接受 durable PENDING installation identity。"
    }
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    $capturedMode = $Mode
    $capturedLock = $LifecycleLock
    $capturedIntent = $FreshIntent
    $capturedSuccessorIntent = $SuccessorIntent
    $capturedReleaseIdentity = $ReleaseIdentity
    $capturedDataRoot = $DataRoot
    $capturedFailureStages = @($script:TicketboxC07FailureStages)
    $capturedSourceRevision = $script:TicketboxC07InstallerSourceRevision
    $basePlan = Get-TicketboxC07InstalledUpgradePlan `
        -ReleaseIdentity $capturedReleaseIdentity `
        -SourceRevision $capturedSourceRevision
    if (
        [string]$basePlan.operation_kind -cne
            "c07_money_minor_bigint_v1" -or
        [string]$basePlan.source_revision -cne $capturedSourceRevision -or
        [string]$basePlan.target_revision -cne
            $script:TicketboxC07TargetRevision -or
        -not [bool]$basePlan.upgrade_required
    ) {
        throw "C07 base lifecycle plan 未绑定 frozen source/target。"
    }
    $capturedTargetRevision = [string]$basePlan.target_revision
    $capturedRevisionManifestSha256 =
        [string]$basePlan.revision_manifest_sha256
    Assert-TicketboxC07LowerSha256 `
        $capturedRevisionManifestSha256 `
        "C07 base revision manifest"
    $capturedHostRevisionManifestSha256 =
        $capturedRevisionManifestSha256.ToUpperInvariant()
    $migrationAction = {
        param(
            [object]$MigrationHostAuthority,
            [Security.SecureString]$MigrationPassword,
            [string]$SourceRevision,
            [string]$TargetRevision,
            [object]$MigrationContext
        )
        return Invoke-TicketboxC07InstalledMigrationAction `
            -ReleaseIdentity $capturedReleaseIdentity `
            -HostAuthority $MigrationHostAuthority `
            -MigratorPassword $MigrationPassword `
            -SourceRevision $SourceRevision `
            -TargetRevision $TargetRevision `
            -MigrationContext $MigrationContext
    }.GetNewClosure()
    $isolatedReplayAction = {
        param(
            [object]$ReplayHostAuthority,
            [Security.SecureString]$ReplayPassword,
            [string]$RestoreDatabase,
            [string]$OperationId,
            [string]$SourceRevision,
            [string]$TargetRevision,
            [string]$RevisionManifestSha256,
            [string]$MaintenanceDeadlineUtc,
            [int]$MaintenanceRemainingCeilingMs,
            [string]$MaintenanceAuthoritySha256,
            [string]$CreateAttemptId
        )
        return Invoke-TicketboxC07InstalledIsolatedReplayAction `
            -ReleaseIdentity $capturedReleaseIdentity `
            -HostAuthority $ReplayHostAuthority `
            -MigratorPassword $ReplayPassword `
            -RestoreDatabase $RestoreDatabase `
            -OperationId $OperationId `
            -SourceRevision $SourceRevision `
            -TargetRevision $TargetRevision `
            -RevisionManifestSha256 $RevisionManifestSha256 `
            -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
            -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
            -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
            -CreateAttemptId $CreateAttemptId
    }.GetNewClosure()
    $moneyFactsAction = {
        param(
            [object]$FactsHostAuthority,
            [Security.SecureString]$FactsPassword,
            [string]$Database,
            [string]$OperationId,
            [string]$SnapshotId,
            [string]$ExpectedRevision,
            [string]$MaintenanceDeadlineUtc,
            [int]$MaintenanceRemainingCeilingMs,
            [string]$MaintenanceAuthoritySha256,
            [AllowEmptyString()][string]$CreateAttemptId
        )
        return Invoke-TicketboxC07InstalledMoneyFactsAction `
            -ReleaseIdentity $capturedReleaseIdentity `
            -HostAuthority $FactsHostAuthority `
            -MigratorPassword $FactsPassword `
            -Database $Database `
            -OperationId $OperationId `
            -SnapshotId $SnapshotId `
            -ExpectedRevision $ExpectedRevision `
            -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
            -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
            -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
            -CreateAttemptId $CreateAttemptId
    }.GetNewClosure()
    $targetSemanticAction = {
        param(
            [object]$SemanticHostAuthority,
            [Security.SecureString]$SemanticPassword,
            [string]$Database,
            [string]$OperationId,
            [string]$SnapshotId,
            [string]$SourceRevision,
            [string]$TargetRevision,
            [string]$RevisionManifestSha256,
            [string]$MaintenanceDeadlineUtc,
            [int]$MaintenanceRemainingCeilingMs,
            [string]$MaintenanceAuthoritySha256,
            [AllowEmptyString()][string]$CreateAttemptId
        )
        return Invoke-TicketboxC07InstalledTargetSemanticAction `
            -ReleaseIdentity $capturedReleaseIdentity `
            -HostAuthority $SemanticHostAuthority `
            -MigratorPassword $SemanticPassword `
            -Database $Database `
            -OperationId $OperationId `
            -SnapshotId $SnapshotId `
            -SourceRevision $SourceRevision `
            -TargetRevision $TargetRevision `
            -RevisionManifestSha256 $RevisionManifestSha256 `
            -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
            -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
            -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
            -CreateAttemptId $CreateAttemptId
    }.GetNewClosure()
    $boundedAction = {
        param([Security.SecureString]$RecoveredSuperuserPassword)

        $expectedOperationId =
            [string]$capturedReleaseIdentity.InstallationOperationId
        if ($capturedMode -ceq "fresh_install") {
            if (
                [string]$capturedIntent.OperationId -cne
                    $expectedOperationId
            ) {
                throw "C07 fresh intent 未绑定 PENDING installation operation。"
            }
            if (-not (Test-Path -LiteralPath (Get-TicketboxC07AuthorityPath))) {
                $migratorValidUntilUtc = [DateTime]::UtcNow.AddMilliseconds(
                    $script:TicketboxC07MaintenanceWindowSeconds * 1000
                )
                $freshDatabase = Initialize-TicketboxC07FreshDatabaseAuthority `
                    -SuperuserPassword $RecoveredSuperuserPassword `
                    -RuntimePassword $capturedIntent.RuntimePassword `
                    -MigratorPassword $capturedIntent.MigratorPassword `
                    -MigratorValidUntilUtc $migratorValidUntilUtc `
                    -OperationId $expectedOperationId
                $freshRevision = Get-TicketboxC07InstalledAlembicRevision `
                    -HostAuthority $hostAuthority `
                    -SuperuserPassword $RecoveredSuperuserPassword
                if ([string]::IsNullOrEmpty($freshRevision)) {
                    $freshSource =
                        Invoke-TicketboxC07InstalledFreshSourceBootstrapAction `
                            -ReleaseIdentity $capturedReleaseIdentity `
                            -HostAuthority $hostAuthority `
                            -MigratorPassword $capturedIntent.MigratorPassword `
                            -SourceRevision $capturedSourceRevision `
                            -TargetRevision $capturedTargetRevision
                    if (
                        [string]$freshSource.result -cne "source_committed" -or
                        [string]$freshSource.alembic_revision -cne
                            $capturedSourceRevision
                    ) {
                        throw (
                            "C07 fresh-source bootstrap 未提交 exact " +
                            "source revision。"
                        )
                    }
                }
                elseif ($freshRevision -cne $capturedSourceRevision) {
                    throw (
                        "C07 fresh install 在 lifecycle capture 前发现未知 " +
                        "Alembic revision：$freshRevision"
                    )
                }
            }
        }

        $operation = New-TicketboxC07LifecycleOperation `
            -DataRoot $capturedDataRoot `
            -LifecycleLock $capturedLock `
            -SuperuserPassword $RecoveredSuperuserPassword `
            -TargetRevision $capturedTargetRevision `
            -OperationKind "c07_money_minor_bigint_v1" `
            -RevisionManifestSha256 `
                $capturedHostRevisionManifestSha256 `
            -ExpectedOperationId $expectedOperationId `
            -SuccessorIntent $capturedSuccessorIntent
        $operationAuthority = Read-TicketboxC07Authority $capturedDataRoot
        $operationStage = [string]$operationAuthority.Receipt.stage
        if ($operationStage -in $capturedFailureStages) {
            # Failure terminals are already durable and authoritative. Do not
            # ask them for an active maintenance budget or create/recover
            # credentials: both would obscure the exact terminal failure_code
            # with a generic "missing active attempt" error.
            throw (New-TicketboxC07InstalledLifecycleFailure (
                [pscustomobject][ordered]@{
                    failure_code =
                        [string]$operationAuthority.Receipt.failure_code
                }
            ))
        }
        $credentials = Get-OrCreateTicketboxC07InstalledCredentials `
            -DataRoot $capturedDataRoot `
            -LifecycleLock $capturedLock `
            -Mode $capturedMode
        $migratorValidUntilUtc = [DateTime]::UtcNow
        if ($operationStage -cne "ready") {
            $operationBudget =
                New-TicketboxC07MaintenanceBudget $operationAuthority
            $migratorValidUntilUtc = [DateTime]$operationBudget.DeadlineUtc
        }
        $lifecycle = Invoke-TicketboxC07InstalledProductionLifecycle `
            -DataRoot $capturedDataRoot `
            -LifecycleLock $capturedLock `
            -SuperuserPassword $RecoveredSuperuserPassword `
            -RuntimePassword $credentials.RuntimePassword `
            -MigratorPassword $credentials.MigratorPassword `
            -MigratorValidUntilUtc $migratorValidUntilUtc `
            -Mode $capturedMode `
            -ExpectedSourceRevision $capturedSourceRevision `
            -TargetRevision $capturedTargetRevision `
            -OperationKind "c07_money_minor_bigint_v1" `
            -RevisionManifestSha256 `
                $capturedHostRevisionManifestSha256 `
            -MigrationAction $migrationAction `
            -IsolatedReplayAction $isolatedReplayAction `
            -MoneyFactsAction $moneyFactsAction `
            -TargetSemanticAction $targetSemanticAction `
            -ExpectedOperationId $expectedOperationId `
            -SuccessorIntent $capturedSuccessorIntent
        if ([string]$lifecycle.result -cne "ready") {
            throw (New-TicketboxC07InstalledLifecycleFailure $lifecycle)
        }
        if (
            [string]$lifecycle.operation_id -cne
                [string]$operation.OperationId -or
            [string]$lifecycle.target_revision -cne
                $capturedTargetRevision
        ) {
            throw "C07 installed lifecycle READY 未绑定 exact operation。"
        }
        return [pscustomobject][ordered]@{
            schema = "ticketbox-c07-installer-migration-result-v1"
            mode = $capturedMode
            operation_id = [string]$operation.OperationId
            result = "ready"
            runtime_password = $credentials.RuntimePassword
            production_authority_sha256 =
                [string]$lifecycle.production_authority_sha256
            runtime_projection_sha256 =
                [string]$lifecycle.runtime_projection_sha256
        }
    }.GetNewClosure()

    return Invoke-TicketboxC07RecoveredSuperuserAction `
        -HostAuthority $hostAuthority `
        -RecoveryArtifactPath $RecoveryArtifactPath `
        -Action $boundedAction
}
function Write-TicketboxC07InstalledRuntimeEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$RuntimePassword
    )

    $authority = Read-TicketboxC07Authority $DataRoot
    if ([string]$authority.Receipt.stage -cne "ready") {
        throw "C07 runtime .env 只能在 durable READY 后发布。"
    }
    [void](Read-TicketboxC07RuntimeProjection $DataRoot)
    $capturedEnvPath = $EnvPath
    $capturedPgPort = $PgPort
    $capturedPgData = $PgData
    $capturedPsql = $Psql
    $capturedTimeoutMs = $DatabaseToolTimeoutMs
    $capturedDatabase = $script:TicketboxC07DatabaseName
    $capturedRole = $script:TicketboxC07RuntimeRole
    $capturedHostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $RuntimePassword `
        -Action ({
            param([string]$PlainPassword)

            $encodedRole = [Uri]::EscapeDataString($capturedRole)
            $encodedPassword = [Uri]::EscapeDataString($PlainPassword)
            $encodedDatabase = [Uri]::EscapeDataString($capturedDatabase)
            $databaseUrl = (
                "postgresql+psycopg://${encodedRole}:${encodedPassword}" +
                "@127.0.0.1:${capturedPgPort}/${encodedDatabase}" +
                "?require_auth=scram-sha-256"
            )
            if (Test-Path -LiteralPath $capturedEnvPath -PathType Leaf) {
                Set-EnvDatabaseUrl `
                    -Path $capturedEnvPath `
                    -DatabaseUrl $databaseUrl
            }
            else {
                $recoveryState = Read-PostgresBootstrapRecoveryState
                $lines = (New-BaseEnvLines $databaseUrl) + @(
                    "ENABLE_HTTP_BOOTSTRAP=true",
                    "HTTP_BOOTSTRAP_SECRET=$($recoveryState.HttpBootstrapSecret)"
                )
                Write-EnvNoBom -Path $capturedEnvPath -Lines $lines
            }
            $environment = Read-EnvMap $capturedEnvPath
            if (-not $environment.ContainsKey("DATABASE_URL")) {
                throw "C07 runtime .env 写后复读缺少 DATABASE_URL。"
            }
            $connection = Get-TicketboxLocalDatabaseConnection `
                -DatabaseUrl ([string]$environment["DATABASE_URL"]) `
                -PgPort $capturedPgPort `
                -ExpectedDatabase $capturedDatabase `
                -ExpectedRole $capturedRole
            Assert-TicketboxConnectedPostgresDataRoot `
                -PsqlPath $capturedPsql `
                -DatabaseUrl $connection.DatabaseUrl `
                -ExpectedDataRoot $capturedPgData `
                -ExpectedPort $capturedPgPort `
                -Password $connection.Password `
                -TimeoutMilliseconds $capturedTimeoutMs
            Assert-TicketboxC07RuntimeCredential `
                -Authority $capturedHostAuthority `
                -RuntimePassword $RuntimePassword
            return [string]$connection.PersistedDatabaseUrl
        }.GetNewClosure())
}

function Complete-TicketboxC07RecoveredSuperuserResidue {
    param([Parameter(Mandatory = $true)][string]$RecoveryArtifactPath)

    if (-not (Test-Path -LiteralPath $RecoveryArtifactPath)) {
        return
    }
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    $capturedDataRoot = $DataRoot
    $boundedAction = {
        param([Security.SecureString]$RecoveredSuperuserPassword)

        $authority = Read-TicketboxC07Authority $capturedDataRoot
        if ([string]$authority.Receipt.stage -cne "ready") {
            throw "C07 superuser residue 只能在 durable READY 后收敛。"
        }
        $projection = Read-TicketboxC07RuntimeProjection $capturedDataRoot
        return [pscustomobject][ordered]@{
            schema = "ticketbox-c07-superuser-residue-result-v1"
            operation_id = [string]$authority.Receipt.operation_id
            result = "ready"
            runtime_projection_sha256 = [string]$projection.PayloadSha256
        }
    }.GetNewClosure()
    $result = Invoke-TicketboxC07RecoveredSuperuserAction `
        -HostAuthority $hostAuthority `
        -RecoveryArtifactPath $RecoveryArtifactPath `
        -Action $boundedAction
    if ([string]$result.result -cne "ready") {
        throw "C07 superuser recovery residue 未收敛到 READY。"
    }
}

function Complete-TicketboxC07InstalledSecretCleanup {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$RecoveryArtifactPath
    )

    if (Test-Path -LiteralPath $RecoveryArtifactPath) {
        throw "C07 superuser recovery artifact 尚未收敛，拒绝删除其它恢复材料。"
    }
    $authority = Read-TicketboxC07Authority $DataRoot
    if ([string]$authority.Receipt.stage -cne "ready") {
        throw "C07 secret cleanup 只允许在 durable READY 后执行。"
    }
    $credentialPath = Get-TicketboxC07InstalledCredentialPath (
        [string]$authority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $credentialPath) {
        Remove-TicketboxC07InstalledCredentials `
            -DataRoot $DataRoot `
            -LifecycleLock $LifecycleLock `
            -Mode $Mode
    }
    $freshIntentPath = Get-TicketboxC07FreshBootstrapIntentPath
    if (Test-Path -LiteralPath $freshIntentPath) {
        if ($Mode -cne "fresh_install") {
            throw "C07 legacy READY 后仍存在 fresh bootstrap intent。"
        }
        Remove-TicketboxC07FreshBootstrapIntent `
            -DataRoot $DataRoot `
            -LifecycleLock $LifecycleLock
    }
    $bootstrapRecoveryPath = Get-PostgresBootstrapRecoveryPath
    if (Test-Path -LiteralPath $bootstrapRecoveryPath) {
        Remove-TicketboxSensitiveFile $bootstrapRecoveryPath
    }
}

function Get-TicketboxRuntimeAlembicRevision {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword
    )

    $revision = Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role $script:TicketboxC07RuntimeRole `
        -Password $RuntimePassword `
        -Label "release schema runtime revision probe" `
        -Sql @"
SELECT CASE
    WHEN count(*) = 0 THEN ''
    WHEN count(*) = 1 THEN min(version_num)
    ELSE '__multiple__'
END
FROM public.alembic_version;
"@
    $canonical = $revision.Trim()
    if ($canonical -ceq "__multiple__") {
        throw "release schema runtime probe 拒绝多个 Alembic head。"
    }
    if ($canonical -cnotmatch '^[0-9]{8}_[0-9]{4}$') {
        throw "release schema runtime revision shape 无效。"
    }
    return $canonical
}

function Invoke-TicketboxInstalledManagedSchemaUpgrade {
    param(
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$C07Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)][object]$LifecycleReceipt,
        [Parameter(Mandatory = $true)][string]$RecoveryArtifactPath,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )

    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    $sourceRevision = Get-TicketboxRuntimeAlembicRevision `
        -HostAuthority $hostAuthority `
        -RuntimePassword $RuntimePassword
    $plan = Get-TicketboxInstalledManagedSchemaPlan `
        -ReleaseIdentity $ReleaseIdentity `
        -SourceRevision $sourceRevision
    if (
        [bool]$plan.upgrade_required -and
        [bool]$LifecycleReceipt.backup_required -and
        (
            -not [bool]$LifecycleReceipt.backup_completed -or
            -not (
                Test-Path `
                    -LiteralPath ([string]$LifecycleReceipt.backup_path) `
                    -PathType Leaf
            )
        )
    ) {
        throw "既有安装缺少已验证的升级前备份，拒绝执行 release schema migration。"
    }
    if (
        [bool]$plan.upgrade_required -and
        -not [bool]$LifecycleReceipt.backup_required -and
        $Mode -cne "fresh_install"
    ) {
        throw "非 fresh 安装没有升级前备份权威，拒绝执行 release schema migration。"
    }

    $migratorText = [string](New-StrongPassword)
    $migratorPassword = ConvertTo-TicketboxC07InstalledSecureString `
        -Value $migratorText `
        -Label "managed schema migrator password"
    $migratorText = ""
    $capturedHostAuthority = $hostAuthority
    $capturedReleaseIdentity = $ReleaseIdentity
    $capturedRuntimePassword = $RuntimePassword
    $capturedMigratorPassword = $migratorPassword
    $capturedPlan = $plan
    $capturedMode = $Mode
    $capturedOperationId = [string]$C07Authority.Receipt.operation_id
    $boundedAction = {
        param([Security.SecureString]$RecoveredSuperuserPassword)

        $liveRevision = Get-TicketboxC07InstalledAlembicRevision `
            -HostAuthority $capturedHostAuthority `
            -SuperuserPassword $RecoveredSuperuserPassword
        $migratorState = Get-TicketboxC07MigratorRetirementState `
            -Authority $capturedHostAuthority `
            -SuperuserPassword $RecoveredSuperuserPassword
        if ($liveRevision -ceq [string]$capturedPlan.target_revision) {
            if (-not $migratorState.IsActive -and -not $migratorState.IsRetired) {
                throw "release schema 已到 target，但 migrator 不是 retired terminal。"
            }
            if ($migratorState.IsActive) {
                Disable-TicketboxC07MigratorLogin `
                    -SuperuserPassword $RecoveredSuperuserPassword `
                    -OperationId $capturedOperationId `
                    -Mode $capturedMode
            }
            try {
                Enable-TicketboxC07MigratorForManagedSchemaUpgrade `
                    -SuperuserPassword $RecoveredSuperuserPassword `
                    -RuntimePassword $capturedRuntimePassword `
                    -MigratorPassword $capturedMigratorPassword `
                    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
                    -OperationId $capturedOperationId `
                    -Mode $capturedMode
                $upgradeResult = Invoke-TicketboxInstalledManagedSchemaUpgradeAction `
                    -ReleaseIdentity $capturedReleaseIdentity `
                    -HostAuthority $capturedHostAuthority `
                    -MigratorPassword $capturedMigratorPassword `
                    -Plan $capturedPlan
                Set-TicketboxManagedSchemaRuntimeAcl `
                    -Authority $capturedHostAuthority `
                    -SuperuserPassword $RecoveredSuperuserPassword
                return $upgradeResult
            }
            finally {
                $state = Get-TicketboxC07MigratorRetirementState `
                    -Authority $capturedHostAuthority `
                    -SuperuserPassword $RecoveredSuperuserPassword
                if ($state.IsActive) {
                    Disable-TicketboxC07MigratorLogin `
                        -SuperuserPassword $RecoveredSuperuserPassword `
                        -OperationId $capturedOperationId `
                        -Mode $capturedMode
                }
                elseif (-not $state.IsRetired) {
                    throw "release schema resume 留下 partial migrator authority。"
                }
            }
        }
        if ($liveRevision -cne [string]$capturedPlan.source_revision) {
            throw "live schema revision 不属于 frozen release migration path。"
        }
        if (-not $migratorState.IsRetired) {
            throw "release schema migration 前 migrator 不是 retired terminal。"
        }

        try {
            Enable-TicketboxC07MigratorForManagedSchemaUpgrade `
                -SuperuserPassword $RecoveredSuperuserPassword `
                -RuntimePassword $capturedRuntimePassword `
                -MigratorPassword $capturedMigratorPassword `
                -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(30)) `
                -OperationId $capturedOperationId `
                -Mode $capturedMode
            $upgradeResult = Invoke-TicketboxInstalledManagedSchemaUpgradeAction `
                -ReleaseIdentity $capturedReleaseIdentity `
                -HostAuthority $capturedHostAuthority `
                -MigratorPassword $capturedMigratorPassword `
                -Plan $capturedPlan
            Set-TicketboxManagedSchemaRuntimeAcl `
                -Authority $capturedHostAuthority `
                -SuperuserPassword $RecoveredSuperuserPassword
            return $upgradeResult
        }
        finally {
            $state = Get-TicketboxC07MigratorRetirementState `
                -Authority $capturedHostAuthority `
                -SuperuserPassword $RecoveredSuperuserPassword
            if ($state.IsActive) {
                Disable-TicketboxC07MigratorLogin `
                    -SuperuserPassword $RecoveredSuperuserPassword `
                    -OperationId $capturedOperationId `
                    -Mode $capturedMode
            }
            elseif (-not $state.IsRetired) {
                throw "release schema migration 留下 partial migrator authority。"
            }
        }
    }.GetNewClosure()

    try {
        $result = Invoke-TicketboxC07RecoveredSuperuserAction `
            -HostAuthority $hostAuthority `
            -RecoveryArtifactPath $RecoveryArtifactPath `
            -Action $boundedAction
    }
    finally {
        if ($null -ne $migratorPassword) {
            $migratorPassword.Dispose()
        }
    }
    if (
        [string]$result.alembic_revision -cne [string]$plan.target_revision -or
        [string]$result.revision_manifest_sha256 -cne
            [string]$plan.revision_manifest_sha256
    ) {
        throw "release schema migration 未返回 exact-head evidence。"
    }
    return $result
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
        [void](Read-PostgresBootstrapRecoveryState)
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
            [void](Read-PostgresBootstrapRecoveryState)
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
            [void](Read-PostgresBootstrapRecoveryState)
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
                [void](Read-PostgresBootstrapRecoveryState)
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
        [Parameter(Mandatory = $true)][object]$LifecycleReceipt,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][bool]$HadExistingPgService,
        [Parameter(Mandatory = $true)][bool]$HadExistingBackendService,
        [Parameter(Mandatory = $true)][ValidateRange(1, 99)][int]$ExpectedPgMajor,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )

    Assert-TicketboxInstallationIdentityBaseMatches $Identity $Candidate
    $releaseMatches = Test-TicketboxInstallationIdentityReleaseMatches `
        $Identity `
        $Candidate
    $receiptOperationId =
        [string]$LifecycleReceipt.c07_installation_operation_id
    if (
        $releaseMatches -and
        (
            [string]::IsNullOrEmpty($receiptOperationId) -or
            $receiptOperationId -ceq [string]$Identity.OperationId
        )
    ) {
        return [pscustomobject]@{
            Identity = $Identity
            RecoveryStage = "same_release"
            AllowReceiptOperationRebind = $false
            C07RecoveryState = "same_release"
            C07IntentRebound = $false
            C07PreviousPayloadSha256 = ""
            C07CurrentPayloadSha256 = ""
            C07PreviousReleaseFingerprint = ""
            C07CurrentReleaseFingerprint = ""
            C07ObservedIntentReleaseFingerprint = ""
        }
    }
    $parsedExpectedOperationId = [guid]::Empty
    if (
        -not [guid]::TryParseExact(
            $ExpectedOperationId,
            "D",
            [ref]$parsedExpectedOperationId
        ) -or
        $parsedExpectedOperationId -eq [guid]::Empty -or
        $parsedExpectedOperationId.ToString("D") -cne $ExpectedOperationId
    ) {
        throw "前数据库 PENDING 换包缺少当前安装器绑定的新 operation id。"
    }
    $canonicalOperationId = $parsedExpectedOperationId.ToString("D")
    if (
        -not $releaseMatches -and
        $canonicalOperationId -ceq [string]$Identity.OperationId
    ) {
        throw "前数据库 PENDING 换包缺少当前安装器绑定的新 operation id。"
    }
    if (-not [string]::IsNullOrEmpty($receiptOperationId)) {
        $parsedReceiptOperationId = [guid]::Empty
        if (
            -not [guid]::TryParseExact(
                $receiptOperationId,
                "D",
                [ref]$parsedReceiptOperationId
            ) -or
            $parsedReceiptOperationId -eq [guid]::Empty -or
            $parsedReceiptOperationId.ToString("D") -cne
                $receiptOperationId
        ) {
            throw "旧 PENDING installation receipt 的 operation id 不规范。"
        }
    }
    if (
        $Identity.State -cne "PENDING" -or
        [bool]$Identity.LegacyCompleted -or
        [string]$LifecycleReceipt.mode -cne "fresh_install" -or
        [string]$LifecycleReceipt.previous_pg_state -cne "absent" -or
        [string]$LifecycleReceipt.previous_backend_state -cne "absent" -or
        [string]$LifecycleReceipt.previous_pg_start_policy -cne "absent" -or
        [string]$LifecycleReceipt.previous_backend_start_policy -cne "absent" -or
        [string]$LifecycleReceipt.preparation_stage -cne
            "files_may_have_been_replaced" -or
        -not [bool]$LifecycleReceipt.files_may_have_been_replaced -or
        [bool]$LifecycleReceipt.backup_required -or
        [bool]$LifecycleReceipt.backup_completed -or
        -not [string]::IsNullOrEmpty([string]$LifecycleReceipt.backup_path) -or
        -not [string]::IsNullOrEmpty([string]$LifecycleReceipt.backup_sha256) -or
        [long]$LifecycleReceipt.backup_byte_length -ne 0 -or
        [bool]$LifecycleReceipt.install_completed -or
        [bool]$LifecycleReceipt.temporary_pg_service_cleanup_pending -or
        -not [string]::IsNullOrEmpty(
            [string]$LifecycleReceipt.c07_production_authority_sha256
        ) -or
        -not [string]::IsNullOrEmpty(
            [string]$LifecycleReceipt.c07_runtime_projection_sha256
        )
    ) {
        throw "旧 PENDING installation identity 不属于可证明的首次安装恢复事务。"
    }
    $readyPath = Get-TicketboxPersistentInstallationIdentityPath (
        [string]$Candidate.DataRoot
    )
    if (Test-Path -LiteralPath $readyPath) {
        throw "存在 READY installation identity，拒绝把旧 PENDING 当作首次安装残留。"
    }
    $envKind = Get-TicketboxPathEntryKindNoFollow $EnvPath
    if ($envKind -cne "Missing") {
        throw "旧 PENDING installation identity 已伴随运行配置。"
    }
    $bootstrapRecoveryPath = Get-PostgresBootstrapRecoveryPath
    $bootstrapRecoveryKind =
        Get-TicketboxPathEntryKindNoFollow $bootstrapRecoveryPath
    $initdbReceiptKind =
        Get-TicketboxPathEntryKindNoFollow $InitdbServiceReceiptPath
    $initdbPasswordKind =
        Get-TicketboxPathEntryKindNoFollow $InitdbPasswordPath
    $pgDataKind = Get-TicketboxPathEntryKindNoFollow $PgData
    $pgServiceExists = Service-Exists $PgServiceName
    $backendServiceExists = Service-Exists $BackendServiceName
    $recoveryStage = ""
    if (
        -not $HadExistingPgService -and
        -not $HadExistingBackendService -and
        -not $pgServiceExists -and
        -not $backendServiceExists -and
        $bootstrapRecoveryKind -ceq "Missing" -and
        $initdbReceiptKind -ceq "Missing" -and
        $initdbPasswordKind -ceq "Missing"
    ) {
        if ($pgDataKind -ceq "Directory") {
            Assert-NoTicketboxReparsePoints $PgData
            if (@(Get-ChildItem -LiteralPath $PgData -Force -ErrorAction Stop).Count -ne 0) {
                throw "旧 PENDING installation identity 的 pgdata 非空，拒绝前数据库换包。"
            }
        }
        elseif ($pgDataKind -cne "Missing") {
            throw "旧 PENDING installation identity 的 pgdata 形态不可恢复。"
        }
        $recoveryStage = "pre_database"
    }
    elseif (
        $HadExistingPgService -and
        $HadExistingBackendService -and
        $pgServiceExists -and
        $backendServiceExists -and
        $pgDataKind -ceq "Directory" -and
        $bootstrapRecoveryKind -ceq "File" -and
        $initdbReceiptKind -ceq "Missing" -and
        $initdbPasswordKind -ceq "Missing"
    ) {
        Assert-NoTicketboxReparsePoints $PgData
        $pgVersionPath = Join-Path $PgData "PG_VERSION"
        $pgControlPath = Join-Path $PgData "global\pg_control"
        if (
            (Get-TicketboxPathEntryKindNoFollow $pgVersionPath) -cne "File" -or
            (Get-TicketboxPathEntryKindNoFollow $pgControlPath) -cne "File" -or
            (Get-TicketboxPathEntryKindNoFollow (Join-Path $PgData "postmaster.pid")) -cne
                "Missing"
        ) {
            throw "旧 PENDING installation identity 的 PostgreSQL 簇未处于完整停止态。"
        }
        $versionItem = Get-Item -LiteralPath $pgVersionPath -Force -ErrorAction Stop
        if ($versionItem.Length -le 0 -or $versionItem.Length -gt 16) {
            throw "旧 PENDING installation identity 的 PG_VERSION 文件不安全。"
        }
        $versionText = [System.IO.File]::ReadAllText(
            $pgVersionPath,
            [System.Text.Encoding]::UTF8
        ).Trim()
        $actualPgMajor = 0
        if (
            -not [int]::TryParse($versionText, [ref]$actualPgMajor) -or
            $actualPgMajor -ne $ExpectedPgMajor
        ) {
            throw "旧 PENDING installation identity 的 PostgreSQL major 与当前安装包不兼容。"
        }
        foreach ($serviceName in @($PgServiceName, $BackendServiceName)) {
            if (
                (Get-TicketboxServiceState $serviceName) -cne "stopped" -or
                (Get-TicketboxServiceStartMode $serviceName) -cne "Disabled"
            ) {
                throw "旧 PENDING installation identity 的服务未保持停止和禁用。"
            }
        }
        Wait-TicketboxBackendRuntimeStopped `
            -Name $PgServiceName `
            -BackendPort $PgPort `
            -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
            @ServiceWaitArguments
        Wait-TicketboxBackendRuntimeStopped `
            -Name $BackendServiceName `
            -BackendPort $BackendPort `
            -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
            @ServiceWaitArguments
        [void](Read-PostgresBootstrapRecoveryState)
        $recoveryStage = "post_initdb_pre_schema"
    }
    else {
        throw "旧 PENDING installation identity 的数据库、服务和 bootstrap 状态不构成可证明的续装边界。"
    }
    $c07Recovery =
        Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
            -Candidate $Candidate `
            -PreviousInstallationIdentity $Identity `
            -LifecycleLock $LifecycleLock
    $targetOperationId = $canonicalOperationId
    if ([bool]$c07Recovery.PreserveOperationId) {
        if (
            [string]::IsNullOrEmpty($receiptOperationId) -or
            $receiptOperationId -cne [string]$Identity.OperationId -or
            [string]$c07Recovery.OperationId -cne
                [string]$Identity.OperationId
        ) {
            throw "C07 fresh bootstrap 续接未绑定旧 installation receipt/identity。"
        }
        $targetOperationId = [string]$c07Recovery.OperationId
    }
    if ($targetOperationId -ceq [string]$Identity.OperationId -and $releaseMatches) {
        return [pscustomobject]@{
            Identity = $Identity
            RecoveryStage = $recoveryStage
            AllowReceiptOperationRebind = (
                -not [string]::IsNullOrEmpty($receiptOperationId) -and
                $receiptOperationId -cne $targetOperationId
            )
            C07RecoveryState = [string]$c07Recovery.State
            C07IntentRebound = [bool]$c07Recovery.Rebound
            C07PreviousPayloadSha256 =
                [string]$c07Recovery.PreviousPayloadSha256
            C07CurrentPayloadSha256 =
                [string]$c07Recovery.CurrentPayloadSha256
            C07PreviousReleaseFingerprint =
                [string]$c07Recovery.PreviousReleaseFingerprint
            C07CurrentReleaseFingerprint =
                [string]$c07Recovery.CurrentReleaseFingerprint
            C07ObservedIntentReleaseFingerprint =
                [string]$c07Recovery.ObservedIntentReleaseFingerprint
        }
    }

    $rebased = Write-TicketboxInstallationIdentityState `
        -State "PENDING" `
        -OperationId $targetOperationId `
        -InstallationId ([string]$Identity.InstallationId) `
        -Candidate $Candidate `
        -ReplaceExisting
    if (
        $rebased.State -cne "PENDING" -or
        $rebased.InstallationId -cne [string]$Identity.InstallationId -or
        $rebased.OperationId -cne $targetOperationId -or
        -not (
            Test-TicketboxInstallationIdentityReleaseMatches `
                $rebased `
                $Candidate
        )
    ) {
        throw "首次安装 PENDING installation identity 恢复换包后未收敛。"
    }
    return [pscustomobject]@{
        Identity = $rebased
        RecoveryStage = $recoveryStage
        AllowReceiptOperationRebind = (
            -not [string]::IsNullOrEmpty($receiptOperationId) -and
            $receiptOperationId -cne $targetOperationId
        )
        C07RecoveryState = [string]$c07Recovery.State
        C07IntentRebound = [bool]$c07Recovery.Rebound
        C07PreviousPayloadSha256 =
            [string]$c07Recovery.PreviousPayloadSha256
        C07CurrentPayloadSha256 =
            [string]$c07Recovery.CurrentPayloadSha256
        C07PreviousReleaseFingerprint =
            [string]$c07Recovery.PreviousReleaseFingerprint
        C07CurrentReleaseFingerprint =
            [string]$c07Recovery.CurrentReleaseFingerprint
        C07ObservedIntentReleaseFingerprint =
            [string]$c07Recovery.ObservedIntentReleaseFingerprint
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
$receiptInstallationId = "not-yet-assigned"
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

    $installLifecycleStage = "installation_identity"
    $c07SuccessorResolution = $null
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
                    [string]$lifecycleReceipt.c07_installation_operation_id
                )
        }
        $c07PendingIdentityResolution =
            Resolve-TicketboxRecoverableFreshInstallPendingIdentity `
                -Candidate $c07InstallationReleaseCandidate `
                -Identity $c07InstallationIdentity `
                -LifecycleReceipt $lifecycleReceipt `
                -ExpectedOperationId $LifecycleFinalizationAttemptId `
                -HadExistingPgService $hadExistingPgService `
                -HadExistingBackendService $hadExistingBackendService `
                -ExpectedPgMajor $TargetPgMajor `
                -LifecycleLock $operationLock
        $c07InstallationIdentity = $c07PendingIdentityResolution.Identity
        if (
            [string]$c07PendingIdentityResolution.C07RecoveryState -cin @(
                "fresh_intent_rebound",
                "fresh_intent_current"
            )
        ) {
            Write-Warn2 (
                "已验证并续接未提交的 C07 fresh bootstrap transaction；" +
                "state=$($c07PendingIdentityResolution.C07RecoveryState)；" +
                "operation_id=$($c07InstallationIdentity.OperationId)；" +
                "previous_release_fingerprint=" +
                "$($c07PendingIdentityResolution.C07PreviousReleaseFingerprint)；" +
                "current_release_fingerprint=" +
                "$($c07PendingIdentityResolution.C07CurrentReleaseFingerprint)；" +
                "observed_intent_release_fingerprint=" +
                "$($c07PendingIdentityResolution.C07ObservedIntentReleaseFingerprint)；" +
                "previous_payload_sha256=" +
                "$($c07PendingIdentityResolution.C07PreviousPayloadSha256)；" +
                "current_payload_sha256=" +
                "$($c07PendingIdentityResolution.C07CurrentPayloadSha256)；" +
                "保留 operation id 与临时凭据并原地收敛 release binding。"
            )
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
        Set-TicketboxLifecycleReceiptC07InstallationOperation `
            -Path $LifecycleReceiptPath `
            -Receipt $lifecycleReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -OperationId $c07InstallationIdentity.OperationId `
            -AllowFreshInstallRecoveryRebind:$(
                [bool]$c07PendingIdentityResolution.AllowReceiptOperationRebind
            )
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
            [string]$lifecycleReceipt.c07_installation_operation_id -cne
                [string]$c07InstallationIdentity.OperationId
        ) {
            throw "安装事务未原子绑定 C07 PENDING installation operation。"
        }
    }
    $c07ReleaseIdentity = if (
        $c07InstallationIdentity.State -ceq "PENDING"
    ) {
        Get-TicketboxC07ReleaseIdentity `
            -DataRoot $DataRoot `
            -ExpectedInstallationOperationId (
                [string]$c07InstallationIdentity.OperationId
            )
    }
    else {
        Get-TicketboxC07ReleaseIdentity -DataRoot $DataRoot
    }
    if (
        $c07ReleaseIdentity.InstallationId -cne
            $c07InstallationIdentity.InstallationId -or
        $c07ReleaseIdentity.BuildManifestSha256 -cne
            $c07InstallationIdentity.BuildManifestSha256 -or
        (
            -not [bool]$c07InstallationIdentity.LegacyCompleted -and
            (
                $c07ReleaseIdentity.MigrationHelperSha256 -cne
                    $c07InstallationIdentity.MigrationHelperSha256 -or
                $c07ReleaseIdentity.InstallationIdentityState -cne
                    $c07InstallationIdentity.State -or
                $c07ReleaseIdentity.InstallationOperationId -cne
                    $c07InstallationIdentity.OperationId
            )
        )
    ) {
        throw "C07 PENDING installation identity 原子复读后发生 release/helper 漂移。"
    }
    $installLifecycleStage = "database_cluster"
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
    $c07SuccessorResolution =
        Initialize-TicketboxC07SuccessorInstallationIdentity `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -PgServiceName $PgServiceName `
            -BackendServiceName $BackendServiceName `
            -BuildManifestPath $InstalledBuildManifestPath `
            -LifecycleLock $operationLock
    if (
        $null -eq $c07SuccessorResolution -and
        [string]$lifecycleReceipt.c07_installation_operation_id -cne
            [string]$c07InstallationIdentity.OperationId
    ) {
        $publishedSuccessor = Read-TicketboxC07Authority $DataRoot `
            -ExpectedInstallationOperationId (
                [string]$c07InstallationIdentity.OperationId
            )
        if ([string]::IsNullOrEmpty(
            [string]$publishedSuccessor.Descriptor.Payload.successor_mode
        )) {
            throw "安装事务与 PENDING C07 operation 漂移且不存在 successor intent。"
        }
        $publishedIntent = Read-TicketboxC07SuccessorIntent `
            -OperationId ([string]$c07InstallationIdentity.OperationId) `
            -SuccessorReleaseIdentity $publishedSuccessor.ReleaseIdentity
        $c07SuccessorResolution = [pscustomobject]@{
            Identity = $c07InstallationIdentity
            Intent = $publishedIntent
            ReleaseIdentity = $publishedSuccessor.ReleaseIdentity
            Mode = [string]$publishedIntent.Payload.successor_mode
        }
    }
    if ($null -ne $c07SuccessorResolution) {
        $c07InstallationIdentity = $c07SuccessorResolution.Identity
        Set-TicketboxLifecycleReceiptC07InstallationOperation `
            -Path $LifecycleReceiptPath `
            -Receipt $lifecycleReceipt `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -OperationId $c07InstallationIdentity.OperationId `
            -SuccessorIntent $c07SuccessorResolution.Intent
        $lifecycleReceipt = Read-TicketboxLifecycleReceipt `
            -Path $LifecycleReceiptPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot `
            -PgPort $PgPort `
            -BackendPort $BackendPort `
            -TargetReleaseConfig $ReleaseConfig `
            -CurrentTargetBackendVersion $TargetBackendVersion `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId
        $c07ReleaseIdentity = Get-TicketboxC07ReleaseIdentity `
            -DataRoot $DataRoot `
            -ExpectedInstallationOperationId (
                [string]$c07InstallationIdentity.OperationId
            )
    }
    $c07Disposition = Get-TicketboxC07InstallerDatabaseDisposition
    $c07RecoveryArtifactPath = Join-Path `
        $InstallerState `
        $script:TicketboxC07SuperuserRecoveryArtifactName
    $c07Mode = ""
    $c07ReadyProductionAuthoritySha256 = ""
    $c07ReadyRuntimeProjectionSha256 = ""
    $runtimePassword = $null
    if ($c07Disposition -ceq "runtime_ready") {
        Complete-TicketboxC07RecoveredSuperuserResidue `
            -RecoveryArtifactPath $c07RecoveryArtifactPath
        $c07Authority = Read-TicketboxC07Authority $DataRoot
        if ([string]$c07Authority.Receipt.stage -cne "ready") {
            throw "runtime DATABASE_URL 已发布，但 C07 durable authority 不是 READY。"
        }
        $c07Production = Read-TicketboxC07ProductionAuthority $c07Authority
        $c07Mode = [string]$c07Production.Payload.mode
        if ($c07Mode -cnotin @("fresh_install", "legacy_adoption")) {
            throw "C07 production authority 含有未知安装模式。"
        }
        $c07Projection = Read-TicketboxC07RuntimeProjection $DataRoot
        $c07ReadyProductionAuthoritySha256 =
            [string]$c07Production.PayloadSha256
        $c07ReadyRuntimeProjectionSha256 =
            [string]$c07Projection.PayloadSha256
        $runtimeEnvironment = Read-EnvMap $EnvPath
        $runtimeConnection = Get-TicketboxLocalDatabaseConnection `
            -DatabaseUrl ([string]$runtimeEnvironment["DATABASE_URL"]) `
            -PgPort $PgPort `
            -ExpectedDatabase $script:TicketboxC07DatabaseName `
            -ExpectedRole $script:TicketboxC07RuntimeRole
        $runtimePassword = ConvertTo-TicketboxC07InstalledSecureString `
            -Value ([string]$runtimeConnection.Password) `
            -Label "persisted runtime password"
        Assert-TicketboxConnectedPostgresDataRoot `
            -PsqlPath $Psql `
            -DatabaseUrl $runtimeConnection.DatabaseUrl `
            -ExpectedDataRoot $PgData `
            -ExpectedPort $PgPort `
            -Password $runtimeConnection.Password `
            -TimeoutMilliseconds $DatabaseToolTimeoutMs
        Assert-TicketboxC07RuntimeCredential `
            -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
            -RuntimePassword $runtimePassword
        $databaseUrl = [string]$runtimeConnection.PersistedDatabaseUrl
        Complete-TicketboxC07InstalledSecretCleanup `
            -Mode $c07Mode `
            -LifecycleLock $operationLock `
            -RecoveryArtifactPath $c07RecoveryArtifactPath
    }
    else {
        $freshIntent = $null
        if ($c07Disposition -ceq "fresh_install") {
            $freshIntent = Get-OrCreateTicketboxC07FreshBootstrapIntent `
                -DataRoot $DataRoot `
                -LifecycleLock $operationLock `
                -ExpectedOperationId (
                    [string]$c07ReleaseIdentity.InstallationOperationId
                )
        }
        elseif (-not (Test-Path -LiteralPath (Get-TicketboxC07AuthorityPath))) {
            [void](Prepare-DatabaseIfNeeded -PreserveBootstrapRecovery)
        }
        $c07Migration = Invoke-TicketboxC07InstalledReleaseMigration `
            -ReleaseIdentity $c07ReleaseIdentity `
            -Mode $c07Disposition `
            -LifecycleLock $operationLock `
            -FreshIntent $freshIntent `
            -SuccessorIntent $(if ($null -eq $c07SuccessorResolution) {
                $null
            } else { $c07SuccessorResolution.Intent }) `
            -RecoveryArtifactPath $c07RecoveryArtifactPath
        $c07Mode = [string]$c07Migration.mode
        $c07ReadyProductionAuthoritySha256 =
            [string]$c07Migration.production_authority_sha256
        $c07ReadyRuntimeProjectionSha256 =
            [string]$c07Migration.runtime_projection_sha256
        $runtimePassword = $c07Migration.runtime_password
        $databaseUrl = Write-TicketboxC07InstalledRuntimeEnvironment `
            -RuntimePassword $runtimePassword
        Complete-TicketboxC07InstalledSecretCleanup `
            -Mode $c07Mode `
            -LifecycleLock $operationLock `
            -RecoveryArtifactPath $c07RecoveryArtifactPath
    }
    $installLifecycleStage = "schema_migration"
    Write-Step "收敛 release schema 到 frozen head"
    $c07Authority = Read-TicketboxC07Authority $DataRoot
    $managedSchemaResult = Invoke-TicketboxInstalledManagedSchemaUpgrade `
        -ReleaseIdentity $c07ReleaseIdentity `
        -C07Authority $c07Authority `
        -RuntimePassword $runtimePassword `
        -LifecycleReceipt $lifecycleReceipt `
        -RecoveryArtifactPath $c07RecoveryArtifactPath `
        -Mode $c07Mode
    Write-Ok (
        "release schema exact head: " +
        [string]$managedSchemaResult.alembic_revision
    )
    Set-TicketboxLifecycleReceiptC07ReadyEvidence `
        -Path $LifecycleReceiptPath `
        -Receipt $lifecycleReceipt `
        -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
        -OperationId ([string]$c07InstallationIdentity.OperationId) `
        -ProductionAuthoritySha256 $c07ReadyProductionAuthoritySha256 `
        -RuntimeProjectionSha256 $c07ReadyRuntimeProjectionSha256
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
        [string]$lifecycleReceipt.c07_production_authority_sha256 -cne
            $c07ReadyProductionAuthoritySha256 -or
        [string]$lifecycleReceipt.c07_runtime_projection_sha256 -cne
            $c07ReadyRuntimeProjectionSha256
    ) {
        throw "安装事务未持久绑定 exact C07 READY authority/projection。"
    }
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
            -InstallationId $receiptInstallationId `
            -LifecycleStage $installLifecycleStage `
            -ProtectedLogPath $resolvedDiagnosticLogPath `
            -Failure $failure `
            -MutationStarted $mutationStarted
    }
    catch {
        Write-Warning (
            "无法发布公开安装失败回执；保留受保护原始日志。" +
            $_.Exception.Message
        )
    }
    try {
        Write-TicketboxInstallC07FailureSummaryIfPresent `
            -DataRoot $DataRoot `
            -InstallerState $InstallerState `
            -LifecycleLock $operationLock `
            -FinalizationAttemptId $LifecycleFinalizationAttemptId `
            -Failure $failure
    }
    catch {
        $failure = New-TicketboxInstallFailureSummaryAggregateFailure `
            -InstallFailure $failure `
            -SummaryFailure $_.Exception
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
        $blockedProjectionFailure =
            New-TicketboxInstallFinalizationAggregateFailure `
                -OperationFailure $operationFailure `
                -FinalizationFailures @($finalizationFailure)
        try {
            Write-TicketboxInstallC07FailureSummaryIfPresent `
                -DataRoot $DataRoot `
                -InstallerState $InstallerState `
                -LifecycleLock $operationLock `
                -FinalizationAttemptId $LifecycleFinalizationAttemptId `
                -Failure $blockedProjectionFailure
        }
        catch {
            $summaryFinalizationFailure = $_.Exception
            $summaryFinalizationFailure.Data["TicketboxInstallFinalizationStep"] =
                "blocked_failure_summary_publish"
            $finalizationFailures += $summaryFinalizationFailure
        }
    }
    # Persist the fail-closed veto before any lifecycle-lock release attempt.
    # Missing, malformed, pending, or operation-mismatched veto state prevents
    # Inno from acting on an older retryable summary.
    try {
        $lifecycleExitVetoProjection =
            New-TicketboxInstallC07LifecycleExitVetoIfPresent `
                -DataRoot $DataRoot `
                -InstallerState $InstallerState `
                -LifecycleLock $operationLock `
                -FinalizationAttemptId $LifecycleFinalizationAttemptId
    }
    catch {
        $lifecycleExitVetoPreparationFailure = $_.Exception
        $lifecycleExitVetoPreparationFailure.Data[
            "TicketboxInstallFinalizationStep"
        ] = "lifecycle_exit_veto_prepare"
        $finalizationFailures += $lifecycleExitVetoPreparationFailure
    }
    try {
        $lifecycleExitFailureProjection =
            New-TicketboxInstallC07LifecycleExitFailureProjectionIfPresent `
                -DataRoot $DataRoot `
                -InstallerState $InstallerState `
                -LifecycleLock $operationLock `
                -FinalizationAttemptId $LifecycleFinalizationAttemptId
    }
    catch {
        $lifecycleExitProjectionPreparationFailure = $_.Exception
    }
    $lifecycleLockExitFailed = $false
    try {
        Exit-TicketboxLifecycleLock $operationLock
    }
    catch {
        $lifecycleLockExitFailed = $true
        $finalizationFailure = $_.Exception
        $finalizationFailure.Data["TicketboxInstallFinalizationStep"] =
            "lifecycle_lock_exit"
        $finalizationFailure.Data["TicketboxC07FailureCode"] =
            "lifecycle_lock_exit_failed"
        $finalizationFailures += $finalizationFailure
        if ($null -ne $lifecycleExitFailureProjection) {
            try {
                Publish-TicketboxC07InstallerLifecycleExitFailureProjection `
                    $lifecycleExitFailureProjection | Out-Null
            }
            catch {
                $summaryFinalizationFailure = $_.Exception
                $summaryFinalizationFailure.Data[
                    "TicketboxInstallFinalizationStep"
                ] = "lifecycle_exit_blocked_summary_publish"
                $finalizationFailures += $summaryFinalizationFailure
            }
        }
        elseif ($null -ne $lifecycleExitProjectionPreparationFailure) {
            $lifecycleExitProjectionPreparationFailure.Data[
                "TicketboxInstallFinalizationStep"
            ] = "lifecycle_exit_blocked_summary_prepare"
            $finalizationFailures +=
                $lifecycleExitProjectionPreparationFailure
        }
    }
    if (-not $lifecycleLockExitFailed) {
        # A successful lock release is necessary but not sufficient to publish
        # retry authorization.  Any earlier finalization failure may have left
        # an older retryable summary in place, so retain pending veto state.
        $failureSummaryPublicationFailed =
            $null -ne $operationFailure -and
            $operationFailure.Data.Contains(
                "TicketboxC07FailureSummaryFailed"
            )
        if (
            $finalizationFailures.Count -eq 0 -and
            -not $failureSummaryPublicationFailed -and
            $null -ne $lifecycleExitVetoProjection
        ) {
            try {
                Complete-TicketboxC07InstallerLifecycleExitVeto `
                    $lifecycleExitVetoProjection | Out-Null
            }
            catch {
                $vetoCompletionFailure = $_.Exception
                $vetoCompletionFailure.Data[
                    "TicketboxInstallFinalizationStep"
                ] = "lifecycle_exit_veto_complete"
                $finalizationFailures += $vetoCompletionFailure
            }
        }
        Remove-TicketboxC07InstallerLifecycleExitFailureProjection `
            $lifecycleExitFailureProjection
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
