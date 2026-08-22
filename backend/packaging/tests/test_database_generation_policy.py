from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines, run_powershell_contract_script
from _powershell_contract import powershell_function as _function

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
RELEASE = PACKAGING / "windows_database_generation_release.ps1"
RECOVERY_EVIDENCE = PACKAGING / "windows_database_generation_recovery_evidence.ps1"
POLICY = PACKAGING / "windows_database_generation_policy.ps1"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_successor_release_binding_keeps_installation_identity_without_reusing_install_operation(
    tmp_path: Path,
) -> None:
    assertion = _function(
        RELEASE.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationReleaseBinding",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Get-TicketboxInstalledDatabaseGenerationProgram {{
    return [pscustomobject]@{{ target_revision = '20260821_0001' }}
}}
{assertion}
$release = [pscustomobject]@{{
    InstallationOperationId = '11111111-1111-4111-8111-111111111111'
    InstallationId = '22222222-2222-4222-8222-222222222222'
    BackendVersionFloor = '1.2.3'
    MaintenanceHelperRelativePath = 'ticketbox-database-maintenance.exe'
    MaintenanceHelperSize = 5
    MaintenanceHelperSha256 = ('a' * 64)
    DatabaseGenerationProgramRelativePath = 'DATABASE_GENERATION_PROGRAM.json'
    DatabaseGenerationProgramSize = 7
    DatabaseGenerationProgramSha256 = ('b' * 64)
}}
$intent = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    operation_id = '33333333-3333-4333-8333-333333333333'
    installation_id = $release.InstallationId
    expected_predecessor_sha256 = ('c' * 64)
    target_backend_version = '1.2.3'
    database_maintenance_helper_relative_path = $release.MaintenanceHelperRelativePath
    database_maintenance_helper_size = 5
    database_maintenance_helper_sha256 = ('a' * 64)
    generation_program_relative_path = $release.DatabaseGenerationProgramRelativePath
    generation_program_size = 7
    generation_program_sha256 = ('b' * 64)
    target_revision = '20260821_0001'
}} }}
Assert-TicketboxDatabaseGenerationReleaseBinding $intent $release
$intent.Payload.expected_predecessor_sha256 = ''
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationReleaseBinding $intent $release }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'fresh intent reused a non-installation operation' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-successor-release-binding.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_generation_recovery_tools_are_bound_to_build_identity(tmp_path: Path) -> None:
    assertion = _function(
        RECOVERY_EVIDENCE.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationToolIdentity",
    )
    tool = tmp_path / "pg_dump.exe"
    other = tmp_path / "other.exe"
    script = f"""
$ErrorActionPreference = 'Stop'
function ConvertTo-TicketboxWin32CanonicalPath {{ param([string]$Path); return [IO.Path]::GetFullPath($Path) }}
function Test-TicketboxPathEquals {{ param([string]$Left, [string]$Right); return [IO.Path]::GetFullPath($Left) -ieq [IO.Path]::GetFullPath($Right) }}
function Get-TicketboxPathEntryKindNoFollow {{ param([string]$Path); if ([IO.File]::Exists($Path)) {{ return 'File' }}; return 'Missing' }}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPortableFileSha256 {{
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }}
    finally {{ $sha.Dispose(); $stream.Dispose() }}
}}
{assertion}
$tool = '{tool}'
$other = '{other}'
[IO.File]::WriteAllText($tool, 'original', [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($other, 'original', [Text.UTF8Encoding]::new($false))
$expected = (Get-TicketboxPortableFileSha256 $tool).ToLowerInvariant()
$resolved = Assert-TicketboxDatabaseGenerationToolIdentity $tool $tool 8 $expected 'pg_dump.exe'
if ([IO.Path]::GetFullPath($resolved) -ine [IO.Path]::GetFullPath($tool)) {{ throw 'tool identity did not resolve exact path' }}
$wrongPath = $false
try {{ Assert-TicketboxDatabaseGenerationToolIdentity $other $tool 8 $expected 'pg_dump.exe' | Out-Null }} catch {{ $wrongPath = $true }}
if (-not $wrongPath) {{ throw 'same bytes at a different path were accepted' }}
[IO.File]::WriteAllText($tool, 'modified', [Text.UTF8Encoding]::new($false))
$swapped = $false
try {{ Assert-TicketboxDatabaseGenerationToolIdentity $tool $tool 8 $expected 'pg_dump.exe' | Out-Null }} catch {{ $swapped = $true }}
if (-not $swapped) {{ throw 'same-size swapped tool bytes were accepted' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="database-generation-owner.ps1")


def test_generation_reducer_is_pure_closed_and_mode_free(tmp_path: Path) -> None:
    reducer = _function(
        POLICY.read_text(encoding="utf-8-sig"),
        "Resolve-TicketboxDatabaseGenerationNextAction",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{reducer}
function New-Observation {{
    param(
        [bool]$CredentialsPresent = $false,
        [bool]$SourceBindingPresent = $false,
        [bool]$TargetAuthorizationPresent = $false,
        [bool]$CandidatePresent = $false,
        [bool]$RuntimeCredentialsPresent = $false,
        [string]$BootstrapRetirementState = 'not_applicable',
        [bool]$RuntimeProjectionPresent = $false,
        [bool]$TransientAuthorityPresent = $true,
        [bool]$TerminalStatePresent = $false,
        [bool]$CurrentPresent = $false,
        [bool]$ServiceTransitionPresent = $false
    )
    return [pscustomobject][ordered]@{{
        bootstrap_retirement_state = $BootstrapRetirementState
        candidate_present = $CandidatePresent
        credentials_present = $CredentialsPresent
        current_present = $CurrentPresent
        runtime_credentials_present = $RuntimeCredentialsPresent
        runtime_projection_present = $RuntimeProjectionPresent
        service_transition_present = $ServiceTransitionPresent
        source_binding_present = $SourceBindingPresent
        target_authorization_present = $TargetAuthorizationPresent
        terminal_state_present = $TerminalStatePresent
        transient_authority_present = $TransientAuthorityPresent
    }}
}}
$actions = @(
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -ServiceTransitionPresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true -SourceBindingPresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true -SourceBindingPresent $true -TargetAuthorizationPresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true -RuntimeCredentialsPresent $true -BootstrapRetirementState 'active')
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true -RuntimeCredentialsPresent $true -BootstrapRetirementState 'retired')
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -CredentialsPresent $true -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true -RuntimeCredentialsPresent $true -BootstrapRetirementState 'retired' -RuntimeProjectionPresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true -RuntimeCredentialsPresent $true -BootstrapRetirementState 'retired' -RuntimeProjectionPresent $true -TransientAuthorityPresent $false)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true -RuntimeCredentialsPresent $true -BootstrapRetirementState 'retired' -RuntimeProjectionPresent $true -TransientAuthorityPresent $false -TerminalStatePresent $true)
    Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -SourceBindingPresent $true -TargetAuthorizationPresent $true -CandidatePresent $true -RuntimeCredentialsPresent $true -BootstrapRetirementState 'retired' -RuntimeProjectionPresent $true -TransientAuthorityPresent $false -TerminalStatePresent $true -CurrentPresent $true)
)
$expected = 'reconcile_service_transition,ensure_credentials,bind_source,authorize_target,seal_candidate,seal_runtime_credentials,transition_bootstrap_authority,publish_runtime_projection,retire_transient_authority,seal_terminal,publish_current,read_current'
if (($actions -join ',') -cne $expected) {{ throw "unexpected reducer: $($actions -join ',')" }}
$invalid = $false
try {{ Resolve-TicketboxDatabaseGenerationNextAction (New-Observation -SourceBindingPresent $true) | Out-Null }} catch {{ $invalid = $true }}
if (-not $invalid) {{ throw 'reducer accepted source without credential/current' }}
"""
    run_powershell_contract_script(script, tmp_path, filename="database-generation-owner.ps1")
