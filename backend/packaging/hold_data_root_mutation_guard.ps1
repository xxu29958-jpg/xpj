#Requires -Version 5.1
<#
.SYNOPSIS
  Hold or conclusively retire the installer DataRoot mutation guard.

.DESCRIPTION
  This is the only long-lived DataRoot guard entrypoint.  It intentionally
  loads no release config, service, database, or receipt state.  Recovery mode
  can acknowledge a pre-ready child failure only after acquiring the delegated
  operation lease and proving that no durable ready artifact exists.
#>
[CmdletBinding(DefaultParameterSetName = "Hold")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "Hold")][string]$InstallDir,
    [Parameter(Mandatory = $true, ParameterSetName = "Hold")][string]$DataRoot,
    [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$InstallerLockOwnerProcessId,
    [Parameter(Mandatory = $true, ParameterSetName = "Hold")][switch]$Hold,
    [Parameter(Mandatory = $true, ParameterSetName = "ConfirmStopped")][switch]$ConfirmStopped,
    [Parameter(Mandatory = $true)][string]$DataRootGuardReadyPath,
    [Parameter(Mandatory = $true)][string]$DataRootGuardReleasePath,
    [Parameter(ParameterSetName = "ConfirmStopped")][ValidateRange(0, 2147483647)][int]$ExpectedHolderProcessId = 0,
    [Parameter(ParameterSetName = "ConfirmStopped")][uint32]$ExpectedHolderStartedFileTimeHigh = 0,
    [Parameter(ParameterSetName = "ConfirmStopped")][uint32]$ExpectedHolderStartedFileTimeLow = 0,
    [Parameter(ParameterSetName = "ConfirmStopped")][string]$ExpectedNonce = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$expectedHolderParameterNames = @(
    "ExpectedHolderProcessId",
    "ExpectedHolderStartedFileTimeHigh",
    "ExpectedHolderStartedFileTimeLow",
    "ExpectedNonce"
)
$expectedHolderParameterCount = @(
    $expectedHolderParameterNames | Where-Object { $PSBoundParameters.ContainsKey($_) }
).Count
if ($expectedHolderParameterCount -notin @(0, $expectedHolderParameterNames.Count)) {
    throw "DataRoot guard holder 身份恢复参数不完整。"
}
$hasExpectedHolder = $expectedHolderParameterCount -eq $expectedHolderParameterNames.Count
if (
    $hasExpectedHolder -and (
        $ExpectedHolderProcessId -le 0 -or
        $ExpectedNonce -cnotmatch "\A[0-9a-f]{64}\z"
    )
) {
    throw "DataRoot guard holder 身份恢复参数无效。"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
foreach ($requiredScript in @($SafetyScript, $LockScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "缺少 DataRoot guard 依赖脚本：$requiredScript"
    }
}
. $SafetyScript
. $LockScript

function Assert-TicketboxDataRootGuardAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "DataRoot guard 必须以管理员身份运行。"
    }
}

function Assert-TicketboxDataRootGuardCoordinationPaths {
    $lockRoot = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    $expectedReady = Join-Path `
        $lockRoot `
        ("data-root-guard-{0}.ready" -f $InstallerLockOwnerProcessId)
    $expectedRelease = Join-Path `
        $lockRoot `
        ("data-root-guard-{0}.release" -f $InstallerLockOwnerProcessId)
    if (
        -not (Test-TicketboxPathEquals $DataRootGuardReadyPath $expectedReady) -or
        -not (Test-TicketboxPathEquals $DataRootGuardReleasePath $expectedRelease)
    ) {
        throw "DataRoot guard IPC 路径不属于当前 installer owner 的机器生命周期根。"
    }
}

function Assert-TicketboxDataRootGuardRecoveryControl {
    $readyKind = Get-TicketboxPathEntryKindNoFollow $DataRootGuardReadyPath
    $releaseKind = Get-TicketboxPathEntryKindNoFollow $DataRootGuardReleasePath
    $temporaryKind = Get-TicketboxPathEntryKindNoFollow "$DataRootGuardReleasePath.tmp"
    if ($readyKind -ceq "File") {
        if (-not $hasExpectedHolder) {
            throw "DataRoot guard 已发布 ready，但调用方没有精确 holder 身份。"
        }
        $expectedReady =
            "STATE=holding$([Environment]::NewLine)" +
            "OWNER_PID=$InstallerLockOwnerProcessId$([Environment]::NewLine)" +
            "HOLDER_PID=$ExpectedHolderProcessId$([Environment]::NewLine)" +
            "HOLDER_STARTED_FILETIME_HIGH=$ExpectedHolderStartedFileTimeHigh$([Environment]::NewLine)" +
            "HOLDER_STARTED_FILETIME_LOW=$ExpectedHolderStartedFileTimeLow$([Environment]::NewLine)" +
            "NONCE=$ExpectedNonce$([Environment]::NewLine)"
        $readyArtifact = Read-TicketboxProtectedUtf8Artifact `
            -Path $DataRootGuardReadyPath `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM" `
            -MaximumBytes 512
        if ($readyArtifact.Text -cne $expectedReady) {
            throw "DataRoot guard ready artifact 与 Setup 已验证身份不一致。"
        }
        $expectedIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
            -ProcessId $ExpectedHolderProcessId `
            -StartedFileTimeHigh $ExpectedHolderStartedFileTimeHigh `
            -StartedFileTimeLow $ExpectedHolderStartedFileTimeLow
        $actualProcess = Get-Process -Id $ExpectedHolderProcessId -ErrorAction SilentlyContinue
        if ($null -ne $actualProcess) {
            $actualIdentity = Get-TicketboxProcessIdentity `
                -ProcessId $ExpectedHolderProcessId `
                -Process $actualProcess
            if (Test-TicketboxProcessIdentityEquals $actualIdentity $expectedIdentity) {
                throw "DataRoot guard holder 仍以原进程身份存活，不能声明停止。"
            }
        }
    }
    elseif ($readyKind -cne "Missing") {
        throw "DataRoot guard ready artifact 形态不可判定，不能声明停止。"
    }
    if ($releaseKind -cne "File" -or $temporaryKind -cne "Missing") {
        throw "DataRoot guard abort artifact 不满足可恢复终态合同。"
    }
    $expectedAbort =
        "STATE=abort$([Environment]::NewLine)" +
        "OWNER_PID=$InstallerLockOwnerProcessId$([Environment]::NewLine)"
    $expectedRelease =
        "STATE=release$([Environment]::NewLine)" +
        "OWNER_PID=$InstallerLockOwnerProcessId$([Environment]::NewLine)" +
        "NONCE=$ExpectedNonce$([Environment]::NewLine)"
    $controlArtifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $DataRootGuardReleasePath `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -MaximumBytes 128
    if (
        $controlArtifact.Text -cne $expectedAbort -and
        (-not $hasExpectedHolder -or $controlArtifact.Text -cne $expectedRelease)
    ) {
        throw "DataRoot guard control artifact 不属于当前 installer owner/holder。"
    }
}

function Write-TicketboxDataRootGuardStoppedAcknowledgement {
    param([Parameter(Mandatory = $true)][object]$OwnerHandleLease)

    if (Test-TicketboxProcessIdentityHandleExited $OwnerHandleLease) {
        return
    }
    $stoppedText =
        "STATE=stopped$([Environment]::NewLine)" +
        "OWNER_PID=$InstallerLockOwnerProcessId$([Environment]::NewLine)"
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $DataRootGuardReleasePath `
        -Text $stoppedText `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting
    $stoppedArtifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $DataRootGuardReleasePath `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -MaximumBytes 128
    if ($stoppedArtifact.Text -cne $stoppedText) {
        throw "DataRoot guard stopped acknowledgement 写后复读不一致。"
    }
}

Assert-TicketboxDataRootGuardAdministrator
Assert-TicketboxDataRootGuardCoordinationPaths

$guardOperationState = [pscustomobject]@{
    Lock = Enter-TicketboxLifecycleLock `
        -ExternalOwnerProcessId $InstallerLockOwnerProcessId
}
$releaseGuardStartupLease = {
    if ($null -ne $guardOperationState.Lock) {
        Exit-TicketboxLifecycleLock $guardOperationState.Lock
        $guardOperationState.Lock = $null
    }
}
$guardOwnerHandleLease = $null
$guardExitReason = ""
$cleanupAuthorized = $false
$acknowledgementAuthorized = $false
try {
    $guardOwnerHandleLease = Open-TicketboxVerifiedProcessIdentityHandle `
        -ProcessId $InstallerLockOwnerProcessId `
        -ExpectedIdentity $guardOperationState.Lock.ExternalOwnerIdentity
    if ($ConfirmStopped) {
        Assert-TicketboxDataRootGuardRecoveryControl
        $cleanupAuthorized = $true
        $acknowledgementAuthorized = $true
        $guardExitReason = "confirmed_inactive"
    }
    else {
        $cleanupAuthorized = $true
        $acknowledgementAuthorized = $true
        Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir | Out-Null
        $guardExitReason = Wait-TicketboxDirectoryMutationGuardLease `
            -Path $DataRoot `
            -InstallDir $InstallDir `
            -ReadyPath $DataRootGuardReadyPath `
            -ReleasePath $DataRootGuardReleasePath `
            -OwnerProcessId $InstallerLockOwnerProcessId `
            -OwnerIdentity $guardOperationState.Lock.ExternalOwnerIdentity `
            -OnLeaseReady $releaseGuardStartupLease `
            -RetainWhileLockPath (Get-TicketboxLifecycleOperationLockPath)
    }
}
finally {
    try {
        if ($cleanupAuthorized) {
            $coordinationPaths = @(
                $DataRootGuardReadyPath,
                $DataRootGuardReleasePath,
                "$DataRootGuardReleasePath.tmp"
            )
            Remove-TicketboxDirectoryGuardCoordinationArtifacts `
                -ParentPath (Split-Path -Parent $DataRootGuardReadyPath) `
                -Paths $coordinationPaths
        }
    }
    finally {
        try {
            & $releaseGuardStartupLease
        }
        finally {
            try {
                if (
                    $acknowledgementAuthorized -and
                    $null -ne $guardOwnerHandleLease -and
                    $null -eq $guardOperationState.Lock
                ) {
                    Write-TicketboxDataRootGuardStoppedAcknowledgement `
                        -OwnerHandleLease $guardOwnerHandleLease
                }
            }
            finally {
                Close-TicketboxProcessIdentityHandle $guardOwnerHandleLease
            }
        }
    }
}

if (
    $guardExitReason -cne "control" -and
    $guardExitReason -cne "owner_exit" -and
    $guardExitReason -cne "confirmed_inactive"
) {
    throw "DataRoot guard 返回未知退出原因：$guardExitReason"
}
