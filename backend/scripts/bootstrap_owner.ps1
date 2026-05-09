param(
    [string]$AccountName = "我",
    [string]$LedgerName = "我的小票夹",
    [string]$DeviceName = "Windows 后端",
    [string]$DefaultTimezone = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "未找到后端虚拟环境。请先运行 backend\setup.bat -Dev。"
}

$Arguments = @(
    "scripts\bootstrap_owner.py",
    "--account-name", $AccountName,
    "--ledger-name", $LedgerName,
    "--device-name", $DeviceName
)
if ($DefaultTimezone.Trim().Length -gt 0) {
    $Arguments += @("--default-timezone", $DefaultTimezone)
}

Push-Location $BackendRoot
try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Bootstrap owner failed."
    }
}
finally {
    Pop-Location
}
