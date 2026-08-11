from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGING / "windows_c07_recovery_generation.ps1"
INSTALLATION_SAFETY = PACKAGING / "windows_installation_safety.ps1"
DATABASE_SCRIPT = PACKAGING / "windows_c07_database.ps1"
DATABASE_SAFETY_SCRIPT = PACKAGING / "windows_database_safety.ps1"


def _ps_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _run_harness(tmp_path: Path, name: str, source: str, *, timeout: int = 90) -> None:
    harness = tmp_path / f"{name}.ps1"
    harness.write_text(source, encoding="utf-8-sig")
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        assert result.returncode == 0, f"{Path(engine).name} failed:\n{result.stdout}\n{result.stderr}"


def test_recovery_source_is_host_authoritative_and_not_a_directory_mirror() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")
    raw = SCRIPT.read_bytes()

    assert source.startswith("#Requires -Version 5.1")
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "Resolve-TicketboxC07DatabaseHostAuthority" in source
    assert "Assert-TicketboxC07LiveHostConnection" in source
    assert "current_setting('data_directory')" in source
    assert "pg_export_snapshot()" in source
    assert (
        "ORDER BY public_id;\n"
        "DO `$ticketbox_timeout`$"
        in source
    )
    assert "SET statement_timeout = '0'" not in source
    assert "SET transaction_timeout = '0'" not in source
    preflight = source[
        source.index("function Get-TicketboxC07RecoverySnapshotPreflightSql") :
        source.index("function Get-TicketboxC07RecoverySnapshotSql")
    ]
    target = source[
        source.index("function Get-TicketboxC07RecoverySnapshotSql") :
        source.index("function Start-TicketboxC07RecoverySnapshotProcess")
    ]
    assert "'transaction_timeout',\n    armed_transaction_ms::text || 'ms',\n    false" in preflight
    assert "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;" in target
    assert "PERFORM set_config(\n    'transaction_timeout'" not in target
    assert source.count('"--command", (') >= 2
    assert "activity.xact_start" in source
    assert "transaction_timeout_armed_ms" in source
    assert "transaction_timeout_derived_upper_bound_expiry_utc" in source
    assert "transaction_timeout_reconfigured_in_transaction" in source
    assert "pre_begin_transaction_plus_per_statement_absolute_v1" in source
    assert "transaction_timeout_effective_remaining_ms" not in source
    assert "effective_transaction_ms" not in source
    assert "idle_in_transaction_session_timeout_effective_ms" in source
    assert "lock_timeout_applied_ms := CASE" in source
    assert "ELSE LEAST(configured_lock_ms, 5000::bigint, holder_remaining_ms)" in source
    assert "SELECT 'TBX_TIMEOUTS:'" in source
    assert "TimeoutContract = $timeoutContract" in source
    assert "TransactionDeadlineUtc = " in source
    assert "exported snapshot 超过 transaction deadline" in source
    assert "SELECT pg_sleep_until(" in source
    assert "pg_sleep_until_active_statement" in source
    assert (
        source.index("SELECT 'TBX_TIMEOUTS:'")
        < source.index("SELECT 'TBX_READY';")
        < source.index("SELECT pg_sleep_until(")
    )
    assert "MaximumRemainingCeilingMilliseconds" in source
    assert "ticketbox.c07_snapshot_maintenance_deadline_utc" in source
    assert "--snapshot=$($Snapshot.SnapshotId)" in source
    assert "Expense.image_path" in source
    assert "Expense.thumbnail_path" in source
    assert "image_deleted_at IS NOT NULL" in source
    assert "thumbnail_deleted_at IS NOT NULL" in source
    assert "pg_tablespace_location" in source
    assert "pg_ls_waldir" in source
    assert "pg_wal" in source
    assert "cleanup_pending" in source
    assert "RestoreIdentityPath" in source
    assert "RestoreCreateIntentPath" in source
    assert "generation_payload_sha256" in source
    assert '"windows_atomic_artifacts.ps1"' in source
    assert "Copy-TicketboxVerifiedArtifact" in source
    assert "Publish-TicketboxVerifiedArtifactDirectory" in source
    assert "Sync-TicketboxDurableArtifactFile $OutputPath" in source
    assert "acl_hash_only" in source
    assert "-CreateIntent $intent" in source
    assert "-CreateAttemptId ([string]$protected.CreateAttemptId)" in source
    assert "protected-intent database create" not in source
    assert "Read-TicketboxC07ProductionRecoveryGeneration" in source
    assert "[string]$DatabaseUrl" not in source
    assert "[string]$PgData" not in source
    assert "Copy-Item" not in source
    assert "robocopy" not in source.lower()
    assert "/MIR" not in source
    assert "Invoke-Expression" not in source
    assert "PGPASSWORD" not in source
    assert "Resolve-TicketboxC07RecoveryConfiguredUploadRoot" in source
    assert "Get-OrCreateTicketboxC07RecoveryUploadRootAuthority" in source
    assert '"recovery_upload_root_authority"' in source
    assert '"upload_root_binding_sha256"' in source


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell GUID contract")
def test_recovery_operation_id_matches_shared_canonical_guid_contract(
    tmp_path: Path,
) -> None:
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

$historical = '1493b3d9-3721-0e51-0255-58aba5ba6e99'
$rfcUuid = '123e4567-e89b-42d3-a456-426614174099'
foreach ($accepted in @($historical, $rfcUuid)) {{
    if ((ConvertTo-TicketboxC07CanonicalOperationId $accepted) -cne $accepted) {{
        throw "canonical operation ID did not round-trip: $accepted"
    }}
}}

foreach ($rejected in @(
    '',
    '00000000-0000-0000-0000-000000000000',
    '1493B3D9-3721-0E51-0255-58ABA5BA6E99',
    'not-a-guid'
)) {{
    $failedClosed = $false
    try {{
        ConvertTo-TicketboxC07CanonicalOperationId $rejected | Out-Null
    }}
    catch {{
        $failedClosed = $true
    }}
    if (-not $failedClosed) {{
        throw "non-canonical operation ID was accepted: $rejected"
    }}
}}
"""
    _run_harness(tmp_path, "canonical-operation-guid", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory identity contract")
def test_external_upload_root_is_operation_bound_and_identity_drift_fails_closed(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    app_root = data_root / "app"
    default_root = app_root / "uploads"
    external_root = tmp_path / "external-receipts"
    host_root = tmp_path / "host-authority"
    relative = Path("owner") / "2026" / "07" / "receipt.png"
    app_root.mkdir(parents=True)
    host_root.mkdir()
    (default_root / relative).parent.mkdir(parents=True)
    (external_root / relative).parent.mkdir(parents=True)
    (default_root / relative).write_bytes(b"wrong-default-root")
    (external_root / relative).write_bytes(b"external-authoritative-original")
    (app_root / ".env").write_text(
        f"UPLOAD_DIR='{external_root}'\n",
        encoding="utf-8",
    )

    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(INSTALLATION_SAFETY)}'
. '{_ps_literal(SCRIPT)}'

$script:leaseChecks = 0
function Assert-TicketboxC07OperationLease {{
    param($Authority,$LifecycleLock)
    if ([string]$LifecycleLock.Token -cne 'held') {{
        throw 'operation lease missing'
    }}
    $script:leaseChecks += 1
}}
function Read-EnvMap {{
    param([string]$Path)
    $map = @{{}}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {{
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith('#')) {{ continue }}
        $index = $trimmed.IndexOf('=')
        if ($index -gt 0) {{
            $map[$trimmed.Substring(0,$index).Trim()] =
                $trimmed.Substring($index + 1).Trim()
        }}
    }}
    return $map
}}
function Write-TicketboxC07HostEnvelope {{
    param($Path,$ArtifactKind,$Payload)
    $envelope = [ordered]@{{
        artifact_kind = [string]$ArtifactKind
        payload = $Payload
    }}
    $text = $envelope | ConvertTo-Json -Depth 8 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {{
        $stream.Write($bytes,0,$bytes.Length)
        $stream.Flush($true)
    }}
    finally {{ $stream.Dispose() }}
    return [pscustomobject]@{{ Payload = [pscustomobject]$Payload }}
}}
function Read-TicketboxC07HostEnvelope {{
    param($Path,$ExpectedKind)
    $parsed = [IO.File]::ReadAllText($Path,[Text.Encoding]::UTF8) |
        ConvertFrom-Json
    if ([string]$parsed.artifact_kind -cne [string]$ExpectedKind) {{
        throw 'host envelope kind mismatch'
    }}
    return [pscustomobject]@{{ Payload = $parsed.payload }}
}}

$operation = '123e4567-e89b-42d3-a456-426614174099'
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{ operation_id = $operation }}
    ReleaseIdentity = [pscustomobject]@{{
        DataRoot = '{_ps_literal(data_root)}'
        Fingerprint = ('A' * 64)
    }}
    Roots = [pscustomobject]@{{ HostRoot = '{_ps_literal(host_root)}' }}
}}
$lock = [pscustomobject]@{{ Token = 'held' }}
$binding = Get-OrCreateTicketboxC07RecoveryUploadRootAuthority `
    -Authority $authority `
    -LifecycleLock $lock
if ($script:leaseChecks -ne 1) {{ throw 'authority creation bypassed operation lease' }}
if (-not (Test-TicketboxPathEquals `
    ([string]$binding.Root) `
    '{_ps_literal(external_root)}')) {{
    throw 'configured external upload root was not authoritative'
}}
if ([string]$binding.BindingSha256 -cnotmatch '^[0-9a-f]{{64}}$') {{
    throw 'upload-root authority binding hash is not canonical lowercase'
}}
$row = [pscustomobject]@{{
    expense_public_id = '123e4567-e89b-42d3-a456-426614174000'
    ledger_id = 'owner'
    image_reference = 'uploads/owner/2026/07/receipt.png'
    image_sha256 = ('b' * 64)
    image_deleted = $false
    thumbnail_reference = ''
    thumbnail_deleted = $false
}}
$plan = Get-TicketboxC07RecoveryAssetSourcePlan `
    -Inventory @($row) `
    -UploadRoot ([string]$binding.Root)
if ($plan.Originals.Count -ne 1 -or
    -not (Test-TicketboxPathEquals `
        ([string]$plan.Originals[0].SourcePath) `
        '{_ps_literal(external_root / relative)}')) {{
    throw 'asset plan fell back to the decoy default root'
}}

# Mutation intent: a post-bind configuration rewrite must not silently switch
# the same operation back to the default app/uploads directory.
[IO.File]::WriteAllText(
    '{_ps_literal(app_root / ".env")}',
    "UPLOAD_DIR=uploads`n",
    [Text.UTF8Encoding]::new($false)
)
$configurationDriftRejected = $false
try {{
    Get-OrCreateTicketboxC07RecoveryUploadRootAuthority `
        -Authority $authority `
        -LifecycleLock $lock | Out-Null
}}
catch {{ $configurationDriftRejected = $true }}
if (-not $configurationDriftRejected) {{
    throw 'post-bind upload-root configuration drift was accepted'
}}

# Restore the configured path, then replace the directory at that exact path.
# The stable string is insufficient: volume/file identity must also match.
[IO.File]::WriteAllText(
    '{_ps_literal(app_root / ".env")}',
    "UPLOAD_DIR='{_ps_literal(external_root)}'`n",
    [Text.UTF8Encoding]::new($false)
)
$relocated = '{_ps_literal(tmp_path / "external-receipts-original")}'
[IO.Directory]::Move('{_ps_literal(external_root)}',$relocated)
[IO.Directory]::CreateDirectory('{_ps_literal(external_root)}') | Out-Null
$identityDriftRejected = $false
try {{
    Read-TicketboxC07RecoveryUploadRootAuthority `
        -Authority $authority `
        -ExpectedConfiguredRoot '{_ps_literal(external_root)}' | Out-Null
}}
catch {{ $identityDriftRejected = $true }}
if (-not $identityDriftRejected) {{
    throw 'same-path replacement of upload root directory was accepted'
}}
[IO.Directory]::Delete('{_ps_literal(external_root)}',$true)
[IO.Directory]::Move($relocated,'{_ps_literal(external_root)}')
[IO.File]::Delete([string]$binding.Path)
"""
    _run_harness(tmp_path, "external-upload-root-authority", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path/handle contract")
def test_path_manifest_and_missing_original_fail_closed(tmp_path: Path) -> None:
    upload_root = tmp_path / "data" / "uploads"
    image = upload_root / "owner" / "2026" / "07" / "receipt.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"same-generation-original")
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()

    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {{
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\\')
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd('\\')
    return $candidate.StartsWith(
        $root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{
    if ($Path -like '*forced-reparse*') {{ throw 'reparse point rejected' }}
}}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ($Path -like '*forced-reparse*') {{ return 'ReparsePoint' }}
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}

$root = '{_ps_literal(upload_root)}'
$valid = Resolve-TicketboxC07RecoveryAssetReference `
    -Reference 'uploads/owner/2026/07/receipt.png' `
    -LedgerId 'owner' `
    -UploadRoot $root `
    -Label 'valid original'
if ($valid.Kind -cne 'File') {{ throw 'valid original did not resolve' }}

$unhashedRow = [pscustomobject]@{{
    expense_public_id = '123e4567-e89b-42d3-a456-426614173999'
    ledger_id = 'owner'
    image_reference = 'uploads/owner/2026/07/receipt.png'
    image_sha256 = ''
    image_deleted = $false
    thumbnail_reference = ''
    thumbnail_deleted = $false
}}
$unhashedRejected = $false
try {{
    Get-TicketboxC07RecoveryAssetSourcePlan `
        -Inventory @($unhashedRow) `
        -UploadRoot $root | Out-Null
}}
catch {{
    $unhashedRejected = (
        $_.Exception.Message -match '缺少权威 SHA-256'
    )
}}
if (-not $unhashedRejected) {{
    throw 'active original without database digest became backup authority'
}}

foreach ($bad in @(
    '../escape.png',
    'C:\\escape.png',
    '\\\\server\\share\\escape.png',
    'uploads/other/2026/07/receipt.png',
    'uploads/owner/../other/receipt.png',
    'uploads/owner/x:evil.png'
)) {{
    $rejected = $false
    try {{
        Resolve-TicketboxC07RecoveryAssetReference `
            -Reference $bad `
            -LedgerId 'owner' `
            -UploadRoot $root `
            -Label 'bad reference' | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "unsafe reference accepted: $bad" }}
}}

$missingRow = [pscustomobject]@{{
    expense_public_id = '123e4567-e89b-42d3-a456-426614174000'
    ledger_id = 'owner'
    image_reference = 'uploads/owner/2026/07/missing.png'
    image_sha256 = ''
    image_deleted = $false
    thumbnail_reference = ''
    thumbnail_deleted = $false
}}
$missingRejected = $false
try {{
    Get-TicketboxC07RecoveryAssetSourcePlan `
        -Inventory @($missingRow) `
        -UploadRoot $root | Out-Null
}}
catch {{ $missingRejected = $true }}
if (-not $missingRejected) {{ throw 'missing active original was accepted' }}

$unsafeThumb = [pscustomobject]@{{
    expense_public_id = '123e4567-e89b-42d3-a456-426614174001'
    ledger_id = 'owner'
    image_reference = 'uploads/owner/2026/07/receipt.png'
    image_sha256 = '{image_sha}'
    image_deleted = $false
    thumbnail_reference = 'uploads/owner/../other/thumb.jpg'
    thumbnail_deleted = $false
}}
$thumbRejected = $false
try {{
    Get-TicketboxC07RecoveryAssetSourcePlan `
        -Inventory @($unsafeThumb) `
        -UploadRoot $root | Out-Null
}}
catch {{ $thumbRejected = $true }}
if (-not $thumbRejected) {{
    throw 'unsafe thumbnail reference escaped audit because thumbnails are derived'
}}

$payload = [ordered]@{{
    schema = 'test'
    operation_id = '123e4567-e89b-42d3-a456-426614174000'
    nested = [ordered]@{{ value = 'bound' }}
}}
$text = New-TicketboxC07RecoveryEnvelopeText $payload
$parsed = ConvertFrom-TicketboxC07RecoveryEnvelopeText $text
if ($parsed.Payload.nested.value -cne 'bound') {{ throw 'manifest roundtrip failed' }}
$replacementPrefix = if ($parsed.PayloadSha256[0] -ceq '0') {{ '1' }} else {{ '0' }}
$corrupted = $text.Replace(
    $parsed.PayloadSha256,
    $replacementPrefix + $parsed.PayloadSha256.Substring(1)
)
$corruptionRejected = $false
try {{ ConvertFrom-TicketboxC07RecoveryEnvelopeText $corrupted | Out-Null }}
catch {{ $corruptionRejected = $true }}
if (-not $corruptionRejected) {{
    throw 'manifest accidental digest corruption was accepted'
}}
"""
    _run_harness(tmp_path, "path-manifest-missing", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows volume contract")
def test_capacity_rejects_low_disk_tablespace_and_external_wal(
    tmp_path: Path,
) -> None:
    pg_data = tmp_path / "pgdata"
    generation = tmp_path / "host" / "recovery-generations"
    (pg_data / "pg_wal").mkdir(parents=True)
    generation.mkdir(parents=True)

    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{
    if ($script:externalWal -and $Path.EndsWith('pg_wal')) {{
        throw 'external WAL rejected'
    }}
}}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ($script:externalWal -and $Path.EndsWith('pg_wal')) {{
        return 'ReparsePoint'
    }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    return 'Missing'
}}
function Get-TicketboxC07RecoveryVolumeKey([string]$Path) {{ return 'TEST-VOLUME' }}
function Get-TicketboxC07RecoveryVolumeFreeBytes([string]$Path) {{
    return [uint64]$script:freeBytes
}}

    $context = [pscustomobject]@{{
    DatabaseAuthority = [pscustomobject]@{{ PgData = '{_ps_literal(pg_data)}' }}
    DatabaseIdentity = [pscustomobject]@{{
        DatabaseOid = [uint32]42
        ClusterSystemIdentifier = '7123456789012345678'
    }}
    Paths = [pscustomobject]@{{
        GenerationRoot = '{_ps_literal(generation)}'
    }}
}}
$meta = [pscustomobject]@{{
    database = 'ticketbox'
    database_oid = '42'
    cluster_system_identifier = '7123456789012345678'
    data_directory = '{_ps_literal(pg_data)}'
    server_version_num = '170000'
    database_size_bytes = '1000'
    wal_bytes = '100'
    server_id = '123e4567-e89b-42d3-a456-426614174000'
    data_generation = '123e4567-e89b-42d3-a456-426614174001'
    alembic_heads = @('20260722_0001')
}}
$snapshot = [pscustomobject]@{{
    Meta = $meta
    Tablespaces = @()
}}

$script:externalWal = $false
$script:freeBytes = [uint64]100000000
    $plan = Get-TicketboxC07RecoveryCapacityPlan `
        -Context $context `
        -Snapshot $snapshot `
        -AssetBytes 500 `
        -ExpectedRevision '20260722_0001'
if (
    $plan.volume_mode -cne 'shared' -or
    [uint64]$plan.required_with_headroom_bytes -lt 5400
) {{
    throw 'capacity plan omitted dump/restore/rewrite/WAL/assets/headroom'
}}

$script:freeBytes = [uint64]100
$lowDiskRejected = $false
try {{
        Get-TicketboxC07RecoveryCapacityPlan `
            -Context $context `
            -Snapshot $snapshot `
            -AssetBytes 500 `
            -ExpectedRevision '20260722_0001' | Out-Null
}}
catch {{ $lowDiskRejected = $true }}
if (-not $lowDiskRejected) {{ throw 'low disk was accepted' }}

$script:freeBytes = [uint64]100000000
$snapshot.Tablespaces = @([pscustomobject]@{{
    name = 'outside'
    location = 'D:\\pg-ts'
    size_bytes = '1'
}})
$tablespaceRejected = $false
try {{
        Get-TicketboxC07RecoveryCapacityPlan `
            -Context $context `
            -Snapshot $snapshot `
            -AssetBytes 0 `
            -ExpectedRevision '20260722_0001' | Out-Null
}}
catch {{ $tablespaceRejected = $true }}
if (-not $tablespaceRejected) {{ throw 'external tablespace was accepted' }}

$snapshot.Tablespaces = @()
$script:externalWal = $true
$walRejected = $false
try {{
        Get-TicketboxC07RecoveryCapacityPlan `
            -Context $context `
            -Snapshot $snapshot `
            -AssetBytes 0 `
            -ExpectedRevision '20260722_0001' | Out-Null
}}
catch {{ $walRejected = $true }}
if (-not $walRejected) {{ throw 'external/reparse pg_wal was accepted' }}
"""
    _run_harness(tmp_path, "capacity-fail-closed", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows protected intent contract")
def test_restore_create_intent_refuses_preexisting_and_crash_window(
    tmp_path: Path,
) -> None:
    generation_root = tmp_path / "generation"
    generation_root.mkdir()
    create_intent = generation_root / "restore-create-intent.json"
    restore_identity = generation_root / "restore-identity.json"
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {{
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\\')
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd('\\')
    return $candidate.StartsWith(
        $root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param(
        [string]$Path,
        [string]$Text,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount,
        [switch]$ReplaceExisting
    )
    if ([IO.File]::Exists($Path) -and -not $ReplaceExisting) {{
        throw 'protected artifact exists'
    }}
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param([string]$Path)
    return [pscustomobject]@{{
        Text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    }}
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param([string]$Path)
    [IO.File]::Delete($Path)
}}
[IO.File]::Delete('{_ps_literal(create_intent)}')
[IO.File]::Delete('{_ps_literal(restore_identity)}')

$operation = '123e4567-e89b-42d3-a456-426614174000'
$database = 'ticketbox_c07_restore_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
function Get-TicketboxC07RestoreDatabaseName {{
    param([string]$OperationId, [string]$CreateAttemptId)
    return $database
}}
function Assert-TicketboxC07RestoreIdentity {{ param([object]$Identity) }}
$script:liveExists = $true
$script:sqlMutations = 0
$script:helperMutations = 0
$script:cleanupMutations = 0
$script:crashAfterCreate = $false
$script:foreignLive = $false
function Get-TicketboxC07DatabaseCatalogObservation {{
    return [pscustomobject]@{{
        Exists = $script:liveExists
        ClusterSystemIdentifier = '7123456789012345678'
        Database = $database
        DatabaseOid = if ($script:liveExists) {{ [uint32]99 }} else {{ [uint32]0 }}
    }}
}}
function Get-TicketboxC07RestoreNamespaceDatabases {{
    if (-not $script:liveExists) {{ return @() }}
    return @($database)
}}
function Assert-TicketboxC07RestoreAttemptNamespace {{
    param([object]$Authority, [object]$SuperuserPassword, [string]$ExpectedDatabase)
    $entries = @(Get-TicketboxC07RestoreNamespaceDatabases)
    if (@($entries | Where-Object {{ $_ -cne $ExpectedDatabase }}).Count -gt 0) {{
        throw 'foreign restore namespace entry'
    }}
    return $entries
}}
function Invoke-TicketboxC07Sql {{
    $script:sqlMutations++
    throw 'recovery must not own CREATE SQL'
}}
function New-TicketboxC07RestoreDatabase {{
    param(
        [Security.SecureString]$SuperuserPassword,
        [string]$OperationId,
        [object]$CreateIntent,
        [string]$OperationKind,
        [string]$TargetAlembicRevision,
        [string]$RevisionManifestSha256
    )
    $script:helperMutations++
    if (
        $OperationId -cne $operation -or
        $OperationKind -cne 'c07_money_minor_bigint_v1' -or
        $TargetAlembicRevision -cne '20260729_0001' -or
        $RevisionManifestSha256 -cne ('B' * 64) -or
        $null -eq $CreateIntent -or
        [string]$CreateIntent.Payload.state -cne 'create_pending' -or
        -not [IO.File]::Exists('{_ps_literal(create_intent)}')
    ) {{
        throw 'database helper did not receive protected create-intent'
    }}
    $script:liveExists = $true
    if ($script:crashAfterCreate) {{
        $script:crashAfterCreate = $false
        throw 'injected crash after exact helper CREATE'
    }}
    if ($script:foreignLive) {{
        throw 'injected foreign live marker mismatch'
    }}
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-restore-db-v2'
        OperationId = $operation
        ClusterSystemIdentifier = '7123456789012345678'
        Database = $database
        DatabaseOid = [uint32]99
        OwnerRoleOid = [uint32]77
        MigratorRoleOid = [uint32]78
        MarkerPhase = 'active'
        State = 'active'
        CreateAttemptId = [string]$CreateIntent.AttemptId
    }}
}}
function Remove-TicketboxC07RestoreDatabaseExact {{
    param(
        [object]$SuperuserPassword,
        [object]$Identity,
        [string]$CreateAttemptId
    )
    $script:cleanupMutations++
    $cleanupIntent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $context `
        -Generation $generation
    if (
        $null -eq $cleanupIntent -or
        $CreateAttemptId -cne [string]$cleanupIntent.AttemptId
    ) {{
        throw 'cleanup did not preserve the protected create attempt'
    }}
    if ($script:foreignLive) {{
        throw 'foreign database must never reach exact cleanup'
    }}
    $script:liveExists = $false
    return [pscustomobject]@{{
        Schema = [string]$Identity.Schema
        OperationId = [string]$Identity.OperationId
        ClusterSystemIdentifier = [string]$Identity.ClusterSystemIdentifier
        Database = [string]$Identity.Database
        DatabaseOid = [uint32]$Identity.DatabaseOid
        OwnerRoleOid = [uint32]$Identity.OwnerRoleOid
        MigratorRoleOid = [uint32]$Identity.MigratorRoleOid
        MarkerPhase = 'cleanup_pending'
        State = 'cleaned'
    }}
}}
$context = [pscustomobject]@{{
        Authority = [pscustomobject]@{{
            Receipt = [pscustomobject]@{{ operation_id = $operation }}
            ReleaseIdentity = [pscustomobject]@{{
                InstallationId = '123e4567-e89b-42d3-a456-426614174001'
            }}
            Descriptor = [pscustomobject]@{{ Payload = [pscustomobject]@{{
                operation_kind = 'c07_money_minor_bigint_v1'
                target_alembic_revision = '20260729_0001'
                revision_manifest_sha256 = ('B' * 64)
            }} }}
        }}
    DatabaseAuthority = [pscustomobject]@{{}}
    DatabaseIdentity = [pscustomobject]@{{
        ClusterSystemIdentifier = '7123456789012345678'
    }}
    Paths = [pscustomobject]@{{
        GenerationRoot = '{_ps_literal(generation_root)}'
        RestoreCreateIntentPath = '{_ps_literal(create_intent)}'
        RestoreIdentityPath = '{_ps_literal(restore_identity)}'
    }}
}}
$generation = [pscustomobject]@{{ PayloadSha256 = ('a' * 64) }}
$secret = New-Object Security.SecureString
foreach ($index in 1..32) {{ $secret.AppendChar('Q') }}
$secret.MakeReadOnly()

$preexisting = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $preexisting.State -cne 'repair_required' -or
    $script:sqlMutations -ne 0 -or
    $script:helperMutations -ne 0 -or
    $script:cleanupMutations -ne 0
) {{
    throw 'preexisting same-name database was mutated or adopted'
}}

$script:liveExists = $false
$script:crashAfterCreate = $true
$crashed = $false
$crashMessage = ''
try {{
    New-TicketboxC07RecoveryRestoreDatabaseBound `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $secret | Out-Null
}}
catch {{
    $crashMessage = $_.Exception.ToString()
    $crashed = $_.Exception.Message -like '*injected crash*'
}}
if (
    -not $crashed -or
    -not [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}') -or
    -not $script:liveExists
) {{
    throw (
        'CREATE crash window did not preserve protected ambiguous state: ' +
        $crashMessage
    )
}}
$sqlAfterCrash = $script:sqlMutations
$afterCrash = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $afterCrash.State -cne 'cleaned' -or
    $script:sqlMutations -ne $sqlAfterCrash -or
    $script:helperMutations -ne 2 -or
    $script:cleanupMutations -ne 1 -or
    $script:liveExists -or
    [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}')
) {{
    throw 'exact CREATE crash residue did not rebuild identity and clean'
}}

$script:liveExists = $false
New-TicketboxC07RecoveryRestoreCreateIntent `
    -Context $context `
    -Generation $generation | Out-Null
$script:liveExists = $true
$script:foreignLive = $true
$foreign = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $foreign.State -cne 'repair_required' -or
    -not $script:liveExists -or
    $script:helperMutations -ne 3 -or
    $script:cleanupMutations -ne 1 -or
    -not [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}')
) {{
    throw 'foreign same-name database was adopted or deleted'
}}
"""
    _run_harness(tmp_path, "restore-create-intent-fail-closed", source)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell cross-script contract")
def test_database_and_recovery_scripts_share_single_create_owner_and_cleanup_retry(
    tmp_path: Path,
) -> None:
    generation_root = tmp_path / "cross-script-generation"
    generation_root.mkdir()
    create_intent = generation_root / "restore-create-intent.json"
    restore_identity = generation_root / "restore-identity.json"
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(DATABASE_SCRIPT)}'
. '{_ps_literal(SCRIPT)}'

function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {{
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\\')
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd('\\')
    return $candidate.StartsWith(
        $root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
$script:failCleanupIdentityWrite = $false
function Write-TicketboxProtectedUtf8FileDurable {{
    param(
        [string]$Path,
        [string]$Text,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount,
        [switch]$ReplaceExisting
    )
    if (
        $script:failCleanupIdentityWrite -and
        (Test-TicketboxPathEquals $Path '{_ps_literal(restore_identity)}')
    ) {{
        throw 'injected crash before cleanup identity durable write'
    }}
    if ([IO.File]::Exists($Path) -and -not $ReplaceExisting) {{
        throw 'protected artifact exists'
    }}
    [IO.File]::WriteAllText(
        $Path,
        $Text,
        [Text.UTF8Encoding]::new($false)
    )
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param(
        [string]$Path,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount,
        [int64]$MaximumBytes
    )
    return [pscustomobject]@{{
        Text = [IO.File]::ReadAllText(
            $Path,
            [Text.UTF8Encoding]::new($false)
        )
    }}
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param(
        [string]$Path,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount
    )
    [IO.File]::Delete($Path)
}}

[IO.File]::Delete('{_ps_literal(create_intent)}')
[IO.File]::Delete('{_ps_literal(restore_identity)}')
$operation = '123e4567-e89b-42d3-a456-426614174000'
function Get-TicketboxC07RestoreDatabaseName {{
    param([string]$OperationId, [string]$CreateAttemptId)
    return 'ticketbox_c07_restore_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
}}
$database = Get-TicketboxC07RestoreDatabaseName `
    -OperationId $operation `
    -CreateAttemptId '323e4567-e89b-42d3-a456-426614174000'
$script:restoreDatabaseName = $database
$script:catalog = [pscustomobject]@{{
    ClusterSystemIdentifier = '7123456789012345678'
    Database = $database
    DatabaseOid = [uint32]0
    OwnerRoleOid = [uint32]0
    AllowsConnections = $false
    Marker = ''
    Exists = $false
}}
$script:sqlLabels = @()
$script:dropShouldFail = $false
$script:dropCalls = 0
$script:restoreAttempt = ''

function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        Port = 5544
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword
    )
}}
function Get-TicketboxC07RoleOid {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Role,
        [switch]$AllowAbsent
    )
    if ($Role -ceq 'ticketbox_owner') {{ return [uint32]5001 }}
    if ($Role -ceq 'ticketbox_migrator') {{ return [uint32]5002 }}
    throw "unexpected role lookup: $Role"
}}
function Get-TicketboxC07DatabaseCatalogObservation {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword,
        [string]$Database
    )
    if ($Database -cne $script:catalog.Database) {{
        throw 'database catalog name drifted'
    }}
    return $script:catalog
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    $script:sqlLabels += $Label
    if ($Label -ceq 'C07 restore attempt namespace inspect') {{
        if ($script:catalog.Exists) {{
            return [string]$script:catalog.Database
        }}
        return ''
    }}
    elseif ($Label -ceq 'C07 unregistered restore attempt fence inspect') {{
        return "true`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue`ttrue"
    }}
    elseif ($Label -ceq 'C07 isolated restore database create') {{
        if (
            $script:catalog.Exists -or
            -not [IO.File]::Exists('{_ps_literal(create_intent)}')
        ) {{
            throw 'helper CREATE lacked unique protected intent'
        }}
        $observedIntent = Read-TicketboxC07RecoveryRestoreCreateIntent `
            -Context $context `
            -Generation $generation
        if (
            $null -eq $observedIntent -or
            [string]$observedIntent.Payload.state -cne 'create_pending'
        ) {{
            throw 'helper CREATE did not observe create_pending'
        }}
        $script:restoreAttempt = [string]$observedIntent.AttemptId
        $script:catalog.DatabaseOid = [uint32]4242
        $script:catalog.OwnerRoleOid = [uint32]5001
        $script:catalog.AllowsConnections = $false
        $script:catalog.Marker = ''
        $script:catalog.Exists = $true
    }}
    elseif ($Label -ceq 'C07 isolated restore exact identity registration') {{
        $script:catalog.Marker = (
            'ticketbox-c07-restore-database-v3|' + $operation + '|' +
            $script:restoreAttempt + '|registered|7123456789012345678|' +
            $script:restoreDatabaseName +
            '|4242|5001|5002'
        )
    }}
    elseif ($Label -ceq 'C07 isolated restore ACL/open transaction') {{
        if ($script:catalog.Marker -cnotmatch '\\|registered\\|') {{
            throw 'database opened before exact registration'
        }}
        $script:catalog.Marker = (
            'ticketbox-c07-restore-database-v3|' + $operation + '|' +
            $script:restoreAttempt + '|active|7123456789012345678|' +
            $script:restoreDatabaseName +
            '|4242|5001|5002'
        )
        $script:catalog.AllowsConnections = $true
    }}
    elseif ($Label -ceq 'C07 isolated restore database ACL verification') {{
        return "true`ttrue`ttrue`ttrue`ttrue"
    }}
    elseif ($Label -ceq 'C07 isolated restore cleanup latch') {{
        $script:catalog.Marker = (
            'ticketbox-c07-restore-database-v3|' + $operation + '|' +
            $script:restoreAttempt + '|cleanup_pending|7123456789012345678|' +
            $script:restoreDatabaseName +
            '|4242|5001|5002'
        )
        $script:catalog.AllowsConnections = $false
    }}
    else {{
        throw "unexpected SQL label: $Label"
    }}
    return ''
}}
function Invoke-TicketboxC07SqlResult {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label,
        [int]$TimeoutMilliseconds = 600000
    )
    if ($Label -cne 'C07 isolated restore database exact cleanup') {{
        throw "unexpected SQL result label: $Label"
    }}
    $script:dropCalls++
    if ($script:dropShouldFail) {{
        return [pscustomobject]@{{ ExitCode = 1; Output = '' }}
    }}
    $script:catalog.Exists = $false
    $script:catalog.DatabaseOid = [uint32]0
    $script:catalog.OwnerRoleOid = [uint32]0
    $script:catalog.AllowsConnections = $false
    $script:catalog.Marker = ''
    return [pscustomobject]@{{ ExitCode = 0; Output = '' }}
}}

$context = [pscustomobject]@{{
    Authority = [pscustomobject]@{{
        Receipt = [pscustomobject]@{{ operation_id = $operation }}
        ReleaseIdentity = [pscustomobject]@{{
            InstallationId = '223e4567-e89b-42d3-a456-426614174000'
        }}
        Descriptor = [pscustomobject]@{{ Payload = [pscustomobject]@{{
            operation_kind = 'c07_money_minor_bigint_v1'
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('B' * 64)
        }} }}
    }}
    DatabaseAuthority = [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
    }}
    DatabaseIdentity = [pscustomobject]@{{
        ClusterSystemIdentifier = '7123456789012345678'
    }}
    Paths = [pscustomobject]@{{
        GenerationRoot = '{_ps_literal(generation_root)}'
        RestoreCreateIntentPath = '{_ps_literal(create_intent)}'
        RestoreIdentityPath = '{_ps_literal(restore_identity)}'
    }}
}}
$generation = [pscustomobject]@{{ PayloadSha256 = ('a' * 64) }}
$secret = New-Object Security.SecureString
foreach ($index in 1..32) {{ $secret.AppendChar('K') }}
$secret.MakeReadOnly()

function New-CrossScriptRestore {{
    $identity = New-TicketboxC07RecoveryRestoreDatabaseBound `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $secret
    Write-TicketboxC07RecoveryRestoreIdentityArtifact `
        -Context $context `
        -Generation $generation `
        -Identity $identity | Out-Null
    return $identity
}}

$first = New-CrossScriptRestore
if (
    $first.DatabaseOid -ne 4242 -or
    -not ($script:sqlLabels -contains 'C07 isolated restore database create') -or
    $script:sqlLabels -contains
        'C07 isolated restore protected-intent database create'
) {{
    throw 'recovery bypassed the real database helper unique CREATE contract'
}}
$firstCleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $firstCleanup.State -cne 'cleaned' -or
    $script:catalog.Exists -or
    [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}')
) {{
    throw 'cross-script happy path did not converge'
}}

$identityBoundOnly = New-TicketboxC07RecoveryRestoreDatabaseBound `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
$boundIntent = Read-TicketboxC07RecoveryRestoreCreateIntent `
    -Context $context `
    -Generation $generation
$createCountBeforeIdentityRepair = @(
    $script:sqlLabels |
        Where-Object {{ $_ -ceq 'C07 isolated restore database create' }}
).Count
if (
    [string]$boundIntent.Payload.state -cne 'identity_bound' -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}')
) {{
    throw 'identity-bound-before-artifact crash window was not reproduced'
}}
$identityCrashCleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
$createCountAfterIdentityRepair = @(
    $script:sqlLabels |
        Where-Object {{ $_ -ceq 'C07 isolated restore database create' }}
).Count
if (
    $identityCrashCleanup.State -cne 'cleaned' -or
    $script:catalog.Exists -or
    $createCountAfterIdentityRepair -ne $createCountBeforeIdentityRepair -or
    [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}')
) {{
    throw 'identity-bound restart did not rebuild exact identity and clean'
}}

$foreignIntent = New-TicketboxC07RecoveryRestoreCreateIntent `
    -Context $context `
    -Generation $generation
$foreignAttempt = '323e4567-e89b-42d3-a456-426614174099'
$script:catalog.DatabaseOid = [uint32]9090
$script:catalog.OwnerRoleOid = [uint32]5001
$script:catalog.AllowsConnections = $true
$script:catalog.Marker = (
    'ticketbox-c07-restore-database-v3|' + $operation + '|' + $foreignAttempt +
    '|active|7123456789012345678|' + $script:restoreDatabaseName +
    '|9090|5001|5002'
)
$script:catalog.Exists = $true
$dropCallsBeforeForeign = $script:dropCalls
$foreign = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $foreign.State -cne 'repair_required' -or
    -not $script:catalog.Exists -or
    [uint32]$script:catalog.DatabaseOid -ne 9090 -or
    [string]$script:catalog.Marker -cnotmatch
        [regex]::Escape("|$foreignAttempt|active|") -or
    $script:dropCalls -ne $dropCallsBeforeForeign -or
    -not [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}')
) {{
    throw 'foreign same-name database was registered, adopted, or deleted'
}}
[IO.File]::Delete('{_ps_literal(create_intent)}')
$script:catalog.DatabaseOid = [uint32]0
$script:catalog.OwnerRoleOid = [uint32]0
$script:catalog.AllowsConnections = $false
$script:catalog.Marker = ''
$script:catalog.Exists = $false

$second = New-CrossScriptRestore
$script:dropShouldFail = $true
$script:failCleanupIdentityWrite = $true
$interrupted = $false
try {{
    Clear-TicketboxC07RecoveryRestoreDatabase `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $secret | Out-Null
}}
catch {{
    $interrupted = $_.Exception.Message -match
        'injected crash before cleanup identity durable write'
}}
if (-not $interrupted -or -not $script:catalog.Exists) {{
    throw 'cleanup crash window was not reproduced'
}}
$transition = Read-TicketboxC07RecoveryRestoreIdentityArtifact `
    -Context $context `
    -Generation $generation
if (
    $transition.State -cne 'cleanup_pending' -or
    $transition.IdentityArtifactState -cne 'active' -or
    $transition.CreateIntentState -cne 'cleanup_pending' -or
    $script:catalog.Marker -cnotmatch '\\|cleanup_pending\\|'
) {{
    throw 'active identity plus cleanup_pending intent was not resumable'
}}
$script:dropShouldFail = $false
$script:failCleanupIdentityWrite = $false
$retried = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $retried.State -cne 'cleaned' -or
    $script:catalog.Exists -or
    [IO.File]::Exists('{_ps_literal(create_intent)}') -or
    [IO.File]::Exists('{_ps_literal(restore_identity)}') -or
    $script:dropCalls -ne 4
) {{
    throw 'cleanup crash retry did not converge DB and both artifacts'
}}
"""
    _run_harness(tmp_path, "database-recovery-cross-script", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native handle contract")
def test_native_destination_parent_lock_and_ready_write_through(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(b"handle-bound-copy")
    source_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()
    generation_root = tmp_path / "generation"
    destination_parent = generation_root / "partial" / "assets"
    destination_parent.mkdir(parents=True)
    destination = destination_parent / "asset.bin"
    renamed_parent = destination_parent.with_name("assets-renamed")
    ready_partial = generation_root / "publish.partial"
    ready_partial.mkdir()
    (ready_partial / "flushed.txt").write_text("ready", encoding="utf-8")
    ready_root = generation_root / "publish.ready"
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (-not [IO.File]::Exists($Path) -and -not [IO.Directory]::Exists($Path)) {{
        return 'Missing'
    }}
    $attributes = [IO.File]::GetAttributes($Path)
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {{
        return 'ReparsePoint'
    }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'File'
}}
function Get-TicketboxVolumeIdentityForPath {{ param([string]$Path) 'TEST-VOLUME' }}
function Set-TicketboxExactFileAcl {{ param([string]$Path) }}
function Assert-TicketboxExactFileAcl {{ param([string]$Path) }}
function Assert-TicketboxProtectedDirectoryAcl {{ param([string]$Path) }}

if ([IO.Directory]::Exists('{_ps_literal(renamed_parent)}')) {{
    [IO.Directory]::Move(
        '{_ps_literal(renamed_parent)}',
        '{_ps_literal(destination_parent)}'
    )
}}
[IO.File]::Delete('{_ps_literal(destination)}')
if ([IO.Directory]::Exists('{_ps_literal(ready_root)}')) {{
    [IO.Directory]::Delete('{_ps_literal(ready_root)}', $true)
}}
if (-not [IO.Directory]::Exists('{_ps_literal(ready_partial)}')) {{
    [IO.Directory]::CreateDirectory('{_ps_literal(ready_partial)}') | Out-Null
}}
[IO.File]::WriteAllText(
    (Join-Path '{_ps_literal(ready_partial)}' 'flushed.txt'),
    'ready',
    [Text.UTF8Encoding]::new($false)
)

Initialize-TicketboxAtomicArtifactNativeMethods
$parentHandle =
    [TicketboxAtomicArtifactNativeMethods]::OpenDirectoryNoFollowNoDelete(
        '{_ps_literal(destination_parent)}'
    )
$renameBlocked = $false
try {{
    [IO.Directory]::Move(
        '{_ps_literal(destination_parent)}',
        '{_ps_literal(renamed_parent)}'
    )
}}
catch {{ $renameBlocked = $true }}
finally {{ $parentHandle.Dispose() }}
if (-not $renameBlocked) {{
    throw 'destination parent rename was not blocked by the live handle'
}}

$copy = Copy-TicketboxVerifiedArtifact `
    -SourcePath '{_ps_literal(source_file)}' `
    -DestinationPath '{_ps_literal(destination)}' `
    -ExpectedSourceSha256 '{source_sha}' `
    -ExpectedLength ([int64]{source_file.stat().st_size}) `
    -FullControlAccounts @('SYSTEM') `
    -OwnerAccount 'SYSTEM'
if (
    $copy.Sha256 -cne '{source_sha}' -or
    -not [IO.File]::Exists('{_ps_literal(destination)}')
) {{
    throw 'native no-follow destination copy failed'
}}

$context = [pscustomobject]@{{
    Paths = [pscustomobject]@{{
        GenerationRoot = '{_ps_literal(generation_root)}'
        PartialRoot = '{_ps_literal(ready_partial)}'
        ReadyRoot = '{_ps_literal(ready_root)}'
    }}
}}
Publish-TicketboxVerifiedArtifactDirectory `
    -GenerationRoot $context.Paths.GenerationRoot `
    -PartialRoot $context.Paths.PartialRoot `
    -ReadyRoot $context.Paths.ReadyRoot `
    -FullControlAccounts @('SYSTEM') `
    -OwnerAccount 'SYSTEM' | Out-Null
if (
    [IO.Directory]::Exists('{_ps_literal(ready_partial)}') -or
    -not [IO.File]::Exists(
        (Join-Path '{_ps_literal(ready_root)}' 'flushed.txt')
    )
) {{
    throw 'native write-through READY publish did not reach one terminal name'
}}
"""
    _run_harness(tmp_path, "native-handle-ready-publish", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native publish failures")
def test_ready_publish_never_replaces_target_and_failed_move_converges(
    tmp_path: Path,
) -> None:
    generation_root = tmp_path / "publish-failures"
    partial = generation_root / "generation.partial"
    ready = generation_root / "generation.ready"
    cleanup = generation_root / "generation-cleanup.json"
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {{
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\\')
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd('\\')
    return $candidate.StartsWith(
        $root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if (-not [IO.File]::Exists($Path) -and -not [IO.Directory]::Exists($Path)) {{
        return 'Missing'
    }}
    $attributes = [IO.File]::GetAttributes($Path)
    if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {{
        return 'ReparsePoint'
    }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'File'
}}
function Get-TicketboxVolumeIdentityForPath {{ param([string]$Path) 'TEST-VOLUME' }}
function Assert-TicketboxProtectedDirectoryAcl {{ param([string]$Path) }}
function Remove-TicketboxTreeExact {{
    param([string]$Path)
    [IO.Directory]::Delete($Path, $true)
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param([string]$Path)
    [IO.File]::Delete($Path)
}}

function Reset-PublishFixture {{
    if ([IO.Directory]::Exists('{_ps_literal(generation_root)}')) {{
        [IO.Directory]::Delete('{_ps_literal(generation_root)}', $true)
    }}
    [IO.Directory]::CreateDirectory('{_ps_literal(partial)}') | Out-Null
}}
$context = [pscustomobject]@{{
    Authority = [pscustomobject]@{{
        Receipt = [pscustomobject]@{{
            operation_id = '123e4567-e89b-42d3-a456-426614174000'
        }}
    }}
    Paths = [pscustomobject]@{{
        GenerationRoot = '{_ps_literal(generation_root)}'
        PartialRoot = '{_ps_literal(partial)}'
        ReadyRoot = '{_ps_literal(ready)}'
        CleanupPath = '{_ps_literal(cleanup)}'
    }}
}}

Reset-PublishFixture
[IO.File]::WriteAllText(
    (Join-Path '{_ps_literal(partial)}' 'source.txt'),
    'candidate',
    [Text.UTF8Encoding]::new($false)
)
[IO.Directory]::CreateDirectory('{_ps_literal(ready)}') | Out-Null
[IO.File]::WriteAllText(
    (Join-Path '{_ps_literal(ready)}' 'sentinel.txt'),
    'existing-authority',
    [Text.UTF8Encoding]::new($false)
)
$targetRejected = $false
try {{
    Publish-TicketboxVerifiedArtifactDirectory `
        -GenerationRoot $context.Paths.GenerationRoot `
        -PartialRoot $context.Paths.PartialRoot `
        -ReadyRoot $context.Paths.ReadyRoot `
        -FullControlAccounts @('SYSTEM') `
        -OwnerAccount 'SYSTEM' | Out-Null
}}
catch {{ $targetRejected = $true }}
if (
    -not $targetRejected -or
    -not [IO.File]::Exists((Join-Path '{_ps_literal(partial)}' 'source.txt')) -or
    [IO.File]::ReadAllText(
        (Join-Path '{_ps_literal(ready)}' 'sentinel.txt')
    ) -cne 'existing-authority'
) {{
    throw 'pre-existing READY target was replaced or source was moved'
}}

Reset-PublishFixture
$lockedPath = Join-Path '{_ps_literal(partial)}' 'locked.bin'
[IO.File]::WriteAllBytes($lockedPath, [byte[]](1, 2, 3, 4))
$locked = [IO.File]::Open(
    $lockedPath,
    [IO.FileMode]::Open,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::Read
)
$moveFailed = $false
try {{
    Publish-TicketboxVerifiedArtifactDirectory `
        -GenerationRoot $context.Paths.GenerationRoot `
        -PartialRoot $context.Paths.PartialRoot `
        -ReadyRoot $context.Paths.ReadyRoot `
        -FullControlAccounts @('SYSTEM') `
        -OwnerAccount 'SYSTEM' | Out-Null
}}
catch {{
    $moveFailed = $_.Exception.ToString() -match
        'MoveFileEx\\(MOVEFILE_WRITE_THROUGH\\)'
}}
finally {{
    $locked.Dispose()
}}
if (
    -not $moveFailed -or
    [IO.Directory]::Exists('{_ps_literal(ready)}') -or
    -not [IO.Directory]::Exists('{_ps_literal(partial)}')
) {{
    throw 'MoveFileEx failure did not preserve one uncommitted partial tree'
}}
$cleaned = Clear-TicketboxC07RecoveryPartialGeneration $context
if (
    $cleaned.State -cne 'cleaned' -or
    [IO.Directory]::Exists('{_ps_literal(partial)}') -or
    [IO.Directory]::Exists('{_ps_literal(ready)}')
) {{
    throw 'MoveFileEx failure did not converge to no published generation'
}}
"""
    _run_harness(tmp_path, "ready-publish-failure-convergence", source)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows recovery generation")
def test_generation_restore_reconcile_and_reentry_cleanup(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    upload_root = data_root / "uploads"
    image = upload_root / "owner" / "2026" / "07" / "receipt.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"release-original-bytes")
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    host_root = tmp_path / "host"
    host_root.mkdir()

    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function ConvertTo-TicketboxCanonicalPath([string]$Path) {{
    return [IO.Path]::GetFullPath($Path).TrimEnd('\\')
}}
function Test-TicketboxPathEquals([string]$Left, [string]$Right) {{
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd('\\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\\'),
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Test-TicketboxPathWithin([string]$Path, [string]$Parent) {{
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd('\\')
    $root = [IO.Path]::GetFullPath($Parent).TrimEnd('\\')
    return $candidate.StartsWith(
        $root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}}
function Assert-NoTicketboxAncestorReparsePoints([string]$Path) {{}}
function Set-TicketboxExactFileAcl {{
    param([string]$Path, [string[]]$Accounts, [string]$OwnerAccount)
}}
function Assert-TicketboxExactFileAcl {{
    param([string]$Path, [string[]]$Accounts, [string]$OwnerAccount)
}}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
function Get-TicketboxVolumeIdentityForPath {{ param([string]$Path) 'TEST-VOLUME' }}
function Assert-TicketboxProtectedDirectoryAcl {{ param([string]$Path) }}
function Initialize-TicketboxProtectedDirectoryAtomically {{
    param([string]$Path)
    [IO.Directory]::CreateDirectory($Path) | Out-Null
    return $Path
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param(
        [string]$Path,
        [string]$Text,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount,
        [switch]$ReplaceExisting
    )
    if ([IO.File]::Exists($Path) -and -not $ReplaceExisting) {{
        throw 'protected file exists'
    }}
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param(
        [string]$Path,
        [string[]]$FullControlAccounts,
        [string]$OwnerAccount,
        [int]$MaximumBytes
    )
    return [pscustomobject]@{{
        Text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    }}
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param([string]$Path)
    [IO.File]::Delete($Path)
}}
function Remove-TicketboxTreeExact {{
    param([string]$Path)
    if ($script:forceCleanupFailure) {{ throw 'injected cleanup failure' }}
    if ([IO.Directory]::Exists($Path)) {{
        [IO.Directory]::Delete($Path, $true)
    }}
}}

$operation = '123e4567-e89b-42d3-a456-426614174000'
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{
        operation_id = $operation
        stage = 'writers_frozen'
        stage_sequence = [int64]1
        transition_kind = 'stage'
        database_binding_sha256 = ('8' * 64)
        freeze_proof_sha256 = ('A' * 64)
        freeze_heartbeat_sequence = [int64]1
        authority_chain_sha256 = ('B' * 64)
        previous_stage = 'captured'
        previous_authority_chain_sha256 = ''
    }}
    ReleaseIdentity = [pscustomobject]@{{
        Fingerprint = ('C' * 64)
        InstallationId = '123e4567-e89b-42d3-a456-426614174002'
        BuildManifestSha256 = ('D' * 64)
        BackendVersionFloor = '1.0.0'
        DataRoot = '{_ps_literal(data_root)}'
    }}
    Descriptor = [pscustomobject]@{{
        Payload = [pscustomobject]@{{
            operation_kind = 'c07_money_minor_bigint_v1'
            source_alembic_revision = '20260722_0001'
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('E' * 64)
        }}
    }}
    Roots = [pscustomobject]@{{ HostRoot = '{_ps_literal(host_root)}' }}
}}
$priorGenerationRoot = Join-Path `
    '{_ps_literal(host_root)}' `
    'recovery-generations'
if ([IO.Directory]::Exists($priorGenerationRoot)) {{
    [IO.Directory]::Delete($priorGenerationRoot, $true)
}}
$paths = Get-TicketboxC07RecoveryPaths $authority
$context = [pscustomobject]@{{
    Authority = $authority
    DatabaseAuthority = [pscustomobject]@{{
        PgData = '{_ps_literal(tmp_path / "pgdata")}'
        PsqlPath = 'psql.exe'
    }}
    DatabaseIdentity = [pscustomobject]@{{
        ClusterSystemIdentifier = '7123456789012345678'
        DatabaseOid = [uint32]42
    }}
    UploadRoot = '{_ps_literal(upload_root)}'
    UploadRootBindingSha256 = ('f' * 64)
    Paths = $paths
    PgDumpPath = 'pg_dump.exe'
    PgRestorePath = 'pg_restore.exe'
        DatabaseUrl = 'internal-only'
        MaintenanceDeadlineUtc =
            [DateTime]::UtcNow.AddMinutes(20).ToString('o')
    }}
    function Get-TicketboxWindowsDeadlineRemainingMilliseconds {{
        param(
            [object]$Budget,
            [int]$MaximumMilliseconds = 600000,
            [string]$Label
        )
        return [Math]::Min($MaximumMilliseconds, 600000)
    }}
function Get-TicketboxC07RecoveryContext {{
    param(
        [string]$DataRoot,
        [object]$LifecycleLock,
        [object]$SuperuserPassword,
        [string[]]$AllowedStages = @('writers_frozen')
    )
    if ([string]$authority.Receipt.stage -cnotin $AllowedStages) {{
        throw 'recovery context rejected unsupported stage'
    }}
    return $context
}}
function Open-TicketboxC07RecoverySnapshot {{
    return [pscustomobject]@{{
        Process = [pscustomobject]@{{ HasExited = $false }}
        SnapshotId = '00000003-0000001B-1'
        FenceCutVerified = $true
        Meta = [pscustomobject]@{{
            database = 'ticketbox'
            database_oid = '42'
            cluster_system_identifier = '7123456789012345678'
            data_directory = '{_ps_literal(tmp_path / "pgdata")}'
            server_version_num = '170000'
            database_size_bytes = '1000'
            wal_bytes = '1000'
            server_id = '123e4567-e89b-42d3-a456-426614174003'
            data_generation = '123e4567-e89b-42d3-a456-426614174004'
            alembic_heads = @('20260722_0001')
        }}
        Tablespaces = @()
        Assets = @([pscustomobject]@{{
            expense_public_id = '123e4567-e89b-42d3-a456-426614174005'
            ledger_id = 'owner'
            image_reference = 'uploads/owner/2026/07/receipt.png'
            image_sha256 = '{image_sha}'
            image_deleted = $false
            thumbnail_reference = 'uploads/owner/2026/07/thumbs/missing.jpg'
            thumbnail_deleted = $false
        }})
    }}
}}
function Assert-TicketboxC07RecoverySnapshotAlive {{ param([object]$Snapshot) }}
function Close-TicketboxC07RecoverySnapshot {{ param([object]$Snapshot) }}
function Get-TicketboxC07RecoveryLiveSourceBinding {{
    return [pscustomobject]@{{
        database = 'ticketbox'
        database_oid = '42'
        cluster_system_identifier = '7123456789012345678'
        server_id = '123e4567-e89b-42d3-a456-426614174003'
        data_generation = '123e4567-e89b-42d3-a456-426614174004'
        alembic_heads = @('20260722_0001')
    }}
}}
function Get-TicketboxC07RecoveryCapacityPlan {{
    return [ordered]@{{
        schema = 'ticketbox-c07-recovery-capacity-v1'
        volume_mode = 'shared'
        database_size_bytes = '1000'
        dump_estimate_bytes = '1000'
        isolated_restore_estimate_bytes = '1000'
        rewrite_index_estimate_bytes = '1000'
        observed_wal_bytes = '1000'
        wal_reserve_bytes = '1000'
        asset_generation_copy_bytes = '22'
        asset_isolated_restore_bytes = '22'
        manifest_inventory_reserve_bytes = '4'
        required_with_headroom_bytes = '4858'
        free_bytes_at_preflight = '10000'
        headroom_percent = 20
    }}
}}
function Invoke-TicketboxC07RecoverySnapshotDump {{
    param([object]$Context, [object]$Snapshot, [object]$SuperuserPassword, [string]$OutputPath)
    [IO.File]::WriteAllBytes($OutputPath, [byte[]](1,2,3,4))
    return [pscustomobject]@{{
        FileName = [IO.Path]::GetFileName($OutputPath)
        Sha256 = Get-TicketboxC07RecoveryFileSha256 $OutputPath
        SizeBytes = [int64]4
        RestoreListSha256 = ('e' * 64)
    }}
}}

$secret = New-Object Security.SecureString
foreach ($index in 1..32) {{ $secret.AppendChar('S') }}
$secret.MakeReadOnly()
$moneyFactsAction = {{
    param(
        $HostAuthority,
        $MigratorPassword,
        $Database,
        $OperationId,
        $SnapshotId,
        $ExpectedRevision,
        $MaintenanceDeadlineUtc,
        $MaintenanceRemainingCeilingMilliseconds,
        $MaintenanceAuthoritySha256,
        $PgpassPath
    )
    return [pscustomobject][ordered]@{{
        schema = 'ticketbox-c07-money-facts-result-v2'
        operation_id = $OperationId
        database = $Database
        snapshot_id = $SnapshotId
        maintenance_authority_sha256 =
            ([string]$MaintenanceAuthoritySha256).ToLowerInvariant()
        maintenance_remaining_ceiling_ms =
            [int]$MaintenanceRemainingCeilingMilliseconds
        alembic_revision = $ExpectedRevision
        money_facts_sha256 = ('7' * 64)
    }}
}}
$first = Invoke-TicketboxC07RecoveryGeneration `
    -DataRoot '{_ps_literal(data_root)}' `
    -LifecycleLock ([pscustomobject]@{{}}) `
    -SuperuserPassword $secret `
    -MigratorPassword $secret `
    -ExpectedSourceRevision '20260722_0001' `
    -MoneyFactsAction $moneyFactsAction
if (
    $first.State -cne 'generation_ready' -or
    $first.Reused -or
    -not [IO.Directory]::Exists($paths.ReadyRoot) -or
    [IO.Directory]::Exists($paths.PartialRoot)
) {{
    throw 'generation did not atomically publish READY'
}}
$second = Invoke-TicketboxC07RecoveryGeneration `
    -DataRoot '{_ps_literal(data_root)}' `
    -LifecycleLock ([pscustomobject]@{{}}) `
    -SuperuserPassword $secret `
    -MigratorPassword $secret `
    -ExpectedSourceRevision '20260722_0001' `
    -MoneyFactsAction $moneyFactsAction
if (-not $second.Reused -or $second.EvidenceSha256 -cne $first.EvidenceSha256) {{
    throw 'valid READY generation was not idempotently reused'
}}

$manifestPath = Join-Path $paths.ReadyRoot $paths.ManifestFileName
$originalManifestText = [IO.File]::ReadAllText(
    $manifestPath,
    [Text.UTF8Encoding]::new($false)
)
$semanticPayload = (
    ConvertFrom-TicketboxC07RecoveryEnvelopeText $originalManifestText
).Payload
$semanticPayload.original_copies.asset_directory = '..\\outside'
[IO.File]::WriteAllText(
    $manifestPath,
    (New-TicketboxC07RecoveryEnvelopeText $semanticPayload),
    [Text.UTF8Encoding]::new($false)
)
$semanticEscapeRejected = $false
try {{
    Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $paths.ReadyRoot | Out-Null
}}
catch {{ $semanticEscapeRejected = $true }}
finally {{
    [IO.File]::WriteAllText(
        $manifestPath,
        $originalManifestText,
        [Text.UTF8Encoding]::new($false)
    )
}}
if (-not $semanticEscapeRejected) {{
    throw 're-hashed manifest asset_directory escape was accepted'
}}

$provenancePayload = (
    ConvertFrom-TicketboxC07RecoveryEnvelopeText $originalManifestText
).Payload
$provenancePayload.lifecycle.authority_chain_sha256 = ('F' * 64)
[IO.File]::WriteAllText(
    $manifestPath,
    (New-TicketboxC07RecoveryEnvelopeText $provenancePayload),
    [Text.UTF8Encoding]::new($false)
)
$staleProvenanceRejected = $false
try {{
    Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $paths.ReadyRoot | Out-Null
}}
catch {{ $staleProvenanceRejected = $true }}
finally {{
    [IO.File]::WriteAllText(
        $manifestPath,
        $originalManifestText,
        [Text.UTF8Encoding]::new($false)
    )
}}
if (-not $staleProvenanceRejected) {{
    throw 're-hashed stale lifecycle provenance was accepted'
}}

$producerPayload = [ordered]@{{
    schema = 'ticketbox-c07-recovery-generation-v3'
    operation_id = $operation
    result = 'generation_ready'
    database_binding_sha256 = ('8' * 64)
    operation_kind = 'c07_money_minor_bigint_v1'
    alembic_target = '20260729_0001'
    revision_manifest_sha256 = ('E' * 64)
    subject_sha256 = ([string]$first.EvidenceSha256).ToUpperInvariant()
}}
$script:recoveryReadyStageEvidence = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        target_stage = 'recovery_generation_ready'
        source_stage = 'writers_frozen'
        source_stage_sequence = [int64]1
        source_authority_chain_sha256 = ('B' * 64)
        producer_payload_json = (
            $producerPayload | ConvertTo-Json -Depth 4 -Compress
        )
    }}
    PayloadSha256 = ('9' * 64)
}}
function Read-TicketboxC07StageEvidence {{
    param([object]$Authority, [string]$Stage)
    if ($Stage -cne 'recovery_generation_ready') {{
        throw 'production reader requested wrong typed evidence'
    }}
    return $script:recoveryReadyStageEvidence
}}
$authority.Receipt.previous_stage = 'writers_frozen'
$authority.Receipt.previous_authority_chain_sha256 = ('B' * 64)
$authority.Receipt.authority_chain_sha256 = ('F' * 64)
$authority.Receipt.stage = 'recovery_generation_ready'
$authority.Receipt.stage_sequence = [int64]2
$generation = Read-TicketboxC07RecoveryManifest `
    -Context $context -Root $paths.ReadyRoot
$copies = Assert-TicketboxC07RecoveryGenerationFiles $generation
$inventory = Read-TicketboxC07RecoveryJsonLines `
    -Path $generation.InventoryPath -Kind inventory -ExpectedRows 1
$reconcile = Assert-TicketboxC07RecoveryAssetReconcile `
    -Inventory $inventory -Copies $copies
if ($reconcile.OriginalCopies -ne 1) {{ throw 'original reconcile failed' }}

function Get-TicketboxC07RestoreDatabaseName {{
    param([string]$OperationId, [string]$CreateAttemptId)
    return 'ticketbox_c07_restore_cccccccccccccccccccccccccccccccccccccccc'
}}
function Assert-TicketboxC07RestoreIdentity {{
    param([object]$Identity)
    if (
        $Identity.Schema -cne 'ticketbox-c07-restore-db-v2' -or
        [uint32]$Identity.OwnerRoleOid -ne 77 -or
        [uint32]$Identity.MigratorRoleOid -ne 78
    ) {{ throw 'invalid restore identity stub' }}
}}
    $script:restoreDbExists = $false
    function Get-TicketboxC07RestoreNamespaceDatabases {{
        if ($script:restoreDbExists) {{
            return @(
                'ticketbox_c07_restore_cccccccccccccccccccccccccccccccccccccccc'
            )
        }}
        return @()
    }}
    function Assert-TicketboxC07RestoreAttemptNamespace {{
        param([object]$Authority, [object]$SuperuserPassword, [string]$ExpectedDatabase)
        $foreign = @(
            Get-TicketboxC07RestoreNamespaceDatabases |
                Where-Object {{ $_ -cne $ExpectedDatabase }}
        )
        if ($foreign.Count -gt 0) {{ throw 'foreign restore namespace entry' }}
    }}
function Get-TicketboxC07DatabaseCatalogObservation {{
    return [pscustomobject]@{{
        Exists = $script:restoreDbExists
        ClusterSystemIdentifier = '7123456789012345678'
        DatabaseOid = [uint32]99
    }}
}}
function Invoke-TicketboxC07Sql {{
    param(
        [object]$Authority,
        [string]$Database,
        [string]$Role,
        [Security.SecureString]$Password,
        [string]$Sql,
        [string]$Label
    )
    if ($Label -cnotin @(
        'C07 isolated replay migrator window open',
        'C07 isolated replay migrator window close'
    )) {{
        throw 'recovery must not issue restore CREATE SQL directly'
    }}
    return ''
}}
    function New-TicketboxC07RestoreDatabase {{
        param(
            [Security.SecureString]$SuperuserPassword,
            [string]$OperationId,
            [object]$CreateIntent,
            [string]$OperationKind,
            [string]$TargetAlembicRevision,
            [string]$RevisionManifestSha256
        )
        if (
            $script:restoreDbExists -or
            $OperationKind -cne 'c07_money_minor_bigint_v1' -or
            $TargetAlembicRevision -cne '20260729_0001' -or
            $RevisionManifestSha256 -cne ('E' * 64) -or
            $null -eq $CreateIntent -or
        [string]$CreateIntent.Payload.state -cne 'create_pending' -or
        -not [IO.File]::Exists($paths.RestoreCreateIntentPath)
    ) {{
        throw 'restore helper did not exclusively own protected CREATE'
    }}
    $script:restoreDbExists = $true
    $script:replayCommitted = $false
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-restore-db-v2'
        OperationId = $operation
        ClusterSystemIdentifier = '7123456789012345678'
        Database = 'ticketbox_c07_restore_cccccccccccccccccccccccccccccccccccccccc'
        DatabaseOid = [uint32]99
        OwnerRoleOid = [uint32]77
        MigratorRoleOid = [uint32]78
        MarkerPhase = 'active'
        State = 'active'
        CreateAttemptId = [string]$CreateIntent.AttemptId
    }}
}}
function Invoke-TicketboxC07RecoveryArchiveRestore {{}}
$script:restoreAssets = @($inventory)
$script:replayCommitted = $false
$script:mutateAssetsAfterReplay = $false
function Get-TicketboxC07RestoredInventory {{
    $assets = @($script:restoreAssets)
    if ($script:replayCommitted -and $script:mutateAssetsAfterReplay) {{
        $assets = @([pscustomobject]@{{
            expense_public_id = '123e4567-e89b-42d3-a456-426614174005'
            ledger_id = 'owner'
            image_reference = 'uploads/owner/2026/07/post-replay-mutated.png'
            image_sha256 = '{image_sha}'
            image_deleted = $false
            thumbnail_reference = ''
            thumbnail_deleted = $false
        }})
    }}
    return [pscustomobject]@{{
        Meta = [pscustomobject]@{{
            database =
                'ticketbox_c07_restore_cccccccccccccccccccccccccccccccccccccccc'
            database_oid = '99'
            cluster_system_identifier = '7123456789012345678'
            server_id = '123e4567-e89b-42d3-a456-426614174003'
            data_generation = '123e4567-e89b-42d3-a456-426614174004'
            alembic_heads = @(
                if ($script:replayCommitted) {{
                    '20260729_0001'
                }}
                else {{
                    '20260722_0001'
                }}
            )
        }}
        Assets = @($assets)
    }}
}}
$script:cleanupState = 'cleaned'
$script:restoreCleanupCalls = 0
function Remove-TicketboxC07RestoreDatabaseExact {{
    param(
        [object]$SuperuserPassword,
        [object]$Identity,
        [string]$CreateAttemptId
    )
    $script:restoreCleanupCalls++
    $cleanupIntent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $context `
        -Generation $generation
    if (
        [string]::IsNullOrWhiteSpace($CreateAttemptId) -or
        $null -eq $cleanupIntent -or
        $CreateAttemptId -cne [string]$cleanupIntent.AttemptId
    ) {{
        throw 'restore cleanup lost create-attempt binding'
    }}
    if ($script:cleanupState -ceq 'cleaned') {{
        $script:restoreDbExists = $false
    }}
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-restore-db-v2'
        OperationId = $operation
        ClusterSystemIdentifier = '7123456789012345678'
        Database = 'ticketbox_c07_restore_cccccccccccccccccccccccccccccccccccccccc'
        DatabaseOid = [uint32]99
        OwnerRoleOid = [uint32]77
        MigratorRoleOid = [uint32]78
        MarkerPhase = 'cleanup_pending'
        State = $script:cleanupState
        CreateAttemptId = $CreateAttemptId
    }}
}}
$script:forwardReplayCalls = 0
$script:rejectForwardReplay = $false
$script:mutateForwardMoneyFacts = $false
$script:reportTargetObserved = $false
$forwardReplayAction = {{
    param(
        $HostAuthority,
        $MigratorPassword,
            $RestoreDatabase,
            $OperationId,
            $SourceRevision,
            $TargetRevision,
            $RevisionManifestSha256,
            $MaintenanceDeadlineUtc,
            $MaintenanceRemainingCeilingMilliseconds,
            $MaintenanceAuthoritySha256,
            $RestoreAttemptId
    )
    $script:forwardReplayCalls++
    if ($script:rejectForwardReplay) {{
        throw 'injected frozen C07 replay rejection'
    }}
    $script:replayCommitted = $true
    return [pscustomobject][ordered]@{{
            schema = 'ticketbox-c07-maintenance-upgrade-result-v3'
            mode = 'isolated_replay'
            operation_id = $OperationId
            source_revision = $SourceRevision
            target_revision = $TargetRevision
            revision_manifest_sha256 =
                ([string]$RevisionManifestSha256).ToLowerInvariant()
            maintenance_authority_sha256 =
                ([string]$MaintenanceAuthoritySha256).ToLowerInvariant()
            maintenance_remaining_ceiling_ms =
                [int]$MaintenanceRemainingCeilingMilliseconds
            resource_shape_sha256 = ('5' * 64)
            result = if ($script:reportTargetObserved) {{
            'target_observed_after_interruption'
        }} else {{
            'isolated_forward_replay_verified'
        }}
        alembic_revision = $TargetRevision
        target_shape_sha256 = ('6' * 64)
        money_facts_sha256 = if ($script:mutateForwardMoneyFacts) {{
            ('8' * 64)
        }} else {{
            ('7' * 64)
        }}
    }}
}}
$restore = Test-TicketboxC07RecoveryGenerationRestore `
    -DataRoot '{_ps_literal(data_root)}' `
    -LifecycleLock ([pscustomobject]@{{}}) `
    -SuperuserPassword $secret `
    -MigratorPassword $secret `
    -ExpectedSourceRevision '20260722_0001' `
    -TargetRevision '20260729_0001' `
    -ForwardReplayAction $forwardReplayAction
if (
    $restore.State -cne 'isolated_restore_verified' -or
    $restore.Reused -or
    $restore.OriginalCopies -ne 1 -or
    $restore.RestoreDatabaseState -cne 'cleaned' -or
    -not [IO.File]::Exists($paths.RestoreEvidencePath) -or
    [IO.File]::Exists($paths.RestoreCreateIntentPath) -or
    $script:forwardReplayCalls -ne 1
) {{
    throw 'isolated restore did not verify DB and asset inventory'
}}
$cleanupCallsAfterVerification = $script:restoreCleanupCalls
$reusedRestore = Test-TicketboxC07RecoveryGenerationRestore `
    -DataRoot '{_ps_literal(data_root)}' `
    -LifecycleLock ([pscustomobject]@{{}}) `
    -SuperuserPassword $secret `
    -MigratorPassword $secret `
    -ExpectedSourceRevision '20260722_0001' `
    -TargetRevision '20260729_0001' `
    -ForwardReplayAction $forwardReplayAction
if (
    -not $reusedRestore.Reused -or
    $script:restoreCleanupCalls -ne $cleanupCallsAfterVerification -or
    $script:forwardReplayCalls -ne 1
) {{
    throw 'durable isolated restore evidence was not idempotently reused'
}}
$authority.Receipt.stage_sequence = [int64]3
$authority.Receipt.stage = 'isolated_restore_verified'
$authority.Receipt.previous_stage = 'recovery_generation_ready'
$isolatedStageReplay = Test-TicketboxC07RecoveryGenerationRestore `
    -DataRoot '{_ps_literal(data_root)}' `
    -LifecycleLock ([pscustomobject]@{{}}) `
    -SuperuserPassword $secret `
    -MigratorPassword $secret `
    -ExpectedSourceRevision '20260722_0001' `
    -TargetRevision '20260729_0001' `
    -ForwardReplayAction $forwardReplayAction
if (
    -not $isolatedStageReplay.Reused -or
    $isolatedStageReplay.EvidenceSha256 -cne $reusedRestore.EvidenceSha256 -or
    $script:restoreCleanupCalls -ne $cleanupCallsAfterVerification -or
    $script:forwardReplayCalls -ne 1
) {{
    throw (
        'isolated_restore_verified did not read-compare-reuse durable evidence'
    )
}}
$authority.Receipt.stage = 'ddl_started'
$authority.Receipt.stage_sequence = [int64]4
$authority.Receipt.previous_stage = 'isolated_restore_verified'
$wrongStageCleanupCalls = $script:restoreCleanupCalls
$wrongStageForwardCalls = $script:forwardReplayCalls
$wrongStageRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $wrongStageRejected = $true }}
if (
    -not $wrongStageRejected -or
    $script:restoreCleanupCalls -ne $wrongStageCleanupCalls -or
    $script:forwardReplayCalls -ne $wrongStageForwardCalls
) {{
    throw 'restore replay did not fail closed at ddl_started'
}}
$production = Read-TicketboxC07ProductionRecoveryGeneration `
    -DataRoot '{_ps_literal(data_root)}' `
    -LifecycleLock ([pscustomobject]@{{}}) `
    -SuperuserPassword $secret
if (
    $production.Schema -cne
        'ticketbox-c07-production-recovery-generation-v1' -or
    $production.Result -cne 'production_recovery_generation_verified' -or
    $production.PayloadSha256 -cne $generation.PayloadSha256 -or
    $production.StageEvidenceSha256 -cne ('9' * 64) -or
    $production.RestoreEvidence.PayloadSha256 -cne
        $reusedRestore.EvidenceSha256 -or
    $production.RestoreEvidence.Path -cne $paths.RestoreEvidencePath -or
    $production.SourceDatabaseIdentity.DatabaseOid -ne 42 -or
    $script:restoreDbExists -or
    [IO.File]::Exists($paths.RestoreIdentityPath) -or
    [IO.File]::Exists($paths.RestoreCreateIntentPath)
) {{
    throw 'production ddl_started reader did not return exact verified binding'
}}
Remove-TicketboxProtectedUtf8Artifact -Path $paths.RestoreEvidencePath
$authority.Receipt.stage = 'isolated_restore_verified'
$authority.Receipt.stage_sequence = [int64]3
$authority.Receipt.previous_stage = 'recovery_generation_ready'
$missingEvidenceCleanupCalls = $script:restoreCleanupCalls
$missingEvidenceForwardCalls = $script:forwardReplayCalls
$missingEvidenceRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $missingEvidenceRejected = $true }}
if (
    -not $missingEvidenceRejected -or
    $script:restoreCleanupCalls -ne $missingEvidenceCleanupCalls -or
    $script:forwardReplayCalls -ne $missingEvidenceForwardCalls
) {{
    throw (
        'isolated_restore_verified missing evidence restarted a write action'
    )
}}
$authority.Receipt.stage = 'recovery_generation_ready'
$authority.Receipt.stage_sequence = [int64]2
$authority.Receipt.previous_stage = 'writers_frozen'

$bad = [pscustomobject]@{{
    expense_public_id = '123e4567-e89b-42d3-a456-426614174005'
    ledger_id = 'owner'
    image_reference = 'uploads/owner/2026/07/different.png'
    image_sha256 = '{image_sha}'
    image_deleted = $false
    thumbnail_reference = 'uploads/owner/2026/07/thumbs/missing.jpg'
    thumbnail_deleted = $false
}}
$script:restoreAssets = @($bad)
$mismatchRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $mismatchRejected = $true }}
if (-not $mismatchRejected -or $script:restoreCleanupCalls -lt 2) {{
    throw 'restore mismatch did not fail closed and clean the isolated database'
}}

$script:restoreAssets = @($inventory)
$script:rejectForwardReplay = $true
$forwardRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{
    if ($_.Exception.Message -notmatch 'frozen C07 replay rejection') {{ throw }}
    $forwardRejected = $true
}}
if (
    -not $forwardRejected -or
    [IO.File]::Exists($paths.RestoreEvidencePath) -or
    $script:restoreDbExists
) {{
    throw 'isolated source published verified evidence after frozen replay rejection'
}}
$script:rejectForwardReplay = $false
$script:reportTargetObserved = $true
$targetObservedRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $targetObservedRejected = $true }}
if (
    -not $targetObservedRejected -or
    [IO.File]::Exists($paths.RestoreEvidencePath) -or
    $script:restoreDbExists
) {{
    throw 'isolated target-observed result was published as forward replay'
}}
$script:reportTargetObserved = $false
$script:mutateForwardMoneyFacts = $true
$forwardMoneyRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $forwardMoneyRejected = $true }}
if (
    -not $forwardMoneyRejected -or
    [IO.File]::Exists($paths.RestoreEvidencePath) -or
    $script:restoreDbExists
) {{
    throw 'restore/replay money-facts drift was published as verified evidence'
}}
$script:mutateForwardMoneyFacts = $false
$script:mutateAssetsAfterReplay = $true
$postReplayMutationRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $postReplayMutationRejected = $true }}
if (
    -not $postReplayMutationRejected -or
    [IO.File]::Exists($paths.RestoreEvidencePath) -or
    $script:restoreDbExists
) {{
    throw 'post-replay asset mutation was published as verified evidence'
}}
$script:mutateAssetsAfterReplay = $false
$script:cleanupState = 'cleanup_pending'
$cleanupRejected = $false
try {{
    Test-TicketboxC07RecoveryGenerationRestore `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock ([pscustomobject]@{{}}) `
        -SuperuserPassword $secret `
        -MigratorPassword $secret `
        -ExpectedSourceRevision '20260722_0001' `
        -TargetRevision '20260729_0001' `
        -ForwardReplayAction $forwardReplayAction | Out-Null
}}
catch {{ $cleanupRejected = $true }}
if (
    -not $cleanupRejected -or
    -not [IO.File]::Exists($paths.RestoreIdentityPath) -or
    -not [IO.File]::Exists($paths.RestoreCreateIntentPath)
) {{
    throw 'cleanup_pending was published as isolated_restore_verified'
}}
$pendingIdentity = Read-TicketboxC07RecoveryRestoreIdentityArtifact `
    -Context $context `
    -Generation $generation
if (
    $pendingIdentity.State -cne 'cleanup_pending' -or
    $pendingIdentity.IdentityArtifactState -cne 'cleanup_pending' -or
    $pendingIdentity.CreateIntentState -cne 'cleanup_pending'
) {{
    throw 'cleanup_pending artifacts did not form a resumable exact pair'
}}
$script:cleanupState = 'cleaned'
$retriedCleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret
if (
    $retriedCleanup.State -cne 'cleaned' -or
    $script:restoreDbExists -or
    [IO.File]::Exists($paths.RestoreIdentityPath) -or
    [IO.File]::Exists($paths.RestoreCreateIntentPath)
) {{
    throw 'cleanup_pending retry did not converge DB and both artifacts'
}}

[IO.Directory]::CreateDirectory($paths.PartialRoot) | Out-Null
$script:forceCleanupFailure = $true
function Write-TicketboxC07RecoveryCleanupMarker {{
    param([object]$Paths, [string]$OperationId, [string]$State)
    [IO.File]::WriteAllText($Paths.CleanupPath, $State)
}}
$pending = Clear-TicketboxC07RecoveryPartialGeneration $context
if (
    $pending.State -cne 'cleanup_pending' -or
    -not [IO.Directory]::Exists($paths.PartialRoot) -or
    -not [IO.File]::Exists($paths.CleanupPath)
) {{
    throw 'interrupted partial generation did not persist cleanup_pending'
}}
"""
    _run_harness(tmp_path, "generation-restore-reentry", source, timeout=180)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell source binding")
def test_ready_generation_rejects_live_logical_generation_drift(
    tmp_path: Path,
) -> None:
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

$script:liveGeneration = '123e4567-e89b-42d3-a456-426614174002'
function Get-TicketboxC07RecoveryLiveSourceBinding {{
    return [pscustomobject]@{{
        database = 'ticketbox'
        database_oid = '42'
        cluster_system_identifier = '7123456789012345678'
        server_id = '123e4567-e89b-42d3-a456-426614174001'
        data_generation = $script:liveGeneration
        alembic_heads = @('20260722_0001')
    }}
}}
$context = [pscustomobject]@{{
    DatabaseIdentity = [pscustomobject]@{{
        DatabaseOid = [uint32]42
        ClusterSystemIdentifier = '7123456789012345678'
    }}
}}
$generation = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        database = [pscustomobject]@{{
            source_database_oid = '42'
            server_id = '123e4567-e89b-42d3-a456-426614174001'
            data_generation = '123e4567-e89b-42d3-a456-426614174002'
            alembic_heads = @('20260722_0001')
        }}
    }}
}}
$secret = New-Object Security.SecureString
foreach ($index in 1..32) {{ $secret.AppendChar('S') }}
$secret.MakeReadOnly()
Assert-TicketboxC07RecoveryLiveSourceBinding `
    -Context $context `
    -Generation $generation `
    -SuperuserPassword $secret

$script:liveGeneration = '123e4567-e89b-42d3-a456-426614174003'
$driftRejected = $false
try {{
    Assert-TicketboxC07RecoveryLiveSourceBinding `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $secret
}}
catch {{ $driftRejected = $true }}
if (-not $driftRejected) {{
    throw 'stale generation was reused after live data_generation drift'
}}
"""
    _run_harness(tmp_path, "live-generation-drift", source)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell command contract")
def test_snapshot_id_injection_is_rejected_before_native_process(
    tmp_path: Path,
) -> None:
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'

function Assert-TicketboxC07RecoverySnapshotAlive {{ param([object]$Snapshot) }}
function Test-TicketboxPathWithin {{ return $true }}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow {{ return 'Missing' }}
$script:nativeCalls = 0
function Invoke-TicketboxC07WithPlainSecret {{
    $script:nativeCalls++
    throw 'must not reach native execution'
}}
$context = [pscustomobject]@{{
    Paths = [pscustomobject]@{{ PartialRoot = 'C:\\safe' }}
}}
$snapshot = [pscustomobject]@{{
    SnapshotId = '00000003-0000001B-1 --file C:\\escape.dump'
}}
$secret = New-Object Security.SecureString
foreach ($index in 1..32) {{ $secret.AppendChar('X') }}
$secret.MakeReadOnly()
$rejected = $false
try {{
    Invoke-TicketboxC07RecoverySnapshotDump `
        -Context $context `
        -Snapshot $snapshot `
        -SuperuserPassword $secret `
        -OutputPath 'C:\\safe\\database.dump' | Out-Null
}}
catch {{ $rejected = $true }}
if (-not $rejected -or $script:nativeCalls -ne 0) {{
    throw 'snapshot/argument injection reached native execution'
}}
"""
    _run_harness(tmp_path, "snapshot-injection", source)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell command contract")
def test_dump_must_durably_flush_before_archive_validation(
    tmp_path: Path,
) -> None:
    partial = tmp_path / "partial"
    partial.mkdir()
    dump = partial / "database.dump"
    source = f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(SCRIPT)}'
. '{_ps_literal(DATABASE_SAFETY_SCRIPT)}'
Initialize-TicketboxBoundedNativeProcessMethods

$script:testHeartbeatOperation =
    [TicketboxC07DurableHeartbeatOperation]::new(
        'C:/Ticketbox/test-data',
        [pscustomobject]@{{ Kind = 'test-lock' }},
        '123e4567-e89b-42d3-a456-426614174011',
        ('A' * 64),
        ('B' * 64),
        [int64]1,
        '123e4567-e89b-42d3-a456-426614174012',
        ('C' * 64),
        [int64]1,
        [int]$PID,
        [uint32]0,
        [uint32]1,
        [DateTime]::UtcNow.AddMinutes(2),
        [int64]120000,
        [string[]]@('SYSTEM'),
        'SYSTEM',
        [string[]]@('SYSTEM'),
        'SYSTEM',
        'C:/Ticketbox/installer-lifecycle.lock',
        'C:/Ticketbox/installer-lifecycle-operation.lock'
    )
function Get-TicketboxC07RecoveryHeartbeatOperation {{
    param([object]$Context)
    return $script:testHeartbeatOperation
}}

function Assert-TicketboxC07RecoverySnapshotAlive {{ param([object]$Snapshot) }}
function Test-TicketboxPathWithin {{ return $true }}
function Assert-NoTicketboxAncestorReparsePoints {{ param([string]$Path) }}
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) {{ return 'File' }}
    return 'Missing'
}}
function Invoke-TicketboxC07WithPlainSecret {{
    param([Security.SecureString]$Secret, [scriptblock]$Action)
    return & $Action 'plain-secret'
}}
function Invoke-TicketboxWithPgPassFile {{
    param([string]$DatabaseUrl, [string]$Password, [scriptblock]$Action)
    return & $Action 'postgresql://protected'
}}
$script:listCalls = 0
function Invoke-TicketboxBoundedNativeProcess {{
    param(
        [string]$FilePath,
        [object[]]$Arguments,
        [int]$TimeoutMilliseconds,
        [string]$Label,
        [AllowNull()][object]$HeartbeatOperation
    )
    if (
        $HeartbeatOperation.GetType().FullName -cne
            'TicketboxC07DurableHeartbeatOperation'
    ) {{
        throw 'recovery generation did not pass the typed heartbeat operation'
    }}
    if ($FilePath -ceq 'pg_dump.exe') {{
        $fileIndex = [Array]::IndexOf($Arguments, '--file')
        [IO.File]::WriteAllBytes(
            [string]$Arguments[$fileIndex + 1],
            [byte[]](1, 2, 3)
        )
        return [pscustomobject]@{{ ExitCode = 0; StandardOutput = '' }}
    }}
    $script:listCalls++
    return [pscustomobject]@{{ ExitCode = 0; StandardOutput = 'archive list' }}
}}
function Sync-TicketboxDurableArtifactFile {{
    param([string]$Path)
    throw 'injected FlushFileBuffers failure'
}}
function Protect-TicketboxC07RecoveryFile {{ param([string]$Path) }}

$context = [pscustomobject]@{{
    Paths = [pscustomobject]@{{ PartialRoot = '{_ps_literal(partial)}' }}
    DatabaseUrl = 'postgresql://source'
    PgDumpPath = 'pg_dump.exe'
    PgRestorePath = 'pg_restore.exe'
}}
$snapshot = [pscustomobject]@{{ SnapshotId = '00000003-0000001B-1' }}
$secret = New-Object Security.SecureString
foreach ($index in 1..32) {{ $secret.AppendChar('X') }}
$secret.MakeReadOnly()
if (Test-Path -LiteralPath '{_ps_literal(dump)}') {{
    Remove-Item -LiteralPath '{_ps_literal(dump)}' -Force
}}
$rejected = $false
try {{
    Invoke-TicketboxC07RecoverySnapshotDump `
        -Context $context `
        -Snapshot $snapshot `
        -SuperuserPassword $secret `
        -OutputPath '{_ps_literal(dump)}' | Out-Null
}}
catch {{
    if ($_.Exception.Message -notmatch 'FlushFileBuffers failure') {{ throw }}
    $rejected = $true
}}
if (-not $rejected -or $script:listCalls -ne 0) {{
    throw 'undurable database.dump reached archive validation/evidence'
}}
"""
    _run_harness(tmp_path, "dump-durable-flush", source)
