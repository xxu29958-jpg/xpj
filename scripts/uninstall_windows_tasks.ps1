param(
    [string]$BackendTaskName = "TicketboxBackend",
    [string]$TunnelTaskName = "TicketboxCloudflareTunnel",
    [string]$BackupTaskName = "TicketboxBackup",
    [switch]$SkipBackend,
    [switch]$SkipTunnel,
    [switch]$SkipBackup,
    [switch]$StopRunning
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Remove-TaskIfExists {
    param([Parameter(Mandatory = $true)][string]$TaskName)

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "任务计划不存在：$TaskName"
        return
    }
    if ($StopRunning -and $task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Host "已停止任务实例：$TaskName"
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已删除任务计划：$TaskName"
}

if (-not $SkipBackend) {
    Remove-TaskIfExists -TaskName $BackendTaskName
}
if (-not $SkipTunnel) {
    Remove-TaskIfExists -TaskName $TunnelTaskName
}
if (-not $SkipBackup) {
    Remove-TaskIfExists -TaskName $BackupTaskName
}
