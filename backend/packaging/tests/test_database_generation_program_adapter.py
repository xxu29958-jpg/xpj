"""PowerShell adapter contracts for the build-owned generation program."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
MIGRATIONS = PACKAGING.parent / "migrations" / "versions"


def _ps_literal(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def test_packaged_adapter_is_generic_closed_and_has_no_runtime_planner() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (
            PACKAGING / "windows_database_generation_program_adapter.ps1",
            PACKAGING / "windows_database_generation_program_execution.ps1",
        )
    )
    for required in (
        "ticketbox-database-generation-program-validation-v2",
        "ticketbox-database-maintenance.exe",
        "Get-TicketboxDatabaseGenerationProgramFromHelper",
        "Open-TicketboxVerifiedDatabaseMaintenanceHelperLease",
        "--validate-generation-program",
        "--generation-program-path",
        "--expected-generation-program-sha256",
        "ticketbox-managed-schema-upgrade-result-v2",
        "-ChildEnvironment $childEnvironment",
        '[CmdletBinding(DefaultParameterSetName = "ValidateProgram")]',
        '[switch]$ValidateProgram',
        '[switch]$UpgradeManagedSchema',
        '[switch]$VerifyTarget',
    ):
        assert required in source
    assert "[string[]]$Arguments" not in source
    for retired in (
        "ticketbox-c07-migrator",
        "ticketbox-c07-revision-manifest",
        "--c07-installed-upgrade-plan",
        "--managed-schema-plan",
        "Get-TicketboxC07",
        "c07_revision_manifest",
    ):
        assert retired not in source


def test_frozen_generation_revisions_do_not_read_ambient_environment() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in sorted(MIGRATIONS.glob("*.py"))
    )
    for ambient_api in ("os.getenv", "os.environ", "environ[", "getenv("):
        assert ambient_api not in source
    upload_link = (
        MIGRATIONS / "20260528_0001_upload_link_expiry.py"
    ).read_text(encoding="utf-8-sig")
    assert "UPLOAD_LINK_TTL_DAYS = 90" in upload_link
    assert "LEGACY_EXPIRY_SPREAD_DAYS = 30" in upload_link


def test_program_validation_binds_exact_bytes_schema_and_helper_lease(
    tmp_path: Path,
) -> None:
    helper = tmp_path / "ticketbox-database-maintenance.exe"
    helper.write_bytes(b"synthetic database maintenance helper")
    program = tmp_path / "DATABASE_GENERATION_PROGRAM.json"
    program.write_text('{"schema":"synthetic"}\n', encoding="utf-8")
    helper_sha = hashlib.sha256(helper.read_bytes()).hexdigest().upper()
    program_sha = hashlib.sha256(program.read_bytes()).hexdigest()
    harness = tmp_path / "generation-program-adapter.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(PACKAGING / "windows_database_generation_contract.ps1")}'
. '{_ps_literal(PACKAGING / "windows_database_generation_program_adapter.ps1")}'
. '{_ps_literal(PACKAGING / "windows_database_generation_program_execution.ps1")}'
$script:closeCount = 0
$script:processCount = 0
$script:addUnknownField = $false
$script:processFailure = $false
$script:leaseFailure = $false
$script:closeFailure = $false
$env:DATABASE_URL = 'postgresql://ambient-authority-is-forbidden'
$env:TICKETBOX_API_TOKEN = 'ambient-token-is-forbidden'

function Get-TicketboxPortableFileSha256 {{
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '') }}
    finally {{ $sha.Dispose(); $stream.Dispose() }}
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow {{ return 'File' }}
function Test-TicketboxPathEquals {{
    param([string]$Left, [string]$Right)
    return [IO.Path]::GetFullPath($Left) -ieq [IO.Path]::GetFullPath($Right)
}}
function Open-TicketboxVerifiedDatabaseMaintenanceHelperLease {{
    param([string]$Path, [string]$ExpectedRelativePath, [int64]$ExpectedSize,
        [string]$ExpectedSha256)
    if ([IO.Path]::GetFileName($Path) -cne $ExpectedRelativePath -or
        (Get-Item -LiteralPath $Path).Length -ne $ExpectedSize -or
        (Get-TicketboxPortableFileSha256 $Path) -cne $ExpectedSha256) {{
        throw 'helper evidence mismatch'
    }}
    return [pscustomobject]@{{ Path = $Path }}
}}
function Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged {{
    param($Lease)
    if ($script:leaseFailure) {{ throw 'lease cleanup failure' }}
}}
function Close-TicketboxDatabaseMaintenanceHelperLease {{
    $script:closeCount += 1
    if ($script:closeFailure) {{ throw 'close cleanup failure' }}
}}
function Invoke-TicketboxBoundedNativeProcess {{
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutMilliseconds,
        [string]$Label, [string]$StandardInputText,
        [System.Collections.IDictionary]$ChildEnvironment)
    $script:processCount += 1
    if ([IO.Path]::GetFullPath($FilePath) -ine [IO.Path]::GetFullPath('{_ps_literal(helper)}')) {{
        throw 'process did not execute the leased helper path'
    }}
    if ($ChildEnvironment.Contains('DATABASE_URL') -or
        $ChildEnvironment.Contains('TICKETBOX_API_TOKEN')) {{
        throw 'ambient authority leaked into helper child environment'
    }}
    if ($Arguments -notcontains '--validate-generation-program' -or
        $Arguments -notcontains '--generation-program-path' -or
        $Arguments -notcontains '--expected-generation-program-sha256') {{
        throw 'validation arguments are incomplete'
    }}
    if ($script:processFailure) {{ throw 'primary execution failure' }}
    $payload = [ordered]@{{
        schema = 'ticketbox-database-generation-program-validation-v2'
        source_revision = 'base'
        target_revision = '20260809_0001'
        revision_count = 43
        generation_program_sha256 = '{program_sha}'
    }}
    if ($script:addUnknownField) {{ $payload.unknown = 'forbidden' }}
    return [pscustomobject]@{{
        ExitCode = 0
        StandardOutput = (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload) + "`n"
        StandardError = ''
    }}
}}

$helperEvidence = [pscustomobject][ordered]@{{
    RelativePath = 'ticketbox-database-maintenance.exe'
    Size = [int64](Get-Item -LiteralPath '{_ps_literal(helper)}').Length
    Sha256 = '{helper_sha}'
}}
$programEvidence = [pscustomobject][ordered]@{{
    RelativePath = 'DATABASE_GENERATION_PROGRAM.json'
    Size = [int64](Get-Item -LiteralPath '{_ps_literal(program)}').Length
    Sha256 = '{program_sha}'
}}
$validated = Get-TicketboxDatabaseGenerationProgramFromHelper `
    -MaintenanceHelperPath '{_ps_literal(helper)}' `
    -MaintenanceHelperEvidence $helperEvidence `
    -ExpectedMaintenanceHelperPath '{_ps_literal(helper)}' `
    -ProgramPath '{_ps_literal(program)}' `
    -ProgramEvidence $programEvidence
$script:addUnknownField = $true
$closed = $false
try {{
    [void](Get-TicketboxDatabaseGenerationProgramFromHelper `
        -MaintenanceHelperPath '{_ps_literal(helper)}' `
        -MaintenanceHelperEvidence $helperEvidence `
        -ExpectedMaintenanceHelperPath '{_ps_literal(helper)}' `
        -ProgramPath '{_ps_literal(program)}' `
        -ProgramEvidence $programEvidence)
}}
catch {{ $closed = $_.Exception.Message -match '闭合合同' }}
$script:addUnknownField = $false
$script:processFailure = $true
$script:leaseFailure = $true
$script:closeFailure = $true
$aggregate = $null
try {{
    [void](Get-TicketboxDatabaseGenerationProgramFromHelper `
        -MaintenanceHelperPath '{_ps_literal(helper)}' `
        -MaintenanceHelperEvidence $helperEvidence `
        -ExpectedMaintenanceHelperPath '{_ps_literal(helper)}' `
        -ProgramPath '{_ps_literal(program)}' `
        -ProgramEvidence $programEvidence)
}}
catch {{ $aggregate = $_.Exception }}
[ordered]@{{
    target = [string]$validated.target_revision
    revision_count = [int]$validated.revision_count
    process_count = [int]$script:processCount
    close_count = [int]$script:closeCount
    unknown_rejected = $closed
    aggregate_type = $aggregate.GetType().FullName
    aggregate_messages = @($aggregate.InnerExceptions | ForEach-Object {{ $_.Message }})
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
        result = json.loads(completed.stdout.strip())
        assert result == {
            "target": "20260809_0001",
            "revision_count": 43,
            "process_count": 3,
            "close_count": 3,
            "unknown_rejected": True,
            "aggregate_type": "System.AggregateException",
            "aggregate_messages": [
                "primary execution failure",
                "lease cleanup failure",
                "close cleanup failure",
            ],
        }
