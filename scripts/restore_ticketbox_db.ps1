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
# 备份目录跟随数据根（与 app.config.DATA_ROOT 一致;冻结 EXE / override 经 TICKETBOX_DATA_DIR 指定）。
$DataRoot = if ([string]::IsNullOrWhiteSpace($env:TICKETBOX_DATA_DIR)) { $BackendRoot } else { $env:TICKETBOX_DATA_DIR }
$BackupDir = Join-Path $DataRoot "backups"

# 共享 SQLite 校验/备份函数(Resolve-Python / Get-BackendVersion / Test-SqliteBackup)
# 与 backup_database.ps1 / maintenance_ticketbox.ps1 共用一份(backend/scripts/lib),
# 消除第三处重复拷贝。restore 特有的 Resolve-DbPath / Assert-PathInside /
# Get-BackendEnvValue / 带 FK-check 的恢复前备份保留在本脚本。
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
        throw "DATABASE_URL 不是 sqlite，恢复脚本只能处理 SQLite 文件：$databaseUrl"
    }

    $candidate = $Matches[1]
    if ($candidate -eq ":memory:") {
        throw "DATABASE_URL 指向内存数据库，无法执行文件恢复。"
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $BackendRoot $candidate
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

$DbPath = Resolve-DbPath -BackendRoot $BackendRoot

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
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
        throw "恢复文件必须位于备份目录内：$fullPath"
    }
    return $fullPath
}

$BackendVersion = Get-BackendVersion -BackendRoot $BackendRoot
$source = Assert-PathInside -Path (Resolve-Path -LiteralPath $BackupPath).Path -Root $BackupDir
$sourceItem = Get-Item -LiteralPath $source
if (-not $sourceItem.Name.StartsWith("ticketbox-", [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $sourceItem.Name.EndsWith(".db", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "备份文件必须是 $BackupDir 下的 ticketbox-*.db：$source"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener -and -not $ForceWhileRunning) {
    throw "检测到后端仍在监听 127.0.0.1:$Port。请先停止后端，或明确传入 -ForceWhileRunning。"
}

Write-Host "校验备份文件：$source"
Test-SqliteBackup -Path $source -ExpectedBackendVersion $BackendVersion
Write-Host "备份校验通过：$(Format-Bytes $sourceItem.Length)"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DbPath) | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

if (Test-Path -LiteralPath $DbPath) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $preRestore = Join-Path $BackupDir "ticketbox-before-restore-$stamp.db"
    $preRestore = Assert-PathInside -Path $preRestore -Root $BackupDir
    $preRestoreTemp = "$preRestore.tmp-$PID"
    $python = Resolve-Python
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
        fk_violations = dst.execute('PRAGMA foreign_key_check').fetchall()
        if fk_violations:
            raise SystemExit('SQLite backup foreign_key_check failed')
    finally:
        dst.close()
finally:
    src.close()
'@
    try {
        & $python -c $script $DbPath $preRestoreTemp
        if ($LASTEXITCODE -ne 0) {
            throw "恢复前备份失败。"
        }
        Test-SqliteBackup -Path $preRestoreTemp -ExpectedBackendVersion $BackendVersion
        Move-Item -LiteralPath $preRestoreTemp -Destination $preRestore -Force
    }
    finally {
        if (Test-Path -LiteralPath $preRestoreTemp) {
            Remove-Item -LiteralPath $preRestoreTemp -Force
        }
    }
    Write-Host "已创建恢复前备份：$preRestore"
}

$restoreTemp = Join-Path (Split-Path -Parent $DbPath) "ticketbox.restore-$PID.tmp"
try {
    Copy-Item -LiteralPath $source -Destination $restoreTemp -Force
    Test-SqliteBackup -Path $restoreTemp -ExpectedBackendVersion $BackendVersion
    if (Test-Path -LiteralPath $DbPath) {
        # PS 5.1 quirk: passing $null as a .NET string argument gets
        # coerced to "", and File.Replace then rejects "" as "path is
        # not of a legal form". Use [NullString]::Value for the
        # destinationBackupFileName slot to forward a real null.
        [System.IO.File]::Replace($restoreTemp, $DbPath, [NullString]::Value, $true)
    }
    else {
        Move-Item -LiteralPath $restoreTemp -Destination $DbPath -Force
    }
}
finally {
    if (Test-Path -LiteralPath $restoreTemp) {
        Remove-Item -LiteralPath $restoreTemp -Force
    }
}
Test-SqliteBackup -Path $DbPath -ExpectedBackendVersion $BackendVersion
Write-Host "数据库恢复完成：$DbPath"
