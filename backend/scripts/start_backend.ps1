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

function Get-ExpectedBackendVersion {
    $VersionFile = Join-Path $BackendRoot "app\version.py"
    if (-not (Test-Path -LiteralPath $VersionFile)) {
        return ""
    }

    $content = Get-Content -LiteralPath $VersionFile -Raw -Encoding UTF8
    $match = [regex]::Match($content, "BACKEND_VERSION\s*=\s*[""']([^""']+)[""']")
    if ($match.Success) {
        return $match.Groups[1].Value
    }

    return ""
}

function Get-BackendHealth {
    param([int]$TargetPort)

    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$TargetPort/api/health" -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Get-BackendSourceStamp {
    $AppDir = Join-Path $BackendRoot "app"
    if (-not (Test-Path -LiteralPath $AppDir)) {
        return $null
    }

    $latest = Get-ChildItem -LiteralPath $AppDir -Recurse -File -Filter "*.py" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($latest) {
        return $latest.LastWriteTimeUtc
    }

    return $null
}

function Test-ListenerLoadedCurrentSource {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $sourceStamp = Get-BackendSourceStamp
    if (-not $sourceStamp) {
        return $true
    }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process -or -not $process.StartTime) {
        return $false
    }

    return $process.StartTime.ToUniversalTime() -ge $sourceStamp
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    $expectedVersion = Get-ExpectedBackendVersion
    $health = Get-BackendHealth -TargetPort $Port
    $runningVersion = if ($health) { [string]$health.backend_version } else { "" }
    $loadedCurrentSource = Test-ListenerLoadedCurrentSource -ProcessId $existing.OwningProcess

    if ($health -and $health.status -eq "ok" -and $expectedVersion -and $runningVersion -eq $expectedVersion -and $loadedCurrentSource) {
        "[{0}] port 127.0.0.1:{1} already has current listener pid={2} backend_version={3}" -f (Get-Date -Format "s"), $Port, $existing.OwningProcess, $runningVersion | Out-File -FilePath $LogFile -Append -Encoding utf8
        exit 0
    }

    "[{0}] refusing stale or unknown listener on 127.0.0.1:{1} pid={2} expected={3} running={4} loaded_current_source={5}" -f (Get-Date -Format "s"), $Port, $existing.OwningProcess, $expectedVersion, $runningVersion, $loadedCurrentSource | Out-File -FilePath $LogFile -Append -Encoding utf8
    Write-Host "FAIL 127.0.0.1:$Port 已有监听进程 pid=$($existing.OwningProcess)，但不是当前后端代码。expected=$expectedVersion running=$runningVersion loaded_current_source=$loadedCurrentSource。请先运行 scripts\restart_backend.ps1 -Port $Port。"
    exit 1
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
