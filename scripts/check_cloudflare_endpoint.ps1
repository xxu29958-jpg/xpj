param(
    [Parameter(Mandatory = $false)]
    [string]$ServerUrl = "https://api.example.com",
    [switch]$SkipUpload,
    [switch]$AllowHttp
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PreflightScript = Join-Path $ProjectRoot "scripts\real_device_preflight.ps1"

if (-not (Test-Path -LiteralPath $PreflightScript)) {
    throw "未找到预检脚本：$PreflightScript"
}

$baseUrl = $ServerUrl.TrimEnd("/")
if (-not $AllowHttp -and -not $baseUrl.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Cloudflare Tunnel 公网入口应使用 HTTPS。开发临时 HTTP 检查请加 -AllowHttp。"
}

$preflightArgs = @(
    "-ServerUrl", $baseUrl,
    "-SkipDevice"
)
if ($SkipUpload) {
    $preflightArgs += "-SkipUpload"
}

Write-Host "检查 Cloudflare Tunnel 公网入口：$baseUrl"
& powershell -ExecutionPolicy Bypass -File $PreflightScript @preflightArgs
if ($LASTEXITCODE -ne 0) {
    throw "Cloudflare Tunnel 公网入口检查失败。"
}

Write-Host "Cloudflare Tunnel 公网入口检查完成。"
