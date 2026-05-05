param(
    [ValidateSet("gray", "internal")]
    [string]$Flavor = "gray"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$AndroidRoot = Join-Path $ProjectRoot "android"

function Require-Env {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "缺少环境变量 $Name。Release 密钥和密码不能写入 Git，请在当前 PowerShell 会话里设置。"
    }
    return $value
}

function Ensure-JavaHome {
    if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME) -and (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
        return
    }

    $candidates = @(
        "C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot",
        "C:\Program Files\Eclipse Adoptium",
        "C:\Program Files\Android\Android Studio\jbr"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "bin\java.exe")) {
            $env:JAVA_HOME = $candidate
            $env:Path = "$candidate\bin;$env:Path"
            return
        }
        if (Test-Path -LiteralPath $candidate) {
            $jdk = Get-ChildItem -LiteralPath $candidate -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "bin\java.exe") } |
                Sort-Object Name -Descending |
                Select-Object -First 1
            if ($jdk) {
                $env:JAVA_HOME = $jdk.FullName
                $env:Path = "$($jdk.FullName)\bin;$env:Path"
                return
            }
        }
    }

    throw "未找到 JDK 17。请安装 Eclipse Temurin 17 JDK 后重试。"
}

$keystorePath = Require-Env "TICKETBOX_KEYSTORE_PATH"
Require-Env "TICKETBOX_KEY_ALIAS" | Out-Null
Require-Env "TICKETBOX_KEYSTORE_PASSWORD" | Out-Null
Require-Env "TICKETBOX_KEY_PASSWORD" | Out-Null
if (-not (Test-Path -LiteralPath $keystorePath)) {
    throw "Release keystore 不存在：$keystorePath"
}

Ensure-JavaHome

$variant = "$($Flavor.Substring(0, 1).ToUpperInvariant())$($Flavor.Substring(1))Release"
$task = ":app:assemble$variant"

$gradleFile = Join-Path $AndroidRoot "app\build.gradle.kts"
$versionName = "unknown"
$versionCode = "unknown"
if (Test-Path -LiteralPath $gradleFile) {
    $gradleText = Get-Content -Encoding UTF8 -Raw -LiteralPath $gradleFile
    $nameMatch = [regex]::Match($gradleText, 'ticketboxVersionName\s*=\s*"([^"]+)"')
    $codeMatch = [regex]::Match($gradleText, 'ticketboxVersionCode\s*=\s*([0-9]+)')
    if ($nameMatch.Success) {
        $versionName = $nameMatch.Groups[1].Value
    }
    if ($codeMatch.Success) {
        $versionCode = $codeMatch.Groups[1].Value
    }
}

Write-Host "正在构建小票夹 $Flavor release APK..."
Write-Host "版本：$versionName ($versionCode)"
Push-Location $AndroidRoot
try {
    & .\gradlew.bat $task --console=plain
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle 构建失败，退出码 $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$apkPath = Join-Path $AndroidRoot "app\build\outputs\apk\$Flavor\release\app-$Flavor-release.apk"
if (-not (Test-Path -LiteralPath $apkPath)) {
    throw "未找到输出 APK：$apkPath"
}

Write-Host "Release APK 已生成：$apkPath"
