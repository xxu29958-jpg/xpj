param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile
)

$ErrorActionPreference = "Stop"
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DataDir = Join-Path $BackendRoot "data"
$BackupDir = Join-Path $BackendRoot "backups"
$DatabasePath = Join-Path $DataDir "ticketbox.db"

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
        throw "Refusing to use path outside backup directory: $fullPath"
    }
    return $fullPath
}

function Invoke-Sqlite {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $python = Resolve-Python
    & $python -c $Script @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite 操作失败。"
    }
}

function Test-SqliteBackup {
    param([Parameter(Mandatory = $true)][string]$Path)

    Invoke-Sqlite `
        -Script "import sqlite3, sys; con = sqlite3.connect(sys.argv[1]); result = con.execute('PRAGMA integrity_check').fetchone()[0]; con.close(); raise SystemExit(0 if result == 'ok' else 1)" `
        -Arguments @($Path)
}

function Backup-SqliteDatabase {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

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
    Invoke-Sqlite -Script $script -Arguments @($SourcePath, $TargetPath)
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$resolvedBackupFile = Assert-PathInside -Path (Resolve-Path -LiteralPath $BackupFile).Path -Root $BackupDir

if ((Split-Path -Leaf $resolvedBackupFile) -notlike "ticketbox-*.db") {
    throw "Backup file must match ticketbox-*.db"
}

Test-SqliteBackup -Path $resolvedBackupFile

if (Test-Path -LiteralPath $DatabasePath) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $safetyBackup = Join-Path $BackupDir "ticketbox-before-restore-$timestamp.db"
    $safetyBackup = Assert-PathInside -Path $safetyBackup -Root $BackupDir
    Backup-SqliteDatabase -SourcePath $DatabasePath -TargetPath $safetyBackup
    Write-Host "恢复前已备份当前数据库到 $safetyBackup"
}

Copy-Item -LiteralPath $resolvedBackupFile -Destination $DatabasePath -Force
Test-SqliteBackup -Path $DatabasePath
Write-Host "已从 $resolvedBackupFile 恢复到 $DatabasePath"
