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

function Test-ListenerUsesExpectedRuntime {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $processInfo) {
        return $false
    }

    $expectedPythonPath = (Resolve-Path -LiteralPath $Python).Path
    $executablePath = [string]$processInfo.ExecutablePath
    $commandLine = [string]$processInfo.CommandLine
    $usesExpectedPython = $executablePath.Equals($expectedPythonPath, [System.StringComparison]::OrdinalIgnoreCase)
    $runsTicketboxApp = (
        $commandLine.Contains("app.main:app") -and
        $commandLine.Contains("--host 127.0.0.1") -and
        $commandLine.Contains("--port $Port")
    )
    if ($usesExpectedPython -and $runsTicketboxApp) {
        return $true
    }

    $parentProcessId = [int]$processInfo.ParentProcessId
    if ($parentProcessId -le 0) {
        return $false
    }

    $parentProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$parentProcessId" -ErrorAction SilentlyContinue
    if (-not $parentProcessInfo) {
        return $false
    }

    $parentExecutablePath = [string]$parentProcessInfo.ExecutablePath
    $parentCommandLine = [string]$parentProcessInfo.CommandLine
    $parentUsesExpectedPython = $parentExecutablePath.Equals($expectedPythonPath, [System.StringComparison]::OrdinalIgnoreCase)
    $parentRunsTicketboxApp = (
        $parentCommandLine.Contains("app.main:app") -and
        $parentCommandLine.Contains("--host 127.0.0.1") -and
        $parentCommandLine.Contains("--port $Port")
    )

    return $runsTicketboxApp -and $parentUsesExpectedPython -and $parentRunsTicketboxApp
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python"
}

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    # codex P2 #12: 此前从 /api/health 读 $health.backend_version,但 /api/health 按
    # SECURITY.md / ENGINEERING_RULES §12 匿名只返 {status:ok},不暴露 version(version 走
    # 需 session 的 /api/status/private)。该字段永远 null → version 比较永远 false →
    # listener 每次被认为版本不匹配。loadedCurrentSource(进程启动时间 ≥ 最新 .py mtime)
    # + usesExpectedRuntime(用期望 .venv python)足以证明 listener 跑的是当前代码。
    $expectedVersion = Get-ExpectedBackendVersion
    $health = Get-BackendHealth -TargetPort $Port
    $loadedCurrentSource = Test-ListenerLoadedCurrentSource -ProcessId $existing.OwningProcess
    $usesExpectedRuntime = Test-ListenerUsesExpectedRuntime -ProcessId $existing.OwningProcess

    if ($health -and $health.status -eq "ok" -and $loadedCurrentSource -and $usesExpectedRuntime) {
        "[{0}] port 127.0.0.1:{1} already has current listener pid={2} expected_version={3}" -f (Get-Date -Format "s"), $Port, $existing.OwningProcess, $expectedVersion | Out-File -FilePath $LogFile -Append -Encoding utf8
        exit 0
    }

    "[{0}] refusing stale or unknown listener on 127.0.0.1:{1} pid={2} expected={3} loaded_current_source={4} expected_runtime={5}" -f (Get-Date -Format "s"), $Port, $existing.OwningProcess, $expectedVersion, $loadedCurrentSource, $usesExpectedRuntime | Out-File -FilePath $LogFile -Append -Encoding utf8
    Write-Host "FAIL 127.0.0.1:$Port 已有监听进程 pid=$($existing.OwningProcess)，但不是当前项目后端运行时。expected=$expectedVersion loaded_current_source=$loadedCurrentSource expected_runtime=$usesExpectedRuntime。请先运行 scripts\restart_backend.ps1 -Port $Port。"
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
