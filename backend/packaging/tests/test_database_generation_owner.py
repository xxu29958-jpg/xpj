import re
from pathlib import Path

import pytest
from _powershell_contract import powershell_function as _function

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]
BACKEND = PACKAGING.parent
OWNER = PACKAGING / "windows_database_generation.ps1"
CONTRACT = PACKAGING / "windows_database_generation_contract.ps1"
RELEASE = PACKAGING / "windows_database_generation_release.ps1"
FAILURE = PACKAGING / "windows_operation_failure.ps1"
ARTIFACTS = PACKAGING / "windows_database_generation_artifacts.ps1"
CURRENT = PACKAGING / "windows_database_generation_current.ps1"
CREDENTIALS = PACKAGING / "windows_database_generation_credentials.ps1"
ROLE_FENCE = PACKAGING / "windows_database_generation_role_fence.ps1"
DATABASE_BINDING = PACKAGING / "windows_database_generation_database_binding.ps1"
COMMIT_VERIFIER = PACKAGING / "windows_database_generation_commit_verifier.ps1"
POLICY = PACKAGING / "windows_database_generation_policy.ps1"
RETIRED_ADAPTER = PACKAGING / "windows_database_generation_adapter.ps1"
SOURCE = PACKAGING / "windows_database_generation_source.ps1"
SOURCE_BINDING = PACKAGING / "windows_database_generation_source_binding.ps1"
HOST_AUTHORITY = PACKAGING / "windows_database_generation_host_authority.ps1"
ROLE_BOOTSTRAP = PACKAGING / "windows_database_generation_role_bootstrap.ps1"
RECOVERY_EVIDENCE = PACKAGING / "windows_database_generation_recovery_evidence.ps1"
TARGET_RECOVERY = PACKAGING / "windows_database_generation_target_recovery.ps1"
TARGET_AUTHORIZATION = PACKAGING / "windows_database_generation_target_authorization.ps1"
PROJECTION = PACKAGING / "windows_database_generation_projection.ps1"
LIFECYCLE_LOCK = PACKAGING / "windows_lifecycle_lock.ps1"
PREPARE = PACKAGING / "prepare_bundled_upgrade.ps1"
RETIRED_C07_RECOVERY = PACKAGING / "windows_c07_recovery_generation.ps1"
RETIRED_C07_AUTHORITY = PACKAGING / "windows_c07_heartbeat_authority.ps1"
RETIRED_C07_LIFECYCLE = PACKAGING / "windows_c07_lifecycle.ps1"
RETIRED_C07_HEARTBEAT_HELPER = PACKAGING / "windows_c07_heartbeat_helper.ps1"
RETIRED_C07_FAILURE_SUMMARY = PACKAGING / "windows_c07_failure_summary.ps1"
RETIRED_C07_DEADLINE_POLICY = PACKAGING / "windows_c07_deadline_policy.ps1"
RETIRED_C07_WRITER_FENCE = PACKAGING / "c07_lifecycle" / "writer_fence.ps1"
RETIRED_C07_WRITER_FENCE_POLICY = PACKAGING / "c07_lifecycle" / "writer_fence" / "policy.ps1"
RETIRED_C07_WRITER_FENCE_ADAPTER = PACKAGING / "c07_lifecycle" / "writer_fence" / "adapter.ps1"
INSTALLER = PACKAGING / "install_bundled_services.ps1"
ISS = PACKAGING / "ticketbox-installer.iss"
FLOW = PACKAGING / "ticketbox-installer-flow.isph"
BUILD = PACKAGING / "build_inno_installer.ps1"
PROVENANCE = BACKEND / "scripts" / "windows_build_provenance.ps1"
BACKEND_BUILD = BACKEND / "scripts" / "build_backend_exe.ps1"
BACKEND_PROVENANCE = BACKEND / "scripts" / "windows_backend_build_provenance.ps1"
GENERATION_PROGRAM_BUILD = BACKEND / "scripts" / "build_database_generation_program.py"
BACKEND_SPEC = PACKAGING / "ticketbox-backend.spec"
RELEASE_CONFIG = PACKAGING / "windows-release-config.json"
BUILD_TOOLCHAIN = PACKAGING / "windows-build-toolchain.json"
_C07_RETIREMENT_GUARDS = {
    BACKEND_SPEC: (
        "retired_c07_modules = sorted(",
        'if module == "app.database_generation_c07_contract"',
        'or module.startswith("app.database._c07_")',
        "if retired_c07_modules:",
        '"retired C07 database modules returned to the frozen source graph: "',
        '+ ", ".join(retired_c07_modules)',
        "*retired_c07_modules,",
    ),
    BACKEND_BUILD: (
        "$retiredC07Sources = @(",
        '-Filter "_c07_*.py"',
        "$retiredC07Contract = Join-Path `",
        '"app\\database_generation_c07_contract.py"',
        "if ($retiredC07Sources.Count -ne 0 -or (Test-Path -LiteralPath $retiredC07Contract)) {",
        'throw "Retired C07 database modules returned to the source snapshot."',
        "$_ -match \"'app\\.database\\._c07_[^']+'$\" -or",
        "$_ -match \"'app\\.database_generation_c07_contract'$\"",
        'throw "Frozen backend archive contains retired C07 database modules."',
    ),
}


def _inno_function(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index(f"function {next_name}(", start)
    return source[start:end]


def _owner_failure_handoff_is_exact(source: str) -> bool:
    owner = _function(source, "Invoke-TicketboxInstalledDatabaseGeneration")
    normalized = re.sub(r"\s+", " ", owner)
    return "Throw-TicketboxOperationFailure $primary $cleanup" in normalized


def _unexpected_c07_production_lines(sources: dict[Path, str]) -> list[str]:
    violations: list[str] = []
    for path, source in sources.items():
        remaining = list(_C07_RETIREMENT_GUARDS.get(path, ()))
        for line_number, line in enumerate(source.splitlines(), start=1):
            if "c07" not in line.lower():
                continue
            stripped = line.strip()
            if stripped in remaining:
                remaining.remove(stripped)
            else:
                violations.append(f"{path}:{line_number}:{stripped}")
        violations.extend(f"{path}:missing:{line}" for line in remaining)
    return violations


def test_generation_owner_is_one_real_shipped_consumer_and_retires_old_authorities() -> None:
    owner = OWNER.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")
    artifacts = ARTIFACTS.read_text(encoding="utf-8-sig") + CURRENT.read_text(encoding="utf-8-sig")
    credentials = CREDENTIALS.read_text(encoding="utf-8-sig")
    role_fence = ROLE_FENCE.read_text(encoding="utf-8-sig")
    database_binding = DATABASE_BINDING.read_text(encoding="utf-8-sig")
    commit_verifier = COMMIT_VERIFIER.read_text(encoding="utf-8-sig")
    policy = POLICY.read_text(encoding="utf-8-sig")
    source = "\n".join(
        path.read_text(encoding="utf-8-sig") for path in (HOST_AUTHORITY, ROLE_BOOTSTRAP, SOURCE, SOURCE_BINDING)
    )
    recovery_evidence = RECOVERY_EVIDENCE.read_text(encoding="utf-8-sig")
    target_recovery = TARGET_RECOVERY.read_text(encoding="utf-8-sig")
    target_authorization = TARGET_AUTHORIZATION.read_text(encoding="utf-8-sig")
    installer = INSTALLER.read_text(encoding="utf-8-sig")
    flow = FLOW.read_text(encoding="utf-8-sig")
    production = "\n".join(path.read_text(encoding="utf-8-sig") for path in PACKAGING.rglob("*.ps1"))
    production_sources: dict[Path, str] = {}
    for path in PACKAGING.rglob("*"):
        if (
            not path.is_file()
            or "tests" in path.parts
            or path.suffix.lower()
            not in {
                ".isph",
                ".iss",
                ".json",
                ".ps1",
                ".py",
                ".spec",
            }
        ):
            continue
        production_sources[path] = path.read_text(encoding="utf-8-sig")
    for path in (
        BACKEND_BUILD,
        BACKEND_PROVENANCE,
        GENERATION_PROGRAM_BUILD,
        PROVENANCE,
        RELEASE_CONFIG,
        BUILD_TOOLCHAIN,
    ):
        production_sources[path] = path.read_text(encoding="utf-8-sig")
    assert _unexpected_c07_production_lines(production_sources) == []
    for mutation_path in (
        BACKEND_SPEC,
        BACKEND_BUILD,
        BACKEND_PROVENANCE,
        GENERATION_PROGRAM_BUILD,
        PROVENANCE,
        RELEASE_CONFIG,
        BUILD_TOOLCHAIN,
    ):
        mutated = dict(production_sources)
        mutated[mutation_path] += "\npositive_ticketbox_c07_lifecycle_producer\n"
        assert _unexpected_c07_production_lines(mutated)
    assert installer.count("Invoke-TicketboxInstalledDatabaseGeneration `") == 1
    assert ". $C07DatabaseScript" not in installer
    for database_owner in (
        "windows_postgresql_database_command.ps1",
        "windows_ticketbox_database_contract.ps1",
        "windows_ticketbox_database_acl.ps1",
        "windows_ticketbox_database_acl_observation.ps1",
        "windows_ticketbox_database_roles.ps1",
    ):
        assert owner.count(f'"{database_owner}"') == 1
    assert '"windows_c07_database.ps1"' not in owner
    assert "New-TicketboxDatabaseGenerationIntent `" not in installer
    assert installer.count("Read-TicketboxDatabaseGenerationIntentContext `") == 1
    prepare_to_install = _inno_function(
        flow,
        "PrepareToInstall",
        "AuthoritativePayloadReplacementPrepared",
    )
    assert prepare_to_install.count("-PersistDatabaseGenerationIntentOnly") == 1
    assert prepare_to_install.index("-PersistDatabaseGenerationIntentOnly") < (
        prepare_to_install.index("install_windows_prerequisites.ps1")
    )
    prepare = (PACKAGING / "prepare_bundled_upgrade.ps1").read_text(encoding="utf-8-sig")
    persist_branch = re.search(
        r"(?m)^    if \(\$PersistDatabaseGenerationIntentOnly\) \{$",
        prepare,
    )
    assert persist_branch is not None
    persist_end = prepare.index("    # A trusted older installer", persist_branch.end())
    persist_body = prepare[persist_branch.end() : persist_end]
    eligibility = persist_body.index("Start-TicketboxDatabaseGenerationIntent `")
    assert "New-TicketboxDatabaseGenerationIntent" not in persist_body
    for hostile_existing_fact in (
        "$HasPersistedInstalledReleaseConfig",
        "$LifecycleReceiptPath",
        "$InstalledBuildManifestPath",
        "$BackendExe",
        "$PgBootstrapRecoveryPath",
    ):
        assert hostile_existing_fact in persist_body[:eligibility]
    payload_replacement = _inno_function(
        flow,
        "PrepareAuthoritativePayloadReplacement",
        "PrepareToInstall",
    )
    assert "StartDataRootMutationGuard(" in payload_replacement
    assert "-PersistDatabaseGenerationIntentOnly" not in payload_replacement
    for retired in (
        "Invoke-TicketboxC07InstalledReleaseMigration",
        "Complete-TicketboxInstalledRuntimePublication",
        "Invoke-TicketboxC07InstalledProductionLifecycle",
        "Invoke-TicketboxC07ProductionLifecycleCoordinator",
        "Invoke-TicketboxC07ProductionAuthorityCoordinator",
        "Set-TicketboxLifecycleReceiptC07ReadyEvidence",
        "Invoke-TicketboxC07TargetRecoveryGeneration",
        "Test-TicketboxC07TargetRecoveryGenerationRestore",
        "TicketboxC07ProductionMarkerSchema",
        "TicketboxC07ProductionResultSchema",
        "TicketboxC07TargetCommitResultSchema",
        "TicketboxC07ProductionLifecycleBindingSchema",
    ):
        assert retired not in production
    for retired_path in (
        RETIRED_C07_RECOVERY,
        RETIRED_C07_AUTHORITY,
        RETIRED_C07_LIFECYCLE,
        RETIRED_C07_HEARTBEAT_HELPER,
        RETIRED_C07_FAILURE_SUMMARY,
        RETIRED_C07_DEADLINE_POLICY,
        RETIRED_C07_WRITER_FENCE,
        RETIRED_C07_WRITER_FENCE_POLICY,
        RETIRED_C07_WRITER_FENCE_ADAPTER,
        RETIRED_ADAPTER,
    ):
        assert not retired_path.exists()
        retired_relative = str(retired_path.relative_to(PACKAGING))
        for shipment_surface in (
            installer,
            ISS.read_text(encoding="utf-8-sig"),
            BUILD.read_text(encoding="utf-8-sig"),
            PROVENANCE.read_text(encoding="utf-8-sig"),
        ):
            assert retired_relative not in shipment_surface
            assert retired_relative.replace("\\", "/") not in shipment_surface
    assert "Invoke-TicketboxDatabaseGenerationTargetRecovery" in target_recovery
    assert "[scriptblock]" not in recovery_evidence + target_recovery
    assert "Invoke-TicketboxDatabaseGenerationTargetRecovery" in target_authorization
    assert "Get-TicketboxPostgresqlWriterFenceObservation" in role_fence
    assert "Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority" not in role_fence
    assert "target_recovery_evidence_sha256" in owner + database_binding
    assert "target_recovery_evidence_sha256" in artifacts
    assert "Get-TicketboxDatabaseGenerationExecutionDependencyPaths" not in commit_verifier
    assert "Assert-TicketboxDatabaseGenerationCommitReadyArtifact" not in artifacts
    for build_bound_tool_field in (
        "pg_dump_path",
        "pg_dump_size",
        "pg_dump_sha256",
        "pg_restore_path",
        "pg_restore_size",
        "pg_restore_sha256",
    ):
        assert build_bound_tool_field in contract
    assert "Assert-TicketboxDatabaseGenerationToolIdentity" in recovery_evidence
    assert recovery_evidence.count("Assert-TicketboxDatabaseGenerationToolIdentity") >= 5
    assert target_recovery.count("Assert-TicketboxDatabaseGenerationToolIdentity") >= 2
    assert "Resolve-TicketboxDatabaseGenerationNextAction" in policy
    assert "Publish-TicketboxDatabaseGenerationCurrent" in owner
    assert "host_contract_sha256" in policy
    assert "projection_contract_sha256" in policy
    assert "source_request_sha256" in policy + artifacts
    assert 'source_kind = "empty"' in source
    assert 'source_kind = "current_generation"' in source
    assert '"restored-source"' in artifacts + owner
    assert "Invoke-TicketboxDatabaseGenerationSourceBinding" in owner
    assert "Invoke-TicketboxDatabaseGenerationRestoredSource" in source
    assert "source_evidence_sha256" in artifacts + source
    assert "create_attempt_sha256" not in artifacts + source
    assert "backup_password" in artifacts
    assert "backup_scram_salt" in artifacts
    invoke_owner = _function(owner, "Invoke-TicketboxInstalledDatabaseGeneration")
    reducer_call = invoke_owner.index("$next = Resolve-TicketboxDatabaseGenerationNextAction $observation")
    assert "$needsBootstrapAuthority" not in invoke_owner
    assert "credentials = $credentials" not in invoke_owner[:reducer_call]
    assert "runtime_credentials = $runtimeCredentials" not in invoke_owner[:reducer_call]
    assert "credentials_present = $credentialsPresent" in invoke_owner[:reducer_call]
    assert "runtime_credentials_present = $runtimeCredentialsPresent" in invoke_owner[:reducer_call]
    assert invoke_owner.count("catch { $iterationCleanup += $_ }") >= 3
    cleanup_start = invoke_owner.index(
        "finally {",
        invoke_owner.index("catch { $iterationPrimary = $_ }"),
    )
    maintenance_cleanup = invoke_owner.index(
        "Close-TicketboxDatabaseGenerationMaintenanceAuthority `",
        cleanup_start,
    )
    credentials_cleanup = invoke_owner.index(
        "Close-TicketboxDatabaseGenerationCredentials $credentials",
        maintenance_cleanup,
    )
    runtime_cleanup = invoke_owner.index(
        "Close-TicketboxDatabaseGenerationRuntimeCredentials `",
        credentials_cleanup,
    )
    assert cleanup_start < maintenance_cleanup < credentials_cleanup < runtime_cleanup
    assert _owner_failure_handoff_is_exact(owner)
    for escaped_handoff in (
        owner.replace(
            "Throw-TicketboxOperationFailure $primary $cleanup",
            "Throw-TicketboxOperationFailure $primary @()",
        ),
        owner.replace(
            "Throw-TicketboxOperationFailure $primary $cleanup",
            "Throw-TicketboxOperationFailure $null $cleanup",
        ),
    ):
        assert not _owner_failure_handoff_is_exact(escaped_handoff)
    for leaked_mode in ("fresh_install", "legacy_adoption", "runtime_ready", "forward_repair"):
        assert leaked_mode not in (
            owner + policy + contract + artifacts + credentials + role_fence + database_binding + source
        )
    for name in (
        "windows_database_generation.ps1",
        "windows_database_generation_program_execution.ps1",
        "windows_database_generation_contract.ps1",
        "windows_database_generation_release.ps1",
        "windows_operation_failure.ps1",
        "windows_database_generation_artifacts.ps1",
        "windows_database_generation_commit_verifier.ps1",
        "windows_database_generation_evidence_verifier.ps1",
        "windows_database_generation_recovery_archive.ps1",
        "windows_database_generation_policy.ps1",
        "windows_database_generation_credentials.ps1",
        "windows_database_generation_role_fence.ps1",
        "windows_database_generation_database_binding.ps1",
        "windows_database_generation_current.ps1",
        "windows_database_generation_host_authority.ps1",
        "windows_database_generation_role_bootstrap.ps1",
        "windows_database_generation_source.ps1",
        "windows_database_generation_source_binding.ps1",
        "windows_database_generation_recovery_evidence.ps1",
        "windows_database_generation_target_recovery.ps1",
        "windows_database_generation_target_authorization.ps1",
        "windows_database_generation_projection.ps1",
    ):
        assert name in ISS.read_text(encoding="utf-8-sig")
        assert name in BUILD.read_text(encoding="utf-8-sig")
        assert name in PROVENANCE.read_text(encoding="utf-8-sig")
