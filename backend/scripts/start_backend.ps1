param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $BackendRoot "logs"
$Python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$LogFile = Join-Path $LogDir ("backend-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}

Set-Location $BackendRoot
"[{0}] starting ticketbox backend on 127.0.0.1:{1}" -f (Get-Date -Format "s"), $Port | Out-File -FilePath $LogFile -Append -Encoding utf8

& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port *>> $LogFile
