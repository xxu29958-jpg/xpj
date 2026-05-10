# reset_dev_uploads.ps1 -- DEV ONLY
# Clear development backend/uploads. Local development only.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$uploads = Join-Path $root "uploads"
if (Test-Path $uploads) {
    Get-ChildItem $uploads -Recurse | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Cleared dev uploads: $uploads"
} else {
    New-Item -ItemType Directory -Path $uploads | Out-Null
    Write-Host "Created empty dev uploads: $uploads"
}