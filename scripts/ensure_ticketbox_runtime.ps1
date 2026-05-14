param(
    [string]$ServerUrl = "https://api.example.com",
    [int]$Port = 8000,
    [string]$BackendTaskName = "TicketboxBackend",
    [string]$TunnelTaskName = "TicketboxCloudflareTunnel",
    [int]$TimeoutSeconds = 45,
    [switch]$SkipPublicAuth,
    [string]$SessionToken = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$BackendStartScript = Join-Path $BackendRoot "scripts\start_backend.ps1"
$BackendRestartScript = Join-Path $ProjectRoot "scripts\restart_backend.ps1"
$BackendVersionFile = Join-Path $BackendRoot "app\version.py"
$ExpectedBackendPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$BaseUrl = $ServerUrl.TrimEnd("/")
$Failures = New-Object System.Collections.Generic.List[string]

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Resolve-SessionToken {
    if ($SessionToken.Trim().Length -gt 0) {
        return $SessionToken.Trim()
    }
    $processValue = [Environment]::GetEnvironmentVariable("TICKETBOX_SESSION_TOKEN")
    if ($processValue -and $processValue.Trim().Length -gt 0) {
        return $processValue.Trim()
    }
    return ""
}

function Get-ExpectedBackendVersion {
    if (-not (Test-Path -LiteralPath $BackendVersionFile)) {
        return ""
    }

    $content = Get-Content -LiteralPath $BackendVersionFile -Raw -Encoding UTF8
    $match = [regex]::Match($content, "BACKEND_VERSION\s*=\s*[""']([^""']+)[""']")
    if ($match.Success) {
        return $match.Groups[1].Value
    }

    return ""
}

function Get-LocalBackendHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
    }
    catch {
        return $null
    }
}

function Get-BackendSourceStamp {
    $appDir = Join-Path $BackendRoot "app"
    if (-not (Test-Path -LiteralPath $appDir)) {
        return $null
    }

    $latest = Get-ChildItem -LiteralPath $appDir -Recurse -File -Filter "*.py" |
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

    if (-not (Test-Path -LiteralPath $ExpectedBackendPython)) {
        return $false
    }

    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $processInfo) {
        return $false
    }

    $expectedPythonPath = (Resolve-Path -LiteralPath $ExpectedBackendPython).Path
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

function Test-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 8
    )

    try {
        $response = Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec
        Write-Host "OK   $Name $($response | ConvertTo-Json -Compress)"
        return $true
    }
    catch {
        Write-Host "FAIL $Name $($_.Exception.Message)"
        return $false
    }
}

function Wait-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{}
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-Endpoint -Name $Name -Uri $Uri -Headers $Headers -TimeoutSec 5) {
            return $true
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Start-BackendIfNeeded {
    Write-Step "检查 FastAPI 后端"
    $expectedVersion = Get-ExpectedBackendVersion
    if (-not $expectedVersion) {
        throw "未能解析后端版本：$BackendVersionFile"
    }

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $health = Get-LocalBackendHealth
        $runningVersion = if ($health) { [string]$health.backend_version } else { "" }
        $loadedCurrentSource = Test-ListenerLoadedCurrentSource -ProcessId $listener.OwningProcess
        $usesExpectedRuntime = Test-ListenerUsesExpectedRuntime -ProcessId $listener.OwningProcess
        if ($health -and $health.status -eq "ok" -and $runningVersion -eq $expectedVersion -and $loadedCurrentSource -and $usesExpectedRuntime) {
            Write-Host "OK   127.0.0.1:$Port 已监听，pid=$($listener.OwningProcess)，backend_version=$runningVersion"
            return
        }

        if (-not (Test-Path -LiteralPath $BackendRestartScript)) {
            throw "127.0.0.1:$Port 已监听但版本不一致，且找不到重启脚本：$BackendRestartScript"
        }

        Write-Host "WARN 127.0.0.1:$Port 已监听但不是当前项目后端运行时，pid=$($listener.OwningProcess)，expected=$expectedVersion running=$runningVersion loaded_current_source=$loadedCurrentSource expected_runtime=$usesExpectedRuntime"
        Write-Host "重启后端以加载当前代码：$BackendRestartScript"
        & $BackendRestartScript -Port $Port
        return
    }

    $task = Get-ScheduledTask -TaskName $BackendTaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "启动计划任务：$BackendTaskName"
        Start-ScheduledTask -TaskName $BackendTaskName
        return
    }

    if (-not (Test-Path -LiteralPath $BackendStartScript)) {
        throw "找不到后端启动脚本：$BackendStartScript"
    }

    Write-Host "未找到后端计划任务，直接启动：$BackendStartScript"
    & $BackendStartScript -Port $Port
}

function Start-TunnelIfNeeded {
    Write-Step "检查 Cloudflare Tunnel"
    $process = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($process) {
        Write-Host "OK   cloudflared 已运行，pid=$($process.Id)"
        return
    }

    $service = Get-Service -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "*cloudflared*" -or $_.DisplayName -like "*cloudflared*"
        } |
        Select-Object -First 1
    if ($service) {
        Write-Host "启动 Windows 服务：$($service.Name)"
        if ($service.Status -ne "Running") {
            Start-Service -Name $service.Name
        }
        return
    }

    $task = Get-ScheduledTask -TaskName $TunnelTaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "启动计划任务：$TunnelTaskName"
        Start-ScheduledTask -TaskName $TunnelTaskName
        return
    }

    Write-Host "WARN 未找到 cloudflared 进程、Windows 服务或计划任务。"
    Write-Host "WARN 如果公网检查失败，请先按 docs\\CLOUDFLARE_TUNNEL.md 安装 Tunnel connector。"
}

Write-Host "小票夹运行保障检查"
Write-Host "项目目录：$ProjectRoot"
Write-Host "公网地址：$BaseUrl"

Start-BackendIfNeeded
Start-TunnelIfNeeded

Write-Step "接口健康检查"
if (-not (Wait-Endpoint -Name "local health " -Uri "http://127.0.0.1:$Port/api/health")) {
    $Failures.Add("本机后端不可用：http://127.0.0.1:$Port/api/health")
}

if (-not (Wait-Endpoint -Name "public health" -Uri "$BaseUrl/api/health")) {
    $Failures.Add("公网入口不可用：$BaseUrl/api/health")
}

$resolvedSessionToken = Resolve-SessionToken
if (-not $SkipPublicAuth -and $resolvedSessionToken.Length -gt 0) {
    if (-not (Wait-Endpoint -Name "public auth  " -Uri "$BaseUrl/api/auth/check" -Headers @{ Authorization = "Bearer $resolvedSessionToken" })) {
        $Failures.Add("公网 session 鉴权检查失败：$BaseUrl/api/auth/check")
    }
}
elseif ($SkipPublicAuth) {
    Write-Host "SKIP public auth：已指定 -SkipPublicAuth。"
}
else {
    Write-Host "SKIP public auth：没有 TICKETBOX_SESSION_TOKEN。"
}

Write-Step "结果"
if ($Failures.Count -gt 0) {
    foreach ($failure in $Failures) {
        Write-Host "FAIL $failure"
    }
    throw "小票夹运行保障检查未通过。"
}

Write-Host "OK   电脑端服务已就绪。手机使用 $BaseUrl 访问即可，不需要和电脑在同一个 Wi-Fi。"
