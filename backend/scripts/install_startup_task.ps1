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

$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" -Port $Port"

schtasks.exe /Create /TN $TaskName /TR $taskCommand /SC ONLOGON /F | Out-Host
Write-Host "已创建任务计划：$TaskName"
Write-Host "下次登录 Windows 时会启动小票夹后端。"
