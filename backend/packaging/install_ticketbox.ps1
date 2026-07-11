# 小票夹后端 · 一键安装向导（档 A，本机 PostgreSQL）
#
# 给「会装软件但不写命令行」的自托管用户：把已装好的 PostgreSQL + 本目录的
# ticketbox-backend.exe 一步配好——建应用角色/库、生成 .env、初始化数据库、
# 创建 owner 身份、装开机自启任务。
#
#   右键「用 PowerShell 运行」，或：
#   powershell -ExecutionPolicy Bypass -File install_ticketbox.ps1
#   非交互：加 -NonInteractive -PostgresSuperPasswordFile <受保护的一次性文件>；
#   既有应用角色还需 -PostgresRolePasswordFile <另一受保护的一次性文件>。文件是单行 UTF-8，
#   ACL 必须断继承且仅授权当前用户/SYSTEM/Administrators，读取后会立即验证删除。
#
# 设计红线（见 docs/runbook/POSTGRES_MIGRATION.md §3「表属主陷阱」）：
#   建角色/建库用超级用户，但**建表只能由应用角色 ticketbox 连接执行**——所以
#   这里只用超级用户建空角色+空库，表结构交给 EXE 首次启动（以 ticketbox 连）来建，
#   绝不用超级用户灌表，否则 owner 错位、下一个 ALTER 迁移启动即崩。
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ExePath = "",
    [string]$DbHost = "127.0.0.1",
    [int]$DbPort = 0,
    [string]$DbName = "",
    [string]$DbRole = "",
    [string]$SuperUser = "postgres",
    [string]$PostgresSuperPasswordFile = "",
    [string]$PostgresRolePasswordFile = "",
    [switch]$NonInteractive,
    [int]$Port = 0,
    [ValidateRange(0, 600000)]
    [int]$BackendReadyTimeoutMs = 0,
    [ValidateRange(0, 60000)]
    [int]$BackendHealthRequestTimeoutMs = 0,
    [ValidateRange(0, 10000)]
    [int]$BackendReadyPollIntervalMs = 0,
    [ValidateRange(0, 120000)]
    [int]$BootstrapRequestTimeoutMs = 0,
    [string]$AccountName = "",
    [string]$LedgerName = "",
    [string]$DeviceName = "",
    [string]$Timezone = "",
    [string]$PublicBaseUrl = "",
    [switch]$SkipScheduledTask,
    [string]$TaskName = "TicketboxBackend"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "    $msg" -ForegroundColor Green }

function Assert-InstallerTimeoutConfiguration {
    foreach ($entry in @(
        @{ Value = $BackendReadyTimeoutMs; Minimum = 1000; Maximum = 600000; Name = "BackendReadyTimeoutMs" },
        @{ Value = $BackendHealthRequestTimeoutMs; Minimum = 100; Maximum = 60000; Name = "BackendHealthRequestTimeoutMs" },
        @{ Value = $BackendReadyPollIntervalMs; Minimum = 100; Maximum = 10000; Name = "BackendReadyPollIntervalMs" },
        @{ Value = $BootstrapRequestTimeoutMs; Minimum = 1000; Maximum = 120000; Name = "BootstrapRequestTimeoutMs" }
    )) {
        if ($entry.Value -lt $entry.Minimum -or $entry.Value -gt $entry.Maximum) {
            throw "$($entry.Name) 必须是 $($entry.Minimum)..$($entry.Maximum) 毫秒。"
        }
    }
    if ($BackendHealthRequestTimeoutMs -gt $BackendReadyTimeoutMs) {
        throw "健康请求超时不能大于后端就绪总超时。"
    }
    if ($BackendReadyPollIntervalMs -gt $BackendReadyTimeoutMs) {
        throw "健康轮询间隔不能大于后端就绪总超时。"
    }
}

function Assert-SimpleSqlIdentifier([string]$Value, [string]$Name) {
    if ($Value -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "$Name 只能包含 ASCII 字母、数字和下划线，且不能以数字开头。"
    }
}

function Assert-SingleLineConfigurationValue([string]$Value, [string]$Name) {
    if ($Value.IndexOfAny(@([char]"`r", [char]"`n", [char]0)) -ge 0) {
        throw "$Name 不能包含换行或 NUL。"
    }
}

function Get-TicketboxFileSystemDriveType([string]$CanonicalPath) {
    $root = [System.IO.Path]::GetPathRoot($CanonicalPath)
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "敏感文件路径没有本机文件系统根目录。"
    }
    return (New-Object System.IO.DriveInfo($root)).DriveType
}

function Get-CanonicalFileSystemPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "密码文件路径不能为空。"
    }
    try {
        $providerPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
        $canonicalPath = [System.IO.Path]::GetFullPath($providerPath)
        if ($canonicalPath.StartsWith("\\", [System.StringComparison]::Ordinal)) {
            throw "敏感文件必须位于本机文件系统。"
        }
        $driveType = Get-TicketboxFileSystemDriveType $canonicalPath
        if ($driveType -in @(
            [System.IO.DriveType]::Network,
            [System.IO.DriveType]::Unknown,
            [System.IO.DriveType]::NoRootDirectory
        )) {
            throw "敏感文件不能位于网络映射盘或未知文件系统。"
        }
        return $canonicalPath
    }
    catch {
        throw "密码文件路径无效，拒绝继续。"
    }
}

function Get-PathAclRecord([string]$Path) {
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

function Assert-NoReparsePointInPath([string]$Path) {
    $currentPath = $Path
    while (-not [string]::IsNullOrWhiteSpace($currentPath)) {
        $item = Get-Item -LiteralPath $currentPath -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "密码文件路径包含重解析点，拒绝读取。"
        }
        $parent = [System.IO.Directory]::GetParent($currentPath)
        if ($null -eq $parent) {
            break
        }
        $currentPath = $parent.FullName
    }
}

function Assert-ProtectedPasswordFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "密码文件不存在或不是普通文件。"
    }
    Assert-NoReparsePointInPath $Path

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $currentSid = $identity.User.Value
    $systemSid = "S-1-5-18"
    $administratorsSid = "S-1-5-32-544"
    $trustedSids = @($currentSid, $systemSid, $administratorsSid) | Sort-Object -Unique
    $processSids = @($currentSid)
    if ($null -ne $identity.Groups) {
        $processSids += @($identity.Groups | ForEach-Object { $_.Value })
    }
    $processSids = @($processSids | Sort-Object -Unique)

    $acl = Get-PathAclRecord $Path
    if ($acl.Owner -notin $trustedSids) {
        throw "密码文件 owner 不可信，拒绝读取。"
    }
    if (-not $acl.AreAccessRulesProtected) {
        throw "密码文件仍继承 ACL，拒绝读取。"
    }
    if ($acl.Access.Count -eq 0) {
        throw "密码文件没有显式 ACL，拒绝读取。"
    }

    $hasProcessFullControl = $false
    foreach ($rule in $acl.Access) {
        $ruleSid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        if ($rule.IsInherited -or $ruleSid -notin $trustedSids) {
            throw "密码文件 ACL 含有不可信主体，拒绝读取。"
        }
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            throw "密码文件 ACL 含有非 Allow 规则，拒绝读取。"
        }
        $hasFullControl =
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq
            [System.Security.AccessControl.FileSystemRights]::FullControl
        if ($ruleSid -in $processSids -and $hasFullControl) {
            $hasProcessFullControl = $true
        }
    }
    if (-not $hasProcessFullControl) {
        throw "当前进程没有密码文件的显式 FullControl，无法保证读取后删除。"
    }
}

function Test-ProtectedPasswordFile([string]$Path) {
    try {
        Assert-ProtectedPasswordFile $Path
        return $true
    }
    catch {
        return $false
    }
}

function Set-ProtectedOutputFileAcl([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "敏感输出文件不存在，无法收紧 ACL。"
    }
    Assert-NoReparsePointInPath $Path
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($PSVersionTable.PSEdition -eq "Core") {
        $descriptor = [System.IO.FileSystemAclExtensions]::GetAccessControl($item)
    }
    else {
        $descriptor = $item.GetAccessControl()
    }
    $descriptor.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($descriptor.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    ))) {
        [void]$descriptor.RemoveAccessRuleSpecific($rule)
    }

    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $descriptor.SetOwner($currentSid)
    $targetSids = @(
        $currentSid,
        (New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")),
        (New-Object System.Security.Principal.SecurityIdentifier("S-1-5-32-544"))
    )
    foreach ($sid in $targetSids) {
        $allow = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$descriptor.AddAccessRule($allow)
    }
    if ($PSVersionTable.PSEdition -eq "Core") {
        [System.IO.FileSystemAclExtensions]::SetAccessControl($item, $descriptor)
    }
    else {
        $item.SetAccessControl($descriptor)
    }
    Assert-ProtectedPasswordFile $Path
}

function Remove-ProtectedPasswordFile([string]$Path) {
    try {
        Assert-ProtectedPasswordFile $Path
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $Path) {
            throw "password file survived deletion"
        }
    }
    catch {
        throw "密码文件未能安全删除，拒绝继续。"
    }
}

function Read-ProtectedPasswordFile(
    [string]$Path,
    [string]$Purpose,
    [switch]$AllowEmpty
) {
    $canonicalPath = Get-CanonicalFileSystemPath $Path
    Assert-ProtectedPasswordFile $canonicalPath

    $stream = $null
    $bytes = $null
    $value = $null
    $validatedOpenFile = $false
    $readFailed = $false
    $cleanupFailed = $false
    try {
        $stream = [System.IO.File]::Open(
            $canonicalPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::None
        )
        Assert-ProtectedPasswordFile $canonicalPath
        $validatedOpenFile = $true
        if ($stream.Length -gt 4096) {
            throw "password file is too large"
        }

        $bytes = New-Object 'System.Byte[]' ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $read = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($read -le 0) {
                throw "password file ended early"
            }
            $offset += $read
        }
        $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
        $value = $utf8.GetString($bytes)
        if ($value.Length -gt 0 -and $value[0] -eq [char]0xFEFF) {
            $value = $value.Substring(1)
        }
        if ($value.EndsWith("`r`n")) {
            $value = $value.Substring(0, $value.Length - 2)
        }
        elseif ($value.EndsWith("`n")) {
            $value = $value.Substring(0, $value.Length - 1)
        }
        if ($value.IndexOfAny(@([char]"`r", [char]"`n", [char]0)) -ge 0) {
            throw "password file must contain one line"
        }
        if (-not $AllowEmpty -and $value.Length -eq 0) {
            throw "password file is empty"
        }
    }
    catch {
        $readFailed = $true
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($null -ne $bytes) {
            [System.Array]::Clear($bytes, 0, $bytes.Length)
        }
        if ($validatedOpenFile) {
            try {
                Remove-ProtectedPasswordFile $canonicalPath
            }
            catch {
                $cleanupFailed = $true
            }
        }
    }

    if ($cleanupFailed) {
        throw "用于 $Purpose 的密码文件清理失败，拒绝继续。"
    }
    if ($readFailed) {
        throw "用于 $Purpose 的密码文件读取失败，拒绝继续。"
    }
    return $value
}

function Read-RetainedBootstrapSecret([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $canonicalPath = Get-CanonicalFileSystemPath $Path
    Assert-ProtectedPasswordFile $canonicalPath
    $stream = $null
    $reader = $null
    try {
        $stream = [System.IO.File]::Open(
            $canonicalPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::None
        )
        Assert-ProtectedPasswordFile $canonicalPath
        if ($stream.Length -gt 65536) {
            throw "retained environment is too large"
        }
        $reader = New-Object System.IO.StreamReader(
            $stream,
            (New-Object System.Text.UTF8Encoding($false, $true)),
            $true
        )
        $text = $reader.ReadToEnd()
    }
    catch {
        throw "无法安全读取既有 bootstrap 配置，拒绝覆盖。"
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        elseif ($null -ne $stream) {
            $stream.Dispose()
        }
    }

    $enabledValues = @()
    $secretValues = @()
    foreach ($line in @($text -split "\r?\n")) {
        if ($line -cmatch '^ENABLE_HTTP_BOOTSTRAP=(.*)$') {
            $enabledValues += $Matches[1]
        }
        elseif ($line -cmatch '^HTTP_BOOTSTRAP_SECRET=(.*)$') {
            $secretValues += $Matches[1]
        }
    }
    if ($enabledValues.Count -eq 0 -and $secretValues.Count -eq 0) {
        return $null
    }
    if (
        $enabledValues.Count -ne 1 -or
        $secretValues.Count -ne 1 -or
        [string]$enabledValues[0] -cne "true" -or
        [string]::IsNullOrWhiteSpace([string]$secretValues[0])
    ) {
        throw "既有 bootstrap 配置不完整，拒绝生成新 secret 覆盖。"
    }

    $secret = [string]$secretValues[0]
    $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($secret)
    try {
        if ($secretBytes.Length -lt 32) {
            throw "既有 bootstrap secret 不符合当前强度契约，拒绝覆盖。"
        }
    }
    finally {
        [System.Array]::Clear($secretBytes, 0, $secretBytes.Length)
    }
    return $secret
}

function Get-LegacyRetainedBootstrapSecret(
    [string]$Path,
    [bool]$PersistentOwnerIdentity
) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $canonicalPath = Get-CanonicalFileSystemPath $Path
    if (
        $PersistentOwnerIdentity -and
        -not (Test-ProtectedPasswordFile $canonicalPath)
    ) {
        # Base-version installs inherited ACLs on .env. Once the database proves
        # the owner already exists, never trust that file as a recovery secret;
        # the caller will atomically replace it with a protected base config.
        return $null
    }
    return Read-RetainedBootstrapSecret $canonicalPath
}

function Protect-LegacyOwnerBootstrapFileIfPresent([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $canonicalPath = Get-CanonicalFileSystemPath $Path
    if (-not (Test-Path -LiteralPath $canonicalPath -PathType Leaf)) {
        throw "既有 owner 凭据路径不是普通文件，拒绝继续。"
    }
    Set-ProtectedOutputFileAcl $canonicalPath
}

function Read-InteractivePassword(
    [string]$Prompt,
    [string]$Purpose,
    [switch]$AllowEmpty
) {
    $secure = $null
    $bstr = [IntPtr]::Zero
    try {
        $secure = Read-Host $Prompt -AsSecureString
        if ($null -eq $secure) {
            throw "未读取到 $Purpose。"
        }
        if (-not $AllowEmpty -and $secure.Length -eq 0) {
            throw "$Purpose 不能为空。"
        }
        if ($secure.Length -eq 0) {
            return ""
        }
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
        if ($null -ne $secure) {
            $secure.Dispose()
        }
    }
}

# ── EXE + 数据目录 ──────────────────────────────────────────────────────────
# 冻结后端是 onedir 形态（ADR-0047 §8）：EXE 在 ticketbox-backend\ 子文件夹里
# （旁边是 _internal\）。优先找子文件夹，兼容历史的单文件平铺布局。
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallationSafetyScript = Join-Path $ScriptDir "windows_installation_safety.ps1"
$LifecycleLockScript = Join-Path $ScriptDir "windows_lifecycle_lock.ps1"
if (-not (Test-Path -LiteralPath $InstallationSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 安装安全脚本：$InstallationSafetyScript"
}
if (-not (Test-Path -LiteralPath $LifecycleLockScript -PathType Leaf)) {
    throw "缺少 Windows 生命周期锁脚本：$LifecycleLockScript"
}
. $InstallationSafetyScript
. $LifecycleLockScript
$ReleaseConfigScript = Join-Path $ScriptDir "windows_release_config.ps1"
$ReleaseConfigPath = Join-Path $ScriptDir "windows-release-config.json"
if (-not (Test-Path -LiteralPath $ReleaseConfigScript -PathType Leaf)) {
    throw "缺少 Windows release config 解析脚本：$ReleaseConfigScript"
}
. $ReleaseConfigScript
$ReleaseConfig = Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath
if (-not $PSBoundParameters.ContainsKey("DbPort")) {
    $DbPort = [int]$ReleaseConfig.default_pg_port
}
if (-not $PSBoundParameters.ContainsKey("DbName")) {
    $DbName = [string]$ReleaseConfig.db_name
}
if (-not $PSBoundParameters.ContainsKey("DbRole")) {
    $DbRole = [string]$ReleaseConfig.db_role
}
if (-not $PSBoundParameters.ContainsKey("Port")) {
    $Port = [int]$ReleaseConfig.default_backend_port
}
if (-not $PSBoundParameters.ContainsKey("BackendReadyTimeoutMs")) {
    $BackendReadyTimeoutMs = [int]$ReleaseConfig.backend_ready_timeout_ms
}
if (-not $PSBoundParameters.ContainsKey("BackendHealthRequestTimeoutMs")) {
    $BackendHealthRequestTimeoutMs = [int]$ReleaseConfig.backend_health_request_timeout_ms
}
if (-not $PSBoundParameters.ContainsKey("BackendReadyPollIntervalMs")) {
    $BackendReadyPollIntervalMs = [int]$ReleaseConfig.backend_ready_poll_interval_ms
}
if (-not $PSBoundParameters.ContainsKey("BootstrapRequestTimeoutMs")) {
    $BootstrapRequestTimeoutMs = [int]$ReleaseConfig.bootstrap_request_timeout_ms
}
if (-not $PSBoundParameters.ContainsKey("AccountName")) {
    $AccountName = [string]$ReleaseConfig.bootstrap_account_name
}
if (-not $PSBoundParameters.ContainsKey("LedgerName")) {
    $LedgerName = [string]$ReleaseConfig.bootstrap_ledger_name
}
if (-not $PSBoundParameters.ContainsKey("DeviceName")) {
    $DeviceName = [string]$ReleaseConfig.bootstrap_device_name
}
if (-not $PSBoundParameters.ContainsKey("Timezone")) {
    $Timezone = [string]$ReleaseConfig.default_timezone
}
$SecretByteCount = [int]$ReleaseConfig.secret_byte_count
if ($DbPort -lt 1 -or $DbPort -gt 65535 -or $Port -lt 1 -or $Port -gt 65535) {
    throw "PostgreSQL 与后端端口必须是 1..65535。"
}
Assert-InstallerTimeoutConfiguration
Assert-SimpleSqlIdentifier $DbName "DbName"
Assert-SimpleSqlIdentifier $DbRole "DbRole"
Assert-SimpleSqlIdentifier $SuperUser "SuperUser"
foreach ($entry in @(
    @{ Value = $DbHost; Name = "DbHost" },
    @{ Value = $Timezone; Name = "Timezone" },
    @{ Value = $PublicBaseUrl; Name = "PublicBaseUrl" }
)) {
    Assert-SingleLineConfigurationValue $entry.Value $entry.Name
}
if (-not [string]::Equals($DbHost, "127.0.0.1", [System.StringComparison]::Ordinal)) {
    throw "旧版本机安装向导只允许 PostgreSQL 连接 127.0.0.1，拒绝向远端发送数据库凭据。"
}
if ($ExePath.Trim().Length -eq 0) {
    $onedir = Join-Path $ScriptDir "ticketbox-backend\ticketbox-backend.exe"
    $flat = Join-Path $ScriptDir "ticketbox-backend.exe"
    if (Test-Path -LiteralPath $onedir) { $ExePath = $onedir } else { $ExePath = $flat }
}
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "未找到后端程序：$ExePath。请把本脚本和 ticketbox-backend\ 文件夹（含 ticketbox-backend.exe）放在同一个目录，或用 -ExePath 指定 exe 路径。"
}
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
# 数据目录跟随 EXE 所在目录（onedir 下即 ticketbox-backend\ 内），与 launch.py 的
# _resolve_writable_data_dir() 默认（未设 TICKETBOX_DATA_DIR 时 = EXE 旁 ticketbox-data\）
# 保持一致，否则向导写的 .env 与运行时找的目录会错位。
$ExeDir = Split-Path -Parent $ExePath
$DataDir = Join-Path $ExeDir "ticketbox-data"
$EnvPath = Join-Path $DataDir ".env"
$bootstrapFile = Join-Path $DataDir "owner-bootstrap.txt"
$bootstrapExposureRecoveryPath = Join-Path $DataDir "bootstrap-exposure-recovery.env"

# ── 定位 psql.exe（环境变量 → PATH → Program Files 最高版本）──────────────────
function Find-Psql {
    if ($env:PG_BIN -and (Test-Path -LiteralPath (Join-Path $env:PG_BIN "psql.exe"))) {
        return (Join-Path $env:PG_BIN "psql.exe")
    }
    $onPath = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($null -ne $onPath) { return $onPath.Source }
    $programFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::ProgramFiles
    )
    $base = if ([string]::IsNullOrWhiteSpace($programFiles)) {
        $null
    }
    else {
        Join-Path $programFiles "PostgreSQL"
    }
    if ($null -ne $base -and (Test-Path -LiteralPath $base)) {
        $versions = Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d+$' } |
            Sort-Object { [int]$_.Name } -Descending
        foreach ($v in $versions) {
            $candidate = Join-Path $v.FullName "bin\psql.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    throw "未找到 psql.exe。请先安装 PostgreSQL（建议 17），或设环境变量 PG_BIN 指向其 bin 目录。"
}

# 用指定角色/口令跑一条 SQL；返回 stdout（修剪）。失败即抛。
function Invoke-Sql {
    param([string]$User, [string]$Password, [string]$Database, [string]$Sql, [switch]$Quiet)
    $prev = $env:PGPASSWORD
    $env:PGPASSWORD = $Password
    try {
        $psqlArgs = @("-X", "-w", "-v", "ON_ERROR_STOP=1", "-U", $User, "-h", $DbHost, "-p", "$DbPort", "-d", $Database, "-tA")
        $nativeErrorPreference = $ErrorActionPreference
        $hadNativeExitPreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
        if ($hadNativeExitPreference) {
            $nativeExitPreference = $PSNativeCommandUseErrorActionPreference
            $PSNativeCommandUseErrorActionPreference = $false
        }
        $ErrorActionPreference = "Continue"
        $out = $null
        $rc = -1
        try {
            $out = $Sql | & $Psql @psqlArgs 2>&1
            $rc = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $nativeErrorPreference
            if ($hadNativeExitPreference) {
                $PSNativeCommandUseErrorActionPreference = $nativeExitPreference
            }
            else {
                Remove-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Local -ErrorAction SilentlyContinue
            }
        }
        if ($rc -ne 0) {
            if ($Quiet) { return $null }
            throw "psql 执行失败（user=$User, db=$Database, exit=$rc）。"
        }
        return ($out | Out-String).Trim()
    }
    finally {
        if ($null -eq $prev) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $prev }
    }
}

function Invoke-SqlFile {
    param([string]$User, [string]$Password, [string]$Database, [string]$Path)
    $prev = $env:PGPASSWORD
    $env:PGPASSWORD = $Password
    try {
        $psqlArgs = @(
            "-X", "-w", "-v", "ON_ERROR_STOP=1", "-U", $User, "-h", $DbHost,
            "-p", "$DbPort", "-d", $Database, "-f", $Path
        )
        $nativeErrorPreference = $ErrorActionPreference
        $hadNativeExitPreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
        if ($hadNativeExitPreference) {
            $nativeExitPreference = $PSNativeCommandUseErrorActionPreference
            $PSNativeCommandUseErrorActionPreference = $false
        }
        $ErrorActionPreference = "Continue"
        $out = $null
        $rc = -1
        try {
            $out = & $Psql @psqlArgs 2>&1
            $rc = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $nativeErrorPreference
            if ($hadNativeExitPreference) {
                $PSNativeCommandUseErrorActionPreference = $nativeExitPreference
            }
            else {
                Remove-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Local -ErrorAction SilentlyContinue
            }
        }
        if ($rc -ne 0) {
            throw "psql 文件执行失败（user=$User, db=$Database, exit=$rc）。"
        }
    }
    finally {
        if ($null -eq $prev) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $prev }
    }
}

function New-StrongPassword([Parameter(Mandatory = $true)][ValidateRange(32, 1024)][int]$Length) {
    # 纯字母数字（避开会破坏 URL/.env 的特殊字符）。
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object 'System.Byte[]' $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
        return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
    }
    finally {
        $rng.Dispose()
        [System.Array]::Clear($bytes, 0, $bytes.Length)
    }
}

function Initialize-LegacyInstallerFileNativeMethods {
    if ("TicketboxLegacyInstallerFileNativeMethods" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class TicketboxLegacyInstallerFileNativeMethods
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

function Move-SensitiveFileAtomically([string]$Source, [string]$Destination) {
    Initialize-LegacyInstallerFileNativeMethods
    $replaceExistingAndWriteThrough = 0x1 -bor 0x8
    if (-not [TicketboxLegacyInstallerFileNativeMethods]::MoveFileEx(
        $Source,
        $Destination,
        $replaceExistingAndWriteThrough
    )) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "敏感输出文件原子替换失败（Win32=$errorCode）。"
    }
}

function Write-EnvNoBom([string]$Path, [string[]]$Lines) {
    # .env 必须**不带 BOM**（PS 5.1 默认会写 BOM；app 端解析不应见 BOM）。
    $canonicalPath = Get-CanonicalFileSystemPath $Path
    $parentPath = Split-Path -Parent $canonicalPath
    if (-not (Test-Path -LiteralPath $parentPath -PathType Container)) {
        throw "敏感输出文件的父目录不存在。"
    }
    Assert-NoReparsePointInPath $parentPath
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $content = [string]::Join([Environment]::NewLine, $Lines) + [Environment]::NewLine
    $bytes = $utf8NoBom.GetBytes($content)
    $temporaryPath = Join-Path $parentPath (
        ".{0}.{1}.tmp" -f [System.IO.Path]::GetFileName($canonicalPath), [Guid]::NewGuid().ToString("N")
    )
    $stream = $null
    $persisted = $null
    try {
        if (Test-Path -LiteralPath $canonicalPath) {
            if (-not (Test-Path -LiteralPath $canonicalPath -PathType Leaf)) {
                throw "敏感输出目标不是普通文件。"
            }
            Set-ProtectedOutputFileAcl $canonicalPath
        }
        $stream = [System.IO.FileStream]::new(
            $temporaryPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None,
            4096,
            [System.IO.FileOptions]::WriteThrough
        )
        $stream.Dispose()
        $stream = $null
        Set-ProtectedOutputFileAcl $temporaryPath
        $stream = [System.IO.FileStream]::new(
            $temporaryPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None,
            4096,
            [System.IO.FileOptions]::WriteThrough
        )
        $stream.SetLength(0)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null
        Set-ProtectedOutputFileAcl $temporaryPath

        Move-SensitiveFileAtomically -Source $temporaryPath -Destination $canonicalPath
        Set-ProtectedOutputFileAcl $canonicalPath
        $persisted = [System.IO.File]::ReadAllBytes($canonicalPath)
        if ($persisted.Length -ne $bytes.Length) {
            throw "敏感输出文件原子落盘校验失败。"
        }
        for ($index = 0; $index -lt $bytes.Length; $index++) {
            if ($persisted[$index] -ne $bytes[$index]) {
                throw "敏感输出文件原子落盘校验失败。"
            }
        }
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ($null -ne $persisted) {
            [System.Array]::Clear($persisted, 0, $persisted.Length)
        }
        [System.Array]::Clear($bytes, 0, $bytes.Length)
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-BackendPortListeners([int]$ListenPort) {
    if ($null -eq (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
        throw "当前系统无法验证 localhost 监听进程归属，拒绝继续。"
    }
    try {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
        return @($listeners | Where-Object { [int]$_.LocalPort -eq $ListenPort })
    }
    catch {
        throw "无法读取 localhost 监听进程归属，拒绝继续。"
    }
}

function Assert-BackendPortAvailable([int]$ListenPort) {
    if ((Get-BackendPortListeners $ListenPort).Count -ne 0) {
        throw "后端端口 $ListenPort 已被占用；无法证明 bootstrap 目标归属，拒绝继续。"
    }
}

function Assert-BackendListenerOwnedByProcess(
    [int]$ExpectedProcessId,
    [string]$ExpectedExecutablePath,
    [int]$ListenPort
) {
    $listeners = @(Get-BackendPortListeners $ListenPort)
    if ($listeners.Count -eq 0) {
        throw "后端端口尚无可验证监听进程。"
    }
    $ownerProcessIds = @($listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    if ($ownerProcessIds.Count -ne 1 -or $ownerProcessIds[0] -ne $ExpectedProcessId) {
        throw "localhost 监听进程不属于本次启动的后端，拒绝发送 bootstrap secret。"
    }

    try {
        $records = @(Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $ExpectedProcessId" `
            -ErrorAction Stop)
    }
    catch {
        throw "无法验证后端监听进程映像，拒绝发送 bootstrap secret。"
    }
    if ($records.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$records[0].ExecutablePath)) {
        throw "后端监听进程映像不可验证，拒绝发送 bootstrap secret。"
    }
    $actualPath = [System.IO.Path]::GetFullPath([string]$records[0].ExecutablePath)
    $expectedPath = [System.IO.Path]::GetFullPath($ExpectedExecutablePath)
    if (-not [string]::Equals($actualPath, $expectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "后端监听进程映像与本次启动程序不一致，拒绝发送 bootstrap secret。"
    }
}

function Read-Utf8HttpResponseBody([System.Net.WebResponse]$Response) {
    $maximumBytes = 1MB
    $stream = $null
    $buffer = New-Object 'System.Byte[]' 8192
    $memory = New-Object System.IO.MemoryStream
    $payloadBytes = $null
    try {
        if ($Response.ContentLength -gt $maximumBytes) {
            throw "loopback response body too large"
        }
        $stream = $Response.GetResponseStream()
        if ($null -eq $stream) {
            throw "loopback response body missing"
        }
        $total = 0
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $read
            if ($total -gt $maximumBytes) {
                throw "loopback response body too large"
            }
            $memory.Write($buffer, 0, $read)
        }
        $payloadBytes = $memory.ToArray()
        $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
        return $utf8.GetString($payloadBytes)
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        $memory.Dispose()
        [System.Array]::Clear($buffer, 0, $buffer.Length)
        if ($null -ne $payloadBytes) {
            [System.Array]::Clear($payloadBytes, 0, $payloadBytes.Length)
        }
    }
}

function Invoke-DirectLoopbackHealthRequest(
    [string]$Url,
    [ValidateRange(100, 60000)][int]$RequestTimeoutMs
) {
    $uri = New-Object System.Uri($Url)
    if (
        $uri.Scheme -cne "http" -or
        $uri.Host -cne "127.0.0.1" -or
        $uri.UserInfo.Length -ne 0 -or
        $uri.Query.Length -ne 0
    ) {
        throw "健康检查 URL 不是无参数的 127.0.0.1 HTTP 地址。"
    }
    $request = [System.Net.HttpWebRequest]::Create($uri)
    $request.Method = "GET"
    $request.Accept = "application/json"
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.KeepAlive = $false
    $request.Timeout = $RequestTimeoutMs
    $request.ReadWriteTimeout = $RequestTimeoutMs
    $response = $null
    try {
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Headers = @{ "Content-Type" = [string]$response.ContentType }
            Content = Read-Utf8HttpResponseBody $response
        }
    }
    finally {
        if ($null -ne $response) {
            $response.Dispose()
        }
    }
}

function Assert-StrictBackendHealthResponse([object]$Response) {
    if ($null -eq $Response -or [int]$Response.StatusCode -ne 200) {
        throw "后端健康响应状态不符合契约。"
    }
    $contentType = [string]$Response.Headers["Content-Type"]
    $mediaType = ($contentType -split ";", 2)[0].Trim()
    if (-not [string]::Equals(
        $mediaType,
        "application/json",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "后端健康响应不是 JSON，拒绝继续。"
    }
    $raw = [string]$Response.Content
    if ($raw -cnotmatch '^\s*\{\s*"status"\s*:\s*"ok"\s*\}\s*$') {
        throw "后端健康 JSON 不符合小票夹最小契约，拒绝继续。"
    }
    try {
        $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "后端健康 JSON 无法解析，拒绝继续。"
    }
    if (@($parsed.PSObject.Properties).Count -ne 1 -or [string]$parsed.status -cne "ok") {
        throw "后端健康 JSON 不符合小票夹最小契约，拒绝继续。"
    }
}

function Wait-OwnedBackendHealth(
    [System.Diagnostics.Process]$Process,
    [string]$ExpectedExecutablePath,
    [int]$ListenPort,
    [ValidateRange(1000, 600000)][int]$TimeoutMs,
    [ValidateRange(100, 60000)][int]$RequestTimeoutMs,
    [ValidateRange(100, 10000)][int]$PollIntervalMs
) {
    $url = "http://127.0.0.1:$ListenPort/api/health"
    $deadline = [System.Diagnostics.Stopwatch]::StartNew()
    while ($deadline.ElapsedMilliseconds -lt $TimeoutMs) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "本次启动的后端进程已提前退出。"
        }
        $response = $null
        try {
            $response = Invoke-DirectLoopbackHealthRequest `
                -Url $url `
                -RequestTimeoutMs $RequestTimeoutMs
        }
        catch {
            $remainingMs = $TimeoutMs - $deadline.ElapsedMilliseconds
            if ($remainingMs -gt 0) {
                Start-Sleep -Milliseconds ([int][Math]::Min($PollIntervalMs, $remainingMs))
            }
            continue
        }
        Assert-StrictBackendHealthResponse $response
        Assert-BackendListenerOwnedByProcess `
            -ExpectedProcessId $Process.Id `
            -ExpectedExecutablePath $ExpectedExecutablePath `
            -ListenPort $ListenPort
        Write-Ok "后端已就绪：$url"
        return
    }
    throw "后端未在配置的就绪时限内完成可信健康检查。"
}

function Invoke-OwnerBootstrapRequest(
    [string]$BaseUrl,
    [string]$Secret,
    [hashtable]$Payload,
    [int]$ExpectedProcessId,
    [string]$ExpectedExecutablePath,
    [int]$ListenPort,
    [ValidateRange(100, 60000)][int]$HealthRequestTimeoutMs,
    [ValidateRange(1000, 120000)][int]$RequestTimeoutMs
) {
    Assert-BackendListenerOwnedByProcess `
        -ExpectedProcessId $ExpectedProcessId `
        -ExpectedExecutablePath $ExpectedExecutablePath `
        -ListenPort $ListenPort
    try {
        $healthResponse = Invoke-DirectLoopbackHealthRequest `
            -Url "$BaseUrl/api/health" `
            -RequestTimeoutMs $HealthRequestTimeoutMs
    }
    catch {
        throw "发送 bootstrap secret 前的健康复核失败，拒绝继续。"
    }
    Assert-StrictBackendHealthResponse $healthResponse
    Assert-BackendListenerOwnedByProcess `
        -ExpectedProcessId $ExpectedProcessId `
        -ExpectedExecutablePath $ExpectedExecutablePath `
        -ListenPort $ListenPort
    $bodyJson = $Payload | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($bodyJson)
    $request = $null
    $requestStream = $null
    $response = $null
    $httpRequestAttempted = $false
    try {
        $uri = New-Object System.Uri("$BaseUrl/api/bootstrap/owner")
        if (
            $uri.Scheme -cne "http" -or
            $uri.Host -cne "127.0.0.1" -or
            $uri.UserInfo.Length -ne 0 -or
            $uri.Query.Length -ne 0 -or
            $uri.AbsolutePath -cne "/api/bootstrap/owner"
        ) {
            throw "bootstrap URL 不符合固定 loopback 契约。"
        }
        $request = [System.Net.HttpWebRequest]::Create($uri)
        $request.Method = "POST"
        $request.Accept = "application/json"
        $request.ContentType = "application/json; charset=utf-8"
        $request.Headers.Add("X-Bootstrap-Secret", $Secret)
        $request.Proxy = $null
        $request.AllowAutoRedirect = $false
        $request.KeepAlive = $false
        $request.Timeout = $RequestTimeoutMs
        $request.ReadWriteTimeout = $RequestTimeoutMs
        $request.ContentLength = $bodyBytes.Length
        $httpRequestAttempted = $true
        $requestStream = $request.GetRequestStream()
        $requestStream.Write($bodyBytes, 0, $bodyBytes.Length)
        $requestStream.Dispose()
        $requestStream = $null
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        if ([int]$response.StatusCode -ne 200) {
            throw "bootstrap HTTP 状态不符合契约。"
        }
        $responseBody = Read-Utf8HttpResponseBody $response
        Assert-BackendListenerOwnedByProcess `
            -ExpectedProcessId $ExpectedProcessId `
            -ExpectedExecutablePath $ExpectedExecutablePath `
            -ListenPort $ListenPort
        return $responseBody | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        if ($httpRequestAttempted) {
            try {
                Assert-BackendListenerOwnedByProcess `
                    -ExpectedProcessId $ExpectedProcessId `
                    -ExpectedExecutablePath $ExpectedExecutablePath `
                    -ListenPort $ListenPort
            }
            catch {
                throw (New-Object System.Security.SecurityException(
                    "owner bootstrap HTTP 请求异常后的 listener 后验复核失败；bootstrap secret 可能已暴露，拒绝继续本轮重试。"
                ))
            }
        }
        throw
    }
    finally {
        if ($null -ne $requestStream) {
            $requestStream.Dispose()
        }
        if ($null -ne $response) {
            $response.Dispose()
        }
        [System.Array]::Clear($bodyBytes, 0, $bodyBytes.Length)
    }
}

function Get-BootstrapHmacDigest([string]$Secret, [string]$Context) {
    $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($Secret)
    $contextBytes = [System.Text.Encoding]::ASCII.GetBytes($Context)
    $hmac = $null
    try {
        if ($secretBytes.Length -lt 32) {
            throw "bootstrap secret 不符合最小强度契约。"
        }
        $hmac = New-Object System.Security.Cryptography.HMACSHA256
        $hmac.Key = $secretBytes
        return ,$hmac.ComputeHash($contextBytes)
    }
    finally {
        if ($null -ne $hmac) {
            $hmac.Dispose()
        }
        [System.Array]::Clear($secretBytes, 0, $secretBytes.Length)
        [System.Array]::Clear($contextBytes, 0, $contextBytes.Length)
    }
}

function ConvertTo-Base64UrlWithoutPadding([byte[]]$Value) {
    return [Convert]::ToBase64String($Value).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-DeterministicBootstrapCredentials([string]$Secret) {
    $adminDigest = $null
    $uploadDigest = $null
    $pairingDigest = $null
    try {
        $adminDigest = Get-BootstrapHmacDigest `
            -Secret $Secret `
            -Context "ticketbox/bootstrap-owner/v1/admin-token"
        $uploadDigest = Get-BootstrapHmacDigest `
            -Secret $Secret `
            -Context "ticketbox/bootstrap-owner/v1/upload-key"
        $pairingDigest = Get-BootstrapHmacDigest `
            -Secret $Secret `
            -Context "ticketbox/bootstrap-owner/v1/pairing-code"
        [long]$pairingRemainder = 0
        foreach ($item in $pairingDigest) {
            $pairingRemainder = (($pairingRemainder * 256L) + [int]$item) % 100000000L
        }
        return [pscustomobject]@{
            AdminToken = "tbx_$(ConvertTo-Base64UrlWithoutPadding $adminDigest)"
            UploadKey = "upl_$(ConvertTo-Base64UrlWithoutPadding $uploadDigest)"
            PairingCode = $pairingRemainder.ToString("D8", [System.Globalization.CultureInfo]::InvariantCulture)
        }
    }
    finally {
        foreach ($digest in @($adminDigest, $uploadDigest, $pairingDigest)) {
            if ($null -ne $digest) {
                [System.Array]::Clear($digest, 0, $digest.Length)
            }
        }
    }
}

function Assert-BootstrapDerivationFixedVector {
    $derived = Get-DeterministicBootstrapCredentials "ticketbox-bootstrap-vector-2026-07-10"
    if (
        [string]$derived.AdminToken -cne "tbx_f1cz5I0IKi0r6iUzmoexescoDH0xYOF7_-R39LpN7lY" -or
        [string]$derived.UploadKey -cne "upl_I8Q7_d0BrxgzKxMlkZFUtd9eFF1xe40zM8dt2h1cyeU" -or
        [string]$derived.PairingCode -cne "05747978"
    ) {
        throw "bootstrap 凭据派生实现未通过固定向量校验。"
    }
}

function Test-FixedTimeStringEquals([string]$Left, [string]$Right) {
    $leftBytes = [System.Text.Encoding]::UTF8.GetBytes($Left)
    $rightBytes = [System.Text.Encoding]::UTF8.GetBytes($Right)
    try {
        [int]$difference = $leftBytes.Length -bxor $rightBytes.Length
        $length = [Math]::Max($leftBytes.Length, $rightBytes.Length)
        for ($index = 0; $index -lt $length; $index++) {
            $leftByte = if ($index -lt $leftBytes.Length) { [int]$leftBytes[$index] } else { 0 }
            $rightByte = if ($index -lt $rightBytes.Length) { [int]$rightBytes[$index] } else { 0 }
            $difference = $difference -bor ($leftByte -bxor $rightByte)
        }
        return $difference -eq 0
    }
    finally {
        [System.Array]::Clear($leftBytes, 0, $leftBytes.Length)
        [System.Array]::Clear($rightBytes, 0, $rightBytes.Length)
    }
}

function Assert-BootstrapResponse([object]$Response, [string]$Secret) {
    $required = @(
        "account_name", "ledger_name", "ledger_id", "device_name", "admin_token",
        "upload_url_path", "upload_key", "pairing_code", "pairing_expires_at"
    )
    foreach ($name in $required) {
        if (
            $null -eq $Response.PSObject.Properties[$name] -or
            [string]::IsNullOrWhiteSpace([string]$Response.$name)
        ) {
            throw "owner 初始化响应不完整，拒绝写入凭证文件。"
        }
    }
    Assert-BootstrapDerivationFixedVector
    $expected = Get-DeterministicBootstrapCredentials $Secret
    if (
        -not (Test-FixedTimeStringEquals ([string]$Response.admin_token) $expected.AdminToken) -or
        -not (Test-FixedTimeStringEquals ([string]$Response.upload_key) $expected.UploadKey) -or
        -not (Test-FixedTimeStringEquals ([string]$Response.upload_url_path) "/u/$($expected.UploadKey)") -or
        -not (Test-FixedTimeStringEquals ([string]$Response.pairing_code) $expected.PairingCode)
    ) {
        throw "owner 初始化响应未通过确定性凭据校验，拒绝写入凭证文件。"
    }
}

function Test-PersistentOwnerIdentity(
    [string]$User,
    [string]$Password,
    [string]$Database
) {
    $tableCount = Invoke-Sql `
        -User $User `
        -Password $Password `
        -Database $Database `
        -Sql "SELECT count(*) FROM pg_catalog.pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p') AND relname IN ('accounts', 'ledgers', 'ledger_members', 'auth_tokens')"
    if ([int]$tableCount -ne 4) {
        return $false
    }
    $identityExists = Invoke-Sql `
        -User $User `
        -Password $Password `
        -Database $Database `
        -Sql "SELECT 1 WHERE EXISTS (SELECT 1 FROM accounts a JOIN ledgers l ON l.owner_account_id = a.id JOIN ledger_members m ON m.ledger_id = l.ledger_id AND m.account_id = a.id WHERE m.role = 'owner' AND m.disabled_at IS NULL) AND EXISTS (SELECT 1 FROM auth_tokens) LIMIT 1"
    return $identityExists -eq "1"
}

function Resolve-LegacyBootstrapPlan(
    [string]$RetainedSecret,
    [bool]$PersistentOwnerIdentity,
    [Parameter(Mandatory = $true)][ValidateRange(32, 1024)][int]$SecretLength
) {
    if (-not [string]::IsNullOrWhiteSpace($RetainedSecret)) {
        return [pscustomobject]@{
            Required = $true
            IsRecovery = $true
            Secret = $RetainedSecret
        }
    }
    if ($PersistentOwnerIdentity) {
        return [pscustomobject]@{
            Required = $false
            IsRecovery = $false
            Secret = $null
        }
    }
    return [pscustomobject]@{
        Required = $true
        IsRecovery = $false
        Secret = New-StrongPassword -Length $SecretLength
    }
}

function Read-LegacyBootstrapExposureRecoveryIntent {
    if (-not (Test-Path -LiteralPath $bootstrapExposureRecoveryPath -PathType Leaf)) {
        return $null
    }
    Assert-TicketboxExactFileAcl `
        -Path $bootstrapExposureRecoveryPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $lines = [System.IO.File]::ReadAllLines(
        $bootstrapExposureRecoveryPath,
        (New-Object System.Text.UTF8Encoding($false, $true))
    )
    if ($lines.Count -ne 3) {
        throw "legacy bootstrap 暴露恢复 intent 格式无效。"
    }
    $values = @{}
    foreach ($line in $lines) {
        if ($line -cnotmatch '^([A-Z_]+)=(.*)$' -or $values.ContainsKey($Matches[1])) {
            throw "legacy bootstrap 暴露恢复 intent 含重复或无效字段。"
        }
        $values[$Matches[1]] = $Matches[2]
    }
    if (
        $values.Count -ne 3 -or
        $values["STATE"] -cne "pending" -or
        [string]::IsNullOrWhiteSpace($values["EXPOSED_SECRET"]) -or
        [string]::IsNullOrWhiteSpace($values["REPLACEMENT_SECRET"]) -or
        $values["EXPOSED_SECRET"] -ceq $values["REPLACEMENT_SECRET"]
    ) {
        throw "legacy bootstrap 暴露恢复 intent 不完整。"
    }
    Get-DeterministicBootstrapCredentials $values["EXPOSED_SECRET"] | Out-Null
    Get-DeterministicBootstrapCredentials $values["REPLACEMENT_SECRET"] | Out-Null
    return [pscustomobject]@{
        ExposedSecret = [string]$values["EXPOSED_SECRET"]
        ReplacementSecret = [string]$values["REPLACEMENT_SECRET"]
    }
}

function Write-LegacyBootstrapExposureRecoveryIntent(
    [string]$ExposedSecret,
    [string]$ReplacementSecret
) {
    Write-EnvNoBom -Path $bootstrapExposureRecoveryPath -Lines @(
        "STATE=pending",
        "EXPOSED_SECRET=$ExposedSecret",
        "REPLACEMENT_SECRET=$ReplacementSecret"
    )
    Set-TicketboxExactFileAcl `
        -Path $bootstrapExposureRecoveryPath `
        -Accounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $persisted = Read-LegacyBootstrapExposureRecoveryIntent
    if (
        $persisted.ExposedSecret -cne $ExposedSecret -or
        $persisted.ReplacementSecret -cne $ReplacementSecret
    ) {
        throw "legacy bootstrap 暴露恢复 intent 持久化校验失败。"
    }
}

function Invoke-LegacyBootstrapExposureMaintenance(
    [string]$ExposedSecret,
    [string]$ReplacementSecret
) {
    $environmentNames = @(
        "TICKETBOX_DATA_DIR",
        "TICKETBOX_MAINTENANCE_ACTION",
        "TICKETBOX_EXPOSED_BOOTSTRAP_SECRET",
        "TICKETBOX_REPLACEMENT_BOOTSTRAP_SECRET"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = if (Test-Path "Env:$name") {
            [pscustomobject]@{ Present = $true; Value = (Get-Item "Env:$name").Value }
        }
        else {
            [pscustomobject]@{ Present = $false; Value = "" }
        }
    }
    try {
        $env:TICKETBOX_DATA_DIR = $DataDir
        $env:TICKETBOX_MAINTENANCE_ACTION = "rotate-exposed-bootstrap"
        $env:TICKETBOX_EXPOSED_BOOTSTRAP_SECRET = $ExposedSecret
        $env:TICKETBOX_REPLACEMENT_BOOTSTRAP_SECRET = $ReplacementSecret
        & $ExePath
        if ($LASTEXITCODE -ne 0) {
            throw "legacy bootstrap 暴露恢复动作失败（exit=$LASTEXITCODE）。"
        }
    }
    finally {
        foreach ($name in $environmentNames) {
            $previous = $previousEnvironment[$name]
            if ($previous.Present) {
                Set-Item -Path "Env:$name" -Value $previous.Value
            }
            else {
                Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
            }
        }
    }
}

function Resolve-LegacyBootstrapExposureRecovery(
    [string]$DatabaseUrl,
    [string[]]$BaseEnvironment
) {
    $intent = Read-LegacyBootstrapExposureRecoveryIntent
    if ($null -eq $intent) {
        return $null
    }
    Write-EnvNoBom -Path $EnvPath -Lines $BaseEnvironment
    if ($null -ne (Read-RetainedBootstrapSecret $EnvPath)) {
        throw "legacy bootstrap 暴露隔离配置仍含 secret。"
    }
    Invoke-LegacyBootstrapExposureMaintenance `
        -ExposedSecret $intent.ExposedSecret `
        -ReplacementSecret $intent.ReplacementSecret
    Write-EnvNoBom -Path $EnvPath -Lines ($BaseEnvironment + @(
        "ENABLE_HTTP_BOOTSTRAP=true",
        "HTTP_BOOTSTRAP_SECRET=$($intent.ReplacementSecret)"
    ))
    $persistedSecret = Read-RetainedBootstrapSecret $EnvPath
    if ($persistedSecret -cne $intent.ReplacementSecret) {
        throw "legacy bootstrap 替换 secret 持久化校验失败。"
    }
    Remove-ProtectedPasswordFile $bootstrapExposureRecoveryPath
    return $intent.ReplacementSecret
}

function Stop-StartedBackendProcess([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process) {
        return
    }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction Stop
            $Process.WaitForExit(10000) | Out-Null
        }
    }
    catch {
        throw "无法停止本次启动的临时后端进程，拒绝继续。"
    }
}

$legacyLifecycleLock = Enter-TicketboxLifecycleLock
try {
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "uploads") | Out-Null
$Psql = Find-Psql
Write-Step "使用 PostgreSQL 客户端：$Psql"

# ── 超级用户口令（EDB 安装时设的 postgres 口令；trust 部署可留空）────────────
Write-Step "连接 PostgreSQL（$DbHost`:$DbPort）"
if ($NonInteractive -and -not $PSBoundParameters.ContainsKey('PostgresSuperPasswordFile')) {
    throw "非交互模式必须通过 -PostgresSuperPasswordFile 提供一次性受保护密码文件。"
}
if ($PSBoundParameters.ContainsKey('PostgresSuperPasswordFile') -and [string]::IsNullOrWhiteSpace($PostgresSuperPasswordFile)) {
    throw "-PostgresSuperPasswordFile 不能是空路径；trust 模式请传入内容为空的受保护文件。"
}
if ($PSBoundParameters.ContainsKey('PostgresRolePasswordFile') -and [string]::IsNullOrWhiteSpace($PostgresRolePasswordFile)) {
    throw "-PostgresRolePasswordFile 不能是空路径。"
}
if (
    $PSBoundParameters.ContainsKey('PostgresSuperPasswordFile') -and
    $PSBoundParameters.ContainsKey('PostgresRolePasswordFile')
) {
    $superFileCanonical = Get-CanonicalFileSystemPath $PostgresSuperPasswordFile
    $dbFileCanonical = Get-CanonicalFileSystemPath $PostgresRolePasswordFile
    if ([string]::Equals(
        $superFileCanonical,
        $dbFileCanonical,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "超级用户与应用角色密码必须使用两个独立的一次性文件。"
    }
}

if ($PSBoundParameters.ContainsKey('PostgresSuperPasswordFile')) {
    $superPwdPlain = Read-ProtectedPasswordFile `
        -Path $PostgresSuperPasswordFile `
        -Purpose "PostgreSQL 超级用户认证" `
        -AllowEmpty
}
else {
    $superPwdPlain = Read-InteractivePassword `
        -Prompt "请输入 PostgreSQL 超级用户「$SuperUser」口令（trust 模式直接回车）" `
        -Purpose "PostgreSQL 超级用户口令" `
        -AllowEmpty
}
$probe = Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database "postgres" -Sql "SELECT 1" -Quiet
if ($probe -ne "1") {
    throw "无法用超级用户「$SuperUser」连接 $DbHost`:$DbPort。请确认 PostgreSQL 服务在运行、端口与口令正确。"
}
Write-Ok "连接成功。"

# ── 建应用角色（幂等）───────────────────────────────────────────────────────
Write-Step "准备应用角色「$DbRole」与数据库「$DbName」"
$roleExists = (Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database "postgres" -Sql "SELECT 1 FROM pg_roles WHERE rolname='$DbRole'") -eq "1"
if ($roleExists) {
    if ($PSBoundParameters.ContainsKey('PostgresRolePasswordFile')) {
        $rolePwd = Read-ProtectedPasswordFile `
            -Path $PostgresRolePasswordFile `
            -Purpose "既有 PostgreSQL 应用角色认证"
    }
    elseif ($NonInteractive) {
        throw "角色「$DbRole」已存在；非交互重跑必须用 -PostgresRolePasswordFile 提供受保护口令文件。"
    }
    else {
        $rolePwd = Read-InteractivePassword `
            -Prompt "请输入既有 PostgreSQL 角色「$DbRole」的口令" `
            -Purpose "PostgreSQL 应用角色口令"
    }
    Write-Ok "角色已存在，沿用安全输入的口令。"
}
else {
    if ($PSBoundParameters.ContainsKey('PostgresRolePasswordFile')) {
        $rolePwd = Read-ProtectedPasswordFile `
            -Path $PostgresRolePasswordFile `
            -Purpose "新 PostgreSQL 应用角色"
    }
    else {
        $rolePwd = New-StrongPassword -Length $SecretByteCount
    }
    $rolePwdSql = $rolePwd.Replace("'", "''")
    Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database "postgres" -Sql "CREATE ROLE `"$DbRole`" LOGIN PASSWORD '$rolePwdSql'" | Out-Null
    $rolePwdSql = $null
    Write-Ok "已创建角色「$DbRole」（口令将写入 .env）。"
}

# ── 建库（幂等，OWNER = 应用角色）。CREATE DATABASE 不能在事务/DO 块里。──────
$dbExists = (Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database "postgres" -Sql "SELECT 1 FROM pg_database WHERE datname='$DbName'") -eq "1"
if ($dbExists) {
    Write-Ok "数据库「$DbName」已存在，跳过创建。"
}
else {
    Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database "postgres" -Sql "CREATE DATABASE `"$DbName`" OWNER `"$DbRole`" ENCODING 'UTF8'" | Out-Null
    Write-Ok "已创建数据库「$DbName」（属主 = $DbRole）。"
}

# ── 生成 .env（无 BOM）。先带一次性 bootstrap 开关，建库初始化后再清掉。────────
Write-Step "生成配置 .env（$EnvPath）"
$databaseRole = [System.Uri]::EscapeDataString($DbRole)
$databasePassword = [System.Uri]::EscapeDataString($rolePwd)
$databaseUrl = "postgresql+psycopg://${databaseRole}:${databasePassword}@${DbHost}:${DbPort}/${DbName}"
$baseEnv = @(
    "DATABASE_URL=$databaseUrl",
    "TICKETBOX_HOST=127.0.0.1",
    "TICKETBOX_PORT=$Port",
    "OCR_DEFAULT_TIMEZONE=$Timezone"
)
if ($PublicBaseUrl.Trim().Length -gt 0) { $baseEnv += "PUBLIC_BASE_URL=$PublicBaseUrl" }
$persistentOwnerIdentity = Test-PersistentOwnerIdentity `
    -User $DbRole `
    -Password $rolePwd `
    -Database $DbName
$recoveredBootstrapSecret = Resolve-LegacyBootstrapExposureRecovery `
    -DatabaseUrl $databaseUrl `
    -BaseEnvironment $baseEnv
$retainedBootstrapSecret = if (-not [string]::IsNullOrWhiteSpace([string]$recoveredBootstrapSecret)) {
    [string]$recoveredBootstrapSecret
}
else {
    Get-LegacyRetainedBootstrapSecret `
        -Path $EnvPath `
        -PersistentOwnerIdentity $persistentOwnerIdentity
}
if ($persistentOwnerIdentity) {
    Protect-LegacyOwnerBootstrapFileIfPresent $bootstrapFile
}
$bootstrapPlan = Resolve-LegacyBootstrapPlan `
    -RetainedSecret $retainedBootstrapSecret `
    -PersistentOwnerIdentity $persistentOwnerIdentity `
    -SecretLength $SecretByteCount
$bootstrapRequired = [bool]$bootstrapPlan.Required
$bootstrapSecret = [string]$bootstrapPlan.Secret
if ($bootstrapPlan.IsRecovery) {
    Write-Host "    检测到上次失败保留的 bootstrap 配置，将使用同一 secret 安全重试。" -ForegroundColor Yellow
}
elseif (-not $bootstrapRequired) {
    Write-Ok "检测到持久 owner 身份，跳过一次性 bootstrap，不生成新 secret。"
}
# 一次性 HTTP bootstrap：仅本机、一次消费即作废，下面建好 owner 后清掉。
$baseUrl = "http://127.0.0.1:$Port"
Assert-BackendPortAvailable $Port
$bootstrapEnv = $baseEnv
if ($bootstrapRequired) {
    $bootstrapEnv += @("ENABLE_HTTP_BOOTSTRAP=true", "HTTP_BOOTSTRAP_SECRET=$bootstrapSecret")
}
Write-EnvNoBom -Path $EnvPath -Lines $bootstrapEnv
Write-Ok "已写入 .env（DATABASE_URL 指向应用角色 $DbRole）。"

# ── 首次启动 EXE：以 ticketbox 连库 → 建表（属主正确）+ 提供 HTTP bootstrap。──
Write-Step "初始化数据库并启动后端（首次建表）"
$proc = $null
$pairingCode = ""
$bootstrapVerifiedAndPersisted = -not $bootstrapRequired
$bootstrapExposureQuarantined = $false
try {
    $proc = Start-Process -FilePath $ExePath -WorkingDirectory $ExeDir -PassThru -WindowStyle Hidden
    Wait-OwnedBackendHealth `
        -Process $proc `
        -ExpectedExecutablePath $ExePath `
        -ListenPort $Port `
        -TimeoutMs $BackendReadyTimeoutMs `
        -RequestTimeoutMs $BackendHealthRequestTimeoutMs `
        -PollIntervalMs $BackendReadyPollIntervalMs

    # ── 表属主自检（堵 owner 陷阱）：非 ticketbox 属主的表应为 0。─────────────
    $mismatch = Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database $DbName -Sql "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner <> '$DbRole'"
    if ([int]$mismatch -ne 0) {
        Write-Host "    警告：检测到 $mismatch 张表属主不是 $DbRole（owner 错位陷阱）。" -ForegroundColor Yellow
        $fixSql = Join-Path $ExeDir "fix_table_owners.sql"
        if (-not (Test-Path -LiteralPath $fixSql)) { $fixSql = Join-Path $ScriptDir "fix_table_owners.sql" }
        if (Test-Path -LiteralPath $fixSql) {
            Invoke-SqlFile `
                -User $SuperUser `
                -Password $superPwdPlain `
                -Database $DbName `
                -Path $fixSql
            Write-Ok "已用 fix_table_owners.sql 归位属主。"
        }
        else {
            Write-Host "    未找到 fix_table_owners.sql；请参见 docs/runbook/POSTGRES_MIGRATION.md §3 手动修复。" -ForegroundColor Yellow
        }
    }
    else {
        Write-Ok "表属主自检通过（全部归 $DbRole）。"
    }

    if ($bootstrapRequired) {
        # ── 创建 owner 身份（HTTP 一次性 bootstrap）──────────────────────────
        Write-Step "创建管理员（owner）身份"
        $payload = @{
            account_name = $AccountName
            ledger_name = $LedgerName
            device_name = $DeviceName
            default_timezone = $Timezone
        }
        try {
            $resp = Invoke-OwnerBootstrapRequest `
                -BaseUrl $baseUrl `
                -Secret $bootstrapSecret `
                -Payload $payload `
                -ExpectedProcessId $proc.Id `
                -ExpectedExecutablePath $ExePath `
                -ListenPort $Port `
                -HealthRequestTimeoutMs $BackendHealthRequestTimeoutMs `
                -RequestTimeoutMs $BootstrapRequestTimeoutMs
            Assert-BootstrapResponse -Response $resp -Secret $bootstrapSecret
            $pairingCode = $resp.pairing_code
            $lines = @(
                "小票夹 Owner 身份（请妥善保存，密钥只显示一次）",
                "owner account: $($resp.account_name)",
                "default ledger: $($resp.ledger_name) ($($resp.ledger_id))",
                "bootstrap device: $($resp.device_name)",
                "admin token: $($resp.admin_token)",
                "iOS upload URL path: $($resp.upload_url_path)",
                "iOS upload key: $($resp.upload_key)",
                "Android pairing code: $($resp.pairing_code)",
                "pairing expires at: $($resp.pairing_expires_at)"
            )
            Write-EnvNoBom -Path $bootstrapFile -Lines $lines
            $bootstrapVerifiedAndPersisted = $true
            Write-Ok "owner 身份已创建，凭证写入：$bootstrapFile"
        }
        catch [System.Security.SecurityException] {
            $replacementSecret = New-StrongPassword -Length $SecretByteCount
            Write-LegacyBootstrapExposureRecoveryIntent `
                -ExposedSecret $bootstrapSecret `
                -ReplacementSecret $replacementSecret
            Write-EnvNoBom -Path $EnvPath -Lines $baseEnv
            $bootstrapExposureQuarantined = $true
            throw "owner 初始化检测到 listener 暴露；旧 secret 已隔离并登记轮换意图。请重新运行安装器完成离线恢复。"
        }
        catch {
            throw "owner 初始化失败；同一 bootstrap secret 已保留以便重试，临时后端将停止。"
        }
    }
    else {
        Write-Ok "持久 owner 身份保持不变，未调用 HTTP bootstrap。"
    }
}
finally {
    $cleanupFailed = $false
    if ($bootstrapVerifiedAndPersisted) {
        try {
            Write-EnvNoBom -Path $EnvPath -Lines $baseEnv
            Write-Ok "已关闭一次性 bootstrap 开关。"
        }
        catch {
            $cleanupFailed = $true
        }
    }
    else {
        if ($bootstrapExposureQuarantined) {
            Write-Host "    可能暴露的 bootstrap secret 已从运行配置隔离；下次安装必须先完成轮换。" -ForegroundColor Yellow
        }
        else {
            Write-Host "    bootstrap 未完成验证及凭据落盘；受保护 secret 已保留供重试。" -ForegroundColor Yellow
        }
    }
    try {
        Stop-StartedBackendProcess $proc
    }
    catch {
        $cleanupFailed = $true
    }
    $superPwdPlain = $null
    $rolePwd = $null
    $databasePassword = $null
    $databaseUrl = $null
    $bootstrapSecret = $null
    $replacementSecret = $null
    $recoveredBootstrapSecret = $null
    $retainedBootstrapSecret = $null
    $resp = $null
    $lines = $null
    $bootstrapEnv = $null
    $baseEnv = $null
    if ($cleanupFailed) {
        throw "一次性 bootstrap 配置或临时后端未能可靠清理，拒绝继续。"
    }
}

# ── 开机自启任务（执行 EXE 本体）────────────────────────────────────────────
if ($SkipScheduledTask) {
    Write-Step "已跳过开机自启任务（-SkipScheduledTask）"
}
else {
    Write-Step "创建开机自启任务「$TaskName」"
    $action = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory $ExeDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "Start 小票夹 FastAPI backend ($ExePath) on 127.0.0.1:$Port" -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Ok "任务已创建并启动；下次登录 Windows 会自动起后端。"
}

# ── 收尾报告 ────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "================ 安装完成 ================" -ForegroundColor Green
Write-Host "后端地址（本机）: http://127.0.0.1:$Port"
Write-Host "管理台（仅本机）: http://127.0.0.1:$Port/owner"
Write-Host "数据目录       : $DataDir"
Write-Host "配置文件       : $EnvPath（含数据库口令，请勿外泄）"
Write-Host "运行日志       : $(Join-Path $DataDir 'logs\backend.log')（窗口化运行无控制台，排查看这里）"
if ($pairingCode.Trim().Length -gt 0) {
    Write-Host ""
    Write-Host "用 Android App 连接：在 App 里输入服务器地址，再填配对码：" -ForegroundColor Cyan
    Write-Host "    配对码: $pairingCode" -ForegroundColor Yellow
    Write-Host "    （完整凭证见 $bootstrapFile）"
}
Write-Host "=========================================" -ForegroundColor Green
}
finally {
    Exit-TicketboxLifecycleLock $legacyLifecycleLock
}
