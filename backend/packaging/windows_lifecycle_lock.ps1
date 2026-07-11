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
$script:TicketboxSharingViolationErrorCode = 32

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

function Get-TicketboxLifecycleLockPath {
    Assert-TicketboxSupportedPowerShellHost
    $commonProgramFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonProgramFiles
    )
    if ([string]::IsNullOrWhiteSpace($commonProgramFiles)) {
        throw "Windows 未提供 Common Program Files，无法建立安装生命周期锁。"
    }
    $lockDirectory = Join-Path $commonProgramFiles $script:TicketboxLifecycleLockDirectoryName
    Assert-NoTicketboxAncestorReparsePoints $lockDirectory
    if (-not (Test-Path -LiteralPath $lockDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $lockDirectory -ErrorAction Stop | Out-Null
    }
    Assert-NoTicketboxAncestorReparsePoints $lockDirectory
    Set-TicketboxExactDirectoryAcl `
        -Path $lockDirectory `
        -Accounts @("SYSTEM", "BUILTIN\Administrators")
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

function Read-TicketboxLifecycleLockOwnerProcessId([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "安装器声称持有生命周期锁，但锁所有者记录不存在：$Path"
    }
    $ownerFile = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($ownerFile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "生命周期锁所有者记录不能是重解析点：$Path"
    }
    if ($ownerFile.Length -gt 32) {
        throw "生命周期锁所有者记录格式无效：$Path"
    }
    $rawOwner = [System.IO.File]::ReadAllText($Path).Trim()
    if ($rawOwner -notmatch '^[1-9][0-9]*$') {
        throw "生命周期锁所有者记录格式无效：$Path"
    }
    try {
        return [int]$rawOwner
    }
    catch {
        throw "生命周期锁所有者进程 ID 超出有效范围：$Path"
    }
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

function Assert-TicketboxExternalLifecycleLock([int]$OwnerProcessId) {
    if ($OwnerProcessId -le 0) {
        throw "外部生命周期锁所有者进程 ID 必须为正整数。"
    }
    $lockPath = Get-TicketboxLifecycleLockPath
    $ownerPath = Get-TicketboxLifecycleLockOwnerPath
    $recordedOwnerProcessId = Read-TicketboxLifecycleLockOwnerProcessId $ownerPath
    if ($recordedOwnerProcessId -ne $OwnerProcessId) {
        throw "生命周期锁所有者记录与安装器参数不一致。"
    }
    $parentProcessId = Get-TicketboxParentProcessId
    if ($parentProcessId -ne $OwnerProcessId) {
        throw "当前 PowerShell 不是持锁安装器的直接子进程，拒绝复用生命周期锁。"
    }
    try {
        Get-Process -Id $OwnerProcessId -ErrorAction Stop | Out-Null
    }
    catch {
        throw "生命周期锁所有者进程已退出，拒绝继续。"
    }
    Assert-TicketboxLifecycleLockIsHeld $lockPath
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

function Enter-TicketboxLifecycleLock([int]$ExternalOwnerProcessId = 0) {
    if ($ExternalOwnerProcessId -lt 0) {
        throw "外部生命周期锁所有者进程 ID 不能为负数。"
    }
    $primaryLock = $null
    $operationLock = $null
    try {
        if ($ExternalOwnerProcessId -gt 0) {
            Assert-TicketboxExternalLifecycleLock $ExternalOwnerProcessId
        }
        else {
            $lockPath = Get-TicketboxLifecycleLockPath
            $primaryLock = Enter-TicketboxExclusiveFileLock $lockPath
            Set-TicketboxExactFileAcl `
                -Path $lockPath `
                -Accounts @("SYSTEM", "BUILTIN\Administrators")
        }
        $operationLockPath = Get-TicketboxLifecycleOperationLockPath
        $operationLock = Enter-TicketboxExclusiveFileLock $operationLockPath
        Set-TicketboxExactFileAcl `
            -Path $operationLockPath `
            -Accounts @("SYSTEM", "BUILTIN\Administrators")
        return [pscustomobject]@{
            Primary = $primaryLock
            Operation = $operationLock
        }
    }
    catch {
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
}
