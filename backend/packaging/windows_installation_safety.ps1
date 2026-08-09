#Requires -Version 5.1

$script:TicketboxDataRootMarkerName = ".ticketbox-data-root.json"
$script:TicketboxLegacyDataRootMarkerSchema = "ticketbox-data-root-v1"
$script:TicketboxDataRootMarkerSchema = "ticketbox-data-root-v2"
$script:TicketboxDataRootProvisioningIntentName = "data-root-provisioning-pending"
$script:TicketboxDataRootProvisioningIntentSchema = "ticketbox-data-root-provisioning-v2"
$script:TicketboxRuntimeDataBindingDirectoryName = "TicketboxRuntimeBinding"
$script:TicketboxRuntimeDataBindingJunctionName = "data-root"
$script:TicketboxBootstrapRecoveryGuardName = "bootstrap-exposure-recovery-pending"
$script:TicketboxPersistentInstallationIdentityName = ".ticketbox-installation-identity"
$script:TicketboxPendingInstallationIdentityName =
    ".ticketbox-installation-identity.pending"
$script:TicketboxLegacyPersistentInstallationIdentitySchema =
    "ticketbox-installation-identity-v1"
$script:TicketboxPersistentInstallationIdentitySchema =
    "ticketbox-installation-identity-v2"
$script:TicketboxPersistentInstallationIdentityAclAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxPersistentInstallationIdentityOwnerAccount = "SYSTEM"
$script:TicketboxC07MigrationHelperRelativePath = "ticketbox-c07-migrator.exe"

function Initialize-TicketboxWin32FilePathMethods {
    if ("TicketboxWin32FilePath" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;

public static class TicketboxWin32FilePath
{
    private const string ExtendedPrefix = @"\\?\";
    private const string ExtendedUncPrefix = @"\\?\UNC\";
    private const string UncPrefix = @"\\";

    private static readonly HashSet<string> ReservedDeviceNames =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "CON", "PRN", "AUX", "NUL", "CLOCK$",
            "COM1", "COM2", "COM3", "COM4", "COM5",
            "COM6", "COM7", "COM8", "COM9",
            "COM¹", "COM²", "COM³",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5",
            "LPT6", "LPT7", "LPT8", "LPT9",
            "LPT¹", "LPT²", "LPT³"
        };

    public static string NormalizeCanonical(string path)
    {
        if (path == null)
        {
            throw new ArgumentNullException("path");
        }
        if (path.Length == 0 ||
            !String.Equals(path, path.Trim(), StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "A Win32 file path must be non-empty and have no surrounding whitespace.",
                "path");
        }
        if (path.IndexOf('\0') >= 0)
        {
            throw new ArgumentException("A Win32 file path contains NUL.", "path");
        }

        string ordinaryPath;
        if (path.StartsWith(ExtendedUncPrefix, StringComparison.OrdinalIgnoreCase))
        {
            AssertExtendedSyntax(path);
            ordinaryPath = UncPrefix + path.Substring(ExtendedUncPrefix.Length);
        }
        else if (path.StartsWith(ExtendedPrefix, StringComparison.OrdinalIgnoreCase))
        {
            AssertExtendedSyntax(path);
            ordinaryPath = path.Substring(ExtendedPrefix.Length);
            if (!IsDriveAbsolute(ordinaryPath))
            {
                throw new ArgumentException(
                    "Only drive and UNC Win32 file namespaces are accepted.",
                    "path");
            }
        }
        else
        {
            if (path.StartsWith(@"\\.\", StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith(@"\??\", StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith(@"\\??\", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException(
                    "Win32 device and NT object-manager paths are not file paths.",
                    "path");
            }
            ordinaryPath = path.Replace('/', '\\');
        }

        ValidateFullyQualifiedPath(ordinaryPath);
        return ordinaryPath;
    }

    public static string NormalizeExtended(string path)
    {
        string canonical = NormalizeCanonical(path);
        string extended = canonical.StartsWith(UncPrefix, StringComparison.Ordinal)
            ? ExtendedUncPrefix + canonical.Substring(UncPrefix.Length)
            : ExtendedPrefix + canonical;
        if (extended.Length >= 32767)
        {
            throw new PathTooLongException(
                "The extended-length Win32 path exceeds the Unicode API limit.");
        }
        return extended;
    }

    private static void AssertExtendedSyntax(string path)
    {
        if (path.IndexOf('/') >= 0)
        {
            throw new ArgumentException(
                "Extended-length Win32 paths require backslash separators.",
                "path");
        }
    }

    private static bool IsDriveAbsolute(string path)
    {
        return path.Length >= 3 &&
            ((path[0] >= 'A' && path[0] <= 'Z') ||
             (path[0] >= 'a' && path[0] <= 'z')) &&
            path[1] == ':' &&
            path[2] == '\\';
    }

    private static void ValidateFullyQualifiedPath(string path)
    {
        int componentStart;
        if (IsDriveAbsolute(path))
        {
            componentStart = 3;
        }
        else if (path.StartsWith(UncPrefix, StringComparison.Ordinal))
        {
            int serverEnd = path.IndexOf('\\', UncPrefix.Length);
            if (serverEnd <= UncPrefix.Length)
            {
                throw new ArgumentException(
                    "A UNC path requires a non-empty server and share.",
                    "path");
            }
            int shareEnd = path.IndexOf('\\', serverEnd + 1);
            string server = path.Substring(UncPrefix.Length, serverEnd - UncPrefix.Length);
            string share = shareEnd < 0
                ? path.Substring(serverEnd + 1)
                : path.Substring(serverEnd + 1, shareEnd - serverEnd - 1);
            ValidateComponent(server, "UNC server", false);
            ValidateComponent(share, "UNC share", false);
            componentStart = shareEnd < 0 ? path.Length : shareEnd + 1;
        }
        else
        {
            throw new ArgumentException(
                "A Win32 file path must be a fully-qualified drive or UNC path.",
                "path");
        }

        if (componentStart >= path.Length)
        {
            return;
        }
        string[] components = path.Substring(componentStart).Split('\\');
        for (int index = 0; index < components.Length; index++)
        {
            string component = components[index];
            if (component.Length == 0 && index == components.Length - 1)
            {
                continue;
            }
            ValidateComponent(component, "path component", true);
        }
    }

    private static void ValidateComponent(
        string component,
        string label,
        bool rejectReservedDeviceName)
    {
        if (String.IsNullOrEmpty(component) ||
            component == "." ||
            component == "..")
        {
            throw new ArgumentException(label + " is empty or relative.", "path");
        }
        if (component.Length > 255)
        {
            throw new PathTooLongException(label + " exceeds 255 UTF-16 code units.");
        }
        if (component[component.Length - 1] == ' ' ||
            component[component.Length - 1] == '.')
        {
            throw new ArgumentException(
                label + " ends in a Win32-ambiguous space or period.",
                "path");
        }
        for (int index = 0; index < component.Length; index++)
        {
            char value = component[index];
            if (value < 32 || value == '<' || value == '>' || value == ':' ||
                value == '"' || value == '|' || value == '?' || value == '*')
            {
                throw new ArgumentException(
                    label + " contains a reserved Win32 character.",
                    "path");
            }
        }
        if (rejectReservedDeviceName)
        {
            int extension = component.IndexOf('.');
            string stem = extension < 0 ? component : component.Substring(0, extension);
            if (ReservedDeviceNames.Contains(stem))
            {
                throw new ArgumentException(
                    label + " is a reserved Win32 device name.",
                    "path");
            }
        }
    }
}
'@
}

function ConvertTo-TicketboxWin32ExtendedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    Initialize-TicketboxWin32FilePathMethods
    return [TicketboxWin32FilePath]::NormalizeExtended($Path)
}

function ConvertTo-TicketboxWin32CanonicalPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    Initialize-TicketboxWin32FilePathMethods
    return [TicketboxWin32FilePath]::NormalizeCanonical($Path)
}

function Initialize-TicketboxDirectoryGuardNativeMethods {
    Initialize-TicketboxWin32FilePathMethods
    if ("TicketboxDirectoryGuardNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class TicketboxDirectoryGuardNativeMethods
{
    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "GetVolumeNameForVolumeMountPointW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetVolumeNameForVolumeMountPointW(
        string volumeMountPoint,
        StringBuilder volumeName,
        uint bufferLength);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "GetVolumePathNameW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetVolumePathNameW(
        string fileName,
        StringBuilder volumePathName,
        uint bufferLength);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "GetVolumeInformationW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetVolumeInformationW(
        string rootPathName,
        StringBuilder volumeNameBuffer,
        uint volumeNameSize,
        out uint volumeSerialNumber,
        out uint maximumComponentLength,
        out uint fileSystemFlags,
        StringBuilder fileSystemNameBuffer,
        uint fileSystemNameSize);

    public static SafeFileHandle OpenDirectory(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        uint creationDisposition,
        uint flagsAndAttributes)
    {
        return CreateFileW(
            fileName,
            desiredAccess,
            shareMode,
            IntPtr.Zero,
            creationDisposition,
            flagsAndAttributes,
            IntPtr.Zero);
    }

    public static bool TryGetVolumeNameForVolumeMountPoint(
        string volumeMountPoint,
        StringBuilder volumeName,
        uint bufferLength)
    {
        return GetVolumeNameForVolumeMountPointW(
            volumeMountPoint,
            volumeName,
            bufferLength);
    }

    public static bool TryGetVolumePathName(
        string fileName,
        StringBuilder volumePathName,
        uint bufferLength)
    {
        return GetVolumePathNameW(
            fileName,
            volumePathName,
            bufferLength);
    }

    public static bool TryGetVolumeInformation(
        string rootPathName,
        StringBuilder fileSystemName,
        uint fileSystemNameSize,
        out uint fileSystemFlags)
    {
        uint volumeSerialNumber;
        uint maximumComponentLength;
        return GetVolumeInformationW(
            rootPathName,
            null,
            0,
            out volumeSerialNumber,
            out maximumComponentLength,
            out fileSystemFlags,
            fileSystemName,
            fileSystemNameSize);
    }
}
'@
}

function Enter-TicketboxDirectoryMutationGuard {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$CreateMissingDirectories,
        [scriptblock]$OnBeforeFirstDirectoryCreation = $null,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    Initialize-TicketboxDirectoryGuardNativeMethods
    $canonicalPath = ConvertTo-TicketboxWin32CanonicalPath $Path
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
    $createdPaths = New-Object "System.Collections.Generic.List[string]"
    $creationCallbackInvoked = $false
    try {
        while ($pathStack.Count -gt 0) {
            $guardedPath = $pathStack.Pop()
            if (-not (Test-Path -LiteralPath $guardedPath)) {
                if (-not $CreateMissingDirectories) {
                    throw "ACL 目标目录链不存在：$guardedPath"
                }
                if (-not $creationCallbackInvoked -and $null -ne $OnBeforeFirstDirectoryCreation) {
                    & $OnBeforeFirstDirectoryCreation | Out-Null
                    $creationCallbackInvoked = $true
                }
                Initialize-TicketboxProtectedDirectoryAtomically `
                    -Path $guardedPath `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount | Out-Null
                $createdPaths.Add((ConvertTo-TicketboxCanonicalPath $guardedPath))
            }
            if (-not (Test-Path -LiteralPath $guardedPath -PathType Container)) {
                throw "ACL 目标目录链节点不是目录：$guardedPath"
            }
            $handle = [TicketboxDirectoryGuardNativeMethods]::OpenDirectory(
                (ConvertTo-TicketboxWin32ExtendedPath $guardedPath),
                $genericRead,
                0x3,
                3,
                0x02200000
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
        $guard = [pscustomobject]@{
            Handles = @($handles)
            CreatedPaths = @($createdPaths)
        }
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
    Initialize-TicketboxWin32FilePathMethods
    if ("TicketboxDurableFileNativeMethods" -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class TicketboxDurableFileNativeMethods
{
    [DllImport(
        "kernel32.dll",
        EntryPoint = "MoveFileExW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileExW(string existingName, string newName, uint flags);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "ReplaceFileW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ReplaceFileW(
        string replacedFileName,
        string replacementFileName,
        string backupFileName,
        uint replaceFlags,
        IntPtr exclude,
        IntPtr reserved);

    public static void MoveFileDurable(string existingName, string newName, bool replaceExisting)
    {
        const uint MoveFileReplaceExisting = 0x1;
        const uint MoveFileWriteThrough = 0x8;
        uint flags = MoveFileWriteThrough;
        if (replaceExisting)
        {
            flags |= MoveFileReplaceExisting;
        }
        if (!MoveFileExW(existingName, newName, flags))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }

    public static int ReplaceFileDurablePreservingMetadata(
        string replacedFileName,
        string replacementFileName,
        string backupFileName)
    {
        // ReplaceFileW currently documents only the two IGNORE_* flags.
        // Zero is intentional: 0x1 is reserved, not a write-through flag.
        if (ReplaceFileW(
            replacedFileName,
            replacementFileName,
            backupFileName,
            0,
            IntPtr.Zero,
            IntPtr.Zero))
        {
            return 0;
        }
        // A FALSE result is not side-effect-free for errors 1175/1176/1177.
        // Return the native error without throwing so the caller can reconcile
        // replaced/replacement/backup names before deciding what is durable.
        return Marshal.GetLastWin32Error();
    }
}
'@
}

function Sync-TicketboxFileDurable([string]$Path) {
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
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
            (ConvertTo-TicketboxWin32ExtendedPath $Source),
            (ConvertTo-TicketboxWin32ExtendedPath $Destination),
            [bool]$ReplaceExisting
        )
    }
    catch {
        throw "无法持久化提交文件：$Destination。$($_.Exception.GetBaseException().Message)"
    }
}

function Replace-TicketboxFileDurablePreservingMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$Replacement,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Backup
    )

    Initialize-TicketboxDurableFileNativeMethods
    try {
        $nativeError =
            [TicketboxDurableFileNativeMethods]::ReplaceFileDurablePreservingMetadata(
            (ConvertTo-TicketboxWin32ExtendedPath $Destination),
            (ConvertTo-TicketboxWin32ExtendedPath $Replacement),
            (ConvertTo-TicketboxWin32ExtendedPath $Backup)
        )
        return [pscustomobject][ordered]@{
            Succeeded = ([int]$nativeError -eq 0)
            NativeErrorCode = [int]$nativeError
        }
    }
    catch {
        throw (
            "无法持久化替换并保全现有文件 metadata：$Destination。" +
            $_.Exception.GetBaseException().Message
        )
    }
}

function Write-TicketboxUtf8FileDurable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [scriptblock]$ProtectTemporaryFile,
        [switch]$ReplaceExisting
    )
    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
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

function Initialize-TicketboxRestorePrivilegeMethods {
    if ("TicketboxRestorePrivilegeScope" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxRestorePrivilegeLuid
{
    internal uint LowPart;
    internal int HighPart;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxRestorePrivilegeLuidAndAttributes
{
    internal TicketboxRestorePrivilegeLuid Luid;
    internal uint Attributes;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxRestorePrivilegeTokenPrivileges
{
    internal uint PrivilegeCount;
    internal TicketboxRestorePrivilegeLuidAndAttributes Privileges;
}

public sealed class TicketboxRestorePrivilegeScope : IDisposable
{
    private const uint TokenQuery = 0x0008;
    private const uint TokenAdjustPrivileges = 0x0020;
    private const uint PrivilegeEnabled = 0x00000002;
    private const int ErrorNotAllAssigned = 1300;
    private IntPtr tokenHandle;
    private TicketboxRestorePrivilegeTokenPrivileges previousState;
    private bool restoreRequired;
    private bool disposed;

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(
        IntPtr processHandle,
        uint desiredAccess,
        out IntPtr tokenHandle);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool LookupPrivilegeValue(
        string systemName,
        string name,
        out TicketboxRestorePrivilegeLuid luid);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr tokenHandle,
        [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TicketboxRestorePrivilegeTokenPrivileges newState,
        int bufferLength,
        out TicketboxRestorePrivilegeTokenPrivileges previousState,
        out int returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr tokenHandle,
        [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TicketboxRestorePrivilegeTokenPrivileges newState,
        int bufferLength,
        IntPtr previousState,
        IntPtr returnLength);

    private TicketboxRestorePrivilegeScope(IntPtr handle)
    {
        tokenHandle = handle;
    }

    public static TicketboxRestorePrivilegeScope Enter()
    {
        IntPtr handle;
        if (!OpenProcessToken(
            GetCurrentProcess(),
            TokenQuery | TokenAdjustPrivileges,
            out handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        TicketboxRestorePrivilegeScope scope =
            new TicketboxRestorePrivilegeScope(handle);
        try
        {
            TicketboxRestorePrivilegeLuid luid;
            if (!LookupPrivilegeValue(null, "SeRestorePrivilege", out luid))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            TicketboxRestorePrivilegeTokenPrivileges requested =
                new TicketboxRestorePrivilegeTokenPrivileges();
            requested.PrivilegeCount = 1;
            requested.Privileges = new TicketboxRestorePrivilegeLuidAndAttributes
            {
                Luid = luid,
                Attributes = PrivilegeEnabled
            };
            int returnLength;
            bool adjusted = AdjustTokenPrivileges(
                handle,
                false,
                ref requested,
                Marshal.SizeOf(typeof(TicketboxRestorePrivilegeTokenPrivileges)),
                out scope.previousState,
                out returnLength);
            int error = Marshal.GetLastWin32Error();
            if (!adjusted || error == ErrorNotAllAssigned)
            {
                throw new Win32Exception(error);
            }
            scope.restoreRequired = true;
            return scope;
        }
        catch
        {
            scope.Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }
        disposed = true;
        Exception restoreFailure = null;
        if (restoreRequired)
        {
            bool restored = AdjustTokenPrivileges(
                tokenHandle,
                false,
                ref previousState,
                0,
                IntPtr.Zero,
                IntPtr.Zero);
            int restoreError = Marshal.GetLastWin32Error();
            if (!restored || restoreError == ErrorNotAllAssigned)
            {
                restoreFailure =
                    new Win32Exception(restoreError);
            }
        }
        if (tokenHandle != IntPtr.Zero)
        {
            CloseHandle(tokenHandle);
            tokenHandle = IntPtr.Zero;
        }
        if (restoreFailure != null)
        {
            throw restoreFailure;
        }
    }
}
'@
}

function Enter-TicketboxRestorePrivilegeForSecurityDescriptor($Security) {
    $ownerSid = $Security.GetOwner(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    $currentUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($ownerSid -eq $currentUserSid) {
        return $null
    }
    Initialize-TicketboxRestorePrivilegeMethods
    try {
        return [TicketboxRestorePrivilegeScope]::Enter()
    }
    catch {
        throw (
            "Windows 未授予创建受保护对象所需的 SeRestorePrivilege：" +
            $_.Exception.Message
        )
    }
}

function New-TicketboxProtectedFileSecurity {
    param(
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
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
    $security.SetOwner((New-Object System.Security.Principal.SecurityIdentifier(
        (ConvertTo-TicketboxAccountSid $OwnerAccount)
    )))
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

function New-TicketboxProtectedDirectorySecurity {
    param(
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$ReadExecuteAccounts = @(),
        [string[]]$InheritableReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullControlSids = @($FullControlAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $inheritableReadExecuteSids = @($InheritableReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if ($fullControlSids.Count -eq 0) {
        throw "受保护目录至少需要一个 FullControl 账户。"
    }
    if (
        @($fullControlSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0 -or
        @($fullControlSids | Where-Object { $_ -in $inheritableReadExecuteSids }).Count -gt 0 -or
        @($readExecuteSids | Where-Object { $_ -in $inheritableReadExecuteSids }).Count -gt 0
    ) {
        throw "受保护目录账户不能同时拥有 FullControl 与 ReadExecute。"
    }
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner((New-Object System.Security.Principal.SecurityIdentifier(
        (ConvertTo-TicketboxAccountSid $OwnerAccount)
    )))
    $inheritance =
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($sidValue in $fullControlSids) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )))
    }
    foreach ($sidValue in $readExecuteSids) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
            [System.Security.AccessControl.AccessControlType]::Allow
        )))
    }
    foreach ($sidValue in $inheritableReadExecuteSids) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )))
    }
    return $security
}

function Initialize-TicketboxProtectedDirectoryAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string[]]$ReadExecuteAccounts = @(),
        [string[]]$InheritableReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "受保护目录父路径不存在：$parent"
    }
    Assert-NoTicketboxAncestorReparsePoints $parent
    if (Test-Path -LiteralPath $fullPath) {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $fullPath `
            -FullControlAccounts $FullControlAccounts `
            -ReadExecuteAccounts $ReadExecuteAccounts `
            -InheritableReadExecuteAccounts $InheritableReadExecuteAccounts `
            -OwnerAccount $OwnerAccount
        return $fullPath
    }
    $security = New-TicketboxProtectedDirectorySecurity `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -InheritableReadExecuteAccounts $InheritableReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    $restorePrivilege = Enter-TicketboxRestorePrivilegeForSecurityDescriptor $security
    try {
        try {
            if ($PSVersionTable.PSEdition -eq "Core") {
                [System.IO.FileSystemAclExtensions]::CreateDirectory($security, $fullPath) | Out-Null
            }
            else {
                (New-Object System.IO.DirectoryInfo($fullPath)).Create($security)
            }
        }
        catch {
            $creationFailure = $_.Exception
            if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) {
                throw $creationFailure
            }
        }
    }
    finally {
        if ($null -ne $restorePrivilege) {
            $restorePrivilege.Dispose()
        }
    }
    Assert-NoTicketboxAncestorReparsePoints $fullPath
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $fullPath `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -InheritableReadExecuteAccounts $InheritableReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    return $fullPath
}

function New-TicketboxProtectedFileStream {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][System.Security.AccessControl.FileSecurity]$Security
    )

    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    $restorePrivilege = Enter-TicketboxRestorePrivilegeForSecurityDescriptor $Security
    try {
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
    finally {
        if ($null -ne $restorePrivilege) {
            $restorePrivilege.Dispose()
        }
    }
}

function Write-TicketboxProtectedUtf8FileDurable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM",
        [switch]$ReplaceExisting
    )

    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "受保护文件父目录不存在：$parent"
    }
    Assert-NoTicketboxAncestorReparsePoints $parent
    $temporaryPath = Join-Path $parent (".ticketbox-protected-{0}.tmp" -f [Guid]::NewGuid().ToString("N"))
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
    $security = New-TicketboxProtectedFileSecurity `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    try {
        $stream = New-TicketboxProtectedFileStream -Path $temporaryPath -Security $security
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally { $stream.Dispose() }
        $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount
        Set-TicketboxOwnerIfNeeded `
            -Path $temporaryPath `
            -ExpectedOwnerSid $expectedOwnerSid
        Assert-TicketboxExactFileAcl `
            -Path $temporaryPath `
            -Accounts $FullControlAccounts `
            -ReadExecuteAccounts $ReadExecuteAccounts `
            -OwnerAccount $OwnerAccount
        Move-TicketboxFileDurable `
            $temporaryPath `
            $fullPath `
            -ReplaceExisting:$ReplaceExisting
        Set-TicketboxOwnerIfNeeded `
            -Path $fullPath `
            -ExpectedOwnerSid $expectedOwnerSid
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

function Initialize-TicketboxInstallerStateDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "installer-state 父目录不存在：$parent"
    }
    Assert-NoTicketboxAncestorReparsePoints $parent
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $parent `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $fullPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount | Out-Null
    Remove-TicketboxProtectedStagingArtifacts `
        -Path $fullPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    return $fullPath
}

function Remove-TicketboxProtectedStagingArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $Path `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    foreach ($item in @(Get-ChildItem -LiteralPath $Path -Force)) {
        if ($item.Name -cnotmatch '^\.ticketbox-(protected|durable)-[0-9a-f]{32}\.tmp$') {
            continue
        }
        if (
            -not (Test-Path -LiteralPath $item.FullName -PathType Leaf) -or
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "受保护 staging artifact 不是普通文件：$($item.FullName)"
        }
        Set-TicketboxExactFileAcl `
            -Path $item.FullName `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        Remove-Item -LiteralPath $item.FullName -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $item.FullName) {
            throw "无法清理受保护 staging artifact：$($item.FullName)"
        }
    }
}

function Test-TicketboxByteArrayEquals {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )

    if ($Left.Length -ne $Right.Length) { return $false }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) { return $false }
    }
    return $true
}

function Read-TicketboxProtectedUtf8Artifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM",
        [ValidateRange(1, 1048576)][int]$MaximumBytes = 65536
    )

    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $fullPath
    Assert-NoTicketboxAncestorReparsePoints $fullPath
    if (-not (Test-Path -LiteralPath $extendedPath -PathType Leaf)) {
        throw "installer-state artifact 不存在或不是普通文件：$fullPath"
    }
    $item = Get-Item -LiteralPath $extendedPath -Force -ErrorAction Stop
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.Length -le 0 -or
        $item.Length -gt $MaximumBytes
    ) {
        throw "installer-state artifact 不是有效的受保护普通文件：$fullPath"
    }
    Assert-TicketboxExactFileAcl `
        -Path $fullPath `
        -Accounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    $bytes = [System.IO.File]::ReadAllBytes($extendedPath)
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    try { $text = $encoding.GetString($bytes) }
    catch { throw "installer-state artifact 不是严格 UTF-8：$fullPath" }
    $roundTripBytes = $encoding.GetBytes($text)
    if (-not (Test-TicketboxByteArrayEquals -Left $bytes -Right $roundTripBytes)) {
        throw "installer-state artifact 不能无损 UTF-8 往返：$fullPath"
    }
    return [PSCustomObject]@{
        Text = $text
        Bytes = $bytes
    }
}

function Remove-TicketboxProtectedUtf8Artifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
    )

    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $fullPath
    Read-TicketboxProtectedUtf8Artifact `
        -Path $fullPath `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $OwnerAccount | Out-Null
    Remove-Item -LiteralPath $extendedPath -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $extendedPath) {
        throw "无法清理受保护的 installer-state artifact：$fullPath"
    }
}

function Move-TicketboxLegacyInstallerStateArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$LegacyPath,
        [Parameter(Mandatory = $true)][string]$CurrentPath,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM",
        [switch]$RetainLegacySource
    )

    $legacyFullPath = ConvertTo-TicketboxWin32CanonicalPath $LegacyPath
    $currentFullPath = ConvertTo-TicketboxWin32CanonicalPath $CurrentPath
    if (Test-TicketboxPathEquals $legacyFullPath $currentFullPath) {
        throw "legacy 与 current installer-state artifact 不能是同一路径：$currentFullPath"
    }
    $currentParent = Split-Path -Parent $currentFullPath
    Assert-NoTicketboxAncestorReparsePoints $currentParent
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $currentParent `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount

    $legacyExists = Test-Path -LiteralPath $legacyFullPath
    $currentExists = Test-Path -LiteralPath $currentFullPath
    if ($legacyExists -and -not (Test-Path -LiteralPath $legacyFullPath -PathType Leaf)) {
        throw "legacy installer-state artifact 存在但不是普通文件：$legacyFullPath"
    }
    if ($currentExists -and -not (Test-Path -LiteralPath $currentFullPath -PathType Leaf)) {
        throw "current installer-state artifact 存在但不是普通文件：$currentFullPath"
    }

    $legacyArtifact = $null
    $currentArtifact = $null
    if ($legacyExists) {
        $legacyArtifact = Read-TicketboxProtectedUtf8Artifact `
            -Path $legacyFullPath `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
    }
    if ($currentExists) {
        $currentArtifact = Read-TicketboxProtectedUtf8Artifact `
            -Path $currentFullPath `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
    }
    if ($legacyExists -and $currentExists) {
        if (-not (Test-TicketboxByteArrayEquals -Left $legacyArtifact.Bytes -Right $currentArtifact.Bytes)) {
            throw "installer-state 新旧位置内容冲突，拒绝猜测权威文件：$currentFullPath"
        }
        if (-not $RetainLegacySource) {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path $legacyFullPath `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
        }
        return
    }
    if ($currentExists -or -not $legacyExists) { return }

    Write-TicketboxProtectedUtf8FileDurable `
        -Path $currentFullPath `
        -Text $legacyArtifact.Text `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    $publishedArtifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $currentFullPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    if (-not (Test-TicketboxByteArrayEquals -Left $legacyArtifact.Bytes -Right $publishedArtifact.Bytes)) {
        throw "installer-state artifact 发布后复读不一致：$currentFullPath"
    }
    if (-not $RetainLegacySource) {
        Remove-TicketboxProtectedUtf8Artifact `
            -Path $legacyFullPath `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
    }
}

function Assert-TicketboxProtectedDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string[]]$ReadExecuteAccounts = @(),
        [string[]]$InheritableReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
    )
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "受保护目录不存在：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "受保护目录不能是重解析点：$Path"
    }
    $fullControlSids = @($FullControlAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $inheritableReadExecuteSids = @($InheritableReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if (
        @($fullControlSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0 -or
        @($fullControlSids | Where-Object { $_ -in $inheritableReadExecuteSids }).Count -gt 0 -or
        @($readExecuteSids | Where-Object { $_ -in $inheritableReadExecuteSids }).Count -gt 0
    ) {
        throw "受保护目录账户不能同时拥有 FullControl 与 ReadExecute：$Path"
    }
    $expectedSids = @(
        $fullControlSids + $readExecuteSids + $inheritableReadExecuteSids |
            Sort-Object -Unique
    )
    $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount
    $acl = Get-TicketboxPathAcl $Path
    if (
        -not $acl.AreAccessRulesProtected -or
        (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $expectedOwnerSid
    ) {
        throw "受保护目录 owner 或继承状态不符合精确 ACL 契约：$Path"
    }
    $requiredInheritance =
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        $isFullControlRule =
            $ruleSid -in $fullControlSids -and
            $rule.FileSystemRights -eq [System.Security.AccessControl.FileSystemRights]::FullControl -and
            $rule.InheritanceFlags -eq $requiredInheritance
        $isReadExecuteRule =
            $ruleSid -in $readExecuteSids -and
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -eq
                [System.Security.AccessControl.FileSystemRights]::ReadAndExecute -and
            ($rule.FileSystemRights -band (
                [System.Security.AccessControl.FileSystemRights]::Write -bor
                [System.Security.AccessControl.FileSystemRights]::Delete -bor
                [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                [System.Security.AccessControl.FileSystemRights]::TakeOwnership
            )) -eq 0 -and
            $rule.InheritanceFlags -eq [System.Security.AccessControl.InheritanceFlags]::None
        $isInheritableReadExecuteRule =
            $ruleSid -in $inheritableReadExecuteSids -and
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -eq
                [System.Security.AccessControl.FileSystemRights]::ReadAndExecute -and
            ($rule.FileSystemRights -band (
                [System.Security.AccessControl.FileSystemRights]::Write -bor
                [System.Security.AccessControl.FileSystemRights]::Delete -bor
                [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                [System.Security.AccessControl.FileSystemRights]::TakeOwnership
            )) -eq 0 -and
            $rule.InheritanceFlags -eq $requiredInheritance
        if (
            $ruleSid -notin $expectedSids -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            (
                -not $isFullControlRule -and
                -not $isReadExecuteRule -and
                -not $isInheritableReadExecuteRule
            ) -or
            $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None -or
            $rule.IsInherited
        ) {
            throw "受保护目录含有精确 ACL 契约外规则或标志：$Path ($ruleSid)"
        }
    }
    foreach ($sid in $fullControlSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value -eq $sid
        })
        if ($matchingRules.Count -ne 1) {
            throw "受保护目录必须且只能有一条预期 FullControl：$Path ($sid)"
        }
    }
    foreach ($sid in $readExecuteSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value -eq $sid
        })
        if ($matchingRules.Count -ne 1) {
            throw "受保护目录必须且只能有一条预期 ReadExecute：$Path ($sid)"
        }
    }
    foreach ($sid in $inheritableReadExecuteSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value -eq $sid -and
            ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -eq
                [System.Security.AccessControl.FileSystemRights]::ReadAndExecute -and
            ($_.FileSystemRights -band (
                [System.Security.AccessControl.FileSystemRights]::Write -bor
                [System.Security.AccessControl.FileSystemRights]::Delete -bor
                [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
                [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
                [System.Security.AccessControl.FileSystemRights]::TakeOwnership
            )) -eq 0 -and
            $_.InheritanceFlags -eq $requiredInheritance
        })
        if ($matchingRules.Count -ne 1) {
            throw "受保护目录必须且只能有一条预期可继承 ReadExecute：$Path ($sid)"
        }
    }
}

function New-TicketboxDirectoryGuardCoordinationNonce {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return -join @($bytes | ForEach-Object { $_.ToString("x2") })
}

function ConvertTo-TicketboxCanonicalVolumeIdentity {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '^\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}\\$') {
        throw "Windows volume identity 不符合 Volume GUID path 契约：$Value"
    }
    return $Value.ToUpperInvariant()
}

function Get-TicketboxVolumeDescriptorForPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    Initialize-TicketboxDirectoryGuardNativeMethods
    $canonicalPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $volumePath = New-Object System.Text.StringBuilder 32768
    if (-not [TicketboxDirectoryGuardNativeMethods]::TryGetVolumePathName(
        $canonicalPath,
        $volumePath,
        [uint32]$volumePath.Capacity
    )) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "无法解析 DataRoot 的 Windows volume mount point（Win32=$errorCode）：$canonicalPath"
    }
    $volumeRoot = $volumePath.ToString()
    if (
        [string]::IsNullOrWhiteSpace($volumeRoot) -or
        -not $volumeRoot.EndsWith("\", [StringComparison]::Ordinal)
    ) {
        throw "DataRoot 没有可解析的 Windows volume mount point：$canonicalPath"
    }
    $volumeName = New-Object System.Text.StringBuilder 1024
    if (-not [TicketboxDirectoryGuardNativeMethods]::TryGetVolumeNameForVolumeMountPoint(
        $volumeRoot,
        $volumeName,
        [uint32]$volumeName.Capacity
    )) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "无法解析 DataRoot 的稳定 Windows volume identity（Win32=$errorCode）：$volumeRoot"
    }
    $fileSystemName = New-Object System.Text.StringBuilder 1024
    [uint32]$fileSystemFlags = 0
    if (-not [TicketboxDirectoryGuardNativeMethods]::TryGetVolumeInformation(
        $volumeRoot,
        $fileSystemName,
        [uint32]$fileSystemName.Capacity,
        [ref]$fileSystemFlags
    )) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "无法读取 DataRoot 卷的文件系统能力（Win32=$errorCode）：$volumeRoot"
    }
    return [pscustomobject]@{
        MountPoint = $volumeRoot
        Identity = ConvertTo-TicketboxCanonicalVolumeIdentity $volumeName.ToString()
        FileSystemName = $fileSystemName.ToString()
        FileSystemFlags = $fileSystemFlags
    }
}

function Get-TicketboxVolumeIdentityForPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-TicketboxVolumeDescriptorForPath $Path).Identity
}

function Assert-TicketboxDataRootVolumeCapabilities {
    param([Parameter(Mandatory = $true)][string]$Path)

    $descriptor = Get-TicketboxVolumeDescriptorForPath $Path
    [uint32]$filePersistentAcls = 0x00000008
    [uint32]$fileReadOnlyVolume = 0x00080000
    if (($descriptor.FileSystemFlags -band $filePersistentAcls) -eq 0) {
        throw (
            "数据目录所在卷不保存并强制执行 Windows ACL，不能安全安装小票夹：" +
            "$($descriptor.MountPoint) ($($descriptor.FileSystemName))"
        )
    }
    if (($descriptor.FileSystemFlags -band $fileReadOnlyVolume) -ne 0) {
        throw "数据目录所在卷为只读卷，不能安装小票夹：$($descriptor.MountPoint)"
    }
    return $descriptor
}

function Assert-TicketboxVolumeIdentityForPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedVolumeIdentity
    )

    $expected = ConvertTo-TicketboxCanonicalVolumeIdentity $ExpectedVolumeIdentity
    $actual = Get-TicketboxVolumeIdentityForPath $Path
    if ($actual -cne $expected) {
        throw "DataRoot 的 Windows volume identity 已变化；拒绝跨卷继续 provisioning：$Path"
    }
}

function Get-TicketboxRuntimeDataBindingDirectory([string]$CommonApplicationData = "") {
    if ([string]::IsNullOrWhiteSpace($CommonApplicationData)) {
        $CommonApplicationData = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::CommonApplicationData
        )
    }
    if ([string]::IsNullOrWhiteSpace($CommonApplicationData)) {
        throw "Windows 未提供 Common Application Data，无法建立 runtime DataRoot binding。"
    }
    return Join-Path `
        (ConvertTo-TicketboxWin32CanonicalPath $CommonApplicationData) `
        $script:TicketboxRuntimeDataBindingDirectoryName
}

function Get-TicketboxRuntimeDataRootPath([string]$CommonApplicationData = "") {
    return Join-Path `
        (Get-TicketboxRuntimeDataBindingDirectory $CommonApplicationData) `
        $script:TicketboxRuntimeDataBindingJunctionName
}

function Get-TicketboxRuntimeBootstrapRecoveryGuardPath([string]$RuntimeDataRoot = "") {
    if ([string]::IsNullOrWhiteSpace($RuntimeDataRoot)) {
        $RuntimeDataRoot = Get-TicketboxRuntimeDataRootPath
    }
    return Join-Path `
        (ConvertTo-TicketboxWin32CanonicalPath $RuntimeDataRoot) `
        $script:TicketboxBootstrapRecoveryGuardName
}

function Assert-TicketboxRuntimeDataBindingDomain {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string]$CommonApplicationData = ""
    )

    $bindingDirectory = Get-TicketboxRuntimeDataBindingDirectory $CommonApplicationData
    foreach ($protectedPath in @($DataRoot, $InstallDir)) {
        if (
            (Test-TicketboxPathWithin $bindingDirectory $protectedPath) -or
            (Test-TicketboxPathWithin $protectedPath $bindingDirectory)
        ) {
            throw "runtime DataRoot binding 不能与 DataRoot 或 InstallDir 重叠。"
        }
    }
    Assert-NoTicketboxAncestorReparsePoints $bindingDirectory
    return $bindingDirectory
}

function Get-TicketboxVolumeBoundDataRootPath {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$DataVolumeIdentity
    )

    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    $driveRoot = [System.IO.Path]::GetPathRoot($canonicalDataRoot)
    if ([string]::IsNullOrWhiteSpace($driveRoot)) {
        throw "DataRoot 没有可绑定 Volume GUID 的本机卷根。"
    }
    $relativePath = $canonicalDataRoot.Substring($driveRoot.Length).TrimStart("\")
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        throw "runtime DataRoot binding 不能指向卷根。"
    }
    return (ConvertTo-TicketboxCanonicalVolumeIdentity $DataVolumeIdentity) + $relativePath
}

function Initialize-TicketboxRuntimeJunctionNativeMethods {
    if ("TicketboxRuntimeJunctionNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class TicketboxRuntimeJunctionNativeMethods
{
    private const uint GenericWrite = 0x40000000;
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint FileShareDelete = 0x00000004;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FsctlSetReparsePoint = 0x000900A4;
    private const uint FsctlGetReparsePoint = 0x000900A8;
    private const uint IoReparseTagMountPoint = 0xA0000003;
    private const uint VolumeNameGuid = 0x00000001;
    private const int MaximumReparseDataBufferSize = 16 * 1024;
    private const string ExtendedVolumePrefix = @"\\?\Volume{";
    private const string NtPrefix = @"\??\";

    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateDirectoryW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateDirectoryW(
        string path,
        IntPtr securityAttributes);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "DeviceIoControl",
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetReparsePoint(
        SafeFileHandle device,
        uint controlCode,
        [In] byte[] inputBuffer,
        uint inputBufferSize,
        IntPtr outputBuffer,
        uint outputBufferSize,
        out uint bytesReturned,
        IntPtr overlapped);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "DeviceIoControl",
        ExactSpelling = true,
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetReparsePoint(
        SafeFileHandle device,
        uint controlCode,
        IntPtr inputBuffer,
        uint inputBufferSize,
        [Out] byte[] outputBuffer,
        uint outputBufferSize,
        out uint bytesReturned,
        IntPtr overlapped);

    [DllImport(
        "kernel32.dll",
        EntryPoint = "GetFinalPathNameByHandleW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        SafeFileHandle file,
        StringBuilder path,
        uint pathLength,
        uint flags);

    public static void CreateVolumeBoundDirectoryJunction(
        string junctionPath,
        string volumeTarget)
    {
        AssertCanonicalJunctionPath(junctionPath);
        AssertCanonicalVolumeTarget(volumeTarget);
        if (!Directory.Exists(volumeTarget))
        {
            throw new DirectoryNotFoundException(
                "The volume-bound junction target does not exist: " + volumeTarget);
        }
        string substituteName = NtPrefix + volumeTarget.Substring(4);
        byte[] substituteBytes = Encoding.Unicode.GetBytes(substituteName);
        byte[] printBytes = Encoding.Unicode.GetBytes(volumeTarget);
        int reparseDataLength = checked(12 + substituteBytes.Length + printBytes.Length);
        int bufferLength = checked(8 + reparseDataLength);
        if (bufferLength > MaximumReparseDataBufferSize ||
            substituteBytes.Length > UInt16.MaxValue ||
            printBytes.Length > UInt16.MaxValue)
        {
            throw new PathTooLongException(
                "The volume-bound junction target exceeds the reparse buffer limit.");
        }

        byte[] buffer = new byte[bufferLength];
        WriteUInt32(buffer, 0, IoReparseTagMountPoint);
        WriteUInt16(buffer, 4, checked((ushort)reparseDataLength));
        WriteUInt16(buffer, 6, 0);
        WriteUInt16(buffer, 8, 0);
        WriteUInt16(buffer, 10, checked((ushort)substituteBytes.Length));
        WriteUInt16(buffer, 12, checked((ushort)(substituteBytes.Length + 2)));
        WriteUInt16(buffer, 14, checked((ushort)printBytes.Length));
        Buffer.BlockCopy(substituteBytes, 0, buffer, 16, substituteBytes.Length);
        Buffer.BlockCopy(
            printBytes,
            0,
            buffer,
            16 + substituteBytes.Length + 2,
            printBytes.Length);

        if (!CreateDirectoryW(junctionPath, IntPtr.Zero))
        {
            ThrowLastWin32("Unable to create the exact junction directory", junctionPath);
        }
        bool created = false;
        try
        {
            using (SafeFileHandle handle = OpenJunction(junctionPath, GenericWrite))
            {
                uint returned;
                if (!SetReparsePoint(
                    handle,
                    FsctlSetReparsePoint,
                    buffer,
                    (uint)buffer.Length,
                    IntPtr.Zero,
                    0,
                    out returned,
                    IntPtr.Zero))
                {
                    ThrowLastWin32("Unable to create the volume-bound junction", junctionPath);
                }
            }
            created = true;
        }
        finally
        {
            if (!created && Directory.Exists(junctionPath))
            {
                Directory.Delete(junctionPath, false);
            }
        }
    }

    public static string ReadMountPointSubstituteName(string junctionPath)
    {
        AssertCanonicalJunctionPath(junctionPath);
        byte[] buffer = new byte[MaximumReparseDataBufferSize];
        uint returned;
        using (SafeFileHandle handle = OpenJunction(junctionPath, 0))
        {
            if (!GetReparsePoint(
                handle,
                FsctlGetReparsePoint,
                IntPtr.Zero,
                0,
                buffer,
                (uint)buffer.Length,
                out returned,
                IntPtr.Zero))
            {
                ThrowLastWin32("Unable to read the runtime junction", junctionPath);
            }
        }
        if (returned < 16 || ReadUInt32(buffer, 0) != IoReparseTagMountPoint)
        {
            throw new IOException(
                "The runtime DataRoot reparse point is not a directory junction: " +
                junctionPath);
        }
        int reparseDataLength = ReadUInt16(buffer, 4);
        if (reparseDataLength < 12 || checked(reparseDataLength + 8) > returned)
        {
            throw new IOException("The runtime junction reparse buffer is malformed.");
        }
        int substituteOffset = ReadUInt16(buffer, 8);
        int substituteLength = ReadUInt16(buffer, 10);
        int pathBufferLength = reparseDataLength - 8;
        if ((substituteOffset & 1) != 0 || (substituteLength & 1) != 0 ||
            substituteOffset < 0 || substituteLength < 2 ||
            checked(substituteOffset + substituteLength) > pathBufferLength)
        {
            throw new IOException("The runtime junction substitute name is malformed.");
        }
        return Encoding.Unicode.GetString(
            buffer,
            checked(16 + substituteOffset),
            substituteLength);
    }

    public static string ReadVolumeBoundTarget(string junctionPath)
    {
        string substituteName = ReadMountPointSubstituteName(junctionPath);
        if (!substituteName.StartsWith(NtPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new IOException(
                "The runtime junction does not use an absolute NT substitute name.");
        }
        string target = @"\\?\" + substituteName.Substring(NtPrefix.Length);
        AssertCanonicalVolumeTarget(target);
        return target;
    }

    public static string ResolveDirectoryTarget(string junctionPath)
    {
        AssertCanonicalJunctionPath(junctionPath);
        using (SafeFileHandle handle = CreateFileW(
            junctionPath,
            0,
            FileShareRead | FileShareWrite | FileShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics,
            IntPtr.Zero))
        {
            if (handle.IsInvalid)
            {
                ThrowLastWin32("Unable to traverse the runtime junction", junctionPath);
            }
            StringBuilder path = new StringBuilder(512);
            uint length = GetFinalPathNameByHandleW(
                handle,
                path,
                (uint)path.Capacity,
                VolumeNameGuid);
            if (length == 0)
            {
                ThrowLastWin32("Unable to resolve the runtime junction target", junctionPath);
            }
            if (length >= path.Capacity)
            {
                path = new StringBuilder(checked((int)length + 1));
                length = GetFinalPathNameByHandleW(
                    handle,
                    path,
                    (uint)path.Capacity,
                    VolumeNameGuid);
                if (length == 0 || length >= path.Capacity)
                {
                    ThrowLastWin32(
                        "Unable to resolve the complete runtime junction target",
                        junctionPath);
                }
            }
            return path.ToString();
        }
    }

    private static SafeFileHandle OpenJunction(string junctionPath, uint desiredAccess)
    {
        SafeFileHandle handle = CreateFileW(
            junctionPath,
            desiredAccess,
            FileShareRead | FileShareWrite | FileShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            ThrowLastWin32("Unable to open the exact runtime junction", junctionPath);
        }
        return handle;
    }

    private static void AssertCanonicalJunctionPath(string path)
    {
        if (String.IsNullOrEmpty(path) ||
            !String.Equals(path, path.Trim(), StringComparison.Ordinal) ||
            path.IndexOf('\0') >= 0 ||
            !Path.IsPathRooted(path))
        {
            throw new ArgumentException(
                "The junction path must be a canonical absolute Windows path.",
                "path");
        }
    }

    private static void AssertCanonicalVolumeTarget(string target)
    {
        if (String.IsNullOrEmpty(target) ||
            !String.Equals(target, target.Trim(), StringComparison.Ordinal) ||
            target.IndexOf('\0') >= 0 ||
            target.IndexOf('/') >= 0 ||
            !target.StartsWith(ExtendedVolumePrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                "The junction target must use a canonical volume GUID path.",
                "target");
        }
        int closeBrace = target.IndexOf('}', ExtendedVolumePrefix.Length);
        Guid volumeGuid;
        if (closeBrace < 0 || closeBrace + 2 >= target.Length ||
            target[closeBrace + 1] != '\\' ||
            !Guid.TryParse(
                target.Substring(
                    ExtendedVolumePrefix.Length,
                    closeBrace - ExtendedVolumePrefix.Length),
                out volumeGuid))
        {
            throw new ArgumentException(
                "The junction target contains an invalid or root-only volume GUID path.",
                "target");
        }
    }

    private static void WriteUInt16(byte[] buffer, int offset, ushort value)
    {
        byte[] encoded = BitConverter.GetBytes(value);
        Buffer.BlockCopy(encoded, 0, buffer, offset, encoded.Length);
    }

    private static void WriteUInt32(byte[] buffer, int offset, uint value)
    {
        byte[] encoded = BitConverter.GetBytes(value);
        Buffer.BlockCopy(encoded, 0, buffer, offset, encoded.Length);
    }

    private static ushort ReadUInt16(byte[] buffer, int offset)
    {
        return BitConverter.ToUInt16(buffer, offset);
    }

    private static uint ReadUInt32(byte[] buffer, int offset)
    {
        return BitConverter.ToUInt32(buffer, offset);
    }

    private static void ThrowLastWin32(string operation, string path)
    {
        int error = Marshal.GetLastWin32Error();
        throw new Win32Exception(error, operation + ": " + path);
    }
}
'@
}

function New-TicketboxRuntimeDataJunction {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Target
    )

    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    $Target = ConvertTo-TicketboxCanonicalVolumeIdentityTarget $Target
    Initialize-TicketboxRuntimeJunctionNativeMethods
    [TicketboxRuntimeJunctionNativeMethods]::CreateVolumeBoundDirectoryJunction(
        $Path,
        $Target
    )
}

function ConvertTo-TicketboxCanonicalVolumeIdentityTarget([string]$Target) {
    if ([string]::IsNullOrWhiteSpace($Target)) {
        throw "Volume GUID target 不能为空。"
    }
    $separator = $Target.IndexOf("\", 4)
    if ($separator -lt 0) {
        throw "Volume GUID target 缺少卷内路径。"
    }
    $volumeIdentity = $Target.Substring(0, $separator + 1)
    $relativePath = $Target.Substring($separator + 1)
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        throw "Volume GUID target 不能指向卷根。"
    }
    return (ConvertTo-TicketboxCanonicalVolumeIdentity $volumeIdentity) + $relativePath
}

function Get-TicketboxRuntimeDataJunctionTarget([string]$Path) {
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    Initialize-TicketboxRuntimeJunctionNativeMethods
    return [TicketboxRuntimeJunctionNativeMethods]::ReadVolumeBoundTarget($Path)
}

function Get-TicketboxRuntimeDataJunctionResolvedTarget([string]$Path) {
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    Initialize-TicketboxRuntimeJunctionNativeMethods
    return [TicketboxRuntimeJunctionNativeMethods]::ResolveDirectoryTarget($Path)
}

function Test-TicketboxLegacyMalformedRuntimeDataJunction {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedTarget
    )

    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    $ExpectedTarget = ConvertTo-TicketboxCanonicalVolumeIdentityTarget $ExpectedTarget
    Initialize-TicketboxRuntimeJunctionNativeMethods
    $actualSubstitute =
        [TicketboxRuntimeJunctionNativeMethods]::ReadMountPointSubstituteName($Path)
    $legacyMalformedSubstitute = "\??\$ExpectedTarget"
    return [string]::Equals(
        $actualSubstitute,
        $legacyMalformedSubstitute,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Read-TicketboxRuntimeDataBinding {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$ServiceReadExecuteAccounts,
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$DataRootMarkerAclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$CommonApplicationData = "",
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $DataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $InstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    Get-TicketboxRuntimeDataBindingDirectory $CommonApplicationData | Out-Null
    $marker = Read-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $FullControlAccounts `
        -AclPhase $DataRootMarkerAclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -OwnerAccount $OwnerAccount
    $bindingDirectory = Assert-TicketboxRuntimeDataBindingDomain `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -CommonApplicationData $CommonApplicationData
    $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath $CommonApplicationData
    if ((Get-TicketboxPathEntryKindNoFollow $bindingDirectory) -cne "Directory") {
        throw "runtime DataRoot binding root 不是受保护的普通目录。"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $bindingDirectory `
        -FullControlAccounts $FullControlAccounts `
        -InheritableReadExecuteAccounts $ServiceReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    if ((Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot) -cne "Reparse") {
        throw "runtime DataRoot binding 必须是专用 junction。"
    }
    $expectedTarget = Get-TicketboxVolumeBoundDataRootPath `
        -DataRoot $DataRoot `
        -DataVolumeIdentity $marker.DataVolumeIdentity
    $actualTarget = Get-TicketboxRuntimeDataJunctionTarget $runtimeDataRoot
    $resolvedTarget = Get-TicketboxRuntimeDataJunctionResolvedTarget $runtimeDataRoot
    if (
        -not [string]::Equals(
            $actualTarget.TrimEnd("\"),
            $expectedTarget.TrimEnd("\"),
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        -not [string]::Equals(
            $resolvedTarget.TrimEnd("\"),
            $expectedTarget.TrimEnd("\"),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "runtime DataRoot junction 与 v2 marker 的 Volume GUID 绑定不一致。"
    }
    return [pscustomobject]@{
        BindingDirectory = $bindingDirectory
        RuntimeDataRoot = $runtimeDataRoot
        RuntimeAppData = Join-Path $runtimeDataRoot "app"
        RuntimePgData = Join-Path $runtimeDataRoot "pgdata"
        DataVolumeIdentity = $marker.DataVolumeIdentity
        VolumeBoundTarget = $expectedTarget
    }
}

function Repair-TicketboxLegacyMalformedRuntimeDataBindingIfNeeded {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$ServiceReadExecuteAccounts,
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$DataRootMarkerAclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$CommonApplicationData = "",
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $DataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $InstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $bindingDirectory = Assert-TicketboxRuntimeDataBindingDomain `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -CommonApplicationData $CommonApplicationData
    $bindingKind = Get-TicketboxPathEntryKindNoFollow $bindingDirectory
    if ($bindingKind -ceq "Missing") {
        return $false
    }
    if ($bindingKind -cne "Directory") {
        throw "runtime DataRoot binding root 形态不安全：$bindingKind"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $bindingDirectory `
        -FullControlAccounts $FullControlAccounts `
        -InheritableReadExecuteAccounts $ServiceReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath $CommonApplicationData
    if ((Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot) -cne "Reparse") {
        return $false
    }
    $marker = Read-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $FullControlAccounts `
        -AclPhase $DataRootMarkerAclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -OwnerAccount $OwnerAccount
    $target = Get-TicketboxVolumeBoundDataRootPath `
        -DataRoot $DataRoot `
        -DataVolumeIdentity $marker.DataVolumeIdentity
    if (-not (Test-TicketboxLegacyMalformedRuntimeDataJunction `
        -Path $runtimeDataRoot `
        -ExpectedTarget $target)) {
        return $false
    }

    # Windows PowerShell and PowerShell 7 both pass the Volume-GUID target to
    # New-Item, but the provider stores a double-prefixed NT substitute name.
    # The protected parent and exact raw substitute are verified before this
    # one known historical residual is replaced; all foreign reparses survive.
    [System.IO.Directory]::Delete($runtimeDataRoot, $false)
    New-TicketboxRuntimeDataJunction `
        -Path $runtimeDataRoot `
        -Target $target
    Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $ServiceReadExecuteAccounts `
        -DataRootMarkerAclPhase $DataRootMarkerAclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -CommonApplicationData $CommonApplicationData `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount | Out-Null
    return $true
}

function Initialize-TicketboxRuntimeDataBinding {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$ServiceReadExecuteAccounts,
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$DataRootMarkerAclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$CommonApplicationData = "",
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $DataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $InstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    Get-TicketboxRuntimeDataBindingDirectory $CommonApplicationData | Out-Null
    $marker = Read-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $FullControlAccounts `
        -AclPhase $DataRootMarkerAclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -OwnerAccount $OwnerAccount
    $bindingDirectory = Assert-TicketboxRuntimeDataBindingDomain `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -CommonApplicationData $CommonApplicationData
    $bindingKind = Get-TicketboxPathEntryKindNoFollow $bindingDirectory
    if ($bindingKind -ceq "Missing") {
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $bindingDirectory `
            -FullControlAccounts $FullControlAccounts `
            -InheritableReadExecuteAccounts $ServiceReadExecuteAccounts `
            -OwnerAccount $OwnerAccount | Out-Null
    }
    elseif ($bindingKind -ceq "Directory") {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $bindingDirectory `
            -FullControlAccounts $FullControlAccounts `
            -InheritableReadExecuteAccounts $ServiceReadExecuteAccounts `
            -OwnerAccount $OwnerAccount
    }
    else {
        throw "runtime DataRoot binding root 形态不安全：$bindingKind"
    }
    $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath $CommonApplicationData
    $junctionKind = Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot
    $target = Get-TicketboxVolumeBoundDataRootPath `
        -DataRoot $DataRoot `
        -DataVolumeIdentity $marker.DataVolumeIdentity
    if ($junctionKind -ceq "Missing") {
        try {
            New-TicketboxRuntimeDataJunction `
                -Path $runtimeDataRoot `
                -Target $target
        }
        catch {
            if ((Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot) -cne "Reparse") {
                throw
            }
        }
    }
    elseif ($junctionKind -ceq "Reparse") {
        Repair-TicketboxLegacyMalformedRuntimeDataBindingIfNeeded `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -ServiceReadExecuteAccounts $ServiceReadExecuteAccounts `
            -DataRootMarkerAclPhase $DataRootMarkerAclPhase `
            -ExpectedBackendServiceName $ExpectedBackendServiceName `
            -CommonApplicationData $CommonApplicationData `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount | Out-Null
    }
    else {
        throw "runtime DataRoot binding child 不是 junction 或缺失路径。"
    }
    return Read-TicketboxRuntimeDataBinding `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -ServiceReadExecuteAccounts $ServiceReadExecuteAccounts `
        -DataRootMarkerAclPhase $DataRootMarkerAclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -CommonApplicationData $CommonApplicationData `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
}

function Remove-TicketboxRuntimeDataBinding {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$ServiceReadExecuteAccounts,
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$DataRootMarkerAclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$CommonApplicationData = "",
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $DataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $InstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $bindingDirectory = Get-TicketboxRuntimeDataBindingDirectory $CommonApplicationData
    if ((Get-TicketboxPathEntryKindNoFollow $bindingDirectory) -ceq "Missing") {
        return
    }
    $bindingDirectory = Assert-TicketboxRuntimeDataBindingDomain `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -CommonApplicationData $CommonApplicationData
    if ((Get-TicketboxPathEntryKindNoFollow $bindingDirectory) -cne "Directory") {
        throw "runtime DataRoot binding root 不是受保护的普通目录。"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $bindingDirectory `
        -FullControlAccounts $FullControlAccounts `
        -InheritableReadExecuteAccounts $ServiceReadExecuteAccounts `
        -OwnerAccount $OwnerAccount
    $runtimeDataRoot = Get-TicketboxRuntimeDataRootPath $CommonApplicationData
    $junctionKind = Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot
    if ($junctionKind -ceq "Reparse") {
        Read-TicketboxRuntimeDataBinding `
            -DataRoot $DataRoot `
            -InstallDir $InstallDir `
            -ServiceReadExecuteAccounts $ServiceReadExecuteAccounts `
            -DataRootMarkerAclPhase $DataRootMarkerAclPhase `
            -ExpectedBackendServiceName $ExpectedBackendServiceName `
            -CommonApplicationData $CommonApplicationData `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount | Out-Null
        [System.IO.Directory]::Delete($runtimeDataRoot)
        if ((Get-TicketboxPathEntryKindNoFollow $runtimeDataRoot) -cne "Missing") {
            throw "无法退役 runtime DataRoot junction。"
        }
    }
    elseif ($junctionKind -cne "Missing") {
        throw "runtime DataRoot binding child 不是可退役的 junction 或已删除状态。"
    }
    $remaining = @(Get-ChildItem -LiteralPath $bindingDirectory -Force -ErrorAction Stop)
    if ($remaining.Count -gt 0) {
        throw "runtime DataRoot binding root 含有未知 artifact：$($remaining.Name -join ', ')"
    }
    Remove-Item -LiteralPath $bindingDirectory -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $bindingDirectory) {
        throw "无法退役 runtime DataRoot binding root。"
    }
}

function Get-TicketboxDataRootProvisioningIntentText {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string]$DataVolumeIdentity = ""
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    $canonicalVolumeIdentity = if ([string]::IsNullOrWhiteSpace($DataVolumeIdentity)) {
        Get-TicketboxVolumeIdentityForPath $canonicalDataRoot
    }
    else {
        ConvertTo-TicketboxCanonicalVolumeIdentity $DataVolumeIdentity
    }
    $dataRootBase64 = [Convert]::ToBase64String(
        $encoding.GetBytes($canonicalDataRoot)
    )
    $dataVolumeBase64 = [Convert]::ToBase64String(
        $encoding.GetBytes($canonicalVolumeIdentity)
    )
    $installDirBase64 = [Convert]::ToBase64String(
        $encoding.GetBytes($canonicalInstallDir)
    )
    return (
        "SCHEMA=$script:TicketboxDataRootProvisioningIntentSchema$([Environment]::NewLine)" +
        "DATA_ROOT_UTF8_B64=$dataRootBase64$([Environment]::NewLine)" +
        "DATA_VOLUME_UTF8_B64=$dataVolumeBase64$([Environment]::NewLine)" +
        "INSTALL_DIR_UTF8_B64=$installDirBase64$([Environment]::NewLine)"
    )
}

function Read-TicketboxDataRootProvisioningIntent {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount `
        -MaximumBytes 131072
    $escapedSchema = [Text.RegularExpressions.Regex]::Escape(
        $script:TicketboxDataRootProvisioningIntentSchema
    )
    $pattern = (
        "\ASCHEMA=$escapedSchema\r?\n" +
        "DATA_ROOT_UTF8_B64=(?<data>[A-Za-z0-9+/]+={0,2})\r?\n" +
        "DATA_VOLUME_UTF8_B64=(?<volume>[A-Za-z0-9+/]+={0,2})\r?\n" +
        "INSTALL_DIR_UTF8_B64=(?<install>[A-Za-z0-9+/]+={0,2})\r?\n\z"
    )
    $match = [Text.RegularExpressions.Regex]::Match(
        $artifact.Text,
        $pattern,
        [Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if (-not $match.Success) {
        throw "DataRoot provisioning intent 结构不符合严格 schema。"
    }
    try {
        $encoding = New-Object System.Text.UTF8Encoding($false, $true)
        $dataRoot = $encoding.GetString(
            [Convert]::FromBase64String($match.Groups["data"].Value)
        )
        $dataVolumeIdentity = $encoding.GetString(
            [Convert]::FromBase64String($match.Groups["volume"].Value)
        )
        $installDir = $encoding.GetString(
            [Convert]::FromBase64String($match.Groups["install"].Value)
        )
        $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $dataRoot
        $canonicalVolumeIdentity = ConvertTo-TicketboxCanonicalVolumeIdentity `
            $dataVolumeIdentity
        $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath $installDir
    }
    catch {
        throw "DataRoot provisioning intent 路径编码无效：$($_.Exception.Message)"
    }
    $canonicalText = Get-TicketboxDataRootProvisioningIntentText `
        -DataRoot $canonicalDataRoot `
        -InstallDir $canonicalInstallDir `
        -DataVolumeIdentity $canonicalVolumeIdentity
    if ($artifact.Text -cne $canonicalText) {
        throw "DataRoot provisioning intent 不是规范路径编码。"
    }
    return [pscustomobject]@{
        Text = $artifact.Text
        DataRoot = $canonicalDataRoot
        DataVolumeIdentity = $canonicalVolumeIdentity
        InstallDir = $canonicalInstallDir
    }
}

function Remove-TicketboxDirectoryGuardCoordinationArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ParentPath,
        [Parameter(Mandatory = $true)][string[]]$Paths,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $parentFullPath = ConvertTo-TicketboxWin32CanonicalPath $ParentPath
    $fullPaths = @($Paths | ForEach-Object {
        ConvertTo-TicketboxWin32CanonicalPath $_
    })
    foreach ($fullPath in $fullPaths) {
        if (-not (Test-TicketboxPathEquals (Split-Path -Parent $fullPath) $parentFullPath)) {
            throw "DataRoot guard cleanup artifact 越出受保护 IPC 目录。"
        }
    }
    Assert-NoTicketboxAncestorReparsePoints $parentFullPath
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $parentFullPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    foreach ($fullPath in $fullPaths) {
        if (-not (Test-Path -LiteralPath $fullPath)) {
            continue
        }
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if (
            $item -isnot [System.IO.FileInfo] -or
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "DataRoot guard cleanup artifact 不是普通文件：$fullPath"
        }
        Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $fullPath) {
            throw "无法清理 DataRoot guard coordination artifact：$fullPath"
        }
    }
}

function Wait-TicketboxDirectoryMutationGuardLease {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$ReadyPath,
        [Parameter(Mandatory = $true)][string]$ReleasePath,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$OwnerProcessId,
        [Parameter(Mandatory = $true)][object]$OwnerIdentity,
        [Parameter(Mandatory = $true)][scriptblock]$OnLeaseReady,
        [string]$RetainWhileLockPath = "",
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string]$OwnerAccount = "SYSTEM"
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $Path
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $readyFullPath = ConvertTo-TicketboxWin32CanonicalPath $ReadyPath
    $releaseFullPath = ConvertTo-TicketboxWin32CanonicalPath $ReleasePath
    $retainWhileLockFullPath = if (
        [string]::IsNullOrWhiteSpace($RetainWhileLockPath)
    ) {
        ""
    }
    else {
        ConvertTo-TicketboxWin32CanonicalPath $RetainWhileLockPath
    }
    $readyParent = Split-Path -Parent $readyFullPath
    $releaseParent = Split-Path -Parent $releaseFullPath
    if (-not (Test-TicketboxPathEquals $readyParent $releaseParent)) {
        throw "DataRoot guard ready/release artifact 必须位于同一受保护目录。"
    }
    Assert-NoTicketboxAncestorReparsePoints $readyParent
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $readyParent `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    if (
        (Test-Path -LiteralPath $readyFullPath) -or
        (Test-Path -LiteralPath $releaseFullPath)
    ) {
        throw "DataRoot guard artifact 已存在，拒绝复用可能过期的 lease。"
    }

    $provisioningIntentPath = Join-Path `
        $readyParent `
        $script:TicketboxDataRootProvisioningIntentName
    $provisioningState = [pscustomobject]@{
        Active = $false
        ExpectedVolumeIdentity = ""
    }

    $ownerHandleLease = Open-TicketboxVerifiedProcessIdentityHandle `
        -ProcessId $OwnerProcessId `
        -ExpectedIdentity $OwnerIdentity
    $guard = $null
    try {
        $provisioningIntentKind = Get-TicketboxPathEntryKindNoFollow $provisioningIntentPath
        if ($provisioningIntentKind -ceq "File") {
            $provisioningIntent = Read-TicketboxDataRootProvisioningIntent `
                -Path $provisioningIntentPath `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            if (
                -not (Test-TicketboxPathEquals $provisioningIntent.DataRoot $canonicalDataRoot) -or
                -not (Test-TicketboxPathEquals $provisioningIntent.InstallDir $canonicalInstallDir)
            ) {
                throw (
                    "DataRoot provisioning intent 固定绑定 " +
                    "$($provisioningIntent.DataRoot) / $($provisioningIntent.InstallDir)；" +
                    "请按原路径重试或进入显式 recovery，拒绝自动改绑。"
                )
            }
            $provisioningState.Active = $true
            $provisioningState.ExpectedVolumeIdentity = `
                $provisioningIntent.DataVolumeIdentity
        }
        elseif ($provisioningIntentKind -cne "Missing") {
            throw "DataRoot provisioning intent 形态不可判定，拒绝继续。"
        }

        $dataRootEntryKind = Get-TicketboxPathEntryKindNoFollow $canonicalDataRoot
        if ($dataRootEntryKind -notin @("Missing", "Directory")) {
            throw "DataRoot 不是普通目录或缺失路径，拒绝创建 guard：$canonicalDataRoot"
        }
        $publishProvisioningIntent = $null
        if ($dataRootEntryKind -ceq "Missing") {
            $publishProvisioningIntent = {
                $mountedVolumeIdentity = Get-TicketboxVolumeIdentityForPath `
                    $canonicalDataRoot
                if ($provisioningState.Active) {
                    if (
                        $mountedVolumeIdentity -cne
                        $provisioningState.ExpectedVolumeIdentity
                    ) {
                        throw "DataRoot provisioning intent 绑定的原卷当前不可用或已被替换。"
                    }
                }
                else {
                    $expectedProvisioningIntent = Get-TicketboxDataRootProvisioningIntentText `
                        -DataRoot $canonicalDataRoot `
                        -InstallDir $canonicalInstallDir `
                        -DataVolumeIdentity $mountedVolumeIdentity
                    Write-TicketboxProtectedUtf8FileDurable `
                        -Path $provisioningIntentPath `
                        -Text $expectedProvisioningIntent `
                        -FullControlAccounts $FullControlAccounts `
                        -OwnerAccount $OwnerAccount
                    $persistedProvisioningIntent = Read-TicketboxDataRootProvisioningIntent `
                        -Path $provisioningIntentPath `
                        -FullControlAccounts $FullControlAccounts `
                        -OwnerAccount $OwnerAccount
                    if ($persistedProvisioningIntent.Text -cne $expectedProvisioningIntent) {
                        throw "DataRoot provisioning intent 写后复读不一致。"
                    }
                    $provisioningState.Active = $true
                    $provisioningState.ExpectedVolumeIdentity = $mountedVolumeIdentity
                }
            }.GetNewClosure()
        }

        $guard = Enter-TicketboxDirectoryMutationGuard `
            -Path $canonicalDataRoot `
            -CreateMissingDirectories `
            -OnBeforeFirstDirectoryCreation $publishProvisioningIntent `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        if (-not [string]::IsNullOrWhiteSpace($provisioningState.ExpectedVolumeIdentity)) {
            Assert-TicketboxVolumeIdentityForPath `
                -Path $canonicalDataRoot `
                -ExpectedVolumeIdentity $provisioningState.ExpectedVolumeIdentity
        }
        $dataRootCreated = @($guard.CreatedPaths | Where-Object {
            Test-TicketboxPathEquals $_ $canonicalDataRoot
        }).Count -eq 1
        $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
        $markerKind = Get-TicketboxPathEntryKindNoFollow $markerPath
        if ($dataRootCreated -or $provisioningState.Active) {
            Assert-TicketboxProtectedDirectoryAcl `
                -Path $canonicalDataRoot `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            if ($markerKind -ceq "Missing") {
                Remove-TicketboxProtectedStagingArtifacts `
                    -Path $canonicalDataRoot `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount
                $existingEntries = @(
                    Get-ChildItem -LiteralPath $canonicalDataRoot -Force -ErrorAction Stop
                )
                if ($existingEntries.Count -ne 0) {
                    throw "DataRoot provisioning intent 只允许恢复仍为空的受保护目录。"
                }
                Write-TicketboxDataRootMarker `
                    -DataRoot $canonicalDataRoot `
                    -InstallDir $canonicalInstallDir `
                    -DataVolumeIdentity $provisioningState.ExpectedVolumeIdentity `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount
            }
            elseif ($markerKind -cne "File") {
                throw "DataRoot marker 形态不可判定，拒绝完成 provisioning。"
            }
            Assert-TicketboxProtectedDataRootMarker `
                -DataRoot $canonicalDataRoot `
                -InstallDir $canonicalInstallDir `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            Assert-TicketboxVolumeIdentityForPath `
                -Path $canonicalDataRoot `
                -ExpectedVolumeIdentity $provisioningState.ExpectedVolumeIdentity
            Remove-TicketboxDirectoryGuardCoordinationArtifacts `
                -ParentPath $readyParent `
                -Paths @($provisioningIntentPath) `
                -FullControlAccounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            $provisioningState.Active = $false
        }
        elseif ($markerKind -ceq "File") {
            Assert-TicketboxDataRootMarker `
                -DataRoot $canonicalDataRoot `
                -InstallDir $canonicalInstallDir `
                -AllowLegacyV1
        }
        elseif ($markerKind -ceq "Missing") {
            $existingEntries = @(Get-ChildItem -LiteralPath $canonicalDataRoot -Force -ErrorAction Stop)
            if ($existingEntries.Count -eq 0) {
                throw "预先存在的空 DataRoot 没有安装权威 marker；拒绝在可能保留旧写句柄的目录上事后收紧 ACL。"
            }
            # The holder grants only a race-free directory lease. The short-lived
            # prepare step must prove legacy authority before any mutation.
        }
        else {
            throw "DataRoot marker 不是普通文件或缺失路径，拒绝继续。"
        }

        $coordinationNonce = New-TicketboxDirectoryGuardCoordinationNonce
        $holderIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
        $readyText =
            "STATE=holding$([Environment]::NewLine)" +
            "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)" +
            "HOLDER_PID=$PID$([Environment]::NewLine)" +
            "HOLDER_STARTED_FILETIME_HIGH=$($holderIdentity.StartedFileTimeHigh)$([Environment]::NewLine)" +
            "HOLDER_STARTED_FILETIME_LOW=$($holderIdentity.StartedFileTimeLow)$([Environment]::NewLine)" +
            "NONCE=$coordinationNonce$([Environment]::NewLine)"
        Write-TicketboxProtectedUtf8FileDurable `
            -Path $readyFullPath `
            -Text $readyText `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        $persistedReady = Read-TicketboxProtectedUtf8Artifact `
            -Path $readyFullPath `
            -FullControlAccounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount `
            -MaximumBytes 512
        if ($persistedReady.Text -cne $readyText) {
            throw "DataRoot guard ready artifact 写后复读不一致。"
        }
        & $OnLeaseReady

        $releaseAccepted = $false
        while ($true) {
            if (-not $releaseAccepted -and (Test-Path -LiteralPath $releaseFullPath -PathType Leaf)) {
                $releaseArtifact = Read-TicketboxProtectedUtf8Artifact `
                    -Path $releaseFullPath `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount `
                    -MaximumBytes 256
                $expectedRelease =
                    "STATE=release$([Environment]::NewLine)" +
                    "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)" +
                    "NONCE=$coordinationNonce$([Environment]::NewLine)"
                $expectedAbort =
                    "STATE=abort$([Environment]::NewLine)" +
                    "OWNER_PID=$OwnerProcessId$([Environment]::NewLine)"
                if (
                    $releaseArtifact.Text -cne $expectedRelease -and
                    $releaseArtifact.Text -cne $expectedAbort
                ) {
                    throw "DataRoot guard release artifact 内容不匹配当前安装器。"
                }
                $releaseAccepted = $true
            }
            $ownerExited = Test-TicketboxProcessIdentityHandleExited $ownerHandleLease
            if ($releaseAccepted -or $ownerExited) {
                $activityLockHeld =
                    -not [string]::IsNullOrWhiteSpace($retainWhileLockFullPath) -and
                    (Test-TicketboxExclusiveFileLockHeld -Path $retainWhileLockFullPath)
                if (-not $activityLockHeld) {
                    if ($releaseAccepted) { return "control" }
                    return "owner_exit"
                }
            }
            Start-Sleep -Milliseconds 100
        }
    }
    finally {
        try {
            if ($null -ne $guard) {
                Remove-TicketboxDirectoryGuardCoordinationArtifacts `
                    -ParentPath $readyParent `
                    -Paths @($readyFullPath, $releaseFullPath, "$releaseFullPath.tmp") `
                    -FullControlAccounts $FullControlAccounts `
                    -OwnerAccount $OwnerAccount
            }
        }
        finally {
            if ($null -ne $guard) { $guard.Dispose() }
            Close-TicketboxProcessIdentityHandle $ownerHandleLease
        }
    }
}

function Test-TicketboxExclusiveFileLockHeld {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
        $entryKind = Get-TicketboxPathEntryKindNoFollow $fullPath
    }
    catch {
        # An active FileShare.None lease, ACL denial, or malformed entry can
        # make even the no-follow classifier fail.  A holder must retain
        # authority whenever the operation state cannot be proven absent.
        return $true
    }
    if ($entryKind -ceq "Missing") { return $false }
    if ($entryKind -cne "File") {
        # A holder must never drop machine/DataRoot authority while the
        # delegated-operation state is malformed or indeterminate.
        return $true
    }
    try {
        Assert-NoTicketboxAncestorReparsePoints $fullPath
    }
    catch {
        return $true
    }
    $probe = $null
    try {
        $probe = [System.IO.File]::Open(
            $fullPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        return $false
    }
    catch {
        return $true
    }
    finally {
        if ($null -ne $probe) { $probe.Dispose() }
    }
}

function Initialize-TicketboxExactTreeDeleteNativeMethods {
    Initialize-TicketboxWin32FilePathMethods
    if ("TicketboxExactTreeDeleteNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class TicketboxExactTreeDeleteNativeMethods
{
    private const uint DeleteAccess = 0x00010000;
    private const uint FileReadData = 0x00000001;
    private const uint FileReadAttributes = 0x00000080;
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint FileShareDelete = 0x00000004;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;
    private const uint FileFlagOpenReparsePoint = 0x00200000;
    private const uint FileAttributeDirectory = 0x00000010;
    private const uint FileAttributeReparsePoint = 0x00000400;
    private const int FileDispositionInfo = 4;
    private const int FileAttributeTagInfo = 9;
    private const int FileIdInfo = 18;
    private static readonly MethodInfo PublicPathNormalizer =
        ResolvePublicPathNormalizer();

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

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_ID_128
    {
        public ulong LowPart;
        public ulong HighPart;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_ID_INFO
    {
        public ulong VolumeSerialNumber;
        public FILE_ID_128 FileId;
    }

    [DllImport(
        "kernel32.dll",
        EntryPoint = "CreateFileW",
        CharSet = CharSet.Unicode,
        ExactSpelling = true,
        SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
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

    [DllImport(
        "kernel32.dll",
        EntryPoint = "GetFileInformationByHandleEx",
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileIdInformationByHandleEx(
        SafeFileHandle file,
        int informationClass,
        out FILE_ID_INFO information,
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

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileSizeEx(
        SafeFileHandle file,
        out long fileSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ReadFile(
        SafeFileHandle file,
        byte[] buffer,
        uint bytesToRead,
        out uint bytesRead,
        IntPtr overlapped);

    public static void DeleteTree(
        string path,
        string deferredRootLeafName,
        Action rootHandleAcquired)
    {
        string fullPath = NormalizePublicPath(path);
        if (!String.IsNullOrEmpty(deferredRootLeafName) &&
            !String.Equals(
                Path.GetFileName(deferredRootLeafName),
                deferredRootLeafName,
                StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "The deferred deletion entry must be a root leaf name.",
                "deferredRootLeafName");
        }
        using (SafeFileHandle root = OpenExact(fullPath))
        {
            VerifyExactPath(root, fullPath);
            if (rootHandleAcquired != null)
            {
                rootHandleAcquired();
            }
            DeleteOpenedNode(fullPath, root, true, deferredRootLeafName);
        }
    }

    public static int InspectEntry(string path)
    {
        string fullPath = NormalizePublicPath(path);
        using (SafeFileHandle handle = CreateFileW(
            fullPath,
            FileReadAttributes,
            FileShareRead | FileShareWrite | FileShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero))
        {
            if (handle.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                if (error == 2 || error == 3)
                {
                    return 0;
                }
                throw new Win32Exception(error, "Unable to inspect exact path entry: " + fullPath);
            }
            FILE_ATTRIBUTE_TAG_INFO attributes = ReadAttributes(handle, fullPath);
            if ((attributes.FileAttributes & FileAttributeReparsePoint) != 0)
            {
                return 3;
            }
            return (attributes.FileAttributes & FileAttributeDirectory) != 0 ? 2 : 1;
        }
    }

    public static string[] GetDirectoryIdentity(string path)
    {
        string fullPath = NormalizePublicPath(path);
        using (SafeFileHandle handle = CreateFileW(
            fullPath,
            FileReadAttributes,
            FileShareRead | FileShareWrite | FileShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics | FileFlagOpenReparsePoint,
            IntPtr.Zero))
        {
            if (handle.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                throw new Win32Exception(
                    error,
                    "Unable to open the directory identity target: " + fullPath);
            }
            VerifyExactPath(handle, fullPath);
            FILE_ATTRIBUTE_TAG_INFO attributes = ReadAttributes(handle, fullPath);
            if ((attributes.FileAttributes & FileAttributeReparsePoint) != 0 ||
                (attributes.FileAttributes & FileAttributeDirectory) == 0)
            {
                throw new IOException(
                    "Directory identity target is not a plain directory: " + fullPath);
            }
            FILE_ID_INFO identity;
            if (!GetFileIdInformationByHandleEx(
                handle,
                FileIdInfo,
                out identity,
                (uint)Marshal.SizeOf(typeof(FILE_ID_INFO))))
            {
                ThrowLastWin32("Unable to read the directory identity", fullPath);
            }
            return new string[]
            {
                identity.VolumeSerialNumber.ToString("X16"),
                identity.FileId.HighPart.ToString("X16") +
                    identity.FileId.LowPart.ToString("X16")
            };
        }
    }

    public static string ReadExactUtf8File(string path, int maximumBytes)
    {
        if (maximumBytes < 1)
        {
            throw new ArgumentOutOfRangeException("maximumBytes");
        }
        string fullPath = NormalizePublicPath(path);
        using (SafeFileHandle handle = CreateFileW(
            fullPath,
            FileReadData | FileReadAttributes,
            FileShareRead,
            IntPtr.Zero,
            OpenExisting,
            FileFlagOpenReparsePoint,
            IntPtr.Zero))
        {
            if (handle.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                throw new Win32Exception(
                    error,
                    "Unable to open the exact UTF-8 file: " + fullPath);
            }
            VerifyExactPath(handle, fullPath);
            FILE_ATTRIBUTE_TAG_INFO attributes = ReadAttributes(handle, fullPath);
            if ((attributes.FileAttributes & FileAttributeReparsePoint) != 0 ||
                (attributes.FileAttributes & FileAttributeDirectory) != 0)
            {
                throw new IOException(
                    "Exact UTF-8 target is not a plain file: " + fullPath);
            }
            long fileSize;
            if (!GetFileSizeEx(handle, out fileSize))
            {
                ThrowLastWin32("Unable to read the exact UTF-8 file size", fullPath);
            }
            if (fileSize < 1 || fileSize > maximumBytes)
            {
                throw new IOException(
                    "Exact UTF-8 file size is outside the allowed range: " + fullPath);
            }
            byte[] bytes = new byte[(int)fileSize];
            int offset = 0;
            while (offset < bytes.Length)
            {
                byte[] remaining = offset == 0
                    ? bytes
                    : new byte[bytes.Length - offset];
                uint bytesRead;
                if (!ReadFile(
                    handle,
                    remaining,
                    (uint)remaining.Length,
                    out bytesRead,
                    IntPtr.Zero))
                {
                    ThrowLastWin32("Unable to read the exact UTF-8 file", fullPath);
                }
                if (bytesRead == 0)
                {
                    throw new EndOfStreamException(
                        "Exact UTF-8 file ended before its reported size: " + fullPath);
                }
                if (offset != 0)
                {
                    Buffer.BlockCopy(remaining, 0, bytes, offset, (int)bytesRead);
                }
                offset += checked((int)bytesRead);
            }
            UTF8Encoding encoding = new UTF8Encoding(false, true);
            return encoding.GetString(bytes);
        }
    }

    private static void DeleteOpenedNode(
        string path,
        SafeFileHandle handle,
        bool isRoot,
        string deferredRootLeafName)
    {
        FILE_ATTRIBUTE_TAG_INFO attributes = ReadAttributes(handle, path);
        if ((attributes.FileAttributes & FileAttributeReparsePoint) != 0)
        {
            throw new IOException("Refusing to delete a reparse point: " + path);
        }
        if ((attributes.FileAttributes & FileAttributeDirectory) != 0)
        {
            string deferredChildPath = null;
            foreach (string childPath in Directory.GetFileSystemEntries(path))
            {
                if (isRoot &&
                    !String.IsNullOrEmpty(deferredRootLeafName) &&
                    String.Equals(
                        Path.GetFileName(childPath),
                        deferredRootLeafName,
                        StringComparison.OrdinalIgnoreCase))
                {
                    if (deferredChildPath != null)
                    {
                        throw new IOException(
                            "Multiple deferred root entries resolve to the same name: " +
                            deferredRootLeafName);
                    }
                    deferredChildPath = childPath;
                    continue;
                }
                using (SafeFileHandle child = OpenExact(childPath))
                {
                    VerifyExactPath(child, childPath);
                    DeleteOpenedNode(childPath, child, false, null);
                }
            }
            if (deferredChildPath != null)
            {
                using (SafeFileHandle deferredChild = OpenExact(deferredChildPath))
                {
                    VerifyExactPath(deferredChild, deferredChildPath);
                    DeleteOpenedNode(deferredChildPath, deferredChild, false, null);
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
        string extendedPath = NormalizeLosslessExtendedPath(path);
        SafeFileHandle handle = CreateFileW(
            extendedPath,
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
            throw new Win32Exception(
                error,
                "Unable to open the exact deletion target: " + extendedPath);
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
        string actualPath = NormalizeLosslessExtendedPath(buffer.ToString());
        string normalizedExpectedPath =
            NormalizeLosslessExtendedPath(expectedPath);
        if (!String.Equals(
            actualPath,
            normalizedExpectedPath,
            StringComparison.OrdinalIgnoreCase))
        {
            throw new IOException(
                "Opened deletion target resolved outside the requested path: " +
                expectedPath + " -> " + actualPath);
        }
    }

    private static string NormalizePublicPath(string path)
    {
        try
        {
            return (string)PublicPathNormalizer.Invoke(
                null,
                new object[] { path });
        }
        catch (TargetInvocationException error)
        {
            if (error.InnerException != null)
            {
                throw error.InnerException;
            }
            throw;
        }
    }

    private static MethodInfo ResolvePublicPathNormalizer()
    {
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type pathType = assembly.GetType(
                "TicketboxWin32FilePath",
                false,
                false);
            if (pathType == null)
            {
                continue;
            }
            MethodInfo method = pathType.GetMethod(
                "NormalizeExtended",
                BindingFlags.Public | BindingFlags.Static,
                null,
                new Type[] { typeof(string) },
                null);
            if (method != null && method.ReturnType == typeof(string))
            {
                return method;
            }
        }
        throw new TypeLoadException(
            "The shared Ticketbox Win32 path normalizer is not loaded.");
    }

    private static string NormalizeLosslessExtendedPath(string path)
    {
        if (path == null)
        {
            throw new ArgumentNullException("path");
        }
        if (path.Length == 0 || path.IndexOf('\0') >= 0)
        {
            throw new ArgumentException(
                "An exact-tree extended path is required.",
                "path");
        }
        if (path.IndexOf('/') >= 0)
        {
            throw new ArgumentException(
                "An exact-tree extended path must use backslash separators.",
                "path");
        }
        if (path.Length >= 32767)
        {
            throw new PathTooLongException(
                "The exact-tree extended path exceeds the Unicode API limit.");
        }

        if (path.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            const int serverStart = 8;
            int serverEnd = path.IndexOf('\\', serverStart);
            int shareEnd = serverEnd < 0
                ? -1
                : path.IndexOf('\\', serverEnd + 1);
            int shareLength = shareEnd < 0
                ? path.Length - serverEnd - 1
                : shareEnd - serverEnd - 1;
            if (serverEnd <= serverStart || shareLength <= 0)
            {
                throw new ArgumentException(
                    "An exact-tree UNC path requires a server and share.",
                    "path");
            }
            return @"\\?\UNC\" + path.Substring(serverStart);
        }
        if (path.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
        {
            const int driveStart = 4;
            if (path.Length < driveStart + 3 ||
                !((path[driveStart] >= 'A' && path[driveStart] <= 'Z') ||
                  (path[driveStart] >= 'a' && path[driveStart] <= 'z')) ||
                path[driveStart + 1] != ':' ||
                path[driveStart + 2] != '\\')
            {
                throw new ArgumentException(
                    "Only drive and UNC extended file paths are exact-tree paths.",
                    "path");
            }
            return @"\\?\" + path.Substring(driveStart);
        }
        throw new ArgumentException(
            "An exact-tree path must already use the extended drive or UNC namespace.",
            "path");
    }

    private static void ThrowLastWin32(string operation, string path)
    {
        int error = Marshal.GetLastWin32Error();
        throw new Win32Exception(error, operation + ": " + path);
    }
}
'@
}

function Remove-TicketboxTreeExact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowEmptyString()][string]$DeferredRootLeafName = "",
        [scriptblock]$OnRootHandleAcquired
    )

    $canonicalPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $canonicalPath
    if (-not (Test-Path -LiteralPath $extendedPath)) {
        return
    }
    if (-not (Test-Path -LiteralPath $extendedPath -PathType Container)) {
        throw "精确删除目标不是目录：$canonicalPath"
    }
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $callback = $null
    if ($null -ne $OnRootHandleAcquired) {
        $callbackScript = { & $OnRootHandleAcquired $canonicalPath }.GetNewClosure()
        $callback = [System.Action]$callbackScript
    }
    [TicketboxExactTreeDeleteNativeMethods]::DeleteTree(
        $canonicalPath,
        $DeferredRootLeafName,
        $callback
    )
    if (Test-Path -LiteralPath $extendedPath) {
        throw "精确删除完成后目标目录仍存在：$canonicalPath"
    }
}

function Remove-TicketboxDataRootExact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowEmptyString()][string]$DeferredRootLeafName = "",
        [scriptblock]$OnRootHandleAcquired
    )

    Remove-TicketboxTreeExact `
        -Path $Path `
        -DeferredRootLeafName $DeferredRootLeafName `
        -OnRootHandleAcquired $OnRootHandleAcquired
}

function ConvertTo-TicketboxCanonicalPath([string]$Path) {
    $full = ConvertTo-TicketboxWin32CanonicalPath $Path
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

function Get-TicketboxPathEntryKindNoFollow([string]$Path) {
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $fullPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    $kind = [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($fullPath)
    if ($kind -eq 0) {
        # CreateFile(FILE_FLAG_OPEN_REPARSE_POINT) can still report PATH_NOT_FOUND
        # for a dangling directory junction. Enumerating its parent observes the
        # directory entry itself without traversing the target.
        $parentPath = [System.IO.Path]::GetDirectoryName($fullPath)
        $leafName = [System.IO.Path]::GetFileName($fullPath)
        $extendedParentPath = if ([string]::IsNullOrWhiteSpace($parentPath)) {
            ""
        }
        else {
            ConvertTo-TicketboxWin32ExtendedPath $parentPath
        }
        if (
            -not [string]::IsNullOrWhiteSpace($extendedParentPath) -and
            (Test-Path -LiteralPath $extendedParentPath -PathType Container)
        ) {
            $matchingEntries = @(
                Get-ChildItem -LiteralPath $extendedParentPath -Force -ErrorAction Stop |
                    Where-Object {
                        [string]::Equals(
                            $_.Name,
                            $leafName,
                            [System.StringComparison]::OrdinalIgnoreCase
                        )
                    }
            )
            if ($matchingEntries.Count -gt 1) {
                throw "no-follow 路径分类发现多个同名目录项：$fullPath"
            }
            if ($matchingEntries.Count -eq 1) {
                $attributes = $matchingEntries[0].Attributes
                if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    $kind = 3
                }
                elseif (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                    $kind = 2
                }
                else {
                    $kind = 1
                }
            }
        }
    }
    switch ($kind) {
        0 { return "Missing" }
        1 { return "File" }
        2 { return "Directory" }
        3 { return "Reparse" }
        default { throw "no-follow 路径分类返回未知结果：$kind" }
    }
}

function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {
    $cursor = ConvertTo-TicketboxCanonicalPath $Path
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if ((Get-TicketboxPathEntryKindNoFollow $cursor) -ceq "Reparse") {
            throw "数据目录或祖先目录是重解析点，拒绝安装：$cursor"
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
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $Path
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $effectiveArguments = @($Arguments + "/L")
        $output = & $icacls $extendedPath @effectiveArguments 2>&1
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
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $Path
    $item = Get-Item -LiteralPath $extendedPath -Force -ErrorAction Stop
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

function Remove-TicketboxExplicitDirectoryAccessRulesBySidExact(
    [string]$Path,
    [string]$Sid
) {
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "Directory") {
        throw "ACL SID 清理目标不是普通目录：$Path"
    }
    try {
        $sidObject = New-Object System.Security.Principal.SecurityIdentifier($Sid)
    }
    catch {
        throw "ACL SID 清理收到无效 SID，拒绝修改目录：$Path ($Sid)"
    }
    if ($sidObject.Value -cne $Sid) {
        throw "ACL SID 清理只接受规范数值 SID：$Path ($Sid)"
    }

    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $Path
    $item = Get-Item -LiteralPath $extendedPath -Force -ErrorAction Stop
    if (
        $item -isnot [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "ACL SID 清理目标不是普通目录：$Path"
    }
    if ($PSVersionTable.PSEdition -eq "Core") {
        $descriptor = [System.IO.FileSystemAclExtensions]::GetAccessControl($item)
    }
    else {
        $descriptor = $item.GetAccessControl()
    }
    if (-not $descriptor.AreAccessRulesProtected) {
        throw "ACL SID 清理只允许在已断开继承的目录上执行：$Path"
    }
    $matchingRules = @($descriptor.GetAccessRules(
        $true,
        $false,
        [System.Security.Principal.SecurityIdentifier]
    ) | Where-Object { $_.IdentityReference.Value -ceq $sidObject.Value })
    if ($matchingRules.Count -eq 0) {
        throw "ACL SID 清理前目标规则已漂移：$Path ($Sid)"
    }

    try {
        $descriptor.PurgeAccessRules($sidObject)
    }
    catch {
        throw "无法按数值 SID 从目录 DACL 清理显式规则：$Path ($Sid)"
    }
    $inMemoryRemaining = @($descriptor.GetAccessRules(
        $true,
        $false,
        [System.Security.Principal.SecurityIdentifier]
    ) | Where-Object { $_.IdentityReference.Value -ceq $sidObject.Value })
    if ($inMemoryRemaining.Count -ne 0) {
        throw "目录 DACL 的 SID 规则未在内存中完全清理：$Path ($Sid)"
    }

    try {
        if ($PSVersionTable.PSEdition -eq "Core") {
            [System.IO.FileSystemAclExtensions]::SetAccessControl($item, $descriptor)
        }
        else {
            $item.SetAccessControl($descriptor)
        }
    }
    catch {
        throw "无法持久化目录 DACL 的 SID 清理：$Path ($Sid)"
    }

    $persistedAcl = Get-TicketboxPathAcl $Path
    if (-not $persistedAcl.AreAccessRulesProtected) {
        throw "目录 DACL 的 SID 清理后继承状态漂移：$Path"
    }
    $persistedRules = @($persistedAcl.Access | Where-Object {
        $_.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value -ceq $sidObject.Value
    })
    if ($persistedRules.Count -ne 0) {
        throw "目录 DACL 的 SID 规则未从磁盘完全清理：$Path ($Sid)"
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
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $currentUserSid = $identity.User.Value
    $administratorsSid = ConvertTo-TicketboxAccountSid "BUILTIN\Administrators"
    $acl = Get-TicketboxPathAcl $Path
    $ownerSid = ConvertTo-TicketboxAccountSid $acl.Owner
    if ($ownerSid -eq $currentUserSid) {
        return
    }

    # Never take ownership merely to edit a DACL.  A crash between temporary
    # Administrators ownership and owner restoration would leave a trusted
    # installer artifact in a state that later retries cannot distinguish from
    # external takeover.  Instead, prove that the current token already has
    # WRITE_DAC through the existing exact ACL and fail closed otherwise.
    $authorizedSids = @($currentUserSid)
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $authorizedSids += $administratorsSid
    }
    $changePermissions = [Security.AccessControl.FileSystemRights]::ChangePermissions
    $authorized = $false
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny) {
            throw "ACL 含 Deny 规则，拒绝通过 owner 过渡强制改写：$Path ($ruleSid)"
        }
        if (
            $ruleSid -in $authorizedSids -and
            $rule.AccessControlType -eq
                [Security.AccessControl.AccessControlType]::Allow -and
            ($rule.FileSystemRights -band $changePermissions) -eq $changePermissions
        ) {
            $authorized = $true
        }
    }
    if (-not $authorized) {
        throw "当前安装 token 未经既有 ACL 授予 WRITE_DAC，拒绝临时接管 owner：$Path"
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
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
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
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
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
            Remove-TicketboxExplicitDirectoryAccessRulesBySidExact `
                -Path $Path `
                -Sid $sid
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
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $Path
    if (-not (Test-Path -LiteralPath $extendedPath -PathType Leaf)) {
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
    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $Path
    if (-not (Test-Path -LiteralPath $extendedPath -PathType Leaf)) {
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

function Test-TicketboxExactAllowFileSystemRights {
    param(
        [Parameter(Mandatory = $true)]
        [Security.AccessControl.FileSystemRights]$ActualRights,
        [Parameter(Mandatory = $true)]
        [Security.AccessControl.FileSystemRights]$RequestedRights
    )

    # .NET/Windows automatically adds SYNCHRONIZE to an allow ACE.  Preserve
    # exact-rights enforcement by accepting that documented normalization and
    # no other bit.
    $normalizedRights =
        $RequestedRights -bor
        [Security.AccessControl.FileSystemRights]::Synchronize
    return [int64]$ActualRights -eq [int64]$normalizedRights
}

function New-TicketboxInitdbPasswordFileSecurity([string]$ServiceName) {
    $security = New-Object System.Security.AccessControl.FileSecurity
    $security.SetAccessRuleProtection($true, $false)
    $ownerSid = New-Object System.Security.Principal.SecurityIdentifier(
        (ConvertTo-TicketboxAccountSid "SYSTEM")
    )
    $security.SetOwner($ownerSid)
    foreach ($account in @("SYSTEM", "BUILTIN\Administrators")) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier(
            (ConvertTo-TicketboxAccountSid $account)
        )
        $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.AccessControlType]::Allow
        )))
    }
    $serviceSid = New-Object System.Security.Principal.SecurityIdentifier(
        (ConvertTo-TicketboxAccountSid "NT SERVICE\$ServiceName")
    )
    $security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $serviceSid,
        [Security.AccessControl.FileSystemRights]::Read,
        [Security.AccessControl.AccessControlType]::Allow
    )))
    return $security
}

function Write-TicketboxInitdbPasswordFileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    $canonicalPath = ConvertTo-TicketboxCanonicalPath $Path
    if (
        [string]::IsNullOrEmpty($Text) -or
        $Text.IndexOf([char]0) -ge 0 -or
        $Text.Contains("`r") -or
        $Text.Contains("`n")
    ) {
        throw "initdb 临时密码必须是非空单行文本。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $canonicalPath) -cne "Missing") {
        throw "initdb 临时密码路径已存在；必须先完成中断恢复。"
    }
    $parent = Split-Path -Parent $canonicalPath
    if ((Get-TicketboxPathEntryKindNoFollow $parent) -cne "Directory") {
        throw "initdb 临时密码父目录不存在或不可信。"
    }
    Assert-NoTicketboxAncestorReparsePoints $parent
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
    if ($bytes.Length -le 0 -or $bytes.Length -gt 1024) {
        throw "initdb 临时密码 UTF-8 字节长度无效。"
    }
    $security = New-TicketboxInitdbPasswordFileSecurity $ServiceName
    $stream = New-TicketboxProtectedFileStream `
        -Path $canonicalPath `
        -Security $security
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
    Set-TicketboxOwnerIfNeeded `
        -Path $canonicalPath `
        -ExpectedOwnerSid (ConvertTo-TicketboxAccountSid "SYSTEM")
    Assert-TicketboxInitdbPasswordFileAcl `
        -Path $canonicalPath `
        -ServiceName $ServiceName
}

function Assert-TicketboxInitdbPasswordFileAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [switch]$AllowEmpty,
        [switch]$AllowServiceReadMissing
    )

    $canonicalPath = ConvertTo-TicketboxCanonicalPath $Path
    if ((Get-TicketboxPathEntryKindNoFollow $canonicalPath) -cne "File") {
        throw "initdb 临时密码文件不存在或不是普通文件。"
    }
    Assert-NoTicketboxAncestorReparsePoints $canonicalPath
    $item = Get-Item -LiteralPath $canonicalPath -Force -ErrorAction Stop
    if (
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        ((-not $AllowEmpty) -and $item.Length -le 0) -or
        $item.Length -gt 1024
    ) {
        throw "initdb 临时密码文件类型或大小无效。"
    }

    $fullControlSids = @(
        @("SYSTEM", "BUILTIN\Administrators") |
            ForEach-Object { ConvertTo-TicketboxAccountSid $_ } |
            Sort-Object -Unique
    )
    $serviceSid = ConvertTo-TicketboxAccountSid "NT SERVICE\$ServiceName"
    $ownerSid = ConvertTo-TicketboxAccountSid "SYSTEM"
    $acl = Get-TicketboxPathAcl $canonicalPath
    if (
        -not $acl.AreAccessRulesProtected -or
        (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $ownerSid
    ) {
        throw "initdb 临时密码文件 owner 或继承状态不可信。"
    }

    $ruleCounts = @{}
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
        if (
            $rule.IsInherited -or
            $rule.AccessControlType -ne
                [Security.AccessControl.AccessControlType]::Allow -or
            $rule.InheritanceFlags -ne
                [Security.AccessControl.InheritanceFlags]::None -or
            $rule.PropagationFlags -ne
                [Security.AccessControl.PropagationFlags]::None
        ) {
            throw "initdb 临时密码文件含有继承或非 Allow 规则。"
        }
        if (-not $ruleCounts.ContainsKey($ruleSid)) {
            $ruleCounts[$ruleSid] = 0
        }
        $ruleCounts[$ruleSid] = [int]$ruleCounts[$ruleSid] + 1
        if ($ruleCounts[$ruleSid] -ne 1) {
            throw "initdb 临时密码文件含有重复授权规则。"
        }

        if ($ruleSid -in $fullControlSids) {
            if (
                [int64]$rule.FileSystemRights -ne
                    [int64][Security.AccessControl.FileSystemRights]::FullControl
            ) {
                throw "initdb 临时密码文件的管理员权限不是精确 FullControl。"
            }
            continue
        }
        if ($ruleSid -eq $serviceSid) {
            if (
                -not (Test-TicketboxExactAllowFileSystemRights `
                    -ActualRights $rule.FileSystemRights `
                    -RequestedRights ([Security.AccessControl.FileSystemRights]::Read))
            ) {
                throw (
                    "initdb 临时密码文件给 PostgreSQL 服务的权限不是精确 Read " +
                    "及 Windows 自动附加的 Synchronize。"
                )
            }
            continue
        }
        throw "initdb 临时密码文件含有未授权账户。"
    }
    foreach ($sid in $fullControlSids) {
        if (-not $ruleCounts.ContainsKey($sid)) {
            throw "initdb 临时密码文件缺少必要账户权限。"
        }
    }
    if (
        -not $AllowServiceReadMissing -and
        -not $ruleCounts.ContainsKey($serviceSid)
    ) {
        throw "initdb 临时密码文件缺少 PostgreSQL 服务 Read 权限。"
    }
}

function Remove-TicketboxInitdbPasswordFileExact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [switch]$AllowServiceReadMissing
    )

    $kind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($kind -ceq "Missing") { return }
    if ($kind -cne "File") {
        throw "initdb 临时密码路径不是普通文件，拒绝清理。"
    }
    Assert-TicketboxInitdbPasswordFileAcl `
        -Path $Path `
        -ServiceName $ServiceName `
        -AllowEmpty `
        -AllowServiceReadMissing:$AllowServiceReadMissing
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "Missing") {
        throw "initdb 临时密码文件未能退役。"
    }
}

function Remove-TicketboxInterruptedInitdbPgDataExact {
    param(
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][string]$PgData,
        [Parameter(Mandatory = $true)][string]$EnvPath,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$RuntimePort,
        [Parameter(Mandatory = $true)][string[]]$ExpectedRuntimeExecutables
    )

    $expectedPgData = ConvertTo-TicketboxCanonicalPath (Join-Path $DataRoot "pgdata")
    if (
        -not (Test-TicketboxPathEquals ([string]$Receipt.pg_data) $expectedPgData) -or
        -not (Test-TicketboxPathEquals $PgData $expectedPgData)
    ) {
        throw "中断 initdb 回执未绑定当前 PgData。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $EnvPath) -cne "Missing") {
        throw "中断 initdb 回执与应用 .env 同时存在，拒绝删除可能已提交的数据。"
    }
    $postmasterPidPath = Join-Path $expectedPgData "postmaster.pid"
    if ((Get-TicketboxPathEntryKindNoFollow $postmasterPidPath) -cne "Missing") {
        throw "中断 initdb PgData 含有 postmaster.pid，拒绝删除可能运行的数据簇。"
    }
    $runtimeAbsentGuard = New-TicketboxRuntimeAbsentAssertion `
        -Name $ServiceName `
        -RuntimePort $RuntimePort `
        -ExpectedRuntimeExecutables $ExpectedRuntimeExecutables
    & $runtimeAbsentGuard
    $kind = Get-TicketboxPathEntryKindNoFollow $expectedPgData
    if ($kind -ceq "Missing") { return }
    if ($kind -cne "Directory") {
        throw "中断 initdb PgData 不是普通目录，拒绝清理。"
    }
    Assert-TicketboxDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir
    Assert-NoTicketboxReparsePoints $expectedPgData
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $expectedIdentity = @(
        [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($expectedPgData)
    )
    if ($expectedIdentity.Count -ne 2) {
        throw "中断 initdb PgData 目录身份无法固定。"
    }
    $deleteGuard = {
        param($GuardedPath)
        $openedPath = [IO.Path]::GetFullPath($GuardedPath).TrimEnd('\', '/')
        if (-not [string]::Equals(
            $openedPath,
            $expectedPgData,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "中断 initdb PgData 句柄与已验证目标不一致。"
        }
        $openedIdentity = @(
            [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($openedPath)
        )
        if (
            $openedIdentity.Count -ne 2 -or
            [string]$openedIdentity[0] -cne [string]$expectedIdentity[0] -or
            [string]$openedIdentity[1] -cne [string]$expectedIdentity[1]
        ) {
            throw "中断 initdb PgData 身份在删除前发生变化。"
        }
        if (
            [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($EnvPath) -ne 0 -or
            [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($postmasterPidPath) -ne 0
        ) {
            throw "中断 initdb 删除边界出现 .env 或 postmaster.pid。"
        }
        & $runtimeAbsentGuard
    }.GetNewClosure()
    Remove-TicketboxDataRootExact `
        -Path $expectedPgData `
        -OnRootHandleAcquired $deleteGuard
}

function Assert-TicketboxRecoverableInheritedFileAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM"
    )

    $extendedPath = ConvertTo-TicketboxWin32ExtendedPath $Path
    if (-not (Test-Path -LiteralPath $extendedPath -PathType Leaf)) {
        throw "可恢复 ACL 目标文件不存在：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    $item = Get-Item -LiteralPath $extendedPath -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "可恢复 ACL 目标不能是重解析点：$Path"
    }

    $fullControlSids = @($FullControlAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    $readExecuteSids = @($ReadExecuteAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if (
        $fullControlSids.Count -eq 0 -or
        @($fullControlSids | Where-Object { $_ -in $readExecuteSids }).Count -gt 0
    ) {
        throw "可恢复文件 ACL 的账户配置无效：$Path"
    }

    # Windows assigns a new object's owner from the creator token's default
    # owner.  That owner is independent of the DACL entries inherited from the
    # parent, so it is not evidence for (or against) this inherited-only retry
    # shape.  Resolve the intended final owner now, then let the exact ACL
    # publisher below normalize and assert it after all pre-write proofs pass.
    [void](ConvertTo-TicketboxAccountSid $OwnerAccount)
    $acl = Get-TicketboxPathAcl $Path
    if ($acl.AreAccessRulesProtected) {
        throw "文件不属于严格的继承 ACL 恢复形态：$Path"
    }
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
        if (
            -not $rule.IsInherited -or
            $rule.AccessControlType -ne
                [Security.AccessControl.AccessControlType]::Allow -or
            $rule.InheritanceFlags -ne
                [Security.AccessControl.InheritanceFlags]::None -or
            $rule.PropagationFlags -ne
                [Security.AccessControl.PropagationFlags]::None
        ) {
            throw "可恢复文件 ACL 含有非继承或非 Allow 规则：$Path ($ruleSid)"
        }
        if ($ruleSid -in $fullControlSids) {
            if (
                [int64]$rule.FileSystemRights -ne
                [int64][Security.AccessControl.FileSystemRights]::FullControl
            ) {
                throw "可恢复文件 ACL 的 FullControl 权限不精确：$Path ($ruleSid)"
            }
            continue
        }
        if ($ruleSid -in $readExecuteSids) {
            if (
                [int64]$rule.FileSystemRights -ne
                [int64][Security.AccessControl.FileSystemRights]::ReadAndExecute
            ) {
                throw "可恢复文件 ACL 的 ReadExecute 权限不精确：$Path ($ruleSid)"
            }
            continue
        }
        throw "可恢复文件 ACL 含有未授权账户：$Path ($ruleSid)"
    }
    foreach ($sid in @($fullControlSids + $readExecuteSids)) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [Security.Principal.SecurityIdentifier]
            ).Value -eq $sid
        })
        if ($matchingRules.Count -ne 1) {
            throw "可恢复文件 ACL 的目标账户规则数不唯一：$Path ($sid)"
        }
    }
}

function Assert-TicketboxRecoverableInheritedDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string]$OwnerAccount = "SYSTEM"
    )

    $canonicalPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    if ((Get-TicketboxPathEntryKindNoFollow $canonicalPath) -cne "Directory") {
        throw "可恢复 ACL 目标目录不存在或不是普通目录：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $canonicalPath

    $fullControlSids = @($FullControlAccounts | ForEach-Object {
        ConvertTo-TicketboxAccountSid $_
    } | Sort-Object -Unique)
    if ($fullControlSids.Count -eq 0) {
        throw "可恢复目录 ACL 的账户配置无效：$Path"
    }

    # Object ownership comes from the creator token; it is not inherited with
    # the directory DACL.  The target owner still has to resolve before any
    # write, and the exact ACL publisher establishes it after this assertion.
    [void](ConvertTo-TicketboxAccountSid $OwnerAccount)
    $acl = Get-TicketboxPathAcl $canonicalPath
    if ($acl.AreAccessRulesProtected) {
        throw "目录不属于严格的继承 ACL 恢复形态：$Path"
    }
    $requiredInheritance =
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [Security.Principal.SecurityIdentifier]
        ).Value
        if (
            -not $rule.IsInherited -or
            $rule.AccessControlType -ne
                [Security.AccessControl.AccessControlType]::Allow -or
            $rule.InheritanceFlags -ne $requiredInheritance -or
            $rule.PropagationFlags -ne
                [Security.AccessControl.PropagationFlags]::None -or
            $ruleSid -notin $fullControlSids -or
            [int64]$rule.FileSystemRights -ne
                [int64][Security.AccessControl.FileSystemRights]::FullControl
        ) {
            throw "可恢复目录 ACL 含有非继承或非精确规则：$Path ($ruleSid)"
        }
    }
    foreach ($sid in $fullControlSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [Security.Principal.SecurityIdentifier]
            ).Value -eq $sid
        })
        if ($matchingRules.Count -ne 1) {
            throw "可恢复目录 ACL 的目标账户规则数不唯一：$Path ($sid)"
        }
    }
}

function Repair-TicketboxRecoverableDataRootMarkerAcl {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string]$OwnerAccount = "SYSTEM"
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    if ((Get-TicketboxPathEntryKindNoFollow $markerPath) -cne "File") {
        throw "DataRoot marker 不是普通文件，拒绝 ACL 恢复。"
    }

    Assert-TicketboxProtectedDirectoryAcl `
        -Path $canonicalDataRoot `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    $markerAcl = Get-TicketboxPathAcl $markerPath
    if ($markerAcl.AreAccessRulesProtected) {
        Assert-TicketboxExactFileAcl `
            -Path $markerPath `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        Assert-TicketboxDataRootMarker `
            -DataRoot $canonicalDataRoot `
            -InstallDir $InstallDir
        return $false
    }

    # This is a deliberately narrow retry repair for the exact residual left
    # by an earlier trusted installer after recursive ACL normalization.  The
    # authority content and every ACL fact are proven before the first write.
    Assert-TicketboxRecoverableInheritedFileAcl `
        -Path $markerPath `
        -FullControlAccounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    Assert-TicketboxDataRootMarker `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir
    Set-TicketboxExactFileAcl `
        -Path $markerPath `
        -Accounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    Assert-TicketboxExactFileAcl `
        -Path $markerPath `
        -Accounts $FullControlAccounts `
        -OwnerAccount $OwnerAccount
    Assert-TicketboxDataRootMarker `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir
    return $true
}

function Get-TicketboxDataRootMarkerPath([string]$DataRoot) {
    return Join-Path (ConvertTo-TicketboxCanonicalPath $DataRoot) $script:TicketboxDataRootMarkerName
}

function Get-TicketboxPersistentInstallationIdentityPath([string]$DataRoot) {
    return Join-Path `
        (ConvertTo-TicketboxCanonicalPath $DataRoot) `
        $script:TicketboxPersistentInstallationIdentityName
}

function Get-TicketboxPendingInstallationIdentityPath([string]$DataRoot) {
    return Join-Path `
        (ConvertTo-TicketboxCanonicalPath $DataRoot) `
        $script:TicketboxPendingInstallationIdentityName
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
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
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

function ConvertTo-TicketboxInstalledC07MigrationHelperEvidence(
    [object]$Evidence
) {
    if ($null -eq $Evidence) {
        throw "已安装 BUILD_PROVENANCE.json 缺少 C07 migration helper 证据。"
    }
    $propertyNames = @($Evidence.PSObject.Properties.Name)
    if (
        $propertyNames.Count -ne 3 -or
        "path" -notin $propertyNames -or
        "size" -notin $propertyNames -or
        "sha256" -notin $propertyNames
    ) {
        throw "已安装 C07 migration helper 证据 shape 无效。"
    }
    $relativePath = [string]$Evidence.path
    if (
        $relativePath -cne $script:TicketboxC07MigrationHelperRelativePath -or
        [System.IO.Path]::IsPathRooted($relativePath) -or
        $relativePath.Contains("\") -or
        $relativePath.Contains("/") -or
        $relativePath.Contains(":")
    ) {
        throw "已安装 C07 migration helper 证据路径不是 canonical payload-relative path。"
    }
    $size = [int64]0
    if (
        -not [int64]::TryParse([string]$Evidence.size, [ref]$size) -or
        $size -lt 1 -or
        [string]$Evidence.sha256 -cnotmatch "^[0-9a-f]{64}$"
    ) {
        throw "已安装 C07 migration helper 证据 size/SHA-256 无效。"
    }
    return [pscustomobject][ordered]@{
        RelativePath = $relativePath
        Size = $size
        Sha256 = ([string]$Evidence.sha256).ToUpperInvariant()
    }
}

function Resolve-TicketboxInstalledC07MigrationHelperPath {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][object]$Evidence
    )
    $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath $InstallDir
    $payloadRoot = ConvertTo-TicketboxCanonicalPath (
        Join-Path $canonicalInstallDir "program\ticketbox-backend"
    )
    if (
        -not (Test-TicketboxPathWithin $payloadRoot $canonicalInstallDir) -or
        (Test-TicketboxPathEquals $payloadRoot $canonicalInstallDir)
    ) {
        throw "C07 frozen backend payload root 越出安装目录。"
    }
    $evidenceProperties = @($Evidence.PSObject.Properties.Name)
    if (
        $evidenceProperties.Count -ne 3 -or
        "RelativePath" -notin $evidenceProperties -or
        "Size" -notin $evidenceProperties -or
        "Sha256" -notin $evidenceProperties -or
        [string]$Evidence.RelativePath -cne
            $script:TicketboxC07MigrationHelperRelativePath -or
        [System.IO.Path]::IsPathRooted([string]$Evidence.RelativePath) -or
        ([string]$Evidence.RelativePath).Contains("\") -or
        ([string]$Evidence.RelativePath).Contains("/") -or
        ([string]$Evidence.RelativePath).Contains(":") -or
        [int64]$Evidence.Size -lt 1 -or
        [string]$Evidence.Sha256 -cnotmatch "^[0-9A-F]{64}$"
    ) {
        throw "C07 migration helper canonical release evidence 无效。"
    }
    $helperPath = ConvertTo-TicketboxCanonicalPath (
        Join-Path $payloadRoot ([string]$Evidence.RelativePath)
    )
    if (
        -not (Test-TicketboxPathWithin $helperPath $payloadRoot) -or
        (Test-TicketboxPathEquals $helperPath $payloadRoot)
    ) {
        throw "C07 migration helper 证据路径逃逸 frozen backend payload root。"
    }
    return $helperPath
}

function Get-TicketboxC07OpenStreamSha256(
    [Parameter(Mandatory = $true)][System.IO.FileStream]$Stream
) {
    $Stream.Position = 0
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (
            [BitConverter]::ToString($sha256.ComputeHash($Stream))
        ).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
        $Stream.Position = 0
    }
}

function Open-TicketboxC07VerifiedMigrationHelperLease {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedRelativePath,
        [Parameter(Mandatory = $true)][int64]$ExpectedSize,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    if (
        $ExpectedRelativePath -cne
            $script:TicketboxC07MigrationHelperRelativePath -or
        $ExpectedSize -lt 1 -or
        $ExpectedSha256 -cnotmatch "^[0-9A-F]{64}$"
    ) {
        throw "C07 migration helper lease 的 release evidence 无效。"
    }
    $helperPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    if ((Get-TicketboxPathEntryKindNoFollow $helperPath) -cne "File") {
        throw "C07 migration helper 不是 regular file。"
    }
    Assert-NoTicketboxAncestorReparsePoints $helperPath
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $helperPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        if (
            (Get-TicketboxPathEntryKindNoFollow $helperPath) -cne "File"
        ) {
            throw "C07 migration helper 在 lease 获取时发生身份变化。"
        }
        Assert-NoTicketboxAncestorReparsePoints $helperPath
        $sha256 = Get-TicketboxC07OpenStreamSha256 $stream
        if (
            [int64]$stream.Length -ne $ExpectedSize -or
            $sha256 -cne $ExpectedSha256
        ) {
            throw "C07 migration helper 与 release size/SHA-256 不一致。"
        }
        return [pscustomobject][ordered]@{
            Path = $helperPath
            RelativePath = $ExpectedRelativePath
            Size = [int64]$stream.Length
            Sha256 = $sha256
            Stream = $stream
        }
    }
    catch {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        throw
    }
}

function Assert-TicketboxC07MigrationHelperLeaseUnchanged(
    [Parameter(Mandatory = $true)][object]$Lease
) {
    if (
        $null -eq $Lease.Stream -or
        $Lease.Stream.SafeFileHandle.IsClosed -or
        (Get-TicketboxPathEntryKindNoFollow ([string]$Lease.Path)) -cne "File"
    ) {
        throw "C07 migration helper lease 已关闭或路径身份已变化。"
    }
    Assert-NoTicketboxAncestorReparsePoints ([string]$Lease.Path)
    $sha256 = Get-TicketboxC07OpenStreamSha256 $Lease.Stream
    if (
        [int64]$Lease.Stream.Length -ne [int64]$Lease.Size -or
        $sha256 -cne [string]$Lease.Sha256
    ) {
        throw "C07 migration helper 在执行窗口内发生字节身份变化。"
    }
}

function Close-TicketboxC07MigrationHelperLease(
    [AllowNull()][object]$Lease
) {
    if (
        $null -ne $Lease -and
        $null -ne $Lease.Stream -and
        -not $Lease.Stream.SafeFileHandle.IsClosed
    ) {
        $Lease.Stream.Dispose()
    }
}

function Read-TicketboxPersistentInstallationIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [switch]$Pending,
        [switch]$AllowRecoverableInheritedAcl
    )
    $path = if ($Pending) {
        Get-TicketboxPendingInstallationIdentityPath $DataRoot
    }
    else {
        Get-TicketboxPersistentInstallationIdentityPath $DataRoot
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    if ($AllowRecoverableInheritedAcl) {
        Assert-TicketboxRecoverableInheritedFileAcl `
            -Path $path `
            -FullControlAccounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
            -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    }
    else {
        Assert-TicketboxExactFileAcl `
            -Path $path `
            -Accounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
            -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    }
    $identityItem = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (
        ($identityItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        [int64]$identityItem.Length -le 0 -or
        [int64]$identityItem.Length -gt 4096
    ) {
        throw "持久安装身份不是有界的普通文件。"
    }
    $legacyNames = @(
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
    $currentNames = @(
        "SCHEMA",
        "STATE",
        "OPERATION_ID",
        "BACKEND_VERSION_FLOOR",
        "INSTALLATION_ID",
        "BUILD_MANIFEST_SHA256",
        "MIGRATION_HELPER_RELATIVE_PATH",
        "MIGRATION_HELPER_SIZE",
        "MIGRATION_HELPER_SHA256",
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
        if ($values.ContainsKey($name)) {
            throw "持久安装身份含有未知或重复字段：$name"
        }
        $values[$name] = $parts[1]
    }
    if (-not $values.ContainsKey("SCHEMA")) {
        throw "持久安装身份缺少 SCHEMA。"
    }
    $legacyCompleted = (
        [string]$values.SCHEMA -ceq
            $script:TicketboxLegacyPersistentInstallationIdentitySchema
    )
    $expectedNames = if ($legacyCompleted) { $legacyNames } else { $currentNames }
    if (
        -not $legacyCompleted -and
        [string]$values.SCHEMA -cne
            $script:TicketboxPersistentInstallationIdentitySchema
    ) {
        throw "持久安装身份 schema 不受支持。"
    }
    if (
        $values.Count -ne $expectedNames.Count -or
        @($values.Keys | Where-Object { $_ -notin $expectedNames }).Count -gt 0
    ) {
        throw "持久安装身份字段不完整或含有未知字段。"
    }
    foreach ($name in $expectedNames) {
        if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($values[$name])) {
            throw "持久安装身份缺少字段：$name"
        }
    }
    ConvertTo-TicketboxNumericVersion $values.BACKEND_VERSION_FLOOR | Out-Null
    $installationId = [guid]::Empty
    if (-not [guid]::TryParseExact($values.INSTALLATION_ID, "D", [ref]$installationId)) {
        throw "持久安装身份 installation id 无效。"
    }
    if ($values.BUILD_MANIFEST_SHA256 -cnotmatch '^[0-9A-F]{64}$') {
        throw "持久安装身份 build manifest SHA-256 无效。"
    }
    $state = "READY"
    $operationId = ""
    $helperRelativePath = ""
    $helperSize = [int64]0
    $helperSha256 = ""
    if (-not $legacyCompleted) {
        $state = [string]$values.STATE
        if ($state -cnotin @("PENDING", "READY")) {
            throw "持久安装身份 state 无效。"
        }
        $parsedOperationId = [guid]::Empty
        if (
            -not [guid]::TryParseExact(
                [string]$values.OPERATION_ID,
                "D",
                [ref]$parsedOperationId
            )
        ) {
            throw "持久安装身份 operation id 无效。"
        }
        $operationId = $parsedOperationId.ToString("D")
        $helperEvidence =
            ConvertTo-TicketboxInstalledC07MigrationHelperEvidence (
                [pscustomobject][ordered]@{
                    path = [string]$values.MIGRATION_HELPER_RELATIVE_PATH
                    size = [string]$values.MIGRATION_HELPER_SIZE
                    sha256 = (
                        [string]$values.MIGRATION_HELPER_SHA256
                    ).ToLowerInvariant()
                }
            )
        if (
            [string]$values.MIGRATION_HELPER_SHA256 -cnotmatch
                "^[0-9A-F]{64}$"
        ) {
            throw "持久安装身份 helper SHA-256 不是 canonical uppercase。"
        }
        $helperRelativePath = $helperEvidence.RelativePath
        $helperSize = [int64]$helperEvidence.Size
        $helperSha256 = [string]$helperEvidence.Sha256
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
        IsPendingArtifact = [bool]$Pending
        Schema = [string]$values.SCHEMA
        State = $state
        OperationId = $operationId
        LegacyCompleted = $legacyCompleted
        BackendVersionFloor = [string]$values.BACKEND_VERSION_FLOOR
        InstallationId = $installationId.ToString("D")
        BuildManifestSha256 = [string]$values.BUILD_MANIFEST_SHA256
        DataRoot = [string]$values.DATA_ROOT
        InstallDir = [string]$values.INSTALL_DIR
        PgServiceName = [string]$values.PG_SERVICE_NAME
        BackendServiceName = [string]$values.BACKEND_SERVICE_NAME
        PgPort = $pgPort
        BackendPort = $backendPort
        MigrationHelperRelativePath = $helperRelativePath
        MigrationHelperSize = $helperSize
        MigrationHelperSha256 = $helperSha256
    }
}

function Read-TicketboxInstalledBuildManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(0, 99)][int]$ExpectedPgMajor = 0
    )

    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
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
    $c07MigrationHelper =
        ConvertTo-TicketboxInstalledC07MigrationHelperEvidence (
            $manifest.backend.c07_migration_helper
        )
    return [pscustomobject]@{
        Path = $Path
        Manifest = $manifest
        BackendVersion = $backendVersion
        PgMajor = $pgMajor
        C07MigrationHelper = $c07MigrationHelper
    }
}

function Get-TicketboxInstallationReleaseCandidate {
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
    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath $InstallDir
    $expectedManifestPath = ConvertTo-TicketboxCanonicalPath (
        Join-Path $canonicalInstallDir "installer\BUILD_PROVENANCE.json"
    )
    if (
        -not (
            Test-TicketboxPathEquals `
                $BuildManifestPath `
                $expectedManifestPath
        )
    ) {
        throw "持久安装身份只接受 installed installer BUILD_PROVENANCE.json。"
    }
    $buildManifest = Read-TicketboxInstalledBuildManifest $expectedManifestPath
    $helperEvidence = $buildManifest.C07MigrationHelper
    $helperPath = Resolve-TicketboxInstalledC07MigrationHelperPath `
        -InstallDir $canonicalInstallDir `
        -Evidence $helperEvidence
    $helperLease = $null
    try {
        $helperLease = Open-TicketboxC07VerifiedMigrationHelperLease `
            -Path $helperPath `
            -ExpectedRelativePath $helperEvidence.RelativePath `
            -ExpectedSize $helperEvidence.Size `
            -ExpectedSha256 $helperEvidence.Sha256
        $verifiedHelperSize = [int64]$helperLease.Size
        $verifiedHelperSha256 = [string]$helperLease.Sha256
    }
    finally {
        Close-TicketboxC07MigrationHelperLease $helperLease
    }
    return [pscustomobject][ordered]@{
        BackendVersionFloor = [string]$buildManifest.BackendVersion
        BuildManifestSha256 =
            Get-TicketboxPortableFileSha256 $expectedManifestPath
        DataRoot = $canonicalDataRoot
        InstallDir = $canonicalInstallDir
        PgServiceName = $PgServiceName
        BackendServiceName = $BackendServiceName
        PgPort = $PgPort
        BackendPort = $BackendPort
        MigrationHelperPath = $helperPath
        MigrationHelperRelativePath = [string]$helperEvidence.RelativePath
        MigrationHelperSize = $verifiedHelperSize
        MigrationHelperSha256 = $verifiedHelperSha256
    }
}

function Assert-TicketboxInstallationIdentityBaseMatches {
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][object]$Candidate
    )
    if (
        -not (Test-TicketboxPathEquals $Identity.DataRoot $Candidate.DataRoot) -or
        -not (Test-TicketboxPathEquals $Identity.InstallDir $Candidate.InstallDir) -or
        $Identity.PgServiceName -cne $Candidate.PgServiceName -or
        $Identity.BackendServiceName -cne $Candidate.BackendServiceName -or
        $Identity.PgPort -ne $Candidate.PgPort -or
        $Identity.BackendPort -ne $Candidate.BackendPort
    ) {
        throw "持久安装身份与当前 protected install/DataRoot authority 不一致。"
    }
    if (
        (Compare-TicketboxNumericVersion `
            $Candidate.BackendVersionFloor `
            $Identity.BackendVersionFloor) -lt 0
    ) {
        throw (
            "拒绝把持久 backend version floor 从 " +
            "$($Identity.BackendVersionFloor) 降到 " +
            "$($Candidate.BackendVersionFloor)。"
        )
    }
}

function Repair-TicketboxRecoverableInstallationIdentityAcl {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [switch]$Pending
    )

    $dataRoot = ConvertTo-TicketboxWin32CanonicalPath (
        [string]$Candidate.DataRoot
    )
    $path = if ($Pending) {
        Get-TicketboxPendingInstallationIdentityPath $dataRoot
    }
    else {
        Get-TicketboxPersistentInstallationIdentityPath $dataRoot
    }
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw "持久安装身份不是普通文件，拒绝 ACL 恢复。"
    }
    $acl = Get-TicketboxPathAcl $path
    if ($acl.AreAccessRulesProtected) {
        $identity = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $dataRoot `
            -Pending:$Pending
        if (
            ($Pending -and (
                $identity.State -cne "PENDING" -or
                [bool]$identity.LegacyCompleted
            )) -or
            (-not $Pending -and $identity.State -cne "READY")
        ) {
            throw "持久安装身份状态与 artifact 路径不一致。"
        }
        Assert-TicketboxInstallationIdentityBaseMatches $identity $Candidate
        return $false
    }

    # A failed trusted installer can leave the exact parent-inherited ACL on
    # an otherwise canonical identity artifact.  Prove the protected parent,
    # the complete inherited ACL shape, the bounded identity schema/state and
    # its base binding before the first ACL write.  Release evidence may differ
    # because a newer signed installer is allowed to reconcile a predecessor.
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $dataRoot `
        -FullControlAccounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    Assert-TicketboxRecoverableInheritedFileAcl `
        -Path $path `
        -FullControlAccounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    $identity = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot $dataRoot `
        -Pending:$Pending `
        -AllowRecoverableInheritedAcl
    if (
        ($Pending -and (
            $identity.State -cne "PENDING" -or
            [bool]$identity.LegacyCompleted
        )) -or
        (-not $Pending -and $identity.State -cne "READY")
    ) {
        throw "可恢复持久安装身份状态与 artifact 路径不一致。"
    }
    Assert-TicketboxInstallationIdentityBaseMatches $identity $Candidate
    $beforeBytes = [IO.File]::ReadAllBytes(
        (ConvertTo-TicketboxWin32ExtendedPath $path)
    )

    Set-TicketboxExactFileAcl `
        -Path $path `
        -Accounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    $repaired = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot $dataRoot `
        -Pending:$Pending
    $afterBytes = [IO.File]::ReadAllBytes(
        (ConvertTo-TicketboxWin32ExtendedPath $path)
    )
    if (
        -not (Test-TicketboxByteArrayEquals $beforeBytes $afterBytes) -or
        $repaired.State -cne $identity.State -or
        $repaired.OperationId -cne $identity.OperationId -or
        $repaired.InstallationId -cne $identity.InstallationId -or
        $repaired.BuildManifestSha256 -cne $identity.BuildManifestSha256
    ) {
        throw "持久安装身份 ACL 恢复改变了受保护字节或绑定身份。"
    }
    Assert-TicketboxInstallationIdentityBaseMatches $repaired $Candidate
    return $true
}

function Test-TicketboxInstallationIdentityReleaseMatches {
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][object]$Candidate
    )
    if (
        $Identity.BuildManifestSha256 -cne
            $Candidate.BuildManifestSha256 -or
        $Identity.BackendVersionFloor -cne
            $Candidate.BackendVersionFloor
    ) {
        return $false
    }
    if ([bool]$Identity.LegacyCompleted) {
        return $true
    }
    return (
        $Identity.MigrationHelperRelativePath -ceq
            $Candidate.MigrationHelperRelativePath -and
        [int64]$Identity.MigrationHelperSize -eq
            [int64]$Candidate.MigrationHelperSize -and
        $Identity.MigrationHelperSha256 -ceq
            $Candidate.MigrationHelperSha256
    )
}

function Get-TicketboxPersistentInstallationIdentityText {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("PENDING", "READY")][string]$State,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][object]$Candidate
    )
    $canonicalOperationId = ([guid]$OperationId).ToString("D")
    $canonicalInstallationId = ([guid]$InstallationId).ToString("D")
    return (@(
        "SCHEMA=$script:TicketboxPersistentInstallationIdentitySchema",
        "STATE=$State",
        "OPERATION_ID=$canonicalOperationId",
        "BACKEND_VERSION_FLOOR=$($Candidate.BackendVersionFloor)",
        "INSTALLATION_ID=$canonicalInstallationId",
        "BUILD_MANIFEST_SHA256=$($Candidate.BuildManifestSha256)",
        "MIGRATION_HELPER_RELATIVE_PATH=$($Candidate.MigrationHelperRelativePath)",
        "MIGRATION_HELPER_SIZE=$([int64]$Candidate.MigrationHelperSize)",
        "MIGRATION_HELPER_SHA256=$($Candidate.MigrationHelperSha256)",
        "DATA_ROOT=$($Candidate.DataRoot)",
        "INSTALL_DIR=$($Candidate.InstallDir)",
        "PG_SERVICE_NAME=$($Candidate.PgServiceName)",
        "BACKEND_SERVICE_NAME=$($Candidate.BackendServiceName)",
        "PG_PORT=$($Candidate.PgPort)",
        "BACKEND_PORT=$($Candidate.BackendPort)"
    ) -join "`r`n") + "`r`n"
}

function Write-TicketboxInstallationIdentityState {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("PENDING", "READY")][string]$State,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [switch]$ReplaceExisting
    )
    $path = if ($State -ceq "PENDING") {
        Get-TicketboxPendingInstallationIdentityPath (
            [string]$Candidate.DataRoot
        )
    }
    else {
        Get-TicketboxPersistentInstallationIdentityPath (
            [string]$Candidate.DataRoot
        )
    }
    $text = Get-TicketboxPersistentInstallationIdentityText `
        -State $State `
        -OperationId $OperationId `
        -InstallationId $InstallationId `
        -Candidate $Candidate
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $text `
        -FullControlAccounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount `
        -ReplaceExisting:$ReplaceExisting
    $persisted = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot ([string]$Candidate.DataRoot) `
        -Pending:($State -ceq "PENDING")
    if (
        $persisted.State -cne $State -or
        $persisted.OperationId -cne ([guid]$OperationId).ToString("D") -or
        $persisted.InstallationId -cne
            ([guid]$InstallationId).ToString("D") -or
        -not (
            Test-TicketboxInstallationIdentityReleaseMatches `
                $persisted `
                $Candidate
        )
    ) {
        throw "持久安装身份原子写入后的复读不一致。"
    }
    return $persisted
}

function Initialize-TicketboxPendingInstallationIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath,
        [string]$ExpectedOperationId = ""
    )
    $candidate = Get-TicketboxInstallationReleaseCandidate `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -PgServiceName $PgServiceName `
        -BackendServiceName $BackendServiceName `
        -BuildManifestPath $BuildManifestPath
    $readyPath =
        Get-TicketboxPersistentInstallationIdentityPath $candidate.DataRoot
    $pendingPath =
        Get-TicketboxPendingInstallationIdentityPath $candidate.DataRoot
    $ready = $null
    $pending = $null
    if (Test-Path -LiteralPath $readyPath) {
        Repair-TicketboxRecoverableInstallationIdentityAcl `
            -Candidate $candidate | Out-Null
        $ready = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $candidate.DataRoot
        if ($ready.State -cne "READY") {
            throw "committed installation identity artifact 只能承载 READY 状态。"
        }
        Assert-TicketboxInstallationIdentityBaseMatches $ready $candidate
    }
    if (Test-Path -LiteralPath $pendingPath) {
        Repair-TicketboxRecoverableInstallationIdentityAcl `
            -Candidate $candidate `
            -Pending | Out-Null
        $pending = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $candidate.DataRoot `
            -Pending
        if (
            $pending.State -cne "PENDING" -or
            [bool]$pending.LegacyCompleted
        ) {
            throw "pending installation identity artifact 状态无效。"
        }
        Assert-TicketboxInstallationIdentityBaseMatches $pending $candidate
    }
    if (
        $null -ne $ready -and
        $null -ne $pending -and
        $ready.InstallationId -cne $pending.InstallationId
    ) {
        throw "READY/PENDING installation identity 属于不同 installation。"
    }
    $operationId = if ([string]::IsNullOrEmpty($ExpectedOperationId)) {
        if ($null -ne $pending) {
            [string]$pending.OperationId
        }
        else {
            [guid]::NewGuid().ToString("D")
        }
    }
    else {
        ([guid]$ExpectedOperationId).ToString("D")
    }
    if ($null -ne $pending) {
        if (
            $pending.OperationId -cne $operationId -or
            -not (
                Test-TicketboxInstallationIdentityReleaseMatches `
                    $pending `
                    $candidate
            )
        ) {
            throw "foreign/mismatched PENDING installation identity 拒绝恢复。"
        }
        return $pending
    }
    if (
        $null -ne $ready -and
        (Test-TicketboxInstallationIdentityReleaseMatches $ready $candidate)
    ) {
        return $ready
    }
    $installationId = if ($null -eq $ready) {
        [guid]::NewGuid().ToString("D")
    }
    else {
        [string]$ready.InstallationId
    }
    return Write-TicketboxInstallationIdentityState `
        -State "PENDING" `
        -OperationId $operationId `
        -InstallationId $installationId `
        -Candidate $candidate
}

function Promote-TicketboxPendingInstallationIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath,
        [string]$ExpectedOperationId = ""
    )
    $candidate = Get-TicketboxInstallationReleaseCandidate `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -PgServiceName $PgServiceName `
        -BackendServiceName $BackendServiceName `
        -BuildManifestPath $BuildManifestPath
    $readyPath =
        Get-TicketboxPersistentInstallationIdentityPath $candidate.DataRoot
    $pendingPath =
        Get-TicketboxPendingInstallationIdentityPath $candidate.DataRoot
    $ready = $null
    $pending = $null
    if (Test-Path -LiteralPath $readyPath) {
        Repair-TicketboxRecoverableInstallationIdentityAcl `
            -Candidate $candidate | Out-Null
        $ready = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $candidate.DataRoot
        if ($ready.State -cne "READY") {
            throw "committed installation identity artifact 只能承载 READY 状态。"
        }
        Assert-TicketboxInstallationIdentityBaseMatches $ready $candidate
    }
    if (Test-Path -LiteralPath $pendingPath) {
        Repair-TicketboxRecoverableInstallationIdentityAcl `
            -Candidate $candidate `
            -Pending | Out-Null
        $pending = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $candidate.DataRoot `
            -Pending
        if (
            $pending.State -cne "PENDING" -or
            [bool]$pending.LegacyCompleted
        ) {
            throw "CommitCompletedInstall 缺少有效 PENDING identity。"
        }
        Assert-TicketboxInstallationIdentityBaseMatches $pending $candidate
    }
    if ($null -eq $pending) {
        if (
            $null -eq $ready -or
            -not (
                Test-TicketboxInstallationIdentityReleaseMatches `
                    $ready `
                    $candidate
            )
        ) {
            throw "CommitCompletedInstall 缺少可验证的 PENDING/READY identity。"
        }
        if (
            -not [string]::IsNullOrEmpty($ExpectedOperationId) -and
            -not [bool]$ready.LegacyCompleted -and
            $ready.OperationId -cne
                ([guid]$ExpectedOperationId).ToString("D")
        ) {
            throw "CommitCompletedInstall READY operation identity 不一致。"
        }
        return $ready
    }
    if ([string]::IsNullOrEmpty($ExpectedOperationId)) {
        throw "CommitCompletedInstall 缺少安装事务绑定的 operation id。"
    }
    $canonicalExpectedOperationId =
        ([guid]$ExpectedOperationId).ToString("D")
    if (
        $pending.OperationId -cne $canonicalExpectedOperationId -or
        -not (
            Test-TicketboxInstallationIdentityReleaseMatches `
                $pending `
                $candidate
        )
    ) {
        throw "CommitCompletedInstall PENDING operation/release identity 不一致。"
    }
    if (
        $null -ne $ready -and
        $ready.InstallationId -cne $pending.InstallationId
    ) {
        throw "CommitCompletedInstall READY/PENDING installation id 冲突。"
    }
    $committed = Write-TicketboxInstallationIdentityState `
        -State "READY" `
        -OperationId $pending.OperationId `
        -InstallationId $pending.InstallationId `
        -Candidate $candidate `
        -ReplaceExisting:($null -ne $ready)
    if (
        $committed.InstallationId -cne $pending.InstallationId -or
        $committed.OperationId -cne $pending.OperationId -or
        -not (
            Test-TicketboxInstallationIdentityReleaseMatches `
                $committed `
                $candidate
        )
    ) {
        throw "CommitCompletedInstall READY ACK 复读未收敛到 exact PENDING。"
    }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $pendingPath `
        -FullControlAccounts $script:TicketboxPersistentInstallationIdentityAclAccounts `
        -OwnerAccount $script:TicketboxPersistentInstallationIdentityOwnerAccount
    return $committed
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
    $pending = Initialize-TicketboxPendingInstallationIdentity `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -PgServiceName $PgServiceName `
        -BackendServiceName $BackendServiceName `
        -BuildManifestPath $BuildManifestPath
    if ($pending.State -ceq "READY") {
        return $pending
    }
    return Promote-TicketboxPendingInstallationIdentity `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -PgServiceName $PgServiceName `
        -BackendServiceName $BackendServiceName `
        -BuildManifestPath $BuildManifestPath `
        -ExpectedOperationId $pending.OperationId
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
    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    try { $registeredDataRoot = [string](& $RegistryReader) }
    catch { throw "无法读取受保护的机器级安装身份，拒绝收编既有数据目录。" }
    if (
        [string]::IsNullOrWhiteSpace($registeredDataRoot) -or
        -not (Test-TicketboxPathEquals $registeredDataRoot $canonicalDataRoot)
    ) {
        throw "既有数据目录与 HKLM 安装身份不匹配，拒绝收编。"
    }
}

function Get-TicketboxDataRootMarkerText {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string]$DataVolumeIdentity = "",
        [switch]$LegacyV1
    )

    $payload = [ordered]@{
        schema = if ($LegacyV1) {
            $script:TicketboxLegacyDataRootMarkerSchema
        }
        else {
            $script:TicketboxDataRootMarkerSchema
        }
        data_root = ConvertTo-TicketboxCanonicalPath $DataRoot
        install_dir = ConvertTo-TicketboxCanonicalPath $InstallDir
    }
    if (-not $LegacyV1) {
        if ([string]::IsNullOrWhiteSpace($DataVolumeIdentity)) {
            throw "DataRoot v2 marker 缺少 Windows volume identity。"
        }
        $payload.data_volume_identity = ConvertTo-TicketboxCanonicalVolumeIdentity `
            $DataVolumeIdentity
    }
    return $payload | ConvertTo-Json -Compress
}

function ConvertFrom-TicketboxDataRootMarkerText {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowLegacyV1
    )

    try { $marker = ConvertFrom-Json -InputObject $Text }
    catch { throw "数据目录标记不是有效 JSON。" }
    $schema = [string]$marker.schema
    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath $InstallDir
    try {
        $markerDataRoot = ConvertTo-TicketboxCanonicalPath ([string]$marker.data_root)
        $markerInstallDir = ConvertTo-TicketboxCanonicalPath ([string]$marker.install_dir)
    }
    catch {
        throw "数据目录标记的路径绑定无效。"
    }
    if (
        -not (Test-TicketboxPathEquals $markerDataRoot $canonicalDataRoot) -or
        -not (Test-TicketboxPathEquals $markerInstallDir $canonicalInstallDir)
    ) {
        throw "数据目录标记与当前安装路径不匹配。"
    }
    if ($schema -ceq $script:TicketboxDataRootMarkerSchema) {
        try {
            $volumeIdentity = ConvertTo-TicketboxCanonicalVolumeIdentity `
                ([string]$marker.data_volume_identity)
        }
        catch {
            throw "DataRoot v2 marker 的 Windows volume identity 无效。"
        }
        $canonicalText = Get-TicketboxDataRootMarkerText `
            -DataRoot $markerDataRoot `
            -InstallDir $markerInstallDir `
            -DataVolumeIdentity $volumeIdentity
        if ($Text -cne $canonicalText) {
            throw "DataRoot v2 marker 不是规范且唯一的安装绑定。"
        }
        return [pscustomobject]@{
            Schema = $schema
            DataRoot = $markerDataRoot
            InstallDir = $markerInstallDir
            DataVolumeIdentity = $volumeIdentity
            IsLegacyV1 = $false
        }
    }
    if ($schema -ceq $script:TicketboxLegacyDataRootMarkerSchema -and $AllowLegacyV1) {
        $canonicalText = Get-TicketboxDataRootMarkerText `
            -DataRoot $markerDataRoot `
            -InstallDir $markerInstallDir `
            -LegacyV1
        if ($Text -cne $canonicalText) {
            throw "legacy DataRoot marker 不是规范且唯一的安装绑定。"
        }
        return [pscustomobject]@{
            Schema = $schema
            DataRoot = $markerDataRoot
            InstallDir = $markerInstallDir
            DataVolumeIdentity = ""
            IsLegacyV1 = $true
        }
    }
    throw "数据目录标记 schema 不受当前操作信任。"
}

function Read-TicketboxDataRootMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowLegacyV1
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    if ((Get-TicketboxPathEntryKindNoFollow $markerPath) -cne "File") {
        throw "拒绝信任缺失或非普通文件的数据目录标记：$markerPath"
    }
    Assert-NoTicketboxAncestorReparsePoints $markerPath
    $item = Get-Item -LiteralPath $markerPath -Force -ErrorAction Stop
    if (
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.Length -le 0 -or
        $item.Length -gt 16384
    ) {
        throw "数据目录标记不是有效普通文件：$markerPath"
    }
    $bytes = [System.IO.File]::ReadAllBytes($markerPath)
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    try { $text = $encoding.GetString($bytes) }
    catch { throw "数据目录标记不是严格 UTF-8：$markerPath" }
    $roundTripBytes = $encoding.GetBytes($text)
    if (-not (Test-TicketboxByteArrayEquals -Left $bytes -Right $roundTripBytes)) {
        throw "数据目录标记不能无损 UTF-8 往返：$markerPath"
    }
    return ConvertFrom-TicketboxDataRootMarkerText `
        -Text $text `
        -DataRoot $canonicalDataRoot `
        -InstallDir $canonicalInstallDir `
        -AllowLegacyV1:$AllowLegacyV1
}

function Get-TicketboxExpectedBackendServiceSid {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedBackendServiceName
    )

    if ([string]::IsNullOrWhiteSpace($ExpectedBackendServiceName)) {
        throw "DataRoot marker backend-read ACL 缺少目标 backend 服务名。"
    }
    if (
        $null -eq (Get-Command `
            -Name Get-TicketboxServiceSid `
            -CommandType Function `
            -ErrorAction SilentlyContinue)
    ) {
        throw "DataRoot marker backend-read ACL 缺少统一服务 SID 查询边界。"
    }
    $backendServiceSid = Get-TicketboxServiceSid $ExpectedBackendServiceName
    if ($backendServiceSid -cnotmatch '^S-1-5-80-(?:[0-9]+-){4}[0-9]+$') {
        throw "DataRoot marker backend-read ACL 的服务 SID 无效。"
    }
    return $backendServiceSid
}

function Get-TicketboxDataRootMarkerAclReadExecuteAccounts {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$AclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$OwnerAccount = "SYSTEM"
    )

    Assert-NoTicketboxAncestorReparsePoints $Path
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "File") {
        throw "DataRoot marker 不存在或不是普通文件：$Path"
    }
    if ($AclPhase -ceq "privileged_only") {
        if (-not [string]::IsNullOrWhiteSpace($ExpectedBackendServiceName)) {
            throw "privileged-only DataRoot marker ACL 不能携带 backend 服务身份。"
        }
        Assert-TicketboxExactFileAcl `
            -Path $Path `
            -Accounts $FullControlAccounts `
            -OwnerAccount $OwnerAccount
        return
    }

    $backendServiceSid = Get-TicketboxExpectedBackendServiceSid `
        $ExpectedBackendServiceName
    if ($AclPhase -ceq "backend_read_optional") {
        $acl = Get-TicketboxPathAcl $Path
        $backendRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value -eq $backendServiceSid
        })
        if ($backendRules.Count -eq 0) {
            Assert-TicketboxExactFileAcl `
                -Path $Path `
                -Accounts $FullControlAccounts `
                -OwnerAccount $OwnerAccount
            return
        }
        # The only second accepted shape is the same privileged ACL plus exact
        # read/execute for the trusted backend service identity. Select the
        # shape from the ACL instead of using a caught exception as control
        # flow; Start-Transcript otherwise records a false terminating error.
    }
    Assert-TicketboxExactFileAcl `
        -Path $Path `
        -Accounts $FullControlAccounts `
        -ReadExecuteAccounts @($backendServiceSid) `
        -OwnerAccount $OwnerAccount
    return $backendServiceSid
}

function Write-TicketboxDataRootMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string]$DataVolumeIdentity = "",
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [string[]]$ReadExecuteAccounts = @(),
        [string]$OwnerAccount = "SYSTEM",
        [switch]$ReplaceExisting
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $canonicalVolumeIdentity = if ([string]::IsNullOrWhiteSpace($DataVolumeIdentity)) {
        Get-TicketboxVolumeIdentityForPath $canonicalDataRoot
    }
    else {
        ConvertTo-TicketboxCanonicalVolumeIdentity $DataVolumeIdentity
    }
    Assert-TicketboxVolumeIdentityForPath `
        -Path $canonicalDataRoot `
        -ExpectedVolumeIdentity $canonicalVolumeIdentity
    $payload = Get-TicketboxDataRootMarkerText `
        -DataRoot $canonicalDataRoot `
        -InstallDir $canonicalInstallDir `
        -DataVolumeIdentity $canonicalVolumeIdentity
    Write-TicketboxProtectedUtf8FileDurable `
        -Path (Get-TicketboxDataRootMarkerPath $canonicalDataRoot) `
        -Text $payload `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $OwnerAccount `
        -ReplaceExisting:$ReplaceExisting
}

function Assert-TicketboxDataRootMarkerInitialization {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowLegacyV1Migration
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    $markerKind = Get-TicketboxPathEntryKindNoFollow $markerPath
    if ($markerKind -ceq "File") {
        Assert-TicketboxDataRootMarker `
            -DataRoot $canonicalDataRoot `
            -InstallDir $canonicalInstallDir `
            -AllowLegacyV1:$AllowLegacyV1Migration
        return
    }
    if ($markerKind -cne "Missing") {
        throw "DataRoot marker 不是普通文件或缺失路径，拒绝初始化。"
    }

    $entries = @(Get-ChildItem -LiteralPath $canonicalDataRoot -Force)
    if ($entries.Count -gt 0) {
        throw "拒绝把 markerless 非空目录收编为小票夹数据根：$canonicalDataRoot"
    }
}

function Assert-TicketboxLegacyProtectedFileAcl([string]$Path) {
    $Path = ConvertTo-TicketboxWin32CanonicalPath $Path
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
    $canonicalEnvPath = ConvertTo-TicketboxWin32CanonicalPath $EnvPath
    $canonicalPgData = ConvertTo-TicketboxWin32CanonicalPath $PgData
    $canonicalDataRoot = Assert-TicketboxDataRootDomain `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir
    Assert-NoTicketboxAncestorReparsePoints $canonicalDataRoot
    Assert-NoTicketboxReparsePoints $canonicalDataRoot
    Assert-TicketboxDataRootMarkerInitialization `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyV1Migration
    Assert-TicketboxLegacyProtectedFileAcl $canonicalEnvPath
    $pgVersionPath = Join-Path $canonicalPgData "PG_VERSION"
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
        [switch]$AllowLegacyV1Migration,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$AclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$OwnerAccount = "SYSTEM"
    )

    $canonicalDataRoot = Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir
    if (-not (Test-Path -LiteralPath $canonicalDataRoot)) {
        New-Item -ItemType Directory -Path $canonicalDataRoot -ErrorAction Stop | Out-Null
    }
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    $markerKind = Get-TicketboxPathEntryKindNoFollow $markerPath
    $markerReadExecuteAccounts = @()
    if ($markerKind -ceq "File") {
        $markerReadExecuteAccounts = @(
            Get-TicketboxDataRootMarkerAclReadExecuteAccounts `
                -Path $markerPath `
                -FullControlAccounts $FullControlAccounts `
                -AclPhase $AclPhase `
                -ExpectedBackendServiceName $ExpectedBackendServiceName `
                -OwnerAccount $OwnerAccount
        )
    }
    elseif ($markerKind -ceq "Missing") {
        if ($AclPhase -ceq "privileged_only") {
            if (-not [string]::IsNullOrWhiteSpace($ExpectedBackendServiceName)) {
                throw "privileged-only DataRoot marker ACL 不能携带 backend 服务身份。"
            }
        }
        else {
            $backendServiceSid = Get-TicketboxExpectedBackendServiceSid `
                $ExpectedBackendServiceName
            if ($AclPhase -ceq "backend_read_required") {
                $markerReadExecuteAccounts = @($backendServiceSid)
            }
        }
    }
    Assert-TicketboxDataRootMarkerInitialization `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyV1Migration:$AllowLegacyV1Migration
    if ($markerKind -ceq "File" -and $AllowLegacyV1Migration) {
        $existingMarker = Read-TicketboxDataRootMarker `
            -DataRoot $canonicalDataRoot `
            -InstallDir $InstallDir `
            -AllowLegacyV1
        if ($existingMarker.IsLegacyV1) {
            $targetVolumeIdentity = Get-TicketboxVolumeIdentityForPath $canonicalDataRoot
            Write-TicketboxDataRootMarker `
                -DataRoot $canonicalDataRoot `
                -InstallDir $InstallDir `
                -DataVolumeIdentity $targetVolumeIdentity `
                -FullControlAccounts $FullControlAccounts `
                -ReadExecuteAccounts $markerReadExecuteAccounts `
                -OwnerAccount $OwnerAccount `
                -ReplaceExisting
        }
    }
    elseif ($markerKind -ceq "Missing") {
        Write-TicketboxDataRootMarker `
            -DataRoot $canonicalDataRoot `
            -InstallDir $InstallDir `
            -FullControlAccounts $FullControlAccounts `
            -ReadExecuteAccounts $markerReadExecuteAccounts `
            -OwnerAccount $OwnerAccount
    }
    elseif ($markerKind -cne "File") {
        throw "DataRoot marker 不是普通文件或缺失路径，拒绝初始化。"
    }
    Assert-TicketboxProtectedDataRootMarker `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $FullControlAccounts `
        -AclPhase $AclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -OwnerAccount $OwnerAccount
}

function Initialize-TicketboxSecureDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string[]]$Accounts,
        [switch]$AllowLegacyV1Migration,
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$DataRootMarkerAclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$OwnerAccount = "SYSTEM"
    )

    $canonicalDataRoot = Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir
    $expectedBackendServiceSid = ""
    if ($DataRootMarkerAclPhase -ceq "privileged_only") {
        if (-not [string]::IsNullOrWhiteSpace($ExpectedBackendServiceName)) {
            throw "privileged-only DataRoot marker ACL 不能携带 backend 服务身份。"
        }
    }
    else {
        $expectedBackendServiceSid = Get-TicketboxExpectedBackendServiceSid `
            $ExpectedBackendServiceName
    }
    Assert-NoTicketboxAncestorReparsePoints $canonicalDataRoot
    if (-not (Test-Path -LiteralPath $canonicalDataRoot)) {
        New-Item -ItemType Directory -Path $canonicalDataRoot -ErrorAction Stop | Out-Null
    }
    Assert-NoTicketboxAncestorReparsePoints $canonicalDataRoot
    Assert-NoTicketboxReparsePoints $canonicalDataRoot
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    $markerKind = Get-TicketboxPathEntryKindNoFollow $markerPath
    $markerReadExecuteAccounts = if (
        $DataRootMarkerAclPhase -ceq "backend_read_required"
    ) {
        @($expectedBackendServiceSid)
    }
    else { @() }
    if ($markerKind -ceq "File") {
        $markerAcl = Get-TicketboxPathAcl $markerPath
        if ($markerAcl.AreAccessRulesProtected) {
            $markerReadExecuteAccounts = @(
                Get-TicketboxDataRootMarkerAclReadExecuteAccounts `
                    -Path $markerPath `
                    -FullControlAccounts $Accounts `
                    -AclPhase $DataRootMarkerAclPhase `
                    -ExpectedBackendServiceName $ExpectedBackendServiceName `
                    -OwnerAccount $OwnerAccount
            )
            Assert-TicketboxDataRootMarker `
                -DataRoot $canonicalDataRoot `
                -InstallDir $InstallDir `
                -AllowLegacyV1:$AllowLegacyV1Migration
        }
        else {
            Repair-TicketboxRecoverableDataRootMarkerAcl `
                -DataRoot $canonicalDataRoot `
                -InstallDir $InstallDir `
                -FullControlAccounts $Accounts `
                -OwnerAccount $OwnerAccount | Out-Null
        }
    }
    elseif ($markerKind -ceq "Missing") {
        Assert-TicketboxDataRootMarkerInitialization `
            -DataRoot $canonicalDataRoot `
            -InstallDir $InstallDir `
            -AllowLegacyV1Migration:$AllowLegacyV1Migration
    }
    else {
        throw "DataRoot marker 不是普通文件或缺失路径，拒绝初始化。"
    }
    Set-TicketboxExactDirectoryAcl `
        -Path $canonicalDataRoot `
        -Accounts $Accounts `
        -OwnerAccount $OwnerAccount `
        -Recurse
    if ($markerKind -ceq "File") {
        # Recursive ACL normalization intentionally resets descendants to the
        # root inheritance shape.  Restore the separately authoritative marker
        # before any later code is allowed to trust it.
        Set-TicketboxExactFileAcl `
            -Path $markerPath `
            -Accounts $Accounts `
            -ReadExecuteAccounts $markerReadExecuteAccounts `
            -OwnerAccount $OwnerAccount
    }
    Initialize-TicketboxDataRootMarker `
        -DataRoot $canonicalDataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyV1Migration:$AllowLegacyV1Migration `
        -FullControlAccounts $Accounts `
        -AclPhase $DataRootMarkerAclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -OwnerAccount $OwnerAccount
}

function Assert-TicketboxDataRootMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$AllowLegacyV1
    )

    $marker = Read-TicketboxDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -AllowLegacyV1:$AllowLegacyV1
    if (-not $marker.IsLegacyV1) {
        Assert-TicketboxVolumeIdentityForPath `
            -Path $DataRoot `
            -ExpectedVolumeIdentity $marker.DataVolumeIdentity
    }
}

function Read-TicketboxProtectedDataRootMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$AclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$OwnerAccount = "SYSTEM"
    )

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $markerPath = Get-TicketboxDataRootMarkerPath $canonicalDataRoot
    $markerReadExecuteAccounts = @(
        Get-TicketboxDataRootMarkerAclReadExecuteAccounts `
            -Path $markerPath `
            -FullControlAccounts $FullControlAccounts `
            -AclPhase $AclPhase `
            -ExpectedBackendServiceName $ExpectedBackendServiceName `
            -OwnerAccount $OwnerAccount
    )

    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $markerPath `
        -FullControlAccounts $FullControlAccounts `
        -ReadExecuteAccounts $markerReadExecuteAccounts `
        -OwnerAccount $OwnerAccount `
        -MaximumBytes 16384
    $marker = ConvertFrom-TicketboxDataRootMarkerText `
        -Text $artifact.Text `
        -DataRoot $canonicalDataRoot `
        -InstallDir $canonicalInstallDir
    Assert-TicketboxVolumeIdentityForPath `
        -Path $canonicalDataRoot `
        -ExpectedVolumeIdentity $marker.DataVolumeIdentity
    return $marker
}

function Assert-TicketboxProtectedDataRootMarker {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [string[]]$FullControlAccounts = @("SYSTEM", "BUILTIN\Administrators"),
        [ValidateSet(
            "privileged_only",
            "backend_read_optional",
            "backend_read_required"
        )][string]$AclPhase = "privileged_only",
        [string]$ExpectedBackendServiceName = "",
        [string]$OwnerAccount = "SYSTEM"
    )

    Read-TicketboxProtectedDataRootMarker `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -FullControlAccounts $FullControlAccounts `
        -AclPhase $AclPhase `
        -ExpectedBackendServiceName $ExpectedBackendServiceName `
        -OwnerAccount $OwnerAccount | Out-Null
}

function Assert-NoTicketboxReparsePoints([string]$DataRoot) {
    $DataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
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

    $full = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalInstallDir = ConvertTo-TicketboxWin32CanonicalPath $InstallDir
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.StartsWith("\\")) {
        throw "数据目录不能使用 UNC 路径：$full"
    }
    if ((Get-TicketboxDataRootDriveType $full) -ne [System.IO.DriveType]::Fixed) {
        throw "数据目录必须位于本机固定磁盘，不能使用映射网络盘或可移除介质：$full"
    }
    Assert-TicketboxDataRootVolumeCapabilities $full | Out-Null
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
        $canonicalInstallDir
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
        [switch]$AllowProtectedMarkerWithoutRegistration,
        [switch]$AllowMarkerlessEmptyRoot
    )

    $canonicalRegisteredDataRoot = if (
        [string]::IsNullOrWhiteSpace($RegisteredDataRoot)
    ) {
        ""
    }
    else {
        ConvertTo-TicketboxWin32CanonicalPath $RegisteredDataRoot
    }
    $full = Assert-TicketboxDataRootDomain -DataRoot $DataRoot -InstallDir $InstallDir
    $registrationMissing = [string]::IsNullOrWhiteSpace($RegisteredDataRoot)
    if ($registrationMissing -and -not $AllowProtectedMarkerWithoutRegistration) {
        throw "安装器注册表缺少 DataRoot，拒绝删除任何数据目录。"
    }
    if (-not $registrationMissing -and -not (Test-TicketboxPathEquals $full $canonicalRegisteredDataRoot)) {
        throw "数据目录与安装器登记值不一致，拒绝删除：$full"
    }
    Assert-NoTicketboxAncestorReparsePoints $full

    if (Test-Path -LiteralPath $full) {
        $markerPath = Get-TicketboxDataRootMarkerPath $full
        if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
            Assert-TicketboxDataRootMarker -DataRoot $full -InstallDir $InstallDir
        }
        elseif ($AllowMarkerlessEmptyRoot) {
            $remainingEntries = @(Get-ChildItem -LiteralPath $full -Force -ErrorAction Stop)
            if ($remainingEntries.Count -gt 0) {
                throw "数据目录缺少权威标记且仍非空，拒绝把它当作中断删除续跑目标：$full"
            }
        }
        else {
            throw "数据目录缺少权威标记，拒绝删除：$markerPath"
        }
        if ($registrationMissing -and (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
            Assert-TicketboxExactFileAcl `
                -Path $markerPath `
                -Accounts @("SYSTEM", "BUILTIN\Administrators") `
                -OwnerAccount "SYSTEM"
        }
        Assert-NoTicketboxReparsePoints $full
    }
    return $full
}
