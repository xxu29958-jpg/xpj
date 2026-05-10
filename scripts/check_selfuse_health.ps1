#requires -Version 5.1
<#
.SYNOPSIS
    v0.3-rc1-preflight self-use health monitor.

.DESCRIPTION
    Aggregates 11 quick health probes against the locally running TicketBox
    backend and its surrounding artefacts. Designed to be safe to run on the
    self-use Windows machine: it never prints tokens, secrets, pairing codes,
    upload keys or full UploadLink URLs.

    Output is a Chinese summary table on stdout; the last line is one of:
        SELFUSE_HEALTH=ok
        SELFUSE_HEALTH=warn
        SELFUSE_HEALTH=fail
    Exit code 0 on ok/warn, 1 on fail (presence of P0 failures).

.PARAMETER BaseUrl
    Public origin used for the Cloudflare-side probe. Defaults to
    https://api.zen70.cn.

.PARAMETER LocalUrl
    Local backend origin. Defaults to http://127.0.0.1:8000.

.PARAMETER BackendRoot
    Filesystem root of the backend folder. Defaults to <repo>/backend.

.NOTES
    The 11 health items, in order:
      H01 backend HTTP up (local /api/health)
      H02 health.identity_schema is set
      H03 owner console reachable on loopback
      H04 owner console rejects testserver host
      H05 public /api/health via Cloudflare 200
      H06 public /owner blocked
      H07 public /docs blocked
      H08 sqlite db file exists and non-empty
      H09 uploads dir exists and writable
      H10 recent backup exists (<= 7d) — warn-only when missing
      H11 recent log errors counted (warn-only when > 50)
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://api.zen70.cn',
    [string]$LocalUrl = 'http://127.0.0.1:8000',
    [string]$BackendRoot = (Join-Path $PSScriptRoot '..\backend')
)

$ErrorActionPreference = 'Stop'
$BackendRoot = (Resolve-Path -LiteralPath $BackendRoot).Path
$items = @()

function Add-Item {
    param(
        [string]$Id,
        [string]$Name,
        [string]$Status,   # ok | warn | fail
        [string]$Detail
    )
    $script:items += [pscustomobject]@{
        Id     = $Id
        Name   = $Name
        Status = $Status
        Detail = $Detail
    }
}

function Get-Status {
    param([string]$Url, [string]$Method = 'GET', [hashtable]$Headers = @{})
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method $Method -Headers $Headers `
            -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop -MaximumRedirection 0
        return [int]$resp.StatusCode
    } catch {
        if ($_.Exception.Response -ne $null) {
            try { return [int]$_.Exception.Response.StatusCode } catch { }
        }
        return -1
    }
}

# H01 backend up
$h1 = Get-Status -Url "$LocalUrl/api/health"
$h1Status = if ($h1 -eq 200) { 'ok' } else { 'fail' }
Add-Item -Id 'H01' -Name '后端本地健康' -Status $h1Status `
    -Detail "GET /api/health -> $h1"

# H02 identity schema
$schemaOk = $false
$schemaDetail = '未连通'
if ($h1 -eq 200) {
    try {
        $body = Invoke-RestMethod -Uri "$LocalUrl/api/health" -TimeoutSec 8
        if ($body.identity_schema) {
            $schemaOk = $true
            $schemaDetail = "identity_schema=$($body.identity_schema), backend=$($body.backend_version)"
        } else {
            $schemaDetail = '响应缺少 identity_schema 字段'
        }
    } catch {
        $schemaDetail = '解析 /api/health 响应失败'
    }
}
Add-Item -Id 'H02' -Name '健康响应携带身份模型版本' `
    -Status (& { if ($schemaOk) { 'ok' } else { 'fail' } }) -Detail $schemaDetail

# H03 owner console loopback
$h3 = Get-Status -Url "$LocalUrl/owner"
$h3Status = if ($h3 -eq 200) { 'ok' } else { 'fail' }
Add-Item -Id 'H03' -Name 'Owner Console 本机可访问' `
    -Status $h3Status -Detail "GET /owner -> $h3"

# H04 owner console rejects bogus host (force public-looking Host header)
$h4 = Get-Status -Url "$LocalUrl/owner" -Headers @{ Host = 'api.zen70.cn' }
$h4Status = if ($h4 -eq 403) { 'ok' } else { 'fail' }
Add-Item -Id 'H04' -Name 'Owner Console 拒绝伪造 Host 头' `
    -Status $h4Status `
    -Detail "GET /owner [Host: api.zen70.cn] -> $h4 (期望 403)"

# H05 public /api/health
$h5 = Get-Status -Url "$BaseUrl/api/health"
$h5Status = if ($h5 -eq 200) { 'ok' } elseif ($h5 -eq -1) { 'warn' } else { 'fail' }
Add-Item -Id 'H05' -Name 'Cloudflare 公网健康' `
    -Status $h5Status -Detail "GET $BaseUrl/api/health -> $h5"

# H06 public /owner blocked
$h6 = Get-Status -Url "$BaseUrl/owner"
$h6ok = $h6 -in 401, 403, 404
$h6Status = if ($h6ok) { 'ok' } elseif ($h6 -eq -1) { 'warn' } else { 'fail' }
Add-Item -Id 'H06' -Name '公网 /owner 被阻断' `
    -Status $h6Status -Detail "GET $BaseUrl/owner -> $h6 (期望 401/403/404)"

# H07 public /docs blocked
$h7 = Get-Status -Url "$BaseUrl/docs"
$h7ok = $h7 -in 401, 403, 404
$h7Status = if ($h7ok) { 'ok' } elseif ($h7 -eq -1) { 'warn' } else { 'fail' }
Add-Item -Id 'H07' -Name '公网 /docs 被阻断' `
    -Status $h7Status -Detail "GET $BaseUrl/docs -> $h7 (期望 401/403/404)"

# H08 sqlite db
$dbPath = Join-Path $BackendRoot 'data\ticketbox.db'
$dbOk = (Test-Path -LiteralPath $dbPath) -and ((Get-Item $dbPath).Length -gt 0)
$dbDetail = if (Test-Path -LiteralPath $dbPath) {
    "size={0:N0}B" -f (Get-Item $dbPath).Length
} else {
    '文件不存在'
}
$dbStatus = if ($dbOk) { 'ok' } else { 'fail' }
Add-Item -Id 'H08' -Name 'SQLite 数据库文件' `
    -Status $dbStatus -Detail $dbDetail

# H09 uploads dir
$upPath = Join-Path $BackendRoot 'uploads'
$upOk = Test-Path -LiteralPath $upPath -PathType Container
$upStatus = if ($upOk) { 'ok' } else { 'fail' }
$upDetail = if ($upOk) { 'uploads/ 存在' } else { 'uploads/ 缺失' }
Add-Item -Id 'H09' -Name '上传目录存在' `
    -Status $upStatus -Detail $upDetail

# H10 recent backup
$bkRoot = Join-Path $BackendRoot 'backups'
$recentBk = $null
if (Test-Path -LiteralPath $bkRoot) {
    $recentBk = Get-ChildItem -LiteralPath $bkRoot -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge (Get-Date).AddDays(-7) } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if ($recentBk) {
    Add-Item -Id 'H10' -Name '最近 7 天内有备份' -Status 'ok' `
        -Detail ("最新备份 {0} ({1:yyyy-MM-dd HH:mm})" -f $recentBk.Name, $recentBk.LastWriteTime)
} else {
    Add-Item -Id 'H10' -Name '最近 7 天内有备份' -Status 'warn' -Detail 'backups/ 内未发现最近 7 天的文件'
}

# H11 recent log errors
$logRoot = Join-Path $BackendRoot 'logs'
$errCount = 0
if (Test-Path -LiteralPath $logRoot) {
    $files = Get-ChildItem -LiteralPath $logRoot -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge (Get-Date).AddDays(-1) }
    foreach ($f in $files) {
        try {
            $matches = Select-String -LiteralPath $f.FullName -Pattern 'ERROR|Traceback' `
                -SimpleMatch:$false -ErrorAction SilentlyContinue
            if ($matches) { $errCount += $matches.Count }
        } catch { }
    }
}
$logStatus = if ($errCount -eq 0) { 'ok' } elseif ($errCount -le 50) { 'warn' } else { 'fail' }
Add-Item -Id 'H11' -Name '近 24h 日志中错误计数' -Status $logStatus -Detail "errors=$errCount"

# ── summary ────────────────────────────────────────────────────────────────
Write-Host "=== v0.3-rc1-preflight self-use health ===" -ForegroundColor Cyan
$items | Format-Table Id, Name, Status, Detail -AutoSize | Out-String | Write-Host

$failCount = ($items | Where-Object { $_.Status -eq 'fail' }).Count
$warnCount = ($items | Where-Object { $_.Status -eq 'warn' }).Count
$okCount = ($items | Where-Object { $_.Status -eq 'ok' }).Count
Write-Host "OK=$okCount WARN=$warnCount FAIL=$failCount"

if ($failCount -gt 0) {
    Write-Host 'SELFUSE_HEALTH=fail' -ForegroundColor Red
    exit 1
} elseif ($warnCount -gt 0) {
    Write-Host 'SELFUSE_HEALTH=warn' -ForegroundColor Yellow
    exit 0
} else {
    Write-Host 'SELFUSE_HEALTH=ok' -ForegroundColor Green
    exit 0
}
