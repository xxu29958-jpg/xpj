#Requires -Version 5.1

$script:TicketboxDataRootMarkerName = ".ticketbox-data-root.json"
$script:TicketboxDataRootMarkerSchema = "ticketbox-data-root-v1"
$script:TicketboxPersistentInstallationIdentityName = ".ticketbox-installation-identity"
$script:TicketboxPersistentInstallationIdentitySchema = "ticketbox-installation-identity-v1"
$script:TicketboxPersistentInstallationIdentityAclAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxPersistentInstallationIdentityOwnerAccount = "SYSTEM"

function Initialize-TicketboxDirectoryGuardNativeMethods {
    if ("TicketboxDirectoryGuardNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class TicketboxDirectoryGuardNativeMethods
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);
}
'@
}

function Enter-TicketboxDirectoryMutationGuard {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$CreateMissingDirectories
    )

    Initialize-TicketboxDirectoryGuardNativeMethods
    $canonicalPath = ConvertTo-TicketboxCanonicalPath $Path
    $genericRead = [Convert]::ToUInt32("80000000", 16)
    $pathStack = New-Object "System.Collections.Generic.Stack[string]"
    $cursor = $canonicalPath
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        $pathStack.Push($cursor)
        $parent = [System.IO.Path]::GetDirectoryName($cursor)
        if ([string]::IsNullOrWhiteSpace($parent) -or (Test-TicketboxPathEquals $cursor $parent)) {
            break
        }
        $cursor = $parent
    }
    $handles = New-Object "System.Collections.Generic.List[Microsoft.Win32.SafeHandles.SafeFileHandle]"
    try {
        while ($pathStack.Count -gt 0) {
            $guardedPath = $pathStack.Pop()
            if (-not (Test-Path -LiteralPath $guardedPath)) {
                if (-not $CreateMissingDirectories) {
                    throw "ACL 目标目录链不存在：$guardedPath"
                }
                [System.IO.Directory]::CreateDirectory($guardedPath) | Out-Null
            }
            if (-not (Test-Path -LiteralPath $guardedPath -PathType Container)) {
                throw "ACL 目标目录链节点不是目录：$guardedPath"
            }
            $handle = [TicketboxDirectoryGuardNativeMethods]::CreateFile(
                $guardedPath,
                $genericRead,
                0x3,
                [IntPtr]::Zero,
                3,
                0x02200000,
                [IntPtr]::Zero
            )
            if ($handle.IsInvalid) {
                $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                $handle.Dispose()
                throw "无法锁定 ACL 目标目录链（Win32=$errorCode）：$guardedPath"
            }
            $handles.Add($handle)
            $item = Get-Item -LiteralPath $guardedPath -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "ACL 目标目录链不能包含重解析点：$guardedPath"
            }
        }
        $guard = [pscustomobject]@{ Handles = @($handles) }
        Add-Member -InputObject $guard -MemberType ScriptMethod -Name Dispose -Value {
            foreach ($heldHandle in $this.Handles) { $heldHandle.Dispose() }
        }
        return $guard
    }
    catch {
        foreach ($heldHandle in $handles) { $heldHandle.Dispose() }
        throw
    }
}

function Initialize-TicketboxDurableFileNativeMethods {
    if ("TicketboxDurableFileNativeMethods" -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class TicketboxDurableFileNativeMethods
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileEx(string existingName, string newName, uint flags);

    public static void MoveFileDurable(string existingName, string newName, bool replaceExisting)
    {
        const uint MoveFileReplaceExisting = 0x1;
        const uint MoveFileWriteThrough = 0x8;
        uint flags = MoveFileWriteThrough;
        if (replaceExisting)
        {
            flags |= MoveFileReplaceExisting;
        }
        if (!MoveFileEx(existingName, newName, flags))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }
}
'@
}

function Sync-TicketboxFileDurable([string]$Path) {
    $stream = New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::Read,
        4096,
        [System.IO.FileOptions]::WriteThrough
    )
    try { $stream.Flush($true) } finally { $stream.Dispose() }
}

function Move-TicketboxFileDurable([string]$Source, [string]$Destination, [switch]$ReplaceExisting) {
    Initialize-TicketboxDurableFileNativeMethods
    try {
        [TicketboxDurableFileNativeMethods]::MoveFileDurable(
            $Source,
            $Destination,
            [bool]$ReplaceExisting
        )
    }
    catch {
        throw "无法持久化提交文件：$Destination。$($_.Exception.GetBaseException().Message)"
    }
}

function Write-TicketboxUtf8FileDurable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [scriptblock]$ProtectTemporaryFile,
        [switch]$ReplaceExisting
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    $temporaryPath = Join-Path $parent (".ticketbox-durable-{0}.tmp" -f [Guid]::NewGuid().ToString("N"))
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
    try {
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
        finally { $stream.Dispose() }
        if ($null -ne $ProtectTemporaryFile) { & $ProtectTemporaryFile $temporaryPath }
        if ($ReplaceExisting) {
            Move-TicketboxFileDurable $temporaryPath $fullPath -ReplaceExisting
        }
        else {
            Move-TicketboxFileDurable $temporaryPath $fullPath
        }
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function New-TicketboxProtectedFileSecurity {
    param(
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$ReadExecuteAccounts = @()
    )

    $fullControlSids = @($FullControlAccounts | ForEach-Object {
        New-Object System.Security.Principal.SecurityIdentifier(
            (ConvertTo-TicketboxAccountSid $_)
        )
    })
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        New-Object System.Security.Principal.SecurityIdentifier(
            (ConvertTo-TicketboxAccountSid $_)
        )
    })
    if ($fullControlSids.Count -eq 0) {
        throw "受保护文件至少需要一个 FullControl 账户。"
    }
    $overlap = @($fullControlSids | Where-Object { $_.Value -in $readExecuteSids.Value })
    if ($overlap.Count -gt 0) {
        throw "受保护文件账户不能同时拥有 FullControl 与 ReadExecute。"
    }

    $security = New-Object System.Security.AccessControl.FileSecurity
    $security.SetAccessRuleProtection($true, $false)
    foreach ($sid in $fullControlSids) {
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )))
    }
    foreach ($sid in $readExecuteSids) {
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
            [System.Security.AccessControl.AccessControlType]::Allow
        )))
    }
    return $security
}

function New-TicketboxProtectedFileStream {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][System.Security.AccessControl.FileSecurity]$Security
    )

    if ($PSVersionTable.PSEdition -eq "Core") {
        return [System.IO.FileSystemAclExtensions]::Create(
            (New-Object System.IO.FileInfo($Path)),
            [System.IO.FileMode]::CreateNew,
            [System.Security.AccessControl.FileSystemRights]::Write,
            [System.IO.FileShare]::None,
            4096,
            [System.IO.FileOptions]::WriteThrough,
            $Security
        )
    }
    return New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::CreateNew,
        [System.Security.AccessControl.FileSystemRights]::Write,
        [System.IO.FileShare]::None,
        4096,
        [System.IO.FileOptions]::WriteThrough,
        $Security
    )
}

function Write-TicketboxProtectedUtf8FileDurable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "受保护文件父目录不存在：$parent"
    }
    Assert-NoTicketboxAncestorReparsePoints $parent
    $temporaryPath = Join-Path $parent (".ticketbox-protected-{0}.tmp" -f [Guid]::NewGuid().ToString("N"))
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
    $security = New-TicketboxProtectedFileSecurity `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts
    try {
        $stream = New-TicketboxProtectedFileStream -Path $temporaryPath -Security $security
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally { $stream.Dispose() }
        Move-TicketboxFileDurable $temporaryPath $fullPath
        Set-TicketboxOwnerIfNeeded `
            -Path $fullPath `
            -ExpectedOwnerSid (ConvertTo-TicketboxAccountSid $OwnerAccount)
        Assert-TicketboxExactFileAcl `
            -Path $fullPath `
            -Accounts $FullControlAccounts `
            -ReadExecuteAccounts $ReadExecuteAccounts `
            -OwnerAccount $OwnerAccount
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Assert-TicketboxProtectedDirectoryAcl([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "受保护目录不存在：$Path"
    }
    $expectedSids = @(
        "SYSTEM",
        "BUILTIN\Administrators"
    ) | ForEach-Object { ConvertTo-TicketboxAccountSid $_ }
    $systemSid = ConvertTo-TicketboxAccountSid "SYSTEM"
    $acl = Get-TicketboxPathAcl $Path
    if (
        -not $acl.AreAccessRulesProtected -or
        (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $systemSid
    ) {
        throw "受保护目录 owner 或继承状态不符合 guard lease 契约：$Path"
    }
    foreach ($sid in $expectedSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $ruleSid = $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
            $hasFullControl =
                ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
                [System.Security.AccessControl.FileSystemRights]::FullControl
            $ruleSid -eq $sid -and
                $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and
                $hasFullControl
        })
        if ($matchingRules.Count -eq 0) {
            throw "受保护目录缺少 SYSTEM/Administrators FullControl：$Path"
        }
    }
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        if (
            $ruleSid -notin $expectedSids -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow
        ) {
            throw "受保护目录含有 guard lease 契约外 ACL：$Path ($ruleSid)"
        }
    }
}

function Wait-TicketboxDirectoryMutationGuardLease {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ReadyPath,
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$OwnerProcessId
    )

    $readyFullPath = [System.IO.Path]::GetFullPath($ReadyPath)
    $releaseFullPath = [System.IO.Path]::GetFullPath($ReleasePath)
    $readyParent = Split-Path -Parent $readyFullPath
    $releaseParent = Split-Path -Parent $releaseFullPath
    if (-not (Test-TicketboxPathEquals $readyParent $releaseParent)) {
        throw "DataRoot guard ready/release artifact 必须位于同一受保护目录。"
    }
    Assert-NoTicketboxAncestorReparsePoints $readyParent
    Assert-TicketboxProtectedDirectoryAcl $readyParent
    if (
        (Test-Path -LiteralPath $readyFullPath) -or
        (Test-Path -LiteralPath $releaseFullPath)
    ) {
        throw "DataRoot guard artifact 已存在，拒绝复用可能过期的 lease。"
    }

    $ownerProcess = Get-Process -Id $OwnerProcessId -ErrorAction Stop
    $guard = Enter-TicketboxDirectoryMutationGuard `
        -Path $Path `
        -CreateMissingDirectories
    try {
        $readyText =
            "STATE=holding$([Environment]::NewLine)" +
            "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)"
        Write-TicketboxProtectedUtf8FileDurable `
            -Path $readyFullPath `
            -Text $readyText `
            -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
            -OwnerAccount "SYSTEM"

        while (-not $ownerProcess.HasExited) {
            if (Test-Path -LiteralPath $releaseFullPath -PathType Leaf) {
                Assert-NoTicketboxAncestorReparsePoints $releaseFullPath
                $releaseItem = Get-Item -LiteralPath $releaseFullPath -Force -ErrorAction Stop
                if (($releaseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    throw "DataRoot guard release artifact 不能是重解析点。"
                }
                Assert-TicketboxExactFileAcl `
                    -Path $releaseFullPath `
                    -Accounts @("SYSTEM", "BUILTIN\Administrators") `
                    -OwnerAccount "SYSTEM"
                $expectedRelease =
                    "STATE=release$([Environment]::NewLine)" +
                    "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)"
                $persistedRelease = [System.IO.File]::ReadAllText(
                    $releaseFullPath,
                    [System.Text.Encoding]::UTF8
                )
                if ($persistedRelease -cne $expectedRelease) {
                    throw "DataRoot guard release artifact 内容不匹配当前安装器。"
                }
                return
            }
            Start-Sleep -Milliseconds 100
            $ownerProcess.Refresh()
        }
    }
    finally {
        $guard.Dispose()
        $ownerProcess.Dispose()
    }
}

function Initialize-TicketboxExactTreeDeleteNativeMethods {
    if ("TicketboxExactTreeDeleteNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class TicketboxExactTreeDeleteNativeMethods
{
    private const uint DeleteAccess = 0x00010000;
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileShareRead = 0x00000001;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private const int FileDispositionInfo = 4;
    private const int FileAttributeTagInfo = 9;

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_ATTRIBUTE_TAG_INFO
    {
        public uint FileAttributes;
        public uint ReparseTag;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_DISPOSITION_INFO
    {
        [MarshalAs(UnmanagedType.Bool)]
        public bool DeleteFile;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(
        SafeFileHandle file,
        int informationClass,
        out FILE_ATTRIBUTE_TAG_INFO information,
        uint bufferSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetFileInformationByHandle(
        SafeFileHandle file,
        int informationClass,
        ref FILE_DISPOSITION_INFO information,
        uint bufferSize);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(
        SafeFileHandle file,
        StringBuilder path,
        uint pathLength,
        uint flags);

    public static void DeleteTree(string path, Action rootHandleAcquired)
    {
        string fullPath = NormalizePath(path);
        using (SafeFileHandle root = OpenExact(fullPath))
        {
            VerifyExactPath(root, fullPath);
            if (rootHandleAcquired != null)
            {
                rootHandleAcquired();
            }
            DeleteOpenedNode(fullPath, root);
        }
    }

    private static void DeleteOpenedNode(string path, SafeFileHandle handle)
    {
        FILE_ATTRIBUTE_TAG_INFO attributes = ReadAttributes(handle, path);
        if ((attributes.FileAttributes & FileAttributeReparsePoint) != 0)
        {
            throw new IOException("Refusing to delete a reparse point: " + path);
        }
        if ((attributes.FileAttributes & FileAttributeDirectory) != 0)
        {
            foreach (string childPath in Directory.GetFileSystemEntries(path))
            {
                using (SafeFileHandle child = OpenExact(childPath))
                {
                    VerifyExactPath(child, childPath);
                    DeleteOpenedNode(childPath, child);
                }
            }
        }

        FILE_DISPOSITION_INFO disposition = new FILE_DISPOSITION_INFO();
        disposition.DeleteFile = true;
        if (!SetFileInformationByHandle(
            handle,
            FileDispositionInfo,
            ref disposition,
            (uint)Marshal.SizeOf(typeof(FILE_DISPOSITION_INFO))))
        {
            ThrowLastWin32("Unable to delete the exact opened path", path);
        }
    }

    private static SafeFileHandle OpenExact(string path)
    {
        SafeFileHandle handle = CreateFile(
            path,
            DeleteAccess | FileReadAttributes,
            FileShareRead,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            int error = Marshal.GetLastWin32Error();
            handle.Dispose();
            throw new Win32Exception(error, "Unable to open the exact deletion target: " + path);
        }
        return handle;
    }

    private static FILE_ATTRIBUTE_TAG_INFO ReadAttributes(SafeFileHandle handle, string path)
    {
        FILE_ATTRIBUTE_TAG_INFO attributes;
        if (!GetFileInformationByHandleEx(
            handle,
            FileAttributeTagInfo,
            out attributes,
            (uint)Marshal.SizeOf(typeof(FILE_ATTRIBUTE_TAG_INFO))))
        {
            ThrowLastWin32("Unable to inspect the exact opened path", path);
        }
        return attributes;
    }

    private static void VerifyExactPath(SafeFileHandle handle, string expectedPath)
    {
        StringBuilder buffer = new StringBuilder(512);
        uint length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Capacity, 0);
        if (length == 0)
        {
            ThrowLastWin32("Unable to resolve the exact opened path", expectedPath);
        }
        if (length >= buffer.Capacity)
        {
            buffer = new StringBuilder((int)length + 1);
            length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Capacity, 0);
            if (length == 0 || length >= buffer.Capacity)
            {
                ThrowLastWin32("Unable to resolve the exact opened path", expectedPath);
            }
        }
        string actualPath = NormalizeFinalPath(buffer.ToString());
        if (!String.Equals(
            actualPath,
            NormalizePath(expectedPath),
            StringComparison.OrdinalIgnoreCase))
        {
            throw new IOException(
                "Opened deletion target resolved outside the requested path: " +
                expectedPath + " -> " + actualPath);
        }
    }

    private static string NormalizeFinalPath(string path)
    {
        if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            path = @"\\" + path.Substring(8);
        }
        else if (path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
        {
            path = path.Substring(4);
        }
        return NormalizePath(path);
    }

    private static string NormalizePath(string path)
    {
        string fullPath = Path.GetFullPath(path);
        string root = Path.GetPathRoot(fullPath);
        if (String.Equals(fullPath, root, StringComparison.OrdinalIgnoreCase))
        {
            return fullPath;
        }
        return fullPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static void ThrowLastWin32(string operation, string path)
    {
        int error = Marshal.GetLastWin32Error();
        throw new Win32Exception(error, operation + ": " + path);
    }
}
'@
}

function Remove-TicketboxDataRootExact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [scriptblock]$OnRootHandleAcquired
    )

    $canonicalPath = ConvertTo-TicketboxCanonicalPath $Path
    if (-not (Test-Path -LiteralPath $canonicalPath)) {
        return
    }
    if (-not (Test-Path -LiteralPath $canonicalPath -PathType Container)) {
        throw "数据删除目标不是目录：$canonicalPath"
    }
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $callback = $null
    if ($null -ne $OnRootHandleAcquired) {
        $callbackScript = { & $OnRootHandleAcquired $canonicalPath }.GetNewClosure()
        $callback = [System.Action]$callbackScript
    }
    [TicketboxExactTreeDeleteNativeMethods]::DeleteTree($canonicalPath, $callback)
    if (Test-Path -LiteralPath $canonicalPath) {
        throw "精确删除完成后数据目录仍存在：$canonicalPath"
    }
}

function ConvertTo-TicketboxCanonicalPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path).Trim())
    $root = [System.IO.Path]::GetPathRoot($full)
    if ([string]::Equals($full, $root, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full
    }
    return $full.TrimEnd("\")
}

function Test-TicketboxPathEquals([string]$Left, [string]$Right) {
    return [string]::Equals(
        (ConvertTo-TicketboxCanonicalPath $Left),
        (ConvertTo-TicketboxCanonicalPath $Right),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {
    $candidate = ConvertTo-TicketboxCanonicalPath $Path
    $container = ConvertTo-TicketboxCanonicalPath $Parent
    if (Test-TicketboxPathEquals $candidate $container) {
        return $true
    }
    return $candidate.StartsWith($container.TrimEnd("\") + "\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {
    $cursor = ConvertTo-TicketboxCanonicalPath $Path
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "数据目录或祖先目录是重解析点，拒绝安装：$cursor"
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($cursor)
        if ([string]::IsNullOrWhiteSpace($parent) -or (Test-TicketboxPathEquals $cursor $parent)) {
            break
        }
        $cursor = $parent
    }
}

function Invoke-TicketboxIcaclsChecked([string]$Path, [string[]]$Arguments) {
    $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $effectiveArguments = @($Arguments + "/L")
        $output = & $icacls $Path @effectiveArguments 2>&1
        $rc = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($rc -ne 0) {
        throw "icacls.exe $Path $($Arguments -join ' ') 失败（exit=$rc）：`n$output"
    }
}

function ConvertTo-TicketboxAccountSid([string]$Account) {
    try {
        if ($Account -match '^S-\d-(?:\d+-)+\d+$') {
            return (New-Object System.Security.Principal.SecurityIdentifier($Account)).Value
        }
        return (New-Object System.Security.Principal.NTAccount($Account)).Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        throw "无法解析 Windows 账户 $Account，拒绝写入不完整 ACL。"
    }
}

function Get-TicketboxPathAcl([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($PSVersionTable.PSEdition -eq "Core") {
        $descriptor = [System.IO.FileSystemAclExtensions]::GetAccessControl($item)
    }
    else {
        $descriptor = $item.GetAccessControl()
    }
    return [pscustomobject]@{
        Owner = $descriptor.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
        Access = @($descriptor.GetAccessRules(
            $true,
            $true,
            [System.Security.Principal.SecurityIdentifier]
        ))
        AreAccessRulesProtected = $descriptor.AreAccessRulesProtected
    }
}

function Set-TicketboxOwnerIfNeeded([string]$Path, [string]$ExpectedOwnerSid) {
    $acl = Get-TicketboxPathAcl $Path
    $ownerSid = ConvertTo-TicketboxAccountSid $acl.Owner
    if ($ownerSid -ne $ExpectedOwnerSid) {
        Invoke-TicketboxIcaclsChecked $Path @("/setowner", "*$ExpectedOwnerSid")
        $ownerSid = ConvertTo-TicketboxAccountSid (Get-TicketboxPathAcl $Path).Owner
        if ($ownerSid -ne $ExpectedOwnerSid) {
            throw "无法验证 ACL owner 转移结果：$Path ($ownerSid)"
        }
    }
}

function Set-TicketboxWritableOwnerForAclUpdate([string]$Path) {
    $currentUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $administratorsSid = ConvertTo-TicketboxAccountSid "BUILTIN\Administrators"
    $ownerSid = ConvertTo-TicketboxAccountSid (Get-TicketboxPathAcl $Path).Owner
    if ($ownerSid -notin @($currentUserSid, $administratorsSid)) {
        Invoke-TicketboxIcaclsChecked $Path @("/setowner", "*$administratorsSid")
    }
}

function Set-TicketboxExactDirectoryAcl(
    [string]$Path,
    [string[]]$Accounts,
    [string[]]$ReadExecuteAccounts = @(),
    [string[]]$InheritableReadExecuteAccounts = @(),
    [string]$OwnerAccount = "SYSTEM",
    [switch]$Recurse
) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "ACL 目标目录不存在：$Path"
    }
    $mutationGuard = Enter-TicketboxDirectoryMutationGuard $Path
    try {
        Assert-NoTicketboxReparsePoints $Path
        Set-TicketboxExactDirectoryAclCore `
            -Path $Path `
            -Accounts $Accounts `
            -ReadExecuteAccounts $ReadExecuteAccounts `
            -InheritableReadExecuteAccounts $InheritableReadExecuteAccounts `
            -OwnerAccount $OwnerAccount `
            -Recurse:$Recurse
    }
    finally {
        $mutationGuard.Dispose()
    }
}

function Set-TicketboxExactDirectoryAclCore(
    [string]$Path,
    [string[]]$Accounts,
    [string[]]$ReadExecuteAccounts = @(),
    [string[]]$InheritableReadExecuteAccounts = @(),
    [string]$OwnerAccount = "SYSTEM",
    [switch]$Recurse
) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "ACL 目标目录不存在：$Path"
    }
    $targetSids = @($Accounts | ForEach-Object { ConvertTo-TicketboxAccountSid $_ } | Sort-Object -Unique)
    if ($targetSids.Count -eq 0) {
        throw "ACL 至少需要一个授权账户：$Path"
    }
    $readExecuteSids = @(
        $ReadExecuteAccounts | ForEach-Object { ConvertTo-TicketboxAccountSid $_ } | Sort-Object -Unique
    )
    $inheritableReadExecuteSids = @(
        $InheritableReadExecuteAccounts |
            ForEach-Object { ConvertTo-TicketboxAccountSid $_ } |
            Sort-Object -Unique
    )
    if (
        @($readExecuteSids | Where-Object { $_ -in $targetSids }).Count -gt 0 -or
        @($inheritableReadExecuteSids | Where-Object { $_ -in $targetSids }).Count -gt 0 -or
        @($inheritableReadExecuteSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0
    ) {
        throw "ACL FullControl 与 ReadExecute 账户不能重叠：$Path"
    }
    $allowedSids = @(
        $targetSids + $readExecuteSids + $inheritableReadExecuteSids |
            Sort-Object -Unique
    )
    $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount

    Set-TicketboxWritableOwnerForAclUpdate $Path
    # Seed explicit grants before removing inheritance so the installer cannot lock itself out mid-update.
    foreach ($sid in $targetSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:(OI)(CI)F")
    }
    foreach ($sid in $readExecuteSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:RX")
    }
    foreach ($sid in $inheritableReadExecuteSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:(OI)(CI)RX")
    }
    Invoke-TicketboxIcaclsChecked $Path @("/inheritance:r")

    $presentSids = @(
        (Get-TicketboxPathAcl $Path).Access |
            ForEach-Object {
                $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            } |
            Sort-Object -Unique
    )
    foreach ($sid in $presentSids) {
        if ($sid -notin $allowedSids) {
            Invoke-TicketboxIcaclsChecked $Path @("/remove", "*$sid")
        }
    }
    foreach ($sid in $targetSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/remove:d", "*$sid")
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:(OI)(CI)F")
    }
    foreach ($sid in $readExecuteSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/remove:d", "*$sid")
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:RX")
    }
    foreach ($sid in $inheritableReadExecuteSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/remove:d", "*$sid")
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:(OI)(CI)RX")
    }

    if ($Recurse) {
        Assert-NoTicketboxReparsePoints $Path
        foreach ($descendant in Get-ChildItem -LiteralPath $Path -Force -Recurse) {
            Set-TicketboxWritableOwnerForAclUpdate $descendant.FullName
        }
        foreach ($child in Get-ChildItem -LiteralPath $Path -Force) {
            Invoke-TicketboxIcaclsChecked $child.FullName @("/reset", "/T")
        }
        foreach ($descendant in Get-ChildItem -LiteralPath $Path -Force -Recurse) {
            Set-TicketboxOwnerIfNeeded -Path $descendant.FullName -ExpectedOwnerSid $expectedOwnerSid
        }
        Invoke-TicketboxIcaclsChecked $Path @("/verify", "/T")
    }

    Set-TicketboxOwnerIfNeeded -Path $Path -ExpectedOwnerSid $expectedOwnerSid

    $acl = Get-TicketboxPathAcl $Path
    if (-not $acl.AreAccessRulesProtected) {
        throw "ACL 仍在继承父目录权限：$Path"
    }
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if (
            $ruleSid -notin $allowedSids -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow
        ) {
            throw "ACL 含有未授权或拒绝规则：$Path ($ruleSid)"
        }
    }
    foreach ($sid in $targetSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $ruleSid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            $requiredInheritance =
                [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
            $hasFullControl =
                ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
                [System.Security.AccessControl.FileSystemRights]::FullControl
            $hasInheritance = ($_.InheritanceFlags -band $requiredInheritance) -eq $requiredInheritance
            $ruleSid -eq $sid -and $hasFullControl -and $hasInheritance
        })
        if ($matchingRules.Count -eq 0) {
            throw "ACL 缺少目标账户的可继承 FullControl：$Path ($sid)"
        }
    }
    foreach ($sid in $readExecuteSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $ruleSid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            $hasReadExecute =
                ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -eq
                [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
            $forbidden =
                [System.Security.AccessControl.FileSystemRights]::Write -bor
                [System.Security.AccessControl.FileSystemRights]::Delete -bor
                [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                [System.Security.AccessControl.FileSystemRights]::TakeOwnership
            $ruleSid -eq $sid -and $hasReadExecute -and
                $_.InheritanceFlags -eq [System.Security.AccessControl.InheritanceFlags]::None -and
                ($_.FileSystemRights -band $forbidden) -eq 0
        })
        if ($matchingRules.Count -eq 0) {
            throw "ACL 缺少目标账户的非继承 ReadExecute：$Path ($sid)"
        }
    }
    foreach ($sid in $inheritableReadExecuteSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $ruleSid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            $requiredInheritance =
                [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
                [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
            $hasReadExecute =
                ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -eq
                [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
            $forbidden =
                [System.Security.AccessControl.FileSystemRights]::Write -bor
                [System.Security.AccessControl.FileSystemRights]::Delete -bor
                [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                [System.Security.AccessControl.FileSystemRights]::TakeOwnership
            $hasInheritance = ($_.InheritanceFlags -band $requiredInheritance) -eq $requiredInheritance
            $ruleSid -eq $sid -and $hasReadExecute -and $hasInheritance -and
                -not $_.IsInherited -and ($_.FileSystemRights -band $forbidden) -eq 0
        })
        if ($matchingRules.Count -eq 0) {
            throw "ACL 缺少目标账户的可继承 ReadExecute：$Path ($sid)"
        }
    }
    $ownerSid = ConvertTo-TicketboxAccountSid $acl.Owner
    if ($ownerSid -ne $expectedOwnerSid) {
        throw "ACL owner 与安装配置不一致：$Path ($ownerSid)"
    }
}

function Set-TicketboxExactFileAcl(
    [string]$Path,
    [string[]]$Accounts,
    [string[]]$ReadExecuteAccounts = @(),
    [string]$OwnerAccount = "SYSTEM"
) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "ACL 目标文件不存在：$Path"
    }
    $targetSids = @($Accounts | ForEach-Object { ConvertTo-TicketboxAccountSid $_ } | Sort-Object -Unique)
    if ($targetSids.Count -eq 0) {
        throw "ACL 至少需要一个授权账户：$Path"
    }
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if (@($targetSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0) {
        throw "文件 ACL 账户不能同时拥有 FullControl 与 ReadExecute：$Path"
    }
    $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount
    Set-TicketboxWritableOwnerForAclUpdate $Path
    foreach ($sid in $targetSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:F")
    }
    foreach ($sid in $readExecuteSids) {
        Invoke-TicketboxIcaclsChecked $Path @("/grant:r", "*${sid}:RX")
    }
    Invoke-TicketboxIcaclsChecked $Path @("/inheritance:r")
    $presentSids = @((Get-TicketboxPathAcl $Path).Access | ForEach-Object {
        $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    } | Sort-Object -Unique)
    foreach ($sid in $presentSids) {
        if ($sid -notin $targetSids -and $sid -notin $readExecuteSids) {
            Invoke-TicketboxIcaclsChecked $Path @("/remove", "*$sid")
        }
    }
    Set-TicketboxOwnerIfNeeded -Path $Path -ExpectedOwnerSid $expectedOwnerSid
    Assert-TicketboxExactFileAcl `
        -Path $Path `
        -Accounts $Accounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
}

function Assert-TicketboxExactFileAcl(
    [string]$Path,
    [string[]]$Accounts,
    [string[]]$ReadExecuteAccounts = @(),
    [string]$OwnerAccount = "SYSTEM"
) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "ACL 目标文件不存在：$Path"
    }
    $targetSids = @($Accounts | ForEach-Object { ConvertTo-TicketboxAccountSid $_ } | Sort-Object -Unique)
    if ($targetSids.Count -eq 0) {
        throw "ACL 至少需要一个授权账户：$Path"
    }
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if (@($targetSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0) {
        throw "文件 ACL 账户不能同时拥有 FullControl 与 ReadExecute：$Path"
    }
    $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount
    $acl = Get-TicketboxPathAcl $Path
    if (-not $acl.AreAccessRulesProtected -or (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $expectedOwnerSid) {
        throw "文件 ACL owner 或继承状态与安装配置不一致：$Path"
    }
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            throw "文件 ACL 含有非 Allow 规则：$Path ($ruleSid)"
        }
        if ($ruleSid -in $targetSids) {
            $hasFullControl =
                ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
                [System.Security.AccessControl.FileSystemRights]::FullControl
            if (-not $hasFullControl) {
                throw "文件 ACL 的 FullControl 账户权限不足：$Path ($ruleSid)"
            }
            continue
        }
        if ($ruleSid -in $readExecuteSids) {
            $required = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
            $forbidden =
                [System.Security.AccessControl.FileSystemRights]::Write -bor
                [System.Security.AccessControl.FileSystemRights]::Delete -bor
                [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                [System.Security.AccessControl.FileSystemRights]::TakeOwnership
            if (
                ($rule.FileSystemRights -band $required) -ne $required -or
                ($rule.FileSystemRights -band $forbidden) -ne 0
            ) {
                throw "文件 ACL 的 ReadExecute 账户拥有不足或越权权限：$Path ($ruleSid)"
            }
            continue
        }
        throw "文件 ACL 含有未授权账户：$Path ($ruleSid)"
    }
    foreach ($sid in $targetSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $sid
        })
        if ($matchingRules.Count -eq 0) {
            throw "文件 ACL 缺少目标账户：$Path ($sid)"
        }
    }
    foreach ($sid in $readExecuteSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $sid
        })
        if ($matchingRules.Count -eq 0) {
            throw "文件 ACL 缺少 ReadExecute 账户：$Path ($sid)"
        }
    }
}

function Get-TicketboxDataRootMarkerPath([string]$DataRoot) {
    return Join-Path (ConvertTo-TicketboxCanonicalPath $DataRoot) $script:TicketboxDataRootMarkerName
}

function Get-TicketboxPersistentInstallationIdentityPath([string]$DataRoot) {
    return Join-Path `
        (ConvertTo-TicketboxCanonicalPath $DataRoot) `
        $script:TicketboxPersistentInstallationIdentityName
}

function ConvertTo-TicketboxNumericVersion([string]$Value) {
    if ($Value -notmatch '^[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(\.[0-9]{1,5})?$') {
        throw "安装身份中的 backend version 不符合三段或四段纯数字契约：$Value"
    }
    $parts = @($Value.Split(".") | ForEach-Object { [int]$_ })
    while ($parts.Count -lt 4) { $parts += 0 }
    if (@($parts | Where-Object { $_ -gt 65535 }).Count -gt 0) {
        throw "安装身份中的 backend version 分量超出范围：$Value"
    }
    return $parts
}

function Compare-TicketboxNumericVersion([string]$Left, [string]$Right) {
    $leftParts = ConvertTo-TicketboxNumericVersion $Left
    $rightParts = ConvertTo-TicketboxNumericVersion $Right
    for ($index = 0; $index -lt 4; $index++) {
        if ($leftParts[$index] -lt $rightParts[$index]) { return -1 }
        if ($leftParts[$index] -gt $rightParts[$index]) { return 1 }
    }
    return 0
}

function Get-TicketboxPortableFileSha256([string]$Path) {
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Read-TicketboxPersistentInstallationIdentity([string]$DataRoot) {
    $path = Get-TicketboxPersistentInstallationIdentityPath $DataRoot
    Assert-NoTicketboxAncestorReparsePoints $path
    Assert-TicketboxExactFileAcl `
        -Path $path `
        -Accounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    $expectedNames = @(
        "SCHEMA",
        "BACKEND_VERSION_FLOOR",
        "INSTALLATION_ID",
        "BUILD_MANIFEST_SHA256",
        "DATA_ROOT",
        "INSTALL_DIR",
        "PG_SERVICE_NAME",
        "BACKEND_SERVICE_NAME",
        "PG_PORT",
        "BACKEND_PORT"
    )
    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $path -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($rawLine) -or -not $rawLine.Contains("=")) {
            throw "持久安装身份含有空行或无效字段。"
        }
        $parts = $rawLine.Split(@("="), 2, [System.StringSplitOptions]::None)
        $name = $parts[0]
        if ($name -notin $expectedNames -or $values.ContainsKey($name)) {
            throw "持久安装身份含有未知或重复字段：$name"
        }
        $values[$name] = $parts[1]
    }
    if ($values.Count -ne $expectedNames.Count) {
        throw "持久安装身份字段不完整。"
    }
    foreach ($name in $expectedNames) {
        if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($values[$name])) {
            throw "持久安装身份缺少字段：$name"
        }
    }
    if ($values.SCHEMA -cne $script:TicketboxPersistentInstallationIdentitySchema) {
        throw "持久安装身份 schema 不受支持。"
    }
    ConvertTo-TicketboxNumericVersion $values.BACKEND_VERSION_FLOOR | Out-Null
    $installationId = [guid]::Empty
    if (-not [guid]::TryParseExact($values.INSTALLATION_ID, "D", [ref]$installationId)) {
        throw "持久安装身份 installation id 无效。"
    }
    if ($values.BUILD_MANIFEST_SHA256 -cnotmatch '^[0-9A-F]{64}$') {
        throw "持久安装身份 build manifest SHA-256 无效。"
    }
    $pgPort = 0
    $backendPort = 0
    if (
        -not [int]::TryParse($values.PG_PORT, [ref]$pgPort) -or
        -not [int]::TryParse($values.BACKEND_PORT, [ref]$backendPort) -or
        $pgPort -lt 1 -or $pgPort -gt 65535 -or
        $backendPort -lt 1 -or $backendPort -gt 65535 -or
        $pgPort -eq $backendPort
    ) {
        throw "持久安装身份端口无效。"
    }
    return [pscustomobject]@{
        Path = $path
        BackendVersionFloor = [string]$values.BACKEND_VERSION_FLOOR
        InstallationId = $installationId.ToString("D")
        BuildManifestSha256 = [string]$values.BUILD_MANIFEST_SHA256
        DataRoot = [string]$values.DATA_ROOT
        InstallDir = [string]$values.INSTALL_DIR
        PgServiceName = [string]$values.PG_SERVICE_NAME
        BackendServiceName = [string]$values.BACKEND_SERVICE_NAME
        PgPort = $pgPort
        BackendPort = $backendPort
    }
}

function Read-TicketboxInstalledBuildManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(0, 99)][int]$ExpectedPgMajor = 0
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少已安装 BUILD_PROVENANCE.json：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    try {
        $manifest = Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "已安装 BUILD_PROVENANCE.json 不是有效 JSON。"
    }
    if (
        $manifest.schema_version -ne 3 -or
        [string]$manifest.artifact_type -cne "ticketbox-windows-installer-inputs" -or
        [string]$manifest.build_mode -cne "installer-build"
    ) {
        throw "已安装 BUILD_PROVENANCE.json 的 schema/artifact_type/build_mode 不受支持。"
    }
    $backendVersion = [string]$manifest.backend.version
    ConvertTo-TicketboxNumericVersion $backendVersion | Out-Null
    $pgMajor = 0
    $pgMajorValue = $manifest.postgresql.major
    if (
        ($pgMajorValue -isnot [int] -and $pgMajorValue -isnot [long]) -or
        -not [int]::TryParse([string]$pgMajorValue, [ref]$pgMajor) -or
        $pgMajor -lt 1 -or
        $pgMajor -gt 99
    ) {
        throw "已安装 BUILD_PROVENANCE.json 的 PostgreSQL major 无效。"
    }
    if ($ExpectedPgMajor -gt 0 -and $pgMajor -ne $ExpectedPgMajor) {
        throw "已安装 BUILD_PROVENANCE.json 的 PostgreSQL major 与安装器目标不一致。"
    }
    $expectedDefine = "/DTargetPgMajor=$pgMajor"
    $targetMajorDefines = @($manifest.compiler_defines | Where-Object {
        [string]$_ -match '^/DTargetPgMajor='
    })
    if ($targetMajorDefines.Count -ne 1 -or [string]$targetMajorDefines[0] -cne $expectedDefine) {
        throw "已安装 BUILD_PROVENANCE.json 未绑定唯一且一致的 TargetPgMajor。"
    }
    return [pscustomobject]@{
        Path = [System.IO.Path]::GetFullPath($Path)
        Manifest = $manifest
        BackendVersion = $backendVersion
        PgMajor = $pgMajor
    }
}

function Write-TicketboxPersistentInstallationIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath
    )
    if ($PgPort -eq $BackendPort) { throw "持久安装身份端口不能相同。" }
    $buildManifest = Read-TicketboxInstalledBuildManifest $BuildManifestPath
    $backendVersion = $buildManifest.BackendVersion
    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath $InstallDir
    $path = Get-TicketboxPersistentInstallationIdentityPath $canonicalDataRoot
    $installationId = [guid]::NewGuid().ToString("D")
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $existing = Read-TicketboxPersistentInstallationIdentity $canonicalDataRoot
        if (
            -not (Test-TicketboxPathEquals $existing.DataRoot $canonicalDataRoot) -or
            -not (Test-TicketboxPathEquals $existing.InstallDir $canonicalInstallDir) -or
            $existing.PgServiceName -cne $PgServiceName -or
            $existing.BackendServiceName -cne $BackendServiceName -or
            $existing.PgPort -ne $PgPort -or
            $existing.BackendPort -ne $BackendPort
        ) {
            throw "持久安装身份与当前 DataRoot 或发布身份不一致。"
        }
        if ((Compare-TicketboxNumericVersion $backendVersion $existing.BackendVersionFloor) -lt 0) {
            throw "拒绝把持久 backend version floor 从 $($existing.BackendVersionFloor) 降到 $backendVersion。"
        }
        $installationId = $existing.InstallationId
    }
    $manifestSha256 = Get-TicketboxPortableFileSha256 $BuildManifestPath
    $text = @(
        "SCHEMA=$script:TicketboxPersistentInstallationIdentitySchema",
        "BACKEND_VERSION_FLOOR=$backendVersion",
        "INSTALLATION_ID=$installationId",
        "BUILD_MANIFEST_SHA256=$manifestSha256",
        "DATA_ROOT=$canonicalDataRoot",
        "INSTALL_DIR=$canonicalInstallDir",
        "PG_SERVICE_NAME=$PgServiceName",
        "BACKEND_SERVICE_NAME=$BackendServiceName",
        "PG_PORT=$PgPort",
        "BACKEND_PORT=$BackendPort"
    ) -join "`r`n"
    $protectTemporary = {
        param($TemporaryPath)
        Set-TicketboxExactFileAcl `
            -Path $TemporaryPath `
            -Accounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
            -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    }
    Write-TicketboxUtf8FileDurable `
        -Path $path `
        -Text ($text + "`r`n") `
        -ProtectTemporaryFile $protectTemporary `
        -ReplaceExisting:(Test-Path -LiteralPath $path)
    Set-TicketboxExactFileAcl `
        -Path $path `
        -Accounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    return Read-TicketboxPersistentInstallationIdentity $canonicalDataRoot
}

function Assert-TicketboxRegisteredDataRootBinding {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [scriptblock]$RegistryReader = {
            $registryPath = "HKLM:\Software\Ticketbox"
            if (-not (Test-Path -LiteralPath $registryPath)) { return "" }
            return [string](Get-ItemProperty `
                -LiteralPath $registryPath `
                -Name "DataRoot" `
                -ErrorAction Stop).DataRoot
        }
    )
    try { $registeredDataRoot = [string](& $RegistryReader) }
    catch { throw "无法读取受保护的机器级安装身份，拒绝收编既有数据目录。" }
    if (
        [string]::IsNullOrWhiteSpace($registeredDataRoot) -or
        -not (Test-TicketboxPathEquals $registeredDataRoot $DataRoot)
    ) {
        throw "既有数据目录与 HKLM 安装身份不匹配，拒绝收编。"
    }
}

function Write-TicketboxDataRootMarker([string]$DataRoot, [string]$InstallDir) {
    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    $payload = [ordered]@{
        schema = $script:TicketboxDataRootMarkerSchema
        data_root = $canonicalDataRoot
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
    } | ConvertTo-Json -Compress
    Write-TicketboxUtf8FileDurable `
        -Path (Get-TicketboxDataRootMarkerPath $canonicalDataRoot) `
        -Text $payload
}

function Assert-TicketboxDataRootMarkerInitialization {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowLegacyAdoption
    )

    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        Assert-TicketboxDataRootMarker -DataRoot $canonicalDataRoot -InstallDir $InstallDir
        return
    }

    $entries = @(Get-ChildItem -LiteralPath $canonicalDataRoot -Force)
    if ($entries.Count -gt 0) {
        if (-not $AllowLegacyAdoption) {
            throw "拒绝把非空目录收编为小票夹数据根：$canonicalDataRoot"
        }
        $unexpected = @($entries | Where-Object { $_.Name -notin @("app", "pgdata") })
        $hasLegacyLayout =
            (Test-Path -LiteralPath (Join-Path $canonicalDataRoot "pgdata\PG_VERSION") -PathType Leaf) -and
            (
                (Test-Path -LiteralPath (Join-Path $canonicalDataRoot "app\.env") -PathType Leaf) -or
                (Test-Path -LiteralPath (Join-Path $canonicalDataRoot "app\.postgres-bootstrap-password") -PathType Leaf)
            )
        if ($unexpected.Count -gt 0 -or -not $hasLegacyLayout) {
            throw "既有目录不是可识别的小票夹 legacy 数据布局，拒绝写入删除标记：$canonicalDataRoot"
        }
    }
}

function Assert-TicketboxLegacyProtectedFileAcl([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "legacy 受保护文件不存在：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "legacy 受保护文件不能是重解析点：$Path"
    }
    $systemSid = ConvertTo-TicketboxAccountSid "SYSTEM"
    $administratorsSid = ConvertTo-TicketboxAccountSid "BUILTIN\Administrators"
    $acl = Get-TicketboxPathAcl $Path
    if (
        -not $acl.AreAccessRulesProtected -or
        (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $systemSid
    ) {
        throw "legacy 受保护文件 owner 或继承状态不安全：$Path"
    }
    $fullControlSids = @()
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        $allowedSid =
            $sid -eq $systemSid -or
            $sid -eq $administratorsSid -or
            $sid.StartsWith("S-1-5-80-", [System.StringComparison]::Ordinal)
        if (
            -not $allowedSid -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow
        ) {
            throw "legacy 受保护文件含有宽权限 ACL：$Path ($sid)"
        }
        $hasFullControl =
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
            [System.Security.AccessControl.FileSystemRights]::FullControl
        if ($hasFullControl) { $fullControlSids += $sid }
    }
    if (
        $systemSid -notin $fullControlSids -or
        $administratorsSid -notin $fullControlSids
    ) {
        throw "legacy 受保护文件缺少 SYSTEM/Administrators FullControl：$Path"
    }
}

function Assert-TicketboxLegacyPreservedDataLayout {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$EnvPath,
        [Parameter(Mandatory = $true)][string]$PgData,
        [Parameter(Mandatory = $true)][int]$ExpectedPgMajor
    )
    $canonicalDataRoot = Assert-TicketboxDataRootDomain `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir
    Assert-NoTicketboxAncestorReparsePoints $canonicalDataRoot
    Assert-NoTicketboxReparsePoints $canonicalDataRoot
    Assert-TicketboxDataRootMarkerInitialization `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyAdoption
    Assert-TicketboxLegacyProtectedFileAcl $EnvPath
    $pgVersionPath = Join-Path $PgData "PG_VERSION"
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        throw "legacy 保留数据缺少 PG_VERSION。"
    }
    $versionItem = Get-Item -LiteralPath $pgVersionPath -Force
    if (
        ($versionItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $versionItem.Length -le 0 -or
        $versionItem.Length -gt 16
    ) {
        throw "legacy 保留数据的 PG_VERSION 文件不安全。"
    }
    $versionText = [System.IO.File]::ReadAllText(
        $pgVersionPath,
        [System.Text.Encoding]::UTF8
    ).Trim()
    $major = 0
    if (-not [int]::TryParse($versionText, [ref]$major) -or $major -ne $ExpectedPgMajor) {
        throw "legacy 保留数据的 PostgreSQL major 与目标运行时不兼容。"
    }
    return $canonicalDataRoot
}

function Initialize-TicketboxDataRootMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowLegacyAdoption
    )

    $canonicalDataRoot = Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir
    if (-not (Test-Path -LiteralPath $canonicalDataRoot)) {
        New-Item -ItemType Directory -Path $canonicalDataRoot -ErrorAction Stop | Out-Null
    }
    Assert-TicketboxDataRootMarkerInitialization `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyAdoption:$AllowLegacyAdoption
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        return
    }
    Write-TicketboxDataRootMarker -DataRoot $canonicalDataRoot -InstallDir $InstallDir
}

function Initialize-TicketboxSecureDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$Accounts,
        [switch]$AllowLegacyAdoption
    )

    $canonicalDataRoot = Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir
    Assert-NoTicketboxAncestorReparsePoints $canonicalDataRoot
    if (-not (Test-Path -LiteralPath $canonicalDataRoot)) {
        New-Item -ItemType Directory -Path $canonicalDataRoot -ErrorAction Stop | Out-Null
    }
    Assert-NoTicketboxAncestorReparsePoints $canonicalDataRoot
    Assert-NoTicketboxReparsePoints $canonicalDataRoot
    Assert-TicketboxDataRootMarkerInitialization `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyAdoption:$AllowLegacyAdoption
    Set-TicketboxExactDirectoryAcl -Path $canonicalDataRoot -Accounts $Accounts -Recurse
    if (-not (Test-Path -LiteralPath (Get-TicketboxDataRootMarkerPath $canonicalDataRoot) -PathType Leaf)) {
        Write-TicketboxDataRootMarker -DataRoot $canonicalDataRoot -InstallDir $InstallDir
    }
}

function Assert-TicketboxDataRootMarker([string]$DataRoot, [string]$InstallDir) {
    $markerPath = Get-TicketboxDataRootMarkerPath $DataRoot
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "拒绝删除未标记的数据目录：$DataRoot"
    }
    try {
        $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "数据目录标记损坏，拒绝删除：$markerPath"
    }
    if (
        $marker.schema -ne $script:TicketboxDataRootMarkerSchema -or
        -not (Test-TicketboxPathEquals ([string]$marker.data_root) $DataRoot) -or
        -not (Test-TicketboxPathEquals ([string]$marker.install_dir) $InstallDir)
    ) {
        throw "数据目录标记与当前安装不匹配，拒绝删除：$markerPath"
    }
}

function Assert-NoTicketboxReparsePoints([string]$DataRoot) {
    $root = Get-Item -LiteralPath $DataRoot -Force -ErrorAction Stop
    $pending = New-Object "System.Collections.Generic.Stack[System.IO.DirectoryInfo]"
    if (($root.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "数据目录是重解析点，拒绝递归删除：$DataRoot"
    }
    $pending.Push([System.IO.DirectoryInfo]$root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($child in $directory.GetFileSystemInfos()) {
            if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "数据目录包含重解析点，拒绝递归删除：$($child.FullName)"
            }
            if ($child -is [System.IO.DirectoryInfo]) {
                $pending.Push($child)
            }
        }
    }
}

function Get-TicketboxProtectedProfileRoots {
    $profileListPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"
    $roots = @()
    $profileList = Get-ItemProperty -LiteralPath $profileListPath -ErrorAction Stop
    if (-not [string]::IsNullOrWhiteSpace([string]$profileList.ProfilesDirectory)) {
        $roots += [Environment]::ExpandEnvironmentVariables([string]$profileList.ProfilesDirectory)
    }
    foreach ($profileKey in Get-ChildItem -LiteralPath $profileListPath -ErrorAction Stop) {
        $profile = Get-ItemProperty -LiteralPath $profileKey.PSPath -ErrorAction Stop
        if (-not [string]::IsNullOrWhiteSpace([string]$profile.ProfileImagePath)) {
            $roots += [Environment]::ExpandEnvironmentVariables([string]$profile.ProfileImagePath)
        }
    }
    return @($roots | Sort-Object -Unique)
}

function Get-TicketboxDataRootDriveType([string]$CanonicalPath) {
    $root = [System.IO.Path]::GetPathRoot($CanonicalPath)
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "数据目录没有本机文件系统根目录。"
    }
    return (New-Object System.IO.DriveInfo($root)).DriveType
}

function Assert-TicketboxDataRootDomain {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir
    )

    $full = ConvertTo-TicketboxCanonicalPath $DataRoot
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.StartsWith("\\")) {
        throw "数据目录不能使用 UNC 路径：$full"
    }
    if ((Get-TicketboxDataRootDriveType $full) -ne [System.IO.DriveType]::Fixed) {
        throw "数据目录必须位于本机固定磁盘，不能使用映射网络盘或可移除介质：$full"
    }
    if ($full.Length -lt 8 -or (Test-TicketboxPathEquals $full $root)) {
        throw "数据目录不能是磁盘根或过短路径：$full"
    }
    $commonApplicationData = [Environment]::GetFolderPath("CommonApplicationData")
    if (Test-TicketboxPathEquals $full $commonApplicationData) {
        throw "数据目录不能是整个 ProgramData：$full"
    }
    $protectedRoots = @(
        [Environment]::GetFolderPath("Windows"),
        [Environment]::GetFolderPath("ProgramFiles"),
        [Environment]::GetFolderPath("ProgramFilesX86"),
        (Get-TicketboxProtectedProfileRoots),
        $InstallDir
    ) | ForEach-Object { $_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($protected in $protectedRoots) {
        if ((Test-TicketboxPathWithin $full $protected) -or (Test-TicketboxPathWithin $protected $full)) {
            throw "数据目录不能位于系统、用户或程序目录内，也不能包含这些目录：$full"
        }
    }
    return $full
}

function Assert-TicketboxInstallRootDomain([string]$InstallDir) {
    $full = ConvertTo-TicketboxCanonicalPath $InstallDir
    if ($full.StartsWith("\\")) {
        throw "安装目录不能使用 UNC 路径：$full"
    }
    $programRoots = @(
        [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles),
        [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | ForEach-Object {
        ConvertTo-TicketboxCanonicalPath $_
    } | Sort-Object -Unique
    $withinProtectedProgramRoot = $false
    foreach ($programRoot in $programRoots) {
        if (
            -not (Test-TicketboxPathEquals $full $programRoot) -and
            (Test-TicketboxPathWithin $full $programRoot)
        ) {
            $withinProtectedProgramRoot = $true
            break
        }
    }
    if (-not $withinProtectedProgramRoot) {
        throw "安装目录必须位于受保护的 Program Files 子目录：$full"
    }
    Assert-NoTicketboxAncestorReparsePoints $full
    return $full
}

function Initialize-TicketboxSecureInstallRoot {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string[]]$ServiceReadExecuteAccounts = @()
    )
    $full = Assert-TicketboxInstallRootDomain $InstallDir
    if (-not (Test-Path -LiteralPath $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        throw "安装目录不是文件夹：$full"
    }
    Set-TicketboxExactDirectoryAcl `
        -Path $full `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -InheritableReadExecuteAccounts (@("BUILTIN\Users") + $ServiceReadExecuteAccounts) `
        -Recurse
    Assert-NoTicketboxReparsePoints $full
    return $full
}

function Assert-TicketboxDataRootDeletionSafety {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RegisteredDataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowProtectedMarkerWithoutRegistration
    )

    $full = Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir
    $registrationMissing = [string]::IsNullOrWhiteSpace($RegisteredDataRoot)
    if ($registrationMissing -and -not $AllowProtectedMarkerWithoutRegistration) {
        throw "安装器注册表缺少 DataRoot，拒绝删除任何数据目录。"
    }
    if (-not $registrationMissing -and -not (Test-TicketboxPathEquals $full $RegisteredDataRoot)) {
        throw "数据目录与安装器登记值不一致，拒绝删除：$full"
    }
    Assert-NoTicketboxAncestorReparsePoints $full

    if (Test-Path -LiteralPath $full) {
        Assert-TicketboxDataRootMarker -DataRoot $full -InstallDir $InstallDir
        if ($registrationMissing) {
            Assert-TicketboxExactFileAcl `
                -Path (Get-TicketboxDataRootMarkerPath $full) `
                -Accounts @("SYSTEM", "BUILTIN\Administrators") `
                -OwnerAccount "SYSTEM"
        }
        Assert-NoTicketboxReparsePoints $full
    }
    return $full
}
