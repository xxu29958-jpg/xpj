param(
    [switch]$SkipBackend,
    [switch]$SkipAndroid,
    [switch]$SkipSmoke,
    [switch]$SkipLint
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$AndroidRoot = Join-Path $ProjectRoot "android"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    Write-Host ""
    Write-Host ">>> $FilePath $($Arguments -join ' ')"
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

function Ensure-BackendTools {
    $python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "未找到后端虚拟环境。请先运行 backend\setup.bat -Dev。"
    }

    $ruff = Join-Path $BackendRoot ".venv\Scripts\ruff.exe"
    if (-not $SkipLint -and -not (Test-Path -LiteralPath $ruff)) {
        throw "未找到 ruff。请先运行 backend\setup.bat -Dev。"
    }

    return @{
        Python = $python
        Ruff = $ruff
    }
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

function Get-AndroidVerifyPlan {
    $gradleFile = Join-Path $AndroidRoot "app\build.gradle.kts"
    $hasGrayFlavor = $false
    $hasInternalFlavor = $false
    if (Test-Path -LiteralPath $gradleFile) {
        $gradleText = Get-Content -Encoding UTF8 -Raw -LiteralPath $gradleFile
        $hasGrayFlavor = $gradleText -match 'create\("gray"\)'
        $hasInternalFlavor = $gradleText -match 'create\("internal"\)'
    }

    if ($hasGrayFlavor) {
        $assembleTasks = @(":app:assembleGrayDebug")
        if ($hasInternalFlavor) {
            $assembleTasks += ":app:assembleInternalDebug"
        }
        return @{
            Label = "gray"
            Test = ":app:testGrayDebugUnitTest"
            Assemble = $assembleTasks
            Lint = ":app:lintGrayDebug"
        }
    }

    return @{
        Label = "debug"
        Test = ":app:testDebugUnitTest"
        Assemble = @(":app:assembleDebug")
        Lint = ":app:lintDebug"
    }
}

if (-not $SkipBackend) {
    Invoke-Checked -FilePath "powershell.exe" -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $PSScriptRoot "check_text_encoding.ps1"),
        "-Root",
        $ProjectRoot.Path
    ) -WorkingDirectory $ProjectRoot.Path

    $tools = Ensure-BackendTools
    Invoke-Checked -FilePath $tools.Python -Arguments @("-m", "compileall", "app", "scripts", "tests") -WorkingDirectory $BackendRoot
    if (-not $SkipLint) {
        Invoke-Checked -FilePath $tools.Ruff -Arguments @("check", "app", "scripts", "tests") -WorkingDirectory $BackendRoot
    }
    Invoke-Checked -FilePath $tools.Python -Arguments @("-m", "pytest") -WorkingDirectory $BackendRoot
    Invoke-Checked -FilePath $tools.Python -Arguments @("scripts\check_api_contract.py") -WorkingDirectory $BackendRoot
    $prevFileBacked = [Environment]::GetEnvironmentVariable("XPJ_TEST_FILE_BACKED")
    try {
        $env:XPJ_TEST_FILE_BACKED = "1"
        Invoke-Checked -FilePath $tools.Python -Arguments @(
            "-m", "pytest", "-q",
            "-k", "v1_migration_readiness or owner_migration_readiness or test_owner_backups_create_makes_file or pre_v03_backup_is_not_recreated"
        ) -WorkingDirectory $BackendRoot
    }
    finally {
        if ($null -eq $prevFileBacked) {
            Remove-Item Env:\XPJ_TEST_FILE_BACKED -ErrorAction SilentlyContinue
        } else {
            $env:XPJ_TEST_FILE_BACKED = $prevFileBacked
        }
    }
    if (-not $SkipSmoke) {
        Invoke-Checked -FilePath $tools.Python -Arguments @("scripts\smoke_test.py") -WorkingDirectory $BackendRoot
    }
}
else {
    Write-Host "已跳过后端验证。"
}

if (-not $SkipAndroid) {
    Ensure-LocalAndroidEnvironment
    $gradle = Join-Path $AndroidRoot "gradlew.bat"
    if (-not (Test-Path -LiteralPath $gradle)) {
        throw "未找到 Android Gradle Wrapper：$gradle"
    }

    $androidPlan = Get-AndroidVerifyPlan
    Write-Host "Android 验证变体：$($androidPlan.Label)"
    Invoke-Checked -FilePath $gradle -Arguments @("--no-daemon", $androidPlan.Test) -WorkingDirectory $AndroidRoot
    Invoke-Checked -FilePath $gradle -Arguments (@("--no-daemon") + $androidPlan.Assemble) -WorkingDirectory $AndroidRoot
    if (-not $SkipLint) {
        Invoke-Checked -FilePath $gradle -Arguments @("--no-daemon", $androidPlan.Lint) -WorkingDirectory $AndroidRoot
    }
}
else {
    Write-Host "已跳过 Android 验证。"
}

Write-Host ""
Write-Host "项目验证完成。"
