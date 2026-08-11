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

function Write-EnvNoBom([string]$Path, [string[]]$Lines) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $text = [string]::Join([Environment]::NewLine, $Lines) + [Environment]::NewLine
    Write-TicketboxFileAtomically -Path $Path -Bytes ($utf8NoBom.GetBytes($text))
}

function New-StrongPassword {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object 'System.Byte[]' $SecretByteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
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
    }
    finally {
        $rng.Dispose()
    }
    $base64 = [Convert]::ToBase64String($bytes)
    return $base64.TrimEnd([char[]]@([char]'=')).Replace("+", "-").Replace("/", "_")
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

function Set-EnvDatabaseUrl([string]$Path, [string]$DatabaseUrl) {
    $lines = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    $matches = @(
        for ($index = 0; $index -lt $lines.Count; $index++) {
            if ([string]$lines[$index] -match '^\s*DATABASE_URL\s*=') { $index }
        }
    )
    if ($matches.Count -ne 1) {
        throw ".env 必须且只能包含一条 DATABASE_URL。"
    }
    $lines[$matches[0]] = "DATABASE_URL=$DatabaseUrl"
    Write-EnvNoBom -Path $Path -Lines $lines
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

function Invoke-Psql([string]$Database, [string]$Sql, [string]$Password) {
    if ([string]::IsNullOrWhiteSpace($Password)) {
        throw "批处理 psql 必须使用显式非空口令。"
    }
    $encodedDatabase = [System.Uri]::EscapeDataString($Database)
    $databaseUrl = "postgresql://postgres@127.0.0.1:${PgPort}/${encodedDatabase}?require_auth=scram-sha-256"
    $psql = Join-Path $PgBin "psql.exe"
    $result = Invoke-TicketboxWithPgPassFile `
        -DatabaseUrl $databaseUrl `
        -Password $Password `
        -Action {
            param([string]$ProtectedDatabaseUrl)
            $args = @(
                "-X", "-w", "-v", "ON_ERROR_STOP=1",
                "--dbname", $ProtectedDatabaseUrl, "-tA"
            )
            $commandResult = Invoke-TicketboxBoundedNativeProcess `
                -FilePath $psql `
                -Arguments $args `
                -StandardInputText ($Sql + "`n") `
                -TimeoutMilliseconds $DatabaseToolTimeoutMs `
                -Label "psql database command"
            return [pscustomobject]@{
                Output = @($commandResult.StandardOutput -split "`r?`n")
                ExitCode = $commandResult.ExitCode
            }
        }
    if ($null -eq $result.ExitCode -or $result.ExitCode -ne 0) {
        throw "psql 执行失败（db=$Database, exit=$($result.ExitCode)）。"
    }
    return ($result.Output | Out-String).Trim()
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
        RolePassword = New-StrongPassword
        HttpBootstrapSecret = New-HttpBootstrapSecret
    }
}

function ConvertTo-PostgresBootstrapRecoveryPayload([object]$State) {
    Assert-PostgresBootstrapPasswordValue $State.SuperuserPassword "superuser_password"
    Assert-PostgresBootstrapPasswordValue $State.RolePassword "role_password"
    Assert-HttpBootstrapSecretValue $State.HttpBootstrapSecret
    return @(
        $State.SuperuserPassword
        "schema=$script:PostgresBootstrapRecoverySchema"
        "role_password=$($State.RolePassword)"
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
    if ($lines.Count -ne 4 -or $lines[1] -cne "schema=$script:PostgresBootstrapRecoverySchema") {
        throw "PostgreSQL bootstrap 恢复文件结构无效。"
    }
    $rolePrefix = "role_password="
    $bootstrapPrefix = "http_bootstrap_secret="
    if (-not $lines[2].StartsWith($rolePrefix, [System.StringComparison]::Ordinal) -or
        -not $lines[3].StartsWith($bootstrapPrefix, [System.StringComparison]::Ordinal)) {
        throw "PostgreSQL bootstrap 恢复文件结构无效。"
    }
    $state = [pscustomobject]@{
        SuperuserPassword = $lines[0]
        RolePassword = $lines[2].Substring($rolePrefix.Length)
        HttpBootstrapSecret = $lines[3].Substring($bootstrapPrefix.Length)
    }
    Assert-PostgresBootstrapPasswordValue $state.SuperuserPassword "superuser_password"
    Assert-PostgresBootstrapPasswordValue $state.RolePassword "role_password"
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
    $pwfile = Get-PostgresBootstrapRecoveryPath
    Assert-PostgresBootstrapRecoveryFileSecurity -Path $pwfile
    try {
        $bytes = [System.IO.File]::ReadAllBytes($pwfile)
    }
    catch {
        throw "无法读取 PostgreSQL bootstrap 恢复文件。"
    }
    return ConvertFrom-PostgresBootstrapRecoveryPayload $bytes
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
        [void](Read-PostgresBootstrapRecoveryState)
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
    [void](Read-PostgresBootstrapRecoveryState)
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
        [void](Read-PostgresBootstrapRecoveryState)
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
    [void](Read-PostgresBootstrapRecoveryState)
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
        $persisted = Read-PostgresBootstrapRecoveryState
        if ($persisted.SuperuserPassword -cne $State.SuperuserPassword -or
            $persisted.RolePassword -cne $State.RolePassword -or
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
        return Read-PostgresBootstrapRecoveryState
    }
    $state = New-PostgresBootstrapRecoveryState
    Write-PostgresBootstrapRecoveryState $state
    return Read-PostgresBootstrapRecoveryState
}

function Assert-TicketboxPostgresAutoConfigurationSafe {
    $autoConfigPath = Join-Path $PgData "postgresql.auto.conf"
    if (-not (Test-Path -LiteralPath $autoConfigPath -PathType Leaf)) {
        return
    }
    $autoConfig = [System.IO.File]::ReadAllText($autoConfigPath, [System.Text.Encoding]::ASCII)
    if ($autoConfig -match '(?m)^\s*(?:listen_addresses|port)\s*=') {
        throw "postgresql.auto.conf 覆盖了安装器的 loopback/端口边界；请先撤销对应 ALTER SYSTEM 设置。"
    }
}

function Set-TicketboxPostgresInstallerConfiguration {
    $configPath = Join-Path $PgData "postgresql.conf"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "PostgreSQL 簇缺少 postgresql.conf，拒绝继续。"
    }
    $beginMarker = "# BEGIN Ticketbox installer overrides"
    $endMarker = "# END Ticketbox installer overrides"
    $legacyMarker = "# Ticketbox installer overrides"
    $newLine = [Environment]::NewLine
    $block = @(
        $beginMarker
        "listen_addresses = '127.0.0.1'"
        "port = $PgPort"
        $endMarker
    ) -join $newLine
    Assert-TicketboxPostgresAutoConfigurationSafe
    $content = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::ASCII)
    $markerIndex = $content.IndexOf($beginMarker, [System.StringComparison]::Ordinal)
    if ($markerIndex -ge 0) {
        if (
            $content.IndexOf(
                $beginMarker,
                $markerIndex + $beginMarker.Length,
                [System.StringComparison]::Ordinal
            ) -ge 0 -or
            $content.IndexOf($legacyMarker, [System.StringComparison]::Ordinal) -ge 0
        ) {
            throw "PostgreSQL installer 配置块重复，拒绝歧义迁移。"
        }
        $endMarkerIndex = $content.IndexOf(
            $endMarker,
            $markerIndex + $beginMarker.Length,
            [System.StringComparison]::Ordinal
        )
        if ($endMarkerIndex -lt 0) {
            throw "PostgreSQL installer 配置块缺少结束标记，拒绝截断现有配置。"
        }
        $suffixIndex = $endMarkerIndex + $endMarker.Length
        $contentWithoutManagedBlock =
            $content.Substring(0, $markerIndex) +
            $content.Substring($suffixIndex)
    }
    else {
        $legacyIndex = $content.IndexOf($legacyMarker, [System.StringComparison]::Ordinal)
        if ($legacyIndex -ge 0) {
            $escapedLegacyMarker = [regex]::Escape($legacyMarker)
            $listenLine = "[ `t]*listen_addresses[ `t]*=[^`r`n]*`r?`n"
            $portLine = "[ `t]*port[ `t]*=[^`r`n]*(?:`r?`n)?"
            $legacyPatterns = @(
                "(?m)^$escapedLegacyMarker`r?`n$listenLine$portLine",
                "(?m)^$escapedLegacyMarker`r?`n$portLine$listenLine"
            )
            $legacyMatch = $null
            foreach ($pattern in $legacyPatterns) {
                $candidate = [regex]::Match($content, $pattern)
                if ($candidate.Success) {
                    if ($null -ne $legacyMatch) {
                        throw "PostgreSQL 旧 installer 配置块存在多种匹配，拒绝歧义迁移。"
                    }
                    $legacyMatch = $candidate
                }
            }
            if ($null -eq $legacyMatch -or $legacyMatch.Index -ne $legacyIndex) {
                throw "PostgreSQL 旧 installer 配置块不完整，拒绝截断现有配置。"
            }
            $contentWithoutManagedBlock =
                $content.Substring(0, $legacyMatch.Index) +
                $content.Substring($legacyMatch.Index + $legacyMatch.Length)
        }
        else {
            $contentWithoutManagedBlock = $content
        }
    }
    $updated = $contentWithoutManagedBlock.TrimEnd() + $newLine + $newLine + $block + $newLine
    Write-TicketboxFileAtomically `
        -Path $configPath `
        -Bytes ([System.Text.Encoding]::ASCII.GetBytes($updated))
    $persisted = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::ASCII)
    if (-not $persisted.TrimEnd().EndsWith($block, [System.StringComparison]::Ordinal)) {
        throw "PostgreSQL installer 配置持久化校验失败。"
    }
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
    param([scriptblock]$InitdbInvoker)

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
            [void](Read-PostgresBootstrapRecoveryState)
        }
        elseif (-not $hasDatabaseUrl) {
            throw "既有 PostgreSQL 簇缺少 .env 和安全 bootstrap 恢复文件，拒绝继续。"
        }
        Set-TicketboxPostgresInstallerConfiguration
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
        $bootstrapRecoveryState = Read-PostgresBootstrapRecoveryState
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
        $revalidatedBootstrapRecoveryState = Read-PostgresBootstrapRecoveryState
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
    $initResult = if ($null -ne $InitdbInvoker) {
        & $InitdbInvoker $bootstrapState
    }
    else {
        Invoke-TicketboxBoundedNativeProcess `
            -FilePath (Join-Path $PgBin "initdb.exe") `
            -Arguments @(
                '-D', $PgData,
                '-U', 'postgres',
                '--auth-local=scram-sha-256',
                '--auth-host=scram-sha-256',
                '--encoding=UTF8',
                '--no-locale',
                "--pwfile=$pwfile"
            ) `
            -TimeoutMilliseconds $DatabaseToolTimeoutMs `
            -Label 'initdb'
    }
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
    Set-TicketboxPostgresInstallerConfiguration
    Write-Ok "PG 簇已初始化（loopback-only, scram-sha-256）。"
    return $null
}

function Prepare-DatabaseIfNeeded {
    param(
        [AllowNull()][object]$BootstrapState,
        [switch]$PreserveBootstrapRecovery
    )
    $existingEnv = Read-EnvMap $EnvPath
    $pwfile = Get-PostgresBootstrapRecoveryPath
    $recoveryState = $null
    if (Test-Path -LiteralPath $pwfile) {
        $recoveryState = Read-PostgresBootstrapRecoveryState
    }
    if ($existingEnv.ContainsKey("DATABASE_URL")) {
        $connection = Get-TicketboxLocalDatabaseConnection `
            -DatabaseUrl $existingEnv["DATABASE_URL"] `
            -PgPort $PgPort `
            -ExpectedDatabase $DbName `
            -ExpectedRole $DbRole
        if ($existingEnv["DATABASE_URL"] -cne $connection.PersistedDatabaseUrl) {
            Set-EnvDatabaseUrl `
                -Path $EnvPath `
                -DatabaseUrl $connection.PersistedDatabaseUrl
            $existingEnv = Read-EnvMap $EnvPath
        }
        if ($null -ne $recoveryState -and -not $PreserveBootstrapRecovery) {
            if ($connection.Password -cne $recoveryState.RolePassword -or
                -not $existingEnv.ContainsKey("ENABLE_HTTP_BOOTSTRAP") -or
                $existingEnv["ENABLE_HTTP_BOOTSTRAP"] -cne "true" -or
                -not $existingEnv.ContainsKey("HTTP_BOOTSTRAP_SECRET") -or
                $existingEnv["HTTP_BOOTSTRAP_SECRET"] -cne $recoveryState.HttpBootstrapSecret) {
                throw ".env 与 PostgreSQL bootstrap 恢复状态不一致，拒绝删除恢复文件。"
            }
        }
        Assert-TicketboxConnectedPostgresDataRoot `
            -PsqlPath (Join-Path $PgBin "psql.exe") `
            -DatabaseUrl $connection.DatabaseUrl `
            -ExpectedDataRoot $PgData `
            -ExpectedPort $PgPort `
            -Password $connection.Password `
            -TimeoutMilliseconds $DatabaseToolTimeoutMs
        if ($null -ne $recoveryState -and -not $PreserveBootstrapRecovery) {
            Remove-TicketboxSensitiveFile $pwfile
        }
        Write-Ok "发现既有 .env，沿用 DATABASE_URL。"
        return $connection.PersistedDatabaseUrl
    }
    if ($null -eq $recoveryState) {
        throw "既有 PostgreSQL 簇缺少 $EnvPath，且没有安全 bootstrap 恢复文件，拒绝继续。"
    }

    Write-Step "创建应用角色和数据库"
    $rolePassword = $recoveryState.RolePassword
    $rolePwdSql = Escape-SqlLiteral $rolePassword
    $roleNameSql = Escape-SqlLiteral $DbRole
    $databaseNameSql = Escape-SqlLiteral $DbName
    $roleExists = (
        Invoke-Psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname='$roleNameSql'" `
            $recoveryState.SuperuserPassword
    ) -eq "1"
    if (-not $roleExists) {
        Invoke-Psql "postgres" "CREATE ROLE `"$DbRole`" LOGIN PASSWORD '$rolePwdSql'" `
            $recoveryState.SuperuserPassword | Out-Null
    }
    else {
        Invoke-Psql "postgres" "ALTER ROLE `"$DbRole`" WITH LOGIN PASSWORD '$rolePwdSql'" `
            $recoveryState.SuperuserPassword | Out-Null
    }
    $databaseOwner = Invoke-Psql "postgres" `
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='$databaseNameSql'" `
        $recoveryState.SuperuserPassword
    if ([string]::IsNullOrWhiteSpace($databaseOwner)) {
        Invoke-Psql "postgres" "CREATE DATABASE `"$DbName`" OWNER `"$DbRole`" ENCODING 'UTF8'" `
            $recoveryState.SuperuserPassword | Out-Null
    }
    elseif ($databaseOwner -cne $DbRole) {
        throw "既有应用数据库 owner 不是预期角色，拒绝接管。"
    }
    $databaseUrl = "postgresql+psycopg://${DbRole}:${rolePassword}@127.0.0.1:${PgPort}/${DbName}?require_auth=scram-sha-256"
    $lines = (New-BaseEnvLines $databaseUrl) + @(
        "ENABLE_HTTP_BOOTSTRAP=true",
        "HTTP_BOOTSTRAP_SECRET=$($recoveryState.HttpBootstrapSecret)"
    )
    Write-EnvNoBom -Path $EnvPath -Lines $lines
    $persistedEnv = Read-EnvMap $EnvPath
    if (-not $persistedEnv.ContainsKey("DATABASE_URL") -or
        $persistedEnv["DATABASE_URL"] -cne $databaseUrl -or
        -not $persistedEnv.ContainsKey("ENABLE_HTTP_BOOTSTRAP") -or
        $persistedEnv["ENABLE_HTTP_BOOTSTRAP"] -cne "true" -or
        -not $persistedEnv.ContainsKey("HTTP_BOOTSTRAP_SECRET") -or
        $persistedEnv["HTTP_BOOTSTRAP_SECRET"] -cne $recoveryState.HttpBootstrapSecret) {
        throw "首次安装 .env 持久化校验失败。"
    }
    $connection = Get-TicketboxLocalDatabaseConnection `
        -DatabaseUrl $persistedEnv["DATABASE_URL"] `
        -PgPort $PgPort `
        -ExpectedDatabase $DbName `
        -ExpectedRole $DbRole
    Assert-TicketboxConnectedPostgresDataRoot `
        -PsqlPath (Join-Path $PgBin "psql.exe") `
        -DatabaseUrl $connection.DatabaseUrl `
        -ExpectedDataRoot $PgData `
        -ExpectedPort $PgPort `
        -Password $connection.Password `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs
    if (-not $PreserveBootstrapRecovery) {
        Remove-TicketboxSensitiveFile $pwfile
    }
    Write-Ok "已写入首次安装 .env。"
    return $databaseUrl
}

function Invoke-TicketboxPreservedDataReinstallBackup {
    param(
        [Parameter(Mandatory = $true)][string]$TargetDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 99)][int]$ExpectedPgMajor
    )
    foreach ($required in @($PgCtl, $PgReady, $Psql, $PgDump, $PgRestore)) {
        Assert-File $required (Split-Path -Leaf $required)
    }
    Assert-NoTicketboxAncestorReparsePoints $DataRoot
    Assert-NoTicketboxReparsePoints $DataRoot
    $pgVersionPath = Join-Path $PgData "PG_VERSION"
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        throw "保留数据重装缺少 PG_VERSION。"
    }
    $clusterMajorText = [System.IO.File]::ReadAllText(
        $pgVersionPath,
        [System.Text.Encoding]::UTF8
    ).Trim()
    $clusterMajor = 0
    if (
        -not [int]::TryParse($clusterMajorText, [ref]$clusterMajor) -or
        $clusterMajor -ne $ExpectedPgMajor
    ) {
        throw "保留数据重装的 PostgreSQL major 与目标运行时不兼容。"
    }
    $environment = Read-EnvMap $EnvPath
    if (-not $environment.ContainsKey("DATABASE_URL")) {
        throw "保留数据重装的 .env 缺少 DATABASE_URL。"
    }
    $connection = Get-TicketboxBundledApplicationDatabaseConnection `
        -DatabaseUrl $environment["DATABASE_URL"]

    if (-not (Test-TicketboxServiceExists $PgServiceName)) {
        throw "保留数据重装备份必须由已验证的临时 PostgreSQL SCM 服务运行。"
    }
    Assert-TicketboxReleaseServiceIdentity `
        -Name $PgServiceName `
        -InstalledConfig $ReleaseConfig `
        -TargetConfig $ReleaseConfig | Out-Null
    Assert-TicketboxPgServiceCommand `
        -Name $PgServiceName `
        -ExpectedExecutable $PgCtl `
        -ExpectedServiceName $PgServiceName `
        -ExpectedDataRoot $PgData
    $serviceState = Wait-TicketboxServiceSettledState `
        -Name $PgServiceName `
        @ServiceWaitArguments
    if ($serviceState -ne "running") {
        throw "保留数据重装的临时 PostgreSQL SCM 服务未处于 running 状态。"
    }

    New-Item -ItemType Directory -Force -Path $TargetDirectory | Out-Null
    Set-TicketboxExactDirectoryAcl `
        -Path $TargetDirectory `
        -Accounts @("SYSTEM", "BUILTIN\Administrators")
    Wait-PgReady
    Assert-TicketboxConnectedPostgresDataRoot `
        -PsqlPath $Psql `
        -DatabaseUrl $connection.DatabaseUrl `
        -ExpectedDataRoot $PgData `
        -ExpectedPort $PgPort `
        -Password $connection.Password `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs

    $backupPath = ""
    $stamp = Get-Date -Format "yyyyMMdd-HHmmssfff"
    $backupPath = Join-Path `
        $TargetDirectory `
        "ticketbox-pre-upgrade-installer-$stamp.dump"
    $temporary = "$backupPath.tmp"
    $dumpResult = Invoke-TicketboxPgDumpCustom `
        -PgDumpPath $PgDump `
        -DatabaseUrl $connection.DatabaseUrl `
        -OutputPath $temporary `
        -Password $connection.Password `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs
    if ($dumpResult -ne 0) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw "保留数据重装的升级前 pg_dump 失败。"
    }
    Sync-TicketboxFileDurable $temporary
    Set-TicketboxExactFileAcl `
        -Path $temporary `
        -Accounts @("SYSTEM", "BUILTIN\Administrators")
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $restoreRc = Invoke-TicketboxPgRestoreList `
            -PgRestorePath $PgRestore `
            -ArchivePath $temporary `
            -TimeoutMilliseconds $DatabaseToolTimeoutMs
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($restoreRc -ne 0) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw "保留数据重装的升级前备份校验失败。"
    }
    Move-TicketboxFileDurable $temporary $backupPath
    Set-TicketboxExactFileAcl `
        -Path $backupPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators")
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "保留数据重装未生成可验证升级前备份。"
    }
    return $backupPath
}

function Invoke-PreUpgradeBackupIfNeeded {
    $envMap = Read-EnvMap $EnvPath
    if (-not $envMap.ContainsKey("DATABASE_URL")) {
        if (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION")) {
            [void](Read-PostgresBootstrapRecoveryState)
            Write-Ok "发现未完成的 PostgreSQL bootstrap，跳过尚不可用的升级备份并继续恢复。"
        }
        return
    }
    if ($PreUpgradeBackupAlreadyCompleted) {
        Write-Ok "升级预检回执已证明备份完成，不重复创建服务层备份。"
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION"))) {
        return
    }
    $connection = Get-TicketboxBundledApplicationDatabaseConnection `
        -DatabaseUrl $envMap["DATABASE_URL"]

    Write-Step "创建服务层升级前备份"
    if (-not (Service-Exists $PgServiceName)) {
        Register-PgService
    }
    Start-TicketboxOwnedServiceIfExists `
        -Name $PgServiceName `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $PgServiceName) `
        @ServiceWaitArguments | Out-Null
    Wait-PgReady
    Assert-TicketboxConnectedPostgresDataRoot `
        -PsqlPath (Join-Path $PgBin "psql.exe") `
        -DatabaseUrl $connection.DatabaseUrl `
        -ExpectedDataRoot $PgData `
        -ExpectedPort $PgPort `
        -Password $connection.Password `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs

    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $target = Join-Path $BackupDir "ticketbox-pre-upgrade-installer-$stamp.dump"
    $temp = "$target.tmp"
    $dumpResult = Invoke-TicketboxPgDumpCustom `
        -PgDumpPath (Join-Path $PgBin "pg_dump.exe") `
        -DatabaseUrl $connection.DatabaseUrl `
        -OutputPath $temp `
        -Password $connection.Password `
        -TimeoutMilliseconds $DatabaseToolTimeoutMs
    if ($dumpResult -ne 0) {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        throw "升级前 pg_dump 失败，拒绝启动新后端。请检查 $LogDir 与 PostgreSQL 服务。"
    }
    $nativeErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $restoreRc = Invoke-TicketboxPgRestoreList `
            -PgRestorePath (Join-Path $PgBin "pg_restore.exe") `
            -ArchivePath $temp `
            -TimeoutMilliseconds $DatabaseToolTimeoutMs
    }
    finally {
        $ErrorActionPreference = $nativeErrorPreference
    }
    if ($restoreRc -ne 0) {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        throw "升级前备份校验失败，拒绝启动新后端。"
    }
    Move-Item -LiteralPath $temp -Destination $target -Force
    Write-Ok "升级前备份已写入：$target"
}
