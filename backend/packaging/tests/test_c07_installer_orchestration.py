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


def _function(source: str, name: str) -> str:
    start = source.index(f"function {name} {{")
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
    main = source[source.rindex("    $c07Disposition =") :]
    assert main.index("$c07Disposition =") < main.index(
        "Invoke-TicketboxC07InstalledReleaseMigration"
    )
    migration_path = main[main.index("$c07Migration =") :]
    assert migration_path.index("Invoke-TicketboxC07InstalledReleaseMigration") < migration_path.index(
        "Write-TicketboxC07InstalledRuntimeEnvironment"
    )
    assert migration_path.index("Write-TicketboxC07InstalledRuntimeEnvironment") < migration_path.index(
        "Complete-TicketboxC07InstalledSecretCleanup"
    )
    assert migration_path.index("Complete-TicketboxC07InstalledSecretCleanup") < migration_path.index(
        "Resolve-TicketboxBootstrapExposureRecoveryIntent"
    )
    assert main.index("Resolve-TicketboxBootstrapExposureRecoveryIntent") < main.index(
        "Start-TicketboxOwnedServiceIfExists `\n            -Name $BackendServiceName"
    )

    release = _function(source, "Invoke-TicketboxC07InstalledReleaseMigration")
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
    upgrade_plan = _function(source, "Get-TicketboxC07InstalledUpgradePlan")
    assert "ExpectedMoneyFactsSha256" not in isolated
    assert "Get-TicketboxC07PackagedInstalledUpgradePlan" in upgrade_plan
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
    assert len(acl_calls) == len(retire_calls) == 2
    assert all(acl < retire for acl, retire in zip(acl_calls, retire_calls, strict=True))
    assert managed.index("$upgradeResult = Invoke-TicketboxInstalledManagedSchemaUpgradeAction") < managed.index(
        "Set-TicketboxManagedSchemaRuntimeAcl",
        acl_calls[0] + 1,
    )
    assert managed.index("return $upgradeResult") > acl_calls[1]


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
    assert prepare.index("Repair-TicketboxPreflightInstallAcl") < prepare.index(
        "Disable-TicketboxOwnedServiceIfExists",
        prepare.index("$installAclMutationStarted = $false"),
    )

    stale_start = prepare.index(
        "if (Test-Path -LiteralPath $LifecycleReceiptPath -PathType Leaf)"
    )
    stale_end = prepare.index(
        "Initialize-TicketboxInstalledReleaseConfiguration",
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
            "$script:testStage = 'refused_pre_ddl'",
            lifecycle_failure,
            release_migration,
            "function Resolve-TicketboxC07DatabaseHostAuthority { "
            "[pscustomobject]@{} }",
            "function Get-TicketboxC07InstalledUpgradePlan { "
            "[pscustomobject]@{ operation_kind = "
            "'c07_money_minor_bigint_v1'; source_revision = "
            "'20260722_0001'; target_revision = '20260729_0001'; "
            "upgrade_required = $true; revision_manifest_sha256 = "
            "('a' * 64) } }",
            "function Assert-TicketboxC07LowerSha256 { param($Value, $Label) }",
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
            compensation_helper,
            "$script:BackendServiceName = 'TicketboxBackend'",
            "$script:PgServiceName = 'TicketboxPostgres'",
            "$script:ShawlExe = 'C:\\ticketbox\\shawl.exe'",
            "$script:BackendExe = 'C:\\ticketbox\\backend.exe'",
            "$script:BackendPort = 8002",
            "$script:PgCtl = 'C:\\ticketbox\\pg_ctl.exe'",
            "$script:PgBin = 'C:\\ticketbox\\pg'",
            "$script:InstallerState = 'C:\\ticketbox\\state'",
            "$script:LegacyRecoveryRequiredPath = 'C:\\legacy.json'",
            "$script:RecoveryRequiredPath = 'C:\\current.json'",
            "$script:InstallDir = 'C:\\ticketbox'",
            "$script:DataRoot = 'C:\\ticketbox-data'",
            "$script:ServiceWaitArguments = @{ "
            "TimeoutMilliseconds = 100; PollMilliseconds = 10 }",
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
            "$compensation = $null",
            "try {",
            "  Invoke-TicketboxInstallFailureCompensation 'install failed'",
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
$script:operationId = '11111111-1111-4111-8111-111111111111'
$releaseIdentity = [pscustomobject]@{
    InstallationIdentityState = 'PENDING'
    InstallationOperationId = $script:operationId
    MigrationHelperPath = 'C:\\protected\\ticketbox-c07-migrator.exe'
}
function Resolve-TicketboxC07DatabaseHostAuthority {
    return [pscustomobject]@{ Schema = 'host' }
}
function Get-TicketboxC07InstalledUpgradePlan {
    param($ReleaseIdentity, [string]$SourceRevision)
    return [pscustomobject]@{
        operation_kind = 'c07_money_minor_bigint_v1'
        source_revision = $SourceRevision
        target_revision = '20260729_0001'
        upgrade_required = $true
        revision_manifest_sha256 = ('a' * 64)
    }
}
function Assert-TicketboxC07LowerSha256 {
    param([string]$Value, [string]$Label)
    if ($Value -cnotmatch '^[0-9a-f]{64}$') { throw "$Label is invalid" }
}
function Get-TicketboxC07AuthorityPath { return $script:authorityPath }
function Invoke-TicketboxC07RecoveredSuperuserAction {
    param($HostAuthority, [string]$RecoveryArtifactPath, [scriptblock]$Action)
    return & $Action $script:superuserPassword
}
function Initialize-TicketboxC07FreshDatabaseAuthority {
    param(
        $SuperuserPassword,
        $RuntimePassword,
        $MigratorPassword,
        [DateTime]$MigratorValidUntilUtc,
        [string]$OperationId
    )
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
    param([string]$Revision, [bool]$HasAuthority)
    $script:revision = $Revision
    $script:initCalls = 0
    $script:freshCalls = 0
    if ($HasAuthority) {
        [IO.File]::WriteAllText($script:authorityPath, '{}')
    }
    elseif (Test-Path -LiteralPath $script:authorityPath) {
        Remove-Item -LiteralPath $script:authorityPath -Force
    }
    $result = Invoke-TicketboxC07InstalledReleaseMigration `
        -ReleaseIdentity $releaseIdentity `
        -Mode fresh_install `
        -LifecycleLock $lock `
        -FreshIntent $intent `
        -RecoveryArtifactPath 'C:\\protected\\c07-superuser-recovery.pgpass'
    return [pscustomobject]@{
        result = $result.result
        init = $script:initCalls
        fresh = $script:freshCalls
    }
}
@(
    Invoke-TestRun '' $false
    Invoke-TestRun '20260722_0001' $false
    Invoke-TestRun '20260729_0001' $true
) | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == [
        {"result": "ready", "init": 1, "fresh": 1},
        {"result": "ready", "init": 1, "fresh": 0},
        {"result": "ready", "init": 0, "fresh": 0},
    ]


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
    env_path = tmp_path / ".env"
    script = "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            _function(source, "Write-TicketboxC07InstalledRuntimeEnvironment"),
            f"$EnvPath = {_ps_literal(env_path)}",
            "$PgPort = 5432",
            "$PgData = 'C:\\protected\\pgdata'",
            "$Psql = 'C:\\protected\\psql.exe'",
            "$DatabaseToolTimeoutMs = 600000",
            "$script:TicketboxC07DatabaseName = 'ticketbox'",
            "$script:TicketboxC07RuntimeRole = 'ticketbox_runtime'",
            "$script:order = @()",
            "$script:envMap = @{}",
            "$script:writtenLines = @()",
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
function Read-TicketboxC07Authority {
    return [pscustomobject]@{
        Receipt = [pscustomobject]@{ stage = 'ready' }
    }
}
function Read-TicketboxC07RuntimeProjection {
    return [pscustomobject]@{ PayloadSha256 = ('A' * 64) }
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
    $script:writtenLines = @($Lines)
    $databaseLine = @($Lines | Where-Object { $_.StartsWith('DATABASE_URL=') })
    $script:envMap = @{ DATABASE_URL = $databaseLine[0].Substring(13) }
}
function Set-EnvDatabaseUrl { throw 'fresh harness must create the complete env' }
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
$result = Write-TicketboxC07InstalledRuntimeEnvironment `
    -RuntimePassword $runtimePassword
[pscustomobject]@{
    result = $result
    order = $script:order
    lines = $script:writtenLines
} | ConvertTo-Json -Compress
""",
        )
    )
    result = _run_ps(engine, script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "ticketbox_runtime:" in payload["result"]
    assert payload["order"] == ["data_root", "runtime_credential"]
    assert "ENABLE_HTTP_BOOTSTRAP=true" in payload["lines"]
    assert "HTTP_BOOTSTRAP_SECRET=http-bootstrap-secret" in payload["lines"]


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
function Read-TicketboxC07Authority {
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
        -RecoveryArtifactPath $recovery
}
catch { $blockedByRecovery = $true }
$orderBeforeRecoveryConverged = @($script:order)
Remove-Item -LiteralPath $recovery -Force
Complete-TicketboxC07InstalledSecretCleanup `
    -Mode fresh_install `
    -LifecycleLock $lock `
    -RecoveryArtifactPath $recovery
$firstOrder = @($script:order)
Complete-TicketboxC07InstalledSecretCleanup `
    -Mode fresh_install `
    -LifecycleLock $lock `
    -RecoveryArtifactPath $recovery
$idempotentOrder = @($script:order)
[IO.File]::WriteAllText($script:intent, 'protected')
$legacyIntentRejected = $false
try {
    Complete-TicketboxC07InstalledSecretCleanup `
        -Mode legacy_adoption `
        -LifecycleLock $lock `
        -RecoveryArtifactPath $recovery
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
    assert payload["first_order"] == ["credentials", "fresh_intent", "bootstrap"]
    assert payload["idempotent_order"] == ["credentials", "fresh_intent", "bootstrap"]
    assert payload["legacy_intent_rejected"] is True


def test_migrator_window_is_renewed_before_every_resumed_migration() -> None:
    source = C07_DATABASE.read_text(encoding="utf-8-sig")
    role_sql = _function(source, "Get-TicketboxC07RoleBootstrapSql")
    production = _function(source, "Invoke-TicketboxC07ProductionAuthorityCoordinator")
    fresh = _function(source, "Initialize-TicketboxC07FreshDatabaseAuthority")
    legacy = _function(source, "Invoke-TicketboxC07LegacyDatabaseAdoption")
    assert role_sql.count("VALID UNTIL '$validUntil'") == 2
    assert production.index("Renew-TicketboxC07RoleCredentialWindow") < production.index(
        "$migrationEvidence = & $MigrationAction"
    )
    assert fresh.index("Renew-TicketboxC07RoleCredentialWindow") < fresh.index(
        "return Get-TicketboxC07DatabaseIdentity"
    )
    assert legacy.index("Renew-TicketboxC07RoleCredentialWindow") < legacy.index(
        "return Get-TicketboxC07DatabaseIdentity"
    )
