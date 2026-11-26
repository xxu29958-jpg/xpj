#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$windows = Join-Path $root 'distribution\windows'
$iss = Join-Path $windows 'installer\ticketbox.iss'
$setupSecurity = Join-Path $windows 'installer\setup_security.iss'
$privateResult = Join-Path $windows 'installer\setup_private_result.iss'
$buildInstaller = Join-Path $windows 'build\build_installer.ps1'
$lifecycle = Join-Path $windows 'lifecycle\ticketbox_lifecycle'
$oldIss = Join-Path $root 'backend\packaging\ticketbox-installer.iss'

if (-not (Test-Path -LiteralPath $iss -PathType Leaf)) { throw "missing $iss" }
if (-not (Test-Path -LiteralPath $setupSecurity -PathType Leaf)) { throw "missing $setupSecurity" }
if (-not (Test-Path -LiteralPath $privateResult -PathType Leaf)) { throw "missing $privateResult" }
if (-not (Test-Path -LiteralPath (Join-Path $lifecycle 'cli.py') -PathType Leaf)) {
    throw 'missing lifecycle cli'
}
if (Test-Path -LiteralPath $oldIss) {
    throw 'old ticketbox-installer.iss must not remain as the shipped recipe'
}

$text = Get-Content -LiteralPath $iss -Raw
$setupSecurityText = Get-Content -LiteralPath $setupSecurity -Raw
$privateResultText = Get-Content -LiteralPath $privateResult -Raw
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
if ($text -notmatch 'TicketboxExactActiveCanContinue' -or
    $text -notmatch 'TicketboxCommittedReplayCanContinue') {
    throw 'ISS must allow only exact active or committed result replay'
}
if ($text -notmatch 'CloseApplications=no' -or $text -match 'CloseApplications=yes') {
    throw 'ISS must not let Restart Manager own pre-copy lifecycle mutation'
}
if ($text -notmatch 'onlyifdoesntexist' -or
    $text -notmatch 'TicketboxExpectedReleaseManifestSha256') {
    throw 'ISS exact resume requires immutable materialization and manifest binding'
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
$uninstallSplit = $text -split 'function TicketboxUninstallPreflightOk\(', 2
$afterUninstall = ($uninstallSplit[1] -split 'procedure DeinitializeUninstall;', 2)[1]
if ($uninstallSplit[0] -match 'Exec\(' -or $afterUninstall -match 'Exec\(' -or $text -match 'RaiseException') {
    throw 'ISS install [Code] must not own lifecycle mutation or exception-based completion'
}
if ($text -notmatch 'GetCustomSetupExitCode' -or
    $text -notmatch 'TicketboxInstallFailed' -or
    $text -notmatch 'FinishedHeadingLabel\.Caption') {
    throw 'ISS must expose failed postconditions in the final page and process exit code'
}
if ($text -match '(?i)Flags:[^\r\n]*(nowait|shellexec|ignoreerrors|postinstall)') {
    throw 'ISS lifecycle [Run] entries must be elevated, waited, and terminal'
}
if ($text -match 'last-result\.json' -or
    $text -notmatch '#include "setup_private_result\.iss"' -or
    $privateResultText -notmatch 'ticketbox-install-result\.json' -or
    $privateResultText -match '\{tmp\}') {
    throw 'ISS must use the protected invocation result channel'
}
if ($setupSecurityText -notmatch 'SetSecurityInfo' -or
    $setupSecurityText -notmatch 'GetSecurityInfo' -or
    $setupSecurityText -match 'SetKernelObjectSecurity' -or
    $privateResultText -notmatch 'TicketboxCreateProtectedDirectory') {
    throw 'ISS setup coordination security is not closed and handle-verified'
}
if ($text -notmatch 'PrivilegesRequired=admin') { throw 'ISS must require UAC' }
$buildText = Get-Content -LiteralPath $buildInstaller -Raw
if ($text -notmatch 'Ticketbox-UpgradeStage\\\{#ReleaseId\}\\lifecycle\\TicketboxLifecycle\.exe' -or
    $text -notmatch '--staged-release-root' -or
    $text -notmatch 'TicketboxPathAbsentOrAdminProtectedDir' -or
    $text -notmatch 'TicketboxUpgradeNeedsVcRedist') {
    throw 'ISS managed upgrade must stage in admin-protected Ticketbox-UpgradeStage and gate VC redist'
}
if ($text -notmatch '/UPGRADE=YES') {
    throw 'ISS managed upgrade recovery hint must instruct rerunning with /UPGRADE=YES'
}
if ($text -match 'TicketboxParseRemovedConnectorState|TicketboxManagedConnectorBlocksUpgrade') {
    throw 'ISS must not duplicate connector business-state parsing owned by Lifecycle'
}
if ($buildText -notmatch 'upgrade_startup_probe' -or
    $buildText -notmatch 'upgrade --help' -or
    $buildText -notmatch 'rollback_upgrade_startup_probe' -or
    $buildText -notmatch 'uninstall_startup_probe' -or
    $buildText -notmatch 'reinstall_startup_probe' -or
    $buildText -notmatch 'purge_data_startup_probe') {
    throw 'build_installer.ps1 must probe frozen TicketboxLifecycle.exe upgrade, rollback-upgrade, uninstall, reinstall and purge-data --help'
}
if ($text -notmatch 'Uninstallable=yes' -or
    $text -notmatch 'UninstallFilesDir=\{commoncf64\}\\Ticketbox\\uninstall' -or
    $text -match '(?m)^\s*\[UninstallRun\]\s*$' -or
    $text -match '(?m)^\s*\[UninstallDelete\]\s*$' -or
    $text -notmatch 'CurUninstallStepChanged' -or
    $text -notmatch 'usUninstall' -or
    $text -notmatch 'TicketboxUninstallResultIsCommitted' -or
    $text -notmatch 'TicketboxAbortUninstall') {
    throw 'ISS must enable gated Uninstallable=yes via CurUninstallStepChanged(usUninstall) with protected UninstallFilesDir and zero [UninstallRun]/[UninstallDelete]'
}
$preflightBlock = (($text -split 'function TicketboxUninstallPreflightOk\(', 2)[1] -split 'procedure TicketboxReportUninstallRefused', 2)[0]
$initUninstallBlock = (($text -split 'function InitializeUninstall: Boolean;', 2)[1] -split 'procedure CurUninstallStepChanged', 2)[0]
$curUninstallBlock = (($text -split 'procedure CurUninstallStepChanged\(CurUninstallStep: TUninstallStep\);', 2)[1] -split 'procedure DeinitializeUninstall;', 2)[0]
if ($text -match 'TicketboxHasJsonUnicodeEscape|TicketboxJsonTopLevelUniqueString|TicketboxWriteUninstallRequest' -or
    $preflightBlock -notmatch 'uninstall --check-preflight' -or
    $preflightBlock -match '--request|--result|DeleteFile\(|SaveStringToFile\(' -or
    $initUninstallBlock -match 'Exec\(|TicketboxAcquireSetupLease|TicketboxPreparePrivateResult|TicketboxAbortUninstall|DeleteFile\(' -or
    $initUninstallBlock -notmatch 'TicketboxPathIsNonReparseType\(LifecycleExe, False\)' -or
    $initUninstallBlock -notmatch 'TicketboxUninstallPreflightOk' -or
    $curUninstallBlock -notmatch 'TicketboxPathIsNonReparseType\(LifecycleExe, False\)' -or
    $curUninstallBlock -notmatch 'TicketboxUninstallPreflightOk' -or
    $curUninstallBlock.IndexOf('TicketboxUninstallPreflightOk') -ge $curUninstallBlock.IndexOf('TicketboxPreparePrivateResult') -or
    $curUninstallBlock -notmatch 'uninstall --from-installed --result' -or
    $curUninstallBlock -match '--request|installation\.json') {
    throw 'ISS uninstall entrypoints must verify LifecycleExe first and delegate both preflight and execution to single-authority TicketboxLifecycle.exe (--check-preflight / --from-installed)'
}
$stageKnownBlock = (($text -split 'function TicketboxStageHasOnlyKnownEntries\(', 2)[1] -split 'function TicketboxUpgradeStageReusableOrEmpty\(', 2)[0]
if ($stageKnownBlock -match 'Result := True;' -or
    $stageKnownBlock -notmatch 'DLLGetLastError = 18' -or
    $setupSecurityText -notmatch 'TicketboxFindNextFile\(Handle, FindData: LongWord\): LongBool;' -or
    $setupSecurityText -notmatch 'TicketboxFindClose\(Handle: LongWord\): LongBool;') {
    throw 'ISS Win32 enumeration must use LongBool and fail closed on invalid handles'
}
$ssInstallBlock = (($text -split 'procedure CurStepChanged\(CurStep: TSetupStep\);', 2)[1] -split 'if CurStep = ssPostInstall then', 2)[0]
if ($ssInstallBlock -match 'Exit;' -or $ssInstallBlock -notmatch 'Abort;') {
    throw 'ISS CurStepChanged(ssInstall) must call Abort on every security precondition failure'
}
if ($text -notmatch 'TicketboxReinstallRequested' -or
    $text -notmatch '/REINSTALL=YES' -or
    $text -notmatch 'RESTOREMODE' -or
    $text -notmatch 'rolled_back_to_previous' -or
    $text -notmatch 'upgrade_failed_restored_previous') {
    throw 'ISS must support R2 RESTOREMODE, /REINSTALL=YES, and U1 rolled_back_to_previous outcome presentation'
}

Write-Output 'ticketbox-windows-vnext-source-inputs-ok'
