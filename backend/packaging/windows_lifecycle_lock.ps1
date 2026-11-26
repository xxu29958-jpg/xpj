#Requires -Version 5.1

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
