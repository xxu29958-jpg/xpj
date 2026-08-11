#Requires -Version 5.1

<#
.SYNOPSIS
  C07 authority binding for generic Windows deadline budgets.
.DESCRIPTION
  Retains Ticketbox operation/attempt policy while delegating clock and
  deadline arithmetic to windows_deadline_budget.ps1.
#>

function Assert-TicketboxC07MaintenanceBudgetBinding {
    param([Parameter(Mandatory = $true)][object]$Budget)

    [void](ConvertTo-TicketboxC07CanonicalOperationId `
        ([string]$Budget.OperationId))
    [void](ConvertTo-TicketboxC07CanonicalUuid `
        -Value ([string]$Budget.AttemptId) `
        -Label "maintenance budget attempt identity")
    if ([int64]$Budget.AttemptSequence -lt 1) {
        throw "C07 maintenance budget attempt sequence 必须为正数。"
    }
    Assert-TicketboxC07Sha256 `
        -Value ([string]$Budget.AttemptSha256) `
        -FieldName "maintenance budget attempt_sha256"
}

function Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds {
    param(
        [Parameter(Mandatory = $true)][object]$Budget,
        [ValidateRange(1000, 3600000)][int]$MaximumMilliseconds = 3600000,
        [ValidateRange(1, 60000)][int]$MinimumMilliseconds = 1000,
        [DateTime]$CurrentUtc = [DateTime]::UtcNow,
        [string]$Label = "C07 authority-bound deadline action"
    )
    Assert-TicketboxC07MaintenanceBudgetBinding $Budget
    return Get-TicketboxWindowsDeadlineRemainingMilliseconds `
        -Budget $Budget `
        -MaximumMilliseconds $MaximumMilliseconds `
        -MinimumMilliseconds $MinimumMilliseconds `
        -CurrentUtc $CurrentUtc `
        -Label $Label
}
