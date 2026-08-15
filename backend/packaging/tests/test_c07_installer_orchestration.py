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


def test_installer_generation_cutover_has_one_shipped_owner() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")
    main = source[source.index('    $installLifecycleStage = "schema_migration"') :]
    owner_name = "Invoke-TicketboxInstalledDatabaseGeneration"
    owner_path = PACKAGING / "windows_database_generation.ps1"

    assert owner_path.is_file(), "the production Generation Owner is not implemented"
    assert main.count(owner_name) == 1
    for retired_call in (
        "Get-TicketboxC07InstallerDatabaseDisposition",
        "Invoke-TicketboxC07InstalledReleaseMigration",
        "Complete-TicketboxInstalledRuntimePublication",
        "Set-TicketboxLifecycleReceiptC07ReadyEvidence",
    ):
        assert retired_call not in main

    flow = (PACKAGING / "ticketbox-installer-flow.isph").read_text(
        encoding="utf-8-sig"
    )
    assert flow.count("{app}\\installer\\install_bundled_services.ps1") == 2
    installer = (PACKAGING / "ticketbox-installer.iss").read_text(
        encoding="utf-8-sig"
    )
    assert (
        'Source: "windows_database_generation.ps1"; '
        'DestDir: "{app}\\installer"; Flags: ignoreversion'
    ) in installer
    provenance = (
        PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"
    ).read_text(encoding="utf-8-sig")
    assert '"packaging\\windows_database_generation.ps1"' in provenance


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
