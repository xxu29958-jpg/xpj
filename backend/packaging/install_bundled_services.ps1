#Requires -Version 5.1
<#
.SYNOPSIS
  ADR-0047 Slice 4: install or upgrade the bundled Ticketbox Windows services.

.DESCRIPTION
  This is the script run by the Inno installer after files have been copied to
  Program Files. It keeps mutable data in ProgramData, registers the bundled
  PostgreSQL service plus the frozen backend service, and preserves existing data
  on upgrades. Existing databases are snapshotted with pg_dump before the new
  backend is allowed to start and run migrations.

  PowerShell 5.1 file encoding must be UTF-8 with BOM. The generated .env is
  deliberately UTF-8 without BOM.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$DataRoot = "C:\ProgramData\Ticketbox",
    [int]$PgPort = 5432,
    [int]$BackendPort = 8000,
    [string]$PgServiceName = "TicketboxPg",
    [string]$BackendServiceName = "TicketboxBackend",
    [string]$DbName = "ticketbox",
    [string]$DbRole = "ticketbox",
    [string]$AccountName = "我",
    [string]$LedgerName = "我的小票夹",
    [string]$DeviceName = "Windows 后端",
    [string]$Timezone = "Asia/Shanghai",
    [string]$PublicBaseUrl = "",
    [int]$StopTimeoutMs = 25000,
    [switch]$SkipServiceStart,
    [switch]$SkipPreUpgradeBackup,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($InstallDir.Trim().Length -eq 0) {
    $InstallDir = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
}

$PgHome = Join-Path $InstallDir "pg"
$PgBin = Join-Path $PgHome "bin"
$PgData = Join-Path $DataRoot "pgdata"
$AppData = Join-Path $DataRoot "app"
$LogDir = Join-Path $AppData "logs"
$BackupDir = Join-Path $AppData "backups"
$EnvPath = Join-Path $AppData ".env"
$OwnerBootstrapPath = Join-Path $AppData "owner-bootstrap.txt"
$ProgramDir = Join-Path $InstallDir "program\ticketbox-backend"
$BackendExe = Join-Path $ProgramDir "ticketbox-backend.exe"
$ShawlExe = Join-Path $InstallDir "shawl\shawl.exe"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn2([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Assert-Admin {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator
    )
    if (-not $admin) {
        throw "需要管理员权限运行安装脚本。"
    }
}

function Assert-SimpleIdentifier([string]$Value, [string]$Name) {
    if ($Value -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "$Name 只能包含字母、数字、下划线，且不能以数字开头：$Value"
    }
}

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 $Label：$Path"
    }
}

function Assert-Dir([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "缺少 $Label：$Path"
    }
}

function Service-Exists([string]$Name) {
    return $null -ne (Get-Service -Name $Name -ErrorAction SilentlyContinue)
}

function Invoke-ScChecked([string[]]$ScArgs) {
    $out = & sc.exe @ScArgs 2>&1
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {
        throw "sc.exe $($ScArgs -join ' ') 失败（exit=$rc）：`n$out"
    }
    return ($out | Out-String).Trim()
}

function Wait-ServiceGone([string]$Name) {
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (Service-Exists $Name)) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    if (Service-Exists $Name) {
        throw "服务 $Name 删除后仍存在，请稍后重试或检查服务管理器。"
    }
}

function Stop-ServiceIfExists([string]$Name) {
    if (-not (Service-Exists $Name)) {
        return
    }
    try {
        Stop-Service -Name $Name -Force -ErrorAction Stop
    }
    catch {
        Write-Warn2 "停止服务 $Name 失败：$($_.Exception.Message)"
    }
}

function Remove-ServiceIfExists([string]$Name) {
    if (-not (Service-Exists $Name)) {
        return
    }
    Stop-ServiceIfExists $Name
    Invoke-ScChecked @("delete", $Name) | Out-Null
    Wait-ServiceGone $Name
}

function Invoke-PgCtlStop {
    $pgctl = Join-Path $PgBin "pg_ctl.exe"
    if ((Test-Path -LiteralPath $pgctl) -and (Test-Path -LiteralPath (Join-Path $PgData "postmaster.pid"))) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $pgctl -D $PgData -m fast -w -t 30 stop 2>$null | Out-Null
        $ErrorActionPreference = $prev
    }
}

function Write-EnvNoBom([string]$Path, [string[]]$Lines) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $utf8NoBom)
}

function New-StrongPassword {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object 'System.Byte[]' 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
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

function ConvertTo-LibpqUrl([string]$DatabaseUrl) {
    return ($DatabaseUrl -replace '^postgresql\+\w+://', 'postgresql://')
}

function New-BaseEnvLines([string]$DatabaseUrl) {
    $lines = @(
        "DATABASE_URL=$DatabaseUrl",
        "TICKETBOX_HOST=127.0.0.1",
        "TICKETBOX_PORT=$BackendPort",
        "TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS=25",
        "PG_DUMP_PATH=$(Join-Path $PgBin 'pg_dump.exe')",
        "PG_RESTORE_PATH=$(Join-Path $PgBin 'pg_restore.exe')",
        "MAX_UPLOAD_SIZE_MB=10",
        "GENERATE_THUMBNAIL=true",
        "OCR_PROVIDER=empty",
        "OCR_AUTO_RUN=false",
        "OCR_DEFAULT_TIMEZONE=$Timezone",
        "ENABLE_API_DOCS=false",
        "ALLOW_PUBLIC_ADMIN_API=false",
        "CLOUDFLARE_ACCESS_REQUIRED=false"
    )
    if ($PublicBaseUrl.Trim().Length -gt 0) {
        $lines += "PUBLIC_BASE_URL=$PublicBaseUrl"
    }
    return $lines
}

function Invoke-Psql([string]$Database, [string]$Sql, [string]$Password) {
    $prev = $env:PGPASSWORD
    $env:PGPASSWORD = $Password
    try {
        $psql = Join-Path $PgBin "psql.exe"
        $args = @("-v", "ON_ERROR_STOP=1", "-U", "postgres", "-h", "127.0.0.1", "-p", "$PgPort", "-d", $Database, "-tAc", $Sql)
        $out = & $psql @args 2>&1
        $rc = $LASTEXITCODE
        if ($rc -ne 0) {
            throw "psql 执行失败（db=$Database）：$Sql`n$out"
        }
        return ($out | Out-String).Trim()
    }
    finally {
        if ($null -eq $prev) {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
        else {
            $env:PGPASSWORD = $prev
        }
    }
}

function Wait-PgReady {
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $PgPort -q | Out-Null
        $rc = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($rc -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "PostgreSQL 服务未在 90s 内就绪（127.0.0.1:$PgPort）。"
    }
}

function Register-PgService {
    Write-Step "注册 PostgreSQL 服务 $PgServiceName"
    Remove-ServiceIfExists $PgServiceName
    & (Join-Path $PgBin "pg_ctl.exe") register -N $PgServiceName -D $PgData -S auto | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "pg_ctl register 失败（exit=$LASTEXITCODE）。"
    }
    Invoke-ScChecked @("config", $PgServiceName, "obj=", "NT SERVICE\$PgServiceName") | Out-Null
    Invoke-ScChecked @("config", $PgServiceName, "start=", "delayed-auto") | Out-Null
    Invoke-ScChecked @("failure", $PgServiceName, "reset=", "3600", "actions=", "restart/5000/restart/10000/restart/60000") | Out-Null
    Write-Ok "PG 服务已注册为虚拟账户 NT SERVICE\$PgServiceName。"
}

function Register-BackendService {
    Write-Step "注册后端服务 $BackendServiceName"
    Remove-ServiceIfExists $BackendServiceName
    & $ShawlExe add --name $BackendServiceName `
        --dependencies $PgServiceName `
        --stop-timeout $StopTimeoutMs `
        --restart --restart-delay 5000 `
        --cwd $AppData `
        --log-dir $LogDir `
        --env "TICKETBOX_DATA_DIR=$AppData" `
        --env "PG_DUMP_PATH=$(Join-Path $PgBin 'pg_dump.exe')" `
        --env "PG_RESTORE_PATH=$(Join-Path $PgBin 'pg_restore.exe')" `
        -- $BackendExe | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "shawl add 失败（exit=$LASTEXITCODE）。"
    }
    Invoke-ScChecked @("config", $BackendServiceName, "obj=", "NT SERVICE\$BackendServiceName") | Out-Null
    Invoke-ScChecked @("config", $BackendServiceName, "start=", "delayed-auto") | Out-Null
    Invoke-ScChecked @("failure", $BackendServiceName, "reset=", "3600", "actions=", "restart/5000/restart/10000/restart/60000") | Out-Null
    Write-Ok "后端服务已注册为虚拟账户 NT SERVICE\$BackendServiceName。"
}

function Set-TicketboxAcl {
    Write-Step "收紧 ProgramData ACL"
    New-Item -ItemType Directory -Force -Path $DataRoot, $PgData, $AppData, $LogDir, $BackupDir | Out-Null

    & icacls $DataRoot /inheritance:r | Out-Null
    & icacls $DataRoot /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${PgServiceName}:(OI)(CI)F" "NT SERVICE\${BackendServiceName}:(OI)(CI)F" | Out-Null
    & icacls $PgData /inheritance:r | Out-Null
    & icacls $PgData /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${PgServiceName}:(OI)(CI)F" | Out-Null
    & icacls $AppData /inheritance:r | Out-Null
    & icacls $AppData /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${BackendServiceName}:(OI)(CI)F" | Out-Null
    & icacls $ProgramDir /grant "NT SERVICE\${BackendServiceName}:(OI)(CI)RX" | Out-Null
    & icacls $PgHome /grant "NT SERVICE\${PgServiceName}:(OI)(CI)RX" | Out-Null
    Write-Ok "数据根已限制为 SYSTEM / Administrators / Ticketbox 服务账户。"
}

function Assert-PortAvailableForFreshInstall {
    if ((Test-Path -LiteralPath $PgData) -or (Service-Exists $PgServiceName)) {
        return
    }
    $pgBusy = Get-NetTCPConnection -State Listen -LocalPort $PgPort -ErrorAction SilentlyContinue
    if ($null -ne $pgBusy) {
        throw "PG 端口 $PgPort 已被占用。首次安装不能覆盖现有 PostgreSQL；请换端口或先清理占用。"
    }
    $backendBusy = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue
    if ($null -ne $backendBusy) {
        throw "后端端口 $BackendPort 已被占用。请换端口或先清理占用。"
    }
}

function Initialize-PgClusterIfNeeded {
    if (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION")) {
        Write-Ok "发现既有 PG 簇，跳过 initdb：$PgData"
        return $null
    }

    Write-Step "初始化 PostgreSQL 簇"
    New-Item -ItemType Directory -Force -Path $PgData | Out-Null
    $pwfile = Join-Path ([System.IO.Path]::GetTempPath()) ("ticketbox_pg_pw_" + [System.Guid]::NewGuid().ToString("N") + ".txt")
    $superPassword = New-StrongPassword
    $superPassword | Out-File -LiteralPath $pwfile -Encoding ascii -NoNewline
    try {
        & (Join-Path $PgBin "initdb.exe") -D $PgData -U postgres --auth-local=scram-sha-256 --auth-host=scram-sha-256 --encoding=UTF8 --no-locale --pwfile=$pwfile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "initdb 失败（exit=$LASTEXITCODE）。"
        }
    }
    finally {
        Remove-Item -LiteralPath $pwfile -Force -ErrorAction SilentlyContinue
    }

    Add-Content -LiteralPath (Join-Path $PgData "postgresql.conf") -Encoding ascii -Value @(
        "",
        "# Ticketbox installer overrides",
        "listen_addresses = '127.0.0.1'",
        "port = $PgPort"
    )
    Write-Ok "PG 簇已初始化（loopback-only, scram-sha-256）。"
    return $superPassword
}

function Prepare-DatabaseIfNeeded([string]$SuperPassword) {
    $existingEnv = Read-EnvMap $EnvPath
    if ($existingEnv.ContainsKey("DATABASE_URL")) {
        Write-Ok "发现既有 .env，沿用 DATABASE_URL。"
        return $existingEnv["DATABASE_URL"]
    }
    if (-not $SuperPassword) {
        throw "既有 PG 簇缺少 $EnvPath，无法安全推断应用角色口令。请先恢复 .env 或手动备份后处理。"
    }

    Write-Step "创建应用角色和数据库"
    $rolePassword = New-StrongPassword
    $rolePwdSql = Escape-SqlLiteral $rolePassword
    $roleExists = (Invoke-Psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname='$DbRole'" $SuperPassword) -eq "1"
    if (-not $roleExists) {
        Invoke-Psql "postgres" "CREATE ROLE `"$DbRole`" LOGIN PASSWORD '$rolePwdSql'" $SuperPassword | Out-Null
    }
    $dbExists = (Invoke-Psql "postgres" "SELECT 1 FROM pg_database WHERE datname='$DbName'" $SuperPassword) -eq "1"
    if (-not $dbExists) {
        Invoke-Psql "postgres" "CREATE DATABASE `"$DbName`" OWNER `"$DbRole`" ENCODING 'UTF8'" $SuperPassword | Out-Null
    }
    $databaseUrl = "postgresql+psycopg://${DbRole}:${rolePassword}@127.0.0.1:${PgPort}/${DbName}"
    $bootstrapSecret = New-StrongPassword
    $lines = (New-BaseEnvLines $databaseUrl) + @(
        "ENABLE_HTTP_BOOTSTRAP=true",
        "HTTP_BOOTSTRAP_SECRET=$bootstrapSecret"
    )
    Write-EnvNoBom -Path $EnvPath -Lines $lines
    Write-Ok "已写入首次安装 .env。"
    return $databaseUrl
}

function Invoke-PreUpgradeBackupIfNeeded {
    $envMap = Read-EnvMap $EnvPath
    if (-not $envMap.ContainsKey("DATABASE_URL")) {
        if (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION")) {
            throw "发现既有 PG 数据，但 $EnvPath 缺少 DATABASE_URL；拒绝无备份升级。"
        }
        return
    }
    if ($SkipPreUpgradeBackup) {
        Write-Warn2 "SkipPreUpgradeBackup 已设置，跳过服务层升级前备份。"
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $PgData "PG_VERSION"))) {
        return
    }

    Write-Step "创建服务层升级前备份"
    if (-not (Service-Exists $PgServiceName)) {
        Register-PgService
    }
    Start-Service -Name $PgServiceName -ErrorAction SilentlyContinue
    Wait-PgReady

    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $target = Join-Path $BackupDir "ticketbox-pre-upgrade-installer-$stamp.dump"
    $temp = "$target.tmp"
    $libpqUrl = ConvertTo-LibpqUrl $envMap["DATABASE_URL"]
    & (Join-Path $PgBin "pg_dump.exe") --format=custom --file $temp --dbname $libpqUrl 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        throw "升级前 pg_dump 失败，拒绝启动新后端。请检查 $LogDir 与 PostgreSQL 服务。"
    }
    & (Join-Path $PgBin "pg_restore.exe") --list $temp 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        throw "升级前备份校验失败，拒绝启动新后端。"
    }
    Move-Item -LiteralPath $temp -Destination $target -Force
    Write-Ok "升级前备份已写入：$target"
}

function Wait-BackendHealth {
    $url = "http://127.0.0.1:$BackendPort/api/health"
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                Write-Ok "后端已就绪：$url"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "后端服务启动超时：$url"
}

function Complete-FirstOwnerBootstrapIfEnabled([string]$DatabaseUrl) {
    $envMap = Read-EnvMap $EnvPath
    if (-not $envMap.ContainsKey("HTTP_BOOTSTRAP_SECRET")) {
        return
    }
    $secret = $envMap["HTTP_BOOTSTRAP_SECRET"]
    if ($secret.Trim().Length -eq 0) {
        return
    }

    Write-Step "首次初始化 owner 身份"
    $url = "http://127.0.0.1:$BackendPort/api/bootstrap/owner"
    $body = @{
        account_name = $AccountName
        ledger_name = $LedgerName
        device_name = $DeviceName
        default_timezone = $Timezone
    } | ConvertTo-Json
    $completed = $false
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Post `
            -Headers @{ "X-Bootstrap-Secret" = $secret; "Content-Type" = "application/json" } `
            -Body $body -TimeoutSec 20
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
        Write-EnvNoBom -Path $OwnerBootstrapPath -Lines $lines
        Write-Ok "owner 凭证已写入：$OwnerBootstrapPath"
        $completed = $true
    }
    catch {
        $message = $_.Exception.Message
        if ($message -notmatch "bootstrap_already_initialized") {
            throw "owner 初始化失败：$message"
        }
        Write-Warn2 "owner 已存在，跳过首次初始化。"
        $completed = $true
    }

    if ($completed) {
        Write-EnvNoBom -Path $EnvPath -Lines (New-BaseEnvLines $DatabaseUrl)
        Restart-Service -Name $BackendServiceName -Force
        Wait-BackendHealth
    }
}

Write-Host "=== 小票夹 Inno 安装器服务配置 ===" -ForegroundColor Cyan
Assert-SimpleIdentifier $DbName "DbName"
Assert-SimpleIdentifier $DbRole "DbRole"

Write-Step "校验安装输入"
Assert-Dir $InstallDir "安装目录"
Assert-File (Join-Path $PgBin "initdb.exe") "initdb.exe"
Assert-File (Join-Path $PgBin "postgres.exe") "postgres.exe"
Assert-File (Join-Path $PgBin "pg_ctl.exe") "pg_ctl.exe"
Assert-File (Join-Path $PgBin "psql.exe") "psql.exe"
Assert-File (Join-Path $PgBin "pg_dump.exe") "pg_dump.exe"
Assert-File (Join-Path $PgBin "pg_restore.exe") "pg_restore.exe"
Assert-File $BackendExe "ticketbox-backend.exe"
Assert-File $ShawlExe "shawl.exe"
Write-Ok "安装输入齐备。"

if ($ValidateOnly) {
    Write-Host ""
    Write-Host "ValidateOnly OK。" -ForegroundColor Green
    return
}

Assert-Admin
Assert-PortAvailableForFreshInstall

New-Item -ItemType Directory -Force -Path $DataRoot, $AppData, $LogDir, $BackupDir | Out-Null

Stop-ServiceIfExists $BackendServiceName
Invoke-PreUpgradeBackupIfNeeded

$superPassword = Initialize-PgClusterIfNeeded
Register-PgService
Set-TicketboxAcl

Write-Step "启动 PostgreSQL"
Start-Service -Name $PgServiceName
Wait-PgReady
$databaseUrl = Prepare-DatabaseIfNeeded $superPassword

Register-BackendService
Set-TicketboxAcl

if ($SkipServiceStart) {
    Write-Warn2 "SkipServiceStart 已设置，服务已注册但未启动后端。"
}
else {
    Write-Step "启动后端服务"
    Start-Service -Name $BackendServiceName
    Wait-BackendHealth
    Complete-FirstOwnerBootstrapIfEnabled $databaseUrl
}

Write-Host ""
Write-Host "================ 安装完成 ================" -ForegroundColor Green
Write-Host "安装目录 : $InstallDir"
Write-Host "数据目录 : $DataRoot"
Write-Host "后端地址 : http://127.0.0.1:$BackendPort"
Write-Host "owner 凭证: $OwnerBootstrapPath（首次安装时生成）"
Write-Host "=========================================" -ForegroundColor Green
