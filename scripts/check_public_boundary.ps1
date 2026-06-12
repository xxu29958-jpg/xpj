#requires -Version 5.1
<#
.SYNOPSIS
    v1.0 public-boundary acceptance probe.

.DESCRIPTION
    Confirms that the Cloudflare Tunnel surface (default https://api.example.com)
    only exposes the endpoints intended for public consumption (/api/health,
    controlled /api/* subsets, /u/{key}, session-gated /web/*, and
    /static/web/* + /static/shared/* assets) and that Owner Console / admin /
    bootstrap / docs / uploads are all rejected.

    Independently confirms that the loopback origin still works, to rule out
    "the backend is just down".

    Outputs a status table on stdout. The last line is one of:
        PUBLIC_BOUNDARY_PASS=true
        PUBLIC_BOUNDARY_PASS=false
    The script exits 0 on pass, 1 on any failure (so CI / report scripts can
    branch on $LASTEXITCODE without parsing).

.PARAMETER BaseUrl
    Public origin to probe. Defaults to https://api.example.com (override
    with -BaseUrl on the command line; never commit your real domain).

.PARAMETER LocalUrl
    Local backend origin used as the "is it actually up" sanity check.
    Defaults to http://127.0.0.1:8000.

.NOTES
    The script never prints tokens, secrets, pairing codes, upload keys or
    UploadLink URLs. It also intentionally does NOT accept those values as
    parameters: the public boundary check must not depend on possessing any
    secret. /api/auth/pair is probed with an obviously invalid pairing code
    that should be rejected with 401 invalid_pairing_code (NOT 200). /web/*
    without a cookie should return 303 with Location pointing at
    /web/auth/login?next=...

    If Cloudflare Access is enabled for /web, set TICKETBOX_CF_ACCESS_JWT in
    the environment. The value is sent as Cf-Access-Jwt-Assertion and is never
    printed.
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://api.example.com',
    [string]$LocalUrl = 'http://127.0.0.1:8000'
)

$ErrorActionPreference = 'Stop'
$results = @()
$cloudflareAccessJwt = [string]$env:TICKETBOX_CF_ACCESS_JWT
$cloudflareAccessJwt = $cloudflareAccessJwt.Trim()

function Add-Result {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method,
        [string]$Expectation,
        [object]$Actual,
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

function Get-HeaderValue {
    param(
        [object]$Headers,
        [string]$Name
    )
    if ($null -eq $Headers) {
        return ""
    }
    try {
        if ($Headers -is [System.Net.WebHeaderCollection]) {
            return [string]$Headers.Get($Name)
        }
        if ($Headers.ContainsKey($Name)) {
            $value = $Headers[$Name]
            if ($value -is [array]) {
                return [string]$value[0]
            }
            return [string]$value
        }
    } catch {
        return ""
    }
    return ""
}

function Read-ErrorResponseBody {
    param([object]$Response)
    if ($null -eq $Response) {
        return ""
    }
    try {
        $stream = $Response.GetResponseStream()
        if ($null -eq $stream) {
            return ""
        }
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        return $reader.ReadToEnd()
    } catch {
        return ""
    }
}

function Get-JsonErrorCode {
    param([string]$Body)
    if ([string]::IsNullOrWhiteSpace($Body)) {
        return ""
    }
    try {
        $json = $Body | ConvertFrom-Json
        if ($json.error) {
            return [string]$json.error
        }
    } catch {
        return ""
    }
    return ""
}

function New-ProbeResult {
    param(
        [int]$StatusCode,
        [object]$Headers = $null,
        [string]$Body = ""
    )
    [pscustomobject]@{
        StatusCode = $StatusCode
        ErrorCode  = Get-JsonErrorCode -Body $Body
        Location   = Get-HeaderValue -Headers $Headers -Name "Location"
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
        if (-not [string]::IsNullOrWhiteSpace($script:cloudflareAccessJwt)) {
            $params['Headers'] = @{ 'Cf-Access-Jwt-Assertion' = $script:cloudflareAccessJwt }
        }
        $resp = Invoke-WebRequest @params
        return New-ProbeResult -StatusCode ([int]$resp.StatusCode) -Headers $resp.Headers -Body ([string]$resp.Content)
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -ne $null) {
            $response = $_.Exception.Response
            return New-ProbeResult `
                -StatusCode ([int]$response.StatusCode) `
                -Headers $response.Headers `
                -Body (Read-ErrorResponseBody -Response $response)
        }
        return New-ProbeResult -StatusCode -1
    } catch {
        if ($_.Exception.Response -ne $null) {
            try {
                $response = $_.Exception.Response
                return New-ProbeResult `
                    -StatusCode ([int]$response.StatusCode) `
                    -Headers $response.Headers `
                    -Body (Read-ErrorResponseBody -Response $response)
            } catch { }
        }
        return New-ProbeResult -StatusCode -1
    }
}

function Format-ProbeActual {
    param([object]$Probe)
    $parts = @("status=$($Probe.StatusCode)")
    if (-not [string]::IsNullOrWhiteSpace($Probe.ErrorCode)) {
        $parts += "error=$($Probe.ErrorCode)"
    }
    if (-not [string]::IsNullOrWhiteSpace($Probe.Location)) {
        $parts += "location=$($Probe.Location)"
    }
    return ($parts -join " ")
}

function Test-Probe {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = 'GET',
        [int[]]$ExpectedStatus,
        [string]$ExpectedError = "",
        [string[]]$ExpectedErrors = @(),
        [string]$ExpectedLocationPrefix = "",
        [hashtable]$Body = $null
    )
    if ($null -eq $ExpectedErrors) {
        $ExpectedErrors = @()
    }
    $probe = Invoke-Probe -Url $Url -Method $Method -Body $Body
    $ok = ($ExpectedStatus -contains $probe.StatusCode)
    $expectParts = @("status=$($ExpectedStatus -join '/')")
    if ($ExpectedErrors.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($ExpectedError)) {
        $ExpectedErrors = @($ExpectedError)
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedError)) {
        $expectParts += "error=$ExpectedError"
    }
    if ($ExpectedErrors.Count -gt 0) {
        $ok = $ok -and ($ExpectedErrors -contains ([string]$probe.ErrorCode))
        if ([string]::IsNullOrWhiteSpace($ExpectedError)) {
            $expectParts += "error=$($ExpectedErrors -join '/')"
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedLocationPrefix)) {
        $location = [string]$probe.Location
        $ok = $ok -and $location.StartsWith($ExpectedLocationPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        $expectParts += "location starts $ExpectedLocationPrefix"
    }
    Add-Result `
        -Name $Name `
        -Url $Url `
        -Method $Method `
        -Expectation ($expectParts -join " ") `
        -Actual (Format-ProbeActual -Probe $probe) `
        -Pass $ok
    return $probe
}

Write-Host "=== v1.0 public boundary check ===" -ForegroundColor Cyan
Write-Host "BaseUrl  = $BaseUrl"
Write-Host "LocalUrl = $LocalUrl"
Write-Host ""

# ── 1) loopback sanity ──────────────────────────────────────────────────────
Test-Probe -Name 'local /api/health' -Url "$LocalUrl/api/health" -Method 'GET' -ExpectedStatus @(200) | Out-Null
Test-Probe -Name 'local /owner' -Url "$LocalUrl/owner" -Method 'GET' -ExpectedStatus @(200) | Out-Null

# ── 2) public allowed surface ───────────────────────────────────────────────
Test-Probe -Name 'public /api/health' -Url "$BaseUrl/api/health" -Method 'GET' -ExpectedStatus @(200) | Out-Null
Test-Probe -Name 'public /api/status/private (no token)' -Url "$BaseUrl/api/status/private" -Method 'GET' `
    -ExpectedStatus @(401, 404) -ExpectedErrors @('invalid_token', 'route_not_found', '') | Out-Null
Test-Probe -Name 'public /static/web/web.css' -Url "$BaseUrl/static/web/web.css" -Method 'GET' -ExpectedStatus @(200) | Out-Null
Test-Probe -Name 'public /static/shared/tokens.css' -Url "$BaseUrl/static/shared/tokens.css" -Method 'GET' -ExpectedStatus @(200) | Out-Null
# PWA install assets — must be public so iOS Safari / Android Chrome can
# fetch them when adding to home screen. None contain account data.
Test-Probe -Name 'public /static/web/manifest.webmanifest' -Url "$BaseUrl/static/web/manifest.webmanifest" -Method 'GET' -ExpectedStatus @(200) | Out-Null
Test-Probe -Name 'public /static/web/sw.js' -Url "$BaseUrl/static/web/sw.js" -Method 'GET' -ExpectedStatus @(200) | Out-Null
Test-Probe -Name 'public /static/web/icon.svg' -Url "$BaseUrl/static/web/icon.svg" -Method 'GET' -ExpectedStatus @(200) | Out-Null

# /api/auth/pair must be reachable but reject obviously invalid input.
# Backend may reject at the auth layer (401 invalid_pairing_code) OR at
# Pydantic schema (422 invalid_request) depending on payload shape;
# both confirm the endpoint is reachable and refuses bad input. The
# probe sends a deliberately short code so it can hit either path.
Test-Probe -Name 'public /api/auth/pair (bad code)' -Url "$BaseUrl/api/auth/pair" -Method 'POST' `
    -ExpectedStatus @(401, 422) -ExpectedErrors @('invalid_pairing_code', 'invalid_request', '') -Body @{
    pairing_code = 'AAAAAA'
    device_name  = 'public-boundary-probe'
    platform     = 'android'
} | Out-Null

# /u/{nonexistent-key} should be reachable but reject. PS 5.1's
# WebException-based body capture occasionally swallows the JSON body
# behind certain TLS proxy edge cases, so accept an empty ErrorCode
# alongside the expected ``invalid_token`` — status=401 already proves
# the endpoint is reachable and refusing the fake key.
Test-Probe -Name 'public /u/{fake}' -Url "$BaseUrl/u/upl_does_not_exist_aaaaaaaaaaaaaaaaa" -Method 'POST' `
    -ExpectedStatus @(401) -ExpectedErrors @('invalid_token', '') | Out-Null

# ── 3) public forbidden surface ─────────────────────────────────────────────
$edgeOrOwnerForbiddenErrors = @('invalid_request', 'route_not_found', '')
$edgeOrAdminForbiddenErrors = @('admin_api_local_only', 'route_not_found', '')
$edgeOrRouteNotFoundErrors = @('route_not_found', '')
$edgeOrBootstrapDisabledErrors = @('bootstrap_disabled', 'route_not_found', '')
$forbiddenChecks = @(
    @{ Name = 'public /owner';                  Url = "$BaseUrl/owner";                  Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/devices';          Url = "$BaseUrl/owner/devices";          Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/upload-links';     Url = "$BaseUrl/owner/upload-links";     Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/pairing';          Url = "$BaseUrl/owner/pairing";          Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/diagnostics';      Url = "$BaseUrl/owner/diagnostics";      Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/settings';         Url = "$BaseUrl/owner/settings";         Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/settings/api';     Url = "$BaseUrl/owner/settings/api";     Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/settings/security';Url = "$BaseUrl/owner/settings/security";Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /owner/backups';          Url = "$BaseUrl/owner/backups";          Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public POST /owner/devices/x/revoke';      Url = "$BaseUrl/owner/devices/00000000-0000-0000-0000-000000000000/revoke";      Method = 'POST'; Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public POST /owner/upload-links create';   Url = "$BaseUrl/owner/upload-links";        Method = 'POST'; Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public POST /owner/pairing/refresh';       Url = "$BaseUrl/owner/pairing/refresh";     Method = 'POST'; Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public POST /owner/settings/public-base-url'; Url = "$BaseUrl/owner/settings/public-base-url"; Method = 'POST'; Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
    @{ Name = 'public /api/admin/devices';      Url = "$BaseUrl/api/admin/devices";      Method = 'GET';  Status = @(403, 404); Errors = $edgeOrAdminForbiddenErrors }
    @{ Name = 'public /api/admin/upload-links'; Url = "$BaseUrl/api/admin/upload-links"; Method = 'GET';  Status = @(403, 404); Errors = $edgeOrAdminForbiddenErrors }
    # POST /api/admin/devices returns 405 method_not_allowed when the
    # admin router does not register a POST handler for the collection
    # path. 405 is a legitimate refusal (the verb is just as forbidden
    # as the resource), so accept it alongside the standard 403/404.
    @{ Name = 'public POST /api/admin/devices'; Url = "$BaseUrl/api/admin/devices";      Method = 'POST'; Status = @(403, 404, 405); Errors = @('admin_api_local_only', 'method_not_allowed', 'route_not_found', '') }
    @{ Name = 'public POST /api/admin/upload-links'; Url = "$BaseUrl/api/admin/upload-links"; Method = 'POST'; Status = @(403, 404); Errors = $edgeOrAdminForbiddenErrors }
    @{ Name = 'public /api/bootstrap/owner';    Url = "$BaseUrl/api/bootstrap/owner";    Method = 'POST'; Status = @(404); Errors = $edgeOrBootstrapDisabledErrors; Body = @{} }
    @{ Name = 'public /api/bootstrap/pairing-codes'; Url = "$BaseUrl/api/bootstrap/pairing-codes"; Method = 'POST'; Status = @(403, 404); Errors = $edgeOrAdminForbiddenErrors }
    @{ Name = 'public POST /api/maintenance/cleanup-images'; Url = "$BaseUrl/api/maintenance/cleanup-images"; Method = 'POST'; Status = @(403, 404); Errors = $edgeOrAdminForbiddenErrors }
    @{ Name = 'public /docs';                   Url = "$BaseUrl/docs";                   Method = 'GET';  Status = @(404); Errors = $edgeOrRouteNotFoundErrors }
    @{ Name = 'public /openapi.json';           Url = "$BaseUrl/openapi.json";           Method = 'GET';  Status = @(404); Errors = $edgeOrRouteNotFoundErrors }
    @{ Name = 'public /redoc';                  Url = "$BaseUrl/redoc";                  Method = 'GET';  Status = @(404); Errors = $edgeOrRouteNotFoundErrors }
    # Uploads dir must NEVER be statically served — image bytes only via auth API.
    @{ Name = 'public /uploads/owner/fake.png';          Url = "$BaseUrl/uploads/owner/2026/05/fake.png";  Method = 'GET';  Status = @(404); Errors = $edgeOrRouteNotFoundErrors }
    @{ Name = 'public /static/uploads/fake.png';         Url = "$BaseUrl/static/uploads/fake.png";         Method = 'GET';  Status = @(404); Errors = $edgeOrRouteNotFoundErrors }
    # P2 boundary defense-in-depth: /static/owner/* are loopback-only.
    # Backend static_owner_guard middleware refuses public requests
    # even if Cloudflare ingress drifts.
    @{ Name = 'public /static/owner/owner.css';          Url = "$BaseUrl/static/owner/owner.css";          Method = 'GET';  Status = @(403, 404); Errors = $edgeOrOwnerForbiddenErrors }
)

foreach ($c in $forbiddenChecks) {
    Test-Probe `
        -Name $c.Name `
        -Url $c.Url `
        -Method $c.Method `
        -ExpectedStatus $c.Status `
        -ExpectedError $c.Error `
        -ExpectedErrors $c.Errors `
        -Body $c.Body | Out-Null
}

# ── 4) /web public mode (PR #60 dual mode) ─────────────────────────────────
# /web is no longer forbidden — it's session-gated: no cookie → 303 to login.
# The login flow itself must be reachable; everything else under /web must
# redirect rather than render owner data.
$webRedirectChecks = @(
    @{ Name = 'public /web (no cookie)';                  Url = "$BaseUrl/web";                              Method = 'GET'; Location = '/web/auth/login?next=%2Fweb' }
    @{ Name = 'public /web/pending (no cookie)';          Url = "$BaseUrl/web/pending";                      Method = 'GET'; Location = '/web/auth/login?next=%2Fweb%2Fpending' }
    @{ Name = 'public /web/confirmed (no cookie)';        Url = "$BaseUrl/web/confirmed";                    Method = 'GET'; Location = '/web/auth/login?next=%2Fweb%2Fconfirmed' }
    @{ Name = 'public /web/reports (no cookie)';          Url = "$BaseUrl/web/reports";                      Method = 'GET'; Location = '/web/auth/login?next=%2Fweb%2Freports' }
    @{ Name = 'public GET /web/expenses/1/edit (no cookie)'; Url = "$BaseUrl/web/expenses/1/edit";           Method = 'GET'; Location = '/web/auth/login?next=%2Fweb%2Fexpenses%2F1%2Fedit' }
    @{ Name = 'public GET /web/expenses/1/image (no cookie)';     Url = "$BaseUrl/web/expenses/1/image";     Method = 'GET'; Location = '/web/auth/login?next=%2Fweb%2Fexpenses%2F1%2Fimage' }
    @{ Name = 'public GET /web/expenses/1/thumbnail (no cookie)'; Url = "$BaseUrl/web/expenses/1/thumbnail"; Method = 'GET'; Location = '/web/auth/login?next=%2Fweb%2Fexpenses%2F1%2Fthumbnail' }
)
foreach ($c in $webRedirectChecks) {
    Test-Probe `
        -Name $c.Name `
        -Url $c.Url `
        -Method $c.Method `
        -ExpectedStatus @(303) `
        -ExpectedLocationPrefix $c.Location | Out-Null
}

# /web/auth/login must be REACHABLE (otherwise the cookie flow is broken).
Test-Probe -Name 'public /web/auth/login (reachable)' -Url "$BaseUrl/web/auth/login" -Method 'GET' -ExpectedStatus @(200) | Out-Null

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
