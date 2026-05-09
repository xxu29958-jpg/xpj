param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $BackendRoot "logs"
$Python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$LogFile = Join-Path $LogDir ("backend-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
$OutLogFile = Join-Path $LogDir ("ticketbox-backend-{0}.out.log" -f (Get-Date -Format "yyyyMMdd"))
$ErrLogFile = Join-Path $LogDir ("ticketbox-backend-{0}.err.log" -f (Get-Date -Format "yyyyMMdd"))

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    "[{0}] port 127.0.0.1:{1} already has listener pid={2}" -f (Get-Date -Format "s"), $Port, $existing.OwningProcess | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 0
}

"[{0}] starting ticketbox backend on 127.0.0.1:{1}" -f (Get-Date -Format "s"), $Port | Out-File -FilePath $LogFile -Append -Encoding utf8
$process = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port", "--no-access-log") `
    -WorkingDirectory $BackendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLogFile `
    -RedirectStandardError $ErrLogFile `
    -PassThru

Start-Sleep -Seconds 4

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    "[{0}] failed to start ticketbox backend, spawned pid={1}" -f (Get-Date -Format "s"), $process.Id | Out-File -FilePath $LogFile -Append -Encoding utf8
    if (Test-Path -LiteralPath $ErrLogFile) {
        Get-Content -LiteralPath $ErrLogFile -Tail 80 | Out-File -FilePath $LogFile -Append -Encoding utf8
    }
    exit 1
}

"[{0}] ticketbox backend started pid={1} listener_pid={2}" -f (Get-Date -Format "s"), $process.Id, $listener.OwningProcess | Out-File -FilePath $LogFile -Append -Encoding utf8
exit 0
