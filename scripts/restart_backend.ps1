<#
.SYNOPSIS
重启 Ticketbox 后端：先停止本机后端进程，再启动新实例。

不会暴露 token、端口或域名。日志在 backend\logs\ 下。
#>
param(
    [int]$Port = 8000,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$StopScript = Join-Path $ProjectRoot "scripts\stop_backend.ps1"
$StartScript = Join-Path $ProjectRoot "scripts\start_backend.ps1"

if (-not (Test-Path -LiteralPath $StopScript)) {
    throw "未找到 stop_backend.ps1：$StopScript"
}
if (-not (Test-Path -LiteralPath $StartScript)) {
    throw "未找到 start_backend.ps1：$StartScript"
}

Write-Host "停止后端 (port $Port)..."
$stopArgs = @{ Port = $Port }
if ($Force) { $stopArgs["Force"] = $true }
& $StopScript @stopArgs

Start-Sleep -Seconds 1

Write-Host "启动后端..."
& $StartScript -Port $Port

Write-Host "完成。可执行 scripts\check_service_status.ps1 验证状态。"
