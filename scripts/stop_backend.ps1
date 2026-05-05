param(
    [int]$Port = 8000,
    [string]$TaskName = "TicketboxBackend",
    [switch]$SkipTask,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Resolve-Path (Join-Path $ProjectRoot "backend")

function Test-TicketboxBackendProcess {
    param([Parameter(Mandatory = $true)]$ProcessInfo)

    $commandLine = [string]$ProcessInfo.CommandLine
    $executablePath = [string]$ProcessInfo.ExecutablePath
    $backendPath = $BackendRoot.Path
    $isTicketboxUvicornCommand = (
        $commandLine.Contains("uvicorn app.main:app") -and
        $commandLine.Contains("--host 127.0.0.1") -and
        $commandLine.Contains("--port $Port")
    )

    return (
        $commandLine.Contains("uvicorn app.main:app") -and
        (
            $commandLine.StartsWith($backendPath, [System.StringComparison]::OrdinalIgnoreCase) -or
            $commandLine.Contains($backendPath)
        )
    ) -or (
        $executablePath.StartsWith($backendPath, [System.StringComparison]::OrdinalIgnoreCase) -and
        $commandLine.Contains("app.main:app")
    ) -or (
        $isTicketboxUvicornCommand
    )
}

if (-not $SkipTask) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq "Running") {
        Write-Host "停止计划任务实例：$TaskName"
        Stop-ScheduledTask -TaskName $TaskName
    }
}

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -eq 0) {
    Write-Host "OK   127.0.0.1:$Port 没有监听中的后端进程。"
    exit 0
}

foreach ($listener in $listeners) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $processInfo) {
        Write-Host "WARN 找不到监听进程信息，pid=$($listener.OwningProcess)"
        continue
    }

    if (-not (Test-TicketboxBackendProcess -ProcessInfo $processInfo) -and -not $Force) {
        throw "端口 $Port 被非小票夹后端进程占用，拒绝停止。pid=$($listener.OwningProcess)。如确认要停止，请加 -Force。"
    }

    Write-Host "停止后端进程：pid=$($listener.OwningProcess)"
    Stop-Process -Id $listener.OwningProcess -Force
}

Start-Sleep -Seconds 2
$remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($remaining) {
    throw "停止后端后端口仍在监听：127.0.0.1:$Port pid=$($remaining.OwningProcess)"
}

Write-Host "OK   后端已停止：127.0.0.1:$Port"
