from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_active_intent_store_rejects_stale_predecessor_cas(tmp_path: Path) -> None:
    source = ARTIFACTS.read_text(encoding="utf-8-sig")
    functions = "\n".join(
        powershell_function(source, name)
        for name in (
            "Get-TicketboxDatabaseGenerationPayloadProperties",
            "Read-TicketboxDatabaseGenerationEnvelope",
            "New-TicketboxDatabaseGenerationEnvelopeText",
            "New-TicketboxDatabaseGenerationActiveIntent",
            "Replace-TicketboxDatabaseGenerationActiveIntent",
        )
    )
    root = str(tmp_path).replace("'", "''")
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:TicketboxDatabaseGenerationActiveIntentName = 'active-intent.json'
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM')
$script:TicketboxDatabaseGenerationOwnerAccount = 'SYSTEM'
$activeIntentPath = Join-Path '{root}' $script:TicketboxDatabaseGenerationActiveIntentName
if ([IO.File]::Exists($activeIntentPath)) {{ [IO.File]::Delete($activeIntentPath) }}
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Get-TicketboxPathEntryKindNoFollow {{
    param($Path)
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    return 'Missing'
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "$Label fields changed" }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label invalid" }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 30 -Compress)
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param($Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes([string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }} finally {{ $sha.Dispose() }}
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path, $Text, $FullControlAccounts, $OwnerAccount, [switch]$ReplaceExisting)
    if ($ReplaceExisting) {{
        if (-not [IO.File]::Exists($Path)) {{ throw 'replace target disappeared' }}
    }} elseif ([IO.File]::Exists($Path)) {{
        throw 'create-only active intent already exists'
    }}
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    return [pscustomobject]@{{ Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) }}
}}
{functions}
$payload = [ordered]@{{
    schema = 'ticketbox-database-generation-intent-v1'
    operation_id = '11111111-1111-4111-8111-111111111111'
    installation_id = '22222222-2222-4222-8222-222222222222'
    expected_predecessor_sha256 = ''
    source_request_sha256 = ('a' * 64)
    target_backend_version = '1.2.3'
    database_maintenance_helper_relative_path = 'ticketbox-database-maintenance.exe'
    database_maintenance_helper_size = 1
    database_maintenance_helper_sha256 = ('b' * 64)
    generation_program_relative_path = 'DATABASE_GENERATION_PROGRAM.json'
    generation_program_size = 2
    generation_program_sha256 = ('c' * 64)
    host_contract_sha256 = ('d' * 64)
    projection_contract_sha256 = ('e' * 64)
    target_revision = '20260821_0001'
}}
$first = New-TicketboxDatabaseGenerationActiveIntent '{root}' $payload @{{}}
$successor = [ordered]@{{}}
foreach ($property in $payload.Keys) {{ $successor[$property] = $payload[$property] }}
$successor.operation_id = '33333333-3333-4333-8333-333333333333'
$successor.expected_predecessor_sha256 = ('f' * 64)
$second = Replace-TicketboxDatabaseGenerationActiveIntent `
    '{root}' $first.PayloadSha256 $successor @{{}}
$staleRejected = $false
try {{
    Replace-TicketboxDatabaseGenerationActiveIntent `
        '{root}' $first.PayloadSha256 $payload @{{}} | Out-Null
}} catch {{ $staleRejected = $true }}
$readback = Read-TicketboxDatabaseGenerationEnvelope `
    (Join-Path '{root}' 'active-intent.json') 'intent'
if (
    -not $staleRejected -or
    $second.PayloadSha256 -cne $readback.PayloadSha256 -or
    [string]$readback.Payload.operation_id -cne
        '33333333-3333-4333-8333-333333333333'
) {{ throw 'active intent stale predecessor CAS escaped' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="active-intent-store-cas.ps1")


def test_active_intent_store_has_no_arbitrary_path_writer() -> None:
    source = ARTIFACTS.read_text(encoding="utf-8-sig")
    assert "function Write-TicketboxDatabaseGenerationEnvelope" not in source
    assert "function Replace-TicketboxDatabaseGenerationEnvelope" not in source
    for name in (
        "New-TicketboxDatabaseGenerationActiveIntent",
        "Replace-TicketboxDatabaseGenerationActiveIntent",
    ):
        function = powershell_function(source, name)
        assert "[string]$Path" not in function
        assert "$script:TicketboxDatabaseGenerationActiveIntentName" in function
