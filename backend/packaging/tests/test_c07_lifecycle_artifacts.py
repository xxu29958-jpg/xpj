from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
SUBJECT_SHA256 = "A" * 64
LOWER_SUBJECT_SHA256 = "a" * 64


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _write_manifest(path: Path, version: str = "7.8.9") -> None:
    install_dir = path.parent.parent
    helper = (
        install_dir
        / "program"
        / "ticketbox-backend"
        / "ticketbox-c07-migrator.exe"
    )
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper_bytes = b"ticketbox-c07-test-migrator\n"
    helper.write_bytes(helper_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "artifact_type": "ticketbox-windows-installer-inputs",
                "build_mode": "installer-build",
                "backend": {
                    "version": version,
                    "c07_migration_helper": {
                        "path": "ticketbox-c07-migrator.exe",
                        "size": len(helper_bytes),
                        "sha256": hashlib.sha256(helper_bytes).hexdigest(),
                    },
                },
                "postgresql": {"major": 17},
                "compiler_defines": ["/DTargetPgMajor=17"],
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def test_c07_writer_fence_commits_all_effective_writer_authorities() -> None:
    source = (PACKAGING / "windows_c07_lifecycle.ps1").read_text(
        encoding="utf-8-sig"
    )
    database_source = (PACKAGING / "windows_c07_database.ps1").read_text(
        encoding="utf-8-sig"
    )

    for required in (
        "pg_try_advisory_lock(",
        "SELECT pg_stat_clear_snapshot();",
        "has_database_privilege(",
        "has_schema_privilege(",
        "has_table_privilege(",
        "has_sequence_privilege(",
        "pg_has_role(",
        "current_setting('max_prepared_transactions')",
        "FROM pg_prepared_xacts",
        "FROM pg_subscription",
        "logical replication worker",
        "unexpected_database_worker_count",
        "inert_unregistered",
        "can_assume_write_owner",
    ):
        assert required in source
    assert '"--quiet",' in database_source
    assert "pg_terminate_backend(\n        pid," in source
    assert "$terminationConfirmationTimeoutMilliseconds" in source


def test_c07_whole_operation_deadline_is_monotonic_and_durable() -> None:
    source = (PACKAGING / "windows_c07_lifecycle.ps1").read_text(
        encoding="utf-8-sig"
    )

    for required in (
        "ticketbox-c07-operation-descriptor-v5",
        "ticketbox-c07-heartbeat-v4",
        "ticketbox-c07-maintenance-attempt-v2",
        "maintenance_attempt_sha256",
        "maintenance_window_ms",
        "captured_tick_count64",
        "captured_boot_identity",
        "captured_at_utc",
        "[Environment]::TickCount64",
        "Win32_OperatingSystem",
        "maintenance_remaining_ceiling_ms",
        "Get-TicketboxC07RemainingMaintenanceMilliseconds",
        "Get-TicketboxC07BoundedMigratorValidUntilUtc",
    ):
        assert required in source

    assert "$currentTick -lt $capturedTick" in source
    assert "$remainingCeiling = [Math]::Min(" in source
    assert "$requestedUtc -lt $operationDeadlineUtc" in source


def _common_harness(
    root: Path,
    *,
    pending_operation_id: str | None = None,
) -> tuple[str, Path, Path, Path]:
    data_root = root / "data"
    install_dir = root / "program"
    lock_root = root / "machine"
    data_root.mkdir(parents=True, exist_ok=True)
    install_dir.mkdir(exist_ok=True)
    manifest = install_dir / "installer" / "BUILD_PROVENANCE.json"
    if not manifest.exists():
        _write_manifest(manifest)
    if pending_operation_id is None:
        identity_setup = f"""
$identityPath = Get-TicketboxPersistentInstallationIdentityPath '{_literal(data_root)}'
if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {{
    Write-TicketboxPersistentInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}' | Out-Null
}}
else {{
    Read-TicketboxPersistentInstallationIdentity '{_literal(data_root)}' |
        Out-Null
}}
"""
    else:
        canonical_operation_id = str(uuid.UUID(pending_operation_id))
        identity_setup = f"""
$pendingIdentityPath =
    Get-TicketboxPendingInstallationIdentityPath '{_literal(data_root)}'
if (-not (Test-Path -LiteralPath $pendingIdentityPath -PathType Leaf)) {{
    Initialize-TicketboxPendingInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}' `
        -ExpectedOperationId '{canonical_operation_id}' | Out-Null
}}
else {{
    $pendingIdentity = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -Pending
    if ($pendingIdentity.OperationId -cne '{canonical_operation_id}') {{
        throw 'test PENDING installation operation changed across restart'
    }}
}}
"""
    prefix = f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_lifecycle_lock.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxPersistentInstallationIdentityAclAccounts = @($currentAccount)
$script:TicketboxPersistentInstallationIdentityOwnerAccount = $currentAccount
$script:TicketboxC07HostFullControlAccounts = @($currentAccount)
$script:TicketboxC07HostOwnerAccount = $currentAccount
$script:testLockRoot = '{_literal(lock_root)}'
$script:testDatabaseHead = '20260722_0001'
$script:testDatabaseFingerprint = '{'D' * 64}'
$script:testDatabaseOid = [uint32]42
$script:testProductionMarker = ''
$script:testServiceState = 'stopped'
$script:testServiceStartPolicy = 'delayed_auto'
$script:testServicePid = 0
$script:testListenerPids = @()
$script:testRuntimePids = @()
$script:testDatabaseSessions = 0
$script:testPublicConnect = $true
function New-TestC07DatabaseAuthorityRole {{
    return [pscustomobject][ordered]@{{
        name = 'postgres'
        oid = [int64]900
        disposition = 'database_authority'
        can_login = $true
        connection_limit = -1
        is_superuser = $true
        can_create_db = $true
        can_create_role = $true
        can_replicate = $true
        can_bypass_rls = $true
        is_database_owner = $false
        owns_public_schema = $false
        owns_user_relations = $false
        direct_connect = $false
        effective_connect = $true
        can_database_create = $true
        can_public_schema_create = $true
        can_table_write = $true
        can_sequence_write = $true
        can_assume_write_owner = $true
    }}
}}
function New-TestC07RuntimeRole {{
    param(
        [bool]$CanLogin,
        [int]$ConnectionLimit,
        [bool]$EffectiveConnect
    )
    return [pscustomobject][ordered]@{{
        name = 'ticketbox'
        oid = [int64]901
        disposition = 'fenced_runtime'
        can_login = $CanLogin
        connection_limit = $ConnectionLimit
        is_superuser = $false
        can_create_db = $false
        can_create_role = $false
        can_replicate = $false
        can_bypass_rls = $false
        is_database_owner = $false
        owns_public_schema = $false
        owns_user_relations = $false
        direct_connect = $false
        effective_connect = $EffectiveConnect
        can_database_create = $false
        can_public_schema_create = $false
        can_table_write = $true
        can_sequence_write = $true
        can_assume_write_owner = $false
    }}
}}
function Set-TestC07FenceRolesFenced {{
    $script:testFenceRoles = @(
        New-TestC07DatabaseAuthorityRole
        New-TestC07RuntimeRole `
            -CanLogin $false `
            -ConnectionLimit 0 `
            -EffectiveConnect $false
    )
}}
$script:testFenceRoles = @(
    New-TestC07DatabaseAuthorityRole
    New-TestC07RuntimeRole `
        -CanLogin $true `
        -ConnectionLimit -1 `
        -EffectiveConnect $true
)
$script:testFenceAvailable = $true
$script:testPassword = New-Object Security.SecureString
1..32 | ForEach-Object {{ $script:testPassword.AppendChar('x') }}
$script:testPassword.MakeReadOnly()
function Get-TicketboxLifecycleLockPath {{
    Initialize-TicketboxLifecycleLockDirectory `
        -LockDirectory $script:testLockRoot `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
    return Join-Path $script:testLockRoot 'installer-lifecycle.lock'
}}
function Get-TicketboxC07RuntimeReadAccount {{
    param($ReleaseIdentity)
    return 'BUILTIN\\Users'
}}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'test' }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
function Invoke-TicketboxC07Sql {{ throw 'unit harness must not invoke psql' }}
function Get-TicketboxC07DatabaseIdentity {{
    return [pscustomobject]@{{ ClusterSystemIdentifier = '7123456789012345678'; DatabaseOid = 42 }}
}}
function Get-TicketboxC07LiveDatabaseAuthority {{
    param($ReleaseIdentity)
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-live-database-authority-v1'
        ClusterSystemIdentifier = '7123456789012345678'
        DatabaseName = 'ticketbox'
        DatabaseOid = [uint32]$script:testDatabaseOid
        ServerVersionNum = 170010
        ServerId = '123e4567-e89b-42d3-a456-426614174000'
        DataGeneration = '123e4567-e89b-42d3-a456-426614174001'
        AlembicHeads = @($script:testDatabaseHead)
        Fingerprint = $script:testDatabaseFingerprint
        ProductionMarker = $script:testProductionMarker
        ProductionMarkerSha256 = if (
            [string]::IsNullOrEmpty($script:testProductionMarker)
        ) {{ '' }} else {{
            Get-TicketboxC07TextSha256 $script:testProductionMarker
        }}
    }}
}}
function Get-TicketboxC07WriterDatabaseFenceObservation {{
    param($ReleaseIdentity)
    $sessions = @(
        for ($index = 0; $index -lt $script:testDatabaseSessions; $index++) {{
            [pscustomobject][ordered]@{{
                pid = 7000 + $index
                role = 'ticketbox'
                application_name = 'test-writer'
                state = 'idle'
            }}
        }}
    )
    return [pscustomobject]@{{
        PublicConnect = [bool]$script:testPublicConnect
        OtherClientSessionCount = [int]$script:testDatabaseSessions
        ClientSessions = @($sessions)
        MaxPreparedTransactions = [int64]0
        PreparedTransactionCount = [int64]0
        LogicalSubscriptionCount = [int64]0
        LogicalApplyWorkerCount = [int64]0
        UnexpectedDatabaseWorkerCount = [int64]0
        AdvisoryFenceAvailable = [bool]$script:testFenceAvailable
        AdvisoryFenceReleased = [bool]$script:testFenceAvailable
        Roles = @($script:testFenceRoles)
    }}
}}
function Enter-TicketboxC07WriterDatabaseFence {{
    param($Authority, $Intent)
    if (-not [bool]$script:testFenceAvailable) {{
        throw 'test advisory fence unavailable'
    }}
    $script:testDatabaseSessions = 0
    $script:testPublicConnect = $false
    Set-TestC07FenceRolesFenced
    $observation = Get-TicketboxC07WriterDatabaseFenceObservation $Authority.ReleaseIdentity
    Assert-TicketboxC07WriterDatabaseFence `
        -Observation $observation `
        -ExpectedRoles @($Intent.Payload.roles)
    return $observation
}}
function Get-TicketboxServiceState {{ param($Name); return $script:testServiceState }}
function Get-TicketboxServiceStartPolicy {{
    param($Name)
    return $script:testServiceStartPolicy
}}
function Get-TicketboxServiceProcessId {{ param($Name); return [int]$script:testServicePid }}
function Get-TicketboxListeningProcessIds {{ param($Port); return @($script:testListenerPids) }}
function Get-TicketboxExpectedRuntimeProcessIds {{
    param($ExpectedExecutables)
    return @($script:testRuntimePids)
}}
function Disable-TicketboxOwnedServiceIfExists {{
    param(
        $Name,
        $ExpectedExecutable,
        $TimeoutMilliseconds,
        $PollMilliseconds,
        $BackendPort,
        $ExpectedRuntimeExecutables
    )
    $script:testServiceState = 'stopped'
    $script:testServiceStartPolicy = 'disabled'
    $script:testServicePid = 0
}}
function New-TestC07ProducerEvidence {{
    param([string]$Stage, [object]$Authority)
    $contracts = @{{
        recovery_generation_ready = @(
            'ticketbox-c07-recovery-generation-v3',
            'generation_ready'
        )
        isolated_restore_verified = @(
            'ticketbox-c07-isolated-restore-evidence-v2',
            'isolated_restore_reconciled'
        )
        ddl_started = @('ticketbox-c07-ddl-start-evidence-v1', 'ddl_started')
        target_committed = @(
            'ticketbox-c07-target-commit-evidence-v1',
            'target_committed'
        )
        target_recovery_generation_ready = @(
            'ticketbox-c07-target-recovery-generation-v2',
            'target_generation_ready'
        )
        target_isolated_restore_verified = @(
            'ticketbox-c07-target-isolated-restore-evidence-v1',
            'target_isolated_restore_verified'
        )
        runtime_acl_verified = @(
            'ticketbox-c07-runtime-acl-evidence-v1',
            'runtime_acl_verified'
        )
        ready = @('ticketbox-c07-ready-evidence-v1', 'ready')
    }}
    $contract = $contracts[$Stage]
    $subjectSha256 = '{SUBJECT_SHA256}'
    if ($Stage -in @('runtime_acl_verified', 'ready')) {{
        $production = Read-TicketboxC07ProductionAuthority $Authority
        $subjectSha256 = [string]$production.PayloadSha256
    }}
    $producer = [ordered]@{{
        schema = $contract[0]
        operation_id = [string]$Authority.Receipt.operation_id
        result = $contract[1]
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        operation_kind = [string]$Authority.Descriptor.Payload.operation_kind
        alembic_target = '20260729_0001'
        revision_manifest_sha256 =
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256
        subject_sha256 = $subjectSha256
    }}
    if ($Stage -ceq 'target_committed') {{
        $producer.migration_evidence_sha256 = '{SUBJECT_SHA256}'
        $producer.resource_shape_sha256 = '{SUBJECT_SHA256}'
        $producer.money_facts_sha256 = '{SUBJECT_SHA256}'
        $producer.statistics_table_count = 18
        $producer.statistics_table_set_sha256 = '{SUBJECT_SHA256}'
    }}
    return [pscustomobject]$producer
}}
function New-TestC07ProductionAuthority {{
    param([object]$Authority)
    $generation = Read-TicketboxC07StageEvidence `
        -Authority $Authority `
        -Stage target_recovery_generation_ready
    $restore = Read-TicketboxC07StageEvidence `
        -Authority $Authority `
        -Stage target_isolated_restore_verified
    $heartbeat = Read-TicketboxC07Heartbeat $Authority
    $result = [pscustomobject][ordered]@{{
        schema = 'ticketbox-c07-production-authority-result-v2'
        operation_id = [string]$Authority.Receipt.operation_id
        mode = 'fresh_install'
        result = 'production_authority_ready'
        recovery_manifest_sha256 = '{LOWER_SUBJECT_SHA256}'
        recovery_dump_sha256 = '{LOWER_SUBJECT_SHA256}'
        recovery_inventory_sha256 = '{LOWER_SUBJECT_SHA256}'
        recovery_copies_sha256 = '{LOWER_SUBJECT_SHA256}'
        integrity_scope = 'acl_hash_only'
        cluster_system_identifier =
            [string]$Authority.Descriptor.Payload.cluster_system_identifier
        database_oid = [string]$Authority.Descriptor.Payload.database_oid
        logical_server_id =
            [string]$Authority.Descriptor.Payload.logical_server_id
        data_generation = [string]$Authority.Descriptor.Payload.data_generation
        source_alembic_revision =
            [string]$Authority.Descriptor.Payload.source_alembic_revision
        target_alembic_revision = '20260729_0001'
        migration_evidence_sha256 = '{LOWER_SUBJECT_SHA256}'
        money_facts_sha256 = '{LOWER_SUBJECT_SHA256}'
        role_authority_sha256 = '{LOWER_SUBJECT_SHA256}'
        runtime_acl_sha256 = '{LOWER_SUBJECT_SHA256}'
        legacy_session_count = 0
        migrator_session_count = 0
        migrator_can_login = $false
        migrator_password_present = $false
        live_postconditions_sha256 = '{LOWER_SUBJECT_SHA256}'
        resource_shape_sha256 = '{LOWER_SUBJECT_SHA256}'
        target_restore_evidence_sha256 = '{LOWER_SUBJECT_SHA256}'
    }}
    $resultJson = ConvertTo-TicketboxC07CompactJson $result
    $payload = [ordered]@{{
        schema = 'ticketbox-c07-production-lifecycle-authority-v4'
        operation_id = [string]$Authority.Receipt.operation_id
        mode = 'fresh_install'
        result = 'production_authority_ready'
        release_fingerprint = [string]$Authority.Receipt.release_fingerprint
        migration_helper_relative_path =
            [string]$Authority.ReleaseIdentity.MigrationHelperRelativePath
        migration_helper_size =
            [int64]$Authority.ReleaseIdentity.MigrationHelperSize
        migration_helper_sha256 =
            [string]$Authority.ReleaseIdentity.MigrationHelperSha256
        database_binding_sha256 =
            [string]$Authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$Authority.Receipt.recovery_epoch_id
        operation_kind = [string]$Authority.Descriptor.Payload.operation_kind
        source_alembic_revision =
            [string]$Authority.Descriptor.Payload.source_alembic_revision
        target_alembic_revision =
            [string]$Authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256
        predecessor_operation_id =
            [string]$Authority.Descriptor.Payload.predecessor_operation_id
        predecessor_production_authority_sha256 =
            [string]$Authority.Descriptor.Payload.predecessor_production_authority_sha256
        target_recovery_manifest_sha256 = '{SUBJECT_SHA256}'
        target_restore_evidence_sha256 = '{SUBJECT_SHA256}'
        money_facts_sha256 = '{SUBJECT_SHA256}'
        resource_shape_sha256 = '{SUBJECT_SHA256}'
        root_authority_chain_sha256 =
            [string]$generation.Payload.source_authority_chain_sha256
        target_restore_authority_chain_sha256 =
            [string]$Authority.Receipt.authority_chain_sha256
        target_restore_stage_evidence_sha256 =
            [string]$restore.PayloadSha256
        target_restore_stage_sequence = [int64]7
        coordinator_binding_sha256 = $Authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$Authority.Binding.Sequence
        heartbeat_sequence = [int64]$heartbeat.Payload.sequence
        freeze_proof_sha256 = [string]$Authority.Receipt.freeze_proof_sha256
        coordinator_result_sha256 = Get-TicketboxC07TextSha256 $resultJson
        coordinator_result_json = $resultJson
        created_at_utc = [DateTime]::UtcNow.ToString('o')
    }}
    return Write-TicketboxC07HostEnvelope `
        -Path (
            Get-TicketboxC07ProductionAuthorityPath `
                ([string]$Authority.Receipt.operation_id)
        ) `
        -ArtifactKind production_authority `
        -Payload $payload
}}
function New-TestC07StageEvidence {{
    param([string]$Stage, [object]$LifecycleLock, [string]$DataRoot)
    $authority = Read-TicketboxC07Authority $DataRoot
    $producer = New-TestC07ProducerEvidence $Stage $authority
    return New-TicketboxC07StageEvidence `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -TargetStage $Stage `
        -ProducerEvidence $producer
}}
{identity_setup}
"""
    return prefix, data_root, install_dir, manifest


def _recovery_combo_support() -> str:
    return (
        r"""
. '__RECOVERY_SCRIPT__'
$script:TicketboxC07RecoveryFullControlAccounts = @($currentAccount)
$script:TicketboxC07RecoveryOwnerAccount = $currentAccount
$script:liveSourceChecks = 0

function New-TestC07RecoveryContext {
    param([object]$Authority)
    $paths = Get-TicketboxC07RecoveryPaths $Authority
    return [pscustomobject]@{
        Authority = $Authority
        DatabaseAuthority = [pscustomobject]@{ Schema = 'test-host-authority' }
        DatabaseIdentity = [pscustomobject]@{
            Exists = $true
            ClusterSystemIdentifier =
                [string]$Authority.Descriptor.Payload.cluster_system_identifier
            DatabaseOid = [uint32]$Authority.Descriptor.Payload.database_oid
        }
        DatabaseUrl = 'test-only'
        PgDumpPath = 'pg_dump.exe'
        PgRestorePath = 'pg_restore.exe'
        UploadRoot = Join-Path $Authority.ReleaseIdentity.DataRoot 'app\uploads'
        UploadRootBindingSha256 = ('a' * 64)
        Paths = $paths
    }
}

function Get-TicketboxC07RestoreDatabaseName {
    param([string]$OperationId, [string]$CreateAttemptId)
    return 'ticketbox_c07_restore_dddddddddddddddddddddddddddddddddddddddd'
}

function Get-TicketboxC07RestoreNamespaceDatabases {
    param($Authority, $SuperuserPassword)
    return @()
}

function Get-TicketboxC07RecoveryContext {
    param(
        [string]$DataRoot,
        [object]$LifecycleLock,
        [object]$SuperuserPassword,
        [string[]]$AllowedStages = @('writers_frozen')
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    if ([string]$authority.Receipt.stage -cnotin $AllowedStages) {
        throw 'combined recovery context rejected unsupported stage'
    }
    return New-TestC07RecoveryContext $authority
}

function Assert-TicketboxC07RecoveryLiveSourceBinding {
    param($Context, $Generation, $SuperuserPassword)
    $script:liveSourceChecks += 1
    if (
        [string]$Generation.Payload.database.cluster_system_identifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$Generation.Payload.database.source_database_oid -cne
            [string]$Context.DatabaseIdentity.DatabaseOid
    ) {
        throw 'combined recovery source identity drifted'
    }
}

function New-TestC07ReadyGeneration {
    param([object]$Authority)
    $context = New-TestC07RecoveryContext $Authority
    $paths = $context.Paths
    Initialize-TicketboxC07RecoveryGenerationRoot $paths | Out-Null
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $paths.ReadyRoot `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
    $assetsRoot = Join-Path $paths.ReadyRoot $paths.AssetsLeaf
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $assetsRoot `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null

    $dumpPath = Join-Path $paths.ReadyRoot $paths.DumpFileName
    $inventoryPath = Join-Path $paths.ReadyRoot $paths.InventoryFileName
    $copiesPath = Join-Path $paths.ReadyRoot $paths.CopiesFileName
    [IO.File]::WriteAllBytes($dumpPath, [byte[]](1))
    [IO.File]::WriteAllText(
        $inventoryPath,
        '',
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        $copiesPath,
        '',
        [Text.UTF8Encoding]::new($false)
    )
    foreach ($path in @($dumpPath, $inventoryPath, $copiesPath)) {
        Set-TicketboxExactFileAcl `
            -Path $path `
            -Accounts @($currentAccount) `
            -OwnerAccount $currentAccount
    }
    $emptySha256 = Get-TicketboxC07RecoveryFileSha256 $inventoryPath
    $payload = [ordered]@{
        schema = 'ticketbox-c07-recovery-generation-v3'
        operation_id = [string]$Authority.Receipt.operation_id
        generation_id = [string]$Authority.Receipt.operation_id
        release = [ordered]@{
            fingerprint = [string]$Authority.ReleaseIdentity.Fingerprint
            installation_id =
                [string]$Authority.ReleaseIdentity.InstallationId
            build_manifest_sha256 =
                [string]$Authority.ReleaseIdentity.BuildManifestSha256
            backend_version =
                [string]$Authority.ReleaseIdentity.BackendVersionFloor
        }
        lifecycle = [ordered]@{
            stage = 'writers_frozen'
            operation_kind =
                [string]$Authority.Descriptor.Payload.operation_kind
            target_alembic_revision =
                [string]$Authority.Descriptor.Payload.target_alembic_revision
            revision_manifest_sha256 =
                [string]$Authority.Descriptor.Payload.revision_manifest_sha256
            authority_chain_sha256 =
                [string]$Authority.Receipt.authority_chain_sha256
            freeze_proof_sha256 =
                [string]$Authority.Receipt.freeze_proof_sha256
            freeze_heartbeat_sequence =
                [string][int64]$Authority.Receipt.freeze_heartbeat_sequence
        }
        integrity = [ordered]@{
            scope = 'acl_hash_only'
            malicious_writer_resistance = $false
            upload_root_binding_sha256 = ('a' * 64)
        }
        barrier = [ordered]@{
            mode = 'bounded_quiesce_plus_pg_export_snapshot'
            exported_snapshot_id = '00000003-0000001B-1'
            captured_at_utc = [DateTime]::UtcNow.ToString('o')
        }
        database = [ordered]@{
            name = 'ticketbox'
            cluster_system_identifier =
                [string]$Authority.Descriptor.Payload.cluster_system_identifier
            source_database_oid =
                [string]$Authority.Descriptor.Payload.database_oid
            server_version_num = '170000'
            server_id =
                [string]$Authority.Descriptor.Payload.logical_server_id
            data_generation =
                [string]$Authority.Descriptor.Payload.data_generation
            alembic_heads = @('20260722_0001')
            dump_file = $paths.DumpFileName
            dump_sha256 = Get-TicketboxC07RecoveryFileSha256 $dumpPath
            dump_size_bytes = '1'
            restore_list_sha256 = ('6' * 64)
            money_facts_sha256 = ('7' * 64)
        }
        asset_inventory = [ordered]@{
            file = $paths.InventoryFileName
            sha256 = $emptySha256
            size_bytes = '0'
            row_count = '0'
        }
        original_copies = [ordered]@{
            file = $paths.CopiesFileName
            sha256 = $emptySha256
            size_bytes = '0'
            row_count = '0'
            asset_directory = $paths.AssetsLeaf
        }
        thumbnail_policy = [ordered]@{
            authority = 'derived_rebuildable_cache'
            copied = $false
            references_audited = $true
        }
        capacity = [ordered]@{
            schema = 'ticketbox-c07-recovery-capacity-v1'
            volume_mode = 'shared'
            database_size_bytes = '1'
            dump_estimate_bytes = '1'
            isolated_restore_estimate_bytes = '1'
            rewrite_index_estimate_bytes = '1'
            observed_wal_bytes = '1'
            wal_reserve_bytes = '1'
            asset_generation_copy_bytes = '0'
            asset_isolated_restore_bytes = '0'
            manifest_inventory_reserve_bytes = '1'
            required_with_headroom_bytes = '6'
            free_bytes_at_preflight = '10'
            headroom_percent = 20
        }
        completion = [ordered]@{
            state = 'generation_ready'
            created_by = 'windows_c07_recovery_generation'
            created_at_utc = [DateTime]::UtcNow.ToString('o')
        }
    }
    Write-TicketboxC07RecoveryManifest `
        -Root $paths.ReadyRoot `
        -Payload $payload | Out-Null
    return Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $paths.ReadyRoot
}

function New-TestC07DurableRestoreEvidence {
    param([object]$Context, [object]$Generation)
    $payload = [ordered]@{
        schema = 'ticketbox-c07-isolated-restore-evidence-v2'
        operation_id = [string]$Context.Authority.Receipt.operation_id
        operation_kind =
            [string]$Context.Authority.Descriptor.Payload.operation_kind
        target_alembic_revision =
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
        installation_id =
            [string]$Context.Authority.ReleaseIdentity.InstallationId
        generation_payload_sha256 = [string]$Generation.PayloadSha256
        source_cluster_system_identifier =
            [string]$Generation.Payload.database.cluster_system_identifier
        source_database_oid =
            [string]$Generation.Payload.database.source_database_oid
        restore_database = Get-TicketboxC07RestoreDatabaseName `
            -OperationId ([string]$Context.Authority.Receipt.operation_id) `
            -CreateAttemptId '123e4567-e89b-42d3-a456-426614174099'
        restore_database_oid = '99'
        restore_create_attempt_id = '123e4567-e89b-42d3-a456-426614174099'
        restore_create_authority_sha256 = ('a' * 64)
        logical_server_id = [string]$Generation.Payload.database.server_id
        logical_data_generation =
            [string]$Generation.Payload.database.data_generation
        asset_inventory_sha256 =
            [string]$Generation.Payload.asset_inventory.sha256
        asset_inventory_rows = '0'
        original_copies_verified = '0'
        isolated_asset_bytes = '0'
        thumbnails = 'audited_rebuildable_not_copied'
        forward_replay_source_revision = '20260722_0001'
        forward_replay_target_revision = '20260729_0001'
        forward_replay_result = 'isolated_forward_replay_verified'
        target_shape_sha256 = ('8' * 64)
        money_facts_sha256 =
            [string]$Generation.Payload.database.money_facts_sha256
        result = 'isolated_restore_reconciled'
        integrity_scope = 'acl_hash_only'
        verified_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    return Write-TicketboxC07RecoveryRestoreEvidence `
        -Context $Context `
        -Generation $Generation `
        -Payload $payload `
        -SuperuserPassword $script:testPassword
}
"""
        .replace(
            "__RECOVERY_SCRIPT__",
            _literal(PACKAGING / "windows_c07_recovery_generation.ps1"),
        )
    )


def _run_harness(
    engine: str,
    harness: Path,
    timeout: int = 50,
    *,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
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
    assert result.returncode == expected_returncode, (
        f"{engine}:\n{result.stdout}\n{result.stderr}"
    )
    return result


def _write_ps1(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_powershell_process(
    command: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    # A launched PostgreSQL process can inherit redirected pipe handles. Plain
    # files let the parent PowerShell exit without waiting for the server.
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stdout,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr,
    ):
        completed = subprocess.run(
            command,
            check=False,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
        )
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            stdout.read().lstrip("\ufeff"),
            stderr.read().lstrip("\ufeff"),
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows monotonic clock contract")
def test_c07_maintenance_budget_rejects_ceiling_reboot_and_tick_rollback(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"deadline-{index}.ps1"
        _write_ps1(
            harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
$script:testCeiling = [int64]1200000
$script:testAttemptId = '123e4567-e89b-42d3-a456-4266141740ab'
$script:testAttemptSha256 = '{SUBJECT_SHA256}'
function Get-TicketboxC07BootIdentity {{ return 'test-boot' }}
function Read-TicketboxC07Heartbeat {{
    return [pscustomobject]@{{
        Payload = [pscustomobject]@{{
            maintenance_attempt_id = $script:testAttemptId
            maintenance_attempt_sequence = [int64]1
            maintenance_attempt_sha256 = $script:testAttemptSha256
            maintenance_attempt_failure_sha256 = ''
            maintenance_remaining_ceiling_ms = $script:testCeiling
        }}
    }}
}}
$tick = [int64][Environment]::TickCount64
$script:testAttempt = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        attempt_id = $script:testAttemptId
        attempt_sequence = [int64]1
        started_tick_count64 = [Math]::Max([int64]0, $tick - 1000)
        started_boot_identity = 'test-boot'
    }}
    PayloadSha256 = $script:testAttemptSha256
    DeadlineUtc = [DateTime]::UtcNow.AddSeconds(1199)
}}
function Read-TicketboxC07MaintenanceAttempt {{
    param($Authority, $AttemptId, $Sequence, $ExpectedPayloadSha256)
    return $script:testAttempt
}}
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{ operation_id = 'operation' }}
}}
$budget = New-TicketboxC07MaintenanceBudget $authority
$bounded = Get-TicketboxC07BoundedMigratorValidUntilUtc `
    -RequestedValidUntilUtc ([DateTime]::UtcNow.AddMinutes(55)) `
    -Budget $budget
if ($bounded -gt [DateTime]$budget.DeadlineUtc) {{
    throw 'migrator credential exceeded operation deadline'
}}

$script:testCeiling = 500
$ceilingRejected = $false
try {{ New-TicketboxC07MaintenanceBudget $authority | Out-Null }}
catch {{ $ceilingRejected = $true }}
if (-not $ceilingRejected) {{ throw 'durable ceiling rollback was accepted' }}

$script:testCeiling = 1200000
$script:testAttempt.Payload.started_boot_identity = 'previous-boot'
$rebootRejected = $false
try {{ New-TicketboxC07MaintenanceBudget $authority | Out-Null }}
catch {{ $rebootRejected = $true }}
if (-not $rebootRejected) {{ throw 'rebooted operation was accepted' }}

$script:testAttempt.Payload.started_boot_identity = 'test-boot'
$script:testAttempt.Payload.started_tick_count64 =
    [int64][Environment]::TickCount64 + 10000
$tickRejected = $false
try {{ New-TicketboxC07MaintenanceBudget $authority | Out-Null }}
catch {{ $tickRejected = $true }}
if (-not $tickRejected) {{ throw 'tick rollback was accepted' }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL lifecycle contract")
def test_c07_lifecycle_uses_typed_evidence_and_reentrant_boundaries(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"flow-{index}"
        prefix, data_root, _, _ = _common_harness(root)
        harness = root / "flow.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$lifecycleLock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lifecycleLock `
        -SuperuserPassword $script:testPassword
    if ($operation.Stage -cne 'captured') {{ throw 'operation did not start captured' }}

    $skipRejected = $false
    try {{
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lifecycleLock `
            -TargetStage recovery_generation_ready `
            -EvidencePath ('A' * 64) | Out-Null
    }}
    catch {{ $skipRejected = $true }}
    if (-not $skipRejected) {{ throw 'raw hash/path skipped writers_frozen' }}

    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lifecycleLock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lifecycleLock `
        -TargetStage writers_frozen | Out-Null
    $frozenReplay = Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lifecycleLock `
        -TargetStage writers_frozen
    if (-not [bool]$frozenReplay.Reused) {{
        throw 'writers_frozen boundary was not read-compare-reused'
    }}

    foreach ($stage in @(
        'recovery_generation_ready',
        'isolated_restore_verified',
        'ddl_started',
        'target_committed',
        'target_recovery_generation_ready',
        'target_isolated_restore_verified',
        'runtime_acl_verified',
        'ready'
    )) {{
        if ($stage -ceq 'target_committed') {{
            $script:testDatabaseHead = '20260729_0001'
        }}
        if ($stage -ceq 'runtime_acl_verified') {{
            $targetAuthority = Read-TicketboxC07Authority '{_literal(data_root)}'
            New-TestC07ProductionAuthority $targetAuthority | Out-Null
        }}
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lifecycleLock `
            -DataRoot '{_literal(data_root)}'
        $advanced = Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lifecycleLock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path
        $reused = Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lifecycleLock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path
        if ([bool]$advanced.Reused -or -not [bool]$reused.Reused) {{
            throw "stage $stage did not provide exact idempotent boundary"
        }}
    }}
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $projection = Read-TicketboxC07RuntimeProjection '{_literal(data_root)}'
    if ($authority.Receipt.stage -cne 'ready' -or
        [int64]$authority.Receipt.stage_sequence -ne 9 -or
        -not [bool]$projection.Payload.ready -or
        -not [bool]$projection.Payload.terminal) {{
        throw 'ready authority/projection did not converge'
    }}
    Assert-TicketboxExactFileAcl `
        -Path (Get-TicketboxC07AuthorityPath) `
        -Accounts @($currentAccount) `
        -OwnerAccount $currentAccount
    Assert-TicketboxExactFileAcl `
        -Path (Get-TicketboxC07ProjectionPath) `
        -Accounts @($currentAccount) `
        -ReadExecuteAccounts @('BUILTIN\\Users') `
        -OwnerAccount $currentAccount
    if (@(Get-ChildItem -LiteralPath $script:testLockRoot -Recurse -Force |
        Where-Object {{ $_.Name -match '^\\.ticketbox-(protected|durable)-.*\\.tmp$' }}).Count -ne 0) {{
        throw 'durable publication left a staging artifact'
    }}
    $script:testDatabaseOid = [uint32]43
    $cloneRejected = $false
    try {{ Read-TicketboxC07Authority '{_literal(data_root)}' | Out-Null }}
    catch {{ $cloneRejected = $true }}
    if (-not $cloneRejected) {{ throw 'same-path cloned database revived stale READY' }}
    $script:testDatabaseOid = [uint32]42
    $script:testDatabaseFingerprint = ('E' * 64)
    $staleReadyRejected = $false
    try {{ Read-TicketboxC07Authority '{_literal(data_root)}' | Out-Null }}
    catch {{ $staleReadyRejected = $true }}
    if (-not $staleReadyRejected) {{ throw 'stale READY survived live database change' }}
}}
finally {{ Exit-TicketboxLifecycleLock $lifecycleLock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows production authority")
def test_c07_production_coordinator_is_unique_stage_authority(tmp_path: Path) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "production"
    prefix, data_root, _, _ = _common_harness(root)
    harness = root / "production.ps1"
    _write_ps1(
        harness,
        prefix
        + f"""
$script:testProductionDataRoot = '{_literal(data_root)}'
$script:precommittedValidationCalls = 0
function Get-TicketboxC07RecoveryPaths {{
    param($Authority)
    $generationRoot = Join-Path $Authority.Roots.HostRoot 'recovery-generations'
    $ready = Join-Path $generationRoot (
        'operation-' + [string]$Authority.Receipt.operation_id + '.ready'
    )
    return [pscustomobject]@{{
        ReadyRoot = $ready
        ManifestFileName = 'manifest.json'
    }}
}}
function Read-TicketboxC07ProductionRecoveryGeneration {{
    param($DataRoot, $LifecycleLock, $SuperuserPassword)
    $authority = Read-TicketboxC07Authority $DataRoot
    $generation = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage recovery_generation_ready
    $restore = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage isolated_restore_verified
    $paths = Get-TicketboxC07RecoveryPaths $authority
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-production-recovery-generation-v1'
        OperationId = [string]$authority.Receipt.operation_id
        Result = 'production_recovery_generation_verified'
        Payload = [pscustomobject]@{{
            schema = 'ticketbox-c07-recovery-generation-v3'
            operation_id = [string]$authority.Receipt.operation_id
            release = [pscustomobject]@{{
                fingerprint = [string]$authority.Receipt.release_fingerprint
                installation_id =
                    [string]$authority.ReleaseIdentity.InstallationId
                build_manifest_sha256 =
                    [string]$authority.ReleaseIdentity.BuildManifestSha256
                backend_version =
                    [string]$authority.ReleaseIdentity.BackendVersionFloor
            }}
                lifecycle = [pscustomobject]@{{
                stage = 'writers_frozen'
                operation_kind =
                    [string]$authority.Descriptor.Payload.operation_kind
                target_alembic_revision =
                    [string]$authority.Descriptor.Payload.target_alembic_revision
                revision_manifest_sha256 =
                    [string]$authority.Descriptor.Payload.revision_manifest_sha256
                authority_chain_sha256 =
                    [string]$generation.Payload.source_authority_chain_sha256
                    freeze_proof_sha256 =
                        [string]$authority.Receipt.freeze_proof_sha256
                }}
                integrity = [pscustomobject]@{{
                    upload_root_binding_sha256 = ('a' * 64)
                }}
            }}
        PayloadSha256 = '{LOWER_SUBJECT_SHA256}'
        ManifestPath = Join-Path $paths.ReadyRoot $paths.ManifestFileName
        DumpPath = Join-Path $paths.ReadyRoot 'database.dump'
        InventoryPath = Join-Path $paths.ReadyRoot 'asset-inventory.jsonl'
        CopiesPath = Join-Path $paths.ReadyRoot 'asset-copies.jsonl'
        Root = $paths.ReadyRoot
        LifecycleAuthorityChainSha256 =
            [string]$generation.Payload.source_authority_chain_sha256
        StageEvidenceSha256 = $generation.PayloadSha256
        SourceDatabaseIdentity = [pscustomobject]@{{
            Database = 'ticketbox'
            ClusterSystemIdentifier =
                [string]$authority.Descriptor.Payload.cluster_system_identifier
            DatabaseOid = [uint32]$authority.Descriptor.Payload.database_oid
            GenerationPayloadSha256 = '{LOWER_SUBJECT_SHA256}'
        }}
        RestoreEvidence = [pscustomobject]@{{
            Payload = [pscustomobject]@{{ result = 'isolated_restore_reconciled' }}
            PayloadSha256 = '{LOWER_SUBJECT_SHA256}'
            Path = Join-Path $paths.ReadyRoot 'isolated-restore-evidence.json'
        }}
    }}
}}
function Read-TicketboxC07ProductionTargetRecoveryGeneration {{
    param($DataRoot, $LifecycleLock, $SuperuserPassword)
    $authority = Read-TicketboxC07Authority $DataRoot
    $generation = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage target_recovery_generation_ready
    $restore = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage target_isolated_restore_verified
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-production-target-recovery-generation-v1'
        OperationId = [string]$authority.Receipt.operation_id
        Result = 'production_target_recovery_generation_verified'
        Payload = [pscustomobject]@{{
            schema = 'ticketbox-c07-target-recovery-generation-v2'
            operation_id = [string]$authority.Receipt.operation_id
        }}
        PayloadSha256 = '{LOWER_SUBJECT_SHA256}'
        ManifestPath = 'target-manifest.json'
        DumpPath = 'target-database.dump'
        InventoryPath = 'target-asset-inventory.jsonl'
        CopiesPath = 'target-asset-copies.jsonl'
        Root = 'target-ready'
        LifecycleAuthorityChainSha256 =
            [string]$generation.Payload.source_authority_chain_sha256
        TargetCommitStageEvidenceSha256 =
            [string]$generation.PayloadSha256
        RestoreEvidence = [pscustomobject]@{{
            Payload = [pscustomobject]@{{
                result = 'target_isolated_restore_verified'
            }}
            PayloadSha256 = '{LOWER_SUBJECT_SHA256}'
            Path = 'target-isolated-restore-evidence.json'
        }}
    }}
}}
function Invoke-TicketboxC07ProductionAuthorityCoordinator {{
    param(
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        $MigratorValidUntilUtc,
        $OperationId,
        $Mode,
        $ExpectedSourceRevision,
        $TargetRevision,
        $RecoveryGeneration,
        $TargetRecoveryGeneration,
        $LifecycleAuthority,
        $MigrationAction,
        $ExpectedProductionResult,
        [switch]$StopAfterMigrationCompleted
    )
    $expectedStage = if ($StopAfterMigrationCompleted) {{
        'ddl_started'
    }} else {{
        'target_isolated_restore_verified'
    }}
    $expectedSequence = if ($StopAfterMigrationCompleted) {{
        [int64]4
    }} else {{
        [int64]7
    }}
    if ($LifecycleAuthority.current_stage -cne $expectedStage -or
        [int64]$LifecycleAuthority.current_stage_sequence -ne $expectedSequence -or
        $LifecycleAuthority.root_authority_chain_sha256 -cne
            $RecoveryGeneration.LifecycleAuthorityChainSha256 -or
        (
            -not $StopAfterMigrationCompleted -and
            $null -eq $TargetRecoveryGeneration
        )) {{
        throw 'fake coordinator received an unbound lifecycle authority'
    }}
    if ($null -ne $ExpectedProductionResult) {{
        if ($StopAfterMigrationCompleted) {{
            throw 'precommitted production validation entered DDL-only mode'
        }}
        $script:precommittedValidationCalls += 1
        return $ExpectedProductionResult
    }}
    $hostAuthority = [pscustomobject]@{{ Schema = 'test-host-authority' }}
    $migration = & $MigrationAction `
        $hostAuthority `
        $MigratorPassword `
        $ExpectedSourceRevision `
        $TargetRevision
    if (
        $migration.schema -cne 'ticketbox-c07-migration-evidence-v2' -or
        $migration.result -cne 'migration_action_bound'
    ) {{
        throw 'production migration callback did not receive typed context'
    }}
    $authority = Read-TicketboxC07Authority $script:testProductionDataRoot
    if ($StopAfterMigrationCompleted) {{
        return [pscustomobject][ordered]@{{
            schema = 'ticketbox-c07-target-commit-result-v1'
            operation_id = $OperationId
            mode = $Mode
            result = 'target_committed'
            cluster_system_identifier =
                [string]$authority.Descriptor.Payload.cluster_system_identifier
            database_oid = [string]$authority.Descriptor.Payload.database_oid
            logical_server_id =
                [string]$authority.Descriptor.Payload.logical_server_id
            data_generation =
                [string]$authority.Descriptor.Payload.data_generation
            source_alembic_revision = $ExpectedSourceRevision
            target_alembic_revision = $TargetRevision
            alembic_revision = $TargetRevision
            source_recovery_manifest_sha256 =
                [string]$RecoveryGeneration.PayloadSha256
            migration_evidence_sha256 = '{LOWER_SUBJECT_SHA256}'
            resource_shape_sha256 =
                [string]$migration.resource_shape_sha256
            money_facts_sha256 = [string]$migration.money_facts_sha256
            statistics_table_count =
                [int]$migration.statistics_table_count
            statistics_table_set_sha256 =
                [string]$migration.statistics_table_set_sha256
        }}
    }}
    return [pscustomobject][ordered]@{{
        schema = 'ticketbox-c07-production-authority-result-v2'
        operation_id = $OperationId
        mode = $Mode
        result = 'production_authority_ready'
        recovery_manifest_sha256 = $TargetRecoveryGeneration.PayloadSha256
        recovery_dump_sha256 = '{LOWER_SUBJECT_SHA256}'
        recovery_inventory_sha256 = '{LOWER_SUBJECT_SHA256}'
        recovery_copies_sha256 = '{LOWER_SUBJECT_SHA256}'
        integrity_scope = 'acl_hash_only'
        cluster_system_identifier =
            [string]$authority.Descriptor.Payload.cluster_system_identifier
        database_oid = [string]$authority.Descriptor.Payload.database_oid
        logical_server_id =
            [string]$authority.Descriptor.Payload.logical_server_id
        data_generation = [string]$authority.Descriptor.Payload.data_generation
        source_alembic_revision = $ExpectedSourceRevision
        target_alembic_revision = $TargetRevision
        migration_evidence_sha256 = '{LOWER_SUBJECT_SHA256}'
        money_facts_sha256 = '{LOWER_SUBJECT_SHA256}'
        role_authority_sha256 = '{LOWER_SUBJECT_SHA256}'
        runtime_acl_sha256 = '{LOWER_SUBJECT_SHA256}'
        legacy_session_count = 0
        migrator_session_count = 0
        migrator_can_login = $false
        migrator_password_present = $false
        live_postconditions_sha256 = '{LOWER_SUBJECT_SHA256}'
        resource_shape_sha256 = '{LOWER_SUBJECT_SHA256}'
        target_restore_evidence_sha256 =
            $TargetRecoveryGeneration.RestoreEvidence.PayloadSha256
    }}
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    foreach ($stage in @(
        'recovery_generation_ready',
        'isolated_restore_verified',
        'ddl_started'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $migrationAction = {{
        param($HostAuthority, $Password, $Source, $Target, $Context)
        Assert-TicketboxC07ExactProperties `
            $Context `
            @(
                'schema',
                'operation_id',
                'release_fingerprint',
                'migration_helper_relative_path',
                'migration_helper_size',
                 'migration_helper_sha256',
                 'database_binding_sha256',
                 'upload_root_binding_sha256',
                 'recovery_epoch_id',
                 'coordinator_binding_sha256',
                 'coordinator_binding_sequence',
                 'heartbeat_sequence',
                 'operation_kind',
                 'target_alembic_revision',
                 'revision_manifest_sha256',
                 'successor_mode',
                 'successor_intent_sha256',
                 'predecessor_operation_id',
                 'predecessor_terminal_authority_chain_sha256',
                 'source_recovery_operation_id',
                 'source_recovery_release_fingerprint',
                 'source_recovery_revision_manifest_sha256',
                 'source_recovery_freeze_proof_sha256',
                 'maintenance_deadline_utc',
                 'maintenance_remaining_ceiling_ms',
                 'maintenance_authority_sha256',
                 'writer_freeze_proof_path',
                 'writer_freeze_proof_sha256',
                 'recovery_manifest_path',
                'recovery_manifest_sha256',
                'isolated_restore_evidence_path',
                'isolated_restore_evidence_sha256',
                'lifecycle_root_authority_chain_sha256'
            ) `
            'production migration context'
        $currentAuthority = Read-TicketboxC07Authority '{_literal(data_root)}'
        $currentHeartbeat = Read-TicketboxC07Heartbeat $currentAuthority
        if ($HostAuthority.Schema -cne 'test-host-authority' -or
            $Password.Length -lt 32 -or
             $Source -cne '20260722_0001' -or
             $Target -cne '20260729_0001' -or
             $Context.schema -cne
                 'ticketbox-c07-production-migration-context-v5' -or
             $Context.release_fingerprint -cne
                 $currentAuthority.Receipt.release_fingerprint -or
            $Context.migration_helper_relative_path -cne
                $currentAuthority.ReleaseIdentity.MigrationHelperRelativePath -or
            [int64]$Context.migration_helper_size -ne
                [int64]$currentAuthority.ReleaseIdentity.MigrationHelperSize -or
            $Context.migration_helper_sha256 -cne
                $currentAuthority.ReleaseIdentity.MigrationHelperSha256 -or
             $Context.database_binding_sha256 -cne
                 $currentAuthority.Receipt.database_binding_sha256 -or
             $Context.upload_root_binding_sha256 -cne ('a' * 64) -or
             $Context.recovery_epoch_id -cne
                $currentAuthority.Receipt.recovery_epoch_id -or
            $Context.coordinator_binding_sha256 -cne
                $currentAuthority.Binding.PayloadSha256 -or
            [int64]$Context.coordinator_binding_sequence -ne
                [int64]$currentAuthority.Binding.Sequence -or
             [int64]$Context.heartbeat_sequence -ne
                 [int64]$currentHeartbeat.Payload.sequence -or
             $Context.operation_kind -cne
                 $currentAuthority.Descriptor.Payload.operation_kind -or
             $Context.target_alembic_revision -cne
                 $currentAuthority.Descriptor.Payload.target_alembic_revision -or
             $Context.revision_manifest_sha256 -cne
                 $currentAuthority.Descriptor.Payload.revision_manifest_sha256 -or
             $Context.predecessor_operation_id -cne
                  $currentAuthority.Descriptor.Payload.predecessor_operation_id -or
             $Context.predecessor_terminal_authority_chain_sha256 -cne
                 $currentAuthority.Descriptor.Payload.predecessor_terminal_authority_chain_sha256 -or
             $Context.successor_mode -cne
                 $currentAuthority.Descriptor.Payload.successor_mode -or
             $Context.successor_intent_sha256 -cne '' -or
             $Context.source_recovery_operation_id -cne
                 $currentAuthority.Receipt.operation_id -or
             $Context.source_recovery_release_fingerprint -cne
                 $currentAuthority.Receipt.release_fingerprint -or
             $Context.source_recovery_revision_manifest_sha256 -cne
                 $currentAuthority.Descriptor.Payload.revision_manifest_sha256 -or
             $Context.source_recovery_freeze_proof_sha256 -cne
                 $currentAuthority.Receipt.freeze_proof_sha256 -or
             [string]::IsNullOrEmpty(
                 [string]$Context.maintenance_deadline_utc
             ) -or
             [int]$Context.maintenance_remaining_ceiling_ms -lt 1 -or
             $Context.maintenance_authority_sha256 -cne
                 $currentHeartbeat.Payload.maintenance_attempt_sha256 -or
             $Context.writer_freeze_proof_sha256 -cne
                 $currentAuthority.Receipt.freeze_proof_sha256 -or
            $Context.recovery_manifest_sha256 -cne '{SUBJECT_SHA256}' -or
            $Context.isolated_restore_evidence_sha256 -cne
                '{SUBJECT_SHA256}') {{
            throw 'production migration context was not exact'
        }}
        return [pscustomobject][ordered]@{{
            schema = 'ticketbox-c07-migration-evidence-v1'
            operation_id = [string]$Context.operation_id
            source_revision = $Source
            target_revision = $Target
            result = 'migration_action_bound'
            alembic_revision = $Target
            money_facts_sha256 = '{LOWER_SUBJECT_SHA256}'
            statistics_table_count = 18
            statistics_table_set_sha256 = '{LOWER_SUBJECT_SHA256}'
        }}
    }}
    $targetSemanticAction = {{
        param(
            $HostAuthority,
            $Password,
            $Database,
            $OperationId,
            $SnapshotId,
            $SourceRevision,
            $TargetRevision,
            $RevisionManifestSha256,
            $MaintenanceDeadlineUtc,
            $MaintenanceRemainingCeilingMs,
            $MaintenanceAuthoritySha256
        )
        return [pscustomobject][ordered]@{{
            schema = 'ticketbox-c07-target-semantic-result-v1'
            operation_id = $OperationId
            database = $Database
            snapshot_id = $SnapshotId
            source_revision = $SourceRevision
            target_revision = $TargetRevision
            revision_manifest_sha256 =
                $RevisionManifestSha256.ToLowerInvariant()
            maintenance_authority_sha256 =
                $MaintenanceAuthoritySha256.ToLowerInvariant()
            maintenance_remaining_ceiling_ms =
                [int]$MaintenanceRemainingCeilingMs
            alembic_revision = $TargetRevision
            resource_shape_sha256 = '{LOWER_SUBJECT_SHA256}'
            money_facts_sha256 = '{LOWER_SUBJECT_SHA256}'
        }}
    }}
    $validTargetSemanticAction = $targetSemanticAction
    $badMoneySemanticAction = {{
        param(
            $HostAuthority,
            $Password,
            $Database,
            $OperationId,
            $SnapshotId,
            $SourceRevision,
            $TargetRevision,
            $RevisionManifestSha256,
            $MaintenanceDeadlineUtc,
            $MaintenanceRemainingCeilingMs,
            $MaintenanceAuthoritySha256
        )
        return [pscustomobject][ordered]@{{
            schema = 'ticketbox-c07-target-semantic-result-v1'
            operation_id = $OperationId
            database = $Database
            snapshot_id = $SnapshotId
            source_revision = $SourceRevision
            target_revision = $TargetRevision
            revision_manifest_sha256 =
                $RevisionManifestSha256.ToLowerInvariant()
            maintenance_authority_sha256 =
                $MaintenanceAuthoritySha256.ToLowerInvariant()
            maintenance_remaining_ceiling_ms =
                [int]$MaintenanceRemainingCeilingMs
            alembic_revision = $TargetRevision
            resource_shape_sha256 = '{LOWER_SUBJECT_SHA256}'
            money_facts_sha256 = '9' * 64
        }}
    }}.GetNewClosure()
    $moneyFailure = $null
    try {{
        Invoke-TicketboxC07ProductionLifecycleCoordinator `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -TargetSemanticAction $badMoneySemanticAction `
            -StopAfterMigrationCompleted | Out-Null
    }} catch {{ $moneyFailure = $_.Exception }}
    if ($null -eq $moneyFailure -or
        [string]$moneyFailure.Data['TicketboxC07FailureClass'] -cne 'invariant' -or
        [string]$moneyFailure.Data['TicketboxC07FailureCode'] -cne
            'money_facts_mismatch') {{
        throw (
            'money-facts mismatch was not a stable invariant failure: ' +
            [string]$moneyFailure.Message + '; class=' +
            [string]$moneyFailure.Data['TicketboxC07FailureClass'] + '; code=' +
            [string]$moneyFailure.Data['TicketboxC07FailureCode'] + '; inner=' +
            [string]$moneyFailure.InnerException.Message
        )
    }}
    $badShapeSemanticAction = {{
        return [pscustomobject]@{{ schema = 'malformed-semantic-result' }}
    }}
    $shapeFailure = $null
    try {{
        Invoke-TicketboxC07ProductionLifecycleCoordinator `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -TargetSemanticAction $badShapeSemanticAction `
            -StopAfterMigrationCompleted | Out-Null
    }} catch {{ $shapeFailure = $_.Exception }}
    if ($null -eq $shapeFailure -or
        [string]$shapeFailure.Data['TicketboxC07FailureClass'] -cne 'invariant' -or
        [string]$shapeFailure.Data['TicketboxC07FailureCode'] -cne
            'resource_shape_mismatch') {{
        throw 'resource-shape mismatch was not a stable invariant failure'
    }}
    $transientSemanticAction = {{
        throw [IO.IOException]::new('injected semantic transport failure')
    }}
    $transientFailure = $null
    try {{
        Invoke-TicketboxC07ProductionLifecycleCoordinator `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -TargetSemanticAction $transientSemanticAction `
            -StopAfterMigrationCompleted | Out-Null
    }} catch {{ $transientFailure = $_.Exception }}
    if ($null -eq $transientFailure -or
        -not [string]::IsNullOrEmpty(
            [string]$transientFailure.Data['TicketboxC07FailureClass']
        )) {{
        throw 'semantic action transport failure was not left transient'
    }}
    $targetCommit = Invoke-TicketboxC07ProductionLifecycleCoordinator `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $script:testPassword `
        -MigratorPassword $script:testPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $migrationAction `
        -TargetSemanticAction $targetSemanticAction `
        -StopAfterMigrationCompleted
    if ($targetCommit.result -cne 'target_committed') {{
        throw 'production coordinator did not return the target commit boundary'
    }}
    $script:testDatabaseHead = '20260729_0001'
    foreach ($stage in @(
        'target_committed',
        'target_recovery_generation_ready',
        'target_isolated_restore_verified'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $production = Invoke-TicketboxC07ProductionLifecycleCoordinator `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $script:testPassword `
        -MigratorPassword $script:testPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $migrationAction `
        -TargetSemanticAction $targetSemanticAction
    $replay = Invoke-TicketboxC07ProductionLifecycleCoordinator `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $script:testPassword `
        -MigratorPassword $script:testPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $migrationAction `
        -TargetSemanticAction $targetSemanticAction
    if ($production.PayloadSha256 -cne $replay.PayloadSha256) {{
        throw 'production authority was not idempotently reused'
    }}
    $validated = Invoke-TicketboxC07ProductionLifecycleCoordinator `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $script:testPassword `
        -MigratorPassword $script:testPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $migrationAction `
        -TargetSemanticAction $targetSemanticAction `
        -ValidateExistingProductionAuthority
    if (
        $validated.PayloadSha256 -cne $production.PayloadSha256 -or
        $script:precommittedValidationCalls -ne 1
    ) {{
        throw 'precommitted production validation rewrote host authority'
    }}
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $wrong = New-TestC07ProducerEvidence runtime_acl_verified $authority
    $wrong.subject_sha256 = ('B' * 64)
    $wrongRejected = $false
    try {{
        New-TicketboxC07StageEvidence `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage runtime_acl_verified `
            -ProducerEvidence $wrong | Out-Null
    }}
    catch {{ $wrongRejected = $true }}
    if (-not $wrongRejected) {{
        throw 'runtime_acl_verified accepted non-production subject'
    }}
    foreach ($stage in @('runtime_acl_verified', 'ready')) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $projection = Read-TicketboxC07RuntimeProjection '{_literal(data_root)}'
    if ($projection.Payload.schema -cne
            'ticketbox-c07-runtime-projection-v6' -or
        $projection.Payload.live_postconditions_sha256 -cne
            '{SUBJECT_SHA256}' -or
        $projection.Payload.recovery_manifest_sha256 -cne
            '{SUBJECT_SHA256}' -or
        $projection.Payload.money_facts_sha256 -cne
            '{SUBJECT_SHA256}' -or
        $projection.Payload.money_shape_sha256 -cne
            '{SUBJECT_SHA256}') {{
        throw 'runtime projection omitted exact production startup facts'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lifecycle contract")
def test_c07_installed_coordinator_runs_and_resumes_the_entire_stage_machine(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"installed-coordinator-{index}"
        root.mkdir()
        prefix, data_root, _, _ = _common_harness(
            root,
            pending_operation_id="123e4567-e89b-42d3-a456-4266141740aa",
        )
        harness = root / "installed-coordinator.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$script:generationCalls = 0
$script:restoreCalls = 0
$script:restoreStages = @()
$script:targetGenerationCalls = 0
$script:targetRestoreCalls = 0
$script:productionCalls = 0
$script:passwordCalls = 0
$script:sourceTransientInjected = $false
$script:postCommitTransientInjected = $false
function New-StrongPassword {{
    $script:passwordCalls += 1
    if ($script:passwordCalls -eq 1) {{ return ('R' * 40) }}
    return ('M' * 40)
}}
function Invoke-TicketboxC07RecoveryGeneration {{
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $MigratorPassword,
        $ExpectedSourceRevision,
        $MoneyFactsAction
    )
    if (
        $ExpectedSourceRevision -cne '20260722_0001' -or
        $null -eq $MoneyFactsAction
    ) {{ throw 'generation lost money-facts authority' }}
    if (-not $script:sourceTransientInjected) {{
        $script:sourceTransientInjected = $true
        throw [IO.IOException]::new('injected transient pg_dump failure')
    }}
    $script:generationCalls += 1
    return [pscustomobject]@{{ EvidenceSha256 = '{SUBJECT_SHA256}' }}
}}
function Test-TicketboxC07RecoveryGenerationRestore {{
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $MigratorPassword,
        $ExpectedSourceRevision,
        $TargetRevision,
        $ForwardReplayAction
    )
    if (
        $ExpectedSourceRevision -cne '20260722_0001' -or
        $TargetRevision -cne '20260729_0001' -or
        $null -eq $ForwardReplayAction
    ) {{
        throw 'installed restore lost frozen replay authority'
    }}
    $authority = Read-TicketboxC07Authority $DataRoot
    $stage = [string]$authority.Receipt.stage
    if ($stage -notin @(
        'recovery_generation_ready',
        'isolated_restore_verified'
    )) {{
        throw "installed restore ran at unsupported stage: $stage"
    }}
    $script:restoreCalls += 1
    $script:restoreStages += $stage
    return [pscustomobject]@{{ EvidenceSha256 = '{SUBJECT_SHA256}' }}
}}
function Invoke-TicketboxC07TargetRecoveryGeneration {{
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $MigratorPassword,
        $ExpectedSourceRevision,
        $TargetRevision,
        $MoneyFactsAction,
        $TargetSemanticAction,
        $TargetCommitEvidenceSha256,
        $MigrationEvidenceSha256,
        $ExpectedResourceShapeSha256,
        $ExpectedMoneyFactsSha256
    )
    if (
        $ExpectedSourceRevision -cne '20260722_0001' -or
        $TargetRevision -cne '20260729_0001' -or
        $null -eq $MoneyFactsAction -or
        $null -eq $TargetSemanticAction -or
        [string]::IsNullOrEmpty($TargetCommitEvidenceSha256) -or
        [string]::IsNullOrEmpty($MigrationEvidenceSha256) -or
        [string]::IsNullOrEmpty($ExpectedResourceShapeSha256) -or
        [string]::IsNullOrEmpty($ExpectedMoneyFactsSha256)
    ) {{
        throw 'target generation lost post-DDL authority'
    }}
    if (-not $script:postCommitTransientInjected) {{
        $script:postCommitTransientInjected = $true
        throw [IO.IOException]::new('injected transient target backup failure')
    }}
    $script:targetGenerationCalls += 1
    return [pscustomobject]@{{ EvidenceSha256 = '{SUBJECT_SHA256}' }}
}}
function Test-TicketboxC07TargetRecoveryGenerationRestore {{
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $MigratorPassword,
        $ExpectedSourceRevision,
        $TargetRevision,
        $MoneyFactsAction,
        $TargetSemanticAction
    )
    if (
        $ExpectedSourceRevision -cne '20260722_0001' -or
        $TargetRevision -cne '20260729_0001' -or
        $null -eq $MoneyFactsAction -or
        $null -eq $TargetSemanticAction
    ) {{
        throw 'target restore lost zero-replay authority'
    }}
    $script:targetRestoreCalls += 1
    return [pscustomobject]@{{ EvidenceSha256 = '{SUBJECT_SHA256}' }}
}}
function Read-TicketboxC07ProductionTargetRecoveryGeneration {{
    throw 'installed coordinator stub owns production target recovery'
}}
function Renew-TicketboxC07RoleCredentialWindow {{}}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{ Schema = 'host-authority' }}
}}
function Invoke-TicketboxC07ProductionLifecycleCoordinator {{
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        $MigratorValidUntilUtc,
        $Mode,
        $ExpectedSourceRevision,
        $MigrationAction,
        $TargetSemanticAction,
        [switch]$StopAfterMigrationCompleted
    )
    if ($Mode -cne 'fresh_install' -or
        $ExpectedSourceRevision -cne '20260722_0001' -or
        $MigratorValidUntilUtc.ToUniversalTime() -le [DateTime]::UtcNow -or
        $null -eq $TargetSemanticAction) {{
        throw 'installed coordinator lost production inputs'
    }}
    $script:productionCalls += 1
    if ($StopAfterMigrationCompleted) {{
        $script:testDatabaseHead = '20260729_0001'
        $authority = Read-TicketboxC07Authority $DataRoot
        return [pscustomobject][ordered]@{{
            schema = 'ticketbox-c07-target-commit-result-v1'
            operation_id = [string]$authority.Receipt.operation_id
            mode = $Mode
            result = 'target_committed'
            cluster_system_identifier =
                [string]$authority.Descriptor.Payload.cluster_system_identifier
            database_oid = [string]$authority.Descriptor.Payload.database_oid
            logical_server_id =
                [string]$authority.Descriptor.Payload.logical_server_id
            data_generation =
                [string]$authority.Descriptor.Payload.data_generation
            source_alembic_revision = $ExpectedSourceRevision
            target_alembic_revision = '20260729_0001'
            alembic_revision = '20260729_0001'
            source_recovery_manifest_sha256 = '{LOWER_SUBJECT_SHA256}'
            migration_evidence_sha256 = '{LOWER_SUBJECT_SHA256}'
            resource_shape_sha256 = '{LOWER_SUBJECT_SHA256}'
            money_facts_sha256 = '{LOWER_SUBJECT_SHA256}'
            statistics_table_count = 18
            statistics_table_set_sha256 = '{LOWER_SUBJECT_SHA256}'
        }}
    }}
    $authority = Read-TicketboxC07Authority $DataRoot
    return New-TestC07ProductionAuthority $authority
}}
$migrationAction = {{
    throw 'unit production coordinator owns the migration callback'
}}
$isolatedReplayAction = {{
    throw 'unit restore harness owns the isolated replay callback'
}}
$moneyFactsAction = {{
    throw 'unit generation harness owns the money-facts callback'
}}
$targetSemanticAction = {{
    throw 'unit target-generation harness owns the semantic callback'
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $installationOperationId = '123e4567-e89b-42d3-a456-4266141740aa'
    $intent = Get-OrCreateTicketboxC07FreshBootstrapIntent `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -ExpectedOperationId $installationOperationId
    $intentReplay = Get-OrCreateTicketboxC07FreshBootstrapIntent `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -ExpectedOperationId $installationOperationId
    if ($intent.PayloadSha256 -cne $intentReplay.PayloadSha256 -or
        $intent.RuntimePassword.Length -ne 40 -or
        $intent.MigratorPassword.Length -ne 40 -or
        $script:passwordCalls -ne 2) {{
        throw 'fresh bootstrap intent was not durable and idempotent'
    }}
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId $intent.OperationId | Out-Null
    $credentials = Get-OrCreateTicketboxC07InstalledCredentials `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -Mode fresh_install
    $credentialsReplay = Get-OrCreateTicketboxC07InstalledCredentials `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -Mode fresh_install
    if ($credentials.PayloadSha256 -cne $credentialsReplay.PayloadSha256 -or
        $credentials.RuntimePassword.Length -ne 40 -or
        $credentials.MigratorPassword.Length -ne 40 -or
        $script:passwordCalls -ne 2) {{
        throw 'installed credentials were not durable and idempotent'
    }}
    $earlyCleanupRejected = $false
    try {{
        Remove-TicketboxC07InstalledCredentials `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -Mode fresh_install
    }}
    catch {{ $earlyCleanupRejected = $true }}
    if (-not $earlyCleanupRejected) {{
        throw 'installed credentials were removed before READY'
    }}
    $sourceTransient = $false
    try {{
        Invoke-TicketboxC07InstalledProductionLifecycle `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $credentials.RuntimePassword `
            -MigratorPassword $credentials.MigratorPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -IsolatedReplayAction $isolatedReplayAction `
            -MoneyFactsAction $moneyFactsAction `
            -TargetSemanticAction $targetSemanticAction `
            -ExpectedOperationId $intent.OperationId | Out-Null
    }}
    catch {{
        if ($_.Exception.Message -cne 'injected transient pg_dump failure') {{
            throw
        }}
        $sourceTransient = $true
    }}
    $sourceAuthority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $sourceHeartbeat = Read-TicketboxC07Heartbeat $sourceAuthority
    if (-not $sourceTransient -or
        $sourceAuthority.Receipt.stage -cne 'writers_frozen' -or
        [int64]$sourceHeartbeat.Payload.maintenance_attempt_sequence -ne 1 -or
        [string]::IsNullOrEmpty(
            [string]$sourceHeartbeat.Payload.maintenance_attempt_failure_sha256
        )) {{
        throw 'pre-DDL transient failure did not retain recoverable stage'
    }}
    $postCommitTransient = $false
    try {{
        Invoke-TicketboxC07InstalledProductionLifecycle `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $credentials.RuntimePassword `
            -MigratorPassword $credentials.MigratorPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -IsolatedReplayAction $isolatedReplayAction `
            -MoneyFactsAction $moneyFactsAction `
            -TargetSemanticAction $targetSemanticAction `
            -ExpectedOperationId $intent.OperationId | Out-Null
    }}
    catch {{
        if ($_.Exception.Message -cne
            'injected transient target backup failure') {{
            throw
        }}
        $postCommitTransient = $true
    }}
    $postCommitAuthority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $postCommitHeartbeat = Read-TicketboxC07Heartbeat $postCommitAuthority
    if (-not $postCommitTransient -or
        $postCommitAuthority.Receipt.stage -cne 'target_committed' -or
        [int64]$postCommitHeartbeat.Payload.maintenance_attempt_sequence -ne 2 -or
        [string]::IsNullOrEmpty(
            [string]$postCommitHeartbeat.Payload.maintenance_attempt_failure_sha256
        )) {{
        throw 'post-commit transient failure did not retain recoverable stage'
    }}
    $script:projectionFailureInjected = $false
    $script:originalProjectionWriter =
        ${{function:Write-TicketboxC07RuntimeProjection}}
    function Write-TicketboxC07RuntimeProjection {{
        param($Authority, $HeartbeatSequence)
        if (
            [string]$Authority.Receipt.stage -ceq 'ready' -and
            -not $script:projectionFailureInjected
        ) {{
            $script:projectionFailureInjected = $true
            throw 'injected crash after READY authority replace'
        }}
        & $script:originalProjectionWriter `
            -Authority $Authority `
            -HeartbeatSequence $HeartbeatSequence
    }}
    $firstFailed = $false
    try {{
        Invoke-TicketboxC07InstalledProductionLifecycle `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $credentials.RuntimePassword `
            -MigratorPassword $credentials.MigratorPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -IsolatedReplayAction $isolatedReplayAction `
            -MoneyFactsAction $moneyFactsAction `
            -TargetSemanticAction $targetSemanticAction `
            -ExpectedOperationId $intent.OperationId | Out-Null
    }}
    catch {{
        if (
            $_.Exception.Message -cne
                'injected crash after READY authority replace'
        ) {{ throw }}
        $firstFailed = $true
    }}
    Set-Item `
        -Path Function:\\Write-TicketboxC07RuntimeProjection `
        -Value $script:originalProjectionWriter
    $readyAuthorityBeforeReplay =
        Read-TicketboxC07Authority '{_literal(data_root)}'
    $readyAuthoritySha256 =
        [string]$readyAuthorityBeforeReplay.Envelope.PayloadSha256
    $second = Invoke-TicketboxC07InstalledProductionLifecycle `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $credentials.RuntimePassword `
        -MigratorPassword $credentials.MigratorPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $migrationAction `
        -IsolatedReplayAction $isolatedReplayAction `
        -MoneyFactsAction $moneyFactsAction `
        -TargetSemanticAction $targetSemanticAction `
        -ExpectedOperationId $intent.OperationId
    $third = Invoke-TicketboxC07InstalledProductionLifecycle `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $credentials.RuntimePassword `
        -MigratorPassword $credentials.MigratorPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $migrationAction `
        -IsolatedReplayAction $isolatedReplayAction `
        -MoneyFactsAction $moneyFactsAction `
        -TargetSemanticAction $targetSemanticAction `
        -ExpectedOperationId $intent.OperationId
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    Remove-TicketboxC07InstalledCredentials `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -Mode fresh_install
    Remove-TicketboxC07FreshBootstrapIntent `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock
    if (-not $firstFailed -or
        -not $script:projectionFailureInjected -or
        $second.schema -cne 'ticketbox-c07-installed-lifecycle-result-v1' -or
        $second.result -cne 'ready' -or
        $third.operation_id -cne $second.operation_id -or
        [string]$authority.Envelope.PayloadSha256 -cne $readyAuthoritySha256 -or
        $authority.Receipt.stage -cne 'ready' -or
        [int64]$authority.Receipt.stage_sequence -ne 9 -or
        [int64](Read-TicketboxC07Heartbeat $authority).Payload.maintenance_attempt_sequence -ne 3 -or
        $script:generationCalls -ne 1 -or
        $script:restoreCalls -ne 2 -or
        [string]::Join(',', $script:restoreStages) -cne
            'recovery_generation_ready,isolated_restore_verified' -or
        $script:targetGenerationCalls -ne 1 -or
        $script:targetRestoreCalls -ne 1 -or
        $script:productionCalls -ne 2 -or
        (Test-Path -LiteralPath $credentials.Path) -or
        (Test-Path -LiteralPath $intent.Path)) {{
        throw 'installed coordinator did not converge idempotently'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows writer-freeze contract")
def test_c07_writer_freeze_rejects_live_service_listener_process_and_session(
    tmp_path: Path,
) -> None:
    cases = {
        "service": "$script:testServiceState = 'running'; $script:testServicePid = 41",
        "listener": "$script:testListenerPids = @(42)",
        "process": "$script:testRuntimePids = @(43)",
        "fence": "$script:testFenceAvailable = $false",
    }
    engine = powershell_contract_engines()[0]
    for case, mutation in cases.items():
        root = tmp_path / case
        prefix, data_root, _, _ = _common_harness(root)
        harness = root / "reject.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    {mutation}
    $rejected = $false
    try {{
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage writers_frozen | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw '{case} did not block writers_frozen' }}
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    if ($authority.Receipt.stage -cne 'captured') {{
        throw '{case} failure mutated lifecycle stage'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)

    cleanup_root = tmp_path / "session-cleanup"
    prefix, data_root, _, _ = _common_harness(cleanup_root)
    cleanup_harness = cleanup_root / "cleanup.ps1"
    _write_ps1(
        cleanup_harness,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    $script:testDatabaseSessions = 2
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    if ($script:testDatabaseSessions -ne 0) {{
        throw 'registered runtime sessions were not evicted'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, cleanup_harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL lifecycle contract")
def test_c07_failure_terminal_is_typed_and_cannot_be_rewritten(tmp_path: Path) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"terminal-{index}"
        prefix, data_root, _, _ = _common_harness(root)
        harness = root / "terminal.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage refused_pre_ddl `
        -FailureCode manifest_not_ready | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $evidence = Read-TicketboxC07FailureEvidence $authority 'refused_pre_ddl'
    if ($authority.Receipt.stage -cne 'refused_pre_ddl' -or
        $evidence.Payload.failure_code -cne 'manifest_not_ready') {{
        throw 'typed failure evidence was not authoritative'
    }}
    $rewriteRejected = $false
    try {{
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage repair_required `
            -FailureCode second_terminal | Out-Null
    }}
    catch {{ $rewriteRejected = $true }}
    if (-not $rewriteRejected) {{ throw 'failure terminal was rewritten' }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows successor contract")
def test_c07_refused_terminal_starts_new_immutable_successor_operation(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"successor-pre-ddl-{index}"
        predecessor_operation_id = "123e4567-e89b-42d3-a456-4266141740ab"
        prefix, data_root, install_dir, _ = _common_harness(
            root,
            pending_operation_id=predecessor_operation_id,
        )
        manifest = install_dir / "installer" / "BUILD_PROVENANCE.json"
        harness = root / "successor-pre-ddl.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{predecessor_operation_id}' | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage refused_pre_ddl `
        -FailureCode manifest_not_ready | Out-Null
    $terminal = Read-TicketboxC07Authority '{_literal(data_root)}' `
        -ExpectedInstallationOperationId '{predecessor_operation_id}'
    $terminalText = [string]$terminal.Envelope.Text

    $resolution = Initialize-TicketboxC07SuccessorInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}' `
        -LifecycleLock $lock
    if ($null -eq $resolution -or
        [string]$resolution.Mode -cne 'pre_ddl' -or
        [string]$resolution.Identity.OperationId -ceq '{predecessor_operation_id}') {{
        throw 'refused terminal did not mint a distinct pre-DDL successor'
    }}
    $successorOperationId = [string]$resolution.Identity.OperationId
    $started = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId $successorOperationId `
        -SuccessorIntent $resolution.Intent
    $successor = Read-TicketboxC07Authority '{_literal(data_root)}' `
        -ExpectedInstallationOperationId $successorOperationId
    $archive = Read-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07TerminalAuthorityArchivePath `
            '{predecessor_operation_id}') `
        -ExpectedKind authority_receipt
    $attempt = Read-TicketboxC07Heartbeat $successor
    if ([string]$started.Stage -cne 'captured' -or
        [string]$successor.Descriptor.Payload.successor_mode -cne 'pre_ddl' -or
        [string]$successor.Descriptor.Payload.predecessor_operation_id -cne
            '{predecessor_operation_id}' -or
        [string]$successor.Descriptor.Payload.predecessor_terminal_receipt_payload_sha256 -cne
            [string]$terminal.Envelope.PayloadSha256 -or
        [string]$successor.Descriptor.Payload.predecessor_terminal_authority_chain_sha256 -cne
            [string]$terminal.Receipt.authority_chain_sha256 -or
        [string]$archive.Text -cne $terminalText -or
        [int64]$attempt.Payload.maintenance_attempt_sequence -ne 1) {{
        throw 'successor did not preserve terminal lineage and start a new budget'
    }}

    $noSecondSuccessor = Initialize-TicketboxC07SuccessorInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}' `
        -LifecycleLock $lock
    if ($null -ne $noSecondSuccessor) {{
        throw 'nonterminal successor incorrectly forked another operation'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows successor contract")
def test_c07_tail_repair_successor_freezes_target_recovery_and_marker_lineage(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"successor-tail-{index}"
        predecessor_operation_id = "123e4567-e89b-42d3-a456-4266141740ac"
        prefix, data_root, install_dir, _ = _common_harness(
            root,
            pending_operation_id=predecessor_operation_id,
        )
        manifest = install_dir / "installer" / "BUILD_PROVENANCE.json"
        harness = root / "successor-tail.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{predecessor_operation_id}' | Out-Null
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    foreach ($stage in @(
        'recovery_generation_ready',
        'isolated_restore_verified',
        'ddl_started'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $script:testDatabaseHead = '20260729_0001'
    foreach ($stage in @(
        'target_committed',
        'target_recovery_generation_ready',
        'target_isolated_restore_verified'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $beforeAcl = Read-TicketboxC07Authority '{_literal(data_root)}'
    New-TestC07ProductionAuthority $beforeAcl | Out-Null
    $runtimeEvidence = New-TestC07StageEvidence `
        -Stage runtime_acl_verified `
        -LifecycleLock $lock `
        -DataRoot '{_literal(data_root)}'
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage runtime_acl_verified `
        -EvidencePath $runtimeEvidence.Path | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage repair_required `
        -FailureCode readiness_publish_failed | Out-Null
    $terminal = Read-TicketboxC07Authority '{_literal(data_root)}'
    $targetCommit = Read-TicketboxC07StageEvidence `
        -Authority $terminal `
        -Stage target_committed
    $targetGeneration = Read-TicketboxC07StageEvidence `
        -Authority $terminal `
        -Stage target_recovery_generation_ready
    $targetRestore = Read-TicketboxC07StageEvidence `
        -Authority $terminal `
        -Stage target_isolated_restore_verified
    $runtimeAcl = Read-TicketboxC07StageEvidence `
        -Authority $terminal `
        -Stage runtime_acl_verified
    $script:testProductionMarker = [string]::Join('|', @(
        'ticketbox-c07-production-authority-v1',
        '{predecessor_operation_id}',
        'fresh_install',
        'production_ready',
        '7123456789012345678',
        '42',
        '20260722_0001',
        '20260729_0001',
        ('1' * 64),
        ('2' * 64),
        ('3' * 64),
        ('4' * 64),
        ('5' * 64)
    ))
    $markerSha256 = Get-TicketboxC07TextSha256 $script:testProductionMarker

    $resolution = Initialize-TicketboxC07SuccessorInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}' `
        -LifecycleLock $lock
    if (
        $null -eq $resolution -or
        [string]$resolution.Mode -cne 'forward_repair' -or
        [string]$resolution.Intent.Payload.predecessor_target_commit_evidence_sha256 -cne
            [string]$targetCommit.PayloadSha256 -or
        [string]$resolution.Intent.Payload.predecessor_target_recovery_generation_evidence_sha256 -cne
            [string]$targetGeneration.PayloadSha256 -or
        [string]$resolution.Intent.Payload.predecessor_target_isolated_restore_evidence_sha256 -cne
            [string]$targetRestore.PayloadSha256 -or
        [string]$resolution.Intent.Payload.predecessor_runtime_acl_evidence_sha256 -cne
            [string]$runtimeAcl.PayloadSha256 -or
        [string]$resolution.Intent.Payload.predecessor_production_marker_sha256 -cne
            $markerSha256
    ) {{
        throw 'tail successor did not freeze exact target recovery/marker lineage'
    }}
    $started = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId ([string]$resolution.Identity.OperationId) `
        -SuccessorIntent $resolution.Intent
    if ([string]$started.Stage -cne 'captured') {{
        throw 'tail successor did not start a distinct lifecycle operation'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL lifecycle contract")
def test_c07_failure_persistence_preserves_action_and_persistence_errors(
    tmp_path: Path,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"dual-failure-{index}"
        operation_id = "123e4567-e89b-42d3-a456-4266141740ab"
        prefix, data_root, _, _ = _common_harness(
            root,
            pending_operation_id=operation_id,
        )
        harness = root / "dual-failure.ps1"
        _write_ps1(
            harness,
            prefix
            + _recovery_combo_support()
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{operation_id}'
    $script:originalStageSetter =
        ${{function:Set-TicketboxC07LifecycleStage}}
    function Set-TicketboxC07LifecycleStage {{
        param(
            [string]$DataRoot,
            $LifecycleLock,
            [string]$TargetStage,
            [string]$EvidencePath = '',
            [string]$FailureCode = ''
        )
        if ($TargetStage -in @('refused_pre_ddl', 'repair_required')) {{
            throw 'injected failure persistence crash'
        }}
        return & $script:originalStageSetter @PSBoundParameters
    }}
    function Invoke-TicketboxC07RecoveryGeneration {{
        throw (New-TicketboxC07ClassifiedFailure `
            -Message 'injected maintenance action crash' `
            -FailureClass invariant `
            -FailureCode writer_fence_invariant_failed)
    }}
    function Renew-TicketboxC07RoleCredentialWindow {{
        return [pscustomobject]@{{ result = 'renewed' }}
    }}
    $unusedAction = {{ throw 'unexpected product action' }}
    $caught = $null
    try {{
        Invoke-TicketboxC07InstalledProductionLifecycle `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $unusedAction `
            -IsolatedReplayAction $unusedAction `
            -MoneyFactsAction $unusedAction `
            -TargetSemanticAction $unusedAction `
            -ExpectedOperationId $operation.OperationId | Out-Null
    }}
    catch {{
        $caught = $_.Exception
    }}
    if ($null -eq $caught -or
        $caught -isnot [AggregateException] -or
        $caught.InnerExceptions.Count -ne 2 -or
        $caught.InnerExceptions[0].Message -cne
            'injected maintenance action crash' -or
        $caught.InnerExceptions[1].Message -cne
            'injected failure persistence crash' -or
        [string]$caught.Data['TicketboxC07FailureCode'] -cne
            'writer_fence_invariant_failed') {{
        $innerMessages = @(
            $caught.InnerExceptions |
                ForEach-Object {{ $_.Message }}
        )
        throw (
            'dual lifecycle failure did not preserve both causes: ' +
            "type=$($caught.GetType().FullName) " +
            "message=$($caught.Message) " +
            "count=$(@($caught.InnerExceptions).Count) " +
            "messages=$($innerMessages -join ' | ') " +
            "code=$($caught.Data['TicketboxC07FailureCode'])"
        )
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL lifecycle contract")
@pytest.mark.parametrize("terminal_stage", ["refused_pre_ddl", "repair_required"])
def test_c07_failure_terminal_restart_rebuilds_projection_without_authority_rewrite(
    tmp_path: Path,
    terminal_stage: str,
) -> None:
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"terminal-projection-{terminal_stage}-{index}"
        prefix, data_root, _, _ = _common_harness(
            root,
            pending_operation_id="123e4567-e89b-42d3-a456-4266141740ab",
        )
        harness = root / "terminal-projection.ps1"
        advance = ""
        if terminal_stage == "repair_required":
            advance = f"""
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    foreach ($stage in @(
        'recovery_generation_ready',
        'isolated_restore_verified',
        'ddl_started'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
"""
        _write_ps1(
            harness,
            prefix
            + f"""
function Invoke-TicketboxC07RecoveryGeneration {{
    throw 'terminal replay invoked recovery generation'
}}
function Test-TicketboxC07RecoveryGenerationRestore {{
    throw 'terminal replay invoked source restore'
}}
function Invoke-TicketboxC07TargetRecoveryGeneration {{
    throw 'terminal replay invoked target generation'
}}
function Test-TicketboxC07TargetRecoveryGenerationRestore {{
    throw 'terminal replay invoked target restore'
}}
function Read-TicketboxC07ProductionTargetRecoveryGeneration {{
    throw 'terminal replay invoked target generation read'
}}
$unusedAction = {{ throw 'terminal replay invoked a product action' }}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $installationOperationId = '123e4567-e89b-42d3-a456-4266141740ab'
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId $installationOperationId
{advance}
    $script:projectionFailureInjected = $false
    $script:originalProjectionWriter =
        ${{function:Write-TicketboxC07RuntimeProjection}}
    function Write-TicketboxC07RuntimeProjection {{
        param($Authority, $HeartbeatSequence)
        if (
            [string]$Authority.Receipt.stage -ceq '{terminal_stage}' -and
            -not $script:projectionFailureInjected
        ) {{
            $script:projectionFailureInjected = $true
            throw 'injected terminal projection crash'
        }}
        & $script:originalProjectionWriter `
            -Authority $Authority `
            -HeartbeatSequence $HeartbeatSequence
    }}
    $transitionFailed = $false
    try {{
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage '{terminal_stage}' `
            -FailureCode 'injected_terminal_failure' | Out-Null
    }}
    catch {{
        if ($_.Exception.Message -cne 'injected terminal projection crash') {{
            throw
        }}
        $transitionFailed = $true
    }}
    Set-Item `
        -Path Function:\\Write-TicketboxC07RuntimeProjection `
        -Value $script:originalProjectionWriter
    $terminalAuthority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $terminalAuthoritySha256 =
        [string]$terminalAuthority.Envelope.PayloadSha256
    $result = Invoke-TicketboxC07InstalledProductionLifecycle `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -RuntimePassword $script:testPassword `
        -MigratorPassword $script:testPassword `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -Mode fresh_install `
        -ExpectedSourceRevision '20260722_0001' `
        -MigrationAction $unusedAction `
        -IsolatedReplayAction $unusedAction `
        -MoneyFactsAction $unusedAction `
        -TargetSemanticAction $unusedAction `
        -ExpectedOperationId $operation.OperationId
    $after = Read-TicketboxC07Authority '{_literal(data_root)}'
    $projection = Read-TicketboxC07RuntimeProjection '{_literal(data_root)}'
    if (
        -not $transitionFailed -or
        -not $script:projectionFailureInjected -or
        [string]$result.result -cne '{terminal_stage}' -or
        [string]$result.failure_code -cne 'injected_terminal_failure' -or
        [string]$after.Envelope.PayloadSha256 -cne
            $terminalAuthoritySha256 -or
        [string]$projection.Payload.stage -cne '{terminal_stage}' -or
        -not [bool]$projection.Payload.terminal
    ) {{
        throw 'terminal restart did not reconstruct projection exactly'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity contract")
def test_c07_release_identity_and_pid_filetime_tampering_fail_closed(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "identity"
    prefix, data_root, _, manifest = _common_harness(root)
    harness = root / "identity.ps1"
    _write_ps1(
        harness,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $identityPath = Get-TicketboxPersistentInstallationIdentityPath '{_literal(data_root)}'
    $identityText = (Read-TicketboxProtectedUtf8Artifact `
        -Path $identityPath `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount).Text
    $replacement = [regex]::Replace(
        $identityText,
        '(?m)^INSTALLATION_ID=[^\\r\\n]+\\r?$',
        ('INSTALLATION_ID=' + [guid]::NewGuid().ToString('D'))
    )
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $identityPath `
        -Text $replacement `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount `
        -ReplaceExisting
    $identityRejected = $false
    try {{ Read-TicketboxC07Authority '{_literal(data_root)}' | Out-Null }}
    catch {{ $identityRejected = $true }}
    if (-not $identityRejected) {{ throw 'installation identity replacement was accepted' }}
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $identityPath `
        -Text $identityText `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount `
        -ReplaceExisting

    $manifestBytes = [IO.File]::ReadAllBytes('{_literal(manifest)}')
    [IO.File]::WriteAllText(
        '{_literal(manifest)}',
        ([IO.File]::ReadAllText('{_literal(manifest)}') + ' ')
    )
    $manifestRejected = $false
    try {{ Read-TicketboxC07Authority '{_literal(data_root)}' | Out-Null }}
    catch {{ $manifestRejected = $true }}
    if (-not $manifestRejected) {{ throw 'installed manifest replacement was accepted' }}
    [IO.File]::WriteAllBytes('{_literal(manifest)}', $manifestBytes)

    $wrongLow = [uint32]$authority.Binding.CoordinatorIdentity.StartedFileTimeLow
    if ($wrongLow -eq [uint32]::MaxValue) {{ $wrongLow-- }} else {{ $wrongLow++ }}
    $wrongIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
        -ProcessId ([int]$authority.Binding.CoordinatorIdentity.ProcessId) `
        -StartedFileTimeHigh ([uint32]$authority.Binding.CoordinatorIdentity.StartedFileTimeHigh) `
        -StartedFileTimeLow $wrongLow
    $fake = [pscustomobject]@{{
        Binding = [pscustomobject]@{{
            CoordinatorIdentity = $wrongIdentity
            LifecycleOwnerIdentity = $authority.Binding.LifecycleOwnerIdentity
        }}
    }}
    $filetimeRejected = $false
    try {{ Assert-TicketboxC07OperationLease $fake $lock }}
    catch {{ $filetimeRejected = $true }}
    if (-not $filetimeRejected) {{ throw 'PID FILETIME mismatch was accepted' }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows protected artifact contract")
def test_c07_hash_mismatch_and_backend_writable_roots_fail_closed(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "hash"
    prefix, data_root, _, _ = _common_harness(root)
    harness = root / "hash.ps1"
    _write_ps1(
        harness,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    $path = Get-TicketboxC07AuthorityPath
    $text = (Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount).Text
    $envelope = $text | ConvertFrom-Json
    $envelope.payload_json = $envelope.payload_json.Replace(
        '"stage":"captured"',
        '"stage":"ready"'
    )
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (($envelope | ConvertTo-Json -Depth 8 -Compress) + "`n") `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount `
        -ReplaceExisting
    $rejected = $false
    try {{ Read-TicketboxC07Authority '{_literal(data_root)}' | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw 'authority payload hash mismatch was accepted' }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}

$script:forbiddenLockRoot = Join-Path '{_literal(data_root)}' 'app\\machine-authority'
function Get-TicketboxLifecycleLockPath {{
    return Join-Path $script:forbiddenLockRoot 'installer-lifecycle.lock'
}}
$release = Get-TicketboxC07ReleaseIdentity '{_literal(data_root)}'
$rootRejected = $false
try {{ Assert-TicketboxC07ArtifactRoots $release | Out-Null }}
catch {{ $rootRejected = $true }}
if (-not $rootRejected) {{
    throw 'Backend-writable DataRoot accepted host authority roots'
}}
""",
    )
    _run_harness(engine, harness)


def _wait_for_path(path: Path, process: subprocess.Popen[str], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"coordinator exited before signal:\n{stdout}\n{stderr}"
            )
        time.sleep(0.05)
    process.kill()
    raise AssertionError(f"timed out waiting for {path}")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows cross-process takeover")
def test_c07_precommitted_runtime_acl_evidence_survives_takeover(
    tmp_path: Path,
) -> None:
    operation_id = "123e4567-e89b-42d3-a456-4266141740ac"
    for engine_index, engine in enumerate(powershell_contract_engines()):
        for mutated in (False, True):
            case = "mutated" if mutated else "valid"
            root = tmp_path / f"runtime-acl-takeover-{engine_index}-{case}"
            root.mkdir()
            prefix, data_root, _, _ = _common_harness(
                root,
                pending_operation_id=operation_id,
            )
            signal = root / "runtime-acl.signal.json"
            mutation = root / "live-acl-drift.mutation"
            replay = root / "forbidden-production-replay.log"
            validations = root / "production-validations.log"
            child_script = root / "runtime-acl-child.ps1"
            _write_ps1(
                child_script,
                prefix
                + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{operation_id}' | Out-Null
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    foreach ($stage in @(
        'recovery_generation_ready',
        'isolated_restore_verified',
        'ddl_started'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $script:testDatabaseHead = '20260729_0001'
    foreach ($stage in @(
        'target_committed',
        'target_recovery_generation_ready',
        'target_isolated_restore_verified'
    )) {{
        $evidence = New-TestC07StageEvidence `
            -Stage $stage `
            -LifecycleLock $lock `
            -DataRoot '{_literal(data_root)}'
        Set-TicketboxC07LifecycleStage `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -TargetStage $stage `
            -EvidencePath $evidence.Path | Out-Null
    }}
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $production = New-TestC07ProductionAuthority $authority
    $runtimeAclEvidence = New-TestC07StageEvidence `
        -Stage runtime_acl_verified `
        -LifecycleLock $lock `
        -DataRoot '{_literal(data_root)}'
    $state = [ordered]@{{
        operation_id = [string]$authority.Receipt.operation_id
        production_sha256 = [string]$production.PayloadSha256
        runtime_acl_evidence_sha256 =
            [string]$runtimeAclEvidence.PayloadSha256
        receipt_sha256 = [string]$authority.Envelope.PayloadSha256
        binding_sequence = [int64]$authority.Binding.Sequence
    }}
    [IO.File]::WriteAllText(
        '{_literal(signal)}',
        ($state | ConvertTo-Json -Compress),
        [Text.UTF8Encoding]::new($false)
    )
    Stop-Process -Id $PID -Force
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
            )
            child = subprocess.Popen(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    child_script,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _wait_for_path(signal, child)
            child.communicate(timeout=10)
            state = json.loads(signal.read_text(encoding="utf-8"))
            assert state["binding_sequence"] == 0
            if mutated:
                mutation.write_text("runtime ACL drift\n", encoding="utf-8")

            resume_script = root / "runtime-acl-resume.ps1"
            _write_ps1(
                resume_script,
                prefix
                + f"""
$script:testDatabaseHead = '20260729_0001'
$script:testServiceState = 'stopped'
$script:testServiceStartPolicy = 'disabled'
$script:testDatabaseSessions = 0
$script:testPublicConnect = $false
Set-TestC07FenceRolesFenced
$script:retiredRoleCatalogCalls = 0
function Assert-TicketboxC07RoleCatalog {{
    throw 'active TTL/LOGIN role catalog verifier reached retired takeover'
}}
function Assert-TicketboxC07RetiredRoleCatalog {{
    param(
        [object]$Authority,
        [Security.SecureString]$SuperuserPassword
    )
    if (
        $Authority.Schema -cne 'test' -or
        -not [object]::ReferenceEquals(
            $SuperuserPassword,
            $script:testPassword
        )
    ) {{
        throw 'retired role catalog validation lost host authority'
    }}
    $script:retiredRoleCatalogCalls += 1
}}
function Invoke-TicketboxC07RecoveryGeneration {{
    throw 'source recovery replayed after runtime ACL commit'
}}
function Test-TicketboxC07RecoveryGenerationRestore {{
    throw 'source restore replayed after runtime ACL commit'
}}
function Invoke-TicketboxC07TargetRecoveryGeneration {{
    throw 'target recovery replayed after runtime ACL commit'
}}
function Test-TicketboxC07TargetRecoveryGenerationRestore {{
    throw 'target restore replayed after runtime ACL commit'
}}
function Read-TicketboxC07ProductionTargetRecoveryGeneration {{
    throw 'normal production path replayed after runtime ACL commit'
}}
function Invoke-TicketboxC07ProductionLifecycleCoordinator {{
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        $MigratorValidUntilUtc,
        $Mode,
        $ExpectedSourceRevision,
        $MigrationAction,
        $TargetSemanticAction,
        [switch]$StopAfterMigrationCompleted,
        [switch]$ValidateExistingProductionAuthority
    )
    if ($StopAfterMigrationCompleted -or
        -not $ValidateExistingProductionAuthority) {{
        [IO.File]::AppendAllText(
            '{_literal(replay)}',
            "forbidden`n",
            [Text.UTF8Encoding]::new($false)
        )
        throw 'production authority was rerun instead of reconciled'
    }}
    Assert-TicketboxC07RetiredRoleCatalog `
        -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
        -SuperuserPassword $SuperuserPassword
    $authority = Read-TicketboxC07Authority $DataRoot
    $production = Read-TicketboxC07ProductionAuthority $authority
    $evidence = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage runtime_acl_verified
    if (
        [string]$authority.Receipt.stage -cne
            'target_isolated_restore_verified' -or
        [int64]$authority.Binding.Sequence -ne 1 -or
        [string]$production.PayloadSha256 -cne
            '{state["production_sha256"]}' -or
        [string]$evidence.PayloadSha256 -cne
            '{state["runtime_acl_evidence_sha256"]}'
    ) {{
        throw 'precommitted runtime ACL lineage was not preserved for validation'
    }}
    [IO.File]::AppendAllText(
        '{_literal(validations)}',
        "validated`n",
        [Text.UTF8Encoding]::new($false)
    )
    if (Test-Path -LiteralPath '{_literal(mutation)}' -PathType Leaf) {{
        throw (New-TicketboxC07ClassifiedFailure `
            -Message 'injected live runtime ACL drift' `
            -FailureClass invariant `
            -FailureCode runtime_acl_invariant_failed)
    }}
    return $production
}}
$migrationAction = {{ throw 'DDL callback replayed after runtime ACL commit' }}
$isolatedReplayAction = {{ throw 'isolated replay ran after runtime ACL commit' }}
$moneyFactsAction = {{ throw 'money facts replayed after runtime ACL commit' }}
$targetSemanticAction = {{ throw 'semantic action replayed after runtime ACL commit' }}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $failure = $null
    $result = $null
    try {{
        $result = Invoke-TicketboxC07InstalledProductionLifecycle `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -RuntimePassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
            -Mode fresh_install `
            -ExpectedSourceRevision '20260722_0001' `
            -MigrationAction $migrationAction `
            -IsolatedReplayAction $isolatedReplayAction `
            -MoneyFactsAction $moneyFactsAction `
            -TargetSemanticAction $targetSemanticAction `
            -ExpectedOperationId '{operation_id}'
    }}
    catch {{ $failure = $_.Exception }}
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $production = Read-TicketboxC07ProductionAuthority $authority
    $runtimeAclEvidence = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage runtime_acl_verified
    if (
        [string]$production.PayloadSha256 -cne
            '{state["production_sha256"]}' -or
        [string]$runtimeAclEvidence.PayloadSha256 -cne
            '{state["runtime_acl_evidence_sha256"]}' -or
        [int64]$authority.Binding.Sequence -ne 1 -or
        $script:retiredRoleCatalogCalls -ne 1 -or
        (Test-Path -LiteralPath '{_literal(replay)}')
    ) {{
        throw 'takeover rewrote immutable runtime ACL/production lineage'
    }}
    $validationCount = @(
        Get-Content -LiteralPath '{_literal(validations)}'
    ).Count
    if ({'$true' if mutated else '$false'}) {{
        if (
            $null -eq $failure -or
            [string]$failure.Data['TicketboxC07FailureClass'] -cne 'invariant' -or
            [string]$failure.Data['TicketboxC07FailureCode'] -cne
                'runtime_acl_invariant_failed' -or
            [string]$authority.Receipt.stage -cne 'repair_required' -or
            $validationCount -ne 1
        ) {{
            throw 'mutated runtime ACL did not fail closed after takeover'
        }}
    }}
    else {{
        if (
            $null -ne $failure -or
            $result.result -cne 'ready' -or
            [string]$authority.Receipt.stage -cne 'ready' -or
            [int64]$authority.Receipt.stage_sequence -ne 9 -or
            [string]$authority.Receipt.previous_stage -cne
                'runtime_acl_verified' -or
            $validationCount -ne 1
        ) {{
            throw 'precommitted runtime ACL evidence did not converge to READY'
        }}
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
            )
            _run_harness(engine, resume_script)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows cross-process takeover")
def test_c07_live_old_process_rejected_and_dead_process_taken_over(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    for mode in ("alive", "dead", "crash"):
        root = tmp_path / mode
        prefix, data_root, _, _ = _common_harness(root)
        signal = root / "captured.signal"
        child_script = root / "child.ps1"
        ending = {
            "alive": (
                f"[IO.File]::WriteAllText('{_literal(signal)}', 'ready'); "
                "Start-Sleep -Seconds 30"
            ),
            "dead": f"[IO.File]::WriteAllText('{_literal(signal)}', 'ready')",
            "crash": (
                f"[IO.File]::WriteAllText('{_literal(signal)}', 'ready'); "
                "Stop-Process -Id $PID -Force"
            ),
        }[mode]
        _write_ps1(
            child_script,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
{ending}
""",
        )
        child = subprocess.Popen(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                child_script,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        _wait_for_path(signal, child)
        if mode != "alive":
            child.wait(timeout=15)

        resume = root / "resume.ps1"
        expected_rejection = "$true" if mode == "alive" else "$false"
        _write_ps1(
            resume,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
    try {{
        $rejected = $false
        $rejectionError = ''
        try {{
            $operation = New-TicketboxC07LifecycleOperation `
                -DataRoot '{_literal(data_root)}' `
                -LifecycleLock $lock `
                -SuperuserPassword $script:testPassword
        }}
        catch {{
            $rejected = $true
            $rejectionError = [string]$_
        }}
        if ($rejected -ne {expected_rejection}) {{
            throw "unexpected takeover disposition for {mode}: $rejectionError"
        }}
    if (-not $rejected -and [int64]$operation.CoordinatorBindingSequence -ne 1) {{
        throw 'dead coordinator was not resumed with one binding takeover'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        try:
            _run_harness(engine, resume)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows attempt commit recovery")
def test_c07_adopts_failure_file_committed_before_heartbeat_binding(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "failure-before-heartbeat"
    prefix, data_root, _, _ = _common_harness(root)
    signal = root / "failure-durable.signal"
    child_script = root / "failure-child.ps1"
    _write_ps1(
        child_script,
        prefix
        + f"""
$script:originalAttemptHeartbeatWriter =
    ${{function:Write-TicketboxC07MaintenanceAttemptHeartbeat}}
function Write-TicketboxC07MaintenanceAttemptHeartbeat {{
    param(
        $Authority,
        $CurrentHeartbeat,
        $Attempt,
        [string]$FailureSha256 = '',
        [switch]$ResetBudget
    )
    if (-not [string]::IsNullOrEmpty($FailureSha256)) {{
        [IO.File]::WriteAllText('{_literal(signal)}', $FailureSha256)
        Stop-Process -Id $PID -Force
    }}
    & $script:originalAttemptHeartbeatWriter @PSBoundParameters
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    New-TicketboxC07MaintenanceAttemptFailure `
        -Authority $authority `
        -LifecycleLock $lock `
        -Failure ([IO.IOException]::new('injected committed failure')) `
        -ActionKind 'recovery_generation' | Out-Null
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            child_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_path(signal, child)
    child.wait(timeout=15)
    resume = root / "failure-resume.ps1"
    _write_ps1(
        resume,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $heartbeat = Read-TicketboxC07Heartbeat $authority
    $attempt = Read-TicketboxC07MaintenanceAttempt `
        -Authority $authority `
        -AttemptId ([string]$heartbeat.Payload.maintenance_attempt_id) `
        -Sequence ([int]$heartbeat.Payload.maintenance_attempt_sequence) `
        -ExpectedPayloadSha256 (
            [string]$heartbeat.Payload.maintenance_attempt_sha256
        )
    if ([int64]$attempt.Payload.attempt_sequence -ne 2 -or
        [int64]$operation.CoordinatorBindingSequence -ne 1 -or
        [string]::IsNullOrEmpty(
            [string]$attempt.Payload.previous_attempt_failure_sha256
        )) {{
        throw 'committed failure was not linked into attempt generation two'
    }}
    $previousAttempt = Read-TicketboxC07MaintenanceAttempt `
        -Authority $authority `
        -AttemptId ([string]$attempt.Payload.previous_attempt_id) `
        -Sequence 1 `
        -ExpectedPayloadSha256 ([string]$attempt.Payload.previous_attempt_sha256)
    $failure = Read-TicketboxC07MaintenanceAttemptFailure `
        -Authority $authority `
        -Attempt $previousAttempt `
        -ExpectedPayloadSha256 (
            [string]$attempt.Payload.previous_attempt_failure_sha256
        )
    if ($failure.Payload.failure_code -cne 'maintenance_action_failed' -or
        $failure.Payload.action_kind -cne 'recovery_generation') {{
        throw 'recovery rewrote the immutable original failure diagnosis'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, resume)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows takeover commit recovery")
def test_c07_reconciles_takeover_receipt_committed_before_heartbeat(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "takeover-before-heartbeat"
    prefix, data_root, _, _ = _common_harness(root)
    initial = root / "initial.ps1"
    _write_ps1(
        initial,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, initial)
    signal = root / "takeover-receipt.signal"
    takeover = root / "takeover-child.ps1"
    _write_ps1(
        takeover,
        prefix
        + f"""
$script:originalHostEnvelopeWriter = ${{function:Write-TicketboxC07HostEnvelope}}
function Write-TicketboxC07HostEnvelope {{
    param(
        [string]$Path,
        [string]$ArtifactKind,
        [object]$Payload,
        [switch]$ReplaceExisting,
        [switch]$ReadCompareReuse
    )
    $result = & $script:originalHostEnvelopeWriter @PSBoundParameters
    if ($ArtifactKind -ceq 'authority_receipt' -and
        $ReplaceExisting -and
        [string]$Payload.transition_kind -ceq 'takeover') {{
        [IO.File]::WriteAllText('{_literal(signal)}', $result.PayloadSha256)
        Stop-Process -Id $PID -Force
    }}
    return $result
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            takeover,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_path(signal, child)
    child.wait(timeout=15)
    resume = root / "takeover-resume.ps1"
    _write_ps1(
        resume,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $heartbeat = Read-TicketboxC07Heartbeat $authority
    if ([int64]$operation.CoordinatorBindingSequence -ne 2 -or
        [int64]$heartbeat.Payload.coordinator_binding_sequence -ne 2 -or
        [string]$heartbeat.Payload.coordinator_binding_sha256 -cne
            [string]$authority.Binding.PayloadSha256 -or
        [int64]$heartbeat.Payload.maintenance_attempt_sequence -ne 2) {{
        throw 'orphan takeover receipt did not reconcile through one new generation'
    }}
    $binding = $authority.Binding.Payload
    if ($binding.schema -cne 'ticketbox-c07-coordinator-binding-v2' -or
        [string]::IsNullOrEmpty(
            [string]$binding.previous_heartbeat_payload_sha256
        ) -or
        [int64]$binding.previous_heartbeat_sequence -lt 1) {{
        throw 'takeover generation omitted the precommitted heartbeat predecessor'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, resume)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows attempt precommit recovery")
def test_c07_adopts_attempt_file_committed_before_heartbeat_binding(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "attempt-before-heartbeat"
    prefix, data_root, _, _ = _common_harness(root)
    signal = root / "attempt-durable.signal"
    child_script = root / "attempt-child.ps1"
    _write_ps1(
        child_script,
        prefix
        + f"""
$script:originalAttemptHeartbeatWriter =
    ${{function:Write-TicketboxC07MaintenanceAttemptHeartbeat}}
function Write-TicketboxC07MaintenanceAttemptHeartbeat {{
    param(
        $Authority,
        $CurrentHeartbeat,
        $Attempt,
        [string]$FailureSha256 = '',
        [switch]$ResetBudget
    )
    if ($ResetBudget -and [string]::IsNullOrEmpty($FailureSha256)) {{
        $signalValue = @(
            [string]$Attempt.Path,
            [string]$Attempt.Payload.attempt_id,
            [string]$Attempt.PayloadSha256,
            [string]$Attempt.Payload.deadline_utc
        ) -join '|'
        [IO.File]::WriteAllText('{_literal(signal)}', $signalValue)
        while ($true) {{ Start-Sleep -Milliseconds 200 }}
    }}
    & $script:originalAttemptHeartbeatWriter @PSBoundParameters
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            child_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_path(signal, child)
    committed = signal.read_text(encoding="utf-8").split("|")
    assert len(committed) == 4
    committed_path, attempt_id, attempt_sha256, deadline_utc = committed
    assert Path(committed_path).is_file()
    time.sleep(1.4)
    child.kill()
    child.wait(timeout=15)

    resume = root / "attempt-resume.ps1"
    _write_ps1(
        resume,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $heartbeat = Read-TicketboxC07Heartbeat $authority
    $attempt = Read-TicketboxC07MaintenanceAttempt `
        -Authority $authority `
        -AttemptId ([string]$heartbeat.Payload.maintenance_attempt_id) `
        -Sequence ([int]$heartbeat.Payload.maintenance_attempt_sequence) `
        -ExpectedPayloadSha256 (
            [string]$heartbeat.Payload.maintenance_attempt_sha256
        )
    if (
        [int64]$heartbeat.Payload.maintenance_attempt_sequence -ne 1 -or
        [string]$attempt.Payload.attempt_id -cne '{attempt_id}' -or
        [string]$attempt.PayloadSha256 -cne '{attempt_sha256}' -or
        [string]$attempt.Payload.deadline_utc -cne '{deadline_utc}' -or
        [int64]$heartbeat.Payload.maintenance_remaining_ceiling_ms -ge 1199000 -or
        -not [string]::IsNullOrEmpty(
            [string]$heartbeat.Payload.maintenance_attempt_failure_sha256
        )
    ) {{
        throw 'precommitted attempt was replaced or its budget was reissued'
    }}
    $operationId = [string]$authority.Receipt.operation_id
    $pattern = '^op-' + [regex]::Escape($operationId) +
        '-a-[0-9a-f-]{{36}}\\.json$'
    $attemptFiles = @(
        Get-ChildItem `
            -LiteralPath (Split-Path -Parent '{_literal(Path(committed_path))}') `
            -Force |
            Where-Object {{ [string]$_.Name -cmatch $pattern }}
    )
    if ($attemptFiles.Count -ne 1 -or
        [string]$attemptFiles[0].FullName -cne '{_literal(Path(committed_path))}') {{
        throw 'precommitted attempt recovery created a fork/orphan file'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, resume)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows attempt fork rejection")
def test_c07_rejects_multiple_precommitted_attempt_candidates(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "attempt-fork"
    prefix, data_root, _, _ = _common_harness(root)
    signal = root / "attempt-fork.signal"
    child_script = root / "attempt-fork-child.ps1"
    _write_ps1(
        child_script,
        prefix
        + f"""
$script:originalAttemptHeartbeatWriter =
    ${{function:Write-TicketboxC07MaintenanceAttemptHeartbeat}}
function Write-TicketboxC07MaintenanceAttemptHeartbeat {{
    param(
        $Authority,
        $CurrentHeartbeat,
        $Attempt,
        [string]$FailureSha256 = '',
        [switch]$ResetBudget
    )
    if ($ResetBudget -and [string]::IsNullOrEmpty($FailureSha256)) {{
        [IO.File]::WriteAllText('{_literal(signal)}', [string]$Attempt.Path)
        while ($true) {{ Start-Sleep -Milliseconds 200 }}
    }}
    & $script:originalAttemptHeartbeatWriter @PSBoundParameters
}}
$lock = Enter-TicketboxLifecycleLock -FullControlAccounts @($currentAccount) -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation -DataRoot '{_literal(data_root)}' -LifecycleLock $lock -SuperuserPassword $script:testPassword | Out-Null
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            child_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_path(signal, child)
        original_attempt_path = Path(signal.read_text(encoding="utf-8"))
        assert original_attempt_path.is_file()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)

    reject = root / "attempt-fork-reject.ps1"
    _write_ps1(
        reject,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock -FullControlAccounts @($currentAccount) -OwnerAccount $currentAccount
try {{
    $originalEnvelope = Read-TicketboxC07HostEnvelope -Path '{_literal(original_attempt_path)}' -ExpectedKind 'maintenance_attempt'
    $forkId = [guid]::NewGuid().ToString('D')
    $forkPayload = [ordered]@{{}}
    foreach ($property in $originalEnvelope.Payload.PSObject.Properties) {{
        $forkPayload[[string]$property.Name] = $property.Value
    }}
    $forkPayload.attempt_id = $forkId
    $forkPath = Get-TicketboxC07MaintenanceAttemptPath -OperationId ([string]$forkPayload.operation_id) -AttemptId $forkId
    Write-TicketboxC07HostEnvelope -Path $forkPath -ArtifactKind 'maintenance_attempt' -Payload $forkPayload | Out-Null
    $caught = $null
    try {{
        New-TicketboxC07LifecycleOperation -DataRoot '{_literal(data_root)}' -LifecycleLock $lock -SuperuserPassword $script:testPassword | Out-Null
    }}
    catch {{ $caught = $_.Exception }}
    if (
        $null -eq $caught -or
        [string]$caught.Data['TicketboxC07FailureClass'] -cne 'invariant' -or
        [string]$caught.Data['TicketboxC07FailureCode'] -cne
            'authority_chain_mismatch'
    ) {{
        throw 'multiple precommitted attempts did not fail closed as invariant'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, reject)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows attempt exhaustion")
def test_c07_attempt_exhaustion_commits_terminal_without_new_budget(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "attempt-exhaustion"
    prefix, data_root, _, _ = _common_harness(root)
    harness = root / "attempt-exhaustion.ps1"
    _write_ps1(
        harness,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock -FullControlAccounts @($currentAccount) -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation -DataRoot '{_literal(data_root)}' -LifecycleLock $lock -SuperuserPassword $script:testPassword | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $before = Read-TicketboxC07Heartbeat $authority
    New-TicketboxC07MaintenanceAttemptFailure -Authority $authority -LifecycleLock $lock -Failure ([IO.IOException]::new('attempt exhausted test')) -ActionKind 'recovery_generation' | Out-Null
    $failedHeartbeat = Read-TicketboxC07Heartbeat $authority
    $script:TicketboxC07MaximumMaintenanceAttempts = 1
    $result = New-TicketboxC07LifecycleOperation -DataRoot '{_literal(data_root)}' -LifecycleLock $lock -SuperuserPassword $script:testPassword
    $terminal = Read-TicketboxC07Authority '{_literal(data_root)}'
    $projection = Read-TicketboxC07RuntimeProjection '{_literal(data_root)}'
    $after = Read-TicketboxC07Heartbeat $terminal
    if (
        [string]$result.Stage -cne 'refused_pre_ddl' -or
        [string]$terminal.Receipt.stage -cne 'refused_pre_ddl' -or
        [string]$terminal.Receipt.failure_code -cne
            'maintenance_attempts_exhausted' -or
        [string]$projection.Payload.stage -cne 'refused_pre_ddl' -or
        -not [bool]$projection.Payload.terminal -or
        [bool]$projection.Payload.ready -or
        [int64]$after.Payload.maintenance_attempt_sequence -ne 1 -or
        [string]$after.Payload.maintenance_attempt_id -cne
            [string]$before.Payload.maintenance_attempt_id -or
        [string]$after.Payload.maintenance_attempt_sha256 -cne
            [string]$before.Payload.maintenance_attempt_sha256 -or
        [string]$after.Payload.maintenance_attempt_failure_sha256 -cne
            [string]$failedHeartbeat.Payload.maintenance_attempt_failure_sha256
    ) {{
        throw 'attempt exhaustion did not commit one auditable terminal'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows recovery takeover contract")
def test_c07_takeover_reuses_generation_published_before_stage_receipt(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path_factory.mktemp("c07-generation-resume")
    pending_operation_id = "123e4567-e89b-42d3-a456-4266141740ac"
    prefix, data_root, _, _ = _common_harness(
        root,
        pending_operation_id=pending_operation_id,
    )
    signal = root / "generation-ready.json"
    child_script = root / "generation-child.ps1"
    _write_ps1(
        child_script,
        prefix
        + _recovery_combo_support()
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{pending_operation_id}'
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $generation = New-TestC07ReadyGeneration $authority
    $state = [ordered]@{{
        operation_id = [string]$operation.OperationId
        manifest_sha256 = [string]$generation.PayloadSha256
        generation_authority_chain_sha256 =
            [string]$generation.Payload.lifecycle.authority_chain_sha256
        generation_freeze_proof_sha256 =
            [string]$generation.Payload.lifecycle.freeze_proof_sha256
    }}
    [IO.File]::WriteAllText(
        '{_literal(signal)}',
        ($state | ConvertTo-Json -Compress),
        [Text.UTF8Encoding]::new($false)
    )
    Stop-Process -Id $PID -Force
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            child_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_path(signal, child)
    child.wait(timeout=15)
    state = json.loads(signal.read_text(encoding="utf-8"))

    resume = root / "generation-resume.ps1"
    _write_ps1(
        resume,
        prefix
        + _recovery_combo_support()
        + f"""
$script:testServiceStartPolicy = 'disabled'
$script:testPublicConnect = $false
Set-TestC07FenceRolesFenced
$script:moneyFactsCalls = 0
function Renew-TicketboxC07RoleCredentialWindow {{}}
$moneyFactsAction = {{
    param(
        $HostAuthority,
        $Password,
        $Database,
        $OperationId,
        $SnapshotId,
        $ExpectedRevision,
        $MaintenanceDeadlineUtc,
        $MaintenanceRemainingCeilingMs,
        $MaintenanceAuthoritySha256,
        $PgpassPath
    )
    $script:moneyFactsCalls += 1
    return [pscustomobject][ordered]@{{
        schema = 'ticketbox-c07-money-facts-result-v2'
        operation_id = $OperationId
        database = $Database
        snapshot_id = $SnapshotId
        maintenance_authority_sha256 =
            $MaintenanceAuthoritySha256.ToLowerInvariant()
        maintenance_remaining_ceiling_ms =
            [int]$MaintenanceRemainingCeilingMs
        alembic_revision = $ExpectedRevision
        money_facts_sha256 = ('7' * 64)
    }}
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{state["operation_id"]}'
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $previousBudget = $script:TicketboxC07ActiveMaintenanceBudget
    try {{
        $script:TicketboxC07ActiveMaintenanceBudget =
            New-TicketboxC07MaintenanceBudget $authority
        $reused = Invoke-TicketboxC07RecoveryGeneration `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -ExpectedSourceRevision '20260722_0001' `
            -MoneyFactsAction $moneyFactsAction
    }}
    finally {{
        $script:TicketboxC07ActiveMaintenanceBudget = $previousBudget
    }}
    Set-TicketboxC07InstalledStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage recovery_generation_ready `
        -SubjectSha256 (
            ([string]$reused.EvidenceSha256).ToUpperInvariant()
        ) | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $context = New-TestC07RecoveryContext $authority
    $generation = Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    $evidence = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage recovery_generation_ready
    $producer = ([string]$evidence.Payload.producer_payload_json) |
        ConvertFrom-Json
    if (
        -not [bool]$reused.Reused -or
        [string]$authority.Receipt.stage -cne 'recovery_generation_ready' -or
        [string]$generation.PayloadSha256 -cne '{state["manifest_sha256"]}' -or
        [string]$generation.Payload.lifecycle.authority_chain_sha256 -cne
            '{state["generation_authority_chain_sha256"]}' -or
        [string]$generation.Payload.lifecycle.freeze_proof_sha256 -cne
            '{state["generation_freeze_proof_sha256"]}' -or
        [string]$authority.Receipt.freeze_proof_sha256 -ceq
            '{state["generation_freeze_proof_sha256"]}' -or
        [string]$producer.subject_sha256 -cne
            ('{state["manifest_sha256"]}').ToUpperInvariant() -or
        $script:moneyFactsCalls -ne 1 -or
        $script:liveSourceChecks -lt 1
    ) {{
        throw 'takeover did not reuse the immutable READY generation'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, resume, timeout=90)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows recovery takeover contract")
def test_c07_takeover_reuses_restore_evidence_before_stage_receipt(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path_factory.mktemp("c07-restore-resume")
    pending_operation_id = "123e4567-e89b-42d3-a456-4266141740ad"
    prefix, data_root, _, _ = _common_harness(
        root,
        pending_operation_id=pending_operation_id,
    )
    signal = root / "restore-ready.json"
    child_script = root / "restore-child.ps1"
    _write_ps1(
        child_script,
        prefix
        + _recovery_combo_support()
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{pending_operation_id}'
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $generation = New-TestC07ReadyGeneration $authority
    Set-TicketboxC07InstalledStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage recovery_generation_ready `
        -SubjectSha256 (
            ([string]$generation.PayloadSha256).ToUpperInvariant()
        ) | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $context = New-TestC07RecoveryContext $authority
    $generation = Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    $restore = New-TestC07DurableRestoreEvidence `
        -Context $context `
        -Generation $generation
    $state = [ordered]@{{
        operation_id = [string]$operation.OperationId
        manifest_sha256 = [string]$generation.PayloadSha256
        restore_evidence_sha256 = [string]$restore.PayloadSha256
        generation_freeze_proof_sha256 =
            [string]$generation.Payload.lifecycle.freeze_proof_sha256
    }}
    [IO.File]::WriteAllText(
        '{_literal(signal)}',
        ($state | ConvertTo-Json -Compress),
        [Text.UTF8Encoding]::new($false)
    )
    Stop-Process -Id $PID -Force
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            child_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_path(signal, child)
    child.wait(timeout=15)
    state = json.loads(signal.read_text(encoding="utf-8"))

    resume = root / "restore-resume.ps1"
    _write_ps1(
        resume,
        prefix
        + _recovery_combo_support()
        + f"""
$script:testServiceStartPolicy = 'disabled'
$script:testPublicConnect = $false
Set-TestC07FenceRolesFenced
$script:forwardReplayCalls = 0
function Renew-TicketboxC07RoleCredentialWindow {{}}
$forwardReplayAction = {{
    $script:forwardReplayCalls += 1
    throw 'durable restore evidence was not reused'
}}
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword `
        -ExpectedOperationId '{state["operation_id"]}'
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $previousBudget = $script:TicketboxC07ActiveMaintenanceBudget
    try {{
        $script:TicketboxC07ActiveMaintenanceBudget =
            New-TicketboxC07MaintenanceBudget $authority
        $reused = Test-TicketboxC07RecoveryGenerationRestore `
            -DataRoot '{_literal(data_root)}' `
            -LifecycleLock $lock `
            -SuperuserPassword $script:testPassword `
            -MigratorPassword $script:testPassword `
            -ExpectedSourceRevision '20260722_0001' `
            -TargetRevision '20260729_0001' `
            -ForwardReplayAction $forwardReplayAction
    }}
    finally {{
        $script:TicketboxC07ActiveMaintenanceBudget = $previousBudget
    }}
    $restoreSubject =
        ('{state["restore_evidence_sha256"]}').ToUpperInvariant()
    Set-TicketboxC07InstalledStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage isolated_restore_verified `
        -SubjectSha256 $restoreSubject | Out-Null
    Set-TicketboxC07InstalledStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage ddl_started `
        -SubjectSha256 $restoreSubject | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $context = New-TestC07RecoveryContext $authority
    $generation = Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    $restore = Read-TicketboxC07RecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    $isolated = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage isolated_restore_verified
    $ddl = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage ddl_started
    $isolatedProducer =
        ([string]$isolated.Payload.producer_payload_json) | ConvertFrom-Json
    $ddlProducer =
        ([string]$ddl.Payload.producer_payload_json) | ConvertFrom-Json
    if (
        -not [bool]$reused.Reused -or
        [string]$authority.Receipt.stage -cne 'ddl_started' -or
        [string]$generation.PayloadSha256 -cne '{state["manifest_sha256"]}' -or
        [string]$restore.PayloadSha256 -cne
            '{state["restore_evidence_sha256"]}' -or
        [string]$authority.Receipt.freeze_proof_sha256 -ceq
            '{state["generation_freeze_proof_sha256"]}' -or
        [string]$isolatedProducer.subject_sha256 -cne $restoreSubject -or
        [string]$ddlProducer.subject_sha256 -cne $restoreSubject -or
        $script:forwardReplayCalls -ne 0 -or
        $script:liveSourceChecks -lt 1 -or
        (Test-Path -LiteralPath $context.Paths.RestoreIdentityPath) -or
        (Test-Path -LiteralPath $context.Paths.RestoreCreateIntentPath)
    ) {{
        throw 'takeover did not reuse durable restore evidence through ddl_started'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, resume, timeout=90)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows stage takeover lineage")
def test_c07_writer_window_takeover_refreshes_generation_proof(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    root = tmp_path / "writer-window"
    prefix, data_root, _, _ = _common_harness(root)
    signal = root / "recovery-stage.json"
    child_script = root / "child-window.ps1"
    _write_ps1(
        child_script,
        prefix
        + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword | Out-Null
    Write-TicketboxC07Heartbeat `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock | Out-Null
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage writers_frozen | Out-Null
    $evidence = New-TestC07StageEvidence `
        -Stage recovery_generation_ready `
        -LifecycleLock $lock `
        -DataRoot '{_literal(data_root)}'
    Set-TicketboxC07LifecycleStage `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -TargetStage recovery_generation_ready `
        -EvidencePath $evidence.Path | Out-Null
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $generation = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage recovery_generation_ready
    $state = [ordered]@{{
        recovery_evidence_sha256 = $generation.PayloadSha256
        root_authority_chain_sha256 =
            [string]$generation.Payload.source_authority_chain_sha256
        freeze_proof_sha256 = [string]$authority.Receipt.freeze_proof_sha256
        recovery_authority_chain_sha256 =
            [string]$authority.Receipt.authority_chain_sha256
    }}
    [IO.File]::WriteAllText(
        '{_literal(signal)}',
        ($state | ConvertTo-Json -Compress),
        (New-Object Text.UTF8Encoding($false))
    )
    Stop-Process -Id $PID -Force
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    child = subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            child_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_path(signal, child)
    child.wait(timeout=15)
    old_state = json.loads(signal.read_text(encoding="utf-8"))

    resume = root / "resume-window.ps1"
    _write_ps1(
        resume,
        prefix
        + f"""
$script:testServiceStartPolicy = 'disabled'
$script:testPublicConnect = $false
Set-TestC07FenceRolesFenced
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $operation = New-TicketboxC07LifecycleOperation `
        -DataRoot '{_literal(data_root)}' `
        -LifecycleLock $lock `
        -SuperuserPassword $script:testPassword
    $authority = Read-TicketboxC07Authority '{_literal(data_root)}'
    $generation = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage recovery_generation_ready
    $proof = Read-TicketboxC07FreezeProof $authority
    $current = Get-TicketboxProcessIdentity -ProcessId $PID
    if ($operation.Stage -cne 'recovery_generation_ready' -or
        [int64]$operation.CoordinatorBindingSequence -ne 1 -or
        [string]$authority.Receipt.previous_stage -cne 'writers_frozen' -or
        [int64]$authority.Receipt.stage_sequence -ne 2 -or
        [int64]$authority.Receipt.coordinator_binding_sequence -ne 1 -or
        [int64]$authority.Receipt.freeze_proof_binding_sequence -ne 1 -or
        [string]$authority.Receipt.freeze_proof_sha256 -ceq
            '{old_state["freeze_proof_sha256"]}' -or
        [string]$generation.PayloadSha256 -cne
            '{old_state["recovery_evidence_sha256"]}' -or
        [string]$generation.Payload.source_authority_chain_sha256 -cne
            '{old_state["root_authority_chain_sha256"]}' -or
        [string]$authority.Receipt.transition_evidence_sha256 -cne
            '{old_state["recovery_evidence_sha256"]}' -or
        [string]$proof.Payload.coordinator_binding_sha256 -cne
            [string]$authority.Binding.PayloadSha256 -or
        [int]$proof.Payload.coordinator_pid -ne $PID -or
        [uint32]$proof.Payload.coordinator_started_filetime_high -ne
            [uint32]$current.StartedFileTimeHigh -or
        [uint32]$proof.Payload.coordinator_started_filetime_low -ne
            [uint32]$current.StartedFileTimeLow) {{
        throw 'writer-window takeover did not refresh exact generation lineage'
    }}
    $initialPath = Get-TicketboxC07FreezeProofPath `
        -OperationId ([string]$authority.Receipt.operation_id) `
        -BindingSequence 0
    $takeoverPath = Get-TicketboxC07FreezeProofPath `
        -OperationId ([string]$authority.Receipt.operation_id) `
        -BindingSequence 1
    $initial = Read-TicketboxC07HostEnvelope `
        -Path $initialPath `
        -ExpectedKind freeze_proof
    if (-not (Test-Path -LiteralPath $takeoverPath -PathType Leaf) -or
        $initial.PayloadSha256 -cne '{old_state["freeze_proof_sha256"]}' -or
        $initial.PayloadSha256 -ceq $proof.PayloadSha256) {{
        throw 'takeover overwrote or reused the old freeze proof'
    }}
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
    )
    _run_harness(engine, resume)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL 17 fence")
def test_c07_real_pg17_fence_evicts_session_and_blocks_ordinary_write(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    storage_contract = BACKEND / "scripts" / "test_pg_storage_contract.ps1"
    start_script = BACKEND / "scripts" / "start_test_pg.ps1"
    stop_script = BACKEND / "scripts" / "stop_test_pg.ps1"
    auth_contract = BACKEND / "scripts" / "test_pg_auth_contract.ps1"
    root_command = (
        f". '{_literal(storage_contract)}'; "
        "(Initialize-XpjTestPostgresRuntimeRoot) | ConvertTo-Json -Compress"
    )
    root_result = subprocess.run(
        [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", root_command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
    )
    assert root_result.returncode == 0, root_result.stdout + root_result.stderr
    protected_root = Path(json.loads(root_result.stdout.strip().splitlines()[-1]))
    data_dir = protected_root / f"xpj_pg_c07_fence_{uuid.uuid4().hex}"
    port = _free_loopback_port()
    started = _run_powershell_process(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(start_script),
            "-Port",
            str(port),
            "-DataDir",
            str(data_dir),
        ],
        timeout=60,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    runtime_session: subprocess.Popen[str] | None = None
    try:
        bin_command = (
            f". '{_literal(storage_contract)}'; "
            "[string](Find-XpjPostgresBin)"
        )
        bin_result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", bin_command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert bin_result.returncode == 0, bin_result.stdout + bin_result.stderr
        pg_bin = Path(bin_result.stdout.strip().splitlines()[-1])
        psql = pg_bin / "psql.exe"
        credential = (data_dir / ".xpj-test-postgres-password").read_text(
            encoding="utf-8"
        ).strip()
        admin_env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("PG")
        }
        admin_env["PGPASSFILE"] = str(data_dir / ".xpj-test-postgres.pgpass")

        def run_sql(
            database: str,
            role: str,
            sql: str,
            *,
            runtime_password: bool = False,
        ) -> subprocess.CompletedProcess[str]:
            environment = dict(admin_env)
            if runtime_password:
                environment.pop("PGPASSFILE", None)
                environment["PGPASSWORD"] = credential
            return subprocess.run(
                [
                    str(psql),
                    "--no-psqlrc",
                    "--no-password",
                    "--tuples-only",
                    "--no-align",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--host",
                    "localhost",
                    "--port",
                    str(port),
                    "--username",
                    role,
                    "--dbname",
                    database,
                    "--command",
                    sql,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=20,
            )

        setup_role = run_sql(
            "postgres",
            "postgres",
            (
                'CREATE ROLE "ticketbox" LOGIN NOSUPERUSER NOCREATEDB '
                f"NOCREATEROLE PASSWORD '{credential}';"
            ),
        )
        assert setup_role.returncode == 0, setup_role.stdout + setup_role.stderr
        setup_database = run_sql(
            "postgres",
            "postgres",
            'CREATE DATABASE "ticketbox" OWNER "postgres";',
        )
        assert setup_database.returncode == 0, (
            setup_database.stdout + setup_database.stderr
        )
        fence_test_infrastructure_role = run_sql(
            "postgres",
            "postgres",
            'ALTER ROLE "xpj_test_app" NOLOGIN CONNECTION LIMIT 0;',
        )
        assert fence_test_infrastructure_role.returncode == 0, (
            fence_test_infrastructure_role.stdout
            + fence_test_infrastructure_role.stderr
        )
        setup_table = run_sql(
            "ticketbox",
            "postgres",
            (
                "CREATE TABLE public.writer_probe(value integer NOT NULL); "
                'GRANT CONNECT ON DATABASE "ticketbox" TO "ticketbox"; '
                'GRANT USAGE ON SCHEMA public TO "ticketbox"; '
                'GRANT INSERT, SELECT ON TABLE public.writer_probe TO "ticketbox";'
            ),
        )
        assert setup_table.returncode == 0, setup_table.stdout + setup_table.stderr
        before_write = run_sql(
            "ticketbox",
            "ticketbox",
            "INSERT INTO public.writer_probe(value) VALUES (1);",
            runtime_password=True,
        )
        assert before_write.returncode == 0, before_write.stdout + before_write.stderr

        runtime_env = {
            key: value for key, value in admin_env.items() if key != "PGPASSFILE"
        }
        runtime_env["PGPASSWORD"] = credential
        runtime_session = subprocess.Popen(
            [
                str(psql),
                "--no-psqlrc",
                "--no-password",
                "--set",
                "ON_ERROR_STOP=1",
                "--host",
                "localhost",
                "--port",
                str(port),
                "--username",
                "ticketbox",
                "--dbname",
                "ticketbox",
                "--command",
                "SELECT pg_sleep(30);",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_env,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            sessions = run_sql(
                "ticketbox",
                "postgres",
                (
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE usename = 'ticketbox' AND pid <> pg_backend_pid();"
                ),
            )
            assert sessions.returncode == 0, sessions.stdout + sessions.stderr
            if sessions.stdout.strip() == "1":
                break
            time.sleep(0.1)
        else:
            raise AssertionError("runtime PostgreSQL session did not become observable")

        harness = tmp_path / "real-pg-fence.ps1"
        _write_ps1(
            harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    return [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{
    param($Authority, $SuperuserPassword)
}}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$release = [pscustomobject]@{{}}
$authority = [pscustomobject]@{{ ReleaseIdentity = $release }}
$before = Get-TicketboxC07WriterDatabaseFenceObservation $release
if ([int64]$before.OtherClientSessionCount -ne 1) {{
    throw 'real runtime session was not observed before fence'
}}
$intent = [pscustomobject]@{{
    Payload = [pscustomobject]@{{
        public_connect = [bool]$before.PublicConnect
        roles = @($before.Roles)
    }}
}}
$after = Enter-TicketboxC07WriterDatabaseFence `
    -Authority $authority `
    -Intent $intent
Assert-TicketboxC07WriterDatabaseFence `
    -Observation $after `
    -ExpectedRoles @($before.Roles)
if ([int64]$after.OtherClientSessionCount -ne 0) {{
    throw 'real runtime session survived durable fence'
}}
""",
        )
        _run_harness(engine, harness, timeout=40)
        _, session_stderr = runtime_session.communicate(timeout=10)
        assert runtime_session.returncode != 0, session_stderr
        runtime_session = None

        rejected_write = run_sql(
            "ticketbox",
            "ticketbox",
            "INSERT INTO public.writer_probe(value) VALUES (2);",
            runtime_password=True,
        )
        assert rejected_write.returncode != 0
        post_count = run_sql(
            "ticketbox",
            "postgres",
            "SELECT count(*) FROM public.writer_probe;",
        )
        assert post_count.returncode == 0, post_count.stdout + post_count.stderr
        assert post_count.stdout.strip() == "1"
        pg17 = run_sql(
            "postgres",
            "postgres",
            "SELECT current_setting('server_version_num')::integer / 10000;",
        )
        assert pg17.returncode == 0, pg17.stdout + pg17.stderr
        assert pg17.stdout.strip() == "17"
    finally:
        if runtime_session is not None:
            runtime_session.kill()
            runtime_session.communicate(timeout=10)
        stopped = _run_powershell_process(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(stop_script),
                "-Port",
                str(port),
                "-DataDir",
                str(data_dir),
            ],
            timeout=60,
        )
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
