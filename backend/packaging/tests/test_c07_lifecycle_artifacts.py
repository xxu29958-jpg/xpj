from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
SUBJECT_SHA256 = "A" * 64
LOWER_SUBJECT_SHA256 = "a" * 64


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^function {re.escape(name)}(?=\s*(?:\{{|\())",
        source,
    )
    if match is None:
        raise ValueError(f"missing function boundary for {name}")
    start = match.start()
    next_function = source.find("\nfunction ", start + 1)
    return source[start:] if next_function < 0 else source[start:next_function]


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
    source = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (
            PACKAGING / "postgresql_writer_fence" / "primitives.ps1",
            PACKAGING / "postgresql_writer_fence" / "observation_query.ps1",
            PACKAGING / "postgresql_writer_fence" / "precondition_guard.ps1",
            PACKAGING / "postgresql_writer_fence" / "session_drain.ps1",
            PACKAGING / "postgresql_writer_fence" / "reconciler.ps1",
            PACKAGING / "c07_lifecycle" / "writer_fence" / "policy.ps1",
            PACKAGING / "c07_lifecycle" / "writer_fence" / "adapter.ps1",
        )
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
        "owns_security_definer_routines",
        "can_execute_unowned_security_definer_routines",
    ):
        assert required in source
    assert '"--quiet",' in database_source
    assert "pg_terminate_backend(\n                fence_pid," in source
    assert "$TerminationTimeoutMilliseconds" in source
    assert "database_lock.locktype = 'object'" in source
    assert "database_lock.classid = 'pg_database'::regclass::oid" in source
    assert "Enter-TicketboxC07CurrentWriterDatabaseFence" in source


def test_c07_whole_operation_deadline_is_monotonic_and_durable() -> None:
    source = (
        PACKAGING / "windows_deadline_budget.ps1"
    ).read_text(encoding="utf-8-sig") + (
        PACKAGING / "windows_c07_heartbeat_authority.ps1"
    ).read_text(encoding="utf-8-sig") + (
        PACKAGING / "windows_c07_lifecycle.ps1"
    ).read_text(encoding="utf-8-sig")

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
        "Get-TicketboxWindowsDeadlineRemainingMilliseconds",
        "Get-TicketboxBoundedDeadlineUtc",
    ):
        assert required in source

    assert "$CurrentTickCount64 -lt $StartedTickCount64" in source
    assert "$remainingCeiling = [Math]::Min(" in source
    assert "$requested -lt $ceiling" in source


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
$script:TicketboxC07LegacyRuntimeRole = 'ticketbox'
$script:TicketboxC07OwnerRole = 'ticketbox_owner'
$script:TicketboxC07MigratorRole = 'ticketbox_migrator'
$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'
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
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $false
        effective_connect = $true
        can_database_create = $true
        can_public_schema_create = $true
        can_table_write = $true
        can_sequence_write = $true
        can_assume_write_owner = $true
        predefined_role_usage = @()
        predefined_role_set = @()
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
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $false
        effective_connect = $EffectiveConnect
        can_database_create = $false
        can_public_schema_create = $false
        can_table_write = $true
        can_sequence_write = $true
        can_assume_write_owner = $false
        predefined_role_usage = @()
        predefined_role_set = @()
    }}
}}
function New-TestC07ManagedMigratorRole {{
    param([bool]$Retired = $false)
    $role = [pscustomobject][ordered]@{{
        name = 'ticketbox_migrator'
        oid = [int64]902
        disposition = $(if ($Retired) {{
            'retired_migration_authority'
        }} else {{ 'migration_authority' }})
        can_login = -not $Retired
        connection_limit = $(if ($Retired) {{ 0 }} else {{ -1 }})
        is_superuser = $false
        can_create_db = $false
        can_create_role = $false
        can_replicate = $false
        can_bypass_rls = $false
        is_database_owner = $false
        owns_public_schema = $false
        owns_user_relations = $false
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = -not $Retired
        effective_connect = -not $Retired
        can_database_create = $false
        can_public_schema_create = $false
        can_table_write = $false
        can_sequence_write = $false
        can_assume_write_owner = -not $Retired
        predefined_role_usage = @()
        predefined_role_set = @('pg_database_owner')
    }}
    if ($Retired) {{ $role.predefined_role_set = [object[]]@() }}
    return $role
}}
function New-TestC07OwnerRole {{
    return [pscustomobject][ordered]@{{
        name = 'ticketbox_owner'
        oid = [int64]903
        disposition = 'nologin_owner'
        can_login = $false
        connection_limit = 0
        is_superuser = $false
        can_create_db = $false
        can_create_role = $false
        can_replicate = $false
        can_bypass_rls = $false
        is_database_owner = $true
        owns_public_schema = $true
        owns_user_relations = $true
        owns_security_definer_routines = $true
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $false
        effective_connect = $true
        can_database_create = $true
        can_public_schema_create = $true
        can_table_write = $true
        can_sequence_write = $true
        can_assume_write_owner = $false
        predefined_role_usage = @('pg_database_owner')
        predefined_role_set = @('pg_database_owner')
    }}
}}
function New-TestC07ManagedRuntimeRole {{
    param([bool]$Published = $false)
    return [pscustomobject][ordered]@{{
        name = 'ticketbox_runtime'
        oid = [int64]904
        disposition = $(if ($Published) {{ 'published_runtime' }} else {{ 'fenced_runtime' }})
        can_login = $Published
        connection_limit = $(if ($Published) {{ -1 }} else {{ 0 }})
        is_superuser = $false
        can_create_db = $false
        can_create_role = $false
        can_replicate = $false
        can_bypass_rls = $false
        is_database_owner = $false
        owns_public_schema = $false
        owns_user_relations = $false
        owns_security_definer_routines = $false
        can_execute_unowned_security_definer_routines = $false
        direct_connect = $Published
        effective_connect = $Published
        can_database_create = $false
        can_public_schema_create = $false
        can_table_write = $true
        can_sequence_write = $true
        can_assume_write_owner = $false
        predefined_role_usage = @()
        predefined_role_set = @()
    }}
}}
function New-TestC07PublishedRoleSet {{
    return @(
        New-TestC07DatabaseAuthorityRole
        New-TestC07ManagedMigratorRole -Retired $true
        New-TestC07OwnerRole
        New-TestC07ManagedRuntimeRole -Published $true
    )
}}
function Set-TestC07FenceRolesFenced {{
    $script:testFenceRoles = @(
        New-TestC07DatabaseAuthorityRole
        New-TestC07ManagedMigratorRole
        New-TestC07OwnerRole
        New-TestC07ManagedRuntimeRole
    )
}}
$script:testFenceRoles = @(
    New-TestC07DatabaseAuthorityRole
    New-TestC07ManagedMigratorRole
    New-TestC07OwnerRole
    New-TestC07ManagedRuntimeRole -Published $true
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
function Get-TicketboxC07DatabaseCatalogObservation {{
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
    param([string]$AuthorityPhase = 'managed_frozen')
    if ([string]::IsNullOrEmpty($AuthorityPhase)) {{
        $AuthorityPhase = 'managed_frozen'
    }}
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
    $roles = if ($AuthorityPhase -ceq 'published_runtime') {{
        @(New-TestC07PublishedRoleSet)
    }} else {{ @($script:testFenceRoles) }}
    return [pscustomobject]@{{
        AuthorityPhase = $AuthorityPhase
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
        Roles = @($roles)
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
    $observation = Get-TicketboxC07WriterDatabaseFenceObservation `
        -AuthorityPhase ([string]$Intent.Payload.authority_phase)
    Assert-TicketboxC07WriterDatabaseFence `
        -Observation $observation
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
$script:testLifecycleLockPath = Get-TicketboxLifecycleLockPath
function Get-TicketboxLifecycleLockPath {{
    # The isolated harness root was already created and ACL-validated above.
    # Keep its exact path stable for this process instead of repeating that
    # unrelated installation-safety ceremony for every C07 artifact lookup.
    return $script:testLifecycleLockPath
}}
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows C07 artifact contract")
@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_historical_v3_intent_is_evidence_and_new_ready_pins_role_oid(
    tmp_path: Path,
    engine: str,
) -> None:
    root = tmp_path / f"historical-v3-{Path(engine).stem}"
    prefix, _, _, _ = _common_harness(root)
    harness = root / "historical-v3.ps1"
    script = prefix + r"""
function ConvertTo-TestLegacyV3Role([object]$Role) {
    return [pscustomobject][ordered]@{
        name = [string]$Role.name
        oid = [int64]$Role.oid
        disposition = [string]$Role.disposition
        can_login = [bool]$Role.can_login
        connection_limit = [int]$Role.connection_limit
        is_superuser = [bool]$Role.is_superuser
        can_create_db = [bool]$Role.can_create_db
        can_create_role = [bool]$Role.can_create_role
        can_replicate = [bool]$Role.can_replicate
        can_bypass_rls = [bool]$Role.can_bypass_rls
        is_database_owner = [bool]$Role.is_database_owner
        owns_public_schema = [bool]$Role.owns_public_schema
        owns_user_relations = [bool]$Role.owns_user_relations
        direct_connect = [bool]$Role.direct_connect
        effective_connect = [bool]$Role.effective_connect
        can_database_create = [bool]$Role.can_database_create
        can_public_schema_create = [bool]$Role.can_public_schema_create
        can_table_write = [bool]$Role.can_table_write
        can_sequence_write = [bool]$Role.can_sequence_write
        can_assume_write_owner = [bool]$Role.can_assume_write_owner
    }
}

$operationId = '11111111-1111-4111-8111-111111111111'
$legacyRoles = @(
    ConvertTo-TestLegacyV3Role (New-TestC07DatabaseAuthorityRole)
    ConvertTo-TestLegacyV3Role (
        New-TestC07RuntimeRole `
            -CanLogin $true `
            -ConnectionLimit -1 `
            -EffectiveConnect $true
    )
)
$legacyRoles[1].is_database_owner = $true
$stagedOwner = ConvertTo-TestLegacyV3Role (New-TestC07OwnerRole)
$stagedOwner.is_database_owner = $false
$legacyRoles += $stagedOwner
$legacyPayload = [pscustomobject][ordered]@{
    schema = 'ticketbox-c07-writer-fence-intent-v3'
    operation_id = $operationId
    descriptor_sha256 = ('A' * 64)
    database_binding_sha256 = ('B' * 64)
    backend_service_start_policy = 'delayed_auto'
    public_connect = $true
    client_session_count_before_fence = [int64]0
    client_sessions_before_fence = @()
    max_prepared_transactions = [int64]0
    prepared_transaction_count = [int64]0
    logical_subscription_count = [int64]0
    logical_apply_worker_count = [int64]0
    unexpected_database_worker_count = [int64]0
    roles = @($legacyRoles)
    created_at_utc = '2026-08-01T00:00:00.0000000Z'
}
function Reset-TestHistoricalIntentEnvelope {
    $script:readEnvelope = [pscustomobject]@{
        Payload = $legacyPayload
        PayloadSha256 = ('C' * 64)
        Text = 'historical-v3-fixture'
    }
}
Reset-TestHistoricalIntentEnvelope
function Get-TicketboxC07WriterFenceIntentPath { return 'historical-v3-intent' }
function Get-TicketboxC07ReadyVerificationPath { return 'ready-verification' }
function Read-TicketboxC07HostEnvelope {
    param([string]$Path, [string]$ExpectedKind)
    return $script:readEnvelope
}
$authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{
        operation_id = $operationId
        database_binding_sha256 = ('B' * 64)
        ready_verification_sha256 = ('D' * 64)
    }
    Descriptor = [pscustomobject]@{
        PayloadSha256 = ('A' * 64)
        Payload = [pscustomobject]@{
            operation_kind = 'c07_money_minor_bigint_v1'
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('E' * 64)
        }
    }
}
$intent = Read-TicketboxC07WriterFenceIntent $authority
if (
    -not [bool]$intent.IsLegacyV3 -or
    [string]$intent.IntentSchema -cne
        'ticketbox-c07-writer-fence-intent-v3' -or
    [string]$intent.OperationMode -cne 'historical_v3' -or
    [string]$intent.AuthorityPhase -cne 'legacy_owner_frozen' -or
    [string]$intent.PayloadSha256 -cne ('C' * 64) -or
    [string]$intent.Text -cne 'historical-v3-fixture' -or
    -not [object]::ReferenceEquals($intent.Payload, $legacyPayload) -or
    $null -ne $intent.Payload.PSObject.Properties['authority_phase']
) {
    throw 'historical v3 intent was rewritten instead of normalized as evidence'
}
$legacyPayload.roles = @(
    ConvertTo-TestLegacyV3Role (New-TestC07DatabaseAuthorityRole)
    ConvertTo-TestLegacyV3Role (New-TestC07RuntimeRole `
        -CanLogin $false -ConnectionLimit 0 -EffectiveConnect $false)
    ConvertTo-TestLegacyV3Role (New-TestC07OwnerRole)
)
Reset-TestHistoricalIntentEnvelope
$managedIntent = Read-TicketboxC07WriterFenceIntent $authority
if ($managedIntent.AuthorityPhase -cne 'managed_frozen') {
    throw 'historical managed v3 owner facts were not classified by the reader'
}
$bothOwnerRoles = @($legacyRoles | ForEach-Object {
    $_ | ConvertTo-Json -Depth 8 | ConvertFrom-Json
})
$bothOwnerRoles[2].is_database_owner = $true
$neitherOwnerRoles = @($legacyRoles | ForEach-Object {
    $_ | ConvertTo-Json -Depth 8 | ConvertFrom-Json
})
$neitherOwnerRoles[1].is_database_owner = $false
foreach ($badRoles in @($bothOwnerRoles, $neitherOwnerRoles)) {
    $legacyPayload.roles = @($badRoles)
    Reset-TestHistoricalIntentEnvelope
    $ambiguousRejected = $false
    try {
        [void](Read-TicketboxC07WriterFenceIntent $authority)
    }
    catch { $ambiguousRejected = $true }
    if (-not $ambiguousRejected) {
        throw 'ambiguous historical v3 owner facts were accepted'
    }
}
$legacyPayload.roles = @($legacyRoles)
$script:historicalIntent = $intent
function Read-TicketboxC07WriterFenceIntent { return $script:historicalIntent }
$script:historicalPhaseCalls = @()
$adapterPath = (Get-Command Initialize-TicketboxC07WriterFenceIntent).ScriptBlock.File
. $adapterPath
function Get-TicketboxC07WriterDatabaseFenceObservation {
    param([string]$AuthorityPhase)
    $script:historicalPhaseCalls += "observe:$AuthorityPhase"
    return [pscustomobject]@{
        AuthorityPhase = $AuthorityPhase
        Roles = @($script:historicalIntent.Roles)
    }
}
function Enter-TicketboxC07CurrentWriterDatabaseFence {
    param($Authority, [string]$AuthorityPhase)
    $script:historicalPhaseCalls += "reconcile:$AuthorityPhase"
    return [pscustomobject]@{
        AuthorityPhase = $AuthorityPhase
        Roles = @($script:historicalIntent.Roles)
    }
}
function Assert-TicketboxC07WriterDatabaseFence { param($Observation) }
[void](Enter-TicketboxC07WriterDatabaseFence `
    -Authority $authority `
    -Intent $script:historicalIntent)
if (
    @($script:historicalPhaseCalls).Count -ne 2 -or
    @($script:historicalPhaseCalls | Where-Object {
        $_ -cnotlike '*:legacy_owner_frozen'
    }).Count -ne 0
) {
    throw (
        'historical v3 resume did not preserve the derived legacy phase: ' +
        (@($script:historicalPhaseCalls) -join ',')
    )
}
$script:historicalPhaseCalls = @()
function Read-TicketboxC07WriterFenceIntent { return $script:historicalIntent }
function Get-TicketboxC07DatabaseAuthorityCredential { return $script:testPassword }
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'test-database-host-authority' }
}
$script:testCatalogMarker = ''
$script:TicketboxC07ProductionMarkerSchema =
    'ticketbox-c07-production-authority-v1'
function Get-TicketboxC07DatabaseCatalogObservation {
    return [pscustomobject]@{ Marker = $script:testCatalogMarker }
}
$script:testServiceStartPolicy = 'disabled'
Assert-TicketboxC07WriterFenceWindow -Authority $authority
if (
    @($script:historicalPhaseCalls).Count -ne 1 -or
    [string]$script:historicalPhaseCalls[0] -cne
        'observe:legacy_owner_frozen'
) {
    throw (
        'production writer-fence window lost the derived historical phase: ' +
        (@($script:historicalPhaseCalls) -join ',')
    )
}
$script:historicalPhaseCalls = @()
$script:testCatalogMarker =
    "$script:TicketboxC07ProductionMarkerSchema|historical-adoption"
Assert-TicketboxC07WriterFenceWindow -Authority $authority
if (
    @($script:historicalPhaseCalls).Count -ne 1 -or
    [string]$script:historicalPhaseCalls[0] -cne 'observe:managed_frozen'
) {
    throw (
        'production writer-fence window did not recognize adopted marker: ' +
        (@($script:historicalPhaseCalls) -join ',')
    )
}

$readyRoles = @($legacyRoles | ForEach-Object {
    $copy = $_ | ConvertTo-Json -Depth 8 | ConvertFrom-Json
    if ([string]$copy.disposition -ceq 'fenced_runtime') {
        $copy.can_login = $false
        $copy.connection_limit = 0
        $copy.direct_connect = $false
        $copy.effective_connect = $false
    }
    $copy
})
function New-TestReadyPayload([string]$Schema, [object[]]$Roles) {
    $payload = [ordered]@{
        schema = $Schema
        operation_id = $operationId
        descriptor_sha256 = ('A' * 64)
        database_binding_sha256 = ('B' * 64)
        writer_fence_intent_sha256 = ('C' * 64)
        operation_kind = 'c07_money_minor_bigint_v1'
        alembic_target = '20260729_0001'
        revision_manifest_sha256 = ('E' * 64)
        backend_service_state = 'stopped'
        backend_service_start_policy = 'disabled'
        backend_service_pid = 0
        backend_listener_pid_count = 0
        runtime_process_count = 0
        database_runtime_session_count = 0
        database_client_sessions = @()
        database_role_capability_count = $Roles.Count
        database_role_capabilities = @($Roles)
        database_max_prepared_transactions = 0
        database_prepared_transaction_count = 0
        database_logical_subscription_count = 0
        database_logical_apply_worker_count = 0
        database_unexpected_worker_count = 0
        database_advisory_fence_available = $true
        verified_at_utc = '2026-08-01T00:01:00.0000000Z'
    }
    if ($Schema -ceq 'ticketbox-c07-ready-verification-v4') {
        $payload.writer_fence_intent_schema =
            'ticketbox-c07-writer-fence-intent-v3'
        $payload.writer_fence_authority_phase = 'published_runtime'
    }
    return [pscustomobject]$payload
}

$script:readEnvelope = [pscustomobject]@{
    Payload = New-TestReadyPayload `
        -Schema 'ticketbox-c07-ready-verification-v3' `
        -Roles $readyRoles
    PayloadSha256 = ('D' * 64)
}
    $legacyFrozenReady = Read-TicketboxC07ReadyVerification $authority
    if (
        [string]$legacyFrozenReady.ReadySchema -cne
            'ticketbox-c07-ready-verification-v3' -or
        [string]$legacyFrozenReady.ReadySemantics -cne 'historical_ambiguous'
    ) {
        throw 'historical frozen READY was relabeled instead of preserved'
    }

    $script:readEnvelope.Payload = New-TestReadyPayload `
        -Schema 'ticketbox-c07-ready-verification-v3' `
        -Roles $legacyRoles
    $legacyPublishedReady = Read-TicketboxC07ReadyVerification $authority
    if ([string]$legacyPublishedReady.ReadySemantics -cne 'historical_ambiguous') {
        throw 'historical published-shaped READY was promoted without live proof'
    }

    $script:readEnvelope = [pscustomobject]@{
        Payload = New-TestReadyPayload `
            -Schema 'ticketbox-c07-ready-verification-v4' `
            -Roles $readyRoles
        PayloadSha256 = ('D' * 64)
    }
    $frozenV4Rejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $frozenV4Rejected = $true }
    if (-not $frozenV4Rejected) {
        throw 'new READY accepted frozen roles as published runtime'
    }

    $currentIntent = [pscustomobject]@{
        IsLegacyV3 = $false
        IntentSchema = 'ticketbox-c07-writer-fence-intent-v4'
        OperationMode = 'fresh_install'
        AuthorityPhase = 'managed_frozen'
        PayloadSha256 = ('C' * 64)
        Roles = @(New-TestC07PublishedRoleSet)
    }
    function Read-TicketboxC07WriterFenceIntent { return $currentIntent }
    $publishedRoles = @(New-TestC07PublishedRoleSet)
    $script:readEnvelope = [pscustomobject]@{
        Payload = New-TestReadyPayload `
            -Schema 'ticketbox-c07-ready-verification-v4' `
            -Roles $publishedRoles
        PayloadSha256 = ('D' * 64)
    }
    $script:readEnvelope.Payload.writer_fence_intent_schema =
        'ticketbox-c07-writer-fence-intent-v4'
    $publishedV4 = Read-TicketboxC07ReadyVerification $authority
    if ([string]$publishedV4.ReadySemantics -cne 'published_runtime') {
        throw 'new READY did not prove published runtime semantics'
    }

    $legacyIntentRoles = @(
        $publishedRoles | Where-Object {
            [string]$_.name -cin @('postgres', 'ticketbox')
        } | ForEach-Object {
            $_ | ConvertTo-Json -Depth 8 | ConvertFrom-Json
        }
    )
    if (@($legacyIntentRoles).Count -eq 1) {
        $legacy = New-TestC07RuntimeRole `
            -CanLogin $false `
            -ConnectionLimit 0 `
            -EffectiveConnect $false
        $legacy.disposition = 'retired_legacy'
        $legacy.can_table_write = $false
        $legacy.can_sequence_write = $false
        $script:readEnvelope.Payload.database_role_capabilities += $legacy
        $script:readEnvelope.Payload.database_role_capability_count += 1
        $legacyIntentRoles += (
            $legacy | ConvertTo-Json -Depth 8 | ConvertFrom-Json
        )
    }
    $currentIntent = [pscustomobject]@{
        IsLegacyV3 = $false
        IntentSchema = 'ticketbox-c07-writer-fence-intent-v4'
        OperationMode = 'legacy_adoption'
        AuthorityPhase = 'legacy_owner_frozen'
        PayloadSha256 = ('C' * 64)
        Roles = @($legacyIntentRoles)
    }
    $legacyPublishedV4 = Read-TicketboxC07ReadyVerification $authority
    if ([string]$legacyPublishedV4.ReadySemantics -cne 'published_runtime') {
        throw 'legacy v4 intent did not admit its exact target-role transition'
    }
    $currentIntent.Roles[0].oid = [int64]777
    $legacySourceOidDriftRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $legacySourceOidDriftRejected = $true }
    if (-not $legacySourceOidDriftRejected) {
        throw 'legacy READY accepted a recreated source authority role'
    }
    $currentIntent.Roles[0].oid = [int64]900
    $unexpected = $script:readEnvelope.Payload.database_role_capabilities[0] |
        ConvertTo-Json -Depth 8 | ConvertFrom-Json
    $unexpected.name = 'unexpected_ready_role'
    $unexpected.oid = [int64]998
    $unexpected.disposition = 'inert_unregistered'
    $unexpected.is_superuser = $false
    $unexpected.can_create_db = $false
    $unexpected.can_create_role = $false
    $unexpected.can_replicate = $false
    $unexpected.can_bypass_rls = $false
    $unexpected.is_database_owner = $false
    $unexpected.owns_public_schema = $false
    $unexpected.owns_user_relations = $false
    $unexpected.owns_security_definer_routines = $false
    $unexpected.can_execute_unowned_security_definer_routines = $false
    $unexpected.direct_connect = $false
    $unexpected.effective_connect = $false
    $unexpected.can_database_create = $false
    $unexpected.can_public_schema_create = $false
    $unexpected.can_table_write = $false
    $unexpected.can_sequence_write = $false
    $unexpected.can_assume_write_owner = $false
    $unexpected.predefined_role_usage = [object[]]@()
    $unexpected.predefined_role_set = [object[]]@()
    $script:readEnvelope.Payload.database_role_capabilities += $unexpected
    $script:readEnvelope.Payload.database_role_capability_count += 1
    $unexpectedLegacyGrowthRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $unexpectedLegacyGrowthRejected = $true }
    if (-not $unexpectedLegacyGrowthRejected) {
        throw 'legacy READY accepted an unbounded role-set expansion'
    }
    $script:readEnvelope.Payload.database_role_capabilities = @(
        $script:readEnvelope.Payload.database_role_capabilities | Where-Object {
            [string]$_.name -cne 'unexpected_ready_role'
        }
    )
    $script:readEnvelope.Payload.database_role_capability_count -= 1
    $currentIntent = [pscustomobject]@{
        IsLegacyV3 = $false
        IntentSchema = 'ticketbox-c07-writer-fence-intent-v4'
        OperationMode = 'fresh_install'
        AuthorityPhase = 'managed_frozen'
        PayloadSha256 = ('C' * 64)
        Roles = @(
            $script:readEnvelope.Payload.database_role_capabilities |
                ForEach-Object {
                    $_ | ConvertTo-Json -Depth 8 | ConvertFrom-Json
                }
        )
    }

    function Assert-TestPublishedReadyMutationRejected {
        param(
            [int]$RoleIndex,
            [string]$Field,
            [object]$Value,
            [string]$Label
        )
        $role = $script:readEnvelope.Payload.database_role_capabilities[$RoleIndex]
        $original = $role.$Field
        try {
            $role.$Field = $Value
            $rejected = $false
            try { [void](Read-TicketboxC07ReadyVerification $authority) }
            catch { $rejected = $true }
            if (-not $rejected) {
                throw "new READY adapter swallowed $Label"
            }
        }
        finally { $role.$Field = $original }
    }
    Assert-TestPublishedReadyMutationRejected 3 'can_create_role' $true `
        'runtime role-creation authority'
    Assert-TestPublishedReadyMutationRejected 3 'is_database_owner' $true `
        'runtime database ownership'
    Assert-TestPublishedReadyMutationRejected 3 'owns_public_schema' $true `
        'runtime schema ownership'
    Assert-TestPublishedReadyMutationRejected 3 'direct_connect' $false `
        'runtime direct CONNECT drift'
    Assert-TestPublishedReadyMutationRejected 3 'effective_connect' $false `
        'runtime effective CONNECT drift'
    Assert-TestPublishedReadyMutationRejected 3 'can_table_write' $false `
        'runtime write capability drift'
    Assert-TestPublishedReadyMutationRejected 3 'can_assume_write_owner' $true `
        'runtime owner-assumption authority'
    Assert-TestPublishedReadyMutationRejected 3 `
        'can_execute_unowned_security_definer_routines' $true `
        'runtime SECURITY DEFINER execution authority'
    Assert-TestPublishedReadyMutationRejected 1 'can_login' $true `
        'retired migrator LOGIN authority'
    Assert-TestPublishedReadyMutationRejected 2 'is_database_owner' $false `
        'missing owner database authority'

    $script:readEnvelope.Payload.database_role_capabilities[3].predefined_role_set =
        @('pg_write_all_data', 'pg_write_all_data')
    $duplicatePredefinedRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $duplicatePredefinedRejected = $true }
    if (-not $duplicatePredefinedRejected) {
        throw 'new READY accepted duplicate predefined-role evidence'
    }
    $script:readEnvelope.Payload.database_role_capabilities[3].predefined_role_set =
        [object[]]@()
    $script:readEnvelope.Payload.database_role_capabilities[3].predefined_role_usage =
        $null
    $nullPredefinedRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $nullPredefinedRejected = $true }
    if (-not $nullPredefinedRejected) {
        throw 'new READY accepted null predefined-role evidence'
    }
    $script:readEnvelope.Payload.database_role_capabilities[3].predefined_role_usage =
        [object[]]@()
    $script:readEnvelope.Payload.database_role_capabilities[3].connection_limit = 0
    $connectionLimitDriftRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $connectionLimitDriftRejected = $true }
    if (-not $connectionLimitDriftRejected) {
        throw 'new READY accepted a runtime connection-limit drift'
    }
    $script:readEnvelope.Payload.database_role_capabilities[3].connection_limit = -1
    $script:readEnvelope.Payload.database_role_capabilities[3].owns_security_definer_routines =
        $true
    $securityDefinerDriftRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $securityDefinerDriftRejected = $true }
    if (-not $securityDefinerDriftRejected) {
        throw 'new READY accepted runtime-owned SECURITY DEFINER authority'
    }
    $script:readEnvelope.Payload.database_role_capabilities[3].owns_security_definer_routines =
        $false
    $script:readEnvelope.Payload.database_role_capabilities[2].predefined_role_usage =
        @('pg_database_owner', 'pg_database_owner')
    $duplicateOwnerEvidenceRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $duplicateOwnerEvidenceRejected = $true }
    if (-not $duplicateOwnerEvidenceRejected) {
        throw 'new READY accepted duplicate owner predefined-role evidence'
    }
    $script:readEnvelope.Payload.database_role_capabilities[2].predefined_role_usage =
        @('pg_database_owner')
    $script:readEnvelope.Payload.database_role_capabilities[3].name = 'ticketbox_owner'
    $duplicateIdentityRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $duplicateIdentityRejected = $true }
    if (-not $duplicateIdentityRejected) {
        throw 'new READY accepted duplicate role identity evidence'
    }
    $script:readEnvelope.Payload.database_role_capabilities[3].name =
        'ticketbox_runtime'
    $script:readEnvelope.Payload.database_role_capabilities[3].can_login = $false
    $capabilityDriftRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $capabilityDriftRejected = $true }
    if (-not $capabilityDriftRejected) {
        throw 'new READY accepted a frozen runtime capability under published label'
    }
    $script:readEnvelope.Payload.database_role_capabilities[3].can_login = $true
    $script:readEnvelope.Payload.database_role_capabilities[3].oid = [int64]999
    $oidDriftRejected = $false
    try { [void](Read-TicketboxC07ReadyVerification $authority) }
    catch { $oidDriftRejected = $true }
    if (-not $oidDriftRejected) {
        throw 'new READY accepted a same-name role recreated with a different OID'
    }
"""
    _write_ps1(harness, script)
    _run_harness(engine, harness, timeout=90)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows C07 artifact contract")
@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_ready_producer_reuses_current_v4_and_never_overwrites_v3(
    engine: str,
) -> None:
    lifecycle = (PACKAGING / "windows_c07_lifecycle.ps1").read_text(
        encoding="utf-8-sig"
    )
    subject = _function(lifecycle, "New-TicketboxC07ReadyVerification")
    script = (
        r"""
$ErrorActionPreference = 'Stop'
$script:TicketboxC07ReadyVerificationSchema =
    'ticketbox-c07-ready-verification-v4'
$script:existingSchema = 'ticketbox-c07-ready-verification-v3'
$script:writeCalls = 0
$script:envelopeCalls = 0
$script:expectedEnvelopeText = 'exact-current-envelope'
function Assert-TicketboxC07OperationLease {}
function Get-TicketboxServiceState { return 'stopped' }
function Get-TicketboxServiceStartPolicy { return 'disabled' }
function Get-TicketboxServiceProcessId { return 0 }
function Get-TicketboxListeningProcessIds { return @() }
function Get-TicketboxExpectedRuntimeProcessIds { return @() }
function Get-TicketboxC07WriterDatabaseFenceObservation {
    return [pscustomobject]@{
        OtherClientSessionCount = [int64]0
        ClientSessions = @()
        Roles = @()
        MaxPreparedTransactions = [int64]0
        PreparedTransactionCount = [int64]0
        LogicalSubscriptionCount = [int64]0
        LogicalApplyWorkerCount = [int64]0
        UnexpectedDatabaseWorkerCount = [int64]0
        AdvisoryFenceAvailable = $true
        AdvisoryFenceReleased = $true
    }
}
function Read-TicketboxC07WriterFenceIntent {
    return [pscustomobject]@{
        PayloadSha256 = ('C' * 64)
        IntentSchema = 'ticketbox-c07-writer-fence-intent-v4'
        IsLegacyV3 = $false
        OperationMode = 'fresh_install'
        AuthorityPhase = 'managed_frozen'
        Roles = @()
    }
}
function Assert-TicketboxC07PublishedDatabaseAuthority {}
function Assert-TicketboxC07PublishedReadyRoleIdentityAuthority {}
function Get-TicketboxC07ReadyVerificationPath { return 'ready-verification' }
function Test-Path { return $true }
function Read-TicketboxC07HostEnvelope {
    return [pscustomobject]@{
        Payload = [pscustomobject]@{
            schema = $script:existingSchema
            verified_at_utc = '2026-08-01T00:00:00.0000000Z'
        }
        Text = 'exact-current-envelope'
        PayloadSha256 = ('D' * 64)
    }
}
function ConvertTo-TicketboxC07CanonicalUtcTimestamp {
    return '2026-08-01T00:00:00.0000000Z'
}
function New-TicketboxC07EnvelopeText {
    $script:envelopeCalls += 1
    return $script:expectedEnvelopeText
}
function Write-TicketboxC07HostEnvelope {
    $script:writeCalls += 1
    throw 'READY writer must not run for an existing artifact'
}
$authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{
        operation_id = '11111111-1111-4111-8111-111111111111'
        database_binding_sha256 = ('B' * 64)
    }
    Descriptor = [pscustomobject]@{
        PayloadSha256 = ('A' * 64)
        Payload = [pscustomobject]@{
            operation_kind = 'c07_money_minor_bigint_v1'
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('E' * 64)
        }
    }
    ReleaseIdentity = [pscustomobject]@{
        BackendServiceName = 'TicketboxBackend'
        BackendPort = 8765
        BackendExe = 'backend.exe'
        ShawlExe = 'shawl.exe'
    }
}
$legacyRejected = $false
try {
    New-TicketboxC07ReadyVerification `
        -Authority $authority `
        -LifecycleLock ([pscustomobject]@{}) | Out-Null
}
catch { $legacyRejected = $_.Exception.Message.Contains('历史 schema') }
if (-not $legacyRejected -or $script:writeCalls -ne 0 -or
    $script:envelopeCalls -ne 0) {
    throw 'existing v3 was not rejected before any rewrite/re-envelope attempt'
}
$script:existingSchema = 'ticketbox-c07-ready-verification-v4'
$reused = New-TicketboxC07ReadyVerification `
    -Authority $authority `
    -LifecycleLock ([pscustomobject]@{})
if ([string]$reused.Text -cne 'exact-current-envelope' -or
    $script:writeCalls -ne 0 -or $script:envelopeCalls -ne 1) {
    throw 'existing current READY was not exact read-compare-reused'
}
$script:expectedEnvelopeText = 'different-current-envelope'
$payloadDriftRejected = $false
try {
    New-TicketboxC07ReadyVerification `
        -Authority $authority `
        -LifecycleLock ([pscustomobject]@{}) | Out-Null
}
catch { $payloadDriftRejected = $true }
if (-not $payloadDriftRejected -or $script:writeCalls -ne 0 -or
    $script:envelopeCalls -ne 2) {
    throw 'existing current READY was reused by schema without full payload equality'
}
"""
        + "\n"
        + subject
    )
    # PowerShell resolves functions at invocation time, so place the subject
    # before the calls while keeping the harness mocks authoritative.
    split = script.index("$authority =")
    script = script[:split] + subject + "\n" + script[split:].rsplit(subject, 1)[0]
    result = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows C07 credential contract")
@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_database_authority_credential_clear_is_reference_scoped(
    engine: str,
) -> None:
    lifecycle = (PACKAGING / "windows_c07_lifecycle.ps1").read_text(
        encoding="utf-8-sig"
    )
    subject = "\n".join(
        (
            _function(lifecycle, "Set-TicketboxC07DatabaseAuthorityCredential"),
            _function(lifecycle, "Clear-TicketboxC07DatabaseAuthorityCredential"),
            _function(lifecycle, "Get-TicketboxC07DatabaseAuthorityCredential"),
        )
    )
    script = (
        subject
        + r"""
function New-TestSecureString([char]$Character) {
    $secret = New-Object Security.SecureString
    1..32 | ForEach-Object { $secret.AppendChar($Character) }
    $secret.MakeReadOnly()
    return $secret
}
$owned = New-TestSecureString 'A'
$foreign = New-TestSecureString 'B'
Set-TicketboxC07DatabaseAuthorityCredential $owned
$foreignRejected = $false
try {
    Clear-TicketboxC07DatabaseAuthorityCredential `
        -ExpectedCredential $foreign
}
catch { $foreignRejected = $true }
if (-not $foreignRejected -or
    -not [object]::ReferenceEquals(
        (Get-TicketboxC07DatabaseAuthorityCredential), $owned
    )) {
    throw 'foreign scoped action cleared or replaced the live credential'
}
Clear-TicketboxC07DatabaseAuthorityCredential -ExpectedCredential $owned
$cleared = $false
try { Get-TicketboxC07DatabaseAuthorityCredential | Out-Null }
catch { $cleared = $true }
if (-not $cleared) { throw 'owned scoped credential survived explicit clear' }
"""
    )
    result = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


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
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_deadline_budget.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
$script:testCeiling = [int64]1200000
$script:testAttemptId = '123e4567-e89b-42d3-a456-4266141740ab'
$script:testAttemptSha256 = '{SUBJECT_SHA256}'
function Get-TicketboxWindowsBootIdentity {{ return 'test-boot' }}
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
$bounded = Get-TicketboxBoundedDeadlineUtc `
    -RequestedDeadlineUtc ([DateTime]::UtcNow.AddMinutes(55)) `
    -CeilingDeadlineUtc ([DateTime]$budget.DeadlineUtc)
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
        $prewrittenReady = $null
        $prewrittenReadyHash = ''
        $prewrittenReadyTimestamp = [int64]0
        if ($stage -ceq 'ready') {{
            $readyAuthority = Read-TicketboxC07Authority '{_literal(data_root)}'
            $prewrittenReady = New-TicketboxC07ReadyVerification `
                -Authority $readyAuthority `
                -LifecycleLock $lifecycleLock
            $readyPath = Get-TicketboxC07ReadyVerificationPath `
                ([string]$readyAuthority.Receipt.operation_id)
            $prewrittenReadyHash = Get-TicketboxC07TextSha256 (
                [IO.File]::ReadAllText($readyPath, [Text.Encoding]::UTF8)
            )
            $prewrittenReadyTimestamp =
                [int64](Get-Item -LiteralPath $readyPath).LastWriteTimeUtc.Ticks
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
        if ($stage -ceq 'ready') {{
            $readyAfter = Read-TicketboxC07Authority '{_literal(data_root)}'
            $readyPath = Get-TicketboxC07ReadyVerificationPath `
                ([string]$readyAfter.Receipt.operation_id)
            if (
                (Get-TicketboxC07TextSha256 (
                    [IO.File]::ReadAllText($readyPath, [Text.Encoding]::UTF8)
                )) -cne $prewrittenReadyHash -or
                [int64](Get-Item -LiteralPath $readyPath).LastWriteTimeUtc.Ticks -ne
                    $prewrittenReadyTimestamp -or
                [string]$readyAfter.Receipt.ready_verification_sha256 -cne
                    [string]$prewrittenReady.PayloadSha256
            ) {{
                throw 'READY crash-window retry rewrote or rebound durable proof'
            }}
        }}
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
    $durableAuthority =
        Read-TicketboxC07DurableHeartbeatAuthority '{_literal(data_root)}'
    $projection = Read-TicketboxC07RuntimeProjection '{_literal(data_root)}'
    if ($authority.Receipt.stage -cne 'ready' -or
        [int64]$authority.Receipt.stage_sequence -ne 9 -or
        [string]$authority.ReadyVerification.ReadySemantics -cne
            'published_runtime' -or
        [string]$durableAuthority.ReadyVerification.ReadySemantics -cne
            'published_runtime' -or
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
def test_c07_fresh_intent_release_transition_recovers_the_two_file_crash_window(
    tmp_path: Path,
) -> None:
    operation_id = "123e4567-e89b-42d3-a456-4266141740a9"
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"fresh-intent-release-transition-{index}"
        prefix, data_root, install_dir, manifest = _common_harness(
            root,
            pending_operation_id=operation_id,
        )
        harness = root / "fresh-intent-release-transition.ps1"
        _write_ps1(
            harness,
            prefix
            + f"""
$lock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    $candidate = Get-TicketboxInstallationReleaseCandidate `
        -DataRoot '{_literal(data_root)}' `
        -InstallDir '{_literal(install_dir)}' `
        -PgPort 5544 `
        -BackendPort 8765 `
        -PgServiceName 'ConfiguredPg' `
        -BackendServiceName 'ConfiguredBackend' `
        -BuildManifestPath '{_literal(manifest)}'
    $currentIdentity = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot '{_literal(data_root)}' `
        -Pending
    $previousIdentity = [pscustomobject]@{{
        State = 'PENDING'
        OperationId = '{operation_id}'
        LegacyCompleted = $false
        InstallationId = [string]$currentIdentity.InstallationId
        BuildManifestSha256 = ('B' * 64)
        BackendVersionFloor = [string]$currentIdentity.BackendVersionFloor
        DataRoot = [string]$currentIdentity.DataRoot
        InstallDir = [string]$currentIdentity.InstallDir
        PgServiceName = [string]$currentIdentity.PgServiceName
        BackendServiceName = [string]$currentIdentity.BackendServiceName
        PgPort = [int]$currentIdentity.PgPort
        BackendPort = [int]$currentIdentity.BackendPort
        MigrationHelperRelativePath =
            [string]$currentIdentity.MigrationHelperRelativePath
        MigrationHelperSize = [int64]$currentIdentity.MigrationHelperSize
        MigrationHelperSha256 = ('C' * 64)
    }}
    $previousRelease =
        Get-TicketboxC07HistoricalReleaseIdentity $previousIdentity
    $successorRelease = Get-TicketboxC07CandidateReleaseIdentity `
        -Candidate $candidate `
        -InstallationId ([string]$previousIdentity.InstallationId) `
        -OperationId '{operation_id}'
    if (
        [string]$previousRelease.Fingerprint -ceq
            [string]$successorRelease.Fingerprint
    ) {{
        throw 'test predecessor and successor fingerprints did not differ'
    }}
    Initialize-TicketboxC07ArtifactRoots $previousRelease | Out-Null
    $emptyRoots =
        Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
            -Candidate $candidate `
            -PreviousInstallationIdentity $previousIdentity `
            -LifecycleLock $lock
    if (
        [string]$emptyRoots.State -cne 'empty_roots' -or
        [bool]$emptyRoots.PreserveOperationId -or
        [bool]$emptyRoots.Rebound -or
        -not [string]::IsNullOrEmpty(
            [string]$emptyRoots.ObservedIntentReleaseFingerprint
        ) -or
        [string]$emptyRoots.PreviousReleaseFingerprint -cne
            [string]$previousRelease.Fingerprint -or
        [string]$emptyRoots.CurrentReleaseFingerprint -cne
            [string]$successorRelease.Fingerprint
    ) {{
        throw 'empty C07 roots were not classified as non-authoritative'
    }}
    $intentPath = Get-TicketboxC07FreshBootstrapIntentPath
    $oldIntent = Write-TicketboxC07HostEnvelope `
        -Path $intentPath `
        -ArtifactKind fresh_bootstrap_intent `
        -Payload ([ordered]@{{
            schema = 'ticketbox-c07-fresh-bootstrap-intent-v1'
            operation_id = '{operation_id}'
            mode = 'fresh_install'
            release_fingerprint = [string]$previousRelease.Fingerprint
            installation_id = [string]$previousIdentity.InstallationId
            source_revision = '20260722_0001'
            target_revision = '20260729_0001'
            runtime_password = ('r' * 32)
            migrator_password = ('m' * 32)
            created_at_utc = [DateTime]::UtcNow.ToString('o')
        }})
    $staleHostStaging = Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) '.ticketbox-protected-11111111111111111111111111111111.tmp'
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $staleHostStaging `
        -Text 'uncommitted replacement bytes' `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount

    # First process publishes the successor intent and dies before it can
    # replace the separate PENDING installation identity.
    $first = Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
        -Candidate $candidate `
        -PreviousInstallationIdentity $previousIdentity `
        -LifecycleLock $lock
    $publishedAfterFirst = Read-TicketboxC07FreshBootstrapIntent `
        $successorRelease
    $textAfterFirst = [IO.File]::ReadAllText($intentPath)
    if (
        -not $first.PreserveOperationId -or
        -not $first.Rebound -or
        [string]$first.State -cne 'fresh_intent_rebound' -or
        [string]$first.OperationId -cne '{operation_id}' -or
        [string]$first.PreviousPayloadSha256 -cne
            [string]$oldIntent.PayloadSha256 -or
        [string]$first.PreviousReleaseFingerprint -cne
            [string]$previousRelease.Fingerprint -or
        [string]$first.CurrentReleaseFingerprint -cne
            [string]$successorRelease.Fingerprint -or
        [string]$first.ObservedIntentReleaseFingerprint -cne
            [string]$previousRelease.Fingerprint -or
        (Test-Path -LiteralPath $staleHostStaging) -or
        [string]$publishedAfterFirst.OperationId -cne '{operation_id}' -or
        [string]$publishedAfterFirst.Payload.runtime_password -cne ('r' * 32) -or
        [string]$publishedAfterFirst.Payload.migrator_password -cne ('m' * 32)
    ) {{
        throw 'first transition did not preserve operation and credentials'
    }}

    # Second process observes old identity + successor intent. This is the
    # allowed prepared crash state: it must reuse the exact intent and let the
    # caller finish only the PENDING identity write.
    $second = Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
        -Candidate $candidate `
        -PreviousInstallationIdentity $previousIdentity `
        -LifecycleLock $lock
    $textAfterSecond = [IO.File]::ReadAllText($intentPath)
    if (
        -not $second.PreserveOperationId -or
        $second.Rebound -or
        [string]$second.State -cne 'fresh_intent_current' -or
        [string]$second.OperationId -cne '{operation_id}' -or
        [string]$second.PreviousPayloadSha256 -cne
            [string]$first.CurrentPayloadSha256 -or
        [string]$second.CurrentPayloadSha256 -cne
            [string]$first.CurrentPayloadSha256 -or
        [string]$second.PreviousReleaseFingerprint -cne
            [string]$previousRelease.Fingerprint -or
        [string]$second.CurrentReleaseFingerprint -cne
            [string]$successorRelease.Fingerprint -or
        [string]$second.ObservedIntentReleaseFingerprint -cne
            [string]$successorRelease.Fingerprint -or
        $textAfterSecond -cne $textAfterFirst
    ) {{
        throw 'prepared transition crash state was not replayed idempotently'
    }}

    function Assert-TransitionRejectedWithoutMutation {{
        param(
            [Parameter(Mandatory = $true)][string]$Label,
            [Parameter(Mandatory = $true)][string]$ExpectedText
        )
        $rejected = $false
        try {{
            Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
                -Candidate $candidate `
                -PreviousInstallationIdentity $previousIdentity `
                -LifecycleLock $lock | Out-Null
        }}
        catch {{ $rejected = $true }}
        if (
            -not $rejected -or
            [IO.File]::ReadAllText($intentPath) -cne $ExpectedText
        ) {{
            throw "$Label was accepted or changed the active intent"
        }}
    }}
    function New-TestTransitionIntentPayload {{
        param(
            [Parameter(Mandatory = $true)][string]$ReleaseFingerprint,
            [Parameter(Mandatory = $true)][string]$OperationId,
            [Parameter(Mandatory = $true)][string]$InstallationId
        )
        $createdAtUtc = if (
            $publishedAfterFirst.Payload.created_at_utc -is [DateTime]
        ) {{
            ([DateTime]$publishedAfterFirst.Payload.created_at_utc).
                ToUniversalTime().ToString('o')
        }}
        else {{ [string]$publishedAfterFirst.Payload.created_at_utc }}
        return [ordered]@{{
            schema = 'ticketbox-c07-fresh-bootstrap-intent-v1'
            operation_id = $OperationId
            mode = 'fresh_install'
            release_fingerprint = $ReleaseFingerprint
            installation_id = $InstallationId
            source_revision = '20260722_0001'
            target_revision = '20260729_0001'
            runtime_password =
                [string]$publishedAfterFirst.Payload.runtime_password
            migrator_password =
                [string]$publishedAfterFirst.Payload.migrator_password
            created_at_utc = $createdAtUtc
        }}
    }}

    $corruptText = $textAfterFirst.Replace(
        ('r' * 32),
        ('x' + ('r' * 31))
    )
    if ($corruptText -ceq $textAfterFirst) {{
        throw 'payload-hash corruption fixture was vacuous'
    }}
    [IO.File]::WriteAllText(
        $intentPath,
        $corruptText,
        (New-Object Text.UTF8Encoding($false))
    )
    Assert-TransitionRejectedWithoutMutation `
        -Label 'payload hash drift' `
        -ExpectedText $corruptText
    [IO.File]::WriteAllText(
        $intentPath,
        $textAfterFirst,
        (New-Object Text.UTF8Encoding($false))
    )

    $foreignFingerprintEnvelope = Write-TicketboxC07HostEnvelope `
        -Path $intentPath `
        -ArtifactKind fresh_bootstrap_intent `
        -Payload (New-TestTransitionIntentPayload `
            -ReleaseFingerprint ('F' * 64) `
            -OperationId '{operation_id}' `
            -InstallationId ([string]$previousIdentity.InstallationId)) `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 (
            [string]$publishedAfterFirst.PayloadSha256
        )
    $foreignFingerprintText = [IO.File]::ReadAllText($intentPath)
    Assert-TransitionRejectedWithoutMutation `
        -Label 'third release fingerprint' `
        -ExpectedText $foreignFingerprintText
    [IO.File]::WriteAllText(
        $intentPath,
        $textAfterFirst,
        (New-Object Text.UTF8Encoding($false))
    )

    $foreignOperationEnvelope = Write-TicketboxC07HostEnvelope `
        -Path $intentPath `
        -ArtifactKind fresh_bootstrap_intent `
        -Payload (New-TestTransitionIntentPayload `
            -ReleaseFingerprint ([string]$successorRelease.Fingerprint) `
            -OperationId '123e4567-e89b-42d3-a456-4266141740ff' `
            -InstallationId ([string]$previousIdentity.InstallationId)) `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 (
            [string]$publishedAfterFirst.PayloadSha256
        )
    $foreignOperationText = [IO.File]::ReadAllText($intentPath)
    Assert-TransitionRejectedWithoutMutation `
        -Label 'foreign operation id' `
        -ExpectedText $foreignOperationText
    [IO.File]::WriteAllText(
        $intentPath,
        $textAfterFirst,
        (New-Object Text.UTF8Encoding($false))
    )

    $foreignInstallationEnvelope = Write-TicketboxC07HostEnvelope `
        -Path $intentPath `
        -ArtifactKind fresh_bootstrap_intent `
        -Payload (New-TestTransitionIntentPayload `
            -ReleaseFingerprint ([string]$successorRelease.Fingerprint) `
            -OperationId '{operation_id}' `
            -InstallationId '123e4567-e89b-42d3-a456-4266141740fe') `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 (
            [string]$publishedAfterFirst.PayloadSha256
        )
    $foreignInstallationText = [IO.File]::ReadAllText($intentPath)
    Assert-TransitionRejectedWithoutMutation `
        -Label 'foreign installation id' `
        -ExpectedText $foreignInstallationText
    [IO.File]::WriteAllText(
        $intentPath,
        $textAfterFirst,
        (New-Object Text.UTF8Encoding($false))
    )

    $foreignPath = Join-Path (Get-TicketboxC07HostArtifactRoot) 'foreign.json'
    [IO.File]::WriteAllText($foreignPath, '{{}}')
    $foreignStateStaging = Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) '.ticketbox-protected-22222222222222222222222222222222.tmp'
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $foreignStateStaging `
        -Text 'must survive foreign-state rejection' `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    $rejected = $false
    try {{
        Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
            -Candidate $candidate `
            -PreviousInstallationIdentity $previousIdentity `
            -LifecycleLock $lock | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (
        -not $rejected -or
        -not (Test-Path -LiteralPath $foreignStateStaging -PathType Leaf) -or
        [IO.File]::ReadAllText($intentPath) -cne $textAfterFirst
    ) {{
        throw 'foreign host artifact was accepted or changed the active intent'
    }}
    [IO.File]::Delete($foreignPath)
    [IO.File]::Delete($foreignStateStaging)

    $projectionPath = Join-Path (
        Get-TicketboxC07RuntimeProjectionRoot
    ) 'projection.json'
    [IO.File]::WriteAllText($projectionPath, '{{}}')
    $runtimeForeignStaging = Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) '.ticketbox-protected-33333333333333333333333333333333.tmp'
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $runtimeForeignStaging `
        -Text 'must survive runtime-state rejection' `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    $rejected = $false
    try {{
        Resolve-TicketboxC07RecoverableFreshBootstrapReleaseTransition `
            -Candidate $candidate `
            -PreviousInstallationIdentity $previousIdentity `
            -LifecycleLock $lock | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (
        -not $rejected -or
        -not (Test-Path -LiteralPath $runtimeForeignStaging -PathType Leaf) -or
        [IO.File]::ReadAllText($intentPath) -cne $textAfterFirst
    ) {{
        throw 'runtime projection artifact was accepted or changed the intent'
    }}
    [IO.File]::Delete($runtimeForeignStaging)
}}
finally {{ Exit-TicketboxLifecycleLock $lock }}
""",
        )
        _run_harness(engine, harness)


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
function Renew-TicketboxC07FrozenMigratorCredentialWindow {{}}
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
    function Renew-TicketboxC07FrozenMigratorCredentialWindow {{
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


def _assert_c07_host_envelope_expected_predecessor_fails_closed(
    tmp_path: Path,
) -> None:
    for engine_index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"host-envelope-predecessor-{engine_index}"
        root.mkdir()
        current_path = root / "current.json"
        missing_path = root / "missing.json"
        harness = root / "predecessor.ps1"
        _write_ps1(
            harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$script:TicketboxC07HostFullControlAccounts = @($currentAccount)
$script:TicketboxC07HostOwnerAccount = $currentAccount

$initial = Write-TicketboxC07HostEnvelope `
    -Path '{_literal(current_path)}' `
    -ArtifactKind 'test_authority' `
    -Payload ([ordered]@{{ generation = 'initial' }})
$drifted = Write-TicketboxC07HostEnvelope `
    -Path '{_literal(current_path)}' `
    -ArtifactKind 'test_authority' `
    -Payload ([ordered]@{{ generation = 'drifted' }}) `
    -ReplaceExisting
$beforeRejectedWrite = Read-TicketboxC07HostEnvelope `
    -Path '{_literal(current_path)}' `
    -ExpectedKind 'test_authority'

$driftRejected = $false
try {{
    Write-TicketboxC07HostEnvelope `
        -Path '{_literal(current_path)}' `
        -ArtifactKind 'test_authority' `
        -Payload ([ordered]@{{ generation = 'stale-writer' }}) `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 $initial.PayloadSha256 | Out-Null
}}
catch {{
    if ($_.Exception.Message -notlike '*预期前态漂移*') {{ throw }}
    $driftRejected = $true
}}
$afterRejectedWrite = Read-TicketboxC07HostEnvelope `
    -Path '{_literal(current_path)}' `
    -ExpectedKind 'test_authority'
if (
    -not $driftRejected -or
    $drifted.PayloadSha256 -cne $beforeRejectedWrite.PayloadSha256 -or
    $afterRejectedWrite.Text -cne $beforeRejectedWrite.Text
) {{
    throw 'stale predecessor overwrote the current legal envelope'
}}

$missingRejected = $false
try {{
    Write-TicketboxC07HostEnvelope `
        -Path '{_literal(missing_path)}' `
        -ArtifactKind 'test_authority' `
        -Payload ([ordered]@{{ generation = 'unexpected-create' }}) `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 $drifted.PayloadSha256 | Out-Null
}}
catch {{
    if ($_.Exception.Message -notlike '*预期前态已丢失*') {{ throw }}
    $missingRejected = $true
}}
if (-not $missingRejected -or
    (Get-TicketboxPathEntryKindNoFollow '{_literal(missing_path)}') -cne 'Missing') {{
    throw 'missing predecessor was recreated by a stale writer'
}}
""",
        )
        _run_harness(engine, harness)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows protected artifact contract")
def test_c07_hash_mismatch_and_backend_writable_roots_fail_closed(
    tmp_path: Path,
) -> None:
    _assert_c07_host_envelope_expected_predecessor_fails_closed(tmp_path)
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
            evidence_suffix = (
                Path("machine")
                / "c07-lifecycle"
                / (
                    f"operation-{operation_id}-stage-"
                    "runtime_acl_verified-evidence.json"
                )
            )
            evidence_path_length = len(str(root / evidence_suffix))
            if evidence_path_length < 261:
                root = (
                    tmp_path
                    / ("p" * (261 - evidence_path_length))
                    / f"runtime-acl-takeover-{engine_index}-{case}"
                )
            assert len(str(root / evidence_suffix)) >= 261
            root.mkdir(parents=True)
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
            _wait_for_path(signal, child, timeout=45)
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
function Renew-TicketboxC07FrozenMigratorCredentialWindow {{}}
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
function Renew-TicketboxC07FrozenMigratorCredentialWindow {{}}
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


def _wait_for_pg_scalar(
    run_sql: Callable[[str, str, str], subprocess.CompletedProcess[str]],
    *,
    sql: str,
    expected: str,
    failure: str,
    timeout: float = 10,
    interval: float = 0.1,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed = run_sql("ticketbox", "postgres", sql)
        assert observed.returncode == 0, observed.stdout + observed.stderr
        if observed.stdout.strip() == expected:
            return
        time.sleep(interval)
    raise AssertionError(failure)


def _cleanup_pg_fence_processes(
    sessions: list[subprocess.Popen[str] | None],
    control_session: subprocess.Popen[str] | None,
) -> None:
    for session in sessions:
        if session is not None:
            session.kill()
            session.communicate(timeout=10)
    if control_session is not None:
        control_session.terminate()
        control_session.communicate(timeout=10)


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
    legacy_session: subprocess.Popen[str] | None = None
    unknown_session: subprocess.Popen[str] | None = None
    runtime_session: subprocess.Popen[str] | None = None
    startup_session: subprocess.Popen[str] | None = None
    control_session: subprocess.Popen[str] | None = None
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

        # start_test_pg provisions a reusable backend-test topology.  This
        # lane instead qualifies the dedicated bundled-cluster legacy shape,
        # so remove only those known test databases/role from this disposable
        # cluster before creating the product topology.
        for test_database in ("xpj_test", "xpj_smoke", "xpj_restore"):
            removed_test_database = run_sql(
                "postgres",
                "postgres",
                f'DROP DATABASE IF EXISTS "{test_database}" WITH (FORCE);',
            )
            assert removed_test_database.returncode == 0, (
                removed_test_database.stdout + removed_test_database.stderr
            )
        removed_test_role = run_sql(
            "postgres",
            "postgres",
            'DROP ROLE IF EXISTS "xpj_test_app";',
        )
        assert removed_test_role.returncode == 0, (
            removed_test_role.stdout + removed_test_role.stderr
        )
        legacy_password = credential.replace("'", "''")
        legacy_role = run_sql(
            "postgres",
            "postgres",
            (
                "CREATE ROLE ticketbox LOGIN NOINHERIT PASSWORD "
                f"'{legacy_password}';"
            ),
        )
        assert legacy_role.returncode == 0, legacy_role.stdout + legacy_role.stderr
        legacy_database = run_sql(
            "postgres",
            "postgres",
            'CREATE DATABASE ticketbox OWNER ticketbox TEMPLATE template0;',
        )
        assert legacy_database.returncode == 0, (
            legacy_database.stdout + legacy_database.stderr
        )
        legacy_table = run_sql(
            "ticketbox",
            "postgres",
            """
ALTER SCHEMA public OWNER TO ticketbox;
SET ROLE ticketbox;
CREATE TABLE public.accounts(
    id bigint GENERATED BY DEFAULT AS IDENTITY,
    value integer NOT NULL
);
INSERT INTO public.accounts(value) VALUES (7);
""",
        )
        assert legacy_table.returncode == 0, legacy_table.stdout + legacy_table.stderr
        legacy_env = {
            key: value for key, value in admin_env.items() if key != "PGPASSFILE"
        }
        legacy_env["PGPASSWORD"] = credential
        legacy_session = subprocess.Popen(
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
            env=legacy_env,
        )
        _wait_for_pg_scalar(
            run_sql,
            sql=(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE usename = 'ticketbox' AND pid <> pg_backend_pid();"
            ),
            expected="1",
            failure="legacy-only PostgreSQL session was not observable",
        )

        legacy_harness = tmp_path / "production-legacy-fence-adoption.ps1"
        _write_ps1(
            legacy_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
function New-TestSecureString([string]$Value) {{
    $secure = New-Object Security.SecureString
    foreach ($character in $Value.ToCharArray()) {{ $secure.AppendChar($character) }}
    $secure.MakeReadOnly()
    return $secure
}}
$password = New-TestSecureString $plain
Set-TicketboxC07DatabaseAuthorityCredential $password
$before = Get-TicketboxC07WriterDatabaseFenceObservation
if (
    [string]$before.AuthorityPhase -cne 'legacy_owner_frozen' -or
    @($before.Roles | Where-Object disposition -CEQ 'legacy_owner_writer').Count -ne 1 -or
    [int64]$before.OtherClientSessionCount -ne 1
) {{
    throw 'real legacy-only topology was not classified before adoption'
}}
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{
        operation_id = '11234567-89ab-cdef-0123-456789abcdef'
        database_binding_sha256 = ('B' * 64)
    }}
    Descriptor = [pscustomobject]@{{
        PayloadSha256 = ('A' * 64)
        Payload = [pscustomobject]@{{
            operation_kind = 'c07_money_minor_bigint_v1'
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('E' * 64)
        }}
    }}
    ReleaseIdentity = [pscustomobject]@{{
        BackendServiceName = 'TicketboxBackend'
        BackendPort = 8765
        BackendExe = 'backend.exe'
        ShawlExe = 'shawl.exe'
    }}
}}
$intent = [pscustomobject]@{{
    IsLegacyV3 = $false
    IntentSchema = 'ticketbox-c07-writer-fence-intent-v4'
    PayloadSha256 = ('C' * 64)
    OperationMode = 'legacy_adoption'
    AuthorityPhase = [string]$before.AuthorityPhase
    PublicConnect = [bool]$before.PublicConnect
    Roles = @($before.Roles)
}}
$frozen = Enter-TicketboxC07WriterDatabaseFence `
    -Authority $authority `
    -Intent $intent
if (
    [string]$frozen.AuthorityPhase -cne 'legacy_owner_frozen' -or
    [int64]$frozen.OtherClientSessionCount -ne 0
) {{
    throw 'real legacy-only writer was not fenced before adoption'
}}
[void](Invoke-TicketboxC07LegacyDatabaseAdoption `
    -SuperuserPassword $password `
    -RuntimePassword $password `
    -MigratorPassword $password `
    -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
    -OperationId ([string]$authority.Receipt.operation_id))
$managed = Get-TicketboxC07WriterDatabaseFenceObservation `
    -AuthorityPhase 'managed_frozen'
Assert-TicketboxC07WriterDatabaseFence -Observation $managed
if (
    @($managed.Roles | Where-Object disposition -CEQ 'retired_legacy').Count -ne 1 -or
    @($managed.Roles | Where-Object disposition -CEQ 'fenced_runtime').Count -ne 1
) {{
    throw 'real legacy adoption did not publish managed-frozen role authority'
}}
Assert-TicketboxC07PublishedReadyRoleIdentityAuthority `
    -Authority $authority `
    -Intent $intent `
    -ReadyRoles @($managed.Roles)
$driftedReadyRoles = @($managed.Roles | ForEach-Object {{
    $_ | ConvertTo-Json -Depth 12 | ConvertFrom-Json
}})
$driftedRuntime = @($driftedReadyRoles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
$driftedRuntime[0].oid = [int64]$driftedRuntime[0].oid + 1
$targetOidDriftRejected = $false
try {{
    Assert-TicketboxC07PublishedReadyRoleIdentityAuthority `
        -Authority $authority `
        -Intent $intent `
        -ReadyRoles $driftedReadyRoles
}}
catch {{ $targetOidDriftRejected = $true }}
if (-not $targetOidDriftRejected) {{
    throw 'legacy READY accepted a same-name target role with a different OID'
}}
$invalidExpansionIntents = @(
    [pscustomobject]@{{
        Label = 'fresh mode'
        Intent = [pscustomobject]@{{
            IsLegacyV3 = $false
            OperationMode = 'fresh_install'
            AuthorityPhase = 'legacy_owner_frozen'
            Roles = @($intent.Roles)
        }}
    }},
    [pscustomobject]@{{
        Label = 'managed phase'
        Intent = [pscustomobject]@{{
            IsLegacyV3 = $false
            OperationMode = 'legacy_adoption'
            AuthorityPhase = 'managed_frozen'
            Roles = @($intent.Roles)
        }}
    }},
    [pscustomobject]@{{
        Label = 'historical v3'
        Intent = [pscustomobject]@{{
            IsLegacyV3 = $true
            OperationMode = 'legacy_adoption'
            AuthorityPhase = 'legacy_owner_frozen'
            Roles = @($intent.Roles)
        }}
    }}
)
foreach ($candidate in $invalidExpansionIntents) {{
    if (Test-TicketboxC07PublishedReadyRoleIdentityTransition `
        -Intent $candidate.Intent `
        -ReadyRoles @($managed.Roles)) {{
        throw (
            "$($candidate.Label) READY inherited the legacy v4 " +
            'role-expansion exception'
        )
    }}
}}
$bootstrap = Get-TicketboxC07RoleBootstrapIdentity `
    -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
    -SuperuserPassword $password `
    -OperationId ([string]$authority.Receipt.operation_id) `
    -Mode 'legacy_adoption'
Invoke-TicketboxC07Sql `
    -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
    -Database 'ticketbox' `
    -Role 'postgres' `
    -Password $password `
    -Label 'C07 test publish runtime admission' `
    -Sql @'
BEGIN;
ALTER ROLE ticketbox_runtime
    LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1;
GRANT CONNECT ON DATABASE ticketbox TO ticketbox_runtime;
COMMIT;
'@ | Out-Null
Disable-TicketboxC07MigratorLogin `
    -SuperuserPassword $password `
    -OperationId ([string]$authority.Receipt.operation_id) `
    -Mode 'legacy_adoption'
$published = Get-TicketboxC07WriterDatabaseFenceObservation `
    -AuthorityPhase 'published_runtime'
Assert-TicketboxC07PublishedDatabaseAuthority -Observation $published
$script:testReadyPath = Join-Path `
    (Split-Path -Parent $PSCommandPath) `
    'real-legacy-ready-verification.json'
function Get-TicketboxC07ReadyVerificationPath {{ return $script:testReadyPath }}
function Write-TicketboxC07HostEnvelope {{
    param(
        [string]$Path,
        [string]$ArtifactKind,
        [object]$Payload
    )
    $text = New-TicketboxC07EnvelopeText `
        -ArtifactKind $ArtifactKind `
        -Payload $Payload
    [IO.File]::WriteAllText($Path, $text, [Text.Encoding]::UTF8)
    return ConvertFrom-TicketboxC07EnvelopeText `
        -Text $text `
        -ExpectedKind $ArtifactKind
}}
function Read-TicketboxC07HostEnvelope {{
    param([string]$Path, [string]$ExpectedKind)
    $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
    return ConvertFrom-TicketboxC07EnvelopeText `
        -Text $text `
        -ExpectedKind $ExpectedKind
}}
function Assert-TicketboxC07OperationLease {{}}
function Get-TicketboxServiceState {{ return 'stopped' }}
function Get-TicketboxServiceStartPolicy {{ return 'disabled' }}
function Get-TicketboxServiceProcessId {{ return 0 }}
function Get-TicketboxListeningProcessIds {{ return @() }}
function Get-TicketboxExpectedRuntimeProcessIds {{ return @() }}
function Read-TicketboxC07WriterFenceIntent {{ return $intent }}
Invoke-TicketboxC07Sql `
    -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
    -Database 'postgres' `
    -Role 'postgres' `
    -Password $password `
    -Label 'C07 test corrupt target role marker' `
    -Sql "COMMENT ON ROLE ticketbox_runtime IS 'foreign-operation';" | Out-Null
$producerMarkerRejected = $false
try {{
    [void](New-TicketboxC07ReadyVerification `
        -Authority $authority `
        -LifecycleLock ([pscustomobject]@{{}}))
}}
catch {{ $producerMarkerRejected = $true }}
if (-not $producerMarkerRejected -or
    (Test-Path -LiteralPath $script:testReadyPath -PathType Leaf)) {{
    throw 'READY producer published before target role marker validation'
}}
$foreignMarkerRejected = $false
try {{
    Assert-TicketboxC07PublishedReadyRoleIdentityAuthority `
        -Authority $authority `
        -Intent $intent `
        -ReadyRoles @($managed.Roles)
}}
catch {{ $foreignMarkerRejected = $true }}
if (-not $foreignMarkerRejected) {{
    throw 'legacy READY accepted a target role not bound to its operation marker'
}}
$runtimeMarker = (
    "$script:TicketboxC07RoleMarkerSchema|" +
    "$($authority.Receipt.operation_id)|legacy_adoption|roles_created|" +
    "$($bootstrap.RuntimeRoleOid)"
)
$runtimeMarkerSql = ConvertTo-TicketboxC07SqlLiteral $runtimeMarker
Invoke-TicketboxC07Sql `
    -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
    -Database 'postgres' `
    -Role 'postgres' `
    -Password $password `
    -Label 'C07 test restore target role marker' `
    -Sql "COMMENT ON ROLE ticketbox_runtime IS $runtimeMarkerSql;" | Out-Null
$ready = New-TicketboxC07ReadyVerification `
    -Authority $authority `
    -LifecycleLock ([pscustomobject]@{{}})
$authority.Receipt | Add-Member `
    -NotePropertyName ready_verification_sha256 `
    -NotePropertyValue ([string]$ready.PayloadSha256) `
    -Force
$readReady = Read-TicketboxC07ReadyVerification $authority
if (
    [string]$readReady.ReadySemantics -cne 'published_runtime' -or
    [string]$readReady.PayloadSha256 -cne [string]$ready.PayloadSha256 -or
    @($readReady.Payload.database_role_capabilities | Where-Object {{
        [string]$_.name -ceq 'ticketbox_runtime' -and
        [uint32]$_.oid -eq [uint32]$bootstrap.RuntimeRoleOid
    }}).Count -ne 1
) {{
    throw 'real legacy READY producer/artifact/reader did not converge'
}}
""",
        )
        _run_harness(engine, legacy_harness, timeout=180)
        _, legacy_stderr = legacy_session.communicate(timeout=10)
        assert legacy_session.returncode != 0, legacy_stderr
        legacy_session = None
        legacy_count = run_sql(
            "ticketbox",
            "postgres",
            "SELECT count(*) FROM public.accounts WHERE value = 7;",
        )
        assert legacy_count.returncode == 0, (
            legacy_count.stdout + legacy_count.stderr
        )
        assert legacy_count.stdout.strip() == "1"
        legacy_database_cleanup = run_sql(
            "postgres",
            "postgres",
            "DROP DATABASE ticketbox WITH (FORCE);",
        )
        assert legacy_database_cleanup.returncode == 0, (
            legacy_database_cleanup.stdout + legacy_database_cleanup.stderr
        )
        legacy_role_cleanup = run_sql(
            "postgres",
            "postgres",
            """
DROP ROLE IF EXISTS ticketbox_runtime;
DROP ROLE IF EXISTS ticketbox_migrator;
DROP ROLE IF EXISTS ticketbox_owner;
DROP ROLE IF EXISTS ticketbox;
""",
        )
        assert legacy_role_cleanup.returncode == 0, (
            legacy_role_cleanup.stdout + legacy_role_cleanup.stderr
        )

        bootstrap_harness = tmp_path / "production-fresh-bootstrap.ps1"
        _write_ps1(
            bootstrap_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
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
function New-TestSecureString([string]$Value) {{
    $secure = New-Object Security.SecureString
    foreach ($character in $Value.ToCharArray()) {{ $secure.AppendChar($character) }}
    $secure.MakeReadOnly()
    return $secure
}}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$superuserPassword = New-TestSecureString $plain
$runtimePassword = New-TestSecureString $plain
$migratorPassword = New-TestSecureString $plain
$operationId = '01234567-89ab-cdef-0123-456789abcdef'
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$runtimeVerifier = ConvertTo-TicketboxC07ScramVerifier $runtimePassword
$migratorVerifier = ConvertTo-TicketboxC07ScramVerifier $migratorPassword
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'postgres' `
    -Role 'postgres' `
    -Password $superuserPassword `
    -Label 'real PG17 production role producer' `
    -Sql (Get-TicketboxC07RoleBootstrapSql `
        -RuntimeVerifier $runtimeVerifier `
        -MigratorVerifier $migratorVerifier `
        -MigratorValidUntilUtc ([DateTime]::UtcNow.AddMinutes(10)) `
        -OperationId $operationId `
        -Mode 'fresh_install'))
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'postgres' `
    -Role 'postgres' `
    -Password $superuserPassword `
    -Label 'real PG17 production database producer' `
    -Sql @'
CREATE DATABASE "ticketbox"
    OWNER "ticketbox_owner" TEMPLATE template0 ENCODING 'UTF8'
    ALLOW_CONNECTIONS false;
BEGIN;
REVOKE ALL ON DATABASE "ticketbox" FROM PUBLIC;
REVOKE ALL ON DATABASE "ticketbox" FROM "ticketbox_runtime";
REVOKE ALL ON DATABASE "ticketbox" FROM "ticketbox_migrator";
GRANT CONNECT ON DATABASE "ticketbox" TO "ticketbox_migrator";
ALTER DATABASE "ticketbox" ALLOW_CONNECTIONS true;
COMMIT;
'@)
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres' `
    -Password $superuserPassword `
    -Label 'real PG17 source-bootstrap table' `
    -Sql @'
BEGIN;
SET LOCAL ROLE "ticketbox_owner";
CREATE TABLE public.accounts(
    id bigint GENERATED BY DEFAULT AS IDENTITY,
    value integer NOT NULL
);
COMMIT;
'@)
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres' `
    -Password $superuserPassword `
    -Label 'real PG17 production ACL publication' `
    -Sql (Get-TicketboxC07DatabasePrivilegeSql))
Assert-TicketboxC07RoleCatalog $hostAuthority $superuserPassword
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'postgres' `
    -Role 'postgres' `
    -Password $superuserPassword `
    -Label 'real PG17 opaque inert role' `
    -Sql 'CREATE ROLE "Third-Party Auditor" NOLOGIN NOINHERIT;')
""",
        )
        _run_harness(engine, bootstrap_harness, timeout=60)
        before_write = run_sql(
            "ticketbox",
            "ticketbox_runtime",
            "INSERT INTO public.accounts(value) VALUES (1);",
            runtime_password=True,
        )
        assert before_write.returncode == 0, before_write.stdout + before_write.stderr

        view_authority_created = run_sql(
            "ticketbox",
            "postgres",
            f"""
CREATE ROLE "Ticketbox View Owner" NOLOGIN NOINHERIT;
CREATE ROLE "View Insert Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Update Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Delete Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Column Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Column Insert Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Trigger Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Trigger Update Writer" NOLOGIN NOINHERIT;
CREATE ROLE "View Trigger Delete Writer" NOLOGIN NOINHERIT;
CREATE ROLE "Table Column Insert Writer" NOLOGIN NOINHERIT;
CREATE ROLE restricted_observer LOGIN NOINHERIT
    PASSWORD '{legacy_password}';
GRANT CONNECT ON DATABASE ticketbox TO restricted_observer;
GRANT USAGE ON SCHEMA public
    TO ticketbox_migrator, "Third-Party Auditor", "Ticketbox View Owner",
       "View Insert Writer", "View Update Writer", "View Delete Writer",
       "View Column Writer", "View Column Insert Writer",
       "View Trigger Writer", "View Trigger Update Writer",
       "View Trigger Delete Writer", "Table Column Insert Writer";
BEGIN;
SET LOCAL ROLE ticketbox_owner;
CREATE VIEW public.ticketbox_writer_fence_insert_view AS
    SELECT id, value FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_update_view AS
    SELECT id, value FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_delete_view AS
    SELECT id, value FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_column_view AS
    SELECT id, value FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_column_insert_view AS
    SELECT id, value FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_third_party_view AS
    SELECT id, value FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_trigger_view AS
    SELECT count(*)::bigint AS account_count FROM public.accounts;
CREATE VIEW public.ticketbox_writer_fence_trigger_update_view AS
    SELECT max(id)::bigint AS account_id, max(value)::integer AS account_value
    FROM public.accounts WHERE id = 9806;
CREATE VIEW public.ticketbox_writer_fence_trigger_delete_view AS
    SELECT max(id)::bigint AS account_id
    FROM public.accounts WHERE id = 9807;
CREATE FUNCTION public.ticketbox_writer_fence_trigger_insert()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
BEGIN
    INSERT INTO public.accounts(id, value) VALUES (NEW.account_count, 105);
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.ticketbox_writer_fence_trigger_insert()
    FROM PUBLIC;
CREATE TRIGGER ticketbox_writer_fence_trigger_insert
INSTEAD OF INSERT ON public.ticketbox_writer_fence_trigger_view
FOR EACH ROW EXECUTE FUNCTION public.ticketbox_writer_fence_trigger_insert();
CREATE FUNCTION public.ticketbox_writer_fence_trigger_update()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
BEGIN
    UPDATE public.accounts SET value = NEW.account_value
    WHERE id = OLD.account_id;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION public.ticketbox_writer_fence_trigger_update()
    FROM PUBLIC;
CREATE TRIGGER ticketbox_writer_fence_trigger_update
INSTEAD OF UPDATE ON public.ticketbox_writer_fence_trigger_update_view
FOR EACH ROW EXECUTE FUNCTION public.ticketbox_writer_fence_trigger_update();
CREATE FUNCTION public.ticketbox_writer_fence_trigger_delete()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
BEGIN
    DELETE FROM public.accounts WHERE id = OLD.account_id;
    RETURN OLD;
END
$function$;
REVOKE ALL ON FUNCTION public.ticketbox_writer_fence_trigger_delete()
    FROM PUBLIC;
CREATE TRIGGER ticketbox_writer_fence_trigger_delete
INSTEAD OF DELETE ON public.ticketbox_writer_fence_trigger_delete_view
FOR EACH ROW EXECUTE FUNCTION public.ticketbox_writer_fence_trigger_delete();
CREATE VIEW public.ticketbox_writer_fence_owner_view AS
    SELECT count(*)::bigint AS account_count FROM public.accounts;
COMMIT;
ALTER VIEW public.ticketbox_writer_fence_owner_view
    OWNER TO "Ticketbox View Owner";
GRANT INSERT ON public.ticketbox_writer_fence_insert_view
    TO "View Insert Writer";
GRANT UPDATE ON public.ticketbox_writer_fence_update_view
    TO "View Update Writer";
GRANT SELECT(id) ON public.ticketbox_writer_fence_update_view
    TO "View Update Writer";
GRANT DELETE ON public.ticketbox_writer_fence_delete_view
    TO "View Delete Writer";
GRANT SELECT(id) ON public.ticketbox_writer_fence_delete_view
    TO "View Delete Writer";
GRANT UPDATE(value) ON public.ticketbox_writer_fence_column_view
    TO "View Column Writer";
GRANT SELECT(id) ON public.ticketbox_writer_fence_column_view
    TO "View Column Writer";
GRANT INSERT(id, value) ON public.ticketbox_writer_fence_column_insert_view
    TO "View Column Insert Writer";
GRANT INSERT ON public.ticketbox_writer_fence_trigger_view
    TO "View Trigger Writer";
GRANT UPDATE ON public.ticketbox_writer_fence_trigger_update_view
    TO "View Trigger Update Writer";
GRANT DELETE ON public.ticketbox_writer_fence_trigger_delete_view
    TO "View Trigger Delete Writer";
GRANT INSERT(id, value) ON public.accounts
    TO "Table Column Insert Writer";
GRANT UPDATE ON public.ticketbox_writer_fence_third_party_view
    TO "Third-Party Auditor";
GRANT INSERT ON public.ticketbox_writer_fence_insert_view
    TO ticketbox_migrator;
GRANT "Ticketbox View Owner" TO "Third-Party Auditor"
    WITH INHERIT FALSE, SET TRUE;
""",
        )
        assert view_authority_created.returncode == 0, (
            view_authority_created.stdout + view_authority_created.stderr
        )
        seeded_view_rows = run_sql(
            "ticketbox",
            "postgres",
            "INSERT INTO public.accounts(id, value) VALUES "
            "(9802, 102), (9803, 103), (9804, 104), "
            "(9806, 106), (9807, 107);",
        )
        assert seeded_view_rows.returncode == 0, (
            seeded_view_rows.stdout + seeded_view_rows.stderr
        )
        view_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Insert Writer"; '
            "INSERT INTO public.ticketbox_writer_fence_insert_view(id, value) "
            "VALUES (9801, 101);",
        )
        assert view_write.returncode == 0, view_write.stdout + view_write.stderr
        update_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Update Writer"; '
            "UPDATE public.ticketbox_writer_fence_update_view "
            "SET value = 202 WHERE id = 9802;",
        )
        assert update_write.returncode == 0, (
            update_write.stdout + update_write.stderr
        )
        delete_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Delete Writer"; '
            "DELETE FROM public.ticketbox_writer_fence_delete_view "
            "WHERE id = 9803;",
        )
        assert delete_write.returncode == 0, (
            delete_write.stdout + delete_write.stderr
        )
        column_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Column Writer"; '
            "UPDATE public.ticketbox_writer_fence_column_view "
            "SET value = 204 WHERE id = 9804;",
        )
        assert column_write.returncode == 0, (
            column_write.stdout + column_write.stderr
        )
        column_insert_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Column Insert Writer"; '
            "INSERT INTO public.ticketbox_writer_fence_column_insert_view(id, value) "
            "VALUES (9808, 108);",
        )
        assert column_insert_write.returncode == 0, (
            column_insert_write.stdout + column_insert_write.stderr
        )
        trigger_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Trigger Writer"; '
            "INSERT INTO public.ticketbox_writer_fence_trigger_view(account_count) "
            "VALUES (9805);",
        )
        assert trigger_write.returncode == 0, (
            trigger_write.stdout + trigger_write.stderr
        )
        trigger_update_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Trigger Update Writer"; '
            "UPDATE public.ticketbox_writer_fence_trigger_update_view "
            "SET account_value = 206;",
        )
        assert trigger_update_write.returncode == 0, (
            trigger_update_write.stdout + trigger_update_write.stderr
        )
        trigger_delete_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "View Trigger Delete Writer"; '
            "DELETE FROM public.ticketbox_writer_fence_trigger_delete_view;",
        )
        assert trigger_delete_write.returncode == 0, (
            trigger_delete_write.stdout + trigger_delete_write.stderr
        )
        table_column_insert_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "Table Column Insert Writer"; '
            "INSERT INTO public.accounts(id, value) VALUES (9809, 109);",
        )
        assert table_column_insert_write.returncode == 0, (
            table_column_insert_write.stdout + table_column_insert_write.stderr
        )
        view_write_count = run_sql(
            "ticketbox",
            "postgres",
            "SELECT count(*) FILTER (WHERE (id, value) IN "
            "((9801,101),(9802,202),(9804,204),(9805,105),"
            "(9806,206),(9808,108),(9809,109)))::text || ':' || "
            "count(*) FILTER (WHERE id = 9807)::text FROM public.accounts;",
        )
        assert view_write_count.returncode == 0, (
            view_write_count.stdout + view_write_count.stderr
        )
        assert view_write_count.stdout.strip() == "7:0"
        view_rejection_harness = tmp_path / "real-pg-view-writer-rejection.ps1"
        _write_ps1(
            view_rejection_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$migrator = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_migrator'
}})
$isolatedWriters = @(
    'View Insert Writer',
    'View Update Writer',
    'View Delete Writer',
    'View Column Writer',
    'View Column Insert Writer',
    'View Trigger Writer',
    'View Trigger Update Writer',
    'View Trigger Delete Writer',
    'Table Column Insert Writer'
)
$viewOwner = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'Ticketbox View Owner'
}})
$thirdParty = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'Third-Party Auditor'
}})
if (
    $migrator.Count -ne 1 -or -not [bool]$migrator[0].can_table_write -or
    @($isolatedWriters | Where-Object {{
        $writerName = $_
        @($raw.Roles | Where-Object {{
            [string]$_.name -ceq $writerName -and
            [bool]$_.can_table_write
        }}).Count -ne 1
    }}).Count -ne 0 -or
    $viewOwner.Count -ne 1 -or
    -not [bool]$viewOwner[0].owns_managed_relations -or
    $thirdParty.Count -ne 1 -or
    -not [bool]$thirdParty[0].can_table_write -or
    -not [bool]$thirdParty[0].can_assume_write_owner
) {{
    throw 'real PG17 updatable-view writer authority was not fully observed'
}}
$restrictedUrl =
    'postgresql://restricted_observer@127.0.0.1:' +
    $script:testPgPort + '/ticketbox?require_auth=scram-sha-256'
$restrictedObservation = Get-TicketboxPostgresqlWriterFenceObservation `
    -PsqlPath (Resolve-TicketboxC07DatabaseHostAuthority).PsqlPath `
    -DatabaseUrl $restrictedUrl `
    -Password $plain `
    -ManagedSchemaName 'public' `
    -AdvisoryLockLabel 'xiaopiaojia:restricted-view-observation' `
    -ApplicationName 'ticketbox-c07-restricted-view-observation' `
    -TimeoutMilliseconds 10000 `
    -StatementTimeoutMilliseconds 5000 `
    -LockTimeoutMilliseconds 1000
$restrictedViewWriters = @(
    'View Insert Writer',
    'View Update Writer',
    'View Delete Writer',
    'View Column Writer',
    'View Column Insert Writer',
    'View Trigger Writer',
    'View Trigger Update Writer',
    'View Trigger Delete Writer',
    'Third-Party Auditor'
)
if (@($restrictedViewWriters | Where-Object {{
    $writerName = $_
    @($restrictedObservation.Roles | Where-Object {{
        [string]$_.name -ceq $writerName -and
        [bool]$_.can_table_write
    }}).Count -ne 1
}}).Count -ne 0) {{
    throw 'restricted authority visibility hid updatable-view writer authority'
}}
$classifiedRejected = $false
try {{ [void](Get-TicketboxC07WriterDatabaseFenceObservation) }}
catch {{ $classifiedRejected = $true }}
if (-not $classifiedRejected) {{
    throw 'C07 policy accepted updatable-view writer authority'
}}
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres' `
    -Password $password `
    -Label 'isolate real PG17 view DML precondition' `
    -Sql @'
REVOKE "Ticketbox View Owner" FROM "Third-Party Auditor";
ALTER VIEW public.ticketbox_writer_fence_owner_view OWNER TO ticketbox_owner;
DROP OWNED BY "Ticketbox View Owner";
DROP ROLE "Ticketbox View Owner";
REVOKE INSERT ON public.ticketbox_writer_fence_insert_view
    FROM ticketbox_migrator, "View Insert Writer";
REVOKE UPDATE ON public.ticketbox_writer_fence_update_view
    FROM "View Update Writer";
REVOKE SELECT(id) ON public.ticketbox_writer_fence_update_view
    FROM "View Update Writer";
REVOKE DELETE ON public.ticketbox_writer_fence_delete_view
    FROM "View Delete Writer";
REVOKE SELECT(id) ON public.ticketbox_writer_fence_delete_view
    FROM "View Delete Writer";
REVOKE UPDATE(value) ON public.ticketbox_writer_fence_column_view
    FROM "View Column Writer";
REVOKE SELECT(id) ON public.ticketbox_writer_fence_column_view
    FROM "View Column Writer";
REVOKE INSERT(id, value) ON public.ticketbox_writer_fence_column_insert_view
    FROM "View Column Insert Writer";
REVOKE INSERT ON public.ticketbox_writer_fence_trigger_view
    FROM "View Trigger Writer";
REVOKE UPDATE ON public.ticketbox_writer_fence_trigger_update_view
    FROM "View Trigger Update Writer";
REVOKE DELETE ON public.ticketbox_writer_fence_trigger_delete_view
    FROM "View Trigger Delete Writer";
REVOKE INSERT(id, value) ON public.accounts
    FROM "Table Column Insert Writer";
DROP OWNED BY "View Insert Writer";
DROP OWNED BY "View Update Writer";
DROP OWNED BY "View Delete Writer";
DROP OWNED BY "View Column Writer";
DROP OWNED BY "View Column Insert Writer";
DROP OWNED BY "View Trigger Writer";
DROP OWNED BY "View Trigger Update Writer";
DROP OWNED BY "View Trigger Delete Writer";
DROP OWNED BY "Table Column Insert Writer";
DROP ROLE "View Insert Writer";
DROP ROLE "View Update Writer";
DROP ROLE "View Delete Writer";
DROP ROLE "View Column Writer";
DROP ROLE "View Column Insert Writer";
DROP ROLE "View Trigger Writer";
DROP ROLE "View Trigger Update Writer";
DROP ROLE "View Trigger Delete Writer";
DROP ROLE "Table Column Insert Writer";
DROP OWNED BY restricted_observer;
DROP ROLE restricted_observer;
'@)
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$databaseUrl = New-TicketboxC07LocalDatabaseUrl `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres'
function Test-TestRoleHasWriterAuthority([object]$Role) {{
    return (
        [bool]$Role.can_login -or [bool]$Role.is_superuser -or
        [bool]$Role.can_create_db -or [bool]$Role.can_create_role -or
        [bool]$Role.can_replicate -or [bool]$Role.can_bypass_rls -or
        [bool]$Role.is_database_owner -or [bool]$Role.owns_managed_schema -or
        [bool]$Role.owns_managed_relations -or
        [bool]$Role.owns_security_definer_routines -or
        [bool]$Role.can_execute_unowned_security_definer_routines -or
        [bool]$Role.can_database_create -or
        [bool]$Role.can_managed_schema_create -or
        [bool]$Role.can_table_write -or [bool]$Role.can_sequence_write -or
        [bool]$Role.can_assume_write_owner -or
        @($Role.predefined_role_usage).Count -ne 0 -or
        @($Role.predefined_role_set).Count -ne 0
    )
}}
$authorizedNames = @(
    'postgres', 'ticketbox', 'ticketbox_owner',
    'ticketbox_migrator', 'ticketbox_runtime'
)
$dmlPreconditionObservation = Get-TicketboxC07RawWriterDatabaseFenceObservation
$dmlUnregisteredAuthority = @($dmlPreconditionObservation.Roles | Where-Object {{
    [string]$_.name -cnotin $authorizedNames -and
    (Test-TestRoleHasWriterAuthority $_)
}})
if (
    $dmlUnregisteredAuthority.Count -ne 1 -or
    [string]$dmlUnregisteredAuthority[0].name -cne 'Third-Party Auditor' -or
    -not [bool]$dmlUnregisteredAuthority[0].can_table_write
) {{
    throw 'real PG17 DML precondition fixture has an independent blocker'
}}
$preconditionRejected = $false
try {{
    [void](Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
        param([string]$PlainPassword)
        Invoke-TicketboxPostgresqlWriterFenceReconcile `
            -PsqlPath $hostAuthority.PsqlPath `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -AuthorityRole 'postgres' `
            -ManagedSchemaName 'public' `
            -AdvisoryLockLabel 'xiaopiaojia:schema' `
            -ApplicationName 'ticketbox-c07-view-precondition' `
            -ManagedWriterRoles @('ticketbox', 'ticketbox_runtime') `
            -AuthorizedRoleNames @(
                'postgres', 'ticketbox', 'ticketbox_owner',
                'ticketbox_migrator', 'ticketbox_runtime'
            ) `
            -AllowedLoginRolesAfterFence @('postgres', 'ticketbox_migrator') `
            -AllowedDatabaseOwnerRoles @('ticketbox_owner') `
            -AllowedManagedWriterOwnerRoles @() `
            -AllowedDatabaseOwnerTransitionRoles @('ticketbox_migrator') `
            -TimeoutMilliseconds 10000 `
            -LockTimeoutMilliseconds 1000 `
            -TerminationTimeoutMilliseconds 3000
    }})
}}
catch {{ $preconditionRejected = $true }}
if (-not $preconditionRejected) {{
    throw 'generic reconcile accepted an unregistered updatable-view writer'
}}
$after = Get-TicketboxC07RawWriterDatabaseFenceObservation
$runtime = @($after.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
if (
    $runtime.Count -ne 1 -or -not [bool]$runtime[0].can_login -or
    [int]$runtime[0].connection_limit -ne -1 -or
    -not [bool]$runtime[0].direct_connect -or
    -not [bool]$runtime[0].effective_connect
) {{
    throw 'updatable-view precondition rejection occurred after mutation'
}}
[void](Invoke-TicketboxC07Sql `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres' `
    -Password $password `
    -Label 'isolate real PG17 view-owner precondition' `
    -Sql @'
REVOKE UPDATE ON public.ticketbox_writer_fence_third_party_view
    FROM "Third-Party Auditor";
REVOKE USAGE ON SCHEMA public FROM "Third-Party Auditor";
CREATE ROLE "Ticketbox View Owner" NOLOGIN NOINHERIT;
ALTER VIEW public.ticketbox_writer_fence_owner_view
    OWNER TO "Ticketbox View Owner";
'@)
$ownerPreconditionObservation = Get-TicketboxC07RawWriterDatabaseFenceObservation
$ownerUnregisteredAuthority = @(
    $ownerPreconditionObservation.Roles | Where-Object {{
        [string]$_.name -cnotin $authorizedNames -and
        (Test-TestRoleHasWriterAuthority $_)
    }}
)
if (
    $ownerUnregisteredAuthority.Count -ne 1 -or
    [string]$ownerUnregisteredAuthority[0].name -cne
        'Ticketbox View Owner' -or
    -not [bool]$ownerUnregisteredAuthority[0].owns_managed_relations -or
    [bool]$ownerUnregisteredAuthority[0].can_table_write
) {{
    throw 'real PG17 view-owner precondition fixture has an independent blocker'
}}
$ownerPreconditionRejected = $false
try {{
    [void](Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
        param([string]$PlainPassword)
        Invoke-TicketboxPostgresqlWriterFenceReconcile `
            -PsqlPath $hostAuthority.PsqlPath `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -AuthorityRole 'postgres' `
            -ManagedSchemaName 'public' `
            -AdvisoryLockLabel 'xiaopiaojia:schema' `
            -ApplicationName 'ticketbox-c07-view-owner-precondition' `
            -ManagedWriterRoles @('ticketbox', 'ticketbox_runtime') `
            -AuthorizedRoleNames @(
                'postgres', 'ticketbox', 'ticketbox_owner',
                'ticketbox_migrator', 'ticketbox_runtime'
            ) `
            -AllowedLoginRolesAfterFence @('postgres', 'ticketbox_migrator') `
            -AllowedDatabaseOwnerRoles @('ticketbox_owner') `
            -AllowedManagedWriterOwnerRoles @() `
            -AllowedDatabaseOwnerTransitionRoles @('ticketbox_migrator') `
            -TimeoutMilliseconds 10000 `
            -LockTimeoutMilliseconds 1000 `
            -TerminationTimeoutMilliseconds 3000
    }})
}}
catch {{ $ownerPreconditionRejected = $true }}
if (-not $ownerPreconditionRejected) {{
    throw 'generic reconcile accepted an unregistered ordinary-view owner'
}}
""",
        )
        _run_harness(engine, view_rejection_harness, timeout=60)
        view_authority_secured = run_sql(
            "ticketbox",
            "postgres",
            """
DROP VIEW public.ticketbox_writer_fence_insert_view;
DROP VIEW public.ticketbox_writer_fence_update_view;
DROP VIEW public.ticketbox_writer_fence_delete_view;
DROP VIEW public.ticketbox_writer_fence_column_view;
DROP VIEW public.ticketbox_writer_fence_column_insert_view;
DROP VIEW public.ticketbox_writer_fence_third_party_view;
DROP VIEW public.ticketbox_writer_fence_trigger_view;
DROP VIEW public.ticketbox_writer_fence_trigger_update_view;
DROP VIEW public.ticketbox_writer_fence_trigger_delete_view;
DROP VIEW public.ticketbox_writer_fence_owner_view;
DROP FUNCTION public.ticketbox_writer_fence_trigger_insert();
DROP FUNCTION public.ticketbox_writer_fence_trigger_update();
DROP FUNCTION public.ticketbox_writer_fence_trigger_delete();
DROP OWNED BY "Ticketbox View Owner";
DROP ROLE "Ticketbox View Owner";
REVOKE USAGE ON SCHEMA public
    FROM ticketbox_migrator, "Third-Party Auditor";
DELETE FROM public.accounts WHERE id BETWEEN 9801 AND 9809;
CREATE VIEW public.ticketbox_writer_fence_read_only AS
    SELECT count(*) AS account_count FROM public.accounts;
GRANT USAGE ON SCHEMA public TO "Third-Party Auditor";
GRANT INSERT, UPDATE, DELETE ON public.ticketbox_writer_fence_read_only
    TO "Third-Party Auditor";
""",
        )
        assert view_authority_secured.returncode == 0, (
            view_authority_secured.stdout + view_authority_secured.stderr
        )
        read_only_harness = tmp_path / "real-pg-read-only-view-control.ps1"
        _write_ps1(
            read_only_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$thirdParty = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'Third-Party Auditor'
}})
if ($thirdParty.Count -ne 1 -or [bool]$thirdParty[0].can_table_write) {{
    throw 'read-only aggregate view DML grants were misclassified as executable'
}}
""",
        )
        _run_harness(engine, read_only_harness, timeout=60)
        read_only_cleanup = run_sql(
            "ticketbox",
            "postgres",
            "DROP VIEW public.ticketbox_writer_fence_read_only; "
            'REVOKE USAGE ON SCHEMA public FROM "Third-Party Auditor";',
        )
        assert read_only_cleanup.returncode == 0, (
            read_only_cleanup.stdout + read_only_cleanup.stderr
        )

        external_view_created = run_sql(
            "ticketbox",
            "postgres",
            """
BEGIN;
CREATE ROLE "External View Writer" NOLOGIN NOINHERIT;
SET LOCAL ROLE ticketbox_owner;
CREATE SCHEMA ticketbox_writer_fence_view_helper
    AUTHORIZATION ticketbox_owner;
CREATE VIEW ticketbox_writer_fence_view_helper.external_accounts AS
    SELECT id, value FROM public.accounts;
GRANT USAGE ON SCHEMA ticketbox_writer_fence_view_helper
    TO "External View Writer";
GRANT INSERT ON ticketbox_writer_fence_view_helper.external_accounts
    TO "External View Writer";
COMMIT;
""",
        )
        assert external_view_created.returncode == 0, (
            external_view_created.stdout + external_view_created.stderr
        )
        external_view_write = run_sql(
            "ticketbox",
            "postgres",
            'SET ROLE "External View Writer"; '
            "INSERT INTO ticketbox_writer_fence_view_helper.external_accounts"
            "(id, value) VALUES (9810, 110);",
        )
        assert external_view_write.returncode == 0, (
            external_view_write.stdout + external_view_write.stderr
        )
        external_view_effect = run_sql(
            "ticketbox",
            "postgres",
            "SELECT count(*) FROM public.accounts WHERE (id, value) = (9810, 110);",
        )
        assert external_view_effect.returncode == 0, (
            external_view_effect.stdout + external_view_effect.stderr
        )
        assert external_view_effect.stdout.strip() == "1"
        external_view_harness = tmp_path / "real-pg-external-view-writer.ps1"
        _write_ps1(
            external_view_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$externalWriter = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'External View Writer'
}})
if ($externalWriter.Count -ne 1 -or
    -not [bool]$externalWriter[0].can_table_write -or
    [bool]$externalWriter[0].owns_managed_relations) {{
    throw 'external-schema updatable view writer authority was not observed'
}}
$classifiedRejected = $false
try {{ [void](Get-TicketboxC07WriterDatabaseFenceObservation) }}
catch {{ $classifiedRejected = $true }}
if (-not $classifiedRejected) {{
    throw 'C07 policy accepted an external-schema updatable-view writer'
}}
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$databaseUrl = New-TicketboxC07LocalDatabaseUrl `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres'
$preconditionRejected = $false
try {{
    [void](Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
        param([string]$PlainPassword)
        Invoke-TicketboxPostgresqlWriterFenceReconcile `
            -PsqlPath $hostAuthority.PsqlPath `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -AuthorityRole 'postgres' `
            -ManagedSchemaName 'public' `
            -AdvisoryLockLabel 'xiaopiaojia:schema' `
            -ApplicationName 'ticketbox-c07-external-view-precondition' `
            -ManagedWriterRoles @('ticketbox', 'ticketbox_runtime') `
            -AuthorizedRoleNames @(
                'postgres', 'ticketbox', 'ticketbox_owner',
                'ticketbox_migrator', 'ticketbox_runtime'
            ) `
            -AllowedLoginRolesAfterFence @('postgres', 'ticketbox_migrator') `
            -AllowedDatabaseOwnerRoles @('ticketbox_owner') `
            -AllowedManagedWriterOwnerRoles @() `
            -AllowedDatabaseOwnerTransitionRoles @('ticketbox_migrator') `
            -TimeoutMilliseconds 10000 `
            -LockTimeoutMilliseconds 1000 `
            -TerminationTimeoutMilliseconds 3000
    }})
}}
catch {{ $preconditionRejected = $true }}
if (-not $preconditionRejected) {{
    throw 'generic reconcile accepted an external-schema updatable-view writer'
}}
$after = Get-TicketboxC07RawWriterDatabaseFenceObservation
$runtime = @($after.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
if ($runtime.Count -ne 1 -or -not [bool]$runtime[0].can_login -or
    [int]$runtime[0].connection_limit -ne -1 -or
    -not [bool]$runtime[0].direct_connect -or
    -not [bool]$runtime[0].effective_connect) {{
    throw 'external-view precondition rejection occurred after mutation'
}}
""",
        )
        _run_harness(engine, external_view_harness, timeout=60)
        external_view_usage_revoked = run_sql(
            "ticketbox",
            "postgres",
            'REVOKE USAGE ON SCHEMA ticketbox_writer_fence_view_helper '
            'FROM "External View Writer";',
        )
        assert external_view_usage_revoked.returncode == 0, (
            external_view_usage_revoked.stdout + external_view_usage_revoked.stderr
        )
        external_view_usage_control = (
            tmp_path / "real-pg-external-view-schema-usage-control.ps1"
        )
        _write_ps1(
            external_view_usage_control,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$externalWriter = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'External View Writer'
}})
if ($externalWriter.Count -ne 1 -or [bool]$externalWriter[0].can_table_write) {{
    throw 'external view without schema USAGE was misclassified as executable'
}}
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$databaseUrl = New-TicketboxC07LocalDatabaseUrl `
    -Authority $hostAuthority -Database 'ticketbox' -Role 'postgres'
$authorizedRolesSql = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
    @('postgres', 'ticketbox', 'ticketbox_owner',
      'ticketbox_migrator', 'ticketbox_runtime') `
    'authorized roles'
$managedSchemaSql =
    ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral 'public'
$guard = New-TicketboxPostgresqlWriterFenceUnregisteredWriterGuardSql `
    -AuthorizedRolesSql $authorizedRolesSql `
    -ManagedSchemaSql $managedSchemaSql
Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
    param([string]$PlainPassword)
    [void](Invoke-TicketboxPostgresqlWriterFenceSql `
        -PsqlPath $hostAuthority.PsqlPath `
        -DatabaseUrl $databaseUrl `
        -Password $PlainPassword `
        -Sql @"
DO `$writer_fence`$
BEGIN
$guard
END
`$writer_fence`$;
"@ `
        -Label 'external view no-USAGE precondition control' `
        -TimeoutMilliseconds 30000)
}}
""",
        )
        _run_harness(engine, external_view_usage_control, timeout=60)
        external_view_cleanup = run_sql(
            "ticketbox",
            "postgres",
            """
DROP SCHEMA ticketbox_writer_fence_view_helper CASCADE;
DROP OWNED BY "External View Writer";
DROP ROLE "External View Writer";
DELETE FROM public.accounts WHERE id = 9810;
""",
        )
        assert external_view_cleanup.returncode == 0, (
            external_view_cleanup.stdout + external_view_cleanup.stderr
        )

        definer_created = run_sql(
            "ticketbox",
            "postgres",
            """
BEGIN;
SET LOCAL ROLE ticketbox_owner;
CREATE SCHEMA ticketbox_writer_fence_helper AUTHORIZATION ticketbox_owner;
CREATE FUNCTION ticketbox_writer_fence_helper.ticketbox_writer_fence_definer_probe()
RETURNS integer LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    INSERT INTO public.accounts(value) VALUES (99);
    SELECT 99;
$function$;
GRANT USAGE ON SCHEMA ticketbox_writer_fence_helper TO ticketbox_runtime;
REVOKE ALL ON FUNCTION
    ticketbox_writer_fence_helper.ticketbox_writer_fence_definer_probe()
    FROM PUBLIC, ticketbox_runtime;
COMMIT;
""",
        )
        assert definer_created.returncode == 0, (
            definer_created.stdout + definer_created.stderr
        )
        definer_execute_control = (
            tmp_path / "real-pg-definer-execute-control.ps1"
        )
        _write_ps1(
            definer_execute_control,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$runtime = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
if ($runtime.Count -ne 1 -or
    [bool]$runtime[0].can_execute_unowned_security_definer_routines) {{
    throw 'SECURITY DEFINER classification ignored missing EXECUTE authority'
}}
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$databaseUrl = New-TicketboxC07LocalDatabaseUrl `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres'
$authoritySql = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral 'postgres'
$allowedOwnerRolesSql = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
    @('ticketbox_owner') `
    'allowed owner roles'
$securityDefinerGuard = New-TicketboxPostgresqlWriterFenceSecurityDefinerGuardSql `
    -AuthorityRoleSql $authoritySql `
    -AllowedOwnerRolesSql $allowedOwnerRolesSql
Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
    param([string]$PlainPassword)
    [void](Invoke-TicketboxPostgresqlWriterFenceSql `
        -PsqlPath $hostAuthority.PsqlPath `
        -DatabaseUrl $databaseUrl `
        -Password $PlainPassword `
        -Sql @"
DO `$writer_fence`$
BEGIN
$securityDefinerGuard
END
`$writer_fence`$;
"@ `
        -Label 'external definer no-EXECUTE precondition control' `
        -TimeoutMilliseconds 30000)
}}
""",
        )
        _run_harness(engine, definer_execute_control, timeout=60)
        definer_execute_granted = run_sql(
            "ticketbox",
            "postgres",
            """
GRANT EXECUTE ON FUNCTION
    ticketbox_writer_fence_helper.ticketbox_writer_fence_definer_probe()
    TO ticketbox_runtime;
""",
        )
        assert definer_execute_granted.returncode == 0, (
            definer_execute_granted.stdout + definer_execute_granted.stderr
        )
        definer_write = run_sql(
            "ticketbox",
            "ticketbox_runtime",
            "SELECT ticketbox_writer_fence_helper.ticketbox_writer_fence_definer_probe();",
            runtime_password=True,
        )
        assert definer_write.returncode == 0, (
            definer_write.stdout + definer_write.stderr
        )
        assert definer_write.stdout.strip() == "99"
        definer_rejection_harness = tmp_path / "real-pg-definer-rejection.ps1"
        _write_ps1(
            definer_rejection_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$databaseUrl = New-TicketboxC07LocalDatabaseUrl `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres'
$genericRejected = $false
Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
    param([string]$PlainPassword)
    try {{
        [void](Invoke-TicketboxPostgresqlWriterFenceReconcile `
            -PsqlPath $hostAuthority.PsqlPath `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -AuthorityRole 'postgres' `
            -ManagedSchemaName 'public' `
            -AdvisoryLockLabel 'xiaopiaojia:schema' `
            -ApplicationName 'ticketbox-definer-precondition' `
            -ManagedWriterRoles @('ticketbox', 'ticketbox_runtime') `
            -AuthorizedRoleNames @(
                'postgres', 'ticketbox', 'ticketbox_owner',
                'ticketbox_migrator', 'ticketbox_runtime'
            ) `
            -AllowedLoginRolesAfterFence @('postgres', 'ticketbox_migrator') `
            -AllowedDatabaseOwnerRoles @('ticketbox_owner') `
            -AllowedManagedWriterOwnerRoles @() `
            -AllowedDatabaseOwnerTransitionRoles @('ticketbox_migrator') `
            -TimeoutMilliseconds 30000 `
            -LockTimeoutMilliseconds 1000 `
            -TerminationTimeoutMilliseconds 3000)
    }}
    catch {{ $script:genericRejected = $true }}
}}
if (-not $script:genericRejected) {{
    throw 'external-schema SECURITY DEFINER escaped generic precondition'
}}
$afterGuard = Get-TicketboxC07RawWriterDatabaseFenceObservation
$runtimeAfterGuard = @($afterGuard.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
if ($runtimeAfterGuard.Count -ne 1 -or -not [bool]$runtimeAfterGuard[0].can_login) {{
    throw 'SECURITY DEFINER precondition mutated runtime before rejection'
}}
$rejected = $false
try {{ [void](Get-TicketboxC07WriterDatabaseFenceObservation) }}
catch {{ $rejected = $true }}
if (-not $rejected) {{
    throw 'runtime SECURITY DEFINER effective EXECUTE escaped C07 observation policy'
}}
""",
        )
        _run_harness(engine, definer_rejection_harness, timeout=60)
        definer_secured = run_sql(
            "ticketbox",
            "postgres",
            """
DELETE FROM public.accounts WHERE value = 99;
REVOKE USAGE ON SCHEMA ticketbox_writer_fence_helper FROM ticketbox_runtime;
""",
        )
        assert definer_secured.returncode == 0, (
            definer_secured.stdout + definer_secured.stderr
        )
        definer_usage_control = tmp_path / "real-pg-definer-schema-usage-control.ps1"
        _write_ps1(
            definer_usage_control,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$runtime = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
if ($runtime.Count -ne 1 -or
    [bool]$runtime[0].can_execute_unowned_security_definer_routines) {{
    throw 'SECURITY DEFINER callable classification ignored schema USAGE'
}}
$hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
$databaseUrl = New-TicketboxC07LocalDatabaseUrl `
    -Authority $hostAuthority `
    -Database 'ticketbox' `
    -Role 'postgres'
$authoritySql = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral 'postgres'
$allowedOwnerRolesSql = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
    @('ticketbox_owner') `
    'allowed owner roles'
$securityDefinerGuard = New-TicketboxPostgresqlWriterFenceSecurityDefinerGuardSql `
    -AuthorityRoleSql $authoritySql `
    -AllowedOwnerRolesSql $allowedOwnerRolesSql
Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {{
    param([string]$PlainPassword)
    [void](Invoke-TicketboxPostgresqlWriterFenceSql `
        -PsqlPath $hostAuthority.PsqlPath `
        -DatabaseUrl $databaseUrl `
        -Password $PlainPassword `
        -Sql @"
DO `$writer_fence`$
BEGIN
$securityDefinerGuard
END
`$writer_fence`$;
"@ `
        -Label 'external definer no-USAGE precondition control' `
        -TimeoutMilliseconds 30000)
}}
""",
        )
        _run_harness(engine, definer_usage_control, timeout=60)

        definer_owner_created = run_sql(
            "ticketbox",
            "postgres",
            """
BEGIN;
CREATE ROLE "Ticketbox External Definer Owner" NOLOGIN NOINHERIT;
CREATE ROLE "Ticketbox External Definer Assumer" NOLOGIN NOINHERIT;
GRANT "Ticketbox External Definer Owner"
    TO "Ticketbox External Definer Assumer"
    WITH INHERIT FALSE, SET TRUE;
CREATE SCHEMA ticketbox_writer_fence_owner_helper
    AUTHORIZATION "Ticketbox External Definer Owner";
SET LOCAL ROLE "Ticketbox External Definer Owner";
CREATE FUNCTION ticketbox_writer_fence_owner_helper.owner_probe()
RETURNS integer LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog
AS 'SELECT 1';
COMMIT;
""",
        )
        assert definer_owner_created.returncode == 0, (
            definer_owner_created.stdout + definer_owner_created.stderr
        )
        definer_owner_harness = tmp_path / "real-pg-definer-owner-closure.ps1"
        _write_ps1(
            definer_owner_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
$owner = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'Ticketbox External Definer Owner'
}})
$assumer = @($raw.Roles | Where-Object {{
    [string]$_.name -ceq 'Ticketbox External Definer Assumer'
}})
if (
    $owner.Count -ne 1 -or
    -not [bool]$owner[0].owns_security_definer_routines -or
    [bool]$owner[0].owns_managed_schema -or
    [bool]$owner[0].owns_managed_relations -or
    $assumer.Count -ne 1 -or
    -not [bool]$assumer[0].can_assume_write_owner
) {{
    throw 'external-schema SECURITY DEFINER owner SET closure was not observed'
}}
""",
        )
        _run_harness(engine, definer_owner_harness, timeout=60)

        definer_cleanup = run_sql(
            "ticketbox",
            "postgres",
            """
DROP SCHEMA ticketbox_writer_fence_helper CASCADE;
DROP SCHEMA ticketbox_writer_fence_owner_helper CASCADE;
REVOKE "Ticketbox External Definer Owner"
    FROM "Ticketbox External Definer Assumer";
DROP OWNED BY "Ticketbox External Definer Assumer";
DROP OWNED BY "Ticketbox External Definer Owner";
DROP ROLE "Ticketbox External Definer Assumer";
DROP ROLE "Ticketbox External Definer Owner";
""",
        )
        assert definer_cleanup.returncode == 0, (
            definer_cleanup.stdout + definer_cleanup.stderr
        )

        unknown_session = subprocess.Popen(
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
                "postgres",
                "--dbname",
                "ticketbox",
                "--command",
                (
                    "SET application_name = "
                    "'ticketbox-writer-fence-unknown-session'; "
                    "SELECT pg_sleep(30);"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=admin_env,
        )
        _wait_for_pg_scalar(
            run_sql,
            sql=(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = "
                "'ticketbox-writer-fence-unknown-session' "
                "AND usename = 'postgres' "
                "AND pid <> pg_backend_pid();"
            ),
            expected="1",
            failure="unknown PostgreSQL session was not observable",
        )

        unknown_rejection_harness = tmp_path / "real-pg-unknown-session.ps1"
        _write_ps1(
            unknown_rejection_harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_database.ps1")}'
. '{_literal(PACKAGING / "windows_c07_lifecycle.ps1")}'
. '{_literal(storage_contract)}'
. '{_literal(auth_contract)}'
$script:testPgBin = '{_literal(pg_bin)}'
$script:testPgData = '{_literal(data_dir)}'
$script:testPgPort = {port}
function Resolve-TicketboxC07DatabaseHostAuthority {{
    [pscustomobject]@{{
        Schema = 'ticketbox-c07-host-db-authority-v1'
        PsqlPath = (Join-Path $script:testPgBin 'psql.exe')
        PgData = $script:testPgData
        Port = $script:testPgPort
    }}
}}
function Assert-TicketboxC07LiveHostConnection {{ param($Authority, $Password) }}
$plain = Read-XpjTestPostgresCredential -DataDir $script:testPgData
$password = New-Object Security.SecureString
foreach ($character in $plain.ToCharArray()) {{ $password.AppendChar($character) }}
$password.MakeReadOnly()
Set-TicketboxC07DatabaseAuthorityCredential $password
$before = Get-TicketboxC07WriterDatabaseFenceObservation
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{
        operation_id = '21234567-89ab-cdef-0123-456789abcdef'
    }}
    ReleaseIdentity = [pscustomobject]@{{}}
}}
$intent = [pscustomobject]@{{
    AuthorityPhase = [string]$before.AuthorityPhase
    PublicConnect = [bool]$before.PublicConnect
    Roles = @($before.Roles)
}}
$rejected = $false
try {{
    [void](Enter-TicketboxC07WriterDatabaseFence `
        -Authority $authority `
        -Intent $intent)
}}
catch {{
    $rejected = $true
}}
if (-not $rejected) {{
    throw 'non-managed target-database session escaped the pre-mutation guard'
}}
$rawAfter = Get-TicketboxC07RawWriterDatabaseFenceObservation
$runtime = @($rawAfter.Roles | Where-Object {{
    [string]$_.name -ceq 'ticketbox_runtime'
}})
if (
    $runtime.Count -ne 1 -or
    -not [bool]$runtime[0].can_login -or
    [int]$runtime[0].connection_limit -ne -1 -or
    -not [bool]$runtime[0].direct_connect -or
    -not [bool]$runtime[0].effective_connect
) {{
    throw 'unknown-session rejection occurred after writer-fence mutation'
}}
""",
        )
        _run_harness(engine, unknown_rejection_harness, timeout=60)
        assert unknown_session.poll() is None
        unknown_backend_cleanup = run_sql(
            "ticketbox",
            "postgres",
            (
                "SELECT pg_terminate_backend(pid, 3000) "
                "FROM pg_stat_activity "
                "WHERE application_name = "
                "'ticketbox-writer-fence-unknown-session' "
                "AND usename = 'postgres' "
                "AND pid <> pg_backend_pid();"
            ),
        )
        assert unknown_backend_cleanup.returncode == 0, (
            unknown_backend_cleanup.stdout + unknown_backend_cleanup.stderr
        )
        assert unknown_backend_cleanup.stdout.strip() == "t"
        _, unknown_stderr = unknown_session.communicate(timeout=10)
        assert unknown_session.returncode != 0, unknown_stderr
        unknown_session = None

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
                "ticketbox_runtime",
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
        _wait_for_pg_scalar(
            run_sql,
            sql=(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE usename = 'ticketbox_runtime' "
                "AND pid <> pg_backend_pid();"
            ),
            expected="1",
            failure="runtime PostgreSQL session did not become observable",
        )

        control_session = subprocess.Popen(
            [
                str(psql),
                "--no-psqlrc",
                "--no-password",
                "--quiet",
                "--tuples-only",
                "--no-align",
                "--set",
                "ON_ERROR_STOP=1",
                "--host",
                "localhost",
                "--port",
                str(port),
                "--username",
                "postgres",
                "--dbname",
                "postgres",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=admin_env,
        )

        def control_sql(sql: str, marker: str) -> list[str]:
            assert control_session is not None
            assert control_session.stdin is not None
            assert control_session.stdout is not None
            control_session.stdin.write(f"{sql};\nSELECT '{marker}';\n")
            control_session.stdin.flush()
            rows: list[str] = []
            while True:
                line = control_session.stdout.readline()
                if line == "":
                    assert control_session.stderr is not None
                    raise AssertionError(
                        "PG17 control session exited: "
                        + control_session.stderr.read()
                    )
                value = line.strip()
                if value == marker:
                    return rows
                if value:
                    rows.append(value)

        startup_env = dict(runtime_env)
        startup_env["PGOPTIONS"] = "-c post_auth_delay=30"
        startup_session = subprocess.Popen(
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
                "ticketbox_runtime",
                "--dbname",
                "ticketbox",
                "--command",
                "SELECT 1;",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=startup_env,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            startup_lock_pids = control_sql(
                """
SELECT database_lock.pid::text
FROM pg_locks AS database_lock
WHERE database_lock.pid IS NOT NULL
  AND database_lock.pid <> pg_backend_pid()
  AND database_lock.locktype = 'object'
  AND database_lock.mode = 'RowExclusiveLock'
  AND database_lock.granted
  AND database_lock.classid = 'pg_database'::regclass::oid
  AND database_lock.objid = (
      SELECT oid FROM pg_database WHERE datname = 'ticketbox'
  )
  AND database_lock.objsubid = 0
  AND NOT EXISTS (
      SELECT 1 FROM pg_stat_activity AS activity
      WHERE activity.pid = database_lock.pid
  )
""",
                "TBX_STARTUP_LOCK_PROBE",
            )
            if len(startup_lock_pids) == 1:
                startup_backend_pid = int(startup_lock_pids[0])
                break
            time.sleep(0.05)
        else:
            raise AssertionError(
                "runtime startup database lock did not become observable"
            )
        harness = tmp_path / "real-pg-fence.ps1"
        _write_ps1(
            harness,
            f"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(PACKAGING / "windows_database_safety.ps1")}'
. '{_literal(PACKAGING / "windows_bundled_database.ps1")}'
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
$before = Get-TicketboxC07WriterDatabaseFenceObservation
if ([int64]$before.OtherClientSessionCount -ne 1) {{
    throw (
        'real runtime session was not observed before fence: ' +
        ($before.ClientSessions | ConvertTo-Json -Compress -Depth 4)
    )
}}
$migrator = @($before.Roles | Where-Object {{ $_.name -ceq 'ticketbox_migrator' }})
$thirdParty = @($before.Roles | Where-Object {{ $_.name -ceq 'Third-Party Auditor' }})
if (
    $migrator.Count -ne 1 -or
    -not [bool]$migrator[0].can_assume_write_owner -or
    $thirdParty.Count -ne 1 -or
    $thirdParty[0].disposition -cne 'inert_unregistered'
) {{
    throw 'real PG17 SET-role or opaque observed-role semantics drifted'
}}
$authority = [pscustomobject]@{{
    Receipt = [pscustomobject]@{{
        operation_id = '01234567-89ab-cdef-0123-456789abcdef'
    }}
    ReleaseIdentity = $release
}}
$intent = [pscustomobject]@{{
    AuthorityPhase = [string]$before.AuthorityPhase
    PublicConnect = [bool]$before.PublicConnect
    Roles = @($before.Roles)
    Payload = [pscustomobject]@{{
        authority_phase = [string]$before.AuthorityPhase
        public_connect = [bool]$before.PublicConnect
        roles = @($before.Roles)
    }}
}}
$after = Enter-TicketboxC07WriterDatabaseFence `
    -Authority $authority `
    -Intent $intent
    Assert-TicketboxC07WriterDatabaseFence -Observation $after
    if ([int64]$after.OtherClientSessionCount -ne 0) {{
        throw 'real runtime session survived durable fence'
    }}
$retry = Enter-TicketboxC07WriterDatabaseFence `
    -Authority $authority `
    -Intent $intent
if ([int64]$retry.OtherClientSessionCount -ne 0) {{
    throw 'real PG17 writer fence was not idempotent'
}}
""",
        )
        _run_harness(engine, harness, timeout=40)
        _, session_stderr = runtime_session.communicate(timeout=10)
        assert runtime_session.returncode != 0, session_stderr
        runtime_session = None
        _, startup_stderr = startup_session.communicate(timeout=10)
        assert startup_session.returncode != 0, startup_stderr
        startup_session = None
        drained_startup = run_sql(
            "postgres",
            "postgres",
            (
                "SELECT count(*) FROM pg_stat_activity "
                f"WHERE pid = {startup_backend_pid} UNION ALL "
                "SELECT count(*) FROM pg_locks "
                f"WHERE pid = {startup_backend_pid};"
            ),
        )
        assert drained_startup.returncode == 0, (
            drained_startup.stdout + drained_startup.stderr
        )
        assert drained_startup.stdout.split() == ["0", "0"]

        rejected_write = run_sql(
            "ticketbox",
            "ticketbox_runtime",
            "INSERT INTO public.accounts(value) VALUES (2);",
            runtime_password=True,
        )
        assert rejected_write.returncode != 0
        post_count = run_sql(
            "ticketbox",
            "postgres",
            "SELECT count(*) FROM public.accounts;",
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
        _cleanup_pg_fence_processes(
            [legacy_session, unknown_session, runtime_session, startup_session],
            control_session,
        )
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
