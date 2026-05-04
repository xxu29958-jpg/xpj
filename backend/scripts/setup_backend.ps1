param(
    [switch]$Dev,
    [switch]$ForceEnv,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvDir = Join-Path $BackendRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$EnvPath = Join-Path $BackendRoot ".env"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-Python {
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }

    if ($Python.Trim().Length -gt 0) {
        return $Python
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return "py"
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        & $pythonCommand.Source -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $pythonCommand.Source
        }
    }

    throw "未找到 Python。请先安装 Python 3.11+，或用 -Python 指定 python.exe 路径。"
}

function Test-PythonVersion {
    param([string]$PythonCommand)

    if ($PythonCommand -eq "py") {
        $version = & py -3.11 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    }
    else {
        $version = & $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "无法读取 Python 版本。"
    }

    $parts = $version.Trim().Split(".")
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
        throw "Python 版本过低：$version。小票夹后端需要 Python 3.11+。"
    }
    Write-Host "Python $version OK"
}

function New-Token {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Write-EnvFile {
    if ((Test-Path -LiteralPath $EnvPath) -and -not $ForceEnv) {
        Write-Host ".env 已存在，未覆盖。需要重建可加 -ForceEnv。"
        return
    }

    $content = @(
        "UPLOAD_TOKEN=$(New-Token)",
        "APP_TOKEN=$(New-Token)",
        "ADMIN_TOKEN=$(New-Token)",
        "DATABASE_URL=sqlite:///data/ticketbox.db",
        "UPLOAD_DIR=uploads",
        "MAX_UPLOAD_SIZE_MB=10",
        "DELETE_IMAGE_AFTER_CONFIRM=false",
        "GENERATE_THUMBNAIL=true",
        "DELETE_IMAGE_AFTER_DAYS=0",
        "OCR_PROVIDER=empty"
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($EnvPath, $content, $utf8NoBom)
    Write-Host "已创建 .env，Token 已随机生成。请妥善保管，不要提交或截图。"
}

Set-Location $BackendRoot
$pythonCommand = Resolve-Python
Test-PythonVersion $pythonCommand

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "创建虚拟环境 .venv"
    if ($pythonCommand -eq "py") {
        Invoke-Checked -FilePath "py" -Arguments @("-3.11", "-m", "venv", ".venv")
    }
    else {
        Invoke-Checked -FilePath $pythonCommand -Arguments @("-m", "venv", ".venv")
    }
}
else {
    Write-Host ".venv 已存在，跳过创建。"
}

Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-r", "requirements.txt")
if ($Dev) {
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-r", "requirements-dev.txt")
}

New-Item -ItemType Directory -Force -Path (Join-Path $BackendRoot "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendRoot "uploads") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendRoot "backups") | Out-Null
Write-EnvFile

Write-Host ""
Write-Host "后端初始化完成。"
Write-Host "启动：run.bat"
Write-Host "开发验证：.venv\Scripts\python.exe -m pytest"
