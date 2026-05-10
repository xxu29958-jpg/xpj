param(
    [string]$ServerUrl = "https://api.example.com",
    [int]$Tail = 40,
    [string]$SessionToken = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendRoot = Join-Path $ProjectRoot "backend"
$LogDir = Join-Path $BackendRoot "logs"

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

function Test-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{}
    )

    try {
        $response = Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec 12
        Write-Host "OK   $Name $Uri $($response | ConvertTo-Json -Compress)"
    }
    catch {
        Write-Host "FAIL $Name $Uri $($_.Exception.Message)"
    }
}

$baseUrl = $ServerUrl.TrimEnd("/")
$resolvedSessionToken = Resolve-SessionToken

Write-Host "小票夹服务器状态"
Write-Host "项目目录：$ProjectRoot"
Write-Host "公网地址：$baseUrl"
Write-Host ""

Write-Host "进程："
Get-Process |
    Where-Object { $_.ProcessName -like "*cloudflared*" -or ($_.Path -and $_.Path.StartsWith($BackendRoot, [System.StringComparison]::OrdinalIgnoreCase)) } |
    Select-Object ProcessName, Id, Path |
    Format-Table -AutoSize

Write-Host "监听端口："
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$listener |
    Select-Object LocalAddress, LocalPort, State, OwningProcess |
    Format-Table -AutoSize
if ($listener) {
    Write-Host "端口所属进程："
    Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue |
        Select-Object ProcessName, Id, Path, StartTime |
        Format-Table -AutoSize
}

Write-Host "计划任务："
Get-ScheduledTask -TaskName TicketboxBackend,TicketboxCloudflareTunnel -ErrorAction SilentlyContinue |
    Select-Object TaskName, State |
    Format-Table -AutoSize

Write-Host "接口检查："
Test-Endpoint -Name "local health " -Uri "http://127.0.0.1:8000/api/health"
Test-Endpoint -Name "public health" -Uri "$baseUrl/api/health"
if ($resolvedSessionToken.Length -gt 0) {
    Test-Endpoint -Name "public auth  " -Uri "$baseUrl/api/auth/check" -Headers @{ Authorization = "Bearer $resolvedSessionToken" }
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
