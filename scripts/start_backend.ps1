param(
    [int]$Port = 8000,
    [int]$TimeoutSeconds = 45,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$BackendStartScript = Join-Path $BackendRoot "scripts\start_backend.ps1"
$BackendVersionFile = Join-Path $BackendRoot "app\version.py"

function Get-ExpectedBackendVersion {
    if (-not (Test-Path -LiteralPath $BackendVersionFile)) {
        return ""
    }

    $content = Get-Content -LiteralPath $BackendVersionFile -Raw -Encoding UTF8
    $match = [regex]::Match($content, "BACKEND_VERSION\s*=\s*[""']([^""']+)[""']")
    if ($match.Success) {
        return $match.Groups[1].Value
    }

    return ""
}

if (-not (Test-Path -LiteralPath $BackendStartScript)) {
    throw "未找到后端启动脚本：$BackendStartScript"
}

$ExpectedBackendVersion = Get-ExpectedBackendVersion
if (-not $ExpectedBackendVersion) {
    throw "未能解析后端版本：$BackendVersionFile"
}

Write-Host "启动小票夹后端：127.0.0.1:$Port"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $BackendStartScript -Port $Port
if ($LASTEXITCODE -ne 0) {
    throw "后端启动脚本失败。"
}

if ($NoWait) {
    Write-Host "已发起启动，不等待健康检查。"
    exit 0
}

$healthUrl = "http://127.0.0.1:$Port/api/health"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
        if ($response.status -eq "ok") {
            $runningVersion = [string]$response.backend_version
            if ($runningVersion -ne $ExpectedBackendVersion) {
                throw "后端版本不一致：expected=$ExpectedBackendVersion running=$runningVersion"
            }
            Write-Host "OK   后端已就绪：$healthUrl"
            exit 0
        }
    }
    catch {
        if ($_.Exception.Message -like "后端版本不一致*") {
            throw
        }
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "后端启动后没有通过健康检查：$healthUrl"
