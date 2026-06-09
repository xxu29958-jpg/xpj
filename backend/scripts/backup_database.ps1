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

# 解析 Python 解释器(优先 venv),供 pg_dump 归档校验步骤
# (app.services.postgres_backup_validation_service)使用。
function Resolve-Python {
    $venvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "未找到 Python，无法运行 PostgreSQL 备份校验。"
}

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

function Get-DatabaseUrl {
    $url = Get-BackendEnvValue -Name "DATABASE_URL"
    if ([string]::IsNullOrWhiteSpace($url)) {
        return ""
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
if ($databaseUrl -notmatch '^postgresql') {
    throw "备份脚本只支持 PostgreSQL（DATABASE_URL=$databaseUrl）。"
}

$target = Join-Path $BackupDir "ticketbox-$timestamp.dump"
$target = Assert-PathInside -Path $target -Root $BackupDir
Backup-PostgresDatabase -DatabaseUrl $databaseUrl -TargetPath $target
$rotateFilter = "ticketbox-*.dump"
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
