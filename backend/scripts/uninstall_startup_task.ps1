param(
    [string]$TaskName = "TicketboxBackend"
)

$ErrorActionPreference = "Stop"

schtasks.exe /Delete /TN $TaskName /F | Out-Host
Write-Host "已删除任务计划：$TaskName"
