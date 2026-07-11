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

function Assert-TicketboxLocalDatabaseUrl([string]$DatabaseUrl, [int]$PgPort) {
    $libpqUrl = ConvertTo-TicketboxLibpqUrl $DatabaseUrl
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
    if (-not [string]::IsNullOrEmpty($uri.Query) -or -not [string]::IsNullOrEmpty($uri.Fragment)) {
        throw "DATABASE_URL 不得包含可覆盖 libpq 连接目标的 query 或 fragment。"
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

    $libpqUrl = Assert-TicketboxLocalDatabaseUrl -DatabaseUrl $DatabaseUrl -PgPort $PgPort
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
        Password = $password
    }
}

function Invoke-TicketboxPgDumpCustom {
    param(
        [Parameter(Mandatory = $true)][string]$PgDumpPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [Parameter(Mandatory = $true)][string]$Password
    )

    $previousPreference = $ErrorActionPreference
    $hadPgPassword = Test-Path Env:PGPASSWORD
    $previousPgPassword = $env:PGPASSWORD
    $ErrorActionPreference = "Continue"
    try {
        if ($Password.Length -gt 0) {
            $env:PGPASSWORD = $Password
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        & $PgDumpPath --no-password --format=custom --file $OutputPath --dbname $DatabaseUrl 2>&1 | Out-Null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
        if ($hadPgPassword) {
            $env:PGPASSWORD = $previousPgPassword
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
    }
}

function Assert-TicketboxConnectedPostgresDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$ExpectedDataRoot,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$ExpectedPort,
        [Parameter(Mandatory = $true)][string]$Password
    )

    $previousPreference = $ErrorActionPreference
    $hadPgPassword = Test-Path Env:PGPASSWORD
    $previousPgPassword = $env:PGPASSWORD
    $ErrorActionPreference = "Continue"
    try {
        if ($Password.Length -gt 0) {
            $env:PGPASSWORD = $Password
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        $output = & $PsqlPath `
            --dbname $DatabaseUrl `
            --no-psqlrc `
            --no-password `
            --tuples-only `
            --no-align `
            --field-separator "`t" `
            --set ON_ERROR_STOP=1 `
            --command "SELECT current_setting('data_directory'), current_setting('listen_addresses'), current_setting('port')" 2>&1
        $rc = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
        if ($hadPgPassword) {
            $env:PGPASSWORD = $previousPgPassword
        }
        else {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
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
