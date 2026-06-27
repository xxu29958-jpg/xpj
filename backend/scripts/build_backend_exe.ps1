# Freeze the Ticketbox backend into the onedir folder dist\ticketbox-backend\
# (ticketbox-backend.exe + _internal\), windowed/console=False — ADR-0047 §8.
#
#   scripts\build_backend_exe.ps1          # incremental
#   scripts\build_backend_exe.ps1 -Clean   # rebuild the build venv too
#
# Uses a dedicated .venv-build (uv-managed Python 3.11) so the runtime .venv
# is never polluted with PyInstaller. OCR is intentionally excluded.
param([switch]$Clean)
$ErrorActionPreference = "Stop"
$BackendRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $BackendRoot
$BuildVenv = Join-Path $BackendRoot ".venv-build"
$PyBuild = Join-Path $BuildVenv "Scripts\python.exe"

if ($Clean -and (Test-Path $BuildVenv)) { Remove-Item -Recurse -Force $BuildVenv }
if (-not (Test-Path $PyBuild)) {
    Write-Host "Creating build venv ($BuildVenv) ..."
    uv venv $BuildVenv --python 3.11
}

Write-Host "Installing build deps (runtime + PyInstaller, no OCR) ..."
uv pip install --python $PyBuild -r requirements-build.txt

Write-Host "Freezing ..."
& (Join-Path $BuildVenv "Scripts\pyinstaller.exe") --noconfirm --clean packaging\ticketbox-backend.spec

$Dir = Join-Path $BackendRoot "dist\ticketbox-backend"
$Exe = Join-Path $Dir "ticketbox-backend.exe"
if (Test-Path $Exe) {
    $sizeMb = [math]::Round(((Get-ChildItem -Recurse -File $Dir | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Write-Host "OK  ->  $Dir  (folder $sizeMb MB)"
} else {
    throw "build finished but $Exe is missing"
}
