param(
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [int]$Port = 8000,
    [switch]$ForceWhileRunning
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$DbPath = Join-Path $BackendRoot "data\ticketbox.db"
$BackupDir = Join-Path $BackendRoot "backups"

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Resolve-Python {
    $venvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "未找到 Python，无法校验 SQLite 备份。"
}

function Test-SqliteBackup {
    param([Parameter(Mandatory = $true)][string]$Path)

    $python = Resolve-Python
    & $python -c "import sqlite3, sys; con = sqlite3.connect(sys.argv[1]); result = con.execute('PRAGMA integrity_check').fetchone()[0]; con.close(); raise SystemExit(0 if result == 'ok' else 1)" $Path
}

$source = Resolve-Path -LiteralPath $BackupPath
$sourceItem = Get-Item -LiteralPath $source
if (-not $sourceItem.Name.EndsWith(".db", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "备份文件必须是 .db：$source"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener -and -not $ForceWhileRunning) {
    throw "检测到后端仍在监听 127.0.0.1:$Port。请先停止后端，或明确传入 -ForceWhileRunning。"
}

Write-Host "校验备份文件：$source"
Test-SqliteBackup -Path $source
Write-Host "备份校验通过：$(Format-Bytes $sourceItem.Length)"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DbPath) | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

if (Test-Path -LiteralPath $DbPath) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $preRestore = Join-Path $BackupDir "pre-restore-$stamp.db"
    Copy-Item -LiteralPath $DbPath -Destination $preRestore
    Write-Host "已创建恢复前备份：$preRestore"
}

Copy-Item -LiteralPath $source -Destination $DbPath -Force
Test-SqliteBackup -Path $DbPath
Write-Host "数据库恢复完成：$DbPath"
