from __future__ import annotations

import os
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
RUNTIME_SETTINGS = PACKAGING / "windows_installed_runtime_settings.ps1"
INSTALLER = PACKAGING / "install_bundled_services.ps1"
BUILD_INNO = PACKAGING / "build_inno_installer.ps1"
INNO = PACKAGING / "ticketbox-installer.iss"
PROVENANCE = PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"
RUNTIME_SETTINGS_STORE = PACKAGING.parent / "app" / "services" / "runtime_settings_store.py"


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
    assert "[Parameter(Mandatory = $true)][string]$BackendServiceName" in writer
    assert "Write-TicketboxProtectedUtf8FileDurable" in writer
    assert '-FullControlAccounts @("SYSTEM", "BUILTIN\\Administrators")' in writer
    assert '-ReadExecuteAccounts @("NT SERVICE\\$BackendServiceName")' in writer
    assert '-OwnerAccount "SYSTEM"' in writer
    assert "-ReplaceExisting" in writer
    assert "Write-TicketboxFileAtomically" not in writer
    assert "-BackendServiceName ([string]$ProjectionContract.backend_service_name)" in (projection_writer)
    assert "RuntimeSettings" not in projection_writer
    assert "runtime-settings" not in PROJECTION.read_text(encoding="utf-8-sig")
    assert "Read-TicketboxInstalledDatasetPublicBaseUrl" not in INSTALLED_READER.read_text(
        encoding="utf-8-sig"
    )


def test_restore_bootstrap_binding_is_explicit_and_does_not_seed_script_globals() -> None:
    restore = RESTORE.read_text(encoding="utf-8-sig")
    database = BUNDLED_DATABASE.read_text(encoding="utf-8-sig")
    bootstrap_owner = powershell_function(
        database,
        "Get-OrCreatePostgresBootstrapRecoveryState",
    )
    path_resolver = powershell_function(
        database,
        "Get-PostgresBootstrapRecoveryPath",
    )
    bootstrap_reader = powershell_function(
        database,
        "Read-PostgresBootstrapRecoveryState",
    )

    for name in ("AppData", "PgData", "PgPort", "SecretByteCount"):
        assert f"$script:{name}" not in restore
    assert "-DataRoot ([string]$subject.Identity.DataRoot)" in restore
    assert "-AppData $appData" in restore
    assert "-SecretByteCount ([int]$subject.Release.secret_byte_count)" in restore
    assert "-AppData $appData" in restore.split("-BootstrapRecoveryPath", maxsplit=1)[1]
    assert "[Parameter(Mandatory = $true)][string]$DataRoot" in bootstrap_owner
    assert "[Parameter(Mandatory = $true)][string]$AppData" in bootstrap_owner
    assert "[Parameter(Mandatory = $true)][int]$SecretByteCount" in bootstrap_owner
    assert "[Parameter(Mandatory = $true)][string]$AppData" in path_resolver
    assert "[Parameter(Mandatory = $true)][string]$AppData" in bootstrap_reader
    assert "[Parameter(Mandatory = $true)][int]$SecretByteCount" in bootstrap_reader


def test_runtime_settings_mutation_has_one_backend_writer() -> None:
    store = RUNTIME_SETTINGS_STORE.read_text(encoding="utf-8")
    assert "def patch_runtime_settings(" in store
    assert "write_protected_file_replace(" in store
    assert not RUNTIME_SETTINGS.exists()
    for path in (INSTALLER, BUILD_INNO, INNO, PROVENANCE):
        source = path.read_text(encoding="utf-8-sig")
        assert "windows_installed_runtime_settings.ps1" not in source
        assert "Initialize-TicketboxInstalledRuntimeSettings" not in source


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_mutable_runtime_settings_are_not_generation_or_restore_authority(
    tmp_path: Path,
) -> None:
    contracts = powershell_function(
        INSTALLED_READER.read_text(encoding="utf-8-sig"),
        "New-TicketboxInstalledDatabaseGenerationContracts",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Read-TicketboxDatabaseGenerationProgramContract {{
    return [pscustomobject]@{{ RelativePath = 'DATABASE_GENERATION_PROGRAM.json'; Size = 1; Sha256 = ('a' * 64) }}
}}
function New-TicketboxDatabaseGenerationHostContract {{ return [pscustomobject]@{{}} }}
function New-TicketboxDatabaseGenerationProjectionContract {{
    param($BackendServiceName, $EnvPath, $StopTimeoutMilliseconds, $BackendPort, $PgBin, $Timezone, $PsqlPath, $PgData, $DatabaseToolTimeoutMilliseconds)
    return [pscustomobject]@{{ backend_port = $BackendPort }}
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
$resolved = New-TicketboxInstalledDatabaseGenerationContracts -Subject $subject
if ([int]$resolved.Projection.backend_port -ne 8123) {{ throw 'projection contract was not built' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="dataset-restore-runtime-settings-boundary.ps1",
    )
    restore = RESTORE.read_text(encoding="utf-8-sig")
    artifact_contract = DATASET_OPERATION.read_text(encoding="utf-8-sig")
    projection_contract = powershell_function(
        GENERATION_CONTRACT.read_text(encoding="utf-8-sig"),
        "New-TicketboxDatabaseGenerationProjectionContract",
    )
    assert "public_base_url" not in projection_contract
    assert '"public_base_url"' not in artifact_contract
    assert "PublicBaseUrl" not in contracts
    assert "publicBaseUrl" not in restore


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
