param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [int]$Port = 8000,
    [switch]$ForceWhileRunning
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$RestoreScript = Join-Path $ProjectRoot "scripts\restore_ticketbox_db.ps1"

if (-not (Test-Path -LiteralPath $RestoreScript)) {
    throw "未找到统一恢复脚本：$RestoreScript"
}

$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $RestoreScript,
    "-BackupPath",
    $BackupFile,
    "-Port",
    $Port
)
if ($ForceWhileRunning) {
    $arguments += "-ForceWhileRunning"
}

& powershell @arguments
if ($LASTEXITCODE -ne 0) {
    throw "数据库恢复失败。"
}
