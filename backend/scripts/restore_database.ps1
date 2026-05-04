param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile
)

$ErrorActionPreference = "Stop"
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DataDir = Join-Path $BackendRoot "data"
$BackupDir = Join-Path $BackendRoot "backups"
$DatabasePath = Join-Path $DataDir "ticketbox.db"

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$resolvedBackupDir = (Resolve-Path $BackupDir).Path
$resolvedBackupRoot = $resolvedBackupDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
$resolvedBackupFile = (Resolve-Path -LiteralPath $BackupFile).Path
if (-not $resolvedBackupFile.StartsWith($resolvedBackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to restore from outside backup directory: $resolvedBackupFile"
}

if ((Split-Path -Leaf $resolvedBackupFile) -notlike "ticketbox-*.db") {
    throw "Backup file must match ticketbox-*.db"
}

if (Test-Path -LiteralPath $DatabasePath) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $safetyBackup = Join-Path $BackupDir "ticketbox-before-restore-$timestamp.db"
    Copy-Item -LiteralPath $DatabasePath -Destination $safetyBackup
    Write-Host "恢复前已备份当前数据库到 $safetyBackup"
}

Copy-Item -LiteralPath $resolvedBackupFile -Destination $DatabasePath -Force
Write-Host "已从 $resolvedBackupFile 恢复到 $DatabasePath"
