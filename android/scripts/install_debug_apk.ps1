param(
    [ValidateSet("gray", "internal")]
    [string]$Flavor = "gray",
    [switch]$Build,
    [switch]$Launch,
    [switch]$ReverseBackend,
    [switch]$DebugBind,
    [switch]$ClearData,
    [switch]$ListDevices,
    [string]$Serial = "",
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$SessionToken = "",
    [string]$Adb = "",
    [string]$ApkPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$AndroidRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ProjectRoot = Resolve-Path (Join-Path $AndroidRoot "..")
$PackageName = if ($Flavor -eq "internal") { "com.ticketbox.internal" } else { "com.ticketbox" }
$DefaultApk = Join-Path $AndroidRoot "app\build\outputs\apk\$Flavor\debug\app-$Flavor-debug.apk"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$WorkingDirectory = $AndroidRoot
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败：$FilePath $($Arguments -join ' ')"
    }
}

function Resolve-Adb {
    if ($Adb.Trim().Length -gt 0) {
        if (-not (Test-Path -LiteralPath $Adb)) {
            throw "指定的 adb 不存在：$Adb"
        }
        return (Resolve-Path -LiteralPath $Adb).Path
    }

    $candidates = @()
    if ($env:ANDROID_HOME) {
        $candidates += Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
    }
    if ($env:ANDROID_SDK_ROOT) {
        $candidates += Join-Path $env:ANDROID_SDK_ROOT "platform-tools\adb.exe"
    }
    $candidates += Join-Path $ProjectRoot ".toolchains\android-sdk\platform-tools\adb.exe"

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $command = Get-Command adb -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    throw "未找到 adb。请安装 Android SDK platform-tools，或用 -Adb 指定 adb.exe。"
}

function Ensure-LocalAndroidEnvironment {
    $localSdk = Join-Path $ProjectRoot ".toolchains\android-sdk"
    if (-not $env:ANDROID_HOME -and (Test-Path -LiteralPath $localSdk)) {
        $env:ANDROID_HOME = (Resolve-Path -LiteralPath $localSdk).Path
    }

    $adoptiumRoot = "C:\Program Files\Eclipse Adoptium"
    if (-not $env:JAVA_HOME -and (Test-Path -LiteralPath $adoptiumRoot)) {
        $jdk = Get-ChildItem -LiteralPath $adoptiumRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "bin\java.exe") } |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($jdk) {
            $env:JAVA_HOME = $jdk.FullName
        }
    }

    $localJava = Join-Path $env:LOCALAPPDATA "Programs\Kimi\runtime"
    if (-not $env:JAVA_HOME -and (Test-Path -LiteralPath (Join-Path $localJava "bin\java.exe"))) {
        $env:JAVA_HOME = $localJava
    }

    if ($env:ANDROID_HOME) {
        $platformTools = Join-Path $env:ANDROID_HOME "platform-tools"
        if (Test-Path -LiteralPath $platformTools) {
            $env:PATH = "$platformTools;$env:PATH"
        }
    }
    if ($env:JAVA_HOME) {
        $env:PATH = "$(Join-Path $env:JAVA_HOME "bin");$env:PATH"
    }
}

function Get-DeviceRows {
    param([string]$AdbPath)

    $output = & $AdbPath devices
    if ($LASTEXITCODE -ne 0) {
        throw "adb devices 执行失败。"
    }
    return $output | Select-Object -Skip 1 | Where-Object { $_.Trim().Length -gt 0 }
}

function Select-DeviceSerial {
    param(
        [string]$AdbPath,
        [string]$RequestedSerial
    )

    $rows = @(Get-DeviceRows -AdbPath $AdbPath)
    if ($ListDevices) {
        if ($rows.Count -eq 0) {
            Write-Host "未发现设备。"
        }
        else {
            $rows | ForEach-Object { Write-Host $_ }
        }
        exit 0
    }

    $ready = @()
    $blocked = @()
    foreach ($row in $rows) {
        $parts = $row -split "\s+"
        if ($parts.Count -lt 2) {
            continue
        }
        if ($parts[1] -eq "device") {
            $ready += $parts[0]
        }
        else {
            $blocked += $row
        }
    }

    if ($RequestedSerial.Trim().Length -gt 0) {
        if ($ready -notcontains $RequestedSerial) {
            throw "指定设备未就绪：$RequestedSerial。请确认 USB 调试授权。"
        }
        return $RequestedSerial
    }

    if ($ready.Count -eq 1) {
        return $ready[0]
    }
    if ($ready.Count -gt 1) {
        throw "发现多个设备，请使用 -Serial 指定：$($ready -join ', ')"
    }
    if ($blocked.Count -gt 0) {
        throw "设备未就绪：$($blocked -join '; ')。请在手机上允许 USB 调试。"
    }

    throw "未发现 Android 设备。请连接手机、打开开发者选项和 USB 调试。"
}

Set-Location $AndroidRoot
Ensure-LocalAndroidEnvironment

if ($Build) {
    $variant = "$($Flavor.Substring(0, 1).ToUpperInvariant())$($Flavor.Substring(1))Debug"
    Write-Host "开始构建 $Flavor debug APK..."
    Invoke-Checked -FilePath (Join-Path $AndroidRoot "gradlew.bat") -Arguments @("--no-daemon", ":app:assemble$variant")
}

$resolvedApk = if ($ApkPath.Trim().Length -gt 0) { $ApkPath } else { $DefaultApk }
if (-not (Test-Path -LiteralPath $resolvedApk)) {
    $variant = "$($Flavor.Substring(0, 1).ToUpperInvariant())$($Flavor.Substring(1))Debug"
    throw "APK 不存在：$resolvedApk。请先运行 .\gradlew.bat --no-daemon :app:assemble$variant，或使用 -Build。"
}
$resolvedApk = (Resolve-Path -LiteralPath $resolvedApk).Path

$adbPath = Resolve-Adb
Write-Host "adb: $adbPath"
Write-Host "apk: $resolvedApk"

$deviceSerial = Select-DeviceSerial -AdbPath $adbPath -RequestedSerial $Serial
Write-Host "设备：$deviceSerial"

Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "install", "-r", $resolvedApk)
Write-Host "安装完成。"

if ($ReverseBackend) {
    Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "reverse", "tcp:8000", "tcp:8000")
    Write-Host "已建立 adb reverse：设备 tcp:8000 -> Windows tcp:8000。"
}

if ($ClearData) {
    Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "shell", "pm", "clear", $PackageName)
    Write-Host "已清除 App 本地数据。"
}

if ($DebugBind) {
    if ($Flavor -ne "internal") {
        throw "DebugBind 只允许用于 internal 调试版，灰度用户版不暴露内部绑定入口。请加 -Flavor internal。"
    }
    $resolvedSessionToken = $SessionToken.Trim()
    if ($resolvedSessionToken.Length -eq 0) {
        throw "DebugBind 需要 -SessionToken。v0.3 不再从 backend\.env 读取 APP_TOKEN。"
    }
    Invoke-Checked -FilePath $adbPath -Arguments @(
        "-s",
        $deviceSerial,
        "shell",
        "am",
        "start",
        "-n",
        "$PackageName/.MainActivity",
        "--es",
        "ticketbox.debug.server_url",
        $ServerUrl,
        "--es",
        "ticketbox.debug.session_token",
        $resolvedSessionToken
    )
    Write-Host "已用 debug intent 启动并绑定服务器。"
}
elseif ($Launch) {
    Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "shell", "monkey", "-p", $PackageName, "1")
    Write-Host "已尝试启动小票夹。"
}
