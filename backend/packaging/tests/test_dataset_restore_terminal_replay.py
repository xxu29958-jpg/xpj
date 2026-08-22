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
DATASET_OPERATION = PACKAGING / "windows_installed_dataset_operation.ps1"
RESTORE_ARTIFACTS = PACKAGING / "windows_installed_dataset_restore_artifacts.ps1"

RESTORE_DEPENDENCIES = (
    "windows_installation_safety.ps1",
    "windows_lifecycle_lock.ps1",
    "windows_deadline_budget.ps1",
    "windows_release_config.ps1",
    "windows_service_lifecycle.ps1",
    "windows_database_safety.ps1",
    "windows_pg_recovery_tools.ps1",
    "windows_postgresql_credentials.ps1",
    "windows_postgresql_database_command.ps1",
    "windows_backend_health.ps1",
    "windows_database_generation.ps1",
    "windows_installed_dataset_reader.ps1",
    "windows_installed_dataset_operation.ps1",
    "windows_installed_dataset_restore_artifacts.ps1",
    "windows_installed_dataset_restore_verification.ps1",
    "windows_dataset_restore_filesystem.ps1",
    "windows_dataset_restore_reducer.ps1",
    "windows_dataset_restore_database.ps1",
    "windows_dataset_restore_runtime.ps1",
    "windows_postgresql_candidate_cluster.ps1",
    "windows_postgresql_candidate_initdb.ps1",
    "windows_postgresql_candidate_runtime.ps1",
    "windows_bundled_database.ps1",
)
RESTORE_CONTRACT_PATHS = tuple(PACKAGING / name for name in RESTORE_DEPENDENCIES)


def _restore_contract() -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in RESTORE_CONTRACT_PATHS)


def test_restore_terminal_result_uses_one_bounded_replay_slot() -> None:
    artifacts = RESTORE_ARTIFACTS.read_text(encoding="utf-8-sig")
    path_owner = powershell_function(
        artifacts,
        "Get-TicketboxInstalledDatasetRestoreResultPath",
    )
    writer = powershell_function(
        artifacts,
        "New-TicketboxInstalledDatasetRestoreResult",
    )

    assert '"dataset-restore-result.json"' in path_owner
    assert "RestoreAttemptId" not in path_owner
    assert "Replace-TicketboxInstalledDatasetRestoreResultEnvelope" in writer


def test_restore_terminal_replay_slot_atomically_supersedes_prior_current(
    tmp_path: Path,
) -> None:
    artifacts = RESTORE_ARTIFACTS.read_text(encoding="utf-8-sig")
    generation_artifacts = (PACKAGING / "windows_database_generation_artifacts.ps1").read_text(encoding="utf-8-sig")
    functions = "\n".join(
        [
            powershell_function(
                generation_artifacts,
                "Get-TicketboxDatabaseGenerationPayloadProperties",
            ),
            powershell_function(
                generation_artifacts,
                "New-TicketboxDatabaseGenerationEnvelopeText",
            ),
            *(
                powershell_function(artifacts, name)
                for name in (
                    "Get-TicketboxInstalledDatasetRestoreResultPath",
                    "Assert-TicketboxInstalledDatasetRestoreResult",
                    "Read-TicketboxInstalledDatasetRestoreResult",
                    "New-TicketboxInstalledDatasetRestoreResultEnvelope",
                    "Replace-TicketboxInstalledDatasetRestoreResultEnvelope",
                    "New-TicketboxInstalledDatasetRestoreResult",
                )
            ),
        ]
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM', 'Administrators')
$script:TicketboxDatabaseGenerationOwnerAccount = 'SYSTEM'
$script:stored = $null
$script:writes = 0
$script:replacements = 0
$script:path = $null
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label invalid" }}
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "$Label fields changed" }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 20 -Compress)
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param($Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes([string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }}
    finally {{ $sha.Dispose() }}
}}
function Read-TicketboxDatabaseGenerationEnvelope {{
    param($Path, $ExpectedKind, [switch]$AllowAbsent)
    if ($null -eq $script:stored) {{
        if ($AllowAbsent) {{ return $null }}
        throw 'bounded replay slot is absent'
    }}
    if ($Path -cne $script:path -or $ExpectedKind -cne 'dataset-restore-result') {{
        throw 'bounded replay slot authority changed'
    }}
    return $script:stored
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    if ($ReplaceExisting) {{
        if ($null -eq $script:stored -or $Path -cne $script:path) {{
            throw 'bounded replay replacement was not atomic'
        }}
        $script:replacements++
    }} else {{
        if ($null -ne $script:stored) {{ throw 'bounded replay created a second slot' }}
        $script:path = $Path
        $script:writes++
    }}
    $envelope = $Text | ConvertFrom-Json
    $script:stored = [pscustomobject]@{{
        PayloadSha256 = [string]$envelope.payload_sha256
        Payload = $envelope.payload
    }}
}}
{functions}
$firstAttempt = '11111111-1111-4111-8111-111111111111'
$secondAttempt = '22222222-2222-4222-8222-222222222222'
$firstCurrent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = '33333333-3333-4333-8333-333333333333' }}
}}
$secondCurrent = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{ operation_id = '44444444-4444-4444-8444-444444444444' }}
}}
$firstRequest = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $firstAttempt
        release_manifest_sha256 = ('d' * 64)
        backup_generation = 'ticketbox-backup-55555555-5555-4555-8555-555555555555'
    }}
}}
$secondRequest = [pscustomobject]@{{
    PayloadSha256 = ('e' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $secondAttempt
        release_manifest_sha256 = ('d' * 64)
        backup_generation = 'ticketbox-backup-66666666-6666-4666-8666-666666666666'
    }}
}}
$firstPayload = [pscustomobject]@{{
    backup_id = '55555555-5555-4555-8555-555555555555'
    dataset_id = '77777777-7777-4777-8777-777777777777'
    restore_epoch = 1
    generation_operation_id = '33333333-3333-4333-8333-333333333333'
}}
$secondPayload = [pscustomobject]@{{
    backup_id = '66666666-6666-4666-8666-666666666666'
    dataset_id = '77777777-7777-4777-8777-777777777777'
    restore_epoch = 2
    generation_operation_id = '44444444-4444-4444-8444-444444444444'
}}
$lock = [pscustomobject]@{{}}
New-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -Request $firstRequest -Current $firstCurrent `
    -Payload $firstPayload -LifecycleLock $lock | Out-Null
New-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -Request $secondRequest -Current $secondCurrent `
    -Payload $secondPayload -LifecycleLock $lock | Out-Null
$latest = Read-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -RestoreAttemptId $secondAttempt `
    -BackupGeneration ([string]$secondRequest.Payload.backup_generation) `
    -Current $secondCurrent -ExpectedReleaseManifestSha256 ('d' * 64)
$prior = Read-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\\state' -RestoreAttemptId $firstAttempt `
    -BackupGeneration ([string]$firstRequest.Payload.backup_generation) `
    -Current $firstCurrent -ExpectedReleaseManifestSha256 ('d' * 64) -AllowAbsent
if (
    $script:writes -ne 1 -or $script:replacements -ne 1 -or
    $script:path -cne 'C:\\state\dataset-restore-result.json' -or
    $latest.Disposition -cne 'current' -or $null -ne $prior
) {{ throw 'bounded terminal replay did not converge to one atomic slot' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-bounded-terminal-replay.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_terminal_result_survives_response_loss_and_is_attempt_bound(
    tmp_path: Path,
) -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    artifacts = RESTORE_ARTIFACTS.read_text(encoding="utf-8-sig")
    subject_read = restore.index("Assert-TicketboxInstalledDatasetSubject")
    current_read = restore.index("Read-TicketboxDatabaseGenerationCurrent")
    request_read = restore.index("Read-TicketboxInstalledDatasetOperation")
    terminal_read = restore.index("Read-TicketboxInstalledDatasetRestoreResult")
    terminal_write = restore.rindex("New-TicketboxInstalledDatasetRestoreResult")
    request_retire = restore.rindex("Remove-TicketboxInstalledDatasetOperation")
    assert subject_read < current_read < request_read < terminal_read
    assert terminal_write < request_retire
    terminal_resume = powershell_function(
        _restore_contract(),
        "Complete-TicketboxInstalledDatasetRestoreTerminalReplay",
    )
    assert "terminal.request_sha256" in terminal_resume
    assert "terminal.release_manifest_sha256" in terminal_resume
    assert terminal_resume.index("Set-TicketboxInstalledDatasetBackendDesiredState") < (
        terminal_resume.index("Remove-TicketboxInstalledDatasetOperation")
    )

    generation_artifacts = (
        PACKAGING / "windows_database_generation_artifacts.ps1"
    ).read_text(encoding="utf-8-sig")
    functions = "\n".join(
        [
            powershell_function(
                generation_artifacts,
                "Get-TicketboxDatabaseGenerationPayloadProperties",
            ),
            powershell_function(
                generation_artifacts,
                "New-TicketboxDatabaseGenerationEnvelopeText",
            ),
            *(
                powershell_function(artifacts, name)
                for name in (
                    "Get-TicketboxInstalledDatasetRestoreResultPath",
                    "Assert-TicketboxInstalledDatasetRestoreResult",
                    "Read-TicketboxInstalledDatasetRestoreResult",
                    "New-TicketboxInstalledDatasetRestoreResultEnvelope",
                    "Replace-TicketboxInstalledDatasetRestoreResultEnvelope",
                    "New-TicketboxInstalledDatasetRestoreResult",
                )
            ),
        ]
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:stored = $null
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM', 'Administrators')
$script:TicketboxDatabaseGenerationOwnerAccount = 'SYSTEM'
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw 'bad digest' }}
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw 'unexpected fields' }}
}}
function Read-TicketboxDatabaseGenerationEnvelope {{
    param($Path, $ExpectedKind, [switch]$AllowAbsent)
    if ($null -eq $script:stored) {{ if ($AllowAbsent) {{ return $null }}; throw 'absent' }}
    return $script:stored
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{ param($Text); return ('d' * 64) }}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    if ($ReplaceExisting) {{ throw 'same-attempt retry unexpectedly replaced terminal result' }}
    $envelope = $Text | ConvertFrom-Json
    $script:stored = [pscustomobject]@{{
        Path = $Path
        Kind = [string]$envelope.kind
        PayloadSha256 = [string]$envelope.payload_sha256
        Payload = $envelope.payload
    }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 20 -Compress)
}}
{functions}
$attempt = '11111111-1111-4111-8111-111111111111'
$backup = '22222222-2222-4222-8222-222222222222'
$request = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $attempt
        backup_generation = "ticketbox-backup-$backup"
        release_manifest_sha256 = ('c' * 64)
        restart_backend = $true
    }}
}}
$current = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{ operation_id = '44444444-4444-4444-8444-444444444444' }}
}}
$payload = [pscustomobject]@{{
    backup_id = $backup
    dataset_id = '33333333-3333-4333-8333-333333333333'
    restore_epoch = 5
    generation_operation_id = '44444444-4444-4444-8444-444444444444'
}}
$first = New-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\state' -Request $request -Current $current `
    -Payload $payload -LifecycleLock ([pscustomobject]@{{}})
$retry = Read-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\state' -RestoreAttemptId $attempt `
    -BackupGeneration "ticketbox-backup-$backup" `
    -Current $current -ExpectedReleaseManifestSha256 ('c' * 64)
if (
    $first.PayloadSha256 -cne $retry.Artifact.PayloadSha256 -or
    $retry.Disposition -cne 'current'
) {{ throw 'terminal result changed on retry' }}
$rejected = $false
try {{
    Read-TicketboxInstalledDatasetRestoreResult `
        -StateRoot 'C:\state' -RestoreAttemptId $attempt `
        -BackupGeneration 'ticketbox-backup-55555555-5555-4555-8555-555555555555' `
        -Current $current -ExpectedReleaseManifestSha256 ('c' * 64) | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'terminal result crossed backup authority' }}
$rejected = $false
try {{
    Read-TicketboxInstalledDatasetRestoreResult `
        -StateRoot 'C:\state' -RestoreAttemptId $attempt `
        -BackupGeneration "ticketbox-backup-$backup" `
        -Current $current -ExpectedReleaseManifestSha256 ('f' * 64) | Out-Null
}} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'terminal result crossed release authority' }}
$foreignCurrent = [pscustomobject]@{{
    PayloadSha256 = ('e' * 64)
    Payload = [pscustomobject]@{{ operation_id = '55555555-5555-4555-8555-555555555555' }}
}}
$superseded = Read-TicketboxInstalledDatasetRestoreResult `
    -StateRoot 'C:\state' -RestoreAttemptId $attempt `
    -BackupGeneration "ticketbox-backup-$backup" `
    -Current $foreignCurrent -ExpectedReleaseManifestSha256 ('c' * 64)
if (
    $superseded.Artifact.PayloadSha256 -cne $first.PayloadSha256 -or
    $superseded.Disposition -cne 'superseded'
) {{ throw 'stale terminal did not classify as superseded' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-terminal-retry.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_terminal_replay_reconciles_desired_backend_before_request_retirement(
    tmp_path: Path,
) -> None:
    contract = _restore_contract()
    replay = powershell_function(
        contract,
        "Complete-TicketboxInstalledDatasetRestoreTerminalReplay",
    )
    desired_state = powershell_function(
        contract,
        "Set-TicketboxInstalledDatasetBackendDesiredState",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = @()
function Assert-TicketboxInstalledDatasetServiceAuthority {{ param($Subject); $script:events += 'authority' }}
function Start-TicketboxOwnedServiceIfExists {{ param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds); $script:events += "start:$Name" }}
function Stop-TicketboxOwnedServiceIfExists {{ param($Name, $ExpectedExecutable, $TimeoutMilliseconds, $PollMilliseconds, $BackendPort, $ExpectedRuntimeExecutables); $script:events += "stop:$Name" }}
function Remove-TicketboxInstalledDatasetOperation {{ param($Operation, $LifecycleLock); $script:events += 'remove-request' }}
{desired_state}
{replay}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{ InstallDir = 'C:\Ticketbox'; BackendServiceName = 'ticketbox-backend'; BackendPort = 8123 }}
    Release = [pscustomobject]@{{ service_state_timeout_ms = 1000; service_poll_interval_ms = 10 }}
}}
$request = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        backup_generation = 'ticketbox-backup-22222222-2222-4222-8222-222222222222'
        release_manifest_sha256 = ('c' * 64)
        restart_backend = $true
    }}
}}
$terminal = [pscustomobject]@{{
    Disposition = 'current'
    Artifact = [pscustomobject]@{{ Payload = [pscustomobject]@{{
        request_sha256 = ('a' * 64)
        release_manifest_sha256 = ('c' * 64)
        restore_attempt_id = '11111111-1111-4111-8111-111111111111'
        backup_id = '22222222-2222-4222-8222-222222222222'
        dataset_id = '33333333-3333-4333-8333-333333333333'
        restore_epoch = 4
        generation_operation_id = '44444444-4444-4444-8444-444444444444'
    }} }}
}}
$result = Complete-TicketboxInstalledDatasetRestoreTerminalReplay `
    -Subject $subject -Request $request -TerminalResult $terminal `
    -BackupGeneration ([string]$request.Payload.backup_generation) `
    -LifecycleLock ([pscustomobject]@{{}})
if (($script:events -join '|') -cne 'authority|start:ticketbox-backend|remove-request') {{
    throw "terminal replay retired request before desired state: $($script:events -join '|')"
}}
if ([string]$result.result -cne 'current_published') {{ throw 'terminal replay lost current result' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-terminal-state-reconciliation.ps1",
    )


def test_completed_restore_can_create_a_new_successor_after_request_retirement() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    intent_branch = restore.split(
        "$contracts = New-TicketboxInstalledDatabaseGenerationContracts",
        maxsplit=1,
    )[1].split("$operationId =", maxsplit=1)[0]

    assert "$resumeCommittedRestore" not in restore
    assert '"request_only"' in intent_branch
    assert '"successor_pending"' in intent_branch
    assert "IsNullOrEmpty" not in intent_branch
