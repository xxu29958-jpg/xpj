# 小票夹后端 · 一键安装向导（档 A，本机 PostgreSQL）
#
# 给「会装软件但不写命令行」的自托管用户：把已装好的 PostgreSQL + 本目录的
# ticketbox-backend.exe 一步配好——建应用角色/库、生成 .env、初始化数据库、
# 创建 owner 身份、装开机自启任务。
#
#   右键「用 PowerShell 运行」，或：
#   powershell -ExecutionPolicy Bypass -File install_ticketbox.ps1
#
# 设计红线（见 docs/runbook/POSTGRES_MIGRATION.md §3「表属主陷阱」）：
#   建角色/建库用超级用户，但**建表只能由应用角色 ticketbox 连接执行**——所以
#   这里只用超级用户建空角色+空库，表结构交给 EXE 首次启动（以 ticketbox 连）来建，
#   绝不用超级用户灌表，否则 owner 错位、下一个 ALTER 迁移启动即崩。
param(
    [string]$ExePath = "",
    [string]$DbHost = "localhost",
    [int]$DbPort = 5432,
    [string]$DbName = "ticketbox",
    [string]$DbRole = "ticketbox",
    [string]$SuperUser = "postgres",
    [string]$SuperPassword = "",
    [string]$DbPassword = "",
    [int]$Port = 8000,
    [string]$AccountName = "我",
    [string]$LedgerName = "我的小票夹",
    [string]$DeviceName = "Windows 后端",
    [string]$Timezone = "Asia/Shanghai",
    [string]$PublicBaseUrl = "",
    [switch]$SkipScheduledTask,
    [string]$TaskName = "TicketboxBackend"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "    $msg" -ForegroundColor Green }

# ── EXE + 数据目录 ──────────────────────────────────────────────────────────
# 冻结后端是 onedir 形态（ADR-0047 §8）：EXE 在 ticketbox-backend\ 子文件夹里
# （旁边是 _internal\）。优先找子文件夹，兼容历史的单文件平铺布局。
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
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
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "uploads") | Out-Null

# ── 定位 psql.exe（环境变量 → PATH → Program Files 最高版本）──────────────────
function Find-Psql {
    if ($env:PG_BIN -and (Test-Path -LiteralPath (Join-Path $env:PG_BIN "psql.exe"))) {
        return (Join-Path $env:PG_BIN "psql.exe")
    }
    $onPath = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($null -ne $onPath) { return $onPath.Source }
    $base = "C:\Program Files\PostgreSQL"
    if (Test-Path -LiteralPath $base) {
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
        $psqlArgs = @("-v", "ON_ERROR_STOP=1", "-U", $User, "-h", $DbHost, "-p", "$DbPort", "-d", $Database, "-tAc", $Sql)
        $out = & $Psql @psqlArgs
        if ($LASTEXITCODE -ne 0) {
            if ($Quiet) { return $null }
            throw "psql 执行失败（user=$User db=$Database）：$Sql"
        }
        return ($out | Out-String).Trim()
    }
    finally {
        if ($null -eq $prev) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $prev }
    }
}

function New-StrongPassword {
    # 纯字母数字（避开会破坏 URL/.env 的特殊字符），28 位。
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object 'System.Byte[]' 28
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function Write-EnvNoBom([string]$Path, [string[]]$Lines) {
    # .env 必须**不带 BOM**（PS 5.1 默认会写 BOM；app 端解析不应见 BOM）。
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $utf8NoBom)
}

$Psql = Find-Psql
Write-Step "使用 PostgreSQL 客户端：$Psql"

# ── 超级用户口令（EDB 安装时设的 postgres 口令；trust 部署可留空）────────────
Write-Step "连接 PostgreSQL（$DbHost`:$DbPort）"
if ($PSBoundParameters.ContainsKey('SuperPassword')) {
    # 非交互/自动化路径（传 -SuperPassword "" 表示 trust 模式空口令）。
    $superPwdPlain = $SuperPassword
}
else {
    $superPwdPlain = ""
    $superSecure = Read-Host "请输入 PostgreSQL 超级用户「$SuperUser」口令（trust 模式直接回车）" -AsSecureString
    if ($superSecure.Length -gt 0) {
        $superPwdPlain = [System.Net.NetworkCredential]::new("", $superSecure).Password
    }
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
    if ($DbPassword.Trim().Length -eq 0) {
        throw "角色「$DbRole」已存在。重跑请用 -DbPassword 传入它已有的口令（无法从 PG 读取明文口令）。"
    }
    Write-Ok "角色已存在，沿用传入口令。"
    $rolePwd = $DbPassword
}
else {
    if ($DbPassword.Trim().Length -gt 0) { $rolePwd = $DbPassword } else { $rolePwd = New-StrongPassword }
    Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database "postgres" -Sql "CREATE ROLE `"$DbRole`" LOGIN PASSWORD '$rolePwd'" | Out-Null
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
$databaseUrl = "postgresql+psycopg://${DbRole}:${rolePwd}@${DbHost}:${DbPort}/${DbName}"
$bootstrapSecret = New-StrongPassword
$baseEnv = @(
    "DATABASE_URL=$databaseUrl",
    "TICKETBOX_HOST=127.0.0.1",
    "TICKETBOX_PORT=$Port",
    "MAX_UPLOAD_SIZE_MB=10",
    "GENERATE_THUMBNAIL=true",
    "OCR_PROVIDER=empty",
    "OCR_AUTO_RUN=false",
    "OCR_DEFAULT_TIMEZONE=$Timezone",
    "ENABLE_API_DOCS=false",
    "ALLOW_PUBLIC_ADMIN_API=false",
    "CLOUDFLARE_ACCESS_REQUIRED=false"
)
if ($PublicBaseUrl.Trim().Length -gt 0) { $baseEnv += "PUBLIC_BASE_URL=$PublicBaseUrl" }
# 一次性 HTTP bootstrap：仅本机、一次消费即作废，下面建好 owner 后清掉。
$bootstrapEnv = $baseEnv + @("ENABLE_HTTP_BOOTSTRAP=true", "HTTP_BOOTSTRAP_SECRET=$bootstrapSecret")
Write-EnvNoBom -Path $EnvPath -Lines $bootstrapEnv
Write-Ok "已写入 .env（DATABASE_URL 指向应用角色 $DbRole）。"

# ── 首次启动 EXE：以 ticketbox 连库 → 建表（属主正确）+ 提供 HTTP bootstrap。──
Write-Step "初始化数据库并启动后端（首次建表）"
$proc = Start-Process -FilePath $ExePath -WorkingDirectory $ExeDir -PassThru -WindowStyle Hidden
$baseUrl = "http://127.0.0.1:$Port"
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "$baseUrl/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    }
    catch { Start-Sleep -Seconds 1 }
}
if (-not $healthy) {
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    # 冻结后端是窗口化（console=False），无控制台输出；日志写在数据目录的 logs\backend.log。
    throw "后端启动超时（60s 内 $baseUrl/api/health 未就绪）。查看日志排查：$(Join-Path $DataDir 'logs\backend.log')。"
}
Write-Ok "后端已就绪：$baseUrl"

# ── 表属主自检（堵 owner 陷阱）：非 ticketbox 属主的表应为 0。─────────────────
$mismatch = Invoke-Sql -User $SuperUser -Password $superPwdPlain -Database $DbName -Sql "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner <> '$DbRole'"
if ([int]$mismatch -ne 0) {
    Write-Host "    警告：检测到 $mismatch 张表属主不是 $DbRole（owner 错位陷阱）。" -ForegroundColor Yellow
    $fixSql = Join-Path $ExeDir "fix_table_owners.sql"
    if (-not (Test-Path -LiteralPath $fixSql)) { $fixSql = Join-Path $ScriptDir "fix_table_owners.sql" }
    if (Test-Path -LiteralPath $fixSql) {
        $prev = $env:PGPASSWORD; $env:PGPASSWORD = $superPwdPlain
        try { & $Psql -v ON_ERROR_STOP=1 -U $SuperUser -h $DbHost -p $DbPort -d $DbName -f $fixSql | Out-Null }
        finally { if ($null -eq $prev) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue } else { $env:PGPASSWORD = $prev } }
        Write-Ok "已用 fix_table_owners.sql 归位属主。"
    }
    else {
        Write-Host "    未找到 fix_table_owners.sql；请参见 docs/runbook/POSTGRES_MIGRATION.md §3 手动修复。" -ForegroundColor Yellow
    }
}
else {
    Write-Ok "表属主自检通过（全部归 $DbRole）。"
}

# ── 创建 owner 身份（HTTP 一次性 bootstrap）──────────────────────────────────
Write-Step "创建管理员（owner）身份"
$bootstrapFile = Join-Path $DataDir "owner-bootstrap.txt"
$pairingCode = ""
try {
    $body = @{ account_name = $AccountName; ledger_name = $LedgerName; device_name = $DeviceName; default_timezone = $Timezone } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$baseUrl/api/bootstrap/owner" -Method Post `
        -Headers @{ "X-Bootstrap-Secret" = $bootstrapSecret; "Content-Type" = "application/json" } `
        -Body $body -TimeoutSec 15
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
    Write-Ok "owner 身份已创建，凭证写入：$bootstrapFile"
}
catch {
    $msg = $_.Exception.Message
    Write-Host "    跳过：owner 可能已存在（或 bootstrap 失败）：$msg" -ForegroundColor Yellow
    Write-Host "    已有安装重跑属正常。需要新设备配对码请用 Owner Console（loopback）。" -ForegroundColor Yellow
}

# ── 清掉一次性 bootstrap 开关，写回干净 .env。──────────────────────────────
Write-EnvNoBom -Path $EnvPath -Lines $baseEnv
Write-Ok "已关闭一次性 bootstrap 开关。"

# ── 停掉临时实例（让正式的自启任务/双击来跑）────────────────────────────────
try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
& taskkill /IM ticketbox-backend.exe /T /F 2>$null | Out-Null

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
