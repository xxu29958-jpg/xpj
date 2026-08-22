from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines, run_powershell_contract_script
from _powershell_contract import powershell_function as _function

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
OWNER = PACKAGING / "windows_database_generation.ps1"
CURRENT = PACKAGING / "windows_database_generation_current.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_owner_current_and_predecessor_restore_are_idempotent_cas(
    tmp_path: Path,
) -> None:
    prospective = _function(
        CURRENT.read_text(encoding="utf-8-sig"),
        "Get-TicketboxDatabaseGenerationProspectiveCurrent",
    )
    advance = _function(
        CURRENT.read_text(encoding="utf-8-sig"),
        "New-TicketboxDatabaseGenerationAdvanceCurrentTransition",
    )
    validate_transition = _function(
        CURRENT.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationCurrentTransition",
    )
    publish = _function(
        CURRENT.read_text(encoding="utf-8-sig"),
        "Publish-TicketboxDatabaseGenerationCurrent",
    )
    restore_predecessor = _function(
        OWNER.read_text(encoding="utf-8-sig"),
        "Restore-TicketboxInstalledDatabaseGenerationPredecessor",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); $Value | ConvertTo-Json -Depth 12 -Compress }}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param($Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes([string]$Text)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }}
    finally {{ $sha256.Dispose() }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{ param($Value, $Label); if ($Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label invalid" }} }}
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function Get-TicketboxDatabaseGenerationPayloadProperties {{ param($Kind); return @() }}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM', 'Administrators')
$script:TicketboxDatabaseGenerationRuntimeAccount = 'NT SERVICE\\TicketboxBackend'
$script:TicketboxDatabaseGenerationOwnerAccount = 'SYSTEM'
$script:current = $null
$script:writes = 0
function Get-TicketboxDatabaseGenerationRuntimeCurrentPath {{ return 'C:\\Ticketbox\\current-generation.json' }}
function Read-TicketboxDatabaseGenerationCurrent {{ param([switch]$AllowAbsent); return $script:current }}
function Initialize-TicketboxProtectedDirectoryAtomically {{}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    if ($null -ne $script:current -and -not $ReplaceExisting) {{
        throw 'CURRENT replacement omitted the atomic replace contract'
    }}
    $script:writes += 1
    $envelope = $Text | ConvertFrom-Json
    $script:current = [pscustomobject]@{{
        Payload = $envelope.payload
        PayloadSha256 = [string]$envelope.payload_sha256
    }}
}}
{prospective}
{advance}
{validate_transition}
{publish}
{restore_predecessor}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        installation_id = '22222222-2222-4222-8222-222222222222'
        generation_program_sha256 = ('c' * 64)
        host_contract_sha256 = ('4' * 64)
        projection_contract_sha256 = ('5' * 64)
        expected_predecessor_sha256 = ''
    }}
}}
$candidate = [pscustomobject]@{{ PayloadSha256 = ('d' * 64); Payload = [pscustomobject]@{{ intent_sha256 = ('b' * 64); target_revision = '20260809_0001'; database_binding_sha256 = ('9' * 64) }} }}
$terminal = [pscustomobject]@{{
    PayloadSha256 = ('7' * 64)
    Payload = [pscustomobject]@{{
        intent_sha256 = ('b' * 64)
        candidate_sha256 = ('d' * 64)
        runtime_credentials_sha256 = ('1' * 64)
        bootstrap_retirement_sha256 = ('2' * 64)
        runtime_projection_sha256 = ('3' * 64)
        host_contract_sha256 = ('4' * 64)
        projection_contract_sha256 = ('5' * 64)
        transient_credentials_state = 'absent'
        bootstrap_recovery_state = 'absent'
        maintenance_service_transition_state = 'absent'
    }}
}}
$lock = @{{}}
$transition = New-TicketboxDatabaseGenerationAdvanceCurrentTransition $intent $candidate $terminal
$first = Publish-TicketboxDatabaseGenerationCurrent $transition $lock
$second = Publish-TicketboxDatabaseGenerationCurrent $transition $lock
if ($script:writes -ne 1 -or $first.PayloadSha256 -cne $second.PayloadSha256) {{ throw 'idempotent CURRENT failed' }}
$script:current.PayloadSha256 = ('e' * 64)
$conflict = $false
try {{ Publish-TicketboxDatabaseGenerationCurrent $transition $lock | Out-Null }} catch {{ $conflict = $true }}
if (-not $conflict -or $script:writes -ne 1) {{ throw 'CURRENT conflict did not fail closed' }}
$predecessorPayload = [pscustomobject]@{{
    schema = 'ticketbox-current-database-generation-v1'
    operation_id = '33333333-3333-4333-8333-333333333333'
    installation_id = '22222222-2222-4222-8222-222222222222'
    intent_sha256 = ('6' * 64)
    candidate_sha256 = ('7' * 64)
    committed_revision = '20260809_0001'
    generation_program_sha256 = ('8' * 64)
    database_binding_sha256 = ('9' * 64)
    terminal_state_sha256 = ('0' * 64)
    expected_predecessor_sha256 = ''
}}
$predecessorSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
    ConvertTo-TicketboxDatabaseGenerationCanonicalJson $predecessorPayload
)
$script:current = [pscustomobject]@{{
    Payload = $predecessorPayload
    PayloadSha256 = $predecessorSha256
}}
$intent.Payload.operation_id = '44444444-4444-4444-8444-444444444444'
$intent.Payload.expected_predecessor_sha256 = $predecessorSha256
$successorTransition = New-TicketboxDatabaseGenerationAdvanceCurrentTransition $intent $candidate $terminal
$successor = Publish-TicketboxDatabaseGenerationCurrent $successorTransition $lock
$successorAgain = Publish-TicketboxDatabaseGenerationCurrent $successorTransition $lock
if (
    $script:writes -ne 2 -or
    $successor.Payload.operation_id -cne $intent.Payload.operation_id -or
    $successorAgain.PayloadSha256 -cne $successor.PayloadSha256
) {{ throw 'successor CURRENT predecessor CAS did not converge' }}
$rolledBack = Restore-TicketboxInstalledDatabaseGenerationPredecessor $predecessorPayload $lock
$rolledBackAgain = Restore-TicketboxInstalledDatabaseGenerationPredecessor $predecessorPayload $lock
if (
    $script:writes -ne 3 -or
    $rolledBack.PayloadSha256 -cne $predecessorSha256 -or
    $rolledBackAgain.PayloadSha256 -cne $predecessorSha256
) {{ throw 'CURRENT predecessor restoration did not converge' }}
$script:current = $null
$missing = $false
try {{ Publish-TicketboxDatabaseGenerationCurrent $successorTransition $lock | Out-Null }} catch {{ $missing = $true }}
if (-not $missing -or $script:writes -ne 3) {{ throw 'missing predecessor mutated CURRENT' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="database-generation-owner.ps1")
