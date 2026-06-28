#Requires -Version 5.1
<#
.SYNOPSIS
  Stop and unregister Ticketbox bundled Windows services.

.DESCRIPTION
  Inno calls this during uninstall. By default it preserves ProgramData so
  uninstall/reinstall is reversible. Passing -DeleteData explicitly removes the
  configured data root after verifying the target path is safe.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$DataRoot = "",
    [string]$PgServiceName = "TicketboxPg",
    [string]$BackendServiceName = "TicketboxBackend",
    [switch]$DeleteData
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($InstallDir.Trim().Length -eq 0) {
    $InstallDir = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
}
if ($DataRoot.Trim().Length -eq 0) {
    $regPath = "HKLM:\Software\Ticketbox"
    if (Test-Path -LiteralPath $regPath) {
        $value = (Get-ItemProperty -LiteralPath $regPath -Name "DataRoot" -ErrorAction SilentlyContinue).DataRoot
        if ($value) {
            $DataRoot = $value
        }
    }
}
if ($DataRoot.Trim().Length -eq 0) {
    $DataRoot = "C:\ProgramData\Ticketbox"
}

$PgBin = Join-Path $InstallDir "pg\bin"
$PgData = Join-Path $DataRoot "pgdata"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn2([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Assert-Admin {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltinRole]::Administrator
    )
    if (-not $admin) {
        throw "需要管理员权限运行卸载脚本。"
    }
}

function Service-Exists([string]$Name) {
    return $null -ne (Get-Service -Name $Name -ErrorAction SilentlyContinue)
}

function Invoke-ScChecked([string[]]$ScArgs) {
    $out = & sc.exe @ScArgs 2>&1
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {
        throw "sc.exe $($ScArgs -join ' ') 失败（exit=$rc）：`n$out"
    }
    return ($out | Out-String).Trim()
}

function Stop-ServiceIfExists([string]$Name) {
    if (-not (Service-Exists $Name)) {
        return
    }
    try {
        Stop-Service -Name $Name -Force -ErrorAction Stop
    }
    catch {
        Write-Warn2 "停止服务 $Name 失败：$($_.Exception.Message)"
    }
}

function Remove-ServiceIfExists([string]$Name) {
    if (-not (Service-Exists $Name)) {
        return
    }
    Stop-ServiceIfExists $Name
    Invoke-ScChecked @("delete", $Name) | Out-Null
}

function Stop-OurPg {
    Stop-ServiceIfExists $PgServiceName
    $pgctl = Join-Path $PgBin "pg_ctl.exe"
    if ((Test-Path -LiteralPath $pgctl) -and (Test-Path -LiteralPath (Join-Path $PgData "postmaster.pid"))) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $pgctl -D $PgData -m fast -w -t 30 stop 2>$null | Out-Null
        $ErrorActionPreference = $prev
    }
}

function Assert-SafeDeleteRoot([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $common = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath("CommonApplicationData"))
    $programFiles = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath("ProgramFiles"))
    if ($full.Length -lt 8 -or $full -match '^[A-Za-z]:\\?$') {
        throw "拒绝删除危险路径：$full"
    }
    if ($full.StartsWith($programFiles, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝把 Program Files 当作数据目录删除：$full"
    }
    if (-not $full.StartsWith($common, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Warn2 "将删除显式配置的数据目录：$full"
    }
    return $full
}

Write-Host "=== 小票夹服务卸载 ===" -ForegroundColor Yellow
Assert-Admin

Write-Step "停止并删除后端服务"
Remove-ServiceIfExists $BackendServiceName
Write-Ok "后端服务已处理。"

Write-Step "停止并删除 PostgreSQL 服务"
Stop-OurPg
if (Service-Exists $PgServiceName) {
    Remove-ServiceIfExists $PgServiceName
}
Write-Ok "PG 服务已处理。"

if ($DeleteData) {
    $safeRoot = Assert-SafeDeleteRoot $DataRoot
    if (Test-Path -LiteralPath $safeRoot) {
        Write-Step "删除数据目录 $safeRoot"
        Start-Sleep -Milliseconds 800
        Remove-Item -LiteralPath $safeRoot -Recurse -Force
        Write-Ok "数据目录已删除。"
    }
}
else {
    Write-Step "保留数据目录"
    Write-Host "    $DataRoot"
}

Write-Host ""
Write-Host "=== 卸载脚本完成 ===" -ForegroundColor Green
