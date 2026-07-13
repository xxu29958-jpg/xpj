#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$InstallerOwnerProcessId,
    [Parameter(Mandatory = $true)][uint32]$InstallerOwnerStartedFileTimeHigh,
    [Parameter(Mandatory = $true)][uint32]$InstallerOwnerStartedFileTimeLow,
    [Parameter(Mandatory = $true)][string]$ExpectedLockDirectory,
    [Parameter(Mandatory = $true)][string]$RootValidatedPath,
    [Parameter(Mandatory = $true)][string]$ReadyPath,
    [Parameter(Mandatory = $true)][string]$ReleasePath
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"
$LockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
foreach ($dependency in @($SafetyScript, $LockScript)) {
    if (-not (Test-Path -LiteralPath $dependency -PathType Leaf)) {
        throw "生命周期锁 holder 缺少依赖：$dependency"
    }
}
. $SafetyScript
. $LockScript

$parentProcessId = Get-TicketboxParentProcessId
if ($parentProcessId -ne $InstallerOwnerProcessId) {
    throw "生命周期锁 holder 不是当前安装器的直接子进程。"
}
$expectedParentIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
    -ProcessId $InstallerOwnerProcessId `
    -StartedFileTimeHigh $InstallerOwnerStartedFileTimeHigh `
    -StartedFileTimeLow $InstallerOwnerStartedFileTimeLow
$parentHandleLease = Open-TicketboxVerifiedProcessIdentityHandle `
    -ProcessId $InstallerOwnerProcessId `
    -ExpectedIdentity $expectedParentIdentity
$commonProgramFiles = [Environment]::GetFolderPath(
    [Environment+SpecialFolder]::CommonProgramFiles
)
if ([string]::IsNullOrWhiteSpace($commonProgramFiles)) {
    throw "Windows 未提供 Common Program Files，无法建立安装生命周期锁。"
}
$expectedRoot = Join-Path $commonProgramFiles $script:TicketboxLifecycleLockDirectoryName
if (-not (Test-TicketboxPathEquals $ExpectedLockDirectory $expectedRoot)) {
    throw "Inno 与 PowerShell 解析出的机器生命周期根不一致。"
}

try {
    Wait-TicketboxExternalInstallerLifecycleLock `
        -LockDirectory $expectedRoot `
        -RootValidatedPath $RootValidatedPath `
        -ReadyPath $ReadyPath `
        -ReleasePath $ReleasePath `
        -OwnerProcessId $InstallerOwnerProcessId `
        -OwnerStartedFileTimeHigh $InstallerOwnerStartedFileTimeHigh `
        -OwnerStartedFileTimeLow $InstallerOwnerStartedFileTimeLow `
        -OwnerProcessHandleLease $parentHandleLease
}
finally {
    try {
        if (Test-Path -LiteralPath $RootValidatedPath -PathType Leaf) {
            Remove-TicketboxProtectedUtf8Artifact -Path $RootValidatedPath
        }
    }
    finally {
        Close-TicketboxProcessIdentityHandle $parentHandleLease
    }
}
