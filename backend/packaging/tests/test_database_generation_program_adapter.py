"""PowerShell bridge contracts for the build-owned generation program."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]


def _ps_literal(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def test_packaged_bridge_has_one_program_api_and_no_runtime_planner() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (
            PACKAGING / "windows_database_generation_program_adapter.ps1",
            PACKAGING / "windows_database_generation_program_execution.ps1",
        )
    )
    for required in (
        "ticketbox-database-generation-program-validation-v1",
        "Get-TicketboxDatabaseGenerationProgramFromHelper",
        "--validate-generation-program",
        "--generation-program-path",
        "--expected-generation-program-sha256",
        "ticketbox-managed-schema-upgrade-result-v2",
        "-ChildEnvironment $childEnvironment",
    ):
        assert required in source
    for retired in (
        "--c07-installed-upgrade-plan",
        "--managed-schema-plan",
        "Get-TicketboxC07PackagedInstalledUpgradePlan",
        "Get-TicketboxPackagedManagedSchemaPlan",
        "ConvertFrom-TicketboxC07PackagedMaintenancePlan",
        "ConvertFrom-TicketboxManagedSchemaPlan",
    ):
        assert retired not in source


def test_program_validation_and_actions_bind_exact_bytes_and_secret_boundary(
    tmp_path: Path,
) -> None:
    helper = tmp_path / "ticketbox-c07-migrator.exe"
    helper.write_bytes(b"synthetic helper")
    program = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    program.write_text('{"schema":"synthetic"}\n', encoding="utf-8")
    helper_sha = hashlib.sha256(helper.read_bytes()).hexdigest().upper()
    program_sha = hashlib.sha256(program.read_bytes()).hexdigest()
    harness = tmp_path / "generation-program-bridge.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(PACKAGING / "windows_database_generation_contract.ps1")}'
. '{_ps_literal(PACKAGING / "windows_database_generation_program_adapter.ps1")}'
. '{_ps_literal(PACKAGING / "windows_database_generation_program_execution.ps1")}'
$script:secret = 'never-emit-this-secret'
$script:calls = @()
$script:cleanup = 0

function Assert-TicketboxC07ExactProperties {{
    param($Value, [string[]]$ExpectedNames, [string]$ArtifactName)
    $actual = @($Value.PSObject.Properties.Name)
    if ($actual.Count -ne $ExpectedNames.Count -or
        @($actual | Where-Object {{ $_ -cnotin $ExpectedNames }}).Count -ne 0) {{
        throw "$ArtifactName shape mismatch"
    }}
}}
function ConvertTo-TicketboxC07CompactJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 64
}}
function Get-TicketboxC07TextSha256 {{
    param([string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '') }}
    finally {{ $sha.Dispose() }}
}}
function Get-TicketboxPortableFileSha256 {{
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }}
    finally {{ $sha.Dispose(); $stream.Dispose() }}
}}
function Assert-TicketboxC07LowerSha256 {{
    param([string]$Value, [string]$FieldName)
    if ($Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "bad lower $FieldName" }}
}}
function Assert-TicketboxC07Sha256 {{
    param([string]$Value, [string]$FieldName)
    if ($Value -cnotmatch '^[0-9A-F]{{64}}$') {{ throw "bad host $FieldName" }}
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Assert-TicketboxC07MigrationHelperLeaseUnchanged {{ param($Lease) }}
function Close-TicketboxC07MigrationHelperLease {{ param($Lease) }}
function Get-TicketboxPathEntryKindNoFollow {{ return 'File' }}
function Test-TicketboxPathEquals {{
    param([string]$Left, [string]$Right)
    return [IO.Path]::GetFullPath($Left) -ieq [IO.Path]::GetFullPath($Right)
}}
function Open-TicketboxC07VerifiedMigrationHelperLease {{
    param([string]$Path, [string]$ExpectedRelativePath, [int64]$ExpectedSize, [string]$ExpectedSha256)
    return [pscustomobject]@{{ Path = $Path }}
}}
function Invoke-TicketboxWithPlainPostgresqlSecret {{
    param([Security.SecureString]$Secret, [scriptblock]$Action)
    return & $Action $script:secret
}}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        MigratorRole = 'ticketbox_migrator'
    }}
}}
function New-TicketboxPostgresqlLocalDatabaseUrl {{
    param($Authority, [string]$Database, [string]$Role)
    return "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/$Database"
}}
function New-TicketboxProtectedPgPassFile {{
    param([string]$DatabaseUrl, [string]$Password)
    if ($Password -cne $script:secret) {{ throw 'secret mismatch' }}
    return [pscustomobject]@{{
        DatabaseUrl = $DatabaseUrl
        Path = 'C:\\TicketboxInstallerSecrets\\.ticketbox-pgpass-1-11111111111111111111111111111111'
        FullControlAccounts = @('SYSTEM')
        OwnerAccount = 'SYSTEM'
    }}
}}
function Remove-TicketboxProtectedPgPassArtifact {{ $script:cleanup += 1 }}
function Get-TestArgumentValue {{
    param([string[]]$Arguments, [string]$Name)
    $index = [array]::IndexOf($Arguments, $Name)
    if ($index -lt 0) {{ throw "missing $Name" }}
    return [string]$Arguments[$index + 1]
}}

$revision = [ordered]@{{
    revision = '20260729_0001'; down_revision = '20260722_0001'
    module_sha256 = ('1' * 64); transactionality = 'postgresql_single_transaction'
    reversibility = 'forward_only'; downgrade_guard = 'raises_runtime_error_before_ddl'
    resources = @('column:expenses.amount_minor:type=int8')
    asset_recovery = 'same_generation_database_and_assets'
}}
$manifest = [ordered]@{{
    schema = 'ticketbox-c07-revision-manifest-v1'
    operation_kind = 'c07_money_minor_bigint_v1'
    source_revision = '20260722_0001'; target_revision = '20260729_0001'
    revisions = @($revision)
}}
$manifestSha = (Get-TicketboxC07TextSha256 (
    ConvertTo-TicketboxC07CompactJson $manifest
)).ToLowerInvariant()
$programResult = [ordered]@{{
    schema = 'ticketbox-database-generation-program-validation-v1'
    source_revision = 'base'; target_revision = '20260809_0001'; revision_count = 12
    generation_program_sha256 = '{program_sha}'
    c07_source_revision = '20260722_0001'; c07_target_revision = '20260729_0001'
    c07_revision_manifest = $manifest
    c07_revision_manifest_sha256 = $manifestSha
}}
function Invoke-TicketboxBoundedNativeProcess {{
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutMilliseconds,
        [string]$Label, [string]$StandardInputText,
        [System.Collections.IDictionary]$ChildEnvironment)
    $script:calls += ,@($Arguments)
    if ($Arguments -contains '--validate-generation-program') {{
        $payload = $programResult
    }} elseif ($Arguments -contains '--managed-schema-upgrade') {{
        $source = Get-TestArgumentValue $Arguments '--source-revision'
        $target = Get-TestArgumentValue $Arguments '--target-revision'
        $payload = [ordered]@{{
            schema = 'ticketbox-managed-schema-upgrade-result-v2'
            source_revision = $source; target_revision = $target
            generation_program_sha256 = '{program_sha}'
            result = 'target_committed'; alembic_revision = $target
        }}
    }} else {{ throw 'unexpected helper mode' }}
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = (ConvertTo-TicketboxC07CompactJson $payload) + "`n"
        StandardError = ''
    }}
}}

$helperEvidence = [pscustomobject][ordered]@{{
    RelativePath = 'ticketbox-c07-migrator.exe'
    Size = [int64](Get-Item -LiteralPath '{_ps_literal(helper)}').Length
    Sha256 = '{helper_sha}'
}}
$programEvidence = [pscustomobject][ordered]@{{
    RelativePath = 'DATABASE_GENERATION_PROGRAM.json'
    Size = [int64](Get-Item -LiteralPath '{_ps_literal(program)}').Length
    Sha256 = '{program_sha}'
}}
$validated = Get-TicketboxDatabaseGenerationProgramFromHelper `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}' `
    -ProgramPath '{_ps_literal(program)}' `
    -ProgramEvidence $programEvidence
$secure = New-Object Security.SecureString
1..32 | ForEach-Object {{ $secure.AppendChar('x') }}
$secure.MakeReadOnly()
$plan = [pscustomobject][ordered]@{{
    source_revision = '20260729_0001'; target_revision = '20260809_0001'
    upgrade_required = $true; generation_program_sha256 = '{program_sha}'
    generation_operation_id = '11111111-1111-4111-8111-111111111111'
}}
$managed = Invoke-TicketboxPackagedManagedSchemaUpgrade `
    -HostAuthority ([pscustomobject]@{{Schema='authority'}}) `
    -MigratorPassword $secure -Plan $plan `
    -MigrationHelperPath '{_ps_literal(helper)}' `
    -MigrationHelperEvidence $helperEvidence `
    -ExpectedMigrationHelperPath '{_ps_literal(helper)}' `
    -ProgramPath '{_ps_literal(program)}' `
    -ProgramEvidence $programEvidence
$allArguments = @($script:calls | ForEach-Object {{ $_ }})
[ordered]@{{
    target = [string]$validated.target_revision
    managed = [string]$managed.result
    program_calls = @($script:calls | Where-Object {{
        $_ -contains '--generation-program-path' -and
        $_ -contains '--expected-generation-program-sha256'
    }}).Count
    secret_exposed = ($allArguments -join "`n").Contains($script:secret)
    cleanup = [int]$script:cleanup
}} | ConvertTo-Json -Compress
""",
        encoding="utf-8-sig",
    )

    for engine in powershell_contract_engines():
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        evidence = json.loads(completed.stdout.strip().splitlines()[-1])
        assert evidence == {
            "target": "20260809_0001",
            "managed": "target_committed",
            "program_calls": 2,
            "secret_exposed": False,
            "cleanup": 1,
        }
