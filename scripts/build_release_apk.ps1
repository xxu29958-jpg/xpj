param(
    [ValidateSet("gray", "internal")]
    [string]$Flavor = "gray",
    [ValidateSet("release", "debug")]
    [string]$Variant = "release",
    [switch]$SkipManifest
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$AndroidRoot = Join-Path $ProjectRoot "android"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

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

function Get-GitValue {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    try {
        $lines = @(& git -C $ProjectRoot @Arguments 2>$null)
        $value = ($lines -join "`n").Trim()
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }
    catch {
        return ""
    }
    return ""
}

$keystoreRequired = ($Variant -eq "release")
$keystorePath = ""
if ($keystoreRequired) {
    $keystorePath = Require-Env "TICKETBOX_KEYSTORE_PATH"
    Require-Env "TICKETBOX_KEY_ALIAS" | Out-Null
    Require-Env "TICKETBOX_KEYSTORE_PASSWORD" | Out-Null
    Require-Env "TICKETBOX_KEY_PASSWORD" | Out-Null
    if (-not (Test-Path -LiteralPath $keystorePath)) {
        throw "Release keystore 不存在：$keystorePath"
    }
}
else {
    Write-Host "Variant=debug：跳过密钥校验，将构建 debug APK。该包仅用于本机安装验证，不要分发。"
}

Ensure-JavaHome

$flavorCap = "$($Flavor.Substring(0, 1).ToUpperInvariant())$($Flavor.Substring(1))"
$variantCap = "$($Variant.Substring(0, 1).ToUpperInvariant())$($Variant.Substring(1))"
$task = ":app:assemble$flavorCap$variantCap"

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

Write-Host "正在构建小票夹 $Flavor $Variant APK..."
Write-Host "版本：$versionName ($versionCode)"
Push-Location $AndroidRoot
try {
    & .\gradlew.bat --no-daemon $task --console=plain
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle 构建失败，退出码 $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$apkPath = Join-Path $AndroidRoot "app\build\outputs\apk\$Flavor\$Variant\app-$Flavor-$Variant.apk"
if (-not (Test-Path -LiteralPath $apkPath)) {
    throw "未找到输出 APK：$apkPath"
}

$apkFile = Get-Item -LiteralPath $apkPath
$sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $apkPath).Hash.ToLowerInvariant()
$shaPath = "$apkPath.sha256"
$manifestPath = Join-Path $apkFile.Directory.FullName "$($apkFile.BaseName).manifest.json"
$outputRelativePath = "android/app/build/outputs/apk/$Flavor/$Variant/$($apkFile.Name)"

[System.IO.File]::WriteAllText($shaPath, "$sha256  $($apkFile.Name)`n", $Utf8NoBom)

if (-not $SkipManifest) {
    $gitCommit = Get-GitValue -Arguments @("rev-parse", "HEAD")
    $gitShortCommit = Get-GitValue -Arguments @("rev-parse", "--short", "HEAD")
    $gitBranch = Get-GitValue -Arguments @("rev-parse", "--abbrev-ref", "HEAD")
    $gitDirty = $false
    $gitStatus = Get-GitValue -Arguments @("status", "--porcelain")
    if (-not [string]::IsNullOrWhiteSpace($gitStatus)) {
        $gitDirty = $true
    }

    # codex P1 #5: 把构建期看到的 TICKETBOX_SERVER_URL 写入 manifest, 灰度验收脚本可与
    # -ServerUrl 做 parity check, 防止 APK 内置 URL 与对外宣称地址不一致(尤其是 release
    # 默认 fallback 已经被 build.gradle.kts 拒绝,但发布人误传错 URL 仍会发出去)。
    $serverUrlBuiltIn = [Environment]::GetEnvironmentVariable("TICKETBOX_SERVER_URL")
    if ([string]::IsNullOrWhiteSpace($serverUrlBuiltIn)) { $serverUrlBuiltIn = "" }

    $manifest = [ordered]@{
        app = "ticketbox"
        flavor = $Flavor
        build_type = $Variant
        version_name = $versionName
        version_code = $versionCode
        apk_file_name = $apkFile.Name
        apk_relative_path = $outputRelativePath
        apk_size_bytes = $apkFile.Length
        sha256 = $sha256
        server_url = $serverUrlBuiltIn
        built_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        git = [ordered]@{
            branch = $gitBranch
            commit = $gitCommit
            short_commit = $gitShortCommit
            dirty = $gitDirty
        }
        notes = @(
            "Release 密钥和密码不写入 manifest。",
            "manifest 只用于灰度发包核验，不包含 token。"
        )
    }

    [System.IO.File]::WriteAllText($manifestPath, (($manifest | ConvertTo-Json -Depth 5) + "`n"), $Utf8NoBom)
}

Write-Host "$Variant APK 已生成：$apkPath"
Write-Host "版本：versionName=$versionName，versionCode=$versionCode"
Write-Host "SHA256：$sha256"
Write-Host "SHA256 文件：$shaPath"
if (-not $SkipManifest) {
    Write-Host "发布 manifest：$manifestPath"
}
if ($Variant -eq "debug") {
    Write-Host "提示：该 APK 为 debug 签名，仅用于本机验证，不要分发。"
}
