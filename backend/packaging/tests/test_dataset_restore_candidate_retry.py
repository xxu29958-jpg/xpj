from __future__ import annotations

from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
CLUSTER = PACKAGING / "windows_postgresql_candidate_cluster.ps1"
INITDB = PACKAGING / "windows_postgresql_candidate_initdb.ps1"
CANDIDATE_RUNTIME = PACKAGING / "windows_postgresql_candidate_runtime.ps1"
FILESYSTEM = PACKAGING / "windows_dataset_restore_filesystem.ps1"
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
RESTORE_CONTRACTS = (
    PACKAGING / "windows_installed_dataset_reader.ps1",
    PACKAGING / "windows_installed_dataset_restore_artifacts.ps1",
    PACKAGING / "windows_installed_dataset_restore_verification.ps1",
    PACKAGING / "windows_dataset_restore_filesystem.ps1",
    PACKAGING / "windows_dataset_restore_reducer.ps1",
    PACKAGING / "windows_dataset_restore_database.ps1",
    PACKAGING / "windows_dataset_restore_runtime.ps1",
)

_CLUSTER_OWNER_FUNCTIONS = (
    "Get-TicketboxPostgresqlRestoreCandidateClusterObservation",
    "Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction",
    "Reset-TicketboxPostgresqlRestoreCandidateInitdbAttempt",
    "Initialize-TicketboxPostgresqlRestoreCandidateInitdbCapability",
    "Invoke-TicketboxPostgresqlRestoreCandidateInitdbOneShot",
    "Remove-TicketboxPostgresqlRestoreCandidateInitdbCapability",
    "Wait-TicketboxPostgresqlRestoreCandidateInitdbTerminal",
    "Initialize-TicketboxPostgresqlRestoreCandidateCluster",
)


def _cluster_owner_source(*names: str) -> str:
    source = "\n".join(path.read_text(encoding="utf-8-sig") for path in (CLUSTER, INITDB))
    return "\n".join(powershell_function(source, name) for name in names)


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_candidate_cluster_executes_failure_cleanup_then_exact_retry(
    tmp_path: Path,
) -> None:
    initializer = _cluster_owner_source(*_CLUSTER_OWNER_FUNCTIONS)
    root = str(tmp_path.resolve()).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$root = Join-Path '{root}' "$($PSVersionTable.PSEdition)-$($PSVersionTable.PSVersion.Major)"
$candidateRoot = Join-Path $root 'candidate'
$candidatePg = Join-Path $candidateRoot 'pgdata'
$candidateUploads = Join-Path $candidateRoot 'uploads'
$script:events = @()
$script:servicePresent = $false
$script:failInitdb = $true
$script:failPasswordRemoval = $true
$script:primaryObserved = $false
function Assert-TicketboxLifecycleOperationLease {{ param($Lock); $script:events += 'lease' }}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "unexpected fields: $Label" }}
}}
    function Assert-TicketboxInstalledDatasetRestorePathAuthority {{
        param($Paths)
        if (
            [string]$Paths.operation_id -cne '11111111-1111-4111-8111-111111111111' -or
            -not (Test-TicketboxPathEquals $Paths.data_root $root)
        ) {{ throw 'closed candidate path authority drifted' }}
        return $Paths
}}
function Test-TicketboxPathEquals {{
    param($Left, $Right)
    return [IO.Path]::GetFullPath([string]$Left) -ceq [IO.Path]::GetFullPath([string]$Right)
}}
function Get-TicketboxPathEntryKindNoFollow {{
    param($Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) {{ return 'File' }}
    if (Test-Path -LiteralPath $Path -PathType Container) {{ return 'Directory' }}
    return 'Missing'
}}
function New-TicketboxInitdbServiceImagePath {{
    param($ShawlPath, $ServiceName, $WorkingDirectory, $InitdbPath, $DataRoot, $PasswordFile, $StopTimeoutMs)
    if (
        -not (Test-TicketboxPathEquals $ShawlPath (Join-Path $root 'install\shawl\shawl.exe')) -or
        [string]$ServiceName -cne 'TicketboxRestore' -or
        -not (Test-TicketboxPathEquals $WorkingDirectory (Join-Path $root 'install\pg\bin')) -or
        -not (Test-TicketboxPathEquals $InitdbPath (Join-Path $root 'install\pg\bin\initdb.exe')) -or
        -not (Test-TicketboxPathEquals $DataRoot $candidatePg) -or
        -not (Test-TicketboxPathEquals $PasswordFile (Join-Path $candidateRoot '.initdb-password')) -or
        [int]$StopTimeoutMs -ne 1000
    ) {{ throw 'initdb image inputs drifted' }}
    return 'init-image'
}}
function Test-TicketboxServiceExists {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service existence probe' }}
    return $script:servicePresent
}}
function Get-TicketboxServiceExecutablePath {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service executable probe' }}
    return (Join-Path $root 'install\shawl\shawl.exe')
}}
function Assert-TicketboxReleaseServiceIdentity {{ param($Name, $InstalledConfig, $TargetConfig, [switch]$AllowTargetSidTypePending) }}
function Get-TicketboxServiceRuntimeSnapshot {{
    param($Name)
    return [pscustomobject]@{{ State = 'stopped'; ExitCode = 0; ServiceSpecificExitCode = 0 }}
}}
function Invoke-TicketboxScChecked {{
    $values = @($args[0])
    if (($values -join '|') -cne 'create|TicketboxRestore|binPath=|init-image|start=|demand|obj=|LocalSystem') {{
        throw "unexpected initdb SCM create: $($values -join '|')"
    }}
    $script:events += 'service-create'
    $script:servicePresent = $true
}}
function Set-TicketboxServiceIdentityContract {{
    param($Name, $LogonAccount, $SidType)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        [string]$LogonAccount -cne 'LocalSystem' -or
        [string]$SidType -cne 'unrestricted'
    ) {{ throw 'initdb service identity drifted' }}
    $script:events += 'identity'
}}
function Assert-TicketboxServiceStartMode {{
    param($Name, $ExpectedStartMode)
    if ([string]$Name -cne 'TicketboxRestore' -or [string]$ExpectedStartMode -cne 'Manual') {{
        throw 'initdb service start mode drifted'
    }}
    $script:events += 'start-mode'
}}
function Assert-TicketboxServiceHasNoFailureActions {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong failure-actions probe' }}
    $script:events += 'no-failure-actions'
}}
function Assert-TicketboxInitdbServiceCommand {{
    param($Name, $ExpectedShawl, $ExpectedServiceName, $ExpectedWorkingDirectory, $ExpectedInitdb, $ExpectedDataRoot, $ExpectedPasswordFile, $ExpectedStopTimeoutMs, $ExpectedImagePath)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        -not (Test-TicketboxPathEquals $ExpectedShawl (Join-Path $root 'install\shawl\shawl.exe')) -or
        [string]$ExpectedServiceName -cne 'TicketboxRestore' -or
        -not (Test-TicketboxPathEquals $ExpectedWorkingDirectory (Join-Path $root 'install\pg\bin')) -or
        -not (Test-TicketboxPathEquals $ExpectedInitdb (Join-Path $root 'install\pg\bin\initdb.exe')) -or
        -not (Test-TicketboxPathEquals $ExpectedDataRoot $candidatePg) -or
        -not (Test-TicketboxPathEquals $ExpectedPasswordFile (Join-Path $candidateRoot '.initdb-password')) -or
        [int]$ExpectedStopTimeoutMs -ne 1000 -or
        [string]$ExpectedImagePath -cne 'init-image'
    ) {{ throw 'initdb command authority drifted' }}
    $script:events += 'initdb-command'
}}
function Get-TicketboxServiceSid {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service SID probe' }}
    return 'NT SERVICE\TicketboxRestore'
}}
function Set-TicketboxExactDirectoryAcl {{
    param($Path, $Accounts, $OwnerAccount, [switch]$Recurse)
    if (
        -not (Test-TicketboxPathEquals $Path $candidateRoot) -or
        (@($Accounts) -join '|') -cne 'SYSTEM|BUILTIN\Administrators|NT SERVICE\TicketboxRestore' -or
        [string]$OwnerAccount -cne 'SYSTEM' -or
        -not $Recurse
    ) {{ throw 'candidate root ACL drifted' }}
    $script:events += 'acl'
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $OwnerAccount)
    if (-not (Test-TicketboxPathEquals $Path (Join-Path $candidateRoot '.initdb-password'))) {{
        throw "wrong password path: $Path"
    }}
    if (
        [string]$Text -cne 'protected-secret' -or
        (@($FullControlAccounts) -join '|') -cne 'SYSTEM|BUILTIN\Administrators|NT SERVICE\TicketboxRestore' -or
        [string]$OwnerAccount -cne 'SYSTEM'
    ) {{ throw 'wrong protected password contract' }}
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText([string]$Path, [string]$Text)
    $script:events += 'password-write'
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $OwnerAccount)
    if (
        -not (Test-TicketboxPathEquals $Path (Join-Path $candidateRoot '.initdb-password')) -or
        (@($FullControlAccounts) -join '|') -cne 'SYSTEM|BUILTIN\Administrators|NT SERVICE\TicketboxRestore' -or
        [string]$OwnerAccount -cne 'SYSTEM'
    ) {{ throw 'password retirement authority drifted' }}
    if ($script:failPasswordRemoval) {{ throw 'injected password retirement failure' }}
    [IO.File]::Delete([string]$Path)
    $script:events += 'password-remove'
}}
function Invoke-TicketboxOwnedOneShotService {{
    param($Name, $ExpectedExecutable, $ExpectedRuntimeExecutables, $TimeoutMilliseconds, $PollMilliseconds)
    $expectedShawl = Join-Path $root 'install\shawl\shawl.exe'
    $expectedInitdb = Join-Path $root 'install\pg\bin\initdb.exe'
    $runtimeExecutables = @($ExpectedRuntimeExecutables)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        -not (Test-TicketboxPathEquals $ExpectedExecutable $expectedShawl) -or
        $runtimeExecutables.Count -ne 2 -or
        -not (Test-TicketboxPathEquals $runtimeExecutables[0] $expectedShawl) -or
        -not (Test-TicketboxPathEquals $runtimeExecutables[1] $expectedInitdb) -or
        [int]$TimeoutMilliseconds -ne 1000 -or
        [int]$PollMilliseconds -ne 10
    ) {{ throw 'one-shot authority drifted' }}
    $script:events += 'one-shot'
    [IO.Directory]::CreateDirectory($candidatePg) | Out-Null
    if ($script:failInitdb) {{
        [IO.File]::WriteAllText((Join-Path $candidatePg 'partial'), 'partial')
        return [pscustomobject]@{{ ExitCode = 1; ServiceSpecificExitCode = 0 }}
    }}
    [IO.Directory]::CreateDirectory((Join-Path $candidatePg 'global')) | Out-Null
    foreach ($relative in @('PG_VERSION', 'global\pg_control', 'postgresql.conf', 'pg_hba.conf')) {{
        [IO.File]::WriteAllText((Join-Path $candidatePg $relative), 'ready')
    }}
    return [pscustomobject]@{{ ExitCode = 0; ServiceSpecificExitCode = 0 }}
}}
function Remove-TicketboxOwnedServiceIfExists {{
    param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        -not (Test-TicketboxPathEquals $ExpectedExecutable (Join-Path $root 'install\shawl\shawl.exe')) -or
        [int]$TimeoutMilliseconds -ne 1000 -or
        [int]$PollMilliseconds -ne 10
    ) {{ throw 'initdb service retirement authority drifted' }}
    $script:servicePresent = $false
    $script:events += 'service-remove'
}}
function Remove-TicketboxDataRootExact {{
    param($Path)
    if (-not (Test-TicketboxPathEquals $Path $candidatePg)) {{ throw 'broad cleanup target' }}
    if (Test-Path -LiteralPath $Path) {{ Remove-Item -LiteralPath $Path -Recurse -Force }}
    $script:events += 'pgdata-remove'
}}
function Throw-TicketboxOperationFailure {{
    param($Failure, $CleanupFailures)
    if ($null -ne $Failure) {{
        $message = [string]$Failure.Message
        if ([string]::IsNullOrEmpty($message)) {{ $message = [string]$Failure.Exception.Message }}
        if ($message -notlike '*initdb failed*') {{ throw "wrong primary: $message" }}
        $script:primaryObserved = $true
        throw 'expected initdb failure'
    }}
    if (@($CleanupFailures).Count -ne 0) {{ throw 'cleanup failure' }}
}}
function Set-TicketboxPostgresqlLoopbackConfiguration {{
    param($PgData, $Port)
    if (-not (Test-TicketboxPathEquals $PgData $candidatePg) -or [int]$Port -ne 5432) {{
        throw 'loopback authority drifted'
    }}
    $script:events += 'loopback'
}}
{initializer}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = (Join-Path $root 'install'); DataRoot = $root; PgPort = 5432 }}
    Release = [pscustomobject]@{{
        pg_recovery_service_name = 'TicketboxRestore'
        stop_timeout_ms = 1000
        database_tool_timeout_ms = 1000
        service_state_timeout_ms = 1000
        service_poll_interval_ms = 10
        service_logon_account = 'LocalSystem'
        service_sid_type = 'unrestricted'
    }}
}}
$paths = [pscustomobject]@{{
    operation_id = '11111111-1111-4111-8111-111111111111'
    data_root = $root
    candidate_root = $candidateRoot
    candidate_pgdata = $candidatePg
    candidate_uploads = $candidateUploads
}}
$bootstrap = [pscustomobject]@{{ SuperuserPassword = 'protected-secret' }}
$failed = $false
$caughtText = ''
try {{
    Initialize-TicketboxPostgresqlRestoreCandidateCluster `
        $subject '11111111-1111-4111-8111-111111111111' $paths $bootstrap 'lock'
}} catch {{ $failed = $true; $caughtText = [string]$_ }}
if (-not $failed -or -not $script:primaryObserved) {{
    throw "initdb primary failure was not preserved: $caughtText; events=$($script:events -join ',')"
}}
if (
    -not $script:servicePresent -or
    -not (Test-Path -LiteralPath $candidatePg) -or
    -not (Test-Path -LiteralPath (Join-Path $candidateRoot '.initdb-password'))
) {{ throw 'password cleanup failure destroyed retry authority' }}
$failureEvents = $script:events -join ','
foreach ($required in @('lease', 'service-create', 'password-write', 'one-shot')) {{
    if ($failureEvents -notlike "*$required*") {{ throw "failure path missed $required" }}
}}
foreach ($forbidden in @('service-remove', 'pgdata-remove')) {{
    if ($failureEvents -like "*$forbidden*") {{ throw "failure path crossed $forbidden" }}
}}
$script:events = @()
$script:failInitdb = $false
$script:failPasswordRemoval = $false
Initialize-TicketboxPostgresqlRestoreCandidateCluster `
    $subject '11111111-1111-4111-8111-111111111111' $paths $bootstrap 'lock'
foreach ($relative in @('PG_VERSION', 'global\pg_control', 'postgresql.conf', 'pg_hba.conf')) {{
    if (-not (Test-Path -LiteralPath (Join-Path $candidatePg $relative) -PathType Leaf)) {{ throw "missing $relative" }}
}}
if ($script:servicePresent -or (Test-Path -LiteralPath (Join-Path $candidateRoot '.initdb-password'))) {{
    throw 'success left initdb authority behind'
}}
$successEvents = $script:events -join ','
if ($successEvents -notlike '*one-shot*password-remove*service-remove*loopback*') {{
    throw "success ordering drifted: $successEvents"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-candidate-cluster.ps1",
        timeout=30,
    )
