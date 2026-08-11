from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from _postgresql_exported_snapshot_support import (
    DATABASE_SAFETY,
    ENTRYPOINT,
    INSTALLATION_SAFETY,
    ps_literal,
    run_harness,
)
from _powershell_contract import powershell_contract_engines


def _write_snapshot_child(path: Path) -> None:
    path.write_text(
        "import json, os, sys, time\n"
        "mode = sys.argv[1]\n"
        "if mode == 'argv':\n"
        "    sys.stderr.write('E' * 262144); sys.stderr.flush()\n"
        "    print(json.dumps(sys.argv[2:]), flush=True)\n"
        "    print('TBX_READY', flush=True)\n"
        "    sys.stdin.read()\n"
        "elif mode == 'silent':\n"
        "    time.sleep(30)\n"
        "elif mode == 'delayed':\n"
        "    time.sleep(0.6); print('LATE', flush=True)\n"
        "    sys.stdin.read()\n"
        "elif mode == 'exit':\n"
        "    sys.exit(0)\n"
        "elif mode == 'pid':\n"
        "    print(os.getpid(), flush=True)\n"
        "    sys.stdin.read()\n",
        encoding="utf-8",
    )


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_session_preserves_sql_actions_drains_and_stops(tmp_path: Path) -> None:
    child = tmp_path / "snapshot_child.py"
    _write_snapshot_child(child)
    sql_one = "SELECT 'one two';\nSELECT 1;"
    sql_two = 'SELECT \'"quoted"\';'
    protected_url = "postgresql://localhost/db?application_name=snapshot holder"
    expected = [
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--quiet",
        "--set",
        "ON_ERROR_STOP=1",
        "--dbname",
        protected_url,
        "--command",
        sql_one,
        "--command",
        sql_two,
        "--file",
        "-",
    ]
    expected_json = json.dumps(expected, ensure_ascii=False)
    expected_ps = ", ".join(f"'{ps_literal(item)}'" for item in expected)
    source = f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(DATABASE_SAFETY)}'
. '{ps_literal(ENTRYPOINT)}'
$process = $null
try {{
    $process = Start-TicketboxPostgresqlExportedSnapshotSession `
        -PsqlPath '{ps_literal(sys.executable)}' `
        -ProtectedDatabaseUrl '{ps_literal(protected_url)}' `
        -SqlCommands @('{ps_literal(sql_one)}', '{ps_literal(sql_two)}') `
        -ExecutablePrefixArguments @('{ps_literal(child)}', 'argv')
    $readBudget = [Diagnostics.Stopwatch]::StartNew()
    $argumentsJson = Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $process `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(10)) `
        -BudgetStopwatch $readBudget -MaximumElapsedMilliseconds 10000
    $decodedArguments = $argumentsJson | ConvertFrom-Json
    [string[]]$actual = @(
        foreach ($item in $decodedArguments) {{
            ([string]$item).Replace("`r`n", "`n")
        }}
    )
    [string[]]$expected = @(
        foreach ($item in @({expected_ps})) {{
            ([string]$item).Replace("`r`n", "`n")
        }}
    )
    if ($actual.Count -ne $expected.Count) {{
        throw ('psql argv count changed: ' + $argumentsJson)
    }}
    foreach ($index in 0..($expected.Count - 1)) {{
        if ([string]$actual[$index] -cne [string]$expected[$index]) {{
            throw (
                "psql argv[$index] changed: actual=<" + $actual[$index] +
                "> expected=<" + $expected[$index] + ">; raw=" +
                $argumentsJson + '; expected-json={ps_literal(expected_json)}'
            )
        }}
    }}
    $ready = Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $process `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(10)) `
        -BudgetStopwatch $readBudget -MaximumElapsedMilliseconds 10000
    if ($ready -cne 'TBX_READY') {{ throw 'stderr drain blocked stdout' }}
    Assert-TicketboxPostgresqlExportedSnapshotSessionAlive $process
    $pidValue = $process.Id
    Stop-TicketboxPostgresqlExportedSnapshotSession -Process $process `
        -WaitTimeoutMilliseconds 5000
    $process = $null
    $stillAlive = $true
    try {{ [void][Diagnostics.Process]::GetProcessById($pidValue) }}
    catch {{ $stillAlive = $false }}
    if ($stillAlive) {{ throw 'holder survived bounded shutdown' }}
}}
finally {{
    if ($null -ne $process) {{
        try {{ if (-not $process.HasExited) {{ $process.Kill() }} }} catch {{ }}
        $process.Dispose()
    }}
}}
"""
    run_harness(tmp_path, "exported-snapshot-session", source)


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_session_deadline_early_exit_and_cleanup_fail_closed(tmp_path: Path) -> None:
    child = tmp_path / "snapshot_child.py"
    _write_snapshot_child(child)
    source = f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(DATABASE_SAFETY)}'
. '{ps_literal(ENTRYPOINT)}'
function Start-Probe([string]$Mode) {{
    return Start-TicketboxPostgresqlExportedSnapshotSession `
        -PsqlPath '{ps_literal(sys.executable)}' `
        -ProtectedDatabaseUrl 'postgresql://unused' `
        -SqlCommands @('unused') `
        -ExecutablePrefixArguments @('{ps_literal(child)}', $Mode)
}}
$silent = Start-Probe 'silent'
$readClock = [Diagnostics.Stopwatch]::StartNew()
$deadlineRejected = $false
try {{
    Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $silent `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddMilliseconds(250)) `
        -BudgetStopwatch $readClock -MaximumElapsedMilliseconds 250 | Out-Null
}}
catch {{ $deadlineRejected = $true }}
finally {{ $readClock.Stop() }}
Stop-TicketboxPostgresqlExportedSnapshotSession $silent 5000
if (-not $deadlineRejected -or $readClock.ElapsedMilliseconds -gt 1500) {{
    throw 'silent holder escaped read deadline'
}}

$delayed = Start-Probe 'delayed'
$delayedClock = [Diagnostics.Stopwatch]::StartNew()
$delayedRejected = $false
try {{
    Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $delayed `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddMilliseconds(250)) `
        -BudgetStopwatch $delayedClock -MaximumElapsedMilliseconds 250 | Out-Null
}}
catch {{ $delayedRejected = $true }}
Stop-TicketboxPostgresqlExportedSnapshotSession $delayed 5000
if (-not $delayedRejected) {{
    throw 'late stdout crossed the monotonic read deadline'
}}

$exited = Start-Probe 'exit'
[void]$exited.WaitForExit(5000)
$exitRejected = $false
$exitReadClock = [Diagnostics.Stopwatch]::StartNew()
try {{
    Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $exited `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(1)) `
        -BudgetStopwatch $exitReadClock `
        -MaximumElapsedMilliseconds 1000 | Out-Null
}}
catch {{ $exitRejected = $true }}
$aliveRejected = $false
try {{ Assert-TicketboxPostgresqlExportedSnapshotSessionAlive $exited }}
catch {{ $aliveRejected = $true }}
Stop-TicketboxPostgresqlExportedSnapshotSession $exited 5000
if (-not $exitRejected -or -not $aliveRejected) {{
    throw 'exited holder was accepted'
}}

function Get-TicketboxPathEntryKindNoFollow {{ return 'ReparsePoint' }}
$psqlReparseRejected = $false
try {{ Start-Probe 'pid' | Out-Null }}
catch {{ $psqlReparseRejected = $true }}
if (-not $psqlReparseRejected) {{ throw 'reparse psql executable was accepted' }}
Remove-Item Function:Get-TicketboxPathEntryKindNoFollow
. '{ps_literal(INSTALLATION_SAFETY)}'

$pidProcess = Start-Probe 'pid'
$pidReadClock = [Diagnostics.Stopwatch]::StartNew()
$pidText = Read-TicketboxPostgresqlExportedSnapshotLine `
    -Process $pidProcess `
    -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(5)) `
    -BudgetStopwatch $pidReadClock -MaximumElapsedMilliseconds 5000
$pidValue = [int]$pidText
$stoppedBudget = [Diagnostics.Stopwatch]::StartNew()
$stoppedBudget.Stop()
$stoppedRejected = $false
try {{
    Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $pidProcess `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(5)) `
        -BudgetStopwatch $stoppedBudget `
        -MaximumElapsedMilliseconds 5000 | Out-Null
}}
catch {{ $stoppedRejected = $true }}
if (-not $stoppedRejected) {{ throw 'stopped read budget was accepted' }}

$expiredBudget = [Diagnostics.Stopwatch]::StartNew()
Start-Sleep -Milliseconds 20
$expiredClock = [Diagnostics.Stopwatch]::StartNew()
$expiredRejected = $false
try {{
    Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $pidProcess `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(5)) `
        -BudgetStopwatch $expiredBudget `
        -MaximumElapsedMilliseconds 1 | Out-Null
}}
catch {{ $expiredRejected = $true }}
$expiredClock.Stop()
if (-not $expiredRejected -or $expiredClock.ElapsedMilliseconds -gt 500) {{
    throw 'monotonic read budget was widened by wall time'
}}
Stop-TicketboxPostgresqlExportedSnapshotSession $pidProcess 5000
$aliveAfterStop = $true
try {{ [void][Diagnostics.Process]::GetProcessById($pidValue) }}
catch {{ $aliveAfterStop = $false }}
if ($aliveAfterStop) {{ throw 'Stop did not terminate holder PID' }}
"""
    run_harness(tmp_path, "exported-snapshot-failures", source)
