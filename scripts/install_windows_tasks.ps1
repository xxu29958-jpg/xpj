param(
    [int]$Port = 8000,
    [string]$BackendTaskName = "TicketboxBackend",
    [string]$BoundaryTaskName = "TicketboxBoundaryCheck",
    [string]$BoundaryCheckTime = "04:00",
    [int]$BoundaryLogRetentionDays = 14,
    [ValidateRange(1, 1440)][int]$BoundaryTaskExecutionTimeLimitMinutes = 15,
    [switch]$SkipBoundaryCheck,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "assert_external_runtime.ps1")
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$StartBackendScript = Join-Path $ProjectRoot "scripts\start_backend.ps1"
$BoundaryCheckScript = Join-Path $ProjectRoot "scripts\scheduled_public_boundary_check.ps1"

function New-TaskSettings([TimeSpan]$ExecutionTimeLimit) {
    New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit $ExecutionTimeLimit `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
}

function Register-LogonTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$Execute,
        [Parameter(Mandatory = $true)][string]$Argument,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $action = New-ScheduledTaskAction -Execute $Execute -Argument $Argument
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings (New-TaskSettings -ExecutionTimeLimit (New-TimeSpan -Hours 0)) `
        -Description $Description `
        -Force | Out-Null
    Write-Host "OK   已创建任务计划：$TaskName"
}

function Register-DailyTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$Execute,
        [Parameter(Mandatory = $true)][string]$Argument,
        [Parameter(Mandatory = $true)][datetime]$At,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][TimeSpan]$ExecutionTimeLimit
    )

    $action = New-ScheduledTaskAction -Execute $Execute -Argument $Argument
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings (New-TaskSettings -ExecutionTimeLimit $ExecutionTimeLimit) `
        -Description $Description `
        -Force | Out-Null
    Write-Host "OK   已创建每日任务：$TaskName ($($At.ToString('HH:mm')))"
}

function Resolve-BoundaryCheckTime {
    try {
        return [datetime]::ParseExact($BoundaryCheckTime, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        throw "公网边界检查时间格式不正确：$BoundaryCheckTime。请使用 HH:mm，例如 04:00。"
    }
}

if (-not (Test-Path -LiteralPath $StartBackendScript)) {
    throw "未找到后端统一启动脚本：$StartBackendScript"
}
if (-not (Test-Path -LiteralPath $BoundaryCheckScript)) {
    throw "未找到公网边界检查脚本：$BoundaryCheckScript"
}

Write-Host "安装小票夹 Windows 登录自启任务"
Write-Host "项目目录：$ProjectRoot"

Register-LogonTask `
    -TaskName $BackendTaskName `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$StartBackendScript`" -Port $Port" `
    -Description "Start 小票夹 FastAPI backend on 127.0.0.1:$Port"

Write-Host "公网连接由小票夹管理器设置；本脚本只保留外部源码后端和边界检查任务。"

if (-not $SkipBoundaryCheck) {
    Register-DailyTask `
        -TaskName $BoundaryTaskName `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BoundaryCheckScript`" -LogRetentionDays $BoundaryLogRetentionDays" `
        -At (Resolve-BoundaryCheckTime) `
        -Description "Daily public-boundary probe for 小票夹 (check_public_boundary.ps1)" `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $BoundaryTaskExecutionTimeLimitMinutes)
}
else {
    Write-Host "SKIP 公网边界检查任务：已指定 -SkipBoundaryCheck。"
}

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $BackendTaskName
    Write-Host "OK   已启动后端计划任务：$BackendTaskName"

}

Write-Host "完成。可运行 scripts\check_service_status.ps1 或 scripts\ensure_ticketbox_runtime.ps1 检查状态。"
