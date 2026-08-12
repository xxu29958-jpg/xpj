#Requires -Version 5.1

function Test-TicketboxC07WriterFenceRoleElevated {
    param([Parameter(Mandatory = $true)][object]$Role)
    return (
        [bool]$Role.is_superuser -or
        [bool]$Role.can_create_db -or
        [bool]$Role.can_create_role -or
        [bool]$Role.can_replicate -or
        [bool]$Role.can_bypass_rls
    )
}

function Test-TicketboxC07WriterFenceRoleHasWriteAuthority {
    param([Parameter(Mandatory = $true)][object]$Role)
    return (
        [bool]$Role.is_database_owner -or
        [bool]$Role.owns_managed_schema -or
        [bool]$Role.owns_managed_relations -or
        [bool]$Role.owns_security_definer_routines -or
        [bool]$Role.can_execute_unowned_security_definer_routines -or
        [bool]$Role.can_database_create -or
        [bool]$Role.can_managed_schema_create -or
        [bool]$Role.can_table_write -or
        [bool]$Role.can_sequence_write -or
        [bool]$Role.can_assume_write_owner
    )
}

function Test-TicketboxC07WriterFenceStringSetEquals {
    param(
        [AllowEmptyCollection()][object[]]$Actual,
        [AllowEmptyCollection()][string[]]$Expected
    )
    $left = @($Actual | ForEach-Object { [string]$_ } | Sort-Object -CaseSensitive)
    $right = @($Expected | Sort-Object -CaseSensitive)
    return (
        $left.Count -eq $right.Count -and
        [string]::Join("`n", $left) -ceq [string]::Join("`n", $right)
    )
}

function Get-TicketboxC07WriterFenceRoleDisposition {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "legacy_owner_frozen",
            "managed_frozen",
            "published_runtime"
        )]
        [string]$AuthorityPhase
    )
    if ($Name -ceq "postgres") { return "database_authority" }
    if ($AuthorityPhase -ceq "legacy_owner_frozen") {
        if ($Name -ceq $script:TicketboxC07LegacyRuntimeRole) {
            return "legacy_owner_writer"
        }
        if ($Name -ceq $script:TicketboxC07MigratorRole) {
            return "staged_migration_authority"
        }
        if ($Name -ceq $script:TicketboxC07OwnerRole) {
            return "staged_nologin_owner"
        }
        if ($Name -ceq $script:TicketboxC07RuntimeRole) {
            return "staged_runtime"
        }
    }
    elseif ($AuthorityPhase -ceq "managed_frozen") {
        if ($Name -ceq $script:TicketboxC07LegacyRuntimeRole) {
            return "retired_legacy"
        }
        if ($Name -ceq $script:TicketboxC07MigratorRole) {
            return "migration_authority"
        }
        if ($Name -ceq $script:TicketboxC07OwnerRole) {
            return "nologin_owner"
        }
        if ($Name -ceq $script:TicketboxC07RuntimeRole) {
            return "fenced_runtime"
        }
    }
    else {
        if ($Name -ceq $script:TicketboxC07LegacyRuntimeRole) {
            return "retired_legacy"
        }
        if ($Name -ceq $script:TicketboxC07MigratorRole) {
            return "retired_migration_authority"
        }
        if ($Name -ceq $script:TicketboxC07OwnerRole) {
            return "nologin_owner"
        }
        if ($Name -ceq $script:TicketboxC07RuntimeRole) {
            return "published_runtime"
        }
    }
    return "inert_unregistered"
}

function Resolve-TicketboxC07FrozenWriterFenceAuthorityPhase {
    param([Parameter(Mandatory = $true)][object]$RawObservation)
    $legacyOwners = @(
        $RawObservation.Roles | Where-Object {
            [string]$_.name -ceq $script:TicketboxC07LegacyRuntimeRole -and
            [bool]$_.is_database_owner
        }
    )
    $managedOwners = @(
        $RawObservation.Roles | Where-Object {
            [string]$_.name -ceq $script:TicketboxC07OwnerRole -and
            [bool]$_.is_database_owner
        }
    )
    if ($legacyOwners.Count -eq 1 -and $managedOwners.Count -eq 0) {
        return "legacy_owner_frozen"
    }
    if ($legacyOwners.Count -eq 0 -and $managedOwners.Count -eq 1) {
        return "managed_frozen"
    }
    throw "C07 无法从只读 database-owner facts 唯一分类 frozen authority phase。"
}

function Assert-TicketboxC07WriterFenceRolePolicy {
    param(
        [Parameter(Mandatory = $true)][object]$Role,
        [Parameter(Mandatory = $true)][string]$Disposition,
        [Parameter(Mandatory = $true)][bool]$PublicConnect
    )
    $elevated = Test-TicketboxC07WriterFenceRoleElevated $Role
    $writeAuthority = Test-TicketboxC07WriterFenceRoleHasWriteAuthority $Role
    $usage = @($Role.predefined_role_usage)
    $set = @($Role.predefined_role_set)
    $ownsDefiner = [bool]$Role.owns_security_definer_routines
    $executesUnownedDefiner =
        [bool]$Role.can_execute_unowned_security_definer_routines
    $valid = switch -CaseSensitive ($Disposition) {
        "database_authority" {
            [bool]$Role.can_login -and [bool]$Role.is_superuser
        }
        "legacy_owner_writer" {
            -not $elevated -and
            [bool]$Role.is_database_owner -and
            [bool]$Role.owns_managed_schema -and
            [bool]$Role.owns_managed_relations -and
            [bool]$Role.can_database_create -and
            [bool]$Role.can_managed_schema_create -and
            [bool]$Role.can_table_write -and
            [bool]$Role.can_sequence_write -and
            -not [bool]$Role.can_assume_write_owner -and
            -not $executesUnownedDefiner -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @("pg_database_owner")) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @("pg_database_owner"))
        }
        "staged_migration_authority" {
            [bool]$Role.can_login -and -not $elevated -and
            -not $writeAuthority -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        "staged_nologin_owner" {
            -not [bool]$Role.can_login -and -not $elevated -and
            -not $writeAuthority -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        "staged_runtime" {
            -not $elevated -and -not $writeAuthority -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        "migration_authority" {
            [bool]$Role.can_login -and -not $elevated -and
            -not [bool]$Role.is_database_owner -and
            -not [bool]$Role.owns_managed_schema -and
            -not [bool]$Role.owns_managed_relations -and
            -not [bool]$Role.can_database_create -and
            -not [bool]$Role.can_managed_schema_create -and
            -not [bool]$Role.can_table_write -and
            -not [bool]$Role.can_sequence_write -and
            [bool]$Role.can_assume_write_owner -and
            -not $ownsDefiner -and -not $executesUnownedDefiner -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @("pg_database_owner"))
        }
        "nologin_owner" {
            -not [bool]$Role.can_login -and -not $elevated -and
            [bool]$Role.is_database_owner -and
            [bool]$Role.owns_managed_schema -and
            [bool]$Role.owns_managed_relations -and
            [bool]$Role.can_database_create -and
            [bool]$Role.can_managed_schema_create -and
            [bool]$Role.can_table_write -and
            [bool]$Role.can_sequence_write -and
            -not [bool]$Role.can_assume_write_owner -and
            -not $executesUnownedDefiner -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @("pg_database_owner")) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @("pg_database_owner"))
        }
        "fenced_runtime" {
            -not $elevated -and
            -not [bool]$Role.is_database_owner -and
            -not [bool]$Role.owns_managed_schema -and
            -not [bool]$Role.owns_managed_relations -and
            -not [bool]$Role.can_database_create -and
            -not [bool]$Role.can_managed_schema_create -and
            [bool]$Role.can_table_write -and
            [bool]$Role.can_sequence_write -and
            -not [bool]$Role.can_assume_write_owner -and
            -not $ownsDefiner -and -not $executesUnownedDefiner -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        "published_runtime" {
            [bool]$Role.can_login -and
            [int]$Role.connection_limit -eq -1 -and
            [bool]$Role.direct_connect -and
            [bool]$Role.effective_connect -and
            -not $elevated -and
            -not [bool]$Role.is_database_owner -and
            -not [bool]$Role.owns_managed_schema -and
            -not [bool]$Role.owns_managed_relations -and
            -not [bool]$Role.can_database_create -and
            -not [bool]$Role.can_managed_schema_create -and
            [bool]$Role.can_table_write -and
            [bool]$Role.can_sequence_write -and
            -not [bool]$Role.can_assume_write_owner -and
            -not $ownsDefiner -and -not $executesUnownedDefiner -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        { $_ -cin @("retired_legacy", "retired_migration_authority") } {
            -not [bool]$Role.can_login -and
            -not [bool]$Role.direct_connect -and
            -not [bool]$Role.effective_connect -and
            -not $elevated -and -not $writeAuthority -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        "inert_unregistered" {
            -not [bool]$Role.can_login -and
            -not [bool]$Role.direct_connect -and
            (-not [bool]$Role.effective_connect -or $PublicConnect) -and
            -not $elevated -and -not $writeAuthority -and
            (Test-TicketboxC07WriterFenceStringSetEquals $usage @()) -and
            (Test-TicketboxC07WriterFenceStringSetEquals $set @())
        }
        default { $false }
    }
    if (-not $valid) {
        throw (
            "C07 PostgreSQL role 不符合显式 authority phase：role=" +
            [string]$Role.name + ", disposition=$Disposition, facts=" +
            ($Role | ConvertTo-Json -Compress -Depth 6) + "。"
        )
    }
}

function ConvertTo-TicketboxC07WriterFenceObservation {
    param(
        [Parameter(Mandatory = $true)][object]$RawObservation,
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "legacy_owner_frozen",
            "managed_frozen",
            "published_runtime"
        )]
        [string]$AuthorityPhase
    )
    if (
        [int64]$RawObservation.MaxPreparedTransactions -ne 0 -or
        [int64]$RawObservation.PreparedTransactionCount -ne 0 -or
        [int64]$RawObservation.LogicalSubscriptionCount -ne 0 -or
        [int64]$RawObservation.LogicalApplyWorkerCount -ne 0 -or
        [int64]$RawObservation.UnexpectedDatabaseWorkerCount -ne 0 -or
        -not [bool]$RawObservation.AdvisoryFenceAvailable -or
        -not [bool]$RawObservation.AdvisoryFenceReleased
    ) {
        throw "C07 PostgreSQL session/fence observation 无效或 migration lease 忙。"
    }
    $validatedRoles = @()
    foreach ($role in @($RawObservation.Roles)) {
        $disposition = Get-TicketboxC07WriterFenceRoleDisposition `
            -Name ([string]$role.name) `
            -AuthorityPhase $AuthorityPhase
        Assert-TicketboxC07WriterFenceRolePolicy `
            -Role $role `
            -Disposition $disposition `
            -PublicConnect ([bool]$RawObservation.PublicConnect)
        $validatedRoles += [pscustomobject][ordered]@{
            name = [string]$role.name
            oid = [int64]$role.oid
            disposition = $disposition
            can_login = [bool]$role.can_login
            connection_limit = [int]$role.connection_limit
            is_superuser = [bool]$role.is_superuser
            can_create_db = [bool]$role.can_create_db
            can_create_role = [bool]$role.can_create_role
            can_replicate = [bool]$role.can_replicate
            can_bypass_rls = [bool]$role.can_bypass_rls
            is_database_owner = [bool]$role.is_database_owner
            owns_public_schema = [bool]$role.owns_managed_schema
            owns_user_relations = [bool]$role.owns_managed_relations
            owns_security_definer_routines =
                [bool]$role.owns_security_definer_routines
            can_execute_unowned_security_definer_routines =
                [bool]$role.can_execute_unowned_security_definer_routines
            direct_connect = [bool]$role.direct_connect
            effective_connect = [bool]$role.effective_connect
            can_database_create = [bool]$role.can_database_create
            can_public_schema_create = [bool]$role.can_managed_schema_create
            can_table_write = [bool]$role.can_table_write
            can_sequence_write = [bool]$role.can_sequence_write
            can_assume_write_owner = [bool]$role.can_assume_write_owner
            predefined_role_usage = @($role.predefined_role_usage)
            predefined_role_set = @($role.predefined_role_set)
        }
    }
    $count = {
        param([string]$Disposition)
        return @(
            $validatedRoles | Where-Object { $_.disposition -ceq $Disposition }
        ).Count
    }
    if ((& $count "database_authority") -ne 1) {
        throw "C07 PostgreSQL 缺少唯一 database authority role。"
    }
    if ($AuthorityPhase -ceq "legacy_owner_frozen") {
        if ((& $count "legacy_owner_writer") -ne 1) {
            throw "C07 legacy phase 缺少唯一 legacy owner writer。"
        }
        $targetCount =
            (& $count "staged_migration_authority") +
            (& $count "staged_nologin_owner") +
            (& $count "staged_runtime")
        if ($targetCount -notin @(0, 3)) {
            throw "C07 legacy phase 存在 partial target-role residue。"
        }
    }
    elseif ($AuthorityPhase -ceq "managed_frozen") {
        if (
            (& $count "migration_authority") -ne 1 -or
            (& $count "nologin_owner") -ne 1 -or
            (& $count "fenced_runtime") -ne 1
        ) {
            throw "C07 managed-frozen phase 缺少唯一 migrator/owner/runtime。"
        }
    }
    elseif (
        (& $count "retired_migration_authority") -ne 1 -or
        (& $count "nologin_owner") -ne 1 -or
        (& $count "published_runtime") -ne 1
    ) {
        throw "C07 published phase 缺少唯一 retired migrator/owner/runtime。"
    }
    return [pscustomobject]@{
        AuthorityPhase = $AuthorityPhase
        PublicConnect = [bool]$RawObservation.PublicConnect
        OtherClientSessionCount = [int64]$RawObservation.OtherClientSessionCount
        ClientSessions = @($RawObservation.ClientSessions)
        MaxPreparedTransactions = [int64]$RawObservation.MaxPreparedTransactions
        PreparedTransactionCount = [int64]$RawObservation.PreparedTransactionCount
        LogicalSubscriptionCount = [int64]$RawObservation.LogicalSubscriptionCount
        LogicalApplyWorkerCount = [int64]$RawObservation.LogicalApplyWorkerCount
        UnexpectedDatabaseWorkerCount =
            [int64]$RawObservation.UnexpectedDatabaseWorkerCount
        AdvisoryFenceAvailable = [bool]$RawObservation.AdvisoryFenceAvailable
        AdvisoryFenceReleased = [bool]$RawObservation.AdvisoryFenceReleased
        Roles = @($validatedRoles)
    }
}

function Test-TicketboxC07ClientSessionSetEquals {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Left,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Right
    )
    if ($Left.Count -ne $Right.Count) { return $false }
    foreach ($leftSession in $Left) {
        $matches = @(
            $Right | Where-Object {
                [int]$_.pid -eq [int]$leftSession.pid -and
                [string]$_.role -ceq [string]$leftSession.role -and
                [string]$_.application_name -ceq [string]$leftSession.application_name
            }
        )
        if ($matches.Count -ne 1) { return $false }
    }
    return $true
}

function Assert-TicketboxC07WriterDatabaseFence {
    param(
        [Parameter(Mandatory = $true)][object]$Observation,
        [object[]]$AllowedClientSessions = @()
    )
    if (
        [string]$Observation.AuthorityPhase -cnotin @(
            "legacy_owner_frozen", "managed_frozen"
        ) -or
        [bool]$Observation.PublicConnect -or
        [int64]$Observation.OtherClientSessionCount -ne $AllowedClientSessions.Count -or
        -not (Test-TicketboxC07ClientSessionSetEquals `
            -Left @($AllowedClientSessions) -Right @($Observation.ClientSessions)) -or
        -not [bool]$Observation.AdvisoryFenceAvailable -or
        -not [bool]$Observation.AdvisoryFenceReleased
    ) {
        throw "C07 durable writer fence 未阻断 runtime login/CONNECT/session。"
    }
    foreach ($role in @($Observation.Roles)) {
        if (
            [string]$role.disposition -cin @("fenced_runtime", "staged_runtime") -and
            (
                [bool]$role.can_login -or
                [int]$role.connection_limit -ne 0 -or
                [bool]$role.direct_connect -or
                [bool]$role.effective_connect
            )
        ) {
            throw "C07 durable writer fence 的 runtime role 仍可连接。"
        }
        if (
            [string]$role.disposition -ceq "legacy_owner_writer" -and
            (
                [bool]$role.can_login -or
                [int]$role.connection_limit -ne 0 -or
                [bool]$role.direct_connect
            )
        ) {
            throw "C07 legacy owner writer 的新连接 admission 未关闭。"
        }
    }
}

function Assert-TicketboxC07PublishedDatabaseAuthority {
    param([Parameter(Mandatory = $true)][object]$Observation)
    if (
        [string]$Observation.AuthorityPhase -cne "published_runtime" -or
        [bool]$Observation.PublicConnect -or
        [int64]$Observation.OtherClientSessionCount -ne 0 -or
        @($Observation.ClientSessions).Count -ne 0 -or
        -not [bool]$Observation.AdvisoryFenceAvailable -or
        -not [bool]$Observation.AdvisoryFenceReleased
    ) {
        throw "C07 published runtime authority 的 session/advisory 边界无效。"
    }
}

function Assert-TicketboxC07PublishedReadyRoleSet {
    param([Parameter(Mandatory = $true)][object[]]$Roles)

    if ($Roles.Count -lt 4 -or $Roles.Count -gt 128) {
        throw "C07 published READY role set count 无效。"
    }
    $expectedNames = @(
        "name", "oid", "disposition", "can_login", "connection_limit",
        "is_superuser", "can_create_db", "can_create_role", "can_replicate",
        "can_bypass_rls", "is_database_owner", "owns_public_schema",
        "owns_user_relations", "owns_security_definer_routines",
        "can_execute_unowned_security_definer_routines", "direct_connect",
        "effective_connect", "can_database_create", "can_public_schema_create",
        "can_table_write", "can_sequence_write", "can_assume_write_owner",
        "predefined_role_usage", "predefined_role_set"
    )
    $booleanNames = @(
        "can_login", "is_superuser", "can_create_db", "can_create_role",
        "can_replicate", "can_bypass_rls", "is_database_owner",
        "owns_public_schema", "owns_user_relations",
        "owns_security_definer_routines",
        "can_execute_unowned_security_definer_routines", "direct_connect",
        "effective_connect", "can_database_create", "can_public_schema_create",
        "can_table_write", "can_sequence_write", "can_assume_write_owner"
    )
    $names = @{}
    $oids = @{}
    $validated = @()
    foreach ($role in $Roles) {
        Assert-TicketboxC07ExactProperties `
            -Value $role `
            -ExpectedNames $expectedNames `
            -ArtifactName "published READY role"
        $name = [string]$role.name
        $oid = [int64]0
        if (
            [string]::IsNullOrEmpty($name) -or $name.Length -gt 63 -or
            ($role.oid -isnot [int] -and $role.oid -isnot [long]) -or
            -not [int64]::TryParse([string]$role.oid, [ref]$oid) -or
            $oid -lt 1 -or $oid -gt [uint32]::MaxValue -or
            $names.ContainsKey($name) -or $oids.ContainsKey([string]$oid) -or
            ($role.connection_limit -isnot [int] -and
                $role.connection_limit -isnot [long]) -or
            [int64]$role.connection_limit -lt -1 -or
            [int64]$role.connection_limit -gt [int]::MaxValue -or
            @($booleanNames | Where-Object { $role.$_ -isnot [bool] }).Count -ne 0
        ) {
            throw "C07 published READY role shape 无效。"
        }
        foreach ($setName in @("predefined_role_usage", "predefined_role_set")) {
            $setValue = $role.$setName
            if (
                $null -eq $setValue -or
                $setValue -is [string] -or
                $setValue -isnot [System.Collections.IEnumerable]
            ) {
                throw "C07 published READY role $setName 必须是 string array。"
            }
            $seenSetItems = @{}
            foreach ($setItem in @($setValue)) {
                if (
                    $setItem -isnot [string] -or
                    [string]::IsNullOrEmpty([string]$setItem) -or
                    $seenSetItems.ContainsKey([string]$setItem)
                ) {
                    throw "C07 published READY role $setName 含无效或重复项。"
                }
                $seenSetItems[[string]$setItem] = $true
            }
        }
        $names[$name] = $true
        $oids[[string]$oid] = $true
        $expectedDisposition = Get-TicketboxC07WriterFenceRoleDisposition `
            -Name $name `
            -AuthorityPhase "published_runtime"
        if ([string]$role.disposition -cne $expectedDisposition) {
            throw (
                "C07 published READY role disposition 与产品 policy 不一致：" +
                "role=$name, actual=$([string]$role.disposition), " +
                "expected=$expectedDisposition。"
            )
        }
        $policyRole = [pscustomobject]@{
            name = $name
            oid = $oid
            can_login = [bool]$role.can_login
            connection_limit = [int]$role.connection_limit
            is_superuser = [bool]$role.is_superuser
            can_create_db = [bool]$role.can_create_db
            can_create_role = [bool]$role.can_create_role
            can_replicate = [bool]$role.can_replicate
            can_bypass_rls = [bool]$role.can_bypass_rls
            is_database_owner = [bool]$role.is_database_owner
            owns_managed_schema = [bool]$role.owns_public_schema
            owns_managed_relations = [bool]$role.owns_user_relations
            owns_security_definer_routines =
                [bool]$role.owns_security_definer_routines
            can_execute_unowned_security_definer_routines =
                [bool]$role.can_execute_unowned_security_definer_routines
            direct_connect = [bool]$role.direct_connect
            effective_connect = [bool]$role.effective_connect
            can_database_create = [bool]$role.can_database_create
            can_managed_schema_create = [bool]$role.can_public_schema_create
            can_table_write = [bool]$role.can_table_write
            can_sequence_write = [bool]$role.can_sequence_write
            can_assume_write_owner = [bool]$role.can_assume_write_owner
            predefined_role_usage = @($role.predefined_role_usage)
            predefined_role_set = @($role.predefined_role_set)
        }
        Assert-TicketboxC07WriterFenceRolePolicy `
            -Role $policyRole `
            -Disposition $expectedDisposition `
            -PublicConnect $false
        $validated += $role
    }
    foreach ($required in @(
        "database_authority", "retired_migration_authority",
        "nologin_owner", "published_runtime"
    )) {
        if (@($validated | Where-Object {
            [string]$_.disposition -ceq $required
        }).Count -ne 1) {
            throw "C07 published READY 缺少唯一 $required role。"
        }
    }
}
