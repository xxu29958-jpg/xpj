param(
    [switch]$SkipBackend,
    [switch]$SkipAndroid,
    [switch]$SkipSmoke,
    [switch]$SkipLint,
    [ValidateSet("ordinary", "full")]
    [string]$BackendTestDepth = "full"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$AndroidRoot = Join-Path $ProjectRoot "android"
$PostgresScriptsRoot = Join-Path $BackendRoot "scripts"

$BackendPostgresEnvironmentNames = @(
    "XPJ_TEST_BASE_DATABASE",
    "XPJ_TEST_SMOKE_DATABASE",
    "XPJ_TEST_RESTORE_DATABASE",
    "XPJ_TEST_APPLICATION_ROLE",
    "XPJ_TEST_CLUSTER_IDENTITY",
    "XPJ_TEST_ADMIN_URL",
    "XPJ_TEST_DATABASE_URL",
    "SMOKE_DATABASE_URL",
    "DRILL_SOURCE_URL",
    "DRILL_RESTORE_URL",
    "PGPASSFILE"
)

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
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
        $stopwatch.Stop()
        Pop-Location
    }
    Write-Host ("<<< completed in {0:c}" -f $stopwatch.Elapsed)
}

function Import-BackendTestPostgresEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Python
    )

    . (Join-Path $PostgresScriptsRoot "test_pg_storage_contract.ps1")
    . (Join-Path $PostgresScriptsRoot "test_pg_auth_contract.ps1")
    $contract = Get-XpjTestPostgresContract
    $port = [int]$contract.ports.local
    $dataDir = Get-XpjTestPostgresDefaultDataDir -Port $port
    $passfile = Assert-XpjTestPostgresAuthenticationFiles -DataDir $dataDir -Port $port
    $environmentFile = [IO.Path]::GetTempFileName()
    try {
        Invoke-Checked -FilePath $Python -Arguments @(
            "-E",
            "-S",
            "-m",
            "scripts.write_test_postgres_env",
            "--host",
            "localhost",
            "--port-profile",
            "local",
            "--admin-user",
            "postgres",
            "--existing-passfile",
            $passfile,
            "--output",
            $environmentFile
        ) -WorkingDirectory $BackendRoot

        $values = @{}
        foreach ($line in [IO.File]::ReadAllLines($environmentFile, [Text.Encoding]::UTF8)) {
            if ($line -notmatch '^(?<Name>[A-Z][A-Z0-9_]*)=(?<Value>.*)$') {
                throw "测试 PostgreSQL 环境包含无效记录。"
            }
            if ($values.ContainsKey($Matches.Name)) {
                throw "测试 PostgreSQL 环境包含重复字段：$($Matches.Name)"
            }
            $values[$Matches.Name] = $Matches.Value
        }
        $missing = @($BackendPostgresEnvironmentNames | Where-Object { -not $values.ContainsKey($_) })
        $unexpected = @($values.Keys | Where-Object { $_ -notin $BackendPostgresEnvironmentNames })
        if ($missing.Count -gt 0 -or $unexpected.Count -gt 0) {
            throw "测试 PostgreSQL 环境合同不匹配。缺失=$($missing -join ',')；多余=$($unexpected -join ',')"
        }

        foreach ($item in @(Get-ChildItem Env: -ErrorAction SilentlyContinue)) {
            if ($item.Name -match '^PG') {
                Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
            }
        }
        foreach ($name in $BackendPostgresEnvironmentNames) {
            [Environment]::SetEnvironmentVariable($name, [string]$values[$name], "Process")
        }
        foreach ($name in @("TEST_POSTGRES_PASSWORD", "TEST_POSTGRES_APPLICATION_PASSWORD", "XPJ_TEST_APPLICATION_PASSWORD")) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
    }
    finally {
        Remove-Item -Force -LiteralPath $environmentFile -ErrorAction SilentlyContinue
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

    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
    $adoptiumRoot = if ([string]::IsNullOrWhiteSpace($programFiles)) {
        ""
    }
    else {
        Join-Path $programFiles "Eclipse Adoptium"
    }
    if (-not $env:JAVA_HOME -and $adoptiumRoot -and (Test-Path -LiteralPath $adoptiumRoot)) {
        $jdk = Get-ChildItem -LiteralPath $adoptiumRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "bin\java.exe") } |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($jdk) {
            $env:JAVA_HOME = $jdk.FullName
        }
    }
    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    $localJava = if ([string]::IsNullOrWhiteSpace($localAppData)) {
        ""
    }
    else {
        Join-Path $localAppData "Programs\Kimi\runtime"
    }
    if (-not $env:JAVA_HOME -and $localJava -and (Test-Path -LiteralPath (Join-Path $localJava "bin\java.exe"))) {
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
            Compile = ":app:compileGrayDebugKotlin"
            Test = ":app:testGrayDebugUnitTest"
            Assemble = $assembleTasks
            Lint = ":app:lintGrayDebug"
            Detekt = @(":app:detektGrayDebug", ":app:detektGrayDebugUnitTest")
        }
    }

    return @{
        Label = "debug"
        Compile = ":app:compileDebugKotlin"
        Test = ":app:testDebugUnitTest"
        Assemble = @(":app:assembleDebug")
        Lint = ":app:lintDebug"
        Detekt = @()
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
    # The local entry point consumes the same lane and connection authorities as CI.
    # The disposable cluster remains running for fast repeat runs; stop it through
    # backend\scripts\stop_test_pg.ps1 when local verification is complete.
    Invoke-Checked -FilePath "powershell.exe" -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $BackendRoot "scripts\start_test_pg.ps1")
    ) -WorkingDirectory $BackendRoot
    Import-BackendTestPostgresEnvironment -Python $tools.Python
    Invoke-Checked -FilePath $tools.Python -Arguments @(
        "-m",
        "scripts.run_postgres_pytest_lane",
        "--lane",
        "ordinary",
        "--workers",
        "4"
    ) -WorkingDirectory $BackendRoot
    if ($BackendTestDepth -eq "full") {
        Invoke-Checked -FilePath $tools.Python -Arguments @(
            "-m",
            "scripts.run_postgres_pytest_lane",
            "--lane",
            "real-db",
            "--workers",
            "1"
        ) -WorkingDirectory $BackendRoot
    }
    Invoke-Checked -FilePath $tools.Python -Arguments @("scripts\check_api_contract.py") -WorkingDirectory $BackendRoot
    if ($BackendTestDepth -eq "full") {
        Invoke-Checked -FilePath $tools.Python -Arguments @("scripts\release_audit.py") -WorkingDirectory $BackendRoot
        if (-not $SkipSmoke) {
            Invoke-Checked -FilePath $tools.Python -Arguments @("scripts\smoke_test.py") -WorkingDirectory $BackendRoot
            Invoke-Checked -FilePath $tools.Python -Arguments @("scripts\postgres_backup_drill.py") -WorkingDirectory $BackendRoot
        }
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
    Invoke-Checked -FilePath $gradle -Arguments @("--no-daemon", $androidPlan.Compile, $androidPlan.Test) -WorkingDirectory $AndroidRoot
    # CI parity: qualify the executed JVM XML and test-count ratchet locally.
    Invoke-Checked -FilePath $gradle -Arguments @("--no-daemon", ":app:assertAndroidTestCountEqualsBaseline") -WorkingDirectory $AndroidRoot
    if (-not $SkipLint) {
        $qualityTasks = @($androidPlan.Lint) + @($androidPlan.Detekt)
        Invoke-Checked -FilePath $gradle -Arguments (@("--no-daemon") + $qualityTasks) -WorkingDirectory $AndroidRoot
    }
    Invoke-Checked -FilePath $gradle -Arguments (@("--no-daemon") + $androidPlan.Assemble) -WorkingDirectory $AndroidRoot
}
else {
    Write-Host "已跳过 Android 验证。"
}

Write-Host ""
Write-Host "项目验证完成。"
