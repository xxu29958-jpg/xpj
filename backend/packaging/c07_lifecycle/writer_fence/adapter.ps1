#Requires -Version 5.1

function Get-TicketboxC07RawWriterDatabaseFenceObservation {
    $password = Get-TicketboxC07DatabaseAuthorityCredential
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $hostAuthority $password
    $nativeTimeoutMilliseconds =
        Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
            -MaximumMilliseconds 30000 `
            -Label "C07 writer-fence observation"
    $statementTimeoutMilliseconds = [Math]::Min(5000, $nativeTimeoutMilliseconds)
    $lockTimeoutMilliseconds = [Math]::Min(1000, $statementTimeoutMilliseconds)
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $hostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres"
    return Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {
        param([string]$PlainPassword)
        Get-TicketboxPostgresqlWriterFenceObservation `
            -PsqlPath $hostAuthority.PsqlPath `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -ManagedSchemaName "public" `
            -AdvisoryLockLabel "xiaopiaojia:schema" `
            -ApplicationName "ticketbox-c07-fence-observation" `
            -TimeoutMilliseconds $nativeTimeoutMilliseconds `
            -StatementTimeoutMilliseconds $statementTimeoutMilliseconds `
            -LockTimeoutMilliseconds $lockTimeoutMilliseconds
    }
}

function Get-TicketboxC07WriterDatabaseFenceObservation {
    param(
        [ValidateSet(
            "",
            "legacy_owner_frozen",
            "managed_frozen",
            "published_runtime"
        )]
        [string]$AuthorityPhase = ""
    )
    $raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
    $selectedPhase = if ([string]::IsNullOrEmpty($AuthorityPhase)) {
        Resolve-TicketboxC07FrozenWriterFenceAuthorityPhase $raw
    }
    else { $AuthorityPhase }
    return ConvertTo-TicketboxC07WriterFenceObservation `
        -RawObservation $raw `
        -AuthorityPhase $selectedPhase
}

function Resolve-TicketboxC07ManagedOrPublishedWriterFenceObservation {
    $raw = Get-TicketboxC07RawWriterDatabaseFenceObservation
    $matches = @()
    $failures = @()
    foreach ($phase in @("managed_frozen", "published_runtime")) {
        try {
            $matches += ConvertTo-TicketboxC07WriterFenceObservation `
                -RawObservation $raw `
                -AuthorityPhase $phase
        }
        catch { $failures += $_.Exception }
    }
    if ($matches.Count -ne 1) {
        throw [AggregateException]::new(
            "C07 runtime-ACL residue 无法唯一分类为 frozen 或 published。",
            [Exception[]]$failures
        )
    }
    return $matches[0]
}

function Test-TicketboxC07WriterFenceRoleIdentitySetEquals {
    param(
        [Parameter(Mandatory = $true)][object[]]$Left,
        [Parameter(Mandatory = $true)][object[]]$Right
    )
    if ($Left.Count -ne $Right.Count) { return $false }
    foreach ($leftRole in $Left) {
        if (@(
            $Right | Where-Object {
                [string]$_.name -ceq [string]$leftRole.name -and
                [int64]$_.oid -eq [int64]$leftRole.oid
            }
        ).Count -ne 1) {
            return $false
        }
    }
    return $true
}

function Initialize-TicketboxC07WriterFenceIntent {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$ServiceStartPolicy,
        [Parameter(Mandatory = $true)][object]$Observation,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$OperationMode,
        [Parameter(Mandatory = $true)]
        [ValidateSet("legacy_owner_frozen", "managed_frozen")]
        [string]$AuthorityPhase
    )
    $path = Get-TicketboxC07WriterFenceIntentPath (
        [string]$Authority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $path) {
        return Read-TicketboxC07WriterFenceIntent $Authority
    }
    if ([string]$Observation.AuthorityPhase -cne $AuthorityPhase) {
        throw "C07 writer-fence intent observation phase 不匹配。"
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07WriterFenceIntentSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        operation_mode = $OperationMode
        authority_phase = $AuthorityPhase
        backend_service_start_policy = $ServiceStartPolicy
        public_connect = [bool]$Observation.PublicConnect
        client_session_count_before_fence = [int64]$Observation.OtherClientSessionCount
        client_sessions_before_fence = @($Observation.ClientSessions)
        max_prepared_transactions = [int64]$Observation.MaxPreparedTransactions
        prepared_transaction_count = [int64]$Observation.PreparedTransactionCount
        logical_subscription_count = [int64]$Observation.LogicalSubscriptionCount
        logical_apply_worker_count = [int64]$Observation.LogicalApplyWorkerCount
        unexpected_database_worker_count =
            [int64]$Observation.UnexpectedDatabaseWorkerCount
        roles = @($Observation.Roles)
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "writer_fence_intent" `
        -Payload $payload | Out-Null
    return Read-TicketboxC07WriterFenceIntent $Authority
}

function Enter-TicketboxC07CurrentWriterDatabaseFence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)]
        [ValidateSet("legacy_owner_frozen", "managed_frozen")]
        [string]$AuthorityPhase
    )
    $password = Get-TicketboxC07DatabaseAuthorityCredential
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $hostAuthority $password
    $databaseFenceSqlTimeout =
        Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
            -MaximumMilliseconds 3600000 `
            -Label "C07 durable writer-fence SQL"
    $terminationTimeoutMilliseconds = [Math]::Max(
        1,
        [Math]::Min(3000, [Math]::Floor($databaseFenceSqlTimeout / 2))
    )
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $hostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres"
    $allowedOwners = @($script:TicketboxC07OwnerRole)
    $allowedManagedOwners = @()
    if ($authorityPhase -ceq "legacy_owner_frozen") {
        $allowedOwners = @($script:TicketboxC07LegacyRuntimeRole)
        $allowedManagedOwners = @($script:TicketboxC07LegacyRuntimeRole)
    }
    $reconcile = Invoke-TicketboxC07WithPlainSecret -Secret $password -Action {
        param([string]$PlainPassword)
        Invoke-TicketboxPostgresqlWriterFenceReconcile `
            -PsqlPath $hostAuthority.PsqlPath `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -AuthorityRole "postgres" `
            -ManagedSchemaName "public" `
            -AdvisoryLockLabel "xiaopiaojia:schema" `
            -ApplicationName (
                "ticketbox-c07-fence:" + [string]$Authority.Receipt.operation_id
            ) `
            -ManagedWriterRoles @(
                $script:TicketboxC07LegacyRuntimeRole,
                $script:TicketboxC07RuntimeRole
            ) `
            -AuthorizedRoleNames @(
                "postgres",
                $script:TicketboxC07LegacyRuntimeRole,
                $script:TicketboxC07OwnerRole,
                $script:TicketboxC07MigratorRole,
                $script:TicketboxC07RuntimeRole
            ) `
            -AllowedLoginRolesAfterFence @(
                "postgres",
                $script:TicketboxC07MigratorRole
            ) `
            -AllowedDatabaseOwnerRoles $allowedOwners `
            -AllowedManagedWriterOwnerRoles $allowedManagedOwners `
            -AllowedDatabaseOwnerTransitionRoles @(
                $script:TicketboxC07MigratorRole
            ) `
            -TimeoutMilliseconds $databaseFenceSqlTimeout `
            -LockTimeoutMilliseconds ([Math]::Min(1000, $databaseFenceSqlTimeout)) `
            -TerminationTimeoutMilliseconds $terminationTimeoutMilliseconds
    }
    if (-not [bool]$reconcile.AdvisoryFenceReleased) {
        throw "C07 durable writer-fence adapter 未返回 lease release 证据。"
    }
    $after = Get-TicketboxC07WriterDatabaseFenceObservation `
        -AuthorityPhase $authorityPhase
    Assert-TicketboxC07WriterDatabaseFence -Observation $after
    return $after
}

function Enter-TicketboxC07WriterDatabaseFence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Intent
    )
    $authorityPhase = [string]$Intent.AuthorityPhase
    $before = Get-TicketboxC07WriterDatabaseFenceObservation `
        -AuthorityPhase $authorityPhase
    if (-not (Test-TicketboxC07WriterFenceRoleIdentitySetEquals `
        -Left @($Intent.Roles) `
        -Right @($before.Roles))) {
        throw "C07 writer-fence acquire 前 live role identity 已漂移。"
    }
    if (
        [bool]$before.PublicConnect -ne [bool]$Intent.PublicConnect -and
        [bool]$before.PublicConnect
    ) {
        throw "C07 writer-fence acquire 前 database ACL 已扩大。"
    }
    $after = Enter-TicketboxC07CurrentWriterDatabaseFence `
        -Authority $Authority `
        -AuthorityPhase $authorityPhase
    if (-not (Test-TicketboxC07WriterFenceRoleIdentitySetEquals `
        -Left @($Intent.Roles) `
        -Right @($after.Roles))) {
        throw "C07 writer-fence reconcile 改变了 role identity set。"
    }
    return $after
}
