from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_contract_engines,
    powershell_function,
    run_powershell_contract_script,
)

PACKAGING = Path(__file__).resolve().parents[1]
INSTALLATION_SAFETY = PACKAGING / "windows_installation_safety.ps1"
BUNDLED_DATABASE = PACKAGING / "windows_bundled_database.ps1"
GENERATION_CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
INSTALLED_READER = PACKAGING / "windows_installed_dataset_reader.ps1"
RESTORE = PACKAGING / "windows_dataset_restore.ps1"
DATASET_OPERATION = PACKAGING / "windows_installed_dataset_operation.ps1"
RESTORE_ARTIFACTS = PACKAGING / "windows_installed_dataset_restore_artifacts.ps1"
RESTORE_RUNTIME = PACKAGING / "windows_dataset_restore_runtime.ps1"

_ELEVATED_WINDOWS = sys.platform == "win32" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def _require_elevated_windows_acl(value: str | None) -> bool:
    if value not in {None, "0", "1"}:
        raise ValueError("XPJ_REQUIRE_ELEVATED_WINDOWS_ACL must be unset, 0, or 1")
    return value == "1"


_REQUIRE_ELEVATED_WINDOWS_ACL = _require_elevated_windows_acl(os.getenv("XPJ_REQUIRE_ELEVATED_WINDOWS_ACL"))


def test_published_candidate_reconciles_main_host_before_h1_publication() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    publication = restore.split('"publish_current" {', maxsplit=1)[1].split('"retire_rollback" {', maxsplit=1)[0]

    assert publication.index("Set-TicketboxInstalledDatasetPublishedAcls") < (
        publication.index("Start-TicketboxOwnedServiceIfExists")
    )
    assert publication.index("Start-TicketboxOwnedServiceIfExists") < (
        publication.index("Invoke-TicketboxInstalledDatabaseGeneration")
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("0", False), ("1", True)],
)
def test_elevated_windows_acl_requirement_is_closed(
    value: str | None,
    expected: bool,
) -> None:
    assert _require_elevated_windows_acl(value) is expected
    with pytest.raises(ValueError, match="unset, 0, or 1"):
        _require_elevated_windows_acl("true")


def test_runtime_environment_acl_contract_is_exact_and_writer_owned() -> None:
    writer = powershell_function(
        BUNDLED_DATABASE.read_text(encoding="utf-8-sig"),
        "Write-EnvNoBom",
    )
    projection_writer = powershell_function(
        PROJECTION.read_text(encoding="utf-8-sig"),
        "Write-TicketboxDatabaseGenerationRuntimeEnvironment",
    )
    reader = powershell_function(
        INSTALLED_READER.read_text(encoding="utf-8-sig"),
        "Read-TicketboxInstalledDatasetPublicBaseUrl",
    )

    assert "[Parameter(Mandatory = $true)][string]$BackendServiceName" in writer
    assert "Write-TicketboxProtectedUtf8FileDurable" in writer
    assert '"NT SERVICE\\$BackendServiceName"' in writer
    assert '-OwnerAccount "SYSTEM"' in writer
    assert "-ReplaceExisting" in writer
    assert "Write-TicketboxFileAtomically" not in writer
    assert "-BackendServiceName ([string]$ProjectionContract.backend_service_name)" in (projection_writer)
    assert "Assert-TicketboxExactFileAcl" in reader
    assert '"NT SERVICE\\$([string]$identity.BackendServiceName)"' in reader
    assert "Assert-TicketboxLegacyProtectedFileAcl" not in reader
    assert '"app\\runtime-settings\\runtime-settings.json"' in reader
    assert reader.index('"app\\runtime-settings\\runtime-settings.json"') < reader.index('"app\\.env"')


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_mutable_public_origin_is_not_generation_projection_authority(
    tmp_path: Path,
) -> None:
    source = GENERATION_CONTRACT.read_text(encoding="utf-8-sig")
    normalizer = powershell_function(
        source,
        "ConvertTo-TicketboxDatabaseGenerationPublicBaseUrl",
    )
    projection = powershell_function(
        source,
        "New-TicketboxDatabaseGenerationProjectionContract",
    )
    authority_digest = powershell_function(
        source,
        "Get-TicketboxDatabaseGenerationProjectionAuthoritySha256",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:TicketboxDatabaseGenerationBackendServiceName = 'ticketbox-backend'
$script:inputs = @()
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 10 -Compress)
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param($Text)
    $script:inputs += $Text
    return ('a' * 64)
}}
{normalizer}
{projection}
{authority_digest}
function New-Projection {{
    param($PublicBaseUrl, $BackendPort)
    return New-TicketboxDatabaseGenerationProjectionContract `
        -BackendServiceName 'ticketbox-backend' -EnvPath 'C:\\data\\app\\.env' `
        -StopTimeoutMilliseconds 60000 -BackendPort $BackendPort `
        -PgBin 'C:\\Ticketbox\\pg\\bin' -Timezone 'Asia/Shanghai' `
        -PublicBaseUrl $PublicBaseUrl -PsqlPath 'C:\\Ticketbox\\pg\\bin\\psql.exe' `
        -PgData 'C:\\data\\pgdata' -DatabaseToolTimeoutMilliseconds 60000
}}
$a = New-Projection 'https://one.example' 8123
$b = New-Projection 'https://two.example' 8123
$c = New-Projection 'https://two.example' 8124
[void](Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 $a)
[void](Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 $b)
[void](Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 $c)
if ($script:inputs[0] -cne $script:inputs[1]) {{ throw 'mutable public origin changed Generation authority' }}
if ($script:inputs[1] -ceq $script:inputs[2]) {{ throw 'immutable backend port left Generation authority' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-projection-authority-boundary.ps1",
    )


@pytest.mark.skipif(
    not _ELEVATED_WINDOWS and not _REQUIRE_ELEVATED_WINDOWS_ACL,
    reason="exact SYSTEM-owned Windows ACL contract requires elevation",
)
def test_runtime_environment_writer_and_public_reader_share_exact_acl(
    tmp_path: Path,
) -> None:
    assert _ELEVATED_WINDOWS, "XPJ_REQUIRE_ELEVATED_WINDOWS_ACL=1 but the runner is not elevated"
    root = str(tmp_path).replace("'", "''")
    paths = {
        "safety": str(INSTALLATION_SAFETY).replace("'", "''"),
        "database": str(BUNDLED_DATABASE).replace("'", "''"),
        "projection": str(PROJECTION).replace("'", "''"),
        "reader": str(INSTALLED_READER).replace("'", "''"),
    }
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{paths["safety"]}'
. '{paths["database"]}'
. '{paths["projection"]}'
. '{paths["reader"]}'
function ConvertTo-TicketboxTimeoutSeconds {{ param($Milliseconds); return 60 }}
$dataRoot = Join-Path '{root}' 'data'
$appRoot = Join-Path $dataRoot 'app'
New-Item -ItemType Directory -Force -Path $appRoot | Out-Null
$envPath = Join-Path $appRoot '.env'
Set-Content -LiteralPath $envPath -Value 'stale=broad' -Encoding UTF8
Invoke-TicketboxIcaclsChecked $envPath @('/inheritance:e')
Invoke-TicketboxIcaclsChecked $envPath @('/grant', '*S-1-1-0:F')
$projection = [pscustomobject]@{{
    backend_service_name = 'TrustedInstaller'
    env_path = $envPath
    stop_timeout_ms = 60000
    backend_port = 8123
    pg_bin = 'C:\Ticketbox\pg\bin'
    timezone = 'Asia/Shanghai'
    public_base_url = 'https://public.example'
}}
$subject = [pscustomobject]@{{ Identity = [pscustomobject]@{{
    DataRoot = $dataRoot
    BackendServiceName = 'TrustedInstaller'
}} }}
Write-TicketboxDatabaseGenerationRuntimeEnvironment `
    -DatabaseUrl 'postgresql://runtime' `
    -ProjectionContract $projection `
    -HttpBootstrapSecret 'bootstrap'
$resolved = Read-TicketboxInstalledDatasetPublicBaseUrl -Subject $subject
if ($resolved -cne 'https://public.example') {{ throw 'exact writer-reader round trip failed' }}
$extraSid = ConvertTo-TicketboxAccountSid 'NT SERVICE\wuauserv'
Invoke-TicketboxIcaclsChecked $envPath @('/grant', "*${{extraSid}}:F")
$rejected = $false
try {{ Read-TicketboxInstalledDatasetPublicBaseUrl -Subject $subject | Out-Null }}
catch {{ if ($_.Exception.Message -match '未授权账户') {{ $rejected = $true }} else {{ throw }} }}
if (-not $rejected) {{ throw 'unrelated service SID retained PUBLIC_BASE_URL authority' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-public-base-url-exact-acl.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restore_contracts_use_durable_public_origin_without_ambient_reread(
    tmp_path: Path,
) -> None:
    contracts = powershell_function(
        INSTALLED_READER.read_text(encoding="utf-8-sig"),
        "New-TicketboxInstalledDatabaseGenerationContracts",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Read-TicketboxInstalledDatasetPublicBaseUrl {{ throw 'ambient env was reread' }}
function Read-TicketboxDatabaseGenerationProgramContract {{
    return [pscustomobject]@{{ RelativePath = 'DATABASE_GENERATION_PROGRAM.json'; Size = 1; Sha256 = ('a' * 64) }}
}}
function New-TicketboxDatabaseGenerationHostContract {{ return [pscustomobject]@{{}} }}
function New-TicketboxDatabaseGenerationProjectionContract {{
    param($BackendServiceName, $EnvPath, $StopTimeoutMilliseconds, $BackendPort, $PgBin, $Timezone, $PublicBaseUrl, $PsqlPath, $PgData, $DatabaseToolTimeoutMilliseconds)
    return [pscustomobject]@{{ public_base_url = $PublicBaseUrl }}
}}
{contracts}
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{
        InstallDir = 'C:\\Ticketbox'; DataRoot = 'C:\\TicketboxData'
        BackendServiceName = 'ticketbox-backend'; PgServiceName = 'ticketbox-pg'
        BackendPort = 8123; OperationId = '11111111-1111-4111-8111-111111111111'
        InstallationId = '22222222-2222-4222-8222-222222222222'; BackendVersionFloor = '1.0.0'
    }}
    Manifest = [pscustomobject]@{{
        DatabaseGenerationProgram = [pscustomobject]@{{ RelativePath = 'DATABASE_GENERATION_PROGRAM.json'; Sha256 = ('a' * 64) }}
        PgDump = [pscustomobject]@{{ Size = 1; Sha256 = ('b' * 64) }}
        PgRestore = [pscustomobject]@{{ Size = 1; Sha256 = ('c' * 64) }}
        DatabaseMaintenanceHelper = [pscustomobject]@{{ RelativePath = 'helper.exe'; Size = 1; Sha256 = ('d' * 64) }}
    }}
    Release = [pscustomobject]@{{ stop_timeout_ms = 60000; database_tool_timeout_ms = 60000; default_timezone = 'Asia/Shanghai' }}
}}
$resolved = New-TicketboxInstalledDatabaseGenerationContracts `
    -Subject $subject -PublicBaseUrl 'https://public.example'
if ([string]$resolved.Projection.public_base_url -cne 'https://public.example') {{
    throw 'durable public origin was not used'
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-durable-public-origin.ps1",
    )
    restore = RESTORE.read_text(encoding="utf-8-sig")
    artifact_contract = DATASET_OPERATION.read_text(encoding="utf-8-sig")
    assert '"public_base_url"' in artifact_contract
    assert "-PublicBaseUrl $publicBaseUrl" in restore
    assert "-PublicBaseUrl ([string]$request.Payload.public_base_url)" in restore


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_predecessor_runtime_rejects_projection_drift_before_mutation(
    tmp_path: Path,
) -> None:
    restore = powershell_function(
        RESTORE_RUNTIME.read_text(encoding="utf-8-sig"),
        "Restore-TicketboxInstalledDatasetPredecessorRuntime",
    )
    classifier = powershell_function(
        DATASET_OPERATION.read_text(encoding="utf-8-sig"),
        "Resolve-TicketboxInstalledDatasetRestoreCurrentDisposition",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$successor = '22222222-2222-4222-8222-222222222222'
$request = [pscustomobject]@{{ PayloadSha256 = ('d' * 64); Payload = [pscustomobject]@{{
    current_sha256 = ('a' * 64)
    predecessor_intent_sha256 = ('e' * 64)
    predecessor_intent_payload = [pscustomobject]@{{ projection_contract_sha256 = ('1' * 64) }}
}} }}
$intent = [pscustomobject]@{{ PayloadSha256 = ('c' * 64); Payload = [pscustomobject]@{{
    operation_id = $successor; source_request_sha256 = ('d' * 64)
    expected_predecessor_sha256 = ('a' * 64)
}} }}
$current = [pscustomobject]@{{ PayloadSha256 = ('b' * 64); Payload = [pscustomobject]@{{
    operation_id = $successor; intent_sha256 = ('c' * 64)
    expected_predecessor_sha256 = ('a' * 64)
}} }}
function Assert-TicketboxInstalledDatasetOperation {{ param($Operation, $ExpectedOperationKind); return $Operation }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ return '{{}}' }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('2' * 64) }}
function Get-TicketboxDatabaseGenerationProjectionAuthoritySha256 {{ return ('2' * 64) }}
function Set-TicketboxInstalledDatasetRestorePhysicalSelection {{ throw 'physical selection crossed projection drift' }}
{classifier}
{restore}
$rejected = $false
try {{
    Restore-TicketboxInstalledDatasetPredecessorRuntime `
        -Subject ([pscustomobject]@{{}}) -Request $request `
        -Paths ([pscustomobject]@{{ operation_id = $successor }}) `
        -StateRoot 'C:\\state' `
        -Contracts ([pscustomobject]@{{ Projection = [pscustomobject]@{{ public_base_url = 'https://changed.example' }} }}) `
        -Intent $intent -Current $current `
        -LifecycleLock ([pscustomobject]@{{}})
}}
catch {{
    if ($_.Exception.Message -match 'projection contract') {{ $rejected = $true }} else {{ throw }}
}}
if (-not $rejected) {{ throw 'projection drift was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-predecessor-projection-drift.ps1",
    )
