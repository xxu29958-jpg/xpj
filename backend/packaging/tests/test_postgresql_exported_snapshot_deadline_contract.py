from __future__ import annotations

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


def _deadline_evidence_harness() -> str:
    return f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(DATABASE_SAFETY)}'
. '{ps_literal(ENTRYPOINT)}'
$now = [DateTimeOffset]::ParseExact(
    '2030-01-01T00:00:00.0000000+00:00', 'o',
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::RoundtripKind
)
$deadline = $now.AddMilliseconds(120000).UtcDateTime.ToString('o')
$started = $now.AddMilliseconds(1000)
$expiry = $started.AddMilliseconds(60000)
$observed = $now.AddMilliseconds(2000)
$base = [pscustomobject][ordered]@{{
    absolute_deadline_utc = $deadline
    maximum_remaining_ceiling_ms = '120000'
    remaining_ms_before_statement = '119000'
    statement_timeout_configured_ceiling_ms = '30000'
    statement_timeout_applied_ms = '30000'
    transaction_timeout_configured_ceiling_ms = '60000'
    transaction_timeout_armed_ms = '60000'
    transaction_timeout_current_setting_ms = '60000'
    transaction_timeout_derived_upper_bound_expiry_utc =
        $expiry.UtcDateTime.ToString('yyyy-MM-dd"T"HH:mm:ss.ffffff"Z"')
    transaction_timeout_reconfigured_in_transaction = $false
    snapshot_exporter_preflight_observed_at_utc = $now.UtcDateTime.ToString('o')
    snapshot_exporter_transaction_started_utc = $started.UtcDateTime.ToString('o')
    snapshot_exporter_deadline_utc = $deadline
    timeout_observed_at_utc = $observed.UtcDateTime.ToString('o')
    idle_in_transaction_session_timeout_configured_ms = '60000'
    idle_in_transaction_session_timeout_effective_ms = '60000'
    lock_timeout_configured_ceiling_ms = '5000'
    lock_timeout_applied_ms = '5000'
    enforcement_kind = 'pre_begin_transaction_plus_per_statement_absolute_v1'
    observed_server_termination = 'not_observed_while_holder_live'
    holder_wait = 'psql_file_stdin_open_idle_transaction'
}}
$result = Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence `
    -Evidence $base -ExpectedAbsoluteDeadlineUtc $deadline `
    -MaximumRemainingCeilingMilliseconds 120000 -CurrentUtc $now
if (
    $result.TransactionDeadlineUtc -cne $expiry.UtcDateTime.ToString('o') -or
    $result.SnapshotExporterTransactionStartedUtc -cne $started.UtcDateTime.ToString('o')
) {{ throw 'normalized deadline result changed' }}
$idleDisabled = $base.PSObject.Copy()
$idleDisabled.idle_in_transaction_session_timeout_configured_ms = '0'
$idleDisabled.idle_in_transaction_session_timeout_effective_ms = '0'
Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence `
    -Evidence $idleDisabled -ExpectedAbsoluteDeadlineUtc $deadline `
    -MaximumRemainingCeilingMilliseconds 120000 -CurrentUtc $now | Out-Null

$cases = @(
    @('absolute deadline', {{ param($e) $e.absolute_deadline_utc = $now.AddMinutes(3).UtcDateTime.ToString('o') }}),
    @('snapshot deadline', {{ param($e) $e.snapshot_exporter_deadline_utc = $now.AddMinutes(3).UtcDateTime.ToString('o') }}),
    @('bool type', {{ param($e) $e.transaction_timeout_reconfigured_in_transaction = [int]0 }}),
    @('bool true', {{ param($e) $e.transaction_timeout_reconfigured_in_transaction = $true }}),
    @('maximum widened', {{ param($e) $e.maximum_remaining_ceiling_ms = '120001' }}),
    @('remaining zero', {{ param($e) $e.remaining_ms_before_statement = '0' }}),
    @('remaining widened', {{ param($e) $e.remaining_ms_before_statement = '120001' }}),
    @('armed versus maximum', {{ param($e) $e.maximum_remaining_ceiling_ms = '59000'; $e.remaining_ms_before_statement = '59000' }}),
    @('armed zero', {{ param($e) $e.transaction_timeout_armed_ms = '0' }}),
    @('current mismatch', {{ param($e) $e.transaction_timeout_current_setting_ms = '59999' }}),
    @('derived mismatch', {{ param($e) $e.transaction_timeout_derived_upper_bound_expiry_utc = $expiry.AddSeconds(1).UtcDateTime.ToString('o') }}),
    @('preflight ordering', {{ param($e) $e.snapshot_exporter_preflight_observed_at_utc = $started.AddMilliseconds(1).UtcDateTime.ToString('o') }}),
    @('observed ordering', {{ param($e) $e.timeout_observed_at_utc = $expiry.UtcDateTime.ToString('o') }}),
    @('transaction cap', {{ param($e) $e.transaction_timeout_configured_ceiling_ms = '59999' }}),
    @('statement zero', {{ param($e) $e.statement_timeout_applied_ms = '0' }}),
    @('statement cap', {{ param($e) $e.statement_timeout_applied_ms = '30001' }}),
    @('statement versus remaining', {{ param($e) $e.remaining_ms_before_statement = '25000' }}),
    @('idle mismatch', {{ param($e) $e.idle_in_transaction_session_timeout_effective_ms = '60001' }}),
    @('idle holder lifetime', {{ param($e) $e.idle_in_transaction_session_timeout_configured_ms = '59000'; $e.idle_in_transaction_session_timeout_effective_ms = '59000' }}),
    @('lock zero', {{ param($e) $e.lock_timeout_applied_ms = '0' }}),
    @('lock global cap', {{ param($e) $e.lock_timeout_configured_ceiling_ms = '0'; $e.lock_timeout_applied_ms = '5001' }}),
    @('lock configured cap', {{ param($e) $e.lock_timeout_configured_ceiling_ms = '4999' }}),
    @('lock versus remaining', {{ param($e) $e.remaining_ms_before_statement = '4000'; $e.statement_timeout_applied_ms = '3000' }}),
    @('enforcement kind', {{ param($e) $e.enforcement_kind = 'widened' }}),
    @('server termination', {{ param($e) $e.observed_server_termination = 'ignored' }}),
    @('holder wait', {{ param($e) $e.holder_wait = 'idle' }})
)
foreach ($case in $cases) {{
    $candidate = $base.PSObject.Copy()
    & $case[1] $candidate
    $rejected = $false
    try {{
        Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence `
            -Evidence $candidate -ExpectedAbsoluteDeadlineUtc $deadline `
            -MaximumRemainingCeilingMilliseconds 120000 -CurrentUtc $now | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "bad evidence accepted: $($case[0])" }}
}}
$expiredRejected = $false
try {{
    Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence `
        -Evidence $base -ExpectedAbsoluteDeadlineUtc $deadline `
        -MaximumRemainingCeilingMilliseconds 120000 `
        -CurrentUtc $expiry | Out-Null
}}
catch {{ $expiredRejected = $true }}
if (-not $expiredRejected) {{ throw 'expired transaction evidence accepted' }}
$base | Add-Member -NotePropertyName unknown_field -NotePropertyValue 'x'
$unknownRejected = $false
try {{
    Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence `
        -Evidence $base -ExpectedAbsoluteDeadlineUtc $deadline `
        -MaximumRemainingCeilingMilliseconds 120000 -CurrentUtc $now | Out-Null
}}
catch {{ $unknownRejected = $true }}
if (-not $unknownRejected) {{ throw 'unknown deadline field accepted' }}
"""


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_deadline_evidence_rejects_each_independent_widening(tmp_path: Path) -> None:
    run_harness(
        tmp_path,
        "exported-snapshot-deadline",
        _deadline_evidence_harness(),
    )


@pytest.mark.skipif(
    not powershell_contract_engines(), reason="PowerShell contract"
)
def test_deadline_numbers_are_canonical_uint64(tmp_path: Path) -> None:
    source = f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(DATABASE_SAFETY)}'
. '{ps_literal(ENTRYPOINT)}'
foreach ($value in @('00', '060000', '-1', ' 1', '1 ', '1e3', '18446744073709551616')) {{
    $rejected = $false
    try {{
        ConvertTo-TicketboxPostgresqlExportedSnapshotUnsignedInt64 `
            -Value $value -Label 'probe' | Out-Null
    }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "non-canonical uint64 accepted: $value" }}
}}
if ((ConvertTo-TicketboxPostgresqlExportedSnapshotUnsignedInt64 0 'zero') -ne 0) {{
    throw 'canonical zero changed'
}}
"""
    run_harness(tmp_path, "exported-snapshot-uint64", source)
