#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$windows = Join-Path $root 'distribution\windows'
$iss = Join-Path $windows 'installer\ticketbox.iss'
$lifecycle = Join-Path $windows 'lifecycle\ticketbox_lifecycle'
$oldIss = Join-Path $root 'backend\packaging\ticketbox-installer.iss'

if (-not (Test-Path -LiteralPath $iss)) { throw "missing $iss" }
if (-not (Test-Path -LiteralPath (Join-Path $lifecycle 'cli.py'))) { throw 'missing lifecycle cli' }
if (Test-Path -LiteralPath $oldIss) { throw 'old ticketbox-installer.iss must not remain as the shipped recipe' }

$text = Get-Content -LiteralPath $iss -Raw
foreach ($token in @(
        'windows_lifecycle_receipt.ps1',
        'windows_owner_handoff.ps1',
        'install_bundled_services.ps1',
        'prepare_bundled_upgrade.ps1',
        'DATABASE_GENERATION_PROGRAM.json',
        'ticketbox-installer-windows.isph',
        'ticketbox-installer-flow.isph'
    )) {
    if ($text.Contains($token)) { throw "ISS still names retired owner $token" }
}
if ($text -notmatch 'PrepareToInstall') { throw 'ISS missing PrepareToInstall' }
if ($text -notmatch 'TicketboxActiveOperationIsResumable') { throw 'ISS must allow same-operation retry when active.json is resumable' }
if ($text -notmatch 'Utf8Encode\(Payload\)') { throw 'ISS must write the lifecycle request as UTF-8' }
if ($text.Contains('AnsiString(Payload)')) { throw 'ISS must not ANSI-narrow the lifecycle request JSON' }
if ($text -notmatch 'TicketboxLifecycle.exe') { throw 'ISS must invoke TicketboxLifecycle.exe' }
if ($text -notmatch '(?m)^\s*\[Run\]\s*$') { throw 'ISS must call the installed coordinator from [Run] after complete [Files]' }
foreach ($line in $text -split "`n") {
    if ($line -match '^\s*\[Run\]' -and $line.Trim() -cne '[Run]') {
        throw 'ISS [Run] must be a section tag on its own line; Pascal comments cannot contain [Run]'
    }
}
if ($text -match 'AfterInstall:\s*TicketboxProvision') { throw 'ISS must not mutate from a [Files] AfterInstall callback' }
if ($text -notmatch 'GetCustomSetupExitCode') { throw 'ISS must overlay Setup exit from last-result' }
if ($text -notmatch 'topic_installorder') { throw 'ISS must cite jrsoftware topic_installorder' }
if ($text -notmatch 'TicketboxBackendLauncher.exe') { throw 'ISS must ship TicketboxBackendLauncher.exe' }
if ($text -notmatch 'PrivilegesRequired=admin') { throw 'ISS must require UAC' }

Write-Output 'ticketbox-windows-vnext-source-inputs-ok'
