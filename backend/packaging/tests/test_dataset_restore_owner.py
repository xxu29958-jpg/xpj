from __future__ import annotations

from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
CONTRACT = PACKAGING / "windows_installed_dataset_contract.ps1"
CLUSTER = PACKAGING / "windows_postgresql_candidate_cluster.ps1"


def test_restore_does_not_ship_unowned_clone_identity_producer() -> None:
    launch = (PACKAGING / "launch.py").read_text(encoding="utf-8")
    restore_service = (
        PACKAGING.parent / "app" / "services" / "dataset_restore_service.py"
    ).read_text(encoding="utf-8")
    restore_action = (
        PACKAGING.parent / "app" / "database" / "_dataset_restore_action.py"
    ).read_text(encoding="utf-8")

    assert "--clone-dataset-id" not in launch
    assert "clone_dataset_id" not in restore_service
    assert "clone_dataset_id" not in restore_action


def test_restore_owner_is_explicit_durable_isolated_and_h1_published() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    cluster = CLUSTER.read_text(encoding="utf-8-sig")

    assert "[Parameter(Mandatory = $true)][string]$BackupGeneration" in restore
    assert "Get-TicketboxInstalledDatasetRestoreRequest" in contract
    assert "Resolve-TicketboxInstalledDatasetRestoreNextAction" in contract
    assert "New-TicketboxInstalledDatasetRestoreRequest" in restore
    assert restore.rindex("New-TicketboxInstalledDatasetRestoreRequest") < restore.rindex(
        "Stop-TicketboxInstalledDatasetWriters"
    )
    assert "Initialize-TicketboxPostgresqlRestoreCandidateCluster" in cluster
    assert "Start-TicketboxPostgresqlRestoreCandidateService" in cluster
    assert "Initialize-TicketboxPostgresqlRestoreCandidateDatabase" in cluster
    assert "New-TicketboxPostgresqlRestoreCandidate" not in cluster
    assert "Invoke-TicketboxInstalledDatabaseGeneration" in restore
    assert "Publish-TicketboxDatabaseGenerationCurrent" not in restore
    assert "LastWriteTime" not in restore
    assert "latest" not in restore.casefold()
    assert "function Assert-TicketboxInstalledDatasetServiceAuthority" in contract
    authority_check = restore.index("Assert-TicketboxInstalledDatasetServiceAuthority")
    first_stop = restore.index("Stop-TicketboxInstalledDatasetWriters", authority_check)
    assert authority_check < first_stop
    service_authority = powershell_function(
        contract,
        "Assert-TicketboxInstalledDatasetServiceAuthority",
    )
    assert "[string]$identity.BackendServiceName" in service_authority
    assert "[string]$identity.PgServiceName" in service_authority
    assert "Assert-TicketboxReleaseServiceIdentity" in service_authority
    assert "Assert-TicketboxPgServiceCommand" in service_authority
    assert '"app\\backups"' not in contract
    assert '"backups"' in contract
    assert "[string]$decoded.release_id -cne [string]$Subject.Manifest.Sha256" in contract


def test_restore_candidate_uses_official_frozen_restore_and_exact_role_owner() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    cluster = CLUSTER.read_text(encoding="utf-8-sig")

    assert '"--isolated-dataset-restore"' in restore
    assert "--restore-role" in restore
    assert "ticketbox_owner" in restore
    assert "function Assert-TicketboxInstalledPostgresToolArtifact" in contract
    assert restore.count("Assert-TicketboxInstalledPostgresToolArtifact") >= 2
    owner_body = restore.split("$inspection =", maxsplit=1)[1]
    assert owner_body.index("Assert-TicketboxInstalledPostgresToolArtifact") < owner_body.index(
        "Stop-TicketboxInstalledDatasetWriters"
    )
    assert "Invoke-TicketboxBoundedNativeProcess" in cluster
    assert "initdb.exe" in cluster
    assert "New-TicketboxInitdbServiceImagePath" in cluster
    assert "Invoke-TicketboxOwnedOneShotService" in cluster
    assert '"obj=", ([string]$release.service_logon_account)' in cluster
    assert "New-TicketboxPgServiceImagePath" in cluster
    assert "Set-TicketboxExactDirectoryAcl" in cluster
    assert "Assert-TicketboxReleaseServiceIdentity" in cluster
    incomplete_cluster_cleanup = cluster.split(
        'if ((Get-TicketboxPathEntryKindNoFollow $pgVersion) -cne "File") {',
        maxsplit=1,
    )[1].split("Invoke-TicketboxScChecked", maxsplit=1)[0]
    assert "-ExpectedExecutable $ownedServiceExecutable" in incomplete_cluster_cleanup
    assert "-ExpectedExecutable $shawl" not in incomplete_cluster_cleanup
    removal = powershell_function(
        cluster,
        "Remove-TicketboxPostgresqlRestoreCandidateService",
    )
    assert "Assert-TicketboxPgServiceCommand" in removal
    assert "Assert-TicketboxReleaseServiceIdentity" in removal


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_candidate_cluster_executes_failure_cleanup_then_exact_retry(
    tmp_path: Path,
) -> None:
    initializer = powershell_function(
        CLUSTER.read_text(encoding="utf-8-sig"),
        "Initialize-TicketboxPostgresqlRestoreCandidateCluster",
    )
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
$script:primaryObserved = $false
function Assert-TicketboxLifecycleOperationLease {{ param($Lock); $script:events += 'lease' }}
function Get-TicketboxInstalledDatasetRestorePaths {{
    param($DataRoot, $OperationId)
    return [pscustomobject]@{{
        candidate_root = $candidateRoot
        candidate_pgdata = $candidatePg
        candidate_uploads = $candidateUploads
    }}
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
function Throw-TicketboxDatabaseGenerationOperationFailure {{
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
if ($script:servicePresent -or (Test-Path -LiteralPath $candidatePg)) {{ throw 'failed cluster was not cleaned' }}
$failureEvents = $script:events -join ','
foreach ($required in @('lease', 'service-create', 'password-write', 'one-shot', 'password-remove', 'service-remove', 'pgdata-remove')) {{
    if ($failureEvents -notlike "*$required*") {{ throw "failure path missed $required" }}
}}
$script:events = @()
$script:failInitdb = $false
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


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_candidate_service_executes_exact_scm_acl_and_readiness_contract(
    tmp_path: Path,
) -> None:
    starter = powershell_function(
        CLUSTER.read_text(encoding="utf-8-sig"),
        "Start-TicketboxPostgresqlRestoreCandidateService",
    )
    root = str(tmp_path.resolve()).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$root = Join-Path '{root}' "$($PSVersionTable.PSEdition)-$($PSVersionTable.PSVersion.Major)"
$candidatePg = Join-Path $root 'candidate\pgdata'
$install = Join-Path $root 'install'
$pgCtl = Join-Path $install 'pg\bin\pg_ctl.exe'
$pgIsReady = Join-Path $install 'pg\bin\pg_isready.exe'
$script:events = @()
$script:servicePresent = $false
$script:createCount = 0
function Assert-TicketboxLifecycleOperationLease {{
    param($Lock)
    if ([string]$Lock -cne 'lock') {{ throw 'wrong lifecycle lease' }}
    $script:events += 'lease'
}}
function New-TicketboxPgServiceImagePath {{
    param($PgCtlPath, $ServiceName, $DataRoot)
    if (
        [string]$PgCtlPath -cne $pgCtl -or
        [string]$ServiceName -cne 'TicketboxRestore' -or
        [string]$DataRoot -cne $candidatePg
    ) {{ throw 'service image authority drifted' }}
    return 'candidate-service-image'
}}
function Test-TicketboxServiceExists {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service existence probe' }}
    return $script:servicePresent
}}
function Invoke-TicketboxScChecked {{
    $values = @($args[0])
    if (($values -join '|') -cne 'create|TicketboxRestore|binPath=|candidate-service-image|start=|demand|obj=|LocalSystem') {{
        throw "unexpected SCM create: $($values -join '|')"
    }}
    $script:events += 'scm-create'
    $script:servicePresent = $true
    $script:createCount += 1
}}
function Assert-TicketboxServiceOwnership {{
    param($Name, $ExpectedExecutable)
    if ([string]$Name -cne 'TicketboxRestore' -or [string]$ExpectedExecutable -cne $pgCtl) {{
        throw 'service ownership drifted'
    }}
    $script:events += 'ownership'
}}
function Assert-TicketboxPgServiceCommand {{
    param($Name, $ExpectedExecutable, $ExpectedServiceName, $ExpectedDataRoot)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        [string]$ExpectedExecutable -cne $pgCtl -or
        [string]$ExpectedServiceName -cne 'TicketboxRestore' -or
        [string]$ExpectedDataRoot -cne $candidatePg
    ) {{ throw 'service command drifted' }}
    $script:events += 'command'
}}
function Set-TicketboxServiceIdentityContract {{
    param($Name, $LogonAccount, $SidType)
    if ([string]$Name -cne 'TicketboxRestore' -or [string]$LogonAccount -cne 'LocalSystem' -or [string]$SidType -cne 'unrestricted') {{
        throw 'service identity drifted'
    }}
    $script:events += 'identity'
}}
function Assert-TicketboxServiceDependencies {{
    param($Name, $ExpectedDependencies)
    if ([string]$Name -cne 'TicketboxRestore' -or @($ExpectedDependencies).Count -ne 0) {{
        throw 'service dependencies drifted'
    }}
    $script:events += 'dependencies'
}}
function Get-TicketboxServiceSid {{
    param($Name)
    if ([string]$Name -cne 'TicketboxRestore') {{ throw 'wrong service SID probe' }}
    return 'NT SERVICE\TicketboxRestore'
}}
function Set-TicketboxExactDirectoryAcl {{
    param($Path, $Accounts, $OwnerAccount, [switch]$Recurse)
    if (
        [string]$Path -cne $candidatePg -or
        (@($Accounts) -join '|') -cne 'SYSTEM|BUILTIN\Administrators|NT SERVICE\TicketboxRestore' -or
        [string]$OwnerAccount -cne 'SYSTEM' -or
        -not $Recurse
    ) {{ throw 'candidate ACL drifted' }}
    $script:events += 'acl'
}}
function Start-TicketboxOwnedServiceIfExists {{
    param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds)
    if (
        [string]$Name -cne 'TicketboxRestore' -or
        [string]$ExpectedExecutable -cne $pgCtl -or
        [int]$TimeoutMilliseconds -ne 1000 -or
        [int]$PollMilliseconds -ne 10
    ) {{ throw 'service start drifted' }}
    $script:events += 'start'
}}
function Wait-TicketboxPostgresqlCandidateReady {{
    param($PgIsReadyPath, $Port, $TimeoutMilliseconds, $PollMilliseconds)
    if (
        [string]$PgIsReadyPath -cne $pgIsReady -or
        [int]$Port -ne 5432 -or
        [int]$TimeoutMilliseconds -ne 2000 -or
        [int]$PollMilliseconds -ne 20
    ) {{ throw 'candidate readiness drifted' }}
    $script:events += 'ready'
}}
{starter}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = $install; PgPort = 5432 }}
    Release = [pscustomobject]@{{
        pg_recovery_service_name = 'TicketboxRestore'
        service_logon_account = 'LocalSystem'
        service_sid_type = 'unrestricted'
        service_state_timeout_ms = 1000
        service_poll_interval_ms = 10
        postgres_ready_timeout_ms = 2000
        postgres_ready_poll_interval_ms = 20
    }}
}}
$paths = [pscustomobject]@{{ candidate_pgdata = $candidatePg }}
Start-TicketboxPostgresqlRestoreCandidateService $subject $paths 'lock'
$expected = 'lease|scm-create|ownership|command|identity|dependencies|acl|start|ready'
if (($script:events -join '|') -cne $expected) {{
    throw "candidate service path incomplete: $($script:events -join '|')"
}}
if ($script:createCount -ne 1) {{ throw 'candidate service was not created exactly once' }}
$script:events = @()
Start-TicketboxPostgresqlRestoreCandidateService $subject $paths 'lock'
$retryExpected = 'lease|ownership|command|identity|dependencies|acl|start|ready'
if (($script:events -join '|') -cne $retryExpected -or $script:createCount -ne 1) {{
    throw "existing candidate service was recreated: $($script:events -join '|')"
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-candidate-service.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_candidate_database_executes_absent_existing_and_secret_lifetime(
    tmp_path: Path,
) -> None:
    initializer = powershell_function(
        CLUSTER.read_text(encoding="utf-8-sig"),
        "Initialize-TicketboxPostgresqlRestoreCandidateDatabase",
    )
    root = str(tmp_path.resolve()).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$root = Join-Path '{root}' "$($PSVersionTable.PSEdition)-$($PSVersionTable.PSVersion.Major)"
$install = Join-Path $root 'install'
$script:events = @()
$script:commands = @()
$script:catalogExists = $false
$script:disposeCount = 0
$script:failLabel = ''
$script:activeSecret = $null
function Assert-TicketboxLifecycleOperationLease {{
    param($Lock)
    if ([string]$Lock -cne 'lock') {{ throw 'wrong lifecycle lease' }}
    $script:events += 'lease'
}}
function ConvertTo-TicketboxPostgresqlSecureString {{
    param($Text, $Label)
    if ([string]$Text -cne 'protected-secret' -or [string]$Label -cne 'restore candidate superuser password') {{
        throw 'superuser secret binding drifted'
    }}
    $secret = [pscustomobject]@{{ Value = [string]$Text }}
    $secret | Add-Member -MemberType ScriptMethod -Name Dispose -Value {{ $script:disposeCount += 1 }}
    $script:activeSecret = $secret
    return $secret
}}
function New-TicketboxDatabaseGenerationEmptyRoleSql {{
    param($OperationId, $RuntimeVerifier, $MigratorVerifier, $BackupVerifier, $MigratorValidUntilUtc)
    if (
        [string]$OperationId -cne '11111111-1111-4111-8111-111111111111' -or
        [string]$RuntimeVerifier -cne 'runtime-verifier' -or
        [string]$MigratorVerifier -cne 'migrator-verifier' -or
        [string]$BackupVerifier -cne 'backup-verifier' -or
        $MigratorValidUntilUtc -le [DateTime]::UtcNow
    ) {{ throw 'role SQL inputs drifted' }}
    return 'ROLE-SQL'
}}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        OwnerRole = 'ticketbox_owner'
        RuntimeRole = 'ticketbox_runtime'
        MigratorRole = 'ticketbox_migrator'
    }}
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{
    param($Authority, $SuperuserPassword, $TargetDatabase)
    if ([int]$Authority.Port -ne 5432 -or $SuperuserPassword -ne $script:activeSecret -or [string]$TargetDatabase -cne 'ticketbox') {{
        throw 'catalog authority drifted'
    }}
    return [pscustomobject]@{{ Exists = $script:catalogExists }}
}}
function New-TicketboxDatabaseRuntimeAclSql {{
    param([switch]$PreserveRuntimeFence)
    if (-not $PreserveRuntimeFence) {{ throw 'runtime fence was not preserved' }}
    return 'ACL-SQL'
}}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    if (
        [string]$Authority.Schema -cne 'ticketbox-postgresql-host-authority-v1' -or
        [int]$Authority.Port -ne 5432 -or
        [string]$Authority.PsqlPath -cne (Join-Path $install 'pg\bin\psql.exe') -or
        [string]$Role -cne 'postgres' -or
        $Password -ne $script:activeSecret
    ) {{ throw 'database command authority drifted' }}
    if ([string]$Label -ceq $script:failLabel) {{ throw 'expected database command failure' }}
    $script:commands += [pscustomobject]@{{ Database = [string]$Database; Label = [string]$Label; Sql = [string]$Sql }}
}}
function Assert-TicketboxDatabaseRolePolicy {{
    param($Authority, $SuperuserPassword, $Phase)
    if ([int]$Authority.Port -ne 5432 -or $SuperuserPassword -ne $script:activeSecret -or [string]$Phase -cne 'fenced') {{
        throw 'role policy drifted'
    }}
    $script:events += 'policy'
}}
{initializer}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = $install; PgPort = 5432 }}
    Release = [pscustomobject]@{{ pg_recovery_service_name = 'TicketboxRestore' }}
}}
$credentials = [pscustomobject]@{{
    RuntimeVerifier = 'runtime-verifier'
    MigratorVerifier = 'migrator-verifier'
    BackupVerifier = 'backup-verifier'
}}
$bootstrap = [pscustomobject]@{{ SuperuserPassword = 'protected-secret' }}
$result = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
    $subject '11111111-1111-4111-8111-111111111111' $credentials $bootstrap 'lock'
$labels = @($script:commands | ForEach-Object {{ $_.Label }}) -join '|'
if ($labels -cne 'restore candidate role authority|restore candidate database creation|restore candidate database admission|restore candidate managed ACL') {{
    throw "absent catalog path drifted: $labels"
}}
$databases = @($script:commands | ForEach-Object {{ $_.Database }}) -join '|'
if ($databases -cne 'postgres|postgres|postgres|ticketbox') {{
    throw "absent catalog database routing drifted: $databases"
}}
$creation = @($script:commands | Where-Object {{ $_.Label -ceq 'restore candidate database creation' }})[0]
if ($creation.Sql -cnotlike '*CREATE DATABASE*OWNER*ticketbox_owner*TEMPLATE template0*') {{ throw 'creation SQL drifted' }}
$admission = @($script:commands | Where-Object {{ $_.Label -ceq 'restore candidate database admission' }})[0]
if ($admission.Sql -cnotlike '*REVOKE ALL ON DATABASE*GRANT CONNECT*ticketbox_migrator*') {{ throw 'admission SQL drifted' }}
if (
    [string]$result.ServiceName -cne 'TicketboxRestore' -or
    [string]$result.PgCtlPath -cne (Join-Path $install 'pg\bin\pg_ctl.exe') -or
    [int]$result.Authority.Port -ne 5432 -or
    $result.SuperuserPassword -ne $script:activeSecret -or
    $script:disposeCount -ne 0
) {{ throw 'candidate database result or secret lifetime drifted' }}
$result.SuperuserPassword.Dispose()
if ($script:disposeCount -ne 1) {{ throw 'caller could not retire returned secret' }}

$script:commands = @()
$script:catalogExists = $true
$existing = Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
    $subject '11111111-1111-4111-8111-111111111111' $credentials $bootstrap 'lock'
$existingLabels = @($script:commands | ForEach-Object {{ $_.Label }}) -join '|'
if ($existingLabels -cne 'restore candidate role authority|restore candidate database admission|restore candidate managed ACL') {{
    throw "existing catalog path drifted: $existingLabels"
}}
$existingDatabases = @($script:commands | ForEach-Object {{ $_.Database }}) -join '|'
if ($existingDatabases -cne 'postgres|postgres|ticketbox') {{
    throw "existing catalog database routing drifted: $existingDatabases"
}}
$existing.SuperuserPassword.Dispose()
if ($script:disposeCount -ne 2) {{ throw 'existing-path secret lifetime drifted' }}

$script:commands = @()
$script:catalogExists = $true
$script:failLabel = 'restore candidate database admission'
$failed = $false
try {{
    Initialize-TicketboxPostgresqlRestoreCandidateDatabase `
        $subject '11111111-1111-4111-8111-111111111111' $credentials $bootstrap 'lock' | Out-Null
}} catch {{ $failed = $true }}
if (-not $failed -or $script:disposeCount -ne 3) {{ throw 'failed database initialization leaked its secret' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-candidate-database.ps1",
    )


def test_restore_promotion_is_forward_reconcilable_and_keeps_old_bytes_until_current() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    assert "candidate_pgdata" in contract
    assert "rollback_pgdata" in contract
    assert "candidate_uploads" in contract
    assert "rollback_uploads" in contract
    assert "Resolve-TicketboxInstalledDatasetRestorePhysicalState" in contract
    assert "Set-TicketboxInstalledDatasetRestorePhysicalSelection" in contract
    assert "Invoke-TicketboxInstalledDatasetRestorePromotion" not in contract
    assert '-Selection "Predecessor"' in restore
    compensation = restore.split("catch {", maxsplit=1)[-1]
    assert compensation.index("Read-TicketboxDatabaseGenerationCurrent") < compensation.index(
        '-Selection "Predecessor"'
    )
    assert restore.index("Invoke-TicketboxInstalledDatabaseGeneration") < restore.index(
        "Remove-TicketboxInstalledDatasetRestoreRollback"
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_physical_selection_can_recover_every_precurrent_cutpoint(tmp_path: Path) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestorePhysicalState",
    )
    selector = powershell_function(
        contract,
        "Set-TicketboxInstalledDatasetRestorePhysicalSelection",
    )
    base = str(tmp_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (Test-Path -LiteralPath $Path -PathType Container) {{ return 'Directory' }}
    return 'Missing'
}}
{classifier}
{selector}
$root = '{base}'
$names = @('stable_pgdata','stable_uploads','candidate_pgdata','candidate_uploads','rollback_pgdata','rollback_uploads')
$forwardCase = Join-Path $root 'forward'
if (Test-Path -LiteralPath $forwardCase) {{ [IO.Directory]::Delete($forwardCase, $true) }}
$forwardPaths = [pscustomobject][ordered]@{{
    stable_pgdata = Join-Path $forwardCase 'stable-pg'
    stable_uploads = Join-Path $forwardCase 'stable-uploads'
    candidate_pgdata = Join-Path $forwardCase 'candidate/pg'
    candidate_uploads = Join-Path $forwardCase 'candidate/uploads'
    rollback_pgdata = Join-Path $forwardCase 'rollback/pg'
    rollback_uploads = Join-Path $forwardCase 'rollback/uploads'
    candidate_root = Join-Path $forwardCase 'candidate'
    rollback_root = Join-Path $forwardCase 'rollback'
}}
foreach ($name in @('stable_pgdata','stable_uploads','candidate_pgdata','candidate_uploads')) {{
    [IO.Directory]::CreateDirectory([string]$forwardPaths.$name) | Out-Null
}}
Set-TicketboxInstalledDatasetRestorePhysicalSelection -Paths $forwardPaths -Selection 'Candidate'
if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $forwardPaths) -cne 'candidate_published') {{
    throw 'candidate publication did not reach its exact physical state'
}}
Set-TicketboxInstalledDatasetRestorePhysicalSelection -Paths $forwardPaths -Selection 'Predecessor'
if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $forwardPaths) -cne 'candidate_ready') {{
    throw 'published candidate did not return to predecessor selection'
}}
$signatures = @('011110','001111','100111','110011')
foreach ($signature in $signatures) {{
    $case = Join-Path $root $signature
    if (Test-Path -LiteralPath $case) {{ [IO.Directory]::Delete($case, $true) }}
    $paths = [pscustomobject][ordered]@{{
        stable_pgdata = Join-Path $case 'stable-pg'
        stable_uploads = Join-Path $case 'stable-uploads'
        candidate_pgdata = Join-Path $case 'candidate/pg'
        candidate_uploads = Join-Path $case 'candidate/uploads'
        rollback_pgdata = Join-Path $case 'rollback/pg'
        rollback_uploads = Join-Path $case 'rollback/uploads'
        candidate_root = Join-Path $case 'candidate'
        rollback_root = Join-Path $case 'rollback'
    }}
    for ($index = 0; $index -lt $names.Count; $index++) {{
        if ($signature[$index] -ceq '1') {{
            [IO.Directory]::CreateDirectory([string]$paths.($names[$index])) | Out-Null
        }}
    }}
    Set-TicketboxInstalledDatasetRestorePhysicalSelection -Paths $paths -Selection 'Predecessor'
    if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $paths) -cne 'candidate_ready') {{
        throw "predecessor recovery failed for $signature"
    }}
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-physical-compensation.ps1",
    )


def test_restore_durable_request_owns_backend_restart_compensation() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    artifacts = (PACKAGING / "windows_database_generation_artifacts.ps1").read_text(encoding="utf-8-sig")
    request = powershell_function(
        contract,
        "Assert-TicketboxInstalledDatasetRestoreRequest",
    )

    assert '"restart_backend"' in request
    assert "$payload.restart_backend -isnot [bool]" in request
    create = powershell_function(
        contract,
        "New-TicketboxInstalledDatasetRestoreRequest",
    )
    assert "[Parameter(Mandatory = $true)][bool]$RestartBackend" in create
    assert "restart_backend = $RestartBackend" in create
    request_fields = artifacts.split('"dataset-restore-request" {', maxsplit=1)[1].split(
        '"source-binding" {', maxsplit=1
    )[0]
    assert '"restart_backend"' in request_fields
    assert "RestartBackend $restartBackend" in restore
    assert "priorPredecessor" in restore
    assert "expected_predecessor_sha256" in restore
    assert "source_request_sha256" in restore
    done = restore.index('"done" {')
    backend_restart = restore.index("Start-TicketboxOwnedServiceIfExists", done)
    assert done < backend_restart
    assert "if ($restartBackend -and $null -ne $result)" in restore[done:backend_restart]
    retirement = restore.index(
        "Remove-TicketboxInstalledDatasetRestoreRequest",
        backend_restart,
    )
    assert backend_restart < retirement
    assert "function Remove-TicketboxInstalledDatasetRestoreRequest" in contract


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_owner_compensation_is_current_guarded_and_ordered(tmp_path: Path) -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    compensation = powershell_function(
        restore,
        "Invoke-TicketboxInstalledDatasetRestoreFailureCompensation",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:events = @()
$script:published = $false
function Read-TicketboxDatabaseGenerationCurrent {{
    $script:events += 'read-current'
    $operation = if ($script:published) {{ '22222222-2222-4222-8222-222222222222' }} else {{ '11111111-1111-4111-8111-111111111111' }}
    return [pscustomobject]@{{ Payload = [pscustomobject]@{{ operation_id = $operation }} }}
}}
function Remove-TicketboxPostgresqlRestoreCandidateService {{ param($Subject, $Paths); $script:events += 'remove-candidate-service' }}
function Stop-TicketboxInstalledDatasetWriters {{ param($Subject); $script:events += 'stop-writers' }}
function Set-TicketboxInstalledDatasetRestorePhysicalSelection {{ param($Paths, $Selection); $script:events += "select:$Selection" }}
function Set-TicketboxInstalledDatasetPublishedAcls {{ param($Subject, $Paths); $script:events += 'set-acls' }}
function Start-TicketboxOwnedServiceIfExists {{
    param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds)
    $script:events += "start:$Name"
}}
{compensation}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\\Ticketbox'; PgServiceName = 'ticketbox-pg'; BackendServiceName = 'ticketbox-backend' }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
$request = [pscustomobject]@{{ Payload = [pscustomobject]@{{ restart_backend = $true }} }}
$paths = [pscustomobject]@{{}}
Invoke-TicketboxInstalledDatasetRestoreFailureCompensation $subject $request $paths '22222222-2222-4222-8222-222222222222'
$expected = 'read-current|remove-candidate-service|stop-writers|select:Predecessor|set-acls|start:ticketbox-pg|start:ticketbox-backend'
if (($script:events -join '|') -cne $expected) {{ throw "unexpected compensation order: $($script:events -join '|')" }}
$script:events = @()
$script:published = $true
Invoke-TicketboxInstalledDatasetRestoreFailureCompensation $subject $request $paths '22222222-2222-4222-8222-222222222222'
if (($script:events -join '|') -cne 'read-current') {{ throw 'published CURRENT was rolled back' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-owner-compensation.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_predecessor_classifier_distinguishes_committed_and_pending_successors(
    tmp_path: Path,
) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    classifier = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestorePredecessor",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{classifier}
$shaA = 'a' * 64
$shaB = 'b' * 64
$fresh = [pscustomobject]@{{
    PayloadSha256 = $shaA
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111'; expected_predecessor_sha256 = '' }}
}}
$committedSuccessor = [pscustomobject]@{{
    PayloadSha256 = $shaB
    Payload = [pscustomobject]@{{ operation_id = '22222222-2222-4222-8222-222222222222'; expected_predecessor_sha256 = $shaA }}
}}
$freshCurrent = [pscustomobject]@{{ PayloadSha256 = $shaA; Payload = [pscustomobject]@{{ operation_id = $fresh.Payload.operation_id; intent_sha256 = $shaA }} }}
$successorCurrent = [pscustomobject]@{{ PayloadSha256 = $shaB; Payload = [pscustomobject]@{{ operation_id = $committedSuccessor.Payload.operation_id; intent_sha256 = $shaB }} }}

$first = Resolve-TicketboxInstalledDatasetRestorePredecessor $fresh $freshCurrent
if ($first.HasPendingSuccessor -or $first.PayloadSha256 -cne $shaA) {{ throw 'fresh CURRENT misclassified' }}
$repeat = Resolve-TicketboxInstalledDatasetRestorePredecessor $committedSuccessor $successorCurrent
if ($repeat.HasPendingSuccessor -or $repeat.PayloadSha256 -cne $shaB) {{ throw 'committed successor blocks repeat restore' }}
$pending = Resolve-TicketboxInstalledDatasetRestorePredecessor $committedSuccessor $freshCurrent
if (-not $pending.HasPendingSuccessor -or $pending.PayloadSha256 -cne $shaA) {{ throw 'pending successor misclassified' }}
$committedSuccessor.Payload.expected_predecessor_sha256 = $shaB
$rejected = $false
try {{ Resolve-TicketboxInstalledDatasetRestorePredecessor $committedSuccessor $freshCurrent | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'mismatched pending predecessor accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-predecessor.ps1",
    )


def test_completed_restore_can_create_a_new_successor_after_request_retirement() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    intent_branch = restore.split(
        "$contracts = New-TicketboxInstalledDatabaseGenerationContracts",
        maxsplit=1,
    )[1].split("$operationId =", maxsplit=1)[0]

    assert "$resumeCommittedRestore = $false" in restore
    assert "$resumeCommittedRestore = $true" in restore
    assert "-not $resumeCommittedRestore" in intent_branch
    assert "IsNullOrEmpty" not in intent_branch


def test_published_candidate_reconciles_main_host_before_h1_publication() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    publication = restore.split('"publish_current" {', maxsplit=1)[1].split('"retire_rollback" {', maxsplit=1)[0]

    assert publication.index("Set-TicketboxInstalledDatasetPublishedAcls") < publication.index(
        "Start-TicketboxOwnedServiceIfExists"
    )
    assert publication.index("Start-TicketboxOwnedServiceIfExists") < publication.index(
        "Invoke-TicketboxInstalledDatabaseGeneration"
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_next_action_reducer_is_closed_and_io_free(tmp_path: Path) -> None:
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    reducer = powershell_function(
        contract,
        "Resolve-TicketboxInstalledDatasetRestoreNextAction",
    )
    assert "[AllowNull()]" not in reducer
    assert reducer.count('[ValidateSet("absent", "present")]') == 2
    script = f"""
$ErrorActionPreference = 'Stop'
{reducer}
$cases = @(
    @('complete', 'absent', 'absent', 'build_candidate'),
    @('candidate_building', 'absent', 'absent', 'restore_candidate'),
    @('candidate_ready', 'present', 'absent', 'promote_candidate'),
    @('old_pg_staged', 'present', 'absent', 'promote_candidate'),
    @('old_staged', 'present', 'absent', 'promote_candidate'),
    @('candidate_pg_published', 'present', 'absent', 'promote_candidate'),
    @('candidate_published', 'present', 'absent', 'publish_current'),
    @('candidate_published', 'present', 'present', 'retire_rollback'),
    @('complete', 'present', 'present', 'done')
)
foreach ($case in $cases) {{
    $actual = Resolve-TicketboxInstalledDatasetRestoreNextAction `
        $case[0] $case[1] $case[2]
    if ($actual -cne $case[3]) {{ throw "unexpected next action: $actual" }}
}}
$rejected = $false
try {{
    Resolve-TicketboxInstalledDatasetRestoreNextAction `
        'candidate_published' 'absent' 'absent' | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'authority-free publication state was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-next-action.ps1",
    )
