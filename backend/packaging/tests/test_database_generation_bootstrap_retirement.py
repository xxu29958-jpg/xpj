from pathlib import Path

import pytest
from _powershell_contract import (
    powershell_function,
    run_powershell_contract_script,
)

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
OWNER = PACKAGING / "windows_database_generation.ps1"
CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
GENERATION_CREDENTIALS = PACKAGING / "windows_database_generation_credentials.ps1"
RETIRED_ADAPTER = PACKAGING / "windows_database_generation_adapter.ps1"
CREDENTIALS = PACKAGING / "windows_postgresql_credentials.ps1"
SOURCE = PACKAGING / "windows_database_generation_source.ps1"
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
RETIREMENT = PACKAGING / "windows_database_generation_retirement.ps1"
SINGLE_USER = PACKAGING / "windows_database_generation_single_user.ps1"
POSTGRESQL_SINGLE_USER = PACKAGING / "windows_postgresql_single_user.ps1"
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"
BUNDLED_DATABASE = PACKAGING / "windows_bundled_database.ps1"
C07_DATABASE = PACKAGING / "windows_c07_database.ps1"
INSTALLER = PACKAGING / "install_bundled_services.ps1"
ISS = PACKAGING / "ticketbox-installer.iss"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = BACKEND / "scripts" / "windows_build_provenance.ps1"


def test_bootstrap_superuser_owner_is_physically_retired_and_shipped() -> None:
    owner = OWNER.read_text(encoding="utf-8-sig")
    generation_credentials = GENERATION_CREDENTIALS.read_text(encoding="utf-8-sig")
    credentials = CREDENTIALS.read_text(encoding="utf-8-sig")
    source = SOURCE.read_text(encoding="utf-8-sig")
    projection = PROJECTION.read_text(encoding="utf-8-sig")
    retirement = RETIREMENT.read_text(encoding="utf-8-sig")
    single_user = SINGLE_USER.read_text(encoding="utf-8-sig")
    postgresql_single_user = POSTGRESQL_SINGLE_USER.read_text(encoding="utf-8-sig")
    artifacts = ARTIFACTS.read_text(encoding="utf-8-sig")
    bundled_database = BUNDLED_DATABASE.read_text(encoding="utf-8-sig")
    c07_database = C07_DATABASE.read_text(encoding="utf-8-sig")
    installer = INSTALLER.read_text(encoding="utf-8-sig")
    production = "\n".join(
        path.read_text(encoding="utf-8-sig") for path in PACKAGING.rglob("*.ps1")
    )

    for prefix in ("C07", "Postgresql"):
        for operation in ("Assert", "Acquire", "Renew", "Revoke"):
            assert f"{operation}-Ticketbox{prefix}SuperuserCapability" not in production
    retired_paths = (
        PACKAGING / "windows_c07_superuser_recovery.ps1",
        PACKAGING / "windows_postgresql_superuser_capability.ps1",
        PACKAGING / "postgresql_superuser_capability",
    )
    shipment = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (ISS, BUILD, PROVENANCE)
    )
    for retired_path in retired_paths:
        assert not retired_path.exists()
        relative = str(retired_path.relative_to(PACKAGING))
        assert relative not in installer + shipment
        assert relative.replace("\\", "/") not in installer + shipment
    assert not RETIRED_ADAPTER.exists()

    for filename in (
        "windows_postgresql_credentials.ps1",
        "windows_postgresql_single_user.ps1",
        "windows_database_generation_retirement.ps1",
    ):
        assert owner.count(f'"{filename}"') == 1
    assert '"windows_database_generation_single_user.ps1"' not in owner
    for filename in (
        "windows_postgresql_single_user.ps1",
        "windows_database_generation_single_user.ps1",
    ):
        assert filename in shipment
    assert owner.count("New-TicketboxDatabaseGenerationMaintenanceAuthority `") == 1
    assert (
        owner
    ).count("Close-TicketboxDatabaseGenerationMaintenanceAuthority `") == 2
    assert "[object]$BootstrapRecoveryState" not in owner
    assert "$databaseGenerationBootstrapState = Read-PostgresBootstrapRecoveryState" not in installer
    assert installer.count("-BootstrapRecoveryPath (Get-PostgresBootstrapRecoveryPath)") == 1
    assert '"runtime-credentials"' in artifacts
    operation_reader = powershell_function(
        artifacts,
        "Read-TicketboxDatabaseGenerationOperationArtifact",
    )
    assert '"runtime-credentials"' in operation_reader
    assert '"terminal-state"' in artifacts
    assert "ticketbox-database-generation-runtime-credentials-v1" in generation_credentials
    assert "function Read-TicketboxDatabaseGenerationRuntimeCredentials" in generation_credentials
    assert "function New-TicketboxDatabaseGenerationRuntimeCredentials" in generation_credentials
    assert "function Close-TicketboxDatabaseGenerationRuntimeCredentials" in generation_credentials
    assert "function Close-TicketboxDatabaseGenerationCredentials" in generation_credentials
    assert "function Prepare-DatabaseIfNeeded" not in bundled_database
    assert "function Set-EnvDatabaseUrl" not in bundled_database
    assert "function Invoke-Psql" not in bundled_database

    factory = powershell_function(
        generation_credentials,
        "New-TicketboxDatabaseGenerationMaintenanceAuthority",
    )
    assert "HttpBootstrapSecret" not in factory
    assert "RolePassword" not in factory
    assert "HostAuthoritySha256" in factory
    for consumer in (source, owner, projection):
        assert consumer.count(
            "Assert-TicketboxDatabaseGenerationMaintenanceAuthority `"
        ) == 1
        assert "SuperuserCapability" not in consumer

    retire = powershell_function(
        retirement,
        "Retire-TicketboxDatabaseGenerationBootstrapAuthority",
    )
    prepare_projection = powershell_function(
        projection,
        "Prepare-TicketboxDatabaseGenerationRuntimeProjection",
    )
    publish_projection = powershell_function(
        projection,
        "Publish-TicketboxDatabaseGenerationRuntimeProjection",
    )
    read_projection = powershell_function(
        projection,
        "Read-TicketboxDatabaseGenerationRuntimeProjection",
    )
    invoke = powershell_function(owner, "Invoke-TicketboxInstalledDatabaseGeneration")
    retirement_read = powershell_function(
        retirement,
        "Test-TicketboxDatabaseGenerationBootstrapRetirement",
    )
    assert "COMMENT ON ROLE postgres" in single_user
    assert "ALTER ROLE postgres PASSWORD NULL" in single_user
    assert "--single" in single_user
    assert "Invoke-TicketboxOwnedOneShotService" in retire
    assert "-ExpectedRuntimeExecutables @($shawl, $postgres)" in retire
    assert "$shawl, $powershell, $postgres" not in retire + retirement
    assert "Enter-TicketboxPostgresqlStoppedHostAuthority" in retire
    assert "Restore-TicketboxDatabaseGenerationFormalPostgresqlService" in retire
    assert "Restore-TicketboxPostgresqlFormalServiceCommand" in retirement
    assert "pg_stat_activity" not in retirement_read
    assert "shobj_description" in retirement_read
    assert "json_build_array" in retirement_read
    assert "role.oid IS NOT NULL" in retirement_read
    assert "COALESCE" not in retirement_read
    assert "public.app_meta" not in retire + retirement_read + single_user
    assert "HBA" not in retire + postgresql_single_user
    assert "Retire-TicketboxDatabaseGenerationBootstrapAuthority" not in (
        prepare_projection + publish_projection
    )
    assert "Write-TicketboxDatabaseGenerationRuntimeCurrent" not in publish_projection
    assert "Test-TicketboxDatabaseGenerationBootstrapRetirement" in read_projection
    assert invoke.index("Test-TicketboxDatabaseGenerationBootstrapRetirement") < invoke.index(
        "Read-PostgresBootstrapRecoveryState"
    )
    assert invoke.index(
        "Prepare-TicketboxDatabaseGenerationRuntimeProjection"
    ) < invoke.index("Retire-TicketboxDatabaseGenerationBootstrapAuthority")
    assert invoke.index(
        "Retire-TicketboxDatabaseGenerationBootstrapAuthority"
    ) < invoke.rindex("Publish-TicketboxDatabaseGenerationRuntimeProjection")
    cleanup = invoke.index("Remove-TicketboxDatabaseGenerationCredentials")
    terminal = invoke.index('"terminal-state"')
    current = invoke.rindex("Publish-TicketboxDatabaseGenerationCurrent")
    assert invoke.index("Remove-PostgresBootstrapRecoveryState") < cleanup < terminal < current
    terminal_contract = artifacts[
        artifacts.index('"terminal-state" {') : artifacts.index('"current" {')
    ]
    assert '"host_contract_sha256"' in terminal_contract
    assert "host_authority_sha256" not in terminal_contract + read_projection + invoke
    for clear in (
        "[Array]::Clear($bytes, 0, $bytes.Length)",
        "[Array]::Clear($saltCopy, 0, $saltCopy.Length)",
        "if ($generatedSalt) { [Array]::Clear($Salt, 0, $Salt.Length) }",
    ):
        assert clear in credentials

    credential_gate = c07_database[c07_database.index("$postgresqlCredentials =") :]
    credential_gate = credential_gate.split("# Runtime DML", 1)[0]
    for dependency in (
        "Assert-TicketboxPostgresqlSecureString",
        "Invoke-TicketboxWithPlainPostgresqlSecret",
    ):
        assert dependency in credential_gate


def test_bootstrap_retirement_observation_is_closed_over_absent_and_drift(
    tmp_path: Path,
) -> None:
    retirement = RETIREMENT.read_text(encoding="utf-8-sig")
    c07_database = C07_DATABASE.read_text(encoding="utf-8-sig")
    script = rf"""
$ErrorActionPreference = 'Stop'
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 20
}}
{powershell_function(retirement, "Get-TicketboxDatabaseGenerationBootstrapRetirementJson")}
{powershell_function(c07_database, "ConvertFrom-TicketboxC07SingleRow")}
$script:observed = ''
function Invoke-TicketboxC07Sql {{ return $script:observed }}
{powershell_function(retirement, "Test-TicketboxDatabaseGenerationBootstrapRetirement")}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        target_revision = '20260809_0001'
    }}
}}
$candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        intent_sha256 = ('a' * 64)
        target_revision = '20260809_0001'
    }}
}}
$hostAuthority = [pscustomobject]@{{ Schema = 'ticketbox-postgresql-host-authority-v1' }}
$runtimePassword = [Security.SecureString]::new()
$expected = Get-TicketboxDatabaseGenerationBootstrapRetirementJson $intent $candidate

$script:observed = ConvertTo-Json -Compress -InputObject @($true, $null)
if (Test-TicketboxDatabaseGenerationBootstrapRetirement `
        $intent $candidate $hostAuthority $runtimePassword) {{
    throw 'absent retirement marker was accepted'
}}

$script:observed = ConvertTo-Json -Compress -InputObject @($true, $expected)
if (-not (Test-TicketboxDatabaseGenerationBootstrapRetirement `
        $intent $candidate $hostAuthority $runtimePassword)) {{
    throw 'exact retirement marker was rejected'
}}

foreach ($hostile in @(
    (ConvertTo-Json -Compress -InputObject @($false, $null)),
    (ConvertTo-Json -Compress -InputObject @($true, 'foreign-marker')),
    (ConvertTo-Json -Compress -InputObject @('true', $null))
)) {{
    $script:observed = $hostile
    $rejected = $false
    try {{
        Test-TicketboxDatabaseGenerationBootstrapRetirement `
            $intent $candidate $hostAuthority $runtimePassword | Out-Null
    }} catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "hostile retirement observation escaped: $hostile" }}
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-bootstrap-retirement-observation.ps1",
    )


def test_maintenance_authority_is_exact_process_local_and_closes(
    tmp_path: Path,
) -> None:
    generation_credentials = GENERATION_CREDENTIALS.read_text(encoding="utf-8-sig")
    script = rf"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Assert-TicketboxPostgresqlSecureString {{
    param($Value, $Label)
    if ($null -eq $Value -or $Value.Length -lt 32) {{ throw 'invalid secure string' }}
}}
{powershell_function(CONTRACT.read_text(encoding="utf-8-sig"), "Assert-TicketboxDatabaseGenerationExactProperties")}
{powershell_function(CREDENTIALS.read_text(encoding="utf-8-sig"), "ConvertTo-TicketboxPostgresqlSecureString")}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return $Value | ConvertTo-Json -Compress -Depth 20
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param($Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes([string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }}
    finally {{ $sha.Dispose() }}
}}
    {powershell_function(CONTRACT.read_text(encoding="utf-8-sig"), "Get-TicketboxDatabaseGenerationHostAuthoritySha256")}
{powershell_function(generation_credentials, "New-TicketboxDatabaseGenerationMaintenanceAuthority")}
    {powershell_function(CONTRACT.read_text(encoding="utf-8-sig"), "Assert-TicketboxDatabaseGenerationMaintenanceAuthority")}
{powershell_function(generation_credentials, "Close-TicketboxDatabaseGenerationMaintenanceAuthority")}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
    }}
}}
$hostAuthorityFixture = [pscustomobject][ordered]@{{
    Schema = 'ticketbox-postgresql-host-authority-v1'
    ServiceName = 'TicketboxPg'
    ServiceProcessId = 1234
    PostmasterProcessId = 5678
    PgCtlPath = 'C:\Ticketbox\pg\bin\pg_ctl.exe'
    PsqlPath = 'C:\Ticketbox\pg\bin\psql.exe'
    PgData = 'C:\TicketboxRuntime\pgdata'
    PhysicalPgData = 'D:\Ticketbox\pgdata'
    Port = 55432
    UsesRuntimeBinding = $true
    DataVolumeIdentity = 'volume-11111111-1111-4111-8111-111111111111'
}}
$authority = New-TicketboxDatabaseGenerationMaintenanceAuthority `
    $intent ('S' * 48) $hostAuthorityFixture @{{}}
[void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
    $authority $intent $hostAuthorityFixture @{{}})
$lastCandidate = $null
foreach ($mutation in @(
    @{{ Name = 'ServiceName'; Value = 'OtherPg' }},
    @{{ Name = 'ServiceProcessId'; Value = 1235 }},
    @{{ Name = 'PostmasterProcessId'; Value = 5679 }},
    @{{ Name = 'PgCtlPath'; Value = 'C:\Other\pg_ctl.exe' }},
    @{{ Name = 'PsqlPath'; Value = 'C:\Other\psql.exe' }},
    @{{ Name = 'PgData'; Value = 'C:\Other\pgdata' }},
    @{{ Name = 'PhysicalPgData'; Value = 'D:\Other\pgdata' }},
    @{{ Name = 'Port'; Value = 55433 }},
    @{{ Name = 'UsesRuntimeBinding'; Value = $false }},
    @{{ Name = 'DataVolumeIdentity'; Value = 'volume-22222222-2222-4222-8222-222222222222' }}
)) {{
    $candidate = $hostAuthorityFixture.PSObject.Copy()
    $candidate.($mutation.Name) = $mutation.Value
    $lastCandidate = $candidate
    $driftRejected = $false
    try {{
        Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
            $authority $intent $candidate @{{}} | Out-Null
    }}
    catch {{ $driftRejected = $true }}
    if (-not $driftRejected) {{ throw "host drift retained authority: $($mutation.Name)" }}
}}
$closeRejected = $false
try {{
    Close-TicketboxDatabaseGenerationMaintenanceAuthority `
        $authority $intent $lastCandidate @{{}}
}}
catch {{ $closeRejected = $true }}
$closedRejected = $false
try {{
    Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $authority $intent $hostAuthorityFixture @{{}} | Out-Null
}}
catch {{ $closedRejected = $true }}
if (
    -not $closeRejected -or -not $closedRejected -or
    -not $authority.Closed -or $null -ne $authority.Secret
) {{ throw 'failed maintenance authority cleanup retained usable secret state' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-bootstrap-retirement.ps1",
    )


def test_runtime_credentials_are_durable_exact_candidate_and_closed(
    tmp_path: Path,
) -> None:
    credentials = CREDENTIALS.read_text(encoding="utf-8-sig")
    generation_credentials = GENERATION_CREDENTIALS.read_text(encoding="utf-8-sig")
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:artifact = $null
function Assert-TicketboxLifecycleOperationLease {{}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join '|') -cne ($expected -join '|')) {{ throw "$Label is not closed" }}
}}
function New-TicketboxDatabaseGenerationChainedArtifact {{
    param($StateRoot, $OperationId, $Kind, $Payload, $LifecycleLock)
    $script:artifact = [pscustomobject]@{{
        Payload = [pscustomobject]$Payload
        PayloadSha256 = ('e' * 64)
    }}
    return $script:artifact
}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{ return $script:artifact }}
{powershell_function(credentials, "ConvertTo-TicketboxPostgresqlSecureString")}
{powershell_function(credentials, "Invoke-TicketboxWithPlainPostgresqlSecret")}
{powershell_function(generation_credentials, "Read-TicketboxDatabaseGenerationRuntimeCredentials")}
{powershell_function(generation_credentials, "Close-TicketboxDatabaseGenerationRuntimeCredentials")}
{powershell_function(generation_credentials, "New-TicketboxDatabaseGenerationRuntimeCredentials")}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111' }}
}}
$candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        intent_sha256 = ('a' * 64)
        target_revision = '20260809_0001'
    }}
}}
$runtimeSecret = ConvertTo-TicketboxPostgresqlSecureString ('r' * 48) 'runtime'
try {{
    $created = New-TicketboxDatabaseGenerationRuntimeCredentials `
        'state' $intent $candidate @{{ RuntimePassword = $runtimeSecret }} ('h' * 43) @{{}}
    $runtimePlain = Invoke-TicketboxWithPlainPostgresqlSecret `
        $created.RuntimePassword {{ param($Value); return $Value }}
    $httpPlain = Invoke-TicketboxWithPlainPostgresqlSecret `
        $created.HttpBootstrapSecret {{ param($Value); return $Value }}
    if ($runtimePlain -cne ('r' * 48) -or $httpPlain -cne ('h' * 43)) {{
        throw 'durable runtime credentials changed secret bytes'
    }}
    if ([string]$created.Artifact.Payload.candidate_sha256 -cne ('c' * 64)) {{
        throw 'runtime credentials did not bind the sealed candidate'
    }}
    $candidate.PayloadSha256 = ('d' * 64)
    $driftRejected = $false
    try {{
        Read-TicketboxDatabaseGenerationRuntimeCredentials 'state' $intent $candidate | Out-Null
    }} catch {{ $driftRejected = $true }}
    if (-not $driftRejected) {{ throw 'runtime credentials accepted foreign CURRENT' }}
    Close-TicketboxDatabaseGenerationRuntimeCredentials $created
    if (
        $null -ne $created.RuntimePassword -or
        $null -ne $created.HttpBootstrapSecret -or
        $null -ne $created.Artifact
    ) {{
        throw 'runtime credential secret graph remained reachable after close'
    }}
}}
finally {{ $runtimeSecret.Dispose() }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-runtime-credentials.ps1",
    )


def test_credential_readers_dispose_partial_secret_construction(
    tmp_path: Path,
) -> None:
    generation_credentials = GENERATION_CREDENTIALS.read_text(encoding="utf-8-sig")
    script = rf"""
$ErrorActionPreference = 'Stop'
class TrackedSecret : System.IDisposable {{
    [bool]$Disposed = $false
    [void] Dispose() {{ $this.Disposed = $true }}
}}
$script:conversionCount = 0
$script:firstSecret = $null
function ConvertTo-TicketboxPostgresqlSecureString {{
    param($Value, $Label)
    $script:conversionCount += 1
    if (($script:conversionCount % 2) -eq 0) {{ throw 'second secret conversion failed' }}
    $script:firstSecret = [TrackedSecret]::new()
    return $script:firstSecret
}}
function ConvertTo-TicketboxPostgresqlScramVerifier {{ throw 'verifier must not be reached' }}
function Assert-TicketboxDatabaseGenerationExactProperties {{}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{ return $script:artifact }}
{powershell_function(generation_credentials, "Read-TicketboxDatabaseGenerationCredentials")}
{powershell_function(generation_credentials, "Close-TicketboxDatabaseGenerationCredentials")}
{powershell_function(generation_credentials, "Read-TicketboxDatabaseGenerationRuntimeCredentials")}
{powershell_function(generation_credentials, "Close-TicketboxDatabaseGenerationRuntimeCredentials")}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111' }}
}}
$candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        intent_sha256 = ('a' * 64)
    }}
}}
$salt = [Convert]::ToBase64String((0..15))
$script:artifact = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    schema = 'ticketbox-database-generation-credentials-v1'
    operation_id = '11111111-1111-4111-8111-111111111111'
    intent_sha256 = ('a' * 64)
    runtime_password = ('r' * 48)
    runtime_scram_salt = $salt
    migrator_password = ('m' * 48)
    migrator_scram_salt = $salt
}} }}
$rejected = $false
try {{ Read-TicketboxDatabaseGenerationCredentials 'state' $intent | Out-Null }}
catch {{ $rejected = $true }}
if (-not $rejected -or -not $script:firstSecret.Disposed) {{
    throw 'database credential partial construction leaked its first secret'
}}
$script:conversionCount = 0
$script:firstSecret = $null
$script:artifact = [pscustomobject]@{{ Payload = [pscustomobject]@{{
    schema = 'ticketbox-database-generation-runtime-credentials-v1'
    operation_id = '11111111-1111-4111-8111-111111111111'
    intent_sha256 = ('a' * 64)
    candidate_sha256 = ('c' * 64)
    runtime_password = ('r' * 48)
    http_bootstrap_secret = ('h' * 48)
}} }}
$rejected = $false
try {{ Read-TicketboxDatabaseGenerationRuntimeCredentials 'state' $intent $candidate | Out-Null }}
catch {{ $rejected = $true }}
if (-not $rejected -or -not $script:firstSecret.Disposed) {{
    throw 'runtime credential partial construction leaked its first secret'
}}
$transientRuntime = [TrackedSecret]::new()
$transientMigrator = [TrackedSecret]::new()
$transient = [pscustomobject]@{{
    Artifact = [pscustomobject]@{{ PayloadSha256 = ('1' * 64) }}
    RuntimePassword = $transientRuntime
    MigratorPassword = $transientMigrator
    RuntimeVerifier = 'runtime-verifier'
    MigratorVerifier = 'migrator-verifier'
}}
Close-TicketboxDatabaseGenerationCredentials $transient
if (
    -not $transientRuntime.Disposed -or -not $transientMigrator.Disposed -or
    $null -ne $transient.RuntimePassword -or $null -ne $transient.MigratorPassword -or
    [string]$transient.RuntimeVerifier -cne '' -or
    [string]$transient.MigratorVerifier -cne '' -or
    $null -ne $transient.Artifact
) {{
    throw 'transient credential close left secret or artifact authority reachable'
}}
$publishedRuntime = [TrackedSecret]::new()
$publishedHttp = [TrackedSecret]::new()
$published = [pscustomobject]@{{
    Artifact = [pscustomobject]@{{ PayloadSha256 = ('2' * 64) }}
    RuntimePassword = $publishedRuntime
    HttpBootstrapSecret = $publishedHttp
}}
Close-TicketboxDatabaseGenerationRuntimeCredentials $published
if (
    -not $publishedRuntime.Disposed -or -not $publishedHttp.Disposed -or
    $null -ne $published.RuntimePassword -or
    $null -ne $published.HttpBootstrapSecret -or
    $null -ne $published.Artifact
) {{
    throw 'runtime credential close left secret or artifact authority reachable'
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-partial-credential-construction.ps1",
    )


def test_service_transition_repair_is_exact_and_cleanup_safe(tmp_path: Path) -> None:
    retirement = RETIREMENT.read_text(encoding="utf-8-sig")
    repair = powershell_function(
        retirement,
        "Repair-TicketboxDatabaseGenerationServiceTransition",
    )
    restore = powershell_function(
        retirement,
        "Restore-TicketboxDatabaseGenerationFormalPostgresqlService",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = [Collections.Generic.List[string]]::new()
$script:throwReadback = $false
$script:currentImagePath = '"C:\Ticketbox\shawl.exe" run temporary'
$script:expectedTemporary = $script:currentImagePath
$script:intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111' }}
}}
$script:candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{ target_revision = '20260809_0001' }}
}}
$script:transition = [pscustomobject]@{{
    operation_id = '11111111-1111-4111-8111-111111111111'
    intent_sha256 = ('a' * 64)
    candidate_sha256 = ('c' * 64)
    service_name = 'TicketboxPg'
    pg_ctl_path = 'C:\Ticketbox\pgsql\bin\pg_ctl.exe'
    postgres_path = 'C:\Ticketbox\pgsql\bin\postgres.exe'
    shawl_path = 'C:\Ticketbox\shawl\shawl.exe'
    powershell_path = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    helper_path = 'C:\Ticketbox\installer\windows_database_generation_single_user.ps1'
    helper_sha256 = ('d' * 64)
    pg_data = 'C:\TicketboxRuntime\pgdata'
    physical_pg_data = 'D:\Ticketbox\pgdata'
    port = 5432
    formal_image_path = '"C:\Ticketbox\pgsql\bin\pg_ctl.exe" runservice -N TicketboxPg -D C:\TicketboxRuntime\pgdata'
    temporary_image_path = $script:expectedTemporary
    phase = 'start_authorized'
}}
$hostContract = [pscustomobject]@{{
    install_dir = 'C:\Ticketbox'
    pg_service_name = 'TicketboxPg'
    pg_ctl_path = 'C:\Ticketbox\pgsql\bin\pg_ctl.exe'
    release_config = [pscustomobject]@{{
        stop_timeout_ms = 30000
        database_tool_timeout_ms = 60000
        service_state_timeout_ms = 30000
        service_poll_interval_ms = 100
        postgres_ready_timeout_ms = 30000
        postgres_ready_poll_interval_ms = 100
    }}
}}
function Read-TicketboxDatabaseGenerationServiceTransition {{ return $script:transition }}
function Read-TicketboxDatabaseGenerationOperationArtifact {{ return $script:candidate }}
function Get-TicketboxWindowsPowerShellExecutable {{ return $script:transition.powershell_path }}
function New-TicketboxPostgresqlSingleUserServiceImagePath {{ return $script:expectedTemporary }}
function Test-TicketboxPathEquals {{
    param($Left, $Right)
    return ([string]$Left).ToLowerInvariant() -ceq ([string]$Right).ToLowerInvariant()
}}
function Get-TicketboxPortableFileSha256 {{ return ('d' * 64) }}
function Restore-TicketboxDatabaseGenerationFormalPostgresqlService {{
    $script:events.Add('restore')
}}
function Write-TicketboxDatabaseGenerationServiceTransition {{
    $script:events.Add('write')
}}
function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {{
    $script:events.Add('resolve')
    return [pscustomobject]@{{ Value = 'fresh-host' }}
}}
function Read-TicketboxDatabaseGenerationRuntimeCredentials {{
    return [pscustomobject]@{{ RuntimePassword = 'runtime' }}
}}
function Test-TicketboxDatabaseGenerationBootstrapRetirement {{
    $script:events.Add('readback')
    if ($script:throwReadback) {{ throw 'readback failed' }}
    return $true
}}
function Close-TicketboxDatabaseGenerationRuntimeCredentials {{
    $script:events.Add('close')
}}
function Remove-TicketboxDatabaseGenerationServiceTransition {{
    $script:events.Add('remove')
}}
    {repair}
Repair-TicketboxDatabaseGenerationServiceTransition 'state' $script:intent $hostContract @{{}}
if (($script:events -join '|') -cne 'restore|write|resolve|readback|close|remove') {{
    throw "repair order drifted: $($script:events -join '|')"
}}
$script:events.Clear()
$script:transition.candidate_sha256 = ('e' * 64)
$rejected = $false
try {{ Repair-TicketboxDatabaseGenerationServiceTransition 'state' $script:intent $hostContract @{{}} }}
catch {{ $rejected = $true }}
if (-not $rejected -or $script:events.Count -ne 0) {{
    throw 'foreign transition mutated the service'
}}
$script:transition.candidate_sha256 = ('c' * 64)
$script:throwReadback = $true
$rejected = $false
try {{ Repair-TicketboxDatabaseGenerationServiceTransition 'state' $script:intent $hostContract @{{}} }}
catch {{ $rejected = $true }}
if (-not $rejected -or ($script:events -join '|') -cne 'restore|write|resolve|readback|close') {{
    throw "readback failure cleanup drifted: $($script:events -join '|')"
}}

$script:events.Clear()
$script:currentImagePath = $script:transition.temporary_image_path
function Get-TicketboxServiceImagePathExact {{ return $script:currentImagePath }}
function Stop-TicketboxOwnedServiceIfExists {{ $script:events.Add('stop') }}
function Restore-TicketboxPostgresqlFormalServiceCommand {{
    param($StoppedHost, $Contract)
    $script:events.Add('restore-formal')
    $script:currentImagePath = [string]$StoppedHost.FormalImagePath
}}
function Start-TicketboxOwnedServiceIfExists {{ $script:events.Add('start'); return @{{}} }}
    {restore}
Restore-TicketboxDatabaseGenerationFormalPostgresqlService $script:transition $hostContract
if (
    ($script:events -join '|') -cne 'stop|restore-formal|start' -or
    $script:currentImagePath -cne $script:transition.formal_image_path
) {{ throw 'temporary command was not restored exactly' }}
$script:events.Clear()
$script:currentImagePath = '"C:\Ticketbox\shawl.exe" run foreign-command'
$rejected = $false
try {{ Restore-TicketboxDatabaseGenerationFormalPostgresqlService $script:transition $hostContract }}
catch {{ $rejected = $true }}
if (-not $rejected -or $script:events.Count -ne 0) {{
    throw 'third ImagePath authority was accepted'
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-service-transition-repair.ps1",
    )


def test_bootstrap_retirement_preserves_primary_and_restore_failures(tmp_path: Path) -> None:
    retirement = RETIREMENT.read_text(encoding="utf-8-sig")
    retire = powershell_function(
        retirement,
        "Retire-TicketboxDatabaseGenerationBootstrapAuthority",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
$script:events = [Collections.Generic.List[string]]::new()
$script:scenario = ''
$script:retired = $false
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = '11111111-1111-4111-8111-111111111111' }}
}}
$candidate = [pscustomobject]@{{
    PayloadSha256 = ('c' * 64)
    Payload = [pscustomobject]@{{ target_revision = '20260809_0001' }}
}}
$hostContract = [pscustomobject]@{{
    install_dir = 'C:\Ticketbox'
    pg_service_name = 'TicketboxPg'
    pg_ctl_path = 'C:\Ticketbox\pgsql\bin\pg_ctl.exe'
    release_config = [pscustomobject]@{{
        stop_timeout_ms = 30000
        database_tool_timeout_ms = 60000
        service_poll_interval_ms = 100
    }}
}}
$hostAuthority = [pscustomobject]@{{
    PgData = 'C:\TicketboxRuntime\pgdata'
    PhysicalPgData = 'D:\Ticketbox\pgdata'
    Port = 5432
}}
$runtimePassword = [Security.SecureString]::new()
function Assert-TicketboxLifecycleOperationLease {{}}
function Get-TicketboxPathEntryKindNoFollow {{ return 'File' }}
function Assert-NoTicketboxAncestorReparsePoints {{}}
function Get-TicketboxWindowsPowerShellExecutable {{
    return 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
}}
function New-TicketboxPostgresqlSingleUserServiceImagePath {{ return 'temporary-image' }}
function Get-TicketboxServiceImagePathExact {{ return 'formal-image' }}
function Get-TicketboxPortableFileSha256 {{ return ('d' * 64) }}
function Write-TicketboxDatabaseGenerationServiceTransition {{
    param($StateRoot, $Transition, $Phase, $LifecycleLock)
    $script:events.Add("write:$Phase")
}}
function Enter-TicketboxPostgresqlStoppedHostAuthority {{ return [pscustomobject]@{{ ServiceName = 'TicketboxPg' }} }}
function Set-TicketboxPostgresqlSingleUserServiceCommand {{}}
function Invoke-TicketboxOwnedOneShotService {{
    if ($script:scenario -eq 'success') {{
        $script:retired = $true
        return [pscustomobject]@{{ ExitCode = 0; ServiceSpecificExitCode = 0 }}
    }}
    if ($script:scenario -eq 'success-ignores-specific') {{
        $script:retired = $true
        return [pscustomobject]@{{ ExitCode = 0; ServiceSpecificExitCode = 23 }}
    }}
    if ($script:scenario -eq 'response-loss') {{ $script:retired = $true }}
    if ($script:scenario -eq 'win32-service-exit') {{
        return [pscustomobject]@{{ ExitCode = 23; ServiceSpecificExitCode = 0 }}
    }}
    if ($script:scenario -eq 'win32-service-exit-ignores-specific') {{
        return [pscustomobject]@{{ ExitCode = 23; ServiceSpecificExitCode = 42 }}
    }}
    if ($script:scenario -eq 'specific-service-exit') {{
        return [pscustomobject]@{{ ExitCode = 1066; ServiceSpecificExitCode = 23 }}
    }}
    if ($script:scenario -eq 'specific-service-exit-missing-code') {{
        return [pscustomobject]@{{ ExitCode = 1066; ServiceSpecificExitCode = 0 }}
    }}
    throw 'primary failure'
}}
function Restore-TicketboxDatabaseGenerationFormalPostgresqlService {{
    $script:events.Add('restore')
    if ($script:scenario -eq 'double-failure') {{ throw 'restore failure' }}
}}
function Resolve-TicketboxInstalledDatabaseGenerationHostAuthority {{
    $script:events.Add('resolve')
    return [pscustomobject]@{{ Value = 'fresh-host' }}
}}
function Test-TicketboxDatabaseGenerationBootstrapRetirement {{
    $script:events.Add('readback')
    if ($script:scenario -eq 'observation-failure') {{ throw 'readback failure' }}
    return $script:retired
}}
function Remove-TicketboxDatabaseGenerationServiceTransition {{ $script:events.Add('remove') }}
function Throw-TicketboxDatabaseGenerationOperationFailure {{
    param($Primary, $Cleanup)
    throw "aggregate:$($Primary.Exception.Message)|$($Cleanup.Exception.Message)"
}}
{retire}
foreach ($case in @(
    [pscustomobject]@{{ Name = 'success'; Expected = 'fresh-host' }},
    [pscustomobject]@{{ Name = 'success-ignores-specific'; Expected = 'fresh-host' }},
    [pscustomobject]@{{ Name = 'response-loss'; Expected = 'fresh-host' }},
    [pscustomobject]@{{ Name = 'precommit'; Expected = 'primary failure' }},
    [pscustomobject]@{{ Name = 'win32-service-exit'; Expected = 'database generation single-user service 失败（exit=23）。' }},
    [pscustomobject]@{{ Name = 'win32-service-exit-ignores-specific'; Expected = 'database generation single-user service 失败（exit=23）。' }},
    [pscustomobject]@{{ Name = 'specific-service-exit'; Expected = 'database generation single-user service 失败（exit=23）。' }},
    [pscustomobject]@{{ Name = 'specific-service-exit-missing-code'; Expected = 'database generation single-user service 失败（exit=1066）。' }},
    [pscustomobject]@{{ Name = 'observation-failure'; Expected = 'aggregate:primary failure|readback failure' }},
    [pscustomobject]@{{ Name = 'double-failure'; Expected = 'aggregate:primary failure|restore failure' }}
)) {{
    $script:scenario = $case.Name
    $script:retired = $false
    $script:events.Clear()
    $actual = ''
    try {{
        $value = Retire-TicketboxDatabaseGenerationBootstrapAuthority `
            'state' $intent $candidate $hostContract $hostAuthority `
            $runtimePassword @{{}}
        $actual = [string]$value.Value
    }} catch {{ $actual = $_.Exception.Message }}
    if ($actual -cne $case.Expected) {{
        throw "$($case.Name) returned '$actual'"
    }}
    if ($case.Name -in @('success', 'success-ignores-specific')) {{
        $expectedEvents = @(
            'write:intent_written',
            'write:host_stopped',
            'write:start_authorized',
            'write:restore_required',
            'restore',
            'write:pgctl_restored',
            'resolve',
            'readback',
            'remove'
        ) -join '|'
        if (($script:events -join '|') -cne $expectedEvents) {{
            throw "$($case.Name) did not complete exact authority order: $($script:events -join '|')"
        }}
    }} elseif ($case.Name -eq 'response-loss') {{
        if (($script:events -join '|') -cnotmatch 'write:pgctl_restored\|resolve\|readback\|remove$') {{
            throw "response-loss did not converge: $($script:events -join '|')"
        }}
    }} elseif ($case.Name -in @(
        'precommit',
        'win32-service-exit',
        'win32-service-exit-ignores-specific',
        'specific-service-exit',
        'specific-service-exit-missing-code',
        'observation-failure'
    )) {{
        if (($script:events -join '|') -cnotmatch 'write:pgctl_restored\|resolve\|readback$') {{
            throw "$($case.Name) did not preserve transition: $($script:events -join '|')"
        }}
    }} else {{
        $afterRestore = @($script:events | Where-Object {{ $_ -in @('write:pgctl_restored', 'resolve', 'readback', 'remove') }})
        if ($afterRestore.Count -ne 0) {{
            throw "double failure advanced authority: $($script:events -join '|')"
        }}
    }}
}}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-bootstrap-retirement-failures.ps1",
    )


def test_single_user_service_adapter_is_exact_and_policy_closed(tmp_path: Path) -> None:
    service_contract = PACKAGING / "windows_service_contract.ps1"
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{service_contract}'
. '{POSTGRESQL_SINGLE_USER}'
$script:currentImagePath = ''
$script:startMode = 'Manual'
$script:failureResetSeconds = 0
$script:failureActions = ''
$script:observedStartModeOverride = $null
$script:observedFailureOverride = $null
$script:events = [Collections.Generic.List[string]]::new()
function Assert-TicketboxServiceDependencies {{}}
function Get-TestFailureObservation {{
    if ($null -ne $script:observedFailureOverride) {{
        return $script:observedFailureOverride
    }}
    return [pscustomobject]@{{
        ResetSeconds = $script:failureResetSeconds
        Actions = $script:failureActions
    }}
}}
function Assert-TicketboxServiceHasNoFailureActions {{
    $observed = Get-TestFailureObservation
    if ($observed.ResetSeconds -ne 0 -or $observed.Actions -cne '') {{
        throw 'failure actions drifted'
    }}
}}
function Assert-TicketboxServiceStartMode {{
    param([string]$Name, [string]$ExpectedStartMode)
    $observed = if ($null -ne $script:observedStartModeOverride) {{
        [string]$script:observedStartModeOverride
    }} else {{
        [string]$script:startMode
    }}
    if ($observed -cne $ExpectedStartMode) {{ throw 'start mode drifted' }}
}}
function Assert-TicketboxServiceFailurePolicy {{
    param(
        [string]$Name,
        [int]$ExpectedResetSeconds,
        [int[]]$ExpectedRestartDelaysMs
    )
    $observed = Get-TestFailureObservation
    $expectedActions = @(
        $ExpectedRestartDelaysMs | ForEach-Object {{ "restart/$([int]$_)" }}
    ) -join '/'
    if (
        $observed.ResetSeconds -ne $ExpectedResetSeconds -or
        $observed.Actions -cne $expectedActions
    ) {{ throw 'failure policy drifted' }}
}}
function Get-TicketboxServiceImagePath {{ return $script:currentImagePath }}
function Get-TicketboxServiceImagePathExact {{ return $script:currentImagePath }}
function Invoke-TicketboxScChecked {{
    param([string[]]$Arguments)
    $script:events.Add("sc:$($Arguments[0])")
    if ($Arguments[0] -ceq 'failure') {{
        if (
            $Arguments.Count -eq 6 -and
            $Arguments[2] -ceq 'reset=' -and
            $Arguments[4] -ceq 'actions='
        ) {{
            $script:failureResetSeconds = [int]$Arguments[3]
            $script:failureActions = [string]$Arguments[5]
        }} else {{
            $script:failureResetSeconds = -1
            $script:failureActions = '<invalid>'
        }}
    }}
    if ($Arguments[0] -ceq 'config') {{
        $valid = (
            $Arguments.Count -eq 6 -and
            $Arguments[2] -ceq 'binPath=' -and
            $Arguments[4] -ceq 'start=' -and $Arguments[5] -ceq 'demand'
        )
        $script:currentImagePath = if ($valid) {{ [string]$Arguments[3] }} else {{ '<invalid>' }}
        $script:startMode = if ($valid) {{ 'Manual' }} else {{ '<invalid>' }}
    }}
    return @{{}}
}}
function Set-TicketboxServiceIdentityContract {{ $script:events.Add('identity') }}
function Assert-TicketboxPgServiceCommand {{ $script:events.Add('pg-contract') }}
function Stop-TicketboxOwnedServiceIfExists {{ $script:events.Add('stop') }}
function Get-TicketboxServiceRuntimeSnapshot {{
    return [pscustomobject]@{{ State = 'stopped'; ProcessId = [uint32]0 }}
}}
function Test-TicketboxPathEquals {{
    param($Left, $Right)
    return [IO.Path]::GetFullPath([string]$Left) -ieq [IO.Path]::GetFullPath([string]$Right)
}}
$parameters = @{{
    ShawlPath = 'C:\Ticketbox\shawl\shawl.exe'
    ServiceName = 'TicketboxPg'
    WorkingDirectory = 'C:\Ticketbox\installer'
    PowerShellPath = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    HelperPath = 'C:\Ticketbox\installer\windows_database_generation_single_user.ps1'
    PostgresPath = 'C:\Ticketbox\pgsql\bin\postgres.exe'
    PhysicalPgData = 'D:\Ticketbox\pgdata'
    OperationId = '11111111-1111-4111-8111-111111111111'
    IntentSha256 = ('a' * 64)
    CandidateSha256 = ('c' * 64)
    CommittedRevision = '20260809_0001'
    StopTimeoutMilliseconds = 30000
    OperationTimeoutMilliseconds = 60000
}}
$image = New-TicketboxPostgresqlSingleUserServiceImagePath @parameters
$script:currentImagePath = $image
Assert-TicketboxPostgresqlSingleUserServiceCommand 'TicketboxPg' $image
$parts = @(Split-TicketboxWindowsCommandLine $image)
foreach ($index in @(1,2,4,5,6,7,9,11,13,14,15,16,17,18,20,22,24,26,28,30,32)) {{
    $poisoned = @($parts)
    $poisoned[$index] = 'poison'
    $script:currentImagePath = Join-TicketboxWindowsCommandLine $poisoned
    $rejected = $false
    try {{ Assert-TicketboxPostgresqlSingleUserServiceCommand 'TicketboxPg' $script:currentImagePath }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "single-user token $index was not closed" }}
}}
$script:currentImagePath = $image + ' '
$rejected = $false
try {{ Assert-TicketboxPostgresqlSingleUserServiceCommand 'TicketboxPg' $image }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'full ImagePath drift was accepted' }}
$script:currentImagePath = $image
$script:startMode = 'Automatic'
$rejected = $false
try {{ Assert-TicketboxPostgresqlSingleUserServiceCommand 'TicketboxPg' $image }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'single-user start mode drift was accepted' }}
$script:startMode = 'Manual'
$hostContract = [pscustomobject]@{{
    pg_service_name = 'TicketboxPg'
    pg_ctl_path = 'C:\Ticketbox\pgsql\bin\pg_ctl.exe'
    release_config = [pscustomobject]@{{
        service_state_timeout_ms = 30000
        service_poll_interval_ms = 100
        service_logon_account = 'NT SERVICE\TicketboxPg'
        service_sid_type = 'restricted'
        scm_failure_reset_seconds = 86400
        scm_restart_delays_ms = @(1000, 5000)
    }}
}}
$hostAuthority = [pscustomobject]@{{
    ServiceName = 'TicketboxPg'
    PgCtlPath = 'C:\Ticketbox\pgsql\bin\pg_ctl.exe'
    PgData = 'C:\TicketboxRuntime\pgdata'
    PhysicalPgData = 'D:\Ticketbox\pgdata'
    Port = 5432
}}
$formal = '"C:\Ticketbox\pgsql\bin\pg_ctl.exe" runservice -N TicketboxPg'
$script:currentImagePath = $formal
$script:failureResetSeconds = 86400
$script:failureActions = 'restart/1000/restart/5000'
$stopped = Enter-TicketboxPostgresqlStoppedHostAuthority $hostAuthority $hostContract $formal
$script:currentImagePath = $image
$script:failureResetSeconds = 86400
$script:failureActions = 'restart/1000/restart/5000'
$rejected = $false
try {{ Assert-TicketboxPostgresqlSingleUserServiceCommand 'TicketboxPg' $image }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'single-user failure actions drift was accepted' }}
$script:observedFailureOverride = [pscustomobject]@{{
    ResetSeconds = 86400
    Actions = 'restart/1000/restart/5000'
}}
$rejected = $false
try {{ Set-TicketboxPostgresqlSingleUserServiceCommand $stopped $hostContract $image }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'single-user failure-policy readback drift was accepted' }}
$script:observedFailureOverride = $null
$script:observedStartModeOverride = 'Automatic'
$rejected = $false
try {{ Set-TicketboxPostgresqlSingleUserServiceCommand $stopped $hostContract $image }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'single-user start-mode readback drift was accepted' }}
$script:observedStartModeOverride = $null
Set-TicketboxPostgresqlSingleUserServiceCommand $stopped $hostContract $image
if (
    $script:currentImagePath -cne $image -or
    $script:failureResetSeconds -ne 0 -or $script:failureActions -cne '' -or
    $script:startMode -cne 'Manual'
) {{
    throw 'single-user command or failure policy was not installed exactly'
}}
$script:observedFailureOverride = [pscustomobject]@{{ ResetSeconds = 0; Actions = '' }}
$rejected = $false
try {{ Restore-TicketboxPostgresqlFormalServiceCommand $stopped $hostContract }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'formal failure-policy readback drift was accepted' }}
$script:observedFailureOverride = $null
$script:observedStartModeOverride = 'Automatic'
$rejected = $false
try {{ Restore-TicketboxPostgresqlFormalServiceCommand $stopped $hostContract }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'formal start-mode readback drift was accepted' }}
$script:observedStartModeOverride = $null
Restore-TicketboxPostgresqlFormalServiceCommand $stopped $hostContract
if (
    $script:currentImagePath -cne $formal -or
    $script:startMode -cne 'Manual' -or
    $script:failureResetSeconds -ne 86400 -or
    $script:failureActions -cne 'restart/1000/restart/5000'
) {{ throw 'formal command or service policy was not restored exactly' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="postgresql-single-user-service-adapter.ps1",
    )
