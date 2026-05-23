#requires -Version 5.1
<#
.SYNOPSIS
    ADR-0031 PR-2 v1.0 -> v0.9 rollback CLI.

.DESCRIPTION
    Restores the latest pre-v1.0 SQLite snapshot back into the live
    backend database. Used when v1.0 cut-over has happened (per
    docs/runbook/ROLLBACK.md "v1.0 migration preflight") but operators
    want to revert within the 30-day rollback window.

    What it does:

    1. Finds the newest "ticketbox-pre-v1.0-*.db" backup in
       backend\backups\.
    2. Refuses if that snapshot is older than 30 days (ADR-0031
       non-goal: silently losing a month of writes).
    3. Hands the snapshot path to scripts\restore_ticketbox_db.ps1,
       which is responsible for the actual stop-restore-start
       choreography.

    This script does NOT downgrade the backend binary, and does NOT
    touch the binary's BACKEND_VERSION. It only puts the database
    file back to its pre-cut-over state. To actually run a v0.9.x
    binary against the restored DB, follow docs/runbook/ROLLBACK.md
    after this script reports success.

.PARAMETER MaxAgeDays
    Override the rollback window (default 30 days from ADR-0031).
    Intentionally exposed so a rehearsal can pass -MaxAgeDays 365 to
    test the script against an old backup; production should leave
    it at the default.

.PARAMETER ForceWhileRunning
    Forward the same switch to restore_ticketbox_db.ps1. Default off
    (refuses to overwrite a DB that has the backend holding it).

.NOTES
    Run from project root: powershell -ExecutionPolicy Bypass -File
    scripts\rollback_to_v0.ps1
#>

[CmdletBinding()]
param(
    [int]$MaxAgeDays = 30,
    [switch]$ForceWhileRunning
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackupDir = Join-Path $ProjectRoot "backend\backups"
$RestoreScript = Join-Path $PSScriptRoot "restore_ticketbox_db.ps1"

if (-not (Test-Path -LiteralPath $BackupDir)) {
    throw "未找到备份目录：$BackupDir"
}
if (-not (Test-Path -LiteralPath $RestoreScript)) {
    throw "未找到 restore_ticketbox_db.ps1：$RestoreScript"
}

$snapshot = Get-ChildItem -LiteralPath $BackupDir -Filter "ticketbox-pre-v1.0-*.db" `
    | Sort-Object LastWriteTime -Descending `
    | Select-Object -First 1

if ($null -eq $snapshot) {
    throw "未找到任何 ticketbox-pre-v1.0-*.db 备份。v1.0 cut-over 尚未运行，或备份已被清理。"
}

# Keep the full-precision Double for the window comparison. The previous
# version cast to int first, which truncated 30.96 → 30 and silently
# allowed rollback up to ~31 days past the snapshot — outside the ADR-0031
# contract. The int cast is now display-only.
$ageSpan = (Get-Date) - $snapshot.LastWriteTime
$ageDaysExact = $ageSpan.TotalDays
$ageDaysDisplay = [math]::Floor($ageDaysExact)
Write-Host "找到 pre-v1.0 备份：$($snapshot.Name)"
Write-Host "  大小: $($snapshot.Length) bytes"
Write-Host "  生成时间: $($snapshot.LastWriteTime)"
Write-Host ("  距今: {0} 天 ({1:N2} 天精确)" -f $ageDaysDisplay, $ageDaysExact)

if ($ageDaysExact -gt $MaxAgeDays) {
    throw (("备份已超出 {0} 天的回滚窗口（实际 {1:N2} 天）。" -f $MaxAgeDays, $ageDaysExact) +
        "v1.0 期间产生的数据已远超回滚可承受的丢失量；" +
        "若仍要继续，请用 -MaxAgeDays 显式覆盖（ADR-0031 明确不推荐）。")
}

Write-Host ""
Write-Host "即将调用 restore_ticketbox_db.ps1 回滚到该备份。"
Write-Host "回滚后请按 docs\runbook\ROLLBACK.md 切回 v0.9.x binary。"
Write-Host ""

$restoreArgs = @{
    BackupPath = $snapshot.FullName
}
if ($ForceWhileRunning) {
    $restoreArgs["ForceWhileRunning"] = $true
}
& $RestoreScript @restoreArgs
