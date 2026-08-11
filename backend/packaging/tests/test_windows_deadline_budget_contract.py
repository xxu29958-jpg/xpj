from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

PACKAGING = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGING / "windows_deadline_budget.ps1"


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
    -not $budget.Stopwatch.IsRunning) {{
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
if ($rejected -ne 5) {{ throw "invalid deadlines accepted: $rejected" }}
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
