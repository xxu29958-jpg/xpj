#Requires -Version 5.1

function Assert-TicketboxDatabaseGenerationMaintenanceAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationExactProperties `
        $Authority `
        @(
            "Closed", "HostAuthoritySha256", "IntentSha256", "OperationId",
            "Schema", "Secret"
        ) `
        "database generation maintenance authority"
    if (
        [string]$Authority.Schema -cne
            "ticketbox-database-generation-maintenance-authority-v1" -or
        [string]$Authority.OperationId -cne
            ([guid][string]$Intent.Payload.operation_id).ToString("D") -or
        [string]$Authority.IntentSha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Authority.HostAuthoritySha256 -cne
            (Get-TicketboxDatabaseGenerationHostAuthoritySha256 $HostAuthority) -or
        [bool]$Authority.Closed
    ) {
        throw "database generation maintenance authority 已关闭或绑定漂移。"
    }
    Assert-TicketboxPostgresqlSecureString `
        $Authority.Secret `
        "database generation maintenance authority"
    return $Authority
}

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
    $cleanupFailures = @()
    try {
        [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
            $Authority $Intent $HostAuthority $LifecycleLock)
    }
    catch { $validationFailure = $_ }
    finally {
        try {
            if ($null -ne $Authority.Secret) { $Authority.Secret.Dispose() }
        }
        catch { $cleanupFailures += $_ }
        $Authority.Secret = $null
        $Authority.Closed = $true
    }
    Throw-TicketboxOperationFailure `
        $validationFailure $cleanupFailures
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
            "backup_password", "backup_scram_salt", "intent_sha256",
            "migrator_password", "migrator_scram_salt", "operation_id",
            "runtime_password", "runtime_scram_salt", "schema"
        ) `
        "database generation credentials"
    $uniqueSecretCount = @(
        @(
            [string]$artifact.Payload.runtime_password,
            [string]$artifact.Payload.migrator_password,
            [string]$artifact.Payload.backup_password
        ) | Select-Object -Unique
    ).Count
    if (
        [string]$artifact.Payload.schema -cne "ticketbox-database-generation-credentials-v2" -or
        [string]$artifact.Payload.operation_id -cne $operationId -or
        [string]$artifact.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        $uniqueSecretCount -ne 3
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
        $backupSalt = [Convert]::FromBase64String(
            [string]$artifact.Payload.backup_scram_salt
        )
    }
    catch { throw "database generation SCRAM salt 不是规范 base64。" }
    if (
        $runtimeSalt.Length -ne 16 -or $migratorSalt.Length -ne 16 -or
        $backupSalt.Length -ne 16 -or
        [Convert]::ToBase64String($runtimeSalt) -cne
            [string]$artifact.Payload.runtime_scram_salt -or
        [Convert]::ToBase64String($migratorSalt) -cne
            [string]$artifact.Payload.migrator_scram_salt -or
        [Convert]::ToBase64String($backupSalt) -cne
            [string]$artifact.Payload.backup_scram_salt
    ) {
        throw "database generation SCRAM salt 不是 canonical 16-byte 值。"
    }
    $runtimePassword = $null
    $migratorPassword = $null
    $backupPassword = $null
    $primary = $null
    $cleanup = @()
    $result = $null
    try {
        $runtimePassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.runtime_password) "runtime password"
        $migratorPassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.migrator_password) "migrator password"
        $backupPassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.backup_password) "backup password"
        $result = [pscustomobject]@{
            Artifact = $artifact
            RuntimePassword = $runtimePassword
            MigratorPassword = $migratorPassword
            BackupPassword = $backupPassword
            RuntimeVerifier = ConvertTo-TicketboxPostgresqlScramVerifier `
                -Password $runtimePassword -Salt $runtimeSalt
            MigratorVerifier = ConvertTo-TicketboxPostgresqlScramVerifier `
                -Password $migratorPassword -Salt $migratorSalt
            BackupVerifier = ConvertTo-TicketboxPostgresqlScramVerifier `
                -Password $backupPassword -Salt $backupSalt
        }
        $runtimePassword = $null
        $migratorPassword = $null
        $backupPassword = $null
    }
    catch { $primary = $_ }
    finally {
        foreach ($secret in @($runtimePassword, $migratorPassword, $backupPassword)) {
            if ($null -eq $secret) { continue }
            try { $secret.Dispose() }
            catch { $cleanup += $_ }
        }
        $runtimePassword = $null
        $migratorPassword = $null
        $backupPassword = $null
    }
    Throw-TicketboxOperationFailure $primary $cleanup
    return $result
}

function Close-TicketboxDatabaseGenerationCredentials {
    param([Parameter(Mandatory = $true)][object]$Credentials)
    $cleanupFailures = @()
    foreach ($name in @("RuntimePassword", "MigratorPassword", "BackupPassword")) {
        $secret = $Credentials.$name
        try {
            if ($null -ne $secret) { $secret.Dispose() }
        }
        catch { $cleanupFailures += $_ }
        $Credentials.$name = $null
    }
    $Credentials.RuntimeVerifier = ""
    $Credentials.MigratorVerifier = ""
    $Credentials.BackupVerifier = ""
    $Credentials.Artifact = $null
    Throw-TicketboxOperationFailure $null $cleanupFailures
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
    $backup = New-TicketboxPostgresqlRandomSecret
    while ($backup -in @($runtime, $migrator)) {
        $backup = New-TicketboxPostgresqlRandomSecret
    }
    $runtimeSalt = New-Object byte[] 16
    $migratorSalt = New-Object byte[] 16
    $backupSalt = New-Object byte[] 16
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($runtimeSalt)
        $random.GetBytes($migratorSalt)
        $random.GetBytes($backupSalt)
    }
    finally { $random.Dispose() }
    while (
        ([Convert]::ToBase64String($migratorSalt)) -ceq
        ([Convert]::ToBase64String($runtimeSalt)) -or
        ([Convert]::ToBase64String($backupSalt)) -in @(
            [Convert]::ToBase64String($runtimeSalt),
            [Convert]::ToBase64String($migratorSalt)
        )
    ) {
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $random.GetBytes($migratorSalt)
            $random.GetBytes($backupSalt)
        }
        finally { $random.Dispose() }
    }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-credentials-v2"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        runtime_password = $runtime
        runtime_scram_salt = [Convert]::ToBase64String($runtimeSalt)
        migrator_password = $migrator
        migrator_scram_salt = [Convert]::ToBase64String($migratorSalt)
        backup_password = $backup
        backup_scram_salt = [Convert]::ToBase64String($backupSalt)
    }
    [void](New-TicketboxDatabaseGenerationChainedArtifact `
        $StateRoot ([string]$Intent.Payload.operation_id) `
        "credentials" $payload $LifecycleLock)
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
            "runtime_password", "backup_password", "http_bootstrap_secret"
        ) `
        "database generation runtime credentials"
    if (
        [string]$artifact.Payload.schema -cne
            "ticketbox-database-generation-runtime-credentials-v2" -or
        [string]$artifact.Payload.operation_id -cne $operationId -or
        [string]$artifact.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$artifact.Payload.candidate_sha256 -cne [string]$Candidate.PayloadSha256 -or
        [string]$artifact.Payload.runtime_password -cnotmatch '^[A-Za-z0-9_-]{32,128}$' -or
        [string]$artifact.Payload.backup_password -cnotmatch '^[A-Za-z0-9_-]{32,128}$' -or
        [string]$artifact.Payload.backup_password -ceq [string]$artifact.Payload.runtime_password -or
        [string]$artifact.Payload.http_bootstrap_secret -cnotmatch '^[A-Za-z0-9_-]{32,128}$'
    ) {
        throw "database generation runtime credentials 未绑定 exact candidate。"
    }
    $runtimePassword = $null
    $backupPassword = $null
    $httpBootstrapSecret = $null
    $primary = $null
    $cleanup = @()
    $result = $null
    try {
        $runtimePassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.runtime_password) "runtime password"
        $backupPassword = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.backup_password) "backup password"
        $httpBootstrapSecret = ConvertTo-TicketboxPostgresqlSecureString `
            ([string]$artifact.Payload.http_bootstrap_secret) "HTTP bootstrap secret"
        $result = [pscustomobject]@{
            Artifact = $artifact
            RuntimePassword = $runtimePassword
            BackupPassword = $backupPassword
            HttpBootstrapSecret = $httpBootstrapSecret
        }
        $runtimePassword = $null
        $backupPassword = $null
        $httpBootstrapSecret = $null
    }
    catch { $primary = $_ }
    finally {
        foreach ($secret in @($runtimePassword, $backupPassword, $httpBootstrapSecret)) {
            if ($null -eq $secret) { continue }
            try { $secret.Dispose() }
            catch { $cleanup += $_ }
        }
        $runtimePassword = $null
        $backupPassword = $null
        $httpBootstrapSecret = $null
    }
    Throw-TicketboxOperationFailure $primary $cleanup
    return $result
}

function Close-TicketboxDatabaseGenerationRuntimeCredentials {
    param([Parameter(Mandatory = $true)][object]$Credentials)
    $cleanupFailures = @()
    foreach ($name in @("RuntimePassword", "BackupPassword", "HttpBootstrapSecret")) {
        $secret = $Credentials.$name
        try {
            if ($null -ne $secret) { $secret.Dispose() }
        }
        catch { $cleanupFailures += $_ }
        $Credentials.$name = $null
    }
    $Credentials.Artifact = $null
    Throw-TicketboxOperationFailure $null $cleanupFailures
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
    $backupPassword = ""
    try {
        $runtimePassword = Invoke-TicketboxWithPlainPostgresqlSecret `
            -Secret $Credentials.RuntimePassword `
            -Action ({ param([string]$PlainPassword) return $PlainPassword })
        $backupPassword = Invoke-TicketboxWithPlainPostgresqlSecret `
            -Secret $Credentials.BackupPassword `
            -Action ({ param([string]$PlainPassword) return $PlainPassword })
        $payload = [ordered]@{
            schema = "ticketbox-database-generation-runtime-credentials-v2"
            operation_id = [string]$Intent.Payload.operation_id
            intent_sha256 = [string]$Intent.PayloadSha256
            candidate_sha256 = [string]$Candidate.PayloadSha256
            runtime_password = $runtimePassword
            backup_password = $backupPassword
            http_bootstrap_secret = $HttpBootstrapSecret
        }
        [void](New-TicketboxDatabaseGenerationChainedArtifact `
            $StateRoot ([string]$Intent.Payload.operation_id) `
            "runtime-credentials" $payload $LifecycleLock)
    }
    finally {
        $runtimePassword = ""
        $backupPassword = ""
    }
    return Read-TicketboxDatabaseGenerationRuntimeCredentials `
        $StateRoot $Intent $Candidate
}
