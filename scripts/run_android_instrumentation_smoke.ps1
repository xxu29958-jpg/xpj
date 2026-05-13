[CmdletBinding()]
param(
    [ValidateSet("gray", "internal")]
    [string]$Flavor = "gray",
    [string]$Serial = "",
    [string]$Adb = "",
    [string]$TestClass = "com.ticketbox.ui.screens.ExpenseEditScreenContractTest",
    [string]$Runner = "androidx.test.runner.AndroidJUnitRunner",
    [switch]$Build,
    [switch]$SkipInstall,
    [switch]$SkipMiuiAppOps,
    [int[]]$MiuiOps = @(10020, 10021),
    [int]$TimeoutSeconds = 300,
    [string]$ArtifactsDir = "artifacts\android-instrumentation"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$AndroidRoot = Join-Path $ProjectRoot "android"
$VariantName = "$($Flavor.Substring(0, 1).ToUpperInvariant())$($Flavor.Substring(1))Debug"
$PackageName = if ($Flavor -eq "internal") { "com.ticketbox.internal" } else { "com.ticketbox" }
$TestPackageName = "$PackageName.test"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory = $ProjectRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "命令失败：$FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
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

function Select-DeviceSerial {
    param(
        [Parameter(Mandatory = $true)][string]$AdbPath,
        [string]$RequestedSerial
    )

    $rows = @(& $AdbPath devices | Select-Object -Skip 1 | Where-Object { $_.Trim().Length -gt 0 })
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

function Get-DeviceProp {
    param(
        [Parameter(Mandatory = $true)][string]$AdbPath,
        [Parameter(Mandatory = $true)][string]$DeviceSerial,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $value = (& $AdbPath -s $DeviceSerial shell getprop $Name) -join "`n"
    return $value.Trim()
}

function Test-MiuiDevice {
    param(
        [Parameter(Mandatory = $true)][string]$AdbPath,
        [Parameter(Mandatory = $true)][string]$DeviceSerial
    )

    $markers = @(
        (Get-DeviceProp -AdbPath $AdbPath -DeviceSerial $DeviceSerial -Name "ro.miui.ui.version.name"),
        (Get-DeviceProp -AdbPath $AdbPath -DeviceSerial $DeviceSerial -Name "ro.mi.os.version.name"),
        (Get-DeviceProp -AdbPath $AdbPath -DeviceSerial $DeviceSerial -Name "ro.miui.ui.version.code")
    )
    foreach ($marker in $markers) {
        if ($marker.Trim().Length -gt 0) {
            return $true
        }
    }

    $manufacturer = Get-DeviceProp -AdbPath $AdbPath -DeviceSerial $DeviceSerial -Name "ro.product.manufacturer"
    return $manufacturer -match "Xiaomi|Redmi|POCO"
}

function Enable-MiuiTestLaunchOps {
    param(
        [Parameter(Mandatory = $true)][string]$AdbPath,
        [Parameter(Mandatory = $true)][string]$DeviceSerial
    )

    foreach ($op in $MiuiOps) {
        $opName = $op.ToString()
        Invoke-Checked -FilePath $AdbPath -Arguments @("-s", $DeviceSerial, "shell", "cmd", "appops", "set", "--uid", $PackageName, $opName, "allow")
        Invoke-Checked -FilePath $AdbPath -Arguments @("-s", $DeviceSerial, "shell", "cmd", "appops", "set", $PackageName, $opName, "allow")
    }

    $ops = & $AdbPath -s $DeviceSerial shell appops get $PackageName
    $ops | Select-String -Pattern "MIUIOP\(10020\)|MIUIOP\(10021\)" | ForEach-Object { Write-Host $_.Line }
}

function Invoke-Instrumentation {
    param(
        [Parameter(Mandatory = $true)][string]$AdbPath,
        [Parameter(Mandatory = $true)][string]$DeviceSerial,
        [Parameter(Mandatory = $true)][string]$RunDir
    )

    $stdoutPath = Join-Path $RunDir "instrumentation-stdout.txt"
    $stderrPath = Join-Path $RunDir "instrumentation-stderr.txt"
    $component = "$TestPackageName/$Runner"
    $arguments = @(
        "-s", $DeviceSerial,
        "shell", "am", "instrument",
        "-w", "-r", "--no-window-animation"
    )
    if ($TestClass.Trim().Length -gt 0) {
        $arguments += @("-e", "class", $TestClass)
    }
    $arguments += $component

    Write-Host "运行 instrumentation：$component"
    $process = Start-Process -FilePath $AdbPath `
        -ArgumentList $arguments `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        Invoke-Checked -FilePath $AdbPath -Arguments @("-s", $DeviceSerial, "shell", "am", "force-stop", $PackageName)
        Invoke-Checked -FilePath $AdbPath -Arguments @("-s", $DeviceSerial, "shell", "am", "force-stop", $TestPackageName)
        throw "instrumentation 超时：$TimeoutSeconds 秒。输出：$stdoutPath"
    }

    $stdout = ""
    if (Test-Path -LiteralPath $stdoutPath) {
        $stdout = Get-Content -LiteralPath $stdoutPath -Raw -Encoding UTF8
        if ($null -eq $stdout) {
            $stdout = ""
        }
    }
    $stderr = ""
    if (Test-Path -LiteralPath $stderrPath) {
        $stderr = Get-Content -LiteralPath $stderrPath -Raw -Encoding UTF8
        if ($null -eq $stderr) {
            $stderr = ""
        }
    }
    if ($stdout.Trim().Length -gt 0) {
        Write-Host $stdout.TrimEnd()
    }
    if ($stderr.Trim().Length -gt 0) {
        Write-Host $stderr.TrimEnd()
    }

    $exitCode = $process.ExitCode
    if ($null -ne $exitCode -and $exitCode -ne 0) {
        throw "instrumentation 命令退出码非 0：$exitCode。输出：$stdoutPath"
    }
    if ($stdout -match "FAILURES!!!" -or $stdout -match "INSTRUMENTATION_STATUS_CODE: -2") {
        throw "instrumentation 测试失败。输出：$stdoutPath"
    }
    if ($stdout -notmatch "OK \(\d+ tests?\)") {
        throw "instrumentation 未返回 OK。输出：$stdoutPath"
    }
}

$adbPath = Resolve-Adb
$deviceSerial = Select-DeviceSerial -AdbPath $adbPath -RequestedSerial $Serial
$runDir = Join-Path (Join-Path $ProjectRoot $ArtifactsDir) (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

Write-Host "adb: $adbPath"
Write-Host "设备：$deviceSerial"
Write-Host "variant: $VariantName"
Write-Host "target: $PackageName"
Write-Host "test: $TestPackageName"
Write-Host "artifacts: $runDir"

if ($Build) {
    Invoke-Checked -FilePath (Join-Path $AndroidRoot "gradlew.bat") -Arguments @("--no-daemon", ":app:assemble$VariantName", ":app:assemble${VariantName}AndroidTest") -WorkingDirectory $AndroidRoot
}

if (-not $SkipInstall) {
    Invoke-Checked -FilePath (Join-Path $AndroidRoot "gradlew.bat") -Arguments @("--no-daemon", ":app:install$VariantName", ":app:install${VariantName}AndroidTest") -WorkingDirectory $AndroidRoot
}

$isMiui = Test-MiuiDevice -AdbPath $adbPath -DeviceSerial $deviceSerial
if ($isMiui -and -not $SkipMiuiAppOps) {
    Write-Host "检测到 MIUI/HyperOS 设备，安装后修正测试启动 appop。"
    Enable-MiuiTestLaunchOps -AdbPath $adbPath -DeviceSerial $deviceSerial
}
elseif ($isMiui) {
    Write-Host "检测到 MIUI/HyperOS 设备，但已按参数跳过 appop 修正。"
}

Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "shell", "am", "force-stop", $PackageName)
Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "shell", "am", "force-stop", $TestPackageName)
Invoke-Checked -FilePath $adbPath -Arguments @("-s", $deviceSerial, "logcat", "-c")

Invoke-Instrumentation -AdbPath $adbPath -DeviceSerial $deviceSerial -RunDir $runDir

& $adbPath -s $deviceSerial logcat -d -t 1000 "*:W" | Out-File -FilePath (Join-Path $runDir "logcat-warning-tail.txt") -Encoding utf8
Write-Host "Android instrumentation smoke 通过。"
