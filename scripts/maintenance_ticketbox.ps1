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
# 备份目录跟随数据根（与 app.config.DATA_ROOT 一致;冻结 EXE / override 经 TICKETBOX_DATA_DIR 指定）。
$DataRoot = if ([string]::IsNullOrWhiteSpace($env:TICKETBOX_DATA_DIR)) { $BackendRoot } else { $env:TICKETBOX_DATA_DIR }
$BackupDir = Join-Path $DataRoot "backups"
$BaseUrl = $ServerUrl.TrimEnd("/")

# PostgreSQL-only backend (ADR-0041): backups are pg_dump custom-format archives,
# produced by the dialect single-source backend\scripts\backup_database.ps1.
$BackupSuffix = ".dump"

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

function Backup-Database {
    # PostgreSQL backup (pg_dump -Fc + pg_restore --list validation) lives in the
    # dialect single-source backend\scripts\backup_database.ps1. Delegate to it;
    # -Keep 0 leaves retention to Prune-OldBackups below.
    $backupScript = Join-Path $BackendRoot "scripts\backup_database.ps1"
    & $backupScript -Keep 0
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
    $oldFiles = @(Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*$BackupSuffix" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff })
    if ($oldFiles.Count -eq 0) {
        Write-Host "备份保留清理完成：没有超过 $BackupRetentionDays 天的备份。"
        return
    }

    # 保留清理在备份锁外运行;锁串行化的是 pg_dump 本身,删除则做成幂等
    # (并发轮转/清理可能已删掉同一旧文件,已不在即达到目标状态,不算错 —— BUG-2)。
    $deletedBytes = 0L
    foreach ($file in $oldFiles) {
        $candidate = Assert-PathInside -Path $file.FullName -Root $backupRoot
        $deletedBytes += $file.Length
        Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
    }
    Write-Host "备份保留清理完成：删除 $($oldFiles.Count) 个旧备份，释放 $(Format-Bytes $deletedBytes)。"
}

function Vacuum-Database {
    Write-Host "PostgreSQL 由 autovacuum 维护，跳过手动 VACUUM。"
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
