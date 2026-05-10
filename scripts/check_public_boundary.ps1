#requires -Version 5.1
<#
.SYNOPSIS
    v0.3-rc1-preflight public-boundary acceptance probe.

.DESCRIPTION
    Confirms that the Cloudflare Tunnel surface (default https://api.zen70.cn)
    only exposes the endpoints intended for public consumption (/api/health,
    /api/auth/pair, /u/{key}, /api/expenses/* with valid app token) and that
    Owner Console / admin / bootstrap / docs are all rejected.

    Independently confirms that the loopback origin still works, to rule out
    "the backend is just down".

    Outputs a status table on stdout. The last line is one of:
        PUBLIC_BOUNDARY_PASS=true
        PUBLIC_BOUNDARY_PASS=false
    The script exits 0 on pass, 1 on any failure (so CI / report scripts can
    branch on $LASTEXITCODE without parsing).

.PARAMETER BaseUrl
    Public origin to probe. Defaults to https://api.zen70.cn.

.PARAMETER LocalUrl
    Local backend origin used as the "is it actually up" sanity check.
    Defaults to http://127.0.0.1:8000.

.NOTES
    The script never prints tokens, secrets, pairing codes, upload keys or
    UploadLink URLs. It also intentionally does NOT accept those values as
    parameters: the public boundary check must not depend on possessing any
    secret. /api/auth/pair is probed with an obviously invalid pairing code
    that should be rejected with 4xx (NOT 200) — what we are testing is
    that the endpoint is reachable on the public origin, not that pairing
    succeeds.
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://api.zen70.cn',
    [string]$LocalUrl = 'http://127.0.0.1:8000'
)

$ErrorActionPreference = 'Stop'
$results = @()

function Add-Result {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method,
        [string]$Expectation,
        [int]$Actual,
        [bool]$Pass
    )
    $script:results += [pscustomobject]@{
        Name        = $Name
        Url         = $Url
        Method      = $Method
        Expectation = $Expectation
        Actual      = $Actual
        Pass        = $Pass
    }
}

function Invoke-Probe {
    param(
        [string]$Url,
        [string]$Method = 'GET',
        [hashtable]$Body = $null
    )
    try {
        $params = @{
            Uri              = $Url
            Method           = $Method
            UseBasicParsing  = $true
            TimeoutSec       = 10
            ErrorAction      = 'Stop'
            MaximumRedirection = 0
        }
        if ($Body -ne $null) {
            $params['Body'] = ($Body | ConvertTo-Json -Compress)
            $params['ContentType'] = 'application/json'
        }
        $resp = Invoke-WebRequest @params
        return [int]$resp.StatusCode
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -ne $null) {
            return [int]$_.Exception.Response.StatusCode
        }
        return -1
    } catch {
        if ($_.Exception.Response -ne $null) {
            try { return [int]$_.Exception.Response.StatusCode } catch { }
        }
        return -1
    }
}

Write-Host "=== v0.3-rc1-preflight public boundary check ===" -ForegroundColor Cyan
Write-Host "BaseUrl  = $BaseUrl"
Write-Host "LocalUrl = $LocalUrl"
Write-Host ""

# ── 1) loopback sanity ──────────────────────────────────────────────────────
$localHealth = Invoke-Probe -Url "$LocalUrl/api/health"
Add-Result -Name 'local /api/health'  -Url "$LocalUrl/api/health" -Method 'GET' `
    -Expectation '200' -Actual $localHealth -Pass ($localHealth -eq 200)

$localOwner = Invoke-Probe -Url "$LocalUrl/owner"
Add-Result -Name 'local /owner'       -Url "$LocalUrl/owner"      -Method 'GET' `
    -Expectation '200 (loopback)' -Actual $localOwner -Pass ($localOwner -eq 200)

# ── 2) public allowed surface ───────────────────────────────────────────────
$pubHealth = Invoke-Probe -Url "$BaseUrl/api/health"
Add-Result -Name 'public /api/health' -Url "$BaseUrl/api/health" -Method 'GET' `
    -Expectation '200' -Actual $pubHealth -Pass ($pubHealth -eq 200)

# /api/auth/pair must be reachable but reject obviously invalid input.
$pairCode = Invoke-Probe -Url "$BaseUrl/api/auth/pair" -Method 'POST' -Body @{
    pairing_code = 'AAAAAA'
    device_name  = 'public-boundary-probe'
    platform     = 'android'
}
$pairOk = ($pairCode -ge 400 -and $pairCode -lt 500)
Add-Result -Name 'public /api/auth/pair (bad code)' -Url "$BaseUrl/api/auth/pair" -Method 'POST' `
    -Expectation '4xx (reachable, rejects)' -Actual $pairCode -Pass $pairOk

# /u/{nonexistent-key} should be reachable but reject.
$uCode = Invoke-Probe -Url "$BaseUrl/u/upl_does_not_exist_aaaaaaaaaaaaaaaaa" -Method 'POST'
$uOk = ($uCode -ge 400 -and $uCode -lt 500)
Add-Result -Name 'public /u/{fake}' -Url "$BaseUrl/u/upl_does_not_exist_*" -Method 'POST' `
    -Expectation '4xx (reachable, rejects)' -Actual $uCode -Pass $uOk

# ── 3) public forbidden surface ─────────────────────────────────────────────
$forbiddenChecks = @(
    @{ Name = 'public /owner';                  Url = "$BaseUrl/owner";              Method = 'GET'  }
    @{ Name = 'public /owner/devices';          Url = "$BaseUrl/owner/devices";      Method = 'GET'  }
    @{ Name = 'public /owner/upload-links';     Url = "$BaseUrl/owner/upload-links"; Method = 'GET'  }
    @{ Name = 'public /api/admin/devices';      Url = "$BaseUrl/api/admin/devices";  Method = 'GET'  }
    @{ Name = 'public /api/admin/upload-links'; Url = "$BaseUrl/api/admin/upload-links"; Method = 'GET' }
    @{ Name = 'public /api/bootstrap/owner';    Url = "$BaseUrl/api/bootstrap/owner"; Method = 'POST' }
    @{ Name = 'public /docs';                   Url = "$BaseUrl/docs";               Method = 'GET'  }
    @{ Name = 'public /openapi.json';           Url = "$BaseUrl/openapi.json";       Method = 'GET'  }
    @{ Name = 'public /redoc';                  Url = "$BaseUrl/redoc";              Method = 'GET'  }
)

foreach ($c in $forbiddenChecks) {
    $code = Invoke-Probe -Url $c.Url -Method $c.Method
    # Acceptable rejection codes: 401, 403, 404, 405. Anything 2xx/3xx fails.
    $ok = ($code -in 401, 403, 404, 405)
    Add-Result -Name $c.Name -Url $c.Url -Method $c.Method `
        -Expectation '401/403/404/405' -Actual $code -Pass $ok
}

# ── 4) summary ──────────────────────────────────────────────────────────────
$rows = $results | ForEach-Object {
    $passLabel = if ($_.Pass) { 'PASS' } else { 'FAIL' }
    "{0,-4} {1,-38} expect={2,-22} actual={3}" -f $passLabel, $_.Name, $_.Expectation, $_.Actual
}
$rows | ForEach-Object { Write-Host $_ }
Write-Host ""

$passCount = ($results | Where-Object { $_.Pass }).Count
$total = $results.Count
$summaryColor = if ($passCount -eq $total) { 'Green' } else { 'Red' }
Write-Host "Passed: $passCount / $total" -ForegroundColor $summaryColor

if ($passCount -eq $total) {
    Write-Host 'PUBLIC_BOUNDARY_PASS=true' -ForegroundColor Green
    exit 0
} else {
    Write-Host 'PUBLIC_BOUNDARY_PASS=false' -ForegroundColor Red
    exit 1
}
