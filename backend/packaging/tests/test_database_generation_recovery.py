import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
RECOVERY_EVIDENCE = PACKAGING / "windows_database_generation_recovery_evidence.ps1"
TARGET_RECOVERY = PACKAGING / "windows_database_generation_target_recovery.ps1"
LAUNCH = PACKAGING / "launch.py"


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


def _run_both(script: str, tmp_path: Path) -> None:
    path = tmp_path / "database-generation-recovery.ps1"
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


def _load_launch_module():
    spec = importlib.util.spec_from_file_location(
        "ticketbox_database_generation_recovery_test_launch",
        LAUNCH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


@pytest.mark.skipif(not powershell_contract_engines(), reason="PowerShell required")
def test_target_recovery_owns_only_exact_random_restore_database(tmp_path: Path) -> None:
    recovery = "\n".join(
        (
            RECOVERY_EVIDENCE.read_text(encoding="utf-8-sig"),
            TARGET_RECOVERY.read_text(encoding="utf-8-sig"),
        )
    )
    marker = _function(recovery, "Get-TicketboxDatabaseGenerationRestoreMarker")
    archive_paths = _function(
        recovery,
        "Get-TicketboxDatabaseGenerationRecoveryArchivePaths",
    )
    archive_writer = _function(
        recovery,
        "Get-TicketboxDatabaseGenerationRecoveryArchive",
    )
    binding = _function(recovery, "Get-TicketboxDatabaseGenerationRestoreBinding")
    restore = _function(recovery, "Invoke-TicketboxDatabaseGenerationArchiveRestore")
    cleanup = _function(recovery, "Remove-TicketboxDatabaseGenerationRestoreDatabase")
    target_recovery = _function(
        recovery,
        "Invoke-TicketboxDatabaseGenerationTargetRecovery",
    )
    script = f"""
$ErrorActionPreference = 'Stop'
{marker}
{archive_paths}
{archive_writer}
{binding}
{restore}
{cleanup}
{target_recovery}
$script:writes = 0
$script:TicketboxDatabaseGenerationRecoveryTimeoutMs = 1200000
$script:restoreCalls = 0
$script:publicOwnerRepairs = 0
$script:publicOwner = 'pg_database_owner'
$script:restoreRevision = ''
$script:catalog = $null
$script:artifacts = @{{}}
$script:events = @()
function Read-TicketboxDatabaseGenerationOperationArtifact {{ param($StateRoot, $OperationId, $Kind, [switch]$AllowAbsent); return $script:artifacts[$Kind] }}
function Get-TicketboxDatabaseAuthorizationContract {{
    return [pscustomobject]@{{
        DatabaseName = 'ticketbox'
        OwnerRole = 'ticketbox_owner'
        MigratorRole = 'ticketbox_migrator'
    }}
}}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{ return $script:catalog }}
function Get-TicketboxDatabaseRoleOid {{
    param($Authority, $SuperuserPassword, $RoleName)
    return [uint32]77
}}
function ConvertTo-TicketboxPostgresqlSqlLiteral {{ param($Value); return "'$Value'" }}
function Assert-TicketboxLifecycleOperationLease {{ param($LifecycleLock) }}
function Get-TicketboxDatabaseGenerationRestoreRevision {{ return $script:restoreRevision }}
function Assert-TicketboxDatabaseGenerationRecoveryChain {{ return $true }}
function Assert-TicketboxDatabaseGenerationRecoveryArchive {{
    param($StateRoot, $Archive)
    return 'archive.dump'
}}
function Assert-TicketboxDatabaseGenerationToolIdentity {{
    param($Path, $ExpectedPath, $ExpectedSize, $ExpectedSha256, $Label)
    return $Path
}}
function Get-TicketboxPortableFileSha256 {{ return ('e' * 64) }}
function Get-TicketboxPathEntryKindNoFollow {{ param($Path); if ([IO.File]::Exists($Path)) {{ return 'File' }}; if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}; return 'Missing' }}
function New-TicketboxPostgresqlLocalDatabaseUrl {{ param($Authority, $Database, $Role); return "postgresql://postgres@127.0.0.1:5432/$Database`?require_auth=scram-sha-256" }}
function Invoke-TicketboxWithPlainPostgresqlSecret {{ param($Secret, $Action); return & $Action 'secret' }}
function Invoke-TicketboxWithPgPassFile {{ param($DatabaseUrl, $Password, $Action); return & $Action $DatabaseUrl }}
function Remove-TicketboxDatabaseGenerationRecoveryFile {{ param($StateRoot, $Path, $LifecycleLock); $script:events += "remove:$([IO.Path]::GetFileName($Path))"; if ([IO.File]::Exists($Path)) {{ [IO.File]::Delete($Path) }} }}
function Invoke-TicketboxPgDumpCustom {{ param($PgDumpPath, $DatabaseUrl, $OutputPath, $Password, $TimeoutMilliseconds); $script:events += 'dump'; $script:dumpPath = $PgDumpPath; $script:dumpUrl = $DatabaseUrl; [IO.File]::WriteAllText($OutputPath, 'archive'); return $script:dumpExit }}
function Sync-TicketboxFileDurable {{ param($Path); $script:events += 'sync' }}
function Copy-TicketboxVerifiedArtifact {{ param($SourcePath, $DestinationPath, $ExpectedSourceSha256, $ExpectedLength, $FullControlAccounts, $OwnerAccount); $script:events += 'copy'; [IO.File]::Copy($SourcePath, $DestinationPath); return $DestinationPath }}
function Invoke-TicketboxPgRestoreList {{ param($PgRestorePath, $ArchivePath, $TimeoutMilliseconds); $script:events += 'restore-list'; return 0 }}
function Invoke-TicketboxBoundedNativeProcess {{
    param($FilePath, $Arguments, $TimeoutMilliseconds, $Label)
    $script:restoreCalls += 1
    $script:restoreArguments = @($Arguments)
    return [pscustomobject]@{{ ExitCode = 0 }}
}}
function New-TicketboxDatabaseGenerationRecoveryArtifact {{
    param($StateRoot, $OperationId, $Kind, $Payload, $LifecycleLock)
    $artifact = [pscustomobject]@{{ Payload = [pscustomobject]$Payload; PayloadSha256 = ('a' * 64) }}
    $script:artifacts[$Kind] = $artifact
    $script:events += "artifact:$Kind"
    return $artifact
}}
function Invoke-TicketboxPostgresqlDatabaseCommand {{
    param($Authority, $Database, $Role, $Password, $Label, $Sql)
    if ($Label -ceq 'database generation restore public schema owner observation') {{
        return $script:publicOwner
    }}
    $script:writes += 1
    if ($Label -ceq 'database generation restore database create') {{
        $script:catalog = [pscustomobject]@{{
            Exists = $true
            ClusterSystemIdentifier = 'cluster-1'
            DatabaseOid = [uint32]222
            OwnerRoleOid = [uint32]77
            Comment = ''
            AllowsConnections = $false
        }}
    }} elseif ($Label -ceq 'database generation restore database bind') {{
        $script:catalog.Comment = Get-TicketboxDatabaseGenerationRestoreMarker $script:attempt $script:catalog.DatabaseOid
        $script:catalog.AllowsConnections = $true
    }} elseif ($Label -ceq 'database generation restore public schema ownership') {{
        if (
            [string]$Database -cne [string]$script:attempt.Payload.restore_database -or
            [string]$Role -cne 'postgres' -or
            [string]$Sql -cne 'ALTER SCHEMA public OWNER TO "ticketbox_owner";'
        ) {{ throw 'restore public schema ownership repair is not exact' }}
        $script:publicOwnerRepairs += 1
        $script:publicOwner = 'ticketbox_owner'
    }} elseif ($Label -ceq 'database generation restore exact cleanup') {{
        $script:catalog.Exists = $false
    }} else {{
        throw "unexpected SQL label: $Label"
    }}
}}
$secret = New-Object Security.SecureString
$secret.AppendChar('x')
$lock = @{{}}
$script:attempt = [pscustomobject]@{{
    PayloadSha256 = ('b' * 64)
    Payload = [pscustomobject]@{{
        operation_id = '11111111-1111-4111-8111-111111111111'
        create_attempt_id = '22222222-2222-4222-8222-222222222222'
        intent_sha256 = ('c' * 64)
        source_binding_sha256 = ('d' * 64)
        source_cluster_system_identifier = 'cluster-1'
        source_database_oid = '100'
        restore_database = 'ticketbox_c07_restore_22222222222242228222222222222222'
        target_revision = '20260809_0001'
    }}
}}

# The real dump writer must bind tool/database/output, durably copy, inspect
# with pg_restore --list, and publish metadata only after all steps succeed.
$stateRoot = Join-Path '{tmp_path}' 'recovery-state'
[IO.Directory]::CreateDirectory($stateRoot) | Out-Null
$hostContract = [pscustomobject]@{{
    pg_dump_path = 'C:\\pg\\bin\\pg_dump.exe'; pg_dump_size = 1; pg_dump_sha256 = ('e' * 64)
    pg_restore_path = 'C:\\pg\\bin\\pg_restore.exe'; pg_restore_size = 1; pg_restore_sha256 = ('e' * 64)
}}
$hostAuthority = [pscustomobject]@{{ PsqlPath = 'C:\\pg\\bin\\psql.exe' }}
$script:dumpExit = 0
$script:events = @()
$archive = Get-TicketboxDatabaseGenerationRecoveryArchive $stateRoot $script:attempt $hostContract $hostAuthority $secret $lock
if (
    $script:dumpPath -cne 'C:\\pg\\bin\\pg_dump.exe' -or
    $script:dumpUrl -cne 'postgresql://postgres@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256' -or
    ($script:events -join ',') -cnotmatch 'dump,sync,copy,remove:.*,restore-list,artifact:target-recovery-archive$' -or
    [string]$archive.Payload.archive_sha256 -cne ('e' * 64)
) {{ throw "recovery archive writer order or identity drifted: $($script:events -join ',')" }}
$script:artifacts.Clear()
[IO.File]::Delete((Join-Path $stateRoot ([string]$archive.Payload.archive_file_name)))
$script:dumpExit = 1
$rejected = $false
try {{ Get-TicketboxDatabaseGenerationRecoveryArchive $stateRoot $script:attempt $hostContract $hostAuthority $secret $lock | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:artifacts.ContainsKey('target-recovery-archive')) {{ throw 'failed dump published recovery authority' }}
$script:dumpExit = 0

# Missing database: create closed from template0, exact-bind, then open.
$script:catalog = [pscustomobject]@{{ Exists = $false; ClusterSystemIdentifier = ''; DatabaseOid = 0; OwnerRoleOid = 0; Comment = ''; AllowsConnections = $false }}
$created = Get-TicketboxDatabaseGenerationRestoreBinding 'state' $script:attempt @{{}} $secret $lock
if ($script:writes -ne 2 -or -not $script:catalog.AllowsConnections) {{ throw 'fresh restore binding did not converge' }}

# CREATE response loss: the random database exists blank and closed, so bind it without a second CREATE.
$script:writes = 0
$script:artifacts.Remove('target-recovery-binding')
$script:catalog = [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]333; OwnerRoleOid = [uint32]77; Comment = ''; AllowsConnections = $false }}
$recovered = Get-TicketboxDatabaseGenerationRestoreBinding 'state' $script:attempt @{{}} $secret $lock
if ($script:writes -ne 1 -or [string]$recovered.Payload.restore_database_oid -cne '333') {{ throw 'CREATE response-loss recovery failed' }}

# A persisted binding never authorizes a database whose live owner drifted.
$script:writes = 0
$script:catalog.OwnerRoleOid = [uint32]88
$rejected = $false
try {{ Get-TicketboxDatabaseGenerationRestoreBinding 'state' $script:attempt @{{}} $secret $lock | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0) {{ throw 'persisted binding accepted a foreign database owner' }}
$script:catalog.OwnerRoleOid = [uint32]77

# The production restore body must execute the exact isolated pg_restore once,
# then converge without a second process after the target revision is visible.
$archive = [pscustomobject]@{{ Payload = [pscustomobject]@{{ pg_restore_sha256 = ('e' * 64) }} }}
$script:publicOwner = 'rogue_owner'
$script:writes = 0
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationArchiveRestore 'state' $script:attempt $archive $hostContract $hostAuthority $secret $lock }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0 -or $script:publicOwnerRepairs -ne 0 -or $script:restoreCalls -ne 0) {{ throw 'foreign public owner was mutated' }}
$script:publicOwner = 'pg_database_owner'
$script:restoreRevision = 'foreign_revision'
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationArchiveRestore 'state' $script:attempt $archive $hostContract $hostAuthority $secret $lock }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0 -or $script:publicOwnerRepairs -ne 0 -or $script:restoreCalls -ne 0) {{ throw 'foreign revision reached restore mutation' }}
$script:restoreRevision = ''
Invoke-TicketboxDatabaseGenerationArchiveRestore `
    'state' $script:attempt $archive $hostContract $hostAuthority $secret $lock
if ($script:restoreCalls -ne 1 -or
    $script:publicOwnerRepairs -ne 1 -or
    $script:restoreArguments -notcontains '--single-transaction' -or
    $script:restoreArguments -notcontains '--no-owner' -or
    $script:restoreArguments -notcontains '--role=ticketbox_owner' -or
    $script:restoreArguments -notcontains 'archive.dump') {{
    throw "isolated pg_restore body was not executed: calls=$script:restoreCalls args=$($script:restoreArguments -join ',')"
}}
$script:restoreRevision = '20260809_0001'
$script:publicOwner = 'pg_database_owner'
Invoke-TicketboxDatabaseGenerationArchiveRestore `
    'state' $script:attempt $archive $hostContract $hostAuthority $secret $lock
if ($script:restoreCalls -ne 1) {{ throw 'target-observed restore retry launched a second pg_restore' }}
if ($script:publicOwnerRepairs -ne 2 -or $script:publicOwner -cne 'ticketbox_owner') {{ throw 'target-observed retry skipped public schema ownership repair' }}
Invoke-TicketboxDatabaseGenerationArchiveRestore `
    'state' $script:attempt $archive $hostContract $hostAuthority $secret $lock
if ($script:restoreCalls -ne 1) {{ throw 'owner-normalized retry launched a second pg_restore' }}
if ($script:publicOwnerRepairs -ne 2) {{ throw 'owner-normalized retry repeated public schema ownership repair' }}

# A blank but open database, or any foreign marker, is never adopted or mutated.
foreach ($foreign in @(
    [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]444; OwnerRoleOid = [uint32]77; Comment = ''; AllowsConnections = $true }},
    [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]445; OwnerRoleOid = [uint32]77; Comment = 'foreign'; AllowsConnections = $false }}
)) {{
    $script:writes = 0
    $script:catalog = $foreign
    $rejected = $false
    try {{ Get-TicketboxDatabaseGenerationRestoreBinding 'state' $script:attempt @{{}} $secret $lock | Out-Null }} catch {{ $rejected = $true }}
    if (-not $rejected -or $script:writes -ne 0) {{ throw 'foreign restore database was mutated' }}
}}

# Cleanup requires the persisted OID and marker; an adjacent binding mutation must fail before DROP.
$script:catalog = [pscustomobject]@{{ Exists = $true; ClusterSystemIdentifier = 'cluster-1'; DatabaseOid = [uint32]333; OwnerRoleOid = [uint32]77; Comment = [string]$recovered.Payload.marker; AllowsConnections = $true }}
$tampered = [pscustomobject]@{{ Payload = [pscustomobject]@{{ restore_database_oid = '334'; marker = [string]$recovered.Payload.marker }} }}
$script:writes = 0
$rejected = $false
try {{ Remove-TicketboxDatabaseGenerationRestoreDatabase $script:attempt $tampered @{{}} $secret $lock }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:writes -ne 0 -or -not $script:catalog.Exists) {{ throw 'tampered cleanup binding reached DROP' }}
Remove-TicketboxDatabaseGenerationRestoreDatabase $script:attempt $recovered @{{}} $secret $lock
if ($script:writes -ne 1 -or $script:catalog.Exists) {{ throw 'exact restore cleanup did not converge' }}
Remove-TicketboxDatabaseGenerationRestoreDatabase $script:attempt $recovered @{{}} $secret $lock
if ($script:writes -ne 1) {{ throw 'absent cleanup was not idempotent' }}

# Execute the real outer recovery owner. It must restore, compare both targets,
# clean up, publish proof, then turn exact retry into a pure read.
$script:artifacts = @{{}}
$script:events = @()
$script:outerArchive = [pscustomobject]@{{ PayloadSha256 = ('4' * 64); Payload = [pscustomobject]@{{ archive_sha256 = ('5' * 64) }} }}
$script:outerBinding = [pscustomobject]@{{ PayloadSha256 = ('6' * 64); Payload = [pscustomobject]@{{ restore_database_oid = '222' }} }}
$outerIntent = [pscustomobject]@{{ PayloadSha256 = ('1' * 64); Payload = [pscustomobject]@{{ operation_id = [string]$script:attempt.Payload.operation_id; target_revision = '20260809_0001'; generation_program_sha256 = ('2' * 64) }} }}
$outerSource = [pscustomobject]@{{ PayloadSha256 = ('3' * 64) }}
function Get-TicketboxDatabaseGenerationRecoveryAttempt {{ $script:artifacts['target-recovery-attempt'] = $script:attempt; return $script:attempt }}
function Get-TicketboxDatabaseGenerationRecoveryArchive {{ $script:events += 'archive'; $script:artifacts['target-recovery-archive'] = $script:outerArchive; return $script:outerArchive }}
function Get-TicketboxDatabaseGenerationRestoreBinding {{ $script:events += 'binding'; $script:artifacts['target-recovery-binding'] = $script:outerBinding; return $script:outerBinding }}
function Invoke-TicketboxDatabaseGenerationArchiveRestore {{ $script:events += 'restore' }}
function Get-TicketboxDatabaseGenerationTargetVerification {{ param($Intent, $Attempt, $Credentials, $ReleaseIdentity, $HostAuthority, $Database, [switch]$IsRestore); $script:events += "verify:$Database"; $money = if ($IsRestore -and $script:semanticDrift) {{ '9' * 64 }} else {{ '8' * 64 }}; return [pscustomobject]@{{ resource_shape_sha256 = ('7' * 64); money_facts_sha256 = $money }} }}
function Assert-TicketboxDatabaseGenerationRecoveryChain {{ return $true }}
function Assert-TicketboxDatabaseGenerationRecoveryArchive {{ return 'archive.dump' }}
function Remove-TicketboxDatabaseGenerationRestoreDatabase {{ $script:events += 'cleanup' }}
function Get-TicketboxPostgresqlDatabaseCatalogObservation {{ return [pscustomobject]@{{ Exists = $false }} }}
function Get-TicketboxDatabaseGenerationTextSha256 {{ return ('a' * 64) }}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{ return '{{}}' }}
$script:semanticDrift = $false
$proof = Invoke-TicketboxDatabaseGenerationTargetRecovery $stateRoot $outerIntent $outerSource @{{}} @{{}} $lock $hostContract $hostAuthority $secret
if (
    [string]$proof.Payload.result -cne 'isolated_restore_verified' -or
    ($script:events -join ',') -cnotmatch 'archive,binding,restore,verify:ticketbox,verify:ticketbox_c07_restore_.*,artifact:target-recovery-verification,cleanup,artifact:target-recovery-proof'
) {{ throw "outer recovery did not close: $($script:events -join ',')" }}
$script:events = @()
Invoke-TicketboxDatabaseGenerationTargetRecovery $stateRoot $outerIntent $outerSource @{{}} @{{}} $lock $hostContract $hostAuthority $secret | Out-Null
if ($script:events.Count -ne 0) {{ throw 'published recovery proof retried mutation' }}
$script:artifacts.Remove('target-recovery-proof')
$script:artifacts.Remove('target-recovery-verification')
$script:semanticDrift = $true
$script:events = @()
$rejected = $false
try {{ Invoke-TicketboxDatabaseGenerationTargetRecovery $stateRoot $outerIntent $outerSource @{{}} @{{}} $lock $hostContract $hostAuthority $secret | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected -or $script:events -contains 'cleanup' -or $script:artifacts.ContainsKey('target-recovery-proof')) {{ throw 'semantic drift reached cleanup/proof' }}
"""
    _run_both(script, tmp_path)


def test_frozen_target_verifier_accepts_only_live_or_exact_attempt_database() -> None:
    launch = _load_launch_module()
    verifier = launch._load_database_generation_target_module()
    operation = "11111111-1111-4111-8111-111111111111"
    attempt = "22222222-2222-4222-8222-222222222222"
    restore = "ticketbox_c07_restore_22222222222242228222222222222222"

    assert (
        verifier._validated_database(
            "ticketbox",
            operation_id=operation,
            restore_attempt_id="",
        )
        == "ticketbox"
    )
    assert (
        verifier._validated_database(
            restore,
            operation_id=operation,
            restore_attempt_id=attempt,
        )
        == restore
    )
    for database, restore_attempt_id in (
        ("ticketbox", attempt),
        (restore, ""),
        ("ticketbox_c07_restore_33333333333343338333333333333333", attempt),
    ):
        with pytest.raises(
            verifier.DatabaseGenerationTargetVerificationError,
            match="outside the exact operation",
        ):
            verifier._validated_database(
                database,
                operation_id=operation,
                restore_attempt_id=restore_attempt_id,
            )


def test_frozen_target_entrypoint_binds_exact_program_attempt_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launch = _load_launch_module()
    captured: dict[str, object] = {}
    operation = "11111111-1111-4111-8111-111111111111"
    attempt = "22222222-2222-4222-8222-222222222222"
    restore = "ticketbox_c07_restore_22222222222242228222222222222222"
    pgpass = Path("C:/TicketboxInstallerSecrets/.ticketbox-pgpass-1-" + "1" * 32)
    result = {
        "schema": "ticketbox-database-generation-target-verification-v1",
        "operation_id": operation,
        "database": restore,
        "target_revision": "20260809_0001",
        "generation_program_sha256": "a" * 64,
        "alembic_revision": "20260809_0001",
        "resource_shape_sha256": "b" * 64,
        "money_facts_sha256": "c" * 64,
    }

    def run_action(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(launch, "_resolve_generation_program", Path)
    monkeypatch.setattr(
        launch,
        "_load_database_generation_target_module",
        lambda: SimpleNamespace(run_database_generation_target_verification_action=run_action),
    )
    for name in tuple(launch.os.environ):
        if name.upper().startswith("PG"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPASSFILE", str(pgpass))
    argv = [
        "--database-generation-verify-target",
        "--database-url",
        f"postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/{restore}",
        "--pgpassfile",
        str(pgpass),
        "--generation-program-path",
        "DATABASE_GENERATION_PROGRAM.json",
        "--expected-generation-program-sha256",
        "a" * 64,
        "--operation-id",
        operation,
        "--database",
        restore,
        "--restore-attempt-id",
        attempt,
        "--target-revision",
        "20260809_0001",
    ]
    output = io.StringIO()
    assert (
        launch._run_database_generation_target_verification(
            argv,
            input_stream=io.BytesIO(b""),
            output_stream=output,
        )
        == 0
    )
    assert captured["operation_id"] == operation
    assert captured["database"] == restore
    assert captured["restore_attempt_id"] == attempt
    assert captured["target_revision"] == "20260809_0001"
    assert (
        output.getvalue()
        == launch.json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n"
    )
