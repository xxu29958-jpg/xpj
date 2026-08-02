param(
    [int]$Keep = 30,
    [ValidateRange(10, 3600)][int]$DatabaseToolTimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$WindowsSafetyScript = Join-Path $BackendRoot "packaging\windows_installation_safety.ps1"
if (-not (Test-Path -LiteralPath $WindowsSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 受保护文件实现：$WindowsSafetyScript"
}
. $WindowsSafetyScript
$DatabaseSafetyScript = Join-Path $BackendRoot "packaging\windows_database_safety.ps1"
if (-not (Test-Path -LiteralPath $DatabaseSafetyScript -PathType Leaf)) {
    throw "缺少 Windows 数据库安全实现：$DatabaseSafetyScript"
}
. $DatabaseSafetyScript
# 备份目录跟随数据根:冻结 EXE / 显式 override 经 TICKETBOX_DATA_DIR 指定,否则 = backend 根
# （与 app.config.DATA_ROOT / backup_service._BACKUP_DIR 一致,保证"备份可恢复"闭环跨部署形态成立）。
$DataRoot = if ([string]::IsNullOrWhiteSpace($env:TICKETBOX_DATA_DIR)) { $BackendRoot } else { $env:TICKETBOX_DATA_DIR }
$BackupDir = Join-Path $DataRoot "backups"

# 备份作业并发守卫(BUG-2):与 backup_service._backup_lock 共用同一个 OS byte-range lease。
# 文件名以 "." 开头,不会被 ticketbox-*.dump 轮转/列举/异地同步匹配到。
$BackupLockPath = Join-Path $BackupDir ".backup.lock"

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

function Assert-DatabaseQueryContract {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Query
    )

    $requireAuthValues = @()
    foreach ($part in $Query.TrimStart('?').Split('&')) {
        if ([string]::IsNullOrWhiteSpace($part)) {
            continue
        }
        $separatorIndex = $part.IndexOf('=')
        if ($separatorIndex -lt 0) {
            $encodedKey = $part
            $encodedValue = ""
        }
        else {
            $encodedKey = $part.Substring(0, $separatorIndex)
            $encodedValue = $part.Substring($separatorIndex + 1)
        }
        try {
            $key = [System.Uri]::UnescapeDataString($encodedKey)
            $value = [System.Uri]::UnescapeDataString($encodedValue)
        }
        catch {
            throw "DATABASE_URL 查询参数格式无效。"
        }
        if ($key.ToLowerInvariant() -in @("password", "sslpassword")) {
            throw "DATABASE_URL 不得通过查询参数传递数据库口令。"
        }
        if ($key.Equals("require_auth", [System.StringComparison]::OrdinalIgnoreCase)) {
            $requireAuthValues += $value
        }
    }
    if ($requireAuthValues.Count -ne 1 -or $requireAuthValues[0] -cne "scram-sha-256") {
        throw "DATABASE_URL 必须精确要求 require_auth=scram-sha-256。"
    }
}

function ConvertTo-PgDumpConnection {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $builder = [System.UriBuilder]::new($Url)
    }
    catch {
        throw "DATABASE_URL 格式无效，无法执行 PostgreSQL 备份。"
    }
    if ($builder.Scheme -notmatch '^postgresql(?:\+\w+)?$') {
        throw "备份脚本只支持 PostgreSQL。"
    }
    Assert-DatabaseQueryContract -Query $builder.Query

    $username = [System.Uri]::UnescapeDataString($builder.UserName)
    $database = [System.Uri]::UnescapeDataString($builder.Path.TrimStart('/'))
    if (
        [string]::IsNullOrWhiteSpace($username) -or
        [string]::IsNullOrWhiteSpace($builder.Host) -or
        [string]::IsNullOrWhiteSpace($database)
    ) {
        throw "DATABASE_URL 缺少 PostgreSQL 用户、主机或数据库。"
    }

    $password = $null
    if (-not [string]::IsNullOrEmpty($builder.Password)) {
        $password = [System.Uri]::UnescapeDataString($builder.Password)
    }
    $builder.Scheme = "postgresql"
    $builder.Password = ""
    return [pscustomobject]@{
        DatabaseUrl = $builder.Uri.AbsoluteUri
        Username = $username
        Host = $builder.Host
        Port = if ($builder.Port -gt 0) { $builder.Port } else { 5432 }
        Database = $database
        Password = $password
    }
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
    $candidate = $null
    $programFiles = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::ProgramFiles
    )
    if (-not [string]::IsNullOrWhiteSpace($programFiles)) {
        $candidate = Get-ChildItem `
            -Path (Join-Path $programFiles "PostgreSQL\*\bin\pg_dump.exe") `
            -ErrorAction SilentlyContinue |
            Sort-Object { Get-PgInstallVersionKey $_.Directory.Parent.Name } -Descending |
            Select-Object -First 1
    }
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
        $result = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $python `
            -Arguments @('-m', 'app.services.postgres_backup_validation_service', $Path) `
            -TimeoutMilliseconds ($DatabaseToolTimeoutSeconds * 1000) `
            -Label 'PostgreSQL 备份校验'
        if ($result.ExitCode -ne 0) {
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
    $connection = ConvertTo-PgDumpConnection -Url $DatabaseUrl
    $tempPath = "$TargetPath.tmp-$PID"
    try {
        if ($null -eq $connection.Password) {
            throw "计划备份要求 DATABASE_URL 提供受保护配置中的数据库口令。"
        }
        $result = Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $connection.DatabaseUrl `
            -Password $connection.Password `
            -Action {
                param([string]$ProtectedDatabaseUrl)
                return Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $pgDump `
                    -Arguments @(
                        '--no-password',
                        '--lock-wait-timeout=30000',
                        '--format=custom',
                        '--file', $tempPath,
                        '--dbname', $ProtectedDatabaseUrl
                    ) `
                    -TimeoutMilliseconds ($DatabaseToolTimeoutSeconds * 1000) `
                    -Label 'pg_dump'
            }
        if ($result.ExitCode -ne 0) {
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
    # 隐私契约：只有显式 true + 显式绝对目录才允许把数据库/票据复制出本地数据根。
    $enabled = $env:XPJ_OFFSITE_BACKUP_ENABLED
    $destination = $env:XPJ_OFFSITE_BACKUP_DIR
    if ([string]::IsNullOrWhiteSpace($enabled)) {
        if (-not [string]::IsNullOrWhiteSpace($destination)) {
            Write-Warning "已配置 XPJ_OFFSITE_BACKUP_DIR，但未显式启用异地备份；仅保留本地备份。"
        }
        return $null
    }
    if ($enabled.Trim().ToLowerInvariant() -eq "false") {
        return $null
    }
    if ($enabled.Trim().ToLowerInvariant() -ne "true") {
        throw "XPJ_OFFSITE_BACKUP_ENABLED 只接受 true 或 false；仅保留本地备份。"
    }
    if ([string]::IsNullOrWhiteSpace($destination)) {
        throw "异地备份已启用，但 XPJ_OFFSITE_BACKUP_DIR 未配置；本地备份已保留。"
    }
    $destination = $destination.Trim()
    if (-not [System.IO.Path]::IsPathRooted($destination)) {
        throw "XPJ_OFFSITE_BACKUP_DIR 必须是绝对路径；本地备份已保留。"
    }
    return $destination
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

function Get-BackupLock {
    # 取得返回 FileStream;另一个存活作业持锁返回 $null(跳过,不报错)。
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        if ($stream.Length -eq 0) {
            $stream.WriteByte(0)
            $stream.Flush($true)
        }
        $stream.Position = 0
        try {
            $stream.Lock(0, 1)
        }
        catch [System.IO.IOException] {
            $stream.Dispose()
            return $null
        }
        $payload = "$PID`n$([DateTime]::UtcNow.ToString('o'))`n"
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $stream.SetLength(0)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Position = 0
        return $stream
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Close-BackupLock {
    param([Parameter(Mandatory = $true)][System.IO.FileStream]$Lease)

    try {
        $Lease.Position = 0
        $Lease.Unlock(0, 1)
    }
    finally {
        $Lease.Dispose()
    }
}

function Invoke-BackupDatabase {
    param([int]$KeepCount)

    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $databaseUrl = Get-DatabaseUrl

    # 并发守卫：检测到在跑就良性跳过，不让计划任务结果出红。
    $backupLock = Get-BackupLock -Path $BackupLockPath
    if ($null -eq $backupLock) {
        Write-Host "另一备份作业正在运行，跳过本次备份（并发守卫）。"
        return
    }

    try {
        $target = Join-Path $BackupDir "ticketbox-$timestamp.dump"
        $target = Assert-PathInside -Path $target -Root $BackupDir
        Backup-PostgresDatabase -DatabaseUrl $databaseUrl -TargetPath $target
        Write-Host "已备份到 $target"

        $resolvedBackupRoot = (Resolve-Path -LiteralPath $BackupDir).Path
        $backups = Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-*.dump" |
            Sort-Object LastWriteTime -Descending
        if ($KeepCount -gt 0 -and $backups.Count -gt $KeepCount) {
            $backups | Select-Object -Skip $KeepCount | ForEach-Object {
                $candidate = Assert-PathInside -Path $_.FullName -Root $resolvedBackupRoot
                Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
            }
        }

        $offsiteDir = Get-OffsiteBackupDir
        if ($offsiteDir) {
            Sync-BackupsOffsite -Destination $offsiteDir
        }
        else {
            Write-Host "异地备份未显式启用；本次仅保留本地备份。"
        }
    }
    finally {
        Close-BackupLock -Lease $backupLock
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Invoke-BackupDatabase -KeepCount $Keep
}
