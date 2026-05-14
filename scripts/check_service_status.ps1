param(
    [string]$ServerUrl = "https://api.example.com",
    [int]$Port = 8000,
    [int]$Tail = 30,
    [switch]$Strict,
    [switch]$SkipPublicAuth,
    [string]$SessionToken = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$BackendVersionFile = Join-Path $BackendRoot "app\version.py"
$LogDir = Join-Path $BackendRoot "logs"
$BaseUrl = $ServerUrl.TrimEnd("/")
$Failures = New-Object System.Collections.Generic.List[string]

function Resolve-SessionToken {
    if ($SessionToken.Trim().Length -gt 0) {
        return $SessionToken.Trim()
    }
    $processValue = [Environment]::GetEnvironmentVariable("TICKETBOX_SESSION_TOKEN")
    if ($processValue -and $processValue.Trim().Length -gt 0) {
        return $processValue.Trim()
    }
    return ""
}

function Get-ExpectedBackendVersion {
    if (-not (Test-Path -LiteralPath $BackendVersionFile)) {
        return ""
    }

    $content = Get-Content -LiteralPath $BackendVersionFile -Raw -Encoding UTF8
    $match = [regex]::Match($content, "BACKEND_VERSION\s*=\s*[""']([^""']+)[""']")
    if ($match.Success) {
        return $match.Groups[1].Value
    }

    return ""
}

function Test-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{}
    )

    try {
        $response = Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 10
        Write-Host "OK   $Name $($response | ConvertTo-Json -Compress)"
        return $true
    }
    catch {
        Write-Host "FAIL $Name $($_.Exception.Message)"
        $Failures.Add($Name)
        return $false
    }
}

function Test-HealthEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$ExpectedBackendVersion
    )

    try {
        $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 10
        $json = $response | ConvertTo-Json -Compress
        if ($response.status -ne "ok") {
            Write-Host "FAIL $Name status=$($response.status) $json"
            $Failures.Add($Name)
            return
        }
        if ([string]$response.backend_version -ne $ExpectedBackendVersion) {
            Write-Host "FAIL $Name 后端版本不一致 expected=$ExpectedBackendVersion running=$($response.backend_version) $json"
            $Failures.Add($Name)
            return
        }
        Write-Host "OK   $Name $json"
    }
    catch {
        Write-Host "FAIL $Name $($_.Exception.Message)"
        $Failures.Add($Name)
    }
}

Write-Host "小票夹服务状态"
Write-Host "项目目录：$ProjectRoot"
Write-Host "本机后端：http://127.0.0.1:$Port"
Write-Host "公网入口：$BaseUrl"
Write-Host ""

Write-Host "监听端口："
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $listener | Select-Object LocalAddress, LocalPort, State, OwningProcess | Format-Table -AutoSize
    Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue |
        Select-Object ProcessName, Id, Path, StartTime |
        Format-Table -AutoSize
}
else {
    Write-Host "FAIL 127.0.0.1:$Port 未监听。"
    $Failures.Add("local listener")
}

Write-Host "Cloudflare 进程或服务："
$cloudflaredProcess = Get-Process -Name "cloudflared*" -ErrorAction SilentlyContinue |
    Select-Object ProcessName, Id, Path
if ($cloudflaredProcess) {
    $cloudflaredProcess | Format-Table -AutoSize
}
else {
    Write-Host "未发现 cloudflared 进程。"
}
$cloudflaredService = Get-Service -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*cloudflared*" -or $_.DisplayName -like "*cloudflared*" } |
    Select-Object Name, DisplayName, Status
if ($cloudflaredService) {
    $cloudflaredService | Format-Table -AutoSize
}

Write-Host "计划任务："
Get-ScheduledTask -TaskName TicketboxBackend,TicketboxCloudflareTunnel -ErrorAction SilentlyContinue |
    Select-Object TaskName, State |
    Format-Table -AutoSize

Write-Host "接口检查："
$expectedBackendVersion = Get-ExpectedBackendVersion
if (-not $expectedBackendVersion) {
    throw "未能解析后端版本：$BackendVersionFile"
}
Test-HealthEndpoint -Name "local health " -Uri "http://127.0.0.1:$Port/api/health" -ExpectedBackendVersion $expectedBackendVersion
Test-HealthEndpoint -Name "public health" -Uri "$BaseUrl/api/health" -ExpectedBackendVersion $expectedBackendVersion

$resolvedSessionToken = Resolve-SessionToken
if (-not $SkipPublicAuth -and $resolvedSessionToken.Length -gt 0) {
    Test-Endpoint -Name "public auth  " -Uri "$BaseUrl/api/auth/check" -Headers @{ Authorization = "Bearer $resolvedSessionToken" } | Out-Null
}
elseif ($SkipPublicAuth) {
    Write-Host "SKIP public auth：已指定 -SkipPublicAuth。"
}
else {
    Write-Host "SKIP public auth：没有 TICKETBOX_SESSION_TOKEN。"
}

Write-Host ""
Write-Host "最近后端访问日志："
$latestLog = Get-ChildItem -LiteralPath $LogDir -Filter "ticketbox-backend-*.out.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($latestLog) {
    Write-Host $latestLog.FullName
    Get-Content -Encoding UTF8 -LiteralPath $latestLog.FullName -Tail $Tail
}
else {
    Write-Host "未找到后端访问日志。"
}

if ($Strict -and $Failures.Count -gt 0) {
    throw "小票夹服务状态检查失败：$($Failures -join ', ')"
}
