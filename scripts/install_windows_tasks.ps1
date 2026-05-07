param(
    [int]$Port = 8000,
    [string]$BackendTaskName = "TicketboxBackend",
    [string]$TunnelTaskName = "TicketboxCloudflareTunnel",
    [string]$BackupTaskName = "TicketboxBackup",
    [string]$BackupTime = "03:30",
    [string]$CloudflaredPath = "",
    [string]$CloudflaredArguments = "",
    [switch]$SkipTunnel,
    [switch]$SkipBackup,
    [switch]$ForceTunnelTask,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$StartBackendScript = Join-Path $ProjectRoot "scripts\start_backend.ps1"
$MaintenanceScript = Join-Path $ProjectRoot "scripts\maintenance_ticketbox.ps1"

function New-TaskSettings {
    New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
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
        -Settings (New-TaskSettings) `
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
        [Parameter(Mandatory = $true)][string]$Description
    )

    $action = New-ScheduledTaskAction -Execute $Execute -Argument $Argument
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings (New-TaskSettings) `
        -Description $Description `
        -Force | Out-Null
    Write-Host "OK   已创建每日任务：$TaskName ($($At.ToString('HH:mm')))"
}

function Resolve-BackupTime {
    try {
        return [datetime]::ParseExact($BackupTime, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        throw "备份时间格式不正确：$BackupTime。请使用 HH:mm，例如 03:30。"
    }
}

function Resolve-CloudflaredExecutable {
    if ($CloudflaredPath.Trim().Length -gt 0) {
        if (-not (Test-Path -LiteralPath $CloudflaredPath)) {
            throw "指定的 cloudflared 不存在：$CloudflaredPath"
        }
        return (Resolve-Path -LiteralPath $CloudflaredPath).Path
    }

    $running = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "cloudflared*.exe" -and $_.ExecutablePath } |
        Select-Object -First 1
    if ($running) {
        return $running.ExecutablePath
    }

    $command = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\cloudflared"
    $candidate = Get-ChildItem -LiteralPath $localPrograms -Filter "cloudflared*.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }

    return ""
}

function Resolve-CloudflaredArguments {
    param([Parameter(Mandatory = $true)][string]$Executable)

    if ($CloudflaredArguments.Trim().Length -gt 0) {
        return $CloudflaredArguments.Trim()
    }

    $running = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -like "cloudflared*.exe" -and
            $_.ExecutablePath -and
            $_.ExecutablePath.Equals($Executable, [System.StringComparison]::OrdinalIgnoreCase) -and
            $_.CommandLine
        } |
        Select-Object -First 1
    if (-not $running) {
        return ""
    }

    $line = [string]$running.CommandLine
    $quoted = '"' + $Executable + '"'
    if ($line.StartsWith($quoted, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $line.Substring($quoted.Length).Trim()
    }
    if ($line.StartsWith($Executable, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $line.Substring($Executable.Length).Trim()
    }
    return ""
}

if (-not (Test-Path -LiteralPath $StartBackendScript)) {
    throw "未找到后端统一启动脚本：$StartBackendScript"
}
if (-not (Test-Path -LiteralPath $MaintenanceScript)) {
    throw "未找到维护脚本：$MaintenanceScript"
}

Write-Host "安装小票夹 Windows 登录自启任务"
Write-Host "项目目录：$ProjectRoot"

Register-LogonTask `
    -TaskName $BackendTaskName `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$StartBackendScript`" -Port $Port" `
    -Description "Start 小票夹 FastAPI backend on 127.0.0.1:$Port"

if (-not $SkipTunnel) {
    $service = Get-Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "*cloudflared*" -or $_.DisplayName -like "*cloudflared*" } |
        Select-Object -First 1
    if ($service -and -not $ForceTunnelTask) {
        Write-Host "OK   已发现 cloudflared Windows 服务：$($service.Name)。不重复创建 Tunnel 计划任务。"
        if ($service.Status -ne "Running" -and -not $NoStart) {
            try {
                Start-Service -Name $service.Name
                Write-Host "OK   已启动 cloudflared 服务：$($service.Name)"
            }
            catch {
                Write-Warning "cloudflared 服务存在但启动失败：$($_.Exception.Message)"
            }
        }
    }
    else {
        $existingTunnelTask = Get-ScheduledTask -TaskName $TunnelTaskName -ErrorAction SilentlyContinue
        if ($existingTunnelTask -and -not $ForceTunnelTask) {
            Write-Host "OK   已发现 Tunnel 计划任务：$TunnelTaskName。不重复覆盖。"
        }
        else {
            $cloudflared = Resolve-CloudflaredExecutable
            if ($cloudflared.Trim().Length -eq 0) {
                throw "未找到 cloudflared.exe。已创建后端任务；Tunnel 任务请安装 cloudflared 后重试，或加 -SkipTunnel。"
            }
            $cloudflaredArgs = Resolve-CloudflaredArguments -Executable $cloudflared
            if ($cloudflaredArgs.Trim().Length -eq 0) {
                throw "未能推断 cloudflared 启动参数。请传入 -CloudflaredArguments，例如 'tunnel run <你的Tunnel名>'，或加 -SkipTunnel。"
            }
            Register-LogonTask `
                -TaskName $TunnelTaskName `
                -Execute $cloudflared `
                -Argument $cloudflaredArgs `
                -Description "Start Cloudflare Tunnel for 小票夹"
        }
    }
}
else {
    Write-Host "SKIP Tunnel 任务：已指定 -SkipTunnel。"
}

if (-not $SkipBackup) {
    Register-DailyTask `
        -TaskName $BackupTaskName `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$MaintenanceScript`" -Backup" `
        -At (Resolve-BackupTime) `
        -Description "Daily SQLite backup for 小票夹"
}
else {
    Write-Host "SKIP 备份任务：已指定 -SkipBackup。"
}

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $BackendTaskName
    Write-Host "OK   已启动后端计划任务：$BackendTaskName"
    if ((Get-ScheduledTask -TaskName $TunnelTaskName -ErrorAction SilentlyContinue) -and -not $SkipTunnel) {
        $runningCloudflared = Get-Process -Name "cloudflared*" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($runningCloudflared) {
            Write-Host "OK   cloudflared 已在运行，不重复启动 Tunnel 计划任务。"
        }
        else {
            Start-ScheduledTask -TaskName $TunnelTaskName
            Write-Host "OK   已启动 Tunnel 计划任务：$TunnelTaskName"
        }
    }
}

Write-Host "完成。可运行 scripts\check_service_status.ps1 或 scripts\ensure_ticketbox_runtime.ps1 检查状态。"
