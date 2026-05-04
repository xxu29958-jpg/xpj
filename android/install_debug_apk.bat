@echo off
cd /d %~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_debug_apk.ps1 %*
