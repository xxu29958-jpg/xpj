#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$windows = Join-Path $root 'distribution\windows'
$iss = Join-Path $windows 'installer\ticketbox.iss'
$lifecycle = Join-Path $windows 'lifecycle\ticketbox_lifecycle'
$oldIss = Join-Path $root 'backend\packaging\ticketbox-installer.iss'

if (-not (Test-Path -LiteralPath $iss -PathType Leaf)) { throw "missing $iss" }
if (-not (Test-Path -LiteralPath (Join-Path $lifecycle 'cli.py') -PathType Leaf)) {
    throw 'missing lifecycle cli'
}
if (Test-Path -LiteralPath $oldIss) {
    throw 'old ticketbox-installer.iss must not remain as the shipped recipe'
}

$text = Get-Content -LiteralPath $iss -Raw
foreach ($token in @(
        'windows_lifecycle_receipt.ps1',
        'windows_owner_handoff.ps1',
        'install_bundled_services.ps1',
        'prepare_bundled_upgrade.ps1',
        'DATABASE_GENERATION_PROGRAM.json',
        'TicketboxBackendLauncher.exe',
        'ExtractTemporaryFile'
    )) {
    if ($text.Contains($token)) { throw "ISS still names retired path $token" }
}
if ($text -notmatch 'PrepareToInstall') { throw 'ISS missing read-only PrepareToInstall' }
if ($text -notmatch 'TicketboxActiveOperationCanContinue') {
    throw 'ISS must allow exact active-operation result delivery or resume'
}
if ($text -notmatch 'Utf8Encode\(Payload\)') {
    throw 'ISS must write the lifecycle request as UTF-8'
}
if ($text.Contains('AnsiString(Payload)')) {
    throw 'ISS must not ANSI-narrow the lifecycle request JSON'
}
if ($text -notmatch 'TicketboxLifecycle.exe') {
    throw 'ISS must invoke the installed TicketboxLifecycle.exe'
}
if ($text -notmatch '(?m)^\s*\[Run\]\s*$' -or $text -notmatch '\{code:TicketboxLifecycleParams\}') {
    throw 'ISS must invoke the installed coordinator from normal [Run]'
}
if ($text -notmatch 'CurStepChanged' -or $text -notmatch 'ssPostInstall') {
    throw 'ISS must observe lifecycle result after [Run]'
}
if ($text -match 'Exec\(' -or $text -match 'RaiseException') {
    throw 'ISS [Code] must not own lifecycle mutation or exception-based completion'
}
if ($text -notmatch 'GetCustomSetupExitCode' -or
    $text -notmatch 'TicketboxInstallFailed' -or
    $text -notmatch 'FinishedHeadingLabel\.Caption') {
    throw 'ISS must expose failed postconditions in the final page and process exit code'
}
if ($text -match '(?i)Flags:[^\r\n]*(nowait|shellexec|ignoreerrors|postinstall)') {
    throw 'ISS lifecycle [Run] entries must be elevated, waited, and terminal'
}
if ($text -match 'last-result\.json' -or $text -notmatch 'ticketbox-install-result\.json') {
    throw 'ISS must use an invocation-scoped temporary result'
}
if ($text -notmatch 'PrivilegesRequired=admin') { throw 'ISS must require UAC' }

Write-Output 'ticketbox-windows-vnext-source-inputs-ok'
