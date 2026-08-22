#Requires -Version 5.1

<#
.SYNOPSIS
  Database lifecycle helpers for the bundled Ticketbox Windows installer.
.DESCRIPTION
  Dot-sourced by install_bundled_services.ps1 after runtime paths and shared
  service/safety helpers have been initialized.
#>

$script:PostgresBootstrapRecoveryFileName = ".postgres-bootstrap-password"
$script:PostgresBootstrapRecoverySchema = "ticketbox-postgres-bootstrap-v1"
$script:PostgresBootstrapAclAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:PostgresBootstrapAclOwnerAccount = "SYSTEM"
$script:TicketboxBundledRuntimeDatabaseRole = "ticketbox_runtime"

function Initialize-TicketboxDatabaseFileNativeMethods {
    if ("TicketboxDatabaseFileNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class TicketboxDatabaseFileNativeMethods
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool MoveFileEx(
        string existingFileName,
        string newFileName,
        int flags);
}
'@
}
function Move-TicketboxFileAtomically([string]$Source, [string]$Destination, [switch]$Replace) {
    Initialize-TicketboxDatabaseFileNativeMethods
    $flags = 0x8
    if ($Replace) {
        $flags = $flags -bor 0x1
    }
    if (-not [TicketboxDatabaseFileNativeMethods]::MoveFileEx($Source, $Destination, $flags)) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "原子文件替换失败（Win32=$errorCode）：$Destination"
    }
}
function Write-TicketboxFileAtomically([string]$Path, [byte[]]$Bytes) {
    $tempPath = "$Path.tmp"
    if (Test-Path -LiteralPath $tempPath) {
        Remove-TicketboxSensitiveFile $tempPath
    }
    $stream = $null
    try {
        $stream = [System.IO.FileStream]::new(
            $tempPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None,
            4096,
            [System.IO.FileOptions]::WriteThrough
        )
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null

        $replace = Test-Path -LiteralPath $Path
        if ($replace) {
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                throw "原子写入目标不是普通文件：$Path"
            }
        }
        Move-TicketboxFileAtomically -Source $tempPath -Destination $Path -Replace:$replace
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if (Test-Path -LiteralPath $tempPath) {
            Remove-TicketboxSensitiveFile $tempPath
        }
    }
}

function Write-EnvNoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Lines,
        [Parameter(Mandatory = $true)][string]$BackendServiceName
    )
    $text = [string]::Join([Environment]::NewLine, $Lines) + [Environment]::NewLine
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $text `
        -FullControlAccounts @(
            "SYSTEM", "BUILTIN\Administrators", "NT SERVICE\$BackendServiceName"
        ) `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting
}

function New-StrongPassword {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object 'System.Byte[]' $SecretByteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

function Get-HttpBootstrapSecretByteCount {
    $byteCount = [int]$SecretByteCount
    if ($byteCount -lt 32) {
        throw "HTTP bootstrap secret 必须至少包含 32 个随机字节。"
    }
    return $byteCount
}

function Get-HttpBootstrapSecretEncodedLength {
    $byteCount = Get-HttpBootstrapSecretByteCount
    return [int][Math]::Ceiling(($byteCount * 8.0) / 6.0)
}

function New-HttpBootstrapSecret {
    $byteCount = Get-HttpBootstrapSecretByteCount
    $bytes = New-Object 'System.Byte[]' $byteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        $base64 = [Convert]::ToBase64String($bytes)
        return $base64.TrimEnd([char[]]@([char]'=')).Replace("+", "-").Replace("/", "_")
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $rng.Dispose()
    }
}

function Escape-SqlLiteral([string]$Value) {
    return $Value.Replace("'", "''")
}

function Read-EnvMap([string]$Path) {
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $map
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }
        $idx = $trimmed.IndexOf("=")
        if ($idx -le 0) {
            continue
        }
        $key = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim()
        $map[$key] = $value
    }
    return $map
}

function Get-TicketboxBundledApplicationDatabaseConnection {
    param([Parameter(Mandatory = $true)][string]$DatabaseUrl)

    $persistedDatabaseUrl = ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    $libpqUrl = Assert-TicketboxLocalDatabaseUrl `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort
    $builder = New-Object System.UriBuilder($libpqUrl)
    $role = [Uri]::UnescapeDataString($builder.UserName)
    if (
        $role -cne $DbRole -and
        $role -cne $script:TicketboxBundledRuntimeDatabaseRole
    ) {
        throw "DATABASE_URL 的 PostgreSQL 角色不属于已登记的 legacy/runtime authority。"
    }
    $connection = Get-TicketboxLocalDatabaseConnection `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort `
        -ExpectedDatabase $DbName `
        -ExpectedRole $role
    $connection | Add-Member -NotePropertyName Role -NotePropertyValue $role
    return $connection
}

function New-BaseEnvLines([string]$DatabaseUrl) {
    $shutdownTimeoutSeconds = ConvertTo-TicketboxTimeoutSeconds $StopTimeoutMs
    $lines = @(
        "DATABASE_URL=$DatabaseUrl",
        "TICKETBOX_HOST=127.0.0.1",
        "TICKETBOX_PORT=$BackendPort",
        "XPJ_EXTRA_LOOPBACK_HOSTS=127.0.0.1:${BackendPort},localhost:${BackendPort},[::1]:${BackendPort}",
        "TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS=$shutdownTimeoutSeconds",
        "PG_DUMP_PATH=$(Join-Path $PgBin 'pg_dump.exe')",
        "PG_RESTORE_PATH=$(Join-Path $PgBin 'pg_restore.exe')",
        "OCR_DEFAULT_TIMEZONE=$Timezone"
    )
    if ($PublicBaseUrl.Trim().Length -gt 0) {
        $lines += "PUBLIC_BASE_URL=$PublicBaseUrl"
    }
    return $lines
}

function Test-PgDataProcessReady([int]$ProbeTimeoutSeconds) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $probeTimeoutMilliseconds = [int][Math]::Min(
            [long]$DatabaseToolTimeoutMs,
            [long][Math]::Max(1000, $ProbeTimeoutSeconds * 1000)
        )
        $statusResult = Invoke-TicketboxBoundedNativeProcess `
            -FilePath (Join-Path $PgBin "pg_ctl.exe") `
            -Arguments @('status', '-D', $PgData) `
            -TimeoutMilliseconds $probeTimeoutMilliseconds `
            -Label 'pg_ctl readiness status'
        if ($statusResult.ExitCode -ne 0) {
            return $false
        }
        $pidLines = @(Get-Content -LiteralPath (Join-Path $PgData "postmaster.pid") -ErrorAction SilentlyContinue)
        if ($pidLines.Count -lt 4 -or $pidLines[3].Trim() -ne [string]$PgPort) {
            return $false
        }
        $readyResult = Invoke-TicketboxBoundedNativeProcess `
            -FilePath (Join-Path $PgBin "pg_isready.exe") `
            -Arguments @('-h', '127.0.0.1', '-p', [string]$PgPort, '-q', '-t', [string]$ProbeTimeoutSeconds) `
            -TimeoutMilliseconds $probeTimeoutMilliseconds `
            -Label 'pg_isready readiness probe'
        return $readyResult.ExitCode -eq 0
    }
    finally {
        $ErrorActionPreference = $prev
    }
}

function Wait-PgReady {
    $deadline = New-TicketboxWaitDeadline $PostgresReadyTimeoutMs
    do {
        $remaining = [Math]::Max(1, $PostgresReadyTimeoutMs - $deadline.ElapsedMilliseconds)
        $probeBudget = [int][Math]::Min([long]$PostgresReadyPollIntervalMs, [long]$remaining)
        if (Test-PgDataProcessReady (ConvertTo-TicketboxTimeoutSeconds $probeBudget)) {
            return
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $PostgresReadyTimeoutMs `
        -PollMilliseconds $PostgresReadyPollIntervalMs)
    throw "PostgreSQL 服务未在 $PostgresReadyTimeoutMs ms 内就绪（127.0.0.1:$PgPort）。"
}

function Remove-TicketboxSensitiveFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "敏感临时文件路径不再是普通文件：$Path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "敏感临时文件不能是重解析点：$Path"
    }
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $Path) {
        throw "敏感临时文件删除后仍存在：$Path"
    }
}

function Get-PostgresBootstrapRecoveryPath {
    return Join-Path $AppData $script:PostgresBootstrapRecoveryFileName
}

function Assert-PostgresBootstrapPasswordValue([string]$Value, [string]$FieldName) {
    $allowedChars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    if ([string]::IsNullOrEmpty($Value) -or $Value.Length -ne $SecretByteCount) {
        throw "PostgreSQL bootstrap 恢复文件中的 $FieldName 长度无效。"
    }
    foreach ($character in $Value.ToCharArray()) {
        if ($allowedChars.IndexOf($character) -lt 0) {
            throw "PostgreSQL bootstrap 恢复文件中的 $FieldName 格式无效。"
        }
    }
}

function Assert-HttpBootstrapSecretValue([string]$Value) {
    $byteCount = Get-HttpBootstrapSecretByteCount
    $expectedLength = Get-HttpBootstrapSecretEncodedLength
    if ([string]::IsNullOrEmpty($Value) -or
        $Value.Length -ne $expectedLength -or
        $Value -cnotmatch '^[A-Za-z0-9_-]+$') {
        throw "PostgreSQL bootstrap 恢复文件中的 http_bootstrap_secret 格式无效。"
    }
    $paddingLength = (4 - ($Value.Length % 4)) % 4
    $padded = $Value.Replace("-", "+").Replace("_", "/") + ("=" * $paddingLength)
    try {
        $bytes = [Convert]::FromBase64String($padded)
    }
    catch {
        throw "PostgreSQL bootstrap 恢复文件中的 http_bootstrap_secret 格式无效。"
    }
    if ($bytes.Length -ne $byteCount) {
        throw "PostgreSQL bootstrap 恢复文件中的 http_bootstrap_secret 长度无效。"
    }
    $canonical = [Convert]::ToBase64String($bytes).TrimEnd(
        [char[]]@([char]'=')
    ).Replace("+", "-").Replace("/", "_")
    if ($canonical -cne $Value) {
        throw "PostgreSQL bootstrap 恢复文件中的 http_bootstrap_secret 编码无效。"
    }
}

function New-PostgresBootstrapRecoveryState {
    return [pscustomobject]@{
        SuperuserPassword = New-StrongPassword
        HttpBootstrapSecret = New-HttpBootstrapSecret
    }
}

function ConvertTo-PostgresBootstrapRecoveryPayload([object]$State) {
    Assert-PostgresBootstrapPasswordValue $State.SuperuserPassword "superuser_password"
    Assert-HttpBootstrapSecretValue $State.HttpBootstrapSecret
    return @(
        $State.SuperuserPassword
        "schema=$script:PostgresBootstrapRecoverySchema"
        "http_bootstrap_secret=$($State.HttpBootstrapSecret)"
    ) -join "`n"
}

function ConvertFrom-PostgresBootstrapRecoveryPayload([byte[]]$Bytes) {
    if ($null -eq $Bytes -or $Bytes.Length -eq 0 -or $Bytes.Length -gt 4096) {
        throw "PostgreSQL bootstrap 恢复文件大小无效。"
    }
    foreach ($value in $Bytes) {
        if ($value -gt 127) {
            throw "PostgreSQL bootstrap 恢复文件必须是 ASCII。"
        }
    }
    $text = [System.Text.Encoding]::ASCII.GetString($Bytes)
    if ($text.IndexOf("`r", [System.StringComparison]::Ordinal) -ge 0) {
        throw "PostgreSQL bootstrap 恢复文件换行格式无效。"
    }
    $lines = @($text.Split([char[]]@([char]10), [System.StringSplitOptions]::None))
    if ($lines.Count -ne 3 -or $lines[1] -cne "schema=$script:PostgresBootstrapRecoverySchema") {
        throw "PostgreSQL bootstrap 恢复文件结构无效。"
    }
    $bootstrapPrefix = "http_bootstrap_secret="
    if (-not $lines[2].StartsWith($bootstrapPrefix, [System.StringComparison]::Ordinal)) {
        throw "PostgreSQL bootstrap 恢复文件结构无效。"
    }
    $state = [pscustomobject]@{
        SuperuserPassword = $lines[0]
        HttpBootstrapSecret = $lines[2].Substring($bootstrapPrefix.Length)
    }
    Assert-PostgresBootstrapPasswordValue $state.SuperuserPassword "superuser_password"
    Assert-HttpBootstrapSecretValue $state.HttpBootstrapSecret
    return $state
}

function Assert-PostgresBootstrapRecoveryFileSecurity {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Accounts = $script:PostgresBootstrapAclAccounts,
        [string]$OwnerAccount = $script:PostgresBootstrapAclOwnerAccount
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "PostgreSQL bootstrap 恢复文件不存在或不是普通文件：$Path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "PostgreSQL bootstrap 恢复文件不能是重解析点：$Path"
    }
    $targetSids = @($Accounts | ForEach-Object { ConvertTo-TicketboxAccountSid $_ } | Sort-Object -Unique)
    if ($targetSids.Count -eq 0) {
        throw "PostgreSQL bootstrap 恢复文件缺少授权账户。"
    }
    $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount
    $acl = Get-TicketboxPathAcl $Path
    if (-not $acl.AreAccessRulesProtected -or
        (ConvertTo-TicketboxAccountSid $acl.Owner) -ne $expectedOwnerSid) {
        throw "PostgreSQL bootstrap 恢复文件 ACL owner 或继承状态不安全。"
    }
    $fullControl = [System.Security.AccessControl.FileSystemRights]::FullControl
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        $hasFullControl = ($rule.FileSystemRights -band $fullControl) -eq $fullControl
        if ($ruleSid -notin $targetSids -or $rule.IsInherited -or -not $hasFullControl -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]::None -or
            $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None) {
            throw "PostgreSQL bootstrap 恢复文件 ACL 含未授权规则。"
        }
    }
    foreach ($sid in $targetSids) {
        $matchingRules = @($acl.Access | Where-Object {
            $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $sid
        })
        if ($matchingRules.Count -eq 0) {
            throw "PostgreSQL bootstrap 恢复文件 ACL 缺少授权账户。"
        }
    }
}

function Read-PostgresBootstrapRecoveryState {
    param([Parameter(Mandatory = $true)][string]$Path)
    $pwfile = Get-PostgresBootstrapRecoveryPath
    if (-not (Test-TicketboxPathEquals $Path $pwfile)) {
        throw "PostgreSQL bootstrap 恢复文件路径不匹配当前 DataRoot。"
    }
    Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile
    try {
        $bytes = [System.IO.File]::ReadAllBytes($pwfile)
    }
    catch {
        throw "无法读取 PostgreSQL bootstrap 恢复文件。"
    }
    return ConvertFrom-PostgresBootstrapRecoveryPayload $bytes
}

function Remove-PostgresBootstrapRecoveryState {
    param([Parameter(Mandatory = $true)][string]$Path)
    $pwfile = Get-PostgresBootstrapRecoveryPath
    if (-not (Test-TicketboxPathEquals $Path $pwfile)) {
        throw "PostgreSQL bootstrap 恢复文件路径不匹配当前 DataRoot。"
    }
    $kind = Get-TicketboxPathEntryKindNoFollow $pwfile
    if ($kind -ceq "Missing") { return }
    if ($kind -cne "File") {
        throw "PostgreSQL bootstrap 恢复文件不是普通文件，拒绝退役。"
    }
    Assert-NoTicketboxAncestorReparsePoints $pwfile
    Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile
    Remove-TicketboxSensitiveFile $pwfile
    if ((Get-TicketboxPathEntryKindNoFollow $pwfile) -cne "Missing") {
        throw "PostgreSQL bootstrap 恢复文件退役后仍存在。"
    }
}

function Repair-PostgresBootstrapRecoveryFileAcl {
    $pwfile = Get-PostgresBootstrapRecoveryPath
    if ((Get-TicketboxPathEntryKindNoFollow $pwfile) -cne "File") {
        throw "PostgreSQL bootstrap 恢复文件不是普通文件，拒绝 ACL 恢复。"
    }

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalAppData = ConvertTo-TicketboxWin32CanonicalPath $AppData
    $expectedAppData = Join-Path $canonicalDataRoot "app"
    $expectedRecoveryPath = Join-Path `
        $canonicalAppData `
        $script:PostgresBootstrapRecoveryFileName
    if (
        -not (Test-TicketboxPathEquals $canonicalAppData $expectedAppData) -or
        -not (Test-TicketboxPathEquals $pwfile $expectedRecoveryPath)
    ) {
        throw "PostgreSQL bootstrap 恢复文件不在标准 DataRoot/app 域内。"
    }

    $acl = Get-TicketboxPathAcl $pwfile
    if ($acl.AreAccessRulesProtected) {
        [void](Read-PostgresBootstrapRecoveryState -Path $pwfile)
        return $false
    }

    # A trusted machine-wide installer can be interrupted after publishing the
    # bounded recovery payload but before converting its inherited DACL into a
    # protected one.  Before the first ACL write, prove the entire generic
    # first-install domain: protected DataRoot, exact inherited app directory,
    # exact inherited file, canonical bounded payload, and unchanged bytes.
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $canonicalDataRoot `
        -FullControlAccounts $script:PostgresBootstrapAclAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount
    Assert-TicketboxRecoverableInheritedDirectoryAcl `
        -Path $canonicalAppData `
        -FullControlAccounts $script:PostgresBootstrapAclAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount
    Assert-TicketboxRecoverableInheritedFileAcl `
        -Path $pwfile `
        -FullControlAccounts $script:PostgresBootstrapAclAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount

    try {
        $beforeBytes = [IO.File]::ReadAllBytes(
            (ConvertTo-TicketboxWin32ExtendedPath $pwfile)
        )
    }
    catch {
        throw "无法读取待恢复的 PostgreSQL bootstrap 恢复文件。"
    }
    [void](ConvertFrom-PostgresBootstrapRecoveryPayload $beforeBytes)

    Set-TicketboxExactFileAcl `
        -Path $pwfile `
        -Accounts $script:PostgresBootstrapAclAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount
    Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile
    $afterBytes = [IO.File]::ReadAllBytes(
        (ConvertTo-TicketboxWin32ExtendedPath $pwfile)
    )
    if (-not (Test-TicketboxWindowsByteArrayEquals $beforeBytes $afterBytes)) {
        throw "PostgreSQL bootstrap 恢复文件 ACL 恢复改变了受保护字节。"
    }
    [void](Read-PostgresBootstrapRecoveryState -Path $pwfile)
    return $true
}

function Protect-PostgresBootstrapRecoveryFileAfterAclNormalization {
    param(
        [Parameter(Mandatory = $true)][string[]]$ParentFullControlAccounts
    )

    $pwfile = Get-PostgresBootstrapRecoveryPath
    $pathKind = Get-TicketboxPathEntryKindNoFollow $pwfile
    if ($pathKind -ceq "Missing") {
        return $false
    }
    if ($pathKind -cne "File") {
        throw "PostgreSQL bootstrap 恢复路径不是普通文件，拒绝 ACL 收敛。"
    }

    $canonicalDataRoot = ConvertTo-TicketboxWin32CanonicalPath $DataRoot
    $canonicalAppData = ConvertTo-TicketboxWin32CanonicalPath $AppData
    if (
        -not (Test-TicketboxPathEquals `
            $canonicalAppData `
            (Join-Path $canonicalDataRoot "app")) -or
        -not (Test-TicketboxPathEquals `
            $pwfile `
            (Join-Path $canonicalAppData $script:PostgresBootstrapRecoveryFileName))
    ) {
        throw "PostgreSQL bootstrap 恢复文件越出标准 DataRoot/app 域。"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $canonicalAppData `
        -FullControlAccounts $ParentFullControlAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount

    $acl = Get-TicketboxPathAcl $pwfile
    if ($acl.AreAccessRulesProtected) {
        [void](Read-PostgresBootstrapRecoveryState -Path $pwfile)
        return $false
    }
    Assert-TicketboxRecoverableInheritedFileAcl `
        -Path $pwfile `
        -FullControlAccounts $ParentFullControlAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount
    $beforeBytes = [IO.File]::ReadAllBytes(
        (ConvertTo-TicketboxWin32ExtendedPath $pwfile)
    )
    [void](ConvertFrom-PostgresBootstrapRecoveryPayload $beforeBytes)

    Set-TicketboxExactFileAcl `
        -Path $pwfile `
        -Accounts $script:PostgresBootstrapAclAccounts `
        -OwnerAccount $script:PostgresBootstrapAclOwnerAccount
    Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile
    $afterBytes = [IO.File]::ReadAllBytes(
        (ConvertTo-TicketboxWin32ExtendedPath $pwfile)
    )
    if (-not (Test-TicketboxWindowsByteArrayEquals $beforeBytes $afterBytes)) {
        throw "AppData ACL 收敛改变了 PostgreSQL bootstrap 恢复字节。"
    }
    [void](Read-PostgresBootstrapRecoveryState -Path $pwfile)
    return $true
}

function Remove-PostgresBootstrapRecoveryTempIfPresent {
    $tempPath = (Get-PostgresBootstrapRecoveryPath) + ".tmp"
    if (-not (Test-Path -LiteralPath $tempPath)) {
        return
    }
    Remove-TicketboxSensitiveFile $tempPath
}

function Write-PostgresBootstrapRecoveryState([object]$State) {
    $pwfile = Get-PostgresBootstrapRecoveryPath
    $tempPath = "$pwfile.tmp"
    if (Test-Path -LiteralPath $pwfile) {
        throw "PostgreSQL bootstrap 恢复文件已存在，拒绝覆盖。"
    }
    Remove-PostgresBootstrapRecoveryTempIfPresent
    $payload = ConvertTo-PostgresBootstrapRecoveryPayload $State
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($payload)
    $stream = $null
    $moved = $false
    try {
        $stream = [System.IO.FileStream]::new(
            $tempPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None,
            4096,
            [System.IO.FileOptions]::WriteThrough
        )
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null

        Set-TicketboxExactFileAcl `
            -Path $tempPath `
            -Accounts $script:PostgresBootstrapAclAccounts `
            -OwnerAccount $script:PostgresBootstrapAclOwnerAccount
        Assert-PostgresBootstrapRecoveryFileSecurity -Path $tempPath
        Move-TicketboxFileAtomically -Source $tempPath -Destination $pwfile
        $moved = $true
        Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile
        $persisted = Read-PostgresBootstrapRecoveryState -Path $pwfile
        if ($persisted.SuperuserPassword -cne $State.SuperuserPassword -or
            $persisted.HttpBootstrapSecret -cne $State.HttpBootstrapSecret) {
            throw "PostgreSQL bootstrap 恢复文件持久化校验失败。"
        }
    }
    catch {
        if ($null -ne $stream) {
            $stream.Dispose()
            $stream = $null
        }
        if (Test-Path -LiteralPath $tempPath) {
            Remove-TicketboxSensitiveFile $tempPath
        }
        if ($moved -and (Test-Path -LiteralPath $pwfile)) {
            Remove-TicketboxSensitiveFile $pwfile
        }
        throw "无法安全持久化 PostgreSQL bootstrap 恢复文件。"
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Get-OrCreatePostgresBootstrapRecoveryState {
    Remove-PostgresBootstrapRecoveryTempIfPresent
    $pwfile = Get-PostgresBootstrapRecoveryPath
    if (Test-Path -LiteralPath $pwfile) {
        [void](Repair-PostgresBootstrapRecoveryFileAcl)
        return Read-PostgresBootstrapRecoveryState -Path $pwfile
    }
    $state = New-PostgresBootstrapRecoveryState
    Write-PostgresBootstrapRecoveryState $state
    return Read-PostgresBootstrapRecoveryState -Path $pwfile
}

function Remove-TicketboxEmptyPgDataBeforeInitdb {
    $pgDataKind = Get-TicketboxPathEntryKindNoFollow $PgData
    if ($pgDataKind -ceq "Missing") { return }
    if ($pgDataKind -cne "Directory") {
        throw "PostgreSQL 初始化目标不是普通目录，拒绝继续。"
    }

    $expectedPgData = Join-Path $DataRoot "pgdata"
    if (-not (Test-TicketboxPathEquals $PgData $expectedPgData)) {
        throw "PostgreSQL 初始化目标不在动态 DataRoot 契约位置。"
    }
    Assert-NoTicketboxReparsePoints $PgData
    if (@(Get-ChildItem -LiteralPath $PgData -Force).Count -ne 0) {
        throw "PostgreSQL 初始化目标含有未绑定恢复权威的内容，拒绝覆盖。"
    }

    Initialize-TicketboxExactTreeDeleteNativeMethods
    $expectedPgData = [IO.Path]::GetFullPath($expectedPgData).TrimEnd('\', '/')
    $expectedPgDataIdentity = @(
        [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($expectedPgData)
    )
    if ($expectedPgDataIdentity.Count -ne 2) {
        throw "PostgreSQL 空初始化目录身份无法固定。"
    }
    $expectedPgVersionPath = Join-Path $expectedPgData "PG_VERSION"
    $emptyCleanupGuard = {
        param($GuardedPath)
        $openedPath = [IO.Path]::GetFullPath($GuardedPath).TrimEnd('\', '/')
        if (-not [string]::Equals(
            $openedPath,
            $expectedPgData,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "PostgreSQL 空初始化目录句柄与已验证目标不一致。"
        }
        $openedIdentity = @(
            [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($openedPath)
        )
        if (
            $openedIdentity.Count -ne 2 -or
            [string]$openedIdentity[0] -cne [string]$expectedPgDataIdentity[0] -or
            [string]$openedIdentity[1] -cne [string]$expectedPgDataIdentity[1]
        ) {
            throw "PostgreSQL 空初始化目录身份在清理前发生变化。"
        }
        if (
            [TicketboxExactTreeDeleteNativeMethods]::InspectEntry(
                $expectedPgVersionPath
            ) -ne 0 -or
            [IO.Directory]::GetFileSystemEntries($openedPath).Length -ne 0
        ) {
            throw "PostgreSQL 空初始化目录在清理前已出现内容。"
        }
    }.GetNewClosure()
    Remove-TicketboxDataRootExact `
        -Path $PgData `
        -OnRootHandleAcquired $emptyCleanupGuard
    Write-Ok "已清理 PostgreSQL 空初始化断点。"
}

function Get-TicketboxNativeExitCodeEvidence {
    param([AllowNull()][object]$ExitCode)

    if ($null -eq $ExitCode) {
        return $null
    }
    $text = [Convert]::ToString(
        $ExitCode,
        [Globalization.CultureInfo]::InvariantCulture
    )
    $numeric = 0L
    if (-not [Int64]::TryParse(
        $text,
        [Globalization.NumberStyles]::Integer,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$numeric
    )) {
        throw "原生进程退出码不是十进制整数：$text"
    }
    if ($numeric -lt [Int32]::MinValue -or $numeric -gt [UInt32]::MaxValue) {
        throw "原生进程退出码超出 32-bit Windows 范围：$numeric"
    }
    $unsigned = if ($numeric -lt 0) {
        [uint64]($numeric + 4294967296L)
    } else {
        [uint64]$numeric
    }
    $unsigned32 = [uint32]$unsigned
    $signed32 = [BitConverter]::ToInt32(
        [BitConverter]::GetBytes($unsigned32),
        0
    )
    return [pscustomobject]@{
        Unsigned = [uint64]$unsigned32
        Signed = [int64]$signed32
        Hex = ("0x{0:X8}" -f $unsigned32)
    }
}

function New-TicketboxInitdbFailure {
    param(
        [Parameter(Mandatory = $true)][string]$FailureKind,
        [AllowNull()][object]$ExitCode
    )

    $nativeExit = Get-TicketboxNativeExitCodeEvidence $ExitCode
    $exitText = if ($null -eq $nativeExit) {
        "unavailable"
    } else {
        "{0} ({1}; signed={2})" -f `
            $nativeExit.Unsigned,
            $nativeExit.Hex,
            $nativeExit.Signed
    }
    $failure = [InvalidOperationException]::new(
        "initdb 未完成（kind=$FailureKind, exit=$exitText）。"
    )
    $failure.Data["TicketboxInstallPublicFailureCode"] =
        "postgres_cluster_initialization_failed"
    if ($null -ne $nativeExit) {
        $failure.Data["TicketboxNativeExitCodeUnsigned"] = $nativeExit.Unsigned
        $failure.Data["TicketboxNativeExitCodeSigned"] = $nativeExit.Signed
        $failure.Data["TicketboxNativeExitCodeHex"] = $nativeExit.Hex
    }
    return $failure
}

function Initialize-PgClusterIfNeeded {
    param(
        [Parameter(Mandatory = $true)][object]$CompensationAuthority
    )

    Assert-TicketboxInstallServiceCompensationAuthority `
        $CompensationAuthority

    $pgVersionPath = Join-Path $PgData "PG_VERSION"
    $pwfile = Get-PostgresBootstrapRecoveryPath
    if ((Test-Path -LiteralPath $pgVersionPath) -and
        -not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        throw "PostgreSQL PG_VERSION 不是普通文件，拒绝继续。"
    }
    if ((Test-Path -LiteralPath $EnvPath) -and
        -not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
        throw ".env 路径不是普通文件，拒绝继续：$EnvPath"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $pwfile) -ceq "File") {
        [void](Repair-PostgresBootstrapRecoveryFileAcl)
    }
    $existingEnv = Read-EnvMap $EnvPath
    $hasDatabaseUrl = $existingEnv.ContainsKey("DATABASE_URL")
    if (Test-Path -LiteralPath $pgVersionPath -PathType Leaf) {
        if (Test-Path -LiteralPath $pwfile) {
            [void](Read-PostgresBootstrapRecoveryState -Path $pwfile)
        }
        elseif (-not $hasDatabaseUrl) {
            throw "既有 PostgreSQL 簇缺少 .env 和安全 bootstrap 恢复文件，拒绝继续。"
        }
        Set-TicketboxPostgresqlLoopbackConfiguration -PgData $PgData -Port $PgPort
        Write-Ok "发现既有 PG 簇，跳过 initdb：$PgData"
        return $null
    }
    if (Test-Path -LiteralPath $EnvPath -PathType Leaf) {
        throw "发现 .env 但 PostgreSQL 簇不存在，拒绝重新初始化并覆盖既有安装身份。"
    }

    if (
        (Test-Path -LiteralPath $pwfile -PathType Leaf) -and
        (Test-Path -LiteralPath $PgData -PathType Container) -and
        @(Get-ChildItem -LiteralPath $PgData -Force).Count -gt 0
    ) {
        $bootstrapRecoveryState = Read-PostgresBootstrapRecoveryState -Path $pwfile
        $expectedBootstrapRecoveryText =
            ConvertTo-PostgresBootstrapRecoveryPayload $bootstrapRecoveryState
        if (Test-Path -LiteralPath (Join-Path $PgData "postmaster.pid")) {
            throw "未完成的 PostgreSQL 初始化仍含 postmaster.pid，拒绝自动清理。"
        }
        $expectedPgData = Join-Path $DataRoot "pgdata"
        if (-not (Test-TicketboxPathEquals $PgData $expectedPgData)) {
            throw "PostgreSQL 部分初始化目录不在动态 DataRoot 契约位置。"
        }
        Assert-NoTicketboxReparsePoints $PgData
        Initialize-TicketboxExactTreeDeleteNativeMethods
        $expectedPgData = [IO.Path]::GetFullPath($expectedPgData).TrimEnd('\', '/')
        $expectedPgDataIdentity = @(
            [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($expectedPgData)
        )
        if ($expectedPgDataIdentity.Count -ne 2) {
            throw "PostgreSQL 部分初始化目录身份无法固定。"
        }
        $expectedPgVersionPath = Join-Path $expectedPgData "PG_VERSION"
        # Revalidate ACL, structure, and secret bytes immediately before the
        # root handle is opened.  The native callback below intentionally uses
        # only BCL/native helpers so it also works in Windows PowerShell 5.1.
        $revalidatedBootstrapRecoveryState = Read-PostgresBootstrapRecoveryState -Path $pwfile
        if (
            (ConvertTo-PostgresBootstrapRecoveryPayload $revalidatedBootstrapRecoveryState) -cne
            $expectedBootstrapRecoveryText
        ) {
            throw "PostgreSQL bootstrap 恢复文件在部分初始化清理前发生变化。"
        }
        $partialCleanupGuard = {
            param($GuardedPath)
            $openedPath = [IO.Path]::GetFullPath($GuardedPath).TrimEnd('\', '/')
            if (-not [string]::Equals(
                $openedPath,
                $expectedPgData,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "PostgreSQL 部分初始化目录句柄与已验证目标不一致。"
            }
            $openedIdentity = @(
                [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($openedPath)
            )
            if (
                $openedIdentity.Count -ne 2 -or
                [string]$openedIdentity[0] -cne [string]$expectedPgDataIdentity[0] -or
                [string]$openedIdentity[1] -cne [string]$expectedPgDataIdentity[1]
            ) {
                throw "PostgreSQL 部分初始化目录身份在清理前发生变化。"
            }
            if (
                [TicketboxExactTreeDeleteNativeMethods]::InspectEntry(
                    $expectedPgVersionPath
                ) -ne 0
            ) {
                throw "PostgreSQL 部分初始化目录在清理前已变成完整数据簇。"
            }
            if (
                [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($pwfile) -ne 1 -or
                [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                    $pwfile,
                    4096
                ) -cne $expectedBootstrapRecoveryText
            ) {
                throw "PostgreSQL bootstrap 恢复权威在部分初始化清理前发生变化。"
            }
        }.GetNewClosure()
        Remove-TicketboxDataRootExact `
            -Path $PgData `
            -OnRootHandleAcquired $partialCleanupGuard
        Write-Ok "已清理受恢复凭据绑定的 PostgreSQL 部分初始化目录。"
    }

    Write-Step "初始化 PostgreSQL 簇"
    Remove-TicketboxEmptyPgDataBeforeInitdb
    if ((Get-TicketboxPathEntryKindNoFollow $PgData) -cne "Missing") {
        throw "PostgreSQL 初始化前无法证明 PGDATA 不存在。"
    }
    $bootstrapState = Get-OrCreatePostgresBootstrapRecoveryState
    $initResult = Invoke-TicketboxServiceOwnedInitdb `
        -BootstrapState $bootstrapState `
        -CompensationAuthority $CompensationAuthority
    if ($initResult.ExitCode -ne 0) {
        throw (New-TicketboxInitdbFailure `
            -FailureKind "native_process_failed" `
            -ExitCode $initResult.ExitCode)
    }
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        throw (New-TicketboxInitdbFailure `
            -FailureKind "pg_version_missing" `
            -ExitCode $initResult.ExitCode)
    }
    Set-TicketboxPostgresqlLoopbackConfiguration -PgData $PgData -Port $PgPort
    Write-Ok "PG 簇已初始化（loopback-only, scram-sha-256）。"
    return $null
}
