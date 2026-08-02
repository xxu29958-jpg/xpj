#Requires -Version 5.1

<#
.SYNOPSIS
  Full ADR-0073 C07 BIGINT lifecycle orchestration.
.DESCRIPTION
  Loads the single shared durable-heartbeat authority implementation, then
  defines the full coordinator, stage-transition, recovery, and projection
  surface. The shared module is also the only authority implementation loaded
  by the credential-free heartbeat helper.
#>

param(
    [ValidateSet("full", "durable_heartbeat")]
    [string]$TicketboxC07DependencyProfile = "full"
)

$ticketboxC07HeartbeatAuthorityPath = Join-Path `
    $PSScriptRoot `
    "windows_c07_heartbeat_authority.ps1"
foreach ($requiredBootstrapCommand in @(
    "Assert-NoTicketboxAncestorReparsePoints",
    "Get-TicketboxPathEntryKindNoFollow"
)) {
    if (
        $null -eq (
            Get-Command `
                $requiredBootstrapCommand `
                -CommandType Function `
                -ErrorAction SilentlyContinue
        )
    ) {
        throw (
            "C07 shared authority bootstrap 缺少 installation-safety guard：" +
            $requiredBootstrapCommand
        )
    }
}
Assert-NoTicketboxAncestorReparsePoints $ticketboxC07HeartbeatAuthorityPath
if (
    (Get-TicketboxPathEntryKindNoFollow `
        $ticketboxC07HeartbeatAuthorityPath) -cne "File"
) {
    throw (
        "Windows C07 shared heartbeat authority module 不是可信普通文件：" +
        $ticketboxC07HeartbeatAuthorityPath
    )
}
. $ticketboxC07HeartbeatAuthorityPath `
    -TicketboxC07DependencyProfile $TicketboxC07DependencyProfile |
    Out-Null

function ConvertTo-TicketboxC07HostSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$ExternalValue,
        [Parameter(Mandatory = $true)][string]$FieldName
    )
    Assert-TicketboxC07LowerSha256 $ExternalValue $FieldName
    return $ExternalValue.ToUpperInvariant()
}

function New-TicketboxC07MaintenanceBudget {
    param([Parameter(Mandatory = $true)][object]$Authority)

    $heartbeat = Read-TicketboxC07Heartbeat $Authority
    $attemptSequence = [int64]$heartbeat.Payload.maintenance_attempt_sequence
    if (
        $attemptSequence -lt 1 -or
        -not [string]::IsNullOrEmpty(
            [string]$heartbeat.Payload.maintenance_attempt_failure_sha256
        )
    ) {
        throw "C07 maintenance budget 缺少 active attempt。"
    }
    $attempt = Read-TicketboxC07MaintenanceAttempt `
        -Authority $Authority `
        -AttemptId ([string]$heartbeat.Payload.maintenance_attempt_id) `
        -Sequence ([int]$attemptSequence) `
        -ExpectedPayloadSha256 (
            [string]$heartbeat.Payload.maintenance_attempt_sha256
        )
    $deadlineUtc = [DateTime]$attempt.DeadlineUtc
    $windowMilliseconds = [double](
        $script:TicketboxC07MaintenanceWindowSeconds * 1000
    )
    $capturedTick = [int64]$attempt.Payload.started_tick_count64
    $currentTick = [int64][Environment]::TickCount64
    if (
        [string]$attempt.Payload.started_boot_identity -cne
            (Get-TicketboxC07BootIdentity) -or
        $capturedTick -lt 0 -or
        $currentTick -lt $capturedTick
    ) {
        throw (
            "C07 maintenance attempt 跨越 reboot/tick rollback；" +
            "必须建立下一 attempt。"
        )
    }
    $tickRemaining = $windowMilliseconds - (
        [double]($currentTick - $capturedTick)
    )
    $durableCeiling = [double](
        [int64]$heartbeat.Payload.maintenance_remaining_ceiling_ms
    )
    $remainingAtStart = [Math]::Min(
        $windowMilliseconds,
        [Math]::Min(
            $durableCeiling,
            [Math]::Min(
                $tickRemaining,
                ($deadlineUtc - [DateTime]::UtcNow).TotalMilliseconds
            )
        )
    )
    if ($remainingAtStart -lt 1000) {
        throw "C07 whole-operation maintenance window 已耗尽。"
    }
    return [pscustomobject]@{
        OperationId = [string]$Authority.Receipt.operation_id
        AttemptId = [string]$attempt.Payload.attempt_id
        AttemptSequence = [int64]$attempt.Payload.attempt_sequence
        AttemptSha256 = [string]$attempt.PayloadSha256
        DeadlineUtc = $deadlineUtc
        RemainingAtStartMilliseconds = [double]$remainingAtStart
        Stopwatch = [Diagnostics.Stopwatch]::StartNew()
    }
}

function Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds {
    param(
        [ValidateRange(1000, 3600000)][int]$MaximumMilliseconds,
        [string]$Label = "C07 maintenance action"
    )
    if ($null -eq $script:TicketboxC07ActiveMaintenanceBudget) {
        return $MaximumMilliseconds
    }
    return Get-TicketboxC07RemainingMaintenanceMilliseconds `
        -Budget $script:TicketboxC07ActiveMaintenanceBudget `
        -MaximumMilliseconds $MaximumMilliseconds `
        -Label $Label
}

function Get-TicketboxC07BoundedMigratorValidUntilUtc {
    param(
        [Parameter(Mandatory = $true)][DateTime]$RequestedValidUntilUtc,
        [Parameter(Mandatory = $true)][object]$Budget
    )
    if ($RequestedValidUntilUtc.Kind -eq [DateTimeKind]::Unspecified) {
        throw "C07 migrator credential deadline 必须是显式 UTC 时间。"
    }
    $requestedUtc = $RequestedValidUntilUtc.ToUniversalTime()
    $operationDeadlineUtc = (
        [DateTime]$Budget.DeadlineUtc
    ).ToUniversalTime()
    $boundedUtc = if ($requestedUtc -lt $operationDeadlineUtc) {
        $requestedUtc
    }
    else {
        $operationDeadlineUtc
    }
    if ($boundedUtc -le [DateTime]::UtcNow) {
        throw "C07 migrator credential deadline 已耗尽。"
    }
    return $boundedUtc
}

function Get-TicketboxC07TerminalAuthorityArchivePath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-terminal-authority.json"
}

function Get-TicketboxC07ProjectionPath {
    return Join-Path (Get-TicketboxC07RuntimeProjectionRoot) $script:TicketboxC07ProjectionFileName
}

function Get-TicketboxC07FreshBootstrapIntentPath {
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) $script:TicketboxC07FreshBootstrapIntentFileName
}

function Get-TicketboxC07InstalledCredentialPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-installed-credentials.json"
}

function Get-TicketboxC07RuntimeReadAccount([object]$ReleaseIdentity) {
    $serviceName = [string]$ReleaseIdentity.BackendServiceName
    if ($serviceName -cnotmatch "^[A-Za-z0-9_.-]{1,128}$") {
        throw "C07 安装身份中的 backend service name 不能安全派生虚拟服务账户。"
    }
    return "NT SERVICE\$serviceName"
}

function Get-TicketboxC07CandidateReleaseIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][string]$OperationId
    )
    $identity = [pscustomobject]@{
        State = "PENDING"
        OperationId = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
        LegacyCompleted = $false
        InstallationId = ConvertTo-TicketboxC07CanonicalUuid `
            $InstallationId `
            "installation id"
        BuildManifestSha256 = [string]$Candidate.BuildManifestSha256
        BackendVersionFloor = [string]$Candidate.BackendVersionFloor
        DataRoot = [string]$Candidate.DataRoot
        InstallDir = [string]$Candidate.InstallDir
        PgServiceName = [string]$Candidate.PgServiceName
        BackendServiceName = [string]$Candidate.BackendServiceName
        PgPort = [int]$Candidate.PgPort
        BackendPort = [int]$Candidate.BackendPort
        MigrationHelperRelativePath =
            [string]$Candidate.MigrationHelperRelativePath
        MigrationHelperSize = [int64]$Candidate.MigrationHelperSize
        MigrationHelperSha256 = [string]$Candidate.MigrationHelperSha256
    }
    return New-TicketboxC07ReleaseIdentityProjection `
        -Identity $identity `
        -MigrationHelperPath ([string]$Candidate.MigrationHelperPath)
}

function Initialize-TicketboxC07ArtifactRoots([object]$ReleaseIdentity) {
    $roots = Assert-TicketboxC07ArtifactRoots $ReleaseIdentity
    $runtimeAccount = Get-TicketboxC07RuntimeReadAccount $ReleaseIdentity
    $lockGuard = Enter-TicketboxDirectoryMutationGuard -Path $roots.LockRoot
    try {
        Assert-TicketboxProtectedDirectoryAcl `
            -Path $roots.LockRoot `
            -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
            -OwnerAccount $script:TicketboxC07HostOwnerAccount
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $roots.HostRoot `
            -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
            -OwnerAccount $script:TicketboxC07HostOwnerAccount | Out-Null
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $roots.RuntimeRoot `
            -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
            -ReadExecuteAccounts @($runtimeAccount) `
            -OwnerAccount $script:TicketboxC07HostOwnerAccount | Out-Null
    }
    finally { $lockGuard.Dispose() }
    return $roots
}

function Set-TicketboxC07DatabaseAuthorityCredential(
    [Security.SecureString]$SuperuserPassword
) {
    if ($null -eq $SuperuserPassword -or $SuperuserPassword.Length -lt 1) {
        throw "C07 live PostgreSQL authority credential 缺失。"
    }
    $script:TicketboxC07DatabaseAuthorityPassword = $SuperuserPassword
}

function ConvertTo-TicketboxC07InstalledSecureString {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch "^[A-Za-z0-9]{32,1024}$") {
        throw "C07 $Label 不符合受保护随机凭据 shape。"
    }
    $secure = New-Object Security.SecureString
    foreach ($character in $Value.ToCharArray()) {
        $secure.AppendChar($character)
    }
    $secure.MakeReadOnly()
    return $secure
}

function Read-TicketboxC07FreshBootstrapIntent {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)

    $path = Get-TicketboxC07FreshBootstrapIntentPath
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "fresh_bootstrap_intent"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "mode",
            "release_fingerprint",
            "installation_id",
            "source_revision",
            "target_revision",
            "runtime_password",
            "migrator_password",
            "created_at_utc"
        ) `
        "fresh bootstrap intent"
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07FreshBootstrapIntentSchema -or
        [string]$payload.mode -cne "fresh_install" -or
        [string]$payload.release_fingerprint -cne
            [string]$ReleaseIdentity.Fingerprint -or
        [string]$payload.installation_id -cne
            [string]$ReleaseIdentity.InstallationId -or
        [string]$payload.source_revision -cne "20260722_0001" -or
        [string]$payload.target_revision -cne
            $script:TicketboxC07TargetRevision
    ) {
        throw "C07 fresh bootstrap intent 未绑定当前 release/installation。"
    }
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$payload.operation_id
    )
    $runtimePassword = ConvertTo-TicketboxC07InstalledSecureString `
        -Value ([string]$payload.runtime_password) `
        -Label "fresh runtime password"
    $migratorPassword = ConvertTo-TicketboxC07InstalledSecureString `
        -Value ([string]$payload.migrator_password) `
        -Label "fresh migrator password"
    if ([string]$payload.runtime_password -ceq [string]$payload.migrator_password) {
        throw "C07 fresh runtime 与 migrator 不得共享 credential。"
    }
    return [pscustomobject]@{
        Path = $path
        Payload = $payload
        PayloadSha256 = [string]$envelope.PayloadSha256
        OperationId = $operationId
        RuntimePassword = $runtimePassword
        MigratorPassword = $migratorPassword
    }
}

function Get-OrCreateTicketboxC07FreshBootstrapIntent {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId
    )
    [void](Assert-TicketboxC07LifecycleLease $LifecycleLock)
    $releaseIdentity = Get-TicketboxC07ReleaseIdentity `
        -DataRoot $DataRoot `
        -ExpectedInstallationOperationId $ExpectedOperationId
    Initialize-TicketboxC07ArtifactRoots $releaseIdentity | Out-Null
    $path = Get-TicketboxC07FreshBootstrapIntentPath
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07FreshBootstrapIntent $releaseIdentity
        if (
            $existing.OperationId -cne
                ([guid]$ExpectedOperationId).ToString("D")
        ) {
            throw "C07 fresh intent 与 PENDING installation operation 不一致。"
        }
        return $existing
    }
    if (Test-Path -LiteralPath (Get-TicketboxC07AuthorityPath)) {
        throw "C07 lifecycle authority 已存在，拒绝另建 fresh bootstrap intent。"
    }
    if ($null -eq (Get-Command New-StrongPassword -ErrorAction SilentlyContinue)) {
        throw "C07 fresh bootstrap intent 缺少系统随机凭据生成器。"
    }
    $runtimePassword = [string](New-StrongPassword)
    $migratorPassword = [string](New-StrongPassword)
    while ($migratorPassword -ceq $runtimePassword) {
        $migratorPassword = [string](New-StrongPassword)
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07FreshBootstrapIntentSchema
        operation_id = ([guid]$ExpectedOperationId).ToString("D")
        mode = "fresh_install"
        release_fingerprint = [string]$releaseIdentity.Fingerprint
        installation_id = [string]$releaseIdentity.InstallationId
        source_revision = "20260722_0001"
        target_revision = $script:TicketboxC07TargetRevision
        runtime_password = $runtimePassword
        migrator_password = $migratorPassword
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "fresh_bootstrap_intent" `
        -Payload $payload | Out-Null
    return Read-TicketboxC07FreshBootstrapIntent $releaseIdentity
}

function Read-TicketboxC07InstalledCredentials {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )
    $path = Get-TicketboxC07InstalledCredentialPath (
        [string]$Authority.Receipt.operation_id
    )
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "installed_credentials"
    $payload = $envelope.Payload
    $createdAtUtc = if ($payload.created_at_utc -is [DateTime]) {
        ([DateTime]$payload.created_at_utc).ToUniversalTime().ToString("o")
    }
    else {
        [string]$payload.created_at_utc
    }
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "mode",
            "release_fingerprint",
            "database_binding_sha256",
            "source_revision",
            "target_revision",
            "runtime_password",
            "migrator_password",
            "created_at_utc"
        ) `
        "installed credentials"
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07InstalledCredentialSchema -or
        [string]$payload.operation_id -cne
            [string]$Authority.Receipt.operation_id -or
        [string]$payload.mode -cne $Mode -or
        [string]$payload.release_fingerprint -cne
            [string]$Authority.Receipt.release_fingerprint -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        [string]$payload.source_revision -cne
            [string]$Authority.Descriptor.Payload.source_alembic_revision -or
        [string]$payload.target_revision -cne
            $script:TicketboxC07TargetRevision -or
        $createdAtUtc -cnotmatch (
            "^[0-9]{4}-[0-9]{2}-[0-9]{2}T" +
            "[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{7}Z$"
        )
    ) {
        throw "C07 installed credentials 未绑定当前 operation/database/release。"
    }
    $runtimePassword = ConvertTo-TicketboxC07InstalledSecureString `
        -Value ([string]$payload.runtime_password) `
        -Label "runtime password"
    $migratorPassword = ConvertTo-TicketboxC07InstalledSecureString `
        -Value ([string]$payload.migrator_password) `
        -Label "migrator password"
    if ([string]$payload.runtime_password -ceq [string]$payload.migrator_password) {
        throw "C07 runtime 与 migrator 不得共享 credential。"
    }
    return [pscustomobject]@{
        Path = $path
        PayloadSha256 = [string]$envelope.PayloadSha256
        RuntimePassword = $runtimePassword
        MigratorPassword = $migratorPassword
    }
}

function Get-OrCreateTicketboxC07InstalledCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $path = Get-TicketboxC07InstalledCredentialPath (
        [string]$authority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $path) {
        return Read-TicketboxC07InstalledCredentials `
            -Authority $authority `
            -Mode $Mode
    }
    if ([string]$authority.Receipt.stage -notin $script:TicketboxC07PreDdlStages) {
        throw (
            "C07 DDL 已开始但缺少原 operation 的受保护 credentials；" +
            "拒绝生成不同凭据。"
        )
    }
    if ($null -eq (Get-Command New-StrongPassword -ErrorAction SilentlyContinue)) {
        throw "C07 installed credentials 缺少系统随机凭据生成器。"
    }
    $runtimePassword = ""
    $migratorPassword = ""
    $freshIntentPath = Get-TicketboxC07FreshBootstrapIntentPath
    if ($Mode -ceq "fresh_install" -and (Test-Path -LiteralPath $freshIntentPath)) {
        $intent = Read-TicketboxC07FreshBootstrapIntent $authority.ReleaseIdentity
        if ([string]$intent.OperationId -cne [string]$authority.Receipt.operation_id) {
            throw "C07 fresh bootstrap intent 与 captured operation 不一致。"
        }
        $runtimePassword = [string]$intent.Payload.runtime_password
        $migratorPassword = [string]$intent.Payload.migrator_password
    }
    else {
        $runtimePassword = [string](New-StrongPassword)
        $migratorPassword = [string](New-StrongPassword)
        while ($migratorPassword -ceq $runtimePassword) {
            $migratorPassword = [string](New-StrongPassword)
        }
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07InstalledCredentialSchema
        operation_id = [string]$authority.Receipt.operation_id
        mode = $Mode
        release_fingerprint = [string]$authority.Receipt.release_fingerprint
        database_binding_sha256 =
            [string]$authority.Receipt.database_binding_sha256
        source_revision =
            [string]$authority.Descriptor.Payload.source_alembic_revision
        target_revision = $script:TicketboxC07TargetRevision
        runtime_password = $runtimePassword
        migrator_password = $migratorPassword
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "installed_credentials" `
        -Payload $payload | Out-Null
    return Read-TicketboxC07InstalledCredentials `
        -Authority $authority `
        -Mode $Mode
}

function Remove-TicketboxC07InstalledCredentials {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    if ([string]$authority.Receipt.stage -cne "ready") {
        throw "C07 installed credentials 只能在 durable READY 后清理。"
    }
    $credentials = Read-TicketboxC07InstalledCredentials `
        -Authority $authority `
        -Mode $Mode
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $credentials.Path `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    if (Test-Path -LiteralPath $credentials.Path) {
        throw "C07 installed credentials READY 后清理失败。"
    }
}

function Remove-TicketboxC07FreshBootstrapIntent {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    if ([string]$authority.Receipt.stage -cne "ready") {
        throw "C07 fresh bootstrap intent 只能在 durable READY 后清理。"
    }
    $intent = Read-TicketboxC07FreshBootstrapIntent $authority.ReleaseIdentity
    if ([string]$intent.OperationId -cne [string]$authority.Receipt.operation_id) {
        throw "C07 fresh bootstrap intent 不属于 READY operation。"
    }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $intent.Path `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    if (Test-Path -LiteralPath $intent.Path) {
        throw "C07 fresh bootstrap intent READY 后清理失败。"
    }
}

function Get-TicketboxC07DatabaseAuthorityCredential {
    if ($null -eq $script:TicketboxC07DatabaseAuthorityPassword) {
        throw "C07 live PostgreSQL authority 尚未在本 coordinator 进程中建立。"
    }
    return $script:TicketboxC07DatabaseAuthorityPassword
}

function Get-TicketboxC07LiveDatabaseAuthority {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)
    $password = Get-TicketboxC07DatabaseAuthorityCredential
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $hostAuthority $password
    $sql = @"
SELECT
    control.system_identifier::text || E'\t' ||
    database.oid::text || E'\t' ||
    current_database() || E'\t' ||
    current_setting('server_version_num') || E'\t' ||
    COALESCE((
        SELECT value FROM public.app_meta WHERE key = 'server_id'
    ), '') || E'\t' ||
    COALESCE((
        SELECT value FROM public.app_meta WHERE key = 'data_generation'
    ), '') || E'\t' ||
    COALESCE((
        SELECT string_agg(version_num, ',' ORDER BY version_num)
        FROM public.alembic_version
    ), '') || E'\t' ||
    COALESCE(shobj_description(database.oid, 'pg_database'), '')
FROM pg_control_system() AS control
JOIN pg_database AS database ON database.datname = current_database();
"@
    $output = Invoke-TicketboxC07Sql `
        -Authority $hostAuthority `
        -Database "ticketbox" `
        -Role "postgres" `
        -Password $password `
        -Sql $sql `
        -Label "C07 live database authority inspect"
    $lines = @(
        $output -split "`r?`n" |
            ForEach-Object { [string]$_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($lines.Count -ne 1) {
        throw "C07 live database authority 未返回唯一结果。"
    }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne 8) {
        throw "C07 live database authority 字段数量异常。"
    }
    if ($fields[0] -cnotmatch "^[0-9]{10,32}$") {
        throw "C07 PostgreSQL cluster system identifier 无效。"
    }
    $databaseOid = [uint32]0
    $serverVersion = 0
    if (
        -not [uint32]::TryParse($fields[1], [ref]$databaseOid) -or
        $databaseOid -lt 1 -or
        -not [int]::TryParse($fields[3], [ref]$serverVersion) -or
        $serverVersion -lt 170000 -or $serverVersion -ge 180000
    ) {
        throw "C07 live PostgreSQL 必须是可识别的 PG17 database identity。"
    }
    $serverId = ConvertTo-TicketboxC07CanonicalUuid $fields[4] "logical server_id"
    $dataGeneration = ConvertTo-TicketboxC07CanonicalUuid `
        $fields[5] `
        "logical data_generation"
    $heads = @()
    if (-not [string]::IsNullOrEmpty($fields[6])) {
        $heads = @($fields[6].Split([char]","))
    }
    if (
        $heads.Count -ne 1 -or
        [string]$heads[0] -cnotmatch "^[A-Za-z0-9_]{1,128}$"
    ) {
        throw "C07 live PostgreSQL 必须具有唯一规范 Alembic head。"
    }
    $identityText = [string]::Join("`n", @(
        "schema=$script:TicketboxC07DatabaseAuthoritySchema",
        "installation_id=$($ReleaseIdentity.InstallationId)",
        "cluster_system_identifier=$($fields[0])",
        "database_name=$($fields[2])",
        "database_oid=$databaseOid",
        "logical_server_id=$serverId",
        "data_generation=$dataGeneration"
    )) + "`n"
    return [pscustomobject]@{
        Schema = $script:TicketboxC07DatabaseAuthoritySchema
        ClusterSystemIdentifier = [string]$fields[0]
        DatabaseName = [string]$fields[2]
        DatabaseOid = $databaseOid
        ServerVersionNum = $serverVersion
        ServerId = $serverId
        DataGeneration = $dataGeneration
        AlembicHeads = @($heads)
        Fingerprint = Get-TicketboxC07TextSha256 $identityText
        ProductionMarker = [string]$fields[7]
        ProductionMarkerSha256 = if ([string]::IsNullOrEmpty($fields[7])) {
            ""
        }
        else {
            Get-TicketboxC07TextSha256 ([string]$fields[7])
        }
    }
}

function Get-TicketboxC07WriterDatabaseFenceObservation {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)
    $password = Get-TicketboxC07DatabaseAuthorityCredential
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $hostAuthority $password
    $nativeTimeoutMilliseconds =
        Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
            -MaximumMilliseconds 30000 `
            -Label "C07 writer-fence observation"
    $statementTimeoutMilliseconds = [Math]::Min(
        5000,
        $nativeTimeoutMilliseconds
    )
    $lockTimeoutMilliseconds = [Math]::Min(
        1000,
        $statementTimeoutMilliseconds
    )
    $sql = @"
SET application_name = 'ticketbox-c07-fence-observation';
SET statement_timeout = '$($statementTimeoutMilliseconds)ms';
SET lock_timeout = '$($lockTimeoutMilliseconds)ms';
SELECT pg_stat_clear_snapshot();
WITH database_record AS (
    SELECT oid, datacl, datdba
    FROM pg_database
    WHERE datname = current_database()
),
advisory_acquire AS MATERIALIZED (
    SELECT pg_try_advisory_lock(
        hashtext(current_database()),
        hashtext('xiaopiaojia:schema')
    ) AS held
),
user_roles AS MATERIALIZED (
    SELECT
        role.oid,
        role.rolname,
        role.rolcanlogin,
        role.rolconnlimit,
        role.rolsuper,
        role.rolcreatedb,
        role.rolcreaterole,
        role.rolreplication,
        role.rolbypassrls,
        role.oid = database_record.datdba AS is_database_owner,
        EXISTS (
            SELECT 1
            FROM pg_namespace AS namespace
            WHERE namespace.nspname = 'public'
              AND namespace.nspowner = role.oid
        ) AS owns_public_schema,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'f', 'S')
              AND relation.relowner = role.oid
        ) AS owns_user_relations,
        EXISTS (
            SELECT 1
            FROM aclexplode(
                COALESCE(
                    database_record.datacl,
                    acldefault('d', database_record.datdba)
                )
            ) AS privilege
            WHERE privilege.grantee = role.oid
              AND privilege.privilege_type = 'CONNECT'
        ) AS direct_connect,
        has_database_privilege(
            role.oid,
            database_record.oid,
            'CONNECT'
        ) AS effective_connect,
        has_database_privilege(
            role.oid,
            database_record.oid,
            'CREATE'
        ) AS can_database_create,
        has_schema_privilege(
            role.oid,
            'public',
            'CREATE'
        ) AS can_public_schema_create,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'f')
              AND (
                  has_table_privilege(role.oid, relation.oid, 'INSERT')
                  OR has_table_privilege(role.oid, relation.oid, 'UPDATE')
                  OR has_table_privilege(role.oid, relation.oid, 'DELETE')
                  OR has_table_privilege(role.oid, relation.oid, 'TRUNCATE')
                  OR has_table_privilege(role.oid, relation.oid, 'REFERENCES')
                  OR has_table_privilege(role.oid, relation.oid, 'TRIGGER')
              )
        ) AS can_table_write,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind = 'S'
              AND (
                  has_sequence_privilege(role.oid, relation.oid, 'USAGE')
                  OR has_sequence_privilege(role.oid, relation.oid, 'UPDATE')
              )
        ) AS can_sequence_write,
        EXISTS (
            SELECT 1
            FROM (
                SELECT database_record.datdba AS owner_oid
                UNION
                SELECT namespace.nspowner
                FROM pg_namespace AS namespace
                WHERE namespace.nspname = 'public'
                UNION
                SELECT relation.relowner
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'f', 'S')
            ) AS write_owner
            WHERE write_owner.owner_oid <> role.oid
              AND pg_has_role(role.oid, write_owner.owner_oid, 'MEMBER')
        ) AS can_assume_write_owner
    FROM pg_roles AS role
    CROSS JOIN database_record
    CROSS JOIN advisory_acquire
    WHERE role.rolname !~ '^pg_'
      AND advisory_acquire.held
),
public_privilege AS MATERIALIZED (
    SELECT EXISTS (
        SELECT 1
        FROM database_record
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                database_record.datacl,
                acldefault('d', database_record.datdba)
            )
        ) AS privilege
        WHERE privilege.grantee = 0
          AND privilege.privilege_type = 'CONNECT'
    ) AS direct_connect
    FROM advisory_acquire
    WHERE advisory_acquire.held
),
session_observation AS MATERIALIZED (
    SELECT
        count(*) AS session_count,
        COALESCE(
            json_agg(
                json_build_object(
                    'pid', pid,
                    'role', usename,
                    'application_name', application_name,
                    'state', state
                )
                ORDER BY pid
            ),
            '[]'::json
        ) AS sessions
    FROM pg_stat_activity
    CROSS JOIN advisory_acquire
    WHERE datid = (SELECT oid FROM database_record)
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      AND advisory_acquire.held
),
writer_catalog_observation AS MATERIALIZED (
    SELECT
        current_setting('max_prepared_transactions')::bigint
            AS max_prepared_transactions,
        (
            SELECT count(*)
            FROM pg_prepared_xacts
            WHERE database = current_database()
        ) AS prepared_transaction_count,
        (
            SELECT count(*)
            FROM pg_subscription
            WHERE subdbid = (SELECT oid FROM database_record)
        ) AS logical_subscription_count,
        (
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datid = (SELECT oid FROM database_record)
              AND pid <> pg_backend_pid()
              AND backend_type = 'logical replication worker'
        ) AS logical_apply_worker_count,
        (
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datid = (SELECT oid FROM database_record)
              AND pid <> pg_backend_pid()
              AND backend_type NOT IN (
                  'client backend',
                  'autovacuum worker',
                  'parallel worker'
              )
        ) AS unexpected_database_worker_count
    FROM advisory_acquire
    WHERE advisory_acquire.held
),
advisory_release AS MATERIALIZED (
    SELECT CASE
        WHEN held
          AND (SELECT count(*) FROM user_roles) >= 0
          AND (SELECT count(*) FROM public_privilege) = 1
          AND (
              SELECT session_count FROM session_observation
          ) >= 0
          AND (SELECT count(*) FROM writer_catalog_observation) = 1
        THEN pg_advisory_unlock(
            hashtext(current_database()),
            hashtext('xiaopiaojia:schema')
        )
        ELSE false
    END AS released
    FROM advisory_acquire
)
SELECT json_build_object(
    'public_connect', (SELECT direct_connect FROM public_privilege),
    'client_session_count', (SELECT session_count FROM session_observation),
    'client_sessions', (SELECT sessions FROM session_observation),
    'max_prepared_transactions', (
        SELECT max_prepared_transactions FROM writer_catalog_observation
    ),
    'prepared_transaction_count', (
        SELECT prepared_transaction_count FROM writer_catalog_observation
    ),
    'logical_subscription_count', (
        SELECT logical_subscription_count FROM writer_catalog_observation
    ),
    'logical_apply_worker_count', (
        SELECT logical_apply_worker_count FROM writer_catalog_observation
    ),
    'unexpected_database_worker_count', (
        SELECT unexpected_database_worker_count
        FROM writer_catalog_observation
    ),
    'advisory_available', (SELECT held FROM advisory_acquire),
    'advisory_released', (SELECT released FROM advisory_release),
    'roles', COALESCE(
        (
            SELECT json_agg(
                json_build_object(
                    'name', rolname,
                    'oid', oid,
                    'can_login', rolcanlogin,
                    'connection_limit', rolconnlimit,
                    'is_superuser', rolsuper,
                    'can_create_db', rolcreatedb,
                    'can_create_role', rolcreaterole,
                    'can_replicate', rolreplication,
                    'can_bypass_rls', rolbypassrls,
                    'is_database_owner', is_database_owner,
                    'owns_public_schema', owns_public_schema,
                    'owns_user_relations', owns_user_relations,
                    'direct_connect', direct_connect,
                    'effective_connect', effective_connect,
                    'can_database_create', can_database_create,
                    'can_public_schema_create', can_public_schema_create,
                    'can_table_write', can_table_write,
                    'can_sequence_write', can_sequence_write,
                    'can_assume_write_owner', can_assume_write_owner
                )
                ORDER BY rolname
            )
            FROM user_roles
        ),
        '[]'::json
    )
);
"@
    $output = Invoke-TicketboxC07Sql `
        -Authority $hostAuthority `
        -Database "ticketbox" `
        -Role "postgres" `
        -Password $password `
        -Sql $sql `
        -Label "C07 writer session and advisory fence inspect" `
        -TimeoutMilliseconds $nativeTimeoutMilliseconds
    try {
        $payload = ConvertFrom-TicketboxC07JsonText `
            -Text ([string]$output).Trim() `
            -Label "PostgreSQL writer-fence observation"
    }
    catch { throw "C07 PostgreSQL writer-fence observation 不是 JSON。" }
    Assert-TicketboxC07ExactProperties `
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
        "writer-fence observation"
    $roles = @($payload.roles)
    if (
        $payload.public_connect -isnot [bool] -or
        $payload.advisory_available -isnot [bool] -or
        $payload.advisory_released -isnot [bool] -or
        (
            $payload.client_session_count -isnot [int] -and
            $payload.client_session_count -isnot [long]
        ) -or
        [int64]$payload.client_session_count -lt 0 -or
        [int64]$payload.max_prepared_transactions -ne 0 -or
        [int64]$payload.prepared_transaction_count -ne 0 -or
        [int64]$payload.logical_subscription_count -ne 0 -or
        [int64]$payload.logical_apply_worker_count -ne 0 -or
        [int64]$payload.unexpected_database_worker_count -ne 0 -or
        -not [bool]$payload.advisory_available -or
        -not [bool]$payload.advisory_released -or
        $roles.Count -lt 2 -or
        $roles.Count -gt 128
    ) {
        throw "C07 PostgreSQL session/fence observation 无效或 migration lease 忙。"
    }
    $validatedSessions = @()
    foreach ($session in @($payload.client_sessions)) {
        Assert-TicketboxC07ExactProperties `
            $session `
            @("pid", "role", "application_name", "state") `
            "writer-fence client session observation"
        $sessionPid = 0
        if (
            -not [int]::TryParse([string]$session.pid, [ref]$sessionPid) -or
            $sessionPid -lt 1 -or
            [string]::IsNullOrEmpty([string]$session.role) -or
            ([string]$session.role).Length -gt 63 -or
            ([string]$session.application_name).Length -gt 63 -or
            ([string]$session.state).Length -gt 64
        ) {
            throw "C07 PostgreSQL client session observation 无效。"
        }
        $validatedSessions += [pscustomobject][ordered]@{
            pid = $sessionPid
            role = [string]$session.role
            application_name = [string]$session.application_name
            state = [string]$session.state
        }
    }
    if ($validatedSessions.Count -ne [int64]$payload.client_session_count) {
        throw "C07 PostgreSQL client session count/set 不一致。"
    }
    $validatedRoles = @()
    foreach ($role in $roles) {
        Assert-TicketboxC07ExactProperties `
            $role `
            @(
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
                "owns_public_schema",
                "owns_user_relations",
                "direct_connect",
                "effective_connect",
                "can_database_create",
                "can_public_schema_create",
                "can_table_write",
                "can_sequence_write",
                "can_assume_write_owner"
            ) `
            "writer-fence role observation"
        $roleOid = [int64]0
        $connectionLimit = 0
        if (
            -not [int64]::TryParse([string]$role.oid, [ref]$roleOid) -or
            $roleOid -lt 1 -or
            $role.can_login -isnot [bool] -or
            -not [int]::TryParse(
                [string]$role.connection_limit,
                [ref]$connectionLimit
            ) -or
            $role.direct_connect -isnot [bool] -or
            $role.effective_connect -isnot [bool] -or
            @(
                "is_superuser",
                "can_create_db",
                "can_create_role",
                "can_replicate",
                "can_bypass_rls",
                "is_database_owner",
                "owns_public_schema",
                "owns_user_relations",
                "can_database_create",
                "can_public_schema_create",
                "can_table_write",
                "can_sequence_write",
                "can_assume_write_owner"
            ).Where({ $role.$_ -isnot [bool] }).Count -ne 0
        ) {
            throw "C07 PostgreSQL writer-fence role observation 无效。"
        }
        $disposition = switch -CaseSensitive ([string]$role.name) {
            "postgres" { "database_authority"; break }
            $script:TicketboxC07MigratorRole {
                "migration_authority"
                break
            }
            $script:TicketboxC07OwnerRole { "nologin_owner"; break }
            $script:TicketboxC07LegacyRuntimeRole {
                "fenced_runtime"
                break
            }
            $script:TicketboxC07RuntimeRole { "fenced_runtime"; break }
            default { "inert_unregistered" }
        }
        $elevated = (
            [bool]$role.is_superuser -or
            [bool]$role.can_create_db -or
            [bool]$role.can_create_role -or
            [bool]$role.can_replicate -or
            [bool]$role.can_bypass_rls
        )
        $writeAuthority = (
            [bool]$role.is_database_owner -or
            [bool]$role.owns_public_schema -or
            [bool]$role.owns_user_relations -or
            [bool]$role.can_database_create -or
            [bool]$role.can_public_schema_create -or
            [bool]$role.can_table_write -or
            [bool]$role.can_sequence_write -or
            [bool]$role.can_assume_write_owner
        )
        if (
            (
                $disposition -ceq "database_authority" -and
                (
                    -not [bool]$role.can_login -or
                    -not [bool]$role.is_superuser
                )
            ) -or
            (
                $disposition -ceq "migration_authority" -and
                (
                    -not [bool]$role.can_login -or
                    $elevated
                )
            ) -or
            (
                $disposition -ceq "nologin_owner" -and
                ([bool]$role.can_login -or $elevated)
            ) -or
            (
                $disposition -ceq "fenced_runtime" -and
                $elevated
            ) -or
            (
                $disposition -ceq "inert_unregistered" -and
                (
                    [bool]$role.can_login -or
                    [bool]$role.direct_connect -or
                    $elevated -or
                    $writeAuthority
                )
            )
        ) {
            throw (
                "C07 检测到未登记或越权 PostgreSQL writer/owner/superuser " +
                "role，拒绝接管。"
            )
        }
        $validatedRoles += [pscustomobject][ordered]@{
            name = [string]$role.name
            oid = $roleOid
            disposition = $disposition
            can_login = [bool]$role.can_login
            connection_limit = $connectionLimit
            is_superuser = [bool]$role.is_superuser
            can_create_db = [bool]$role.can_create_db
            can_create_role = [bool]$role.can_create_role
            can_replicate = [bool]$role.can_replicate
            can_bypass_rls = [bool]$role.can_bypass_rls
            is_database_owner = [bool]$role.is_database_owner
            owns_public_schema = [bool]$role.owns_public_schema
            owns_user_relations = [bool]$role.owns_user_relations
            direct_connect = [bool]$role.direct_connect
            effective_connect = [bool]$role.effective_connect
            can_database_create = [bool]$role.can_database_create
            can_public_schema_create = [bool]$role.can_public_schema_create
            can_table_write = [bool]$role.can_table_write
            can_sequence_write = [bool]$role.can_sequence_write
            can_assume_write_owner = [bool]$role.can_assume_write_owner
        }
    }
    if (
        @(
            $validatedRoles |
                Where-Object {
                    $_.disposition -ceq "database_authority"
                }
        ).Count -ne 1
    ) {
        throw "C07 PostgreSQL 缺少唯一受管 database authority role。"
    }
    if (
        @(
            $validatedRoles |
                Where-Object { $_.disposition -ceq "fenced_runtime" }
        ).Count -lt 1
    ) {
        throw "C07 PostgreSQL 缺少受管 runtime writer role。"
    }
    return [pscustomobject]@{
        PublicConnect = [bool]$payload.public_connect
        OtherClientSessionCount = [int64]$payload.client_session_count
        ClientSessions = @($validatedSessions)
        MaxPreparedTransactions = [int64]$payload.max_prepared_transactions
        PreparedTransactionCount = [int64]$payload.prepared_transaction_count
        LogicalSubscriptionCount = [int64]$payload.logical_subscription_count
        LogicalApplyWorkerCount = [int64]$payload.logical_apply_worker_count
        UnexpectedDatabaseWorkerCount =
            [int64]$payload.unexpected_database_worker_count
        AdvisoryFenceAvailable = $true
        AdvisoryFenceReleased = $true
        Roles = @($validatedRoles)
    }
}

function Test-TicketboxC07ClientSessionSetEquals {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Left,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Right
    )
    if ($Left.Count -ne $Right.Count) { return $false }
    foreach ($leftSession in $Left) {
        $matches = @(
            $Right |
                Where-Object {
                    [int]$_.pid -eq [int]$leftSession.pid -and
                    [string]$_.role -ceq [string]$leftSession.role -and
                    [string]$_.application_name -ceq
                        [string]$leftSession.application_name
                }
        )
        if ($matches.Count -ne 1) { return $false }
    }
    return $true
}

function Initialize-TicketboxC07WriterFenceIntent {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$ServiceStartPolicy,
        [Parameter(Mandatory = $true)][object]$Observation
    )
    $path = Get-TicketboxC07WriterFenceIntentPath (
        [string]$Authority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $path) {
        return Read-TicketboxC07WriterFenceIntent $Authority
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07WriterFenceIntentSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        backend_service_start_policy = $ServiceStartPolicy
        public_connect = [bool]$Observation.PublicConnect
        client_session_count_before_fence =
            [int64]$Observation.OtherClientSessionCount
        client_sessions_before_fence = @($Observation.ClientSessions)
        max_prepared_transactions =
            [int64]$Observation.MaxPreparedTransactions
        prepared_transaction_count =
            [int64]$Observation.PreparedTransactionCount
        logical_subscription_count =
            [int64]$Observation.LogicalSubscriptionCount
        logical_apply_worker_count =
            [int64]$Observation.LogicalApplyWorkerCount
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

function Enter-TicketboxC07WriterDatabaseFence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Intent
    )
    $before = Get-TicketboxC07WriterDatabaseFenceObservation `
        $Authority.ReleaseIdentity
    $expectedRoles = @($Intent.Payload.roles)
    if (
        (
            [bool]$before.PublicConnect -ne
                [bool]$Intent.Payload.public_connect -and
            [bool]$before.PublicConnect
        ) -or
        -not (
            Test-TicketboxC07WriterFenceRoleSetEquals `
                -Left $expectedRoles `
                -Right @($before.Roles) `
                -AllowFencedRight
        )
    ) {
        throw "C07 writer-fence acquire 前 live role/database ACL 已漂移。"
    }
    $password = Get-TicketboxC07DatabaseAuthorityCredential
    $hostAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $hostAuthority $password
    $databaseFenceSqlTimeout = if (
        $null -eq $script:TicketboxC07ActiveMaintenanceBudget
    ) {
        5000
    }
    else {
        Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
            -MaximumMilliseconds 5000 `
            -Label "C07 durable writer-fence SQL"
    }
    $terminationConfirmationTimeoutMilliseconds = [Math]::Max(
        1,
        [Math]::Min(
            3000,
            [Math]::Floor($databaseFenceSqlTimeout / 2)
        )
    )
    Invoke-TicketboxC07Sql `
        -Authority $hostAuthority `
        -Database "ticketbox" `
        -Role "postgres" `
        -Password $password `
        -Label "C07 durable writer fence acquire" `
        -TimeoutMilliseconds $databaseFenceSqlTimeout `
        -Sql @"
SET application_name =
    'ticketbox-c07-fence:$([string]$Authority.Receipt.operation_id)';
SET statement_timeout = '$($databaseFenceSqlTimeout)ms';
SET lock_timeout = '1000ms';
DO `$ticketbox`$
BEGIN
    IF NOT pg_try_advisory_lock(
        hashtext(current_database()),
        hashtext('xiaopiaojia:schema')
    ) THEN
        RAISE EXCEPTION 'C07 writer-fence schema lease is busy';
    END IF;
END
`$ticketbox`$;
SELECT pg_stat_clear_snapshot();
DO `$ticketbox`$
BEGIN
    IF session_user <> 'postgres' OR current_user <> 'postgres' THEN
        RAISE EXCEPTION
            'C07 writer fence is not held by the database authority session';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE datid = (
            SELECT oid FROM pg_database
            WHERE datname = '$script:TicketboxC07DatabaseName'
        )
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
          AND usename NOT IN (
              '$script:TicketboxC07LegacyRuntimeRole',
              '$script:TicketboxC07RuntimeRole'
          )
    ) THEN
        RAISE EXCEPTION
            'C07 unknown client session blocks writer-fence mutation';
    END IF;
    IF current_setting('max_prepared_transactions')::bigint <> 0
       OR EXISTS (
           SELECT 1 FROM pg_prepared_xacts
           WHERE database = current_database()
       )
       OR EXISTS (
           SELECT 1 FROM pg_subscription
           WHERE subdbid = (
               SELECT oid FROM pg_database
               WHERE datname = current_database()
           )
       )
       OR EXISTS (
           SELECT 1
           FROM pg_stat_activity
           WHERE datid = (
               SELECT oid FROM pg_database
               WHERE datname = current_database()
           )
             AND pid <> pg_backend_pid()
             AND backend_type NOT IN (
                 'client backend',
                 'autovacuum worker',
                 'parallel worker'
             )
       )
    THEN
        RAISE EXCEPTION
            'C07 prepared/logical/background writer authority is unsupported';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname !~ '^pg_'
          AND role.rolname NOT IN (
              'postgres',
              '$script:TicketboxC07LegacyRuntimeRole',
              '$script:TicketboxC07OwnerRole',
              '$script:TicketboxC07MigratorRole',
              '$script:TicketboxC07RuntimeRole'
          )
          AND (
              role.rolcanlogin
              OR role.rolsuper
              OR role.rolcreatedb
              OR role.rolcreaterole
              OR role.rolreplication
              OR role.rolbypassrls
              OR role.oid = (
                  SELECT datdba FROM pg_database
                  WHERE datname = current_database()
              )
              OR EXISTS (
                  SELECT 1
                  FROM pg_namespace AS namespace
                  WHERE namespace.nspname = 'public'
                    AND namespace.nspowner = role.oid
              )
              OR EXISTS (
                  SELECT 1
                  FROM pg_class AS relation
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = 'public'
                    AND relation.relkind IN ('r', 'p', 'f', 'S')
                    AND relation.relowner = role.oid
              )
              OR has_database_privilege(
                  role.oid,
                  current_database(),
                  'CREATE'
              )
              OR has_schema_privilege(role.oid, 'public', 'CREATE')
              OR EXISTS (
                  SELECT 1
                  FROM pg_class AS relation
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = 'public'
                    AND relation.relkind IN ('r', 'p', 'f')
                    AND (
                        has_table_privilege(role.oid, relation.oid, 'INSERT')
                        OR has_table_privilege(role.oid, relation.oid, 'UPDATE')
                        OR has_table_privilege(role.oid, relation.oid, 'DELETE')
                        OR has_table_privilege(role.oid, relation.oid, 'TRUNCATE')
                        OR has_table_privilege(role.oid, relation.oid, 'REFERENCES')
                        OR has_table_privilege(role.oid, relation.oid, 'TRIGGER')
                    )
              )
              OR EXISTS (
                  SELECT 1
                  FROM pg_class AS relation
                  JOIN pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  WHERE namespace.nspname = 'public'
                    AND relation.relkind = 'S'
                    AND (
                        has_sequence_privilege(role.oid, relation.oid, 'USAGE')
                        OR has_sequence_privilege(role.oid, relation.oid, 'UPDATE')
                    )
              )
          )
    ) THEN
        RAISE EXCEPTION
            'C07 unregistered effective writer/owner/superuser role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname <> 'postgres'
          AND (
              role.rolsuper
              OR role.rolcreatedb
              OR role.rolcreaterole
              OR role.rolreplication
              OR role.rolbypassrls
          )
    ) THEN
        RAISE EXCEPTION
            'C07 non-authority elevated role blocks writer fence';
    END IF;
END
`$ticketbox`$;
BEGIN;
DO `$ticketbox`$
DECLARE fence_role text;
BEGIN
    FOREACH fence_role IN ARRAY ARRAY[
        '$script:TicketboxC07LegacyRuntimeRole',
        '$script:TicketboxC07RuntimeRole'
    ] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = fence_role) THEN
            EXECUTE format(
                'ALTER ROLE %I NOLOGIN CONNECTION LIMIT 0',
                fence_role
            );
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM %I',
                '$script:TicketboxC07DatabaseName',
                fence_role
            );
        END IF;
    END LOOP;
END
`$ticketbox`$;
REVOKE CONNECT ON DATABASE "$script:TicketboxC07DatabaseName" FROM PUBLIC;
COMMIT;
WITH runtime_targets AS MATERIALIZED (
    SELECT pid
    FROM pg_stat_activity
    WHERE datid = (
        SELECT oid FROM pg_database
        WHERE datname = '$script:TicketboxC07DatabaseName'
    )
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      AND usename IN (
          '$script:TicketboxC07LegacyRuntimeRole',
          '$script:TicketboxC07RuntimeRole'
      )
),
terminated AS MATERIALIZED (
    SELECT pg_terminate_backend(pid) AS stopped
    FROM runtime_targets
)
SELECT count(*)::text
FROM terminated
WHERE stopped;
WITH remaining_runtime_targets AS MATERIALIZED (
    SELECT pid
    FROM pg_stat_activity
    WHERE datid = (
        SELECT oid FROM pg_database
        WHERE datname = '$script:TicketboxC07DatabaseName'
    )
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      AND usename IN (
          '$script:TicketboxC07LegacyRuntimeRole',
          '$script:TicketboxC07RuntimeRole'
      )
),
confirmed AS MATERIALIZED (
    SELECT pg_terminate_backend(
        pid,
        $terminationConfirmationTimeoutMilliseconds
    ) AS stopped
    FROM remaining_runtime_targets
)
SELECT count(*)::text
FROM confirmed
WHERE NOT stopped;
SELECT pg_stat_clear_snapshot();
DO `$ticketbox`$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE datid = (
            SELECT oid FROM pg_database
            WHERE datname = '$script:TicketboxC07DatabaseName'
        )
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
    ) THEN
        RAISE EXCEPTION
            'C07 client session appeared before writer fence completed';
    END IF;
    IF current_setting('max_prepared_transactions')::bigint <> 0
       OR EXISTS (
           SELECT 1 FROM pg_prepared_xacts
           WHERE database = current_database()
       )
       OR EXISTS (
           SELECT 1 FROM pg_subscription
           WHERE subdbid = (
               SELECT oid FROM pg_database
               WHERE datname = current_database()
           )
       )
       OR EXISTS (
           SELECT 1
           FROM pg_stat_activity
           WHERE datid = (
               SELECT oid FROM pg_database
               WHERE datname = current_database()
           )
             AND pid <> pg_backend_pid()
             AND backend_type NOT IN (
                 'client backend',
                 'autovacuum worker',
                 'parallel worker'
             )
       )
    THEN
        RAISE EXCEPTION
            'C07 prepared/logical/background writer appeared during fence';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname !~ '^pg_'
          AND role.rolname NOT IN (
              'postgres',
              '$script:TicketboxC07MigratorRole'
          )
          AND role.rolcanlogin
    ) THEN
        RAISE EXCEPTION
            'C07 writer role regained LOGIN before fence completed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS role
        WHERE role.rolname IN (
              '$script:TicketboxC07LegacyRuntimeRole',
              '$script:TicketboxC07RuntimeRole'
          )
          AND (
              role.rolcanlogin
              OR role.rolconnlimit <> 0
              OR EXISTS (
                  SELECT 1
                  FROM pg_database AS database_record
                  CROSS JOIN LATERAL aclexplode(
                      COALESCE(
                          database_record.datacl,
                          acldefault('d', database_record.datdba)
                      )
                  ) AS privilege
                  WHERE database_record.datname = current_database()
                    AND privilege.grantee = role.oid
                    AND privilege.privilege_type = 'CONNECT'
              )
          )
    ) THEN
        RAISE EXCEPTION
            'C07 durable runtime LOGIN/direct CONNECT fence is incomplete';
    END IF;
END
`$ticketbox`$;
SELECT pg_advisory_unlock(
    hashtext(current_database()),
    hashtext('xiaopiaojia:schema')
);
"@ | Out-Null
    $after = Get-TicketboxC07WriterDatabaseFenceObservation `
        $Authority.ReleaseIdentity
    Assert-TicketboxC07WriterDatabaseFence `
        -Observation $after `
        -ExpectedRoles $expectedRoles
    return $after
}

function Assert-TicketboxC07WriterDatabaseFence {
    param(
        [Parameter(Mandatory = $true)][object]$Observation,
        [Parameter(Mandatory = $true)][object[]]$ExpectedRoles,
        [object[]]$AllowedClientSessions = @()
    )
    if (
        [bool]$Observation.PublicConnect -or
        [int64]$Observation.OtherClientSessionCount -ne
            $AllowedClientSessions.Count -or
        -not (
            Test-TicketboxC07ClientSessionSetEquals `
                -Left @($AllowedClientSessions) `
                -Right @($Observation.ClientSessions)
        ) -or
        -not [bool]$Observation.AdvisoryFenceAvailable -or
        -not [bool]$Observation.AdvisoryFenceReleased -or
        [int64]$Observation.MaxPreparedTransactions -ne 0 -or
        [int64]$Observation.PreparedTransactionCount -ne 0 -or
        [int64]$Observation.LogicalSubscriptionCount -ne 0 -or
        [int64]$Observation.LogicalApplyWorkerCount -ne 0 -or
        [int64]$Observation.UnexpectedDatabaseWorkerCount -ne 0 -or
        -not (
            Test-TicketboxC07WriterFenceRoleSetEquals `
                -Left $ExpectedRoles `
                -Right @($Observation.Roles) `
                -AllowFencedRight
        )
    ) {
        throw "C07 durable writer fence 未阻断 runtime login/CONNECT/session。"
    }
    foreach ($role in @($Observation.Roles)) {
        if (
            [string]$role.disposition -ceq "fenced_runtime" -and
            (
                [bool]$role.can_login -or
                [int]$role.connection_limit -ne 0 -or
                [bool]$role.direct_connect -or
                (
                    [bool]$role.effective_connect -and
                    -not [bool]$role.is_database_owner
                )
            )
        ) {
            throw "C07 durable writer fence 的 runtime role 仍可连接写入。"
        }
        if (
            [string]$role.disposition -ceq "inert_unregistered" -and
            (
                [bool]$role.can_login -or
                [bool]$role.direct_connect -or
                [bool]$role.effective_connect -or
                [bool]$role.can_database_create -or
                [bool]$role.can_public_schema_create -or
                [bool]$role.can_table_write -or
                [bool]$role.can_sequence_write -or
                [bool]$role.can_assume_write_owner
            )
        ) {
            throw "C07 durable writer fence 检测到未登记 effective writer。"
        }
    }
}

function Assert-TicketboxC07LifecycleLease([object]$LifecycleLock) {
    if (
        $null -eq $LifecycleLock -or
        $null -eq $LifecycleLock.Operation -or
        -not [bool]$LifecycleLock.Operation.CanWrite
    ) {
        throw "C07 操作缺少仍持有的 lifecycle operation lease。"
    }
    Assert-TicketboxLifecycleLockIsHeld (Get-TicketboxLifecycleOperationLockPath)
    if ($null -ne $LifecycleLock.Primary) {
        if (-not [bool]$LifecycleLock.Primary.CanWrite) {
            throw "C07 primary lifecycle lease 不可信。"
        }
        Assert-TicketboxLifecycleLockIsHeld (Get-TicketboxLifecycleLockPath)
        return Get-TicketboxProcessIdentity -ProcessId $PID
    }
    $externalIdentity = $LifecycleLock.ExternalOwnerIdentity
    if ($null -eq $externalIdentity) {
        throw "C07 delegated lifecycle lease 缺少外部 owner identity。"
    }
    if (
        $null -ne (
            Get-Command Get-TicketboxValidatedExternalLifecycleOwnerIdentity `
                -ErrorAction SilentlyContinue
        )
    ) {
        $validated = Get-TicketboxValidatedExternalLifecycleOwnerIdentity `
            ([int]$externalIdentity.ProcessId)
        if (-not (Test-TicketboxProcessIdentityEquals $validated $externalIdentity)) {
            throw "C07 delegated lifecycle owner identity 与已验证锁身份不一致。"
        }
    }
    return $externalIdentity
}

function Assert-TicketboxC07PriorProcessIdentityDead([object]$Identity) {
    $liveProcess = Get-Process -Id ([int]$Identity.ProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $liveProcess) {
        return
    }
    try {
        $liveIdentity = Get-TicketboxProcessIdentity -ProcessId ([int]$Identity.ProcessId)
    }
    catch {
        throw "C07 无法证明旧 coordinator PID/FILETIME 已死亡，拒绝 takeover。"
    }
    if (Test-TicketboxProcessIdentityEquals $liveIdentity $Identity) {
        throw "C07 旧 coordinator PID/FILETIME 仍存活，拒绝 takeover。"
    }
}

function Initialize-TicketboxC07RecoveryEpoch([object]$ReleaseIdentity) {
    $path = Get-TicketboxC07RecoveryEpochPath
    if (Test-Path -LiteralPath $path) {
        return Read-TicketboxC07RecoveryEpoch $ReleaseIdentity
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07RecoveryEpochSchema
        installation_id = $ReleaseIdentity.InstallationId
        recovery_epoch_id = [guid]::NewGuid().ToString("D")
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "recovery_epoch" `
        -Payload $payload | Out-Null
    return Read-TicketboxC07RecoveryEpoch $ReleaseIdentity
}

function Get-TicketboxC07SuccessorOperationId {
    param(
        [Parameter(Mandatory = $true)][object]$PredecessorAuthority,
        [Parameter(Mandatory = $true)][object]$SuccessorReleaseIdentity,
        [Parameter(Mandatory = $true)][ValidateSet("pre_ddl", "forward_repair")]
        [string]$SuccessorMode,
        [Parameter(Mandatory = $true)][string]$LiveDatabaseBindingSha256
    )
    Assert-TicketboxC07Sha256 `
        $LiveDatabaseBindingSha256 `
        "successor live database binding"
    $digest = (Get-TicketboxC07TextSha256 ([string]::Join("`n", @(
        $script:TicketboxC07SuccessorIntentSchema,
        [string]$PredecessorAuthority.Receipt.operation_id,
        [string]$PredecessorAuthority.Envelope.PayloadSha256,
        [string]$PredecessorAuthority.Receipt.authority_chain_sha256,
        [string]$SuccessorReleaseIdentity.BuildManifestSha256,
        [string]$SuccessorReleaseIdentity.MigrationHelperSha256,
        $SuccessorMode,
        $LiveDatabaseBindingSha256
    )) + "`n")).ToLowerInvariant()
    return (
        $digest.Substring(0, 8) + "-" +
        $digest.Substring(8, 4) + "-5" +
        $digest.Substring(13, 3) + "-b" +
        $digest.Substring(17, 3) + "-" +
        $digest.Substring(20, 12)
    )
}

function Get-TicketboxC07PredecessorStageEvidenceSha256 {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $previousIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        [string]$Authority.Receipt.previous_stage
    )
    $stageIndex = [array]::IndexOf($script:TicketboxC07OrderedStages, $Stage)
    if ($previousIndex -lt $stageIndex -or $stageIndex -lt 1) {
        return ""
    }
    return [string](
        Read-TicketboxC07StageEvidence `
            -Authority $Authority `
            -Stage $Stage
    ).PayloadSha256
}

function Write-TicketboxC07TerminalAuthorityArchive {
    param(
        [Parameter(Mandatory = $true)][object]$PredecessorAuthority,
        [Parameter(Mandatory = $true)][object]$SuccessorIntent
    )
    $payload = $SuccessorIntent.Payload
    if (
        [string]$PredecessorAuthority.Receipt.operation_id -cne
            [string]$payload.predecessor_operation_id -or
        [string]$PredecessorAuthority.Envelope.PayloadSha256 -cne
            [string]$payload.predecessor_terminal_receipt_payload_sha256 -or
        [string]$PredecessorAuthority.Receipt.authority_chain_sha256 -cne
            [string]$payload.predecessor_terminal_authority_chain_sha256
    ) {
        throw "C07 terminal archive predecessor hash chain 与 successor intent 不一致。"
    }
    $path = Get-TicketboxC07TerminalAuthorityArchivePath (
        [string]$PredecessorAuthority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07HostEnvelope `
            -Path $path `
            -ExpectedKind "authority_receipt"
        if ($existing.Text -cne [string]$PredecessorAuthority.Envelope.Text) {
            throw "C07 immutable predecessor terminal authority archive 已分叉。"
        }
        return $existing
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text ([string]$PredecessorAuthority.Envelope.Text) `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    $persisted = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "authority_receipt"
    if ($persisted.Text -cne [string]$PredecessorAuthority.Envelope.Text) {
        throw "C07 immutable predecessor terminal authority archive 写后复读不一致。"
    }
    return $persisted
}

function Read-TicketboxC07HistoricalTerminalAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [string]$AuthorityPath = ""
    )
    if (-not [bool]$ReleaseIdentity.Historical) {
        throw "C07 historical terminal reader 拒绝执行当前 helper authority。"
    }
    if ([string]::IsNullOrEmpty($AuthorityPath)) {
        $AuthorityPath = Get-TicketboxC07AuthorityPath
    }
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $AuthorityPath `
        -ExpectedKind "authority_receipt"
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$envelope.Payload.operation_id
    )
    if ($operationId -cne [string]$ReleaseIdentity.InstallationOperationId) {
        throw "C07 historical terminal authority 与 predecessor installation operation 不一致。"
    }
    $roots = Assert-TicketboxC07ArtifactRoots $ReleaseIdentity
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $roots.HostRoot `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    $recoveryEpoch = Read-TicketboxC07RecoveryEpoch $ReleaseIdentity
    $descriptor = Read-TicketboxC07Descriptor `
        -OperationId $operationId `
        -ReleaseIdentity $ReleaseIdentity `
        -RecoveryEpoch $recoveryEpoch
    Assert-TicketboxC07ReceiptShape `
        -Receipt $envelope.Payload `
        -ReleaseIdentity $ReleaseIdentity `
        -Descriptor $descriptor `
        -RecoveryEpoch $recoveryEpoch
    if ([string]$envelope.Payload.stage -notin $script:TicketboxC07FailureStages) {
        throw "C07 successor 只能引用 immutable failure terminal。"
    }
    $binding = Read-TicketboxC07CoordinatorBinding `
        -Receipt $envelope.Payload `
        -Descriptor $descriptor
    $authority = [pscustomobject]@{
        ReleaseIdentity = $ReleaseIdentity
        Roots = $roots
        RecoveryEpoch = $recoveryEpoch
        Envelope = $envelope
        Receipt = $envelope.Payload
        Descriptor = $descriptor
        Binding = $binding
    }
    Assert-TicketboxC07LiveDatabaseBinding `
        -Descriptor $descriptor `
        -Receipt $envelope.Payload `
        -ReleaseIdentity $ReleaseIdentity | Out-Null
    if (-not [string]::IsNullOrEmpty(
        [string]$envelope.Payload.freeze_proof_sha256
    )) {
        Read-TicketboxC07FreezeProof -Authority $authority | Out-Null
    }
    $failure = Read-TicketboxC07FailureEvidence `
        -Authority $authority `
        -Stage ([string]$envelope.Payload.stage)
    if (
        [string]$failure.Payload.failure_code -cne
            [string]$envelope.Payload.failure_code
    ) {
        throw "C07 historical terminal failure evidence 已漂移。"
    }
    Read-TicketboxC07Heartbeat $authority | Out-Null
    return $authority
}

function New-TicketboxC07SuccessorIntent {
    param(
        [Parameter(Mandatory = $true)][object]$PredecessorAuthority,
        [Parameter(Mandatory = $true)][object]$SuccessorReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$LiveDatabase,
        [Parameter(Mandatory = $true)][ValidateSet("pre_ddl", "forward_repair")]
        [string]$SuccessorMode
    )
    $operationId = Get-TicketboxC07SuccessorOperationId `
        -PredecessorAuthority $PredecessorAuthority `
        -SuccessorReleaseIdentity $SuccessorReleaseIdentity `
        -SuccessorMode $SuccessorMode `
        -LiveDatabaseBindingSha256 ([string]$LiveDatabase.Fingerprint)
    if (
        [string]$SuccessorReleaseIdentity.InstallationOperationId -cne
            $operationId
    ) {
        throw "C07 successor release identity 未绑定 deterministic operation id。"
    }
    $path = Get-TicketboxC07SuccessorIntentPath $operationId
    if (Test-Path -LiteralPath $path) {
        return Read-TicketboxC07SuccessorIntent `
            -OperationId $operationId `
            -SuccessorReleaseIdentity $SuccessorReleaseIdentity
    }
    $predecessor = $PredecessorAuthority.ReleaseIdentity
    $predecessorProductionMarkerSha256 = ""
    if ($SuccessorMode -ceq "forward_repair") {
        if (
            $null -eq $LiveDatabase.PSObject.Properties["ProductionMarker"] -or
            $null -eq $LiveDatabase.PSObject.Properties["ProductionMarkerSha256"]
        ) {
            throw "C07 forward-repair live database 未返回 predecessor marker authority。"
        }
        $markerParts = @(([string]$LiveDatabase.ProductionMarker).Split([char]"|"))
        if (
            $markerParts.Count -ne 13 -or
            $markerParts[0] -cne "ticketbox-c07-production-authority-v1" -or
            $markerParts[1] -cne [string]$PredecessorAuthority.Receipt.operation_id -or
            $markerParts[3] -cnotin @(
                "migration_started",
                "migration_completed",
                "runtime_acl_verified",
                "production_ready"
            ) -or
            [string]::IsNullOrEmpty(
                [string]$LiveDatabase.ProductionMarkerSha256
            )
        ) {
            throw "C07 forward-repair live predecessor marker shape/operation 无效。"
        }
        Assert-TicketboxC07Sha256 `
            ([string]$LiveDatabase.ProductionMarkerSha256) `
            "successor predecessor production marker"
        $predecessorProductionMarkerSha256 =
            [string]$LiveDatabase.ProductionMarkerSha256
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07SuccessorIntentSchema
        successor_operation_id = $operationId
        successor_mode = $SuccessorMode
        successor_release_fingerprint =
            [string]$SuccessorReleaseIdentity.Fingerprint
        successor_build_manifest_sha256 =
            [string]$SuccessorReleaseIdentity.BuildManifestSha256
        installation_id = [string]$SuccessorReleaseIdentity.InstallationId
        data_root = [string]$SuccessorReleaseIdentity.DataRoot
        install_dir = [string]$SuccessorReleaseIdentity.InstallDir
        pg_service_name = [string]$SuccessorReleaseIdentity.PgServiceName
        backend_service_name =
            [string]$SuccessorReleaseIdentity.BackendServiceName
        pg_port = [int]$SuccessorReleaseIdentity.PgPort
        backend_port = [int]$SuccessorReleaseIdentity.BackendPort
        predecessor_operation_id =
            [string]$PredecessorAuthority.Receipt.operation_id
        predecessor_release_fingerprint = [string]$predecessor.Fingerprint
        predecessor_backend_version_floor =
            [string]$predecessor.BackendVersionFloor
        predecessor_build_manifest_sha256 =
            [string]$predecessor.BuildManifestSha256
        predecessor_migration_helper_relative_path =
            [string]$predecessor.MigrationHelperRelativePath
        predecessor_migration_helper_size =
            [int64]$predecessor.MigrationHelperSize
        predecessor_migration_helper_sha256 =
            [string]$predecessor.MigrationHelperSha256
        predecessor_terminal_receipt_payload_sha256 =
            [string]$PredecessorAuthority.Envelope.PayloadSha256
        predecessor_terminal_authority_chain_sha256 =
            [string]$PredecessorAuthority.Receipt.authority_chain_sha256
        predecessor_terminal_stage =
            [string]$PredecessorAuthority.Receipt.stage
        predecessor_failure_code =
            [string]$PredecessorAuthority.Receipt.failure_code
        predecessor_database_binding_sha256 =
            [string]$PredecessorAuthority.Receipt.database_binding_sha256
        predecessor_revision_manifest_sha256 =
            [string]$PredecessorAuthority.Descriptor.Payload.revision_manifest_sha256
        predecessor_freeze_proof_sha256 =
            [string]$PredecessorAuthority.Receipt.freeze_proof_sha256
        predecessor_recovery_epoch_id =
            [string]$PredecessorAuthority.Receipt.recovery_epoch_id
        predecessor_recovery_generation_evidence_sha256 =
            Get-TicketboxC07PredecessorStageEvidenceSha256 `
                -Authority $PredecessorAuthority `
                -Stage "recovery_generation_ready"
        predecessor_isolated_restore_evidence_sha256 =
            Get-TicketboxC07PredecessorStageEvidenceSha256 `
                -Authority $PredecessorAuthority `
                -Stage "isolated_restore_verified"
        predecessor_target_commit_evidence_sha256 =
            Get-TicketboxC07PredecessorStageEvidenceSha256 `
                -Authority $PredecessorAuthority `
                -Stage "target_committed"
        predecessor_target_recovery_generation_evidence_sha256 =
            Get-TicketboxC07PredecessorStageEvidenceSha256 `
                -Authority $PredecessorAuthority `
                -Stage "target_recovery_generation_ready"
        predecessor_target_isolated_restore_evidence_sha256 =
            Get-TicketboxC07PredecessorStageEvidenceSha256 `
                -Authority $PredecessorAuthority `
                -Stage "target_isolated_restore_verified"
        predecessor_runtime_acl_evidence_sha256 =
            Get-TicketboxC07PredecessorStageEvidenceSha256 `
                -Authority $PredecessorAuthority `
                -Stage "runtime_acl_verified"
        predecessor_production_marker_sha256 =
            $predecessorProductionMarkerSha256
        source_alembic_revision =
            [string]$PredecessorAuthority.Descriptor.Payload.source_alembic_revision
        target_alembic_revision =
            [string]$PredecessorAuthority.Descriptor.Payload.target_alembic_revision
        live_alembic_revision = [string]@($LiveDatabase.AlembicHeads)[0]
        live_database_binding_sha256 = [string]$LiveDatabase.Fingerprint
        authorized_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "successor_intent" `
        -Payload $payload | Out-Null
    return Read-TicketboxC07SuccessorIntent `
        -OperationId $operationId `
        -SuccessorReleaseIdentity $SuccessorReleaseIdentity
}

function Initialize-TicketboxC07SuccessorInstallationIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$PgPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$PgServiceName,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$BuildManifestPath,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxC07LifecycleLease $LifecycleLock | Out-Null
    $pendingPath = Get-TicketboxPendingInstallationIdentityPath $DataRoot
    $authorityPath = Get-TicketboxC07AuthorityPath
    if (
        -not (Test-Path -LiteralPath $pendingPath) -or
        -not (Test-Path -LiteralPath $authorityPath)
    ) {
        return $null
    }
    $candidate = Get-TicketboxInstallationReleaseCandidate `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -PgPort $PgPort `
        -BackendPort $BackendPort `
        -PgServiceName $PgServiceName `
        -BackendServiceName $BackendServiceName `
        -BuildManifestPath $BuildManifestPath
    $pending = Read-TicketboxPersistentInstallationIdentity `
        -DataRoot $DataRoot `
        -Pending
    Assert-TicketboxInstallationIdentityBaseMatches $pending $candidate
    $currentEnvelope = Read-TicketboxC07HostEnvelope `
        -Path $authorityPath `
        -ExpectedKind "authority_receipt"
    $currentOperationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$currentEnvelope.Payload.operation_id
    )
    $predecessor = $null
    $successorReleaseIdentity = $null
    $successorIntent = $null
    $successorMode = ""
    if ($currentOperationId -ceq [string]$pending.OperationId) {
        if (
            [string]$currentEnvelope.Payload.stage -notin
                $script:TicketboxC07FailureStages
        ) {
            return $null
        }
        $predecessorReleaseIdentity =
            Get-TicketboxC07HistoricalReleaseIdentity $pending
        $predecessor = Read-TicketboxC07HistoricalTerminalAuthority `
            -DataRoot $DataRoot `
            -ReleaseIdentity $predecessorReleaseIdentity
        $live = Get-TicketboxC07LiveDatabaseAuthority $predecessorReleaseIdentity
        $liveHead = [string]@($live.AlembicHeads)[0]
        $successorMode = if (
            [string]$predecessor.Receipt.stage -ceq "refused_pre_ddl" -and
            $liveHead -ceq
                [string]$predecessor.Descriptor.Payload.source_alembic_revision
        ) {
            "pre_ddl"
        }
        elseif (
            [string]$predecessor.Receipt.stage -ceq "repair_required" -and
            $liveHead -ceq
                [string]$predecessor.Descriptor.Payload.target_alembic_revision
        ) {
            "forward_repair"
        }
        else {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message (
                    "C07 terminal successor 无法从当前 live revision " +
                    "建立无歧义的 forward-only repair。"
                ) `
                -FailureClass "invariant" `
                -FailureCode "successor_live_revision_incompatible")
        }
        $provisionalReleaseIdentity =
            Get-TicketboxC07CandidateReleaseIdentity `
                -Candidate $candidate `
                -InstallationId ([string]$pending.InstallationId) `
                -OperationId ([string]$pending.OperationId)
        $successorOperationId = Get-TicketboxC07SuccessorOperationId `
            -PredecessorAuthority $predecessor `
            -SuccessorReleaseIdentity $provisionalReleaseIdentity `
            -SuccessorMode $successorMode `
            -LiveDatabaseBindingSha256 ([string]$live.Fingerprint)
        $successorReleaseIdentity =
            Get-TicketboxC07CandidateReleaseIdentity `
                -Candidate $candidate `
                -InstallationId ([string]$pending.InstallationId) `
                -OperationId $successorOperationId
        $successorIntent = New-TicketboxC07SuccessorIntent `
            -PredecessorAuthority $predecessor `
            -SuccessorReleaseIdentity $successorReleaseIdentity `
            -LiveDatabase $live `
            -SuccessorMode $successorMode
        Write-TicketboxC07TerminalAuthorityArchive `
            -PredecessorAuthority $predecessor `
            -SuccessorIntent $successorIntent | Out-Null
        $pending = Write-TicketboxInstallationIdentityState `
            -State "PENDING" `
            -OperationId $successorOperationId `
            -InstallationId ([string]$pending.InstallationId) `
            -Candidate $candidate `
            -ReplaceExisting
    }
    else {
        if (-not (Test-TicketboxInstallationIdentityReleaseMatches `
            $pending `
            $candidate)) {
            throw "C07 successor PENDING identity 与当前 repair build 不一致。"
        }
        $successorReleaseIdentity =
            Get-TicketboxC07CandidateReleaseIdentity `
                -Candidate $candidate `
                -InstallationId ([string]$pending.InstallationId) `
                -OperationId ([string]$pending.OperationId)
        $successorIntent = Read-TicketboxC07SuccessorIntent `
            -OperationId ([string]$pending.OperationId) `
            -SuccessorReleaseIdentity $successorReleaseIdentity
        if (
            [string]$successorIntent.Payload.predecessor_operation_id -cne
                $currentOperationId
        ) {
            throw "C07 successor PENDING 指向 foreign terminal authority。"
        }
        $predecessor = Read-TicketboxC07HistoricalTerminalAuthority `
            -DataRoot $DataRoot `
            -ReleaseIdentity $successorIntent.PredecessorReleaseIdentity
        if (
            [string]$predecessor.Envelope.PayloadSha256 -cne
                [string]$successorIntent.Payload.predecessor_terminal_receipt_payload_sha256 -or
            [string]$predecessor.Receipt.authority_chain_sha256 -cne
                [string]$successorIntent.Payload.predecessor_terminal_authority_chain_sha256
        ) {
            throw "C07 successor intent predecessor terminal hash chain 已漂移。"
        }
        $live = Get-TicketboxC07LiveDatabaseAuthority (
            $successorIntent.PredecessorReleaseIdentity
        )
        if (
            [string]$live.Fingerprint -cne
                [string]$successorIntent.Payload.live_database_binding_sha256 -or
            [string]@($live.AlembicHeads)[0] -cne
                [string]$successorIntent.Payload.live_alembic_revision
        ) {
            throw "C07 successor intent 授权后 live database/revision 已漂移。"
        }
        Write-TicketboxC07TerminalAuthorityArchive `
            -PredecessorAuthority $predecessor `
            -SuccessorIntent $successorIntent | Out-Null
    }
    return [pscustomobject]@{
        Identity = $pending
        Intent = $successorIntent
        PredecessorAuthority = $predecessor
        ReleaseIdentity = $successorReleaseIdentity
        Mode = [string]$successorIntent.Payload.successor_mode
    }
}

function Assert-TicketboxC07WriterFenceWindow {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [object[]]$AllowedClientSessions = @()
    )
    $intent = Read-TicketboxC07WriterFenceIntent $Authority
    $serviceState = [string](
        Get-TicketboxServiceState $Authority.ReleaseIdentity.BackendServiceName
    )
    $servicePolicy = [string](
        Get-TicketboxServiceStartPolicy $Authority.ReleaseIdentity.BackendServiceName
    )
    $servicePid = [int](
        Get-TicketboxServiceProcessId $Authority.ReleaseIdentity.BackendServiceName
    )
    $listeners = @(
        Get-TicketboxListeningProcessIds $Authority.ReleaseIdentity.BackendPort
    )
    $runtimeProcesses = @(
        Get-TicketboxExpectedRuntimeProcessIds `
            -ExpectedExecutables @(
                $Authority.ReleaseIdentity.BackendExe,
                $Authority.ReleaseIdentity.ShawlExe
            )
    )
    $observation = Get-TicketboxC07WriterDatabaseFenceObservation `
        $Authority.ReleaseIdentity
    Assert-TicketboxC07WriterDatabaseFence `
        -Observation $observation `
        -ExpectedRoles @($intent.Payload.roles) `
        -AllowedClientSessions @($AllowedClientSessions)
    if (
        $serviceState.ToLowerInvariant() -cne "stopped" -or
        $servicePolicy.ToLowerInvariant() -cne "disabled" -or
        $servicePid -ne 0 -or
        $listeners.Count -ne 0 -or
        $runtimeProcesses.Count -ne 0
    ) {
        throw "C07 recovery generation 窗口内 backend writer fence 已失效。"
    }
}

function New-TicketboxC07ReadyVerification {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    $serviceState = [string](
        Get-TicketboxServiceState $Authority.ReleaseIdentity.BackendServiceName
    )
    $servicePolicy = [string](
        Get-TicketboxServiceStartPolicy $Authority.ReleaseIdentity.BackendServiceName
    )
    $servicePid = [int](
        Get-TicketboxServiceProcessId $Authority.ReleaseIdentity.BackendServiceName
    )
    $listeners = @(
        Get-TicketboxListeningProcessIds $Authority.ReleaseIdentity.BackendPort
    )
    $runtimeProcesses = @(
        Get-TicketboxExpectedRuntimeProcessIds `
            -ExpectedExecutables @(
                $Authority.ReleaseIdentity.BackendExe,
                $Authority.ReleaseIdentity.ShawlExe
            )
    )
    $database = Get-TicketboxC07WriterDatabaseFenceObservation `
        $Authority.ReleaseIdentity
    $intent = Read-TicketboxC07WriterFenceIntent $Authority
    Assert-TicketboxC07WriterDatabaseFence `
        -Observation $database `
        -ExpectedRoles @($intent.Payload.roles)
    if (
        $serviceState.ToLowerInvariant() -cne "stopped" -or
        $servicePolicy.ToLowerInvariant() -cne "disabled" -or
        $servicePid -ne 0 -or
        $listeners.Count -ne 0 -or
        $runtimeProcesses.Count -ne 0 -or
        [int64]$database.OtherClientSessionCount -ne 0 -or
        -not [bool]$database.AdvisoryFenceAvailable -or
        -not [bool]$database.AdvisoryFenceReleased
    ) {
        throw "C07 READY 前 backend/session/advisory 二次核验失败。"
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07ReadyVerificationSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        writer_fence_intent_sha256 = $intent.PayloadSha256
        operation_kind = [string]$Authority.Descriptor.Payload.operation_kind
        alembic_target =
            [string]$Authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256
        backend_service_state = "stopped"
        backend_service_start_policy = "disabled"
        backend_service_pid = 0
        backend_listener_pid_count = 0
        runtime_process_count = 0
        database_runtime_session_count =
            [int64]$database.OtherClientSessionCount
        database_client_sessions = @($database.ClientSessions)
        database_role_capability_count = @($database.Roles).Count
        database_role_capabilities = @($database.Roles)
        database_max_prepared_transactions =
            [int64]$database.MaxPreparedTransactions
        database_prepared_transaction_count =
            [int64]$database.PreparedTransactionCount
        database_logical_subscription_count =
            [int64]$database.LogicalSubscriptionCount
        database_logical_apply_worker_count =
            [int64]$database.LogicalApplyWorkerCount
        database_unexpected_worker_count =
            [int64]$database.UnexpectedDatabaseWorkerCount
        database_advisory_fence_available = $true
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $path = Get-TicketboxC07ReadyVerificationPath (
        [string]$Authority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07HostEnvelope `
            -Path $path `
            -ExpectedKind "ready_verification"
        if (
            [string]$existing.Payload.operation_id -ceq
                [string]$Authority.Receipt.operation_id -and
            [string]$existing.Payload.descriptor_sha256 -ceq
                $Authority.Descriptor.PayloadSha256 -and
            [string]$existing.Payload.database_binding_sha256 -ceq
                [string]$Authority.Receipt.database_binding_sha256
        ) {
            return $existing
        }
        throw "C07 READY verification 已存在但不属于当前 operation/database。"
    }
    return Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "ready_verification" `
        -Payload $payload
}

function Assert-TicketboxC07LiveDatabaseBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Descriptor,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity
    )
    $live = Get-TicketboxC07LiveDatabaseAuthority $ReleaseIdentity
    if (
        $live.Fingerprint -cne [string]$Descriptor.Payload.database_binding_sha256 -or
        [string]$live.ClusterSystemIdentifier -cne
            [string]$Descriptor.Payload.cluster_system_identifier -or
        [string]$live.DatabaseName -cne [string]$Descriptor.Payload.database_name -or
        [uint32]$live.DatabaseOid -ne [uint32]$Descriptor.Payload.database_oid -or
        [string]$live.ServerId -cne [string]$Descriptor.Payload.logical_server_id -or
        [string]$live.DataGeneration -cne [string]$Descriptor.Payload.data_generation
    ) {
        throw "C07 live PostgreSQL cluster/database/logical generation 已被替换。"
    }
    $stage = [string]$Receipt.stage
    $head = [string]@($live.AlembicHeads)[0]
    $source = [string]$Descriptor.Payload.source_alembic_revision
    $target = [string]$Descriptor.Payload.target_alembic_revision
    $successorMode = [string]$Descriptor.Payload.successor_mode
    if (
        $successorMode -ceq "forward_repair" -and
        $stage -in @("captured", "writers_frozen")
    ) {
        if ($head -cne $target) {
            throw "C07 forward-repair successor live Alembic head 不是目标 revision。"
        }
        return $live
    }
    if (
        $stage -in @(
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified",
            "runtime_acl_verified",
            "ready"
        ) -and
        $head -cne $target
    ) {
        throw "C07 target_committed 之后 live Alembic head 不是目标 revision。"
    }
    if (
        $stage -in @(
            "captured",
            "writers_frozen",
            "recovery_generation_ready",
            "isolated_restore_verified",
            "refused_pre_ddl"
        ) -and
        $head -cne $source
    ) {
        throw "C07 DDL 前 live Alembic head 已漂移。"
    }
    if ($stage -in @("ddl_started", "repair_required") -and $head -notin @($source, $target)) {
        throw "C07 DDL/repair 阶段 live Alembic head 不在受控 source/target 集。"
    }
    return $live
}

function Read-TicketboxC07Authority {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [string]$ExpectedInstallationOperationId = ""
    )
    return Read-TicketboxC07AuthorityCore `
        -DataRoot $DataRoot `
        -ExpectedInstallationOperationId $ExpectedInstallationOperationId
}

function Assert-TicketboxC07OperationLease {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $lifecycleOwner = Assert-TicketboxC07LifecycleLease $LifecycleLock
    $currentCoordinator = Get-TicketboxProcessIdentity -ProcessId $PID
    if (
        -not (Test-TicketboxProcessIdentityEquals `
            $currentCoordinator `
            $Authority.Binding.CoordinatorIdentity) -or
        -not (Test-TicketboxProcessIdentityEquals `
            $lifecycleOwner `
            $Authority.Binding.LifecycleOwnerIdentity)
    ) {
        throw "C07 当前 coordinator/lifecycle lock identity 与 operation binding 不一致。"
    }
    Assert-TicketboxC07LiveProcessIdentity $Authority.Binding.CoordinatorIdentity
}

function Get-TicketboxC07SafeFailureCode {
    param(
        [Parameter(Mandatory = $true)][Exception]$Failure,
        [string]$Default = "maintenance_action_failed"
    )
    $candidate = ""
    if ($Failure.Data.Contains("TicketboxC07FailureCode")) {
        $candidate = [string]$Failure.Data["TicketboxC07FailureCode"]
    }
    if ($candidate -cmatch "^[a-z0-9_]{1,64}$") {
        return $candidate
    }
    return $Default
}

function Test-TicketboxC07InvariantFailure {
    param([Parameter(Mandatory = $true)][Exception]$Failure)
    $classification = [string]$Failure.Data["TicketboxC07FailureClass"]
    if ($classification -ceq "invariant") { return $true }
    if ($classification -ceq "transient") { return $false }
    $code = Get-TicketboxC07SafeFailureCode $Failure ""
    return $code -cin @(
        "database_identity_or_revision_drift",
        "release_identity_mismatch",
        "authority_chain_mismatch",
        "resource_shape_mismatch",
        "money_facts_mismatch",
        "writer_fence_invariant_failed",
        "role_authority_invariant_failed",
        "runtime_acl_invariant_failed"
    )
}

function Get-TicketboxC07PrecommittedMaintenanceAttempt {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [ValidateRange(1, [int]::MaxValue)][int]$ExpectedSequence
    )
    $operationId = [string]$Authority.Receipt.operation_id
    $escapedOperationId = [regex]::Escape($operationId)
    $attemptPattern = (
        "^op-$escapedOperationId-a-" +
        "(?<attempt>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-" +
        "[0-9a-f]{4}-[0-9a-f]{12})\.json$"
    )
    $bySequence = @{}
    foreach ($entry in @(
        Get-ChildItem `
            -LiteralPath (Get-TicketboxC07HostArtifactRoot) `
            -Force `
            -ErrorAction Stop
    )) {
        $match = [regex]::Match(
            [string]$entry.Name,
            $attemptPattern,
            [Text.RegularExpressions.RegexOptions]::CultureInvariant
        )
        if (-not $match.Success) { continue }
        if ((Get-TicketboxPathEntryKindNoFollow $entry.FullName) -cne "File") {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 maintenance attempt artifact 不是普通文件。" `
                -FailureClass "invariant" `
                -FailureCode "authority_chain_mismatch")
        }
        $envelope = Read-TicketboxC07HostEnvelope `
            -Path $entry.FullName `
            -ExpectedKind "maintenance_attempt"
        $sequenceValue = $envelope.Payload.attempt_sequence
        if (
            ($sequenceValue -isnot [int] -and $sequenceValue -isnot [long]) -or
            [int64]$sequenceValue -lt 1 -or
            [int64]$sequenceValue -gt
                $script:TicketboxC07MaximumMaintenanceAttempts
        ) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 maintenance attempt sequence artifact 无效。" `
                -FailureClass "invariant" `
                -FailureCode "authority_chain_mismatch")
        }
        $sequence = [int]$sequenceValue
        try {
            $attempt = Read-TicketboxC07MaintenanceAttempt `
                -Authority $Authority `
                -AttemptId ([string]$match.Groups["attempt"].Value) `
                -Sequence $sequence `
                -ExpectedPayloadSha256 $envelope.PayloadSha256
        }
        catch {
            if (Test-TicketboxC07InvariantFailure $_.Exception) { throw }
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 maintenance attempt candidate 验证失败。" `
                -FailureClass "invariant" `
                -FailureCode "authority_chain_mismatch" `
                -InnerException $_.Exception)
        }
        $key = [string]$sequence
        if ($bySequence.ContainsKey($key)) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 maintenance attempt sequence 存在分叉。" `
                -FailureClass "invariant" `
                -FailureCode "authority_chain_mismatch")
        }
        $bySequence[$key] = $attempt
    }
    $expectedKey = [string]$ExpectedSequence
    if ($bySequence.ContainsKey($expectedKey)) {
        return $bySequence[$expectedKey]
    }
    return $null
}

function Assert-TicketboxC07PrecommittedMaintenanceAttempt {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Heartbeat,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [AllowNull()][object]$PreviousAttempt,
        [Parameter(Mandatory = $true)][AllowEmptyString()]
        [string]$PreviousFailureSha256,
        [Parameter(Mandatory = $true)][string]$LiveAlembicRevision
    )
    $payload = $Attempt.Payload
    $expectedSequence =
        [int64]$Heartbeat.Payload.maintenance_attempt_sequence + 1
    $expectedPreviousId = if ($null -eq $PreviousAttempt) {
        ""
    }
    else { [string]$PreviousAttempt.Payload.attempt_id }
    $expectedPreviousSha256 = if ($null -eq $PreviousAttempt) {
        ""
    }
    else { [string]$PreviousAttempt.PayloadSha256 }
    if (
        [int64]$payload.attempt_sequence -ne $expectedSequence -or
        [string]$payload.previous_attempt_id -cne $expectedPreviousId -or
        [string]$payload.previous_attempt_sha256 -cne
            $expectedPreviousSha256 -or
        [string]$payload.previous_attempt_failure_sha256 -cne
            $PreviousFailureSha256 -or
        [string]$payload.source_stage -cne
            [string]$Authority.Receipt.stage -or
        [int64]$payload.source_stage_sequence -ne
            [int64]$Authority.Receipt.stage_sequence -or
        [string]$payload.live_alembic_revision -cne $LiveAlembicRevision
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 precommitted maintenance attempt 与当前 predecessor 不一致。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch")
    }
    $attemptBindingSequence =
        [int64]$payload.coordinator_binding_sequence
    $currentBindingSequence = [int64]$Authority.Binding.Sequence
    if ($attemptBindingSequence -eq $currentBindingSequence) {
        if (
            [string]$payload.coordinator_binding_sha256 -cne
                [string]$Authority.Binding.PayloadSha256 -or
            [string]$payload.source_receipt_payload_sha256 -cne
                [string]$Authority.Envelope.PayloadSha256 -or
            [string]$payload.source_authority_chain_sha256 -cne
                [string]$Authority.Receipt.authority_chain_sha256 -or
            [string]$payload.previous_heartbeat_payload_sha256 -cne
                [string]$Heartbeat.PayloadSha256 -or
            [int64]$payload.previous_heartbeat_sequence -ne
                [int64]$Heartbeat.Payload.sequence
        ) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 precommitted attempt 未绑定 exact current authority。" `
                -FailureClass "invariant" `
                -FailureCode "authority_chain_mismatch")
        }
        return
    }
    if ($attemptBindingSequence -lt 0 -or
        $attemptBindingSequence -ge $currentBindingSequence) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 precommitted attempt binding sequence 无效。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch")
    }
    $firstTakeover = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Descriptor $Authority.Descriptor `
        -Sequence ([int]($attemptBindingSequence + 1))
    if (
        [string]$firstTakeover.Payload.previous_binding_sha256 -cne
            [string]$payload.coordinator_binding_sha256 -or
        [string]$firstTakeover.Payload.previous_heartbeat_payload_sha256 -cne
            [string]$payload.previous_heartbeat_payload_sha256 -or
        [int64]$firstTakeover.Payload.previous_heartbeat_sequence -ne
            [int64]$payload.previous_heartbeat_sequence -or
        [string]$firstTakeover.Payload.previous_receipt_payload_sha256 -cne
            [string]$payload.source_receipt_payload_sha256 -or
        [string]$firstTakeover.Payload.previous_authority_chain_sha256 -cne
            [string]$payload.source_authority_chain_sha256 -or
        [string]$firstTakeover.Payload.resumed_stage -cne
            [string]$payload.source_stage
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 precommitted attempt 未绑定 first takeover predecessor。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch")
    }
    Assert-TicketboxC07PriorProcessIdentityDead $Attempt.CoordinatorIdentity
}

function Get-TicketboxC07MaintenanceAttemptRemainingMilliseconds {
    param([Parameter(Mandatory = $true)][object]$Attempt)
    $windowMilliseconds = [double](
        $script:TicketboxC07MaintenanceWindowSeconds * 1000
    )
    $capturedTick = [int64]$Attempt.Payload.started_tick_count64
    $currentTick = [int64][Environment]::TickCount64
    if (
        [string]$Attempt.Payload.started_boot_identity -cne
            (Get-TicketboxC07BootIdentity) -or
        $capturedTick -lt 0 -or
        $currentTick -lt $capturedTick
    ) {
        return [int64]0
    }
    $remaining = [Math]::Min(
        $windowMilliseconds - [double]($currentTick - $capturedTick),
        (([DateTime]$Attempt.DeadlineUtc) - [DateTime]::UtcNow).TotalMilliseconds
    )
    return [int64][Math]::Max(0, [Math]::Floor($remaining))
}

function Write-TicketboxC07MaintenanceAttemptHeartbeat {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$CurrentHeartbeat,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [string]$FailureSha256 = "",
        [switch]$ResetBudget
    )
    if (-not [string]::IsNullOrEmpty($FailureSha256)) {
        Assert-TicketboxC07Sha256 `
            $FailureSha256 `
            "maintenance attempt failure heartbeat binding"
    }
    $identity = $Authority.Binding.CoordinatorIdentity
    $remaining = if ($ResetBudget) {
        Get-TicketboxC07MaintenanceAttemptRemainingMilliseconds $Attempt
    }
    else {
        [int64]$CurrentHeartbeat.Payload.maintenance_remaining_ceiling_ms
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07HeartbeatSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        coordinator_binding_sha256 = $Authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$Authority.Binding.Sequence
        coordinator_pid = [int]$identity.ProcessId
        coordinator_started_filetime_high = [uint32]$identity.StartedFileTimeHigh
        coordinator_started_filetime_low = [uint32]$identity.StartedFileTimeLow
        maintenance_attempt_id = [string]$Attempt.Payload.attempt_id
        maintenance_attempt_sequence =
            [int64]$Attempt.Payload.attempt_sequence
        maintenance_attempt_sha256 = [string]$Attempt.PayloadSha256
        maintenance_attempt_failure_sha256 = $FailureSha256
        sequence = [int64]$CurrentHeartbeat.Payload.sequence + 1
        maintenance_remaining_ceiling_ms = $remaining
        observed_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    return Write-TicketboxC07HostEnvelope `
        -Path (
            Get-TicketboxC07HeartbeatPath (
                [string]$Authority.Receipt.operation_id
            )
        ) `
        -ArtifactKind "heartbeat" `
        -Payload $payload `
        -ReplaceExisting
}

function New-TicketboxC07MaintenanceAttemptFailure {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][Exception]$Failure,
        [Parameter(Mandatory = $true)][string]$ActionKind,
        [string]$FailureCode = ""
    )
    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    if ($ActionKind -cnotmatch "^[a-z0-9_]{1,64}$") {
        throw "C07 maintenance attempt action kind 无效。"
    }
    $heartbeat = Read-TicketboxC07Heartbeat $Authority
    if ([int64]$heartbeat.Payload.maintenance_attempt_sequence -lt 1) {
        throw "C07 无 active maintenance attempt 可记录瞬态失败。"
    }
    $attempt = Read-TicketboxC07MaintenanceAttempt `
        -Authority $Authority `
        -AttemptId ([string]$heartbeat.Payload.maintenance_attempt_id) `
        -Sequence ([int]$heartbeat.Payload.maintenance_attempt_sequence) `
        -ExpectedPayloadSha256 (
            [string]$heartbeat.Payload.maintenance_attempt_sha256
        )
    $existingFailureSha256 =
        [string]$heartbeat.Payload.maintenance_attempt_failure_sha256
    if (-not [string]::IsNullOrEmpty($existingFailureSha256)) {
        return Read-TicketboxC07MaintenanceAttemptFailure `
            -Authority $Authority `
            -Attempt $attempt `
            -ExpectedPayloadSha256 $existingFailureSha256
    }
    if ([string]::IsNullOrEmpty($FailureCode)) {
        $FailureCode = Get-TicketboxC07SafeFailureCode $Failure
    }
    if ($FailureCode -cnotmatch "^[a-z0-9_]{1,64}$") {
        throw "C07 maintenance attempt failure code 无效。"
    }
    $live = Get-TicketboxC07LiveDatabaseAuthority $Authority.ReleaseIdentity
    $expectedHeads = @(
        Get-TicketboxC07ExpectedAttemptRevisions `
            -Authority $Authority `
            -Stage ([string]$Authority.Receipt.stage)
    )
    $liveHead = [string]@($live.AlembicHeads)[0]
    if (
        [string]$live.Fingerprint -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        @($live.AlembicHeads).Count -ne 1 -or
        $liveHead -notin $expectedHeads
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message (
                "C07 maintenance attempt failure 时 database/head invariant " +
                "已漂移。"
            ) `
            -FailureClass "invariant" `
            -FailureCode "database_identity_or_revision_drift" `
            -InnerException $Failure)
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07MaintenanceAttemptFailureSchema
        operation_id = [string]$Authority.Receipt.operation_id
        attempt_id = [string]$attempt.Payload.attempt_id
        attempt_sequence = [int64]$attempt.Payload.attempt_sequence
        attempt_sha256 = [string]$attempt.PayloadSha256
        failure_class = "transient"
        failure_code = $FailureCode
        action_kind = $ActionKind
        failure_message_sha256 = Get-TicketboxC07TextSha256 (
            [string]$Failure.Message
        )
        failed_stage = [string]$Authority.Receipt.stage
        failed_stage_sequence = [int64]$Authority.Receipt.stage_sequence
        failed_receipt_payload_sha256 = $Authority.Envelope.PayloadSha256
        failed_authority_chain_sha256 =
            [string]$Authority.Receipt.authority_chain_sha256
        database_binding_sha256 =
            [string]$Authority.Receipt.database_binding_sha256
        live_alembic_revision = $liveHead
        failed_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $path = Get-TicketboxC07MaintenanceAttemptFailurePath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -AttemptId ([string]$attempt.Payload.attempt_id)
    $failureEnvelope = if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07HostEnvelope `
            -Path $path `
            -ExpectedKind "maintenance_attempt_failure"
        # The immutable failure is the commit record. A hard kill may occur
        # after that file is durable but before the mutable heartbeat points
        # at it. Re-read the existing artifact against its own protected hash
        # and adopt it; a later coordinator must not rewrite history to match
        # its inferred coordinator_replaced/attempt_recovery diagnosis.
        Read-TicketboxC07MaintenanceAttemptFailure `
            -Authority $Authority `
            -Attempt $attempt `
            -ExpectedPayloadSha256 $existing.PayloadSha256
    }
    else {
        Write-TicketboxC07HostEnvelope `
            -Path $path `
            -ArtifactKind "maintenance_attempt_failure" `
            -Payload $payload
    }
    Write-TicketboxC07MaintenanceAttemptHeartbeat `
        -Authority $Authority `
        -CurrentHeartbeat $heartbeat `
        -Attempt $attempt `
        -FailureSha256 $failureEnvelope.PayloadSha256 | Out-Null
    $updatedHeartbeat = Read-TicketboxC07Heartbeat $Authority
    return Read-TicketboxC07MaintenanceAttemptFailure `
        -Authority $Authority `
        -Attempt $attempt `
        -ExpectedPayloadSha256 (
            [string]$updatedHeartbeat.Payload.maintenance_attempt_failure_sha256
        )
}

function Start-TicketboxC07MaintenanceAttempt {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    $stage = [string]$Authority.Receipt.stage
    if ($stage -eq "ready" -or $stage -in $script:TicketboxC07FailureStages) {
        return $null
    }
    $heartbeat = Read-TicketboxC07Heartbeat $Authority
    $previousAttempt = $null
    $previousFailureSha256 = ""
    $previousSequence = [int64]$heartbeat.Payload.maintenance_attempt_sequence
    if ($previousSequence -gt 0) {
        $previousAttempt = Read-TicketboxC07MaintenanceAttempt `
            -Authority $Authority `
            -AttemptId ([string]$heartbeat.Payload.maintenance_attempt_id) `
            -Sequence ([int]$previousSequence) `
            -ExpectedPayloadSha256 (
                [string]$heartbeat.Payload.maintenance_attempt_sha256
            )
        $previousFailureSha256 =
            [string]$heartbeat.Payload.maintenance_attempt_failure_sha256
        $sameCoordinator = Test-TicketboxProcessIdentityEquals `
            $previousAttempt.CoordinatorIdentity `
            $Authority.Binding.CoordinatorIdentity
        $sameBoot = [string]$previousAttempt.Payload.started_boot_identity -ceq
            (Get-TicketboxC07BootIdentity)
        $active = (
            [string]::IsNullOrEmpty($previousFailureSha256) -and
            $sameCoordinator -and
            $sameBoot -and
            [DateTime]$previousAttempt.DeadlineUtc -gt
                [DateTime]::UtcNow.AddSeconds(1)
        )
        if ($active) { return $previousAttempt }
        if ([string]::IsNullOrEmpty($previousFailureSha256)) {
            $abandonCode = if (-not $sameCoordinator) {
                "coordinator_replaced"
            }
            elseif (-not $sameBoot) {
                "maintenance_attempt_rebooted"
            }
            else {
                "maintenance_attempt_expired"
            }
            $abandon = New-TicketboxC07ClassifiedFailure `
                -Message "C07 prior maintenance attempt 已失去有效 coordinator/budget。" `
                -FailureClass "transient" `
                -FailureCode $abandonCode
            New-TicketboxC07MaintenanceAttemptFailure `
                -Authority $Authority `
                -LifecycleLock $LifecycleLock `
                -Failure $abandon `
                -ActionKind "attempt_recovery" `
                -FailureCode $abandonCode | Out-Null
            $heartbeat = Read-TicketboxC07Heartbeat $Authority
            $previousFailureSha256 =
                [string]$heartbeat.Payload.maintenance_attempt_failure_sha256
        }
    }
    if (
        $previousSequence -ge
            $script:TicketboxC07MaximumMaintenanceAttempts
    ) {
        $terminalStage = if ($stage -in $script:TicketboxC07PreDdlStages) {
            "refused_pre_ddl"
        }
        else { "repair_required" }
        # Attempt exhaustion is a durable policy terminal, not another
        # transient attempt. Commit it while the lifecycle lease is held so an
        # installed caller cannot remain forever non-terminal outside its
        # action try/catch or receive a sixty-fifth maintenance budget.
        Set-TicketboxC07LifecycleStage `
            -DataRoot ([string]$Authority.ReleaseIdentity.DataRoot) `
            -LifecycleLock $LifecycleLock `
            -TargetStage $terminalStage `
            -FailureCode "maintenance_attempts_exhausted" | Out-Null
        return $null
    }
    $live = Get-TicketboxC07LiveDatabaseAuthority $Authority.ReleaseIdentity
    $expectedHeads = @(
        Get-TicketboxC07ExpectedAttemptRevisions `
            -Authority $Authority `
            -Stage $stage
    )
    $liveHead = [string]@($live.AlembicHeads)[0]
    if (
        [string]$live.Fingerprint -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        @($live.AlembicHeads).Count -ne 1 -or
        $liveHead -notin $expectedHeads
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 new maintenance attempt 拒绝 database/head invariant 漂移。" `
            -FailureClass "invariant" `
            -FailureCode "database_identity_or_revision_drift")
    }
    $nextSequence = [int]($previousSequence + 1)
    $precommittedAttempt = Get-TicketboxC07PrecommittedMaintenanceAttempt `
        -Authority $Authority `
        -ExpectedSequence $nextSequence
    if ($null -ne $precommittedAttempt) {
        Assert-TicketboxC07PrecommittedMaintenanceAttempt `
            -Authority $Authority `
            -Heartbeat $heartbeat `
            -Attempt $precommittedAttempt `
            -PreviousAttempt $previousAttempt `
            -PreviousFailureSha256 $previousFailureSha256 `
            -LiveAlembicRevision $liveHead
        Write-TicketboxC07MaintenanceAttemptHeartbeat `
            -Authority $Authority `
            -CurrentHeartbeat $heartbeat `
            -Attempt $precommittedAttempt `
            -ResetBudget | Out-Null
        $adoptedHeartbeat = Read-TicketboxC07Heartbeat $Authority
        return Read-TicketboxC07MaintenanceAttempt `
            -Authority $Authority `
            -AttemptId ([string]$adoptedHeartbeat.Payload.maintenance_attempt_id) `
            -Sequence ([int]$adoptedHeartbeat.Payload.maintenance_attempt_sequence) `
            -ExpectedPayloadSha256 (
                [string]$adoptedHeartbeat.Payload.maintenance_attempt_sha256
            )
    }
    $startedAt = [DateTime]::UtcNow
    $attemptId = Get-TicketboxC07MaintenanceAttemptId `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Sequence $nextSequence
    $identity = $Authority.Binding.CoordinatorIdentity
    $payload = [ordered]@{
        schema = $script:TicketboxC07MaintenanceAttemptSchema
        operation_id = [string]$Authority.Receipt.operation_id
        attempt_id = $attemptId
        attempt_sequence = $nextSequence
        source_stage = $stage
        source_stage_sequence = [int64]$Authority.Receipt.stage_sequence
        source_receipt_payload_sha256 = $Authority.Envelope.PayloadSha256
        source_authority_chain_sha256 =
            [string]$Authority.Receipt.authority_chain_sha256
        previous_heartbeat_payload_sha256 = $heartbeat.PayloadSha256
        previous_heartbeat_sequence = [int64]$heartbeat.Payload.sequence
        previous_attempt_id = if ($null -eq $previousAttempt) {
            ""
        }
        else { [string]$previousAttempt.Payload.attempt_id }
        previous_attempt_sha256 = if ($null -eq $previousAttempt) {
            ""
        }
        else { [string]$previousAttempt.PayloadSha256 }
        previous_attempt_failure_sha256 = $previousFailureSha256
        release_fingerprint = [string]$Authority.Receipt.release_fingerprint
        database_binding_sha256 =
            [string]$Authority.Receipt.database_binding_sha256
        live_alembic_revision = $liveHead
        coordinator_binding_sha256 = $Authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$Authority.Binding.Sequence
        coordinator_pid = [int]$identity.ProcessId
        coordinator_started_filetime_high = [uint32]$identity.StartedFileTimeHigh
        coordinator_started_filetime_low = [uint32]$identity.StartedFileTimeLow
        maintenance_window_ms = [int64](
            $script:TicketboxC07MaintenanceWindowSeconds * 1000
        )
        started_tick_count64 = [int64][Environment]::TickCount64
        started_boot_identity = Get-TicketboxC07BootIdentity
        started_at_utc = $startedAt.ToString("o")
        deadline_utc = $startedAt.AddSeconds(
            $script:TicketboxC07MaintenanceWindowSeconds
        ).ToString("o")
    }
    $attemptEnvelope = Write-TicketboxC07HostEnvelope `
        -Path (
            Get-TicketboxC07MaintenanceAttemptPath `
                -OperationId ([string]$Authority.Receipt.operation_id) `
                -AttemptId $attemptId
        ) `
        -ArtifactKind "maintenance_attempt" `
        -Payload $payload
    $attempt = Read-TicketboxC07MaintenanceAttempt `
        -Authority $Authority `
        -AttemptId $attemptId `
        -Sequence ([int]$payload.attempt_sequence) `
        -ExpectedPayloadSha256 $attemptEnvelope.PayloadSha256
    Write-TicketboxC07MaintenanceAttemptHeartbeat `
        -Authority $Authority `
        -CurrentHeartbeat $heartbeat `
        -Attempt $attempt `
        -ResetBudget | Out-Null
    $updated = Read-TicketboxC07Heartbeat $Authority
    return Read-TicketboxC07MaintenanceAttempt `
        -Authority $Authority `
        -AttemptId ([string]$updated.Payload.maintenance_attempt_id) `
        -Sequence ([int]$updated.Payload.maintenance_attempt_sequence) `
        -ExpectedPayloadSha256 (
            [string]$updated.Payload.maintenance_attempt_sha256
        )
}

function Write-TicketboxC07HeartbeatForAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [ValidateRange(-1, 1200000)]
        [int64]$MaintenanceRemainingCeilingMilliseconds = -1
    )
    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    return Write-TicketboxC07HeartbeatPayload `
        -Authority $Authority `
        -MaintenanceRemainingCeilingMilliseconds (
            $MaintenanceRemainingCeilingMilliseconds
        )
}

function Write-TicketboxC07Heartbeat {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [ValidateRange(-1, 1200000)]
        [int64]$MaintenanceRemainingCeilingMilliseconds = -1
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    return Write-TicketboxC07HeartbeatForAuthority `
        -Authority $authority `
        -LifecycleLock $LifecycleLock `
        -MaintenanceRemainingCeilingMilliseconds (
            $MaintenanceRemainingCeilingMilliseconds
        )
}

function Write-TicketboxC07RuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][int64]$HeartbeatSequence
    )
    $releaseIdentity = $Authority.ReleaseIdentity
    $runtimeAccount = Get-TicketboxC07RuntimeReadAccount $releaseIdentity
    $stage = [string]$Authority.Receipt.stage
    $isFailure = $stage -in $script:TicketboxC07FailureStages
    $recoveryManifestSha256 = ""
    $migrationEvidenceSha256 = ""
    $roleAuthoritySha256 = ""
    $runtimeAclSha256 = ""
    $livePostconditionsSha256 = ""
    $moneyFactsSha256 = ""
    $moneyShapeSha256 = ""
    if ($stage -in $script:TicketboxC07ProductionGatedStages) {
        $production = Read-TicketboxC07ProductionAuthority $Authority
        $recoveryManifestSha256 =
            [string]$production.Payload.target_recovery_manifest_sha256
        $migrationEvidenceSha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.migration_evidence_sha256) `
                "production migration evidence"
        )
        $roleAuthoritySha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.role_authority_sha256) `
                "production role authority"
        )
        $runtimeAclSha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.runtime_acl_sha256) `
                "production runtime ACL"
        )
        $livePostconditionsSha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.live_postconditions_sha256) `
                "production live postconditions"
        )
        $moneyFactsSha256 = [string]$production.Payload.money_facts_sha256
        $moneyShapeSha256 =
            [string]$production.Payload.resource_shape_sha256
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07ProjectionSchema
        operation_id = [string]$Authority.Receipt.operation_id
        installation_id = [string]$releaseIdentity.InstallationId
        stage = $stage
        terminal = [bool]($isFailure -or $stage -eq "ready")
        ready = [bool]($stage -eq "ready")
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        logical_server_id =
            [string]$Authority.Descriptor.Payload.logical_server_id
        data_generation = [string]$Authority.Descriptor.Payload.data_generation
        recovery_epoch_id = [string]$Authority.Receipt.recovery_epoch_id
        operation_kind =
            [string]$Authority.Descriptor.Payload.operation_kind
        source_alembic_revision =
            [string]$Authority.Descriptor.Payload.source_alembic_revision
        alembic_target =
            [string]$Authority.Descriptor.Payload.target_alembic_revision
        recovery_manifest_sha256 = $recoveryManifestSha256
        migration_evidence_sha256 = $migrationEvidenceSha256
        role_authority_sha256 = $roleAuthoritySha256
        runtime_acl_sha256 = $runtimeAclSha256
        live_postconditions_sha256 = $livePostconditionsSha256
        money_facts_sha256 = $moneyFactsSha256
        money_shape_sha256 = $moneyShapeSha256
        heartbeat_sequence_at_publish = $HeartbeatSequence
        updated_at_utc = [string]$Authority.Receipt.updated_at_utc
    }
    $path = Get-TicketboxC07ProjectionPath
    $text = New-TicketboxC07EnvelopeText -ArtifactKind "runtime_projection" -Payload $payload
    if (Test-Path -LiteralPath $path) {
        $existingArtifact = Read-TicketboxProtectedUtf8Artifact `
            -Path $path `
            -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
            -ReadExecuteAccounts @($runtimeAccount) `
            -OwnerAccount $script:TicketboxC07HostOwnerAccount `
            -MaximumBytes 32768
        $existing = ConvertFrom-TicketboxC07EnvelopeText `
            -Text $existingArtifact.Text `
            -ExpectedKind "runtime_projection"
        if ($existing.Text -ceq $text) {
            return $existing
        }
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount `
        -ReplaceExisting:(Test-Path -LiteralPath $path)
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount `
        -MaximumBytes 32768
    $persisted = ConvertFrom-TicketboxC07EnvelopeText `
        -Text $artifact.Text `
        -ExpectedKind "runtime_projection"
    if ($persisted.Text -cne $text) {
        throw "C07 runtime projection 写后复读不一致。"
    }
    return $persisted
}

function Read-TicketboxC07RuntimeProjection([string]$DataRoot) {
    $authority = Read-TicketboxC07Authority $DataRoot
    $runtimeAccount = Get-TicketboxC07RuntimeReadAccount $authority.ReleaseIdentity
    Assert-TicketboxProtectedDirectoryAcl `
        -Path (Get-TicketboxC07RuntimeProjectionRoot) `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path (Get-TicketboxC07ProjectionPath) `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount `
        -MaximumBytes 32768
    $envelope = ConvertFrom-TicketboxC07EnvelopeText `
        -Text $artifact.Text `
        -ExpectedKind "runtime_projection"
    $payload = $envelope.Payload
    $expectedNames = @(
        "schema",
        "operation_id",
        "installation_id",
        "stage",
        "terminal",
        "ready",
        "database_binding_sha256",
        "logical_server_id",
        "data_generation",
        "recovery_epoch_id",
        "operation_kind",
        "source_alembic_revision",
        "alembic_target",
        "recovery_manifest_sha256",
        "migration_evidence_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "live_postconditions_sha256",
        "money_facts_sha256",
        "money_shape_sha256",
        "heartbeat_sequence_at_publish",
        "updated_at_utc"
    )
    Assert-TicketboxC07ExactProperties $payload $expectedNames "runtime projection"
    $expectedTerminal = (
        [string]$authority.Receipt.stage -in $script:TicketboxC07FailureStages -or
        [string]$authority.Receipt.stage -eq "ready"
    )
    $expectedRecoveryManifestSha256 = ""
    $expectedMigrationEvidenceSha256 = ""
    $expectedRoleAuthoritySha256 = ""
    $expectedRuntimeAclSha256 = ""
    $expectedLivePostconditionsSha256 = ""
    $expectedMoneyFactsSha256 = ""
    $expectedMoneyShapeSha256 = ""
    if ([string]$authority.Receipt.stage -in $script:TicketboxC07ProductionGatedStages) {
        $production = Read-TicketboxC07ProductionAuthority $authority
        $expectedRecoveryManifestSha256 =
            [string]$production.Payload.target_recovery_manifest_sha256
        $expectedMigrationEvidenceSha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.migration_evidence_sha256) `
                "production migration evidence"
        )
        $expectedRoleAuthoritySha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.role_authority_sha256) `
                "production role authority"
        )
        $expectedRuntimeAclSha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.runtime_acl_sha256) `
                "production runtime ACL"
        )
        $expectedLivePostconditionsSha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$production.CoordinatorResult.live_postconditions_sha256) `
                "production live postconditions"
        )
        $expectedMoneyFactsSha256 =
            [string]$production.Payload.money_facts_sha256
        $expectedMoneyShapeSha256 =
            [string]$production.Payload.resource_shape_sha256
    }
    if (
        [string]$payload.schema -cne $script:TicketboxC07ProjectionSchema -or
        [string]$payload.operation_id -cne [string]$authority.Receipt.operation_id -or
        [string]$payload.installation_id -cne
            [string]$authority.ReleaseIdentity.InstallationId -or
        [string]$payload.stage -cne [string]$authority.Receipt.stage -or
        $payload.terminal -isnot [bool] -or
        [bool]$payload.terminal -ne $expectedTerminal -or
        $payload.ready -isnot [bool] -or
        [bool]$payload.ready -ne ([string]$authority.Receipt.stage -eq "ready") -or
        [string]$payload.database_binding_sha256 -cne
            [string]$authority.Receipt.database_binding_sha256 -or
        [string]$payload.logical_server_id -cne
            [string]$authority.Descriptor.Payload.logical_server_id -or
        [string]$payload.data_generation -cne
            [string]$authority.Descriptor.Payload.data_generation -or
        [string]$payload.recovery_epoch_id -cne
            [string]$authority.Receipt.recovery_epoch_id -or
        [string]$payload.operation_kind -cne
            [string]$authority.Descriptor.Payload.operation_kind -or
        [string]$payload.source_alembic_revision -cne
            [string]$authority.Descriptor.Payload.source_alembic_revision -or
        [string]$payload.alembic_target -cne
            [string]$authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.recovery_manifest_sha256 -cne
            $expectedRecoveryManifestSha256 -or
        [string]$payload.migration_evidence_sha256 -cne
            $expectedMigrationEvidenceSha256 -or
        [string]$payload.role_authority_sha256 -cne
            $expectedRoleAuthoritySha256 -or
        [string]$payload.runtime_acl_sha256 -cne
            $expectedRuntimeAclSha256 -or
        [string]$payload.live_postconditions_sha256 -cne
            $expectedLivePostconditionsSha256 -or
        [string]$payload.money_facts_sha256 -cne
            $expectedMoneyFactsSha256 -or
        [string]$payload.money_shape_sha256 -cne
            $expectedMoneyShapeSha256
    ) {
        throw "C07 runtime projection 与 live host/database authority 不一致。"
    }
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
    }
}

function Assert-TicketboxC07CommitReadyArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$ExpectedProductionAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$ExpectedRuntimeProjectionSha256
    )

    $operationId = ConvertTo-TicketboxC07CanonicalOperationId $ExpectedOperationId
    Assert-TicketboxC07Sha256 `
        $ExpectedProductionAuthoritySha256 `
        "commit production authority"
    Assert-TicketboxC07Sha256 `
        $ExpectedRuntimeProjectionSha256 `
        "commit runtime projection"
    if ($BackendServiceName -cnotmatch '^[A-Za-z0-9_.-]{1,128}$') {
        throw "C07 commit backend service name 无效。"
    }

    $lockRoot = ConvertTo-TicketboxCanonicalPath (
        Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    )
    $hostRoot = ConvertTo-TicketboxCanonicalPath (
        Join-Path $lockRoot $script:TicketboxC07HostDirectoryName
    )
    $runtimeRoot = ConvertTo-TicketboxCanonicalPath (
        Join-Path $lockRoot $script:TicketboxC07RuntimeDirectoryName
    )
    $runtimeAccount = "NT SERVICE\$BackendServiceName"
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $hostRoot `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $runtimeRoot `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount

    $authority = Read-TicketboxC07HostEnvelope `
        -Path (Join-Path $hostRoot $script:TicketboxC07AuthorityFileName) `
        -ExpectedKind "authority_receipt"
    $production = Read-TicketboxC07HostEnvelope `
        -Path (
            Join-Path `
                $hostRoot `
                "operation-$operationId-production-authority.json"
        ) `
        -ExpectedKind "production_authority"
    $projectionArtifact = Read-TicketboxProtectedUtf8Artifact `
        -Path (Join-Path $runtimeRoot $script:TicketboxC07ProjectionFileName) `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -ReadExecuteAccounts @($runtimeAccount) `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount `
        -MaximumBytes 32768
    $projection = ConvertFrom-TicketboxC07EnvelopeText `
        -Text $projectionArtifact.Text `
        -ExpectedKind "runtime_projection"

    if (
        [string]$authority.Payload.operation_id -cne $operationId -or
        [string]$authority.Payload.stage -cne "ready" -or
        [string]$production.Payload.operation_id -cne $operationId -or
        [string]$production.Payload.schema -cne
            $script:TicketboxC07ProductionAuthoritySchema -or
        [string]$production.Payload.result -cne "production_authority_ready" -or
        [string]$production.Payload.release_fingerprint -cne
            [string]$authority.Payload.release_fingerprint -or
        [string]$projection.Payload.operation_id -cne $operationId -or
        [string]$projection.Payload.schema -cne $script:TicketboxC07ProjectionSchema -or
        [string]$projection.Payload.stage -cne "ready" -or
        $projection.Payload.terminal -isnot [bool] -or
        -not [bool]$projection.Payload.terminal -or
        $projection.Payload.ready -isnot [bool] -or
        -not [bool]$projection.Payload.ready -or
        [string]$projection.Payload.database_binding_sha256 -cne
            [string]$authority.Payload.database_binding_sha256 -or
        [string]$projection.Payload.alembic_target -cne
            [string]$production.Payload.target_alembic_revision -or
        [string]$projection.Payload.recovery_manifest_sha256 -cne
            [string]$production.Payload.target_recovery_manifest_sha256 -or
        [string]$projection.Payload.money_facts_sha256 -cne
            [string]$production.Payload.money_facts_sha256 -or
        [string]$projection.Payload.money_shape_sha256 -cne
            [string]$production.Payload.resource_shape_sha256 -or
        [string]$production.PayloadSha256 -cne
            $ExpectedProductionAuthoritySha256 -or
        [string]$projection.PayloadSha256 -cne
            $ExpectedRuntimeProjectionSha256
    ) {
        throw "C07 install commit 前 READY authority/projection 已漂移或不一致。"
    }
    return [pscustomobject][ordered]@{
        OperationId = $operationId
        ProductionAuthoritySha256 = [string]$production.PayloadSha256
        RuntimeProjectionSha256 = [string]$projection.PayloadSha256
    }
}

function Restore-TicketboxC07TerminalRuntimeProjection {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$Authority
    )
    $stage = [string]$Authority.Receipt.stage
    if (
        $stage -cne "ready" -and
        $stage -notin $script:TicketboxC07FailureStages
    ) {
        throw "C07 runtime projection 仅允许从 durable terminal authority 重建。"
    }
    $heartbeat = Read-TicketboxC07Heartbeat $Authority
    Write-TicketboxC07RuntimeProjection `
        -Authority $Authority `
        -HeartbeatSequence ([int64]$heartbeat.Payload.sequence) | Out-Null
    return Read-TicketboxC07RuntimeProjection $DataRoot
}

function New-TicketboxC07ReceiptPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Values
    )
    $payload = [ordered]@{
        schema = $script:TicketboxC07ReceiptSchema
        operation_id = [string]$Values.operation_id
        stage = [string]$Values.stage
        previous_stage = [string]$Values.previous_stage
        stage_sequence = [int64]$Values.stage_sequence
        authority_revision = [int64]$Values.authority_revision
        transition_kind = [string]$Values.transition_kind
        release_fingerprint = [string]$Values.release_fingerprint
        descriptor_sha256 = [string]$Values.descriptor_sha256
        coordinator_binding_sha256 = [string]$Values.coordinator_binding_sha256
        coordinator_binding_sequence = [int64]$Values.coordinator_binding_sequence
        database_binding_sha256 = [string]$Values.database_binding_sha256
        recovery_epoch_id = [string]$Values.recovery_epoch_id
        freeze_proof_sha256 = [string]$Values.freeze_proof_sha256
        freeze_proof_binding_sequence =
            [int64]$Values.freeze_proof_binding_sequence
        freeze_heartbeat_sequence = [int64]$Values.freeze_heartbeat_sequence
        ready_verification_sha256 = [string]$Values.ready_verification_sha256
        previous_receipt_payload_sha256 = [string]$Values.previous_receipt_payload_sha256
        previous_authority_chain_sha256 = [string]$Values.previous_authority_chain_sha256
        transition_evidence_sha256 = [string]$Values.transition_evidence_sha256
        authority_chain_sha256 = ""
        failure_code = [string]$Values.failure_code
        updated_at_utc = [string]$Values.updated_at_utc
    }
    $payload.authority_chain_sha256 = Get-TicketboxC07TextSha256 (
        Get-TicketboxC07ReceiptChainText $payload
    )
    return $payload
}

function New-TicketboxC07InitialOperation {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$RecoveryEpoch,
        [string]$ExpectedOperationId = "",
        [string]$TargetRevision = $script:TicketboxC07TargetRevision,
        [ValidateSet("c07_money_minor_bigint_v1")]
        [string]$OperationKind = "c07_money_minor_bigint_v1",
        [string]$RevisionManifestSha256 = "",
        [AllowNull()][object]$SuccessorIntent
    )
    $lifecycleOwner = Assert-TicketboxC07LifecycleLease $LifecycleLock
    $coordinator = Get-TicketboxProcessIdentity -ProcessId $PID
    Assert-TicketboxC07LiveProcessIdentity $coordinator
    $database = Get-TicketboxC07LiveDatabaseAuthority $ReleaseIdentity
    if (@($database.AlembicHeads).Count -ne 1) {
        throw "C07 captured database 必须具有唯一 Alembic source revision。"
    }
    $liveHead = [string]@($database.AlembicHeads)[0]
    if ($TargetRevision -cne $script:TicketboxC07TargetRevision) {
        throw "C07 lifecycle 只接受 frozen source/target edge。"
    }
    if ([string]::IsNullOrEmpty($RevisionManifestSha256)) {
        $RevisionManifestSha256 = [string]$ReleaseIdentity.BuildManifestSha256
    }
    Assert-TicketboxC07Sha256 `
        $RevisionManifestSha256 `
        "revision manifest"
    if (
        [string]$ReleaseIdentity.InstallationIdentityState -ceq "PENDING"
    ) {
        if (
            [string]::IsNullOrEmpty($ExpectedOperationId) -or
            ([guid]$ExpectedOperationId).ToString("D") -cne
                [string]$ReleaseIdentity.InstallationOperationId
        ) {
            throw "C07 lifecycle operation 未绑定 PENDING installation identity。"
        }
    }
    $operationId = if ([string]::IsNullOrEmpty($ExpectedOperationId)) {
        [guid]::NewGuid().ToString("D")
    }
    else {
        ConvertTo-TicketboxC07CanonicalOperationId $ExpectedOperationId
    }
    $successor = $null
    if ($null -ne $SuccessorIntent) {
        $successor = Read-TicketboxC07SuccessorIntent `
            -OperationId $operationId `
            -SuccessorReleaseIdentity $ReleaseIdentity
        if (
            [string]$successor.PayloadSha256 -cne
                [string]$SuccessorIntent.PayloadSha256 -or
            [string]$successor.Payload.successor_operation_id -cne
                $operationId -or
            [string]$successor.Payload.live_database_binding_sha256 -cne
                [string]$database.Fingerprint -or
            [string]$successor.Payload.live_alembic_revision -cne $liveHead
        ) {
            throw "C07 successor operation 初始化时 intent/live authority 已漂移。"
        }
    }
    $expectedLiveHead = if (
        $null -ne $successor -and
        [string]$successor.Payload.successor_mode -ceq "forward_repair"
    ) {
        $script:TicketboxC07TargetRevision
    }
    else {
        "20260722_0001"
    }
    if ($liveHead -cne $expectedLiveHead) {
        throw "C07 lifecycle captured live revision 与 operation mode 不一致。"
    }
    $dataRootHash = Get-TicketboxC07TextSha256 (
        $releaseIdentity.DataRoot.ToUpperInvariant() + "`n"
    )
    $expectedSuccessorIntentSha256 = if ($null -eq $successor) {
        ""
    }
    else {
        [string]$successor.PayloadSha256
    }
    $descriptorPath = Get-TicketboxC07DescriptorPath $operationId
    if (Test-Path -LiteralPath $descriptorPath) {
        $descriptor = Read-TicketboxC07Descriptor `
            -OperationId $operationId `
            -ReleaseIdentity $ReleaseIdentity `
            -RecoveryEpoch $RecoveryEpoch
        if (
            [string]$descriptor.Payload.database_binding_sha256 -cne
                [string]$database.Fingerprint -or
            [string]$descriptor.Payload.operation_kind -cne $OperationKind -or
            [string]$descriptor.Payload.target_alembic_revision -cne
                $TargetRevision -or
            [string]$descriptor.Payload.revision_manifest_sha256 -cne
                $RevisionManifestSha256 -or
            [string]$descriptor.Payload.successor_intent_sha256 -cne
                $expectedSuccessorIntentSha256
        ) {
            throw "C07 orphan descriptor 不属于 exact successor initialization。"
        }
    }
    else {
        $capturedAtUtc = [DateTime]::UtcNow
        $capturedTickCount64 = [int64][Environment]::TickCount64
        $capturedBootIdentity = Get-TicketboxC07BootIdentity
        $descriptorPayload = [ordered]@{
            schema = $script:TicketboxC07DescriptorSchema
            operation_id = $operationId
            release_fingerprint = $releaseIdentity.Fingerprint
            installation_id = $releaseIdentity.InstallationId
            build_manifest_sha256 = $releaseIdentity.BuildManifestSha256
            backend_version_floor = $releaseIdentity.BackendVersionFloor
            data_root_binding_sha256 = $dataRootHash
            database_binding_sha256 = $database.Fingerprint
            cluster_system_identifier = $database.ClusterSystemIdentifier
            database_name = $database.DatabaseName
            database_oid = [uint32]$database.DatabaseOid
            logical_server_id = $database.ServerId
            data_generation = $database.DataGeneration
            operation_kind = $OperationKind
            source_alembic_revision = "20260722_0001"
            target_alembic_revision = $TargetRevision
            revision_manifest_sha256 = $RevisionManifestSha256
            successor_mode = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.Payload.successor_mode
            }
            successor_intent_sha256 = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.PayloadSha256
            }
            predecessor_operation_id = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_operation_id
            }
            predecessor_terminal_receipt_payload_sha256 = if (
                $null -eq $successor
            ) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_terminal_receipt_payload_sha256
            }
            predecessor_terminal_authority_chain_sha256 = if (
                $null -eq $successor
            ) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_terminal_authority_chain_sha256
            }
            predecessor_terminal_stage = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_terminal_stage
            }
            predecessor_failure_code = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_failure_code
            }
            predecessor_database_binding_sha256 = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_database_binding_sha256
            }
            predecessor_revision_manifest_sha256 = if ($null -eq $successor) {
                ""
            }
            else {
                [string]$successor.Payload.predecessor_revision_manifest_sha256
            }
            recovery_epoch_id = [string]$recoveryEpoch.Payload.recovery_epoch_id
            recovery_epoch_payload_sha256 = $recoveryEpoch.PayloadSha256
            coordinator_pid = [int]$coordinator.ProcessId
            coordinator_started_filetime_high =
                [uint32]$coordinator.StartedFileTimeHigh
            coordinator_started_filetime_low =
                [uint32]$coordinator.StartedFileTimeLow
            lifecycle_owner_pid = [int]$lifecycleOwner.ProcessId
            lifecycle_owner_started_filetime_high =
                [uint32]$lifecycleOwner.StartedFileTimeHigh
            lifecycle_owner_started_filetime_low =
                [uint32]$lifecycleOwner.StartedFileTimeLow
            initial_heartbeat_sequence = [int64]0
            maintenance_window_ms = [int64](
                $script:TicketboxC07MaintenanceWindowSeconds * 1000
            )
            captured_tick_count64 = $capturedTickCount64
            captured_boot_identity = $capturedBootIdentity
            captured_at_utc = $capturedAtUtc.ToString("o")
        }
        $descriptor = Write-TicketboxC07HostEnvelope `
            -Path $descriptorPath `
            -ArtifactKind "descriptor" `
            -Payload $descriptorPayload
        $descriptor = Read-TicketboxC07Descriptor `
            -OperationId $operationId `
            -ReleaseIdentity $ReleaseIdentity `
            -RecoveryEpoch $RecoveryEpoch
    }
    $heartbeatPath = Get-TicketboxC07HeartbeatPath $operationId
    if (Test-Path -LiteralPath $heartbeatPath) {
        $initialAuthority = [pscustomobject]@{
            Receipt = [pscustomobject]@{ operation_id = $operationId }
            Descriptor = $descriptor
        }
        $initialBinding = [pscustomobject]@{
            PayloadSha256 = $descriptor.PayloadSha256
            Sequence = [int64]0
            CoordinatorIdentity = $descriptor.CoordinatorIdentity
        }
        Read-TicketboxC07HeartbeatForBinding `
            -Authority $initialAuthority `
            -ExpectedBinding $initialBinding `
            -Envelope (
                Read-TicketboxC07HostEnvelope `
                    -Path $heartbeatPath `
                    -ExpectedKind "heartbeat"
            ) | Out-Null
    }
    else {
        $descriptorCoordinator = $descriptor.CoordinatorIdentity
        $heartbeatPayload = [ordered]@{
            schema = $script:TicketboxC07HeartbeatSchema
            operation_id = $operationId
            descriptor_sha256 = $descriptor.PayloadSha256
            coordinator_binding_sha256 = $descriptor.PayloadSha256
            coordinator_binding_sequence = [int64]0
            coordinator_pid = [int]$descriptorCoordinator.ProcessId
            coordinator_started_filetime_high =
                [uint32]$descriptorCoordinator.StartedFileTimeHigh
            coordinator_started_filetime_low =
                [uint32]$descriptorCoordinator.StartedFileTimeLow
            maintenance_attempt_id = ""
            maintenance_attempt_sequence = [int64]0
            maintenance_attempt_sha256 = ""
            maintenance_attempt_failure_sha256 = ""
            sequence = [int64]0
            maintenance_remaining_ceiling_ms = [int64](
                $script:TicketboxC07MaintenanceWindowSeconds * 1000
            )
            observed_at_utc = [DateTime]::UtcNow.ToString("o")
        }
        Write-TicketboxC07HostEnvelope `
            -Path $heartbeatPath `
            -ArtifactKind "heartbeat" `
            -Payload $heartbeatPayload | Out-Null
    }
    $receipt = New-TicketboxC07ReceiptPayload ([pscustomobject]@{
        operation_id = $operationId
        stage = "captured"
        previous_stage = ""
        stage_sequence = 0
        authority_revision = 0
        transition_kind = "captured"
        release_fingerprint = $releaseIdentity.Fingerprint
        descriptor_sha256 = $descriptor.PayloadSha256
        coordinator_binding_sha256 = $descriptor.PayloadSha256
        coordinator_binding_sequence = 0
        database_binding_sha256 = $database.Fingerprint
        recovery_epoch_id = [string]$recoveryEpoch.Payload.recovery_epoch_id
        freeze_proof_sha256 = ""
        freeze_proof_binding_sequence = 0
        freeze_heartbeat_sequence = 0
        ready_verification_sha256 = ""
        previous_receipt_payload_sha256 = ""
        previous_authority_chain_sha256 = ""
        transition_evidence_sha256 = $descriptor.PayloadSha256
        failure_code = ""
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    })
    $authorityPath = Get-TicketboxC07AuthorityPath
    $replaceTerminal = Test-Path -LiteralPath $authorityPath
    if ($replaceTerminal) {
        if ($null -eq $successor) {
            throw "C07 initial operation 不允许覆盖既有 lifecycle authority。"
        }
        $existing = Read-TicketboxC07HostEnvelope `
            -Path $authorityPath `
            -ExpectedKind "authority_receipt"
        if (
            [string]$existing.Payload.operation_id -cne
                [string]$successor.Payload.predecessor_operation_id -or
            [string]$existing.PayloadSha256 -cne
                [string]$successor.Payload.predecessor_terminal_receipt_payload_sha256
        ) {
            throw "C07 successor 只能替换 exact 已归档 predecessor terminal pointer。"
        }
        $archive = Read-TicketboxC07HostEnvelope `
            -Path (
                Get-TicketboxC07TerminalAuthorityArchivePath (
                    [string]$successor.Payload.predecessor_operation_id
                )
            ) `
            -ExpectedKind "authority_receipt"
        if ($archive.Text -cne $existing.Text) {
            throw "C07 predecessor terminal archive 未在 successor publish 前 durable。"
        }
    }
    Write-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07AuthorityPath) `
        -ArtifactKind "authority_receipt" `
        -Payload $receipt `
        -ReplaceExisting:$replaceTerminal | Out-Null
}

function Write-TicketboxC07CoordinatorBindingGeneration {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$CurrentCoordinator,
        [Parameter(Mandatory = $true)][object]$CurrentOwner
    )
    $sequence = [int]$Payload.binding_sequence
    $path = Get-TicketboxC07CoordinatorBindingPath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Sequence $sequence
    if (-not (Test-Path -LiteralPath $path)) {
        return Write-TicketboxC07HostEnvelope `
            -Path $path `
            -ArtifactKind "coordinator_binding" `
            -Payload $Payload
    }
    $existing = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Descriptor $Authority.Descriptor `
        -Sequence $sequence
    $existingPayload = $existing.Payload
    foreach ($field in @(
        "previous_binding_sha256",
        "previous_heartbeat_payload_sha256",
        "previous_heartbeat_sequence",
        "previous_receipt_payload_sha256",
        "previous_authority_chain_sha256",
        "resumed_stage",
        "old_coordinator_pid",
        "old_coordinator_started_filetime_high",
        "old_coordinator_started_filetime_low"
    )) {
        if ([string]$existingPayload.$field -cne [string]$Payload.$field) {
            throw "C07 orphan coordinator binding 与 authoritative predecessor 不一致：$field"
        }
    }
    if (
        Test-TicketboxProcessIdentityEquals `
            $existing.CoordinatorIdentity `
            $CurrentCoordinator
    ) {
        if (
            -not (
                Test-TicketboxProcessIdentityEquals `
                    $existing.LifecycleOwnerIdentity `
                    $CurrentOwner
            )
        ) {
            throw "C07 orphan coordinator binding 当前进程匹配但 lifecycle owner 不一致。"
        }
        return [pscustomobject]@{
            PayloadSha256 = $existing.PayloadSha256
            Payload = $existing.Payload
        }
    }
    Assert-TicketboxC07PriorProcessIdentityDead $existing.CoordinatorIdentity
    return Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "coordinator_binding" `
        -Payload $Payload `
        -ReplaceExisting
}

function Complete-TicketboxC07TakeoverHeartbeatTransition {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $currentOwner = Assert-TicketboxC07LifecycleLease $LifecycleLock
    $currentCoordinator = Get-TicketboxProcessIdentity -ProcessId $PID
    $path = Get-TicketboxC07HeartbeatPath (
        [string]$Authority.Receipt.operation_id
    )
    $heartbeat = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "heartbeat"
    $payload = $heartbeat.Payload
    if (
        [string]$payload.coordinator_binding_sha256 -ceq
            [string]$Authority.Binding.PayloadSha256 -and
        [int64]$payload.coordinator_binding_sequence -eq
            [int64]$Authority.Binding.Sequence
    ) {
        return Read-TicketboxC07HeartbeatForBinding `
            -Authority $Authority `
            -ExpectedBinding $Authority.Binding `
            -Envelope $heartbeat
    }
    if (
        [string]$Authority.Receipt.transition_kind -cne "takeover" -or
        [int64]$Authority.Binding.Sequence -lt 1
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 heartbeat binding 漂移且不存在可恢复 takeover transition。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch")
    }
    $bindingPayload = $Authority.Binding.Payload
    if (
        $heartbeat.PayloadSha256 -cne
            [string]$bindingPayload.previous_heartbeat_payload_sha256 -or
        [int64]$payload.sequence -ne
            [int64]$bindingPayload.previous_heartbeat_sequence -or
        [string]$payload.coordinator_binding_sha256 -cne
            [string]$bindingPayload.previous_binding_sha256 -or
        [int64]$payload.coordinator_binding_sequence -ne
            ([int64]$Authority.Binding.Sequence - 1)
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 orphan takeover heartbeat 不匹配 precommitted predecessor。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch")
    }
    $previousBinding = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Descriptor $Authority.Descriptor `
        -Sequence ([int]$payload.coordinator_binding_sequence) `
        -ExpectedPayloadSha256 (
            [string]$bindingPayload.previous_binding_sha256
        )
    try {
        Read-TicketboxC07HeartbeatForBinding `
            -Authority $Authority `
            -ExpectedBinding $previousBinding `
            -Envelope $heartbeat | Out-Null
    }
    catch {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 orphan takeover predecessor heartbeat 验证失败。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch" `
            -InnerException $_.Exception)
    }
    Assert-TicketboxC07PriorProcessIdentityDead `
        $previousBinding.CoordinatorIdentity
    if (Test-TicketboxProcessIdentityEquals `
        $currentCoordinator `
        $Authority.Binding.CoordinatorIdentity) {
        if (-not (Test-TicketboxProcessIdentityEquals `
            $currentOwner `
            $Authority.Binding.LifecycleOwnerIdentity)) {
            throw "C07 takeover heartbeat reconciliation owner 不一致。"
        }
        Assert-TicketboxC07LiveProcessIdentity $currentCoordinator
    }
    else {
        Assert-TicketboxC07PriorProcessIdentityDead `
            $Authority.Binding.CoordinatorIdentity
    }
    $bindingCoordinator = $Authority.Binding.CoordinatorIdentity
    $reconciled = [ordered]@{
        schema = $script:TicketboxC07HeartbeatSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        coordinator_binding_sha256 = $Authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$Authority.Binding.Sequence
        coordinator_pid = [int]$bindingCoordinator.ProcessId
        coordinator_started_filetime_high =
            [uint32]$bindingCoordinator.StartedFileTimeHigh
        coordinator_started_filetime_low =
            [uint32]$bindingCoordinator.StartedFileTimeLow
        maintenance_attempt_id = [string]$payload.maintenance_attempt_id
        maintenance_attempt_sequence =
            [int64]$payload.maintenance_attempt_sequence
        maintenance_attempt_sha256 =
            [string]$payload.maintenance_attempt_sha256
        maintenance_attempt_failure_sha256 =
            [string]$payload.maintenance_attempt_failure_sha256
        sequence = [int64]$payload.sequence + 1
        maintenance_remaining_ceiling_ms =
            [int64]$payload.maintenance_remaining_ceiling_ms
        observed_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "heartbeat" `
        -Payload $reconciled `
        -ReplaceExisting | Out-Null
    return Read-TicketboxC07Heartbeat $Authority
}

function Resume-TicketboxC07LifecycleOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Authority.Receipt.stage -eq "ready" -or
        [string]$Authority.Receipt.stage -in $script:TicketboxC07FailureStages
    ) {
        return $Authority
    }
    $currentCoordinator = Get-TicketboxProcessIdentity -ProcessId $PID
    $currentOwner = Assert-TicketboxC07LifecycleLease $LifecycleLock
    $oldHeartbeat = Complete-TicketboxC07TakeoverHeartbeatTransition `
        -Authority $Authority `
        -LifecycleLock $LifecycleLock
    if (
        (Test-TicketboxProcessIdentityEquals `
            $currentCoordinator `
            $Authority.Binding.CoordinatorIdentity) -and
        (Test-TicketboxProcessIdentityEquals `
            $currentOwner `
            $Authority.Binding.LifecycleOwnerIdentity)
    ) {
        Assert-TicketboxC07LiveProcessIdentity $currentCoordinator
        if (
            [string]$Authority.Receipt.stage -in @(
                "writers_frozen",
                "recovery_generation_ready"
            ) -and
            [int64]$Authority.Receipt.freeze_proof_binding_sequence -ne
                [int64]$Authority.Binding.Sequence
        ) {
            return Update-TicketboxC07FreezeProofBinding `
                -Authority $Authority `
                -LifecycleLock $LifecycleLock
        }
        return $Authority
    }
    Assert-TicketboxC07PriorProcessIdentityDead $Authority.Binding.CoordinatorIdentity
    $sequence = [int64]$Authority.Binding.Sequence + 1
    if ($sequence -gt [int]::MaxValue) {
        throw "C07 coordinator binding sequence 已耗尽。"
    }
    $old = $Authority.Binding.CoordinatorIdentity
    $payload = [ordered]@{
        schema = $script:TicketboxC07CoordinatorBindingSchema
        operation_id = [string]$Authority.Receipt.operation_id
        binding_sequence = $sequence
        previous_binding_sha256 = $Authority.Binding.PayloadSha256
        previous_heartbeat_payload_sha256 = $oldHeartbeat.PayloadSha256
        previous_heartbeat_sequence = [int64]$oldHeartbeat.Payload.sequence
        previous_receipt_payload_sha256 = $Authority.Envelope.PayloadSha256
        previous_authority_chain_sha256 = [string]$Authority.Receipt.authority_chain_sha256
        resumed_stage = [string]$Authority.Receipt.stage
        old_coordinator_pid = [int]$old.ProcessId
        old_coordinator_started_filetime_high = [uint32]$old.StartedFileTimeHigh
        old_coordinator_started_filetime_low = [uint32]$old.StartedFileTimeLow
        new_coordinator_pid = [int]$currentCoordinator.ProcessId
        new_coordinator_started_filetime_high = [uint32]$currentCoordinator.StartedFileTimeHigh
        new_coordinator_started_filetime_low = [uint32]$currentCoordinator.StartedFileTimeLow
        new_lifecycle_owner_pid = [int]$currentOwner.ProcessId
        new_lifecycle_owner_started_filetime_high = [uint32]$currentOwner.StartedFileTimeHigh
        new_lifecycle_owner_started_filetime_low = [uint32]$currentOwner.StartedFileTimeLow
        resumed_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $binding = Write-TicketboxC07CoordinatorBindingGeneration `
        -Authority $Authority `
        -Payload $payload `
        -CurrentCoordinator $currentCoordinator `
        -CurrentOwner $currentOwner
    $receipt = New-TicketboxC07ReceiptPayload ([pscustomobject]@{
        operation_id = [string]$Authority.Receipt.operation_id
        stage = [string]$Authority.Receipt.stage
        previous_stage = [string]$Authority.Receipt.previous_stage
        stage_sequence = [int64]$Authority.Receipt.stage_sequence
        authority_revision = [int64]$Authority.Receipt.authority_revision + 1
        transition_kind = "takeover"
        release_fingerprint = [string]$Authority.Receipt.release_fingerprint
        descriptor_sha256 = [string]$Authority.Receipt.descriptor_sha256
        coordinator_binding_sha256 = $binding.PayloadSha256
        coordinator_binding_sequence = $sequence
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$Authority.Receipt.recovery_epoch_id
        freeze_proof_sha256 = [string]$Authority.Receipt.freeze_proof_sha256
        freeze_proof_binding_sequence =
            [int64]$Authority.Receipt.freeze_proof_binding_sequence
        freeze_heartbeat_sequence = [int64]$Authority.Receipt.freeze_heartbeat_sequence
        ready_verification_sha256 = [string]$Authority.Receipt.ready_verification_sha256
        previous_receipt_payload_sha256 = $Authority.Envelope.PayloadSha256
        previous_authority_chain_sha256 = [string]$Authority.Receipt.authority_chain_sha256
        transition_evidence_sha256 = [string]$Authority.Receipt.transition_evidence_sha256
        failure_code = ""
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    })
    Write-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07AuthorityPath) `
        -ArtifactKind "authority_receipt" `
        -Payload $receipt `
        -ReplaceExisting | Out-Null
    $updated = Read-TicketboxC07Authority $Authority.ReleaseIdentity.DataRoot
    $newHeartbeat = [ordered]@{
        schema = $script:TicketboxC07HeartbeatSchema
        operation_id = [string]$updated.Receipt.operation_id
        descriptor_sha256 = $updated.Descriptor.PayloadSha256
        coordinator_binding_sha256 = $updated.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$updated.Binding.Sequence
        coordinator_pid = [int]$currentCoordinator.ProcessId
        coordinator_started_filetime_high = [uint32]$currentCoordinator.StartedFileTimeHigh
        coordinator_started_filetime_low = [uint32]$currentCoordinator.StartedFileTimeLow
        maintenance_attempt_id =
            [string]$oldHeartbeat.Payload.maintenance_attempt_id
        maintenance_attempt_sequence =
            [int64]$oldHeartbeat.Payload.maintenance_attempt_sequence
        maintenance_attempt_sha256 =
            [string]$oldHeartbeat.Payload.maintenance_attempt_sha256
        maintenance_attempt_failure_sha256 =
            [string]$oldHeartbeat.Payload.maintenance_attempt_failure_sha256
        sequence = [int64]$oldHeartbeat.Payload.sequence + 1
        maintenance_remaining_ceiling_ms =
            [int64]$oldHeartbeat.Payload.maintenance_remaining_ceiling_ms
        observed_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07HeartbeatPath ([string]$updated.Receipt.operation_id)) `
        -ArtifactKind "heartbeat" `
        -Payload $newHeartbeat `
        -ReplaceExisting | Out-Null
    $updated = Read-TicketboxC07Authority $Authority.ReleaseIdentity.DataRoot
    if (
        [string]$updated.Receipt.stage -in @(
            "writers_frozen",
            "recovery_generation_ready"
        )
    ) {
        $updated = Update-TicketboxC07FreezeProofBinding `
            -Authority $updated `
            -LifecycleLock $LifecycleLock
    }
    return $updated
}

function New-TicketboxC07LifecycleOperation {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [string]$ExpectedOperationId = "",
        [string]$TargetRevision = $script:TicketboxC07TargetRevision,
        [ValidateSet("c07_money_minor_bigint_v1")]
        [string]$OperationKind = "c07_money_minor_bigint_v1",
        [string]$RevisionManifestSha256 = "",
        [AllowNull()][object]$SuccessorIntent
    )
    Set-TicketboxC07DatabaseAuthorityCredential $SuperuserPassword
    $releaseIdentity = Get-TicketboxC07ReleaseIdentity `
        -DataRoot $DataRoot `
        -ExpectedInstallationOperationId $ExpectedOperationId
    if ([string]::IsNullOrEmpty($RevisionManifestSha256)) {
        $RevisionManifestSha256 = [string]$releaseIdentity.BuildManifestSha256
    }
    Assert-TicketboxC07Sha256 `
        $RevisionManifestSha256 `
        "requested revision manifest"
    Initialize-TicketboxC07ArtifactRoots $releaseIdentity | Out-Null
    $recoveryEpoch = Initialize-TicketboxC07RecoveryEpoch $releaseIdentity
    if (Test-Path -LiteralPath (Get-TicketboxC07AuthorityPath)) {
        $authorityEnvelope = Read-TicketboxC07HostEnvelope `
            -Path (Get-TicketboxC07AuthorityPath) `
            -ExpectedKind "authority_receipt"
        $authorityOperationId = ConvertTo-TicketboxC07CanonicalOperationId (
            [string]$authorityEnvelope.Payload.operation_id
        )
        $expectedCanonicalOperationId = if (
            [string]::IsNullOrEmpty($ExpectedOperationId)
        ) {
            ""
        }
        else {
            ConvertTo-TicketboxC07CanonicalOperationId $ExpectedOperationId
        }
        $publishingSuccessor = (
            $null -ne $SuccessorIntent -and
            $authorityOperationId -ceq
                [string]$SuccessorIntent.Payload.predecessor_operation_id -and
            $expectedCanonicalOperationId -ceq
                [string]$SuccessorIntent.Payload.successor_operation_id
        )
        if ($publishingSuccessor) {
            New-TicketboxC07InitialOperation `
                -DataRoot $DataRoot `
                -LifecycleLock $LifecycleLock `
                -ReleaseIdentity $releaseIdentity `
                -RecoveryEpoch $recoveryEpoch `
                -ExpectedOperationId $ExpectedOperationId `
                -TargetRevision $TargetRevision `
                -OperationKind $OperationKind `
                -RevisionManifestSha256 $RevisionManifestSha256 `
                -SuccessorIntent $SuccessorIntent
            $authority = Read-TicketboxC07Authority `
                -DataRoot $DataRoot `
                -ExpectedInstallationOperationId $ExpectedOperationId
            $authority = Resume-TicketboxC07LifecycleOperation `
                -Authority $authority `
                -LifecycleLock $LifecycleLock
        }
        else {
            $authority = Read-TicketboxC07Authority `
                -DataRoot $DataRoot `
                -ExpectedInstallationOperationId $ExpectedOperationId
            $matchesRequestedOperation = (
                [string]$authority.Descriptor.Payload.operation_kind -ceq
                    $OperationKind -and
                [string]$authority.Descriptor.Payload.target_alembic_revision -ceq
                    $TargetRevision -and
                [string]$authority.Descriptor.Payload.revision_manifest_sha256 -ceq
                    $RevisionManifestSha256
            )
            if (-not $matchesRequestedOperation) {
                throw "C07 existing lifecycle authority 与 requested target/manifest 不一致。"
            }
            elseif ([string]$authority.Receipt.stage -ceq "ready") {
                # Exact same immutable operation is an idempotent terminal read.
            }
            else {
                if (
                    -not [string]::IsNullOrEmpty($ExpectedOperationId) -and
                    [string]$authority.Receipt.operation_id -cne
                        $expectedCanonicalOperationId
                ) {
                    throw "C07 existing lifecycle authority 与 expected operation 不一致。"
                }
                $authority = Resume-TicketboxC07LifecycleOperation `
                    -Authority $authority `
                    -LifecycleLock $LifecycleLock
            }
        }
    }
    else {
        New-TicketboxC07InitialOperation `
            -DataRoot $DataRoot `
            -LifecycleLock $LifecycleLock `
            -ReleaseIdentity $releaseIdentity `
            -RecoveryEpoch $recoveryEpoch `
            -ExpectedOperationId $ExpectedOperationId `
            -TargetRevision $TargetRevision `
            -OperationKind $OperationKind `
            -RevisionManifestSha256 $RevisionManifestSha256 `
            -SuccessorIntent $SuccessorIntent
        $authority = Read-TicketboxC07Authority $DataRoot
        $authority = Resume-TicketboxC07LifecycleOperation `
            -Authority $authority `
            -LifecycleLock $LifecycleLock
    }
    $stage = [string]$authority.Receipt.stage
    if (
        $stage -cne "ready" -and
        $stage -notin $script:TicketboxC07FailureStages
    ) {
        Start-TicketboxC07MaintenanceAttempt `
            -Authority $authority `
            -LifecycleLock $LifecycleLock | Out-Null
        $authority = Read-TicketboxC07Authority $DataRoot
        $stage = [string]$authority.Receipt.stage
    }
    if (
        $stage -ceq "ready" -or
        $stage -in $script:TicketboxC07FailureStages
    ) {
        Restore-TicketboxC07TerminalRuntimeProjection `
            -DataRoot $DataRoot `
            -Authority $authority | Out-Null
    }
    else {
        $heartbeat = Read-TicketboxC07Heartbeat $authority
        Write-TicketboxC07RuntimeProjection `
            -Authority $authority `
            -HeartbeatSequence ([int64]$heartbeat.Payload.sequence) | Out-Null
    }
    return [pscustomobject]@{
        OperationId = [string]$authority.Receipt.operation_id
        OperationKind = [string]$authority.Descriptor.Payload.operation_kind
        TargetRevision =
            [string]$authority.Descriptor.Payload.target_alembic_revision
        RevisionManifestSha256 =
            [string]$authority.Descriptor.Payload.revision_manifest_sha256
        Stage = [string]$authority.Receipt.stage
        AuthorityPath = Get-TicketboxC07AuthorityPath
        ProjectionPath = Get-TicketboxC07ProjectionPath
        ReleaseFingerprint = $releaseIdentity.Fingerprint
        DatabaseBindingSha256 = [string]$authority.Receipt.database_binding_sha256
        RecoveryEpochId = [string]$authority.Receipt.recovery_epoch_id
        CoordinatorBindingSequence = [int64]$authority.Binding.Sequence
        SuccessorMode = [string]$authority.Descriptor.Payload.successor_mode
    }
}

function New-TicketboxC07FreezeProof {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    $heartbeat = Read-TicketboxC07Heartbeat $Authority
    $heartbeatSequence = [int64]$heartbeat.Payload.sequence
    if ($heartbeatSequence -lt 1) {
        throw "C07 writers_frozen 前至少需要一次可验证 heartbeat observation。"
    }
    $serviceState = [string](
        Get-TicketboxServiceState $Authority.ReleaseIdentity.BackendServiceName
    )
    $serviceStartPolicy = [string](
        Get-TicketboxServiceStartPolicy $Authority.ReleaseIdentity.BackendServiceName
    ).ToLowerInvariant()
    $servicePid = [int](
        Get-TicketboxServiceProcessId $Authority.ReleaseIdentity.BackendServiceName
    )
    $listeners = @(
        Get-TicketboxListeningProcessIds $Authority.ReleaseIdentity.BackendPort
    )
    $runtimeProcesses = @(
        Get-TicketboxExpectedRuntimeProcessIds `
            -ExpectedExecutables @(
                $Authority.ReleaseIdentity.BackendExe,
                $Authority.ReleaseIdentity.ShawlExe
            )
    )
    if (
        $serviceState.ToLowerInvariant() -cne "stopped" -or
        $servicePid -ne 0 -or
        $listeners.Count -ne 0 -or
        $runtimeProcesses.Count -ne 0 -or
        $serviceStartPolicy -cnotin @(
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        )
    ) {
        throw "C07 writers_frozen 前 backend 服务/进程/监听未先静止。"
    }
    $beforeFence = Get-TicketboxC07WriterDatabaseFenceObservation `
        $Authority.ReleaseIdentity
    $intent = Initialize-TicketboxC07WriterFenceIntent `
        -Authority $Authority `
        -ServiceStartPolicy $serviceStartPolicy `
        -Observation $beforeFence
    $serviceStopTimeoutMilliseconds =
        Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
            -MaximumMilliseconds 60000 `
            -Label "C07 backend writer freeze"
    Disable-TicketboxOwnedServiceIfExists `
        -Name $Authority.ReleaseIdentity.BackendServiceName `
        -ExpectedExecutable $Authority.ReleaseIdentity.ShawlExe `
        -TimeoutMilliseconds $serviceStopTimeoutMilliseconds `
        -PollMilliseconds 250 `
        -BackendPort $Authority.ReleaseIdentity.BackendPort `
        -ExpectedRuntimeExecutables @(
            $Authority.ReleaseIdentity.BackendExe,
            $Authority.ReleaseIdentity.ShawlExe
        )
    $databaseFence = Enter-TicketboxC07WriterDatabaseFence `
        -Authority $Authority `
        -Intent $intent
    $serviceState = [string](
        Get-TicketboxServiceState $Authority.ReleaseIdentity.BackendServiceName
    )
    $serviceStartPolicy = [string](
        Get-TicketboxServiceStartPolicy $Authority.ReleaseIdentity.BackendServiceName
    ).ToLowerInvariant()
    $servicePid = [int](
        Get-TicketboxServiceProcessId $Authority.ReleaseIdentity.BackendServiceName
    )
    $listeners = @(
        Get-TicketboxListeningProcessIds $Authority.ReleaseIdentity.BackendPort
    )
    $runtimeProcesses = @(
        Get-TicketboxExpectedRuntimeProcessIds `
            -ExpectedExecutables @(
                $Authority.ReleaseIdentity.BackendExe,
                $Authority.ReleaseIdentity.ShawlExe
            )
    )
    if (
        $serviceState.ToLowerInvariant() -cne "stopped" -or
        $serviceStartPolicy -cne "disabled" -or
        $servicePid -ne 0 -or
        $listeners.Count -ne 0 -or
        $runtimeProcesses.Count -ne 0
    ) {
        throw "C07 durable writer fence 未禁用并清退 backend service/runtime。"
    }
    $coordinator = $Authority.Binding.CoordinatorIdentity
    $owner = $Authority.Binding.LifecycleOwnerIdentity
    $payload = [ordered]@{
        schema = $script:TicketboxC07FreezeProofSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        operation_kind = [string]$Authority.Descriptor.Payload.operation_kind
        target_alembic_revision =
            [string]$Authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256
        release_fingerprint = $Authority.ReleaseIdentity.Fingerprint
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$Authority.Receipt.recovery_epoch_id
        writer_fence_intent_sha256 = $intent.PayloadSha256
        coordinator_binding_sha256 = $Authority.Binding.PayloadSha256
        coordinator_pid = [int]$coordinator.ProcessId
        coordinator_started_filetime_high = [uint32]$coordinator.StartedFileTimeHigh
        coordinator_started_filetime_low = [uint32]$coordinator.StartedFileTimeLow
        lifecycle_owner_pid = [int]$owner.ProcessId
        lifecycle_owner_started_filetime_high = [uint32]$owner.StartedFileTimeHigh
        lifecycle_owner_started_filetime_low = [uint32]$owner.StartedFileTimeLow
        heartbeat_sequence = $heartbeatSequence
        backend_service_state = "stopped"
        backend_service_start_policy = "disabled"
        backend_service_pid = 0
        backend_listener_pid_count = 0
        runtime_process_count = 0
        database_client_session_count =
            [int64]$databaseFence.OtherClientSessionCount
        database_client_sessions = @($databaseFence.ClientSessions)
        database_public_connect = $false
        database_role_capability_count = @($databaseFence.Roles).Count
        database_role_capabilities = @($databaseFence.Roles)
        database_authority_role = "postgres"
        database_authority_scope =
            "process_local_secret_same_session_advisory_cut"
        database_max_prepared_transactions =
            [int64]$databaseFence.MaxPreparedTransactions
        database_prepared_transaction_count =
            [int64]$databaseFence.PreparedTransactionCount
        database_logical_subscription_count =
            [int64]$databaseFence.LogicalSubscriptionCount
        database_logical_apply_worker_count =
            [int64]$databaseFence.LogicalApplyWorkerCount
        database_unexpected_worker_count =
            [int64]$databaseFence.UnexpectedDatabaseWorkerCount
        database_advisory_fence_available = $true
        writers_frozen_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $path = Get-TicketboxC07FreezeProofPath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -BindingSequence ([int]$Authority.Binding.Sequence)
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07HostEnvelope -Path $path -ExpectedKind "freeze_proof"
        Assert-TicketboxC07ExactProperties `
            -Value $existing.Payload `
            -ExpectedNames @($payload.Keys) `
            -ArtifactName "orphan writers frozen proof"
        $sameGeneration = $true
        foreach ($field in @(
            "schema",
            "operation_id",
            "descriptor_sha256",
            "operation_kind",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "release_fingerprint",
            "database_binding_sha256",
            "recovery_epoch_id",
            "writer_fence_intent_sha256",
            "coordinator_binding_sha256",
            "coordinator_pid",
            "coordinator_started_filetime_high",
            "coordinator_started_filetime_low",
            "lifecycle_owner_pid",
            "lifecycle_owner_started_filetime_high",
            "lifecycle_owner_started_filetime_low",
            "heartbeat_sequence",
            "backend_service_state",
            "backend_service_start_policy",
            "backend_service_pid",
            "backend_listener_pid_count",
            "runtime_process_count",
            "database_client_session_count",
            "database_client_sessions",
            "database_public_connect",
            "database_role_capability_count",
            "database_role_capabilities",
            "database_authority_role",
            "database_authority_scope",
            "database_max_prepared_transactions",
            "database_prepared_transaction_count",
            "database_logical_subscription_count",
            "database_logical_apply_worker_count",
            "database_unexpected_worker_count",
            "database_advisory_fence_available"
        )) {
            if ([string]$existing.Payload.$field -cne [string]$payload.$field) {
                $sameGeneration = $false
                break
            }
        }
        if ($sameGeneration) {
            return [pscustomobject]@{
                PayloadSha256 = $existing.PayloadSha256
                HeartbeatSequence = [int64]$existing.Payload.heartbeat_sequence
                BindingSequence = [int64]$Authority.Binding.Sequence
            }
        }
        if (
            [string]$existing.Payload.operation_id -ceq
                [string]$Authority.Receipt.operation_id -and
            [string]$existing.Payload.descriptor_sha256 -ceq
                $Authority.Descriptor.PayloadSha256 -and
            [string]$existing.Payload.release_fingerprint -ceq
                $Authority.ReleaseIdentity.Fingerprint -and
            [string]$existing.Payload.database_binding_sha256 -ceq
                [string]$Authority.Receipt.database_binding_sha256 -and
            [string]$existing.Payload.recovery_epoch_id -ceq
                [string]$Authority.Receipt.recovery_epoch_id -and
            [string]$existing.Payload.writer_fence_intent_sha256 -ceq
                $intent.PayloadSha256
        ) {
            $isReferenced = (
                -not [string]::IsNullOrEmpty(
                    [string]$Authority.Receipt.freeze_proof_sha256
                ) -and
                [int64]$Authority.Receipt.freeze_proof_binding_sequence -eq
                    [int64]$Authority.Binding.Sequence
            )
            if ($isReferenced) {
                throw "C07 当前 authority 已引用不同 freeze proof，拒绝覆盖。"
            }
            $oldCoordinator = New-TicketboxC07IdentityFromPayload `
                $existing.Payload `
                "coordinator"
            Assert-TicketboxC07PriorProcessIdentityDead $oldCoordinator
        }
        else {
            throw "C07 orphan freeze proof 未绑定 authoritative operation lineage。"
        }
    }
    $envelope = Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "freeze_proof" `
        -Payload $payload `
        -ReplaceExisting:(Test-Path -LiteralPath $path)
    return [pscustomobject]@{
        PayloadSha256 = $envelope.PayloadSha256
        HeartbeatSequence = $heartbeatSequence
        BindingSequence = [int64]$Authority.Binding.Sequence
    }
}

function Update-TicketboxC07FreezeProofBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Authority.Receipt.stage -notin @(
            "writers_frozen",
            "recovery_generation_ready"
        )
    ) {
        throw "C07 只能在 durable writer-fence window 刷新 freeze proof binding。"
    }
    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    if (
        [int64]$Authority.Receipt.freeze_proof_binding_sequence -eq
            [int64]$Authority.Binding.Sequence
    ) {
        return $Authority
    }
    $freeze = New-TicketboxC07FreezeProof `
        -Authority $Authority `
        -LifecycleLock $LifecycleLock
    $transitionEvidenceSha256 = [string]$Authority.Receipt.transition_evidence_sha256
    if ([string]$Authority.Receipt.stage -ceq "writers_frozen") {
        $transitionEvidenceSha256 = $freeze.PayloadSha256
    }
    $receipt = New-TicketboxC07ReceiptPayload ([pscustomobject]@{
        operation_id = [string]$Authority.Receipt.operation_id
        stage = [string]$Authority.Receipt.stage
        previous_stage = [string]$Authority.Receipt.previous_stage
        stage_sequence = [int64]$Authority.Receipt.stage_sequence
        authority_revision = [int64]$Authority.Receipt.authority_revision + 1
        transition_kind = "takeover"
        release_fingerprint = [string]$Authority.Receipt.release_fingerprint
        descriptor_sha256 = [string]$Authority.Receipt.descriptor_sha256
        coordinator_binding_sha256 = [string]$Authority.Receipt.coordinator_binding_sha256
        coordinator_binding_sequence = [int64]$Authority.Receipt.coordinator_binding_sequence
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$Authority.Receipt.recovery_epoch_id
        freeze_proof_sha256 = $freeze.PayloadSha256
        freeze_proof_binding_sequence = [int64]$freeze.BindingSequence
        freeze_heartbeat_sequence = [int64]$freeze.HeartbeatSequence
        ready_verification_sha256 = [string]$Authority.Receipt.ready_verification_sha256
        previous_receipt_payload_sha256 = $Authority.Envelope.PayloadSha256
        previous_authority_chain_sha256 = [string]$Authority.Receipt.authority_chain_sha256
        transition_evidence_sha256 = $transitionEvidenceSha256
        failure_code = ""
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    })
    Write-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07AuthorityPath) `
        -ArtifactKind "authority_receipt" `
        -Payload $receipt `
        -ReplaceExisting | Out-Null
    return Read-TicketboxC07Authority $Authority.ReleaseIdentity.DataRoot
}

function Resolve-TicketboxC07ForwardRepairRecovery {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    if (
        [string]$authority.Descriptor.Payload.successor_mode -cne
            "forward_repair"
    ) {
        throw "C07 forward-repair recovery resolver 拒绝非 forward successor。"
    }
    $intent = Read-TicketboxC07SuccessorIntent `
        -OperationId ([string]$authority.Receipt.operation_id) `
        -SuccessorReleaseIdentity $authority.ReleaseIdentity
    $predecessor = Read-TicketboxC07HistoricalTerminalAuthority `
        -DataRoot $DataRoot `
        -ReleaseIdentity $intent.PredecessorReleaseIdentity `
        -AuthorityPath (
            Get-TicketboxC07TerminalAuthorityArchivePath (
                [string]$intent.Payload.predecessor_operation_id
            )
        )
    $recovery = Read-TicketboxC07HistoricalProductionRecoveryGeneration `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -PredecessorAuthority $predecessor `
        -SuccessorIntent $intent `
        -SuperuserPassword $SuperuserPassword
    Assert-TicketboxC07ProductionRecoveryGeneration `
        -Recovery $recovery `
        -Authority $authority `
        -RecoveryAuthority $predecessor
    $targetGenerationSha256 =
        [string]$intent.Payload.predecessor_target_recovery_generation_evidence_sha256
    $targetRestoreSha256 =
        [string]$intent.Payload.predecessor_target_isolated_restore_evidence_sha256
    if (
        [string]::IsNullOrEmpty($targetGenerationSha256) -xor
        [string]::IsNullOrEmpty($targetRestoreSha256)
    ) {
        throw "C07 forward-repair predecessor target recovery lineage 不完整。"
    }
    $targetRecovery = $null
    if (-not [string]::IsNullOrEmpty($targetGenerationSha256)) {
        $targetRecovery =
            Read-TicketboxC07HistoricalProductionTargetRecoveryGeneration `
                -DataRoot $DataRoot `
                -LifecycleLock $LifecycleLock `
                -PredecessorAuthority $predecessor `
                -SuccessorIntent $intent `
                -SuperuserPassword $SuperuserPassword
    }
    return [pscustomobject]@{
        Authority = $authority
        Intent = $intent
        PredecessorAuthority = $predecessor
        Recovery = $recovery
        TargetRecovery = $targetRecovery
    }
}

function Assert-TicketboxC07ProductionRecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][object]$Recovery,
        [Parameter(Mandatory = $true)][object]$Authority,
        [object]$RecoveryAuthority = $Authority
    )
    Assert-TicketboxC07ExactProperties `
        $Recovery `
        @(
            "Schema",
            "OperationId",
            "Result",
            "Payload",
            "PayloadSha256",
            "ManifestPath",
            "DumpPath",
            "InventoryPath",
            "CopiesPath",
            "Root",
            "LifecycleAuthorityChainSha256",
            "StageEvidenceSha256",
            "SourceDatabaseIdentity",
            "RestoreEvidence"
        ) `
        "production recovery generation"
    Assert-TicketboxC07ExactProperties `
        $Recovery.SourceDatabaseIdentity `
        @(
            "Database",
            "ClusterSystemIdentifier",
            "DatabaseOid",
            "GenerationPayloadSha256"
        ) `
        "production recovery source database identity"
    Assert-TicketboxC07ExactProperties `
        $Recovery.RestoreEvidence `
        @("Payload", "PayloadSha256", "Path") `
        "production isolated restore evidence"
    Assert-TicketboxC07LowerSha256 `
        ([string]$Recovery.PayloadSha256) `
        "production recovery manifest"
    Assert-TicketboxC07Sha256 `
        ([string]$Recovery.LifecycleAuthorityChainSha256) `
        "production recovery root authority"
    Assert-TicketboxC07Sha256 `
        ([string]$Recovery.StageEvidenceSha256) `
        "production recovery stage evidence"
    Assert-TicketboxC07LowerSha256 `
        ([string]$Recovery.RestoreEvidence.PayloadSha256) `
        "production isolated restore evidence"
    $payload = $Recovery.Payload
    $paths = Get-TicketboxC07RecoveryPaths $RecoveryAuthority
    if (
        [string]$Recovery.Schema -cne
            "ticketbox-c07-production-recovery-generation-v1" -or
        [string]$Recovery.OperationId -cne
            [string]$RecoveryAuthority.Receipt.operation_id -or
        [string]$Recovery.Result -cne
            "production_recovery_generation_verified" -or
        [string]$payload.schema -cne "ticketbox-c07-recovery-generation-v3" -or
        [string]$payload.operation_id -cne
            [string]$RecoveryAuthority.Receipt.operation_id -or
        [string]$payload.release.fingerprint -cne
            [string]$RecoveryAuthority.Receipt.release_fingerprint -or
        [string]$payload.release.installation_id -cne
            [string]$RecoveryAuthority.ReleaseIdentity.InstallationId -or
        [string]$payload.release.build_manifest_sha256 -cne
            [string]$RecoveryAuthority.ReleaseIdentity.BuildManifestSha256 -or
        [string]$payload.release.backend_version -cne
            [string]$RecoveryAuthority.ReleaseIdentity.BackendVersionFloor -or
        [string]$payload.lifecycle.stage -cne "writers_frozen" -or
        [string]$payload.lifecycle.authority_chain_sha256 -cne
            [string]$Recovery.LifecycleAuthorityChainSha256 -or
        [string]$payload.lifecycle.freeze_proof_sha256 -cne
            [string]$RecoveryAuthority.Receipt.freeze_proof_sha256 -or
        [string]$Recovery.SourceDatabaseIdentity.Database -cne "ticketbox" -or
        [string]$Recovery.SourceDatabaseIdentity.ClusterSystemIdentifier -cne
                [string]$RecoveryAuthority.Descriptor.Payload.cluster_system_identifier -or
        [string]$Recovery.SourceDatabaseIdentity.DatabaseOid -cne
            [string]$RecoveryAuthority.Descriptor.Payload.database_oid -or
        [string]$Recovery.SourceDatabaseIdentity.GenerationPayloadSha256 -cne
            [string]$Recovery.PayloadSha256 -or
        -not (Test-TicketboxPathEquals $Recovery.Root $paths.ReadyRoot) -or
        -not (
            Test-TicketboxPathEquals `
                $Recovery.ManifestPath `
                (Join-Path $paths.ReadyRoot $paths.ManifestFileName)
        )
    ) {
        throw "C07 production recovery generation 未绑定 fixed READY root/source authority。"
    }
    $generationEvidence = Read-TicketboxC07StageEvidence `
        -Authority $RecoveryAuthority `
        -Stage "recovery_generation_ready"
    $generationProducer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$generationEvidence.Payload.producer_payload_json) `
        -Label "production recovery generation producer"
    if (
        $generationEvidence.PayloadSha256 -cne
            [string]$Recovery.StageEvidenceSha256 -or
        [string]$generationEvidence.Payload.source_stage -cne "writers_frozen" -or
        [int64]$generationEvidence.Payload.source_stage_sequence -ne 1 -or
        [string]$generationEvidence.Payload.source_authority_chain_sha256 -cne
            [string]$Recovery.LifecycleAuthorityChainSha256 -or
        [string]$generationProducer.subject_sha256 -cne
            ([string]$Recovery.PayloadSha256).ToUpperInvariant()
    ) {
        throw "C07 production recovery manifest 未绑定 writers_frozen root/stage evidence。"
    }
    $restoreEvidence = Read-TicketboxC07StageEvidence `
        -Authority $RecoveryAuthority `
        -Stage "isolated_restore_verified"
    $restoreProducer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$restoreEvidence.Payload.producer_payload_json) `
        -Label "production restore producer"
    if (
        [string]$restoreProducer.subject_sha256 -cne
            ([string]$Recovery.RestoreEvidence.PayloadSha256).ToUpperInvariant()
    ) {
        throw "C07 production recovery 未绑定 isolated-restore durable evidence。"
    }
}

function Invoke-TicketboxC07ProductionLifecycleCoordinator {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [AllowNull()][Security.SecureString]$RuntimePassword,
        [AllowNull()][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][scriptblock]$MigrationAction,
        [Parameter(Mandatory = $true)][scriptblock]$TargetSemanticAction,
        [switch]$StopAfterMigrationCompleted,
        [switch]$ValidateExistingProductionAuthority
    )
    foreach ($commandName in @(
        "Get-TicketboxC07RecoveryPaths",
        "Read-TicketboxC07ProductionRecoveryGeneration",
        "Invoke-TicketboxC07ProductionAuthorityCoordinator"
    )) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "C07 production lifecycle 缺少权威依赖：$commandName"
        }
    }
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $createdMaintenanceBudget = $false
    if ($null -eq $script:TicketboxC07ActiveMaintenanceBudget) {
        $script:TicketboxC07ActiveMaintenanceBudget =
            New-TicketboxC07MaintenanceBudget $authority
        $createdMaintenanceBudget = $true
    }
    elseif (
        [string]$script:TicketboxC07ActiveMaintenanceBudget.OperationId -cne
            [string]$authority.Receipt.operation_id -or
        [string]$script:TicketboxC07ActiveMaintenanceBudget.AttemptId -cne
            [string](
                (Read-TicketboxC07Heartbeat $authority).Payload.maintenance_attempt_id
            )
    ) {
        throw "C07 active maintenance budget 绑定了其他 operation/attempt。"
    }
    $maintenanceBudget = $script:TicketboxC07ActiveMaintenanceBudget
    $maintenanceWindowMilliseconds =
        $script:TicketboxC07MaintenanceWindowSeconds * 1000
    try {
      $boundedMigratorValidUntilUtc =
          Get-TicketboxC07BoundedMigratorValidUntilUtc `
              -RequestedValidUntilUtc $MigratorValidUntilUtc `
              -Budget $maintenanceBudget
      $currentMaintenanceCeiling =
          Get-TicketboxC07RemainingMaintenanceMilliseconds `
        -Budget $maintenanceBudget `
        -MaximumMilliseconds $maintenanceWindowMilliseconds `
        -Label "C07 production DDL preflight"
    $expectedCoordinatorStage = "ddl_started"
    $expectedCoordinatorSequence = [int64]4
    if (-not $StopAfterMigrationCompleted) {
        $expectedCoordinatorStage = "target_isolated_restore_verified"
        $expectedCoordinatorSequence = [int64]7
    }
    if (
        [string]$authority.Receipt.stage -cne $expectedCoordinatorStage -or
        [int64]$authority.Receipt.stage_sequence -ne
            $expectedCoordinatorSequence
    ) {
        throw "C07 production coordinator lifecycle stage/sequence 无效。"
    }
    if (
        [string]$ExpectedSourceRevision -cne
            [string]$authority.Descriptor.Payload.source_alembic_revision
    ) {
        throw "C07 production coordinator source revision 未绑定 captured descriptor。"
    }
    if ($ValidateExistingProductionAuthority -and $StopAfterMigrationCompleted) {
        throw "C07 existing production authority validation 不接受 DDL-only mode。"
    }
    $existingProductionAuthority = $null
    if ($ValidateExistingProductionAuthority) {
        $existingProductionAuthority =
            Read-TicketboxC07ProductionAuthority $authority
    }
    Assert-TicketboxC07WriterFenceWindow -Authority $authority
    $successorMode = [string]$authority.Descriptor.Payload.successor_mode
    $successorIntent = $null
    $recoveryAuthority = $authority
    $predecessorTargetRecovery = $null
    if (-not [string]::IsNullOrEmpty($successorMode)) {
        $successorIntent = Read-TicketboxC07SuccessorIntent `
            -OperationId ([string]$authority.Receipt.operation_id) `
            -SuccessorReleaseIdentity $authority.ReleaseIdentity
    }
    if ($successorMode -ceq "forward_repair") {
        $lineage = Resolve-TicketboxC07ForwardRepairRecovery `
            -DataRoot $DataRoot `
            -LifecycleLock $LifecycleLock `
            -SuperuserPassword $SuperuserPassword
        $successorIntent = $lineage.Intent
        $recoveryAuthority = $lineage.PredecessorAuthority
        $recovery = $lineage.Recovery
        $predecessorTargetRecovery = $lineage.TargetRecovery
    }
    else {
        $recovery = Read-TicketboxC07ProductionRecoveryGeneration `
            -DataRoot $DataRoot `
            -LifecycleLock $LifecycleLock `
            -SuperuserPassword $SuperuserPassword
    }
    Assert-TicketboxC07ProductionRecoveryGeneration `
        -Recovery $recovery `
        -Authority $authority `
        -RecoveryAuthority $recoveryAuthority
    $targetRecovery = $null
    if (-not $StopAfterMigrationCompleted) {
        $targetRecovery =
            Read-TicketboxC07ProductionTargetRecoveryGeneration `
                -DataRoot $DataRoot `
                -LifecycleLock $LifecycleLock `
                -SuperuserPassword $SuperuserPassword
    }
    $heartbeat = Read-TicketboxC07Heartbeat $authority
    $lifecycleAuthority = [pscustomobject][ordered]@{
        schema = "ticketbox-c07-production-lifecycle-binding-v2"
        operation_id = [string]$authority.Receipt.operation_id
        root_authority_chain_sha256 =
            [string]$recovery.LifecycleAuthorityChainSha256
        current_authority_chain_sha256 =
            [string]$authority.Receipt.authority_chain_sha256
        current_receipt_payload_sha256 = $authority.Envelope.PayloadSha256
        current_stage = $expectedCoordinatorStage
        current_stage_sequence = $expectedCoordinatorSequence
        current_coordinator_binding_sha256 =
            [string]$authority.Binding.PayloadSha256
        current_coordinator_binding_sequence =
            [int64]$authority.Binding.Sequence
        current_heartbeat_sequence = [int64]$heartbeat.Payload.sequence
        current_freeze_proof_sha256 =
            [string]$authority.Receipt.freeze_proof_sha256
        recovery_manifest_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$recovery.PayloadSha256) `
                "production recovery manifest"
        )
        target_recovery_manifest_sha256 = if ($null -ne $targetRecovery) {
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$targetRecovery.PayloadSha256) `
                "production target recovery manifest"
        }
        else {
            "0" * 64
        }
    }
    $uploadRootBindingSha256 =
        [string]$recovery.Payload.integrity.upload_root_binding_sha256
    Assert-TicketboxC07LowerSha256 `
        $uploadRootBindingSha256 `
        "production migration upload-root binding"
    if ($uploadRootBindingSha256 -ceq ("0" * 64)) {
        throw "C07 production migration upload-root binding 不能为零。"
    }
    $migrationContext = [pscustomobject][ordered]@{
        schema = $script:TicketboxC07ProductionMigrationContextSchema
        operation_id = [string]$authority.Receipt.operation_id
        release_fingerprint = [string]$authority.Receipt.release_fingerprint
        migration_helper_relative_path =
            [string]$authority.ReleaseIdentity.MigrationHelperRelativePath
        migration_helper_size =
            [int64]$authority.ReleaseIdentity.MigrationHelperSize
        migration_helper_sha256 =
            [string]$authority.ReleaseIdentity.MigrationHelperSha256
        database_binding_sha256 =
            [string]$authority.Receipt.database_binding_sha256
        upload_root_binding_sha256 = $uploadRootBindingSha256
        recovery_epoch_id = [string]$authority.Receipt.recovery_epoch_id
        coordinator_binding_sha256 =
            [string]$authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$authority.Binding.Sequence
        heartbeat_sequence = [int64]$heartbeat.Payload.sequence
        operation_kind = [string]$authority.Descriptor.Payload.operation_kind
        target_alembic_revision =
            [string]$authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$authority.Descriptor.Payload.revision_manifest_sha256
        successor_mode = $successorMode
        successor_intent_sha256 = if ($null -eq $successorIntent) {
            ""
        }
        else {
            [string]$successorIntent.PayloadSha256
        }
        predecessor_operation_id =
            [string]$authority.Descriptor.Payload.predecessor_operation_id
        predecessor_terminal_authority_chain_sha256 =
            [string]$authority.Descriptor.Payload.predecessor_terminal_authority_chain_sha256
        source_recovery_operation_id =
            [string]$recoveryAuthority.Receipt.operation_id
        source_recovery_release_fingerprint =
            [string]$recoveryAuthority.Receipt.release_fingerprint
        source_recovery_revision_manifest_sha256 =
            [string]$recoveryAuthority.Descriptor.Payload.revision_manifest_sha256
        source_recovery_freeze_proof_sha256 =
            [string]$recoveryAuthority.Receipt.freeze_proof_sha256
        maintenance_deadline_utc = (
            [DateTime]$maintenanceBudget.DeadlineUtc
        ).ToUniversalTime().ToString("o")
        maintenance_remaining_ceiling_ms =
            [int]$currentMaintenanceCeiling
        maintenance_authority_sha256 =
            [string]$heartbeat.Payload.maintenance_attempt_sha256
        writer_freeze_proof_path = Get-TicketboxC07FreezeProofPath `
            -OperationId ([string]$authority.Receipt.operation_id) `
            -BindingSequence (
                [int]$authority.Receipt.freeze_proof_binding_sequence
            )
        writer_freeze_proof_sha256 =
            [string]$authority.Receipt.freeze_proof_sha256
        recovery_manifest_path = [string]$recovery.ManifestPath
        recovery_manifest_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$recovery.PayloadSha256) `
                "production recovery manifest"
        )
        isolated_restore_evidence_path =
            [string]$recovery.RestoreEvidence.Path
        isolated_restore_evidence_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$recovery.RestoreEvidence.PayloadSha256) `
                "production isolated restore evidence"
        )
        lifecycle_root_authority_chain_sha256 =
            [string]$recovery.LifecycleAuthorityChainSha256
    }
    $callerMigrationAction = $MigrationAction
    $callerTargetSemanticAction = $TargetSemanticAction
    $capturedMigrationContext = $migrationContext
    $capturedOperationId = [string]$authority.Receipt.operation_id
    $capturedRevisionManifestSha256 =
        [string]$authority.Descriptor.Payload.revision_manifest_sha256
    $capturedMaintenanceDeadlineUtc =
        [string]$migrationContext.maintenance_deadline_utc
    $capturedMaintenanceAuthoritySha256 =
        [string]$migrationContext.maintenance_authority_sha256
    $capturedMaintenanceBudget = $maintenanceBudget
    $coordinatorMigrationAction = {
        param(
            [object]$HostAuthority,
            [Security.SecureString]$MigrationPassword,
            [string]$SourceRevision,
            [string]$TargetRevision
        )
        $migrationEvidence = & $callerMigrationAction `
            $HostAuthority `
            $MigrationPassword `
            $SourceRevision `
            $TargetRevision `
            $capturedMigrationContext
        if ($null -eq $migrationEvidence) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 packaged migration 未返回 evidence。" `
                -FailureClass "invariant" `
                -FailureCode "resource_shape_mismatch")
        }
        $remainingCeiling =
            Get-TicketboxC07RemainingMaintenanceMilliseconds `
                -Budget $capturedMaintenanceBudget `
                -MaximumMilliseconds $maintenanceWindowMilliseconds `
                -Label "C07 post-DDL target resource attestation"
        $semantic = & $callerTargetSemanticAction `
            $HostAuthority `
            $MigrationPassword `
            "ticketbox" `
            $capturedOperationId `
            "" `
            $SourceRevision `
            $TargetRevision `
            $capturedRevisionManifestSha256 `
            $capturedMaintenanceDeadlineUtc `
            $remainingCeiling `
            $capturedMaintenanceAuthoritySha256
        try {
                Assert-TicketboxC07ExactProperties `
                    $semantic `
                    @(
                        "schema",
                        "operation_id",
                        "database",
                        "snapshot_id",
                        "source_revision",
                        "target_revision",
                        "revision_manifest_sha256",
                        "maintenance_authority_sha256",
                        "maintenance_remaining_ceiling_ms",
                        "alembic_revision",
                        "resource_shape_sha256",
                        "money_facts_sha256"
                    ) `
                    "C07 post-DDL target semantic attestation"
                foreach ($field in @(
                    "revision_manifest_sha256",
                    "maintenance_authority_sha256",
                    "resource_shape_sha256",
                    "money_facts_sha256"
                )) {
                    Assert-TicketboxC07LowerSha256 `
                        ([string]$semantic.$field) `
                        "C07 post-DDL semantic $field"
                }
                $bindingMismatches = @()
                foreach ($binding in @(
                    @("schema", [string]$semantic.schema,
                        "ticketbox-c07-target-semantic-result-v1"),
                    @("operation_id", [string]$semantic.operation_id,
                        $capturedOperationId),
                    @("database", [string]$semantic.database, "ticketbox"),
                    @("snapshot_id", [string]$semantic.snapshot_id, ""),
                    @("source_revision", [string]$semantic.source_revision,
                        $SourceRevision),
                    @("target_revision", [string]$semantic.target_revision,
                        $TargetRevision),
                    @("alembic_revision", [string]$semantic.alembic_revision,
                        $TargetRevision),
                    @(
                        "revision_manifest_sha256",
                        [string]$semantic.revision_manifest_sha256,
                        $capturedRevisionManifestSha256.ToLowerInvariant()
                    ),
                    @(
                        "maintenance_authority_sha256",
                        [string]$semantic.maintenance_authority_sha256,
                        $capturedMaintenanceAuthoritySha256.ToLowerInvariant()
                    )
                )) {
                    if ([string]$binding[1] -cne [string]$binding[2]) {
                        $bindingMismatches += [string]$binding[0]
                    }
                }
                if (
                    [int]$semantic.maintenance_remaining_ceiling_ms -ne
                        $remainingCeiling
                ) {
                    $bindingMismatches += "maintenance_remaining_ceiling_ms"
                }
                if ($bindingMismatches.Count -ne 0) {
                    throw (
                        "C07 post-DDL target semantic attestation 未绑定 exact " +
                        "operation fields: " +
                        ([string]::Join(",", @($bindingMismatches)))
                    )
                }
        }
        catch {
            if (
                [string]$_.Exception.Data["TicketboxC07FailureClass"] -ceq
                    "invariant"
            ) {
                throw
            }
            throw (New-TicketboxC07ClassifiedFailure `
                -Message (
                    "C07 post-DDL target semantic attestation " +
                    "未满足发布不变量。"
                ) `
                -FailureClass "invariant" `
                -FailureCode "resource_shape_mismatch" `
                -InnerException $_.Exception)
        }
        if (
            [string]$migrationEvidence.schema -cne
                "ticketbox-c07-migration-evidence-v1"
        ) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 base DDL evidence schema 未登记。" `
                -FailureClass "invariant" `
                -FailureCode "resource_shape_mismatch")
        }
        if (
            [string]$migrationEvidence.money_facts_sha256 -cne
                [string]$semantic.money_facts_sha256
        ) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 DDL money facts 与 post-DDL attestation 不一致。" `
                -FailureClass "invariant" `
                -FailureCode "money_facts_mismatch")
        }
        return [pscustomobject][ordered]@{
            schema = "ticketbox-c07-migration-evidence-v2"
            operation_id = [string]$migrationEvidence.operation_id
            source_revision = [string]$migrationEvidence.source_revision
            target_revision = [string]$migrationEvidence.target_revision
            result = [string]$migrationEvidence.result
            alembic_revision = [string]$migrationEvidence.alembic_revision
            resource_shape_sha256 =
                [string]$semantic.resource_shape_sha256
            money_facts_sha256 =
                [string]$semantic.money_facts_sha256
            statistics_table_count =
                [int]$migrationEvidence.statistics_table_count
            statistics_table_set_sha256 =
                [string]$migrationEvidence.statistics_table_set_sha256
        }
    }.GetNewClosure()
    $result = Invoke-TicketboxC07ProductionAuthorityCoordinator `
        -SuperuserPassword $SuperuserPassword `
        -RuntimePassword $RuntimePassword `
        -MigratorPassword $MigratorPassword `
        -MigratorValidUntilUtc $boundedMigratorValidUntilUtc `
        -OperationId ([string]$authority.Receipt.operation_id) `
        -Mode $Mode `
        -ExpectedSourceRevision $ExpectedSourceRevision `
        -TargetRevision (
            [string]$authority.Descriptor.Payload.target_alembic_revision
        ) `
        -RecoveryGeneration $recovery `
        -TargetRecoveryGeneration $targetRecovery `
        -PredecessorTargetRecoveryGeneration $predecessorTargetRecovery `
        -LifecycleAuthority $lifecycleAuthority `
        -MigrationAction $coordinatorMigrationAction `
        -SuccessorIntent $(if ($successorMode -ceq "forward_repair") {
            $successorIntent
        } else { $null }) `
        -ExpectedProductionResult $(
            if ($ValidateExistingProductionAuthority) {
                $existingProductionAuthority.CoordinatorResult
            }
            else { $null }
        ) `
        -StopAfterMigrationCompleted:$StopAfterMigrationCompleted
    if ($StopAfterMigrationCompleted) {
        try {
              Assert-TicketboxC07ExactProperties `
            $result `
            @(
                "schema",
                "operation_id",
                "mode",
                "result",
                "cluster_system_identifier",
                "database_oid",
                "logical_server_id",
                "data_generation",
                "source_alembic_revision",
                "target_alembic_revision",
                "alembic_revision",
                "source_recovery_manifest_sha256",
                "migration_evidence_sha256",
                "resource_shape_sha256",
                "money_facts_sha256",
                "statistics_table_count",
                "statistics_table_set_sha256"
            ) `
            "C07 target commit coordinator result"
        if (
            [string]$result.schema -cne
                "ticketbox-c07-target-commit-result-v1" -or
            [string]$result.operation_id -cne
                [string]$authority.Receipt.operation_id -or
            [string]$result.result -cne "target_committed" -or
            [string]$result.alembic_revision -cne
                [string]$authority.Descriptor.Payload.target_alembic_revision
        ) {
            throw "C07 target commit coordinator result 未绑定 exact target。"
        }
        foreach ($field in @(
            "source_recovery_manifest_sha256",
            "migration_evidence_sha256",
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_set_sha256"
        )) {
            Assert-TicketboxC07LowerSha256 `
                ([string]$result.$field) "C07 target commit $field"
        }
        if ([int]$result.statistics_table_count -ne 18) {
            throw "C07 target commit statistics table count 不完整。"
        }
        }
        catch {
            if (
                [string]$_.Exception.Data["TicketboxC07FailureClass"] -ceq
                    "invariant"
            ) {
                throw
            }
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 target commit result 未满足发布不变量。" `
                -FailureClass "invariant" `
                -FailureCode "resource_shape_mismatch" `
                -InnerException $_.Exception)
        }
        return $result
    }
    try {
            Assert-TicketboxC07ProductionCoordinatorResult `
                -Result $result `
                -Authority $authority `
                -Mode $Mode `
                -RecoveryManifestSha256 (
                    ConvertTo-TicketboxC07HostSha256 `
                        ([string]$targetRecovery.PayloadSha256) `
                        "production target recovery manifest"
                )
    }
    catch {
        if (
            [string]$_.Exception.Data["TicketboxC07FailureClass"] -ceq
                "invariant"
        ) {
            throw
        }
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 production coordinator result 未满足发布不变量。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch" `
                -InnerException $_.Exception)
    }
    if ($ValidateExistingProductionAuthority) {
        $validatedResultJson = ConvertTo-TicketboxC07CompactJson $result
        if (
            (Get-TicketboxC07TextSha256 $validatedResultJson) -cne
                [string]$existingProductionAuthority.Payload.coordinator_result_sha256
        ) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message (
                    "C07 precommitted runtime ACL validation 未返回原 " +
                    "production result。"
                ) `
                -FailureClass "invariant" `
                -FailureCode "runtime_acl_invariant_failed")
        }
        $revalidatedProduction = Read-TicketboxC07ProductionAuthority $authority
        if (
            [string]$revalidatedProduction.PayloadSha256 -cne
                [string]$existingProductionAuthority.PayloadSha256
        ) {
            throw (New-TicketboxC07ClassifiedFailure `
                -Message "C07 production authority 在 runtime ACL reconcile 期间漂移。" `
                -FailureClass "invariant" `
                -FailureCode "authority_chain_mismatch")
        }
        return $revalidatedProduction
    }
    $resultJson = ConvertTo-TicketboxC07CompactJson $result
    $payload = [ordered]@{
        schema = $script:TicketboxC07ProductionAuthoritySchema
        operation_id = [string]$authority.Receipt.operation_id
        mode = $Mode
        result = "production_authority_ready"
        release_fingerprint = [string]$authority.Receipt.release_fingerprint
        migration_helper_relative_path =
            [string]$authority.ReleaseIdentity.MigrationHelperRelativePath
        migration_helper_size =
            [int64]$authority.ReleaseIdentity.MigrationHelperSize
        migration_helper_sha256 =
            [string]$authority.ReleaseIdentity.MigrationHelperSha256
        database_binding_sha256 =
            [string]$authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$authority.Receipt.recovery_epoch_id
        operation_kind = [string]$authority.Descriptor.Payload.operation_kind
        source_alembic_revision =
            [string]$authority.Descriptor.Payload.source_alembic_revision
        target_alembic_revision =
            [string]$authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$authority.Descriptor.Payload.revision_manifest_sha256
        predecessor_operation_id =
            [string]$authority.Descriptor.Payload.predecessor_operation_id
        predecessor_production_authority_sha256 =
            [string]$authority.Descriptor.Payload.predecessor_production_authority_sha256
        target_recovery_manifest_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$targetRecovery.PayloadSha256) `
                "production target recovery manifest"
        )
        target_restore_evidence_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$targetRecovery.RestoreEvidence.PayloadSha256) `
                "production target restore evidence"
        )
        money_facts_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$result.money_facts_sha256) `
                "production target money facts"
        )
        resource_shape_sha256 = (
            ConvertTo-TicketboxC07HostSha256 `
                ([string]$result.resource_shape_sha256) `
                "production target resource shape"
        )
        root_authority_chain_sha256 =
            [string]$targetRecovery.LifecycleAuthorityChainSha256
        target_restore_authority_chain_sha256 =
            [string]$authority.Receipt.authority_chain_sha256
        target_restore_stage_evidence_sha256 =
            [string]$authority.Receipt.transition_evidence_sha256
        target_restore_stage_sequence =
            [int64]$authority.Receipt.stage_sequence
        coordinator_binding_sha256 = [string]$authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$authority.Binding.Sequence
        heartbeat_sequence = [int64]$heartbeat.Payload.sequence
        freeze_proof_sha256 = [string]$authority.Receipt.freeze_proof_sha256
        coordinator_result_sha256 = Get-TicketboxC07TextSha256 $resultJson
        coordinator_result_json = $resultJson
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $path = Get-TicketboxC07ProductionAuthorityPath (
        [string]$authority.Receipt.operation_id
    )
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07ProductionAuthority $authority
        $sameAuthority = $true
        foreach ($field in @(
            "operation_id",
            "mode",
            "release_fingerprint",
            "migration_helper_relative_path",
            "migration_helper_size",
            "migration_helper_sha256",
            "database_binding_sha256",
            "recovery_epoch_id",
            "operation_kind",
            "source_alembic_revision",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "predecessor_operation_id",
            "predecessor_production_authority_sha256",
            "target_recovery_manifest_sha256",
            "target_restore_evidence_sha256",
            "money_facts_sha256",
            "resource_shape_sha256",
            "root_authority_chain_sha256",
            "target_restore_authority_chain_sha256",
            "target_restore_stage_evidence_sha256",
            "target_restore_stage_sequence",
            "coordinator_binding_sha256",
            "coordinator_binding_sequence",
            "heartbeat_sequence",
            "freeze_proof_sha256",
            "coordinator_result_sha256"
        )) {
            if ([string]$existing.Payload.$field -cne [string]$payload.$field) {
                $sameAuthority = $false
                break
            }
        }
        if ($sameAuthority) {
            return $existing
        }
        if (
            [int64]$existing.Payload.coordinator_binding_sequence -ge
                [int64]$authority.Binding.Sequence -or
            [string]$existing.Payload.root_authority_chain_sha256 -cne
                [string]$payload.root_authority_chain_sha256 -or
            [string]$existing.Payload.target_recovery_manifest_sha256 -cne
                [string]$payload.target_recovery_manifest_sha256
        ) {
            throw "C07 production authority 已存在且不可在同 generation 覆盖。"
        }
        $oldBinding = Read-TicketboxC07CoordinatorBindingAtSequence `
            -OperationId ([string]$authority.Receipt.operation_id) `
            -Descriptor $authority.Descriptor `
            -Sequence ([int]$existing.Payload.coordinator_binding_sequence) `
            -ExpectedPayloadSha256 (
                [string]$existing.Payload.coordinator_binding_sha256
            )
        Assert-TicketboxC07PriorProcessIdentityDead $oldBinding.CoordinatorIdentity
    }
    Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "production_authority" `
        -Payload $payload `
        -ReplaceExisting:(Test-Path -LiteralPath $path) | Out-Null
      return Read-TicketboxC07ProductionAuthority $authority
    }
    finally {
        if ($createdMaintenanceBudget) {
            $script:TicketboxC07ActiveMaintenanceBudget = $null
        }
    }
}

function New-TicketboxC07InstalledStageProducer {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][ValidateSet(
            "recovery_generation_ready",
            "isolated_restore_verified",
            "ddl_started",
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified",
            "runtime_acl_verified",
            "ready"
        )][string]$TargetStage,
        [Parameter(Mandatory = $true)][string]$SubjectSha256,
        [string]$MigrationEvidenceSha256 = "",
        [string]$ResourceShapeSha256 = "",
        [string]$MoneyFactsSha256 = "",
        [int]$StatisticsTableCount = 0,
        [string]$StatisticsTableSetSha256 = ""
    )
    Assert-TicketboxC07Sha256 $SubjectSha256 "$TargetStage subject hash"
    $contract = $script:TicketboxC07StageEvidenceContracts[$TargetStage]
    if ($null -eq $contract) {
        throw "C07 installed coordinator 缺少 $TargetStage typed contract。"
    }
    $producer = [ordered]@{
        schema = [string]$contract.Schema
        operation_id = [string]$Authority.Receipt.operation_id
        result = [string]$contract.Result
        database_binding_sha256 =
            [string]$Authority.Receipt.database_binding_sha256
        operation_kind = [string]$Authority.Descriptor.Payload.operation_kind
        alembic_target =
            [string]$Authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256
        subject_sha256 = $SubjectSha256
    }
    if ($TargetStage -ceq "target_committed") {
        foreach ($binding in @(
            $MigrationEvidenceSha256,
            $ResourceShapeSha256,
            $MoneyFactsSha256,
            $StatisticsTableSetSha256
        )) {
            Assert-TicketboxC07LowerSha256 `
                $binding "target committed evidence digest"
        }
        $producer.migration_evidence_sha256 =
            $MigrationEvidenceSha256.ToUpperInvariant()
        $producer.resource_shape_sha256 =
            $ResourceShapeSha256.ToUpperInvariant()
        $producer.money_facts_sha256 =
            $MoneyFactsSha256.ToUpperInvariant()
        if ($StatisticsTableCount -ne 18) {
            throw "C07 target committed statistics table count 不完整。"
        }
        $producer.statistics_table_count = $StatisticsTableCount
        $producer.statistics_table_set_sha256 =
            $StatisticsTableSetSha256.ToUpperInvariant()
    }
    elseif (
        -not [string]::IsNullOrEmpty($MigrationEvidenceSha256) -or
        -not [string]::IsNullOrEmpty($ResourceShapeSha256) -or
        -not [string]::IsNullOrEmpty($MoneyFactsSha256) -or
        $StatisticsTableCount -ne 0 -or
        -not [string]::IsNullOrEmpty($StatisticsTableSetSha256)
    ) {
        throw "C07 非 target_committed producer 不接受 DDL evidence fields。"
    }
    return [pscustomobject]$producer
}

function Set-TicketboxC07InstalledStage {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][ValidateSet(
            "recovery_generation_ready",
            "isolated_restore_verified",
            "ddl_started",
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified",
            "runtime_acl_verified",
            "ready"
        )][string]$TargetStage,
        [Parameter(Mandatory = $true)][string]$SubjectSha256,
        [string]$MigrationEvidenceSha256 = "",
        [string]$ResourceShapeSha256 = "",
        [string]$MoneyFactsSha256 = "",
        [int]$StatisticsTableCount = 0,
        [string]$StatisticsTableSetSha256 = ""
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    $producer = New-TicketboxC07InstalledStageProducer `
        -Authority $authority `
        -TargetStage $TargetStage `
        -SubjectSha256 $SubjectSha256 `
        -MigrationEvidenceSha256 $MigrationEvidenceSha256 `
        -ResourceShapeSha256 $ResourceShapeSha256 `
        -MoneyFactsSha256 $MoneyFactsSha256 `
        -StatisticsTableCount $StatisticsTableCount `
        -StatisticsTableSetSha256 $StatisticsTableSetSha256
    $evidence = New-TicketboxC07StageEvidence `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -TargetStage $TargetStage `
        -ProducerEvidence $producer
    return Set-TicketboxC07LifecycleStage `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -TargetStage $TargetStage `
        -EvidencePath $evidence.Path
}

function Resume-TicketboxC07PrecommittedRuntimeAclStage {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][scriptblock]$MigrationAction,
        [Parameter(Mandatory = $true)][scriptblock]$TargetSemanticAction
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    if (
        [string]$authority.Receipt.stage -cne
            "target_isolated_restore_verified" -or
        [int64]$authority.Receipt.stage_sequence -ne 7
    ) {
        throw "C07 precommitted runtime ACL reconcile stage/sequence 无效。"
    }
    $evidencePath = Get-TicketboxC07StageEvidencePath `
        -OperationId ([string]$authority.Receipt.operation_id) `
        -Stage "runtime_acl_verified"
    $evidenceKind = Get-TicketboxPathEntryKindNoFollow $evidencePath
    if ($evidenceKind -ceq "Missing") {
        return $null
    }
    if ($evidenceKind -cne "File") {
        throw "C07 precommitted runtime ACL evidence 不是受支持的普通文件。"
    }

    # The evidence is immutable and may reference a production authority from
    # the dead coordinator binding.  Validate that exact artifact first, then
    # re-prove its live DB/role/ACL result under the current operation lease.
    # Do not republish the database marker or replace the referenced host
    # authority: the following stage receipt is the sole missing durable write.
    $evidence = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage "runtime_acl_verified"
    $production = Invoke-TicketboxC07ProductionLifecycleCoordinator `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -RuntimePassword $RuntimePassword `
        -MigratorPassword $MigratorPassword `
        -MigratorValidUntilUtc $MigratorValidUntilUtc `
        -Mode $Mode `
        -ExpectedSourceRevision $ExpectedSourceRevision `
        -MigrationAction $MigrationAction `
        -TargetSemanticAction $TargetSemanticAction `
        -ValidateExistingProductionAuthority
    $producer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$evidence.Payload.producer_payload_json) `
        -Label "precommitted runtime ACL producer"
    if (
        [string]$producer.subject_sha256 -cne
            [string]$production.PayloadSha256
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message (
                "C07 precommitted runtime ACL evidence 未绑定重验后的 " +
                "production authority。"
            ) `
            -FailureClass "invariant" `
            -FailureCode "runtime_acl_invariant_failed")
    }
    return Set-TicketboxC07LifecycleStage `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -TargetStage "runtime_acl_verified" `
        -EvidencePath $evidencePath
}

function Invoke-TicketboxC07InstalledProductionLifecycle {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][scriptblock]$MigrationAction,
        [Parameter(Mandatory = $true)][scriptblock]$IsolatedReplayAction,
        [Parameter(Mandatory = $true)][scriptblock]$MoneyFactsAction,
        [Parameter(Mandatory = $true)][scriptblock]$TargetSemanticAction,
        [string]$ExpectedOperationId = "",
        [AllowNull()][object]$SuccessorIntent,
        [string]$TargetRevision = $script:TicketboxC07TargetRevision,
        [ValidateSet("c07_money_minor_bigint_v1")]
        [string]$OperationKind = "c07_money_minor_bigint_v1",
        [string]$RevisionManifestSha256 = ""
    )
    foreach ($commandName in @(
        "Invoke-TicketboxC07RecoveryGeneration",
        "Test-TicketboxC07RecoveryGenerationRestore",
        "Invoke-TicketboxC07TargetRecoveryGeneration",
        "Test-TicketboxC07TargetRecoveryGenerationRestore",
        "Read-TicketboxC07ProductionTargetRecoveryGeneration"
    )) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "C07 installed coordinator 缺少权威依赖：$commandName"
        }
    }
    New-TicketboxC07LifecycleOperation `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -ExpectedOperationId $ExpectedOperationId `
        -TargetRevision $TargetRevision `
        -OperationKind $OperationKind `
        -RevisionManifestSha256 $RevisionManifestSha256 `
        -SuccessorIntent $SuccessorIntent | Out-Null

    $previousMaintenanceBudget = $script:TicketboxC07ActiveMaintenanceBudget
    $activeActionKind = ""
    try {
      $initialAuthority = Read-TicketboxC07Authority $DataRoot
      $boundedMigratorValidUntilUtc = $MigratorValidUntilUtc
      $initialStage = [string]$initialAuthority.Receipt.stage
      if (
          $initialStage -cne "ready" -and
          $initialStage -notin $script:TicketboxC07FailureStages
      ) {
          $script:TicketboxC07ActiveMaintenanceBudget =
              New-TicketboxC07MaintenanceBudget $initialAuthority
          $boundedMigratorValidUntilUtc =
              Get-TicketboxC07BoundedMigratorValidUntilUtc `
                  -RequestedValidUntilUtc $MigratorValidUntilUtc `
                  -Budget $script:TicketboxC07ActiveMaintenanceBudget
      }
      while ($true) {
        $authority = Read-TicketboxC07Authority $DataRoot
        $stage = [string]$authority.Receipt.stage
        if (
            $stage -cne "ready" -and
            $stage -notin $script:TicketboxC07FailureStages
        ) {
            [void](Get-TicketboxC07RemainingMaintenanceMilliseconds `
                -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                -Label "C07 installed lifecycle stage $stage")
        }
        $activeActionKind = switch ($stage) {
            "captured" { "writer_freeze" }
            "writers_frozen" { "source_recovery_generation" }
            "recovery_generation_ready" { "source_isolated_restore" }
            "isolated_restore_verified" { "ddl_start_commit" }
            "ddl_started" { "production_migration" }
            "target_committed" { "target_recovery_generation" }
            "target_recovery_generation_ready" {
                "target_isolated_restore"
            }
            "target_isolated_restore_verified" { "runtime_acl_commit" }
            "runtime_acl_verified" { "ready_commit" }
            default { "" }
        }
        switch ($stage) {
            "captured" {
                Write-TicketboxC07Heartbeat `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock | Out-Null
                Set-TicketboxC07LifecycleStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "writers_frozen" | Out-Null
                continue
            }
            "writers_frozen" {
                if (
                    [string]$authority.Descriptor.Payload.successor_mode -ceq
                        "forward_repair"
                ) {
                    $lineage = Resolve-TicketboxC07ForwardRepairRecovery `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword
                    Set-TicketboxC07InstalledStage `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -TargetStage "recovery_generation_ready" `
                        -SubjectSha256 (
                            ([string]$lineage.Recovery.PayloadSha256).ToUpperInvariant()
                        ) | Out-Null
                    continue
                }
                Renew-TicketboxC07RoleCredentialWindow `
                    -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
                    -SuperuserPassword $SuperuserPassword `
                    -RuntimePassword $RuntimePassword `
                    -MigratorPassword $MigratorPassword `
                    -MigratorValidUntilUtc $boundedMigratorValidUntilUtc `
                    -OperationId ([string]$authority.Receipt.operation_id) `
                    -Mode $Mode
                $generation = Invoke-TicketboxC07RecoveryGeneration `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -SuperuserPassword $SuperuserPassword `
                    -MigratorPassword $MigratorPassword `
                    -ExpectedSourceRevision $ExpectedSourceRevision `
                    -MoneyFactsAction $MoneyFactsAction
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "recovery_generation_ready" `
                    -SubjectSha256 (
                        ([string]$generation.EvidenceSha256).ToUpperInvariant()
                    ) | Out-Null
                continue
            }
            "recovery_generation_ready" {
                if (
                    [string]$authority.Descriptor.Payload.successor_mode -ceq
                        "forward_repair"
                ) {
                    $lineage = Resolve-TicketboxC07ForwardRepairRecovery `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword
                    Set-TicketboxC07InstalledStage `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -TargetStage "isolated_restore_verified" `
                        -SubjectSha256 (
                            ([string]$lineage.Recovery.RestoreEvidence.PayloadSha256).ToUpperInvariant()
                        ) | Out-Null
                    continue
                }
                Renew-TicketboxC07RoleCredentialWindow `
                    -Authority (Resolve-TicketboxC07DatabaseHostAuthority) `
                    -SuperuserPassword $SuperuserPassword `
                    -RuntimePassword $RuntimePassword `
                    -MigratorPassword $MigratorPassword `
                    -MigratorValidUntilUtc $boundedMigratorValidUntilUtc `
                    -OperationId ([string]$authority.Receipt.operation_id) `
                    -Mode $Mode
                $restore = Test-TicketboxC07RecoveryGenerationRestore `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -SuperuserPassword $SuperuserPassword `
                    -MigratorPassword $MigratorPassword `
                    -ExpectedSourceRevision $ExpectedSourceRevision `
                    -TargetRevision (
                        [string]$authority.Descriptor.Payload.target_alembic_revision
                    ) `
                    -ForwardReplayAction $IsolatedReplayAction
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "isolated_restore_verified" `
                    -SubjectSha256 (
                        ([string]$restore.EvidenceSha256).ToUpperInvariant()
                    ) | Out-Null
                continue
            }
            "isolated_restore_verified" {
                if (
                    [string]$authority.Descriptor.Payload.successor_mode -ceq
                        "forward_repair"
                ) {
                    $lineage = Resolve-TicketboxC07ForwardRepairRecovery `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword
                    Set-TicketboxC07InstalledStage `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -TargetStage "ddl_started" `
                        -SubjectSha256 (
                            ([string]$lineage.Recovery.RestoreEvidence.PayloadSha256).ToUpperInvariant()
                        ) | Out-Null
                    continue
                }
                $restore = Test-TicketboxC07RecoveryGenerationRestore `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -SuperuserPassword $SuperuserPassword `
                    -MigratorPassword $MigratorPassword `
                    -ExpectedSourceRevision $ExpectedSourceRevision `
                    -TargetRevision (
                        [string]$authority.Descriptor.Payload.target_alembic_revision
                    ) `
                    -ForwardReplayAction $IsolatedReplayAction
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "ddl_started" `
                    -SubjectSha256 (
                        ([string]$restore.EvidenceSha256).ToUpperInvariant()
                    ) | Out-Null
                continue
            }
            "ddl_started" {
                $targetCommit =
                    Invoke-TicketboxC07ProductionLifecycleCoordinator `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -SuperuserPassword $SuperuserPassword `
                    -RuntimePassword $RuntimePassword `
                    -MigratorPassword $MigratorPassword `
                    -MigratorValidUntilUtc $boundedMigratorValidUntilUtc `
                    -Mode $Mode `
                    -ExpectedSourceRevision $ExpectedSourceRevision `
                    -MigrationAction $MigrationAction `
                    -TargetSemanticAction $TargetSemanticAction `
                    -StopAfterMigrationCompleted
                $targetCommitJson =
                    ConvertTo-TicketboxC07CompactJson $targetCommit
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "target_committed" `
                    -SubjectSha256 (
                        Get-TicketboxC07TextSha256 $targetCommitJson
                    ) `
                    -MigrationEvidenceSha256 (
                        [string]$targetCommit.migration_evidence_sha256
                    ) `
                    -ResourceShapeSha256 (
                        [string]$targetCommit.resource_shape_sha256
                    ) `
                    -MoneyFactsSha256 (
                        [string]$targetCommit.money_facts_sha256
                    ) `
                    -StatisticsTableCount (
                        [int]$targetCommit.statistics_table_count
                    ) `
                    -StatisticsTableSetSha256 (
                        [string]$targetCommit.statistics_table_set_sha256
                    ) | Out-Null
                continue
            }
            "target_committed" {
                $targetCommitEvidence = Read-TicketboxC07StageEvidence `
                    -Authority $authority `
                    -Stage "target_committed"
                $targetCommitProducer = ConvertFrom-TicketboxC07JsonText `
                    -Text ([string]$targetCommitEvidence.Payload.producer_payload_json) `
                    -Label "target commit producer"
                $targetGeneration =
                    Invoke-TicketboxC07TargetRecoveryGeneration `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword `
                        -MigratorPassword $MigratorPassword `
                        -ExpectedSourceRevision $ExpectedSourceRevision `
                        -TargetRevision (
                            [string]$authority.Descriptor.Payload.target_alembic_revision
                        ) `
                        -MoneyFactsAction $MoneyFactsAction `
                        -TargetSemanticAction $TargetSemanticAction `
                        -TargetCommitEvidenceSha256 (
                            [string]$targetCommitEvidence.PayloadSha256
                        ) `
                        -MigrationEvidenceSha256 (
                            [string]$targetCommitProducer.migration_evidence_sha256
                        ).ToLowerInvariant() `
                        -ExpectedResourceShapeSha256 (
                            [string]$targetCommitProducer.resource_shape_sha256
                        ).ToLowerInvariant() `
                        -ExpectedMoneyFactsSha256 (
                            [string]$targetCommitProducer.money_facts_sha256
                        ).ToLowerInvariant()
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "target_recovery_generation_ready" `
                    -SubjectSha256 (
                        ([string]$targetGeneration.EvidenceSha256).ToUpperInvariant()
                    ) | Out-Null
                continue
            }
            "target_recovery_generation_ready" {
                $targetRestore =
                    Test-TicketboxC07TargetRecoveryGenerationRestore `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword `
                        -MigratorPassword $MigratorPassword `
                        -ExpectedSourceRevision $ExpectedSourceRevision `
                        -TargetRevision (
                            [string]$authority.Descriptor.Payload.target_alembic_revision
                        ) `
                        -MoneyFactsAction $MoneyFactsAction `
                        -TargetSemanticAction $TargetSemanticAction
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "target_isolated_restore_verified" `
                    -SubjectSha256 (
                        ([string]$targetRestore.EvidenceSha256).ToUpperInvariant()
                    ) | Out-Null
                continue
            }
            "target_isolated_restore_verified" {
                $reconciledRuntimeAcl =
                    Resume-TicketboxC07PrecommittedRuntimeAclStage `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword `
                        -RuntimePassword $RuntimePassword `
                        -MigratorPassword $MigratorPassword `
                        -MigratorValidUntilUtc $boundedMigratorValidUntilUtc `
                        -Mode $Mode `
                        -ExpectedSourceRevision $ExpectedSourceRevision `
                        -MigrationAction $MigrationAction `
                        -TargetSemanticAction $TargetSemanticAction
                if ($null -ne $reconciledRuntimeAcl) { continue }
                $production =
                    Invoke-TicketboxC07ProductionLifecycleCoordinator `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -SuperuserPassword $SuperuserPassword `
                        -RuntimePassword $RuntimePassword `
                        -MigratorPassword $MigratorPassword `
                        -MigratorValidUntilUtc $boundedMigratorValidUntilUtc `
                        -Mode $Mode `
                        -ExpectedSourceRevision $ExpectedSourceRevision `
                        -MigrationAction $MigrationAction `
                        -TargetSemanticAction $TargetSemanticAction
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "runtime_acl_verified" `
                    -SubjectSha256 (
                        [string]$production.PayloadSha256
                    ) | Out-Null
                continue
            }
            "runtime_acl_verified" {
                $production = Read-TicketboxC07ProductionAuthority $authority
                Set-TicketboxC07InstalledStage `
                    -DataRoot $DataRoot `
                    -LifecycleLock $LifecycleLock `
                    -TargetStage "ready" `
                    -SubjectSha256 ([string]$production.PayloadSha256) | Out-Null
                continue
            }
            "ready" {
                $production = Read-TicketboxC07ProductionAuthority $authority
                $projection =
                    Restore-TicketboxC07TerminalRuntimeProjection `
                        -DataRoot $DataRoot `
                        -Authority $authority
                return [pscustomobject][ordered]@{
                    schema = "ticketbox-c07-installed-lifecycle-result-v1"
                    operation_id = [string]$authority.Receipt.operation_id
                    result = "ready"
                    target_revision =
                        [string]$authority.Descriptor.Payload.target_alembic_revision
                    production_authority_sha256 =
                        [string]$production.PayloadSha256
                    runtime_projection_sha256 =
                        [string]$projection.PayloadSha256
                }
            }
            { $_ -in $script:TicketboxC07FailureStages } {
                $projection =
                    Restore-TicketboxC07TerminalRuntimeProjection `
                        -DataRoot $DataRoot `
                        -Authority $authority
                return [pscustomobject][ordered]@{
                    schema = "ticketbox-c07-installed-lifecycle-result-v1"
                    operation_id = [string]$authority.Receipt.operation_id
                    result = $stage
                    failure_code = [string]$authority.Receipt.failure_code
                    target_revision =
                        [string]$authority.Descriptor.Payload.target_alembic_revision
                    runtime_projection_sha256 =
                        [string]$projection.PayloadSha256
                }
            }
            default {
                throw "C07 installed coordinator 拒绝终态或未知 stage：$stage"
            }
        }
      }
    }
    catch {
        $failure = $_.Exception
        try {
            $failedAuthority = Read-TicketboxC07Authority $DataRoot
            $failedStage = [string]$failedAuthority.Receipt.stage
            if ($failedStage -notin $script:TicketboxC07FailureStages -and
                $failedStage -cne "ready") {
                if (Test-TicketboxC07InvariantFailure $failure) {
                    $failureTarget = if (
                        $failedStage -in $script:TicketboxC07PreDdlStages
                    ) {
                        "refused_pre_ddl"
                    }
                    else {
                        "repair_required"
                    }
                    $failureCode = Get-TicketboxC07SafeFailureCode `
                        $failure `
                        "maintenance_invariant_failed"
                    Set-TicketboxC07LifecycleStage `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -TargetStage $failureTarget `
                        -FailureCode $failureCode | Out-Null
                }
                else {
                    if ([string]::IsNullOrEmpty($activeActionKind)) {
                        $activeActionKind = "maintenance_coordinator"
                    }
                    New-TicketboxC07MaintenanceAttemptFailure `
                        -Authority $failedAuthority `
                        -LifecycleLock $LifecycleLock `
                        -Failure $failure `
                        -ActionKind $activeActionKind | Out-Null
                }
            }
        }
        catch {
            $persistenceFailure = $_.Exception
            try {
                $terminalAuthority = Read-TicketboxC07Authority $DataRoot
                $terminalStage = [string]$terminalAuthority.Receipt.stage
                if (
                    $terminalStage -notin $script:TicketboxC07FailureStages -and
                    $terminalStage -cne "ready" -and
                    (Test-TicketboxC07InvariantFailure $persistenceFailure)
                ) {
                    $terminalTarget = if (
                        $terminalStage -in $script:TicketboxC07PreDdlStages
                    ) { "refused_pre_ddl" } else { "repair_required" }
                    Set-TicketboxC07LifecycleStage `
                        -DataRoot $DataRoot `
                        -LifecycleLock $LifecycleLock `
                        -TargetStage $terminalTarget `
                        -FailureCode (
                            Get-TicketboxC07SafeFailureCode `
                                $persistenceFailure `
                                "maintenance_invariant_failed"
                        ) | Out-Null
                }
            }
            catch {
                $terminalPersistenceFailure = $_.Exception
                $persistenceFailure = [AggregateException]::new(
                    "C07 invariant terminal 持久化失败。",
                    [Exception[]]@(
                        $persistenceFailure,
                        $terminalPersistenceFailure
                    )
                )
            }
            $aggregateFailure = [AggregateException]::new(
                (
                    "C07 lifecycle attempt/failure evidence 持久化失败；" +
                    "原始维护动作与持久化错误均已保留。"
                ),
                [Exception[]]@($failure, $persistenceFailure)
            )
            $aggregateFailure.Data["TicketboxC07FailureCode"] =
                Get-TicketboxC07SafeFailureCode $failure
            throw $aggregateFailure
        }
        throw
    }
    finally {
        $script:TicketboxC07ActiveMaintenanceBudget =
            $previousMaintenanceBudget
    }
}

function New-TicketboxC07StageEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][ValidateSet(
            "recovery_generation_ready",
            "isolated_restore_verified",
            "ddl_started",
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified",
            "runtime_acl_verified",
            "ready"
        )][string]$TargetStage,
        [Parameter(Mandatory = $true)][object]$ProducerEvidence
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $currentIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        [string]$authority.Receipt.stage
    )
    $targetIndex = [array]::IndexOf($script:TicketboxC07OrderedStages, $TargetStage)
    if (
        $targetIndex -ne $currentIndex -and
        $targetIndex -ne ($currentIndex + 1)
    ) {
        throw (
            "C07 typed stage evidence 只能为当前/下一边界生成：" +
            " current=$($authority.Receipt.stage) target=$TargetStage。"
        )
    }
    $contract = $script:TicketboxC07StageEvidenceContracts[$TargetStage]
    $producerProperties = @(
        "schema",
        "operation_id",
        "result",
        "database_binding_sha256",
        "operation_kind",
        "alembic_target",
        "revision_manifest_sha256",
        "subject_sha256"
    )
    if ($TargetStage -ceq "target_committed") {
        $producerProperties += @(
            "migration_evidence_sha256",
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_count",
            "statistics_table_set_sha256"
        )
    }
    Assert-TicketboxC07ExactProperties `
        $ProducerEvidence `
        $producerProperties `
        "$TargetStage producer evidence"
    if (
        [string]$ProducerEvidence.schema -cne [string]$contract.Schema -or
        [string]$ProducerEvidence.operation_id -cne
            [string]$authority.Receipt.operation_id -or
        [string]$ProducerEvidence.result -cne [string]$contract.Result -or
        [string]$ProducerEvidence.database_binding_sha256 -cne
            [string]$authority.Receipt.database_binding_sha256 -or
        [string]$ProducerEvidence.operation_kind -cne
            [string]$authority.Descriptor.Payload.operation_kind -or
        [string]$ProducerEvidence.alembic_target -cne
            [string]$authority.Descriptor.Payload.target_alembic_revision -or
        [string]$ProducerEvidence.revision_manifest_sha256 -cne
            [string]$authority.Descriptor.Payload.revision_manifest_sha256
    ) {
        throw "C07 $TargetStage producer evidence 不符合固定类型合同。"
    }
    Assert-TicketboxC07Sha256 `
        ([string]$ProducerEvidence.subject_sha256) `
        "$TargetStage subject hash"
    if ($TargetStage -ceq "target_committed") {
        foreach ($field in @(
            "migration_evidence_sha256",
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_set_sha256"
        )) {
            Assert-TicketboxC07Sha256 `
                ([string]$ProducerEvidence.$field) `
                "target committed $field"
        }
        if ([int]$ProducerEvidence.statistics_table_count -ne 18) {
            throw "C07 target committed statistics table count 不完整。"
        }
    }
    if ($TargetStage -in $script:TicketboxC07ProductionGatedStages) {
        $production = Read-TicketboxC07ProductionAuthority $authority
        if (
            [string]$ProducerEvidence.subject_sha256 -cne
                [string]$production.PayloadSha256
        ) {
            throw "C07 $TargetStage producer 未绑定唯一 production authority artifact。"
        }
    }
    $producerJson = ConvertTo-TicketboxC07CompactJson $ProducerEvidence
    $payload = [ordered]@{
        schema = $script:TicketboxC07StageEvidenceSchema
        operation_id = [string]$authority.Receipt.operation_id
        target_stage = $TargetStage
        evidence_type = "$TargetStage-evidence"
        producer_schema = [string]$contract.Schema
        producer_result = [string]$contract.Result
        producer_payload_sha256 = Get-TicketboxC07TextSha256 $producerJson
        producer_payload_json = $producerJson
        release_fingerprint = [string]$authority.Receipt.release_fingerprint
        database_binding_sha256 = [string]$authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$authority.Receipt.recovery_epoch_id
        operation_kind = [string]$authority.Descriptor.Payload.operation_kind
        target_alembic_revision =
            [string]$authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$authority.Descriptor.Payload.revision_manifest_sha256
        source_stage = [string]$authority.Receipt.stage
        source_stage_sequence = [int64]$authority.Receipt.stage_sequence
        source_authority_chain_sha256 =
            [string]$authority.Receipt.authority_chain_sha256
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $path = Get-TicketboxC07StageEvidencePath `
        -OperationId ([string]$authority.Receipt.operation_id) `
        -Stage $TargetStage
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07HostEnvelope -Path $path -ExpectedKind "stage_evidence"
        if (
            [string]$existing.Payload.producer_payload_sha256 -ceq
                [string]$payload.producer_payload_sha256 -and
            [string]$existing.Payload.operation_id -ceq
                [string]$payload.operation_id -and
            [string]$existing.Payload.target_stage -ceq $TargetStage
        ) {
            return [pscustomobject]@{
                Path = $path
                PayloadSha256 = $existing.PayloadSha256
                Stage = $TargetStage
            }
        }
        throw "C07 $TargetStage 已有不同 typed evidence，拒绝覆盖。"
    }
    $envelope = Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "stage_evidence" `
        -Payload $payload
    return [pscustomobject]@{
        Path = $path
        PayloadSha256 = $envelope.PayloadSha256
        Stage = $TargetStage
    }
}

function New-TicketboxC07FailureEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$TargetStage,
        [Parameter(Mandatory = $true)][string]$FailureCode
    )
    $path = Get-TicketboxC07StageEvidencePath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Stage $TargetStage
    if (Test-Path -LiteralPath $path) {
        $existing = Read-TicketboxC07HostEnvelope `
            -Path $path `
            -ExpectedKind "failure_evidence"
        if (
            [string]$existing.Payload.operation_id -ceq
                [string]$Authority.Receipt.operation_id -and
            [string]$existing.Payload.target_stage -ceq $TargetStage -and
            [string]$existing.Payload.failure_code -ceq $FailureCode
        ) {
            return $existing
        }
        throw "C07 failure evidence 已存在且不可复用。"
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07FailureEvidenceSchema
        operation_id = [string]$Authority.Receipt.operation_id
        target_stage = $TargetStage
        failure_code = $FailureCode
        release_fingerprint = [string]$Authority.Receipt.release_fingerprint
        database_binding_sha256 = [string]$Authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$Authority.Receipt.recovery_epoch_id
        created_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    return Write-TicketboxC07HostEnvelope `
        -Path $path `
        -ArtifactKind "failure_evidence" `
        -Payload $payload
}

function New-TicketboxC07PersistedStageAuthoritySnapshot {
    param(
        [Parameter(Mandatory = $true)][object]$PreviousAuthority,
        [Parameter(Mandatory = $true)][object]$PersistedEnvelope,
        [Parameter(Mandatory = $true)][string]$ExpectedStage,
        [Parameter(Mandatory = $true)][string]$ExpectedEvidenceSha256,
        [string]$ExpectedFailureCode = ""
    )
    $receipt = $PersistedEnvelope.Payload
    Assert-TicketboxC07ReceiptShape `
        -Receipt $receipt `
        -ReleaseIdentity $PreviousAuthority.ReleaseIdentity `
        -Descriptor $PreviousAuthority.Descriptor `
        -RecoveryEpoch $PreviousAuthority.RecoveryEpoch
    $expectedTransitionKind = if (
        [string]::IsNullOrEmpty($ExpectedFailureCode)
    ) { "stage" } else { "failure" }
    if (
        [string]$receipt.operation_id -cne
            [string]$PreviousAuthority.Receipt.operation_id -or
        [string]$receipt.stage -cne $ExpectedStage -or
        [string]$receipt.previous_stage -cne
            [string]$PreviousAuthority.Receipt.stage -or
        [int64]$receipt.stage_sequence -ne
            ([int64]$PreviousAuthority.Receipt.stage_sequence + 1) -or
        [int64]$receipt.authority_revision -ne
            ([int64]$PreviousAuthority.Receipt.authority_revision + 1) -or
        [string]$receipt.transition_kind -cne $expectedTransitionKind -or
        [string]$receipt.coordinator_binding_sha256 -cne
            [string]$PreviousAuthority.Binding.PayloadSha256 -or
        [int64]$receipt.coordinator_binding_sequence -ne
            [int64]$PreviousAuthority.Binding.Sequence -or
        [string]$receipt.previous_receipt_payload_sha256 -cne
            [string]$PreviousAuthority.Envelope.PayloadSha256 -or
        [string]$receipt.previous_authority_chain_sha256 -cne
            [string]$PreviousAuthority.Receipt.authority_chain_sha256 -or
        [string]$receipt.transition_evidence_sha256 -cne
            $ExpectedEvidenceSha256 -or
        [string]$receipt.failure_code -cne $ExpectedFailureCode
    ) {
        throw "C07 写后 receipt snapshot 未精确延续已验证的 authority lineage。"
    }
    return [pscustomobject]@{
        ReleaseIdentity = $PreviousAuthority.ReleaseIdentity
        Roots = $PreviousAuthority.Roots
        RecoveryEpoch = $PreviousAuthority.RecoveryEpoch
        Envelope = $PersistedEnvelope
        Receipt = $receipt
        Descriptor = $PreviousAuthority.Descriptor
        Binding = $PreviousAuthority.Binding
    }
}

function Set-TicketboxC07LifecycleStage {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][ValidateSet(
            "writers_frozen",
            "recovery_generation_ready",
            "isolated_restore_verified",
            "ddl_started",
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified",
            "runtime_acl_verified",
            "ready",
            "refused_pre_ddl",
            "repair_required"
        )][string]$TargetStage,
        [string]$EvidencePath = "",
        [string]$FailureCode = ""
    )
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $currentStage = [string]$authority.Receipt.stage
    if ($currentStage -eq $TargetStage) {
        if (
            $TargetStage -notin (
                @("writers_frozen") + $script:TicketboxC07FailureStages
            )
        ) {
            $expectedPath = Get-TicketboxC07StageEvidencePath `
                -OperationId ([string]$authority.Receipt.operation_id) `
                -Stage $TargetStage
            if (
                [string]::IsNullOrEmpty($EvidencePath) -or
                -not (Test-TicketboxPathEquals $EvidencePath $expectedPath)
            ) {
                throw "C07 idempotent stage resume 必须重用同一 typed evidence artifact。"
            }
            $evidence = Read-TicketboxC07StageEvidence $authority $TargetStage
            if ($evidence.PayloadSha256 -cne [string]$authority.Receipt.transition_evidence_sha256) {
                throw "C07 idempotent stage evidence 与既有 receipt 不一致。"
            }
        }
        $heartbeat = Read-TicketboxC07Heartbeat $authority
        Write-TicketboxC07RuntimeProjection `
            -Authority $authority `
            -HeartbeatSequence ([int64]$heartbeat.Payload.sequence) | Out-Null
        return [pscustomobject]@{
            OperationId = [string]$authority.Receipt.operation_id
            Stage = $currentStage
            StageSequence = [int64]$authority.Receipt.stage_sequence
            AuthorityRevision = [int64]$authority.Receipt.authority_revision
            AuthorityChainSha256 = [string]$authority.Receipt.authority_chain_sha256
            Reused = $true
        }
    }
    if (
        $currentStage -in $script:TicketboxC07FailureStages -or
        $currentStage -eq "ready"
    ) {
        throw "C07 terminal lifecycle receipt 不允许改写为其他阶段。"
    }
    $isFailure = $TargetStage -in $script:TicketboxC07FailureStages
    if ($TargetStage -eq "refused_pre_ddl") {
        if ($currentStage -notin $script:TicketboxC07PreDdlStages) {
            throw "C07 refused_pre_ddl 只能从 DDL 前阶段进入。"
        }
    }
    elseif ($TargetStage -eq "repair_required") {
        if ($currentStage -notin $script:TicketboxC07PostDdlStages) {
            throw "C07 repair_required 只能从 DDL 已开始的阶段进入。"
        }
    }
    else {
        $currentIndex = [array]::IndexOf($script:TicketboxC07OrderedStages, $currentStage)
        $targetIndex = [array]::IndexOf($script:TicketboxC07OrderedStages, $TargetStage)
        if ($currentIndex -lt 0 -or $targetIndex -ne ($currentIndex + 1)) {
            throw "C07 lifecycle stage 只能单调推进一个阶段，拒绝跳级或倒退。"
        }
    }
    if ($isFailure) {
        if ($FailureCode -cnotmatch "^[a-z0-9_]{1,64}$") {
            throw "C07 failure terminal 必须提供稳定 failure code。"
        }
        if (-not [string]::IsNullOrEmpty($EvidencePath)) {
            throw "C07 failure evidence 由 lifecycle authority 内部生成。"
        }
    }
    elseif (-not [string]::IsNullOrEmpty($FailureCode)) {
        throw "C07 非失败阶段不能携带 failure code。"
    }
    $freezeProofSha256 = [string]$authority.Receipt.freeze_proof_sha256
    $freezeProofBindingSequence =
        [int64]$authority.Receipt.freeze_proof_binding_sequence
    $freezeHeartbeatSequence = [int64]$authority.Receipt.freeze_heartbeat_sequence
    $readyVerificationSha256 = [string]$authority.Receipt.ready_verification_sha256
    if ($TargetStage -eq "writers_frozen") {
        if (-not [string]::IsNullOrEmpty($EvidencePath)) {
            throw "C07 writers_frozen evidence 由 live host/database proof 内部派生。"
        }
        $freeze = New-TicketboxC07FreezeProof `
            -Authority $authority `
            -LifecycleLock $LifecycleLock
        $evidenceSha256 = $freeze.PayloadSha256
        $freezeProofSha256 = $freeze.PayloadSha256
        $freezeProofBindingSequence = [int64]$freeze.BindingSequence
        $freezeHeartbeatSequence = $freeze.HeartbeatSequence
    }
    elseif ($isFailure) {
        $failureEvidence = New-TicketboxC07FailureEvidence `
            -Authority $authority `
            -TargetStage $TargetStage `
            -FailureCode $FailureCode
        $evidenceSha256 = $failureEvidence.PayloadSha256
    }
    else {
        $expectedPath = Get-TicketboxC07StageEvidencePath `
            -OperationId ([string]$authority.Receipt.operation_id) `
            -Stage $TargetStage
        if (
            [string]::IsNullOrEmpty($EvidencePath) -or
            -not (Test-TicketboxPathEquals $EvidencePath $expectedPath)
        ) {
            throw "C07 $TargetStage 必须提供本 operation 的受保护 typed evidence artifact。"
        }
        $evidence = Read-TicketboxC07StageEvidence `
            -Authority $authority `
            -Stage $TargetStage
        $evidenceSha256 = $evidence.PayloadSha256
        if ($TargetStage -eq "ready") {
            $readyVerification = New-TicketboxC07ReadyVerification `
                -Authority $authority `
                -LifecycleLock $LifecycleLock
            $readyVerificationSha256 = $readyVerification.PayloadSha256
        }
    }
    $heartbeat = Read-TicketboxC07Heartbeat $authority
    if ([int64]$heartbeat.Payload.sequence -lt $freezeHeartbeatSequence) {
        throw "C07 heartbeat sequence 早于 writers frozen proof。"
    }
    $stageSequence = [int64]$authority.Receipt.stage_sequence + 1
    $receipt = New-TicketboxC07ReceiptPayload ([pscustomobject]@{
        operation_id = [string]$authority.Receipt.operation_id
        stage = $TargetStage
        previous_stage = $currentStage
        stage_sequence = $stageSequence
        authority_revision = [int64]$authority.Receipt.authority_revision + 1
        transition_kind = if ($isFailure) { "failure" } else { "stage" }
        release_fingerprint = [string]$authority.Receipt.release_fingerprint
        descriptor_sha256 = [string]$authority.Receipt.descriptor_sha256
        coordinator_binding_sha256 = [string]$authority.Receipt.coordinator_binding_sha256
        coordinator_binding_sequence = [int64]$authority.Receipt.coordinator_binding_sequence
        database_binding_sha256 = [string]$authority.Receipt.database_binding_sha256
        recovery_epoch_id = [string]$authority.Receipt.recovery_epoch_id
        freeze_proof_sha256 = $freezeProofSha256
        freeze_proof_binding_sequence = $freezeProofBindingSequence
        freeze_heartbeat_sequence = $freezeHeartbeatSequence
        ready_verification_sha256 = $readyVerificationSha256
        previous_receipt_payload_sha256 = $authority.Envelope.PayloadSha256
        previous_authority_chain_sha256 = [string]$authority.Receipt.authority_chain_sha256
        transition_evidence_sha256 = $evidenceSha256
        failure_code = $FailureCode
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    })
    $persistedReceipt = Write-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07AuthorityPath) `
        -ArtifactKind "authority_receipt" `
        -Payload $receipt `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 (
            [string]$authority.Envelope.PayloadSha256
        )
    # The operation lock excludes another lifecycle writer. Reuse only the
    # immutable authority objects validated at entry and the exact receipt that
    # the durable writer has just read back. The next operation still performs
    # a complete authority read; this snapshot exists only for this projection.
    $updated = New-TicketboxC07PersistedStageAuthoritySnapshot `
        -PreviousAuthority $authority `
        -PersistedEnvelope $persistedReceipt `
        -ExpectedStage $TargetStage `
        -ExpectedEvidenceSha256 $evidenceSha256 `
        -ExpectedFailureCode $FailureCode
    Write-TicketboxC07RuntimeProjection `
        -Authority $updated `
        -HeartbeatSequence ([int64]$heartbeat.Payload.sequence) | Out-Null
    return [pscustomobject]@{
        OperationId = [string]$updated.Receipt.operation_id
        Stage = [string]$updated.Receipt.stage
        StageSequence = [int64]$updated.Receipt.stage_sequence
        AuthorityRevision = [int64]$updated.Receipt.authority_revision
        AuthorityChainSha256 = [string]$updated.Receipt.authority_chain_sha256
        Reused = $false
    }
}
