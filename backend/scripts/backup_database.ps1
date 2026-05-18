param(
    [int]$Keep = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackupDir = Join-Path $BackendRoot "backups"

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
        throw "DATABASE_URL 不是 sqlite，备份脚本只能处理 SQLite 文件：$databaseUrl"
    }

    $candidate = $Matches[1]
    if ($candidate -eq ":memory:") {
        throw "DATABASE_URL 指向内存数据库，无法执行文件备份。"
    }
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $BackendRoot $candidate
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

$DatabasePath = Resolve-DbPath -BackendRoot $BackendRoot

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

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

if (-not (Test-Path -LiteralPath $DatabasePath)) {
    throw "Database not found: $DatabasePath"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$target = Join-Path $BackupDir "ticketbox-$timestamp.db"
$target = Assert-PathInside -Path $target -Root $BackupDir
Backup-SqliteDatabase -SourcePath $DatabasePath -TargetPath $target
Write-Host "已备份到 $target"

$resolvedBackupRoot = (Resolve-Path -LiteralPath $BackupDir).Path
$backups = Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*.db" |
    Sort-Object LastWriteTime -Descending

if ($Keep -gt 0 -and $backups.Count -gt $Keep) {
    $backups | Select-Object -Skip $Keep | ForEach-Object {
        $resolvedCandidate = Assert-PathInside -Path $_.FullName -Root $resolvedBackupRoot
        Remove-Item -LiteralPath $resolvedCandidate -Force
    }
}
