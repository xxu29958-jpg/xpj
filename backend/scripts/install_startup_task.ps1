param(
    [string]$TaskName = "TicketboxBackend",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$StartScript = Join-Path $BackendRoot "scripts\start_backend.ps1"

if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "Start script not found: $StartScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" -Port $Port"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Start 小票夹 FastAPI backend on 127.0.0.1:$Port" `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($task.TaskName -ne $TaskName) {
    throw "任务计划创建后未找到：$TaskName"
}

Write-Host "已创建任务计划：$TaskName"
Write-Host "下次登录 Windows 时会启动小票夹后端。"
