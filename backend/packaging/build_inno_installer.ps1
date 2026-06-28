#Requires -Version 5.1
<#
.SYNOPSIS
  Build the Ticketbox Inno Setup installer.

.DESCRIPTION
  Validates the frozen backend, bundled PostgreSQL, Shawl, and installer scripts,
  then invokes ISCC.exe. Use -CheckInputsOnly on machines without Inno Setup.
#>
[CmdletBinding()]
param(
    [string]$InnoCompiler = "",
    [string]$Version = "",
    [switch]$CheckInputsOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")).Path
$IssPath = Join-Path $ScriptDir "ticketbox-installer.iss"
$BackendDist = Join-Path $BackendRoot "dist\ticketbox-backend"
$PgBundle = Join-Path $ScriptDir "vendor\pg"
$ShawlExe = Join-Path $ScriptDir "vendor\shawl\shawl.exe"
$InstallScript = Join-Path $ScriptDir "install_bundled_services.ps1"
$UninstallScript = Join-Path $ScriptDir "uninstall_bundled_services.ps1"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 $Label：$Path"
    }
}

function Assert-Dir([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "缺少 $Label：$Path"
    }
}

function Find-Iscc {
    if ($InnoCompiler.Trim().Length -gt 0) {
        if (-not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
            throw "指定的 ISCC.exe 不存在：$InnoCompiler"
        }
        return (Resolve-Path -LiteralPath $InnoCompiler).Path
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }
    $candidates = @()
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Resolve-Version {
    if ($Version.Trim().Length -gt 0) {
        return $Version
    }
    $versionFile = Join-Path $BackendRoot "app\version.py"
    $content = Get-Content -LiteralPath $versionFile -Encoding UTF8 -Raw
    $m = [regex]::Match($content, 'BACKEND_VERSION\s*=\s*"([^"]+)"')
    if (-not $m.Success) {
        throw "无法从 app\version.py 读取 BACKEND_VERSION。"
    }
    return $m.Groups[1].Value
}

function Resolve-VersionInfoVersion([string]$Value) {
    $m = [regex]::Match($Value, '^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $m.Success) {
        return "0.0.0.0"
    }

    $parts = @($m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value)
    if ($m.Groups[4].Success) {
        $parts += $m.Groups[4].Value
    }
    else {
        $parts += "0"
    }
    return ($parts -join ".")
}

Write-Step "校验 Inno 安装器输入"
Assert-File $IssPath "Inno 脚本"
Assert-Dir $BackendDist "冻结后端 onedir"
Assert-File (Join-Path $BackendDist "ticketbox-backend.exe") "ticketbox-backend.exe"
Assert-Dir $PgBundle "捆绑 PostgreSQL"
foreach ($name in @("initdb.exe", "postgres.exe", "pg_ctl.exe", "psql.exe", "pg_dump.exe", "pg_restore.exe", "pg_isready.exe")) {
    Assert-File (Join-Path $PgBundle "bin\$name") "PG $name"
}
Assert-File $ShawlExe "shawl.exe"
Assert-File $InstallScript "install_bundled_services.ps1"
Assert-File $UninstallScript "uninstall_bundled_services.ps1"
Write-Ok "输入齐备。"

$resolvedVersion = Resolve-Version
Write-Ok "安装包版本：$resolvedVersion"
$resolvedVersionInfo = Resolve-VersionInfoVersion $resolvedVersion
Write-Ok "Windows 文件版本：$resolvedVersionInfo"

if ($CheckInputsOnly) {
    Write-Host ""
    Write-Host "CheckInputsOnly OK。" -ForegroundColor Green
    return
}

$iscc = Find-Iscc
if (-not $iscc) {
    throw "未找到 ISCC.exe。请安装 Inno Setup 6（JRSoftware.InnoSetup），或用 -InnoCompiler 指定 ISCC.exe 路径。"
}

$outDir = Join-Path $BackendRoot "dist\installer"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Write-Step "调用 ISCC.exe"
& $iscc "/DAppVersion=$resolvedVersion" "/DAppVersionInfo=$resolvedVersionInfo" $IssPath
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe 编译失败（exit=$LASTEXITCODE）。"
}
Write-Ok "安装包输出目录：$outDir"
