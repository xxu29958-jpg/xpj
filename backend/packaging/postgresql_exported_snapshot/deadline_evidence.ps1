#Requires -Version 5.1

function Assert-TicketboxPostgresqlExportedSnapshotDeadlineEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Evidence,
        [Parameter(Mandatory = $true)][string]$ExpectedAbsoluteDeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 2147483647)]
        [int]$MaximumRemainingCeilingMilliseconds,
        [DateTimeOffset]$CurrentUtc = [DateTimeOffset]::UtcNow
    )

    $fields = @(
        "absolute_deadline_utc",
        "maximum_remaining_ceiling_ms",
        "remaining_ms_before_statement",
        "statement_timeout_configured_ceiling_ms",
        "statement_timeout_applied_ms",
        "transaction_timeout_configured_ceiling_ms",
        "transaction_timeout_armed_ms",
        "transaction_timeout_current_setting_ms",
        "transaction_timeout_derived_upper_bound_expiry_utc",
        "transaction_timeout_reconfigured_in_transaction",
        "snapshot_exporter_preflight_observed_at_utc",
        "snapshot_exporter_transaction_started_utc",
        "snapshot_exporter_deadline_utc",
        "timeout_observed_at_utc",
        "idle_in_transaction_session_timeout_configured_ms",
        "idle_in_transaction_session_timeout_effective_ms",
        "lock_timeout_configured_ceiling_ms",
        "lock_timeout_applied_ms",
        "enforcement_kind",
        "observed_server_termination",
        "holder_wait"
    )
    Assert-TicketboxPostgresqlExportedSnapshotExactProperties `
        $Evidence $fields "PostgreSQL exported-snapshot deadline evidence"
    $expectedDeadline = ConvertTo-TicketboxPostgresqlExportedSnapshotUtc `
        $ExpectedAbsoluteDeadlineUtc "expected absolute deadline"
    $timestamps = @{}
    foreach ($field in @(
        "snapshot_exporter_preflight_observed_at_utc",
        "snapshot_exporter_transaction_started_utc",
        "transaction_timeout_derived_upper_bound_expiry_utc",
        "timeout_observed_at_utc"
    )) {
        $timestamps[$field] = ConvertTo-TicketboxPostgresqlExportedSnapshotUtc `
            -Value ([string]$Evidence.$field) `
            -Label $field
    }
    $numbers = @{}
    foreach ($field in @(
        "maximum_remaining_ceiling_ms",
        "remaining_ms_before_statement",
        "statement_timeout_configured_ceiling_ms",
        "statement_timeout_applied_ms",
        "transaction_timeout_configured_ceiling_ms",
        "transaction_timeout_armed_ms",
        "transaction_timeout_current_setting_ms",
        "idle_in_transaction_session_timeout_configured_ms",
        "idle_in_transaction_session_timeout_effective_ms",
        "lock_timeout_configured_ceiling_ms",
        "lock_timeout_applied_ms"
    )) {
        $numbers[$field] =
            ConvertTo-TicketboxPostgresqlExportedSnapshotUnsignedInt64 `
                -Value $Evidence.$field `
                -Label $field
    }
    $preflight = $timestamps["snapshot_exporter_preflight_observed_at_utc"]
    $started = $timestamps["snapshot_exporter_transaction_started_utc"]
    $expiry = $timestamps[
        "transaction_timeout_derived_upper_bound_expiry_utc"
    ]
    $observed = $timestamps["timeout_observed_at_utc"]
    $maximum = $numbers["maximum_remaining_ceiling_ms"]
    $remaining = $numbers["remaining_ms_before_statement"]
    $statementConfigured = $numbers[
        "statement_timeout_configured_ceiling_ms"
    ]
    $statementApplied = $numbers["statement_timeout_applied_ms"]
    $transactionConfigured = $numbers[
        "transaction_timeout_configured_ceiling_ms"
    ]
    $transactionArmed = $numbers["transaction_timeout_armed_ms"]
    $transactionCurrent = $numbers[
        "transaction_timeout_current_setting_ms"
    ]
    $idleConfigured = $numbers[
        "idle_in_transaction_session_timeout_configured_ms"
    ]
    $idleEffective = $numbers[
        "idle_in_transaction_session_timeout_effective_ms"
    ]
    $lockConfigured = $numbers["lock_timeout_configured_ceiling_ms"]
    $lockApplied = $numbers["lock_timeout_applied_ms"]
    $derivedArmed = [int64][Math]::Round(
        ($expiry - $started).TotalMilliseconds
    )
    $expectedText = $expectedDeadline.UtcDateTime.ToString("o")
    if (
        [string]$Evidence.absolute_deadline_utc -cne $expectedText -or
        [string]$Evidence.snapshot_exporter_deadline_utc -cne $expectedText -or
        $Evidence.transaction_timeout_reconfigured_in_transaction -isnot
            [bool] -or
        [bool]$Evidence.transaction_timeout_reconfigured_in_transaction -or
        $maximum -lt 1000 -or
        $maximum -gt [uint64]$MaximumRemainingCeilingMilliseconds -or
        $remaining -lt 1 -or $remaining -gt $maximum -or
        $transactionArmed -lt 1 -or $transactionArmed -gt $maximum -or
        $transactionCurrent -ne $transactionArmed -or
        [Math]::Abs($derivedArmed - [int64]$transactionArmed) -gt 2 -or
        $preflight -gt $started -or $started -gt $observed -or
        $observed -ge $expiry -or $expiry -gt $expectedDeadline -or
        $CurrentUtc -ge $expiry -or
        (
            $transactionConfigured -gt 0 -and
            $transactionArmed -gt $transactionConfigured
        ) -or
        $statementApplied -lt 1 -or $statementApplied -gt $remaining -or
        (
            $statementConfigured -gt 0 -and
            $statementApplied -gt $statementConfigured
        ) -or
        $idleEffective -ne $idleConfigured -or
        $lockApplied -lt 1 -or $lockApplied -gt 5000 -or
        $lockApplied -gt $remaining -or
        ($lockConfigured -gt 0 -and $lockApplied -gt $lockConfigured) -or
        [string]$Evidence.enforcement_kind -cne
            "pre_begin_transaction_plus_per_statement_absolute_v1" -or
        [string]$Evidence.observed_server_termination -cne
            "not_observed_while_holder_live" -or
        [string]$Evidence.holder_wait -cne
            "psql_file_stdin_open_idle_transaction"
    ) {
        throw "PostgreSQL exported-snapshot deadline evidence 未保持 no-widen。"
    }
    return [pscustomobject][ordered]@{
        AbsoluteDeadlineUtc = $expectedText
        TransactionDeadlineUtc = $expiry.UtcDateTime.ToString("o")
        SnapshotExporterTransactionStartedUtc =
            $started.UtcDateTime.ToString("o")
    }
}
