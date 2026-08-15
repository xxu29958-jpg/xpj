import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"


def _literal(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows projection contract")
def test_runtime_projection_read_is_pure_and_fail_closed(tmp_path: Path) -> None:
    harness = tmp_path / "runtime-projection-read.ps1"
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PROJECTION)}'
$script:writes = 0
$script:mode = 'exact'
$script:secret = New-Object Security.SecureString
$script:secret.AppendChar('x')
$script:secret.MakeReadOnly()
$script:current = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [ordered]@{{
        intent_sha256 = ('a' * 64)
        committed_revision = '20260809_0001'
    }}
}}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 64
}}
function Get-TicketboxDatabaseGenerationRuntimeCurrentPath {{ return 'runtime-current.json' }}
function Read-TicketboxProtectedUtf8Artifact {{
    param($Path, $FullControlAccounts, $ReadExecuteAccounts, $OwnerAccount)
    if ($script:mode -ceq 'missing') {{ throw 'runtime CURRENT missing' }}
    $envelope = [ordered]@{{
        schema = 'ticketbox-database-generation-envelope-v1'
        kind = 'current'
        payload_sha256 = [string]$script:current.PayloadSha256
        payload = $script:current.Payload
    }}
    $text = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope
    if ($script:mode -ceq 'foreign') {{ $text = '{{}}' }}
    return [pscustomobject]@{{ Text = $text }}
}}
function Read-EnvMap {{
    $map = [Collections.Generic.Dictionary[string,string]]::new()
    $map['DATABASE_URL'] = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
    return $map
}}
function Get-TicketboxLocalDatabaseConnection {{
    return [pscustomobject]@{{
        DatabaseUrl = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        PersistedDatabaseUrl = 'postgresql+psycopg://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        Password = $script:secret
    }}
}}
function Assert-TicketboxConnectedPostgresDataRoot {{}}
function Write-TicketboxDatabaseGenerationRuntimeCurrent {{ $script:writes += 1 }}
$script:TicketboxC07DatabaseName = 'ticketbox'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
$script:TicketboxDatabaseGenerationAclAccounts = @('SYSTEM', 'Administrators')
$script:TicketboxDatabaseGenerationOwnerAccount = 'Administrators'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        target_revision = '20260809_0001'
    }}
}}
$contract = [pscustomobject]@{{
    backend_service_name = 'TicketboxBackend'; env_path = '.env'
    psql_path = 'psql.exe'; pg_data = 'pgdata'; database_tool_timeout_ms = 1000
}}
$authority = [pscustomobject]@{{ Port = 5432 }}
$result = Read-TicketboxDatabaseGenerationRuntimeProjection `
    $intent $script:current $authority $contract @{{}}
if ($result.CurrentSha256 -cne ('c' * 64) -or $script:writes -ne 0) {{
    throw 'exact runtime projection read mutated state'
}}
foreach ($mode in @('missing', 'foreign')) {{
    $script:mode = $mode
    $rejected = $false
    try {{ Read-TicketboxDatabaseGenerationRuntimeProjection `
        $intent $script:current $authority $contract @{{}} | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected -or $script:writes -ne 0) {{
        throw "$mode runtime CURRENT did not fail closed without a write"
    }}
}}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
