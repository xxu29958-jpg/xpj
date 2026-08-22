from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines, powershell_function, run_powershell_contract_script

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
OWNER = PACKAGING / "windows_database_generation.ps1"
POLICY = PACKAGING / "windows_database_generation_policy.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_owner_recovers_after_bootstrap_retirement_response_loss(tmp_path: Path) -> None:
    source = OWNER.read_text(encoding="utf-8-sig")
    policy = POLICY.read_text(encoding="utf-8-sig")
    invoke = powershell_function(source, "Invoke-TicketboxInstalledDatabaseGeneration")
    reducer = powershell_function(policy, "Resolve-TicketboxDatabaseGenerationNextAction")
    result_factory = powershell_function(policy, "New-TicketboxInstalledDatabaseGenerationResult")
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:retired = $false
$script:runtimeReady = $false
$script:bootstrapExists = $true
$script:credentialsExist = $true
$script:bootstrapReads = 0
$script:credentialCreates = 0
$script:retirementCalls = 0
$script:projectionWrites = 0
$script:terminalWrites = 0
$script:currentWrites = 0
$script:sourceBindingReads = 0
$script:sourceChainCalls = 0
$script:rejectSourceChain = $true
$script:current = $null
$script:terminal = $null
$script:throwAfterTerminalWrite = $true
$script:adminSecret = [Security.SecureString]::new()
$script:adminSecret.AppendChar('a'); $script:adminSecret.MakeReadOnly()
$script:runtimeSecret = [Security.SecureString]::new()
$script:runtimeSecret.AppendChar('r'); $script:runtimeSecret.MakeReadOnly()
$script:httpSecret = [Security.SecureString]::new()
$script:httpSecret.AppendChar('h'); $script:httpSecret.MakeReadOnly()
$script:AppData = 'C:\ambient-poison'
$script:SecretByteCount = 1
$script:expectedAppData = $null
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ($Path -eq 'bootstrap.json') {{ if ($script:bootstrapExists) {{ return 'File' }}; return 'Missing' }}
    if ($Path -eq 'credentials.json') {{ if ($script:credentialsExist) {{ return 'File' }}; return 'Missing' }}
    if ($Path -eq 'service-transition.json') {{ return 'Missing' }}
    return 'File'
}}
function Assert-NoTicketboxAncestorReparsePoints {{}}
function Get-TicketboxDatabaseGenerationExecutionDependencyPaths {{ return @() }}
function Get-PostgresBootstrapRecoveryPath {{
    param($AppData)
    if ([string]$AppData -cne [string]$script:expectedAppData) {{
        throw 'bootstrap path used ambient AppData'
    }}
    return 'bootstrap.json'
}}
function Test-TicketboxPathEquals {{
    param($Left, $Right)
    return [string]$Left -ceq [string]$Right
}}
function Assert-TicketboxLifecycleOperationLease {{}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); $Value | ConvertTo-Json -Depth 20 -Compress }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('9' * 64) }}
function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {{ return ('9' * 64) }}
function Assert-TicketboxDatabaseGenerationReleaseBinding {{}}
function Repair-TicketboxDatabaseGenerationServiceTransition {{}}
function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {{ return [pscustomobject]@{{ Port = 5432 }} }}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        OwnerRole = 'ticketbox_owner'
        MigratorRole = 'ticketbox_migrator'
        RuntimeRole = 'ticketbox_runtime'
        RetiredLegacyRole = 'ticketbox'
    }}
}}
function Get-TicketboxDatabaseGenerationHostAuthoritySha256 {{ return ('8' * 64) }}
function Read-TicketboxDatabaseGenerationCurrent {{ param([switch]$AllowAbsent); return $script:current }}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    param($StateRoot, $OperationId, $Kind, [switch]$AllowAbsent)
    if ($Kind -eq 'candidate') {{ return $script:candidate }}
    if ($Kind -eq 'source-binding') {{
        $script:sourceBindingReads += 1
        return $script:sourceBinding
    }}
    if ($Kind -eq 'target-authorization') {{ return $script:targetAuthorization }}
    throw "unexpected artifact $Kind"
}}
function Assert-TicketboxDatabaseGenerationSourceBindingChain {{
    param($StateRoot, $Binding, $Intent)
    if (
        [string]$StateRoot -cne 'state' -or
        -not [object]::ReferenceEquals($Binding, $script:sourceBinding) -or
        -not [object]::ReferenceEquals($Intent, $script:intent)
    ) {{ throw 'source chain authority drifted' }}
    $script:sourceChainCalls += 1
    if ($script:rejectSourceChain) {{ throw 'rejected source binding evidence' }}
    return $Binding
}}
function Read-TicketboxDatabaseGenerationRuntimeCredentials {{ return $script:runtimeCredentials }}
function Close-TicketboxDatabaseGenerationRuntimeCredentials {{}}
function Close-TicketboxDatabaseGenerationCredentials {{}}
function Test-TicketboxDatabaseGenerationBootstrapRetirement {{
    param($Intent, $Candidate, $HostAuthority, $RuntimePassword)
    if (-not [object]::ReferenceEquals($RuntimePassword, $script:runtimeSecret)) {{ throw 'wrong runtime secret' }}
    if (-not $script:runtimeReady) {{ throw 'runtime login is still disabled' }}
    return $script:retired
}}
function Get-TicketboxDatabaseGenerationBootstrapRetirementJson {{ return '{{"retired":true}}' }}
function Read-PostgresBootstrapRecoveryState {{
    param($Path, $AppData, $SecretByteCount)
    if (
        [string]$Path -cne 'bootstrap.json' -or
        [string]$AppData -cne [string]$script:expectedAppData -or
        [int]$SecretByteCount -ne 32
    ) {{ throw 'bootstrap reader did not receive HostContract operands' }}
    $script:bootstrapReads += 1
    return [pscustomobject]@{{ SuperuserPassword = 'admin'; HttpBootstrapSecret = 'http-bootstrap-secret-0000000000000000' }}
}}
function New-TicketboxDatabaseGenerationMaintenanceAuthority {{
    return [pscustomobject]@{{ Secret = $script:adminSecret }}
}}
function Close-TicketboxDatabaseGenerationMaintenanceAuthority {{}}
function Read-TicketboxDatabaseGenerationCredentials {{
    if (-not $script:credentialsExist) {{ return $null }}
    return [pscustomobject]@{{ Value = 'transient' }}
}}
function New-TicketboxDatabaseGenerationCredentials {{
    $script:credentialCreates += 1
    $script:credentialsExist = $true
    return [pscustomobject]@{{ Value = 'transient' }}
}}
function Prepare-TicketboxDatabaseGenerationRuntimeProjection {{
    param($Intent, $Candidate, $RuntimeCredentials, $HostAuthority, $MaintenanceAuthority)
    if (-not [object]::ReferenceEquals($MaintenanceAuthority.Secret, $script:adminSecret)) {{ throw 'wrong admin secret' }}
    $script:runtimeReady = $true
    return [pscustomobject]@{{ Schema = 'ticketbox-database-generation-projection-prepared-v1'; OperationId = $Intent.Payload.operation_id; CandidateSha256 = $Candidate.PayloadSha256 }}
}}
function Retire-TicketboxDatabaseGenerationBootstrapAuthority {{
    param($StateRoot, $Intent, $Candidate, $HostContract, $HostAuthority, $RuntimePassword, $LifecycleLock)
    if (-not [object]::ReferenceEquals($RuntimePassword, $script:runtimeSecret)) {{ throw 'wrong retirement observer secret' }}
    $script:retirementCalls += 1
    $script:retired = $true
    throw 'simulated response loss after retirement commit'
}}
function Publish-TicketboxDatabaseGenerationRuntimeProjection {{
    if ($script:projectionWrites -eq 0) {{ $script:projectionWrites = 1 }}
    return Read-TicketboxDatabaseGenerationRuntimeProjection
}}
function Read-TicketboxDatabaseGenerationRuntimeProjection {{
    return [pscustomobject]@{{
        Payload = [pscustomobject]@{{ operation_id = $script:intent.Payload.operation_id; candidate_sha256 = $script:candidate.PayloadSha256; committed_revision = $script:candidate.Payload.target_revision }}
        PayloadSha256 = ('7' * 64)
        DatabaseUrl = 'postgresql://runtime'
    }}
}}
function Remove-PostgresBootstrapRecoveryState {{
    param($Path, $AppData)
    if (
        [string]$Path -cne 'bootstrap.json' -or
        [string]$AppData -cne [string]$script:expectedAppData
    ) {{ throw 'bootstrap cleanup did not receive HostContract AppData' }}
    $script:bootstrapExists = $false
}}
function Remove-TicketboxDatabaseGenerationCredentials {{ $script:credentialsExist = $false }}
function Get-TicketboxDatabaseGenerationArtifactPath {{ return 'credentials.json' }}
function Get-TicketboxDatabaseGenerationServiceTransitionPath {{ return 'service-transition.json' }}
function New-TicketboxDatabaseGenerationChainedArtifact {{
    param($StateRoot, $OperationId, $Kind, $Payload, $LifecycleLock)
    if ($Kind -cne 'terminal-state') {{ throw "unexpected chained artifact $Kind" }}
    if ($null -eq $script:terminal) {{
        $script:terminalWrites += 1
        $script:terminal = [pscustomobject]@{{
            Payload = [pscustomobject]$Payload
            PayloadSha256 = ('6' * 64)
        }}
        if ($script:throwAfterTerminalWrite) {{
            $script:throwAfterTerminalWrite = $false
            throw 'simulated response loss after terminal-state write'
        }}
    }}
    return $script:terminal
}}
function New-TicketboxDatabaseGenerationAdvanceCurrentTransition {{
    param($Intent, $Candidate, $TerminalState)
    return [pscustomobject]@{{
        schema = 'ticketbox-database-generation-current-transition-v1'
        mode = 'advance'
        expected_current_sha256 = ''
        target_payload_sha256 = ('5' * 64)
        target_payload = [pscustomobject]@{{ operation_id = $Intent.Payload.operation_id }}
    }}
}}
function Publish-TicketboxDatabaseGenerationCurrent {{
    param($Transition, $LifecycleLock)
    if ($null -eq $script:current) {{
        $script:currentWrites += 1
        $script:current = [pscustomobject]@{{
            Payload = [pscustomobject]@{{ operation_id = $script:intent.Payload.operation_id; candidate_sha256 = $script:candidate.PayloadSha256; committed_revision = $script:candidate.Payload.target_revision }}
            PayloadSha256 = ('5' * 64)
        }}
    }}
    return $script:current
}}
function Assert-TicketboxDatabaseGenerationCommitReadyArtifact {{ return $script:current }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    if ($null -ne $Primary) {{ throw $Primary }}
    if (@($Cleanup).Count -gt 0) {{ throw $Cleanup }}
}}
    {result_factory}
    {reducer}
    {invoke}
$script:intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111'; target_revision = '20260809_0001'; host_contract_sha256 = ('9' * 64); projection_contract_sha256 = ('9' * 64) }}
}}
$script:candidate = [pscustomobject]@{{ PayloadSha256 = ('c' * 64); Payload = [pscustomobject]@{{ intent_sha256 = ('a' * 64); target_revision = '20260809_0001' }} }}
$script:sourceBinding = [pscustomobject]@{{ PayloadSha256 = ('b' * 64) }}
$script:targetAuthorization = [pscustomobject]@{{ PayloadSha256 = ('d' * 64) }}
$script:runtimeCredentials = [pscustomobject]@{{ RuntimePassword = $script:runtimeSecret; HttpBootstrapSecret = $script:httpSecret; Artifact = [pscustomobject]@{{ PayloadSha256 = ('4' * 64) }} }}
$context = [pscustomobject]@{{ StateRoot = 'state'; Artifact = $script:intent }}
$contract = [pscustomobject]@{{
    data_root = 'C:\\data'
    release_config = [pscustomobject]@{{ secret_byte_count = 32 }}
}}
$script:expectedAppData = Join-Path ([string]$contract.data_root) 'app'
$sourceRejected = $false
try {{ Invoke-TicketboxInstalledDatabaseGeneration $context @{{}} @{{}} $contract $contract 'bootstrap.json' | Out-Null }}
catch {{ $sourceRejected = ([string]$_ -like '*rejected source binding evidence*') }}
if (
    -not $sourceRejected -or $script:retired -or
    $script:retirementCalls -ne 0 -or $script:projectionWrites -ne 0 -or
    $script:terminalWrites -ne 0 -or $script:currentWrites -ne 0
) {{ throw 'invalid source chain reached generation mutation' }}
$script:rejectSourceChain = $false
$script:bootstrapReads = 0
$interrupted = $false
try {{ Invoke-TicketboxInstalledDatabaseGeneration $context @{{}} @{{}} $contract $contract 'bootstrap.json' | Out-Null }}
catch {{ $interrupted = $true }}
if (-not $interrupted -or -not $script:retired -or $script:retirementCalls -ne 1 -or $script:currentWrites -ne 0) {{ throw 'retirement response-loss boundary was not preserved' }}
$terminalInterrupted = $false
try {{ Invoke-TicketboxInstalledDatabaseGeneration $context @{{}} @{{}} $contract $contract 'bootstrap.json' | Out-Null }}
catch {{ $terminalInterrupted = $true }}
if (
    -not $terminalInterrupted -or $script:terminalWrites -ne 1 -or
    $script:currentWrites -ne 0 -or $script:bootstrapExists -or
    $script:credentialsExist
) {{ throw 'terminal-state response-loss boundary was not preserved' }}
$result = Invoke-TicketboxInstalledDatabaseGeneration $context @{{}} @{{}} $contract $contract 'bootstrap.json'
$again = Invoke-TicketboxInstalledDatabaseGeneration $context @{{}} @{{}} $contract $contract 'bootstrap.json'
if (
    $script:bootstrapReads -ne 1 -or $script:retirementCalls -ne 1 -or
    $script:credentialCreates -ne 1 -or
    $script:projectionWrites -ne 1 -or $script:terminalWrites -ne 1 -or
    $script:currentWrites -ne 1 -or
    $script:sourceChainCalls -lt 1 -or
    $script:sourceChainCalls -ne $script:sourceBindingReads -or
    $result.CurrentSha256 -cne ('5' * 64) -or $again.CurrentSha256 -cne ('5' * 64) -or
    $result.CommittedRevision -cne '20260809_0001' -or $result.DatabaseUrl -cne 'postgresql://runtime'
) {{ throw 'owner retry did not converge through one terminal CURRENT publication' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="generation-owner-retry.ps1")
