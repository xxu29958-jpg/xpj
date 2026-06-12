# Capture v0.4-alpha3 slice 2 UI screenshots into artifacts/screenshots/.
#
# Usage:
#   cd e:\projects\xiaopiaojia
#   pwsh -ExecutionPolicy Bypass -File scripts\capture_slice2_screenshots.ps1
#
# Requires:
#   - Backend NOT already running on port 8765 (script spins up its own copy).
#   - Python venv at backend\.venv with project deps installed.
#   - Edge/Chrome installed for headless capture.
#
# Behaviour:
#   - Starts uvicorn on 127.0.0.1:8765 (a temporary port whitelisted via env).
#   - Drives Edge headless to each /owner and /web page and saves PNGs.
#   - Stops the temporary uvicorn before exiting.
#   - Does NOT touch the main backend on :8000 if running.

param(
    [string]$Port = "8765",
    [string]$OutDir = "artifacts\screenshots"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Whitelist the temp port for the loopback gate by patching env before launch.
$env:XPJ_EXTRA_LOOPBACK_HOSTS = "127.0.0.1:$Port,localhost:$Port"

$logPath = Join-Path $root "artifacts\screenshot_uvicorn.log"
New-Item -Path (Split-Path $logPath) -ItemType Directory -Force | Out-Null

$uvicorn = Start-Process -PassThru -NoNewWindow `
    -FilePath "backend\.venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$Port `
    -WorkingDirectory (Join-Path $root "backend") `
    -RedirectStandardOutput $logPath -RedirectStandardError $logPath

try {
    # Wait for /api/health.
    $deadline = (Get-Date).AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 250
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 1
            if ($r.StatusCode -eq 200) { break }
        } catch { }
    } until ((Get-Date) -gt $deadline)

    Write-Host "Backend ready on :$Port"

    $pages = @(
        @{ name="owner-index.png";                 url="/owner" },
        @{ name="web-dashboard.png";               url="/web" },
        @{ name="web-pending.png";                 url="/web/pending" },
        @{ name="web-data-quality.png";            url="/web/data-quality" },
        @{ name="web-duplicates.png";              url="/web/duplicates" },
        @{ name="web-categories.png";              url="/web/categories" },
        @{ name="web-categories-uncategorized.png";url="/web/categories/uncategorized" },
        @{ name="web-import.png";                  url="/web/import" },
        @{ name="web-reports.png";                 url="/web/reports" }
    )

    $absOut = Join-Path $root $OutDir
    New-Item -ItemType Directory -Path $absOut -Force | Out-Null

    $edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
    if (-not (Test-Path $edge)) { $edge = "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe" }
    if (-not (Test-Path $edge)) { throw "Microsoft Edge not found; install Edge or adapt to Chrome." }

    foreach ($p in $pages) {
        $out = Join-Path $absOut $p.name
        $args = @(
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--window-size=1280,900",
            "--screenshot=$out",
            "http://127.0.0.1:$Port$($p.url)"
        )
        & $edge @args 2>$null
        if (Test-Path $out) {
            Write-Host "  saved $($p.name)"
        } else {
            Write-Warning "  failed $($p.name)"
        }
    }
}
finally {
    if ($uvicorn -and -not $uvicorn.HasExited) {
        Stop-Process -Id $uvicorn.Id -Force
    }
}

Write-Host "Done. Screenshots in $OutDir."
