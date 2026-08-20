#Requires -Version 5.1

function New-TicketboxDatabaseGenerationMaintenanceAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][string]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    if ($SuperuserPassword -cnotmatch '^[A-Za-z0-9_-]{32,128}$') {
        throw "PostgreSQL bootstrap superuser password 不是受控 secret。"
    }
    return [pscustomobject][ordered]@{
        Schema = "ticketbox-database-generation-maintenance-authority-v1"
        OperationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
        IntentSha256 = [string]$Intent.PayloadSha256
        HostAuthoritySha256 = Get-TicketboxDatabaseGenerationHostAuthoritySha256 $HostAuthority
        Secret = ConvertTo-TicketboxPostgresqlSecureString `
            $SuperuserPassword `
            "PostgreSQL bootstrap superuser password"
        Closed = $false
    }
}

function Close-TicketboxDatabaseGenerationMaintenanceAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if ([bool]$Authority.Closed) {
        if ($null -ne $Authority.Secret) {
            throw "closed database generation maintenance authority 仍持有 secret。"
        }
        return
    }
    $validationFailure = $null
    try {
        [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
            $Authority $Intent $HostAuthority $LifecycleLock)
    }
    catch { $validationFailure = $_ }
    finally {
        if ($null -ne $Authority.Secret) { $Authority.Secret.Dispose() }
        $Authority.Secret = $null
        $Authority.Closed = $true
    }
    if ($null -ne $validationFailure) { throw $validationFailure }
}

function Read-TicketboxDatabaseGenerationCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [switch]$AllowAbsent
    )
    $operationId = [string]$Intent.Payload.operation_id
    $artifact = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "credentials" -AllowAbsent:$AllowAbsent
    if ($null -eq $artifact) { return $null }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $artifact.Payload `
        @(
            "intent_sha256", "migrator_password", "migrator_scram_salt",
            "operation_id", "runtime_password", "runtime_scram_salt", "schema"
        ) `
        "database generation credentials"
    if (
        [string]$artifact.Payload.schema -cne "ticketbox-database-generation-credentials-v1" -or
        [string]$artifact.Payload.operation_id -cne $operationId -or
        [string]$artifact.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$artifact.Payload.runtime_password -ceq [string]$artifact.Payload.migrator_password
    ) {
        throw "database generation credentials 未绑定 exact intent。"
    }
    try {
        $runtimeSalt = [Convert]::FromBase64String(
            [string]$artifact.Payload.runtime_scram_salt
        )
        $migratorSalt = [Convert]::FromBase64String(
            [string]$artifact.Payload.migrator_scram_salt
        )
    }
    catch { throw "database generation SCRAM salt 不是规范 base64。" }
    if (
        $runtimeSalt.Length -ne 16 -or $migratorSalt.Length -ne 16 -or
        [Convert]::ToBase64String($runtimeSalt) -cne
            [string]$artifact.Payload.runtime_scram_salt -or
        [Convert]::ToBase64String($migratorSalt) -cne
            [string]$artifact.Payload.migrator_scram_salt
    ) {
        throw "database generation SCRAM salt 不是 canonical 16-byte 值。"
    }
    $runtimePassword = $null
    $migratorPassword = $null
    try {
        $runtimePassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.runtime_password) "runtime password"
        $migratorPassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.migrator_password) "migrator password"
        $result = [pscustomobject]@{
            Artifact = $artifact
            RuntimePassword = $runtimePassword
            MigratorPassword = $migratorPassword
            RuntimeVerifier = ConvertTo-TicketboxPostgresqlScramVerifier `
                -Password $runtimePassword -Salt $runtimeSalt
            MigratorVerifier = ConvertTo-TicketboxPostgresqlScramVerifier `
                -Password $migratorPassword -Salt $migratorSalt
        }
        $runtimePassword = $null
        $migratorPassword = $null
        return $result
    }
    finally {
        if ($null -ne $runtimePassword) { $runtimePassword.Dispose() }
        if ($null -ne $migratorPassword) { $migratorPassword.Dispose() }
    }
}

function Close-TicketboxDatabaseGenerationCredentials {
    param([Parameter(Mandatory = $true)][object]$Credentials)
    foreach ($name in @("RuntimePassword", "MigratorPassword")) {
        $secret = $Credentials.$name
        if ($null -ne $secret) { $secret.Dispose() }
        $Credentials.$name = $null
    }
    $Credentials.RuntimeVerifier = ""
    $Credentials.MigratorVerifier = ""
    $Credentials.Artifact = $null
}

function New-TicketboxDatabaseGenerationCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $existing = Read-TicketboxDatabaseGenerationCredentials `
        -StateRoot $StateRoot -Intent $Intent -AllowAbsent
    if ($null -ne $existing) { return $existing }
    $runtime = New-TicketboxPostgresqlRandomSecret
    $migrator = New-TicketboxPostgresqlRandomSecret
    while ($migrator -ceq $runtime) {
        $migrator = New-TicketboxPostgresqlRandomSecret
    }
    $runtimeSalt = New-Object byte[] 16
    $migratorSalt = New-Object byte[] 16
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($runtimeSalt)
        $random.GetBytes($migratorSalt)
    }
    finally { $random.Dispose() }
    while (
        ([Convert]::ToBase64String($migratorSalt)) -ceq
        ([Convert]::ToBase64String($runtimeSalt))
    ) {
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($migratorSalt) }
        finally { $random.Dispose() }
    }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-credentials-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        runtime_password = $runtime
        runtime_scram_salt = [Convert]::ToBase64String($runtimeSalt)
        migrator_password = $migrator
        migrator_scram_salt = [Convert]::ToBase64String($migratorSalt)
    }
    $path = Get-TicketboxDatabaseGenerationArtifactPath `
        $StateRoot "credentials" ([string]$Intent.Payload.operation_id)
    [void](Write-TicketboxDatabaseGenerationEnvelope `
        $path "credentials" $payload $LifecycleLock)
    return Read-TicketboxDatabaseGenerationCredentials `
        -StateRoot $StateRoot -Intent $Intent
}

function Remove-TicketboxDatabaseGenerationCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Get-TicketboxDatabaseGenerationArtifactPath `
        $StateRoot "credentials" ([string]$Intent.Payload.operation_id)
    if ((Get-TicketboxPathEntryKindNoFollow $path) -ceq "Missing") { return }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
}

function Read-TicketboxDatabaseGenerationRuntimeCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [switch]$AllowAbsent
    )
    $operationId = [string]$Intent.Payload.operation_id
    $artifact = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "runtime-credentials" -AllowAbsent:$AllowAbsent
    if ($null -eq $artifact) { return $null }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $artifact.Payload `
        @(
            "schema", "operation_id", "intent_sha256", "candidate_sha256",
            "runtime_password", "http_bootstrap_secret"
        ) `
        "database generation runtime credentials"
    if (
        [string]$artifact.Payload.schema -cne
            "ticketbox-database-generation-runtime-credentials-v1" -or
        [string]$artifact.Payload.operation_id -cne $operationId -or
        [string]$artifact.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$artifact.Payload.candidate_sha256 -cne [string]$Candidate.PayloadSha256 -or
        [string]$artifact.Payload.runtime_password -cnotmatch '^[A-Za-z0-9_-]{32,128}$' -or
        [string]$artifact.Payload.http_bootstrap_secret -cnotmatch '^[A-Za-z0-9_-]{32,128}$'
    ) {
        throw "database generation runtime credentials 未绑定 exact candidate。"
    }
    $runtimePassword = $null
    $httpBootstrapSecret = $null
    try {
        $runtimePassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.runtime_password) "runtime password"
        $httpBootstrapSecret = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.http_bootstrap_secret) "HTTP bootstrap secret"
        $result = [pscustomobject]@{
            Artifact = $artifact
            RuntimePassword = $runtimePassword
            HttpBootstrapSecret = $httpBootstrapSecret
        }
        $runtimePassword = $null
        $httpBootstrapSecret = $null
        return $result
    }
    finally {
        if ($null -ne $runtimePassword) { $runtimePassword.Dispose() }
        if ($null -ne $httpBootstrapSecret) { $httpBootstrapSecret.Dispose() }
    }
}

function Close-TicketboxDatabaseGenerationRuntimeCredentials {
    param([Parameter(Mandatory = $true)][object]$Credentials)
    foreach ($name in @("RuntimePassword", "HttpBootstrapSecret")) {
        $secret = $Credentials.$name
        if ($null -ne $secret) { $secret.Dispose() }
        $Credentials.$name = $null
    }
    $Credentials.Artifact = $null
}

function New-TicketboxDatabaseGenerationRuntimeCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$Credentials,
        [Parameter(Mandatory = $true)][string]$HttpBootstrapSecret,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    if (
        [string]$Candidate.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Candidate.Payload.operation_id -cne [string]$Intent.Payload.operation_id -or
        $HttpBootstrapSecret -cnotmatch '^[A-Za-z0-9_-]{32,128}$'
    ) {
        throw "runtime credential authority 拒绝非 exact candidate/secret。"
    }
    $runtimePassword = ""
    try {
        $runtimePassword = Invoke-TicketboxWithPlainPostgresqlSecret `
            -Secret $Credentials.RuntimePassword `
            -Action ({ param([string]$PlainPassword) return $PlainPassword })
        $payload = [ordered]@{
            schema = "ticketbox-database-generation-runtime-credentials-v1"
            operation_id = [string]$Intent.Payload.operation_id
            intent_sha256 = [string]$Intent.PayloadSha256
            candidate_sha256 = [string]$Candidate.PayloadSha256
            runtime_password = $runtimePassword
            http_bootstrap_secret = $HttpBootstrapSecret
        }
        [void](New-TicketboxDatabaseGenerationChainedArtifact `
            $StateRoot ([string]$Intent.Payload.operation_id) `
            "runtime-credentials" $payload $LifecycleLock)
    }
    finally { $runtimePassword = "" }
    return Read-TicketboxDatabaseGenerationRuntimeCredentials `
        $StateRoot $Intent $Candidate
}
