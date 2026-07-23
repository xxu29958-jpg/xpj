#Requires -Version 5.1

<#
.SYNOPSIS
  Shared database safety helpers for the bundled Ticketbox Windows installer.
.DESCRIPTION
  Validates loopback libpq targets, keeps credentials out of process argv, and
  verifies that backup commands are connected to the expected PostgreSQL data root.
#>

function ConvertTo-TicketboxLibpqUrl([string]$DatabaseUrl) {
    return $DatabaseUrl -replace '^postgresql\+\w+://', 'postgresql://'
}

function ConvertTo-TicketboxRequiredDatabaseUrl([string]$DatabaseUrl) {
    $driverMatch = [regex]::Match($DatabaseUrl, '^postgresql(?<driver>\+\w+)?://')
    if (-not $driverMatch.Success) {
        throw "DATABASE_URL 不是有效 PostgreSQL URL，拒绝继续。"
    }
    $libpqUrl = ConvertTo-TicketboxLibpqUrl $DatabaseUrl
    try {
        $builder = New-Object System.UriBuilder($libpqUrl)
    }
    catch {
        throw "DATABASE_URL 不是有效 PostgreSQL URL，拒绝继续。"
    }
    if (-not [string]::IsNullOrEmpty($builder.Fragment)) {
        throw "DATABASE_URL 不得包含 fragment。"
    }
    $query = $builder.Query.TrimStart('?')
    if (
        -not [string]::IsNullOrEmpty($query) -and
        $query -cne 'require_auth=scram-sha-256'
    ) {
        throw "DATABASE_URL query 必须只包含 require_auth=scram-sha-256。"
    }
    $builder.Query = 'require_auth=scram-sha-256'
    $hardened = $builder.Uri.AbsoluteUri
    if (-not [string]::IsNullOrEmpty($driverMatch.Groups['driver'].Value)) {
        $hardened = $hardened -replace '^postgresql://', (
            'postgresql' + $driverMatch.Groups['driver'].Value + '://'
        )
    }
    return $hardened
}

function Assert-TicketboxLocalDatabaseUrl([string]$DatabaseUrl, [int]$PgPort) {
    $libpqUrl = ConvertTo-TicketboxLibpqUrl (
        ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    )
    try {
        $uri = [System.Uri]$libpqUrl
    }
    catch {
        throw "DATABASE_URL 不是有效 PostgreSQL URL，拒绝继续。"
    }
    $address = $null
    $isLoopbackIp =
        [System.Net.IPAddress]::TryParse($uri.Host, [ref]$address) -and
        [System.Net.IPAddress]::IsLoopback($address)
    if ($uri.Scheme -ne "postgresql" -or -not $isLoopbackIp -or $uri.Port -ne $PgPort) {
        throw "DATABASE_URL 必须指向本机 PostgreSQL 端口 $PgPort，拒绝操作其它数据库。"
    }
    return $libpqUrl
}

function Get-TicketboxLocalDatabaseConnection {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][int]$PgPort,
        [Parameter(Mandatory = $true)][string]$ExpectedDatabase,
        [Parameter(Mandatory = $true)][string]$ExpectedRole
    )

    $persistedDatabaseUrl = ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    $libpqUrl = Assert-TicketboxLocalDatabaseUrl `
        -DatabaseUrl $persistedDatabaseUrl `
        -PgPort $PgPort
    $builder = New-Object System.UriBuilder($libpqUrl)
    $role = [System.Uri]::UnescapeDataString($builder.UserName)
    $database = [System.Uri]::UnescapeDataString($builder.Path.TrimStart("/"))
    if (-not [string]::Equals($role, $ExpectedRole, [System.StringComparison]::Ordinal)) {
        throw "DATABASE_URL 的 PostgreSQL 角色为 $role，预期为 $ExpectedRole。"
    }
    if (-not [string]::Equals($database, $ExpectedDatabase, [System.StringComparison]::Ordinal)) {
        throw "DATABASE_URL 的数据库为 $database，预期为 $ExpectedDatabase。"
    }
    $password = [System.Uri]::UnescapeDataString($builder.Password)
    if ([string]::IsNullOrWhiteSpace($password)) {
        throw "DATABASE_URL 必须包含非空 PostgreSQL 应用角色口令。"
    }
    $builder.Password = ""
    return [pscustomobject]@{
        DatabaseUrl = $builder.Uri.AbsoluteUri
        PersistedDatabaseUrl = $persistedDatabaseUrl
        Password = $password
    }
}

function ConvertTo-TicketboxPgPassField([string]$Value) {
    if ($Value.IndexOfAny([char[]]@("`r", "`n", [char]0)) -ge 0) {
        throw "PostgreSQL 连接字段不能写入 passfile。"
    }
    return $Value.Replace("\", "\\").Replace(":", "\:")
}

function ConvertTo-TicketboxNativeCommandLineArgument([string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
        }
        else {
            [void]$builder.Append(('\' * $backslashes))
            [void]$builder.Append($character)
        }
        $backslashes = 0
    }
    [void]$builder.Append(('\' * ($backslashes * 2)))
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-TicketboxBoundedNativeProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label,
        [AllowEmptyString()][string]$StandardInputText
    )

    $resolvedExecutable = [System.IO.Path]::GetFullPath($FilePath)
    if ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedExecutable) -cne 'File') {
        throw "$Label 可执行文件不是普通文件：$resolvedExecutable"
    }
    Assert-NoTicketboxAncestorReparsePoints $resolvedExecutable
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $resolvedExecutable
    $startInfo.Arguments = (@(
        $Arguments | ForEach-Object {
            ConvertTo-TicketboxNativeCommandLineArgument ([string]$_)
        }
    ) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "$Label 启动失败。"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if ($PSBoundParameters.ContainsKey("StandardInputText")) {
            $process.StandardInput.Write($StandardInputText)
            $process.StandardInput.Flush()
        }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            try { $process.Kill() } catch {}
            if (-not $process.WaitForExit(5000)) {
                throw "$Label 超时后无法终止精确进程。"
            }
            [void]$stdoutTask.Result
            [void]$stderrTask.Result
            throw "$Label 超过允许的 $TimeoutMilliseconds 毫秒，已终止。"
        }
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StandardOutput = [string]$stdoutTask.Result
            StandardError = [string]$stderrTask.Result
        }
    }
    finally {
        $process.Dispose()
    }
}

function Get-TicketboxProtectedPgPassDirectory {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    $isElevated = $principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if ($isElevated) {
        $parent = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::CommonProgramFiles
        )
        $accounts = @("SYSTEM", "BUILTIN\Administrators")
        $ownerAccount = "SYSTEM"
        $root = Join-Path $parent "Ticketbox"
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $root `
            -FullControlAccounts $accounts `
            -OwnerAccount $ownerAccount | Out-Null
        $directory = Join-Path $root "installer-secrets"
    }
    else {
        $parent = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::LocalApplicationData
        )
        $accounts = @($identity.User.Value)
        $ownerAccount = $identity.User.Value
        $directory = Join-Path $parent "TicketboxInstallerSecrets"
    }
    if ([string]::IsNullOrWhiteSpace($parent)) {
        throw "Windows 未提供受保护的本机凭据根目录。"
    }
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $directory `
        -FullControlAccounts $accounts `
        -OwnerAccount $ownerAccount | Out-Null
    # The longest supported database-tool budget is one hour. Keep a second
    # hour of margin so scavenging can never delete another live invocation's
    # passfile while still recovering crash residue deterministically.
    $staleBefore = [DateTime]::UtcNow.AddHours(-2)
    foreach ($item in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
        if ($item.Name -notlike '.ticketbox-pgpass-*') {
            throw "PostgreSQL 临时凭据目录含有未知对象：$($item.FullName)"
        }
        if ((Get-TicketboxPathEntryKindNoFollow -Path $item.FullName) -cne 'File') {
            throw "PostgreSQL 临时凭据不是普通文件：$($item.FullName)"
        }
        Assert-TicketboxExactFileAcl `
            -Path $item.FullName `
            -Accounts $accounts `
            -OwnerAccount $ownerAccount
        if ($item.LastWriteTimeUtc -lt $staleBefore) {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path $item.FullName `
                -FullControlAccounts $accounts `
                -OwnerAccount $ownerAccount
        }
    }
    return [pscustomobject]@{
        Path = $directory
        FullControlAccounts = $accounts
        OwnerAccount = $ownerAccount
    }
}

function New-TicketboxProtectedPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password
    )

    if ([string]::IsNullOrWhiteSpace($Password)) {
        throw "PostgreSQL passfile 必须使用显式非空口令。"
    }
    $requiredUrl = ConvertTo-TicketboxRequiredDatabaseUrl $DatabaseUrl
    $builder = New-Object System.UriBuilder((ConvertTo-TicketboxLibpqUrl $requiredUrl))
    $username = [System.Uri]::UnescapeDataString($builder.UserName)
    $database = [System.Uri]::UnescapeDataString($builder.Path.TrimStart('/'))
    if (
        [string]::IsNullOrWhiteSpace($username) -or
        [string]::IsNullOrWhiteSpace($builder.Host) -or
        [string]::IsNullOrWhiteSpace($database)
    ) {
        throw "PostgreSQL passfile 缺少用户、主机或数据库。"
    }
    $directory = Get-TicketboxProtectedPgPassDirectory
    $passfile = Join-Path `
        $directory.Path `
        (".ticketbox-pgpass-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
    $port = if ($builder.Port -gt 0) { $builder.Port } else { 5432 }
    $fields = @($builder.Host, [string]$port, $database, $username, $Password) |
        ForEach-Object { ConvertTo-TicketboxPgPassField ([string]$_) }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $passfile `
        -Text (($fields -join ':') + "`n") `
        -FullControlAccounts $directory.FullControlAccounts `
        -OwnerAccount $directory.OwnerAccount | Out-Null
    return [pscustomobject]@{
        Path = $passfile
        FullControlAccounts = $directory.FullControlAccounts
        OwnerAccount = $directory.OwnerAccount
        DatabaseUrl = (ConvertTo-TicketboxLibpqUrl $requiredUrl)
    }
}

function Invoke-TicketboxWithPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $protected = New-TicketboxProtectedPgPassFile `
        -DatabaseUrl $DatabaseUrl `
        -Password $Password
    $hadPgPassword = Test-Path Env:PGPASSWORD
    $previousPgPassword = $env:PGPASSWORD
    $hadPgPassFile = Test-Path Env:PGPASSFILE
    $previousPgPassFile = $env:PGPASSFILE
    try {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        $env:PGPASSFILE = $protected.Path
        return & $Action $protected.DatabaseUrl
    }
    finally {
        try {
            Remove-TicketboxProtectedUtf8Artifact `
                -Path $protected.Path `
                -FullControlAccounts $protected.FullControlAccounts `
                -OwnerAccount $protected.OwnerAccount
        }
        finally {
            if ($hadPgPassword) {
                $env:PGPASSWORD = $previousPgPassword
            }
            else {
                Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
            }
            if ($hadPgPassFile) {
                $env:PGPASSFILE = $previousPgPassFile
            }
            else {
                Remove-Item Env:PGPASSFILE -ErrorAction SilentlyContinue
            }
        }
    }
}

function Invoke-TicketboxPgDumpCustom {
    param(
        [Parameter(Mandatory = $true)][string]$PgDumpPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        return Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $DatabaseUrl `
            -Password $Password `
            -Action {
                param([string]$ProtectedDatabaseUrl)
                $result = Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $PgDumpPath `
                    -Arguments @(
                        '--no-password',
                        '--lock-wait-timeout=30000',
                        '--format=custom',
                        '--file', $OutputPath,
                        '--dbname', $ProtectedDatabaseUrl
                    ) `
                    -TimeoutMilliseconds $TimeoutMilliseconds `
                    -Label 'pg_dump'
                return $result.ExitCode
            }
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-TicketboxPgRestoreList {
    param(
        [Parameter(Mandatory = $true)][string]$PgRestorePath,
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $result = Invoke-TicketboxBoundedNativeProcess `
        -FilePath $PgRestorePath `
        -Arguments @('--list', $ArchivePath) `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -Label 'pg_restore --list'
    return $result.ExitCode
}

function Assert-TicketboxConnectedPostgresDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$ExpectedDataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$ExpectedPort,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $result = Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $DatabaseUrl `
            -Password $Password `
            -Action {
                param([string]$ProtectedDatabaseUrl)
                $commandResult = Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $PsqlPath `
                    -Arguments @(
                        '--dbname', $ProtectedDatabaseUrl,
                        '--no-psqlrc',
                        '--no-password',
                        '--tuples-only',
                        '--no-align',
                        '--field-separator', "`t",
                        '--set', 'ON_ERROR_STOP=1'
                    ) `
                    -StandardInputText (
                        "SELECT current_setting('data_directory'), " +
                        "current_setting('listen_addresses'), " +
                        "current_setting('port');`n"
                    ) `
                    -TimeoutMilliseconds $TimeoutMilliseconds `
                    -Label 'psql PostgreSQL data-root verification'
                return [pscustomobject]@{
                    Output = @($commandResult.StandardOutput -split "`r?`n")
                    ExitCode = $commandResult.ExitCode
                }
            }
        $output = $result.Output
        $rc = $result.ExitCode
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($rc -ne 0) {
        throw "无法验证 PostgreSQL data_directory/listen_addresses/port（exit=$rc）：`n$output"
    }
    $lines = @($output | ForEach-Object { [string]$_ } | Where-Object { $_.Trim().Length -gt 0 })
    if ($lines.Count -ne 1) {
        throw "PostgreSQL 运行时边界返回格式异常，拒绝继续。"
    }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne 3) {
        throw "PostgreSQL 运行时边界字段数量异常，拒绝继续。"
    }
    $actual = ConvertTo-TicketboxCanonicalPath $fields[0].Trim()
    $expected = ConvertTo-TicketboxCanonicalPath $ExpectedDataRoot
    if (-not (Test-TicketboxPathEquals $actual $expected)) {
        throw "DATABASE_URL 连接的数据目录为 $actual，预期为 $expected，拒绝操作其它实例。"
    }
    if ([string]$fields[1].Trim() -cne "127.0.0.1") {
        throw "PostgreSQL 生效 listen_addresses 不是 127.0.0.1，拒绝继续。"
    }
    $actualPort = 0
    if (-not [int]::TryParse($fields[2].Trim(), [ref]$actualPort) -or $actualPort -ne $ExpectedPort) {
        throw "PostgreSQL 生效端口与安装配置不一致，拒绝继续。"
    }
}
