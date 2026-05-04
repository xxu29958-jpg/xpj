param(
    [string]$TaskName = "TicketboxBackend"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已删除任务计划：$TaskName"
}
else {
    Write-Host "任务计划不存在：$TaskName"
}
