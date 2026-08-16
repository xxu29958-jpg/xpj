#Requires -Version 5.1
<#
.SYNOPSIS
  Stop and unregister Ticketbox bundled Windows services.

.DESCRIPTION
  Inno calls this during uninstall. By default it preserves ProgramData so
  uninstall/reinstall is reversible. Passing -DeleteData explicitly removes the
  configured data root after verifying the target path is safe.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$DataRoot = "",
    [string]$ReleaseConfigPath = "",
    [int]$InstallerLockOwnerProcessId = 0,
    [switch]$DeleteData
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
$UninstallInstalledReleaseConfig = $ReleaseConfig
$UninstallLifecycleReceipt = $null
$PgServiceName = [string]$ReleaseConfig.pg_service_name
$BackendServiceName = [string]$ReleaseConfig.backend_service_name
$OwnerRecoveryChannel = [string]$ReleaseConfig.owner_recovery_channel
$StopTimeoutMs = [int]$ReleaseConfig.stop_timeout_ms
$RestartDelayMs = [int]$ReleaseConfig.restart_delay_ms
$DatabaseToolTimeoutMs = [int]$ReleaseConfig.database_tool_timeout_ms
$ServiceWaitArguments = @{
    TimeoutMilliseconds = [int]$ReleaseConfig.service_state_timeout_ms
    PollMilliseconds = [int]$ReleaseConfig.service_poll_interval_ms
}
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
$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"
if (-not (Test-Path -LiteralPath $DatabaseSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 数据库安全脚本：$DatabaseSafetyScript"
}
. $DatabaseSafetyScript
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
if (-not (Test-Path -LiteralPath $LockScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期锁脚本：$LockScript"
}
. $LockScript
$DatabaseGenerationContractScript = Join-Path `
    $ScriptDir `
    "windows_database_generation_contract.ps1"
if (-not (Test-Path -LiteralPath $DatabaseGenerationContractScript -PathType Leaf)) {
    throw "缺少 database generation contract：$DatabaseGenerationContractScript"
}
. $DatabaseGenerationContractScript
$ReceiptScript = Join-Path $ScriptDir "windows_lifecycle_receipt.ps1"
if (-not (Test-Path -LiteralPath $ReceiptScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期回执脚本：$ReceiptScript"
}
. $ReceiptScript
$DatabaseGenerationAuthorityScript = Join-Path `
    $ScriptDir `
    "windows_database_generation.ps1"
if ((Get-TicketboxPathEntryKindNoFollow $DatabaseGenerationAuthorityScript) -cne "File") {
    throw "缺少可信 database generation authority：$DatabaseGenerationAuthorityScript"
}
Assert-NoTicketboxAncestorReparsePoints $DatabaseGenerationAuthorityScript
. $DatabaseGenerationAuthorityScript
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
$BackendBootstrapScript = Join-Path $ScriptDir "windows_backend_bootstrap.ps1"
if (-not (Test-Path -LiteralPath $BackendBootstrapScript -PathType Leaf)) {
    throw "缺少 Windows owner handoff 脚本：$BackendBootstrapScript"
}
. $BackendBootstrapScript

$regPath = "HKLM:\Software\Ticketbox"
$ExplicitDataRootProvided = -not [string]::IsNullOrWhiteSpace($DataRoot)
$PreservedIdentityNames = @(
    "InstallDir",
    "BackendPort",
    "PgPort",
    "BackendServiceName",
    "PgServiceName",
    "DataRoot"
)
$RegisteredInstallDir = ""
$RegisteredDataRoot = ""
$RegisteredBackendPort = ""
$RegisteredPgPort = ""
$RegisteredBackendServiceName = ""
$RegisteredPgServiceName = ""
$RegisteredIdentityValueNames = @()
if (Test-Path -LiteralPath $regPath) {
    $registeredValues = @{}
    foreach ($name in $PreservedIdentityNames) {
        $existing = Get-ItemProperty -LiteralPath $regPath -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $existing -and $null -ne $existing.PSObject.Properties[$name]) {
            $RegisteredIdentityValueNames += $name
            $registeredValues[$name] = [string]$existing.PSObject.Properties[$name].Value
        }
    }
    $RegisteredInstallDir = [string]$registeredValues["InstallDir"]
    $RegisteredDataRoot = [string]$registeredValues["DataRoot"]
    $RegisteredBackendPort = [string]$registeredValues["BackendPort"]
    $RegisteredPgPort = [string]$registeredValues["PgPort"]
    $RegisteredBackendServiceName = [string]$registeredValues["BackendServiceName"]
    $RegisteredPgServiceName = [string]$registeredValues["PgServiceName"]
}
if ($DataRoot.Trim().Length -eq 0 -and $RegisteredDataRoot.Length -gt 0) {
    $DataRoot = $RegisteredDataRoot
}
$InstallationIdentityAlreadyRemoved = (
    $RegisteredIdentityValueNames.Count -eq 0
)
$InstallationIdentityCleanupIncomplete = (
    $RegisteredIdentityValueNames.Count -gt 0 -and
    $RegisteredIdentityValueNames.Count -ne $PreservedIdentityNames.Count
)
if (
    ($InstallationIdentityAlreadyRemoved -or $InstallationIdentityCleanupIncomplete) -and
    [string]::IsNullOrWhiteSpace($DataRoot)
) {
    # The main block exits before any path mutation. A concrete placeholder only
    # lets the shared helper functions be declared for an idempotent retry.
    $DataRoot = $InstallDir
}

$PgBin = Join-Path $InstallDir "pg\bin"
$InstallerState = Get-TicketboxInstallerStateDirectory
$OwnerHandoffPath = Join-Path $InstallerState "installation-owner-handoff-v2.txt"
$RetiredOwnerBootstrapPath = Join-Path $InstallerState "owner-bootstrap.txt"
$RetiredOwnerHandoffPendingPath = Join-Path $InstallerState "owner-handoff-pending"
$RecoveryRequiredPath = Join-Path $InstallerState "installer-recovery-required.json"
$DeleteDataIntentPath = Join-Path $InstallerState "delete-data-in-progress.json"
$script:DeleteDataIntentValidated = $false
$script:AbortedFreshInstallLifecycleReceipt = $null
$BackendExe = Join-Path $InstallDir "program\ticketbox-backend\ticketbox-backend.exe"
$ShawlExe = Join-Path $InstallDir "shawl\shawl.exe"
$PgCtl = Join-Path $PgBin "pg_ctl.exe"
$InitdbExe = Join-Path $PgBin "initdb.exe"
$InstalledBuildManifestPath = Join-Path $ScriptDir "BUILD_PROVENANCE.json"
$LifecycleReceiptPath = Get-TicketboxLifecycleReceiptPath
$InitdbServiceReceiptPath = Get-TicketboxInitdbServiceReceiptPath
$TargetPgMajor = ([Version][string]$ReleaseConfig.postgres_version_policy.minimum).Major

function Set-TicketboxUninstallDataRoot([string]$ResolvedDataRoot) {
    $script:DataRoot = ConvertTo-TicketboxCanonicalPath $ResolvedDataRoot
    $script:PgData = Join-Path $script:DataRoot "pgdata"
    $script:AppData = Join-Path $script:DataRoot "app"
    $script:InitdbPasswordPath = Get-TicketboxInitdbPasswordPath $script:DataRoot
    $script:PgBootstrapRecoveryPath = Join-Path `
        $script:AppData `
        ".postgres-bootstrap-password"
    $script:LogDir = Join-Path $script:AppData "logs"
    $script:BootstrapExposureRecoveryGuardPath = Join-Path `
        $script:DataRoot `
        "bootstrap-exposure-recovery-pending"
    $script:ServiceBootstrapExposureRecoveryGuardPath =
        $script:BootstrapExposureRecoveryGuardPath
    $script:InstallerRuntimeRecoveryGuardPath =
        Get-TicketboxInstallerRuntimeRecoveryGuardPath
}

Set-TicketboxUninstallDataRoot $DataRoot
$RuntimeDataBindingServiceAccounts = @(
    (Get-TicketboxServiceSid $PgServiceName),
    (Get-TicketboxServiceSid $BackendServiceName)
)
$RuntimeDataBindingPresent = $false
$ServicePgData = $PgData
$ServiceAppData = $AppData
$ServiceLogDir = $LogDir
$ServiceDataRootMarkerPath = Join-Path `
    (Get-TicketboxRuntimeDataRootPath) `
    $script:TicketboxDataRootMarkerName
$ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
$ServiceDataVolumeIdentity = ""
$AllowMissingRuntimeDataAuthority = $true

function Set-TicketboxUninstallRuntimeServiceContract {
    $bindingDirectory = Get-TicketboxRuntimeDataBindingDirectory
    $bindingKind = Get-TicketboxPathEntryKindNoFollow $bindingDirectory
    if ($bindingKind -ceq "Missing") {
        $script:RuntimeDataBindingPresent = $false
        $script:ServicePgData = $PgData
        $script:ServiceAppData = $AppData
        $script:ServiceLogDir = $LogDir
        $script:ServiceBootstrapExposureRecoveryGuardPath = $BootstrapExposureRecoveryGuardPath
        $script:ServiceDataVolumeIdentity = ""
        $script:AllowMissingRuntimeDataAuthority = $true
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
            throw "runtime DataRoot binding 退役断点含有未知 artifact。"
        }
        if ((Service-Exists $BackendServiceName) -or (Service-Exists $PgServiceName)) {
            throw "runtime DataRoot junction 已缺失但 Ticketbox 服务仍存在；拒绝继续卸载。"
        }
        $script:RuntimeDataBindingPresent = $true
        return
    }
    $binding = Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $RuntimeDataBindingServiceAccounts `
        -DataRootMarkerAclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName
    $script:RuntimeDataBindingPresent = $true
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
}

function Remove-TicketboxUninstallRuntimeDataBindingIfPresent {
    if (-not $RuntimeDataBindingPresent) { return }
    Remove-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $RuntimeDataBindingServiceAccounts `
        -DataRootMarkerAclPhase backend_read_optional `
        -ExpectedBackendServiceName $BackendServiceName
    $script:RuntimeDataBindingPresent = $false
}
$BackendPort = 0
if (-not [string]::IsNullOrWhiteSpace($RegisteredBackendPort)) {
    $parsedBackendPort = 0
    if (
        -not [int]::TryParse($RegisteredBackendPort, [ref]$parsedBackendPort) -or
        $parsedBackendPort -lt 1 -or
        $parsedBackendPort -gt 65535
    ) {
        throw "安装器登记的 BackendPort 无效，拒绝在无法证明后端进程退出时卸载。"
    }
    $BackendPort = $parsedBackendPort
}
elseif (Test-Path -LiteralPath (Join-Path $AppData ".env") -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath (Join-Path $AppData ".env") -Encoding UTF8) {
        if ($line -match '^TICKETBOX_PORT=(\d+)$') {
            $BackendPort = [int]$Matches[1]
            break
        }
    }
}

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
        throw "需要管理员权限运行卸载脚本。"
    }
}

function Service-Exists([string]$Name) {
    return Test-TicketboxServiceExists $Name
}

function Assert-TicketboxUninstallServiceIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$AllowTargetSidTypePending
    )

    $receiptAuthorizesPending =
        $null -ne $UninstallLifecycleReceipt -and
        (Test-TicketboxLifecycleReceiptAuthorizesServiceSidPending `
            -Receipt $UninstallLifecycleReceipt `
            -ServiceName $Name)
    return Assert-TicketboxReleaseServiceIdentity `
        -Name $Name `
        -InstalledConfig $UninstallInstalledReleaseConfig `
        -TargetConfig $ReleaseConfig `
        -AllowTargetSidTypePending:($AllowTargetSidTypePending -or $receiptAuthorizesPending)
}

function Invoke-ScChecked([string[]]$ScArgs) {
    return Invoke-TicketboxScChecked $ScArgs
}

function Get-ExpectedServiceExecutable([string]$Name) {
    if ($Name -eq $PgServiceName) {
        return $PgCtl
    }
    if ($Name -eq $BackendServiceName) {
        return $ShawlExe
    }
    throw "未知 Ticketbox 服务：$Name"
}

function Assert-ExpectedServiceConfiguration([string]$Name) {
    if (-not (Service-Exists $Name)) {
        return
    }
    Assert-TicketboxServiceOwnership -Name $Name -ExpectedExecutable (Get-ExpectedServiceExecutable $Name) | Out-Null
    Assert-TicketboxUninstallServiceIdentity -Name $Name | Out-Null
    if ($Name -eq $PgServiceName) {
        Assert-TicketboxPgServiceCommand `
            -Name $Name `
            -ExpectedExecutable $PgCtl `
            -ExpectedServiceName $PgServiceName `
            -ExpectedDataRoot $ServicePgData
        return
    }
    Assert-TicketboxShawlServiceCommand `
        -Name $Name `
        -ExpectedExecutable $ShawlExe `
        -ExpectedServiceName $BackendServiceName `
        -ExpectedCwd $ServiceAppData `
        -ExpectedPayload $BackendExe `
        -ExpectedDependency $PgServiceName `
        -ExpectedLogDir $ServiceLogDir `
        -ExpectedPgDumpPath (Join-Path $PgBin "pg_dump.exe") `
        -ExpectedPgRestorePath (Join-Path $PgBin "pg_restore.exe") `
        -ExpectedBootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath `
        -ExpectedInstallerRecoveryGuardPath $InstallerRuntimeRecoveryGuardPath `
        -ExpectedDataRootMarkerPath $ServiceDataRootMarkerPath `
        -ExpectedDataVolumeIdentity $ServiceDataVolumeIdentity `
        -ExpectedOwnerRecoveryChannel $OwnerRecoveryChannel `
        -ExpectedStopTimeoutMs $StopTimeoutMs `
        -ExpectedRestartDelayMs $RestartDelayMs `
        -AllowMissingInstallerRecoveryGuard `
        -AllowMissingRuntimeDataAuthority:$AllowMissingRuntimeDataAuthority `
        -AllowMissingOwnerRecoveryChannel
}

function Stop-ServiceIfExists([string]$Name) {
    Assert-ExpectedServiceConfiguration $Name
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

function Remove-ServiceIfExists([string]$Name) {
    Assert-ExpectedServiceConfiguration $Name
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

function Test-TicketboxPgClusterRunning {
    $pidPath = Join-Path $PgData "postmaster.pid"
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $PgCtl -PathType Leaf)) {
        throw "发现 PostgreSQL PID 文件但缺少 pg_ctl.exe，无法验证数据簇是否仍在运行：$PgData"
    }
    $statusResult = Invoke-TicketboxBoundedNativeProcess `
        -FilePath $PgCtl `
        -Arguments @('status', '-D', $PgData) `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs `
        -Label 'pg_ctl uninstall-state verification'
    $rc = $statusResult.ExitCode
    if ($rc -eq 0) {
        return $true
    }
    if ($rc -eq 3) {
        return $false
    }
    throw "pg_ctl 无法确认 PostgreSQL 数据簇状态（exit=$rc）。"
}

function Assert-TicketboxPgScmProcessAgreement {
    $clusterRunning = Test-TicketboxPgClusterRunning
    if (-not (Service-Exists $PgServiceName)) {
        if ($clusterRunning) {
            throw "发现没有归属服务但仍在运行的 PostgreSQL 数据簇，拒绝卸载：$PgData"
        }
        return
    }
    $serviceState = Wait-TicketboxServiceSettledState -Name $PgServiceName @ServiceWaitArguments
    if (($serviceState -eq "running") -ne $clusterRunning) {
        throw "PostgreSQL SCM 状态 ($serviceState) 与数据簇进程状态不一致，拒绝卸载：$PgData"
    }
}

function Get-TicketboxPreservedPgMajor {
    $versionPath = Join-Path $PgData "PG_VERSION"
    if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) { return 0 }
    $text = (Get-Content -LiteralPath $versionPath -Encoding ASCII -Raw).Trim()
    $major = 0
    if (-not [int]::TryParse($text, [ref]$major) -or $major -le 0) {
        throw "PostgreSQL PG_VERSION 无效，拒绝生成不可验证的卸载恢复点。"
    }
    return $major
}

function Save-TicketboxUninstallPgRecoveryIfRequired {
    if ($DeleteData) { return }
    $major = Get-TicketboxPreservedPgMajor
    $envPath = Join-Path $AppData ".env"
    if ($major -le 0 -or -not (Test-Path -LiteralPath $envPath -PathType Leaf)) { return }
    Write-Step "创建 PostgreSQL 保留数据重装恢复点"
    Save-TicketboxPgRecoveryToolset `
        -SourcePgHome (Join-Path $InstallDir "pg") `
        -BuildManifestPath $InstalledBuildManifestPath `
        -ExpectedMajor $major | Out-Null
    Write-Ok "恢复工具已绑定当前安装 provenance 并保存到机器级受保护目录。"
}

function Assert-TicketboxRuntimeProcessesStoppedForDataDeletion {
    param(
        [scriptblock]$ProcessReader = {
            Get-CimInstance -ClassName Win32_Process -ErrorAction Stop
        }
    )

    $expectedPaths = @(
        $BackendExe,
        $ShawlExe,
        $PgCtl,
        (Join-Path $PgBin "postgres.exe")
    )
    $expectedNames = @($expectedPaths | ForEach-Object {
        [System.IO.Path]::GetFileName($_)
    } | Sort-Object -Unique)
    try {
        $processes = @(& $ProcessReader)
    }
    catch {
        throw "无法枚举运行进程，拒绝在无法证明安装进程已退出时删除数据。"
    }

    $blockingProcessIds = @()
    foreach ($process in $processes) {
        $processPath = [string]$process.ExecutablePath
        $processName = [string]$process.Name
        $processId = [int]$process.ProcessId
        if ([string]::IsNullOrWhiteSpace($processPath)) {
            if ($processName -in $expectedNames) {
                $blockingProcessIds += $processId
            }
            continue
        }
        if (@($expectedPaths | Where-Object {
            Test-TicketboxPathEquals $processPath $_
        }).Count -gt 0) {
            $blockingProcessIds += $processId
        }
    }
    if ($blockingProcessIds.Count -gt 0) {
        throw "删除数据前仍发现 Ticketbox 运行进程或无法核验路径的同名进程：PID $($blockingProcessIds -join ',')"
    }
}
$RegisteredPgPortNumber = 0
if (-not [string]::IsNullOrWhiteSpace($RegisteredPgPort)) {
    if (
        -not [int]::TryParse($RegisteredPgPort, [ref]$RegisteredPgPortNumber) -or
        $RegisteredPgPortNumber -lt 1 -or
        $RegisteredPgPortNumber -gt 65535
    ) {
        throw "安装器登记的 PgPort 无效，拒绝清理生命周期回执。"
    }
}

function Assert-TicketboxBackendPortStoppedForDataDeletion {
    if ($BackendPort -le 0) {
        return
    }
    $listeners = @(Get-TicketboxListeningProcessIds $BackendPort)
    if ($listeners.Count -gt 0) {
        throw "删除数据前登记端口 $BackendPort 仍被 PID $($listeners -join ',') 监听。"
    }
}

function Remove-TicketboxPgServiceIfExists {
    Remove-ServiceIfExists $PgServiceName
    if (Test-TicketboxPgClusterRunning) {
        throw "PostgreSQL 服务已停止或缺失，但数据簇仍在运行，拒绝继续。"
    }
}

function Assert-TicketboxMissingBackendServicePortStoppedForDataDeletion {
    if (-not $DeleteData -or (Service-Exists $BackendServiceName)) {
        return
    }
    Assert-TicketboxRuntimeProcessesStoppedForDataDeletion
    if ($BackendPort -gt 0) {
        Assert-TicketboxBackendPortStoppedForDataDeletion
    }
}

function Assert-TicketboxDataRootForDeletion([string]$CandidateRoot) {
    $arguments = @{
        DataRoot = $CandidateRoot
        RegisteredDataRoot = $RegisteredDataRoot
        InstallDir = $InstallDir
    }
    if ([string]::IsNullOrWhiteSpace($RegisteredDataRoot)) {
        if (-not $ExplicitDataRootProvided -and -not $script:DeleteDataIntentValidated) {
            throw "安装器注册表缺少 DataRoot；请显式传入原 DataRoot 后重试数据删除。"
        }
        $arguments.AllowProtectedMarkerWithoutRegistration = $true
    }
    if ($script:DeleteDataIntentValidated) {
        $arguments.AllowMarkerlessEmptyRoot = $true
    }
    return Assert-TicketboxDataRootDeletionSafety @arguments
}

function Remove-TicketboxInstallerRuntimeProjectionForUninstall {
    $runtimeState = Get-TicketboxInstallerRuntimeStateShape -DataRoot $DataRoot
    if (-not (Service-Exists $BackendServiceName)) {
        if ($runtimeState.DirectoryExists -or $runtimeState.GuardExists) {
            throw "backend 服务已缺失但 machine runtime-state 仍存在；拒绝在无法验证服务 SID 的状态下清理。"
        }
        return
    }

    Assert-ExpectedServiceConfiguration $BackendServiceName
    Disable-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable $ShawlExe `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments
    $generationCurrentPath = Get-TicketboxDatabaseGenerationRuntimeCurrentPath
    $generationRuntimeRoot = Split-Path -Parent $generationCurrentPath
    $backendReadAccount = "NT SERVICE\$BackendServiceName"
    if ((Get-TicketboxPathEntryKindNoFollow $generationCurrentPath) -cne "Missing") {
        Remove-TicketboxProtectedUtf8Artifact `
            -Path $generationCurrentPath `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -ReadExecuteAccounts @($backendReadAccount) `
            -OwnerAccount "SYSTEM"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $generationRuntimeRoot) -cne "Missing") {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $generationRuntimeRoot `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -ReadExecuteAccounts @($backendReadAccount) `
            -OwnerAccount "SYSTEM"
        Remove-Item -LiteralPath $generationRuntimeRoot -Force -ErrorAction Stop
    }
    Remove-TicketboxInstallerRuntimeRecoveryGuard `
        -Path $InstallerRuntimeRecoveryGuardPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -BackendServiceName $BackendServiceName
    if ($runtimeState.DirectoryExists) {
        Remove-TicketboxInstallerRuntimeStateDirectoryIfEmpty `
            -DataRoot $DataRoot `
            -BackendServiceName $BackendServiceName
    }
}

function Assert-UninstallInputs {
    Assert-ExpectedServiceConfiguration $BackendServiceName
    Assert-ExpectedServiceConfiguration $PgServiceName
    Assert-TicketboxPgScmProcessAgreement
    if ((Service-Exists $BackendServiceName) -and $BackendPort -le 0) {
        throw "无法从注册表或 .env 确定后端端口，拒绝在无法证明后端 PID/端口退出时卸载。"
    }
    if (-not $DeleteData) {
        return $null
    }
    Assert-TicketboxMissingBackendServicePortStoppedForDataDeletion
    return Assert-TicketboxDataRootForDeletion $DataRoot
}

function Get-TicketboxCompletedLifecycleReceiptForUninstall {
    $installerStateSnapshot = if ($DeleteData) {
        Get-TicketboxInstallerStateDataDeletionSnapshot
    }
    else { $null }
    $receiptKind = Get-TicketboxPathEntryKindNoFollow $LifecycleReceiptPath
    if ($receiptKind -ceq "Missing") {
        if (-not $DeleteData) { return $null }
        if ($installerStateSnapshot.Kinds[$DeleteDataIntentPath] -ceq "File") {
            Read-TicketboxDeleteDataIntent `
                -Path $DeleteDataIntentPath `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot | Out-Null
            $script:DeleteDataIntentValidated = $true
            return $null
        }
        throw "删除数据要求已完成 lifecycle receipt，或要求存在由其生成的受保护删除意图。"
    }
    if ($receiptKind -cne "File") {
        throw "生命周期回执路径存在但不是受支持的普通文件。"
    }
    if (
        $RegisteredInstallDir.Trim().Length -gt 0 -and
        -not (Test-TicketboxPathEquals $RegisteredInstallDir $InstallDir)
    ) {
        throw "旧注册安装目录与当前卸载目录不匹配，拒绝清理生命周期回执。"
    }
    $receipt = Read-TicketboxUninstallLifecycleReceipt `
        -Path $LifecycleReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -TargetReleaseConfig $ReleaseConfig `
        -ExpectedPgPort $RegisteredPgPortNumber `
        -ExpectedBackendPort $BackendPort `
        -ExpectedPgServiceName $RegisteredPgServiceName `
        -ExpectedBackendServiceName $RegisteredBackendServiceName
    if ([bool]$receipt.install_completed) {
        Assert-TicketboxCompletedLifecycleReceipt $receipt
        Assert-TicketboxUninstallLifecycleReceiptMutationAuthority $receipt
        return $receipt
    }
    Assert-TicketboxAbortedFreshInstallLifecycleReceipt $receipt
    $script:AbortedFreshInstallLifecycleReceipt = $receipt
    return $null
}

function Remove-TicketboxPreservedInstallationIdentity {
    if (-not (Test-Path -LiteralPath $regPath)) {
        return
    }
    $identityNamesToRemove = @($PreservedIdentityNames)
    if ($DeleteData) {
        $identityNamesToRemove += "BackendVersion"
    }
    foreach ($name in $identityNamesToRemove) {
        $existing = Get-ItemProperty -LiteralPath $regPath -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $existing -and $null -ne $existing.PSObject.Properties[$name]) {
            Remove-ItemProperty -LiteralPath $regPath -Name $name -Force -ErrorAction Stop
        }
        $remaining = Get-ItemProperty -LiteralPath $regPath -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $remaining -and $null -ne $remaining.PSObject.Properties[$name]) {
            throw "数据已删除，但无法清除安装身份注册表值：$name"
        }
    }
}

function Remove-TicketboxDataRootForUninstall([string]$CandidateRoot) {
    $safeRoot = Assert-TicketboxDataRootForDeletion $CandidateRoot
    if (-not (Test-Path -LiteralPath $safeRoot)) {
        return
    }
    Write-Step "删除数据目录 $safeRoot"
    if (-not $script:DeleteDataIntentValidated) {
        throw "数据目录删除前缺少已验证的删除意图。"
    }
    Read-TicketboxDeleteDataIntent `
        -Path $DeleteDataIntentPath `
        -InstallDir $InstallDir `
        -DataRoot $safeRoot | Out-Null
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $expectedDeleteIntentText = [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
        $DeleteDataIntentPath,
        16384
    )
    $safeRoot = [IO.Path]::GetFullPath($safeRoot).TrimEnd('\', '/')
    $expectedRootIdentity = @(
        [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($safeRoot)
    )
    if ($expectedRootIdentity.Count -ne 2) {
        throw "数据目录身份无法固定，拒绝删除。"
    }
    $dataRootMarkerPath = Join-Path $safeRoot $script:TicketboxDataRootMarkerName
    $expectedMarkerKind =
        [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($dataRootMarkerPath)
    $expectedMarkerText = if ($expectedMarkerKind -eq 1) {
        [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
            $dataRootMarkerPath,
            16384
        )
    }
    elseif ($expectedMarkerKind -eq 0) {
        if ([IO.Directory]::GetFileSystemEntries($safeRoot).Length -ne 0) {
            throw "无 marker 的中断删除目录在最终句柄获取前已不再为空。"
        }
        ""
    }
    else {
        throw "数据目录权威 marker 形态在最终删除前发生变化。"
    }
    # Services have already been removed.  Keep the live process, port, and
    # SCM proofs immediately adjacent to the exact root open; the callback is
    # native-delegate-safe and rebinds the opened directory plus authority
    # bytes without relying on script-scope command resolution.
    Assert-TicketboxRuntimeProcessesStoppedForDataDeletion
    Assert-TicketboxBackendPortStoppedForDataDeletion
    Assert-TicketboxPgScmProcessAgreement
    $finalDeletionGuard = {
        param($GuardedPath)
        $openedPath = [IO.Path]::GetFullPath($GuardedPath).TrimEnd('\', '/')
        if (-not [string]::Equals(
            $openedPath,
            $safeRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "数据目录句柄与已验证删除目标不一致。"
        }
        $openedIdentity = @(
            [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($openedPath)
        )
        if (
            $openedIdentity.Count -ne 2 -or
            [string]$openedIdentity[0] -cne [string]$expectedRootIdentity[0] -or
            [string]$openedIdentity[1] -cne [string]$expectedRootIdentity[1]
        ) {
            throw "数据目录身份在最终删除前发生变化。"
        }
        if (
            [TicketboxExactTreeDeleteNativeMethods]::InspectEntry(
                $DeleteDataIntentPath
            ) -ne 1 -or
            [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                $DeleteDataIntentPath,
                16384
            ) -cne $expectedDeleteIntentText
        ) {
            throw "数据目录句柄获取后删除意图发生变化。"
        }
        $openedMarkerKind =
            [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($dataRootMarkerPath)
        if ($expectedMarkerKind -eq 1) {
            if (
                $openedMarkerKind -ne 1 -or
                [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                    $dataRootMarkerPath,
                    16384
                ) -cne $expectedMarkerText
            ) {
                throw "数据目录权威 marker 在最终删除前发生变化。"
            }
        }
        elseif (
            $openedMarkerKind -ne 0 -or
            [IO.Directory]::GetFileSystemEntries($openedPath).Length -ne 0
        ) {
            throw "无 marker 的中断删除目录在最终删除前已不再为空。"
        }
    }.GetNewClosure()
    Remove-TicketboxDataRootExact `
        -Path $safeRoot `
        -DeferredRootLeafName $script:TicketboxDataRootMarkerName `
        -OnRootHandleAcquired $finalDeletionGuard
    Write-Ok "数据目录已删除。"
}

function Get-TicketboxInstallerStateDataDeletionSnapshot {
    $rootKind = Get-TicketboxPathEntryKindNoFollow $InstallerState
    if ($rootKind -ceq "Missing") {
        return [pscustomobject]@{ Exists = $false; Kinds = @{} }
    }
    if ($rootKind -cne "Directory") {
        throw "installer-state 不是普通目录，拒绝随数据删除：$rootKind"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $InstallerState `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    $kinds = @{}
    foreach ($path in @(
        $OwnerHandoffPath,
        $RetiredOwnerBootstrapPath,
        $RetiredOwnerHandoffPendingPath,
        $RecoveryRequiredPath,
        $DeleteDataIntentPath
    )) {
        $kind = Get-TicketboxPathEntryKindNoFollow $path
        if ($kind -notin @("Missing", "File")) {
            throw "installer-state 已知状态不是普通文件，拒绝随数据删除：$path ($kind)"
        }
        $kinds[$path] = $kind
    }
    return [pscustomobject]@{ Exists = $true; Kinds = $kinds }
}

function Assert-TicketboxRetiredInstallerStateShape([object]$Snapshot) {
    if (-not $Snapshot.Exists) { return }
    foreach ($path in @(
        $OwnerHandoffPath,
        $RetiredOwnerBootstrapPath,
        $RetiredOwnerHandoffPendingPath,
        $RecoveryRequiredPath,
        $DeleteDataIntentPath
    )) {
        if ($Snapshot.Kinds[$path] -cne "Missing") {
            throw "安装身份已缺少 DataRoot，且 installer-state 仍含权威状态：$path"
        }
    }
    foreach ($item in @(Get-ChildItem -LiteralPath $InstallerState -Force -ErrorAction Stop)) {
        if ($item.Name -cnotmatch '^\.ticketbox-(protected|durable)-[0-9a-f]{32}\.tmp$') {
            throw "安装身份已缺少 DataRoot，且 installer-state 含未知状态：$($item.Name)"
        }
        if ((Get-TicketboxPathEntryKindNoFollow $item.FullName) -cne "File") {
            throw "退役 installer-state 的 staging artifact 不是普通文件：$($item.FullName)"
        }
    }
}

function Remove-TicketboxRetiredInstallerStateAfterRuntimeProjection {
    $snapshot = Get-TicketboxInstallerStateDataDeletionSnapshot
    if (-not $snapshot.Exists) { return }
    Assert-TicketboxRetiredInstallerStateShape $snapshot
    Remove-TicketboxProtectedStagingArtifacts `
        -Path $InstallerState `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    $revalidatedSnapshot = Get-TicketboxInstallerStateDataDeletionSnapshot
    Assert-TicketboxRetiredInstallerStateShape $revalidatedSnapshot
    if (@(Get-ChildItem -LiteralPath $InstallerState -Force -ErrorAction Stop).Count -gt 0) {
        throw "退役 installer-state 清理 staging 后仍非空。"
    }
    Remove-Item -LiteralPath $InstallerState -Force -ErrorAction Stop
    if ((Get-TicketboxPathEntryKindNoFollow $InstallerState) -cne "Missing") {
        throw "无法清理删除意图退役后留下的空 installer-state。"
    }
}

function Assert-TicketboxInstallerStateForDataDeletion {
    $snapshot = Get-TicketboxInstallerStateDataDeletionSnapshot
    if (-not $snapshot.Exists) { return $snapshot }
    $knownNames = @(
        "installation-owner-handoff-v2.txt",
        "owner-bootstrap.txt",
        "owner-handoff-pending",
        "installer-recovery-required.json",
        "delete-data-in-progress.json"
    )
    $unknownEntries = @(Get-ChildItem -LiteralPath $InstallerState -Force | Where-Object {
        $_.Name -notin $knownNames -and
        $_.Name -cnotmatch '^\.ticketbox-(protected|durable)-[0-9a-f]{32}\.tmp$'
    })
    if ($unknownEntries.Count -gt 0) {
        throw "installer-state 含有未知状态，拒绝随数据删除：$($unknownEntries.Name -join ', ')"
    }
    foreach ($item in @(Get-ChildItem -LiteralPath $InstallerState -Force | Where-Object {
        $_.Name -cmatch '^\.ticketbox-(protected|durable)-[0-9a-f]{32}\.tmp$'
    })) {
        if ((Get-TicketboxPathEntryKindNoFollow $item.FullName) -cne "File") {
            throw "installer-state staging artifact 不是普通文件：$($item.FullName)"
        }
    }
    foreach ($path in @(
        $OwnerHandoffPath,
        $RetiredOwnerBootstrapPath,
        $RetiredOwnerHandoffPendingPath
    )) {
        if ($snapshot.Kinds[$path] -ceq "File") {
            Read-TicketboxProtectedUtf8Artifact `
                -Path $path `
                -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
                -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount `
                -MaximumBytes 16384 | Out-Null
        }
    }
    if ($snapshot.Kinds[$RecoveryRequiredPath] -ceq "File") {
        Read-TicketboxInstallerRecoveryMarker `
            -Path $RecoveryRequiredPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot | Out-Null
    }
    if ($snapshot.Kinds[$DeleteDataIntentPath] -ceq "File") {
        Read-TicketboxDeleteDataIntent `
            -Path $DeleteDataIntentPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot | Out-Null
        $script:DeleteDataIntentValidated = $true
    }
    if ($snapshot.Kinds[$OwnerHandoffPath] -ceq "File") {
        Read-TicketboxOwnerHandoffRecord | Out-Null
    }
    return $snapshot
}

function Remove-TicketboxInstallerStateStagingAfterRuntimeProjection {
    $snapshot = Assert-TicketboxInstallerStateForDataDeletion
    if (-not $snapshot.Exists) { return }
    Remove-TicketboxProtectedStagingArtifacts `
        -Path $InstallerState `
        -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
        -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    Assert-TicketboxInstallerStateForDataDeletion | Out-Null
}

function Remove-TicketboxInstallerStateAfterDataDeletion {
    $snapshot = Assert-TicketboxInstallerStateForDataDeletion
    if (-not $snapshot.Exists) { return }
    Remove-TicketboxInstallerStateStagingAfterRuntimeProjection
    $snapshot = Assert-TicketboxInstallerStateForDataDeletion
    foreach ($path in @(
        $OwnerHandoffPath,
        $RetiredOwnerBootstrapPath,
        $RetiredOwnerHandoffPendingPath
    )) {
        if ($snapshot.Kinds[$path] -ceq "File") {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path $path `
                -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
                -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
        }
    }
    if ($snapshot.Kinds[$RecoveryRequiredPath] -ceq "File") {
        Remove-TicketboxInstallerRecoveryMarker `
            -Path $RecoveryRequiredPath `
            -InstallDir $InstallDir `
            -DataRoot $DataRoot
    }
    if ($snapshot.Kinds[$DeleteDataIntentPath] -ceq "File") {
        Remove-TicketboxProtectedUtf8Artifact `
            -Path $DeleteDataIntentPath `
            -FullControlAccounts $script:TicketboxLifecycleReceiptAclAccounts `
            -OwnerAccount $script:TicketboxLifecycleReceiptOwnerAccount
    }
    if (@(Get-ChildItem -LiteralPath $InstallerState -Force).Count -gt 0) {
        throw "删除已验证 installer-state 后目录仍非空。"
    }
    Remove-Item -LiteralPath $InstallerState -Force -ErrorAction Stop
    if ((Get-TicketboxPathEntryKindNoFollow $InstallerState) -cne "Missing") {
        throw "无法删除已退役的 installer-state 目录。"
    }
}

function Resolve-TicketboxDeleteDataRetryAuthority {
    if (
        -not $DeleteData -or
        -not ($InstallationIdentityAlreadyRemoved -or $InstallationIdentityCleanupIncomplete) -or
        $ExplicitDataRootProvided -or
        $RegisteredDataRoot.Trim().Length -gt 0
    ) {
        return "not_required"
    }
    $lifecycleReceiptKind = Get-TicketboxPathEntryKindNoFollow $LifecycleReceiptPath
    if ($lifecycleReceiptKind -notin @("Missing", "File")) {
        throw "安装身份已缺少 DataRoot，但 lifecycle receipt 形态不可信：$lifecycleReceiptKind"
    }
    $installerStateSnapshot = Get-TicketboxInstallerStateDataDeletionSnapshot
    if ($installerStateSnapshot.Kinds[$DeleteDataIntentPath] -ceq "File") {
        $intent = Read-TicketboxDeleteDataIntent `
            -Path $DeleteDataIntentPath `
            -InstallDir $InstallDir
        Set-TicketboxUninstallDataRoot ([string]$intent.data_root)
        $script:DeleteDataIntentValidated = $true
        return "resolved"
    }
    if ($lifecycleReceiptKind -cne "Missing") {
        throw "安装身份已缺少 DataRoot，但 lifecycle receipt 仍存在且没有绑定删除意图。"
    }
    if ($installerStateSnapshot.Exists) {
        Assert-TicketboxRetiredInstallerStateShape $installerStateSnapshot
        return "retired"
    }
    return "retired"
}

function Get-TicketboxUninstallInitdbReceiptOwnerProcessId {
    if ($InstallerLockOwnerProcessId -gt 0) {
        return $InstallerLockOwnerProcessId
    }
    return $PID
}

function Read-TicketboxUninstallInitdbServiceReceipt {
    param([switch]$AllowPreviousInstallerOwnerProcessId)

    return Read-TicketboxBoundInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -ServiceName $PgServiceName `
        -InstallerOwnerProcessId (Get-TicketboxUninstallInitdbReceiptOwnerProcessId) `
        -AllowPreviousInstallerOwnerProcessId:$AllowPreviousInstallerOwnerProcessId
}

function Remove-TicketboxUninstallInitdbPasswordFile([object]$Receipt) {
    $allowPreAuthorizationAcl =
        [string]$Receipt.phase -in @("intent_written", "registered")
    Remove-TicketboxInitdbPasswordFileExact `
        -Path $InitdbPasswordPath `
        -ServiceName $PgServiceName `
        -AllowServiceReadMissing:$allowPreAuthorizationAcl
}

function Remove-TicketboxUninstallInitdbBootstrapRecoveryIfPresent {
    $kind = Get-TicketboxPathEntryKindNoFollow $PgBootstrapRecoveryPath
    if ($kind -ceq "Missing") { return }
    if ($kind -cne "File") {
        throw "中断首装的 PostgreSQL 凭据恢复路径不是普通文件。"
    }
    Assert-TicketboxExactFileAcl `
        -Path $PgBootstrapRecoveryPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $PgBootstrapRecoveryPath `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
}

function Remove-TicketboxUninstallAbortedInitdbPgData([object]$Receipt) {
    Remove-TicketboxInterruptedInitdbPgDataExact `
        -Receipt $Receipt `
        -PgData $PgData `
        -EnvPath (Join-Path $AppData ".env") `
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

function Invoke-TicketboxInitdbServiceUninstallRecovery {
    $receiptKind = Get-TicketboxPathEntryKindNoFollow $InitdbServiceReceiptPath
    if ($receiptKind -ceq "Missing") { return }
    if ($receiptKind -cne "File") {
        throw "initdb one-shot 回执路径形态不可信，拒绝卸载。"
    }
    $receipt = Read-TicketboxUninstallInitdbServiceReceipt `
        -AllowPreviousInstallerOwnerProcessId
    if ((Get-TicketboxPathEntryKindNoFollow (Join-Path $AppData ".env")) -cne "Missing") {
        throw "未提交的 initdb 回执与应用 .env 同时存在，拒绝在卸载中改变服务或秘密。"
    }
    $phase = [string]$receipt.phase
    $serviceShape = "absent"
    if (Service-Exists $PgServiceName) {
        $actualExecutable = Get-TicketboxServiceExecutablePath $PgServiceName
        $startMode = Get-TicketboxServiceStartMode $PgServiceName
        if ($startMode -notin @("Disabled", "Manual")) {
            throw "中断首装 PostgreSQL 服务启动模式越界：$startMode"
        }
        $targetIdentityShape = @(Get-TicketboxReleaseServiceIdentityShapes `
            -InstalledConfig $ReleaseConfig `
            -TargetConfig $ReleaseConfig `
            -ServiceName $PgServiceName)[0]
        Assert-TicketboxServiceIdentityShape `
            -Name $PgServiceName `
            -AllowedShapes @(Get-TicketboxInitdbReceiptServiceIdentityShapes `
                -Receipt $receipt `
                -ServiceName $PgServiceName `
                -TargetShape $targetIdentityShape `
                -AllowCurrentSidTypePending:($phase -ceq "intent_written")) | Out-Null
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
                -ExpectedStopTimeoutMs ([int]$receipt.stop_timeout_ms) `
                -ExpectedImagePath ([string]$receipt.image_path)
            Assert-TicketboxServiceHasNoFailureActions $PgServiceName
            $serviceShape = "initdb_one_shot"
        }
        elseif (Test-TicketboxPathEquals $actualExecutable $PgCtl) {
            Assert-TicketboxPgServiceCommand `
                -Name $PgServiceName `
                -ExpectedExecutable $PgCtl `
                -ExpectedServiceName $PgServiceName `
                -ExpectedDataRoot $ServicePgData
            $actualFailurePolicy = Get-TicketboxServiceFailurePolicy $PgServiceName
            $expectedFailurePolicy = Get-TicketboxExpectedServiceFailurePolicy `
                -ResetSeconds ([int]$ReleaseConfig.scm_failure_reset_seconds) `
                -RestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)
            if ($actualFailurePolicy -notin @("0|", $expectedFailurePolicy)) {
                throw "中断首装的正式 PostgreSQL 服务 failure policy 不属于可恢复状态。"
            }
            $serviceShape = "formal_pg_ctl"
        }
        else {
            throw "中断首装回执对应的同名 PostgreSQL 服务 executable 不匹配。"
        }
    }

    if ($serviceShape -ceq "formal_pg_ctl") {
        if ($phase -notin @("initdb_succeeded", "converted_to_pgctl")) {
            throw "未提交的 initdb 回执却已指向正式 pg_ctl 服务。"
        }
        if ((Get-TicketboxPathEntryKindNoFollow $InitdbPasswordPath) -cne "Missing") {
            throw "正式 pg_ctl 服务仍残留 initdb 临时密码文件。"
        }
        Disable-TicketboxOwnedServiceIfExists `
            -Name $PgServiceName `
            -ExpectedExecutable $PgCtl `
            -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
            @ServiceWaitArguments
        Assert-TicketboxServiceStartMode `
            -Name $PgServiceName `
            -ExpectedStartMode "Disabled"
        $scmRestartActions = @(
            $ReleaseConfig.scm_restart_delays_ms |
                ForEach-Object { "restart/$([int]$_)" }
        ) -join "/"
        Invoke-ScChecked @(
            "failure", $PgServiceName,
            "reset=", [string]$ReleaseConfig.scm_failure_reset_seconds,
            "actions=", $scmRestartActions
        ) | Out-Null
        Assert-TicketboxServiceFailurePolicy `
            -Name $PgServiceName `
            -ExpectedResetSeconds ([int]$ReleaseConfig.scm_failure_reset_seconds) `
            -ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)
        if ($phase -ceq "initdb_succeeded") {
            Set-TicketboxInitdbServiceReceiptPhase `
                -Path $InitdbServiceReceiptPath `
                -Receipt $receipt `
                -InstallerOwnerProcessId (Get-TicketboxUninstallInitdbReceiptOwnerProcessId) `
                -Phase "converted_to_pgctl"
            $receipt = Read-TicketboxUninstallInitdbServiceReceipt
        }
        Remove-TicketboxInitdbServiceReceipt `
            -Path $InitdbServiceReceiptPath `
            -Receipt $receipt
        return
    }
    if ($phase -ceq "converted_to_pgctl") {
        throw "initdb 回执已提交但正式 PostgreSQL 服务缺失。"
    }
    if ($serviceShape -ceq "initdb_one_shot") {
        Disable-TicketboxOwnedServiceIfExists `
            -Name $PgServiceName `
            -ExpectedExecutable $ShawlExe `
            -ExpectedRuntimeExecutables @($ShawlExe, $InitdbExe) `
            @ServiceWaitArguments
        Remove-TicketboxUninstallInitdbPasswordFile $receipt
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
        Remove-TicketboxUninstallInitdbPasswordFile $receipt
    }
    Remove-TicketboxUninstallAbortedInitdbPgData $receipt
    Remove-TicketboxUninstallInitdbBootstrapRecoveryIfPresent
    Remove-TicketboxAbortedInitdbServiceReceipt `
        -Path $InitdbServiceReceiptPath `
        -Receipt $receipt
    Write-Warn2 "已清理正式提交前中断的 initdb one-shot 服务与临时数据。"
}

Write-Host "=== 小票夹服务卸载 ===" -ForegroundColor Yellow
$operationLock = Enter-TicketboxLifecycleLock `
    -ExternalOwnerProcessId $InstallerLockOwnerProcessId
try {
    Assert-Admin
    $deleteDataRetryAuthority = Resolve-TicketboxDeleteDataRetryAuthority
    Set-TicketboxUninstallRuntimeServiceContract
    $completedLifecycleReceipt = if ($deleteDataRetryAuthority -ceq "retired") {
        $null
    }
    else {
        Get-TicketboxCompletedLifecycleReceiptForUninstall
    }
    if ($null -ne $completedLifecycleReceipt) {
        $UninstallLifecycleReceipt = $completedLifecycleReceipt
        $UninstallInstalledReleaseConfig =
            $completedLifecycleReceipt.installed_release_config
    }
    elseif ($null -ne $script:AbortedFreshInstallLifecycleReceipt) {
        $UninstallLifecycleReceipt =
            $script:AbortedFreshInstallLifecycleReceipt
        $UninstallInstalledReleaseConfig =
            $script:AbortedFreshInstallLifecycleReceipt.installed_release_config
    }
    Invoke-TicketboxInitdbServiceUninstallRecovery
    if ($InstallationIdentityAlreadyRemoved -or $InstallationIdentityCleanupIncomplete) {
        if ((Service-Exists $BackendServiceName) -or (Service-Exists $PgServiceName)) {
            throw "安装身份已缺少 DataRoot，但 Ticketbox 服务仍存在；拒绝把损坏状态误判为已卸载。"
        }
        Wait-TicketboxBackendRuntimeStopped `
            -Name $BackendServiceName `
            -BackendPort $BackendPort `
            -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
            @ServiceWaitArguments
        Wait-TicketboxBackendRuntimeStopped `
            -Name $PgServiceName `
            -ExpectedRuntimeExecutables @($PgCtl, (Join-Path $PgBin "postgres.exe")) `
            @ServiceWaitArguments
        Remove-TicketboxInstallerRuntimeProjectionForUninstall
        if ($deleteDataRetryAuthority -ceq "retired") {
            Remove-TicketboxRetiredInstallerStateAfterRuntimeProjection
        }
        Remove-TicketboxUninstallRuntimeDataBindingIfPresent
        if (
            $DeleteData -and
            (
                $ExplicitDataRootProvided -or
                $RegisteredDataRoot.Trim().Length -gt 0 -or
                $deleteDataRetryAuthority -ceq "resolved"
            )
        ) {
            Assert-TicketboxInstallerStateForDataDeletion
            if ($null -ne $completedLifecycleReceipt) {
                Write-TicketboxDeleteDataIntent `
                    -Path $DeleteDataIntentPath `
                    -CompletedReceiptPath $LifecycleReceiptPath `
                    -CompletedReceipt $completedLifecycleReceipt `
                    -InstallDir $InstallDir `
                    -DataRoot $DataRoot | Out-Null
                $script:DeleteDataIntentValidated = $true
                Remove-TicketboxCompletedLifecycleReceipt `
                    -Path $LifecycleReceiptPath `
                    -Receipt $completedLifecycleReceipt
                $completedLifecycleReceipt = $null
            }
            Remove-TicketboxDataRootForUninstall $DataRoot
            Remove-TicketboxPgRecoveryToolset `
                -ExpectedMajor 0 `
                -DeleteDataIntentValidated:$script:DeleteDataIntentValidated
        }
        if ($null -ne $completedLifecycleReceipt) {
            Remove-TicketboxCompletedLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $completedLifecycleReceipt
        }
        if ($InstallationIdentityCleanupIncomplete -or $DeleteData) {
            Remove-TicketboxPreservedInstallationIdentity
        }
        if ($DeleteData -and $deleteDataRetryAuthority -ne "retired") {
            Remove-TicketboxInstallerStateAfterDataDeletion
        }
        if ($InstallationIdentityCleanupIncomplete) {
            Write-Host "残留安装身份已完成清理；本次卸载重试已安全收口。" -ForegroundColor Green
        }
        else {
            Write-Host "安装身份、服务与安装路径进程均已移除；本次卸载重试按幂等成功处理。" -ForegroundColor Green
        }
        return
    }
    $safeRoot = Assert-UninstallInputs
    if ($DeleteData) {
        Assert-TicketboxInstallerStateForDataDeletion
        if ($null -ne $script:AbortedFreshInstallLifecycleReceipt) {
            Write-TicketboxAbortedFreshInstallDeleteDataIntent `
                -Path $DeleteDataIntentPath `
                -AuthorityReceiptPath $LifecycleReceiptPath `
                -AuthorityReceipt $script:AbortedFreshInstallLifecycleReceipt `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot | Out-Null
            $script:DeleteDataIntentValidated = $true
        }
    }
    $preservedPgMajor = Get-TicketboxPreservedPgMajor
    Remove-TicketboxInstallerRuntimeProjectionForUninstall
    if ($DeleteData) {
        Remove-TicketboxInstallerStateStagingAfterRuntimeProjection
    }
    Save-TicketboxUninstallPgRecoveryIfRequired

    Write-Step "停止并删除后端服务"
    Remove-ServiceIfExists $BackendServiceName
    Write-Ok "后端服务已处理。"

    Write-Step "停止并删除 PostgreSQL 服务"
    Remove-TicketboxPgServiceIfExists
    Write-Ok "PG 服务已处理。"
    Remove-TicketboxUninstallRuntimeDataBindingIfPresent

    if ($DeleteData) {
        if ($null -ne $completedLifecycleReceipt) {
            Write-TicketboxDeleteDataIntent `
                -Path $DeleteDataIntentPath `
                -CompletedReceiptPath $LifecycleReceiptPath `
                -CompletedReceipt $completedLifecycleReceipt `
                -InstallDir $InstallDir `
                -DataRoot $DataRoot | Out-Null
            $script:DeleteDataIntentValidated = $true
            Remove-TicketboxCompletedLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $completedLifecycleReceipt
            $completedLifecycleReceipt = $null
        }
        if ($null -ne $script:AbortedFreshInstallLifecycleReceipt) {
            Remove-TicketboxAbortedFreshInstallLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $script:AbortedFreshInstallLifecycleReceipt
            $script:AbortedFreshInstallLifecycleReceipt = $null
        }
        Remove-TicketboxDataRootForUninstall $safeRoot
        Remove-TicketboxPgRecoveryToolset `
            -ExpectedMajor $preservedPgMajor `
            -DeleteDataIntentValidated:$script:DeleteDataIntentValidated
        Remove-TicketboxPreservedInstallationIdentity
        Remove-TicketboxInstallerStateAfterDataDeletion
    }
    else {
        Write-Step "保留数据目录"
        Write-Host "    $DataRoot"
        if ($null -ne $completedLifecycleReceipt) {
            Remove-TicketboxCompletedLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $completedLifecycleReceipt
            $completedLifecycleReceipt = $null
        }
        if ($null -ne $script:AbortedFreshInstallLifecycleReceipt) {
            Remove-TicketboxAbortedFreshInstallLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $script:AbortedFreshInstallLifecycleReceipt
            $script:AbortedFreshInstallLifecycleReceipt = $null
        }
    }

    Write-Host ""
    Write-Host "=== 卸载脚本完成 ===" -ForegroundColor Green
}
finally {
    Exit-TicketboxLifecycleLock $operationLock
}
