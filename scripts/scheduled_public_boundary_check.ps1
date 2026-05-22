#requires -Version 5.1
<#
.SYNOPSIS
    Task Scheduler wrapper around check_public_boundary.ps1.

.DESCRIPTION
    Runs the public-boundary probe against the configured public origin,
    appends a stamped run record to logs\public-boundary-<YYYY-MM-DD>.log,
    prunes logs older than -LogRetentionDays days, and exits with the same
    status code as the probe (0 PASS / 1 FAIL).

    BaseUrl resolution order:
      1. -BaseUrl parameter
      2. $env:PUBLIC_BASE_URL
      3. PUBLIC_BASE_URL line in backend\.env

    Designed to be invoked by the `TicketboxBoundaryCheck` Daily Trigger
    installed by install_windows_tasks.ps1. Logs are intentionally kept
    out of backend\logs so backend log rotation does not delete them, and
    out of git so the public domain never ends up in the repository.
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = "",
    [int]$LogRetentionDays = 14
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$ProbeScript = Join-Path $ProjectRoot "scripts\check_public_boundary.ps1"
$LogDir = Join-Path $ProjectRoot "logs"

function Get-BackendEnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value.Trim().Trim('"').Trim("'")
    }
    $envFile = Join-Path $BackendRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return $null
    }
    $escapedName = [Regex]::Escape($Name)
    $line = Get-Content -LiteralPath $envFile -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$escapedName\s*=" } |
        Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return ($line -replace "^\s*$escapedName\s*=", "").Trim().Trim('"').Trim("'")
}

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = Get-BackendEnvValue -Name "PUBLIC_BASE_URL"
}
if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    Write-Error "未能解析 PUBLIC_BASE_URL。请在 backend\.env 设置或用 -BaseUrl 传入。"
    exit 2
}
if (-not (Test-Path -LiteralPath $ProbeScript)) {
    Write-Error "未找到探测脚本：$ProbeScript"
    exit 2
}

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$logFile = Join-Path $LogDir "public-boundary-$stamp.log"
$header = "=== {0} probe BaseUrl={1} ===" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"), $BaseUrl

# Run probe, capture stdout + stderr together so failures get logged.
$probeOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProbeScript -BaseUrl $BaseUrl 2>&1
$probeExit = $LASTEXITCODE

# Append run record. Out-File default UTF-16; force UTF-8 so the file is
# greppable from bash without iconv.
$header | Out-File -FilePath $logFile -Append -Encoding utf8
$probeOutput | Out-File -FilePath $logFile -Append -Encoding utf8
("=== exit={0} ===" -f $probeExit) | Out-File -FilePath $logFile -Append -Encoding utf8
"" | Out-File -FilePath $logFile -Append -Encoding utf8

# Prune old logs.
$cutoff = (Get-Date).AddDays(-1 * $LogRetentionDays)
Get-ChildItem -LiteralPath $LogDir -Filter "public-boundary-*.log" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Surface probe output to whoever invoked the wrapper interactively.
$probeOutput | ForEach-Object { Write-Host $_ }

exit $probeExit
