#Requires -Version 5.1

<#
.SYNOPSIS
  Recovers a bounded PostgreSQL bootstrap-superuser authority for C07 upgrades.
.DESCRIPTION
  Existing bundled installations deliberately discard the postgres bootstrap
  password.  This helper briefly maps the exact elevated Windows caller to only
  the postgres role through SSPI on IPv4 loopback, rotates postgres to a
  protected one-shot SCRAM credential, restores pg_hba.conf/pg_ident.conf
  byte-for-byte, and only then invokes the caller's bounded action.

  The recovery artifact is also the sole libpq passfile holding the one-shot
  secret.  It is SYSTEM-owned, Administrators-only, crash durable, and contains
  the exact original authentication files needed to converge every retry.
#>

$script:TicketboxC07SuperuserRecoverySchema =
    "ticketbox-c07-superuser-recovery-v1"
$script:TicketboxC07SuperuserRecoveryArtifactName =
    "c07-superuser-recovery.pgpass"
$script:TicketboxC07SuperuserRecoveryAccounts =
    @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxC07SuperuserRecoveryOwner = "SYSTEM"
$script:TicketboxC07SuperuserRecoveryMaximumArtifactBytes = 1048576
$script:TicketboxC07SuperuserRecoveryMaximumAuthFileBytes = 262144
$script:TicketboxC07SuperuserRecoveryStages = @(
    "captured",
    "sspi_ident_published",
    "sspi_hba_published",
    "credential_rotated",
    "auth_files_restored",
    "action_running",
    "action_succeeded",
    "password_cleared",
    "completed"
)
$script:TicketboxC07SuperuserRecoveryFields = @(
    "schema",
    "operation_id",
    "stage",
    "cluster_system_identifier",
    "pg_data",
    "port",
    "postgresql_conf_sha256",
    "postgresql_auto_conf_sha256",
    "pg_version_sha256",
    "hba_path",
    "hba_original_sha256",
    "hba_original_bytes",
    "hba_security_descriptor",
    "hba_temporary_sha256",
    "ident_path",
    "ident_original_sha256",
    "ident_original_bytes",
    "ident_security_descriptor",
    "ident_temporary_sha256",
    "principal_name",
    "principal_sid",
    "sspi_system_username",
    "sspi_realm",
    "map_name",
    "created_at_utc",
    "action_attempt",
    "scram_salt"
)

function Assert-TicketboxC07SuperuserRecoveryDependencies {
    foreach ($commandName in @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "Assert-TicketboxProtectedDirectoryAcl",
        "ConvertTo-TicketboxCanonicalPath",
        "ConvertTo-TicketboxC07ScramVerifier",
        "Get-TicketboxPathEntryKindNoFollow",
        "Invoke-TicketboxBoundedNativeProcess",
        "New-TicketboxProtectedFileStream",
        "Read-TicketboxProtectedUtf8Artifact",
        "Replace-TicketboxFileDurablePreservingMetadata",
        "Remove-TicketboxProtectedUtf8Artifact",
        "Sync-TicketboxFileDurable",
        "Test-TicketboxByteArrayEquals",
        "Test-TicketboxPathEquals",
        "Write-TicketboxProtectedUtf8FileDurable"
    )) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "C07 superuser recovery 缺少受信依赖：$commandName"
        }
    }
}

function Initialize-TicketboxC07SuperuserRecoverySecurityPrivilegeMethods {
    if ("TicketboxC07SecurityPrivilegeScope" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxC07Luid
{
    internal uint LowPart;
    internal int HighPart;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxC07LuidAndAttributes
{
    internal TicketboxC07Luid Luid;
    internal uint Attributes;
}

[StructLayout(LayoutKind.Sequential)]
internal struct TicketboxC07TokenPrivileges
{
    internal uint PrivilegeCount;
    internal TicketboxC07LuidAndAttributes Privileges;
}

public sealed class TicketboxC07SecurityPrivilegeScope : IDisposable
{
    private const uint TokenQuery = 0x0008;
    private const uint TokenAdjustPrivileges = 0x0020;
    private const uint PrivilegeEnabled = 0x00000002;
    private const int ErrorNotAllAssigned = 1300;
    private IntPtr tokenHandle;
    private TicketboxC07TokenPrivileges previousState;
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
        out TicketboxC07Luid luid);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr tokenHandle,
        [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TicketboxC07TokenPrivileges newState,
        int bufferLength,
        out TicketboxC07TokenPrivileges previousState,
        out int returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AdjustTokenPrivileges(
        IntPtr tokenHandle,
        [MarshalAs(UnmanagedType.Bool)] bool disableAllPrivileges,
        ref TicketboxC07TokenPrivileges newState,
        int bufferLength,
        IntPtr previousState,
        IntPtr returnLength);

    private TicketboxC07SecurityPrivilegeScope(IntPtr handle)
    {
        tokenHandle = handle;
    }

    public static TicketboxC07SecurityPrivilegeScope Enter()
    {
        IntPtr handle;
        if (!OpenProcessToken(
            GetCurrentProcess(),
            TokenQuery | TokenAdjustPrivileges,
            out handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        TicketboxC07SecurityPrivilegeScope scope =
            new TicketboxC07SecurityPrivilegeScope(handle);
        try
        {
            TicketboxC07Luid luid;
            if (!LookupPrivilegeValue(null, "SeSecurityPrivilege", out luid))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            TicketboxC07TokenPrivileges requested =
                new TicketboxC07TokenPrivileges();
            requested.PrivilegeCount = 1;
            requested.Privileges = new TicketboxC07LuidAndAttributes
            {
                Luid = luid,
                Attributes = PrivilegeEnabled
            };
            int returnLength;
            bool adjusted = AdjustTokenPrivileges(
                handle,
                false,
                ref requested,
                Marshal.SizeOf(typeof(TicketboxC07TokenPrivileges)),
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
            if (!AdjustTokenPrivileges(
                tokenHandle,
                false,
                ref previousState,
                0,
                IntPtr.Zero,
                IntPtr.Zero))
            {
                restoreFailure =
                    new Win32Exception(Marshal.GetLastWin32Error());
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

function Enter-TicketboxC07SuperuserRecoverySecurityPrivilege {
    Initialize-TicketboxC07SuperuserRecoverySecurityPrivilegeMethods
    try {
        return [TicketboxC07SecurityPrivilegeScope]::Enter()
    }
    catch {
        throw (
            "C07 PostgreSQL auth-file SACL authority 不可用；" +
            "拒绝在未启用 SeSecurityPrivilege 时读取或替换。" +
            $_.Exception.GetBaseException().Message
        )
    }
}

function Get-TicketboxC07SuperuserRecoverySha256 {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString(
            $sha.ComputeHash($Bytes)
        ).Replace("-", "").ToUpperInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-TicketboxC07SuperuserRecoveryFileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return Get-TicketboxC07SuperuserRecoverySha256 (
        [System.IO.File]::ReadAllBytes($Path)
    )
}

function ConvertTo-TicketboxC07SuperuserRecoveryBase64 {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    $bytes = (New-Object Text.UTF8Encoding($false, $true)).GetBytes($Value)
    return [Convert]::ToBase64String($bytes)
}

function ConvertFrom-TicketboxC07SuperuserRecoveryBase64 {
    param(
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    try {
        $bytes = [Convert]::FromBase64String($Value)
        if ([Convert]::ToBase64String($bytes) -cne $Value) {
            throw "non-canonical"
        }
        return (New-Object Text.UTF8Encoding($false, $true)).GetString($bytes)
    }
    catch {
        throw "$Label 不是 canonical UTF-8 base64。"
    }
}

function Assert-TicketboxC07SuperuserRecoverySha256 {
    param(
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowMissing
    )

    if ($AllowMissing -and $Value -ceq "MISSING") {
        return
    }
    if ($Value -cnotmatch '^[0-9A-F]{64}$') {
        throw "$Label 不是 canonical host SHA-256。"
    }
}

function Assert-TicketboxC07SuperuserRecoveryArtifactPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (
        [System.IO.Path]::GetFileName($fullPath) -cne
            $script:TicketboxC07SuperuserRecoveryArtifactName
    ) {
        throw "C07 superuser recovery artifact 必须使用登记的精确文件名。"
    }
    $parent = Split-Path -Parent $fullPath
    Assert-NoTicketboxAncestorReparsePoints $parent
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $parent `
        -FullControlAccounts $script:TicketboxC07SuperuserRecoveryAccounts `
        -OwnerAccount $script:TicketboxC07SuperuserRecoveryOwner
    return $fullPath
}

function Get-TicketboxC07SuperuserRecoveryFileSecurityBytes {
    param([Parameter(Mandatory = $true)][string]$Path)

    $privilege = Enter-TicketboxC07SuperuserRecoverySecurityPrivilege
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        $sections = [Security.AccessControl.AccessControlSections]::All
        if ($PSVersionTable.PSEdition -eq "Core") {
            $security = [System.IO.FileSystemAclExtensions]::GetAccessControl(
                $item,
                $sections
            )
        }
        else {
            $security = $item.GetAccessControl($sections)
        }
        return $security.GetSecurityDescriptorBinaryForm()
    }
    finally {
        $privilege.Dispose()
    }
}

function New-TicketboxC07SuperuserRecoveryCreationSecurity {
    param([Parameter(Mandatory = $true)][byte[]]$SecurityBytes)

    $captured = New-Object Security.AccessControl.FileSecurity
    try {
        $captured.SetSecurityDescriptorBinaryForm($SecurityBytes)
        $sections =
            [Security.AccessControl.AccessControlSections]::Access -bor
            [Security.AccessControl.AccessControlSections]::Owner -bor
            [Security.AccessControl.AccessControlSections]::Group
        $creation = New-Object Security.AccessControl.FileSecurity
        $creation.SetSecurityDescriptorSddlForm(
            $captured.GetSecurityDescriptorSddlForm($sections),
            $sections
        )
        return $creation
    }
    catch {
        throw "C07 PostgreSQL auth-file captured security descriptor 无效。"
    }
}

function Get-TicketboxC07SuperuserRecoveryAuthFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    Assert-NoTicketboxAncestorReparsePoints $fullPath
    if ((Get-TicketboxPathEntryKindNoFollow $fullPath) -cne "File") {
        throw "$Label 不是受管普通文件。"
    }
    $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    if (
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.Length -gt
            $script:TicketboxC07SuperuserRecoveryMaximumAuthFileBytes
    ) {
        throw "$Label 的文件类型或大小越界。"
    }
    $bytes = [IO.File]::ReadAllBytes($fullPath)
    return [pscustomobject]@{
        Path = $fullPath
        Bytes = $bytes
        Sha256 = Get-TicketboxC07SuperuserRecoverySha256 $bytes
        SecurityBytes =
            Get-TicketboxC07SuperuserRecoveryFileSecurityBytes $fullPath
    }
}

function Join-TicketboxC07SuperuserRecoveryPrefix {
    param(
        [Parameter(Mandatory = $true)][byte[]]$OriginalBytes,
        [Parameter(Mandatory = $true)][string]$Line,
        [AllowNull()][Text.Encoding]$Encoding = $null
    )

    if ($Line.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw "C07 临时 PostgreSQL auth record 含非法控制字符。"
    }
    if (
        $OriginalBytes.Length -ge 2 -and
        (
            ($OriginalBytes[0] -eq 0xFF -and $OriginalBytes[1] -eq 0xFE) -or
            ($OriginalBytes[0] -eq 0xFE -and $OriginalBytes[1] -eq 0xFF)
        )
    ) {
        throw "C07 PostgreSQL auth file 不接受 UTF-16。"
    }
    if ($null -eq $Encoding) {
        $Encoding = New-Object Text.UTF8Encoding($false, $true)
    }
    $prefix = $Encoding.GetBytes($Line + "`r`n")
    $bomLength = 0
    if (
        $OriginalBytes.Length -ge 3 -and
        $OriginalBytes[0] -eq 0xEF -and
        $OriginalBytes[1] -eq 0xBB -and
        $OriginalBytes[2] -eq 0xBF
    ) {
        $bomLength = 3
    }
    $combined = New-Object byte[] ($OriginalBytes.Length + $prefix.Length)
    if ($bomLength -gt 0) {
        [Array]::Copy($OriginalBytes, 0, $combined, 0, $bomLength)
    }
    [Array]::Copy($prefix, 0, $combined, $bomLength, $prefix.Length)
    [Array]::Copy(
        $OriginalBytes,
        $bomLength,
        $combined,
        $bomLength + $prefix.Length,
        $OriginalBytes.Length - $bomLength
    )
    return $combined
}

function Get-TicketboxC07SuperuserRecoveryWindowsAnsiEncoding {
    $codePage =
        [Globalization.CultureInfo]::CurrentCulture.TextInfo.ANSICodePage
    if ($codePage -lt 1) {
        throw "C07 无法确定 Windows ANSI code page。"
    }
    try {
        return [Text.Encoding]::GetEncoding(
            $codePage,
            [Text.EncoderFallback]::ExceptionFallback,
            [Text.DecoderFallback]::ExceptionFallback
        )
    }
    catch {
        throw "C07 当前 Windows principal 无法按 PostgreSQL SSPI code page 编码。"
    }
}

function ConvertTo-TicketboxC07SuperuserRecoveryQuotedToken {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    if ($Value.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw "PostgreSQL auth token 含非法控制字符。"
    }
    return '"' + $Value.Replace('"', '""') + '"'
}

function Get-TicketboxC07SuperuserRecoveryPrincipal {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($null -eq $identity.User) {
        throw "Windows 未提供当前调用者 SID。"
    }
    $sid = $identity.User.Value
    $translated = $identity.User.Translate(
        [Security.Principal.NTAccount]
    ).Value
    $separator = $translated.IndexOf("\", [StringComparison]::Ordinal)
    if (
        $separator -le 0 -or
        $separator -ge ($translated.Length - 1) -or
        $translated.IndexOf("\", $separator + 1) -ge 0
    ) {
        throw "当前 Windows principal 不是唯一 DOMAIN\\account 形式。"
    }
    $realm = $translated.Substring(0, $separator)
    $account = $translated.Substring($separator + 1)
    foreach ($value in @($translated, $realm, $account)) {
        if (
            [string]::IsNullOrWhiteSpace($value) -or
            $value.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0
        ) {
            throw "当前 Windows principal 含非法字段。"
        }
    }
    return [pscustomobject]@{
        Name = $translated
        Sid = $sid
        Realm = $realm
        SystemUsername = "$account@$realm"
    }
}

function Invoke-TicketboxC07SuperuserRecoveryNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [AllowEmptyString()][string]$StandardInputText,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000,
        [AllowEmptyString()][string]$PgPassFile = ""
    )

    $saved = @{}
    foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
        if ($item.Name -match '^(?i)PG') {
            $saved[$item.Name] = [string]$item.Value
        }
    }
    try {
        foreach ($name in @($saved.Keys)) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        if (-not [string]::IsNullOrWhiteSpace($PgPassFile)) {
            $env:PGPASSFILE = [System.IO.Path]::GetFullPath($PgPassFile)
        }
        $parameters = @{
            FilePath = $FilePath
            Arguments = $Arguments
            TimeoutMilliseconds = $TimeoutMilliseconds
            Label = $Label
        }
        if ($PSBoundParameters.ContainsKey("StandardInputText")) {
            $parameters.StandardInputText = $StandardInputText
        }
        return Invoke-TicketboxBoundedNativeProcess @parameters
    }
    finally {
        foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
            if ($item.Name -match '^(?i)PG') {
                Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
            }
        }
        foreach ($entry in $saved.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable(
                [string]$entry.Key,
                [string]$entry.Value,
                "Process"
            )
        }
    }
}

function Get-TicketboxC07SuperuserRecoveryClusterSystemIdentifier {
    param([Parameter(Mandatory = $true)][object]$HostAuthority)

    $pgControlData = Join-Path (
        Split-Path -Parent ([string]$HostAuthority.PgCtlPath)
    ) "pg_controldata.exe"
    if ((Get-TicketboxPathEntryKindNoFollow $pgControlData) -cne "File") {
        throw "C07 superuser recovery 缺少受管 pg_controldata.exe。"
    }
    Assert-NoTicketboxAncestorReparsePoints $pgControlData
    $result = Invoke-TicketboxC07SuperuserRecoveryNative `
        -FilePath $pgControlData `
        -Arguments @("-D", [string]$HostAuthority.PgData) `
        -TimeoutMilliseconds 60000 `
        -Label "C07 pg_controldata cluster binding"
    if ($result.ExitCode -ne 0) {
        throw "C07 pg_controldata cluster binding 失败（exit=$($result.ExitCode)）。"
    }
    $lines = @(
        $result.StandardOutput -split "`r?`n" |
            ForEach-Object { [string]$_ } |
            Where-Object { $_.Trim().Length -gt 0 }
    )
    if ($lines.Count -lt 3) {
        throw "C07 pg_controldata 未返回完整 cluster identity。"
    }
    $separator = $lines[2].LastIndexOf(":")
    if (
        $separator -lt 0 -or
        $lines[2].Substring($separator + 1).Trim() -cnotmatch '^[0-9]{16,20}$'
    ) {
        throw "C07 pg_controldata cluster system identifier 格式无效。"
    }
    return $lines[2].Substring($separator + 1).Trim()
}

function Get-TicketboxC07SuperuserRecoveryOptionalFileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $kind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($kind -ceq "Missing") {
        return "MISSING"
    }
    if ($kind -cne "File") {
        throw "C07 cluster config 不是普通文件：$Path"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    return Get-TicketboxC07SuperuserRecoveryFileSha256 $Path
}

function Resolve-TicketboxC07SuperuserRecoveryHost {
    param([Parameter(Mandatory = $true)][object]$HostAuthority)

    if (
        [string]$HostAuthority.Schema -cne
            "ticketbox-c07-host-db-authority-v1"
    ) {
        throw "C07 superuser recovery host authority schema 无效。"
    }
    $pgData = ConvertTo-TicketboxCanonicalPath ([string]$HostAuthority.PgData)
    Assert-NoTicketboxAncestorReparsePoints $pgData
    if ((Get-TicketboxPathEntryKindNoFollow $pgData) -cne "Directory") {
        throw "C07 superuser recovery PGDATA 不是普通目录。"
    }
    $port = [int]$HostAuthority.Port
    if ($port -lt 1 -or $port -gt 65535) {
        throw "C07 superuser recovery PostgreSQL port 无效。"
    }
    $psql = [System.IO.Path]::GetFullPath([string]$HostAuthority.PsqlPath)
    $pgCtl = [System.IO.Path]::GetFullPath([string]$HostAuthority.PgCtlPath)
    foreach ($tool in @($psql, $pgCtl)) {
        Assert-NoTicketboxAncestorReparsePoints $tool
        if ((Get-TicketboxPathEntryKindNoFollow $tool) -cne "File") {
            throw "C07 superuser recovery 受管 PostgreSQL 工具缺失。"
        }
    }
    $hba = Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path (Join-Path $pgData "pg_hba.conf") `
        -Label "pg_hba.conf"
    $ident = Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path (Join-Path $pgData "pg_ident.conf") `
        -Label "pg_ident.conf"
    $postgresqlConf = Join-Path $pgData "postgresql.conf"
    $pgVersion = Join-Path $pgData "PG_VERSION"
    foreach ($required in @($postgresqlConf, $pgVersion)) {
        if ((Get-TicketboxPathEntryKindNoFollow $required) -cne "File") {
            throw "C07 cluster binding 缺少受管 config：$required"
        }
        Assert-NoTicketboxAncestorReparsePoints $required
    }
    return [pscustomobject]@{
        Schema = "ticketbox-c07-superuser-recovery-host-v1"
        PgData = $pgData
        Port = $port
        PsqlPath = $psql
        PgCtlPath = $pgCtl
        ClusterSystemIdentifier =
            Get-TicketboxC07SuperuserRecoveryClusterSystemIdentifier `
                $HostAuthority
        PostgresqlConfSha256 =
            Get-TicketboxC07SuperuserRecoveryFileSha256 $postgresqlConf
        PostgresqlAutoConfSha256 =
            Get-TicketboxC07SuperuserRecoveryOptionalFileSha256 (
                Join-Path $pgData "postgresql.auto.conf"
            )
        PgVersionSha256 =
            Get-TicketboxC07SuperuserRecoveryFileSha256 $pgVersion
        Hba = $hba
        Ident = $ident
    }
}

function New-TicketboxC07SuperuserRecoverySecret {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes).
            TrimEnd([char[]]@([char]"=")).
            Replace("+", "-").
            Replace("/", "_")
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

function New-TicketboxC07SuperuserRecoverySalt {
    $bytes = New-Object byte[] 16
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes)
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

function Get-TicketboxC07SuperuserRecoveryTemporaryFiles {
    param(
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][byte[]]$HbaOriginal,
        [Parameter(Mandatory = $true)][byte[]]$IdentOriginal
    )

    $hbaLine =
        'host "postgres" "postgres" 127.0.0.1/32 sspi ' +
        'include_realm=1 compat_realm=1 upn_username=0 ' +
        "map=$($Artifact.map_name)"
    $identLine =
        "$($Artifact.map_name) " +
        (ConvertTo-TicketboxC07SuperuserRecoveryQuotedToken (
            [string]$Artifact.sspi_system_username
        )) +
        ' "postgres"'
    return [pscustomobject]@{
        HbaBytes = Join-TicketboxC07SuperuserRecoveryPrefix `
            -OriginalBytes $HbaOriginal `
            -Line $hbaLine
        IdentBytes = Join-TicketboxC07SuperuserRecoveryPrefix `
            -OriginalBytes $IdentOriginal `
            -Line $identLine `
            -Encoding (
                Get-TicketboxC07SuperuserRecoveryWindowsAnsiEncoding
            )
    }
}

function ConvertTo-TicketboxC07SuperuserRecoveryArtifactText {
    param([Parameter(Mandatory = $true)][object]$Artifact)

    $lines = @("# ticketbox-c07-superuser-recovery-v1")
    foreach ($field in $script:TicketboxC07SuperuserRecoveryFields) {
        $value = [string]$Artifact.$field
        $lines += "# $field=$(ConvertTo-TicketboxC07SuperuserRecoveryBase64 $value)"
    }
    if ([string]$Artifact.secret -cnotmatch '^[A-Za-z0-9_-]{64}$') {
        throw "C07 superuser recovery one-shot secret shape 无效。"
    }
    $lines += "127.0.0.1:$($Artifact.port):postgres:postgres:$($Artifact.secret)"
    return ($lines -join "`n") + "`n"
}

function Write-TicketboxC07SuperuserRecoveryArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Artifact
    )

    $fullPath = Assert-TicketboxC07SuperuserRecoveryArtifactPath $Path
    $text = ConvertTo-TicketboxC07SuperuserRecoveryArtifactText $Artifact
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $fullPath `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07SuperuserRecoveryAccounts `
        -OwnerAccount $script:TicketboxC07SuperuserRecoveryOwner `
        -ReplaceExisting:(Test-Path -LiteralPath $fullPath)
    return Read-TicketboxC07SuperuserRecoveryArtifact $fullPath
}

function Read-TicketboxC07SuperuserRecoveryArtifact {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = Assert-TicketboxC07SuperuserRecoveryArtifactPath $Path
    $protected = Read-TicketboxProtectedUtf8Artifact `
        -Path $fullPath `
        -FullControlAccounts $script:TicketboxC07SuperuserRecoveryAccounts `
        -OwnerAccount $script:TicketboxC07SuperuserRecoveryOwner `
        -MaximumBytes $script:TicketboxC07SuperuserRecoveryMaximumArtifactBytes
    if (
        -not $protected.Text.EndsWith("`n", [StringComparison]::Ordinal) -or
        $protected.Text.Contains("`r")
    ) {
        throw "C07 superuser recovery artifact 必须为 LF-only strict UTF-8。"
    }
    $lines = @($protected.Text.Split([char]"`n"))
    $expectedLineCount =
        1 + $script:TicketboxC07SuperuserRecoveryFields.Count + 1 + 1
    if (
        $lines.Count -ne $expectedLineCount -or
        $lines[0] -cne "# ticketbox-c07-superuser-recovery-v1" -or
        $lines[$lines.Count - 1] -cne ""
    ) {
        throw "C07 superuser recovery artifact 行结构无效。"
    }
    $values = [ordered]@{}
    for (
        $index = 0;
        $index -lt $script:TicketboxC07SuperuserRecoveryFields.Count;
        $index++
    ) {
        $field = $script:TicketboxC07SuperuserRecoveryFields[$index]
        $prefix = "# $field="
        $line = $lines[$index + 1]
        if (-not $line.StartsWith($prefix, [StringComparison]::Ordinal)) {
            throw "C07 superuser recovery artifact 字段顺序无效：$field"
        }
        $values[$field] =
            ConvertFrom-TicketboxC07SuperuserRecoveryBase64 `
                -Value $line.Substring($prefix.Length) `
                -Label $field
    }
    $port = 0
    $attempt = 0
    if (
        -not [int]::TryParse([string]$values.port, [ref]$port) -or
        $port -lt 1 -or
        $port -gt 65535 -or
        -not [int]::TryParse([string]$values.action_attempt, [ref]$attempt) -or
        $attempt -lt 0
    ) {
        throw "C07 superuser recovery artifact 数字字段无效。"
    }
    $passFields = @(
        $lines[$lines.Count - 2].Split([char]":")
    )
    if (
        $passFields.Count -ne 5 -or
        $passFields[0] -cne "127.0.0.1" -or
        $passFields[1] -cne [string]$port -or
        $passFields[2] -cne "postgres" -or
        $passFields[3] -cne "postgres" -or
        $passFields[4] -cnotmatch '^[A-Za-z0-9_-]{64}$'
    ) {
        throw "C07 superuser recovery artifact 的 sole pgpass record 无效。"
    }
    $result = [ordered]@{}
    foreach ($field in $script:TicketboxC07SuperuserRecoveryFields) {
        $result[$field] = [string]$values[$field]
    }
    $result.port = $port
    $result.action_attempt = $attempt
    $result.secret = $passFields[4]
    return [pscustomobject]$result
}

function New-TicketboxC07SuperuserRecoveryArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][object]$Principal
    )

    $operationId = [Guid]::NewGuid().ToString("D").ToLowerInvariant()
    $mapName = "ticketbox_c07_recover_" + $operationId.Replace("-", "")
    $prototype = [pscustomobject][ordered]@{
        schema = $script:TicketboxC07SuperuserRecoverySchema
        operation_id = $operationId
        stage = "captured"
        cluster_system_identifier = [string]$HostContext.ClusterSystemIdentifier
        pg_data = [string]$HostContext.PgData
        port = [int]$HostContext.Port
        postgresql_conf_sha256 = [string]$HostContext.PostgresqlConfSha256
        postgresql_auto_conf_sha256 =
            [string]$HostContext.PostgresqlAutoConfSha256
        pg_version_sha256 = [string]$HostContext.PgVersionSha256
        hba_path = [string]$HostContext.Hba.Path
        hba_original_sha256 = [string]$HostContext.Hba.Sha256
        hba_original_bytes = [Convert]::ToBase64String($HostContext.Hba.Bytes)
        hba_security_descriptor =
            [Convert]::ToBase64String($HostContext.Hba.SecurityBytes)
        hba_temporary_sha256 = ""
        ident_path = [string]$HostContext.Ident.Path
        ident_original_sha256 = [string]$HostContext.Ident.Sha256
        ident_original_bytes = [Convert]::ToBase64String($HostContext.Ident.Bytes)
        ident_security_descriptor =
            [Convert]::ToBase64String($HostContext.Ident.SecurityBytes)
        ident_temporary_sha256 = ""
        principal_name = [string]$Principal.Name
        principal_sid = [string]$Principal.Sid
        sspi_system_username = [string]$Principal.SystemUsername
        sspi_realm = [string]$Principal.Realm
        map_name = $mapName
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        action_attempt = 0
        scram_salt = New-TicketboxC07SuperuserRecoverySalt
        secret = New-TicketboxC07SuperuserRecoverySecret
    }
    $temporary = Get-TicketboxC07SuperuserRecoveryTemporaryFiles `
        -Artifact $prototype `
        -HbaOriginal $HostContext.Hba.Bytes `
        -IdentOriginal $HostContext.Ident.Bytes
    $prototype.hba_temporary_sha256 =
        Get-TicketboxC07SuperuserRecoverySha256 $temporary.HbaBytes
    $prototype.ident_temporary_sha256 =
        Get-TicketboxC07SuperuserRecoverySha256 $temporary.IdentBytes
    return $prototype
}

function ConvertFrom-TicketboxC07SuperuserRecoveryStoredBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1, 1048576)][int]$MaximumBytes = 262144
    )

    try {
        $bytes = [Convert]::FromBase64String($Value)
        if (
            $bytes.Length -gt $MaximumBytes -or
            [Convert]::ToBase64String($bytes) -cne $Value
        ) {
            throw "non-canonical"
        }
        return $bytes
    }
    catch {
        throw "$Label 不是 bounded canonical base64 bytes。"
    }
}

function Assert-TicketboxC07SuperuserRecoveryArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][object]$HostContext
    )

    if (
        [string]$Artifact.schema -cne
            $script:TicketboxC07SuperuserRecoverySchema -or
        [string]$Artifact.operation_id -cnotmatch
            '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
        [string]$Artifact.stage -cnotin
            $script:TicketboxC07SuperuserRecoveryStages -or
        [string]$Artifact.map_name -cne (
            "ticketbox_c07_recover_" +
            ([string]$Artifact.operation_id).Replace("-", "")
        )
    ) {
        throw "C07 superuser recovery artifact identity/stage 无效。"
    }
    if (
        [string]$Artifact.cluster_system_identifier -cne
            [string]$HostContext.ClusterSystemIdentifier -or
        -not (Test-TicketboxPathEquals (
            [string]$Artifact.pg_data
        ) ([string]$HostContext.PgData)) -or
        [int]$Artifact.port -ne [int]$HostContext.Port -or
        [string]$Artifact.postgresql_conf_sha256 -cne
            [string]$HostContext.PostgresqlConfSha256 -or
        [string]$Artifact.postgresql_auto_conf_sha256 -cne
            [string]$HostContext.PostgresqlAutoConfSha256 -or
        [string]$Artifact.pg_version_sha256 -cne
            [string]$HostContext.PgVersionSha256 -or
        -not (Test-TicketboxPathEquals (
            [string]$Artifact.hba_path
        ) ([string]$HostContext.Hba.Path)) -or
        -not (Test-TicketboxPathEquals (
            [string]$Artifact.ident_path
        ) ([string]$HostContext.Ident.Path))
    ) {
        throw "C07 superuser recovery artifact 与当前 cluster/config 不一致。"
    }
    foreach ($entry in @(
        @([string]$Artifact.postgresql_conf_sha256, "postgresql.conf", $false),
        @([string]$Artifact.postgresql_auto_conf_sha256, "postgresql.auto.conf", $true),
        @([string]$Artifact.pg_version_sha256, "PG_VERSION", $false),
        @([string]$Artifact.hba_original_sha256, "original pg_hba.conf", $false),
        @([string]$Artifact.hba_temporary_sha256, "temporary pg_hba.conf", $false),
        @([string]$Artifact.ident_original_sha256, "original pg_ident.conf", $false),
        @([string]$Artifact.ident_temporary_sha256, "temporary pg_ident.conf", $false)
    )) {
        Assert-TicketboxC07SuperuserRecoverySha256 `
            -Value $entry[0] `
            -Label $entry[1] `
            -AllowMissing:([bool]$entry[2])
    }
    if (
        [string]$Artifact.principal_sid -cnotmatch '^S-1-[0-9-]+$' -or
        [string]::IsNullOrWhiteSpace([string]$Artifact.principal_name) -or
        [string]::IsNullOrWhiteSpace([string]$Artifact.sspi_system_username) -or
        [string]::IsNullOrWhiteSpace([string]$Artifact.sspi_realm) -or
        [string]$Artifact.scram_salt -cnotmatch
            '^[A-Za-z0-9+/]{22}==$'
    ) {
        throw "C07 superuser recovery principal/SCRAM binding 无效。"
    }
    $hbaBytes = ConvertFrom-TicketboxC07SuperuserRecoveryStoredBytes `
        -Value ([string]$Artifact.hba_original_bytes) `
        -Label "stored pg_hba.conf"
    $identBytes = ConvertFrom-TicketboxC07SuperuserRecoveryStoredBytes `
        -Value ([string]$Artifact.ident_original_bytes) `
        -Label "stored pg_ident.conf"
    $hbaSecurity = ConvertFrom-TicketboxC07SuperuserRecoveryStoredBytes `
        -Value ([string]$Artifact.hba_security_descriptor) `
        -Label "stored pg_hba.conf security" `
        -MaximumBytes 65536
    $identSecurity = ConvertFrom-TicketboxC07SuperuserRecoveryStoredBytes `
        -Value ([string]$Artifact.ident_security_descriptor) `
        -Label "stored pg_ident.conf security" `
        -MaximumBytes 65536
    if (
        (Get-TicketboxC07SuperuserRecoverySha256 $hbaBytes) -cne
            [string]$Artifact.hba_original_sha256 -or
        (Get-TicketboxC07SuperuserRecoverySha256 $identBytes) -cne
            [string]$Artifact.ident_original_sha256
    ) {
        throw "C07 superuser recovery original auth bytes digest 不一致。"
    }
    $temporary = Get-TicketboxC07SuperuserRecoveryTemporaryFiles `
        -Artifact $Artifact `
        -HbaOriginal $hbaBytes `
        -IdentOriginal $identBytes
    if (
        (Get-TicketboxC07SuperuserRecoverySha256 $temporary.HbaBytes) -cne
            [string]$Artifact.hba_temporary_sha256 -or
        (Get-TicketboxC07SuperuserRecoverySha256 $temporary.IdentBytes) -cne
            [string]$Artifact.ident_temporary_sha256
    ) {
        throw "C07 superuser recovery temporary auth bytes digest 不一致。"
    }
    return [pscustomobject]@{
        HbaOriginalBytes = $hbaBytes
        HbaSecurityBytes = $hbaSecurity
        HbaTemporaryBytes = $temporary.HbaBytes
        IdentOriginalBytes = $identBytes
        IdentSecurityBytes = $identSecurity
        IdentTemporaryBytes = $temporary.IdentBytes
    }
}

function Test-TicketboxC07SuperuserRecoverySecurityEquals {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )

    if (Test-TicketboxByteArrayEquals -Left $Left -Right $Right) {
        return $true
    }

    try {
        # Windows may recompute DEFAULTED/automatic-inheritance provenance when
        # an ACL is reapplied. Normalize those flags, inherited provenance and
        # equivalent auto-inherited DACL mask splits only; identities, ACE type,
        # inheritance behavior, PRESENT/PROTECTED and the SACL stay authoritative.
        $ignoredFlags =
            [Security.AccessControl.ControlFlags]::OwnerDefaulted -bor
            [Security.AccessControl.ControlFlags]::GroupDefaulted -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::SystemAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInherited
        $ignoredMask = [int]$ignoredFlags
        $leftDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Left, 0)
        $rightDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Right, 0)
        $leftSecurity = New-Object Security.AccessControl.FileSecurity
        $rightSecurity = New-Object Security.AccessControl.FileSecurity
        $leftSecurity.SetSecurityDescriptorBinaryForm($Left)
        $rightSecurity.SetSecurityDescriptorBinaryForm($Right)
        if (
            -not $leftSecurity.AreAccessRulesCanonical -or
            -not $rightSecurity.AreAccessRulesCanonical -or
            -not $leftSecurity.AreAuditRulesCanonical -or
            -not $rightSecurity.AreAuditRulesCanonical
        ) {
            return $false
        }
        $leftFlags = [int]$leftDescriptor.ControlFlags -band (-bnot $ignoredMask)
        $rightFlags = [int]$rightDescriptor.ControlFlags -band (-bnot $ignoredMask)
        if (
            $leftFlags -ne $rightFlags -or
            -not $leftDescriptor.Owner.Equals($rightDescriptor.Owner) -or
            -not $leftDescriptor.Group.Equals($rightDescriptor.Group) -or
            $leftDescriptor.ResourceManagerControl -ne
                $rightDescriptor.ResourceManagerControl -or
            $leftDescriptor.Revision -ne $rightDescriptor.Revision
        ) {
            return $false
        }
        $normalizeDaclMasks = (
            ([int]$leftDescriptor.ControlFlags -bor
                [int]$rightDescriptor.ControlFlags) -band
                [int][Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
        ) -ne 0
        return (
            (Test-TicketboxC07SuperuserRecoveryRawAclEquals `
                -Left $leftDescriptor.DiscretionaryAcl `
                -Right $rightDescriptor.DiscretionaryAcl `
                -NormalizeInheritedProvenance `
                -NormalizeEquivalentQualifiedMasks:$normalizeDaclMasks) -and
            (Test-TicketboxC07SuperuserRecoveryRawAclEquals `
                -Left $leftDescriptor.SystemAcl `
                -Right $rightDescriptor.SystemAcl `
                -NormalizeInheritedProvenance)
        )
    }
    catch {
        return $false
    }
}

function Test-TicketboxC07SuperuserRecoveryRawAclEquals {
    param(
        [AllowNull()][object]$Left,
        [AllowNull()][object]$Right,
        [switch]$NormalizeInheritedProvenance,
        [switch]$NormalizeEquivalentQualifiedMasks
    )

    if ($null -eq $Left -or $null -eq $Right) {
        return $null -eq $Left -and $null -eq $Right
    }
    $aclBytes = @()
    foreach ($acl in @($Left, $Right)) {
        if ($NormalizeInheritedProvenance) {
            $aceFingerprints = @()
            $qualifiedMasks = @{}
            for ($index = 0; $index -lt $acl.Count; $index++) {
                $aceBytes = New-Object byte[] $acl[$index].BinaryLength
                $acl[$index].GetBinaryForm($aceBytes, 0)
                $ace = [Security.AccessControl.GenericAce]::CreateFromBinaryForm(
                    $aceBytes,
                    0
                )
                $ace.AceFlags = [Security.AccessControl.AceFlags](
                    [int]$ace.AceFlags -band
                        (-bnot [int][Security.AccessControl.AceFlags]::Inherited)
                )
                $accessMask = $null
                if (
                    $NormalizeEquivalentQualifiedMasks -and
                    $ace -is [Security.AccessControl.QualifiedAce]
                ) {
                    $accessMask = [int64]$ace.AccessMask -band 0xFFFFFFFFL
                    $ace.AccessMask = 0
                }
                $normalizedAceBytes = New-Object byte[] $ace.BinaryLength
                $ace.GetBinaryForm($normalizedAceBytes, 0)
                $fingerprint = [Convert]::ToBase64String($normalizedAceBytes)
                if ($null -eq $accessMask) {
                    $aceFingerprints += $fingerprint
                }
                else {
                    $qualifiedMasks[$fingerprint] =
                        [int64]$qualifiedMasks[$fingerprint] -bor $accessMask
                }
            }
            $aceFingerprints += @(
                $qualifiedMasks.GetEnumerator() | ForEach-Object {
                    "{0}:{1:X8}" -f $_.Key, [int64]$_.Value
                }
            )
            $canonicalAcl = (
                [string]$acl.Revision + ":" +
                (@($aceFingerprints | Sort-Object -CaseSensitive) -join ",")
            )
            $bytes = [Text.Encoding]::UTF8.GetBytes($canonicalAcl)
        }
        else {
            $bytes = New-Object byte[] $acl.BinaryLength
            $acl.GetBinaryForm($bytes, 0)
        }
        $aclBytes += ,$bytes
    }
    return Test-TicketboxByteArrayEquals `
        -Left $aclBytes[0] `
        -Right $aclBytes[1]
}

function Get-TicketboxC07SuperuserRecoverySecurityDifferenceDiagnostic {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )

    try {
        $leftDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Left, 0)
        $rightDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Right, 0)
        $leftFlags = [int]$leftDescriptor.ControlFlags -band 0xFFFF
        $rightFlags = [int]$rightDescriptor.ControlFlags -band 0xFFFF
        $flagsXor = ($leftFlags -bxor $rightFlags) -band 0xFFFF
        $daclFlags = [int](
            [Security.AccessControl.ControlFlags]::DiscretionaryAclPresent -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclUntrusted -bor
            [Security.AccessControl.ControlFlags]::ServerSecurity -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected
        )
        $saclFlags = [int](
            [Security.AccessControl.ControlFlags]::SystemAclPresent -bor
            [Security.AccessControl.ControlFlags]::SystemAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::SystemAclProtected
        )
        $ownerEqual = if (
            $null -eq $leftDescriptor.Owner -or
            $null -eq $rightDescriptor.Owner
        ) {
            $null -eq $leftDescriptor.Owner -and
                $null -eq $rightDescriptor.Owner
        }
        else {
            $leftDescriptor.Owner.Equals($rightDescriptor.Owner)
        }
        $groupEqual = if (
            $null -eq $leftDescriptor.Group -or
            $null -eq $rightDescriptor.Group
        ) {
            $null -eq $leftDescriptor.Group -and
                $null -eq $rightDescriptor.Group
        }
        else {
            $leftDescriptor.Group.Equals($rightDescriptor.Group)
        }
        $daclBinaryEqual =
            Test-TicketboxC07SuperuserRecoveryRawAclEquals `
                -Left $leftDescriptor.DiscretionaryAcl `
                -Right $rightDescriptor.DiscretionaryAcl
        $saclBinaryEqual =
            Test-TicketboxC07SuperuserRecoveryRawAclEquals `
                -Left $leftDescriptor.SystemAcl `
                -Right $rightDescriptor.SystemAcl
        $daclComponentEqual =
            ($flagsXor -band $daclFlags) -eq 0 -and $daclBinaryEqual
        $saclComponentEqual =
            ($flagsXor -band $saclFlags) -eq 0 -and $saclBinaryEqual
        $diagnosticFormat =
            "security_descriptor_diagnostic " +
            "control_flags_left=0x{0:X4} control_flags_right=0x{1:X4} " +
            "control_flags_xor=0x{2:X4} owner_equal={3} group_equal={4} " +
            "dacl_component_equal={5} dacl_binary_equal={6} " +
            "sacl_component_equal={7} sacl_binary_equal={8} " +
            "rm_control_equal={9} revision_equal={10}"
        return $diagnosticFormat -f @(
            $leftFlags,
            $rightFlags,
            $flagsXor,
            $ownerEqual.ToString().ToLowerInvariant(),
            $groupEqual.ToString().ToLowerInvariant(),
            $daclComponentEqual.ToString().ToLowerInvariant(),
            $daclBinaryEqual.ToString().ToLowerInvariant(),
            $saclComponentEqual.ToString().ToLowerInvariant(),
            $saclBinaryEqual.ToString().ToLowerInvariant(),
            ($leftDescriptor.ResourceManagerControl -eq
                $rightDescriptor.ResourceManagerControl).ToString().ToLowerInvariant(),
            ($leftDescriptor.Revision -eq
                $rightDescriptor.Revision).ToString().ToLowerInvariant()
        )
    }
    catch {
        return (
            "security_descriptor_diagnostic control_flags_left=unavailable " +
            "control_flags_right=unavailable control_flags_xor=unavailable " +
            "owner_equal=unavailable group_equal=unavailable " +
            "dacl_component_equal=unavailable dacl_binary_equal=unavailable " +
            "sacl_component_equal=unavailable sacl_binary_equal=unavailable " +
            "rm_control_equal=unavailable revision_equal=unavailable"
        )
    }
}

function Get-TicketboxC07SuperuserRecoveryCreationSecuritySddl {
    param([Parameter(Mandatory = $true)][byte[]]$SecurityBytes)

    $security = New-Object Security.AccessControl.FileSecurity
    try {
        $security.SetSecurityDescriptorBinaryForm($SecurityBytes)
        $sections =
            [Security.AccessControl.AccessControlSections]::Access -bor
            [Security.AccessControl.AccessControlSections]::Owner -bor
            [Security.AccessControl.AccessControlSections]::Group
        return $security.GetSecurityDescriptorSddlForm($sections)
    }
    catch {
        throw "C07 auth-file sidecar security descriptor 无效。"
    }
}

function Get-TicketboxC07SuperuserRecoveryAuthCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $kind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($kind -ceq "Missing") {
        return $null
    }
    if ($kind -cne "File") {
        throw "$Label 不是 missing/plain-file。"
    }
    return Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $Path `
        -Label $Label
}

function Assert-TicketboxC07SuperuserRecoveryReplacementCandidate {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][byte[]]$ExpectedSecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ([string]$Candidate.Sha256 -cne $ExpectedSha256) {
        throw "$Label bytes 不属于当前 deterministic replacement。"
    }
    $candidateSddl =
        Get-TicketboxC07SuperuserRecoveryCreationSecuritySddl `
            $Candidate.SecurityBytes
    $expectedSddl =
        Get-TicketboxC07SuperuserRecoveryCreationSecuritySddl `
            $ExpectedSecurityBytes
    if ($candidateSddl -cne $expectedSddl) {
        throw "$Label owner/group/DACL 已漂移。"
    }
}

function Set-TicketboxC07SuperuserRecoveryFileSecurityBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$SecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $security = New-Object Security.AccessControl.FileSecurity
    try {
        $security.SetSecurityDescriptorBinaryForm($SecurityBytes)
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if ($PSVersionTable.PSEdition -eq "Core") {
            [System.IO.FileSystemAclExtensions]::SetAccessControl(
                $item,
                $security
            )
        }
        else {
            $item.SetAccessControl($security)
        }
    }
    catch {
        throw "$Label 无法恢复 captured full security descriptor。"
    }
    $persistedSecurity =
        Get-TicketboxC07SuperuserRecoveryFileSecurityBytes $Path
    if (-not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
        -Left $persistedSecurity `
        -Right $SecurityBytes)) {
        $securityDiagnostic =
            Get-TicketboxC07SuperuserRecoverySecurityDifferenceDiagnostic `
                -Left $persistedSecurity `
                -Right $SecurityBytes
        throw (
            "$Label full security descriptor 复读不一致。 " +
            $securityDiagnostic
        )
    }
    Sync-TicketboxFileDurable $Path
}

function Complete-TicketboxC07SuperuserRecoveryReplacementCandidate {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][byte[]]$ExpectedSecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-TicketboxC07SuperuserRecoveryReplacementCandidate `
        -Candidate $Candidate `
        -ExpectedSha256 $ExpectedSha256 `
        -ExpectedSecurityBytes $ExpectedSecurityBytes `
        -Label $Label
    if (-not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
        -Left $Candidate.SecurityBytes `
        -Right $ExpectedSecurityBytes)) {
        Set-TicketboxC07SuperuserRecoveryFileSecurityBytes `
            -Path $Path `
            -SecurityBytes $ExpectedSecurityBytes `
            -Label $Label
        $Candidate = Get-TicketboxC07SuperuserRecoveryAuthFile `
            -Path $Path `
            -Label $Label
    }
    if (
        [string]$Candidate.Sha256 -cne $ExpectedSha256 -or
        -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
            -Left $Candidate.SecurityBytes `
            -Right $ExpectedSecurityBytes)
    ) {
        throw "$Label 未收敛到 exact bytes/full security descriptor。"
    }
    return $Candidate
}

function Assert-TicketboxC07SuperuserRecoveryBackupCandidate {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][string]$PreviousSha256,
        [Parameter(Mandatory = $true)][byte[]]$ExpectedSecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (
        [string]$Candidate.Sha256 -cne $PreviousSha256 -or
        -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
            -Left $Candidate.SecurityBytes `
            -Right $ExpectedSecurityBytes)
    ) {
        throw "$Label 不是 exact previous auth-file authority。"
    }
}

function Assert-TicketboxC07SuperuserRecoveryDestinationCandidate {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][string[]]$AllowedSha256,
        [Parameter(Mandatory = $true)][byte[]]$ExpectedSecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (
        [string]$Candidate.Sha256 -cnotin $AllowedSha256 -or
        -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
            -Left $Candidate.SecurityBytes `
            -Right $ExpectedSecurityBytes)
    ) {
        throw "$Label bytes/security descriptor 不属于 captured authority。"
    }
}

function Restore-TicketboxC07SuperuserRecoveryBackupDestination {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$PreviousSha256,
        [Parameter(Mandatory = $true)][byte[]]$ExpectedSecurityBytes,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$ReplaceExisting
    )

    Move-TicketboxFileDurable `
        -Source $BackupPath `
        -Destination $DestinationPath `
        -ReplaceExisting:$ReplaceExisting
    $restored = Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path $DestinationPath `
        -Label "$Label restored previous destination"
    Assert-TicketboxC07SuperuserRecoveryDestinationCandidate `
        -Candidate $restored `
        -AllowedSha256 @($PreviousSha256) `
        -ExpectedSecurityBytes $ExpectedSecurityBytes `
        -Label "$Label restored previous destination"
    Sync-TicketboxFileDurable $DestinationPath
}

function Remove-TicketboxC07SuperuserRecoveryReconciledSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ((Get-TicketboxPathEntryKindNoFollow $Path) -ceq "Missing") {
        return
    }
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "File") {
        throw "$Label cleanup target 不是普通文件。"
    }
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "Missing") {
        throw "$Label 无法在已验证 destination 后清理。"
    }
}

function Get-TicketboxC07SuperuserRecoveryAuthState {
    param(
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][object]$Material
    )

    $hba = Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path ([string]$Artifact.hba_path) `
        -Label "live pg_hba.conf"
    $ident = Get-TicketboxC07SuperuserRecoveryAuthFile `
        -Path ([string]$Artifact.ident_path) `
        -Label "live pg_ident.conf"
    $hbaKind = if (
        $hba.Sha256 -ceq [string]$Artifact.hba_original_sha256
    ) {
        "original"
    }
    elseif ($hba.Sha256 -ceq [string]$Artifact.hba_temporary_sha256) {
        "temporary"
    }
    else {
        throw "live pg_hba.conf 既非 captured original 也非 exact temporary。"
    }
    $identKind = if (
        $ident.Sha256 -ceq [string]$Artifact.ident_original_sha256
    ) {
        "original"
    }
    elseif ($ident.Sha256 -ceq [string]$Artifact.ident_temporary_sha256) {
        "temporary"
    }
    else {
        throw "live pg_ident.conf 既非 captured original 也非 exact temporary。"
    }
    if (
        -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
            -Left $hba.SecurityBytes `
            -Right $Material.HbaSecurityBytes) -or
        -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
            -Left $ident.SecurityBytes `
            -Right $Material.IdentSecurityBytes)
    ) {
        throw "C07 PostgreSQL auth file security descriptor 已偏离 captured authority。"
    }
    return [pscustomobject]@{
        Hba = $hbaKind
        Ident = $identKind
    }
}

function Write-TicketboxC07SuperuserRecoveryAuthFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][byte[]]$SecurityBytes,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$PreviousSha256,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-TicketboxC07SuperuserRecoverySha256 `
        -Value $ExpectedSha256 `
        -Label "$Label expected"
    Assert-TicketboxC07SuperuserRecoverySha256 `
        -Value $PreviousSha256 `
        -Label "$Label previous"
    if (
        $ExpectedSha256 -ceq $PreviousSha256 -or
        (Get-TicketboxC07SuperuserRecoverySha256 $Bytes) -cne
            $ExpectedSha256
    ) {
        throw "$Label replacement/previous digest contract 无效。"
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    Assert-NoTicketboxAncestorReparsePoints $parent
    $security = New-TicketboxC07SuperuserRecoveryCreationSecurity `
        $SecurityBytes
    $leaf = [IO.Path]::GetFileName($fullPath)
    $replacementPath = Join-Path `
        $parent `
        (".{0}.ticketbox-c07-replacement" -f $leaf)
    $stagingPath = Join-Path `
        $parent `
        (".{0}.ticketbox-c07-replacement-staging" -f $leaf)
    $backupPath = Join-Path `
        $parent `
        (".{0}.ticketbox-c07-backup" -f $leaf)
    $privilege = Enter-TicketboxC07SuperuserRecoverySecurityPrivilege
    try {
        $destination = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $fullPath `
            -Label "$Label destination"
        if ($null -ne $destination) {
            if ([string]$destination.Sha256 -cnotin @(
                $PreviousSha256,
                $ExpectedSha256
            )) {
                throw "$Label destination bytes 不属于 captured authority。"
            }
        }

        # A crash may occur after ReplaceFileW committed but before sidecar
        # cleanup.  Exact destination bytes + the complete captured security
        # descriptor are the only completion authority.
        if (
            $null -ne $destination -and
            [string]$destination.Sha256 -ceq $ExpectedSha256 -and
            (Test-TicketboxC07SuperuserRecoverySecurityEquals `
                -Left $destination.SecurityBytes `
                -Right $SecurityBytes)
        ) {
            Sync-TicketboxFileDurable $fullPath
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $replacementPath `
                -Label "$Label deterministic replacement"
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $stagingPath `
                -Label "$Label deterministic replacement staging"
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $backupPath `
                -Label "$Label deterministic backup"
            return
        }

        $replacement = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $replacementPath `
            -Label "$Label deterministic replacement"
        $staging = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $stagingPath `
            -Label "$Label deterministic replacement staging"
        $backup = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $backupPath `
            -Label "$Label deterministic backup"
        if ($null -ne $backup) {
            Assert-TicketboxC07SuperuserRecoveryBackupCandidate `
                -Candidate $backup `
                -PreviousSha256 $PreviousSha256 `
                -ExpectedSecurityBytes $SecurityBytes `
                -Label "$Label deterministic backup"
        }

        # ReplaceFileW may have published the desired bytes without preserving
        # the complete captured descriptor.  A verified backup is the only
        # authority allowed to repair that state; retain every other sidecar.
        if (
            $null -ne $destination -and
            -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
                -Left $destination.SecurityBytes `
                -Right $SecurityBytes)
        ) {
            if ($null -ne $backup) {
                Restore-TicketboxC07SuperuserRecoveryBackupDestination `
                    -BackupPath $backupPath `
                    -DestinationPath $fullPath `
                    -PreviousSha256 $PreviousSha256 `
                    -ExpectedSecurityBytes $SecurityBytes `
                    -Label $Label `
                    -ReplaceExisting
                throw (
                    "$Label recovered a descriptor-drift ReplaceFileW state; " +
                    "retry is required."
                )
            }
            throw "$Label destination full security descriptor 已漂移。"
        }

        $replacementFailure = $null
        if ($null -ne $replacement) {
            try {
                $replacement =
                    Complete-TicketboxC07SuperuserRecoveryReplacementCandidate `
                        -Candidate $replacement `
                        -Path $replacementPath `
                        -ExpectedSha256 $ExpectedSha256 `
                        -ExpectedSecurityBytes $SecurityBytes `
                        -Label "$Label deterministic replacement"
            }
            catch {
                $replacementFailure = $_.Exception
            }
        }

        # ERROR_UNABLE_TO_MOVE_REPLACEMENT_2 (1177), or a crash in that
        # window, leaves the old destination at Backup and the new bytes at
        # Replacement while Destination is absent.  Promote only when the
        # replacement already has the exact full descriptor; otherwise restore
        # the verified backup and retain the desired replacement for retry.
        if ($null -eq $destination) {
            if ($null -ne $backup) {
                if ($null -ne $replacement -and $null -eq $replacementFailure) {
                    Move-TicketboxFileDurable `
                        -Source $replacementPath `
                        -Destination $fullPath
                    $persisted = Get-TicketboxC07SuperuserRecoveryAuthFile `
                        -Path $fullPath `
                        -Label $Label
                    Assert-TicketboxC07SuperuserRecoveryDestinationCandidate `
                        -Candidate $persisted `
                        -AllowedSha256 @($ExpectedSha256) `
                        -ExpectedSecurityBytes $SecurityBytes `
                        -Label $Label
                    Sync-TicketboxFileDurable $fullPath
                    Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                        -Path $stagingPath `
                        -Label "$Label deterministic replacement staging"
                    Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                        -Path $backupPath `
                        -Label "$Label deterministic backup"
                    return
                }
                Restore-TicketboxC07SuperuserRecoveryBackupDestination `
                    -BackupPath $backupPath `
                    -DestinationPath $fullPath `
                    -PreviousSha256 $PreviousSha256 `
                    -ExpectedSecurityBytes $SecurityBytes `
                    -Label $Label
                throw "$Label recovered a partial ReplaceFileW state; retry is required."
            }
            if ($null -ne $replacement -and $null -eq $replacementFailure) {
                Move-TicketboxFileDurable `
                    -Source $replacementPath `
                    -Destination $fullPath
                $persisted = Get-TicketboxC07SuperuserRecoveryAuthFile `
                    -Path $fullPath `
                    -Label $Label
                Assert-TicketboxC07SuperuserRecoveryDestinationCandidate `
                    -Candidate $persisted `
                    -AllowedSha256 @($ExpectedSha256) `
                        -ExpectedSecurityBytes $SecurityBytes `
                        -Label $Label
                Sync-TicketboxFileDurable $fullPath
                Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                    -Path $stagingPath `
                    -Label "$Label deterministic replacement staging"
                return
            }
            throw "$Label destination 缺失，且没有可安全提升或恢复的 exact copy。"
        }

        if ($null -ne $backup) {
            throw "$Label 存在未收敛的 deterministic backup；拒绝覆盖或猜测。"
        }
        if ($null -ne $replacementFailure) {
            # The live destination is the exact previous bytes/full descriptor
            # and no backup exists, so an incomplete deterministic replacement
            # is only unpublished staging and is safe to rebuild.
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $replacementPath `
                -Label "$Label incomplete deterministic replacement"
            $replacement = $null
            $replacementFailure = $null
        }
        if ($null -eq $replacement) {
            $stagingFailure = $null
            if ($null -ne $staging) {
                try {
                    $staging =
                        Complete-TicketboxC07SuperuserRecoveryReplacementCandidate `
                            -Candidate $staging `
                            -Path $stagingPath `
                            -ExpectedSha256 $ExpectedSha256 `
                            -ExpectedSecurityBytes $SecurityBytes `
                            -Label "$Label deterministic replacement staging"
                }
                catch {
                    $stagingFailure = $_.Exception
                }
            }
            if ($null -ne $stagingFailure) {
                Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                    -Path $stagingPath `
                    -Label "$Label incomplete replacement staging"
                $staging = $null
            }
            if ($null -eq $staging) {
                $stream = New-TicketboxProtectedFileStream `
                    -Path $stagingPath `
                    -Security $security
                try {
                    $stream.Write($Bytes, 0, $Bytes.Length)
                    $stream.Flush($true)
                }
                finally {
                    $stream.Dispose()
                }
                $staging = Get-TicketboxC07SuperuserRecoveryAuthFile `
                    -Path $stagingPath `
                    -Label "$Label deterministic replacement staging"
                $staging =
                    Complete-TicketboxC07SuperuserRecoveryReplacementCandidate `
                        -Candidate $staging `
                        -Path $stagingPath `
                        -ExpectedSha256 $ExpectedSha256 `
                        -ExpectedSecurityBytes $SecurityBytes `
                        -Label "$Label deterministic replacement staging"
            }
            Move-TicketboxFileDurable `
                -Source $stagingPath `
                -Destination $replacementPath
            $replacement = Get-TicketboxC07SuperuserRecoveryAuthFile `
                -Path $replacementPath `
                -Label "$Label deterministic replacement"
            $replacement =
                Complete-TicketboxC07SuperuserRecoveryReplacementCandidate `
                    -Candidate $replacement `
                    -Path $replacementPath `
                    -ExpectedSha256 $ExpectedSha256 `
                    -ExpectedSecurityBytes $SecurityBytes `
                    -Label "$Label deterministic replacement"
        }

        $replaceResult = Replace-TicketboxFileDurablePreservingMetadata `
            -Replacement $replacementPath `
            -Destination $fullPath `
            -Backup $backupPath
        $destinationAfter = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $fullPath `
            -Label "$Label destination after ReplaceFileW"
        $replacementAfter = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $replacementPath `
            -Label "$Label deterministic replacement"
        $replacementAfterFailure = $null
        if ($null -ne $replacementAfter) {
            try {
                $replacementAfter =
                    Complete-TicketboxC07SuperuserRecoveryReplacementCandidate `
                        -Candidate $replacementAfter `
                        -Path $replacementPath `
                        -ExpectedSha256 $ExpectedSha256 `
                        -ExpectedSecurityBytes $SecurityBytes `
                        -Label "$Label deterministic replacement"
            }
            catch {
                $replacementAfterFailure = $_.Exception
            }
        }
        $backupAfter = Get-TicketboxC07SuperuserRecoveryAuthCandidate `
            -Path $backupPath `
            -Label "$Label deterministic backup"
        if ($null -ne $backupAfter) {
            Assert-TicketboxC07SuperuserRecoveryBackupCandidate `
                -Candidate $backupAfter `
                -PreviousSha256 $PreviousSha256 `
                -ExpectedSecurityBytes $SecurityBytes `
                -Label "$Label deterministic backup"
        }
        if ($null -ne $destinationAfter) {
            if ([string]$destinationAfter.Sha256 -cnotin @(
                $PreviousSha256,
                $ExpectedSha256
            )) {
                throw (
                    "$Label destination after ReplaceFileW bytes " +
                    "不属于 captured authority。"
                )
            }
        }
        if (
            $null -ne $destinationAfter -and
            [string]$destinationAfter.Sha256 -ceq $ExpectedSha256 -and
            (Test-TicketboxC07SuperuserRecoverySecurityEquals `
                -Left $destinationAfter.SecurityBytes `
                -Right $SecurityBytes)
        ) {
            Sync-TicketboxFileDurable $fullPath
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $replacementPath `
                -Label "$Label deterministic replacement"
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $stagingPath `
                -Label "$Label deterministic replacement staging"
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $backupPath `
                -Label "$Label deterministic backup"
            return
        }
        if (
            $null -ne $destinationAfter -and
            -not (Test-TicketboxC07SuperuserRecoverySecurityEquals `
                -Left $destinationAfter.SecurityBytes `
                -Right $SecurityBytes)
        ) {
            if ($null -ne $backupAfter) {
                Restore-TicketboxC07SuperuserRecoveryBackupDestination `
                    -BackupPath $backupPath `
                    -DestinationPath $fullPath `
                    -PreviousSha256 $PreviousSha256 `
                    -ExpectedSecurityBytes $SecurityBytes `
                    -Label $Label `
                    -ReplaceExisting
            }
        }
        if ($null -eq $destinationAfter -and $null -ne $backupAfter) {
            if (
                $null -ne $replacementAfter -and
                $null -eq $replacementAfterFailure
            ) {
                Move-TicketboxFileDurable `
                    -Source $replacementPath `
                    -Destination $fullPath
                $persisted = Get-TicketboxC07SuperuserRecoveryAuthFile `
                    -Path $fullPath `
                    -Label $Label
                Assert-TicketboxC07SuperuserRecoveryDestinationCandidate `
                    -Candidate $persisted `
                    -AllowedSha256 @($ExpectedSha256) `
                        -ExpectedSecurityBytes $SecurityBytes `
                        -Label $Label
                Sync-TicketboxFileDurable $fullPath
                Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                    -Path $stagingPath `
                    -Label "$Label deterministic replacement staging"
                Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                    -Path $backupPath `
                    -Label "$Label deterministic backup"
                return
            }
            Restore-TicketboxC07SuperuserRecoveryBackupDestination `
                -BackupPath $backupPath `
                -DestinationPath $fullPath `
                -PreviousSha256 $PreviousSha256 `
                -ExpectedSecurityBytes $SecurityBytes `
                -Label $Label
        }
        elseif (
            $null -eq $destinationAfter -and
            $null -eq $backupAfter -and
            $null -ne $replacementAfter -and
            $null -eq $replacementAfterFailure
        ) {
            Move-TicketboxFileDurable `
                -Source $replacementPath `
                -Destination $fullPath
            $persisted = Get-TicketboxC07SuperuserRecoveryAuthFile `
                -Path $fullPath `
                -Label $Label
            Assert-TicketboxC07SuperuserRecoveryDestinationCandidate `
                -Candidate $persisted `
                -AllowedSha256 @($ExpectedSha256) `
                -ExpectedSecurityBytes $SecurityBytes `
                -Label $Label
            Sync-TicketboxFileDurable $fullPath
            Remove-TicketboxC07SuperuserRecoveryReconciledSidecar `
                -Path $stagingPath `
                -Label "$Label deterministic replacement staging"
            return
        }
        # Never delete any remaining sidecar here.  ReplaceFileW FALSE may have
        # moved or modified a name even when another name retained its place.
        $nativeError = if ($null -eq $replaceResult) {
            -1
        }
        else { [int]$replaceResult.NativeErrorCode }
        throw (
            "$Label ReplaceFileW 后未收敛" +
            "（native_error=$nativeError）；有效副本与 sidecars 已保留供重试。"
        )
    }
    finally {
        $privilege.Dispose()
    }
}

function Invoke-TicketboxC07SuperuserRecoveryReload {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 60000
    )

    $result = Invoke-TicketboxC07SuperuserRecoveryNative `
        -FilePath ([string]$HostContext.PgCtlPath) `
        -Arguments @("reload", "-D", [string]$HostContext.PgData, "-s") `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -Label "C07 PostgreSQL auth reload"
    if ($result.ExitCode -ne 0) {
        throw "C07 PostgreSQL auth reload 失败（exit=$($result.ExitCode)）。"
    }
}

function Set-TicketboxC07SuperuserRecoveryStage {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][string]$Stage
    )

    if ($Stage -cnotin $script:TicketboxC07SuperuserRecoveryStages) {
        throw "C07 superuser recovery stage 未登记。"
    }
    $Artifact.stage = $Stage
    return Write-TicketboxC07SuperuserRecoveryArtifact `
        -Path $Path `
        -Artifact $Artifact
}

function Restore-TicketboxC07SuperuserRecoveryAuthFiles {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][string]$ArtifactPath,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][object]$Material
    )

    $state = Get-TicketboxC07SuperuserRecoveryAuthState `
        -Artifact $Artifact `
        -Material $Material
    # On Windows, a new pg_hba.conf is applied to subsequent connections
    # immediately.  Restore it before removing the user map so no connection
    # can ever select the temporary SSPI line with a missing map.
    if ($state.Hba -cne "original") {
        Write-TicketboxC07SuperuserRecoveryAuthFile `
            -Path ([string]$Artifact.hba_path) `
            -Bytes $Material.HbaOriginalBytes `
            -SecurityBytes $Material.HbaSecurityBytes `
            -ExpectedSha256 ([string]$Artifact.hba_original_sha256) `
            -PreviousSha256 ([string]$Artifact.hba_temporary_sha256) `
            -Label "restore pg_hba.conf"
    }
    $state = Get-TicketboxC07SuperuserRecoveryAuthState `
        -Artifact $Artifact `
        -Material $Material
    if ($state.Ident -cne "original") {
        Write-TicketboxC07SuperuserRecoveryAuthFile `
            -Path ([string]$Artifact.ident_path) `
            -Bytes $Material.IdentOriginalBytes `
            -SecurityBytes $Material.IdentSecurityBytes `
            -ExpectedSha256 ([string]$Artifact.ident_original_sha256) `
            -PreviousSha256 ([string]$Artifact.ident_temporary_sha256) `
            -Label "restore pg_ident.conf"
        Invoke-TicketboxC07SuperuserRecoveryReload $HostContext
    }
    $state = Get-TicketboxC07SuperuserRecoveryAuthState `
        -Artifact $Artifact `
        -Material $Material
    if ($state.Hba -cne "original" -or $state.Ident -cne "original") {
        throw "C07 PostgreSQL auth files 未 exact restore。"
    }
    if (
        [string]$Artifact.stage -cin @(
            "sspi_ident_published",
            "sspi_hba_published",
            "credential_rotated"
        )
    ) {
        $Artifact = Set-TicketboxC07SuperuserRecoveryStage `
            -Path $ArtifactPath `
            -Artifact $Artifact `
            -Stage "auth_files_restored"
    }
    return $Artifact
}

function Publish-TicketboxC07SuperuserRecoverySspi {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][string]$ArtifactPath,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][object]$Material
    )

    $Artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
        -Host $HostContext `
        -ArtifactPath $ArtifactPath `
        -Artifact $Artifact `
        -Material $Material
    # Publish and load the exact mapping before the first-match HBA line.
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path ([string]$Artifact.ident_path) `
        -Bytes $Material.IdentTemporaryBytes `
        -SecurityBytes $Material.IdentSecurityBytes `
        -ExpectedSha256 ([string]$Artifact.ident_temporary_sha256) `
        -PreviousSha256 ([string]$Artifact.ident_original_sha256) `
        -Label "publish temporary pg_ident.conf"
    $Artifact = Set-TicketboxC07SuperuserRecoveryStage `
        -Path $ArtifactPath `
        -Artifact $Artifact `
        -Stage "sspi_ident_published"
    Invoke-TicketboxC07SuperuserRecoveryReload $HostContext
    Write-TicketboxC07SuperuserRecoveryAuthFile `
        -Path ([string]$Artifact.hba_path) `
        -Bytes $Material.HbaTemporaryBytes `
        -SecurityBytes $Material.HbaSecurityBytes `
        -ExpectedSha256 ([string]$Artifact.hba_temporary_sha256) `
        -PreviousSha256 ([string]$Artifact.hba_original_sha256) `
        -Label "publish temporary pg_hba.conf"
    $Artifact = Set-TicketboxC07SuperuserRecoveryStage `
        -Path $ArtifactPath `
        -Artifact $Artifact `
        -Stage "sspi_hba_published"
    $state = Get-TicketboxC07SuperuserRecoveryAuthState `
        -Artifact $Artifact `
        -Material $Material
    if ($state.Ident -cne "temporary" -or $state.Hba -cne "temporary") {
        throw "C07 exact SSPI auth pair 未同时生效。"
    }
    return $Artifact
}

function Assert-TicketboxC07SuperuserRecoveryAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (
        -not $principal.IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator
        )
    ) {
        throw "C07 superuser recovery 需要当前进程持有提升后的管理员 token。"
    }
}

function Assert-TicketboxC07SuperuserRecoveryServerReady {
    param([Parameter(Mandatory = $true)][object]$HostContext)

    $pgIsReady = Join-Path (
        Split-Path -Parent ([string]$HostContext.PgCtlPath)
    ) "pg_isready.exe"
    if ((Get-TicketboxPathEntryKindNoFollow $pgIsReady) -cne "File") {
        throw "C07 superuser recovery 缺少受管 pg_isready.exe。"
    }
    Assert-NoTicketboxAncestorReparsePoints $pgIsReady
    $result = Invoke-TicketboxC07SuperuserRecoveryNative `
        -FilePath $pgIsReady `
        -Arguments @(
            "-h", "127.0.0.1",
            "-p", [string]$HostContext.Port,
            "-d", "postgres",
            "-t", "10",
            "-q"
        ) `
        -TimeoutMilliseconds 15000 `
        -Label "C07 PostgreSQL readiness"
    if ($result.ExitCode -ne 0) {
        throw "C07 PostgreSQL 未处于 accepting-connections 状态。"
    }
}

function New-TicketboxC07SuperuserRecoveryDatabaseUrl {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)]
        [ValidateSet("sspi", "scram-sha-256")]
        [string]$Authentication
    )

    if ($Authentication -ceq "sspi") {
        # libpq requires a host name for SSPI target-name construction.
        # hostaddr pins the actual transport to the IPv4 loopback HBA row.
        return (
            "postgresql://postgres@localhost:$($HostContext.Port)/postgres" +
            "?hostaddr=127.0.0.1&require_auth=sspi&sslmode=disable" +
            "&connect_timeout=10"
        )
    }
    # Keep the numeric host for SCRAM so the sole recovery pgpass record
    # exactly matches libpq's password-file lookup key.
    return (
        "postgresql://postgres@127.0.0.1:$($HostContext.Port)/postgres" +
        "?require_auth=scram-sha-256&sslmode=disable&connect_timeout=10"
    )
}

function Invoke-TicketboxC07SuperuserRecoveryPsql {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)]
        [ValidateSet("sspi", "scram-sha-256")]
        [string]$Authentication,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [AllowEmptyString()][string]$ArtifactPath = "",
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    Assert-TicketboxC07SuperuserRecoveryServerReady $HostContext
    if (
        $Authentication -ceq "scram-sha-256" -and
        [string]::IsNullOrWhiteSpace($ArtifactPath)
    ) {
        throw "C07 SCRAM probe 缺少 sole protected recovery passfile。"
    }
    $parameters = @{
        FilePath = [string]$HostContext.PsqlPath
        Arguments = @(
            "--no-psqlrc",
            "--no-password",
            "--tuples-only",
            "--no-align",
            "--field-separator", "`t",
            "--set", "ON_ERROR_STOP=1",
            "--dbname", (
                New-TicketboxC07SuperuserRecoveryDatabaseUrl `
                    -Host $HostContext `
                    -Authentication $Authentication
            )
        )
        StandardInputText = $Sql + "`n"
        TimeoutMilliseconds = $TimeoutMilliseconds
        Label = $Label
    }
    if ($Authentication -ceq "scram-sha-256") {
        $parameters.PgPassFile = $ArtifactPath
    }
    return Invoke-TicketboxC07SuperuserRecoveryNative @parameters
}

function ConvertFrom-TicketboxC07SuperuserRecoveryRow {
    param(
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Output,
        [ValidateRange(1, 16)][int]$FieldCount,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $lines = @(
        $Output -split "`r?`n" |
            ForEach-Object { [string]$_ } |
            Where-Object { $_.Trim().Length -gt 0 }
    )
    if ($lines.Count -ne 1) {
        throw "$Label 未返回唯一结果行。"
    }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne $FieldCount) {
        throw "$Label 返回字段数无效。"
    }
    return $fields
}

function ConvertTo-TicketboxC07SuperuserRecoverySecureString {
    param([Parameter(Mandatory = $true)][object]$Artifact)

    if ([string]$Artifact.secret -cnotmatch '^[A-Za-z0-9_-]{64}$') {
        throw "C07 one-shot secret shape 无效。"
    }
    $secure = New-Object Security.SecureString
    foreach ($character in ([string]$Artifact.secret).ToCharArray()) {
        $secure.AppendChar($character)
    }
    $secure.MakeReadOnly()
    return $secure
}

function Get-TicketboxC07SuperuserRecoveryVerifier {
    param(
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][Security.SecureString]$Secret
    )

    $salt = ConvertFrom-TicketboxC07SuperuserRecoveryStoredBytes `
        -Value ([string]$Artifact.scram_salt) `
        -Label "C07 SCRAM salt" `
        -MaximumBytes 16
    if ($salt.Length -ne 16) {
        throw "C07 SCRAM salt 必须正好为 16 bytes。"
    }
    $verifier = ConvertTo-TicketboxC07ScramVerifier `
        -Password $Secret `
        -Salt $salt
    [Array]::Clear($salt, 0, $salt.Length)
    if (
        $verifier -cnotmatch
            '^SCRAM-SHA-256\$4096:[A-Za-z0-9+/]+={0,2}\$' +
            '[A-Za-z0-9+/]+={0,2}:[A-Za-z0-9+/]+={0,2}$'
    ) {
        throw "C07 locally derived SCRAM verifier shape 无效。"
    }
    return $verifier
}

function Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow {
    param(
        [Parameter(Mandatory = $true)][string[]]$Fields,
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (
        $Fields.Count -lt 5 -or
        $Fields[0].Trim() -cne "postgres" -or
        $Fields[1].Trim() -cne "postgres" -or
        $Fields[2].Trim() -cne [string]$HostContext.ClusterSystemIdentifier -or
        -not (Test-TicketboxPathEquals $Fields[3].Trim() (
            [string]$HostContext.PgData
        )) -or
        $Fields[4].Trim() -cne [string]$HostContext.Port
    ) {
        throw "$Label 未绑定 exact postgres/cluster/data-dir/port。"
    }
}

function Invoke-TicketboxC07SuperuserRecoveryRotateCredential {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][string]$ArtifactPath,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][Security.SecureString]$Secret
    )

    $verifier = Get-TicketboxC07SuperuserRecoveryVerifier `
        -Artifact $Artifact `
        -Secret $Secret
    $validUntil = [DateTime]::UtcNow.AddHours(1).ToString(
        "yyyy-MM-dd HH:mm:ss.fffffff'+00'"
    )
    $sql = @"
ALTER ROLE postgres WITH LOGIN PASSWORD '$verifier' VALID UNTIL '$validUntil';
SELECT
    session_user,
    current_user,
    control.system_identifier::text,
    current_setting('data_directory'),
    current_setting('port'),
    role.rolcanlogin::text,
    (role.rolpassword = '$verifier')::text
FROM pg_catalog.pg_control_system() AS control
CROSS JOIN pg_catalog.pg_authid AS role
WHERE role.rolname = 'postgres';
"@
    $result = Invoke-TicketboxC07SuperuserRecoveryPsql `
        -Host $HostContext `
        -Authentication "sspi" `
        -Sql $sql `
        -Label "C07 SSPI one-shot credential rotation"
    if ($result.ExitCode -ne 0) {
        throw "C07 SSPI one-shot credential rotation 失败（原生输出已抑制）。"
    }
    $fields = ConvertFrom-TicketboxC07SuperuserRecoveryRow `
        -Output $result.StandardOutput `
        -FieldCount 7 `
        -Label "C07 SSPI rotation evidence"
    Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow `
        -Fields $fields `
        -Host $HostContext `
        -Label "C07 SSPI rotation evidence"
    if ($fields[5].Trim() -cne "true" -or $fields[6].Trim() -cne "true") {
        throw "C07 postgres one-shot LOGIN/verifier 未 exact commit。"
    }
}

function Test-TicketboxC07SuperuserRecoveryScramCredential {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][string]$ArtifactPath
    )

    $result = Invoke-TicketboxC07SuperuserRecoveryPsql `
        -Host $HostContext `
        -Authentication "scram-sha-256" `
        -Sql "SELECT 1;" `
        -ArtifactPath $ArtifactPath `
        -Label "C07 one-shot SCRAM verification"
    if ($result.ExitCode -ne 0) {
        return $false
    }
    $fields = ConvertFrom-TicketboxC07SuperuserRecoveryRow `
        -Output $result.StandardOutput `
        -FieldCount 1 `
        -Label "C07 one-shot SCRAM verification"
    if ($fields[0].Trim() -cne "1") {
        throw "C07 one-shot SCRAM verification 返回意外结果。"
    }
    return $true
}

function Invoke-TicketboxC07SuperuserRecoveryRenewCredential {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][string]$ArtifactPath
    )

    $validUntil = [DateTime]::UtcNow.AddHours(1).ToString(
        "yyyy-MM-dd HH:mm:ss.fffffff'+00'"
    )
    $result = Invoke-TicketboxC07SuperuserRecoveryPsql `
        -Host $HostContext `
        -Authentication "scram-sha-256" `
        -Sql (
            "ALTER ROLE postgres WITH LOGIN VALID UNTIL '$validUntil'; " +
            "SELECT rolcanlogin::text FROM pg_catalog.pg_authid " +
            "WHERE rolname = 'postgres';"
        ) `
        -ArtifactPath $ArtifactPath `
        -Label "C07 one-shot credential renewal"
    if ($result.ExitCode -ne 0) {
        throw "C07 one-shot credential renewal 失败（原生输出已抑制）。"
    }
    $fields = ConvertFrom-TicketboxC07SuperuserRecoveryRow `
        -Output $result.StandardOutput `
        -FieldCount 1 `
        -Label "C07 one-shot credential renewal"
    if ($fields[0].Trim() -cne "true") {
        throw "C07 one-shot credential renewal 未保留 postgres LOGIN。"
    }
}

function Invoke-TicketboxC07SuperuserRecoveryReadPasswordStateViaSspi {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][Security.SecureString]$Secret
    )

    $verifier = Get-TicketboxC07SuperuserRecoveryVerifier `
        -Artifact $Artifact `
        -Secret $Secret
    $sql = @"
SELECT
    session_user,
    current_user,
    control.system_identifier::text,
    current_setting('data_directory'),
    current_setting('port'),
    role.rolcanlogin::text,
    (role.rolpassword IS NULL)::text,
    (role.rolpassword = '$verifier')::text
FROM pg_catalog.pg_control_system() AS control
CROSS JOIN pg_catalog.pg_authid AS role
WHERE role.rolname = 'postgres';
"@
    $result = Invoke-TicketboxC07SuperuserRecoveryPsql `
        -Host $HostContext `
        -Authentication "sspi" `
        -Sql $sql `
        -Label "C07 SSPI postgres credential state"
    if ($result.ExitCode -ne 0) {
        throw "C07 SSPI credential-state read 失败（原生输出已抑制）。"
    }
    $fields = ConvertFrom-TicketboxC07SuperuserRecoveryRow `
        -Output $result.StandardOutput `
        -FieldCount 8 `
        -Label "C07 SSPI credential-state evidence"
    Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow `
        -Fields $fields `
        -Host $HostContext `
        -Label "C07 SSPI credential-state evidence"
    return [pscustomobject]@{
        Login = $fields[5].Trim() -ceq "true"
        PasswordNull = $fields[6].Trim() -ceq "true"
        PasswordMatchesRecovery = $fields[7].Trim() -ceq "true"
    }
}

function Invoke-TicketboxC07SuperuserRecoveryClearCredential {
    param(
        [Parameter(Mandatory = $true)][object]$HostContext,
        [ValidateSet("sspi", "scram-sha-256")]
        [string]$Authentication = "scram-sha-256",
        [AllowEmptyString()][string]$ArtifactPath = ""
    )

    if (
        $Authentication -ceq "scram-sha-256" -and
        [string]::IsNullOrWhiteSpace($ArtifactPath)
    ) {
        throw "C07 SCRAM credential retirement 缺少 recovery artifact。"
    }
    $sql = @"
ALTER ROLE postgres WITH LOGIN PASSWORD NULL VALID UNTIL 'infinity';
SELECT
    session_user,
    current_user,
    control.system_identifier::text,
    current_setting('data_directory'),
    current_setting('port'),
    role.rolcanlogin::text,
    (role.rolpassword IS NULL)::text
FROM pg_catalog.pg_control_system() AS control
CROSS JOIN pg_catalog.pg_authid AS role
WHERE role.rolname = 'postgres';
"@
    $parameters = @{
        Host = $HostContext
        Authentication = $Authentication
        Sql = $sql
        Label = "C07 one-shot postgres credential retirement"
    }
    if ($Authentication -ceq "scram-sha-256") {
        $parameters.ArtifactPath = $ArtifactPath
    }
    $result = Invoke-TicketboxC07SuperuserRecoveryPsql @parameters
    if ($result.ExitCode -ne 0) {
        throw "C07 one-shot postgres credential retirement 失败（原生输出已抑制）。"
    }
    $fields = ConvertFrom-TicketboxC07SuperuserRecoveryRow `
        -Output $result.StandardOutput `
        -FieldCount 7 `
        -Label "C07 postgres credential-retirement evidence"
    Assert-TicketboxC07SuperuserRecoveryDatabaseIdentityRow `
        -Fields $fields `
        -Host $HostContext `
        -Label "C07 postgres credential-retirement evidence"
    if ($fields[5].Trim() -cne "true" -or $fields[6].Trim() -cne "true") {
        throw "C07 postgres 必须保留 LOGIN 且 password 必须为 NULL。"
    }
}

function Update-TicketboxC07SuperuserRecoveryPrincipal {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactPath,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][object]$Principal,
        [Parameter(Mandatory = $true)][object]$Material
    )

    $Artifact.principal_name = [string]$Principal.Name
    $Artifact.principal_sid = [string]$Principal.Sid
    $Artifact.sspi_system_username = [string]$Principal.SystemUsername
    $Artifact.sspi_realm = [string]$Principal.Realm
    $Artifact.stage = "captured"
    $temporary = Get-TicketboxC07SuperuserRecoveryTemporaryFiles `
        -Artifact $Artifact `
        -HbaOriginal $Material.HbaOriginalBytes `
        -IdentOriginal $Material.IdentOriginalBytes
    $Artifact.hba_temporary_sha256 =
        Get-TicketboxC07SuperuserRecoverySha256 $temporary.HbaBytes
    $Artifact.ident_temporary_sha256 =
        Get-TicketboxC07SuperuserRecoverySha256 $temporary.IdentBytes
    return Write-TicketboxC07SuperuserRecoveryArtifact `
        -Path $ArtifactPath `
        -Artifact $Artifact
}

function Test-TicketboxC07SuperuserRecoveryResidue {
    param([Parameter(Mandatory = $true)][object]$HostContext)

    $needle = "ticketbox_c07_recover_"
    foreach ($file in @($HostContext.Hba, $HostContext.Ident)) {
        $text = [Text.Encoding]::UTF8.GetString([byte[]]$file.Bytes)
        if ($text.IndexOf($needle, [StringComparison]::Ordinal) -ge 0) {
            return $true
        }
    }
    return $false
}

function Remove-TicketboxC07CompletedSuperuserRecoveryArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Artifact,
        [Parameter(Mandatory = $true)][object]$Material
    )

    if ([string]$Artifact.stage -cne "completed") {
        throw "C07 superuser recovery 只允许删除 completed secret artifact。"
    }
    $state = Get-TicketboxC07SuperuserRecoveryAuthState `
        -Artifact $Artifact `
        -Material $Material
    if ($state.Hba -cne "original" -or $state.Ident -cne "original") {
        throw "C07 superuser recovery 删除 secret 前仍有临时 auth mapping。"
    }
    $null = Remove-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $script:TicketboxC07SuperuserRecoveryAccounts `
        -OwnerAccount $script:TicketboxC07SuperuserRecoveryOwner
}

function Invoke-TicketboxC07RecoveredSuperuserAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][string]$RecoveryArtifactPath,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $null = Assert-TicketboxC07SuperuserRecoveryDependencies
    $null = Assert-TicketboxC07SuperuserRecoveryAdministrator
    $artifactPath = Assert-TicketboxC07SuperuserRecoveryArtifactPath `
        $RecoveryArtifactPath
    $HostContext = Resolve-TicketboxC07SuperuserRecoveryHost $HostAuthority
    $principal = Get-TicketboxC07SuperuserRecoveryPrincipal
    $actionResult = $null

    # A completed-but-not-yet-deleted crash window is retired, then the
    # idempotent bounded Action is re-run under a fresh authority so the caller
    # receives a real result rather than a guessed reconstruction.
    for ($cycle = 0; $cycle -lt 3; $cycle++) {
        if (-not (Test-Path -LiteralPath $artifactPath)) {
            if (Test-TicketboxC07SuperuserRecoveryResidue $HostContext) {
                throw (
                    "C07 PostgreSQL auth files 含 recovery mapping 但 durable " +
                    "artifact 缺失；拒绝把未知临时权限当作 original。"
                )
            }
            $newArtifact = New-TicketboxC07SuperuserRecoveryArtifact `
                -Host $HostContext `
                -Principal $principal
            $artifact = Write-TicketboxC07SuperuserRecoveryArtifact `
                -Path $artifactPath `
                -Artifact $newArtifact
        }
        else {
            $artifact = Read-TicketboxC07SuperuserRecoveryArtifact $artifactPath
        }

        $material = Assert-TicketboxC07SuperuserRecoveryArtifact `
            -Artifact $artifact `
            -Host $HostContext
        $artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
            -Host $HostContext `
            -ArtifactPath $artifactPath `
            -Artifact $artifact `
            -Material $material

        if (
            [string]$artifact.principal_sid -cne [string]$principal.Sid -or
            [string]$artifact.principal_name -cne [string]$principal.Name -or
            [string]$artifact.sspi_system_username -cne
                [string]$principal.SystemUsername -or
            [string]$artifact.sspi_realm -cne [string]$principal.Realm
        ) {
            # Exact originals are already restored.  It is now safe for a
            # different elevated administrator to replace only the principal
            # binding and continue with the same protected one-shot secret.
            $artifact = Update-TicketboxC07SuperuserRecoveryPrincipal `
                -ArtifactPath $artifactPath `
                -Artifact $artifact `
                -Principal $principal `
                -Material $material
            $material = Assert-TicketboxC07SuperuserRecoveryArtifact `
                -Artifact $artifact `
                -Host $HostContext
        }

        $secret = ConvertTo-TicketboxC07SuperuserRecoverySecureString $artifact
        try {
            $credentialActive =
                Test-TicketboxC07SuperuserRecoveryScramCredential `
                    -Host $HostContext `
                    -ArtifactPath $artifactPath

            if (
                [string]$artifact.stage -cin @("password_cleared", "completed")
            ) {
                if ($credentialActive) {
                    throw "C07 completed recovery artifact 仍可执行 SCRAM 登录。"
                }
                $artifact = Publish-TicketboxC07SuperuserRecoverySspi `
                    -Host $HostContext `
                    -ArtifactPath $artifactPath `
                    -Artifact $artifact `
                    -Material $material
                try {
                    $passwordState =
                        Invoke-TicketboxC07SuperuserRecoveryReadPasswordStateViaSspi `
                            -Host $HostContext `
                            -Artifact $artifact `
                            -Secret $secret
                }
                finally {
                    $artifact =
                        Read-TicketboxC07SuperuserRecoveryArtifact $artifactPath
                    $material =
                        Assert-TicketboxC07SuperuserRecoveryArtifact `
                            -Artifact $artifact `
                            -Host $HostContext
                    $artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
                        -Host $HostContext `
                        -ArtifactPath $artifactPath `
                        -Artifact $artifact `
                        -Material $material
                }
                if (-not $passwordState.Login -or -not $passwordState.PasswordNull) {
                    throw "C07 completed recovery 未证明 postgres LOGIN/password NULL。"
                }
                $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                    -Path $artifactPath `
                    -Artifact $artifact `
                    -Stage "completed"
                $null = Remove-TicketboxC07CompletedSuperuserRecoveryArtifact `
                    -Path $artifactPath `
                    -Artifact $artifact `
                    -Material $material
                continue
            }

            if (
                -not $credentialActive -and
                [string]$artifact.stage -ceq "action_succeeded"
            ) {
                # Legitimate recovery windows are PASSWORD NULL whose stage
                # publication was interrupted, or the exact one-shot verifier
                # whose one-hour validity expired after Action committed.
                $artifact = Publish-TicketboxC07SuperuserRecoverySspi `
                    -Host $HostContext `
                    -ArtifactPath $artifactPath `
                    -Artifact $artifact `
                    -Material $material
                try {
                    $passwordState =
                        Invoke-TicketboxC07SuperuserRecoveryReadPasswordStateViaSspi `
                            -Host $HostContext `
                            -Artifact $artifact `
                            -Secret $secret
                    if (
                        -not $passwordState.PasswordNull -and
                        $passwordState.PasswordMatchesRecovery
                    ) {
                        # Exact verifier equality proves that no foreign
                        # credential replaced it; retire it through the
                        # already-bounded SSPI mapping.
                        $null = Invoke-TicketboxC07SuperuserRecoveryClearCredential `
                            -Host $HostContext `
                            -Authentication "sspi"
                        $passwordState =
                            Invoke-TicketboxC07SuperuserRecoveryReadPasswordStateViaSspi `
                                -Host $HostContext `
                                -Artifact $artifact `
                                -Secret $secret
                    }
                }
                finally {
                    $artifact =
                        Read-TicketboxC07SuperuserRecoveryArtifact $artifactPath
                    $material =
                        Assert-TicketboxC07SuperuserRecoveryArtifact `
                            -Artifact $artifact `
                            -Host $HostContext
                    $artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
                        -Host $HostContext `
                        -ArtifactPath $artifactPath `
                        -Artifact $artifact `
                        -Material $material
                }
                if (-not $passwordState.Login -or -not $passwordState.PasswordNull) {
                    throw (
                        "C07 action_succeeded 后 postgres credential 既非 " +
                        "recovery verifier 也非 NULL。"
                    )
                }
                $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                    -Path $artifactPath `
                    -Artifact $artifact `
                    -Stage "password_cleared"
                $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                    -Path $artifactPath `
                    -Artifact $artifact `
                    -Stage "completed"
                $null = Remove-TicketboxC07CompletedSuperuserRecoveryArtifact `
                    -Path $artifactPath `
                    -Artifact $artifact `
                    -Material $material
                continue
            }

            if (-not $credentialActive) {
                $artifact = Publish-TicketboxC07SuperuserRecoverySspi `
                    -Host $HostContext `
                    -ArtifactPath $artifactPath `
                    -Artifact $artifact `
                    -Material $material
                try {
                    $null = Invoke-TicketboxC07SuperuserRecoveryRotateCredential `
                        -Host $HostContext `
                        -ArtifactPath $artifactPath `
                        -Artifact $artifact `
                        -Secret $secret
                    $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                        -Path $artifactPath `
                        -Artifact $artifact `
                        -Stage "credential_rotated"
                }
                finally {
                    $artifact =
                        Read-TicketboxC07SuperuserRecoveryArtifact $artifactPath
                    $material =
                        Assert-TicketboxC07SuperuserRecoveryArtifact `
                            -Artifact $artifact `
                            -Host $HostContext
                    $artifact = Restore-TicketboxC07SuperuserRecoveryAuthFiles `
                        -Host $HostContext `
                        -ArtifactPath $artifactPath `
                        -Artifact $artifact `
                        -Material $material
                }
                if (
                    -not (
                        Test-TicketboxC07SuperuserRecoveryScramCredential `
                            -Host $HostContext `
                            -ArtifactPath $artifactPath
                    )
                ) {
                    throw "C07 one-shot SCRAM credential 未在 exact auth restore 后生效。"
                }
            }

            $null = Invoke-TicketboxC07SuperuserRecoveryRenewCredential `
                -Host $HostContext `
                -ArtifactPath $artifactPath
            $artifact.action_attempt = [int]$artifact.action_attempt + 1
            $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                -Path $artifactPath `
                -Artifact $artifact `
                -Stage "action_running"
            try {
                $results = @(& $Action $secret)
                if ($results.Count -ne 1 -or $null -eq $results[0]) {
                    throw "bounded Action 必须返回且仅返回一个非空结果。"
                }
                $actionResult = $results[0]
            }
            catch {
                throw (
                    "C07 bounded Action 失败；one-shot authority 已在 exact " +
                    "original auth 下保留供重试，原始输出已抑制。"
                )
            }
            $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                -Path $artifactPath `
                -Artifact $artifact `
                -Stage "action_succeeded"
            $null = Invoke-TicketboxC07SuperuserRecoveryClearCredential `
                -Host $HostContext `
                -ArtifactPath $artifactPath
            $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                -Path $artifactPath `
                -Artifact $artifact `
                -Stage "password_cleared"
            if (
                Test-TicketboxC07SuperuserRecoveryScramCredential `
                    -Host $HostContext `
                    -ArtifactPath $artifactPath
            ) {
                throw "C07 postgres PASSWORD NULL 后 SCRAM 仍可认证。"
            }
            $state = Get-TicketboxC07SuperuserRecoveryAuthState `
                -Artifact $artifact `
                -Material $material
            if ($state.Hba -cne "original" -or $state.Ident -cne "original") {
                throw "C07 Action 完成后仍残留 temporary SSPI mapping。"
            }
            $artifact = Set-TicketboxC07SuperuserRecoveryStage `
                -Path $artifactPath `
                -Artifact $artifact `
                -Stage "completed"
            $null = Remove-TicketboxC07CompletedSuperuserRecoveryArtifact `
                -Path $artifactPath `
                -Artifact $artifact `
                -Material $material
            return $actionResult
        }
        finally {
            if ($null -ne $secret) {
                $secret.Dispose()
            }
        }
    }
    throw "C07 superuser recovery 超过 completed-artifact convergence 上限。"
}
