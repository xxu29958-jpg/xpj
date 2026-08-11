#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$InstallerOwnerProcessId,
    [Parameter(Mandatory = $true)][uint32]$InstallerOwnerStartedFileTimeHigh,
    [Parameter(Mandatory = $true)][uint32]$InstallerOwnerStartedFileTimeLow,
    [Parameter(Mandatory = $true)][string]$ExpectedLockDirectory,
    [Parameter(Mandatory = $true)][string]$RootValidatedPath,
    [Parameter(Mandatory = $true)][string]$ReadyPath,
    [Parameter(Mandatory = $true)][string]$ReleasePath,
    [Parameter(Mandatory = $true)][string]$FailurePath
)

$ErrorActionPreference = "Stop"

function Write-TicketboxLifecycleHolderStartupFailure([string]$Message) {
    $temporaryPath = $null
    try {
        $failureFullPath = [System.IO.Path]::GetFullPath($FailurePath)
        $validatedRootParent = [System.IO.Path]::GetFullPath(
            (Split-Path -Parent $RootValidatedPath)
        )
        if (
            -not [string]::Equals(
                (Split-Path -Parent $failureFullPath),
                $validatedRootParent,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            (Split-Path -Leaf $failureFullPath) -cne "lifecycle-holder-failure.txt"
        ) {
            return
        }
        $safeMessage = ($Message -replace "[`r`n`0]", " ").Trim()
        if ([string]::IsNullOrWhiteSpace($safeMessage)) {
            $safeMessage = "生命周期锁 holder 启动失败。"
        }
        if ($safeMessage.Length -gt 512) {
            $safeMessage = $safeMessage.Substring(0, 512)
        }
        $errorCode = "holder_start_failed"
        if ($safeMessage -match "SeRestorePrivilege") {
            $errorCode = "restore_privilege_unavailable"
        }
        elseif ($safeMessage -match "直接子进程|创建时间") {
            $errorCode = "installer_identity_invalid"
        }
        elseif ($safeMessage -match "机器生命周期根|Common Program Files") {
            $errorCode = "machine_root_invalid"
        }
        elseif ($safeMessage -match "缺少依赖") {
            $errorCode = "bootstrap_dependency_missing"
        }
        $safeMessage = -join @(
            foreach ($character in $safeMessage.ToCharArray()) {
                $value = [int]$character
                if ($value -ge 32 -and $value -le 126) {
                    $character
                }
                else {
                    "?"
                }
            }
        )
        $failureText = [string]::Join([Environment]::NewLine, @(
            "SCHEMA=ticketbox-lifecycle-holder-failure-v1",
            "STATE=failed",
            "OWNER_PID=$InstallerOwnerProcessId",
            "OWNER_STARTED_FILETIME_HIGH=$InstallerOwnerStartedFileTimeHigh",
            "OWNER_STARTED_FILETIME_LOW=$InstallerOwnerStartedFileTimeLow",
            "ERROR_CODE=$errorCode",
            "MESSAGE=$safeMessage"
        )) + [Environment]::NewLine
        $temporaryPath = "$failureFullPath.$PID.$([Guid]::NewGuid().ToString('N')).tmp"
        $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($failureText)
        $stream = New-Object System.IO.FileStream(
            $temporaryPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None,
            4096,
            [System.IO.FileOptions]::WriteThrough
        )
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
        [System.IO.File]::Move($temporaryPath, $failureFullPath)
        $temporaryPath = $null
    }
    catch {
        # This artifact is diagnostic only. The original fail-closed exception
        # remains authoritative if even protected diagnostic publication fails.
    }
    finally {
        if ($null -ne $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

$parentHandleLease = $null
try {
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
catch {
    Write-TicketboxLifecycleHolderStartupFailure $_.Exception.Message
    throw
}
finally {
    try {
        if (
            (Get-Command Remove-TicketboxProtectedUtf8Artifact -ErrorAction SilentlyContinue) -and
            (Test-Path -LiteralPath $RootValidatedPath -PathType Leaf)
        ) {
            Remove-TicketboxProtectedUtf8Artifact -Path $RootValidatedPath
        }
    }
    finally {
        if (
            ($null -ne $parentHandleLease) -and
            (Get-Command Close-TicketboxProcessIdentityHandle -ErrorAction SilentlyContinue)
        ) {
            Close-TicketboxProcessIdentityHandle $parentHandleLease
        }
    }
}
