from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
SUMMARY = PACKAGING / "windows_c07_failure_summary.ps1"
INSTALLER = PACKAGING / "install_bundled_services.ps1"
INNO_WINDOWS = PACKAGING / "ticketbox-installer-windows.isph"
INNO_FLOW = PACKAGING / "ticketbox-installer-flow.isph"
INNO = PACKAGING / "ticketbox-installer.iss"
PROVENANCE = PACKAGING.parent / "scripts" / "windows_build_provenance.ps1"


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


def test_failure_summary_is_an_allowlisted_projection_not_a_second_authority() -> None:
    source = SUMMARY.read_text(encoding="utf-8-sig")
    install = INSTALLER.read_text(encoding="utf-8-sig")
    windows = INNO_WINDOWS.read_text(encoding="utf-8-sig")
    flow = INNO_FLOW.read_text(encoding="utf-8-sig")

    assert "ticketbox-c07-installer-failure-summary-v2" in source
    assert '"OPERATION_ID"' in source
    assert '"FINALIZATION_ATTEMPT_ID"' in source
    assert '"SOURCE_REVISION"' in source
    assert '"TARGET_REVISION"' in source
    assert '"LIFECYCLE_STAGE"' in source
    assert '"LAST_DURABLE_STAGE"' in source
    assert '"FAILURE_CODE"' in source
    assert '"RECOVERY_POINT"' in source
    assert '"RETRY_POLICY"' in source
    assert '"NO_RETURN_CROSSED"' in source
    assert '"DATA_STATE"' in source
    assert '"NEXT_ACTION"' in source
    assert "$Failure.Message" not in source
    assert "InnerException.Message" not in source
    assert "DATABASE_URL" not in source
    assert "Password" not in source
    assert "Write-TicketboxProtectedUtf8FileDurable" in source
    assert "ReadExactUtf8File" in source
    assert "GetDirectoryIdentity" in source
    assert "Get-TicketboxPathEntryKindNoFollow" in source
    assert "Assert-TicketboxExactFileAcl" in source
    assert "Assert-TicketboxProtectedDirectoryAcl" in source

    compensation = install.rindex("Invoke-TicketboxInstallFailureCompensation")
    publish = install.index(
        "Write-TicketboxInstallC07FailureSummaryIfPresent",
        compensation,
    )
    payload_close = install.rindex("Close-TicketboxInstalledC07PayloadAuthorityLease")
    blocked_publish = install.rindex(
        "Write-TicketboxInstallC07FailureSummaryIfPresent"
    )
    lifecycle_exit_projection = install.rindex(
        "New-TicketboxInstallC07LifecycleExitFailureProjectionIfPresent"
    )
    lifecycle_exit_veto = install.rindex(
        "New-TicketboxInstallC07LifecycleExitVetoIfPresent"
    )
    release = install.rindex("Exit-TicketboxLifecycleLock")
    lifecycle_exit_blocked_publish = install.rindex(
        "Publish-TicketboxC07InstallerLifecycleExitFailureProjection"
    )
    assert compensation < publish < release
    assert payload_close < blocked_publish < release
    lifecycle_exit_veto_complete = install.rindex(
        "Complete-TicketboxC07InstallerLifecycleExitVeto"
    )
    finalization_success_guard = install.rindex(
        "$finalizationFailures.Count -eq 0"
    )
    assert lifecycle_exit_veto < lifecycle_exit_projection < release
    assert release < finalization_success_guard < lifecycle_exit_veto_complete
    assert '"TicketboxC07FailureSummaryFailed"' in install[
        finalization_success_guard - 500 : lifecycle_exit_veto_complete
    ]
    assert release < lifecycle_exit_blocked_publish
    assert '"TicketboxInstallFinalizationFailed"' in install
    assert '"blocked_failure_summary_publish"' in install
    assert '"lifecycle_exit_blocked_summary_publish"' in install
    assert '"lifecycle_exit_veto_prepare"' in install
    assert '"lifecycle_exit_veto_complete"' in install
    assert "$C07FailureSummaryScript" in install
    assert ". $C07FailureSummaryScript" in install

    assert "GetArrayLength(Lines) <> 18" in windows
    assert "SummarySize > C07FailureSummaryMaximumBytes" in windows
    assert "IsC07FailureSummaryOperationId" in windows
    assert "C07FailureSummaryStageFieldsValid" in windows
    assert "successor_pre_ddl" in windows
    assert "successor_forward_repair" in windows
    assert "resume_same_operation" in windows
    assert "keep_services_stopped_contact_support" in windows
    assert "安全回执缺失、过期或校验失败" in windows
    assert "无法安全判断失败发生在数据库维护前还是维护中" in windows
    assert "TryLoadC07FailureSummary(Result)" in windows
    assert "TryLoadInstallPublicFailure(Result)" in windows
    assert windows.index("TryLoadC07FailureSummary(Result)") < windows.index(
        "TryLoadInstallPublicFailure(Result)"
    )
    assert "ticketbox-c07-installer-lifecycle-exit-veto-v2" in windows
    assert "'FINALIZATION_ATTEMPT_ID'" in windows
    assert "C07FailureSummaryReleaseAllowsRetry" in windows
    assert "(FinalizationAttemptId = ExpectedFinalizationAttemptId)" in windows
    assert "IsC07FailureSummaryOperationId(FinalizationAttemptId)" in windows
    assert "(FinalizationAttemptId <> LifecycleFinalizationAttemptId)" in windows
    assert "LifecycleFinalizationAttemptId))" in windows
    assert "function BeginLifecycleFinalizationAttempt(): Boolean;" in windows
    assert "GetSHA256OfString(BindingText)" in windows
    assert '"LifecycleFinalizationAttemptId"' in windows
    assert "State = 'lock_release_completed'" in windows
    veto_gate = windows.index("C07FailureSummaryReleaseAllowsRetry(")
    actionable_message = windows.index("if RevisionState = 'source'", veto_gate)
    assert veto_gate < actionable_message
    assert "可能过期的重试摘要" in windows
    assert "$LifecycleFinalizationAttemptId" in install
    assert "[guid]::NewGuid()" not in install
    assert "[guid]::TryParseExact(" in install
    assert install.count(
        "-FinalizationAttemptId $LifecycleFinalizationAttemptId"
    ) == 5
    begin_attempt = flow.index("BeginLifecycleFinalizationAttempt()")
    pass_attempt = flow.index(" -LifecycleFinalizationAttemptId ", begin_attempt)
    pass_public_failure = flow.index(" -PublicFailurePath ", pass_attempt)
    service_call = flow.index("'Ticketbox service installation'", pass_attempt)
    assert begin_attempt < pass_attempt < pass_public_failure < service_call
    assert "RecordInstallationFailure(LastPowerShellFailureMessage)" in flow
    post_install = flow[
        flow.index("if CurStep = ssPostInstall") : flow.index(
            "function GetCustomSetupExitCode"
        )
    ]
    assert "RaiseException" not in post_install
    assert "ShowInstallationFailurePage" in flow
    assert "LifecycleInstallFailed or" in flow
    assert "Result := 4" in flow
    assert "Ticketbox service installation failed." not in flow
    assert "LifecycleBootstrapFilePath(InstallPublicFailureFileName)" in flow
    assert "LifecycleInstallerStatePath(InstallPublicFailureFileName)" not in flow
    runner = windows[
        windows.index("function RunPowerShellChecked") : windows.index(
            "function DataRootGuardStoppedAcknowledged"
        )
    ]
    assert "PowerShell 退出码" not in runner
    assert "详细日志：" not in runner
    assert "日志目录：" not in runner
    assert "TBX-PREP-FAILED" in runner
    assert "TBX-INSTALL-LOG" in runner
    assert "postgres_cluster_initialization_failed" in install
    assert "TBX-INSTALL-INITDB" in install
    assert "postgres_host_authority_validation_failed" in install
    assert "TBX-INSTALL-POSTGRES-HOST" in install
    assert "installation_identity_recovery_failed" in install
    assert "TBX-INSTALL-IDENTITY" in install
    preinstall = flow[
        flow.index("if CurStep = ssInstall") : flow.index("if CurStep = ssPostInstall")
    ]
    assert "SuppressibleMsgBox(" in preinstall
    assert "Abort();" in preinstall
    assert "RaiseException(PreparationFailure)" not in preinstall
    public_reader = windows[
        windows.index("function TryLoadInstallPublicFailure") : windows.index(
            "function C07ServiceInstallationFailureMessage"
        )
    ]
    assert "LifecycleBootstrapFilePath(InstallPublicFailureFileName)" in public_reader
    assert "postgres_cluster_initialization_failed" in public_reader
    assert "TBX-INSTALL-INITDB" in public_reader
    assert "postgres_host_authority_validation_failed" in public_reader
    assert "TBX-INSTALL-POSTGRES-HOST" in public_reader
    assert "installation_identity_recovery_failed" in public_reader
    assert "TBX-INSTALL-IDENTITY" in public_reader
    resolver = install[
        install.index("function Resolve-TicketboxInstallPublicFailurePath") : install.index(
            "function Publish-TicketboxInstallPublicFailureReceipt"
        )
    ]
    assert "[Environment+SpecialFolder]::CommonProgramFiles" in resolver
    assert '"Ticketbox-Installer-Bootstrap-$InstallerLockOwnerProcessId"' in resolver
    assert "Assert-TicketboxProtectedDirectoryAcl $bootstrapRoot" in resolver
    assert "$InstallerState" not in resolver
    resolve_before_lease = install.index(
        "Resolve-TicketboxInstallPublicFailurePath $PublicFailurePath",
        install.index("$operationLock = Enter-TicketboxLifecycleLock"),
    )
    payload_lease = install.index("Enter-TicketboxInstalledC07PayloadAuthorityLease")
    assert resolve_before_lease < payload_lease


def test_failure_summary_is_packaged_and_bound_into_recipe_provenance() -> None:
    installer = INNO.read_text(encoding="utf-8-sig")
    provenance = PROVENANCE.read_text(encoding="utf-8-sig")
    assert (
        'Source: "windows_c07_failure_summary.ps1"; '
        'DestDir: "{app}\\installer"; Flags: ignoreversion'
    ) in installer
    assert '"packaging\\windows_c07_failure_summary.ps1"' in provenance


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
    'installer-public-failure-v1.txt'
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
$receipt = $script:ExpectedReceipt
$failure = [IO.InvalidDataException]::new(
    'raw DATABASE_URL=super-secret must never leave the protected log'
)
$failure.Data['TicketboxInstallPublicFailureCode'] =
    'backend_payload_manifest_order_invalid'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -Failure $failure `
    -MutationStarted $false
$lines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($lines.Count -ne 9 -or
    $lines[0] -cne 'SCHEMA=ticketbox-install-public-failure-v1' -or
    $lines[1] -cne 'INSTALLER_OWNER_PID=4242' -or
    $lines[4] -cne "FINALIZATION_ATTEMPT_ID=$attempt" -or
    $lines[5] -cne 'CONTEXT=service_installation' -or
    $lines[6] -cne 'FAILURE_CODE=backend_payload_manifest_order_invalid' -or
    $lines[7] -cne 'DATABASE_MUTATION_STATE=not_started' -or
    $lines[8] -cne 'SUPPORT_CODE=TBX-INSTALL-PROVENANCE-ORDER') {{
    throw 'public failure receipt shape or binding drifted'
}}
$text = [IO.File]::ReadAllText($receipt,[Text.UTF8Encoding]::new($false))
if ($text.Length -gt 2048 -or $text -match 'DATABASE_URL|super-secret') {{
    throw 'public failure receipt exposed raw exception material'
}}
$initdbFailure = [InvalidOperationException]::new('private initdb diagnostic')
$initdbFailure.Data['TicketboxInstallPublicFailureCode'] =
    'postgres_cluster_initialization_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -Failure $initdbFailure `
    -MutationStarted $true
$initdbLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($initdbLines[6] -cne 'FAILURE_CODE=postgres_cluster_initialization_failed' -or
    $initdbLines[7] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $initdbLines[8] -cne 'SUPPORT_CODE=TBX-INSTALL-INITDB') {{
    throw 'initdb public failure receipt drifted'
}}
$hostFailure = [InvalidOperationException]::new('private PostgreSQL host diagnostic')
$hostFailure.Data['TicketboxInstallPublicFailureCode'] =
    'postgres_host_authority_validation_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -Failure $hostFailure `
    -MutationStarted $true
$hostLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($hostLines[6] -cne 'FAILURE_CODE=postgres_host_authority_validation_failed' -or
    $hostLines[7] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $hostLines[8] -cne 'SUPPORT_CODE=TBX-INSTALL-POSTGRES-HOST') {{
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
    -Failure $aggregateFailure `
    -MutationStarted $true
$aggregateLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($aggregateLines[6] -cne 'FAILURE_CODE=unclassified_service_install_failure' -or
    $aggregateLines[8] -cne 'SUPPORT_CODE=TBX-INSTALL-UNKNOWN') {{
    throw 'incomplete compensation did not fail closed to UNKNOWN support'
}}
$identityFailure = [InvalidOperationException]::new('private identity diagnostic')
$identityFailure.Data['TicketboxInstallPublicFailureCode'] =
    'installation_identity_recovery_failed'
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -Failure $identityFailure `
    -MutationStarted $true
$identityLines = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($identityLines[6] -cne 'FAILURE_CODE=installation_identity_recovery_failed' -or
    $identityLines[7] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $identityLines[8] -cne 'SUPPORT_CODE=TBX-INSTALL-IDENTITY') {{
    throw 'identity public failure receipt drifted'
}}
$unknown = [InvalidOperationException]::new('another private diagnostic')
Publish-TicketboxInstallPublicFailureReceipt `
    -Path $receipt `
    -LifecycleLock $lock `
    -FinalizationAttemptId $attempt `
    -Failure $unknown `
    -MutationStarted $true
$updated = [IO.File]::ReadAllLines($receipt,[Text.UTF8Encoding]::new($false))
if ($updated[6] -cne 'FAILURE_CODE=unclassified_service_install_failure' -or
    $updated[7] -cne 'DATABASE_MUTATION_STATE=started_or_possible' -or
    $updated[8] -cne 'SUPPORT_CODE=TBX-INSTALL-UNKNOWN') {{
    throw 'unknown public failure receipt did not fail closed'
}}
$outsideRejected = $false
try {{
    Publish-TicketboxInstallPublicFailureReceipt `
        -Path (Join-Path (Split-Path -Parent {_ps_literal(bootstrap_dir)}) 'outside.txt') `
        -LifecycleLock $lock `
        -FinalizationAttemptId $attempt `
        -Failure $failure `
        -MutationStarted $false
}}
catch {{ $outsideRejected = $_.Exception.Message -like '*lifecycle bootstrap*' }}
if (-not $outsideRejected) {{ throw 'out-of-scope public receipt path was accepted' }}
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = _run_ps(engine, harness)
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_failure_summary_round_trip_and_tamper_rejection_on_ps51_and_ps7(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "failure-summary-contract.ps1"
    state_dir = tmp_path / "installer-state"
    state_dir.mkdir()
    harness.write_text(
        f"""
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$script:StateDirectory = {_ps_literal(state_dir)}
$script:TicketboxC07OrderedStages = @(
    'captured','writers_frozen','recovery_generation_ready',
    'isolated_restore_verified','ddl_started','target_committed',
    'target_recovery_generation_ready','target_isolated_restore_verified',
    'runtime_acl_verified','ready'
)
$script:TicketboxC07FailureStages = @('refused_pre_ddl','repair_required')
$script:leaseHeld = $true
$script:finalizationAttemptId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
function Assert-TicketboxC07OperationLease {{
    param($Authority,$LifecycleLock)
    if (-not $script:leaseHeld) {{ throw 'operation lease was released' }}
}}
function Assert-TicketboxExactFileAcl {{ param($Path,$Accounts,$OwnerAccount) }}
function Assert-TicketboxProtectedDirectoryAcl {{ param($Path,$FullControlAccounts,$OwnerAccount) }}
function Get-TicketboxInstallerStateDirectory {{ return $script:StateDirectory }}
function Get-TicketboxPathEntryKindNoFollow([string]$Path) {{
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
function Initialize-TicketboxExactTreeDeleteNativeMethods {{ }}
$script:ownerIdentity = [pscustomobject]@{{
    ProcessId = 4242
    StartedFileTimeHigh = [uint32]123
    StartedFileTimeLow = [uint32]456
}}
$script:coordinatorIdentity = [pscustomobject]@{{
    ProcessId = $PID
    StartedFileTimeHigh = [uint32]789
    StartedFileTimeLow = [uint32]1011
}}
function Get-TicketboxProcessIdentity {{
    param([int]$ProcessId)
    if ($ProcessId -eq 4242) {{ return $script:ownerIdentity }}
    if ($ProcessId -eq $PID) {{ return $script:coordinatorIdentity }}
    throw 'unexpected process identity request'
}}
function Test-TicketboxProcessIdentityEquals {{
    param($Left,$Right)
    return (
        [int]$Left.ProcessId -eq [int]$Right.ProcessId -and
        [uint32]$Left.StartedFileTimeHigh -eq
            [uint32]$Right.StartedFileTimeHigh -and
        [uint32]$Left.StartedFileTimeLow -eq
            [uint32]$Right.StartedFileTimeLow
    )
}}
function Read-TicketboxC07Authority([string]$DataRoot) {{
    return [pscustomobject]@{{
        Receipt = [pscustomobject]@{{
            stage = 'repair_required'
            previous_stage = 'ddl_started'
            operation_id = '12345678-1234-1234-1234-1234567890ab'
            failure_code = 'migration_process_failed'
        }}
        Descriptor = [pscustomobject]@{{ Payload = [pscustomobject]@{{
            source_alembic_revision = '20260722_0001'
            target_alembic_revision = '20260729_0001'
        }} }}
    }}
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path,$Text,$FullControlAccounts,$OwnerAccount,[switch]$ReplaceExisting)
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path,$Text,$encoding)
}}
function Remove-TicketboxProtectedUtf8Artifact {{
    param($Path,$FullControlAccounts,$OwnerAccount)
    [IO.File]::Delete($Path)
}}
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
public static class TicketboxExactTreeDeleteNativeMethods {{
    public static string[] GetDirectoryIdentity(string path) {{
        return new string[] {{ "0000000000000001", "00000000000000000000000000000001" }};
    }}
    public static string ReadExactUtf8File(string path, int maximumBytes) {{
        byte[] bytes = File.ReadAllBytes(path);
        if (bytes.Length < 1 || bytes.Length > maximumBytes) throw new IOException("size");
        return new UTF8Encoding(false, true).GetString(bytes);
    }}
}}
'@
. {_ps_literal(SUMMARY)}
[IO.File]::Delete((Join-Path `
    $script:StateDirectory `
    'c07-installer-failure-summary-v2.txt'))
[IO.File]::Delete((Join-Path `
    $script:StateDirectory `
    'c07-installer-lifecycle-exit-veto-v2.txt'))
$failure = [InvalidOperationException]::new('DATABASE_URL=secret password=secret business-row')
$failure.Data['TicketboxC07FailureCode'] = 'ignored_nonterminal_code'
$lifecycleLock = [pscustomobject]@{{
    ExternalOwnerIdentity = $script:ownerIdentity
}}
$result = Write-TicketboxC07InstallerFailureSummary `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId `
    -Failure $failure
$text = [IO.File]::ReadAllText($result.Path,(New-Object Text.UTF8Encoding($false,$true)))
$parsed = ConvertFrom-TicketboxC07InstallerFailureSummaryText $text
if ($parsed.lifecycle_stage -cne 'repair_required') {{ throw 'stage mismatch' }}
if ($parsed.finalization_attempt_id -cne $script:finalizationAttemptId) {{
    throw 'finalization attempt mismatch'
}}
if ($parsed.last_durable_stage -cne 'ddl_started') {{ throw 'origin mismatch' }}
if ($parsed.revision_state -cne 'unknown_source_or_target') {{ throw 'revision mismatch' }}
if ($parsed.recovery_point -cne 'source_restore_verified') {{ throw 'recovery mismatch' }}
if ($parsed.retry_policy -cne 'successor_forward_repair') {{ throw 'retry mismatch' }}
if ($parsed.no_return_crossed -cne 'true') {{ throw 'no-return mismatch' }}
if ($parsed.ddl_state -cne 'execution_started_commit_unknown') {{ throw 'ddl mismatch' }}
if ($parsed.data_state -cne 'revision_unknown_writer_stopped') {{ throw 'data mismatch' }}
if ($parsed.next_action -cne 'install_compatible_repair_build') {{ throw 'action mismatch' }}
if ($text -match 'secret|DATABASE_URL|password|business-row') {{ throw 'sensitive data leaked' }}
$tampered = $text.Replace('NO_RETURN_CROSSED=true','NO_RETURN_CROSSED=false')
$rejected = $false
try {{ [void](ConvertFrom-TicketboxC07InstallerFailureSummaryText $tampered) }}
catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'cross-field tamper was accepted' }}
$blockedFailure = [AggregateException]::new(
    'finalization failed',
    [Exception[]]@([InvalidOperationException]::new('payload lease close failed'))
)
$blockedFailure.Data['TicketboxInstallFinalizationFailed'] = $true
$blockedResult = Write-TicketboxC07InstallerFailureSummary `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId `
    -Failure $blockedFailure
$blockedText = [IO.File]::ReadAllText(
    $blockedResult.Path,
    (New-Object Text.UTF8Encoding($false,$true))
)
$blocked = ConvertFrom-TicketboxC07InstallerFailureSummaryText $blockedText
if ($blocked.retry_policy -cne 'blocked') {{ throw 'blocked retry mismatch' }}
if ($blocked.data_state -cne 'authority_or_writer_state_unverified') {{
    throw 'blocked data-state mismatch'
}}
if ($blocked.next_action -cne 'keep_services_stopped_contact_support') {{
    throw 'blocked action mismatch'
}}
$retryableResult = Write-TicketboxC07InstallerFailureSummary `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId `
    -Failure $failure
$retryableText = [IO.File]::ReadAllText(
    $retryableResult.Path,
    (New-Object Text.UTF8Encoding($false,$true))
)
$retryable = ConvertFrom-TicketboxC07InstallerFailureSummaryText $retryableText
if ($retryable.retry_policy -cne 'successor_forward_repair') {{
    throw 'retryable precondition was not restored'
}}
$vetoProjection = New-TicketboxC07InstallerLifecycleExitVeto `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId
$vetoPath = Join-Path `
    $script:StateDirectory `
    'c07-installer-lifecycle-exit-veto-v2.txt'
$pendingVetoText = [IO.File]::ReadAllText(
    $vetoPath,
    (New-Object Text.UTF8Encoding($false,$true))
)
$pendingVeto =
    ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText $pendingVetoText
if ($pendingVeto.state -cne 'lock_release_pending' -or
    $pendingVeto.operation_id -cne $retryable.operation_id -or
    $pendingVeto.finalization_attempt_id -cne
        $retryable.finalization_attempt_id) {{
    throw 'durable veto was not pending for the exact operation'
}}
$script:leaseHeld = $false
$completedVetoResult =
    Complete-TicketboxC07InstallerLifecycleExitVeto $vetoProjection
$completedVetoText = [IO.File]::ReadAllText(
    $completedVetoResult.Path,
    (New-Object Text.UTF8Encoding($false,$true))
)
$completedVeto =
    ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText $completedVetoText
if ($completedVeto.state -cne 'lock_release_completed') {{
    throw 'successful exact release did not clear the durable veto'
}}
$vetoReplayRejected = $false
try {{
    Complete-TicketboxC07InstallerLifecycleExitVeto `
        $vetoProjection | Out-Null
}}
catch {{ $vetoReplayRejected = $true }}
if (-not $vetoReplayRejected) {{
    throw 'lifecycle-exit veto completion replay was accepted'
}}
$script:leaseHeld = $true
$projection = New-TicketboxC07InstallerLifecycleExitFailureProjection `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId
$script:leaseHeld = $false
$projectedResult =
    Publish-TicketboxC07InstallerLifecycleExitFailureProjection $projection
$projectedText = [IO.File]::ReadAllText(
    $projectedResult.Path,
    (New-Object Text.UTF8Encoding($false,$true))
)
$projected = ConvertFrom-TicketboxC07InstallerFailureSummaryText $projectedText
if ($projected.retry_policy -cne 'blocked' -or
    $projected.next_action -cne 'keep_services_stopped_contact_support' -or
    $projected.data_state -cne 'authority_or_writer_state_unverified') {{
    throw 'lifecycle-exit projection did not replace retryable guidance'
}}
$replayRejected = $false
try {{
    Publish-TicketboxC07InstallerLifecycleExitFailureProjection `
        $projection | Out-Null
}}
catch {{ $replayRejected = $true }}
if (-not $replayRejected) {{ throw 'one-shot projection replay was accepted' }}
$forgedRejected = $false
try {{
    Publish-TicketboxC07InstallerLifecycleExitFailureProjection `
        ([pscustomobject]@{{ Nonce = ('0' * 64) }}) | Out-Null
}}
catch {{ $forgedRejected = $true }}
if (-not $forgedRejected) {{ throw 'forged projection was accepted' }}

# Mutation 1: a completed marker exists for an earlier finalization attempt of
# the same owner and operation, and its matching retryable summary also
# survives.  Both current summary publication and current marker preparation
# fail before overwrite, then lock release fails.  The Inno runtime attempt,
# not the stale pair's self-reported attempt, must prevent authorization.
$script:leaseHeld = $true
$script:finalizationAttemptId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
$retryableResult = Write-TicketboxC07InstallerFailureSummary `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId `
    -Failure $failure
$script:currentRuntimeAttemptId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
$script:finalizationAttemptId = $script:currentRuntimeAttemptId
$script:injectVetoWriteFailure = $true
function Write-TicketboxProtectedUtf8FileDurable {{
    param($Path,$Text,$FullControlAccounts,$OwnerAccount,[switch]$ReplaceExisting)
    if ($script:injectVetoWriteFailure -and
        [IO.Path]::GetFileName($Path) -ceq
            'c07-installer-lifecycle-exit-veto-v2.txt') {{
        throw 'injected durable-veto preparation failure'
    }}
    [IO.File]::WriteAllText(
        $Path,
        $Text,
        (New-Object Text.UTF8Encoding($false))
    )
}}
$vetoPreparationRejected = $false
try {{
    New-TicketboxC07InstallerLifecycleExitVeto `
        -DataRoot 'D:\\TicketboxData' `
        -InstallerState $script:StateDirectory `
        -LifecycleLock $lifecycleLock `
        -FinalizationAttemptId $script:finalizationAttemptId | Out-Null
}}
catch {{ $vetoPreparationRejected = $true }}
$script:leaseHeld = $false
$staleCompletedVetoText = [IO.File]::ReadAllText(
    $vetoPath,
    (New-Object Text.UTF8Encoding($false,$true))
)
$staleCompletedVeto =
    ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText `
        $staleCompletedVetoText
$staleRetryableText = [IO.File]::ReadAllText(
    $retryableResult.Path,
    (New-Object Text.UTF8Encoding($false,$true))
)
$staleRetryable =
    ConvertFrom-TicketboxC07InstallerFailureSummaryText `
        $staleRetryableText
if (-not $vetoPreparationRejected -or
    $staleCompletedVeto.state -cne 'lock_release_completed' -or
    $staleCompletedVeto.operation_id -cne $staleRetryable.operation_id -or
    $staleCompletedVeto.finalization_attempt_id -cne
        $staleRetryable.finalization_attempt_id -or
    $staleRetryable.finalization_attempt_id -ceq
        $script:currentRuntimeAttemptId) {{
    throw 'preparation-failure + release-failure mutation was not fail-closed'
}}

# Mutation 2: pending veto is durable, release fails, then the blocked-summary
# pre-invalidation step fails.  The stale retryable summary may survive, but
# pending veto has consumer precedence and therefore cannot authorize retry.
$script:leaseHeld = $true
$script:injectVetoWriteFailure = $false
$script:finalizationAttemptId = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
$retryableResult = Write-TicketboxC07InstallerFailureSummary `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId `
    -Failure $failure
$pendingVetoProjection = New-TicketboxC07InstallerLifecycleExitVeto `
    -DataRoot 'D:\\TicketboxData' `
    -InstallerState $script:StateDirectory `
    -LifecycleLock $lifecycleLock `
    -FinalizationAttemptId $script:finalizationAttemptId
$preInvalidationProjection =
    New-TicketboxC07InstallerLifecycleExitFailureProjection `
        -DataRoot 'D:\\TicketboxData' `
        -InstallerState $script:StateDirectory `
        -LifecycleLock $lifecycleLock `
        -FinalizationAttemptId $script:finalizationAttemptId
$script:leaseHeld = $false
function Remove-TicketboxProtectedUtf8Artifact {{
    param($Path,$FullControlAccounts,$OwnerAccount)
    if ([IO.Path]::GetFileName($Path) -ceq
        'c07-installer-failure-summary-v2.txt') {{
        throw 'injected stale-summary pre-invalidation failure'
    }}
    [IO.File]::Delete($Path)
}}
$preInvalidationRejected = $false
try {{
    Publish-TicketboxC07InstallerLifecycleExitFailureProjection `
        $preInvalidationProjection | Out-Null
}}
catch {{ $preInvalidationRejected = $true }}
$survivingRetryableText = [IO.File]::ReadAllText(
    $retryableResult.Path,
    (New-Object Text.UTF8Encoding($false,$true))
)
$survivingRetryable =
    ConvertFrom-TicketboxC07InstallerFailureSummaryText `
        $survivingRetryableText
$survivingVetoText = [IO.File]::ReadAllText(
    $vetoPath,
    (New-Object Text.UTF8Encoding($false,$true))
)
$survivingVeto =
    ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText `
        $survivingVetoText
if (-not $preInvalidationRejected -or
    $survivingRetryable.retry_policy -ceq 'blocked' -or
    $survivingVeto.state -cne 'lock_release_pending' -or
    $survivingVeto.operation_id -cne $survivingRetryable.operation_id -or
    $survivingVeto.finalization_attempt_id -cne
        $survivingRetryable.finalization_attempt_id) {{
    throw 'pre-invalidation-failure mutation lost durable veto precedence'
}}

# Mutation 3: current-attempt retryable summary + pending veto exist; payload
# close fails, blocked-summary rewrite also fails, but lock release succeeds.
# The completion guard must leave pending in place because finalization was not
# otherwise clean, preventing the surviving retryable summary from authorizing.
$simulatedLockExitFailed = $false
[Exception[]]$simulatedFinalizationFailures = @(
    [InvalidOperationException]::new(
        'payload close failed and blocked summary rewrite failed'
    )
)
if (-not $simulatedLockExitFailed -and
    $simulatedFinalizationFailures.Count -eq 0) {{
    Complete-TicketboxC07InstallerLifecycleExitVeto `
        $pendingVetoProjection | Out-Null
}}
$guardedVetoText = [IO.File]::ReadAllText(
    $vetoPath,
    (New-Object Text.UTF8Encoding($false,$true))
)
$guardedVeto =
    ConvertFrom-TicketboxC07InstallerLifecycleExitVetoText $guardedVetoText
if ($guardedVeto.state -cne 'lock_release_pending' -or
    $survivingRetryable.retry_policy -ceq 'blocked' -or
    $guardedVeto.finalization_attempt_id -cne
        $survivingRetryable.finalization_attempt_id) {{
    throw 'finalization failure incorrectly authorized stale retry guidance'
}}
[ordered]@{{
    edition = [string]$PSVersionTable.PSEdition
    stage = [string]$parsed.lifecycle_stage
    action = [string]$parsed.next_action
    blocked_action = [string]$blocked.next_action
    projected_action = [string]$projected.next_action
    bytes = [Text.Encoding]::UTF8.GetByteCount($text)
}} | ConvertTo-Json -Compress
""",
        encoding="utf-8-sig",
        newline="\r\n",
    )

    outputs: list[dict[str, object]] = []
    for engine in powershell_contract_engines():
        result = _run_ps(engine, harness)
        assert result.returncode == 0, result.stderr or result.stdout
        outputs.append(json.loads(result.stdout.strip().splitlines()[-1]))

    assert {str(output["edition"]) for output in outputs} == {"Desktop", "Core"}
    assert {str(output["stage"]) for output in outputs} == {"repair_required"}
    assert {str(output["action"]) for output in outputs} == {
        "install_compatible_repair_build"
    }
    assert {str(output["blocked_action"]) for output in outputs} == {
        "keep_services_stopped_contact_support"
    }
    assert {str(output["projected_action"]) for output in outputs} == {
        "keep_services_stopped_contact_support"
    }
    assert all(1 <= int(output["bytes"]) <= 4096 for output in outputs)
