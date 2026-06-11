param(
    [ValidateSet("gray", "internal")]
    [string]$Flavor = "gray",
    [ValidateSet("release", "debug")]
    [string]$Variant = "release",
    [switch]$SkipManifest,
    # release 变体默认拒绝 dirty 工作树(发包必须可追溯到一个干净 commit);
    # 本机实验性构建可显式加 -AllowDirty。manifest 仍如实记录 dirty,
    # 灰度验收(accept_gray_release.ps1)会再次硬性拒绝 dirty manifest。
    [switch]$AllowDirty
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

function Get-UntrackedBuildInputs {
    # codex review follow-up:--untracked-files=no 的洞——纯新增且未 add 的
    # Kotlin/资源文件会被打进 APK 而 manifest 仍显示 clean。APK 的文件级
    # 构建输入都在 android/ 下,把 untracked 检查 path-scope 到 android/
    # (=no 全局误拦:docs/audits/ 等本地审计目录天然在范围外;
    # android/local.properties 等被 .gitignore 忽略的不会出现在 porcelain)。
    $status = Get-GitValue -Arguments @("status", "--porcelain", "--untracked-files=all", "--", "android")
    if ([string]::IsNullOrWhiteSpace($status)) {
        return @()
    }
    return @($status -split "`n" | Where-Object { $_ -match "^\?\?" } | ForEach-Object { $_.Substring(3).Trim() })
}

if ($Variant -eq "release" -and -not $AllowDirty) {
    # codex review P1 #1: dirty 此前只写进 manifest、从不失败——脏树构建的
    # 包可以一路走到发包。release 变体在动 gradle 之前就拦下;manifest 的
    # dirty 字段仍然如实记录(覆盖 -AllowDirty 实验性构建),验收脚本对
    # manifest.git.dirty 再做第二道硬校验。
    # 语义=「已跟踪文件的未提交改动(全仓)」+「android/ 下未跟踪非忽略文件
    # (构建输入)」。全局 untracked-inclusive 会被 docs/audits/ 这类长期
    # untracked 的本地目录永久误拦,所以 untracked 只查构建输入范围。
    $dirtyStatus = Get-GitValue -Arguments @("status", "--porcelain", "--untracked-files=no")
    if (-not [string]::IsNullOrWhiteSpace($dirtyStatus)) {
        throw "工作树有未提交改动（已跟踪文件），release 构建被拒绝：发包必须可追溯到干净 commit。本机实验加 -AllowDirty。"
    }
    $untrackedInputs = Get-UntrackedBuildInputs
    if ($untrackedInputs.Count -gt 0) {
        throw "android/ 下有未跟踪文件会被打进 APK 但不在 commit 里：$($untrackedInputs -join '; ')。先 git add 提交（或删除），本机实验加 -AllowDirty。"
    }
}

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
    # 与上面 release 门禁同一语义:全仓已跟踪改动 OR android/ 下未跟踪
    # 构建输入,二者任一即 dirty(全局 untracked-inclusive 会因 docs/audits/
    # 这类长期 untracked 本地目录把每个包都标 dirty,故 untracked 只查
    # 构建输入范围;验收的 manifest.git.dirty 硬校验依赖本字段如实)。
    $gitStatus = Get-GitValue -Arguments @("status", "--porcelain", "--untracked-files=no")
    if (-not [string]::IsNullOrWhiteSpace($gitStatus)) {
        $gitDirty = $true
    }
    if (-not $gitDirty -and (Get-UntrackedBuildInputs).Count -gt 0) {
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
