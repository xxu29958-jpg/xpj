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

# 共享 SQLite 备份/校验函数(Resolve-Python / Get-BackendVersion / Test-SqliteBackup /
# Backup-SqliteDatabase),与 backend\scripts\backup_database.ps1 共用同一份实现。dot-source
# 后这些函数沿用本脚本作用域的 $BackendRoot(此处已就绪)。
. (Join-Path $BackendRoot "scripts\lib\sqlite_backup.ps1")

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

function Resolve-DbPath {
    param([Parameter(Mandatory = $true)][string]$BackendRoot)

    $databaseUrl = Get-BackendEnvValue -Name "DATABASE_URL"
    if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
        $databaseUrl = "sqlite:///data/ticketbox.db"
    }
    if ($databaseUrl -notmatch '^sqlite:///(.+)$') {
        throw "DATABASE_URL 不是 sqlite，维护脚本只能处理 SQLite 文件：$databaseUrl"
    }

    $candidate = $Matches[1]
    if ($candidate -eq ":memory:") {
        throw "DATABASE_URL 指向内存数据库，无法执行文件维护。"
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $BackendRoot $candidate
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

# Dialect detection. On PostgreSQL there is no SQLite file path, so resolving it
# eagerly (it throws on a non-sqlite URL) would kill every op at load — including
# the scheduled backup. Resolve lazily: $DbPath stays $null on PostgreSQL.
$DatabaseUrl = Get-BackendEnvValue -Name "DATABASE_URL"
if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    $DatabaseUrl = "sqlite:///data/ticketbox.db"
}
$IsPostgres = $DatabaseUrl -match '^postgresql'
$BackupSuffix = if ($IsPostgres) { ".dump" } else { ".db" }
$DbPath = if ($IsPostgres) { $null } else { Resolve-DbPath -BackendRoot $BackendRoot }

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
    if ($IsPostgres) {
        # PostgreSQL backup (pg_dump -Fc + validation) is dialect-dispatched in
        # backend\scripts\backup_database.ps1. Delegate to that single source so
        # the pg logic lives in one place; -Keep 0 leaves retention to
        # Prune-OldBackups below. (The two scripts still duplicate the SQLite
        # path — deduping them is tracked as backlog.)
        $backupScript = Join-Path $BackendRoot "scripts\backup_database.ps1"
        & $backupScript -Keep 0
        return
    }

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
    $oldFiles = @(Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*$BackupSuffix" -File -ErrorAction SilentlyContinue |
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
    if ($IsPostgres) {
        Write-Host "PostgreSQL 由 autovacuum 维护，跳过手动 VACUUM。"
        return
    }
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
