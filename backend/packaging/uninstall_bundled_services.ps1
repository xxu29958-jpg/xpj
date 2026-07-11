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
$PgServiceName = [string]$ReleaseConfig.pg_service_name
$BackendServiceName = [string]$ReleaseConfig.backend_service_name
$StopTimeoutMs = [int]$ReleaseConfig.stop_timeout_ms
$RestartDelayMs = [int]$ReleaseConfig.restart_delay_ms
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
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
if (-not (Test-Path -LiteralPath $LockScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期锁脚本：$LockScript"
}
. $LockScript
$ReceiptScript = Join-Path $ScriptDir "windows_lifecycle_receipt.ps1"
if (-not (Test-Path -LiteralPath $ReceiptScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期回执脚本：$ReceiptScript"
}
. $ReceiptScript
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
$PgData = Join-Path $DataRoot "pgdata"
$AppData = Join-Path $DataRoot "app"
$LogDir = Join-Path $AppData "logs"
$BackendExe = Join-Path $InstallDir "program\ticketbox-backend\ticketbox-backend.exe"
$BootstrapExposureRecoveryGuardPath = Join-Path $DataRoot "bootstrap-exposure-recovery-pending"
$ShawlExe = Join-Path $InstallDir "shawl\shawl.exe"
$PgCtl = Join-Path $PgBin "pg_ctl.exe"
$InstalledBuildManifestPath = Join-Path $ScriptDir "BUILD_PROVENANCE.json"
$LifecycleReceiptPath = Get-TicketboxLifecycleReceiptPath
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
    Assert-TicketboxServiceAccount -Name $Name -ExpectedAccount "NT SERVICE\$Name"
    if ($Name -eq $PgServiceName) {
        Assert-TicketboxPgServiceCommand -Name $Name -ExpectedExecutable $PgCtl -ExpectedServiceName $PgServiceName -ExpectedDataRoot $PgData
        return
    }
    Assert-TicketboxShawlServiceCommand `
        -Name $Name `
        -ExpectedExecutable $ShawlExe `
        -ExpectedServiceName $BackendServiceName `
        -ExpectedCwd $AppData `
        -ExpectedPayload $BackendExe `
        -ExpectedDependency $PgServiceName `
        -ExpectedLogDir $LogDir `
        -ExpectedPgDumpPath (Join-Path $PgBin "pg_dump.exe") `
        -ExpectedPgRestorePath (Join-Path $PgBin "pg_restore.exe") `
        -ExpectedBootstrapRecoveryGuardPath $BootstrapExposureRecoveryGuardPath `
        -ExpectedStopTimeoutMs $StopTimeoutMs `
        -ExpectedRestartDelayMs $RestartDelayMs
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
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $PgCtl status -D $PgData 2>&1
        $rc = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($rc -eq 0) {
        return $true
    }
    if ($rc -eq 3) {
        return $false
    }
    throw "pg_ctl 无法确认 PostgreSQL 数据簇状态（exit=$rc）：`n$output"
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
        if (-not $ExplicitDataRootProvided) {
            throw "安装器注册表缺少 DataRoot；请显式传入原 DataRoot 后重试数据删除。"
        }
        $arguments.AllowProtectedMarkerWithoutRegistration = $true
    }
    return Assert-TicketboxDataRootDeletionSafety @arguments
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

function Get-TicketboxCompletedLifecycleReceiptForDataDeletion {
    if (-not $DeleteData -or -not (Test-Path -LiteralPath $LifecycleReceiptPath -PathType Leaf)) {
        return $null
    }
    if (
        $RegisteredInstallDir.Trim().Length -gt 0 -and
        -not (Test-TicketboxPathEquals $RegisteredInstallDir $InstallDir)
    ) {
        throw "旧注册安装目录与当前卸载目录不匹配，拒绝清理生命周期回执。"
    }
    return Read-TicketboxCompletedLifecycleReceipt `
        -Path $LifecycleReceiptPath `
        -InstallDir $InstallDir `
        -DataRoot $DataRoot `
        -TargetReleaseConfig $ReleaseConfig `
        -ExpectedPgPort $RegisteredPgPortNumber `
        -ExpectedBackendPort $BackendPort `
        -ExpectedPgServiceName $RegisteredPgServiceName `
        -ExpectedBackendServiceName $RegisteredBackendServiceName
}

function Remove-TicketboxPreservedInstallationIdentity {
    if (-not (Test-Path -LiteralPath $regPath)) {
        return
    }
    foreach ($name in $PreservedIdentityNames) {
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
    $finalDeletionGuard = {
        param($GuardedPath)
        if (-not (Test-TicketboxPathEquals $GuardedPath $safeRoot)) {
            throw "数据目录句柄与已验证删除目标不一致。"
        }
        Assert-TicketboxRuntimeProcessesStoppedForDataDeletion
        Assert-TicketboxBackendPortStoppedForDataDeletion
        Assert-TicketboxPgScmProcessAgreement
    }.GetNewClosure()
    Remove-TicketboxDataRootExact `
        -Path $safeRoot `
        -OnRootHandleAcquired $finalDeletionGuard
    Write-Ok "数据目录已删除。"
}

Write-Host "=== 小票夹服务卸载 ===" -ForegroundColor Yellow
$operationLock = Enter-TicketboxLifecycleLock `
    -ExternalOwnerProcessId $InstallerLockOwnerProcessId
try {
    Assert-Admin
    $completedLifecycleReceipt = Get-TicketboxCompletedLifecycleReceiptForDataDeletion
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
        if (
            $DeleteData -and
            ($ExplicitDataRootProvided -or $RegisteredDataRoot.Trim().Length -gt 0)
        ) {
            Remove-TicketboxDataRootForUninstall $DataRoot
        }
        if ($InstallationIdentityCleanupIncomplete) {
            Remove-TicketboxPreservedInstallationIdentity
            Write-Host "残留安装身份已完成清理；本次卸载重试已安全收口。" -ForegroundColor Green
        }
        else {
            Write-Host "安装身份、服务与安装路径进程均已移除；本次卸载重试按幂等成功处理。" -ForegroundColor Green
        }
        if ($null -ne $completedLifecycleReceipt) {
            Remove-TicketboxCompletedLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $completedLifecycleReceipt
        }
        return
    }
    $safeRoot = Assert-UninstallInputs
    $preservedPgMajor = Get-TicketboxPreservedPgMajor
    Save-TicketboxUninstallPgRecoveryIfRequired

    Write-Step "停止并删除后端服务"
    Remove-ServiceIfExists $BackendServiceName
    Write-Ok "后端服务已处理。"

    Write-Step "停止并删除 PostgreSQL 服务"
    Remove-TicketboxPgServiceIfExists
    Write-Ok "PG 服务已处理。"

    if ($DeleteData) {
        Remove-TicketboxDataRootForUninstall $safeRoot
        Remove-TicketboxPreservedInstallationIdentity
        Remove-TicketboxPgRecoveryToolset -ExpectedMajor $preservedPgMajor
        if ($null -ne $completedLifecycleReceipt) {
            Remove-TicketboxCompletedLifecycleReceipt `
                -Path $LifecycleReceiptPath `
                -Receipt $completedLifecycleReceipt
        }
    }
    else {
        Write-Step "保留数据目录"
        Write-Host "    $DataRoot"
    }

    Write-Host ""
    Write-Host "=== 卸载脚本完成 ===" -ForegroundColor Green
}
finally {
    Exit-TicketboxLifecycleLock $operationLock
}
