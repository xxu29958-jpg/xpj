#Requires -Version 5.1

function ConvertTo-TicketboxPostgresqlWriterFencePredefinedRoleNames {
    param(
        [AllowNull()][object]$Values,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Values -isnot [System.Array]) {
        throw "$Label is not a JSON array."
    }
    if (@($Values).Count -gt 128) {
        throw "$Label contains too many PostgreSQL predefined roles."
    }
    $seen = @{}
    $normalized = @()
    foreach ($value in @($Values)) {
        if ($value -isnot [string] -or [string]$value -cnotmatch '^pg_') {
            throw "$Label contains an invalid PostgreSQL predefined role."
        }
        Assert-TicketboxPostgresqlWriterFenceIdentifier ([string]$value) $Label
        if ($seen.ContainsKey([string]$value)) {
            throw "$Label contains a duplicate PostgreSQL predefined role."
        }
        $seen[[string]$value] = $true
        $normalized += [string]$value
    }
    return @($normalized | Sort-Object -CaseSensitive)
}

function Assert-TicketboxPostgresqlWriterFenceObservedRoleName {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (
        $Value -isnot [string] -or
        [string]::IsNullOrEmpty([string]$Value) -or
        ([string]$Value).Length -gt 63 -or
        ([string]$Value).IndexOf([char]0) -ge 0
    ) {
        throw "$Label is not a valid observed PostgreSQL role name."
    }
}

function ConvertFrom-TicketboxPostgresqlWriterFenceObservationJson {
    param([Parameter(Mandatory = $true)][string]$Json)

    try {
        $payload = $Json | ConvertFrom-Json
    }
    catch {
        throw "PostgreSQL writer-fence observation is not JSON."
    }
    if (
        $payload.client_sessions -isnot [System.Array] -or
        $payload.roles -isnot [System.Array]
    ) {
        throw "PostgreSQL writer-fence observation arrays are invalid."
    }
    Assert-TicketboxPostgresqlWriterFenceExactProperties `
        $payload `
        @(
            "public_connect",
            "client_session_count",
            "client_sessions",
            "max_prepared_transactions",
            "prepared_transaction_count",
            "logical_subscription_count",
            "logical_apply_worker_count",
            "unexpected_database_worker_count",
            "advisory_available",
            "advisory_released",
            "roles"
        ) `
        "PostgreSQL writer-fence observation"
    foreach ($field in @(
        "public_connect",
        "advisory_available",
        "advisory_released"
    )) {
        if ($payload.$field -isnot [bool]) {
            throw "PostgreSQL writer-fence observation has an invalid boolean."
        }
    }
    foreach ($field in @(
        "client_session_count",
        "max_prepared_transactions",
        "prepared_transaction_count",
        "logical_subscription_count",
        "logical_apply_worker_count",
        "unexpected_database_worker_count"
    )) {
        $number = [int64]0
        if (
            (
                $payload.$field -isnot [int] -and
                $payload.$field -isnot [long]
            ) -or
            -not [int64]::TryParse([string]$payload.$field, [ref]$number) -or
            $number -lt 0
        ) {
            throw "PostgreSQL writer-fence observation has an invalid count."
        }
    }
    if (
        -not [bool]$payload.advisory_available -or
        -not [bool]$payload.advisory_released
    ) {
        throw "PostgreSQL writer-fence advisory lease is busy or unreleased."
    }

    $sessions = @()
    $sessionPids = @{}
    foreach ($session in @($payload.client_sessions)) {
        Assert-TicketboxPostgresqlWriterFenceExactProperties `
            $session `
            @("pid", "role", "application_name", "state") `
            "PostgreSQL writer-fence client session"
        $pidValue = 0
        if (
            (
                $session.pid -isnot [int] -and
                $session.pid -isnot [long]
            ) -or
            -not [int]::TryParse([string]$session.pid, [ref]$pidValue) -or
            $pidValue -lt 1 -or
            $sessionPids.ContainsKey($pidValue) -or
            $session.role -isnot [string] -or
            [string]::IsNullOrEmpty([string]$session.role) -or
            ([string]$session.role).Length -gt 63 -or
            $session.application_name -isnot [string] -or
            ([string]$session.application_name).Length -gt 63 -or
            $session.state -isnot [string] -or
            [string]$session.state -cnotin @(
                "active",
                "idle",
                "idle in transaction",
                "idle in transaction (aborted)",
                "fastpath function call",
                "disabled"
            )
        ) {
            throw "PostgreSQL writer-fence client session is invalid."
        }
        $sessionPids[$pidValue] = $true
        $sessions += [pscustomobject][ordered]@{
            pid = $pidValue
            role = [string]$session.role
            application_name = [string]$session.application_name
            state = [string]$session.state
        }
    }
    if ($sessions.Count -ne [int64]$payload.client_session_count) {
        throw "PostgreSQL writer-fence client session count does not match."
    }

    $roleFields = @(
        "name",
        "oid",
        "can_login",
        "connection_limit",
        "is_superuser",
        "can_create_db",
        "can_create_role",
        "can_replicate",
        "can_bypass_rls",
        "is_database_owner",
        "owns_managed_schema",
        "owns_managed_relations",
        "owns_security_definer_routines",
        "can_execute_unowned_security_definer_routines",
        "direct_connect",
        "effective_connect",
        "can_database_create",
        "can_managed_schema_create",
        "can_table_write",
        "can_sequence_write",
        "can_assume_write_owner",
        "predefined_role_usage",
        "predefined_role_set"
    )
    $roles = @()
    $roleNames = @{}
    $roleOids = @{}
    foreach ($role in @($payload.roles)) {
        Assert-TicketboxPostgresqlWriterFenceExactProperties `
            $role `
            $roleFields `
            "PostgreSQL writer-fence role"
        Assert-TicketboxPostgresqlWriterFenceObservedRoleName `
            $role.name `
            "observed role"
        $roleOid = [int64]0
        $connectionLimit = 0
        if (
            $role.name -isnot [string] -or
            [string]::IsNullOrEmpty([string]$role.name)
        ) {
            throw "PostgreSQL writer-fence role name type is invalid."
        }
        if ($role.oid -isnot [int] -and $role.oid -isnot [long]) {
            throw (
                "PostgreSQL writer-fence role OID type is invalid: " +
                $role.oid.GetType().FullName
            )
        }
        if (
            -not [int64]::TryParse([string]$role.oid, [ref]$roleOid) -or
            $roleOid -lt 1 -or
            $roleOid -gt [uint32]::MaxValue
        ) {
            throw "PostgreSQL writer-fence role OID value is invalid."
        }
        if (
            $role.connection_limit -isnot [int] -and
            $role.connection_limit -isnot [long]
        ) {
            throw (
                "PostgreSQL writer-fence connection-limit type is invalid: " +
                $role.connection_limit.GetType().FullName
            )
        }
        if (
            -not [int]::TryParse(
                [string]$role.connection_limit,
                [ref]$connectionLimit
            ) -or
            $connectionLimit -lt -1
        ) {
            throw "PostgreSQL writer-fence connection-limit value is invalid."
        }
        if ($roleNames.ContainsKey([string]$role.name)) {
            throw "PostgreSQL writer-fence role name is duplicated."
        }
        if ($roleOids.ContainsKey($roleOid)) {
            throw "PostgreSQL writer-fence role OID is duplicated."
        }
        foreach ($field in @(
            "can_login",
            "is_superuser",
            "can_create_db",
            "can_create_role",
            "can_replicate",
            "can_bypass_rls",
            "is_database_owner",
            "owns_managed_schema",
            "owns_managed_relations",
            "owns_security_definer_routines",
            "can_execute_unowned_security_definer_routines",
            "direct_connect",
            "effective_connect",
            "can_database_create",
            "can_managed_schema_create",
            "can_table_write",
            "can_sequence_write",
            "can_assume_write_owner"
        )) {
            if ($role.$field -isnot [bool]) {
                throw "PostgreSQL writer-fence role has an invalid boolean."
            }
        }
        $roleNames[[string]$role.name] = $true
        $roleOids[$roleOid] = $true
        $predefinedRoleUsage = @(
            ConvertTo-TicketboxPostgresqlWriterFencePredefinedRoleNames `
                -Values $role.predefined_role_usage `
                -Label "PostgreSQL writer-fence predefined role usage"
        )
        $predefinedRoleSet = @(
            ConvertTo-TicketboxPostgresqlWriterFencePredefinedRoleNames `
                -Values $role.predefined_role_set `
                -Label "PostgreSQL writer-fence predefined role set"
        )
        $normalized = [ordered]@{
            name = [string]$role.name
            oid = $roleOid
            can_login = [bool]$role.can_login
            connection_limit = $connectionLimit
        }
        foreach ($field in $roleFields[4..($roleFields.Count - 3)]) {
            $normalized[$field] = [bool]$role.$field
        }
        $normalized["predefined_role_usage"] = @($predefinedRoleUsage)
        $normalized["predefined_role_set"] = @($predefinedRoleSet)
        $roles += [pscustomobject]$normalized
    }
    if ($roles.Count -lt 1 -or $roles.Count -gt 128) {
        throw "PostgreSQL writer-fence role set has an invalid size."
    }
    return [pscustomobject]@{
        PublicConnect = [bool]$payload.public_connect
        OtherClientSessionCount = [int64]$payload.client_session_count
        ClientSessions = @($sessions)
        MaxPreparedTransactions = [int64]$payload.max_prepared_transactions
        PreparedTransactionCount = [int64]$payload.prepared_transaction_count
        LogicalSubscriptionCount = [int64]$payload.logical_subscription_count
        LogicalApplyWorkerCount = [int64]$payload.logical_apply_worker_count
        UnexpectedDatabaseWorkerCount =
            [int64]$payload.unexpected_database_worker_count
        AdvisoryFenceAvailable = [bool]$payload.advisory_available
        AdvisoryFenceReleased = [bool]$payload.advisory_released
        Roles = @($roles)
    }
}
