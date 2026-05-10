<#
.SYNOPSIS
    Android pairing + recovery + offline E2E helper for v0.3.2 self-use validation.

.DESCRIPTION
    本脚本用于把 v0.3.x 的实机绑定/恢复链路跑成可重复的 best-effort 流程：

      1. 检查 adb 设备已 authorized
      2. 校验 APK 是否存在
      3. 安装/重装 APK（保留数据）
      4. 启动 App
      5. 可选：尝试通过 ADB input 输入 6 位绑定码
      6. 抓取截图与 logcat 到 artifacts/ 目录

    本脚本不携带任何真实绑定码、token 或域名常量；所有敏感参数走命令行入参。
    UI 自动点击/输入是 best-effort，Compose 导航有时会忽略 ADB tap，
    失败时按 docs\REAL_DEVICE_RUNBOOK.md 与 docs\V0_3_2_SELFUSE_CHECKLIST.md 人工点按。

    截图与 logcat 会写入 artifacts\ 目录（已在 .gitignore 中，不会进入仓库）。

.PARAMETER DeviceSerial
    adb 设备序列号，必填。例如：c16cd054。

.PARAMETER PackageName
    Android 包名，默认 com.ticketbox。

.PARAMETER ApkPath
    grayDebug APK 路径，默认 android\app\build\outputs\apk\gray\debug\app-gray-debug.apk。

.PARAMETER PairingCode
    可选，6 位绑定码。提供时脚本会尝试自动 input；不提供则只跑构建/启动/截图。

.PARAMETER ServerUrl
    可选，仅用于在最终摘要里提示用户检查 Cloudflare/health。

.PARAMETER ArtifactsDir
    输出目录，默认 artifacts。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_android_pairing_e2e.ps1 -DeviceSerial c16cd054

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_android_pairing_e2e.ps1 `
        -DeviceSerial c16cd054 -PairingCode 123456 -ServerUrl https://api.example.com

.NOTES
    本脚本不会：
      - 出厂重置设备
      - 清空相册 / 下载 / 外部存储
      - 提交 artifacts 到 git
      - 打印任何 token 或 secret
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $DeviceSerial,

    [string] $PackageName = "com.ticketbox",

    [string] $ApkPath = "android\app\build\outputs\apk\gray\debug\app-gray-debug.apk",

    [ValidatePattern('^$|^\d{6}$')]
    [string] $PairingCode = "",

    [string] $ServerUrl = "",

    [string] $ArtifactsDir = "artifacts"
)

$ErrorActionPreference = "Stop"

function Write-Step([string] $Msg) {
    Write-Host ""
    Write-Host "=== $Msg ===" -ForegroundColor Cyan
}

# 解析仓库根
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$adb = Join-Path $repoRoot ".toolchains\android-sdk\platform-tools\adb.exe"
if (-not (Test-Path $adb)) {
    $adbCmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($adbCmd) {
        $adb = $adbCmd.Source
    } else {
        throw "未找到 adb.exe，请确认 Android SDK 路径。"
    }
}

if (-not (Test-Path $ArtifactsDir)) {
    New-Item -ItemType Directory -Path $ArtifactsDir | Out-Null
}

Write-Step "1. 检查设备"
$devices = & $adb devices | Select-Object -Skip 1
$matched = $devices | Where-Object { $_ -match "^$DeviceSerial\s+device" }
if (-not $matched) {
    Write-Host "adb devices:`n$($devices -join "`n")" -ForegroundColor Yellow
    throw "设备 $DeviceSerial 未授权或未连接。请先在手机上确认 USB 调试。"
}
Write-Host "OK: $DeviceSerial 已 authorized"

Write-Step "2. 校验 APK"
if (-not (Test-Path $ApkPath)) {
    throw "APK 不存在：$ApkPath。请先执行 .\android\gradlew.bat :app:assembleGrayDebug。"
}
Write-Host "OK: $ApkPath"

Write-Step "3. 安装 APK（保留数据）"
& $adb -s $DeviceSerial install -r -d $ApkPath
if ($LASTEXITCODE -ne 0) { throw "adb install 失败。" }

Write-Step "4. 启动 App"
& $adb -s $DeviceSerial shell monkey -p $PackageName -c android.intent.category.LAUNCHER 1 | Out-Null
Start-Sleep -Seconds 3

Write-Step "5. 抓启动截图"
$shot1 = Join-Path $ArtifactsDir "e2e_launch.png"
& $adb -s $DeviceSerial shell screencap -p /sdcard/e2e_launch.png | Out-Null
& $adb -s $DeviceSerial pull /sdcard/e2e_launch.png $shot1 | Out-Null
Write-Host "OK: $shot1"

if ($PairingCode) {
    Write-Step "6. 尝试自动输入绑定码（best-effort）"
    Write-Host "若未跳到绑定页，请按 runbook 人工点按「绑定服务器」。"
    # 假定输入框已聚焦或包含 IME 自动展开。最稳妥还是人工点击。
    & $adb -s $DeviceSerial shell input text $PairingCode | Out-Null
    Start-Sleep -Seconds 2
    $shot2 = Join-Path $ArtifactsDir "e2e_pairing_input.png"
    & $adb -s $DeviceSerial shell screencap -p /sdcard/e2e_pairing.png | Out-Null
    & $adb -s $DeviceSerial pull /sdcard/e2e_pairing.png $shot2 | Out-Null
    Write-Host "OK: $shot2"
} else {
    Write-Host "未提供 PairingCode，跳过自动输入。"
}

Write-Step "7. 抓 logcat 片段"
$logPath = Join-Path $ArtifactsDir "e2e_logcat.txt"
& $adb -s $DeviceSerial logcat -d -t 500 *:W | Out-File -FilePath $logPath -Encoding utf8
Write-Host "OK: $logPath"

Write-Step "完成"
Write-Host "Device      : $DeviceSerial"
Write-Host "Package     : $PackageName"
Write-Host "Apk         : $ApkPath"
Write-Host "Artifacts   : $ArtifactsDir"
if ($ServerUrl) {
    Write-Host "ServerUrl   : $ServerUrl  （请人工核 /api/health）"
}
Write-Host ""
Write-Host "下一步（人工）：" -ForegroundColor Yellow
Write-Host "  · 在 App 内确认绑定状态、已确认账单恢复、飞行模式下账本可读。"
Write-Host "  · 详细步骤见 docs\V0_3_2_SELFUSE_CHECKLIST.md。"
Write-Host "  · 不要把 artifacts\ 内的截图/logcat 提交进 git。"
