from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
INSTALLER = PACKAGING / "install_bundled_services.ps1"
PREPARE = PACKAGING / "prepare_bundled_upgrade.ps1"
C07_DATABASE = PACKAGING / "windows_c07_database.ps1"
BUNDLED_DATABASE = PACKAGING / "windows_bundled_database.ps1"
C07_WRITER_FENCE_ADAPTER = (
    PACKAGING / "c07_lifecycle" / "writer_fence" / "adapter.ps1"
)


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


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_ps(engine: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=120,
        check=False,
    )


def test_installer_c07_caller_has_release_order_and_resume_guards() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    adapter = C07_WRITER_FENCE_ADAPTER.read_text(encoding="utf-8-sig")
    main = source[source.rindex("    $c07Disposition =") :]
    assert main.index("$c07Disposition =") < main.index(
        "Invoke-TicketboxC07InstalledReleaseMigration"
    )
    migration_path = main[main.index("$c07Migration =") :]
    assert migration_path.index("Invoke-TicketboxC07InstalledReleaseMigration") < migration_path.index(
        "Complete-TicketboxInstalledRuntimePublication"
    )
    assert migration_path.index("Complete-TicketboxInstalledRuntimePublication") < migration_path.index(
        "Resolve-TicketboxBootstrapExposureRecoveryIntent"
    )
    assert main.index("Resolve-TicketboxBootstrapExposureRecoveryIntent") < main.index(
        "Start-TicketboxOwnedServiceIfExists `\n            -Name $BackendServiceName"
    )

    qualification = _function(
        adapter,
        "Get-TicketboxC07PublishedRuntimeQualification",
    )
    assert qualification.index("Read-TicketboxC07Authority") < qualification.index(
        "Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority"
    )
    assert qualification.index('AuthorityPhase "published_runtime"') < qualification.index(
        "Assert-TicketboxC07PublishedDatabaseAuthority"
    )
    assert qualification.index("Assert-TicketboxC07PublishedDatabaseAuthority") < qualification.index(
        "Assert-TicketboxC07RuntimeCredential"
    )
    runtime_ready = main[main.index('if ($c07Disposition -ceq "runtime_ready")') :]
    assert runtime_ready.index("Read-EnvMap $EnvPath") < runtime_ready.index(
        "Complete-TicketboxInstalledRuntimePublication"
    )
    assert runtime_ready.index("Complete-TicketboxInstalledRuntimePublication") < runtime_ready.index(
        "Resolve-TicketboxBootstrapExposureRecoveryIntent"
    )
    runtime_publication_start = main.index(
        "$runtimePublication = Complete-TicketboxInstalledRuntimePublication"
    )
    runtime_publication_call = main[
        runtime_publication_start : main.index(
            "    $databaseUrl =", runtime_publication_start
        )
    ]
    for exact_binding in (
        "-Disposition $c07Disposition",
        "-DataRoot $DataRoot",
        "-HostAuthority $c07HostAuthority",
        "-ReleaseIdentity $c07ReleaseIdentity",
        "-C07Authority $c07Authority",
        "-RuntimePassword $runtimePassword",
        "-LifecycleReceipt $lifecycleReceipt",
        "-LifecycleLock $operationLock",
        "-RecoveryArtifactPath $c07RecoveryArtifactPath",
        "-RuntimeConnection $runtimeConnection",
        "-PsqlPath $Psql",
        "-ExpectedDataRoot $PgData",
        "-ExpectedPort $PgPort",
        "-DatabaseToolTimeoutMilliseconds $DatabaseToolTimeoutMs",
    ):
        assert exact_binding in runtime_publication_call
    assert re.search(
        r"-ObservationTimeoutMilliseconds\s+`?\s*"
        r"\$c07QualificationTimeoutMilliseconds\s+`",
        runtime_publication_call,
    )
    release = _function(source, "Invoke-TicketboxC07InstalledReleaseMigration")
    assert release.index("Invoke-TicketboxC07InstalledProductionLifecycle") < release.index(
        "Get-TicketboxC07PublishedRuntimeQualification"
    )
    environment = _function(source, "Write-TicketboxC07InstalledRuntimeEnvironment")
    assert environment.index("Assert-TicketboxC07PublishedRuntimeQualification") < environment.index(
        "Write-EnvNoBom"
    )
    cleanup = _function(source, "Complete-TicketboxC07InstalledSecretCleanup")
    assert cleanup.index("Assert-TicketboxC07PublishedRuntimeQualification") < cleanup.index(
        "Remove-TicketboxC07InstalledCredentials"
    )

    managed = _function(source, "Invoke-TicketboxInstalledManagedSchemaUpgrade")
    assert managed.index("Set-TicketboxC07DatabaseAuthorityCredential") < managed.index(
        "Read-TicketboxC07Authority"
    )
    assert managed.index("Read-TicketboxC07Authority") < managed.index(
        "Get-TicketboxC07InstalledAlembicRevision"
    )
    assert "Clear-TicketboxC07DatabaseAuthorityCredential" in managed
    assert managed.index("Invoke-TicketboxInstalledManagedSchemaUpgradeAction") < managed.index(
        "Get-TicketboxC07PublishedRuntimeQualification"
    )
    assert managed.index("Get-TicketboxC07PublishedRuntimeQualification") < managed.index(
        "Invoke-TicketboxC07RecoveredSuperuserAction"
    )
    assert re.search(
        r"Set-TicketboxC07DatabaseAuthorityCredential[\s\S]*?"
        r"try\s*\{[\s\S]*?finally\s*\{\s*"
        r"Clear-TicketboxC07DatabaseAuthorityCredential",
        managed,
    )

    successor_start = source.index("$c07SuccessorResolution =")
    successor_end = source.index("    $c07Disposition =", successor_start)
    successor = source[successor_start:successor_end]
    assert "Read-TicketboxC07Authority $DataRoot" in successor
    assert "Read-TicketboxC07DurableHeartbeatAuthority $DataRoot" not in successor

    release = _function(source, "Invoke-TicketboxC07InstalledReleaseMigration")
    assert "Clear-TicketboxC07DatabaseAuthorityCredential" in release
    assert re.search(
        r"Set-TicketboxC07DatabaseAuthorityCredential[\s\S]*?"
        r"try\s*\{[\s\S]*?finally\s*\{\s*"
        r"Clear-TicketboxC07DatabaseAuthorityCredential",
        release,
    )
    assert release.index("Get-TicketboxC07AuthorityPath") < release.index(
        "Initialize-TicketboxC07FreshDatabaseAuthority"
    )
    assert release.index("Get-TicketboxC07InstalledAlembicRevision") < release.index(
        "Invoke-TicketboxC07InstalledFreshSourceBootstrapAction"
    )
    assert release.index("New-TicketboxC07LifecycleOperation") < release.index(
        "Get-OrCreateTicketboxC07InstalledCredentials"
    )
    assert release.index("Get-OrCreateTicketboxC07InstalledCredentials") < release.index(
        "Invoke-TicketboxC07InstalledProductionLifecycle"
    )

    cleanup = _function(source, "Complete-TicketboxC07InstalledSecretCleanup")
    assert cleanup.index("RecoveryArtifactPath") < cleanup.index(
        "Remove-TicketboxC07InstalledCredentials"
    )
    assert cleanup.index("Remove-TicketboxC07InstalledCredentials") < cleanup.index(
        "Remove-TicketboxC07FreshBootstrapIntent"
    )
    assert cleanup.index("Remove-TicketboxC07FreshBootstrapIntent") < cleanup.index(
        "Remove-TicketboxSensitiveFile"
    )
    isolated = _function(
        source,
        "Invoke-TicketboxC07InstalledIsolatedReplayAction",
    )
    generation_program = _function(
        source,
        "Get-TicketboxInstalledDatabaseGenerationProgram",
    )
    assert "ExpectedMoneyFactsSha256" not in isolated
    assert "Get-TicketboxC07PackagedDatabaseGenerationProgram" in generation_program
    assert "Get-TicketboxC07InstalledUpgradePlan" not in source
    assert "Get-TicketboxInstalledManagedSchemaPlan" not in source
    assert "Invoke-TicketboxC07InstalledDescendantUpgrade" not in source

    managed = _function(source, "Invoke-TicketboxInstalledManagedSchemaUpgrade")
    acl_calls = [
        match.start()
        for match in re.finditer(
            "Set-TicketboxManagedSchemaRuntimeAcl",
            managed,
        )
    ]
    retire_calls = [
        match.start()
        for match in re.finditer(
            "Disable-TicketboxC07MigratorLogin",
            managed,
        )
    ]
    action_calls = [
        match.start()
        for match in re.finditer(
            r"\$upgradeResult = Invoke-TicketboxInstalledManagedSchemaUpgradeAction",
            managed,
        )
    ]
    enable_calls = [
        match.start()
        for match in re.finditer(
            "Enable-TicketboxC07MigratorForManagedSchemaUpgrade",
            managed,
        )
    ]
    assert len(action_calls) == len(enable_calls) == len(acl_calls) == 2
    assert len(retire_calls) == 4
    assert retire_calls[0] < enable_calls[0] < action_calls[0] < acl_calls[0]
    assert acl_calls[0] < retire_calls[1]
    assert retire_calls[1] < retire_calls[2] < enable_calls[1]
    assert enable_calls[1] < action_calls[1] < acl_calls[1] < retire_calls[3]
    assert retire_calls[3] < managed.index("Get-TicketboxC07PublishedRuntimeQualification")
    publication = _function(
        source,
        "Complete-TicketboxInstalledManagedSchemaPublication",
    )
    assert publication.index("Invoke-TicketboxInstalledManagedSchemaUpgrade") < publication.index(
        "Read-TicketboxC07DurableHeartbeatAuthority"
    )
    assert publication.index("Read-TicketboxC07DurableHeartbeatAuthority") < publication.index(
        "return [pscustomobject][ordered]"
    )
    runtime_publication = _function(
        source,
        "Complete-TicketboxInstalledRuntimePublication",
    )
    assert runtime_publication.index(
        "Complete-TicketboxInstalledManagedSchemaPublication"
    ) < runtime_publication.index("Write-TicketboxC07InstalledRuntimeEnvironment")
    assert runtime_publication.index(
        "Write-TicketboxC07InstalledRuntimeEnvironment"
    ) < runtime_publication.index("Complete-TicketboxC07InstalledSecretCleanup")


def test_installed_payload_authority_lease_spans_c07_under_lifecycle_lock() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    validate_read = source.index("$installedBuildManifest = Read-TicketboxInstalledBuildManifest")
    validate_only = source.index("if ($ValidateOnly)", validate_read)
    lifecycle_lock = source.index("$operationLock = Enter-TicketboxLifecycleLock")
    lease_slot = source.index("$installedC07PayloadLease = $null", lifecycle_lock)
    main_try = source.index("try {", lease_slot)
    acl_repair = source.index(
        "Initialize-TicketboxSecureInstallRoot",
        main_try,
    )
    enter = source.index(
        "Enter-TicketboxInstalledC07PayloadAuthorityLease",
        main_try,
    )
    first_c07_consumption = source.index(
        "Invoke-TicketboxC07InstalledReleaseMigration",
        enter,
    )
    finalizer = source.rindex(
        "finally {\n    [Exception[]]$finalizationFailures"
    )
    close = source.index(
        "Close-TicketboxInstalledC07PayloadAuthorityLease",
        finalizer,
    )
    exit_lock = source.index("Exit-TicketboxLifecycleLock", close)

    assert validate_read < validate_only < lifecycle_lock
    assert lifecycle_lock < lease_slot < main_try < acl_repair < enter
    assert enter < first_c07_consumption < finalizer < close < exit_lock
    sealed_span = source[enter:close]
    assert "Initialize-TicketboxSecureInstallRoot" not in sealed_span
    assert "Set-TicketboxExactDirectoryAcl" not in sealed_span

    prepare = (PACKAGING / "prepare_bundled_upgrade.ps1").read_text(
        encoding="utf-8-sig"
    )
    repair_start = prepare.index("function Repair-TicketboxPreflightInstallAcl")
    repair_end = prepare.index("\nfunction ", repair_start + 1)
    repair = prepare[repair_start:repair_end]
    assert "Initialize-TicketboxSecureInstallRoot" in repair
    interrupted_start = prepare.index(
        "function Repair-TicketboxInterruptedPayloadLeaseAcl"
    )
    interrupted_end = prepare.index("\nfunction ", interrupted_start + 1)
    interrupted_repair = prepare[interrupted_start:interrupted_end]
    remove_stale_deny = interrupted_repair.index(
        "Remove-TicketboxInterruptedInstalledPayloadMutationDeny"
    )
    normalize_install_root = interrupted_repair.index(
        "Repair-TicketboxPreflightInstallAcl"
    )
    assert remove_stale_deny < normalize_install_root
    assert prepare.index("Repair-TicketboxPreflightInstallAcl") < prepare.index(
        "Disable-TicketboxOwnedServiceIfExists",
        prepare.index("$installAclMutationStarted = $false"),
    )

    stale_start = prepare.index(
        "if (Test-Path -LiteralPath $LifecycleReceiptPath -PathType Leaf)"
    )
    stale_end = prepare.index(
        "$hasPgService = Test-TicketboxServiceExists",
        stale_start,
    )
    stale_flow = prepare[stale_start:stale_end]
    deferred_start = stale_flow.index(
        'elseif ([string]$staleReceipt.preparation_stage -eq '
        '"program_files_installed_backup_pending")'
    )
    post_copy_start = stale_flow.index(
        "        else {\n"
        "            Set-TicketboxInstalledReleaseConfiguration",
        deferred_start,
    )
    deferred_branch = stale_flow[deferred_start:post_copy_start]
    post_copy_branch = stale_flow[post_copy_start:]
    for branch in (deferred_branch, post_copy_branch):
        repair_acl = branch.index(
            "Repair-TicketboxInterruptedPayloadLeaseAcl"
        )
        recover = branch.index("Invoke-TicketboxPreparedInstallRecovery")
        branch_return = branch.index("return", recover)
        assert repair_acl < recover < branch_return


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_installer_c07_failure_code_is_machine_readable(engine: str) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    helper = _function(
        source,
        "New-TicketboxC07InstalledLifecycleFailure",
    )
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            helper,
            "$failure = New-TicketboxC07InstalledLifecycleFailure "
            "([pscustomobject]@{ failure_code = 'manifest_not_ready' })",
            "$invalidRejected = $false",
            "try { New-TicketboxC07InstalledLifecycleFailure "
            "([pscustomobject]@{ failure_code = '../invalid' }) | Out-Null } "
            "catch { $invalidRejected = $true }",
            "[ordered]@{",
            "  type = $failure.GetType().FullName",
            "  message = $failure.Message",
            "  failure_code = "
            "$failure.Data['TicketboxC07FailureCode']",
            "  invalid_rejected = $invalidRejected",
            "} | ConvertTo-Json -Compress",
        )
    )

    result = _run_ps(engine, script)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "type": "System.InvalidOperationException",
        "message": (
            "C07 installed lifecycle failure_code=manifest_not_ready"
        ),
        "failure_code": "manifest_not_ready",
        "invalid_rejected": True,
    }


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_installer_c07_failure_terminal_preserves_code_without_budget_or_secrets(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    lifecycle_failure = _function(
        source,
        "New-TicketboxC07InstalledLifecycleFailure",
    )
    release_migration = _function(
        source,
        "Invoke-TicketboxC07InstalledReleaseMigration",
    )
    operation_id = "123e4567-e89b-42d3-a456-4266141740ac"
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            "$DataRoot = 'C:\\ProgramData\\TicketBox'",
            "$script:TicketboxC07InstallerSourceRevision = '20260722_0001'",
            "$script:TicketboxC07TargetRevision = '20260729_0001'",
            "$script:TicketboxC07FailureStages = "
            "@('refused_pre_ddl', 'repair_required')",
            "$script:secretCalls = 0",
            "$script:budgetCalls = 0",
            "$script:lifecycleCalls = 0",
            "$script:credentialSetCalls = 0",
            "$script:credentialClearCalls = 0",
            "$script:testStage = 'refused_pre_ddl'",
            lifecycle_failure,
            release_migration,
            "function Resolve-TicketboxC07DatabaseHostAuthority { "
            "[pscustomobject]@{} }",
            "function Get-TicketboxInstalledDatabaseGenerationProgram { "
            "[pscustomobject]@{ c07_source_revision = '20260722_0001'; "
            "c07_target_revision = '20260729_0001'; "
            "c07_revision_manifest_sha256 = ('a' * 64); "
            "c07_revision_manifest = [pscustomobject]@{ operation_kind = "
            "'c07_money_minor_bigint_v1' }; target_revision = "
            "'20260809_0001'; generation_program_sha256 = ('b' * 64) } }",
            "function Assert-TicketboxC07LowerSha256 { param($Value, $Label) }",
            "function Set-TicketboxC07DatabaseAuthorityCredential { "
            "$script:credentialSetCalls += 1 }",
            "function Clear-TicketboxC07DatabaseAuthorityCredential { "
            "$script:credentialClearCalls += 1 }",
            "function Invoke-TicketboxC07RecoveredSuperuserAction { "
            "param($HostAuthority, $RecoveryArtifactPath, $Action); "
            "$secret = [Security.SecureString]::new(); "
            "& $Action $secret }",
            "function New-TicketboxC07LifecycleOperation { "
            "[pscustomobject]@{ OperationId = '"
            + operation_id
            + "'; Stage = $script:testStage } }",
            "function Read-TicketboxC07Authority { "
            "[pscustomobject]@{ Receipt = [pscustomobject]@{ "
            "stage = $script:testStage; failure_code = "
            "'maintenance_attempts_exhausted' } } }",
            "function Get-OrCreateTicketboxC07InstalledCredentials { "
            "param($DataRoot, $LifecycleLock, $Mode); "
            "$script:secretCalls += 1; [pscustomobject]@{ "
            "RuntimePassword = [Security.SecureString]::new(); "
            "MigratorPassword = [Security.SecureString]::new() } }",
            "function New-TicketboxC07MaintenanceBudget { "
            "$script:budgetCalls += 1; [pscustomobject]@{ "
            "DeadlineUtc = [DateTime]::UtcNow.AddMinutes(20) } }",
                "function Invoke-TicketboxC07InstalledProductionLifecycle { "
            "$script:lifecycleCalls += 1; [pscustomobject]@{ "
            "result = 'ready'; operation_id = '"
            + operation_id
            + "'; target_revision = '20260729_0001'; "
            "production_authority_sha256 = ('A' * 64); "
                "runtime_projection_sha256 = ('B' * 64) } }",
                "function Get-TicketboxC07PublishedRuntimeQualification { "
                "param($DataRoot, $HostAuthority, $DatabaseAuthorityCredential, "
                "$RuntimePassword, $ExpectedOperationId, "
                "$ObservationTimeoutMilliseconds); "
                "[pscustomobject]@{ schema = "
                "'ticketbox-c07-published-runtime-qualification-v1'; "
                "operation_id = $ExpectedOperationId; "
                "ready_verification_sha256 = ('c' * 64); "
                "ready_semantics = 'published_runtime'; "
                "production_authority_sha256 = ('A' * 64); "
                "runtime_projection_sha256 = ('B' * 64) } }",
            "$releaseIdentity = [pscustomobject]@{ "
            "InstallationIdentityState = 'PENDING'; "
            "InstallationOperationId = '"
            + operation_id
            + "' }",
            "$caught = $null",
            "try { Invoke-TicketboxC07InstalledReleaseMigration "
            "-ReleaseIdentity $releaseIdentity -Mode legacy_adoption "
            "-LifecycleLock ([pscustomobject]@{}) -FreshIntent $null "
            "-RecoveryArtifactPath 'C:\\recovery.json' | Out-Null } "
            "catch { $caught = $_.Exception }",
            "$failureSecretCalls = $script:secretCalls",
            "$failureBudgetCalls = $script:budgetCalls",
            "$failureLifecycleCalls = $script:lifecycleCalls",
            "$script:testStage = 'ready'",
            "$ready = Invoke-TicketboxC07InstalledReleaseMigration "
            "-ReleaseIdentity $releaseIdentity -Mode legacy_adoption "
            "-LifecycleLock ([pscustomobject]@{}) -FreshIntent $null "
            "-RecoveryArtifactPath 'C:\\recovery.json'",
            "[ordered]@{",
            "  type = $caught.GetType().FullName",
            "  message = $caught.Message",
            "  failure_code = "
            "$caught.Data['TicketboxC07FailureCode']",
            "  failure_secret_calls = $failureSecretCalls",
            "  failure_budget_calls = $failureBudgetCalls",
            "  failure_lifecycle_calls = $failureLifecycleCalls",
            "  ready_result = [string]$ready.result",
            "  ready_secret_calls = $script:secretCalls",
            "  ready_budget_calls = $script:budgetCalls",
            "  ready_lifecycle_calls = $script:lifecycleCalls",
            "  credential_set_calls = $script:credentialSetCalls",
            "  credential_clear_calls = $script:credentialClearCalls",
            "} | ConvertTo-Json -Compress",
        )
    )

    result = _run_ps(engine, script)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "type": "System.InvalidOperationException",
        "message": (
            "C07 installed lifecycle "
            "failure_code=maintenance_attempts_exhausted"
        ),
        "failure_code": "maintenance_attempts_exhausted",
        "failure_secret_calls": 0,
        "failure_budget_calls": 0,
        "failure_lifecycle_calls": 0,
        "ready_result": "ready",
        "ready_secret_calls": 1,
        "ready_budget_calls": 0,
        "ready_lifecycle_calls": 1,
        "credential_set_calls": 2,
        "credential_clear_calls": 2,
    }


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_installer_compensation_failure_preserves_both_typed_causes(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    helper = _function(
        source,
        "New-TicketboxInstallCompensationAggregateFailure",
    )
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            helper,
            "$install = [InvalidOperationException]::new('install failed')",
            "$install.Data['TicketboxC07FailureCode'] = 'manifest_not_ready'",
            "$compensation = "
            "[InvalidOperationException]::new('compensation failed')",
            "$failure = New-TicketboxInstallCompensationAggregateFailure "
            "-InstallFailure $install -CompensationFailure $compensation",
            "[ordered]@{",
            "  type = $failure.GetType().FullName",
            "  inner_count = $failure.InnerExceptions.Count",
            "  install_message = $failure.InnerExceptions[0].Message",
            "  compensation_message = $failure.InnerExceptions[1].Message",
            "  failure_code = $failure.Data['TicketboxC07FailureCode']",
            "  compensation_failed = "
            "$failure.Data['TicketboxInstallCompensationFailed']",
            "} | ConvertTo-Json -Compress",
        )
    )

    result = _run_ps(engine, script)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "type": "System.AggregateException",
        "inner_count": 2,
        "install_message": "install failed",
        "compensation_message": "compensation failed",
        "failure_code": "manifest_not_ready",
        "compensation_failed": True,
    }


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_install_failure_preserves_action_all_compensations_and_finalizers(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    compensation_start = source.index(
        "function Invoke-TicketboxInstallFailureCompensation {"
    )
    compensation_helper = source[
        compensation_start : source.index(
            '\nWrite-Host "=== 小票夹 Inno 安装器服务配置 ==="',
            compensation_start,
        )
    ]
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(
                source,
                "New-TicketboxInstallCompensationAggregateFailure",
            ),
            _function(
                source,
                "New-TicketboxInstallFinalizationAggregateFailure",
            ),
            _function(
                source,
                "New-TicketboxInstallServiceCompensationAuthority",
            ),
            _function(
                source,
                "Assert-TicketboxInstallServiceCompensationAuthority",
            ),
            _function(
                source,
                "Grant-TicketboxInstallServiceCompensationAuthority",
            ),
            compensation_helper,
            "$script:BackendServiceName = 'TicketboxBackend'",
            "$script:PgServiceName = 'TicketboxPostgres'",
            "$script:ShawlExe = 'C:\\ticketbox\\shawl.exe'",
            "$script:BackendExe = 'C:\\ticketbox\\backend.exe'",
            "$script:BackendPort = 8002",
            "$script:PgCtl = 'C:\\ticketbox\\pg_ctl.exe'",
            "$script:PgBin = 'C:\\ticketbox\\pg'",
            "$script:PgPort = 5440",
            "$script:InitdbExe = 'C:\\ticketbox\\initdb.exe'",
            "$script:InitdbServiceReceiptPath = "
            "'C:\\ticketbox-data\\initdb-one-shot-receipt.json'",
            "$script:InstallerState = 'C:\\ticketbox\\state'",
            "$script:LegacyRecoveryRequiredPath = 'C:\\legacy.json'",
            "$script:RecoveryRequiredPath = 'C:\\current.json'",
            "$script:InstallDir = 'C:\\ticketbox'",
            "$script:DataRoot = 'C:\\ticketbox-data'",
            "$script:ServiceWaitArguments = @{ "
            "TimeoutMilliseconds = 100; PollMilliseconds = 10 }",
            "function Service-Exists { return $true }",
            "function Get-TicketboxServiceExecutablePath {",
            "  param($Name)",
            "  if ($Name -ceq $script:PgServiceName) { return $script:PgCtl }",
            "  return $script:ShawlExe",
            "}",
            "function Test-TicketboxPathEquals {",
            "  param($Left, $Right)",
            "  return ([string]$Left).Equals(",
            "    [string]$Right,",
            "    [StringComparison]::OrdinalIgnoreCase",
            "  )",
            "}",
            "function Disable-TicketboxOwnedServiceIfExists {",
            "  param($Name, $ExpectedExecutable, $BackendPort, "
            "$ExpectedRuntimeExecutables, $TimeoutMilliseconds, "
            "$PollMilliseconds)",
            "  if ($Name -ceq $script:BackendServiceName) {",
            "    $failure = [UnauthorizedAccessException]::new("
            "'backend disable failed')",
            "    $failure.Data['TicketboxC07FailureCode'] = "
            "'backend_disable_denied'",
            "    throw $failure",
            "  }",
            "  $failure = [InvalidOperationException]::new("
            "'postgres disable failed')",
            "  $failure.Data['TicketboxC07FailureCode'] = "
            "'postgres_disable_failed'",
            "  throw $failure",
            "}",
            "function Assert-TicketboxPgClusterStoppedAfterFailure {",
            "  $failure = [TimeoutException]::new("
            "'cluster stopped assertion failed')",
            "  $failure.Data['TicketboxC07FailureCode'] = "
            "'cluster_stop_unconfirmed'",
            "  throw $failure",
            "}",
            "function Ensure-TicketboxInstallerRecoveryMarkerAfterFailure {",
            "  param($InstallerStatePath, $LegacyPath, $CurrentPath, "
            "$InstallDir, $DataRoot, $Reason)",
            "  $failure = [IO.IOException]::new("
            "'recovery marker failed')",
            "  $failure.Data['TicketboxC07FailureCode'] = "
            "'recovery_marker_write_failed'",
            "  throw $failure",
            "}",
            "$compensationAuthority = "
            "New-TicketboxInstallServiceCompensationAuthority",
            "Grant-TicketboxInstallServiceCompensationAuthority "
            "-Authority $compensationAuthority -Service BackendService "
            "-Grant validated_preexisting",
            "Grant-TicketboxInstallServiceCompensationAuthority "
            "-Authority $compensationAuthority -Service PostgresService "
            "-Grant validated_preexisting",
            "$compensation = $null",
            "try {",
            "  Invoke-TicketboxInstallFailureCompensation "
            "-Reason 'install failed' "
            "-ServiceCompensationAuthority $compensationAuthority",
            "}",
            "catch { $compensation = $_.Exception }",
            "if ($null -eq $compensation) { "
            "throw 'expected compensation failure' }",
            "$install = [FormatException]::new('install action failed')",
            "$install.Data['TicketboxC07FailureCode'] = 'install_action_failed'",
            "$operation = New-TicketboxInstallCompensationAggregateFailure "
            "-InstallFailure $install -CompensationFailure $compensation",
            "$close = [IO.InvalidDataException]::new("
            "'payload lease close failed')",
            "$close.Data['TicketboxC07FailureCode'] = "
            "'payload_lease_close_failed'",
            "$close.Data['TicketboxInstallFinalizationStep'] = "
            "'payload_lease_close'",
            "$unlock = [ApplicationException]::new('lifecycle lock exit failed')",
            "$unlock.Data['TicketboxC07FailureCode'] = "
            "'lifecycle_lock_exit_failed'",
            "$unlock.Data['TicketboxInstallFinalizationStep'] = "
            "'lifecycle_lock_exit'",
            "$failure = New-TicketboxInstallFinalizationAggregateFailure "
            "-OperationFailure $operation "
            "-FinalizationFailures ([Exception[]]@($close, $unlock))",
            "$records = @($failure.InnerExceptions | ForEach-Object {",
            "  [ordered]@{",
            "    type = $_.GetType().FullName",
            "    message = $_.Message",
            "    compensation_step = "
            "[string]$_.Data['TicketboxInstallCompensationStep']",
            "    finalization_step = "
            "[string]$_.Data['TicketboxInstallFinalizationStep']",
            "    failure_code = [string]$_.Data['TicketboxC07FailureCode']",
            "  }",
            "})",
            "[ordered]@{",
            "  type = $failure.GetType().FullName",
            "  inner_count = $failure.InnerExceptions.Count",
            "  records = $records",
            "  failure_codes = $failure.Data['TicketboxC07FailureCodes']",
            "  compensation_failed = "
            "$failure.Data['TicketboxInstallCompensationFailed']",
            "  finalization_failed = "
            "$failure.Data['TicketboxInstallFinalizationFailed']",
            "} | ConvertTo-Json -Compress -Depth 5",
        )
    )

    result = _run_ps(engine, script)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "type": "System.AggregateException",
        "inner_count": 7,
        "records": [
            {
                "type": "System.FormatException",
                "message": "install action failed",
                "compensation_step": "",
                "finalization_step": "",
                "failure_code": "install_action_failed",
            },
            {
                "type": "System.UnauthorizedAccessException",
                "message": "backend disable failed",
                "compensation_step": "backend_disable",
                "finalization_step": "",
                "failure_code": "backend_disable_denied",
            },
            {
                "type": "System.InvalidOperationException",
                "message": "postgres disable failed",
                "compensation_step": "postgres_disable",
                "finalization_step": "",
                "failure_code": "postgres_disable_failed",
            },
            {
                "type": "System.TimeoutException",
                "message": "cluster stopped assertion failed",
                "compensation_step": "cluster_stopped_assertion",
                "finalization_step": "",
                "failure_code": "cluster_stop_unconfirmed",
            },
            {
                "type": "System.IO.IOException",
                "message": "recovery marker failed",
                "compensation_step": "recovery_marker",
                "finalization_step": "",
                "failure_code": "recovery_marker_write_failed",
            },
            {
                "type": "System.IO.InvalidDataException",
                "message": "payload lease close failed",
                "compensation_step": "",
                "finalization_step": "payload_lease_close",
                "failure_code": "payload_lease_close_failed",
            },
            {
                "type": "System.ApplicationException",
                "message": "lifecycle lock exit failed",
                "compensation_step": "",
                "finalization_step": "lifecycle_lock_exit",
                "failure_code": "lifecycle_lock_exit_failed",
            },
        ],
        "failure_codes": (
            "install_action_failed,backend_disable_denied,"
            "postgres_disable_failed,cluster_stop_unconfirmed,"
            "recovery_marker_write_failed,payload_lease_close_failed,"
            "lifecycle_lock_exit_failed"
        ),
        "compensation_failed": True,
        "finalization_failed": True,
    }

    compensation = _function(
        source,
        "Invoke-TicketboxInstallFailureCompensation",
    )
    for step in (
        "backend_disable",
        "postgres_disable",
        "cluster_stopped_assertion",
        "recovery_marker",
    ):
        assert step in compensation
    finalization = source[
        source.rindex("finally {\n    [Exception[]]$finalizationFailures") :
    ]
    assert '"payload_lease_close"' in finalization
    assert '"lifecycle_lock_exit"' in finalization


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_installer_finalization_failure_preserves_all_four_causes(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(
                source,
                "New-TicketboxInstallCompensationAggregateFailure",
            ),
            _function(
                source,
                "New-TicketboxInstallFinalizationAggregateFailure",
            ),
            "$install = [InvalidOperationException]::new('install failed')",
            "$install.Data['TicketboxC07FailureCode'] = 'manifest_not_ready'",
            "$compensation = "
            "[InvalidOperationException]::new('compensation failed')",
            "$operation = New-TicketboxInstallCompensationAggregateFailure "
            "-InstallFailure $install -CompensationFailure $compensation",
            "$close = [InvalidOperationException]::new('lease close failed')",
            "$unlock = [InvalidOperationException]::new('lock exit failed')",
            "$failure = New-TicketboxInstallFinalizationAggregateFailure "
            "-OperationFailure $operation "
            "-FinalizationFailures ([Exception[]]@($close, $unlock))",
            "[ordered]@{",
            "  type = $failure.GetType().FullName",
            "  inner_count = $failure.InnerExceptions.Count",
            "  messages = @($failure.InnerExceptions | "
            "ForEach-Object { $_.Message })",
            "  failure_code = $failure.Data['TicketboxC07FailureCode']",
            "  compensation_failed = "
            "$failure.Data['TicketboxInstallCompensationFailed']",
            "  finalization_failed = "
            "$failure.Data['TicketboxInstallFinalizationFailed']",
            "} | ConvertTo-Json -Compress",
        )
    )

    result = _run_ps(engine, script)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "type": "System.AggregateException",
        "inner_count": 4,
        "messages": [
            "install failed",
            "compensation failed",
            "lease close failed",
            "lock exit failed",
        ],
        "failure_code": "manifest_not_ready",
        "compensation_failed": True,
        "finalization_failed": True,
    }

    finalization = source[source.index("$operationFailure = $null") :]
    assert "$operationFailure = $failure" in finalization
    lease_close = finalization.index(
        "Close-TicketboxInstalledC07PayloadAuthorityLease"
    )
    lock_exit = finalization.index("Exit-TicketboxLifecycleLock", lease_close)
    aggregate = finalization.index(
        "New-TicketboxInstallFinalizationAggregateFailure",
        lock_exit,
    )
    rethrow = finalization.index(
        "if ($null -ne $operationFailure)",
        aggregate,
    )
    assert lease_close < lock_exit < aggregate < rethrow


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_prepare_failure_preserves_action_compensations_and_lock_exit(
    engine: str,
) -> None:
    source = PREPARE.read_text(encoding="utf-8-sig")
    helper = _function(source, "New-TicketboxPrepareAggregateFailure")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            helper,
            "$action = [InvalidOperationException]::new('prepare action failed')",
            "$action.Data['TicketboxC07FailureCode'] = 'shape_not_ready'",
            "$cleanup = [InvalidOperationException]::new('recovery cleanup failed')",
            "$acl = [InvalidOperationException]::new('ACL restore failed')",
            "$service = [InvalidOperationException]::new('service restore failed')",
            "$operation = New-TicketboxPrepareAggregateFailure "
            "-OperationFailure $action "
            "-SecondaryFailures ([Exception[]]@($cleanup, $acl, $service)) "
            "-FailureKind compensation",
            "$unlock = [InvalidOperationException]::new('lock exit failed')",
            "$failure = New-TicketboxPrepareAggregateFailure "
            "-OperationFailure $operation "
            "-SecondaryFailures ([Exception[]]@($unlock)) "
            "-FailureKind finalization",
            "[ordered]@{",
            "  type = $failure.GetType().FullName",
            "  inner_count = $failure.InnerExceptions.Count",
            "  messages = @($failure.InnerExceptions | "
            "ForEach-Object { $_.Message })",
            "  failure_code = $failure.Data['TicketboxC07FailureCode']",
            "  failure_codes = $failure.Data['TicketboxC07FailureCodes']",
            "  compensation_failed = "
            "$failure.Data['TicketboxPrepareCompensationFailed']",
            "  finalization_failed = "
            "$failure.Data['TicketboxPrepareFinalizationFailed']",
            "  failure_kind = $failure.Data['TicketboxPrepareFailureKind']",
            "} | ConvertTo-Json -Compress",
        )
    )

    result = _run_ps(engine, script)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "type": "System.AggregateException",
        "inner_count": 5,
        "messages": [
            "prepare action failed",
            "recovery cleanup failed",
            "ACL restore failed",
            "service restore failed",
            "lock exit failed",
        ],
        "failure_code": "shape_not_ready",
        "failure_codes": "shape_not_ready",
        "compensation_failed": True,
        "finalization_failed": True,
        "failure_kind": "finalization",
    }

    assert '$prepareOperationFailure = $_.Exception' in source
    for step in (
        "recovery_pg_cleanup",
        "install_acl_restore",
        "service_state_restore",
        "receipt_retire",
    ):
        assert step in source
    outer_finalizer = source.rindex("finally {\n    try {")
    lock_exit = source.index("Exit-TicketboxLifecycleLock", outer_finalizer)
    aggregate = source.index(
        "New-TicketboxPrepareAggregateFailure",
        lock_exit,
    )
    rethrow = source.index(
        "if ($null -ne $prepareOperationFailure)",
        aggregate,
    )
    assert lock_exit < aggregate < rethrow


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_installer_c07_disposition_distinguishes_fresh_legacy_and_runtime(
    engine: str,
    tmp_path: Path,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    recovery = tmp_path / "bootstrap.recovery"
    recovery.write_text("protected", encoding="ascii")
    intent = tmp_path / "fresh-intent.json"
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Get-TicketboxC07BootstrapCatalogDisposition"),
            _function(source, "Get-TicketboxC07InstallerDatabaseDisposition"),
            f"$script:recoveryPath = {_ps_literal(recovery)}",
            f"$script:intentPath = {_ps_literal(intent)}",
            "$script:envRole = 'none'",
            "$script:catalog = \"0`t0`t__missing__\"",
            "$script:catalogCalls = 0",
            "$PgPort = 5432",
            "$EnvPath = 'unused'",
            "$script:TicketboxC07DatabaseName = 'ticketbox'",
            "$script:TicketboxC07LegacyRuntimeRole = 'ticketbox'",
            "$script:TicketboxC07OwnerRole = 'ticketbox_owner'",
            "$script:TicketboxC07MigratorRole = 'ticketbox_migrator'",
            "$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'",
            """
function Get-PostgresBootstrapRecoveryPath { return $script:recoveryPath }
function Get-TicketboxC07FreshBootstrapIntentPath { return $script:intentPath }
function Read-PostgresBootstrapRecoveryState {
    return [pscustomobject]@{ SuperuserPassword = 'bootstrap-password' }
}
function Escape-SqlLiteral { param([string]$Value); return $Value }
function Invoke-Psql {
    param([string]$Database, [string]$Sql, [string]$Password)
    $script:catalogCalls += 1
    return $script:catalog
}
function Read-EnvMap {
    if ($script:envRole -ceq 'none') { return @{} }
    return @{
        DATABASE_URL = (
            "postgresql+psycopg://$($script:envRole):secret" +
            '@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256'
        )
    }
}
function ConvertTo-TicketboxRequiredDatabaseUrl {
    param([string]$DatabaseUrl)
    return $DatabaseUrl
}
function Assert-TicketboxLocalDatabaseUrl {
    param([string]$DatabaseUrl, [int]$PgPort)
    return $DatabaseUrl.Replace('postgresql+psycopg', 'postgresql')
}
function Invoke-TestDisposition {
    param(
        [string]$EnvironmentRole,
        [string]$Catalog,
        [bool]$HasIntent
    )
    $script:envRole = $EnvironmentRole
    $script:catalog = $Catalog
    if ($HasIntent) {
        [IO.File]::WriteAllText($script:intentPath, '{}')
    }
    elseif (Test-Path -LiteralPath $script:intentPath) {
        Remove-Item -LiteralPath $script:intentPath -Force
    }
    return Get-TicketboxC07InstallerDatabaseDisposition
}
$results = @(
    Invoke-TestDisposition 'none' "0`t0`t__missing__" $false
    Invoke-TestDisposition 'none' "1`t0`tticketbox" $false
    Invoke-TestDisposition 'none' "1`t1`tticketbox" $true
    Invoke-TestDisposition 'ticketbox_runtime' '' $false
)
$partialRejected = $false
try {
    [void](Invoke-TestDisposition 'none' "1`t1`tticketbox" $false)
}
catch { $partialRejected = $true }
$legacyIntentRejected = $false
try {
    [void](Invoke-TestDisposition 'ticketbox' '' $true)
}
catch { $legacyIntentRejected = $true }
[pscustomobject]@{
    results = $results
    partial_rejected = $partialRejected
    legacy_intent_rejected = $legacyIntentRejected
    catalog_calls = $script:catalogCalls
} | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["results"] == [
        "fresh_install",
        "legacy_adoption",
        "fresh_install",
        "runtime_ready",
    ]
    assert payload["partial_rejected"] is True
    assert payload["legacy_intent_rejected"] is True
    assert payload["catalog_calls"] == 3


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_installer_c07_fresh_action_is_idempotent_across_crash_windows(
    engine: str,
    tmp_path: Path,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    authority = tmp_path / "authority.json"
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Invoke-TicketboxC07InstalledReleaseMigration"),
            f"$script:authorityPath = {_ps_literal(authority)}",
            "$script:TicketboxC07InstallerSourceRevision = '20260722_0001'",
            "$script:TicketboxC07TargetRevision = '20260729_0001'",
            "$DataRoot = 'C:\\protected\\data'",
            "$script:initCalls = 0",
            "$script:freshCalls = 0",
            "$script:revision = ''",
            """
function New-TestSecureString {
    param([string]$Value)
    $secret = New-Object Security.SecureString
    foreach ($character in $Value.ToCharArray()) {
        $secret.AppendChar($character)
    }
    $secret.MakeReadOnly()
    return $secret
}
$script:runtimePassword = New-TestSecureString ('R' * 40)
$script:migratorPassword = New-TestSecureString ('M' * 40)
$script:superuserPassword = New-TestSecureString ('S' * 40)
$script:operationId = '1493b3d9-3721-0e51-0255-58aba5ba6e99'
$script:recoveryExists = $true
$script:qualificationCalls = 0
$script:invalidEvidence = $false
$script:failQualification = $false
$script:environmentCalls = 0
$script:cleanupCalls = 0
$script:failQualification = $false
$releaseIdentity = [pscustomobject]@{
    InstallationIdentityState = 'PENDING'
    InstallationOperationId = $script:operationId
    MigrationHelperPath = 'C:\\protected\\ticketbox-c07-migrator.exe'
}
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'host' }
}
function Get-TicketboxInstalledDatabaseGenerationProgram {
    return [pscustomobject]@{
        c07_source_revision = '20260722_0001'
        c07_target_revision = '20260729_0001'
        c07_revision_manifest_sha256 = ('a' * 64)
        c07_revision_manifest = [pscustomobject]@{
            operation_kind = 'c07_money_minor_bigint_v1'
        }
        target_revision = '20260809_0001'
        generation_program_sha256 = ('b' * 64)
    }
}
function Assert-TicketboxC07LowerSha256 {
    param([string]$Value, [string]$Label)
    if ($Value -cnotmatch '^[0-9a-f]{64}$') { throw "$Label is invalid" }
}
function Set-TicketboxC07DatabaseAuthorityCredential {}
function Clear-TicketboxC07DatabaseAuthorityCredential {}
function Get-TicketboxC07AuthorityPath { return $script:authorityPath }
function Invoke-TicketboxC07RecoveredSuperuserAction {
    param($HostAuthority, [string]$RecoveryArtifactPath, [scriptblock]$Action)
    $result = & $Action $script:superuserPassword
    $script:recoveryExists = $false
    return $result
}
function Initialize-TicketboxC07FreshDatabaseAuthority {
    param(
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        [DateTime]$MigratorValidUntilUtc,
        [string]$OperationId
    )
    if ($OperationId -cne $script:operationId) {
        throw 'installer changed the installation operation ID at the database boundary'
    }
    $script:initCalls += 1
    return [pscustomobject]@{ Result = 'authority_ready' }
}
function Get-TicketboxC07InstalledAlembicRevision {
    param($HostAuthority, $SuperuserPassword)
    return $script:revision
}
function Invoke-TicketboxC07InstalledFreshSourceBootstrapAction {
    param(
        $ReleaseIdentity,
        $HostAuthority,
        $MigratorPassword,
        [string]$SourceRevision,
        [string]$TargetRevision
    )
    $script:freshCalls += 1
    return [pscustomobject]@{
        result = 'source_committed'
        alembic_revision = $SourceRevision
    }
}
function New-TicketboxC07LifecycleOperation {
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        [string]$TargetRevision,
        [string]$OperationKind,
        [string]$RevisionManifestSha256,
        [string]$ExpectedOperationId
    )
    return [pscustomobject]@{ OperationId = $ExpectedOperationId }
}
function Get-OrCreateTicketboxC07InstalledCredentials {
    param($DataRoot, $LifecycleLock, [string]$Mode)
    return [pscustomobject]@{
        RuntimePassword = $script:runtimePassword
        MigratorPassword = $script:migratorPassword
    }
}
function Invoke-TicketboxC07InstalledProductionLifecycle {
    param(
        $DataRoot,
        $LifecycleLock,
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        [DateTime]$MigratorValidUntilUtc,
        [string]$Mode,
        [string]$ExpectedSourceRevision,
        [string]$TargetRevision,
        [string]$OperationKind,
        [string]$RevisionManifestSha256,
        [scriptblock]$MigrationAction,
        [scriptblock]$IsolatedReplayAction,
        [scriptblock]$MoneyFactsAction,
        [scriptblock]$TargetSemanticAction,
        [string]$ExpectedOperationId
    )
    return [pscustomobject]@{
        result = 'ready'
        operation_id = $ExpectedOperationId
        target_revision = $TargetRevision
        production_authority_sha256 = ('A' * 64)
        runtime_projection_sha256 = ('B' * 64)
    }
}
function Get-TicketboxC07PublishedRuntimeQualification {
    param(
        $DataRoot,
        $HostAuthority,
        $DatabaseAuthorityCredential,
        $RuntimePassword,
        [string]$ExpectedOperationId,
        $ObservationTimeoutMilliseconds
    )
    $script:qualificationCalls += 1
    if ($script:failQualification) {
        throw 'injected published runtime qualification failure'
    }
    return [pscustomobject]@{
        schema = 'ticketbox-c07-published-runtime-qualification-v1'
        operation_id = $ExpectedOperationId
        ready_verification_sha256 = ('c' * 64)
        ready_semantics = 'historical_ambiguous'
        production_authority_sha256 = ('A' * 64)
        runtime_projection_sha256 = ('B' * 64)
    }
}
function Read-TicketboxC07Authority {
    param($DataRoot)
    return [pscustomobject]@{ Receipt = [pscustomobject]@{ stage = 'operation' } }
}
function New-TicketboxC07MaintenanceBudget {
    param($Authority)
    return [pscustomobject]@{ DeadlineUtc = [DateTime]::UtcNow.AddMinutes(5) }
}
function Invoke-TicketboxC07InstalledMigrationAction { throw 'not invoked by harness' }
$intent = [pscustomobject]@{
    OperationId = $script:operationId
    RuntimePassword = $script:runtimePassword
    MigratorPassword = $script:migratorPassword
}
$lock = [pscustomobject]@{ Lease = 'held' }
function Invoke-TestRun {
    param(
        [string]$Revision,
        [bool]$HasAuthority,
        [string]$Mode = 'fresh_install',
        [bool]$FailQualification = $false
    )
    $script:revision = $Revision
    $script:initCalls = 0
    $script:freshCalls = 0
    $script:qualificationCalls = 0
    $script:environmentCalls = 0
    $script:cleanupCalls = 0
    $script:recoveryExists = $true
    $script:failQualification = $FailQualification
    if ($HasAuthority) {
        [IO.File]::WriteAllText($script:authorityPath, '{}')
    }
    elseif (Test-Path -LiteralPath $script:authorityPath) {
        Remove-Item -LiteralPath $script:authorityPath -Force
    }
    $selectedIntent = if ($Mode -ceq 'fresh_install') { $intent } else { $null }
    $failed = $false
    try {
        $result = Invoke-TicketboxC07InstalledReleaseMigration `
            -ReleaseIdentity $releaseIdentity `
            -Mode $Mode `
            -LifecycleLock $lock `
            -FreshIntent $selectedIntent `
            -RecoveryArtifactPath 'C:\\protected\\c07-superuser-recovery.pgpass'
        $script:environmentCalls += 1
        $script:cleanupCalls += 1
    }
    catch {
        $failed = $_.Exception.Message.Contains(
            'injected published runtime qualification failure'
        )
        $result = [pscustomobject]@{ result = 'blocked' }
    }
    return [pscustomobject]@{
        result = $result.result
        init = $script:initCalls
        fresh = $script:freshCalls
        failed = $failed
        recovery_exists = [bool]$script:recoveryExists
        qualification_calls = $script:qualificationCalls
        environment_calls = $script:environmentCalls
        cleanup_calls = $script:cleanupCalls
    }
}
@(
    Invoke-TestRun '' $false
    Invoke-TestRun '20260722_0001' $false
    Invoke-TestRun '20260729_0001' $true
    Invoke-TestRun '20260729_0001' $true fresh_install $true
    Invoke-TestRun '20260729_0001' $true legacy_adoption $true
) | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    for result, init_calls, fresh_calls in zip(
        payload[:3],
        (1, 1, 0),
        (1, 0, 0),
        strict=True,
    ):
        assert result == {
            "result": "ready",
            "init": init_calls,
            "fresh": fresh_calls,
            "failed": False,
            "recovery_exists": False,
            "qualification_calls": 1,
            "environment_calls": 1,
            "cleanup_calls": 1,
        }
    for result in payload[3:]:
        assert result == {
            "result": "blocked",
            "init": 0,
            "fresh": 0,
            "failed": True,
            "recovery_exists": True,
            "qualification_calls": 1,
            "environment_calls": 0,
            "cleanup_calls": 0,
        }


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_bundled_database_accepts_only_registered_legacy_and_runtime_roles(
    engine: str,
) -> None:
    source = BUNDLED_DATABASE.read_text(encoding="utf-8-sig")
    helper = _function(source, "Get-TicketboxBundledApplicationDatabaseConnection")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            helper,
            "$PgPort = 5432",
            "$DbName = 'ticketbox'",
            "$DbRole = 'ticketbox'",
            "$script:TicketboxBundledRuntimeDatabaseRole = 'ticketbox_runtime'",
            """
function ConvertTo-TicketboxRequiredDatabaseUrl {
    param([string]$DatabaseUrl)
    return $DatabaseUrl
}
function Assert-TicketboxLocalDatabaseUrl {
    param([string]$DatabaseUrl, [int]$PgPort)
    return $DatabaseUrl
}
function Get-TicketboxLocalDatabaseConnection {
    param(
        [string]$DatabaseUrl,
        [int]$PgPort,
        [string]$ExpectedDatabase,
        [string]$ExpectedRole
    )
    return [pscustomobject]@{ PersistedDatabaseUrl = $DatabaseUrl }
}
$legacy = Get-TicketboxBundledApplicationDatabaseConnection `
    'postgresql://ticketbox:secret@127.0.0.1:5432/ticketbox'
$runtime = Get-TicketboxBundledApplicationDatabaseConnection `
    'postgresql://ticketbox_runtime:secret@127.0.0.1:5432/ticketbox'
$rejected = $false
try {
    [void](Get-TicketboxBundledApplicationDatabaseConnection `
        'postgresql://postgres:secret@127.0.0.1:5432/ticketbox')
}
catch { $rejected = $true }
[pscustomobject]@{
    legacy = $legacy.Role
    runtime = $runtime.Role
    rejected = $rejected
} | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "legacy": "ticketbox",
        "runtime": "ticketbox_runtime",
        "rejected": True,
    }


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_runtime_environment_is_published_and_verified_before_secret_cleanup(
    engine: str,
    tmp_path: Path,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    adapter = C07_WRITER_FENCE_ADAPTER.read_text(encoding="utf-8-sig")
    env_path = tmp_path / ".env"
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(adapter, "Assert-TicketboxC07PublishedRuntimeQualification"),
            _function(source, "Write-TicketboxC07InstalledRuntimeEnvironment"),
            f"$EnvPath = {_ps_literal(env_path)}",
            "$DataRoot = 'C:\\protected\\data'",
            "$PgPort = 5432",
            "$PgData = 'C:\\protected\\pgdata'",
            "$Psql = 'C:\\protected\\psql.exe'",
            "$DatabaseToolTimeoutMs = 600000",
            "$script:TicketboxC07DatabaseName = 'ticketbox'",
            "$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'",
            "$script:order = @()",
            "$script:envMap = @{}",
            "$script:writtenLines = @()",
            "$script:envMutationCalls = 0",
            """
function New-TestSecureString {
    $secret = New-Object Security.SecureString
    foreach ($character in ('R' * 40).ToCharArray()) {
        $secret.AppendChar($character)
    }
    $secret.MakeReadOnly()
    return $secret
}
$runtimePassword = New-TestSecureString
function Read-TicketboxC07DurableHeartbeatAuthority {
    return [pscustomobject]@{
        Receipt = [pscustomobject]@{
            stage = 'ready'
            operation_id = '11111111-1111-4111-8111-111111111111'
            ready_verification_sha256 = ('c' * 64)
        }
        ReadyVerification = [pscustomobject]@{
            ReadySemantics = 'historical_ambiguous'
        }
    }
}
function Assert-TicketboxC07LowerSha256 {
    param([string]$Value, [string]$Label)
    if ($Value -cnotmatch '^[0-9a-f]{64}$') {
        throw "$Label invalid"
    }
}
function Read-TicketboxC07ProductionAuthority {
    return [pscustomobject]@{ PayloadSha256 = ('a' * 64) }
}
function Read-TicketboxC07RuntimeProjectionForAuthority {
    return [pscustomobject]@{ PayloadSha256 = ('b' * 64) }
}
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'host' }
}
function Invoke-TicketboxC07WithPlainSecret {
    param([Security.SecureString]$Secret, [scriptblock]$Action)
    return & $Action ('R' * 40)
}
function Read-PostgresBootstrapRecoveryState {
    return [pscustomobject]@{ HttpBootstrapSecret = 'http-bootstrap-secret' }
}
function New-BaseEnvLines {
    param([string]$DatabaseUrl)
    return @("DATABASE_URL=$DatabaseUrl", 'TICKETBOX_HOST=127.0.0.1')
}
function Write-EnvNoBom {
    param([string]$Path, [string[]]$Lines)
    $script:envMutationCalls += 1
    $script:writtenLines = @($Lines)
    $databaseLine = @($Lines | Where-Object { $_.StartsWith('DATABASE_URL=') })
    $script:envMap = @{ DATABASE_URL = $databaseLine[0].Substring(13) }
}
function Set-EnvDatabaseUrl {
    param([string]$Path, [string]$DatabaseUrl)
    $script:envMutationCalls += 1
    $script:envMap = @{ DATABASE_URL = $DatabaseUrl }
}
function Read-EnvMap { return $script:envMap }
function Get-TicketboxLocalDatabaseConnection {
    param(
        [string]$DatabaseUrl,
        [int]$PgPort,
        [string]$ExpectedDatabase,
        [string]$ExpectedRole
    )
    if (
        $ExpectedDatabase -cne 'ticketbox' -or
        $ExpectedRole -cne 'ticketbox_runtime' -or
        -not $DatabaseUrl.Contains('ticketbox_runtime:')
    ) {
        throw 'runtime env target mismatch'
    }
    return [pscustomobject]@{
        PersistedDatabaseUrl = $DatabaseUrl
        DatabaseUrl = 'postgresql://ticketbox_runtime@127.0.0.1:5432/ticketbox'
        Password = ('R' * 40)
    }
}
function Assert-TicketboxConnectedPostgresDataRoot {
    $script:order += 'data_root'
}
function Assert-TicketboxC07RuntimeCredential {
    param($Authority, [Security.SecureString]$RuntimePassword)
    $script:order += 'runtime_credential'
}
$qualification = [pscustomobject][ordered]@{
    schema = 'ticketbox-c07-published-runtime-qualification-v1'
    operation_id = '11111111-1111-4111-8111-111111111111'
    ready_verification_sha256 = ('c' * 64)
    ready_semantics = 'historical_ambiguous'
    production_authority_sha256 = ('a' * 64)
    runtime_projection_sha256 = ('b' * 64)
}
$script:order += 'qualification'
$result = Write-TicketboxC07InstalledRuntimeEnvironment `
    -RuntimePassword $runtimePassword `
    -Qualification $qualification
$mutationsBefore = $script:envMutationCalls
$acceptedDrift = @()
foreach ($mutation in @(
    @('schema', 'ticketbox-c07-published-runtime-qualification-v0'),
    @('operation_id', '22222222-2222-4222-8222-222222222222'),
    @('ready_verification_sha256', ('d' * 64)),
    @('ready_semantics', 'published_runtime'),
    @('production_authority_sha256', ('d' * 64)),
    @('runtime_projection_sha256', ('d' * 64))
)) {
    $candidate = [pscustomobject][ordered]@{
        schema = [string]$qualification.schema
        operation_id = [string]$qualification.operation_id
        ready_verification_sha256 = [string]$qualification.ready_verification_sha256
        ready_semantics = [string]$qualification.ready_semantics
        production_authority_sha256 = [string]$qualification.production_authority_sha256
        runtime_projection_sha256 = [string]$qualification.runtime_projection_sha256
    }
    $candidate.([string]$mutation[0]) = [string]$mutation[1]
    try {
        [void](Write-TicketboxC07InstalledRuntimeEnvironment `
            -RuntimePassword $runtimePassword `
            -Qualification $candidate)
        $acceptedDrift += [string]$mutation[0]
    }
    catch {}
}
$missingField = [pscustomobject][ordered]@{
    schema = [string]$qualification.schema
    operation_id = [string]$qualification.operation_id
    ready_verification_sha256 = [string]$qualification.ready_verification_sha256
    ready_semantics = [string]$qualification.ready_semantics
    production_authority_sha256 = [string]$qualification.production_authority_sha256
}
try {
    [void](Write-TicketboxC07InstalledRuntimeEnvironment `
        -RuntimePassword $runtimePassword `
        -Qualification $missingField)
    $acceptedDrift += 'missing_field'
}
catch {}
$extraField = $qualification | Select-Object *, @{Name='extra'; Expression={'x'}}
try {
    [void](Write-TicketboxC07InstalledRuntimeEnvironment `
        -RuntimePassword $runtimePassword `
        -Qualification $extraField)
    $acceptedDrift += 'extra_field'
}
catch {}
[pscustomobject]@{
    result = $result
    order = $script:order
    lines = $script:writtenLines
    accepted_drift = $acceptedDrift
    mutation_calls_before = $mutationsBefore
    mutation_calls_after = $script:envMutationCalls
} | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "ticketbox_runtime:" in payload["result"]
    assert payload["order"] == ["qualification", "data_root", "runtime_credential"]
    assert payload["accepted_drift"] == []
    assert payload["mutation_calls_before"] == 1
    assert payload["mutation_calls_after"] == payload["mutation_calls_before"]
    assert "ENABLE_HTTP_BOOTSTRAP=true" in payload["lines"]
    assert "HTTP_BOOTSTRAP_SECRET=http-bootstrap-secret" in payload["lines"]


@pytest.mark.parametrize("ready_semantics", ["historical_ambiguous", "published_runtime"])
@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_historical_ready_requires_live_published_proof_before_recovery_cleanup(
    engine: str,
    ready_semantics: str,
) -> None:
    adapter = C07_WRITER_FENCE_ADAPTER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(adapter, "Assert-TicketboxC07PublishedRuntimeQualification"),
            _function(adapter, "Get-TicketboxC07PublishedRuntimeQualification"),
            r"""
function Complete-TicketboxC07RecoveredSuperuserResidue {
    param(
        [string]$DataRoot,
        [string]$RecoveryArtifactPath,
        [Security.SecureString]$RuntimePassword,
        [string]$ExpectedOperationId
    )
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    $capturedDataRoot = $DataRoot
    $capturedHostAuthority = $hostAuthority
    $capturedRuntimePassword = $RuntimePassword
    $capturedExpectedOperationId = $ExpectedOperationId
    $capturedTimeoutMilliseconds = [Math]::Min(30000, [int]$DatabaseToolTimeoutMs)
    $boundedAction = {
        param([Security.SecureString]$RecoveredSuperuserPassword)
        Set-TicketboxC07DatabaseAuthorityCredential $RecoveredSuperuserPassword
        try {
            return Get-TicketboxC07PublishedRuntimeQualification `
                -DataRoot $capturedDataRoot `
                -HostAuthority $capturedHostAuthority `
                -DatabaseAuthorityCredential $RecoveredSuperuserPassword `
                -RuntimePassword $capturedRuntimePassword `
                -ExpectedOperationId $capturedExpectedOperationId `
                -ObservationTimeoutMilliseconds $capturedTimeoutMilliseconds
        }
        finally {
            Clear-TicketboxC07DatabaseAuthorityCredential `
                -ExpectedCredential $RecoveredSuperuserPassword
        }
    }.GetNewClosure()
    return Invoke-TicketboxC07RecoveredSuperuserAction `
        -HostAuthority $hostAuthority `
        -RecoveryArtifactPath $RecoveryArtifactPath `
        -Action $boundedAction
}
""",
            "$DataRoot = 'C:\\poison\\global'",
            "$DatabaseToolTimeoutMs = 7000",
            "$script:order = @()",
            "$script:failPublished = $true",
            "$script:durableStageDrift = $false",
            "$script:rawCalls = 0",
            "$script:recoveryExists = $true",
            r"""
function New-TestSecureString {
    $secret = New-Object Security.SecureString
    foreach ($character in ('R' * 40).ToCharArray()) {
        $secret.AppendChar($character)
    }
    $secret.MakeReadOnly()
    return $secret
}
$runtimePassword = New-TestSecureString
function Resolve-TicketboxC07DatabaseHostAuthority {
    $script:resolveCalls += 1
    if ($script:resolveCalls -gt 1) { throw 'host authority re-resolved' }
    return [pscustomobject]@{ Schema = 'host'; Nonce = 'bound' }
}
function Set-TicketboxC07DatabaseAuthorityCredential {
    param($Credential)
    $script:databaseAuthorityCredential = $Credential
    $script:order += 'set_authority'
}
function Clear-TicketboxC07DatabaseAuthorityCredential {
    param($ExpectedCredential)
    if (-not [object]::ReferenceEquals(
        $script:databaseAuthorityCredential,
        $ExpectedCredential
    )) { throw 'scope credential mismatch' }
    $script:databaseAuthorityCredential = $null
    $script:order += 'clear_authority'
}
function Get-TicketboxC07DatabaseAuthorityCredential {
    return $script:databaseAuthorityCredential
}
function Read-TicketboxC07Authority {
    param($BoundDataRoot)
    if ($BoundDataRoot -cne 'C:\expected\bound') { throw 'poison data root used' }
    $script:order += 'full_authority'
    return [pscustomobject]@{
        Receipt = [pscustomobject]@{
            stage = 'ready'
            operation_id = '11111111-1111-4111-8111-111111111111'
            ready_verification_sha256 = ('c' * 64)
        }
        ReadyVerification = [pscustomobject]@{
            ReadySemantics = '__READY_SEMANTICS__'
        }
    }
}
function Read-TicketboxC07ProductionAuthority {
    $script:order += 'production'
    return [pscustomobject]@{ PayloadSha256 = ('a' * 64) }
}
function Read-TicketboxC07RuntimeProjectionForAuthority {
    $script:order += 'projection'
    return [pscustomobject]@{ PayloadSha256 = ('b' * 64) }
}
function Get-TicketboxC07WriterDatabaseFenceObservation {
    param([string]$AuthorityPhase)
    $script:order += "observe:$AuthorityPhase"
    return [pscustomobject]@{ AuthorityPhase = $AuthorityPhase }
}
function Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority {
    param($HostAuthority, $DatabaseAuthorityCredential, $TimeoutMilliseconds)
    if (
        [string]$HostAuthority.Nonce -cne 'bound' -or
        -not [object]::ReferenceEquals(
            $script:databaseAuthorityCredential,
            $DatabaseAuthorityCredential
        ) -or
        [int]$TimeoutMilliseconds -ne 7000
    ) { throw 'explicit observation boundary drift' }
    $script:rawCalls += 1
    return [pscustomobject]@{ AuthorityPhase = 'raw' }
}
function ConvertTo-TicketboxC07WriterFenceObservation {
    param($RawObservation, [string]$AuthorityPhase)
    $script:order += "observe:$AuthorityPhase"
    return [pscustomobject]@{ AuthorityPhase = $AuthorityPhase }
}
function Assert-TicketboxC07PublishedDatabaseAuthority {
    $script:order += 'assert_published'
    if ($script:failPublished) { throw 'injected frozen historical READY' }
}
function Assert-TicketboxC07RuntimeCredential {
    param($Authority, $RuntimePassword)
    if ([string]$Authority.Nonce -cne 'bound') { throw 'host authority drift' }
    $script:order += 'runtime_credential'
}
function Assert-TicketboxC07LowerSha256 {
    param([string]$Value, [string]$Label)
    if ($Value -cnotmatch '^[0-9a-f]{64}$') { throw "$Label invalid" }
}
function Read-TicketboxC07DurableHeartbeatAuthority {
    param($BoundDataRoot)
    $authority = Read-TicketboxC07Authority $BoundDataRoot
    if ($script:durableStageDrift) {
        $authority.Receipt.stage = 'runtime_acl_verified'
    }
    return $authority
}
function Invoke-TicketboxC07RecoveredSuperuserAction {
    param($HostAuthority, [string]$RecoveryArtifactPath, [scriptblock]$Action)
    $script:order += 'recovered_action'
    $result = & $Action (New-TestSecureString)
    $script:recoveryExists = $false
    $script:order += 'recovery_cleanup'
    return $result
}
$failedClosed = $false
try {
    Complete-TicketboxC07RecoveredSuperuserResidue `
        -DataRoot 'C:\expected\bound' `
        -RecoveryArtifactPath 'recovery.pgpass' `
        -RuntimePassword $runtimePassword `
        -ExpectedOperationId '11111111-1111-4111-8111-111111111111' | Out-Null
}
catch { $failedClosed = $_.Exception.Message.Contains('injected frozen') }
$failureOrder = @($script:order)
$recoveryPreserved = [bool]$script:recoveryExists
$rawCallsAfterPublishedFailure = $script:rawCalls
$script:order = @()
$script:resolveCalls = 0
$script:failPublished = $false
$wrongOperationRejected = $false
try {
    Complete-TicketboxC07RecoveredSuperuserResidue `
        -DataRoot 'C:\expected\bound' `
        -RecoveryArtifactPath 'recovery.pgpass' `
        -RuntimePassword $runtimePassword `
        -ExpectedOperationId '22222222-2222-4222-8222-222222222222' | Out-Null
}
catch { $wrongOperationRejected = $_.Exception.Message.Contains('exact operation') }
$wrongOperationRecoveryPreserved = [bool]$script:recoveryExists
$rawCallsAfterWrongOperation = $script:rawCalls
$script:order = @()
$script:resolveCalls = 0
$scopeCredential = New-TestSecureString
$foreignCredential = New-TestSecureString
Set-TicketboxC07DatabaseAuthorityCredential $scopeCredential
$foreignCredentialRejected = $false
try {
    [void](Get-TicketboxC07PublishedRuntimeQualification `
        -DataRoot 'C:\expected\bound' `
        -HostAuthority ([pscustomobject]@{ Nonce = 'bound' }) `
        -DatabaseAuthorityCredential $foreignCredential `
        -RuntimePassword $runtimePassword `
        -ExpectedOperationId '11111111-1111-4111-8111-111111111111' `
        -ObservationTimeoutMilliseconds 7000)
}
catch { $foreignCredentialRejected = $_.Exception.Message.Contains('scoped') }
Clear-TicketboxC07DatabaseAuthorityCredential -ExpectedCredential $scopeCredential
$rawCallsAfterForeignCredential = $script:rawCalls
$script:order = @()
$script:resolveCalls = 0
$script:durableStageDrift = $true
$receiptDriftRejected = $false
try {
    Complete-TicketboxC07RecoveredSuperuserResidue `
        -DataRoot 'C:\expected\bound' `
        -RecoveryArtifactPath 'recovery.pgpass' `
        -RuntimePassword $runtimePassword `
        -ExpectedOperationId '11111111-1111-4111-8111-111111111111' | Out-Null
}
catch { $receiptDriftRejected = $_.Exception.Message.Contains('durable READY') }
$receiptDriftRecoveryPreserved = [bool]$script:recoveryExists
$script:order = @()
$script:resolveCalls = 0
$script:durableStageDrift = $false
$qualified = Complete-TicketboxC07RecoveredSuperuserResidue `
    -DataRoot 'C:\expected\bound' `
    -RecoveryArtifactPath 'recovery.pgpass' `
    -RuntimePassword $runtimePassword `
    -ExpectedOperationId '11111111-1111-4111-8111-111111111111'
[pscustomobject]@{
    failed_closed = $failedClosed
    recovery_preserved = $recoveryPreserved
    wrong_operation_rejected = $wrongOperationRejected
    wrong_operation_recovery_preserved = $wrongOperationRecoveryPreserved
    foreign_credential_rejected = $foreignCredentialRejected
    raw_calls_after_published_failure = $rawCallsAfterPublishedFailure
    raw_calls_after_wrong_operation = $rawCallsAfterWrongOperation
    raw_calls_after_foreign_credential = $rawCallsAfterForeignCredential
    receipt_drift_rejected = $receiptDriftRejected
    receipt_drift_recovery_preserved = $receiptDriftRecoveryPreserved
    failure_order = $failureOrder
    success_order = @($script:order)
    semantics = [string]$qualified.ready_semantics
} | ConvertTo-Json -Compress
""",
        )
    )
    script = script.replace("__READY_SEMANTICS__", ready_semantics)
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["failed_closed"] is True
    assert payload["recovery_preserved"] is True
    assert payload["wrong_operation_rejected"] is True
    assert payload["wrong_operation_recovery_preserved"] is True
    assert payload["foreign_credential_rejected"] is True
    assert payload["raw_calls_after_published_failure"] == 1
    assert payload["raw_calls_after_wrong_operation"] == 1
    assert payload["raw_calls_after_foreign_credential"] == 1
    assert payload["receipt_drift_rejected"] is True
    assert payload["receipt_drift_recovery_preserved"] is True
    assert payload["failure_order"] == [
        "recovered_action",
        "set_authority",
        "full_authority",
        "production",
        "projection",
        "observe:published_runtime",
        "assert_published",
        "clear_authority",
    ]
    assert payload["success_order"] == [
        "recovered_action",
        "set_authority",
        "full_authority",
        "production",
        "projection",
        "observe:published_runtime",
        "assert_published",
        "runtime_credential",
        "full_authority",
        "production",
        "projection",
        "clear_authority",
        "recovery_cleanup",
    ]
    assert payload["semantics"] == ready_semantics


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_release_schema_target_mismatch_fails_before_recovery_or_mutation(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Invoke-TicketboxInstalledManagedSchemaUpgrade"),
            "$script:recoveryCalls = 0",
            "$script:passwordCalls = 0",
            r"""
$DataRoot = 'C:\protected\data'
function New-TestSecureString {
    $secret = New-Object Security.SecureString
    1..32 | ForEach-Object { $secret.AppendChar('R') }
    $secret.MakeReadOnly()
    return $secret
}
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'host' }
}
function Get-TicketboxRuntimeAlembicRevision { return '20260729_0001' }
function Get-TicketboxInstalledDatabaseGenerationProgram {
    return [pscustomobject]@{
        target_revision = '20260809_0001'
        generation_program_sha256 = ('b' * 64)
        c07_target_revision = '20260809_0001'
        c07_revision_manifest_sha256 = ('a' * 64)
    }
}
function New-StrongPassword {
    $script:passwordCalls += 1
    return ('M' * 40)
}
function Invoke-TicketboxC07RecoveredSuperuserAction {
    $script:recoveryCalls += 1
    throw 'recovery action must not run for an unpublished generation target'
}
$authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{
        stage = 'ready'
        operation_id = '11111111-1111-4111-8111-111111111111'
    }
        Descriptor = [pscustomobject]@{
            PayloadSha256 = ('9' * 64)
            Payload = [pscustomobject]@{
            target_alembic_revision = '20260729_0001'
        }
    }
}
$rejected = $false
try {
    Invoke-TicketboxInstalledManagedSchemaUpgrade `
        -DataRoot 'C:\protected\data' `
        -HostAuthority ([pscustomobject]@{ Schema = 'host' }) `
        -ReleaseIdentity ([pscustomobject]@{
            InstallationOperationId = '11111111-1111-4111-8111-111111111111'
        }) `
        -C07Authority $authority `
        -RuntimePassword (New-TestSecureString) `
        -LifecycleReceipt ([pscustomobject]@{}) `
        -RecoveryArtifactPath 'recovery.pgpass' `
        -ObservationTimeoutMilliseconds 7000 `
        -Mode fresh_install | Out-Null
}
catch {
    $rejected = $_.Exception.Message.Contains('generation authority')
}
if (-not $rejected -or $script:recoveryCalls -ne 0 -or
    $script:passwordCalls -ne 0) {
    throw 'unpublished release-schema generation reached credential or mutation path'
}
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_managed_schema_retry_retires_exact_active_migrator_before_replay(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Invoke-TicketboxInstalledManagedSchemaUpgrade"),
            _function(
                C07_WRITER_FENCE_ADAPTER.read_text(encoding="utf-8-sig"),
                "Assert-TicketboxC07PublishedRuntimeQualification",
            ),
            _function(
                C07_WRITER_FENCE_ADAPTER.read_text(encoding="utf-8-sig"),
                "Get-TicketboxC07PublishedRuntimeQualification",
            ),
            r"""
$DataRoot = 'C:\protected\data'
$script:operationId = '11111111-1111-4111-8111-111111111111'
$script:currentRevision = ''
$script:mode = ''
$script:migratorDisposition = 'retired'
$script:events = @()
$script:recoveryExists = $true
$script:backupPath = [IO.Path]::GetTempFileName()
$script:qualificationCalls = 0
function New-TestSecureString {
    $secret = New-Object Security.SecureString
    1..40 | ForEach-Object { $secret.AppendChar('R') }
    $secret.MakeReadOnly()
    return $secret
}
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'host'; Nonce = 'bound' }
}
function Get-TicketboxC07DatabaseAuthorityCredential {
    return $script:scopedCredential
}
function Get-TicketboxRuntimeAlembicRevision {
    $script:events += "outer_revision:$($script:currentRevision)"
    return $script:currentRevision
}
function Get-TicketboxInstalledDatabaseGenerationProgram {
    return [pscustomobject]@{
        target_revision = '20260729_0001'
        generation_program_sha256 = ('b' * 64)
        c07_target_revision = '20260729_0001'
        c07_revision_manifest_sha256 = ('a' * 64)
    }
}
function New-StrongPassword { return ('M' * 40) }
function ConvertTo-TicketboxC07InstalledSecureString { return New-TestSecureString }
function Set-TicketboxC07DatabaseAuthorityCredential {
    param($Credential)
    $script:scopedCredential = $Credential
    $script:events += 'set_authority'
}
function Clear-TicketboxC07DatabaseAuthorityCredential {
    param($ExpectedCredential)
    if (-not [object]::ReferenceEquals(
        $script:scopedCredential,
        $ExpectedCredential
    )) { throw 'scope credential drift' }
    $script:scopedCredential = $null
    $script:events += 'clear_authority'
}
function Read-TicketboxC07Authority {
    $script:events += 'read_exact_ready'
    return [pscustomobject]@{
        Receipt = [pscustomobject]@{
            stage = 'ready'
            operation_id = $script:operationId
            ready_verification_sha256 = ('d' * 64)
        }
        ReadyVerification = [pscustomobject]@{
            ReadySemantics = 'published_runtime'
        }
        Descriptor = [pscustomobject]@{
            PayloadSha256 = $(if ($script:liveDescriptorDrift) {
                ('8' * 64)
            } else { ('9' * 64) })
            Payload = [pscustomobject]@{
                target_alembic_revision = $(if ($script:liveTargetDrift) {
                    '20260809_0001'
                } else { '20260729_0001' })
                revision_manifest_sha256 = $(if ($script:liveManifestDrift) {
                    ('7' * 64)
                } else { ('a' * 64) })
            }
        }
    }
}
function Read-TicketboxC07DurableHeartbeatAuthority {
    param($BoundDataRoot)
    return Read-TicketboxC07Authority $BoundDataRoot
}
function Read-TicketboxC07ProductionAuthority {
    return [pscustomobject]@{ PayloadSha256 = ('b' * 64) }
}
function Read-TicketboxC07RuntimeProjectionForAuthority {
    return [pscustomobject]@{ PayloadSha256 = ('c' * 64) }
}
function Get-TicketboxC07RawWriterDatabaseFenceObservationForAuthority {
    $script:qualificationCalls += 1
    $script:events += 'post_schema_observation'
    return [pscustomobject]@{}
}
function ConvertTo-TicketboxC07WriterFenceObservation {
    return [pscustomobject]@{ AuthorityPhase = 'published_runtime' }
}
function Assert-TicketboxC07PublishedDatabaseAuthority {
    $script:events += 'post_schema_assertion'
    if ($script:failQualification) {
        throw 'injected post-schema qualification failure'
    }
}
function Assert-TicketboxC07RuntimeCredential {
    $script:events += 'post_schema_runtime_credential'
}
function Assert-TicketboxC07PublishedRuntimeQualification {
    param($DataRoot, $Qualification)
    $script:events += 'qualification_receipt_asserted'
    return Read-TicketboxC07DurableHeartbeatAuthority $DataRoot
}
function Get-TicketboxC07InstalledAlembicRevision {
    $script:events += "live_revision:$($script:currentRevision)"
    return $script:currentRevision
}
function Get-TicketboxC07MigratorRetirementState {
    $script:events += "migrator_state:$($script:migratorDisposition)"
    return [pscustomobject]@{
        IsActive = [string]$script:migratorDisposition -ceq 'active' -or
            [string]$script:migratorDisposition -ceq 'partial'
        IsRetired = [string]$script:migratorDisposition -ceq 'retired' -or
            [string]$script:migratorDisposition -ceq 'partial'
    }
}
function Disable-TicketboxC07MigratorLogin {
    param($SuperuserPassword, [string]$OperationId, [string]$Mode)
    if (
        -not [object]::ReferenceEquals(
            $script:scopedCredential,
            $SuperuserPassword
        ) -or
        $OperationId -cne $script:operationId -or
        $Mode -cne $script:mode
    ) { throw 'migrator retirement binding drift' }
    $script:events += "disable:$Mode"
    $script:migratorDisposition = 'retired'
}
function Enable-TicketboxC07MigratorForManagedSchemaUpgrade {
    param($OperationId, [string]$Mode)
    if ($OperationId -cne $script:operationId -or $Mode -cne $script:mode -or
        [string]$script:migratorDisposition -cne 'retired') {
        throw 'migrator re-enable binding drift'
    }
    $script:events += "enable:$Mode"
    $script:migratorDisposition = 'active'
}
function Invoke-TicketboxInstalledManagedSchemaUpgradeAction {
    $script:events += 'upgrade_action'
        return [pscustomobject]@{
            alembic_revision = $(if ($script:invalidEvidence) {
                '20260722_0001'
            } else { '20260729_0001' })
            revision_manifest_sha256 = ('a' * 64)
            generation_program_sha256 = $(if ($script:invalidProgramEvidence) {
                ('f' * 64)
            } else { ('b' * 64) })
        }
}
function Set-TicketboxManagedSchemaRuntimeAcl {
    $script:events += 'runtime_acl'
}
function Invoke-TicketboxC07RecoveredSuperuserAction {
    param($HostAuthority, [string]$RecoveryArtifactPath, [scriptblock]$Action)
    $script:events += 'recovered_action'
    try {
        $result = & $Action (New-TestSecureString)
        $script:recoveryExists = $false
        $script:events += 'recovery_cleanup'
        return $result
    }
    catch { throw }
}
$authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{
        stage = 'ready'
        operation_id = $script:operationId
        ready_verification_sha256 = ('d' * 64)
    }
    ReadyVerification = [pscustomobject]@{
        ReadySemantics = 'published_runtime'
    }
    Descriptor = [pscustomobject]@{
        PayloadSha256 = ('9' * 64)
        Payload = [pscustomobject]@{
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('a' * 64)
        }
    }
}
$receipt = [pscustomobject]@{
    backup_required = $true
    backup_completed = $true
    backup_path = $script:backupPath
}
function Invoke-TestCase {
    param(
        [string]$Revision,
        [string]$Mode,
        [string]$Disposition,
        [string]$FailureKind = '',
        [string]$AuthorityStage = 'ready',
        [string]$AuthorityOperationId = '',
        [bool]$LiveDescriptorDrift = $false
    )
    $script:currentRevision = $Revision
    $script:mode = $Mode
    $script:migratorDisposition = $Disposition
    $script:events = @()
    $script:recoveryExists = $true
    $script:invalidEvidence = $FailureKind -ceq 'evidence'
    $script:invalidProgramEvidence = $FailureKind -ceq 'program_evidence'
    $script:failQualification = $FailureKind -ceq 'qualification'
    $script:liveDescriptorDrift = $LiveDescriptorDrift
    $script:liveTargetDrift = $FailureKind -ceq 'live_target'
    $script:liveManifestDrift = $FailureKind -ceq 'live_manifest'
    $authority.Descriptor.PayloadSha256 = $(if (
        $FailureKind -ceq 'captured_payload_empty'
    ) { '' } else { ('9' * 64) })
    $authority.Descriptor.Payload.revision_manifest_sha256 = $(if (
        $FailureKind -ceq 'captured_manifest'
    ) { ('e' * 64) } else { ('a' * 64) })
    $authority.Receipt.stage = $AuthorityStage
    $authority.Receipt.operation_id = $(if (
        [string]::IsNullOrEmpty($AuthorityOperationId)
    ) { $script:operationId } else { $AuthorityOperationId })
    $failed = $false
    $errorMessage = ''
    try {
        $result = Invoke-TicketboxInstalledManagedSchemaUpgrade `
            -DataRoot $DataRoot `
            -HostAuthority (Resolve-TicketboxC07DatabaseHostAuthority) `
            -ReleaseIdentity ([pscustomobject]@{
                InstallationOperationId = $script:operationId
            }) `
            -C07Authority $authority `
            -RuntimePassword (New-TestSecureString) `
            -LifecycleReceipt $receipt `
            -RecoveryArtifactPath 'recovery.pgpass' `
            -ObservationTimeoutMilliseconds 7000 `
            -Mode $Mode
    }
    catch {
        $errorMessage = $_.Exception.Message
        $failed = (
            $_.Exception.Message.Contains('unknown/partial') -or
            $_.Exception.Message.Contains('exact-head evidence') -or
            $_.Exception.Message.Contains('post-schema qualification') -or
            $_.Exception.Message.Contains('exact C07 READY') -or
            $_.Exception.Message.Contains('generation authority') -or
            $_.Exception.Message.Contains('exact live C07 READY authority')
        )
        $result = [pscustomobject]@{ alembic_revision = 'blocked' }
    }
    return [pscustomobject]@{
        revision = $Revision
        mode = $Mode
        disposition = $Disposition
        failure_kind = $FailureKind
        failed = $failed
        error = $errorMessage
        recovery_exists = [bool]$script:recoveryExists
        result = [string]$result.alembic_revision
        events = @($script:events)
    }
}
@(
    Invoke-TestCase '20260722_0001' fresh_install active
    Invoke-TestCase '20260729_0001' fresh_install active
    Invoke-TestCase '20260722_0001' legacy_adoption active
    Invoke-TestCase '20260729_0001' legacy_adoption active
    Invoke-TestCase '20260722_0001' fresh_install unknown
    Invoke-TestCase '20260729_0001' legacy_adoption unknown
    Invoke-TestCase '20260729_0001' fresh_install retired evidence
    Invoke-TestCase '20260729_0001' fresh_install retired program_evidence
    Invoke-TestCase '20260729_0001' legacy_adoption retired qualification
    Invoke-TestCase '20260729_0001' fresh_install retired captured_manifest
    Invoke-TestCase '20260729_0001' fresh_install retired '' runtime_acl_verified
    Invoke-TestCase `
        '20260729_0001' `
        legacy_adoption `
        retired `
        '' `
        ready `
        '22222222-2222-4222-8222-222222222222'
    Invoke-TestCase `
        '20260729_0001' `
        fresh_install `
        retired `
        '' `
        ready `
        '' `
        $true
    Invoke-TestCase '20260729_0001' fresh_install retired captured_payload_empty
    Invoke-TestCase '20260729_0001' fresh_install retired live_target
    Invoke-TestCase '20260729_0001' legacy_adoption retired live_manifest
    Invoke-TestCase '20260729_0001' legacy_adoption partial
) | ConvertTo-Json -Depth 5 -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    for item in payload[:4]:
        assert item["failed"] is False
        assert item["recovery_exists"] is False, item
        assert item["result"] == "20260729_0001"
        events = item["events"]
        first_state = events.index("migrator_state:active")
        first_disable = events.index(f"disable:{item['mode']}")
        first_retired = events.index("migrator_state:retired", first_disable)
        enable = events.index(f"enable:{item['mode']}")
        assert first_state < first_disable < first_retired < enable
        assert enable < events.index("upgrade_action") < events.index("runtime_acl")
        assert events.index("runtime_acl") < events.index("post_schema_observation")
        assert events.index("post_schema_runtime_credential") < events.index("clear_authority")
        assert events.index("qualification_receipt_asserted") < events.index("clear_authority")
        assert events[-2:] == ["clear_authority", "recovery_cleanup"]
    for partial in payload[4:6]:
        assert partial["failed"] is True
        assert partial["recovery_exists"] is True
        assert f"disable:{partial['mode']}" not in partial["events"]
        assert f"enable:{partial['mode']}" not in partial["events"]
        assert "upgrade_action" not in partial["events"]
    evidence = payload[6]
    assert evidence["failed"] is True
    assert evidence["recovery_exists"] is True
    assert "upgrade_action" in evidence["events"]
    assert "post_schema_observation" not in evidence["events"]
    program_evidence = payload[7]
    assert program_evidence["failed"] is True
    assert program_evidence["recovery_exists"] is True
    assert "upgrade_action" in program_evidence["events"]
    assert "post_schema_observation" not in program_evidence["events"]
    qualification = payload[8]
    assert qualification["failed"] is True
    assert qualification["recovery_exists"] is True
    assert qualification["events"].index("runtime_acl") < qualification["events"].index(
        "post_schema_observation"
    )
    assert "recovery_cleanup" not in qualification["events"]
    for authority_drift in payload[9:12]:
        assert authority_drift["failed"] is True
        assert authority_drift["recovery_exists"] is True
        assert "recovered_action" not in authority_drift["events"]
        assert f"disable:{authority_drift['mode']}" not in authority_drift["events"]
        assert f"enable:{authority_drift['mode']}" not in authority_drift["events"]
    live_descriptor_drift = payload[12]
    assert live_descriptor_drift["failed"] is True
    assert live_descriptor_drift["recovery_exists"] is True
    assert "recovered_action" in live_descriptor_drift["events"]
    assert "disable:fresh_install" not in live_descriptor_drift["events"]
    assert "enable:fresh_install" not in live_descriptor_drift["events"]
    captured_payload_empty = payload[13]
    assert captured_payload_empty["failed"] is True
    assert captured_payload_empty["recovery_exists"] is True
    assert "recovered_action" not in captured_payload_empty["events"]
    for live_authority_drift in payload[14:16]:
        assert live_authority_drift["failed"] is True
        assert live_authority_drift["recovery_exists"] is True
        assert "recovered_action" in live_authority_drift["events"]
        assert not any(
            event.startswith("live_revision:")
            or event.startswith("migrator_state:")
            or event.startswith("disable:")
            or event.startswith("enable:")
            or event == "upgrade_action"
            or event == "recovery_cleanup"
            for event in live_authority_drift["events"]
        )
    partial = payload[16]
    assert partial["failed"] is True
    assert partial["recovery_exists"] is True
    assert "migrator_state:partial" in partial["events"]
    assert not any(
        event.startswith("disable:")
        or event.startswith("enable:")
        or event == "upgrade_action"
        or event == "recovery_cleanup"
        for event in partial["events"]
    )


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_managed_schema_publication_rebinds_post_schema_qualification(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(
                source,
                "Complete-TicketboxInstalledManagedSchemaPublication",
            ),
            r"""
$script:operationId = '11111111-1111-4111-8111-111111111111'
$script:managedCalls = 0
$script:durableReads = 0
$script:productionMode = 'fresh_install'
$script:productionHash = ('b' * 64)
$script:projectionHash = ('c' * 64)
$script:qualificationProductionHash = ('b' * 64)
$script:qualificationProjectionHash = ('c' * 64)
$script:managedRevision = '20260729_0001'
$script:managedManifest = ('a' * 64)
$script:durableStage = 'ready'
$script:durableOperationId = $script:operationId
$runtimePassword = New-Object Security.SecureString
1..32 | ForEach-Object { $runtimePassword.AppendChar('R') }
$runtimePassword.MakeReadOnly()
$hostAuthority = [pscustomobject]@{ Nonce = 'bound-host' }
$releaseIdentity = [pscustomobject]@{
    InstallationOperationId = $script:operationId
}
$c07Authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{
        stage = 'ready'
        operation_id = $script:operationId
    }
    Descriptor = [pscustomobject]@{
        PayloadSha256 = ('9' * 64)
        Payload = [pscustomobject]@{
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('a' * 64)
        }
    }
}
$lifecycleReceipt = [pscustomobject]@{ schema = 'receipt-v3' }
function Invoke-TicketboxInstalledManagedSchemaUpgrade {
    param(
        $DataRoot,
        $HostAuthority,
        $ReleaseIdentity,
        $C07Authority,
        $RuntimePassword,
        $LifecycleReceipt,
        [string]$RecoveryArtifactPath,
        [int]$ObservationTimeoutMilliseconds,
        [string]$Mode
    )
    if (
        $DataRoot -cne 'C:\expected\data' -or
        -not [object]::ReferenceEquals($HostAuthority, $hostAuthority) -or
        -not [object]::ReferenceEquals($RuntimePassword, $runtimePassword) -or
        $ReleaseIdentity.InstallationOperationId -cne $script:operationId -or
        $C07Authority.Receipt.operation_id -cne $script:operationId -or
        -not [object]::ReferenceEquals($LifecycleReceipt, $lifecycleReceipt) -or
        $RecoveryArtifactPath -cne 'C:\expected\recovery.pgpass' -or
        $ObservationTimeoutMilliseconds -ne 7000 -or
        $Mode -cnotin @('fresh_install', 'legacy_adoption')
    ) {
        throw 'managed publication argument binding drift'
    }
    $script:managedCalls += 1
    $script:lastQualification = [pscustomobject]@{
        schema = 'ticketbox-c07-published-runtime-qualification-v1'
        operation_id = $script:operationId
        production_authority_sha256 =
            $script:qualificationProductionHash
        runtime_projection_sha256 =
            $script:qualificationProjectionHash
    }
    return [pscustomobject]@{
        schema = 'ticketbox-managed-schema-publication-v1'
        alembic_revision = $script:managedRevision
        revision_manifest_sha256 = $script:managedManifest
        published_runtime_qualification = $script:lastQualification
    }
}
function Read-TicketboxC07DurableHeartbeatAuthority {
    param([string]$DataRoot)
    if ($DataRoot -cne 'C:\expected\data') {
        throw 'publication reread used an ambient DataRoot'
    }
    $script:durableReads += 1
    $c07Authority.Receipt.stage = $script:durableStage
    $c07Authority.Receipt.operation_id = $script:durableOperationId
    return $c07Authority
}
function Read-TicketboxC07ProductionAuthority {
    param($Authority)
    if (-not [object]::ReferenceEquals($Authority, $c07Authority)) {
        throw 'production reread authority drift'
    }
    return [pscustomobject]@{
        Payload = [pscustomobject]@{ mode = $script:productionMode }
        PayloadSha256 = $script:productionHash
    }
}
function Read-TicketboxC07RuntimeProjectionForAuthority {
    param($Authority)
    if (-not [object]::ReferenceEquals($Authority, $c07Authority)) {
        throw 'projection reread authority drift'
    }
    return [pscustomobject]@{ PayloadSha256 = $script:projectionHash }
}
function Invoke-Publication {
    param([string]$Mode = 'fresh_install')
    $beforeManaged = $script:managedCalls
    $beforeDurable = $script:durableReads
    try {
        $result = Complete-TicketboxInstalledManagedSchemaPublication `
            -DataRoot 'C:\expected\data' `
            -HostAuthority $hostAuthority `
            -ReleaseIdentity $releaseIdentity `
            -C07Authority $c07Authority `
            -RuntimePassword $runtimePassword `
            -LifecycleReceipt $lifecycleReceipt `
            -RecoveryArtifactPath 'C:\expected\recovery.pgpass' `
            -ObservationTimeoutMilliseconds 7000 `
            -Mode $Mode
        return [pscustomobject]@{
            rejected = $false
            schema = [string]$result.schema
            mode = [string]$result.mode
            revision = [string]$result.alembic_revision
            manifest = [string]$result.revision_manifest_sha256
            production = [string]$result.production_authority_sha256
            projection = [string]$result.runtime_projection_sha256
            qualification_same = [object]::ReferenceEquals(
                $result.published_runtime_qualification,
                $script:lastQualification
            )
            managed_delta = $script:managedCalls - $beforeManaged
            durable_delta = $script:durableReads - $beforeDurable
        }
    }
    catch {
        return [pscustomobject]@{
            rejected = $true
            error = $_.Exception.Message
            managed_delta = $script:managedCalls - $beforeManaged
            durable_delta = $script:durableReads - $beforeDurable
        }
    }
}
$acceptedFresh = Invoke-Publication fresh_install
$script:productionMode = 'legacy_adoption'
$acceptedLegacy = Invoke-Publication legacy_adoption
$modeDrift = Invoke-Publication fresh_install
$script:productionMode = 'fresh_install'
$script:qualificationProductionHash = ('d' * 64)
$productionDrift = Invoke-Publication
$script:qualificationProductionHash = ('b' * 64)
$script:qualificationProjectionHash = ('e' * 64)
$projectionDrift = Invoke-Publication
$script:qualificationProjectionHash = ('c' * 64)
$script:managedRevision = '20260722_0001'
$revisionDrift = Invoke-Publication
$script:managedRevision = '20260729_0001'
$script:managedManifest = ('f' * 64)
$manifestDrift = Invoke-Publication
$script:managedManifest = ('a' * 64)
$script:durableStage = 'runtime_acl_verified'
$stageDrift = Invoke-Publication
$script:durableStage = 'ready'
$script:durableOperationId = '22222222-2222-4222-8222-222222222222'
$operationDrift = Invoke-Publication
@(
    $acceptedFresh,
    $acceptedLegacy,
    $modeDrift,
    $productionDrift,
    $projectionDrift,
    $revisionDrift,
    $manifestDrift,
    $stageDrift,
    $operationDrift
) |
    ConvertTo-Json -Depth 5 -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    (
        accepted_fresh,
        accepted_legacy,
        mode_drift,
        production_drift,
        projection_drift,
        revision_drift,
        manifest_drift,
        stage_drift,
        operation_drift,
    ) = json.loads(result.stdout)
    for accepted, mode in (
        (accepted_fresh, "fresh_install"),
        (accepted_legacy, "legacy_adoption"),
    ):
        assert accepted == {
            "rejected": False,
            "schema": "ticketbox-installed-schema-publication-v1",
            "mode": mode,
            "revision": "20260729_0001",
            "manifest": "a" * 64,
            "production": "b" * 64,
            "projection": "c" * 64,
            "qualification_same": True,
            "managed_delta": 1,
            "durable_delta": 1,
        }
    for drift in (
        mode_drift,
        production_drift,
        projection_drift,
        revision_drift,
        manifest_drift,
        stage_drift,
        operation_drift,
    ):
        assert drift["rejected"] is True
        assert drift["managed_delta"] == 1
        assert drift["durable_delta"] == 1


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_runtime_publication_dispatches_all_three_dispositions(engine: str) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Complete-TicketboxInstalledRuntimePublication"),
            r"""
$script:operationId = '11111111-1111-4111-8111-111111111111'
$script:publishedMode = 'legacy_adoption'
$script:events = @()
$script:failSchema = $false
$runtimePassword = New-Object Security.SecureString
1..32 | ForEach-Object { $runtimePassword.AppendChar('R') }
$runtimePassword.MakeReadOnly()
$hostAuthority = [pscustomobject]@{ Nonce = 'host' }
$releaseIdentity = [pscustomobject]@{
    InstallationOperationId = $script:operationId
}
$authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{ operation_id = $script:operationId }
}
$receipt = [pscustomobject]@{ schema = 'receipt-v3' }
$lock = [pscustomobject]@{ Nonce = 'lock' }
$runtimeConnection = [pscustomobject]@{
    DatabaseUrl = 'postgresql://runtime@127.0.0.1/ticketbox'
    PersistedDatabaseUrl = 'postgresql://runtime@localhost/ticketbox'
    Password = 'runtime-secret'
}
function Read-TicketboxC07ProductionAuthority {
    return [pscustomobject]@{
        Payload = [pscustomobject]@{ mode = $script:publishedMode }
    }
}
function Complete-TicketboxInstalledManagedSchemaPublication {
    param(
        $DataRoot,
        $HostAuthority,
        $ReleaseIdentity,
        $C07Authority,
        $RuntimePassword,
        $LifecycleReceipt,
        [string]$RecoveryArtifactPath,
        [int]$ObservationTimeoutMilliseconds,
        [string]$Mode
    )
    if ($script:failSchema) { throw 'injected schema publication failure' }
    if (
        $DataRoot -cne 'C:\bound\data' -or
        -not [object]::ReferenceEquals($HostAuthority, $hostAuthority) -or
        -not [object]::ReferenceEquals($ReleaseIdentity, $releaseIdentity) -or
        -not [object]::ReferenceEquals($C07Authority, $authority) -or
        -not [object]::ReferenceEquals($RuntimePassword, $runtimePassword) -or
        -not [object]::ReferenceEquals($LifecycleReceipt, $receipt) -or
        $RecoveryArtifactPath -cne 'C:\bound\recovery.pgpass' -or
        $ObservationTimeoutMilliseconds -ne 7000
    ) { throw 'dispatcher argument binding drift' }
    $script:events += "schema:$Mode"
    $script:lastQualification = [pscustomobject]@{
        schema = 'ticketbox-c07-published-runtime-qualification-v1'
    }
    return [pscustomobject]@{
        published_runtime_qualification = $script:lastQualification
    }
}
function Assert-TicketboxConnectedPostgresDataRoot {
    param(
        [string]$PsqlPath,
        [string]$DatabaseUrl,
        [string]$ExpectedDataRoot,
        [int]$ExpectedPort,
        [string]$Password,
        [int]$TimeoutMilliseconds
    )
    if (
        $PsqlPath -cne 'C:\bound\psql.exe' -or
        $DatabaseUrl -cne $runtimeConnection.DatabaseUrl -or
        $ExpectedDataRoot -cne 'C:\bound\pgdata' -or
        $ExpectedPort -ne 5432 -or
        $Password -cne 'runtime-secret' -or
        $TimeoutMilliseconds -ne 9000
    ) { throw 'runtime connection binding drift' }
    $script:events += 'data_root'
}
function Assert-TicketboxC07RuntimeCredential {
    param($Authority, $RuntimePassword)
    if (
        -not [object]::ReferenceEquals($Authority, $hostAuthority) -or
        -not [object]::ReferenceEquals($RuntimePassword, $runtimePassword)
    ) { throw 'runtime credential binding drift' }
    $script:events += 'runtime_credential'
}
function Write-TicketboxC07InstalledRuntimeEnvironment {
    param($RuntimePassword, $Qualification)
    if (
        -not [object]::ReferenceEquals($RuntimePassword, $runtimePassword) -or
        -not [object]::ReferenceEquals(
            $Qualification,
            $script:lastQualification
        )
    ) {
        throw 'environment password binding drift'
    }
    $script:events += 'environment'
    return 'postgresql://published'
}
function Complete-TicketboxC07InstalledSecretCleanup {
    param($Mode, $LifecycleLock, $RecoveryArtifactPath, $Qualification)
    if (
        -not [object]::ReferenceEquals($LifecycleLock, $lock) -or
        $RecoveryArtifactPath -cne 'C:\bound\recovery.pgpass' -or
        -not [object]::ReferenceEquals(
            $Qualification,
            $script:lastQualification
        )
    ) { throw 'cleanup binding drift' }
    $script:events += "cleanup:$Mode"
}
function Invoke-Case {
    param([string]$Disposition, [object]$Connection)
    $script:events = @()
    try {
        $result = Complete-TicketboxInstalledRuntimePublication `
            -Disposition $Disposition `
            -DataRoot 'C:\bound\data' `
            -HostAuthority $hostAuthority `
            -ReleaseIdentity $releaseIdentity `
            -C07Authority $authority `
            -RuntimePassword $runtimePassword `
            -LifecycleReceipt $receipt `
            -LifecycleLock $lock `
            -RecoveryArtifactPath 'C:\bound\recovery.pgpass' `
            -ObservationTimeoutMilliseconds 7000 `
            -RuntimeConnection $Connection `
            -PsqlPath 'C:\bound\psql.exe' `
            -ExpectedDataRoot 'C:\bound\pgdata' `
            -ExpectedPort 5432 `
            -DatabaseToolTimeoutMilliseconds 9000
        return [pscustomobject]@{
            rejected = $false
            disposition = $Disposition
            mode = [string]$result.mode
            database_url = [string]$result.database_url
            events = @($script:events)
        }
    }
    catch {
        return [pscustomobject]@{
            rejected = $true
            disposition = $Disposition
            error = $_.Exception.Message
            events = @($script:events)
        }
    }
}
$fresh = Invoke-Case fresh_install $null
$legacy = Invoke-Case legacy_adoption $null
$runtime = Invoke-Case runtime_ready $runtimeConnection
$missingConnection = Invoke-Case runtime_ready $null
$script:failSchema = $true
$failedSchema = Invoke-Case runtime_ready $runtimeConnection
@($fresh, $legacy, $runtime, $missingConnection, $failedSchema) |
    ConvertTo-Json -Depth 5 -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    fresh, legacy, runtime, missing_connection, failed_schema = json.loads(
        result.stdout
    )
    assert fresh["mode"] == "fresh_install"
    assert fresh["events"] == ["schema:fresh_install", "environment", "cleanup:fresh_install"]
    assert legacy["mode"] == "legacy_adoption"
    assert legacy["events"] == [
        "schema:legacy_adoption",
        "environment",
        "cleanup:legacy_adoption",
    ]
    assert runtime["mode"] == "legacy_adoption"
    assert runtime["database_url"] == "postgresql://runtime@localhost/ticketbox"
    assert runtime["events"] == [
        "schema:legacy_adoption",
        "data_root",
        "runtime_credential",
        "cleanup:legacy_adoption",
    ]
    assert missing_connection["rejected"] is True
    assert missing_connection["events"] == ["schema:legacy_adoption"]
    assert failed_schema["rejected"] is True
    assert failed_schema["events"] == []


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_managed_schema_scoped_authority_clears_exact_credential_on_failure(
    engine: str,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Invoke-TicketboxInstalledManagedSchemaUpgrade"),
            r"""
$DataRoot = 'C:\protected\data'
$script:setCalls = 0
$script:clearCalls = 0
$script:clearedExactCredential = $false
function New-TestSecureString {
    $secret = New-Object Security.SecureString
    1..32 | ForEach-Object { $secret.AppendChar('R') }
    $secret.MakeReadOnly()
    return $secret
}
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'host' }
}
function Get-TicketboxRuntimeAlembicRevision { return '20260729_0001' }
function Get-TicketboxInstalledDatabaseGenerationProgram {
    return [pscustomobject]@{
        target_revision = '20260729_0001'
        generation_program_sha256 = ('B' * 64)
        c07_target_revision = '20260729_0001'
        c07_revision_manifest_sha256 = ('A' * 64)
    }
}
function New-StrongPassword { return ('M' * 40) }
function ConvertTo-TicketboxC07InstalledSecureString { return New-TestSecureString }
function Set-TicketboxC07DatabaseAuthorityCredential {
    param([Security.SecureString]$Credential)
    $script:setCalls += 1
    $script:setCredential = $Credential
}
function Clear-TicketboxC07DatabaseAuthorityCredential {
    param([Security.SecureString]$ExpectedCredential)
    $script:clearCalls += 1
    $script:clearedExactCredential = [object]::ReferenceEquals(
        $script:setCredential,
        $ExpectedCredential
    )
}
function Read-TicketboxC07Authority {
    throw 'injected managed authority failure'
}
function Invoke-TicketboxC07RecoveredSuperuserAction {
    param($HostAuthority, [string]$RecoveryArtifactPath, [scriptblock]$Action)
    $secret = New-TestSecureString
    try { return & $Action $secret }
    finally { $secret.Dispose() }
}
$authority = [pscustomobject]@{
    Receipt = [pscustomobject]@{
        stage = 'ready'
        operation_id = '11111111-1111-4111-8111-111111111111'
    }
    Descriptor = [pscustomobject]@{
        PayloadSha256 = ('9' * 64)
        Payload = [pscustomobject]@{
            target_alembic_revision = '20260729_0001'
            revision_manifest_sha256 = ('A' * 64)
        }
    }
}
$failedWithPrimary = $false
try {
    Invoke-TicketboxInstalledManagedSchemaUpgrade `
        -DataRoot 'C:\protected\data' `
        -HostAuthority ([pscustomobject]@{ Schema = 'host' }) `
        -ReleaseIdentity ([pscustomobject]@{
            InstallationOperationId = '11111111-1111-4111-8111-111111111111'
        }) `
        -C07Authority $authority `
        -RuntimePassword (New-TestSecureString) `
        -LifecycleReceipt ([pscustomobject]@{}) `
        -RecoveryArtifactPath 'recovery.pgpass' `
        -ObservationTimeoutMilliseconds 7000 `
        -Mode fresh_install | Out-Null
}
catch {
    $failedWithPrimary = $_.Exception.Message.Contains(
        'injected managed authority failure'
    )
}
if (-not $failedWithPrimary -or $script:setCalls -ne 1 -or
    $script:clearCalls -ne 1 -or -not $script:clearedExactCredential) {
    throw 'managed schema action did not clear its exact scoped credential'
}
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_ready_secret_cleanup_is_ordered_fail_closed_and_idempotent(
    engine: str,
    tmp_path: Path,
) -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    recovery = tmp_path / "c07-superuser-recovery.pgpass"
    credential = tmp_path / "installed-credentials.json"
    intent = tmp_path / "fresh-intent.json"
    bootstrap = tmp_path / "bootstrap.recovery"
    for path in (recovery, credential, intent, bootstrap):
        path.write_text("protected", encoding="ascii")
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Complete-TicketboxC07InstalledSecretCleanup"),
            f"$script:credential = {_ps_literal(credential)}",
            f"$script:intent = {_ps_literal(intent)}",
            f"$script:bootstrap = {_ps_literal(bootstrap)}",
            f"$recovery = {_ps_literal(recovery)}",
            "$DataRoot = 'C:\\protected\\data'",
            "$script:order = @()",
            """
$lock = [pscustomobject]@{ Lease = 'held' }
function Assert-TicketboxC07PublishedRuntimeQualification {
    param($DataRoot, $Qualification)
    $script:order += 'qualification'
    return [pscustomobject]@{
        Receipt = [pscustomobject]@{
            stage = 'ready'
            operation_id = '11111111-1111-4111-8111-111111111111'
        }
    }
}
$qualification = [pscustomobject]@{
    schema = 'ticketbox-c07-published-runtime-qualification-v1'
    operation_id = '11111111-1111-4111-8111-111111111111'
}
function Read-TicketboxC07DurableHeartbeatAuthority {
    return [pscustomobject]@{
        Receipt = [pscustomobject]@{
            stage = 'ready'
            operation_id = '11111111-1111-4111-8111-111111111111'
        }
    }
}
function Get-TicketboxC07InstalledCredentialPath { return $script:credential }
function Get-TicketboxC07FreshBootstrapIntentPath { return $script:intent }
function Get-PostgresBootstrapRecoveryPath { return $script:bootstrap }
function Remove-TicketboxC07InstalledCredentials {
    $script:order += 'credentials'
    Remove-Item -LiteralPath $script:credential -Force
}
function Remove-TicketboxC07FreshBootstrapIntent {
    $script:order += 'fresh_intent'
    Remove-Item -LiteralPath $script:intent -Force
}
function Remove-TicketboxSensitiveFile {
    param([string]$Path)
    $script:order += 'bootstrap'
    Remove-Item -LiteralPath $Path -Force
}
$blockedByRecovery = $false
try {
    Complete-TicketboxC07InstalledSecretCleanup `
        -Mode fresh_install `
        -LifecycleLock $lock `
        -RecoveryArtifactPath $recovery `
        -Qualification $qualification
}
catch { $blockedByRecovery = $true }
$orderBeforeRecoveryConverged = @($script:order)
Remove-Item -LiteralPath $recovery -Force
Complete-TicketboxC07InstalledSecretCleanup `
    -Mode fresh_install `
    -LifecycleLock $lock `
    -RecoveryArtifactPath $recovery `
    -Qualification $qualification
$firstOrder = @($script:order)
Complete-TicketboxC07InstalledSecretCleanup `
    -Mode fresh_install `
    -LifecycleLock $lock `
    -RecoveryArtifactPath $recovery `
    -Qualification $qualification
$idempotentOrder = @($script:order)
[IO.File]::WriteAllText($script:intent, 'protected')
$legacyIntentRejected = $false
try {
    Complete-TicketboxC07InstalledSecretCleanup `
        -Mode legacy_adoption `
        -LifecycleLock $lock `
        -RecoveryArtifactPath $recovery `
        -Qualification $qualification
}
catch { $legacyIntentRejected = $true }
[pscustomobject]@{
    blocked_by_recovery = $blockedByRecovery
    order_before_recovery = $orderBeforeRecoveryConverged
    first_order = $firstOrder
    idempotent_order = $idempotentOrder
    legacy_intent_rejected = $legacyIntentRejected
} | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["blocked_by_recovery"] is True
    assert payload["order_before_recovery"] == []
    assert payload["first_order"] == [
        "qualification",
        "credentials",
        "fresh_intent",
        "bootstrap",
    ]
    assert payload["idempotent_order"] == payload["first_order"] + ["qualification"]
    assert payload["legacy_intent_rejected"] is True


def test_migrator_window_is_renewed_before_every_resumed_migration() -> None:
    source = C07_DATABASE.read_text(encoding="utf-8-sig")
    role_sql = _function(source, "Get-TicketboxC07RoleBootstrapSql")
    production = _function(source, "Invoke-TicketboxC07ProductionAuthorityCoordinator")
    fresh = _function(source, "Initialize-TicketboxC07FreshDatabaseAuthority")
    legacy = _function(source, "Invoke-TicketboxC07LegacyDatabaseAdoption")
    assert role_sql.count("VALID UNTIL '$validUntil'") == 2
    assert production.index(
        "Renew-TicketboxC07FrozenMigratorCredentialWindow"
    ) < production.index(
        "$migrationEvidence = & $MigrationAction"
    )
    assert fresh.index(
        "Renew-TicketboxC07FrozenMigratorCredentialWindow"
    ) < fresh.index(
        "return Get-TicketboxC07DatabaseCatalogObservation"
    )
    assert legacy.index(
        "Renew-TicketboxC07FrozenMigratorCredentialWindow"
    ) < legacy.index(
        "return Get-TicketboxC07DatabaseCatalogObservation"
    )
