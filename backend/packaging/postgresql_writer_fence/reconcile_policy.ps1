#Requires -Version 5.1

function Resolve-TicketboxPostgresqlWriterFenceReconcilePolicy {
    param(
        [Parameter(Mandatory = $true)][string]$AuthorityRole,
        [Parameter(Mandatory = $true)][string]$ManagedSchemaName,
        [Parameter(Mandatory = $true)][string]$AdvisoryLockLabel,
        [Parameter(Mandatory = $true)][string]$ApplicationName,
        [Parameter(Mandatory = $true)][string[]]$ManagedWriterRoles,
        [Parameter(Mandatory = $true)][string[]]$AuthorizedRoleNames,
        [Parameter(Mandatory = $true)][string[]]$AllowedLoginRolesAfterFence,
        [Parameter(Mandatory = $true)][string[]]$AllowedDatabaseOwnerRoles,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()]
        [string[]]$AllowedManagedWriterOwnerRoles,
        [Parameter(Mandatory = $true)][string[]]$AllowedDatabaseOwnerTransitionRoles,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds,
        [ValidateRange(1, 3600000)][int]$LockTimeoutMilliseconds,
        [ValidateRange(1, 3600000)][int]$TerminationTimeoutMilliseconds
    )

    Assert-TicketboxPostgresqlWriterFenceIdentifier $AuthorityRole "authority role"
    Assert-TicketboxPostgresqlWriterFenceIdentifier `
        $ManagedSchemaName `
        "managed schema"
    $managedRoles = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
        $ManagedWriterRoles `
        "managed writer roles"
    $authorizedRoles = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
        $AuthorizedRoleNames `
        "authorized roles"
    $allowedLoginRoles = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
        $AllowedLoginRolesAfterFence `
        "allowed login roles"
    $allowedDatabaseOwnerRolesSql = ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
        $AllowedDatabaseOwnerRoles `
        "allowed database owner roles"
    $allowedDatabaseOwnerTransitionRolesSql = `
        ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
            $AllowedDatabaseOwnerTransitionRoles `
            "allowed database owner transition roles"
    $allowedManagedWriterOwnerRolesSql = `
        ConvertTo-TicketboxPostgresqlWriterFenceTextArray `
            $AllowedManagedWriterOwnerRoles `
            "allowed managed-writer owner roles"
    $violations = @()
    if ($ManagedWriterRoles.Count -lt 1) { $violations += "managed_roles_empty" }
    if ($AuthorityRole -cnotin $AuthorizedRoleNames) {
        $violations += "authority_not_authorized"
    }
    if ($AuthorityRole -cnotin $AllowedLoginRolesAfterFence) {
        $violations += "authority_login_not_allowed"
    }
    if (@($ManagedWriterRoles | Where-Object { $_ -cnotin $AuthorizedRoleNames }).Count -ne 0) {
        $violations += "managed_role_not_authorized"
    }
    if (@($ManagedWriterRoles | Where-Object { $_ -cin $AllowedLoginRolesAfterFence }).Count -ne 0) {
        $violations += "managed_role_login_allowed"
    }
    if (@($AllowedLoginRolesAfterFence | Where-Object { $_ -cnotin $AuthorizedRoleNames }).Count -ne 0) {
        $violations += "login_role_not_authorized"
    }
    if ($AllowedDatabaseOwnerRoles.Count -lt 1) {
        $violations += "database_owner_roles_empty"
    }
    if (@($AllowedDatabaseOwnerRoles | Where-Object { $_ -cnotin $AuthorizedRoleNames }).Count -ne 0) {
        $violations += "database_owner_not_authorized"
    }
    if (
        @(
            $AllowedManagedWriterOwnerRoles |
                Where-Object {
                    $_ -cnotin $ManagedWriterRoles -or
                    $_ -cnotin $AllowedDatabaseOwnerRoles
                }
        ).Count -ne 0
    ) {
        $violations += "managed_writer_owner_not_authorized"
    }
    if (
        @(
            $AllowedDatabaseOwnerTransitionRoles |
                Where-Object { $_ -cnotin $AuthorizedRoleNames }
        ).Count -ne 0
    ) {
        $violations += "database_owner_transition_not_authorized"
    }
    if (
        @(
            $AllowedDatabaseOwnerTransitionRoles |
                Where-Object { $_ -cnotin $AllowedLoginRolesAfterFence }
        ).Count -ne 0
    ) {
        $violations += "database_owner_transition_login_not_allowed"
    }
    if (
        @(
            $AllowedDatabaseOwnerTransitionRoles |
                Where-Object { $_ -cin $ManagedWriterRoles }
        ).Count -ne 0
    ) {
        $violations += "managed_role_can_transition_to_database_owner"
    }
    if ($LockTimeoutMilliseconds -gt $TimeoutMilliseconds) {
        $violations += "lock_timeout_widens_deadline"
    }
    if ($TerminationTimeoutMilliseconds -gt $TimeoutMilliseconds) {
        $violations += "termination_timeout_widens_deadline"
    }
    if (
        [string]::IsNullOrWhiteSpace($AdvisoryLockLabel) -or
        $AdvisoryLockLabel.Length -gt 128
    ) {
        $violations += "advisory_label_invalid"
    }
    if (
        [string]::IsNullOrWhiteSpace($ApplicationName) -or
        $ApplicationName.Length -gt 63
    ) {
        $violations += "application_name_invalid"
    }
    if ($violations.Count -ne 0) {
        throw (
            "PostgreSQL writer-fence reconcile policy is invalid: " +
            [string]::Join(",", $violations)
        )
    }
    return [pscustomobject]@{
        Authority = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $AuthorityRole
        Schema = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $ManagedSchemaName
        Lease = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $AdvisoryLockLabel
        Application = ConvertTo-TicketboxPostgresqlWriterFenceSqlLiteral $ApplicationName
        ManagedRoles = $managedRoles
        AuthorizedRoles = $authorizedRoles
        AllowedLoginRoles = $allowedLoginRoles
        AllowedDatabaseOwnerRoles = $allowedDatabaseOwnerRolesSql
        AllowedManagedWriterOwnerRoles = $allowedManagedWriterOwnerRolesSql
        AllowedDatabaseOwnerTransitionRoles =
            $allowedDatabaseOwnerTransitionRolesSql
    }
}

function ConvertFrom-TicketboxPostgresqlWriterFenceReconcileJson {
    param([Parameter(Mandatory = $true)][string]$Json)

    try { $result = $Json | ConvertFrom-Json }
    catch { throw "PostgreSQL writer-fence reconcile result is not JSON." }
    Assert-TicketboxPostgresqlWriterFenceExactProperties `
        $result `
        @("advisory_released") `
        "PostgreSQL writer-fence reconcile result"
    if ($result.advisory_released -isnot [bool] -or -not $result.advisory_released) {
        throw "PostgreSQL writer-fence reconcile did not release its lease."
    }
    return [pscustomobject]@{ AdvisoryFenceReleased = $true }
}
