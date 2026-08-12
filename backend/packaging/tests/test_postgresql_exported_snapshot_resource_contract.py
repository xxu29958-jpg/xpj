from __future__ import annotations

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


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_session_disposes_redirected_readers_without_handle_growth(
    tmp_path: Path,
) -> None:
    child = tmp_path / "snapshot_resource_child.py"
    child.write_text(
        "import sys\n"
        "print('TBX_READY', flush=True)\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    source = f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(DATABASE_SAFETY)}'
. '{ps_literal(ENTRYPOINT)}'
$retainedResources = [Collections.Generic.List[object]]::new()
$before = [Diagnostics.Process]::GetCurrentProcess().HandleCount
foreach ($iteration in 1..100) {{
    $process = Start-TicketboxPostgresqlExportedSnapshotSession `
        -PsqlPath '{ps_literal(sys.executable)}' `
        -ProtectedDatabaseUrl 'postgresql://unused' `
        -SqlCommands @('unused') `
        -ExecutablePrefixArguments @('{ps_literal(child)}')
    $resources = $process.PSObject.Properties[
        'TicketboxStreamResources'
    ].Value
    $readBudget = [Diagnostics.Stopwatch]::StartNew()
    $ready = Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $process `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(5)) `
        -BudgetStopwatch $readBudget -MaximumElapsedMilliseconds 5000
    if ($ready -cne 'TBX_READY') {{ throw 'resource child not ready' }}
    Stop-TicketboxPostgresqlExportedSnapshotSession $process 5000
    if (
        $resources.OutputReader.BaseStream.CanRead -or
        $resources.ErrorReader.BaseStream.CanRead -or
        -not $resources.ErrorDrainTask.IsCompleted
    ) {{ throw 'redirected process resource survived Stop' }}
    $retainedResources.Add($resources)
}}
$after = [Diagnostics.Process]::GetCurrentProcess().HandleCount
if (($after - $before) -gt 32) {{
    throw "redirected process handles grew without bound: $before -> $after"
}}

$pendingProbe = Start-TicketboxPostgresqlExportedSnapshotSession `
    -PsqlPath '{ps_literal(sys.executable)}' `
    -ProtectedDatabaseUrl 'postgresql://unused' `
    -SqlCommands @('unused') `
    -ExecutablePrefixArguments @('{ps_literal(child)}')
$pendingResources = $pendingProbe.TicketboxStreamResources
$originalDrain = $pendingResources.ErrorDrainTask
$pendingProbe.Kill()
[void]$pendingProbe.WaitForExit(5000)
$pendingResources.ErrorDrainTask = [Threading.Tasks.Task]::Delay(5000)
$primaryFailure = ''
try {{ Stop-TicketboxPostgresqlExportedSnapshotSession $pendingProbe 1000 }}
catch {{ $primaryFailure = $_.Exception.Message }}
if ($primaryFailure -notmatch 'stderr.*有界时间') {{
    throw "pending drain masked primary shutdown failure: $primaryFailure"
}}
if ($originalDrain.IsCompleted) {{ $originalDrain.Dispose() }}
"""
    run_harness(
        tmp_path,
        "exported-snapshot-resources",
        source,
        timeout=90,
    )
