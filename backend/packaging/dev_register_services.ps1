#Requires -Version 5.1
<#
.SYNOPSIS
  ADR-0047 Slice 2-D：把捆绑 PG + 冻结后端 EXE 注册成两个 Windows 服务（Shawl 包后端 +
  pg_ctl register PG），落 C:\ProgramData\Ticketbox，用于在 Inno 安装器（Slice 4）之前
  *在开发机上*验证 Option D 的服务模型（独立虚拟服务账户 / ACL / depend= / connect-retry /
  优雅关停）。**不发给最终用户**——用户走 Inno 安装器。

.DESCRIPTION
  本脚本是自洽的「装 → 起 → 验 → 卸」开发验收工具：

    install（默认）：
      1) 校验管理员 + 端口安全（拒绝 prod 5432 / CI 5433 / test 5438；后端拒绝 prod 8000）。
      2) 复制捆绑 PG（vendor\pg）到 <Root>\pg、复制冻结后端 onedir（dist\ticketbox-backend）
         到 <Root>\program\ticketbox-backend。
      3) initdb 一套**独立**簇 <Root>\pgdata（loopback-only + 指定端口；trust 本地鉴权，
         靠 ACL + loopback 兜安全）。**绝不**碰系统已装的 PG（5432）或测试簇（5438）。
      4) pg_ctl register PG 服务 → sc config obj= 专属虚拟账户 NT SERVICE\<PgService> →
         icacls 簇/二进制目录断继承 + 只授 SYSTEM/Administrators/该账户。
      5) 以超级用户建空角色 + 空库（OWNER=应用角色）；表交给后端首启（以应用角色连）建，堵
         owner 错位陷阱（docs/runbook/POSTGRES_MIGRATION.md §3）。
      6) 写 <Root>\app\.env（**无 BOM**，DATABASE_URL 指向应用角色）。
      7) shawl add 包冻结后端 → --env TICKETBOX_DATA_DIR=<Root>\app --dependencies <PgService>
         --stop-timeout <ms> --restart → sc config obj= NT SERVICE\<BackendService> →
         icacls 程序目录(RX)/数据目录(F)。
      8) 起两服务，逐条过 ADR Confirmation：health 200 / owner-trap=0 / 优雅关停 / ACL /
         connect-retry。

    -Teardown：停 + 删两服务（按精确名）+ 删 <Root>。**只**动本脚本建的东西。

.NOTES
  ★PROD 安全红线（本机同时跑着 prod PG 5432 / prod 后端 8000 / test PG 5438）：
    - 端口默认走开发隔离值（PG 5440 / 后端 8001），并**硬拒**5432/5433/5438/8000。
    - 停 PG **只**用「Stop-Service 本服务」或「pg_ctl -D <本簇datadir> stop」；
      **绝不** taskkill /T 任何 pg_ctl/postgres（树杀会连根端掉 prod postmaster——
      见记忆 feedback_taskkill_tree_can_hit_prod_pg / 2026-06-27 近失）。
    - <Root> 已存在时拒绝 install（除非 -Force）——避免覆盖一套真安装。

  ★2-D 真机实测（2026-06-28）：
    - `sc config <svc> obj= "NT SERVICE\<svc>"` 可切到专属虚拟服务账户；**不要**传
      `password= ""`——PS 5.1 会吞尾随空字符串，导致 sc.exe 返回 1639 且保持 LocalSystem。
      本脚本用 Invoke-ScChecked 强制检查返回码，避免静默降级。
    - 冻结后端是 console=False（窗口化，2-B），Shawl 停服务发 Ctrl-C **收不到** →
      stop-timeout 后强杀、跳过 uvicorn 优雅 lifespan shutdown。ADR Confirmation 记录为
      「可容忍 fallback」：后端 lifespan shutdown 不写业务状态，PG 进程独立且靠 WAL/断连回滚保完整性。

  PS 5.1：无 && / ||；本文件 UTF-8 with BOM（check_text_encoding.ps1 要求）。
#>
[CmdletBinding()]
param(
    [switch]$Teardown,
    [switch]$Force,
    [int]$PgPort = 5440,
    [int]$BackendPort = 8001,
    [string]$Root = "C:\ProgramData\Ticketbox",
    [string]$PgServiceName = "TicketboxPg",
    [string]$BackendServiceName = "TicketboxBackend",
    [string]$DbName = "ticketbox",
    [string]$DbRole = "ticketbox",
    [int]$StopTimeoutMs = 25000,
    [string]$BundlePgDir = "",
    [string]$BackendDistDir = "",
    [string]$ShawlExe = ""
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# $PSScriptRoot 在 `powershell.exe -File` 调用、param() 默认值里取不到（5.1 已知坑），
# 故脚本目录在**主体**用 $MyInvocation 解析（build_pg_bundle.ps1 / install_ticketbox.ps1 同款）。
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($BundlePgDir.Trim().Length -eq 0)    { $BundlePgDir = Join-Path $ScriptDir "vendor\pg" }
if ($BackendDistDir.Trim().Length -eq 0) { $BackendDistDir = Join-Path $ScriptDir "..\dist\ticketbox-backend" }
if ($ShawlExe.Trim().Length -eq 0)       { $ShawlExe = Join-Path $ScriptDir "vendor\shawl\shawl.exe" }

# 落点布局（全部在 <Root> 下，便于 -Teardown 整体删）
$PgHome    = Join-Path $Root "pg"                              # 捆绑 PG 二进制
$PgBin     = Join-Path $PgHome "bin"
$PgData    = Join-Path $Root "pgdata"                          # 独立簇
$ProgDir   = Join-Path $Root "program\ticketbox-backend"      # 冻结后端 onedir
$AppData   = Join-Path $Root "app"                            # = TICKETBOX_DATA_DIR
$LogDir    = Join-Path $AppData "logs"
$EnvPath   = Join-Path $AppData ".env"
$BackendExe = Join-Path $ProgDir "ticketbox-backend.exe"

function Write-Step([string]$m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2([string]$m) { Write-Host "    $m" -ForegroundColor Yellow }

# ── 公共：管理员 + 服务工具 ──────────────────────────────────────────────────
function Assert-Admin {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator)
    if (-not $admin) { throw "需要管理员 PowerShell 运行（注册服务 + 改 ACL）。" }
}
function Service-Exists([string]$name) {
    return $null -ne (Get-Service -Name $name -ErrorAction SilentlyContinue)
}
function Invoke-ScChecked([string[]]$ScArgs) {
    $out = & sc.exe @ScArgs 2>&1
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {
        throw "sc.exe $($ScArgs -join ' ') 失败（exit=$rc）：`n$out"
    }
    return ($out | Out-String).Trim()
}
# 停 PG 只走「本簇 datadir」的 pg_ctl，绝不树杀（红线）。服务存在时优先 Stop-Service。
function Stop-OurPg {
    if (Service-Exists $PgServiceName) {
        try { Stop-Service -Name $PgServiceName -Force -ErrorAction Stop } catch { Write-Warn2 "Stop-Service ${PgServiceName}: $($_.Exception.Message)" }
    }
    if (Test-Path -LiteralPath (Join-Path $PgData "postmaster.pid")) {
        $pgctl = Join-Path $PgBin "pg_ctl.exe"
        if (Test-Path -LiteralPath $pgctl) {
            $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            & $pgctl -D $PgData -m fast -w -t 30 stop 2>$null | Out-Null
            $ErrorActionPreference = $prev
        }
    }
}

# ── -Teardown：只删本脚本建的两服务 + <Root> ─────────────────────────────────
if ($Teardown) {
    Assert-Admin
    Write-Host "=== [Teardown] 卸载 ADR-0047 2-D 开发服务 + 簇 ===" -ForegroundColor Yellow
    # 1) 后端服务
    if (Service-Exists $BackendServiceName) {
        Write-Step "停 + 删后端服务 $BackendServiceName"
        try { Stop-Service -Name $BackendServiceName -Force -ErrorAction SilentlyContinue } catch {}
        & sc.exe delete $BackendServiceName | Out-Null
        Write-Ok "已删 $BackendServiceName。"
    }
    # 2) PG 服务（先优雅停簇，再注销服务；绝不树杀）
    if (Service-Exists $PgServiceName) {
        Write-Step "停 + 删 PG 服务 $PgServiceName（按本簇 datadir 停，绝不树杀）"
        Stop-OurPg
        $pgctl = Join-Path $PgBin "pg_ctl.exe"
        if (Test-Path -LiteralPath $pgctl) {
            $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            & $pgctl unregister -N $PgServiceName 2>$null | Out-Null
            $ErrorActionPreference = $prev
        }
        if (Service-Exists $PgServiceName) { & sc.exe delete $PgServiceName | Out-Null }
        Write-Ok "已删 $PgServiceName。"
    }
    else {
        Stop-OurPg   # 服务没了但簇可能还在跑
    }
    # 3) 删 <Root>
    if (Test-Path -LiteralPath $Root) {
        Write-Step "删数据根 $Root"
        Start-Sleep -Milliseconds 800   # 等服务进程退干净，避免文件占用
        Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $Root) { Write-Warn2 "部分文件未删（可能仍被占用）：$Root。手动复查。" }
        else { Write-Ok "已删 $Root。" }
    }
    Write-Host ""
    Write-Host "=== [Teardown] 完成。prod PG(5432)/test PG(5438) 未受影响。 ===" -ForegroundColor Green
    return
}

# ════════════════════════════════════════════════════════════════════════════
#  install（默认）
# ════════════════════════════════════════════════════════════════════════════
Write-Host "=== ADR-0047 Slice 2-D 开发服务注册（PG + 后端，落 $Root）===" -ForegroundColor Cyan
Assert-Admin

# ── 0) 端口/落点安全闸（PROD 红线）──────────────────────────────────────────
Write-Step "安全检查：端口 + 落点"
$forbiddenPg = @(5432, 5433, 5438)
if ($forbiddenPg -contains $PgPort) { throw "拒绝 PG 端口 ${PgPort}：5432=prod / 5433=CI / 5438=test。开发隔离请用 5440 等专用端口。" }
if ($BackendPort -eq 8000) { throw "拒绝后端端口 8000（本机 prod 后端占用）。开发隔离请用 8001 等。" }
function Assert-PortFree([int]$port, [string]$what) {
    $busy = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($null -ne $busy) { throw "端口 $port（$what）已被占用（PID $($busy[0].OwningProcess)）。换端口或先收拾占用进程。" }
}
Assert-PortFree $PgPort "PG"
Assert-PortFree $BackendPort "backend"
if ((Test-Path -LiteralPath $Root) -and -not $Force) {
    throw "$Root 已存在。这是开发验收脚本，拒绝覆盖既有安装。先 -Teardown，或加 -Force 重建。"
}
foreach ($s in @($PgServiceName, $BackendServiceName)) {
    if ((Service-Exists $s) -and (-not $Force)) { throw "服务 $s 已存在。先 -Teardown，或加 -Force。" }
}
Write-Ok "端口安全（PG=$PgPort / 后端=$BackendPort，均非 prod/test）。落点 $Root 可用。"

# ── 1) 源校验 ────────────────────────────────────────────────────────────────
Write-Step "校验源：捆绑 PG / 冻结后端 / Shawl"
if (-not (Test-Path -LiteralPath (Join-Path $BundlePgDir "bin\pg_ctl.exe"))) {
    throw "未找到捆绑 PG（$BundlePgDir\bin\pg_ctl.exe）。先跑：build_pg_bundle.ps1 -Zip <17.10-1 zip> -Verify。"
}
if (-not (Test-Path -LiteralPath (Join-Path $BackendDistDir "ticketbox-backend.exe"))) {
    throw "未找到冻结后端 onedir（$BackendDistDir\ticketbox-backend.exe）。先在 backend\ 跑 .venv-build\Scripts\pyinstaller.exe --noconfirm --clean packaging\ticketbox-backend.spec。"
}
if (-not (Test-Path -LiteralPath $ShawlExe)) { throw "未找到 shawl.exe（$ShawlExe）。见 DEPENDENCIES.md「Shawl」节。" }
$BundlePgDir    = (Resolve-Path -LiteralPath $BundlePgDir).Path
$BackendDistDir = (Resolve-Path -LiteralPath $BackendDistDir).Path
$ShawlExe       = (Resolve-Path -LiteralPath $ShawlExe).Path
Write-Ok "源齐备。"

# 若 -Force 覆盖：先 teardown 既有服务/簇，再重建（复用上面的卸载逻辑过于绕，这里精简内联）
if ($Force) {
    if (Service-Exists $BackendServiceName) { try { Stop-Service $BackendServiceName -Force -ErrorAction SilentlyContinue } catch {}; & sc.exe delete $BackendServiceName | Out-Null }
    if (Service-Exists $PgServiceName) { Stop-OurPg; & sc.exe delete $PgServiceName | Out-Null }
    if (Test-Path -LiteralPath $Root) { Start-Sleep -Milliseconds 800; Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue }
}

# ── 2) 复制二进制 ────────────────────────────────────────────────────────────
Write-Step "复制 PG 二进制 → $PgHome，后端 → $ProgDir"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
Copy-Item -LiteralPath $BundlePgDir -Destination $PgHome -Recurse -Force
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProgDir) | Out-Null
Copy-Item -LiteralPath $BackendDistDir -Destination $ProgDir -Recurse -Force
New-Item -ItemType Directory -Force -Path $AppData | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $AppData "uploads") | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Write-Ok "二进制就位。"

# ── 3) initdb 独立簇 ─────────────────────────────────────────────────────────
Write-Step "initdb 独立簇 @ $PgData（端口 $PgPort，loopback-only，trust 本地）"
$pwfile = Join-Path ([System.IO.Path]::GetTempPath()) ("xpj_2d_pw_" + [System.Guid]::NewGuid().ToString("N") + ".txt")
$superPw = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 28 | ForEach-Object { [char]$_ })
$superPw | Out-File -LiteralPath $pwfile -Encoding ascii -NoNewline
try {
    # Windows 无 Unix socket：所有连接(含 loopback)都走 host。簇只听 127.0.0.1 + ACL 锁死,
    # 故 host=trust(应用角色免密、DATABASE_URL 免口令);与 2-C 冒烟一致。真部署(Slice4 Inno)
    # 才上 scram + per-install 口令。
    & (Join-Path $PgBin "initdb.exe") -D $PgData -U postgres --auth-local=trust --auth-host=trust `
        --encoding=UTF8 --no-locale --pwfile=$pwfile | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "initdb 失败（exit=$LASTEXITCODE）。" }
}
finally { Remove-Item -LiteralPath $pwfile -Force -ErrorAction SilentlyContinue }
# 把端口/监听写进 postgresql.conf（服务态最可靠，晚于默认行覆盖）。
Add-Content -LiteralPath (Join-Path $PgData "postgresql.conf") -Encoding ascii -Value @(
    "",
    "# ADR-0047 2-D dev cluster overrides",
    "listen_addresses = '127.0.0.1'",
    "port = $PgPort"
)
Write-Ok "簇已建。"

# ── 4) 注册 PG 服务 + 虚拟账户 + ACL ─────────────────────────────────────────
Write-Step "注册 PG 服务 $PgServiceName + 专属虚拟账户 + ACL"
& (Join-Path $PgBin "pg_ctl.exe") register -N $PgServiceName -D $PgData -S auto | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pg_ctl register 失败（exit=$LASTEXITCODE）。" }
# 切到专属虚拟服务账户（无密码、自动管理、最小权限）。[真机待证：虚拟账户能否这样切]
# PS 5.1 原生命令会吞掉尾随空字符串；虚拟服务账户无需 password=，且必须检查 sc.exe 返回码。
Invoke-ScChecked @("config", $PgServiceName, "obj=", "NT SERVICE\$PgServiceName") | Out-Null
Invoke-ScChecked @("config", $PgServiceName, "start=", "delayed-auto") | Out-Null
Invoke-ScChecked @("failure", $PgServiceName, "reset=", "3600", "actions=", "restart/5000/restart/10000/restart/60000") | Out-Null
# ACL：簇 + 二进制目录断继承，只授 SYSTEM/Administrators/该服务账户。
& icacls $PgData /inheritance:r | Out-Null
& icacls $PgData /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${PgServiceName}:(OI)(CI)F" | Out-Null
& icacls $PgHome /inheritance:r | Out-Null
& icacls $PgHome /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${PgServiceName}:(OI)(CI)RX" | Out-Null
Write-Ok "PG 服务注册完。"

Write-Step "起 PG 服务并等就绪"
Start-Service -Name $PgServiceName
$ready = $false
for ($r = 0; $r -lt 60; $r++) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & (Join-Path $PgBin "pg_isready.exe") -h 127.0.0.1 -p $PgPort -q | Out-Null
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($rc -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "PG 服务起后未在超时内接受连接（端口 $PgPort）。看 $PgData\log\ 排查。" }
Write-Ok "PG 已就绪 @ 127.0.0.1:$PgPort。"

# ── 5) 建空角色 + 空库（OWNER=应用角色），表交后端首启建（堵 owner 陷阱）─────
Write-Step "建应用角色「$DbRole」+ 数据库「$DbName」（OWNER=$DbRole）"
$psql = Join-Path $PgBin "psql.exe"
function Invoke-Psql([string]$db, [string]$sql) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $out = & $psql -v ON_ERROR_STOP=1 -U postgres -h 127.0.0.1 -p $PgPort -d $db -tAc $sql 2>&1
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($rc -ne 0) { throw "psql 失败（db=$db）：$sql`n$out" }
    return ($out | Out-String).Trim()
}
$roleExists = (Invoke-Psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname='$DbRole'") -eq "1"
if (-not $roleExists) {
    # trust 本地鉴权下应用角色可无密码；建带 LOGIN 即可。
    Invoke-Psql "postgres" "CREATE ROLE `"$DbRole`" LOGIN" | Out-Null
    Write-Ok "已建角色 $DbRole。"
} else { Write-Ok "角色 $DbRole 已存在。" }
$dbExists = (Invoke-Psql "postgres" "SELECT 1 FROM pg_database WHERE datname='$DbName'") -eq "1"
if (-not $dbExists) {
    Invoke-Psql "postgres" "CREATE DATABASE `"$DbName`" OWNER `"$DbRole`" ENCODING 'UTF8'" | Out-Null
    Write-Ok "已建库 $DbName（属主 $DbRole）。"
} else { Write-Ok "库 $DbName 已存在。" }

# ── 6) 写 .env（无 BOM）──────────────────────────────────────────────────────
Write-Step "写 $EnvPath（无 BOM）"
# trust 本地鉴权：DATABASE_URL 可省口令。后端是 PostgreSQL-only，连本簇。
$databaseUrl = "postgresql+psycopg://$DbRole@127.0.0.1:$PgPort/$DbName"
$envLines = @(
    "DATABASE_URL=$databaseUrl",
    "TICKETBOX_HOST=127.0.0.1",
    "TICKETBOX_PORT=$BackendPort",
    "TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS=25",
    "OCR_PROVIDER=empty",
    "OCR_AUTO_RUN=false",
    "ENABLE_API_DOCS=false",
    "ALLOW_PUBLIC_ADMIN_API=false",
    "CLOUDFLARE_ACCESS_REQUIRED=false"
)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($EnvPath, $envLines, $utf8NoBom)
Write-Ok ".env 写好（DATABASE_URL 指向应用角色 $DbRole @ $PgPort）。"

# ── 7) Shawl 注册后端服务 + 虚拟账户 + ACL ───────────────────────────────────
Write-Step "Shawl 注册后端服务 $BackendServiceName（--env / --dependencies / --stop-timeout / --restart）"
# --env TICKETBOX_DATA_DIR：launcher 据此把数据落 <Root>\app 并加载其中 .env（override=True）。
# --dependencies：替代 sc config depend=（Shawl 自带，§9 已核实）。
# --stop-timeout：发 Ctrl-C 到强杀的等待窗口，配 uvicorn timeout_graceful_shutdown=25s。
# --restart + --restart-delay：子进程退出即重起（服务级崩溃退避另由下面 sc failure 兜）。
& $ShawlExe add --name $BackendServiceName `
    --dependencies $PgServiceName `
    --stop-timeout $StopTimeoutMs `
    --restart --restart-delay 5000 `
    --cwd $AppData `
    --log-dir $LogDir `
    --env "TICKETBOX_DATA_DIR=$AppData" `
    -- $BackendExe | Out-Null
if ($LASTEXITCODE -ne 0) { throw "shawl add 失败（exit=$LASTEXITCODE）。" }
Invoke-ScChecked @("config", $BackendServiceName, "obj=", "NT SERVICE\$BackendServiceName") | Out-Null
Invoke-ScChecked @("config", $BackendServiceName, "start=", "delayed-auto") | Out-Null
Invoke-ScChecked @("failure", $BackendServiceName, "reset=", "3600", "actions=", "restart/5000/restart/10000/restart/60000") | Out-Null
# ACL：程序目录只读执行、数据目录全控；均断继承移除 Users。
& icacls $ProgDir /inheritance:r | Out-Null
& icacls $ProgDir /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${BackendServiceName}:(OI)(CI)RX" | Out-Null
& icacls $AppData /inheritance:r | Out-Null
& icacls $AppData /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "NT SERVICE\${BackendServiceName}:(OI)(CI)F" | Out-Null
Write-Ok "后端服务注册完。"

Write-Step "起后端服务并等 /api/health"
Start-Service -Name $BackendServiceName
$baseUrl = "http://127.0.0.1:$BackendPort"
$healthy = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "$baseUrl/api/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $healthy) { throw "后端服务起后 90s 内 $baseUrl/api/health 未就绪。看 $LogDir\backend.log 排查。" }
Write-Ok "后端已就绪：$baseUrl"

# ── 8) ADR Confirmation 逐条验收 ─────────────────────────────────────────────
Write-Host ""
Write-Host "=== ADR-0047 Confirmation 验收 ===" -ForegroundColor Cyan
$pass = $true

# (a) owner-trap：非 ticketbox 属主的表应为 0。
$mismatch = Invoke-Psql $DbName "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner <> '$DbRole'"
if ([int]$mismatch -eq 0) { Write-Ok "[PASS] owner-trap：全部表属主 = $DbRole。" }
else { $pass = $false; Write-Warn2 "[FAIL] owner-trap：$mismatch 张表属主不是 $DbRole（跑 fix_table_owners.sql 归位）。" }

# (b) ACL：数据/簇目录 Users 无读权。
$aclApp = (& icacls $AppData | Out-String)
$aclPg  = (& icacls $PgData | Out-String)
if (($aclApp -notmatch "Users") -and ($aclPg -notmatch "Users")) { Write-Ok "[PASS] ACL：数据/簇目录无 Users 读权。" }
else { $pass = $false; Write-Warn2 "[FAIL] ACL：仍含 Users ACE（检查 icacls 输出）。" }

# (c) 优雅关停：停后端服务，看 backend.log 是否出现 uvicorn 干净 lifespan shutdown。
Write-Step "[验收] 优雅关停：停后端服务，检查 backend.log"
Stop-Service -Name $BackendServiceName -Force
Start-Sleep -Seconds 2
$logPath = Join-Path $LogDir "backend.log"
$graceful = $false
if (Test-Path -LiteralPath $logPath) {
    $tail = Get-Content -LiteralPath $logPath -Encoding UTF8 -Tail 40 | Out-String
    if ($tail -match "Application shutdown complete|Finished server process|Waiting for application shutdown") { $graceful = $true }
}
if ($graceful) { Write-Ok "[PASS] 优雅关停：backend.log 见 uvicorn lifespan shutdown。" }
else {
    Write-Warn2 "[WARN] 未在 backend.log 见优雅关停标记 —— console=False 子进程可能收不到 Ctrl-C（§9 ★风险）。"
    Write-Warn2 "       这是 ADR Confirmation 允许的「可容忍 fallback」(需显式记录)，或改后端独立停机路径。"
    Write-Warn2 "       Shawl 日志见：$LogDir\shawl_for_${BackendServiceName}_rCURRENT.log（看是否 Ctrl-C 后 stop-timeout 强杀）。"
}
Start-Service -Name $BackendServiceName   # 恢复

# (d) connect-retry（可选手动）：停 PG → 重起后端 → 后端应等待而非 4 秒猝死 → 起 PG → 自愈。
Write-Warn2 "[手动] connect-retry：Stop-Service $PgServiceName; Restart-Service $BackendServiceName; (看 backend.log 是否重试等待) ; Start-Service $PgServiceName。"

Write-Host ""
Write-Host "================ 2-D 开发服务就绪 ================" -ForegroundColor Green
Write-Host "PG 服务   : $PgServiceName  @ 127.0.0.1:$PgPort（簇 $PgData）"
Write-Host "后端服务  : $BackendServiceName @ $baseUrl（依赖 $PgServiceName）"
Write-Host "数据目录  : $AppData（.env / uploads / logs / backups）"
Write-Host "日志      : $logPath（窗口化无控制台，排查看这里）"
Write-Host "卸载      : powershell -File dev_register_services.ps1 -Teardown"
if ($pass) { Write-Host "验收      : 自动项 PASS（优雅关停见上 WARN/PASS）" -ForegroundColor Green }
else { Write-Host "验收      : 有 FAIL 项,见上。" -ForegroundColor Yellow }
Write-Host "==================================================" -ForegroundColor Green
