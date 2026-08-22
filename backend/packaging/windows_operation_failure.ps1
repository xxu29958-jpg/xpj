#Requires -Version 5.1

function Throw-TicketboxOperationFailure {
    param(
        [AllowNull()][object]$Primary,
        [AllowNull()][object[]]$Cleanup
    )
    $cleanupFailures = @($Cleanup | Where-Object { $null -ne $_ })
    if ($null -ne $Primary -and $cleanupFailures.Count -gt 0) {
        $exceptions = @($Primary.Exception)
        foreach ($failure in $cleanupFailures) {
            if ($failure -is [Management.Automation.ErrorRecord]) {
                $exceptions += $failure.Exception
            }
            elseif ($failure -is [Exception]) {
                $exceptions += $failure
            }
            else {
                $exceptions += [InvalidOperationException]::new([string]$failure)
            }
        }
        $aggregate = [AggregateException]::new(
            "Ticketbox primary operation and cleanup failed",
            $exceptions
        )
        foreach ($key in @("TicketboxFailureCode", "TicketboxFailureCodes")) {
            if ($Primary.Exception.Data.Contains($key)) {
                $aggregate.Data[$key] = $Primary.Exception.Data[$key]
            }
        }
        throw $aggregate
    }
    if ($null -ne $Primary) { throw $Primary }
    if ($cleanupFailures.Count -eq 1) { throw $cleanupFailures[0] }
    if ($cleanupFailures.Count -gt 1) {
        $exceptions = foreach ($failure in $cleanupFailures) {
            if ($failure -is [Management.Automation.ErrorRecord]) {
                $failure.Exception
            }
            elseif ($failure -is [Exception]) { $failure }
            else { [InvalidOperationException]::new([string]$failure) }
        }
        throw [AggregateException]::new(
            "Ticketbox cleanup failed",
            @($exceptions)
        )
    }
}
