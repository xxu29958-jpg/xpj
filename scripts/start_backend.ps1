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

# 注意：不要从 /api/health 读 backend_version 做比对。该端点按 SECURITY.md /
# ENGINEERING_RULES §14 匿名只返回 {status:ok}（version 走需 session 的
# /api/status/private），字段永远为空 → 比对永远失败 → 登录自启任务每次
# result=1 且进程树被任务引擎收割（2026-06-07 起生产静默停机 4 天的外层根因；
# backend\scripts\start_backend.ps1 的 listener 检查早已为同一坑修过——见其
# codex P2 #12 注释——本包装层是漏网残留）。代码新旧由内层脚本的
# source-stamp + runtime 双证保障，这里只确认进程就绪。
$healthUrl = "http://127.0.0.1:$Port/api/health"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
        if ($response.status -eq "ok") {
            Write-Host "OK   后端已就绪：$healthUrl（expected_version=$ExpectedBackendVersion）"
            exit 0
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $deadline)

throw "后端启动后没有通过健康检查：$healthUrl"
