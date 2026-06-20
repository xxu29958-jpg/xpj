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

# 备份作业并发守卫(BUG-2):与 backup_service._backup_lock 共用同一个哨兵文件 + TTL。
# 文件名以 "." 开头,不会被 ticketbox-*.dump 轮转/列举/异地同步匹配到。
$BackupLockPath = Join-Path $BackupDir ".backup.lock"
$BackupLockStaleSeconds = 30 * 60

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

    # .env 落点跟随应用:app.config 在 DATA_ROOT\.env 上 load_dotenv(冻结 EXE /
    # TICKETBOX_DATA_DIR 部署下 Owner Console 把设置写在那里),源码形态
    # DataRoot==BackendRoot 自然不变。固定读 $BackendRoot\.env 会让备份在
    # 自定义数据根部署下读错(或读不到)DATABASE_URL/UPLOAD_DIR——dump 错库
    # 或漏备真实上传目录。
    $envFile = Join-Path $DataRoot ".env"
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

function Get-PgInstallVersionKey {
    # "17" / "9.6" → 数值排序键；字符串倒序会让 9.x 压过 17（"9" > "1"），
    # 老客户端残留时备份会静默用旧工具跑。非数字目录名排最低。
    param([Parameter(Mandatory = $true)][string]$VersionDirName)

    $value = 0.0
    $parsed = [double]::TryParse(
        $VersionDirName,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$value
    )
    if ($parsed) {
        return $value
    }
    return -1.0
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
        Sort-Object { Get-PgInstallVersionKey $_.Directory.Parent.Name } -Descending |
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

function Get-UploadsSourceDir {
    # 票据图片真实目录与 app.config.get_settings() 同一解析:UPLOAD_DIR
    # (进程 env → backend\.env,默认 "uploads"),相对路径按数据根解析、
    # 绝对路径原样使用。固定拼 $DataRoot\uploads 会在 UPLOAD_DIR 自定义
    # 部署下把图片漏出异地备份(数据库 dump 有了、图片没有)。
    $configured = Get-BackendEnvValue -Name "UPLOAD_DIR"
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = "uploads"
    }
    if ([System.IO.Path]::IsPathRooted($configured)) {
        return $configured
    }
    return (Join-Path $DataRoot $configured)
}

function Get-OffsiteBackupDir {
    # 异地备份目标解析：XPJ_OFFSITE_BACKUP_DIR 显式优先（值为 off 表示禁用）；
    # 未设置时检测到 OneDrive 即默认 %OneDrive%\TicketboxBackups；都没有则跳过。
    $explicit = $env:XPJ_OFFSITE_BACKUP_DIR
    if (-not [string]::IsNullOrWhiteSpace($explicit)) {
        if ($explicit.Trim().ToLowerInvariant() -eq "off") {
            return $null
        }
        return $explicit.Trim()
    }
    if (-not [string]::IsNullOrWhiteSpace($env:OneDrive)) {
        return (Join-Path $env:OneDrive "TicketboxBackups")
    }
    return $null
}

function Invoke-Robocopy {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & robocopy @Arguments | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy 失败(exit=$LASTEXITCODE)：$($Arguments -join ' ')"
    }
}

function Sync-BackupsOffsite {
    # 异地同步（ENGINEERING_RULES §6：数据库和文件存储都必须备份；单机部署盘损是主要数据风险）。
    param([Parameter(Mandatory = $true)][string]$Destination)

    $dbDest = Join-Path $Destination "db"
    New-Item -ItemType Directory -Force -Path $dbDest | Out-Null

    # 数据库归档只增量复制（不镜像删除——本地目录被清空/勒索时不殃及异地副本）；
    # 异地按 90 天保留（本地 30 天），超期才删，保证有界。
    $dumps = @(Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*.dump" -File -ErrorAction SilentlyContinue)
    if ($dumps.Count -gt 0) {
        Invoke-Robocopy -Arguments @($BackupDir, $dbDest, "ticketbox-*.dump", "/NJH", "/NJS", "/NDL", "/NP")
    }
    $offsiteCutoff = (Get-Date).AddDays(-90)
    Get-ChildItem -LiteralPath $dbDest -Filter "ticketbox-*.dump" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $offsiteCutoff } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

    # 票据图片镜像真实上传目录(UPLOAD_DIR 感知,见 Get-UploadsSourceDir)；
    # 空源守卫——本地 uploads 意外为空时跳过，防 /MIR 把异地副本一并清空。
    $uploadsSource = Get-UploadsSourceDir
    if (Test-Path -LiteralPath $uploadsSource) {
        $uploadCount = @(Get-ChildItem -LiteralPath $uploadsSource -Recurse -File -ErrorAction SilentlyContinue).Count
        if ($uploadCount -gt 0) {
            $uploadsDest = Join-Path $Destination "uploads"
            New-Item -ItemType Directory -Force -Path $uploadsDest | Out-Null
            Invoke-Robocopy -Arguments @($uploadsSource, $uploadsDest, "/MIR", "/NJH", "/NJS", "/NDL", "/NP")
        }
        else {
            Write-Host "本地 uploads 为空，跳过异地镜像（空源守卫）。"
        }
    }

    Write-Host "异地备份同步完成：$Destination（db 归档 $($dumps.Count) 个，异地保留 90 天）。"
}

function Test-BackupLockStale {
    # 哨兵文件早于 TTL = 之前的备份作业崩溃残留,可回收(镜像 backup_service._lock_is_stale)。
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    if (-not $item) {
        return $false  # 已不在 —— 下一次独占创建会赢
    }
    return ((Get-Date) - $item.LastWriteTime).TotalSeconds -gt $BackupLockStaleSeconds
}

function Get-BackupLock {
    # 取得返回 $true;另一个存活作业持锁返回 $false(跳过,不报错)。CreateNew 等价于
    # Python 的 O_CREAT|O_EXCL:文件已存在即抛 IOException,由它仲裁回收竞态。
    param([Parameter(Mandatory = $true)][string]$Path)

    while ($true) {
        try {
            $stream = [System.IO.File]::Open(
                $Path,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $payload = "$PID`n$([DateTime]::UtcNow.ToString('o'))`n"
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
                $stream.Write($bytes, 0, $bytes.Length)
            }
            finally {
                $stream.Dispose()
            }
            return $true
        }
        catch [System.IO.IOException] {
            if (Test-BackupLockStale -Path $Path) {
                Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
                continue
            }
            return $false
        }
    }
}

function Remove-BackupLock {
    param([Parameter(Mandatory = $true)][string]$Path)
    Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$databaseUrl = Get-DatabaseUrl
if ($databaseUrl -notmatch '^postgresql') {
    throw "备份脚本只支持 PostgreSQL（DATABASE_URL=$databaseUrl）。"
}

# 并发守卫(BUG-2):手动备份 / Owner Console / 本计划任务同写 backups\ 时,轮转会互相
# 删到对方的文件而报错。检测到在跑就跳过(良性,退出码 0,不让计划任务结果出红)。
if (-not (Get-BackupLock -Path $BackupLockPath)) {
    Write-Host "另一备份作业正在运行，跳过本次备份（并发守卫）。"
    return
}

try {
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
            # 并发轮转可能已删掉同一个旧文件 —— 已不在即达到目标状态,不算错(BUG-2)。
            Remove-Item -LiteralPath $resolvedCandidate -Force -ErrorAction SilentlyContinue
        }
    }

    $offsiteDir = Get-OffsiteBackupDir
    if ($offsiteDir) {
        Sync-BackupsOffsite -Destination $offsiteDir
    }
    else {
        Write-Host "未配置异地备份目录（XPJ_OFFSITE_BACKUP_DIR / OneDrive 均缺席），跳过异地同步。"
    }
}
finally {
    Remove-BackupLock -Path $BackupLockPath
}
