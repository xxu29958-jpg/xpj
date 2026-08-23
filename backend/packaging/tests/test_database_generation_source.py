import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines, run_powershell_contract_script

PACKAGING = Path(__file__).resolve().parents[1]
SOURCE = PACKAGING / "windows_database_generation_source.ps1"
SOURCE_BINDING = PACKAGING / "windows_database_generation_source_binding.ps1"
EVIDENCE_VERIFIER = PACKAGING / "windows_database_generation_evidence_verifier.ps1"
ROLE_BOOTSTRAP = PACKAGING / "windows_database_generation_role_bootstrap.ps1"
CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
POLICY = PACKAGING / "windows_database_generation_policy.ps1"


def _function(source: str, name: str) -> str:
    match = re.search(rf"(?m)^function {re.escape(name)}\s*\{{", source)
    assert match is not None, name
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unterminated PowerShell function: {name}")


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_source_binding_boundary_rejects_mode_request_mismatch(tmp_path: Path) -> None:
    validator = _function(
        EVIDENCE_VERIFIER.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationSourceBinding",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) {{ throw 'open contract' }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw 'bad digest' }}
}}
{validator}
$operation = '11111111-1111-4111-8111-111111111111'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $operation
        target_revision = '20260821_0001'
        source_request_sha256 = ''
    }}
}}
$binding = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-database-generation-source-binding-v1'
        operation_id = $operation
        intent_sha256 = ('a' * 64)
        source_evidence_sha256 = ('c' * 64)
        source_kind = 'empty'
        source_revision = 'base'
        cluster_system_identifier = '7612345678901234567'
        database_oid = 16384
        writer_fence_sha256 = ('d' * 64)
    }}
}}
[void](Assert-TicketboxDatabaseGenerationSourceBinding $binding $intent)
$binding.Payload.source_kind = 'current_generation'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationSourceBinding $binding $intent | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'mode/request mismatch crossed SourceBinding' }}
$binding.Payload.source_kind = 'empty'
$intent.Payload.source_request_sha256 = ('e' * 64)
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationSourceBinding $binding $intent | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'empty source accepted a restore request' }}
$binding.Payload.source_kind = 'current_generation'
$binding.Payload.source_revision = '20260821_0001'
[void](Assert-TicketboxDatabaseGenerationSourceBinding $binding $intent)
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-source-binding.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_source_binding_chain_rejects_missing_or_corrupt_backing_evidence(
    tmp_path: Path,
) -> None:
    source = EVIDENCE_VERIFIER.read_text(encoding="utf-8-sig")
    validator = _function(
        source,
        "Assert-TicketboxDatabaseGenerationSourceBinding",
    )
    chain = _function(
        source,
        "Assert-TicketboxDatabaseGenerationSourceBindingChain",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) {{ throw 'open contract' }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw 'bad digest' }}
}}
function Read-TicketboxDatabaseGenerationOperationArtifact {{
    param($StateRoot, $OperationId, $ArtifactKind)
    if ([string]$StateRoot -cne 'state' -or [string]$OperationId -cne $operation) {{
        throw 'wrong evidence lookup authority'
    }}
    if ($null -eq $script:evidence) {{ throw 'backing evidence missing' }}
    if ([string]$ArtifactKind -cne [string]$script:expectedEvidenceKind) {{ throw 'wrong evidence type' }}
    return $script:evidence
}}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{ DatabaseName = 'ticketbox' }}
}}
{validator}
{chain}
$operation = '11111111-1111-4111-8111-111111111111'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = $operation
        target_revision = '20260821_0001'
        source_request_sha256 = ('b' * 64)
        expected_predecessor_sha256 = ('c' * 64)
    }}
}}
$binding = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-database-generation-source-binding-v1'
        operation_id = $operation
        intent_sha256 = ('a' * 64)
        source_evidence_sha256 = ('e' * 64)
        source_kind = 'current_generation'
        source_revision = '20260821_0001'
        cluster_system_identifier = '7612345678901234567'
        database_oid = [uint32]16384
        writer_fence_sha256 = ('f' * 64)
    }}
}}
$script:expectedEvidenceKind = 'restored-source'
$script:evidence = [pscustomobject]@{{
    PayloadSha256 = ('e' * 64)
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-database-generation-restored-source-v1'
        operation_id = $operation
        intent_sha256 = ('a' * 64)
        source_request_sha256 = ('b' * 64)
        predecessor_current_sha256 = ('c' * 64)
        backup_manifest_sha256 = ('1' * 64)
        backup_id = '22222222-2222-4222-8222-222222222222'
        dataset_id = '33333333-3333-4333-8333-333333333333'
        restore_epoch = [int64]4
        source_revision = '20260821_0001'
        cluster_system_identifier = '7612345678901234567'
        database_oid = [uint32]16384
        writer_fence_sha256 = ('f' * 64)
        result = 'isolated_restore_candidate_ready'
    }}
}}
[void](Assert-TicketboxDatabaseGenerationSourceBindingChain 'state' $binding $intent)
$restoredEvidence = $script:evidence
$script:evidence = $null
$missingRejected = $false
try {{ Assert-TicketboxDatabaseGenerationSourceBindingChain 'state' $binding $intent | Out-Null }} catch {{ $missingRejected = $true }}
if (-not $missingRejected) {{ throw 'missing backing evidence was accepted' }}
$script:evidence = $restoredEvidence
$script:evidence.Payload.result = 'foreign-result'
$corruptRejected = $false
try {{ Assert-TicketboxDatabaseGenerationSourceBindingChain 'state' $binding $intent | Out-Null }} catch {{
    $corruptRejected = ([string]$_ -like '*restored evidence drifted*')
}}
if (-not $corruptRejected) {{ throw 'corrupt backing evidence was accepted' }}
$intent.Payload.source_request_sha256 = ''
$binding.Payload.source_evidence_sha256 = ('8' * 64)
$binding.Payload.source_kind = 'empty'
$binding.Payload.source_revision = 'base'
$script:expectedEvidenceKind = 'source-create-attempt'
$script:evidence = [pscustomobject]@{{
    PayloadSha256 = ('8' * 64)
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-database-generation-source-create-attempt-v1'
        operation_id = $operation
        intent_sha256 = ('a' * 64)
        cluster_system_identifier = '7612345678901234567'
        database_name = 'ticketbox'
        temporary_database = 'ticketbox_generation_11111111111141118111111111111111'
        observed_target_absent = $true
    }}
}}
[void](Assert-TicketboxDatabaseGenerationSourceBindingChain 'state' $binding $intent)
$script:evidence.Payload.temporary_database = 'ticketbox_generation_foreign'
$emptyCorruptRejected = $false
try {{ Assert-TicketboxDatabaseGenerationSourceBindingChain 'state' $binding $intent | Out-Null }} catch {{ $emptyCorruptRejected = $true }}
if (-not $emptyCorruptRejected) {{ throw 'corrupt empty-source evidence was accepted' }}
"""
    run_powershell_contract_script(
        script,
        tmp_path,
        filename="database-generation-source-binding-chain.ps1",
    )


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_preinstall_eligibility_is_read_only_and_fails_closed(tmp_path: Path) -> None:
    eligibility = _function(
        POLICY.read_text(encoding="utf-8-sig"),
        "Assert-TicketboxDatabaseGenerationPreinstallEligibility",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:active = $null
$script:current = $null
$script:services = @{{}}
$script:pathKinds = @{{}}
$script:writes = 0
function Assert-TicketboxLifecycleOperationLease {{ param($Lock) }}
function Read-TicketboxDatabaseGenerationActiveIntent {{ param($Root, [switch]$AllowAbsent); return $script:active }}
function Read-TicketboxDatabaseGenerationCurrent {{ param([switch]$AllowAbsent); return $script:current }}
function Test-TicketboxServiceExists {{ param($Name); return [bool]$script:services[$Name] }}
function Get-TicketboxPathEntryKindNoFollow {{
    param($Path)
    if ($script:pathKinds.ContainsKey([string]$Path)) {{ return $script:pathKinds[[string]$Path] }}
    return 'Missing'
}}
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param($Value, $ExpectedNames, $Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive)
    $expected = @($ExpectedNames | Sort-Object -CaseSensitive)
    if (($actual -join "`n") -cne ($expected -join "`n")) {{ throw 'open path fact' }}
}}
function New-TicketboxDatabaseGenerationIntent {{ $script:writes += 1 }}
function Start-Service {{ $script:writes += 1 }}
function Remove-Item {{ $script:writes += 1 }}
{eligibility}
if (-not (Get-Command Assert-TicketboxDatabaseGenerationPreinstallEligibility).Parameters.ContainsKey('LifecycleEvidence')) {{
    throw 'preinstall eligibility lacks closed lifecycle authority'
}}
$lock = [pscustomobject]@{{ Identity = 'held' }}
$facts = @([pscustomobject][ordered]@{{ Path = 'pgdata\\PG_VERSION'; Label = 'PG_VERSION' }})
$lifecycle = [pscustomobject][ordered]@{{
    schema = 'ticketbox-database-generation-lifecycle-evidence-v2'
    receipt_present = $false
    phase = 'absent'
    operation_id = ''
    current_sha256 = ''
}}

Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $false $lifecycle $facts
if ($script:writes -ne 0) {{ throw 'empty classification mutated state' }}

$script:services['pg'] = $true
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $false $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'existing service crossed eligibility gate' }}
$script:services.Clear()

$script:pathKinds['pgdata\\PG_VERSION'] = 'File'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $false $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'existing PGDATA crossed eligibility gate' }}
$script:pathKinds.Clear()

$operation = '11111111-1111-4111-8111-111111111111'
$script:active = [pscustomobject]@{{ PayloadSha256 = ('a' * 64); Payload = [pscustomobject]@{{ operation_id = $operation }} }}
$script:current = [pscustomobject]@{{ PayloadSha256 = ('b' * 64); Payload = [pscustomobject]@{{ operation_id = $operation; intent_sha256 = ('a' * 64) }} }}
$lifecycle.receipt_present = $true
$lifecycle.phase = 'active_precommit'
$lifecycle.operation_id = $operation
Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts
if ($script:writes -ne 0) {{ throw 'exact retry mutated state' }}

$lifecycle.current_sha256 = ('b' * 64)
$beforeRetry = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts
$afterRetry = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
if ($beforeRetry -cne $afterRetry -or $script:writes -ne 0) {{ throw 'exact bound retry mutated authority' }}

$savedCurrent = $script:current
$script:current = $null
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'receipt-bound missing CURRENT crossed eligibility gate' }}
$script:current = $savedCurrent

$lifecycle.operation_id = '33333333-3333-4333-8333-333333333333'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign lifecycle receipt crossed eligibility gate' }}
$lifecycle.operation_id = $operation

$lifecycle.current_sha256 = ('c' * 64)
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign lifecycle CURRENT crossed eligibility gate' }}
$lifecycle.current_sha256 = ('b' * 64)

$beforeCommitted = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
$lifecycle.phase = 'install_cleanup_pending'
$pendingAction = Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts
$lifecycle.phase = 'install_completed'
$completedAction = Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts
$afterCommitted = ConvertTo-Json @($script:active, $script:current) -Compress -Depth 8
if (
    $pendingAction -cne 'resume_install_cleanup' -or
    $completedAction -cne 'acknowledge_completed_install' -or
    $beforeCommitted -cne $afterCommitted -or
    $script:writes -ne 0
) {{ throw 'committed install was not classified without mutation' }}

$lifecycle.phase = 'active_precommit'
$script:current.Payload.operation_id = '22222222-2222-4222-8222-222222222222'
$rejected = $false
try {{ Assert-TicketboxDatabaseGenerationPreinstallEligibility 'state' $lock 'pg' 'backend' $true $lifecycle $facts }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign CURRENT crossed eligibility gate' }}
"""
    path = tmp_path / "database-generation-preinstall-eligibility.ps1"
    path.write_text(script, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_empty_source_classification_is_zero_write_and_operation_bound(
    tmp_path: Path,
) -> None:
    source_text = SOURCE.read_text(encoding="utf-8-sig")
    normalize = _function(
        source_text,
        "Invoke-TicketboxDatabaseGenerationEmptySource",
    )
    role_sql = _function(
        ROLE_BOOTSTRAP.read_text(encoding="utf-8-sig"),
        "New-TicketboxDatabaseGenerationEmptyRoleSql",
    )
    sql_literal = _function(
        (PACKAGING / "windows_postgresql_database_command.ps1").read_text(
            encoding="utf-8-sig"
        ),
        "ConvertTo-TicketboxPostgresqlSqlLiteral",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
$script:writes = 0
$script:nonempty = $false
$script:attempt = $null
$script:target = $null
function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {{ param($Authority, $Intent, $HostAuthority, $Lock); return $Authority }}
function Read-TicketboxDatabaseGenerationOperationArtifact {{ param($Root, $Operation, $Kind, [switch]$AllowAbsent); return $script:attempt }}
function New-TicketboxDatabaseGenerationChainedArtifact {{ $script:writes += 1; return $script:attempt }}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        OwnerRole = 'ticketbox_owner'
        MigratorRole = 'ticketbox_migrator'
        RuntimeRole = 'ticketbox_runtime'
        BackupRole = 'ticketbox_backup'
        RetiredLegacyRole = 'ticketbox'
    }}
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{
    param($Authority, $SuperuserPassword, $TargetDatabase)
    if ($TargetDatabase -ceq 'ticketbox') {{ return $script:target }}
    return [pscustomobject]@{{
        Exists = $false; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]0
        OwnerRoleOid = [uint32]0; Comment = ''; AllowsConnections = $false
    }}
}}
function Get-TicketboxDatabaseRoleOid {{
    param($Authority, $SuperuserPassword, $RoleName)
    return [uint32]77
}}
function Assert-TicketboxDatabaseGenerationEmptySchema {{ if ($script:nonempty) {{ throw 'nonempty' }} }}
{sql_literal}
{role_sql}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param($Authority, $Database, $Role, $Password, [string]$Label, [string]$Sql)
    $script:writes += 1
    if ($Label -ceq 'database generation empty-source ACL attestation') {{
        if ($Sql -cne 'DO ticketbox empty ACL guard;') {{ throw 'empty ACL guard drifted' }}
        $script:emptyAclAttested = $true
    }}
}}
function New-TicketboxDatabaseRuntimeAclSql {{ return 'SELECT 1;' }}
function New-TicketboxDatabaseForeignAclGuardSql {{ return 'DO ticketbox empty ACL guard;' }}
function Assert-TicketboxDatabaseCredential {{}}
function Assert-TicketboxDatabaseRolePolicy {{}}
function Assert-TicketboxDatabaseRuntimeAcl {{ throw 'full table ACL asserted before migration' }}
function Get-TicketboxDatabaseGenerationFrozenFence {{ return [ordered]@{{ state = 'frozen' }} }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ param($Value); return ($Value | ConvertTo-Json -Compress) }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('f' * 64) }}
{normalize}
$operation = '11111111-1111-4111-8111-111111111111'
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{ operation_id = $operation }}
}}
$migratorSecret = New-Object Security.SecureString
$migratorSecret.AppendChar('m')
$superuserSecret = New-Object Security.SecureString
$superuserSecret.AppendChar('s')
$credentials = [pscustomobject]@{{
    RuntimeVerifier = 'SCRAM-SHA-256$4096:x'; MigratorVerifier = 'SCRAM-SHA-256$4096:y'
    BackupVerifier = 'SCRAM-SHA-256$4096:z'
    MigratorPassword = $migratorSecret
}}
$maintenanceAuthority = [pscustomobject]@{{ Secret = $superuserSecret }}
$roleBootstrapSql = New-TicketboxDatabaseGenerationEmptyRoleSql `
    -OperationId $operation `
    -RuntimeVerifier $credentials.RuntimeVerifier `
    -MigratorVerifier $credentials.MigratorVerifier `
    -BackupVerifier $credentials.BackupVerifier `
    -MigratorValidUntilUtc ([DateTime]'2030-01-02T03:04:05Z')
if (
    $roleBootstrapSql -notlike "*PASSWORD 'SCRAM-SHA-256`$4096:x';*" -or
    $roleBootstrapSql -notlike "*PASSWORD 'SCRAM-SHA-256`$4096:y' VALID UNTIL '2030-01-02T03:04:05.000Z';*" -or
    $roleBootstrapSql -notlike "*PASSWORD 'SCRAM-SHA-256`$4096:z';*" -or
    $roleBootstrapSql -like "*PASSWORD ''SCRAM-SHA-256*" -or
    $roleBootstrapSql -like "*IS DISTINCT FROM ''SCRAM-SHA-256*" -or
    $roleBootstrapSql -like "*''11111111-1111-4111-8111-111111111111''*"
) {{ throw 'empty-source SQL literal ownership drifted' }}
$attemptFixture = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject]@{{
        intent_sha256 = ('a' * 64); cluster_system_identifier = 'cluster-1'
        database_name = 'ticketbox'
        temporary_database = 'ticketbox_generation_11111111111141118111111111111111'
        observed_target_absent = $true
    }}
}}
$exactMarker = "ticketbox-database-generation-empty-source-v1|$operation|cluster-1|42"

# A pre-existing target cannot create an attempt or mutate roles/ACL.
$script:attempt = $null
$script:target = [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]42; OwnerRoleOid = [uint32]77; Comment = ''; AllowsConnections = $true }}
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationEmptySource 'state' $intent $credentials @{{}} $maintenanceAuthority @{{}} | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'pre-existing target reached mutation' }}

# Even an operation marker cannot authorize a non-empty target.
$script:attempt = $attemptFixture
$script:target.Comment = $exactMarker
$script:nonempty = $true
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationEmptySource 'state' $intent $credentials @{{}} $maintenanceAuthority @{{}} | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'non-empty exact marker reached mutation' }}

# The exact persisted attempt + marker + empty schema is the only retry lane.
$script:nonempty = $false
$script:emptyAclAttested = $false
$result = Invoke-TicketboxDatabaseGenerationEmptySource 'state' $intent $credentials @{{}} $maintenanceAuthority @{{}}
if (
    $script:writes -ne 4 -or
    -not $script:emptyAclAttested -or
    [string]$result.source_evidence_sha256 -cne ('d' * 64) -or
    [string]$result.source_kind -cne 'empty' -or
    [string]$result.database_oid -cne '42'
) {{ throw 'exact operation-bound retry did not converge' }}
"""
    path = tmp_path / "database-generation-source.ps1"
    path.write_text(script, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_restored_source_normalizes_exact_evidence_and_rejects_drift(tmp_path: Path) -> None:
    source_text = SOURCE_BINDING.read_text(encoding="utf-8-sig")
    normalize = _function(
        source_text,
        "Invoke-TicketboxDatabaseGenerationRestoredSource",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{ param($Value, $ExpectedNames, $Label) }}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param($Value, $Label)
    if ([string]$Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label invalid" }}
}}
function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {{
    param($Authority, $Intent, $HostAuthority, $Lock)
    return $Authority
}}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{ DatabaseName = 'ticketbox' }}
}}
$script:live = [pscustomobject]@{{
    Exists = $true; ClusterSystemIdentifier = 'cluster-2'; DatabaseOid = [uint32]84
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{ return $script:live }}
function Get-TicketboxDatabaseGenerationLiveIdentity {{
    return [pscustomobject]@{{
        ClusterSystemIdentifier = $script:live.ClusterSystemIdentifier
        DatabaseOid = $script:live.DatabaseOid
        DatasetId = '33333333-3333-4333-8333-333333333333'
        RestoreEpoch = [int64]2
        SchemaRevision = '20260821_0001'
    }}
}}
function Get-TicketboxDatabaseGenerationFrozenFence {{ return [ordered]@{{ state = 'frozen' }} }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param($Value)
    return ($Value | ConvertTo-Json -Depth 8 -Compress)
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{ param($Text); return ('e' * 64) }}
{normalize}
$intent = [pscustomobject]@{{
    PayloadSha256 = ('a' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        expected_predecessor_sha256 = ('b' * 64)
        source_request_sha256 = ('c' * 64)
        target_revision = '20260821_0001'
    }}
}}
$evidence = [pscustomobject]@{{
    PayloadSha256 = ('d' * 64)
    Payload = [pscustomobject][ordered]@{{
        schema = 'ticketbox-database-generation-restored-source-v1'
        operation_id = $intent.Payload.operation_id
        intent_sha256 = $intent.PayloadSha256
        source_request_sha256 = $intent.Payload.source_request_sha256
        predecessor_current_sha256 = $intent.Payload.expected_predecessor_sha256
        backup_manifest_sha256 = ('f' * 64)
        backup_id = '22222222-2222-4222-8222-222222222222'
        dataset_id = '33333333-3333-4333-8333-333333333333'
        restore_epoch = [int64]2
        source_revision = $intent.Payload.target_revision
        cluster_system_identifier = 'cluster-2'
        database_oid = [uint32]84
        writer_fence_sha256 = ('e' * 64)
        result = 'isolated_restore_candidate_ready'
    }}
}}
$maintenance = [pscustomobject]@{{ Secret = (New-Object Security.SecureString) }}
$result = Invoke-TicketboxDatabaseGenerationRestoredSource `
    $intent $evidence @{{}} $maintenance @{{}}
if (
    [string]$result.source_kind -cne 'current_generation' -or
    [string]$result.source_evidence_sha256 -cne ('d' * 64) -or
    [string]$result.source_revision -cne '20260821_0001' -or
    [string]$result.cluster_system_identifier -cne 'cluster-2' -or
    [uint32]$result.database_oid -ne 84
) {{ throw 'restored source did not normalize exact evidence' }}
$rejected = 0
foreach ($mutation in @('predecessor', 'request', 'dataset', 'epoch', 'cluster', 'fence')) {{
    $copy = $evidence | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    switch ($mutation) {{
        'predecessor' {{ $copy.Payload.predecessor_current_sha256 = ('9' * 64) }}
        'request' {{ $copy.Payload.source_request_sha256 = ('9' * 64) }}
        'dataset' {{ $copy.Payload.dataset_id = '44444444-4444-4444-8444-444444444444' }}
        'epoch' {{ $copy.Payload.restore_epoch = [int64]3 }}
        'cluster' {{ $copy.Payload.cluster_system_identifier = 'other-cluster' }}
        'fence' {{ $copy.Payload.writer_fence_sha256 = ('9' * 64) }}
    }}
    try {{ Invoke-TicketboxDatabaseGenerationRestoredSource $intent $copy @{{}} $maintenance @{{}} | Out-Null }}
    catch {{ $rejected += 1 }}
}}
if ($rejected -ne 6) {{ throw 'restored source accepted drift' }}
"""
    path = tmp_path / "database-generation-restored-source.ps1"
    path.write_text(script, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
