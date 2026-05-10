# seed_dev_confirmed.ps1 -- DEV ONLY
# Insert 3 confirmed sample expenses on a fresh dev DB. Local development only.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & .\.venv\Scripts\python.exe scripts\_seed_dev_confirmed.py
} finally {
    Pop-Location
}