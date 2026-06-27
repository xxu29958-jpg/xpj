#Requires -Version 5.1
<#
.SYNOPSIS
  ADR-0047 Slice 2-C：从 EDB「binaries without installer」zip 裁出最小 PostgreSQL
  捆绑包（server + initdb + psql + pg_dump/pg_restore），供 Option D 服务化（2-D）
  与 Inno 安装器（Slice 4）打包。

.DESCRIPTION
  EDB 的 postgresql-<ver>-windows-x64-binaries.zip 解包后约 800MB+（pgAdmin 一项就
  ~670MB）。本脚本只抽 `bin` / `lib` / `share` 三个运行时必需目录 + license 文本，
  并在 `bin` 内把客户端便利工具裁掉、只留单机内嵌部署真正用得到的 EXE（所有 *.dll
  全留——是 postgres.exe 的运行时依赖）。产物落 `vendor\pg\`（已被 .gitignore 忽略，
  可由本脚本重建，绝不进 git）。

  裁剪依据 ADR-0047 §6：「裁掉 docs/pgAdmin/symbols/stackbuilder，把 ~330MB 的
  binaries-without-installer zip 削到最小 server + initdb + psql 集」。

  PG major 钉死 17（ADR §6）；minor/patch 随新 zip 换。pin 见下面 $Pinned*。

.PARAMETER Zip
  已下载的 binaries zip 路径。缺省时在脚本目录、vendor\ 下找 $PinnedZipName；都没有
  且带 -Download 时才联网拉取（~330MB）。

.PARAMETER OutDir
  捆绑包输出目录。默认 <packaging>\vendor\pg。

.PARAMETER Download
  zip 不存在时允许联网下载（默认不下，避免误触发 330MB 下载）。

.PARAMETER Verify
  裁完后跑一次**独立**冒烟：用裁出的 initdb 建一次性簇、起 postgres、psql 查
  `SELECT version()`、停服、清簇。证明裁剪后的二进制自洽（不依赖系统 PG）。
  绝不碰端口 5432(prod)/5433(CI)/5438(test)。

.PARAMETER VerifyPort
  冒烟用的临时端口。默认 5439。拒绝 5432/5433/5438。

.PARAMETER Force
  OutDir 已存在时先清空重建。

.NOTES
  §9 依赖治理：PostgreSQL License（permissive BSD/MIT 式，准予 bundle，保留
  server_license.txt）。详见 docs/rules/DEPENDENCIES.md「捆绑原生二进制」节。
  PS 5.1：无 && / ||；本文件 UTF-8 with BOM（check_text_encoding.ps1 要求）。
#>
[CmdletBinding()]
param(
    [string]$Zip = "",
    [string]$OutDir = "",
    [switch]$Download,
    [switch]$Verify,
    [int]$VerifyPort = 5439,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
# $PSScriptRoot 在 `powershell.exe -File` 调用下、param() 默认值里取不到（5.1 已知坑），
# 故脚本目录在**主体**用 $MyInvocation 解析（install_ticketbox.ps1 同款）。
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($OutDir.Trim().Length -eq 0) { $OutDir = Join-Path $ScriptDir "vendor\pg" }

# ── pin（ADR §6：major=17 钉死；换 minor 时同步改这三行 + DEPENDENCIES.md）──────
$PinnedVersion   = "17.10-1"
$PinnedZipName   = "postgresql-17.10-1-windows-x64-binaries.zip"
$PinnedZipSha256 = "f9aafca58e7026a1ef2caeee711acf761671e57904d430adc85f468374f5a821"
$DownloadUrl     = "https://get.enterprisedb.com/postgresql/$PinnedZipName"

# bin 内保留的 EXE 白名单；所有 *.dll 无条件保留（运行时依赖）。
# 单机内嵌单库部署用得到的最小集：server + 簇生命周期 + 管理客户端 + 备份/恢复 + 诊断。
$KeepExe = @(
    "postgres.exe",       # 服务器
    "initdb.exe",         # 首启建簇
    "pg_ctl.exe",         # 起停 / register 服务
    "psql.exe",           # 应用角色 bootstrap + fix_table_owners.sql
    "pg_dump.exe",        # 升级前快照 + 计划备份（backup_service）
    "pg_restore.exe",     # 恢复 / 备份校验
    "pg_isready.exe",     # 就绪探针（运维）
    "pg_controldata.exe", # 诊断
    "pg_resetwal.exe"     # 应急恢复
)
# 顶层只保留这些目录 + license 文本；pgAdmin/doc/include/StackBuilder 全裁。
$KeepTopDirs = @("bin", "lib", "share")
$KeepTopFiles = @("server_license.txt", "commandlinetools_3rd_party_licenses.txt")

function Write-Step([string]$m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "    $m" -ForegroundColor Green }

# ── 1) 定位 / 下载 zip ────────────────────────────────────────────────────────
if ($Zip.Trim().Length -eq 0) {
    $candidates = @(
        (Join-Path $ScriptDir $PinnedZipName),
        (Join-Path (Join-Path $ScriptDir "vendor") $PinnedZipName)
    )
    foreach ($c in $candidates) { if (Test-Path -LiteralPath $c) { $Zip = $c; break } }
}
if ($Zip.Trim().Length -eq 0 -or -not (Test-Path -LiteralPath $Zip)) {
    if (-not $Download) {
        throw "未找到 $PinnedZipName。请把它放在 $ScriptDir 或 vendor\ 下、用 -Zip 指定，或加 -Download 联网拉取（~330MB）。来源：$DownloadUrl"
    }
    $vendorDir = Join-Path $ScriptDir "vendor"
    New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
    $Zip = Join-Path $vendorDir $PinnedZipName
    $partFile = "$Zip.part"
    Write-Step "下载 $PinnedZipName（~330MB）…"
    $oldPref = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
    try {
        if (Test-Path -LiteralPath $partFile) { Remove-Item -LiteralPath $partFile -Force }
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $partFile -UseBasicParsing
        # 下完整才落到最终路径——中断的半截 zip 不会留在 $Zip 毒化下次运行（再跑 sha 必失败且无救）。
        Move-Item -LiteralPath $partFile -Destination $Zip -Force
    }
    catch {
        if (Test-Path -LiteralPath $partFile) { Remove-Item -LiteralPath $partFile -Force -ErrorAction SilentlyContinue }
        throw
    }
    finally { $ProgressPreference = $oldPref }
}
$Zip = (Resolve-Path -LiteralPath $Zip).Path

# ── 2) 校验 sha256（pin）─────────────────────────────────────────────────────
Write-Step "校验 zip 完整性：$Zip"
$actual = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $PinnedZipSha256) {
    throw "zip sha256 不匹配！期望 $PinnedZipSha256，实际 $actual。拒绝使用来源不明的二进制（§9）。"
}
Write-Ok "sha256 OK（$PinnedVersion）。"

# ── 3) 选择性解包到 staging（跳过 pgAdmin/doc/include/StackBuilder）────────────
Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("xpj_pgbundle_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Write-Step "裁剪解包到 staging：$staging"
$kept = 0; $kbytes = [long]0
$archive = [System.IO.Compression.ZipFile]::OpenRead($Zip)
try {
    foreach ($entry in $archive.Entries) {
        $full = $entry.FullName            # 形如 "pgsql/bin/postgres.exe"
        if ($full.EndsWith("/")) { continue }   # 目录条目，需要时再建
        if (-not $full.StartsWith("pgsql/")) { continue }
        $rel = $full.Substring("pgsql/".Length)  # "bin/postgres.exe"
        if ($rel.Length -eq 0) { continue }
        $segs = $rel.Split([char]'/')
        $top = $segs[0]
        $keep = $false
        if ($KeepTopDirs -contains $top) {
            if ($top -eq "bin" -and $segs.Length -eq 2 -and $segs[1].ToLower().EndsWith(".exe")) {
                # bin 直属 EXE：只留白名单
                $keep = ($KeepExe -contains $segs[1].ToLower())
            }
            else {
                $keep = $true   # bin 的 dll/其它、lib/**、share/**
            }
        }
        elseif ($segs.Length -eq 1 -and ($KeepTopFiles -contains $top)) {
            $keep = $true       # 顶层 license 文本
        }
        if (-not $keep) { continue }
        $dest = Join-Path $staging ($rel -replace '/', '\')
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $destDir)) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
        $kept++; $kbytes += $entry.Length
    }
}
finally { $archive.Dispose() }
Write-Ok ("保留 {0:N0} 个文件，解包后约 {1:N1} MB。" -f $kept, ($kbytes / 1MB))

# 必备目录存在性自检
foreach ($d in @("bin", "share")) {
    if (-not (Test-Path -LiteralPath (Join-Path $staging $d))) { throw "staging 缺少必备目录 $d（裁剪逻辑错误）。" }
}
foreach ($e in @("bin\postgres.exe", "bin\initdb.exe", "bin\psql.exe", "bin\pg_ctl.exe", "server_license.txt")) {
    if (-not (Test-Path -LiteralPath (Join-Path $staging $e))) { throw "staging 缺少必备项 $e。" }
}

# ── 4) 落 OutDir（原子替换）────────────────────────────────────────────────────
Write-Step "写入捆绑包：$OutDir"
if (Test-Path -LiteralPath $OutDir) {
    if (-not $Force) { throw "$OutDir 已存在。加 -Force 覆盖重建。" }
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}
$parent = Split-Path -Parent $OutDir
if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
Move-Item -LiteralPath $staging -Destination $OutDir

# 产物清单（provenance）
$exeCount = (Get-ChildItem -LiteralPath (Join-Path $OutDir "bin") -Filter *.exe).Count
$dllCount = (Get-ChildItem -LiteralPath (Join-Path $OutDir "bin") -Filter *.dll).Count
$totalMb = [math]::Round(((Get-ChildItem -LiteralPath $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
$manifest = @(
    "Ticketbox 捆绑 PostgreSQL（ADR-0047 Slice 2-C，由 build_pg_bundle.ps1 生成）",
    "pg_version      = $PinnedVersion",
    "source_zip      = $PinnedZipName",
    "source_sha256   = $PinnedZipSha256",
    "source_url      = $DownloadUrl",
    "bin_exe_count   = $exeCount（白名单：$($KeepExe -join ', ')）",
    "bin_dll_count   = $dllCount（全保留）",
    "total_size_mb   = $totalMb",
    "dropped         = pgAdmin, doc, include, StackBuilder, 非白名单客户端 EXE",
    "license         = PostgreSQL License（见 server_license.txt，准予 bundle）"
)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines((Join-Path $OutDir "BUNDLE_MANIFEST.txt"), $manifest, $utf8NoBom)
Write-Ok ("完成：bin {0} EXE + {1} DLL，全包 {2} MB。" -f $exeCount, $dllCount, $totalMb)

# ── 5) 可选独立冒烟（裁出的 initdb/postgres/psql 自洽性）──────────────────────
if ($Verify) {
    if ($VerifyPort -eq 5432 -or $VerifyPort -eq 5433 -or $VerifyPort -eq 5438) {
        throw "拒绝端口 ${VerifyPort}：5432=prod / 5433=CI / 5438=test。换专用端口（默认 5439）。"
    }
    $bin = Join-Path $OutDir "bin"
    $cluster = Join-Path ([System.IO.Path]::GetTempPath()) ("xpj_pgbundle_smoke_" + $VerifyPort)
    $pwfile = Join-Path ([System.IO.Path]::GetTempPath()) ("xpj_pgbundle_pw_" + [System.Guid]::NewGuid().ToString("N") + ".txt")
    $logfile = Join-Path ([System.IO.Path]::GetTempPath()) ("xpj_pgbundle_smoke_" + $VerifyPort + ".log")
    Write-Step "独立冒烟：initdb 一次性簇 @ 127.0.0.1:$VerifyPort（簇=$cluster）"
    if (Test-Path -LiteralPath $cluster) {
        # 上次跑泄漏的同端口簇：尽量清；清不掉（被进程占用）给清晰错误，别让 initdb 报含糊的"非空目录"。
        Remove-Item -LiteralPath $cluster -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $cluster) { throw "残留簇目录无法清除（可能有进程占用）：$cluster。先停掉占用进程再重试。" }
    }
    "smokepw" | Out-File -LiteralPath $pwfile -Encoding ascii -NoNewline
    $errlog = "$logfile.err"
    $server = $null
    try {
        & (Join-Path $bin "initdb.exe") -D $cluster -U postgres --auth=trust --encoding=UTF8 --no-locale --pwfile=$pwfile | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "initdb 失败（exit=$LASTEXITCODE）。" }
        # 直接用 Start-Process 拉起 postgres.exe（**不经 pg_ctl、不经 PowerShell 管道**）：
        # 经 pg_ctl 起 + `| Out-Null` 会挂死——pg_ctl 派生的 postgres 继承管道写端，`| Out-Null`
        # 永等子进程退出。Start-Process 把子进程 stdio 重定向到文件、完全脱离父管道，无此问题。
        $pgArgs = @("-D", $cluster, "-p", "$VerifyPort", "-c", "listen_addresses=127.0.0.1", "-c", "fsync=off")
        $server = Start-Process -FilePath (Join-Path $bin "postgres.exe") -ArgumentList $pgArgs `
            -PassThru -WindowStyle Hidden -RedirectStandardOutput $logfile -RedirectStandardError $errlog
        # pg_isready 轮询到真正接受连接（client 查完即退）。
        $ready = $false
        for ($r = 0; $r -lt 60; $r++) {
            & (Join-Path $bin "pg_isready.exe") -h 127.0.0.1 -p $VerifyPort -q | Out-Null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            if ($server.HasExited) { throw "postgres 启动即退出（exit=$($server.ExitCode)）；日志：$errlog" }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) { throw "PG 未在超时内接受连接（端口 $VerifyPort）；日志：$errlog" }
        try {
            $env:PGPASSWORD = "smokepw"
            $ver = & (Join-Path $bin "psql.exe") -U postgres -h 127.0.0.1 -p $VerifyPort -d postgres -tAc "SELECT version()"
            if ($LASTEXITCODE -ne 0) { throw "psql 查询失败（exit=$LASTEXITCODE）。" }
            Write-Ok ("冒烟 OK：{0}" -f ($ver | Out-String).Trim())
        }
        finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
    finally {
        # PS 5.1 坑：native 命令写 stderr + 重定向会被包成 NativeCommandError，在
        # ErrorActionPreference=Stop 下中止整个 finally（清理半途而废）。这里降级，保证清理跑全。
        $ErrorActionPreference = "Continue"
        # 停服务：pg_ctl -m immediate（按 datadir，实证可靠）；兜底 kill Start-Process 句柄。
        if (Test-Path -LiteralPath (Join-Path $cluster "postmaster.pid")) {
            & (Join-Path $bin "pg_ctl.exe") -D $cluster -m immediate -w -t 20 stop 2>$null | Out-Null
        }
        if ($null -ne $server -and -not $server.HasExited) { try { $server.Kill(); $server.WaitForExit(5000) | Out-Null } catch {} }
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $cluster) { Remove-Item -LiteralPath $cluster -Recurse -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $pwfile) { Remove-Item -LiteralPath $pwfile -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $logfile) { Remove-Item -LiteralPath $logfile -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $errlog) { Remove-Item -LiteralPath $errlog -Force -ErrorAction SilentlyContinue }
    }
}

Write-Host ""
Write-Host "================ 捆绑 PG 就绪 ================" -ForegroundColor Green
Write-Host "输出目录: $OutDir"
Write-Host "清单    : $(Join-Path $OutDir 'BUNDLE_MANIFEST.txt')"
Write-Host "下一步  : 2-D 用 vendor\pg\bin\pg_ctl.exe register / Shawl 包后端，落 ProgramData。" -ForegroundColor DarkGray
Write-Host "=============================================" -ForegroundColor Green
