param(
    [string]$ServerUrl = "https://api.example.com",
    [switch]$SkipProjectVerify,
    [switch]$SkipPublicEndpoint,
    [switch]$SkipRelease,
    [switch]$UseTemporaryKeystore,
    [switch]$SkipDevice,
    # codex review P1 #1: RC 发包门禁的 CI/commit 绑定(替代已退役的
    # GitHub verify_rc_artifacts.ps1)。默认开;离线/无 CI 环境显式
    # -SkipCiBinding(会醒目 SKIP,跳过的包不算 RC)。
    [switch]$SkipCiBinding,
    [string]$GiteaUrl = "http://localhost:3000",
    [string]$GiteaRepo = "codex/xiaopiaojia",
    [string]$GiteaToken = "",
    [string]$SessionToken = "",
    [string]$UploadLink = "",
    [string]$Serial = "",
    [string]$Adb = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$AndroidRoot = Join-Path $ProjectRoot "android"
$VerifyScript = Join-Path $ProjectRoot "scripts\verify_project.ps1"
$EncodingScript = Join-Path $ProjectRoot "scripts\check_text_encoding.ps1"
$DiagnoseScript = Join-Path $ProjectRoot "scripts\diagnose_ticketbox.ps1"
$ReleaseScript = Join-Path $ProjectRoot "scripts\build_release_apk.ps1"
$InstallScript = Join-Path $AndroidRoot "scripts\install_debug_apk.ps1"
$BaseUrl = $ServerUrl.TrimEnd("/")

$RequiredRoutes = @(
    "/api/expenses/pending",
    "/api/expenses/confirmed",
    "/api/expenses/{expense_id}",
    "/api/expenses/{expense_id}/image",
    "/api/expenses/{expense_id}/thumbnail",
    "/api/expenses/{expense_id}/ocr/retry",
    "/api/expenses/{expense_id}/recognize-text",
    "/api/expenses/{expense_id}/mark-not-duplicate",
    "/api/stats/monthly",
    "/api/stats/lifestyle",
    "/api/rules/categories",
    "/api/rules/categories/{rule_id}",
    "/api/duplicates",
    "/api/settings/server",
    "/api/expenses/export.csv",
    "/api/auth/check",
    "/api/auth/pair",
    "/api/bootstrap/owner",
    "/api/bootstrap/pairing-codes",
    "/api/app/upload-screenshot",
    "/u/{upload_key}"
)

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Invoke-CheckedScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$Arguments = @()
    )

    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        throw "脚本不存在：$ScriptPath"
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "脚本失败：$ScriptPath $($Arguments -join ' ')"
    }
}

function Get-Secret {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$ExplicitValue = ""
    )

    if ($ExplicitValue.Trim().Length -gt 0) {
        return $ExplicitValue.Trim()
    }
    $processValue = [Environment]::GetEnvironmentVariable($Name)
    if ($processValue -and $processValue.Trim().Length -gt 0) {
        return $processValue.Trim()
    }
    return ""
}

function Resolve-UploadUrl {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("http://", [System.StringComparison]::OrdinalIgnoreCase) -or
        $trimmed.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $trimmed
    }
    if ($trimmed.StartsWith("/")) {
        return "$BaseUrl$trimmed"
    }
    return "$BaseUrl/$trimmed"
}

function Invoke-MultipartUpload {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )

    $pngBytes = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
    $boundary = "----ticketbox-gray-accept-$([Guid]::NewGuid().ToString("N"))"
    $prefix = (
        "--$boundary`r`n" +
        "Content-Disposition: form-data; name=`"file`"; filename=`"acceptance.png`"`r`n" +
        "Content-Type: image/png`r`n`r`n"
    )
    $suffix = "`r`n--$boundary--`r`n"
    $prefixBytes = [System.Text.Encoding]::UTF8.GetBytes($prefix)
    $suffixBytes = [System.Text.Encoding]::UTF8.GetBytes($suffix)
    $body = New-Object byte[] ($prefixBytes.Length + $pngBytes.Length + $suffixBytes.Length)
    [System.Buffer]::BlockCopy($prefixBytes, 0, $body, 0, $prefixBytes.Length)
    [System.Buffer]::BlockCopy($pngBytes, 0, $body, $prefixBytes.Length, $pngBytes.Length)
    [System.Buffer]::BlockCopy($suffixBytes, 0, $body, $prefixBytes.Length + $pngBytes.Length, $suffixBytes.Length)

    try {
        $response = Invoke-WebRequest `
            -Method Post `
            -Uri $Uri `
            -Headers $Headers `
            -ContentType "multipart/form-data; boundary=$boundary" `
            -Body $body `
            -UseBasicParsing
        return ($response.Content | ConvertFrom-Json)
    }
    catch {
        $response = $_.Exception.Response
        if ($response) {
            $stream = $response.GetResponseStream()
            if ($stream) {
                $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
                $bodyText = $reader.ReadToEnd()
                if ($bodyText.Trim().Length -gt 0) {
                    throw "上传验收失败：$bodyText"
                }
            }
        }
        throw "上传验收失败：$($_.Exception.Message)"
    }
}

function Assert-RouteSet {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$OpenApiUrl
    )

    $openApi = Invoke-RestMethod -Uri $OpenApiUrl -TimeoutSec 15
    $routes = @($openApi.paths.PSObject.Properties.Name)
    foreach ($required in $RequiredRoutes) {
        if ($routes -notcontains $required) {
            throw "$Name 缺少接口：$required"
        }
    }
    Write-Host "OK   $Name 接口清单完整。"
}

function Ensure-JavaAndKeytool {
    if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME) -and (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME "bin\keytool.exe"))) {
        return (Join-Path $env:JAVA_HOME "bin\keytool.exe")
    }
    $adoptiumRoot = "C:\Program Files\Eclipse Adoptium"
    if (Test-Path -LiteralPath $adoptiumRoot) {
        $jdk = Get-ChildItem -LiteralPath $adoptiumRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "bin\keytool.exe") } |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($jdk) {
            $env:JAVA_HOME = $jdk.FullName
            $env:Path = "$($jdk.FullName)\bin;$env:Path"
            return (Join-Path $jdk.FullName "bin\keytool.exe")
        }
    }
    throw "未找到 keytool。请安装 JDK 17。"
}

function New-TemporaryReleaseKey {
    $keytool = Ensure-JavaAndKeytool
    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "ticketbox-release-acceptance"
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $keystore = Join-Path $tempDir "ticketbox-acceptance.jks"
    if (Test-Path -LiteralPath $keystore) {
        Remove-Item -LiteralPath $keystore -Force
    }
    $password = "TicketboxAccept2026!"
    & $keytool `
        -genkeypair `
        -v `
        -keystore $keystore `
        -storepass $password `
        -keypass $password `
        -alias ticketbox `
        -keyalg RSA `
        -keysize 2048 `
        -validity 365 `
        -dname "CN=TicketBox Acceptance, OU=Gray, O=TicketBox, L=Local, ST=Local, C=CN" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "临时 release keystore 生成失败。"
    }
    $env:TICKETBOX_KEYSTORE_PATH = $keystore
    $env:TICKETBOX_KEY_ALIAS = "ticketbox"
    $env:TICKETBOX_KEYSTORE_PASSWORD = $password
    $env:TICKETBOX_KEY_PASSWORD = $password
    Write-Host "OK   已生成临时 release keystore，仅用于本机验收，不要发布给灰度用户。"
}

function Assert-ReleaseArtifact {
    param([Parameter(Mandatory = $true)][string]$ApkPath)

    $shaPath = "$ApkPath.sha256"
    $apkFile = Get-Item -LiteralPath $ApkPath
    $manifestPath = Join-Path $apkFile.Directory.FullName "$($apkFile.BaseName).manifest.json"

    if (-not (Test-Path -LiteralPath $shaPath)) {
        throw "缺少 release SHA256 文件：$shaPath"
    }
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "缺少 release manifest：$manifestPath"
    }

    $actualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $ApkPath).Hash.ToLowerInvariant()
    $shaText = (Get-Content -Encoding UTF8 -Raw -LiteralPath $shaPath).Trim()
    if (-not $shaText.StartsWith($actualSha, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "release SHA256 文件与 APK 不一致。"
    }

    $manifest = Get-Content -Encoding UTF8 -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ($manifest.sha256 -ne $actualSha) {
        throw "release manifest 中的 sha256 与 APK 不一致。"
    }
    if ($manifest.flavor -ne "gray" -or $manifest.build_type -ne "release") {
        throw "release manifest 不是 gray release 产物。"
    }
    # codex P1 #5: APK 内置 server_url 必须与对外宣称 -ServerUrl 一致, 防止"灰度脚本验证
    # https://api.zen70.cn 通,但 APK 实际编译时 TICKETBOX_SERVER_URL 误设成别的地址"这类
    # 链路分裂(以前只验后端 URL 可达,不验包内编译值)。空 server_url 说明构建时没设 env,
    # build.gradle.kts 的 release fail-fast 应当先一步拦住,这里是 second line。
    $manifestServerUrl = if ($manifest.PSObject.Properties["server_url"]) { [string]$manifest.server_url } else { "" }
    if ([string]::IsNullOrWhiteSpace($manifestServerUrl)) {
        throw "release manifest 缺少 server_url(构建时 TICKETBOX_SERVER_URL 未设)。重建 release APK 前先设环境变量。"
    }
    $expectedServerUrl = $BaseUrl
    $actualServerUrl = $manifestServerUrl.TrimEnd("/")
    if ($actualServerUrl -ne $expectedServerUrl) {
        throw "release APK 内置 server_url($actualServerUrl) 与验收 -ServerUrl($expectedServerUrl) 不一致。重建 APK 或修正 -ServerUrl。"
    }

    Write-Host "OK   release 产物校验通过：APK / SHA256 / manifest / server_url 一致。"
}

function Assert-ReleaseProvenance {
    # codex review P1 #1: verify_rc_artifacts.ps1 随 GitHub→Gitea 迁移退役后,
    # 验收只剩 APK/SHA/manifest/server_url 一致性——dirty 树或没过 CI 的
    # commit 构建的包同样能通过。本函数把「§9 红线」从文档散文变成可执行
    # 门禁:① manifest.git.dirty 一票否决;② manifest.git.commit 必须等于
    # 当前 HEAD(包↔checkout 绑定);③ 该 commit 在 Gitea 上 windows-ci 四
    # job 最新一次全 success(包↔CI 绑定;path-filtered 的 connected lane
    # 存在则一并要求 success,缺席不强求)。
    param([Parameter(Mandatory = $true)][string]$ApkPath)

    $apkFile = Get-Item -LiteralPath $ApkPath
    $manifestPath = Join-Path $apkFile.Directory.FullName "$($apkFile.BaseName).manifest.json"
    $manifest = Get-Content -Encoding UTF8 -Raw -LiteralPath $manifestPath | ConvertFrom-Json

    if ($manifest.git.dirty) {
        throw "release manifest 标记 dirty 构建——RC 必须从干净 commit 构建（重建前提交或还原改动）。"
    }
    $manifestCommit = [string]$manifest.git.commit
    if ([string]::IsNullOrWhiteSpace($manifestCommit)) {
        throw "release manifest 缺少 git.commit，无法绑定来源 commit。"
    }
    $headLines = @(& git -C $ProjectRoot rev-parse HEAD 2>$null)
    $head = ($headLines -join "").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($head)) {
        throw "无法读取当前 HEAD，无法校验 release 来源 commit。"
    }
    if ($manifestCommit -ne $head) {
        throw "release manifest commit($($manifestCommit.Substring(0, 8))) 与当前 HEAD($($head.Substring(0, 8))) 不一致——在发包 commit 上重新构建。"
    }
    Write-Host "OK   release 来源校验通过：干净构建，commit = $($head.Substring(0, 8))。"

    if ($SkipCiBinding) {
        Write-Host "SKIP CI 绑定校验（-SkipCiBinding）。该包未经 CI 绑定，不得作为正式 RC 发出。"
        return
    }
    $token = Get-Secret -Name "TICKETBOX_GITEA_TOKEN" -ExplicitValue $GiteaToken
    if ($token.Length -eq 0) {
        throw "缺少 TICKETBOX_GITEA_TOKEN（或 -GiteaToken），无法查询 CI 状态。离线验收用 -SkipCiBinding 显式跳过。"
    }
    $headers = @{ Authorization = "token $token" }
    $tasksUri = "$($GiteaUrl.TrimEnd('/'))/api/v1/repos/$GiteaRepo/actions/tasks?limit=200"
    $tasks = Invoke-RestMethod -Headers $headers -Uri $tasksUri -TimeoutSec 20
    $forCommit = @($tasks.workflow_runs | Where-Object { $_.head_sha -eq $head })
    if ($forCommit.Count -eq 0) {
        throw "Gitea 上找不到 commit $($head.Substring(0, 8)) 的任何 CI 任务——先推送该 commit 并等 CI 全绿。"
    }
    $requiredJobs = @("Backend full checks", "Backend (PostgreSQL)", "Desktop manager", "Android unit/build")
    foreach ($jobName in $requiredJobs) {
        $latest = $forCommit |
            Where-Object { $_.name -eq $jobName } |
            Sort-Object id -Descending |
            Select-Object -First 1
        if (-not $latest) {
            throw "commit $($head.Substring(0, 8)) 缺少 CI job「$jobName」——等 windows-ci 跑完再验收。"
        }
        if ($latest.status -ne "success") {
            throw "CI job「$jobName」最新状态为 $($latest.status)（commit $($head.Substring(0, 8))）——CI 全绿才能发包。"
        }
    }
    $connected = $forCommit |
        Where-Object { $_.name -eq "Connected (emulator)" } |
        Sort-Object id -Descending |
        Select-Object -First 1
    if ($connected -and $connected.status -ne "success") {
        throw "CI job「Connected (emulator)」最新状态为 $($connected.status)——instrumented lane 红着不能发包。"
    }
    Write-Host "OK   CI 绑定校验通过：commit $($head.Substring(0, 8)) 的 windows-ci 四 job 全 success。"
}

Write-Host "小票夹灰度版验收"
Write-Host "项目目录：$ProjectRoot"
Write-Host "公网地址：$BaseUrl"

if (-not $SkipProjectVerify) {
    Write-Step "项目自动化验证"
    Invoke-CheckedScript -ScriptPath $VerifyScript
}
else {
    Write-Host "SKIP 项目自动化验证。"
}

Write-Step "文本编码"
Invoke-CheckedScript -ScriptPath $EncodingScript

Write-Step "接口清单"
Assert-RouteSet -Name "本地后端" -OpenApiUrl "http://127.0.0.1:8000/openapi.json"
if (-not $SkipPublicEndpoint) {
    Assert-RouteSet -Name "公网后端" -OpenApiUrl "$BaseUrl/openapi.json"
}
else {
    Write-Host "SKIP 公网接口清单。"
}

Write-Step "公网上传闭环"
if (-not $SkipPublicEndpoint) {
    $sessionToken = Get-Secret -Name "TICKETBOX_SESSION_TOKEN" -ExplicitValue $SessionToken
    $uploadLink = Get-Secret -Name "TICKETBOX_UPLOAD_LINK" -ExplicitValue $UploadLink
    if ($sessionToken.Length -eq 0 -or $uploadLink.Length -eq 0) {
        throw "缺少 TICKETBOX_SESSION_TOKEN 或 TICKETBOX_UPLOAD_LINK，无法做公网上传验收。"
    }

    $appHeaders = @{ Authorization = "Bearer $sessionToken" }
    $uploadUrl = Resolve-UploadUrl -BaseUrl $BaseUrl -Value $uploadLink
    $iosUpload = Invoke-MultipartUpload -Uri $uploadUrl -Headers @{}
    $androidUpload = Invoke-MultipartUpload -Uri "$BaseUrl/api/app/upload-screenshot" -Headers $appHeaders
    foreach ($item in @($iosUpload, $androidUpload)) {
        $reject = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/expenses/$($item.id)/reject" -Headers $appHeaders -TimeoutSec 15
        if ($reject.status -ne "rejected") {
            throw "验收上传账单清理失败：$($item.id)"
        }
    }
    Write-Host "OK   UploadLink 和 Android session 上传接口均可通过公网创建 pending，并已清理为忽略。"
}
else {
    Write-Host "SKIP 公网上传闭环。"
}

Write-Step "Windows 诊断"
Invoke-CheckedScript -ScriptPath $DiagnoseScript -Arguments @("-Strict")
Invoke-CheckedScript -ScriptPath $DiagnoseScript -Arguments @("-Advanced", "-Tail", "3")

if (-not $SkipRelease) {
    Write-Step "Release APK"
    $hasReleaseEnv = (
        [Environment]::GetEnvironmentVariable("TICKETBOX_KEYSTORE_PATH") -and
        [Environment]::GetEnvironmentVariable("TICKETBOX_KEY_ALIAS") -and
        [Environment]::GetEnvironmentVariable("TICKETBOX_KEYSTORE_PASSWORD") -and
        [Environment]::GetEnvironmentVariable("TICKETBOX_KEY_PASSWORD")
    )
    if (-not $hasReleaseEnv) {
        if ($UseTemporaryKeystore) {
            New-TemporaryReleaseKey
        }
        else {
            throw "未配置 release keystore 环境变量。仅本机验收可加 -UseTemporaryKeystore。"
        }
    }
    Invoke-CheckedScript -ScriptPath $ReleaseScript -Arguments @("-Flavor", "gray")
    $releaseApk = Join-Path $AndroidRoot "app\build\outputs\apk\gray\release\app-gray-release.apk"
    if (-not (Test-Path -LiteralPath $releaseApk)) {
        throw "release APK 不存在：$releaseApk"
    }
    Assert-ReleaseArtifact -ApkPath $releaseApk
    Assert-ReleaseProvenance -ApkPath $releaseApk
    Write-Host "OK   release APK 已生成：$releaseApk"
}
else {
    Write-Host "SKIP release APK 构建。"
}

if (-not $SkipDevice) {
    Write-Step "Android 真机"
    $args = @("-Flavor", "gray", "-Build", "-Launch")
    if ($Serial.Trim().Length -gt 0) {
        $args += @("-Serial", $Serial)
    }
    if ($Adb.Trim().Length -gt 0) {
        $args += @("-Adb", $Adb)
    }
    Invoke-CheckedScript -ScriptPath $InstallScript -Arguments $args
    Write-Host "OK   最新 grayDebug 已安装并启动。生物识别、真实选图、编辑确认仍需在手机上人工完成。"
}
else {
    Write-Host "SKIP Android 真机安装。"
}

Write-Step "人工验收提醒"
Write-Host "TODO 需要手机人工确认：iPhone 快捷指令真实账单、Android 解锁后上传真实截图、编辑确认入账、账本和统计变化、蜂窝网络访问。"
Write-Host "OK   可自动化灰度验收完成。"
