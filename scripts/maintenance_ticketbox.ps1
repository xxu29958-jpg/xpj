<#
.SYNOPSIS
源码/测试环境的本机维护入口。
.PARAMETER ServerUrl
运行此脚本的电脑上的后端环回地址，默认 http://127.0.0.1:8000。
自定义端口须在源码/测试后端启动前，为该后端进程设置 XPJ_EXTRA_LOOPBACK_HOSTS，
值为与 ServerUrl 精确匹配的主机:端口（不含协议或路径）。例如地址为
http://127.0.0.1:8765 时，在后端启动窗口先设置：
$env:XPJ_EXTRA_LOOPBACK_HOSTS = "127.0.0.1:8765"
再从该窗口按现有方式启动监听此地址的后端；已运行的后端须按原方式重启以继承配置。
只在维护脚本窗口设置变量无效。localhost:8765 等其他环回别名须分别显式列出，逗号分隔。
不支持公网域名或其他电脑的服务地址。管理会话不能放宽本机网络边界。
.DESCRIPTION
仅用于源码/测试环境，不拥有正式安装的数据、备份或恢复 authority。
#>
param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$AdminToken = "",
    [switch]$CleanupConfirmedImages,
    [switch]$CleanupRejectedImages,
    [switch]$CleanupOrphans,
    [switch]$DeleteOrphans,
    [switch]$Vacuum
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$BaseUrl = $ServerUrl.TrimEnd("/")

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Invoke-MaintenancePost {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Query = ""
    )

    if ([string]::IsNullOrWhiteSpace($AdminToken)) {
        throw "没有 admin session token。请传入 -AdminToken，或设置 TICKETBOX_ADMIN_TOKEN。"
    }

    $uri = "$BaseUrl$Path$Query"
    Invoke-RestMethod -Method Post -Uri $uri -Headers @{ Authorization = "Bearer $AdminToken" } -TimeoutSec 60
}

function Vacuum-Database {
    Write-Host "PostgreSQL 由 autovacuum 维护，跳过手动 VACUUM。"
}

if ([string]::IsNullOrWhiteSpace($AdminToken)) {
    $AdminToken = [Environment]::GetEnvironmentVariable("TICKETBOX_ADMIN_TOKEN")
}

$hasAction = $CleanupConfirmedImages -or $CleanupRejectedImages -or $CleanupOrphans -or $Vacuum
if (-not $hasAction) {
    Write-Host "小票夹本机维护脚本（源码/测试环境）"
    Write-Host "请在运行后端的电脑上执行，ServerUrl 仅支持本机环回地址。"
    Write-Host "自定义端口须先在后端启动环境配置精确的 XPJ_EXTRA_LOOPBACK_HOSTS；详见 Get-Help .\scripts\maintenance_ticketbox.ps1 -Parameter ServerUrl。"
    Write-Host "常用："
    Write-Host "  -CleanupConfirmedImages"
    Write-Host "  -CleanupRejectedImages"
    Write-Host "  -CleanupOrphans [-DeleteOrphans]"
    Write-Host "  -Vacuum"
    Write-Host ""
    Write-Host "建议：先确认无需保留待清理的原图，并保持 dry-run 预览。"
    return
}

if ($CleanupConfirmedImages) {
    $result = Invoke-MaintenancePost -Path "/api/maintenance/cleanup-images"
    Write-Host "confirmed 图片清理：扫描 $($result.scanned)，原图 $($result.deleted_images)，缩略图 $($result.deleted_thumbnails)。"
}

if ($CleanupRejectedImages) {
    $result = Invoke-MaintenancePost -Path "/api/maintenance/cleanup-rejected"
    Write-Host "rejected 图片清理：扫描 $($result.scanned)，原图 $($result.deleted_images)，缩略图 $($result.deleted_thumbnails)。"
}

if ($CleanupOrphans) {
    $dryRun = if ($DeleteOrphans) { "false" } else { "true" }
    $result = Invoke-MaintenancePost -Path "/api/maintenance/cleanup-orphans" -Query "?dry_run=$dryRun"
    $mode = if ($result.dry_run) { "dry-run" } else { "delete" }
    Write-Host "孤儿文件清理($mode)：扫描 $($result.scanned_files)，孤儿 $($result.orphan_files)，删除 $($result.deleted_files)，可清理 $(Format-Bytes $result.orphan_bytes)。"
}

if ($Vacuum) {
    Vacuum-Database
}
