param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$AdminToken = "",
    [int]$BackupRetentionDays = 30,
    [switch]$Backup,
    [switch]$PruneBackups,
    [switch]$SkipBackupPrune,
    [switch]$CleanupConfirmedImages,
    [switch]$CleanupRejectedImages,
    [switch]$CleanupOrphans,
    [switch]$DeleteOrphans,
    [switch]$Vacuum
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$DbPath = Join-Path $BackendRoot "data\ticketbox.db"
$BackupDir = Join-Path $BackendRoot "backups"
$BaseUrl = $ServerUrl.TrimEnd("/")

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Invoke-MaintenancePost {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Query = ""
    )

    if ([string]::IsNullOrWhiteSpace($AdminToken)) {
        throw "没有 admin session token。请传入 -AdminToken，或设置 TICKETBOX_ADMIN_TOKEN。"
    }

    $uri = "$BaseUrl$Path$Query"
    Invoke-RestMethod -Method Post -Uri $uri -Headers @{ Authorization = "Bearer $AdminToken" } -TimeoutSec 60
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
    throw "未找到 Python，无法使用 SQLite Online Backup API。"
}

function Assert-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $separators = [char[]]@(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $rootPrefix = $resolvedRoot.TrimEnd($separators) + [System.IO.Path]::DirectorySeparatorChar
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝访问备份目录外路径：$fullPath"
    }
    return $fullPath
}

function Backup-SqliteDatabase {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $python = Resolve-Python
    $tempPath = "$TargetPath.tmp-$PID"
    $script = @'
import sqlite3
import sys

source, target = sys.argv[1], sys.argv[2]
src = sqlite3.connect(source)
try:
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        result = dst.execute('PRAGMA integrity_check').fetchone()[0]
        if result != 'ok':
            raise SystemExit('SQLite backup integrity_check failed: ' + str(result))
    finally:
        dst.close()
finally:
    src.close()
'@
    try {
        & $python -c $script $SourcePath $tempPath
        if ($LASTEXITCODE -ne 0) {
            throw "SQLite 备份失败。"
        }
        Move-Item -LiteralPath $tempPath -Destination $TargetPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }
}

function Backup-Database {
    if (-not (Test-Path -LiteralPath $DbPath)) {
        Write-Host "数据库不存在，跳过备份：$DbPath"
        return
    }

    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $target = Join-Path $BackupDir "ticketbox-$stamp.db"
    $target = Assert-PathInside -Path $target -Root $BackupDir
    Backup-SqliteDatabase -SourcePath $DbPath -TargetPath $target
    $size = (Get-Item -LiteralPath $target).Length
    Write-Host "数据库备份完成：$target ($(Format-Bytes $size))"
}

function Prune-OldBackups {
    if ($BackupRetentionDays -le 0) {
        Write-Host "备份保留清理已禁用：BackupRetentionDays=$BackupRetentionDays"
        return
    }
    if (-not (Test-Path -LiteralPath $BackupDir)) {
        Write-Host "备份目录不存在，跳过清理：$BackupDir"
        return
    }

    $cutoff = (Get-Date).AddDays(-$BackupRetentionDays)
    $backupRoot = (Resolve-Path -LiteralPath $BackupDir).Path
    $oldFiles = @(Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*.db" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff })
    if ($oldFiles.Count -eq 0) {
        Write-Host "备份保留清理完成：没有超过 $BackupRetentionDays 天的备份。"
        return
    }

    $deletedBytes = 0L
    foreach ($file in $oldFiles) {
        $candidate = Assert-PathInside -Path $file.FullName -Root $backupRoot
        $deletedBytes += $file.Length
        Remove-Item -LiteralPath $candidate -Force
    }
    Write-Host "备份保留清理完成：删除 $($oldFiles.Count) 个旧备份，释放 $(Format-Bytes $deletedBytes)。"
}

function Vacuum-Database {
    if (-not (Test-Path -LiteralPath $DbPath)) {
        Write-Host "数据库不存在，跳过 VACUUM：$DbPath"
        return
    }

    $python = Resolve-Python
    & $python -c "import sqlite3, sys; conn = sqlite3.connect(sys.argv[1]); conn.execute('VACUUM'); conn.close()" $DbPath
    Write-Host "SQLite VACUUM 完成。"
}

if ([string]::IsNullOrWhiteSpace($AdminToken)) {
    $AdminToken = [Environment]::GetEnvironmentVariable("TICKETBOX_ADMIN_TOKEN")
}

$hasAction = $Backup -or $PruneBackups -or $CleanupConfirmedImages -or $CleanupRejectedImages -or $CleanupOrphans -or $Vacuum
if (-not $hasAction) {
    Write-Host "小票夹维护脚本"
    Write-Host "常用："
    Write-Host "  -Backup"
    Write-Host "  -PruneBackups [-BackupRetentionDays 30]"
    Write-Host "  -CleanupConfirmedImages"
    Write-Host "  -CleanupRejectedImages"
    Write-Host "  -CleanupOrphans [-DeleteOrphans]"
    Write-Host "  -Vacuum"
    Write-Host ""
    Write-Host "建议顺序：先 -Backup，再 dry-run 清理，确认后再 -DeleteOrphans。"
    return
}

if ($Backup) {
    Backup-Database
    if (-not $SkipBackupPrune) {
        Prune-OldBackups
    }
}

if ($PruneBackups) {
    Prune-OldBackups
}

if ($CleanupConfirmedImages) {
    $result = Invoke-MaintenancePost -Path "/api/maintenance/cleanup-images"
    Write-Host "confirmed 图片清理：扫描 $($result.scanned)，原图 $($result.deleted_images)，缩略图 $($result.deleted_thumbnails)。"
}

if ($CleanupRejectedImages) {
    $result = Invoke-MaintenancePost -Path "/api/maintenance/cleanup-rejected"
    Write-Host "rejected 图片清理：扫描 $($result.scanned)，原图 $($result.deleted_images)，缩略图 $($result.deleted_thumbnails)。"
}

if ($CleanupOrphans) {
    $dryRun = if ($DeleteOrphans) { "false" } else { "true" }
    $result = Invoke-MaintenancePost -Path "/api/maintenance/cleanup-orphans" -Query "?dry_run=$dryRun"
    $mode = if ($result.dry_run) { "dry-run" } else { "delete" }
    Write-Host "孤儿文件清理($mode)：扫描 $($result.scanned_files)，孤儿 $($result.orphan_files)，删除 $($result.deleted_files)，可清理 $(Format-Bytes $result.orphan_bytes)。"
}

if ($Vacuum) {
    Vacuum-Database
}
