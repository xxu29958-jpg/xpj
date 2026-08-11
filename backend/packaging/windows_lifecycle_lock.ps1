#Requires -Version 5.1

<#
.SYNOPSIS
  Machine-wide lifecycle lock shared by installer service scripts.
.DESCRIPTION
  Uses an exclusive file below the OS Common Program Files directory. The
  directory and file are owned by SYSTEM and writable only by SYSTEM/Admins,
  preventing a standard user from pre-creating or read-locking the primitive.
#>

$script:TicketboxLifecycleLockDirectoryName = "Ticketbox"
$script:TicketboxLifecycleLockFileName = "installer-lifecycle.lock"
$script:TicketboxLifecycleLockOwnerFileName = "installer-lifecycle.owner"
$script:TicketboxLifecycleOperationLockFileName = "installer-operation.lock"
$script:TicketboxInstallerStateDirectoryName = "installer-state"
$script:TicketboxLifecycleOwnerRecordSchema = "ticketbox-lifecycle-owner-v2"
$script:TicketboxSharingViolationErrorCode = 32
$script:TicketboxLockViolationErrorCode = 33
$script:TicketboxLifecycleCoordinationReadAttempts = 40
$script:TicketboxLifecycleCoordinationReadDelayMilliseconds = 50
$script:TicketboxValidatedExternalLifecycleOwnerIdentity = $null

function Initialize-TicketboxProcessIdentityNativeMethods {
    if ("TicketboxProcessIdentityNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

[StructLayout(LayoutKind.Sequential)]
public struct TicketboxProcessFileTime
{
    public uint Low;
    public uint High;
}

public static class TicketboxProcessIdentityNativeMethods
{
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern SafeWaitHandle OpenProcess(
        uint desiredAccess,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandle,
        int processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetProcessTimes(
        SafeWaitHandle process,
        out TicketboxProcessFileTime creationTime,
        out TicketboxProcessFileTime exitTime,
        out TicketboxProcessFileTime kernelTime,
        out TicketboxProcessFileTime userTime);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint WaitForSingleObject(
        SafeWaitHandle handle,
        uint milliseconds);
}
'@
}

function Assert-TicketboxPowerShellBitness(
    [bool]$Is64BitOperatingSystem,
    [bool]$Is64BitProcess
) {
    if ($Is64BitOperatingSystem -and -not $Is64BitProcess) {
        throw "小票夹服务脚本必须由 64 位 PowerShell 运行，拒绝使用会分裂机器锁路径的 32 位宿主。"
    }
}

function Assert-TicketboxSupportedPowerShellHost {
    Assert-TicketboxPowerShellBitness `
        -Is64BitOperatingSystem ([Environment]::Is64BitOperatingSystem) `
        -Is64BitProcess ([Environment]::Is64BitProcess)
}

function Initialize-TicketboxLifecycleLockDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$LockDirectory,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    Assert-NoTicketboxAncestorReparsePoints $LockDirectory
    if (Test-Path -LiteralPath $LockDirectory) {
        $validationLease = Enter-TicketboxDirectoryMutationGuard -Path $LockDirectory
        try {
            Assert-TicketboxProtectedDirectoryAcl `
                -Path $LockDirectory `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
        }
        finally { $validationLease.Dispose() }
    }
    else {
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $LockDirectory `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount | Out-Null
    }
    return [System.IO.Path]::GetFullPath($LockDirectory)
}

function Get-TicketboxLifecycleLockPath {
    Assert-TicketboxSupportedPowerShellHost
    $commonProgramFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonProgramFiles
    )
    if ([string]::IsNullOrWhiteSpace($commonProgramFiles)) {
        throw "Windows 未提供 Common Program Files，无法建立安装生命周期锁。"
    }
    $lockDirectory = Join-Path $commonProgramFiles $script:TicketboxLifecycleLockDirectoryName
    $lockDirectory = Initialize-TicketboxLifecycleLockDirectory `
        -LockDirectory $lockDirectory
    return Join-Path $lockDirectory $script:TicketboxLifecycleLockFileName
}

function Get-TicketboxLifecycleLockOwnerPath {
    $lockPath = Get-TicketboxLifecycleLockPath
    return Join-Path (Split-Path -Parent $lockPath) $script:TicketboxLifecycleLockOwnerFileName
}

function Get-TicketboxLifecycleOperationLockPath {
    $lockPath = Get-TicketboxLifecycleLockPath
    return Join-Path (Split-Path -Parent $lockPath) $script:TicketboxLifecycleOperationLockFileName
}

function Get-TicketboxInstallerStateDirectory {
    $lockPath = Get-TicketboxLifecycleLockPath
    return Join-Path `
        (Split-Path -Parent $lockPath) `
        $script:TicketboxInstallerStateDirectoryName
}

function New-TicketboxProcessIdentityFromFileTimeParts {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$ProcessId,
        [Parameter(Mandatory = $true)][uint32]$StartedFileTimeHigh,
        [Parameter(Mandatory = $true)][uint32]$StartedFileTimeLow
    )

    $fileTime =
        ([uint64]$StartedFileTimeHigh * [uint64]4294967296) +
        [uint64]$StartedFileTimeLow
    if ($fileTime -gt [uint64][int64]::MaxValue) {
        throw "Windows 进程创建 FILETIME 超出可表示范围。"
    }
    try { $startedUtc = [DateTime]::FromFileTimeUtc([int64]$fileTime) }
    catch { throw "Windows 进程创建 FILETIME 无效。" }
    return [pscustomobject]@{
        ProcessId = $ProcessId
        StartedFileTimeHigh = $StartedFileTimeHigh
        StartedFileTimeLow = $StartedFileTimeLow
        StartedUtc = $startedUtc.ToString(
            "yyyy-MM-ddTHH:mm:ss.fffffffZ",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    }
}

function Get-TicketboxProcessIdentity {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$ProcessId,
        [object]$Process
    )

    if ($null -eq $Process) {
        $Process = Get-Process -Id $ProcessId -ErrorAction Stop
    }
    if ([int]$Process.Id -ne $ProcessId) {
        throw "Windows 进程对象与预期 PID 不一致。"
    }
    try { $fileTime = [uint64]$Process.StartTime.ToFileTimeUtc() }
    catch { throw "无法读取 Windows 进程创建时间，拒绝建立生命周期身份。" }
    return New-TicketboxProcessIdentityFromFileTimeParts `
        -ProcessId $ProcessId `
        -StartedFileTimeHigh ([uint32]($fileTime -shr 32)) `
        -StartedFileTimeLow ([uint32]($fileTime -band [uint64]4294967295))
}

function Test-TicketboxProcessIdentityEquals([object]$Left, [object]$Right) {
    return (
        [int]$Left.ProcessId -eq [int]$Right.ProcessId -and
        [uint32]$Left.StartedFileTimeHigh -eq [uint32]$Right.StartedFileTimeHigh -and
        [uint32]$Left.StartedFileTimeLow -eq [uint32]$Right.StartedFileTimeLow
    )
}

function Open-TicketboxVerifiedProcessIdentityHandle {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$ProcessId,
        [Parameter(Mandatory = $true)][object]$ExpectedIdentity
    )

    Initialize-TicketboxProcessIdentityNativeMethods
    if ([int]$ExpectedIdentity.ProcessId -ne $ProcessId) {
        throw "预期 Windows 进程身份与 PID 参数不一致。"
    }
    $synchronize = [uint32]0x00100000
    $queryLimitedInformation = [uint32]0x00001000
    $handle = [TicketboxProcessIdentityNativeMethods]::OpenProcess(
        ($synchronize -bor $queryLimitedInformation),
        $false,
        $ProcessId
    )
    if ($null -eq $handle -or $handle.IsInvalid) {
        $nativeError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        if ($null -ne $handle) { $handle.Dispose() }
        throw "无法打开 Windows 进程身份句柄（Win32 error=$nativeError，PID=$ProcessId）。"
    }
    try {
        $creationTime = New-Object TicketboxProcessFileTime
        $exitTime = New-Object TicketboxProcessFileTime
        $kernelTime = New-Object TicketboxProcessFileTime
        $userTime = New-Object TicketboxProcessFileTime
        if (-not [TicketboxProcessIdentityNativeMethods]::GetProcessTimes(
            $handle,
            [ref]$creationTime,
            [ref]$exitTime,
            [ref]$kernelTime,
            [ref]$userTime
        )) {
            $nativeError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw "无法读取 Windows 进程句柄创建时间（Win32 error=$nativeError，PID=$ProcessId）。"
        }
        $actualIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
            -ProcessId $ProcessId `
            -StartedFileTimeHigh ([uint32]$creationTime.High) `
            -StartedFileTimeLow ([uint32]$creationTime.Low)
        if (-not (Test-TicketboxProcessIdentityEquals $actualIdentity $ExpectedIdentity)) {
            throw "Windows 进程 PID 已复用或创建时间与预期身份不匹配。"
        }
        return [pscustomobject]@{
            Handle = $handle
            Identity = $actualIdentity
        }
    }
    catch {
        $handle.Dispose()
        throw
    }
}

function Test-TicketboxProcessIdentityHandleExited([object]$HandleLease) {
    if ($null -eq $HandleLease -or $null -eq $HandleLease.Handle -or $HandleLease.Handle.IsInvalid) {
        throw "Windows 进程身份句柄租约无效。"
    }
    $waitResult = [TicketboxProcessIdentityNativeMethods]::WaitForSingleObject(
        $HandleLease.Handle,
        [uint32]0
    )
    if ($waitResult -eq [uint32]0) { return $true }
    if ($waitResult -eq [uint32]258) { return $false }
    $nativeError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw "无法等待 Windows 进程身份句柄（result=$waitResult，Win32 error=$nativeError）。"
}

function Close-TicketboxProcessIdentityHandle([object]$HandleLease) {
    if ($null -ne $HandleLease -and $null -ne $HandleLease.Handle) {
        $HandleLease.Handle.Dispose()
    }
}

function ConvertTo-TicketboxLifecycleLockOwnerRecordText([object]$Identity) {
    return [string]::Join([Environment]::NewLine, @(
        "SCHEMA=$script:TicketboxLifecycleOwnerRecordSchema",
        "OWNER_PID=$([int]$Identity.ProcessId)",
        "OWNER_STARTED_FILETIME_HIGH=$([uint32]$Identity.StartedFileTimeHigh)",
        "OWNER_STARTED_FILETIME_LOW=$([uint32]$Identity.StartedFileTimeLow)"
    )) + [Environment]::NewLine
}

function Read-TicketboxLifecycleLockOwnerRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount `
        -MaximumBytes 512
    $newline = [regex]::Escape([Environment]::NewLine)
    $pattern =
        "\ASCHEMA=$([regex]::Escape($script:TicketboxLifecycleOwnerRecordSchema))$newline" +
        "OWNER_PID=([1-9][0-9]*)$newline" +
        "OWNER_STARTED_FILETIME_HIGH=([0-9]+)$newline" +
        "OWNER_STARTED_FILETIME_LOW=([0-9]+)$newline\z"
    $match = [regex]::Match($artifact.Text, $pattern)
    if (-not $match.Success) {
        throw "生命周期锁所有者记录格式无效：$Path"
    }
    $ownerProcessId = 0
    $startedHigh = [uint32]0
    $startedLow = [uint32]0
    if (
        -not [int]::TryParse(
            $match.Groups[1].Value,
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$ownerProcessId
        ) -or
        $ownerProcessId -le 0 -or
        -not [uint32]::TryParse(
            $match.Groups[2].Value,
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$startedHigh
        ) -or
        -not [uint32]::TryParse(
            $match.Groups[3].Value,
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$startedLow
        )
    ) {
        throw "生命周期锁所有者记录数值超出有效范围：$Path"
    }
    $identity = New-TicketboxProcessIdentityFromFileTimeParts `
        -ProcessId $ownerProcessId `
        -StartedFileTimeHigh $startedHigh `
        -StartedFileTimeLow $startedLow
    if ((ConvertTo-TicketboxLifecycleLockOwnerRecordText $identity) -cne $artifact.Text) {
        throw "生命周期锁所有者记录不是规范编码：$Path"
    }
    return $identity
}

function Read-TicketboxLifecycleLockOwnerProcessId([string]$Path) {
    return [int](Read-TicketboxLifecycleLockOwnerRecord -Path $Path).ProcessId
}

function Get-TicketboxParentProcessId {
    $processes = @(
        Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $PID" `
            -ErrorAction Stop
    )
    if ($processes.Count -ne 1) {
        throw "无法唯一确定当前 PowerShell 的父进程，拒绝复用安装器生命周期锁。"
    }
    return [int]$processes[0].ParentProcessId
}

function Assert-TicketboxLifecycleLockIsHeld([string]$Path) {
    $probe = $null
    try {
        $probe = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        $nativeError = $_.Exception.HResult -band 0xFFFF
        if ($nativeError -eq $script:TicketboxSharingViolationErrorCode) {
            return
        }
        throw "无法确认安装器生命周期锁状态（Win32 error=$nativeError）：$Path"
    }
    finally {
        if ($null -ne $probe) {
            $probe.Dispose()
        }
    }
    throw "安装器声称持有生命周期锁，但锁文件当前可被独占打开：$Path"
}

function Assert-TicketboxExternalLifecycleLock {
    param(
        [Parameter(Mandatory = $true)][int]$OwnerProcessId,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )
    if ($OwnerProcessId -le 0) {
        throw "外部生命周期锁所有者进程 ID 必须为正整数。"
    }
    $lockPath = Get-TicketboxLifecycleLockPath
    $ownerPath = Get-TicketboxLifecycleLockOwnerPath
    $recordedOwner = Read-TicketboxLifecycleLockOwnerRecord `
        -Path $ownerPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    if ([int]$recordedOwner.ProcessId -ne $OwnerProcessId) {
        throw "生命周期锁所有者记录与安装器参数不一致。"
    }
    $parentProcessId = Get-TicketboxParentProcessId
    if ($parentProcessId -ne $OwnerProcessId) {
        throw "当前 PowerShell 不是持锁安装器的直接子进程，拒绝复用生命周期锁。"
    }
    try { $ownerProcess = Get-Process -Id $OwnerProcessId -ErrorAction Stop }
    catch {
        throw "生命周期锁所有者进程已退出，拒绝继续。"
    }
    $actualOwner = Get-TicketboxProcessIdentity `
        -ProcessId $OwnerProcessId `
        -Process $ownerProcess
    if (-not (Test-TicketboxProcessIdentityEquals $actualOwner $recordedOwner)) {
        throw "生命周期锁所有者 PID 已复用或创建时间不匹配。"
    }
    Assert-TicketboxLifecycleLockIsHeld $lockPath
    return $recordedOwner
}

function Get-TicketboxValidatedExternalLifecycleOwnerIdentity([int]$OwnerProcessId) {
    $identity = $script:TicketboxValidatedExternalLifecycleOwnerIdentity
    if (
        $null -eq $identity -or
        [int]$identity.ProcessId -ne $OwnerProcessId
    ) {
        throw "当前 mutation 没有已验证的安装器生命周期身份。"
    }
    return $identity
}

function Enter-TicketboxExclusiveFileLock([string]$Path) {
    try {
        return [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        throw "另一项小票夹安装、升级或卸载操作正在进行。"
    }
}

function Enter-TicketboxProtectedExclusiveFileLock {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    Assert-NoTicketboxAncestorReparsePoints $parent
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $parent `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    $entryKind = Get-TicketboxPathEntryKindNoFollow $fullPath
    if ($entryKind -cne "Missing") {
        if ($entryKind -cne "File") {
            throw "生命周期锁路径存在但不是普通文件：$fullPath ($entryKind)"
        }
        Assert-TicketboxExactFileAcl `
            -Path $fullPath `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        return Enter-TicketboxExclusiveFileLock $fullPath
    }

    $security = New-TicketboxProtectedFileSecurity `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    try {
        $stream = New-TicketboxProtectedFileStream `
            -Path $fullPath `
            -Security $security
    }
    catch [System.IO.IOException] {
        $entryKind = Get-TicketboxPathEntryKindNoFollow $fullPath
        if ($entryKind -cne "File") {
            throw "另一项小票夹安装、升级或卸载操作正在进行。"
        }
        Assert-TicketboxExactFileAcl `
            -Path $fullPath `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        return Enter-TicketboxExclusiveFileLock $fullPath
    }
    try {
        Set-TicketboxOwnerIfNeeded `
            -Path $fullPath `
            -ExpectedOwnerSid (ConvertTo-TicketboxAccountSid $OwnerAccount)
        Assert-TicketboxExactFileAcl `
            -Path $fullPath `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        return $stream
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Write-TicketboxLifecycleLockOwnerRecord {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$OwnerIdentity,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $replaceExisting = Test-Path -LiteralPath $Path
    if ($replaceExisting) {
        Read-TicketboxProtectedUtf8Artifact `
            -Path $Path `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount `
            -MaximumBytes 512 | Out-Null
    }
    $ownerText = ConvertTo-TicketboxLifecycleLockOwnerRecordText $OwnerIdentity
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $ownerText `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount `
        -ReplaceExisting:$replaceExisting
    $persisted = Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount `
        -MaximumBytes 512
    if ($persisted.Text -cne $ownerText) {
        throw "生命周期锁所有者记录写后复读不一致。"
    }
}

function Write-TicketboxLifecycleCoordinationArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "生命周期锁 IPC 父目录不存在：$parent"
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $fullPath `
        -Text $Text `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
}

function Read-TicketboxLifecycleCoordinationArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    for (
        $attempt = 1;
        $attempt -le $script:TicketboxLifecycleCoordinationReadAttempts;
        $attempt++
    ) {
        try {
            $artifact = Read-TicketboxProtectedUtf8Artifact `
                -Path $Path `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount `
                -MaximumBytes 256
            return $artifact.Text
        }
        catch {
            $nativeError = $_.Exception.GetBaseException().HResult -band 0xFFFF
            if (
                $nativeError -notin @(
                    $script:TicketboxSharingViolationErrorCode,
                    $script:TicketboxLockViolationErrorCode
                ) -or
                $attempt -eq $script:TicketboxLifecycleCoordinationReadAttempts
            ) {
                throw
            }
        }
        Start-Sleep `
            -Milliseconds $script:TicketboxLifecycleCoordinationReadDelayMilliseconds
    }
    throw "生命周期锁 IPC 读取重试循环异常退出：$Path"
}

function New-TicketboxLifecycleCoordinationNonce {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return -join @($bytes | ForEach-Object { $_.ToString("x2") })
}

function Wait-TicketboxExternalInstallerLifecycleLock {
    param(
        [Parameter(Mandatory = $true)][string]$LockDirectory,
        [Parameter(Mandatory = $true)][string]$RootValidatedPath,
        [Parameter(Mandatory = $true)][string]$ReadyPath,
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$OwnerProcessId,
        [Parameter(Mandatory = $true)][uint32]$OwnerStartedFileTimeHigh,
        [Parameter(Mandatory = $true)][uint32]$OwnerStartedFileTimeLow,
        [Parameter(Mandatory = $true)][object]$OwnerProcessHandleLease,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $readyFullPath = [System.IO.Path]::GetFullPath($ReadyPath)
    $releaseFullPath = [System.IO.Path]::GetFullPath($ReleasePath)
    $rootValidatedFullPath = [System.IO.Path]::GetFullPath($RootValidatedPath)
    if (Test-TicketboxPathEquals $readyFullPath $releaseFullPath) {
        throw "生命周期锁 ready/release IPC 不能使用同一路径。"
    }
    if (-not (Test-TicketboxPathEquals `
        (Split-Path -Parent $readyFullPath) `
        (Split-Path -Parent $releaseFullPath)
    )) {
        throw "生命周期锁 ready/release IPC 必须位于同一目录。"
    }
    $lockRoot = Initialize-TicketboxLifecycleLockDirectory `
        -LockDirectory $LockDirectory `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    $coordinationDirectory = Split-Path -Parent $readyFullPath
    if (-not (Test-TicketboxPathEquals $coordinationDirectory $lockRoot)) {
        throw "生命周期锁 IPC 必须位于已验证的机器级锁根。"
    }
    if (
        (Test-Path -LiteralPath $readyFullPath) -or
        (Test-Path -LiteralPath $releaseFullPath)
    ) {
        throw "生命周期锁 IPC artifact 已存在，拒绝复用。"
    }
    $validationDirectory = Split-Path -Parent $rootValidatedFullPath
    if (Test-TicketboxPathWithin $validationDirectory $lockRoot) {
        throw "机器根验证信号必须位于独立的受保护 transient 目录。"
    }
    Assert-NoTicketboxAncestorReparsePoints $validationDirectory
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $validationDirectory `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    if (Test-Path -LiteralPath $rootValidatedFullPath) {
        throw "机器根验证信号已存在，拒绝复用。"
    }
    $rootValidatedText =
        "STATE=root_validated$([Environment]::NewLine)" +
        "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)"
    Write-TicketboxLifecycleCoordinationArtifact `
        -Path $rootValidatedFullPath `
        -Text $rootValidatedText `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    $lockPath = Join-Path $lockRoot $script:TicketboxLifecycleLockFileName
    $ownerPath = Join-Path $lockRoot $script:TicketboxLifecycleLockOwnerFileName
    $expectedOwnerIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
        -ProcessId $OwnerProcessId `
        -StartedFileTimeHigh $OwnerStartedFileTimeHigh `
        -StartedFileTimeLow $OwnerStartedFileTimeLow
    $ownerIdentity = $OwnerProcessHandleLease.Identity
    if (
        -not (Test-TicketboxProcessIdentityEquals $ownerIdentity $expectedOwnerIdentity) -or
        (Test-TicketboxProcessIdentityHandleExited $OwnerProcessHandleLease)
    ) {
        throw "生命周期锁 holder 观察到的安装器创建时间与启动参数不匹配。"
    }
    $ownerRecordText = ConvertTo-TicketboxLifecycleLockOwnerRecordText $ownerIdentity
    $primaryLock = Enter-TicketboxProtectedExclusiveFileLock `
        -Path $lockPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    try {
        Write-TicketboxLifecycleLockOwnerRecord `
            -Path $ownerPath `
            -OwnerIdentity $ownerIdentity `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        $coordinationNonce = New-TicketboxLifecycleCoordinationNonce
        $holderIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
        $readyText =
            "STATE=holding$([Environment]::NewLine)" +
            "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)" +
            "HOLDER_PID=$PID$([Environment]::NewLine)" +
            "HOLDER_STARTED_FILETIME_HIGH=$($holderIdentity.StartedFileTimeHigh)$([Environment]::NewLine)" +
            "HOLDER_STARTED_FILETIME_LOW=$($holderIdentity.StartedFileTimeLow)$([Environment]::NewLine)" +
            "INSTALLER_STATE=$(Join-Path $lockRoot $script:TicketboxInstallerStateDirectoryName)$([Environment]::NewLine)" +
            "NONCE=$coordinationNonce$([Environment]::NewLine)"
        Write-TicketboxLifecycleCoordinationArtifact `
            -Path $readyFullPath `
            -Text $readyText `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        $expectedRelease =
            "STATE=release$([Environment]::NewLine)" +
            "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)" +
            "NONCE=$coordinationNonce$([Environment]::NewLine)"
        $operationLockPath = Join-Path $lockRoot $script:TicketboxLifecycleOperationLockFileName
        $releaseAccepted = $false
        while ($true) {
            if (-not $releaseAccepted -and (Test-Path -LiteralPath $releaseFullPath)) {
                $releaseText = Read-TicketboxLifecycleCoordinationArtifact `
                    -Path $releaseFullPath `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount
                if ($releaseText -cne $expectedRelease) {
                    throw "生命周期锁 release IPC 与当前安装器身份不匹配。"
                }
                $releaseAccepted = $true
            }
            if (
                $releaseAccepted -or
                (Test-TicketboxProcessIdentityHandleExited $OwnerProcessHandleLease)
            ) {
                if (-not (Test-TicketboxExclusiveFileLockHeld -Path $operationLockPath)) {
                    return
                }
            }
            Start-Sleep -Milliseconds 100
        }
    }
    finally {
        try {
            if (Test-Path -LiteralPath $ownerPath) {
                $persistedOwner = Read-TicketboxProtectedUtf8Artifact `
                    -Path $ownerPath `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount `
                    -MaximumBytes 512
                if ($persistedOwner.Text -ceq $ownerRecordText) {
                    Remove-TicketboxProtectedUtf8Artifact `
                        -Path $ownerPath `
                        -FullControlAccounts $FullControlAccounts `
                        -OwnerAccount $OwnerAccount
                }
            }
        }
        finally {
            try {
                foreach ($coordinationPath in @($readyFullPath, $releaseFullPath)) {
                    if (Test-Path -LiteralPath $coordinationPath -PathType Leaf) {
                        Remove-TicketboxProtectedUtf8Artifact `
                            -Path $coordinationPath `
                            -FullControlAccounts $FullControlAccounts `
                            -OwnerAccount $OwnerAccount
                    }
                }
            }
            finally {
                $primaryLock.Dispose()
            }
        }
    }
}

function Enter-TicketboxLifecycleLock(
    [int]$ExternalOwnerProcessId = 0,
    [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
    [string]$OwnerAccount = "SYSTEM"
) {
    if ($ExternalOwnerProcessId -lt 0) {
        throw "外部生命周期锁所有者进程 ID 不能为负数。"
    }
    $primaryLock = $null
    $operationLock = $null
    $validatedExternalOwnerIdentity = $null
    try {
        if ($ExternalOwnerProcessId -gt 0) {
            # Acquire the delegated-operation lease before validating the parent.
            # If the parent exits in this window, the holder observes this lease
            # and keeps both machine and DataRoot authority until validation fails
            # or the already-authorized operation returns.
            $operationLockPath = Get-TicketboxLifecycleOperationLockPath
            $operationLock = Enter-TicketboxProtectedExclusiveFileLock `
                -Path $operationLockPath `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            $validatedExternalOwnerIdentity =
                Assert-TicketboxExternalLifecycleLock `
                    -OwnerProcessId $ExternalOwnerProcessId `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount
        }
        else {
            $script:TicketboxValidatedExternalLifecycleOwnerIdentity = $null
            $lockPath = Get-TicketboxLifecycleLockPath
            $primaryLock = Enter-TicketboxProtectedExclusiveFileLock `
                -Path $lockPath `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            $operationLockPath = Get-TicketboxLifecycleOperationLockPath
            $operationLock = Enter-TicketboxProtectedExclusiveFileLock `
                -Path $operationLockPath `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
        }
        Remove-TicketboxProtectedStagingArtifacts `
            -Path (Split-Path -Parent $operationLockPath) `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        $script:TicketboxValidatedExternalLifecycleOwnerIdentity =
            $validatedExternalOwnerIdentity
        return [pscustomobject]@{
            Primary = $primaryLock
            Operation = $operationLock
            ExternalOwnerIdentity = $validatedExternalOwnerIdentity
        }
    }
    catch {
        $script:TicketboxValidatedExternalLifecycleOwnerIdentity = $null
        if ($null -ne $operationLock) {
            $operationLock.Dispose()
        }
        if ($null -ne $primaryLock) {
            $primaryLock.Dispose()
        }
        throw
    }
}

function Exit-TicketboxLifecycleLock($Lock) {
    if ($null -eq $Lock) {
        return
    }
    if ($Lock -is [System.IO.FileStream]) {
        $Lock.Dispose()
        return
    }
    if ($null -ne $Lock.Operation) {
        $Lock.Operation.Dispose()
    }
    if ($null -ne $Lock.Primary) {
        $Lock.Primary.Dispose()
    }
    $script:TicketboxValidatedExternalLifecycleOwnerIdentity = $null
}
