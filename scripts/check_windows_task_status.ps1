<#
.SYNOPSIS
查看 Ticketbox Windows 计划任务状态（不打印任何 token / 域名 / 端口）。
#>
param(
    [string[]]$TaskNames = @("TicketboxBackend", "TicketboxCloudflareTunnel", "TicketboxBackup", "TicketboxBoundaryCheck")
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

$TaskSchedulerInfoResults = @(
    0,
    0x41300,
    0x41301,
    0x41302,
    0x41303,
    0x41304,
    0x41305,
    0x41306,
    0x41307,
    0x41308
)

function Convert-TaskResultCode {
    param([object]$Value)
    if ($Value -eq $null -or $Value -eq "") {
        return $null
    }
    $raw = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    $match = [Regex]::Match($raw, "0x[0-9a-fA-F]+|-?\d+")
    if (-not $match.Success) {
        return $null
    }
    $token = $match.Value
    try {
        if ($token.StartsWith("0x", [System.StringComparison]::OrdinalIgnoreCase)) {
            return [Convert]::ToInt32($token, 16)
        }
        return [int]$token
    }
    catch {
        return $null
    }
}

function Test-TaskResultFailure {
    param([object]$LastResult)
    $code = Convert-TaskResultCode -Value $LastResult
    if ($null -eq $code) {
        return $false
    }
    # Task Scheduler 0x413xx values are informational states, not failures.
    # BoundaryCheck still returns 1 on probe failure and remains a failure.
    return -not ($TaskSchedulerInfoResults -contains $code)
}

$failed = @($rows | Where-Object { Test-TaskResultFailure -LastResult $_.LastResult })
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "提示：以下任务上一次运行返回非零结果，请检查任务计划程序中的历史。"
    $failed | Select-Object Task, LastResult, LastRun | Format-Table -AutoSize
    exit 1
}
