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

function Assert-RegexAll {
    param(
        [string]$Content,
        [string[]]$Patterns,
        [string]$Message
    )
    foreach ($pattern in $Patterns) {
        if ($Content -notmatch $pattern) { throw $Message }
    }
}

function Assert-RegexNone {
    param(
        [string]$Content,
        [string[]]$Patterns,
        [string]$Message
    )
    foreach ($pattern in $Patterns) {
        if ($Content -match $pattern) { throw $Message }
    }
}

function Assert-TicketboxIssCore {
    param([string]$Text, [string]$SetupSecurityText, [string]$PrivateResultText)
    foreach ($token in @(
            'windows_lifecycle_receipt.ps1', 'windows_owner_handoff.ps1',
            'install_bundled_services.ps1', 'prepare_bundled_upgrade.ps1',
            'DATABASE_GENERATION_PROGRAM.json', 'TicketboxBackendLauncher.exe',
            'ExtractTemporaryFile'
        )) {
        if ($Text.Contains($token)) { throw "ISS still names retired path $token" }
    }
    Assert-RegexAll $Text @('PrepareToInstall') 'ISS missing read-only PrepareToInstall'
    Assert-RegexAll $Text @('TicketboxExactActiveCanContinue', 'TicketboxCommittedReplayCanContinue') `
        'ISS must allow only exact active or committed result replay'
    Assert-RegexAll $Text @('CloseApplications=no') 'ISS must not let Restart Manager own pre-copy lifecycle mutation'
    Assert-RegexNone $Text @('CloseApplications=yes') 'ISS must not let Restart Manager own pre-copy lifecycle mutation'
    Assert-RegexAll $Text @('onlyifdoesntexist', 'TicketboxExpectedReleaseManifestSha256') `
        'ISS exact resume requires immutable materialization and manifest binding'
    Assert-RegexAll $Text @('Utf8Encode\(Payload\)') 'ISS must write the lifecycle request as UTF-8'
    if ($Text.Contains('AnsiString(Payload)')) { throw 'ISS must not ANSI-narrow the lifecycle request JSON' }
    Assert-RegexAll $Text @('TicketboxLifecycle.exe') 'ISS must invoke the installed TicketboxLifecycle.exe'
    Assert-RegexAll $Text @('(?m)^\s*\[Run\]\s*$', '\{code:TicketboxLifecycleParams\}') `
        'ISS must invoke the installed coordinator from normal [Run]'
    Assert-RegexAll $Text @('CurStepChanged', 'ssPostInstall') 'ISS must observe lifecycle result after [Run]'
    $uninstallSplit = $Text -split 'function TicketboxUninstallPreflightOk\(', 2
    $afterUninstall = ($uninstallSplit[1] -split 'procedure DeinitializeUninstall;', 2)[1]
    Assert-RegexNone $uninstallSplit[0] @('Exec\(') 'ISS install [Code] must not own lifecycle mutation or exception-based completion'
    Assert-RegexNone $afterUninstall @('Exec\(') 'ISS install [Code] must not own lifecycle mutation or exception-based completion'
    Assert-RegexNone $Text @('RaiseException') 'ISS install [Code] must not own lifecycle mutation or exception-based completion'
    Assert-RegexAll $Text @('GetCustomSetupExitCode', 'TicketboxInstallFailed', 'FinishedHeadingLabel\.Caption') `
        'ISS must expose failed postconditions in the final page and process exit code'
    Assert-RegexNone $Text @('(?i)Flags:[^\r\n]*(nowait|shellexec|ignoreerrors|postinstall)') `
        'ISS lifecycle [Run] entries must be elevated, waited, and terminal'
    Assert-RegexNone $Text @('last-result\.json') 'ISS must use the protected invocation result channel'
    Assert-RegexAll $Text @('#include "setup_private_result\.iss"') 'ISS must use the protected invocation result channel'
    Assert-RegexAll $PrivateResultText @('ticketbox-install-result\.json') 'ISS must use the protected invocation result channel'
    Assert-RegexNone $PrivateResultText @('\{tmp\}') 'ISS must use the protected invocation result channel'
    Assert-RegexAll $SetupSecurityText @('SetSecurityInfo', 'GetSecurityInfo') `
        'ISS setup coordination security is not closed and handle-verified'
    Assert-RegexNone $SetupSecurityText @('SetKernelObjectSecurity') `
        'ISS setup coordination security is not closed and handle-verified'
    Assert-RegexAll $PrivateResultText @('TicketboxCreateProtectedDirectory') `
        'ISS setup coordination security is not closed and handle-verified'
    Assert-RegexAll $Text @('PrivilegesRequired=admin') 'ISS must require UAC'
}

function Assert-TicketboxIssUpgradeAndUninstall {
    param([string]$Text, [string]$SetupSecurityText, [string]$BuildText)
    Assert-RegexAll $Text @(
        'Ticketbox-UpgradeStage\\\{#ReleaseId\}\\lifecycle\\TicketboxLifecycle\.exe',
        '--staged-release-root',
        'TicketboxPathAbsentOrAdminProtectedDir',
        'TicketboxUpgradeNeedsVcRedist'
    ) 'ISS managed upgrade must stage in admin-protected Ticketbox-UpgradeStage and gate VC redist'
    Assert-RegexAll $Text @('/UPGRADE=YES') 'ISS managed upgrade recovery hint must instruct rerunning with /UPGRADE=YES'
    Assert-RegexNone $Text @('TicketboxParseRemovedConnectorState|TicketboxManagedConnectorBlocksUpgrade') `
        'ISS must not duplicate connector business-state parsing owned by Lifecycle'
    Assert-RegexAll $BuildText @(
        'upgrade_startup_probe', 'upgrade --help', 'rollback_upgrade_startup_probe',
        'uninstall_startup_probe', 'reinstall_startup_probe', 'purge_data_startup_probe'
    ) 'build_installer.ps1 must probe frozen TicketboxLifecycle.exe upgrade, rollback-upgrade, uninstall, reinstall and purge-data --help'
    Assert-RegexAll $Text @(
        'Uninstallable=yes', 'UninstallFilesDir=\{commoncf64\}\\Ticketbox\\uninstall',
        'CurUninstallStepChanged', 'usUninstall', 'TicketboxUninstallResultIsCommitted', 'TicketboxAbortUninstall'
    ) 'ISS must enable gated Uninstallable=yes via CurUninstallStepChanged(usUninstall) with protected UninstallFilesDir and zero [UninstallRun]/[UninstallDelete]'
    Assert-RegexNone $Text @('(?m)^\s*\[UninstallRun\]\s*$', '(?m)^\s*\[UninstallDelete\]\s*$') `
        'ISS must enable gated Uninstallable=yes via CurUninstallStepChanged(usUninstall) with protected UninstallFilesDir and zero [UninstallRun]/[UninstallDelete]'
    $preflightBlock = (($Text -split 'function TicketboxUninstallPreflightOk\(', 2)[1] -split 'procedure TicketboxReportUninstallRefused', 2)[0]
    $initUninstallBlock = (($Text -split 'function InitializeUninstall: Boolean;', 2)[1] -split 'procedure CurUninstallStepChanged', 2)[0]
    $curUninstallBlock = (($Text -split 'procedure CurUninstallStepChanged\(CurUninstallStep: TUninstallStep\);', 2)[1] -split 'procedure DeinitializeUninstall;', 2)[0]
    $uninstallMsg = 'ISS uninstall entrypoints must verify LifecycleExe first and delegate both preflight and execution to single-authority TicketboxLifecycle.exe (--check-preflight / --from-installed)'
    Assert-RegexNone $Text @('TicketboxHasJsonUnicodeEscape|TicketboxJsonTopLevelUniqueString|TicketboxWriteUninstallRequest') $uninstallMsg
    Assert-RegexAll $preflightBlock @('uninstall --check-preflight') $uninstallMsg
    Assert-RegexNone $preflightBlock @('--request|--result|DeleteFile\(|SaveStringToFile\(') $uninstallMsg
    Assert-RegexNone $initUninstallBlock @('Exec\(|TicketboxAcquireSetupLease|TicketboxPreparePrivateResult|TicketboxAbortUninstall|DeleteFile\(') $uninstallMsg
    Assert-RegexAll $initUninstallBlock @('TicketboxPathIsNonReparseType\(LifecycleExe, False\)', 'TicketboxUninstallPreflightOk') $uninstallMsg
    Assert-RegexAll $curUninstallBlock @('TicketboxPathIsNonReparseType\(LifecycleExe, False\)', 'TicketboxUninstallPreflightOk', 'uninstall --from-installed --result') $uninstallMsg
    Assert-RegexNone $curUninstallBlock @('--request|installation\.json') $uninstallMsg
    if ($curUninstallBlock.IndexOf('TicketboxUninstallPreflightOk') -ge $curUninstallBlock.IndexOf('TicketboxPreparePrivateResult')) {
        throw $uninstallMsg
    }
    $stageKnownBlock = (($Text -split 'function TicketboxStageHasOnlyKnownEntries\(', 2)[1] -split 'function TicketboxUpgradeStageReusableOrEmpty\(', 2)[0]
    $enumMsg = 'ISS Win32 enumeration must use LongBool and fail closed on invalid handles'
    Assert-RegexNone $stageKnownBlock @('Result := True;') $enumMsg
    Assert-RegexAll $stageKnownBlock @('DLLGetLastError = 18') $enumMsg
    Assert-RegexAll $SetupSecurityText @('TicketboxFindNextFile\(Handle, FindData: LongWord\): LongBool;', 'TicketboxFindClose\(Handle: LongWord\): LongBool;') $enumMsg
    $ssInstallBlock = (($Text -split 'procedure CurStepChanged\(CurStep: TSetupStep\);', 2)[1] -split 'if CurStep = ssPostInstall then', 2)[0]
    Assert-RegexNone $ssInstallBlock @('Exit;') 'ISS CurStepChanged(ssInstall) must call Abort on every security precondition failure'
    Assert-RegexAll $ssInstallBlock @('Abort;') 'ISS CurStepChanged(ssInstall) must call Abort on every security precondition failure'
    Assert-RegexAll $Text @('TicketboxReinstallRequested', '/REINSTALL=YES', 'RESTOREMODE', 'rolled_back_to_previous', 'upgrade_failed_restored_previous') `
        'ISS must support R2 RESTOREMODE, /REINSTALL=YES, and U1 rolled_back_to_previous outcome presentation'
}

$text = Get-Content -LiteralPath $iss -Raw
$setupSecurityText = Get-Content -LiteralPath $setupSecurity -Raw
$privateResultText = Get-Content -LiteralPath $privateResult -Raw
$buildText = Get-Content -LiteralPath $buildInstaller -Raw
Assert-TicketboxIssCore $text $setupSecurityText $privateResultText
Assert-TicketboxIssUpgradeAndUninstall $text $setupSecurityText $buildText

Write-Output 'ticketbox-windows-vnext-source-inputs-ok'
