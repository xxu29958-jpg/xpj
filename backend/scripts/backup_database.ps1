param(
    [int]$Keep = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
# 备份目录跟随数据根:冻结 EXE / 显式 override 经 TICKETBOX_DATA_DIR 指定,否则 = backend 根
# （与 app.config.DATA_ROOT / backup_service._BACKUP_DIR 一致,保证"备份可恢复"闭环跨部署形态成立）。
$DataRoot = if ([string]::IsNullOrWhiteSpace($env:TICKETBOX_DATA_DIR)) { $BackendRoot } else { $env:TICKETBOX_DATA_DIR }
$BackupDir = Join-Path $DataRoot "backups"

# 共享 SQLite 备份/校验函数(Resolve-Python / Get-BackendVersion / Test-SqliteBackup /
# Backup-SqliteDatabase),与 scripts\maintenance_ticketbox.ps1 共用同一份实现。dot-source
# 后这些函数沿用本脚本作用域的 $BackendRoot(此处已就绪)。
. (Join-Path $PSScriptRoot "lib\sqlite_backup.ps1")

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

function Get-DatabaseUrl {
    $url = Get-BackendEnvValue -Name "DATABASE_URL"
    if ([string]::IsNullOrWhiteSpace($url)) {
        return "sqlite:///data/ticketbox.db"
    }
    return $url
}

function ConvertTo-LibpqUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    # pg_dump/pg_restore want a libpq URL without the SQLAlchemy +driver tag.
    return ($Url -replace '^postgresql\+\w+://', 'postgresql://')
}

function Get-PgDumpBinary {
    if (-not [string]::IsNullOrWhiteSpace($env:PG_DUMP_PATH)) {
        return $env:PG_DUMP_PATH
    }
    $command = Get-Command pg_dump -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidate = Get-ChildItem -Path "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }
    throw "未找到 pg_dump，无法备份 PostgreSQL 数据库。请设置 PG_DUMP_PATH 或将其加入 PATH。"
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

function Test-PostgresBackup {
    param([Parameter(Mandatory = $true)][string]$Path)

    $python = Resolve-Python
    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH")
    try {
        if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
            $env:PYTHONPATH = $BackendRoot
        }
        else {
            $env:PYTHONPATH = "$BackendRoot;$previousPythonPath"
        }
        & $python -m app.services.postgres_backup_validation_service $Path
        if ($LASTEXITCODE -ne 0) {
            throw "PostgreSQL 备份校验失败：$Path"
        }
    }
    finally {
        if ($null -eq $previousPythonPath) {
            Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $previousPythonPath
        }
    }
}

function Backup-PostgresDatabase {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $pgDump = Get-PgDumpBinary
    $libpqUrl = ConvertTo-LibpqUrl -Url $DatabaseUrl
    $tempPath = "$TargetPath.tmp-$PID"
    try {
        & $pgDump --format=custom --file $tempPath --dbname $libpqUrl
        if ($LASTEXITCODE -ne 0) {
            throw "pg_dump 失败。"
        }
        Test-PostgresBackup -Path $tempPath
        Move-Item -LiteralPath $tempPath -Destination $TargetPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$databaseUrl = Get-DatabaseUrl

if ($databaseUrl -match '^postgresql') {
    $target = Join-Path $BackupDir "ticketbox-$timestamp.dump"
    $target = Assert-PathInside -Path $target -Root $BackupDir
    Backup-PostgresDatabase -DatabaseUrl $databaseUrl -TargetPath $target
    $rotateFilter = "ticketbox-*.dump"
}
else {
    $DatabasePath = Resolve-DbPath -BackendRoot $BackendRoot
    if (-not (Test-Path -LiteralPath $DatabasePath)) {
        throw "Database not found: $DatabasePath"
    }
    $target = Join-Path $BackupDir "ticketbox-$timestamp.db"
    $target = Assert-PathInside -Path $target -Root $BackupDir
    Backup-SqliteDatabase -SourcePath $DatabasePath -TargetPath $target
    $rotateFilter = "ticketbox-*.db"
}
Write-Host "已备份到 $target"

$resolvedBackupRoot = (Resolve-Path -LiteralPath $BackupDir).Path
$backups = Get-ChildItem -LiteralPath $BackupDir -Filter $rotateFilter |
    Sort-Object LastWriteTime -Descending

if ($Keep -gt 0 -and $backups.Count -gt $Keep) {
    $backups | Select-Object -Skip $Keep | ForEach-Object {
        $resolvedCandidate = Assert-PathInside -Path $_.FullName -Root $resolvedBackupRoot
        Remove-Item -LiteralPath $resolvedCandidate -Force
    }
}
