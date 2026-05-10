<#
.SYNOPSIS
查看 Ticketbox Windows 计划任务状态（不打印任何 token / 域名 / 端口）。
#>
param(
    [string[]]$TaskNames = @("TicketboxBackend", "TicketboxCloudflareTunnel", "TicketboxBackup")
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$rows = @()
foreach ($name in $TaskNames) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        $rows += [pscustomobject]@{
            Task = $name
            Registered = $false
            State = "(未注册)"
            LastRun = ""
            LastResult = ""
            NextRun = ""
        }
        continue
    }
    $info = Get-ScheduledTaskInfo -TaskName $name -ErrorAction SilentlyContinue
    $rows += [pscustomobject]@{
        Task = $name
        Registered = $true
        State = [string]$task.State
        LastRun = if ($info) { $info.LastRunTime } else { "" }
        LastResult = if ($info) { $info.LastTaskResult } else { "" }
        NextRun = if ($info) { $info.NextRunTime } else { "" }
    }
}

$rows | Format-Table -AutoSize

$missing = @($rows | Where-Object { -not $_.Registered })
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "提示：以上任务未注册。请运行 scripts\install_windows_tasks.ps1。"
    exit 1
}

$failed = @($rows | Where-Object { $_.LastResult -ne 0 -and $_.LastResult -ne $null -and $_.LastResult -ne "" })
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "提示：以下任务上一次运行返回非零结果，请检查任务计划程序中的历史。"
    $failed | Select-Object Task, LastResult, LastRun | Format-Table -AutoSize
}
