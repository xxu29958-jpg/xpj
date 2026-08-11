from __future__ import annotations

from pathlib import Path

import pytest
from _postgresql_exported_snapshot_support import (
    C07_RECOVERY,
    INSTALLATION_SAFETY,
    ps_literal,
    run_harness,
)
from _powershell_contract import powershell_contract_engines


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_c07_opener_passes_split_sql_and_cleans_up_failed_read(
    tmp_path: Path,
) -> None:
    recovery = C07_RECOVERY.read_text(encoding="utf-8-sig")
    snapshot_sql = recovery[
        recovery.index("function Get-TicketboxC07RecoverySnapshotSql") :
        recovery.index("function Read-TicketboxC07RecoverySnapshotProcess")
    ]
    assert "SELECT 'TBX_READY';" in snapshot_sql
    assert "SELECT pg_sleep_until(" not in snapshot_sql
    assert "Get-TicketboxC07RecoverySnapshotHoldSql" not in recovery

    source = f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(C07_RECOVERY)}'

$script:startCalls = 0
$script:stopCalls = 0
$script:failRead = $false
$script:failStop = $false
$script:capturedCommands = $null
function Get-TicketboxC07RecoverySnapshotLifetime {{
    return [pscustomobject]@{{
        MaintenanceDeadlineUtc =
            [DateTimeOffset]::UtcNow.AddMinutes(5).UtcDateTime.ToString('o')
        MaximumRemainingCeilingMilliseconds = 120000
    }}
}}
function Invoke-TicketboxC07WithPlainSecret {{
    param([Security.SecureString]$Secret, [scriptblock]$Action)
    return & $Action 'plain-secret'
}}
function Invoke-TicketboxWithPgPassFile {{
    param([string]$DatabaseUrl, [string]$Password, [scriptblock]$Action)
    if ($DatabaseUrl -cne 'postgresql://authority' -or
        $Password -cne 'plain-secret') {{
        throw 'authority input changed'
    }}
    return & $Action 'postgresql://protected'
}}
function Get-TicketboxC07RecoverySnapshotPreflightSql {{
    param(
        [string]$OperationId,
        [string]$MaintenanceDeadlineUtc,
        [int]$MaximumRemainingCeilingMilliseconds
    )
    return "PREFLIGHT:$OperationId"
}}
function Get-TicketboxC07RecoverySnapshotSql {{
    param(
        [string]$OperationId,
        [string]$MaintenanceDeadlineUtc,
        [int]$MaximumRemainingCeilingMilliseconds
    )
    return "SNAPSHOT:$OperationId"
}}
function Start-TicketboxPostgresqlExportedSnapshotSession {{
    param(
        [string]$PsqlPath,
        [string]$ProtectedDatabaseUrl,
        [string[]]$SqlCommands
    )
    $script:startCalls++
    if ($PsqlPath -cne 'C:\\trusted\\psql.exe' -or
        $ProtectedDatabaseUrl -cne 'postgresql://protected') {{
        throw 'generic session authority input changed'
    }}
    $script:capturedCommands = @($SqlCommands)
    return [pscustomobject]@{{ Id = 41 }}
}}
function Read-TicketboxC07RecoverySnapshotProcess {{
    param(
        [object]$Process,
        [string]$ExpectedMaintenanceDeadlineUtc,
        [int]$MaximumRemainingCeilingMilliseconds,
        [int]$TimeoutMilliseconds
    )
    if ($script:failRead) {{ throw 'injected read failure' }}
    return [pscustomobject]@{{ Process = $Process }}
}}
function Stop-TicketboxPostgresqlExportedSnapshotSession {{
    param([object]$Process, [int]$WaitTimeoutMilliseconds)
    $script:stopCalls++
    if ($script:failStop) {{ throw 'injected stop failure' }}
}}
function Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds {{
    return 10000
}}

$context = [pscustomobject]@{{
    DatabaseUrl = 'postgresql://authority'
    DatabaseAuthority = [pscustomobject]@{{
        PsqlPath = 'C:\\trusted\\psql.exe'
    }}
    Authority = [pscustomobject]@{{ Receipt = [pscustomobject]@{{
        operation_id = '123e4567-e89b-42d3-a456-426614174099'
    }} }}
}}
$secret = [Security.SecureString]::new()
foreach ($index in 1..16) {{ $secret.AppendChar('X') }}
$secret.MakeReadOnly()
$opened = Open-TicketboxC07RecoverySnapshot $context $secret
if (
    $script:startCalls -ne 1 -or $script:stopCalls -ne 0 -or
    $opened.Process.Id -ne 41 -or
    [string]::Join('|', $script:capturedCommands) -cne
        'PREFLIGHT:123e4567-e89b-42d3-a456-426614174099|' +
        'SNAPSHOT:123e4567-e89b-42d3-a456-426614174099'
) {{ throw 'C07 opener did not pass the split SQL sequence' }}

$script:failRead = $true
$rejected = $false
try {{ Open-TicketboxC07RecoverySnapshot $context $secret | Out-Null }}
catch {{
    if ($_.Exception.Message -notmatch 'injected read failure') {{ throw }}
    $rejected = $true
}}
if (-not $rejected -or $script:startCalls -ne 2 -or
    $script:stopCalls -ne 1) {{
    throw 'C07 opener did not clean up one failed startup'
}}

$script:failStop = $true
$combinedFailure = ''
try {{ Open-TicketboxC07RecoverySnapshot $context $secret | Out-Null }}
catch {{ $combinedFailure = $_.Exception.Message }}
if (
    $script:startCalls -ne 3 -or $script:stopCalls -ne 2 -or
    $combinedFailure -notmatch 'injected read failure' -or
    $combinedFailure -notmatch 'injected stop failure'
) {{ throw 'C07 opener did not preserve read plus cleanup failure' }}
"""
    run_harness(tmp_path, "c07-exported-snapshot-adapter", source)
