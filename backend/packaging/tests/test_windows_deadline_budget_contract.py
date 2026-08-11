from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGING / "windows_deadline_budget.ps1"
C07_POLICY = PACKAGING / "windows_c07_deadline_policy.ps1"
C07_HEARTBEAT = PACKAGING / "windows_c07_heartbeat_authority.ps1"
C07_HEARTBEAT_HELPER = PACKAGING / "windows_c07_heartbeat_helper.ps1"
C07_LIFECYCLE = PACKAGING / "windows_c07_lifecycle.ps1"
C07_RECOVERY = PACKAGING / "windows_c07_recovery_generation.ps1"


def _literal(path: Path) -> str:
    return str(path).replace("'", "''")


def _run(engine: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def test_deadline_budget_is_focused_bom_safe_and_c07_free() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")

    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")
    assert source.startswith("#Requires -Version 5.1")
    assert len(source.splitlines()) <= 220
    assert "c07" not in source.lower()
    for command in (
        "Get-TicketboxWindowsBootIdentity",
        "Measure-TicketboxWindowsPersistedDeadline",
        "New-TicketboxWindowsDeadlineBudget",
        "Get-TicketboxWindowsDeadlineRemainingMilliseconds",
        "Get-TicketboxBoundedDeadlineUtc",
    ):
        assert f"function {command}" in source
    for forbidden in (
        "Set-Service",
        "Start-Service",
        "Stop-Service",
        "Set-ItemProperty",
        "New-Item",
        "Remove-Item",
        "Invoke-Sqlcmd",
        "psql.exe",
    ):
        assert forbidden not in source


def test_c07_consumers_use_one_explicit_generic_deadline_path() -> None:
    heartbeat = C07_HEARTBEAT.read_text(encoding="utf-8-sig")
    policy = C07_POLICY.read_text(encoding="utf-8-sig")
    heartbeat_helper = C07_HEARTBEAT_HELPER.read_text(encoding="utf-8-sig")
    lifecycle = C07_LIFECYCLE.read_text(encoding="utf-8-sig")
    recovery = C07_RECOVERY.read_text(encoding="utf-8-sig")
    production = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in PACKAGING.rglob("*.ps1")
        if "tests" not in path.parts
    )

    assert '"windows_deadline_budget.ps1"' in heartbeat
    active_heartbeat = "\n".join(
        line for line in heartbeat.splitlines() if not line.lstrip().startswith("#")
    )
    active_heartbeat_helper = "\n".join(
        line
        for line in heartbeat_helper.splitlines()
        if not line.lstrip().startswith("#")
    )
    active_lifecycle = "\n".join(
        line for line in lifecycle.splitlines() if not line.lstrip().startswith("#")
    )
    active_recovery = "\n".join(
        line for line in recovery.splitlines() if not line.lstrip().startswith("#")
    )
    assert ". $deadlineDependencyPath" in active_heartbeat
    assert "Assert-NoTicketboxAncestorReparsePoints $deadlineDependencyPath" in (
        active_heartbeat
    )
    assert "Get-TicketboxPathEntryKindNoFollow $deadlineDependencyPath" in (
        active_heartbeat
    )
    assert (
        active_heartbeat_helper.index('"windows_deadline_budget.ps1"')
        < active_heartbeat_helper.index('"windows_c07_deadline_policy.ps1"')
        < active_heartbeat_helper.index('"windows_c07_heartbeat_authority.ps1"')
    )
    assert C07_POLICY.read_bytes().startswith(b"\xef\xbb\xbf")
    assert len(policy.splitlines()) <= 80
    assert "function Assert-TicketboxC07MaintenanceBudgetBinding" in policy
    assert (
        "function Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds"
        in policy
    )
    assert "New-TicketboxWindowsDeadlineBudget" in lifecycle
    assert "Measure-TicketboxWindowsPersistedDeadline" in lifecycle
    assert "Get-TicketboxBoundedDeadlineUtc" in lifecycle
    assert '"Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds",' in recovery
    assert "Get-TicketboxWindowsDeadlineRemainingMilliseconds" in policy
    assert active_heartbeat.count(
        "Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds"
    ) == 1
    assert active_lifecycle.count(
        "Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds"
    ) == 4
    assert active_recovery.count(
        "Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds"
    ) == 12
    for label in (
        "C07 recovery boundary",
        "C07 native maintenance heartbeat operation",
        "C07 reused source recovery money facts",
        "C07 source generation money facts",
        "C07 recovery asset copy",
        "C07 isolated forward replay",
        "C07 reused target recovery live evidence",
        "C07 target generation evidence",
        "C07 target recovery asset copy",
        "C07 target restore semantic evidence",
    ):
        assert f'-Label "{label}"' in active_recovery

    # C07 keeps operation/attempt binding policy while the generic layer owns
    # only boot observation and deadline arithmetic.
    for binding in (
        "OperationId = [string]$Authority.Receipt.operation_id",
        "AttemptId = [string]$attempt.Payload.attempt_id",
        "AttemptSha256 = [string]$attempt.PayloadSha256",
    ):
        assert binding in lifecycle

    for retired in (
        "Get-TicketboxC07BootIdentity",
        "Get-TicketboxC07RemainingMaintenanceMilliseconds",
        "Get-TicketboxC07MaintenanceAttemptRemainingMilliseconds",
        "Get-TicketboxC07BoundedMigratorValidUntilUtc",
    ):
        assert retired not in production


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_deadline_loader_rejects_no_follow_kind_before_execution(
    engine: str,
    tmp_path: Path,
) -> None:
    authority = tmp_path / "windows_c07_heartbeat_authority.ps1"
    deadline = tmp_path / "windows_deadline_budget.ps1"
    marker = tmp_path / "untrusted-loader-executed.txt"
    authority.write_bytes(C07_HEARTBEAT.read_bytes())
    deadline.write_text(
        f"Set-Content -LiteralPath '{_literal(marker)}' -Value executed\n",
        encoding="utf-8-sig",
    )
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ($Path -ceq '{_literal(deadline)}') {{ return 'ReparsePoint' }}
    return 'File'
}}
$rejected = $false
try {{
    . '{_literal(authority)}'
}} catch {{
    if ($_.Exception.Message -cnotmatch 'trusted ordinary file') {{ throw }}
    $rejected = $true
}}
if (-not $rejected) {{ throw 'no-follow loader kind was accepted' }}
if (Test-Path -LiteralPath '{_literal(marker)}') {{
    throw 'untrusted deadline adapter executed before rejection'
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_c07_deadline_policy_rejects_unbound_or_malformed_budget(
    engine: str,
) -> None:
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_literal(C07_HEARTBEAT)}' -TicketboxC07DependencyProfile durable_heartbeat
$deadline = [DateTime]::UtcNow.AddMinutes(1)
function New-TestBudget {{
    param(
        [string]$OperationId = '123e4567-e89b-42d3-a456-426614174000',
        [string]$AttemptId = '123e4567-e89b-42d3-a456-426614174001',
        [int64]$AttemptSequence = 1,
        [string]$AttemptSha256 = ('A' * 64)
    )
    return [pscustomobject]@{{
        OperationId = $OperationId
        AttemptId = $AttemptId
        AttemptSequence = $AttemptSequence
        AttemptSha256 = $AttemptSha256
        DeadlineUtc = $deadline
        RemainingAtStartMilliseconds = [double]60000
        Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    }}
}}
$valid = New-TestBudget
$remaining = Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds `
    -Budget $valid -MaximumMilliseconds 5000
if ($remaining -lt 1000 -or $remaining -gt 5000) {{
    throw "valid authority-bound budget returned invalid remainder: $remaining"
}}
$invalid = @(
    [pscustomobject]@{{
        DeadlineUtc = $deadline
        RemainingAtStartMilliseconds = [double]60000
        Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    }},
    (New-TestBudget -OperationId ''),
    (New-TestBudget -AttemptId ''),
    (New-TestBudget -AttemptSequence 0),
    (New-TestBudget -AttemptSha256 ('a' * 64))
)
$rejected = 0
foreach ($candidate in $invalid) {{
    try {{
        Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds `
            -Budget $candidate -MaximumMilliseconds 5000 | Out-Null
    }} catch {{ $rejected++ }}
    if ($null -ne $candidate.Stopwatch) {{ $candidate.Stopwatch.Stop() }}
}}
$valid.Stopwatch.Stop()
if ($rejected -ne $invalid.Count) {{
    throw "malformed C07 budget accepted: $rejected/$($invalid.Count) rejected"
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_deadline_budget_uses_tick_durable_wall_process_and_action_ceilings(
    engine: str,
) -> None:
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(SCRIPT)}'
$now = [DateTime]::Parse(
    '2030-01-01T00:00:00.0000000Z',
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::RoundtripKind
)

$observed = Measure-TicketboxWindowsPersistedDeadline `
    -DeadlineUtc $now.AddSeconds(20) `
    -WindowMilliseconds 10000 `
    -StartedTickCount64 1000 `
    -StartedBootIdentity 'boot-a' `
    -CurrentUtc $now `
    -CurrentTickCount64 3500 `
    -CurrentBootIdentity 'boot-a'
if (-not $observed.Continuous -or
    $observed.FailureCode -cne '' -or
    $observed.RemainingMilliseconds -ne 7500) {{
    throw 'persisted observation did not choose the tick-count ceiling'
}}
$wallObserved = Measure-TicketboxWindowsPersistedDeadline `
    -DeadlineUtc $now.AddSeconds(4) `
    -WindowMilliseconds 10000 `
    -StartedTickCount64 1000 `
    -StartedBootIdentity 'boot-a' `
    -CurrentUtc $now `
    -CurrentTickCount64 3000 `
    -CurrentBootIdentity 'boot-a'
if (-not $wallObserved.Continuous -or
    $wallObserved.RemainingMilliseconds -ne 4000) {{
    throw 'persisted observation did not choose the durable UTC ceiling'
}}

$budget = New-TicketboxWindowsDeadlineBudget `
    -DeadlineUtc $now.AddSeconds(20) `
    -WindowMilliseconds 10000 `
    -DurableRemainingCeilingMilliseconds 6000 `
    -StartedTickCount64 1000 `
    -StartedBootIdentity 'boot-a' `
    -CurrentUtc $now `
    -CurrentTickCount64 3500 `
    -CurrentBootIdentity 'boot-a'
if ($budget.RemainingAtStartMilliseconds -ne 6000 -or
    $budget.DeadlineUtc.Ticks -ne $now.AddSeconds(20).Ticks -or
    -not $budget.Stopwatch.IsRunning -or
    $budget.Stopwatch -isnot [Diagnostics.Stopwatch]) {{
    throw 'budget did not choose the durable remaining ceiling'
}}

$processBudget = [pscustomobject]@{{
    DeadlineUtc = $now.AddSeconds(20)
    RemainingAtStartMilliseconds = [double]8000
    Stopwatch = [pscustomobject]@{{
        IsRunning = $true
        Elapsed = [TimeSpan]::FromMilliseconds(2500)
    }}
}}
$processRemaining = Get-TicketboxWindowsDeadlineRemainingMilliseconds `
    -Budget $processBudget `
    -CurrentUtc $now `
    -MaximumMilliseconds 7000 `
    -MinimumMilliseconds 1000
if ($processRemaining -ne 5500) {{
    throw "process-local monotonic ceiling was ignored: $processRemaining"
}}
$actionRemaining = Get-TicketboxWindowsDeadlineRemainingMilliseconds `
    -Budget $processBudget `
    -CurrentUtc $now `
    -MaximumMilliseconds 3000 `
    -MinimumMilliseconds 1000
if ($actionRemaining -ne 3000) {{
    throw "per-action maximum was ignored: $actionRemaining"
}}

$wallBudget = [pscustomobject]@{{
    DeadlineUtc = $now.AddMilliseconds(5000)
    RemainingAtStartMilliseconds = [double]8000
    Stopwatch = [pscustomobject]@{{
        IsRunning = $true
        Elapsed = [TimeSpan]::FromMilliseconds(1000)
    }}
}}
$wallRemaining = Get-TicketboxWindowsDeadlineRemainingMilliseconds `
    -Budget $wallBudget `
    -CurrentUtc $now `
    -MaximumMilliseconds 7000 `
    -MinimumMilliseconds 1000
if ($wallRemaining -ne 5000) {{
    throw "durable UTC ceiling was ignored: $wallRemaining"
}}

$requestedBound = Get-TicketboxBoundedDeadlineUtc `
    -RequestedDeadlineUtc $now.AddSeconds(4) `
    -CeilingDeadlineUtc $now.AddSeconds(7) `
    -CurrentUtc $now
if ($requestedBound.Ticks -ne $now.AddSeconds(4).Ticks) {{
    throw 'requested deadline was not retained below the operation ceiling'
}}
$ceilingBound = Get-TicketboxBoundedDeadlineUtc `
    -RequestedDeadlineUtc $now.AddSeconds(10) `
    -CeilingDeadlineUtc $now.AddSeconds(7) `
    -CurrentUtc $now
if ($ceilingBound.Ticks -ne $now.AddSeconds(7).Ticks) {{
    throw 'requested deadline exceeded the operation ceiling'
}}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_deadline_budget_fails_closed_on_discontinuity_expiry_and_bad_shape(
    engine: str,
) -> None:
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(SCRIPT)}'
$now = [DateTime]::Parse(
    '2030-01-01T00:00:00.0000000Z',
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::RoundtripKind
)
$reboot = Measure-TicketboxWindowsPersistedDeadline `
    -DeadlineUtc $now.AddMinutes(20) `
    -WindowMilliseconds 1200000 `
    -StartedTickCount64 1000 `
    -StartedBootIdentity 'boot-a' `
    -CurrentUtc $now `
    -CurrentTickCount64 1200 `
    -CurrentBootIdentity 'boot-b'
if ($reboot.Continuous -or $reboot.RemainingMilliseconds -ne 0 -or
    $reboot.FailureCode -cne 'boot_session_changed') {{
    throw 'boot discontinuity was not classified fail-closed'
}}
$rollback = Measure-TicketboxWindowsPersistedDeadline `
    -DeadlineUtc $now.AddMinutes(20) `
    -WindowMilliseconds 1200000 `
    -StartedTickCount64 2000 `
    -StartedBootIdentity 'boot-a' `
    -CurrentUtc $now `
    -CurrentTickCount64 1200 `
    -CurrentBootIdentity 'boot-a'
if ($rollback.Continuous -or $rollback.FailureCode -cne 'tick_count_rollback') {{
    throw 'tick rollback was not classified fail-closed'
}}
$negativeTick = Measure-TicketboxWindowsPersistedDeadline `
    -DeadlineUtc $now.AddMinutes(20) `
    -WindowMilliseconds 1200000 `
    -StartedTickCount64 -1 `
    -StartedBootIdentity 'boot-a' `
    -CurrentUtc $now `
    -CurrentTickCount64 1200 `
    -CurrentBootIdentity 'boot-a'
if ($negativeTick.Continuous -or
    $negativeTick.FailureCode -cne 'tick_count_rollback') {{
    throw 'negative persisted tick was not classified fail-closed'
}}

$rejected = 0
try {{
    New-TicketboxWindowsDeadlineBudget `
        -DeadlineUtc $now.AddMinutes(20) `
        -WindowMilliseconds 1200000 `
        -DurableRemainingCeilingMilliseconds 500 `
        -StartedTickCount64 1000 `
        -StartedBootIdentity 'boot-a' `
        -CurrentUtc $now `
        -CurrentTickCount64 1200 `
        -CurrentBootIdentity 'boot-a' | Out-Null
}} catch {{ $rejected++ }}
try {{
    New-TicketboxWindowsDeadlineBudget `
        -DeadlineUtc $now.AddSeconds(-1) `
        -WindowMilliseconds 1200000 `
        -DurableRemainingCeilingMilliseconds 60000 `
        -StartedTickCount64 1000 `
        -StartedBootIdentity 'boot-a' `
        -CurrentUtc $now `
        -CurrentTickCount64 1200 `
        -CurrentBootIdentity 'boot-a' | Out-Null
}} catch {{ $rejected++ }}
try {{
    Get-TicketboxWindowsDeadlineRemainingMilliseconds `
        -Budget ([pscustomobject]@{{
            DeadlineUtc = $now.AddSeconds(20)
            RemainingAtStartMilliseconds = [double]8000
            Stopwatch = [pscustomobject]@{{
                IsRunning = $false
                Elapsed = [TimeSpan]::Zero
            }}
        }}) `
        -CurrentUtc $now | Out-Null
}} catch {{ $rejected++ }}
try {{
    Get-TicketboxWindowsDeadlineRemainingMilliseconds `
        -Budget ([pscustomobject]@{{
            DeadlineUtc = $now.AddSeconds(20)
            RemainingAtStartMilliseconds = [double]8000
            Stopwatch = [pscustomobject]@{{
                IsRunning = $true
                Elapsed = [TimeSpan]::FromMilliseconds(7500)
            }}
        }}) `
        -CurrentUtc $now `
        -MinimumMilliseconds 1000 | Out-Null
}} catch {{ $rejected++ }}
try {{
    Get-TicketboxBoundedDeadlineUtc `
        -RequestedDeadlineUtc ([DateTime]::new(2030, 1, 1)) `
        -CeilingDeadlineUtc $now.AddSeconds(7) `
        -CurrentUtc $now | Out-Null
}} catch {{ $rejected++ }}
try {{
    Get-TicketboxBoundedDeadlineUtc `
        -RequestedDeadlineUtc $now.AddSeconds(1) `
        -CeilingDeadlineUtc $now.AddSeconds(-1) `
        -CurrentUtc $now | Out-Null
}} catch {{ $rejected++ }}
try {{
    Get-TicketboxBoundedDeadlineUtc `
        -RequestedDeadlineUtc $now.AddSeconds(-1) `
        -CeilingDeadlineUtc $now.AddSeconds(7) `
        -CurrentUtc $now | Out-Null
}} catch {{ $rejected++ }}
if ($rejected -ne 7) {{ throw "invalid deadlines accepted: $rejected" }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("engine", powershell_contract_engines())
def test_boot_identity_observation_is_exact_and_missing_value_fails_closed(
    engine: str,
) -> None:
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{_literal(SCRIPT)}'
function Get-CimInstance {{
    param($ClassName, $Property, $ErrorAction)
    if ($ClassName -cne 'Win32_OperatingSystem' -or
        $Property -cne 'LastBootUpTime') {{
        throw 'unexpected CIM query shape'
    }}
    return [pscustomobject]@{{
        LastBootUpTime = [DateTime]::Parse(
            '2030-01-01T08:00:00.0000000+08:00',
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }}
}}
$identity = Get-TicketboxWindowsBootIdentity
if ($identity -cne '2030-01-01T00:00:00.0000000Z') {{
    throw "boot identity was not canonical UTC: $identity"
}}
function Get-CimInstance {{
    param($ClassName, $Property, $ErrorAction)
    return [pscustomobject]@{{ LastBootUpTime = $null }}
}}
$rejected = $false
try {{ Get-TicketboxWindowsBootIdentity | Out-Null }} catch {{ $rejected = $true }}
if (-not $rejected) {{ throw 'missing boot identity was accepted' }}
"""
    result = _run(engine, script)
    assert result.returncode == 0, result.stderr or result.stdout
