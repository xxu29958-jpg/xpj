# reset_dev_db.ps1 -- DEV ONLY
# Reset development SQLite. Removes backend/data/ticketbox.db then re-inits.
# Local development only; never run on real data.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dbPath = Join-Path $root "data\ticketbox.db"
if (Test-Path $dbPath) {
    Remove-Item $dbPath -Force
    Write-Host "Removed dev DB: $dbPath"
} else {
    Write-Host "No dev DB to remove."
}
Push-Location $root
try {
    & .\.venv\Scripts\python.exe -c "from app.database import init_db; init_db(); print('init_db OK')"
} finally {
    Pop-Location
}