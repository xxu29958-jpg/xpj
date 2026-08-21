from __future__ import annotations

import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
INSTALLER = PACKAGING / "install_bundled_services.ps1"
INNO_WINDOWS = PACKAGING / "ticketbox-installer-windows.isph"
INNO_FLOW = PACKAGING / "ticketbox-installer-flow.isph"


def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_ps(engine: str, script_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=120,
        check=False,
    )


def test_public_failure_receipt_separates_identity_and_database_state() -> None:
    install = INSTALLER.read_text(encoding="utf-8-sig")
    windows = INNO_WINDOWS.read_text(encoding="utf-8-sig")
    writer = install[
        install.index("function Publish-TicketboxInstallPublicFailureReceipt") :
        install.index("$DatabaseGenerationScript")
    ]
    operation = install[install.index("$operationLock = Enter-TicketboxLifecycleLock") :]
    reader = windows[
        windows.index("function TryLoadInstallPublicFailure") : windows.index(
            "function ServiceInstallationFailureMessage"
        )
    ]

    assert "ticketbox-install-public-failure-v3" in writer
    assert "INSTALLATION_ID_STATE=$InstallationIdState" in writer
    assert "$MutationStarted" not in writer
    assert '[ValidateSet("not_assigned", "assigned")]' in writer
    assert '[ValidateSet("not_started", "started_or_possible")]' in writer
    assert '$receiptInstallationId = ""' in operation
    assert '$receiptInstallationIdState = "not_assigned"' in operation
    assert '$databaseMutationState = "not_started"' in operation
    identity_assigned = operation.index('$receiptInstallationIdState = "assigned"')
    identity_value = operation.index(
        "$receiptInstallationId = [string]$installationIdentity.InstallationId"
    )
    database_possible = operation.index(
        '$databaseMutationState = "started_or_possible"'
    )
    database_boundary = operation.index("Initialize-PgClusterIfNeeded")
    assert identity_value < identity_assigned < database_possible < database_boundary
    catch_publish = operation[operation.rindex("Publish-TicketboxInstallPublicFailureReceipt") :]
    assert "-InstallationIdState $receiptInstallationIdState" in catch_publish
    assert "-DatabaseMutationState $databaseMutationState" in catch_publish
    assert "-MutationStarted" not in catch_publish

    assert "ticketbox-install-public-failure-v3" in windows
    assert "installer-public-failure-v3.txt" in windows
    assert "GetArrayLength(Lines) <> 16" in reader
    assert "'INSTALLATION_ID_STATE'" in reader
    assert "InstallationIdState = 'not_assigned'" in reader
    assert "InstallationId <> ''" in reader
    assert "InstallationIdState = 'assigned'" in reader
    assert "IsInstallerPublicFailureOperationId(InstallationId)" in reader
    assert "installation ID：尚未分配" in reader
    host_reader = reader[
        reader.index("else if FailureCode = 'postgres_host_authority_validation_failed'") :
        reader.index("else if FailureCode = 'installation_identity_recovery_failed'")
    ]
    assert "InstallationIdState <> 'assigned'" not in host_reader


def test_public_failure_receipt_is_bounded_and_contains_no_raw_exception(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "public-failure-receipt-contract.ps1"
    bootstrap_dir = tmp_path / "Ticketbox-Installer-Bootstrap-4242"
    bootstrap_dir.mkdir()
    harness.write_text(
        f"""
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$sourcePath = {_ps_literal(INSTALLER)}
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $sourcePath,
    [ref]$tokens,
    [ref]$errors
)
foreach ($functionName in @(
    'Assert-TicketboxInstallPublicGuid',
    'Publish-TicketboxInstallPublicFailureReceipt',
    'New-TicketboxInstallCompensationAggregateFailure'
)) {{
    $functionAst = $ast.FindAll({{
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq $functionName
    }}, $true) | Select-Object -First 1
    if ($null -eq $functionAst) {{ throw "missing function $functionName" }}
    Invoke-Expression $functionAst.Extent.Text
}}
$script:ExpectedReceipt = Join-Path `
    {_ps_literal(bootstrap_dir)} `
    'installer-public-failure-v3.txt'
$script:ExpectedLog = Join-Path {_ps_literal(bootstrap_dir)} 'installer-test.log'
[IO.File]::WriteAllText(
    $script:ExpectedLog,
    'protected log without secret material',
    [Text.UTF8Encoding]::new($false)
)
function Resolve-TicketboxInstallPublicFailurePath([string]$Path) {{
    $actual = [IO.Path]::GetFullPath($Path)
    $expected = [IO.Path]::GetFullPath($script:ExpectedReceipt)
    if (-not [string]::Equals(
        $actual,
        $expected,
        [StringComparison]::OrdinalIgnoreCase
    )) {{ throw 'public receipt path is outside lifecycle bootstrap' }}
    return $actual
}}
function Resolve-TicketboxInstallDiagnosticLogPath([string]$Path) {{
    $actual = [IO.Path]::GetFullPath($Path)
    $expected = [IO.Path]::GetFullPath($script:ExpectedLog)
    if (-not [string]::Equals(
        $actual,
        $expected,
        [StringComparison]::OrdinalIgnoreCase
    )) {{ throw 'diagnostic log path is outside protected test root' }}
    return $actual
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path,$Text,$FullControlAccounts,$OwnerAccount,[switch]$ReplaceExisting)
    [IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false))
}}
$owner = [pscustomobject]@{{
    ProcessId = [uint32]4242
    StartedFileTimeHigh = [uint32]123
    StartedFileTimeLow = [uint32]456
}}
$lock = [pscustomobject]@{{ ExternalOwnerIdentity = $owner }}
$attempt = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
$installOperation = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
$installation = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
$receipt = $script:ExpectedReceipt
$protectedLog = $script:ExpectedLog
$failure = [IO.InvalidDataException]::new(
    'raw DATABASE_URL=super-secret must never leave the protected log'
)
$failure.Data['TicketboxInstallPublicFailureCode'] =
    'backend_payload_manifest_order_invalid'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState not_assigned `
    -InstallationId '' `
    -LifecycleStage 'package_provenance' `
    -ProtectedLogPath $protectedLog `
    -Failure $failure `
    -DatabaseMutationState not_started
$lines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($lines.Count -ne 16 -or
    $lines[0] -cne 'SCHEMA=ticketbox-install-public-failure-v3' -or
    $lines[1] -cne 'INSTALLER_OWNER_PID=4242' -or
    $lines[4] -cne "FINALIZATION_ATTEMPT_ID=$attempt" -or
    $lines[5] -cne "INSTALLATION_OPERATION_ID=$installOperation" -or
    $lines[6] -cne 'INSTALLATION_ID_STATE=not_assigned' -or
    $lines[7] -cne 'INSTALLATION_ID=' -or
    $lines[8] -cne 'LIFECYCLE_STAGE=package_provenance' -or
    $lines[9] -cne 'CONTEXT=service_installation' -or
    $lines[10] -cne 'FAILURE_CODE=backend_payload_manifest_order_invalid' -or
    $lines[11] -cne 'RETRY_CLASS=replace_package_then_retry_no_cleanup' -or
    $lines[12] -cne 'DATABASE_MUTATION_STATE=not_started' -or
    $lines[13] -cne 'SUPPORT_CODE=TBX-INSTALL-PROVENANCE-ORDER' -or
    $lines[14] -cne "PROTECTED_LOG_PATH=$protectedLog" -or
    $lines[15] -cne "PUBLIC_RECEIPT_PATH=$receipt") {{
    throw 'public failure receipt shape or binding drifted'
}}
$text = [IO.File]::ReadAllText($receipt,[Text.UTF8Encoding]::new($false))
if ($text.Length -gt 4096 -or $text -match 'DATABASE_URL|super-secret') {{
    throw 'public failure receipt exposed raw exception material'
}}
$fakeUnassignedRejected = $false
try {{
    Publish-TicketboxInstallPublicFailureReceipt `
        -Path $receipt `
        -LifecycleLock $lock `
        -FinalizationAttemptId $attempt `
        -InstallationOperationId $installOperation `
        -InstallationIdState not_assigned `
        -InstallationId $installation `
        -LifecycleStage 'package_provenance' `
        -ProtectedLogPath $protectedLog `
        -Failure $failure `
        -DatabaseMutationState not_started
}}
catch {{ $fakeUnassignedRejected = $_.Exception.Message -like '*不得携带伪造值*' }}
if (-not $fakeUnassignedRejected) {{
    throw 'not_assigned receipt accepted a fabricated installation ID'
}}
$invalidAssignedRejected = $false
try {{
    Publish-TicketboxInstallPublicFailureReceipt `
        -Path $receipt `
        -LifecycleLock $lock `
        -FinalizationAttemptId $attempt `
        -InstallationOperationId $installOperation `
        -InstallationIdState assigned `
        -InstallationId 'not-yet-assigned' `
        -LifecycleStage 'service_registration' `
        -ProtectedLogPath $protectedLog `
        -Failure $failure `
        -DatabaseMutationState started_or_possible
}}
catch {{ $invalidAssignedRejected = $_.Exception.Message -like '*规范非零 UUID*' }}
if (-not $invalidAssignedRejected) {{
    throw 'assigned receipt accepted a consumer-invalid installation ID'
}}
$initdbFailure = [InvalidOperationException]::new('private initdb diagnostic')
$initdbFailure.Data['TicketboxInstallPublicFailureCode'] =
    'postgres_cluster_initialization_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState assigned `
    -InstallationId $installation `
    -LifecycleStage 'database_cluster' `
    -ProtectedLogPath $protectedLog `
    -Failure $initdbFailure `
    -DatabaseMutationState started_or_possible
$initdbLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($initdbLines[10] -cne 'FAILURE_CODE=postgres_cluster_initialization_failed' -or
    $initdbLines[11] -cne 'RETRY_CLASS=retry_no_cleanup' -or
    $initdbLines[12] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $initdbLines[13] -cne 'SUPPORT_CODE=TBX-INSTALL-INITDB') {{
    throw 'initdb public failure receipt drifted'
}}
$hostFailure = [InvalidOperationException]::new('private PostgreSQL host diagnostic')
$hostFailure.Data['TicketboxInstallPublicFailureCode'] =
    'postgres_host_authority_validation_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState assigned `
    -InstallationId $installation `
    -LifecycleStage 'service_registration' `
    -ProtectedLogPath $protectedLog `
    -Failure $hostFailure `
    -DatabaseMutationState started_or_possible
$hostLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($hostLines[10] -cne 'FAILURE_CODE=postgres_host_authority_validation_failed' -or
    $hostLines[11] -cne 'RETRY_CLASS=retry_no_cleanup' -or
    $hostLines[12] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $hostLines[13] -cne 'SUPPORT_CODE=TBX-INSTALL-POSTGRES-HOST') {{
    throw 'PostgreSQL host public failure receipt drifted'
}}
$cleanupFailure = [InvalidOperationException]::new('private cleanup diagnostic')
$aggregateFailure = New-TicketboxInstallCompensationAggregateFailure `
    -InstallFailure $initdbFailure `
    -CompensationFailure $cleanupFailure
if (-not [bool]$aggregateFailure.Data['TicketboxInstallCompensationFailed'] -or
    [string]$aggregateFailure.Data['TicketboxInstallPublicFailureCode'] -cne
        'unclassified_service_install_failure') {{
    throw 'incomplete compensation preserved a misleading retry classification'
}}
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState assigned `
    -InstallationId $installation `
    -LifecycleStage 'service_registration' `
    -ProtectedLogPath $protectedLog `
    -Failure $aggregateFailure `
    -DatabaseMutationState started_or_possible
$aggregateLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($aggregateLines[10] -cne 'FAILURE_CODE=unclassified_service_install_failure' -or
    $aggregateLines[11] -cne 'RETRY_CLASS=manual_review_preserve_state' -or
    $aggregateLines[13] -cne 'SUPPORT_CODE=TBX-INSTALL-UNKNOWN') {{
    throw 'incomplete compensation did not fail closed to UNKNOWN support'
}}
$identityFailure = [InvalidOperationException]::new('private identity diagnostic')
$identityFailure.Data['TicketboxInstallPublicFailureCode'] =
    'installation_identity_recovery_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState not_assigned `
    -InstallationId '' `
    -LifecycleStage 'installation_identity' `
    -ProtectedLogPath $protectedLog `
    -Failure $identityFailure `
    -DatabaseMutationState not_started
$identityLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($identityLines[6] -cne 'INSTALLATION_ID_STATE=not_assigned' -or
    $identityLines[7] -cne 'INSTALLATION_ID=' -or
    $identityLines[10] -cne 'FAILURE_CODE=installation_identity_recovery_failed' -or
    $identityLines[11] -cne 'RETRY_CLASS=retry_same_operation_no_cleanup' -or
    $identityLines[12] -cne 'DATABASE_MUTATION_STATE=not_started' -or
    $identityLines[13] -cne 'SUPPORT_CODE=TBX-INSTALL-IDENTITY') {{
    throw 'identity public failure receipt drifted'
}}
$ownerBindingFailure = [InvalidOperationException]::new('private owner binding diagnostic')
$ownerBindingFailure.Data['TicketboxInstallPublicFailureCode'] =
    'installation_owner_binding_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState assigned `
    -InstallationId $installation `
    -LifecycleStage 'installation_owner_claim' `
    -ProtectedLogPath $protectedLog `
    -Failure $ownerBindingFailure `
    -DatabaseMutationState started_or_possible
$ownerBindingLines = [IO.File]::ReadAllLines(
    $receipt,
    [Text.UTF8Encoding]::new($false)
)
if ($ownerBindingLines[10] -cne 'FAILURE_CODE=installation_owner_binding_failed' -or
    $ownerBindingLines[11] -cne 'RETRY_CLASS=retry_same_operation_no_cleanup' -or
    $ownerBindingLines[13] -cne 'SUPPORT_CODE=TBX-INSTALL-OWNER-BINDING') {{
    throw 'installation owner binding public failure receipt drifted'
}}
$unknown = [InvalidOperationException]::new('another private diagnostic')
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -InstallationOperationId $installOperation `
    -InstallationIdState assigned `
    -InstallationId $installation `
    -LifecycleStage 'schema_migration' `
    -ProtectedLogPath $protectedLog `
    -Failure $unknown `
    -DatabaseMutationState started_or_possible
$updated = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($updated[10] -cne 'FAILURE_CODE=unclassified_service_install_failure' -or
    $updated[11] -cne 'RETRY_CLASS=manual_review_preserve_state' -or
    $updated[12] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $updated[13] -cne 'SUPPORT_CODE=TBX-INSTALL-UNKNOWN') {{
    throw 'unknown public failure receipt did not fail closed'
}}
$outsideRejected = $false
try {{
    Publish-TicketboxInstallPublicFailureReceipt `
        -Path (Join-Path (Split-Path -Parent {_ps_literal(bootstrap_dir)}) 'outside.txt') `
        -LifecycleLock $lock `
        -FinalizationAttemptId $attempt `
        -InstallationOperationId $installOperation `
        -InstallationIdState not_assigned `
        -InstallationId '' `
        -LifecycleStage 'package_provenance' `
        -ProtectedLogPath $protectedLog `
        -Failure $failure `
        -DatabaseMutationState not_started
}}
catch {{ $outsideRejected = $_.Exception.Message -like '*lifecycle bootstrap*' }}
if (-not $outsideRejected) {{ throw 'out-of-scope public receipt path was accepted' }}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = _run_ps(engine, harness)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
