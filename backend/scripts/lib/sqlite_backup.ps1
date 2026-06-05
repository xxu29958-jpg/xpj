# 共享 SQLite 备份 + 校验函数(dot-source 库,无副作用、不在加载时执行任何动作)。
#
# 由 backend/scripts/backup_database.ps1(手动备份)与 scripts/maintenance_ticketbox.ps1
# (计划任务维护)共同 dot-source,消除两边重复的 SQLite 备份/校验逻辑。PG 备份路径仍只在
# backup_database.ps1 里(maintenance 委托给它),本库只负责 SQLite 那条路。
#
# 约定:这些函数在 dot-source 后运行于调用脚本的作用域,沿用调用脚本的 $BackendRoot
# (与原先内联定义时的行为一致);调用脚本必须在 dot-source 前已设置 $BackendRoot。

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

function Get-BackendVersion {
    param([Parameter(Mandatory = $true)][string]$BackendRoot)

    $versionFile = Join-Path $BackendRoot "app\version.py"
    if (-not (Test-Path -LiteralPath $versionFile)) {
        throw "未找到后端版本文件：$versionFile"
    }
    $content = Get-Content -LiteralPath $versionFile -Raw -Encoding UTF8
    if ($content -notmatch "BACKEND_VERSION\s*=\s*['""]([^'""]+)['""]") {
        throw "无法从 app\version.py 读取 BACKEND_VERSION。"
    }
    return $Matches[1]
}

function Test-SqliteBackup {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedBackendVersion
    )

    $python = Resolve-Python
    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH")
    try {
        if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
            $env:PYTHONPATH = $BackendRoot
        }
        else {
            $env:PYTHONPATH = "$BackendRoot;$previousPythonPath"
        }
        & $python -m app.services.sqlite_backup_validation_service $Path --expected-backend-version $ExpectedBackendVersion
        if ($LASTEXITCODE -ne 0) {
            throw "Ticketbox 备份校验失败：$Path"
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
        Test-SqliteBackup -Path $tempPath -ExpectedBackendVersion (Get-BackendVersion -BackendRoot $BackendRoot)
        Move-Item -LiteralPath $tempPath -Destination $TargetPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }
}
