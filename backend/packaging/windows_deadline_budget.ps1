#Requires -Version 5.1

<#
.SYNOPSIS
  Windows boot-session and monotonic deadline mechanics.
.DESCRIPTION
  Combines a durable UTC ceiling with Windows uptime and a process-local
  Stopwatch. Callers retain authority, retry, failure, and mutation policy.
#>

function ConvertTo-TicketboxExplicitUtcDeadline {
    param(
        [Parameter(Mandatory = $true)][DateTime]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value.Kind -eq [DateTimeKind]::Unspecified) {
        throw "$Label must have an explicit UTC or local offset."
    }
    return $Value.ToUniversalTime()
}

function Get-TicketboxWindowsBootIdentity {
    try {
        $operatingSystem = Get-CimInstance `
            -ClassName Win32_OperatingSystem `
            -Property LastBootUpTime `
            -ErrorAction Stop
        if ($null -eq $operatingSystem.LastBootUpTime) {
            throw "Win32_OperatingSystem returned no LastBootUpTime."
        }
        $bootUtc = ([DateTime]$operatingSystem.LastBootUpTime).ToUniversalTime()
        return $bootUtc.ToString("o")
    }
    catch {
        throw "Unable to obtain the current Windows boot identity: $($_.Exception.Message)"
    }
}

function Measure-TicketboxWindowsPersistedDeadline {
    param(
        [Parameter(Mandatory = $true)][DateTime]$DeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 604800000)][int64]$WindowMilliseconds,
        [Parameter(Mandatory = $true)][int64]$StartedTickCount64,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$StartedBootIdentity,
        [DateTime]$CurrentUtc = [DateTime]::UtcNow,
        [int64]$CurrentTickCount64 = [Environment]::TickCount64,
        [string]$CurrentBootIdentity = ""
    )
    $deadline = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value $DeadlineUtc `
        -Label "Deadline"
    $current = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value $CurrentUtc `
        -Label "Current time"
    if ([string]::IsNullOrWhiteSpace($CurrentBootIdentity)) {
        $CurrentBootIdentity = Get-TicketboxWindowsBootIdentity
    }
    if ($StartedBootIdentity -cne $CurrentBootIdentity) {
        return [pscustomobject]@{
            Continuous = $false
            FailureCode = "boot_session_changed"
            RemainingMilliseconds = [int64]0
        }
    }
    if ($StartedTickCount64 -lt 0 -or
        $CurrentTickCount64 -lt $StartedTickCount64) {
        return [pscustomobject]@{
            Continuous = $false
            FailureCode = "tick_count_rollback"
            RemainingMilliseconds = [int64]0
        }
    }
    $tickRemaining = [double]$WindowMilliseconds -
        [double]($CurrentTickCount64 - $StartedTickCount64)
    $wallRemaining = ($deadline - $current).TotalMilliseconds
    $remaining = [Math]::Max(
        0,
        [Math]::Floor([Math]::Min($tickRemaining, $wallRemaining))
    )
    return [pscustomobject]@{
        Continuous = $true
        FailureCode = ""
        RemainingMilliseconds = [int64]$remaining
    }
}

function New-TicketboxWindowsDeadlineBudget {
    param(
        [Parameter(Mandatory = $true)][DateTime]$DeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 604800000)][int64]$WindowMilliseconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 604800000)]
        [int64]$DurableRemainingCeilingMilliseconds,
        [Parameter(Mandatory = $true)][int64]$StartedTickCount64,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$StartedBootIdentity,
        [DateTime]$CurrentUtc = [DateTime]::UtcNow,
        [int64]$CurrentTickCount64 = [Environment]::TickCount64,
        [string]$CurrentBootIdentity = "",
        [ValidateRange(1, 60000)][int]$MinimumMilliseconds = 1000
    )
    $observation = Measure-TicketboxWindowsPersistedDeadline `
        -DeadlineUtc $DeadlineUtc `
        -WindowMilliseconds $WindowMilliseconds `
        -StartedTickCount64 $StartedTickCount64 `
        -StartedBootIdentity $StartedBootIdentity `
        -CurrentUtc $CurrentUtc `
        -CurrentTickCount64 $CurrentTickCount64 `
        -CurrentBootIdentity $CurrentBootIdentity
    if (-not [bool]$observation.Continuous) {
        throw "Persisted deadline is discontinuous: $($observation.FailureCode)."
    }
    $remaining = [Math]::Min(
        [double]$DurableRemainingCeilingMilliseconds,
        [double]$observation.RemainingMilliseconds
    )
    if ($remaining -lt $MinimumMilliseconds) {
        throw "Whole-operation deadline has expired."
    }
    return [pscustomobject]@{
        DeadlineUtc = (ConvertTo-TicketboxExplicitUtcDeadline `
            -Value $DeadlineUtc `
            -Label "Deadline")
        RemainingAtStartMilliseconds = [double]$remaining
        Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    }
}

function Get-TicketboxWindowsDeadlineRemainingMilliseconds {
    param(
        [Parameter(Mandatory = $true)][object]$Budget,
        [ValidateRange(1000, 3600000)][int]$MaximumMilliseconds = 3600000,
        [ValidateRange(1, 60000)][int]$MinimumMilliseconds = 1000,
        [DateTime]$CurrentUtc = [DateTime]::UtcNow,
        [string]$Label = "Windows deadline action"
    )
    if ($null -eq $Budget.Stopwatch -or
        -not [bool]$Budget.Stopwatch.IsRunning) {
        throw "$Label lacks an active process-local monotonic budget."
    }
    $deadline = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value ([DateTime]$Budget.DeadlineUtc) `
        -Label "$Label deadline"
    $current = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value $CurrentUtc `
        -Label "$Label current time"
    $monotonicRemaining =
        [double]$Budget.RemainingAtStartMilliseconds -
        [double]$Budget.Stopwatch.Elapsed.TotalMilliseconds
    $remaining = [Math]::Min(
        $monotonicRemaining,
        ($deadline - $current).TotalMilliseconds
    )
    if ($remaining -lt $MinimumMilliseconds) {
        throw "$Label exceeded the whole-operation deadline."
    }
    return [int][Math]::Floor(
        [Math]::Min([double]$MaximumMilliseconds, $remaining)
    )
}

function Get-TicketboxBoundedDeadlineUtc {
    param(
        [Parameter(Mandatory = $true)][DateTime]$RequestedDeadlineUtc,
        [Parameter(Mandatory = $true)][DateTime]$CeilingDeadlineUtc,
        [DateTime]$CurrentUtc = [DateTime]::UtcNow,
        [string]$Label = "Bounded deadline"
    )
    $requested = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value $RequestedDeadlineUtc `
        -Label "$Label requested value"
    $ceiling = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value $CeilingDeadlineUtc `
        -Label "$Label ceiling"
    $current = ConvertTo-TicketboxExplicitUtcDeadline `
        -Value $CurrentUtc `
        -Label "$Label current time"
    $bounded = if ($requested -lt $ceiling) { $requested } else { $ceiling }
    if ($bounded -le $current) {
        throw "$Label has expired."
    }
    return $bounded
}

function New-TicketboxProcessDeadlineBudget {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 25200000)][int64]$TimeoutMilliseconds
    )
    return [pscustomobject]@{
        TimeoutMilliseconds = $TimeoutMilliseconds
        Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    }
}

function Assert-TicketboxProcessDeadlinePhaseBudget {
    param(
        [Parameter(Mandatory = $true)][object]$Budget,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 21600000)][int64]$RequiredMilliseconds,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 3600000)][int64]$CleanupReserveMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($null -eq $Budget.Stopwatch -or -not [bool]$Budget.Stopwatch.IsRunning) {
        throw "$Label lacks an active whole-operation deadline."
    }
    $remaining = [int64]$Budget.TimeoutMilliseconds -
        [int64]$Budget.Stopwatch.ElapsedMilliseconds
    $requiredWithCleanup = $RequiredMilliseconds + $CleanupReserveMilliseconds
    if ($requiredWithCleanup -lt $RequiredMilliseconds -or $remaining -lt $requiredWithCleanup) {
        throw "$Label cannot start within the remaining whole-operation deadline."
    }
}
