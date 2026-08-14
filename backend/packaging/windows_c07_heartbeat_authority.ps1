#Requires -Version 5.1

<#
.SYNOPSIS
  Shared host authority and durable heartbeat for ADR-0073 C07.
.DESCRIPTION
  This is the single implementation used by both the full lifecycle and its
  credential-free heartbeat child. It validates the protected installation,
  release, recovery, descriptor, receipt, stage-evidence, coordinator-binding,
  lease, maintenance-attempt, and heartbeat chain before an atomic renewal.

  The durable_heartbeat profile requires only installation-safety and lifecycle
  lock authorities. The full profile additionally requires the service and
  database authorities loaded by the installer coordinator.
#>

param(
    [ValidateSet("full", "durable_heartbeat")]
    [string]$TicketboxC07DependencyProfile = "full"
)

$script:TicketboxC07DependencyProfile = $TicketboxC07DependencyProfile
foreach ($requiredDeadlineGuard in @(
    "Assert-NoTicketboxAncestorReparsePoints",
    "Get-TicketboxPathEntryKindNoFollow"
)) {
    if ($null -eq (Get-Command $requiredDeadlineGuard `
        -CommandType Function -ErrorAction SilentlyContinue)) {
        throw "Windows deadline-budget loader lacks guard: $requiredDeadlineGuard"
    }
}
foreach ($deadlineDependencyLeaf in @(
    "windows_deadline_budget.ps1",
    "windows_c07_deadline_policy.ps1"
)) {
    $deadlineDependencyPath = Join-Path $PSScriptRoot $deadlineDependencyLeaf
    Assert-NoTicketboxAncestorReparsePoints $deadlineDependencyPath
    if ((Get-TicketboxPathEntryKindNoFollow $deadlineDependencyPath) -cne "File") {
        throw "Windows deadline dependency is not a trusted ordinary file: $deadlineDependencyPath"
    }
    . $deadlineDependencyPath
}

$script:TicketboxC07EnvelopeSchema = "ticketbox-c07-host-envelope-v2"
$script:TicketboxC07DescriptorSchema = "ticketbox-c07-operation-descriptor-v5"
$script:TicketboxC07HeartbeatSchema = "ticketbox-c07-heartbeat-v4"
$script:TicketboxC07MaintenanceAttemptSchema =
    "ticketbox-c07-maintenance-attempt-v2"
$script:TicketboxC07MaintenanceAttemptFailureSchema =
    "ticketbox-c07-maintenance-attempt-failure-v1"
$script:TicketboxC07FreezeProofSchema = "ticketbox-c07-writers-frozen-proof-v5"
$script:TicketboxC07LegacyWriterFenceIntentSchema =
    "ticketbox-c07-writer-fence-intent-v3"
$script:TicketboxC07WriterFenceIntentSchema = "ticketbox-c07-writer-fence-intent-v4"
$script:TicketboxC07LegacyReadyVerificationSchema =
    "ticketbox-c07-ready-verification-v3"
$script:TicketboxC07ReadyVerificationSchema = "ticketbox-c07-ready-verification-v4"
$script:TicketboxC07ReceiptSchema = "ticketbox-c07-lifecycle-receipt-v3"
$script:TicketboxC07ProjectionSchema = "ticketbox-c07-runtime-projection-v6"
$script:TicketboxC07ReleaseIdentitySchema = "ticketbox-c07-release-identity-v3"
$script:TicketboxC07DatabaseAuthoritySchema = "ticketbox-c07-live-database-authority-v1"
$script:TicketboxC07RecoveryEpochSchema = "ticketbox-c07-recovery-epoch-v1"
$script:TicketboxC07CoordinatorBindingSchema = "ticketbox-c07-coordinator-binding-v2"
$script:TicketboxC07StageEvidenceSchema = "ticketbox-c07-stage-evidence-v2"
$script:TicketboxC07FailureEvidenceSchema = "ticketbox-c07-failure-evidence-v1"
$script:TicketboxC07SuccessorIntentSchema = "ticketbox-c07-successor-intent-v2"
$script:TicketboxC07ProductionAuthoritySchema =
    "ticketbox-c07-production-lifecycle-authority-v4"
$script:TicketboxC07ProductionMigrationContextSchema =
    "ticketbox-c07-production-migration-context-v5"
$script:TicketboxC07InstalledCredentialSchema =
    "ticketbox-c07-installed-credentials-v1"
$script:TicketboxC07FreshBootstrapIntentSchema =
    "ticketbox-c07-fresh-bootstrap-intent-v1"
$script:TicketboxC07HistoricalLegacyRuntimeRole = "ticketbox"
$script:TicketboxC07HistoricalOwnerRole = "ticketbox_owner"
$script:TicketboxC07HistoricalMigratorRole = "ticketbox_migrator"
$script:TicketboxC07ManagedRuntimeRole = "ticketbox_runtime"
$script:TicketboxC07TargetRevision = "20260729_0001"
$script:TicketboxC07MaintenanceWindowSeconds = 20 * 60
$script:TicketboxC07MaximumMaintenanceAttempts = 64
$script:TicketboxC07ActiveMaintenanceBudget = $null
$script:TicketboxC07HostDirectoryName = "c07-lifecycle"
$script:TicketboxC07RuntimeDirectoryName = "c07-runtime-projection"
$script:TicketboxC07AuthorityFileName = "c07-lifecycle-authority.json"
$script:TicketboxC07ProjectionFileName = "c07-lifecycle-projection.json"
$script:TicketboxC07RecoveryEpochFileName = "c07-recovery-epoch.json"
$script:TicketboxC07FreshBootstrapIntentFileName =
    "c07-fresh-bootstrap-intent.json"
$script:TicketboxC07HostFullControlAccounts = @("SYSTEM", "BUILTIN\Administrators")
$script:TicketboxC07HostOwnerAccount = "SYSTEM"
$script:TicketboxC07DatabaseAuthorityPassword = $null
$script:TicketboxC07OrderedStages = @(
    "captured",
    "writers_frozen",
    "recovery_generation_ready",
    "isolated_restore_verified",
    "ddl_started",
    "target_committed",
    "target_recovery_generation_ready",
    "target_isolated_restore_verified",
    "runtime_acl_verified",
    "ready"
)
$script:TicketboxC07FailureStages = @("refused_pre_ddl", "repair_required")
$script:TicketboxC07ProductionGatedStages = @(
    "runtime_acl_verified",
    "ready"
)
$script:TicketboxC07PreDdlStages = @(
    "captured",
    "writers_frozen",
    "recovery_generation_ready",
    "isolated_restore_verified"
)
$script:TicketboxC07PostDdlStages = @(
    "ddl_started",
    "target_committed",
    "target_recovery_generation_ready",
    "target_isolated_restore_verified",
    "runtime_acl_verified"
)
$script:TicketboxC07StageEvidenceContracts = @{
    recovery_generation_ready = [pscustomobject]@{
        Schema = "ticketbox-c07-recovery-generation-v3"
        Result = "generation_ready"
    }
    isolated_restore_verified = [pscustomobject]@{
        Schema = "ticketbox-c07-isolated-restore-evidence-v2"
        Result = "isolated_restore_reconciled"
    }
    ddl_started = [pscustomobject]@{
        Schema = "ticketbox-c07-ddl-start-evidence-v1"
        Result = "ddl_started"
    }
    target_committed = [pscustomobject]@{
        Schema = "ticketbox-c07-target-commit-evidence-v1"
        Result = "target_committed"
    }
    target_recovery_generation_ready = [pscustomobject]@{
        Schema = "ticketbox-c07-target-recovery-generation-v2"
        Result = "target_generation_ready"
    }
    target_isolated_restore_verified = [pscustomobject]@{
        Schema = "ticketbox-c07-target-isolated-restore-evidence-v1"
        Result = "target_isolated_restore_verified"
    }
    runtime_acl_verified = [pscustomobject]@{
        Schema = "ticketbox-c07-runtime-acl-evidence-v1"
        Result = "runtime_acl_verified"
    }
    ready = [pscustomobject]@{
        Schema = "ticketbox-c07-ready-evidence-v1"
        Result = "ready"
    }
}

function Assert-TicketboxC07DependencyCommands {
    param(
        [Parameter(Mandatory = $true)][string[]]$CommandNames,
        [Parameter(Mandatory = $true)][string]$ProfileName
    )

    foreach ($commandName in $CommandNames) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw (
                "C07 $ProfileName dependency profile 缺少真实依赖函数：" +
                $commandName
            )
        }
    }
}

function Assert-TicketboxC07DurableHeartbeatDependencies {
    Assert-TicketboxC07DependencyCommands `
        -ProfileName "durable_heartbeat" `
        -CommandNames @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "Assert-TicketboxExactFileAcl",
        "Assert-TicketboxLifecycleLockIsHeld",
        "Assert-TicketboxProtectedDirectoryAcl",
        "Close-TicketboxC07MigrationHelperLease",
        "Close-TicketboxProcessIdentityHandle",
        "Compare-TicketboxNumericVersion",
        "ConvertTo-TicketboxCanonicalPath",
        "Enter-TicketboxDirectoryMutationGuard",
        "Get-TicketboxLifecycleLockPath",
        "Get-TicketboxLifecycleOperationLockPath",
        "Get-TicketboxPendingInstallationIdentityPath",
        "Get-TicketboxPortableFileSha256",
        "Get-TicketboxProcessIdentity",
        "Initialize-TicketboxProtectedDirectoryAtomically",
        "New-TicketboxProcessIdentityFromFileTimeParts",
        "Open-TicketboxVerifiedProcessIdentityHandle",
        "Open-TicketboxC07VerifiedMigrationHelperLease",
        "Read-TicketboxInstalledBuildManifest",
        "Read-TicketboxPersistentInstallationIdentity",
        "Read-TicketboxProtectedUtf8Artifact",
        "Resolve-TicketboxInstalledC07MigrationHelperPath",
        "Test-TicketboxPathEquals",
        "Test-TicketboxPathWithin",
        "Test-TicketboxProcessIdentityEquals",
        "Test-TicketboxProcessIdentityHandleExited",
        "Write-TicketboxProtectedUtf8FileDurable"
    )
}

function Assert-TicketboxC07FullDependencies {
    Assert-TicketboxC07DurableHeartbeatDependencies
    Assert-TicketboxC07DependencyCommands `
        -ProfileName "full" `
        -CommandNames @(
        "Assert-TicketboxC07LiveHostConnection",
        "Get-TicketboxC07DatabaseCatalogObservation",
        "Get-TicketboxExpectedRuntimeProcessIds",
        "Get-TicketboxListeningProcessIds",
        "Get-TicketboxServiceProcessId",
        "Get-TicketboxServiceStartPolicy",
        "Get-TicketboxServiceState",
        "Assert-TicketboxC07PublishedReadyRoleSet",
        "Invoke-TicketboxC07Sql",
        "Resolve-TicketboxC07DatabaseHostAuthority",
        "Disable-TicketboxOwnedServiceIfExists"
    )
}

function Assert-TicketboxC07Dependencies {
    if ($script:TicketboxC07DependencyProfile -ceq "durable_heartbeat") {
        Assert-TicketboxC07DurableHeartbeatDependencies
    }
    else {
        Assert-TicketboxC07FullDependencies
    }
}

function Get-TicketboxC07TextSha256([string]$Text) {
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "")
    }
    finally { $sha256.Dispose() }
}

function ConvertTo-TicketboxC07CompactJson([object]$Value) {
    return [string]($Value | ConvertTo-Json -Depth 32 -Compress)
}

function Assert-TicketboxC07Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$FieldName
    )
    if ($Value -cnotmatch "^[0-9A-F]{64}$") {
        throw "C07 $FieldName 不是规范 SHA-256。"
    }
}

function Assert-TicketboxC07LowerSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$FieldName
    )
    if ($Value -cnotmatch "^[0-9a-f]{64}$") {
        throw "C07 $FieldName 不是外部合同的 canonical lowercase SHA-256。"
    }
}

function Assert-TicketboxC07ExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$ExpectedNames,
        [Parameter(Mandatory = $true)][string]$ArtifactName
    )
    if ($null -eq $Value) {
        throw "C07 $ArtifactName 为空。"
    }
    $actualNames = @($Value.PSObject.Properties | ForEach-Object { $_.Name })
    if ($actualNames.Count -ne $ExpectedNames.Count) {
        throw "C07 $ArtifactName 字段数量不符合契约。"
    }
    foreach ($name in $ExpectedNames) {
        if ($name -notin $actualNames) {
            throw "C07 $ArtifactName 缺少字段：$name"
        }
    }
    foreach ($name in $actualNames) {
        if ($name -notin $ExpectedNames) {
            throw "C07 $ArtifactName 含有未知字段：$name"
        }
    }
}

function ConvertTo-TicketboxC07CanonicalOperationId([string]$OperationId) {
    $parsed = [guid]::Empty
    if (
        -not [guid]::TryParseExact($OperationId, "D", [ref]$parsed) -or
        $parsed -eq [guid]::Empty
    ) {
        throw "C07 operation identity 必须是非空规范 UUID。"
    }
    $canonical = $parsed.ToString("D")
    if ($OperationId -cne $canonical) {
        throw "C07 operation identity 不是规范小写 UUID。"
    }
    return $canonical
}

function ConvertTo-TicketboxC07CanonicalUtcTimestamp {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $parsed = [DateTimeOffset]::MinValue
    if (
        -not [DateTimeOffset]::TryParseExact(
            $Value,
            "o",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$parsed
        ) -or
        $parsed.Offset -ne [TimeSpan]::Zero
    ) {
        throw "$Label 不是 canonical UTC。"
    }
    return $parsed.UtcDateTime.ToString("o")
}

function ConvertTo-TicketboxC07CanonicalUuid {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    try { $parsed = [guid]::ParseExact($Value, "D") }
    catch { throw "C07 $Label 不是规范 UUID。" }
    if ($parsed -eq [guid]::Empty -or $parsed.ToString("D") -cne $Value) {
        throw "C07 $Label 不是非空规范小写 UUID。"
    }
    return $Value
}

function Get-TicketboxC07HostArtifactRoot {
    Assert-TicketboxC07Dependencies
    $lockRoot = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    return Join-Path $lockRoot $script:TicketboxC07HostDirectoryName
}

function Get-TicketboxC07RuntimeProjectionRoot {
    Assert-TicketboxC07Dependencies
    $lockRoot = Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    return Join-Path $lockRoot $script:TicketboxC07RuntimeDirectoryName
}

function Get-TicketboxC07AuthorityPath {
    return Join-Path (Get-TicketboxC07HostArtifactRoot) $script:TicketboxC07AuthorityFileName
}

function Get-TicketboxC07SuccessorIntentPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-successor-intent.json"
}

function Get-TicketboxC07RecoveryEpochPath {
    return Join-Path (Get-TicketboxC07HostArtifactRoot) $script:TicketboxC07RecoveryEpochFileName
}

function Get-TicketboxC07DescriptorPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (Get-TicketboxC07HostArtifactRoot) "operation-$canonical-descriptor.json"
}

function Get-TicketboxC07HeartbeatPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (Get-TicketboxC07HostArtifactRoot) "operation-$canonical-heartbeat.json"
}

function Get-TicketboxC07MaintenanceAttemptPath {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$AttemptId
    )
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    $canonicalAttempt = ConvertTo-TicketboxC07CanonicalOperationId $AttemptId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "op-$canonical-a-$canonicalAttempt.json"
}

function Get-TicketboxC07MaintenanceAttemptId {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [ValidateRange(1, [int]::MaxValue)][int]$Sequence
    )
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    $digest = (Get-TicketboxC07TextSha256 (
        "ticketbox-c07-maintenance-attempt-v2`n$canonical`n$Sequence`n"
    )).ToLowerInvariant()
    # A deterministic UUID-shaped identifier makes the immutable attempt file
    # itself the precommit record. Retrying the same operation/sequence can no
    # longer mint a second path after a kill between file and heartbeat writes.
    return (
        $digest.Substring(0, 8) + "-" +
        $digest.Substring(8, 4) + "-5" +
        $digest.Substring(13, 3) + "-a" +
        $digest.Substring(17, 3) + "-" +
        $digest.Substring(20, 12)
    )
}

function Get-TicketboxC07MaintenanceAttemptFailurePath {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$AttemptId
    )
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    $canonicalAttempt = ConvertTo-TicketboxC07CanonicalOperationId $AttemptId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "op-$canonical-af-$canonicalAttempt.json"
}

function Get-TicketboxC07FreezeProofPath {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [ValidateRange(0, [int]::MaxValue)][int]$BindingSequence = 0
    )
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    $leaf = if ($BindingSequence -eq 0) {
        "operation-$canonical-freeze-proof.json"
    }
    else {
        "operation-$canonical-freeze-proof-binding-$BindingSequence.json"
    }
    return Join-Path (Get-TicketboxC07HostArtifactRoot) $leaf
}

function Get-TicketboxC07WriterFenceIntentPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-writer-fence-intent.json"
}

function Get-TicketboxC07ReadyVerificationPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-ready-verification.json"
}

function Get-TicketboxC07ProductionAuthorityPath([string]$OperationId) {
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-production-authority.json"
}

function Get-TicketboxC07CoordinatorBindingPath {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][ValidateRange(1, [int]::MaxValue)][int]$Sequence
    )
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-coordinator-binding-$Sequence.json"
}

function Get-TicketboxC07StageEvidencePath {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $canonical = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    if (
        $Stage -notin $script:TicketboxC07OrderedStages -and
        $Stage -notin $script:TicketboxC07FailureStages
    ) {
        throw "C07 stage evidence 使用未知阶段。"
    }
    return Join-Path (
        Get-TicketboxC07HostArtifactRoot
    ) "operation-$canonical-stage-$Stage-evidence.json"
}

function Get-TicketboxC07ReleaseIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [string]$ExpectedInstallationOperationId = ""
    )
    Assert-TicketboxC07Dependencies
    $identity = if (
        [string]::IsNullOrEmpty($ExpectedInstallationOperationId)
    ) {
        Read-TicketboxPersistentInstallationIdentity -DataRoot $DataRoot
    }
    else {
        $expectedOperationId =
            ([guid]$ExpectedInstallationOperationId).ToString("D")
        $pendingPath =
            Get-TicketboxPendingInstallationIdentityPath $DataRoot
        if (-not (Test-Path -LiteralPath $pendingPath)) {
            throw "C07 安装事务缺少 exact PENDING installation identity。"
        }
        $pendingIdentity = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $DataRoot `
            -Pending
        if (
            $pendingIdentity.State -cne "PENDING" -or
            [bool]$pendingIdentity.LegacyCompleted -or
            $pendingIdentity.OperationId -cne $expectedOperationId
        ) {
            throw "C07 安装事务与 PENDING installation operation 不一致。"
        }
        $pendingIdentity
    }
    if (
        [string]::IsNullOrEmpty($ExpectedInstallationOperationId) -and
        $identity.State -cne "READY"
    ) {
        throw "普通 C07 runtime 只能使用 committed READY installation identity。"
    }
    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath $DataRoot
    if (-not (Test-TicketboxPathEquals $identity.DataRoot $canonicalDataRoot)) {
        throw "C07 DataRoot 与受保护 installation identity 不一致。"
    }
    $manifestPath = Join-Path (
        $identity.InstallDir
    ) "installer\BUILD_PROVENANCE.json"
    if (-not (Test-TicketboxPathWithin $manifestPath $identity.InstallDir)) {
        throw "C07 installed build manifest 越出 installation identity。"
    }
    $manifest = Read-TicketboxInstalledBuildManifest -Path $manifestPath
    $manifestSha256 = Get-TicketboxPortableFileSha256 $manifestPath
    if ($manifestSha256 -cne [string]$identity.BuildManifestSha256) {
        throw "C07 installed build manifest 与受保护 installation identity 摘要不一致。"
    }
    if (
        (Compare-TicketboxNumericVersion `
            ([string]$manifest.BackendVersion) `
            ([string]$identity.BackendVersionFloor)) -ne 0
    ) {
        throw "C07 release identity 要求 installed build 与 backend version floor 精确同代。"
    }
    $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath $identity.InstallDir
    $helperEvidence = $manifest.C07MigrationHelper
    $helperPath = Resolve-TicketboxInstalledC07MigrationHelperPath `
        -InstallDir $canonicalInstallDir `
        -Evidence $helperEvidence
    $helperLease = $null
    try {
        $helperLease = Open-TicketboxC07VerifiedMigrationHelperLease `
            -Path $helperPath `
            -ExpectedRelativePath ([string]$helperEvidence.RelativePath) `
            -ExpectedSize ([int64]$helperEvidence.Size) `
            -ExpectedSha256 ([string]$helperEvidence.Sha256)
        $helperSize = [int64]$helperLease.Size
        $helperSha256 = [string]$helperLease.Sha256
    }
    finally {
        Close-TicketboxC07MigrationHelperLease $helperLease
    }
    $programEvidence = $manifest.DatabaseGenerationProgram
    $programPath = Resolve-TicketboxInstalledDatabaseGenerationProgramPath `
        -InstallDir $canonicalInstallDir `
        -Evidence $programEvidence
    $bindingText = [string]::Join("`n", @(
        "schema=$script:TicketboxC07ReleaseIdentitySchema",
        "installation_id=$([string]$identity.InstallationId)",
        "build_manifest_sha256=$manifestSha256",
        "backend_version_floor=$([string]$identity.BackendVersionFloor)",
        "data_root=$($canonicalDataRoot.ToUpperInvariant())",
        "install_dir=$($canonicalInstallDir.ToUpperInvariant())",
        "pg_service_name=$([string]$identity.PgServiceName)",
        "backend_service_name=$([string]$identity.BackendServiceName)",
        "pg_port=$([int]$identity.PgPort)",
        "backend_port=$([int]$identity.BackendPort)",
        "migration_helper_relative_path=$([string]$helperEvidence.RelativePath)",
        "migration_helper_size=$helperSize",
        "migration_helper_sha256=$helperSha256",
        "database_generation_program_relative_path=$([string]$programEvidence.RelativePath)",
        "database_generation_program_size=$([int64]$programEvidence.Size)",
        "database_generation_program_sha256=$([string]$programEvidence.Sha256)"
    )) + "`n"
    return [pscustomobject]@{
        InstallationIdentityState = [string]$identity.State
        InstallationOperationId = [string]$identity.OperationId
        LegacyCompletedInstallationIdentity = [bool]$identity.LegacyCompleted
        InstallationId = [string]$identity.InstallationId
        BuildManifestSha256 = $manifestSha256
        BackendVersionFloor = [string]$identity.BackendVersionFloor
        DataRoot = $canonicalDataRoot
        InstallDir = $canonicalInstallDir
        PgServiceName = [string]$identity.PgServiceName
        BackendServiceName = [string]$identity.BackendServiceName
        PgPort = [int]$identity.PgPort
        BackendPort = [int]$identity.BackendPort
        BackendExe = Join-Path $canonicalInstallDir "program\ticketbox-backend\ticketbox-backend.exe"
        ShawlExe = Join-Path $canonicalInstallDir "shawl\shawl.exe"
        MigrationHelperPath = $helperPath
        MigrationHelperRelativePath = [string]$helperEvidence.RelativePath
        MigrationHelperSize = $helperSize
        MigrationHelperSha256 = $helperSha256
        DatabaseGenerationProgramPath = $programPath
        DatabaseGenerationProgramRelativePath =
            [string]$programEvidence.RelativePath
        DatabaseGenerationProgramSize = [int64]$programEvidence.Size
        DatabaseGenerationProgramSha256 =
            [string]$programEvidence.Sha256
        Fingerprint = Get-TicketboxC07TextSha256 $bindingText
    }
}

function New-TicketboxC07ReleaseIdentityProjection {
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [switch]$Historical
    )
    if (
        [string]$Identity.State -cnotin @("PENDING", "READY") -or
        [bool]$Identity.LegacyCompleted
    ) {
        throw "C07 release identity projection 只接受当前受保护 identity schema。"
    }
    $canonicalDataRoot = ConvertTo-TicketboxCanonicalPath (
        [string]$Identity.DataRoot
    )
    $canonicalInstallDir = ConvertTo-TicketboxCanonicalPath (
        [string]$Identity.InstallDir
    )
    if (
        [string]$Identity.BuildManifestSha256 -cnotmatch "^[0-9A-F]{64}$" -or
        [string]$Identity.MigrationHelperSha256 -cnotmatch "^[0-9A-F]{64}$" -or
        [int64]$Identity.MigrationHelperSize -lt 1 -or
        [string]$Identity.MigrationHelperRelativePath -cne
            $script:TicketboxC07MigrationHelperRelativePath
    ) {
        throw "C07 historical release identity 的 manifest/helper evidence 无效。"
    }
    ConvertTo-TicketboxNumericVersion (
        [string]$Identity.BackendVersionFloor
    ) | Out-Null
    $bindingText = [string]::Join("`n", @(
        "schema=$script:TicketboxC07ReleaseIdentitySchema",
        "installation_id=$([string]$Identity.InstallationId)",
        "build_manifest_sha256=$([string]$Identity.BuildManifestSha256)",
        "backend_version_floor=$([string]$Identity.BackendVersionFloor)",
        "data_root=$($canonicalDataRoot.ToUpperInvariant())",
        "install_dir=$($canonicalInstallDir.ToUpperInvariant())",
        "pg_service_name=$([string]$Identity.PgServiceName)",
        "backend_service_name=$([string]$Identity.BackendServiceName)",
        "pg_port=$([int]$Identity.PgPort)",
        "backend_port=$([int]$Identity.BackendPort)",
        "migration_helper_relative_path=$([string]$Identity.MigrationHelperRelativePath)",
        "migration_helper_size=$([int64]$Identity.MigrationHelperSize)",
        "migration_helper_sha256=$([string]$Identity.MigrationHelperSha256)"
    )) + "`n"
    return [pscustomobject]@{
        InstallationIdentityState = [string]$Identity.State
        InstallationOperationId = [string]$Identity.OperationId
        LegacyCompletedInstallationIdentity = $false
        InstallationId = [string]$Identity.InstallationId
        BuildManifestSha256 = [string]$Identity.BuildManifestSha256
        BackendVersionFloor = [string]$Identity.BackendVersionFloor
        DataRoot = $canonicalDataRoot
        InstallDir = $canonicalInstallDir
        PgServiceName = [string]$Identity.PgServiceName
        BackendServiceName = [string]$Identity.BackendServiceName
        PgPort = [int]$Identity.PgPort
        BackendPort = [int]$Identity.BackendPort
        BackendExe = Join-Path `
            $canonicalInstallDir `
            "program\ticketbox-backend\ticketbox-backend.exe"
        ShawlExe = Join-Path $canonicalInstallDir "shawl\shawl.exe"
        MigrationHelperPath = [System.IO.Path]::GetFullPath(
            $MigrationHelperPath
        )
        MigrationHelperRelativePath =
            [string]$Identity.MigrationHelperRelativePath
        MigrationHelperSize = [int64]$Identity.MigrationHelperSize
        MigrationHelperSha256 = [string]$Identity.MigrationHelperSha256
        Fingerprint = Get-TicketboxC07TextSha256 $bindingText
        Historical = [bool]$Historical
    }
}

function Get-TicketboxC07HistoricalReleaseIdentity {
    param([Parameter(Mandatory = $true)][object]$InstallationIdentity)
    if (
        [string]$InstallationIdentity.State -cne "PENDING" -or
        [bool]$InstallationIdentity.LegacyCompleted
    ) {
        throw "C07 terminal predecessor 缺少当前 PENDING installation identity。"
    }
    $helperPath = Join-Path (
        Join-Path (
            [string]$InstallationIdentity.InstallDir
        ) "program\ticketbox-backend"
    ) ([string]$InstallationIdentity.MigrationHelperRelativePath)
    return New-TicketboxC07ReleaseIdentityProjection `
        -Identity $InstallationIdentity `
        -MigrationHelperPath $helperPath `
        -Historical
}

function Assert-TicketboxC07ArtifactRoots([object]$ReleaseIdentity) {
    $lockRoot = ConvertTo-TicketboxCanonicalPath (
        Split-Path -Parent (Get-TicketboxLifecycleLockPath)
    )
    $hostRoot = ConvertTo-TicketboxCanonicalPath (Get-TicketboxC07HostArtifactRoot)
    $runtimeRoot = ConvertTo-TicketboxCanonicalPath (Get-TicketboxC07RuntimeProjectionRoot)
    foreach ($entry in @(
        [pscustomobject]@{ Name = "host authority"; Path = $hostRoot },
        [pscustomobject]@{ Name = "runtime projection"; Path = $runtimeRoot }
    )) {
        if (
            -not (Test-TicketboxPathWithin $entry.Path $lockRoot) -or
            (Test-TicketboxPathEquals $entry.Path $lockRoot)
        ) {
            throw "C07 $($entry.Name) 必须位于机器生命周期锁根的专用子目录。"
        }
        if (
            (Test-TicketboxPathWithin $entry.Path $ReleaseIdentity.DataRoot) -or
            (Test-TicketboxPathWithin $ReleaseIdentity.DataRoot $entry.Path)
        ) {
            throw "C07 $($entry.Name) 不能位于 Backend 可写 AppData/DataRoot 或其祖先。"
        }
    }
    if (
        (Test-TicketboxPathWithin $hostRoot $runtimeRoot) -or
        (Test-TicketboxPathWithin $runtimeRoot $hostRoot)
    ) {
        throw "C07 host authority 与 runtime projection 必须使用隔离目录。"
    }
    return [pscustomobject]@{
        LockRoot = $lockRoot
        HostRoot = $hostRoot
        RuntimeRoot = $runtimeRoot
    }
}

function New-TicketboxC07EnvelopeText {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactKind,
        [Parameter(Mandatory = $true)][object]$Payload
    )
    if ($ArtifactKind -cnotmatch "^[a-z0-9_-]{1,64}$") {
        throw "C07 artifact kind 无效。"
    }
    $payloadJson = ConvertTo-TicketboxC07CompactJson $Payload
    $payloadSha256 = Get-TicketboxC07TextSha256 $payloadJson
    $envelope = [ordered]@{
        schema = $script:TicketboxC07EnvelopeSchema
        artifact_kind = $ArtifactKind
        payload_sha256 = $payloadSha256
        payload_json = $payloadJson
    }
    return (ConvertTo-TicketboxC07CompactJson $envelope) + "`n"
}

function ConvertFrom-TicketboxC07JsonText {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Label
    )
    try {
        $command = Get-Command ConvertFrom-Json -CommandType Cmdlet
        if ($command.Parameters.ContainsKey("DateKind")) {
            return ConvertFrom-Json -InputObject $Text -DateKind String
        }
        return ConvertFrom-Json -InputObject $Text
    }
    catch {
        throw "C07 $Label 不是有效 JSON。"
    }
}

function ConvertFrom-TicketboxC07EnvelopeText {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$ExpectedKind
    )
    $envelope = ConvertFrom-TicketboxC07JsonText `
        -Text $Text `
        -Label "$ExpectedKind envelope"
    Assert-TicketboxC07ExactProperties `
        -Value $envelope `
        -ExpectedNames @("schema", "artifact_kind", "payload_sha256", "payload_json") `
        -ArtifactName "$ExpectedKind envelope"
    if (
        [string]$envelope.schema -cne $script:TicketboxC07EnvelopeSchema -or
        [string]$envelope.artifact_kind -cne $ExpectedKind -or
        $envelope.payload_sha256 -isnot [string] -or
        $envelope.payload_json -isnot [string]
    ) {
        throw "C07 $ExpectedKind envelope schema 或类型不受支持。"
    }
    $expectedSha256 = [string]$envelope.payload_sha256
    Assert-TicketboxC07Sha256 $expectedSha256 "$ExpectedKind payload hash"
    if (
        (Get-TicketboxC07TextSha256 ([string]$envelope.payload_json)) -cne
        $expectedSha256
    ) {
        throw "C07 $ExpectedKind payload hash mismatch。"
    }
    $payload = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$envelope.payload_json) `
        -Label "$ExpectedKind payload"
    return [pscustomobject]@{
        Payload = $payload
        PayloadJson = [string]$envelope.payload_json
        PayloadSha256 = $expectedSha256
        Text = $Text
    }
}

function Read-TicketboxC07HostEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedKind
    )
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount `
        -MaximumBytes 1048576
    return ConvertFrom-TicketboxC07EnvelopeText `
        -Text $artifact.Text `
        -ExpectedKind $ExpectedKind
}

function Write-TicketboxC07HostEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ArtifactKind,
        [Parameter(Mandatory = $true)][object]$Payload,
        [switch]$ReplaceExisting,
        [switch]$ReadCompareReuse,
        [string]$ExpectedExistingPayloadSha256 = ""
    )
    if (-not [string]::IsNullOrEmpty($ExpectedExistingPayloadSha256)) {
        Assert-TicketboxC07Sha256 `
            $ExpectedExistingPayloadSha256 `
            "$ArtifactKind expected existing payload hash"
    }
    $text = New-TicketboxC07EnvelopeText -ArtifactKind $ArtifactKind -Payload $Payload
    if (Test-Path -LiteralPath $Path) {
        $existing = Read-TicketboxC07HostEnvelope -Path $Path -ExpectedKind $ArtifactKind
        if (
            -not [string]::IsNullOrEmpty($ExpectedExistingPayloadSha256) -and
            [string]$existing.PayloadSha256 -cne $ExpectedExistingPayloadSha256
        ) {
            throw "C07 host authority artifact 已从预期前态漂移：$Path"
        }
        if ($ReadCompareReuse -and $existing.Text -ceq $text) {
            return $existing
        }
        if (-not $ReplaceExisting) {
            throw "C07 host authority artifact 已存在但内容不可复用：$Path"
        }
    }
    elseif (-not [string]::IsNullOrEmpty($ExpectedExistingPayloadSha256)) {
        throw "C07 host authority artifact 的预期前态已丢失：$Path"
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount `
        -ReplaceExisting:(Test-Path -LiteralPath $Path)
    $persisted = Read-TicketboxC07HostEnvelope -Path $Path -ExpectedKind $ArtifactKind
    if ($persisted.Text -cne $text) {
        throw "C07 host authority artifact 写后复读不一致：$Path"
    }
    return $persisted
}

function Read-TicketboxC07WriterFenceIntent([object]$Authority) {
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path (
            Get-TicketboxC07WriterFenceIntentPath (
                [string]$Authority.Receipt.operation_id
            )
        ) `
        -ExpectedKind "writer_fence_intent"
    $payload = $envelope.Payload
    $schema = [string]$payload.schema
    $isLegacyV3 = $schema -ceq $script:TicketboxC07LegacyWriterFenceIntentSchema
    $expectedPayloadNames = @(
        "schema",
        "operation_id",
        "descriptor_sha256",
        "database_binding_sha256",
        "backend_service_start_policy",
        "public_connect",
        "client_session_count_before_fence",
        "client_sessions_before_fence",
        "max_prepared_transactions",
        "prepared_transaction_count",
        "logical_subscription_count",
        "logical_apply_worker_count",
        "unexpected_database_worker_count",
        "roles",
        "created_at_utc"
    )
    if (-not $isLegacyV3) {
        $expectedPayloadNames = @(
            $expectedPayloadNames[0..3] +
            @("operation_mode", "authority_phase") +
            $expectedPayloadNames[4..($expectedPayloadNames.Count - 1)]
        )
    }
    Assert-TicketboxC07ExactProperties `
        $payload `
        $expectedPayloadNames `
        "writer-fence intent"
    if (
        $schema -cnotin @(
            $script:TicketboxC07LegacyWriterFenceIntentSchema,
            $script:TicketboxC07WriterFenceIntentSchema
        ) -or
        [string]$payload.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$payload.descriptor_sha256 -cne
            $Authority.Descriptor.PayloadSha256 -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        (
            -not $isLegacyV3 -and
            (
                [string]$payload.operation_mode -cnotin @(
                    "fresh_install", "legacy_adoption"
                ) -or
                [string]$payload.authority_phase -cnotin @(
                    "legacy_owner_frozen", "managed_frozen"
                ) -or
                (
                    [string]$payload.operation_mode -ceq "fresh_install" -and
                    [string]$payload.authority_phase -cne "managed_frozen"
                )
            )
        ) -or
        [string]$payload.backend_service_start_policy -cnotin @(
            "disabled",
            "manual",
            "auto",
            "delayed_auto"
        ) -or
        $payload.public_connect -isnot [bool] -or
        (
            $payload.client_session_count_before_fence -isnot [int] -and
            $payload.client_session_count_before_fence -isnot [long]
        ) -or
        [int64]$payload.client_session_count_before_fence -lt 0 -or
        @($payload.client_sessions_before_fence).Count -ne
            [int64]$payload.client_session_count_before_fence -or
        [int64]$payload.max_prepared_transactions -ne 0 -or
        [int64]$payload.prepared_transaction_count -ne 0 -or
        [int64]$payload.logical_subscription_count -ne 0 -or
        [int64]$payload.logical_apply_worker_count -ne 0 -or
        [int64]$payload.unexpected_database_worker_count -ne 0
    ) {
        throw "C07 writer-fence intent 未绑定 operation/database/service authority。"
    }
    foreach ($session in @($payload.client_sessions_before_fence)) {
        Assert-TicketboxC07ExactProperties `
            $session `
            @("pid", "role", "application_name", "state") `
            "writer-fence intent client session"
        if (
            [int]$session.pid -lt 1 -or
            [string]::IsNullOrEmpty([string]$session.role)
        ) {
            throw "C07 writer-fence intent client session 无效。"
        }
    }
    $roles = @($payload.roles)
    if ($roles.Count -lt 2 -or $roles.Count -gt 128) {
        throw "C07 writer-fence intent role 集无效。"
    }
    foreach ($role in $roles) {
        $roleNames = @(
            "name",
            "oid",
            "disposition",
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
        )
        if (-not $isLegacyV3) {
            $roleNames = @(
                $roleNames[0..12] +
                @(
                    "owns_security_definer_routines",
                    "can_execute_unowned_security_definer_routines"
                ) +
                $roleNames[13..($roleNames.Count - 1)] +
                @("predefined_role_usage", "predefined_role_set")
            )
        }
        Assert-TicketboxC07ExactProperties `
            $role `
            $roleNames `
            "writer-fence intent role"
    }
    $authorityPhase = if ($isLegacyV3) {
        Resolve-TicketboxC07HistoricalWriterFenceAuthorityPhase -Roles $roles
    }
    else {
        [string]$payload.authority_phase
    }
    $envelope | Add-Member -NotePropertyName IntentSchema -NotePropertyValue $schema
    $envelope | Add-Member `
        -NotePropertyName IsLegacyV3 `
        -NotePropertyValue $isLegacyV3
    $envelope | Add-Member `
        -NotePropertyName OperationMode `
        -NotePropertyValue $(if ($isLegacyV3) { "historical_v3" } else {
            [string]$payload.operation_mode
        })
    $envelope | Add-Member `
        -NotePropertyName AuthorityPhase `
        -NotePropertyValue $authorityPhase
    $envelope | Add-Member `
        -NotePropertyName PublicConnect `
        -NotePropertyValue ([bool]$payload.public_connect)
    $envelope | Add-Member `
        -NotePropertyName Roles `
        -NotePropertyValue @($roles)
    return $envelope
}

function Resolve-TicketboxC07HistoricalWriterFenceAuthorityPhase {
    param([Parameter(Mandatory = $true)][object[]]$Roles)

    $databaseOwners = @($Roles | Where-Object { [bool]$_.is_database_owner })
    $legacyOwnerRoles = @($Roles | Where-Object {
        [string]$_.name -ceq $script:TicketboxC07HistoricalLegacyRuntimeRole -and
        [bool]$_.is_database_owner
    })
    $managedOwnerRoles = @($Roles | Where-Object {
        [string]$_.name -ceq $script:TicketboxC07HistoricalOwnerRole -and
        [bool]$_.is_database_owner
    })
    if (
        $databaseOwners.Count -eq 1 -and
        $legacyOwnerRoles.Count -eq 1 -and
        $managedOwnerRoles.Count -eq 0
    ) {
        return "legacy_owner_frozen"
    }
    if (
        $databaseOwners.Count -eq 1 -and
        $legacyOwnerRoles.Count -eq 0 -and
        $managedOwnerRoles.Count -eq 1 -and
        [bool]$managedOwnerRoles[0].is_database_owner
    ) {
        return "managed_frozen"
    }
    throw (
        "C07 historical v3 intent 无法从不可变 database-owner facts " +
        "唯一分类 frozen authority phase。"
    )
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

function Test-TicketboxC07PublishedReadyRoleIdentityTransition {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object[]]$ReadyRoles
    )

    $intentRoles = @($Intent.Roles)
    if (Test-TicketboxC07WriterFenceRoleIdentitySetEquals $intentRoles $ReadyRoles) {
        return $true
    }
    if (
        [bool]$Intent.IsLegacyV3 -or
        [string]$Intent.OperationMode -cne "legacy_adoption" -or
        [string]$Intent.AuthorityPhase -cne "legacy_owner_frozen"
    ) {
        return $false
    }
    $targetRoleNames = @(
        $script:TicketboxC07HistoricalOwnerRole,
        $script:TicketboxC07HistoricalMigratorRole,
        $script:TicketboxC07ManagedRuntimeRole
    )
    if (@($intentRoles | Where-Object {
        [string]$_.name -cin $targetRoleNames
    }).Count -ne 0) {
        return $false
    }
    if ($ReadyRoles.Count -ne $intentRoles.Count + $targetRoleNames.Count) {
        return $false
    }
    foreach ($intentRole in $intentRoles) {
        if (@($ReadyRoles | Where-Object {
            [string]$_.name -ceq [string]$intentRole.name -and
            [int64]$_.oid -eq [int64]$intentRole.oid
        }).Count -ne 1) {
            return $false
        }
    }
    $addedRoles = @($ReadyRoles | Where-Object {
        $readyRole = $_
        @($intentRoles | Where-Object {
            [string]$_.name -ceq [string]$readyRole.name -and
            [int64]$_.oid -eq [int64]$readyRole.oid
        }).Count -eq 0
    })
    return (
        $addedRoles.Count -eq $targetRoleNames.Count -and
        @($targetRoleNames | Where-Object {
            $targetName = $_
            @($addedRoles | Where-Object {
                [string]$_.name -ceq $targetName
            }).Count -ne 1
        }).Count -eq 0
    )
}

function Test-TicketboxC07LegacyV3WriterFenceRoleSetEquals {
    param(
        [Parameter(Mandatory = $true)][object[]]$Left,
        [Parameter(Mandatory = $true)][object[]]$Right,
        [switch]$AllowFencedRight
    )
    if ($Left.Count -ne $Right.Count) { return $false }
    foreach ($leftRole in $Left) {
        $matches = @(
            $Right | Where-Object {
                [string]$_.name -ceq [string]$leftRole.name -and
                [int64]$_.oid -eq [int64]$leftRole.oid
            }
        )
        if ($matches.Count -ne 1) { return $false }
        $rightRole = $matches[0]
        foreach ($field in @(
            "disposition", "is_superuser", "can_create_db",
            "can_create_role", "can_replicate", "can_bypass_rls",
            "is_database_owner", "owns_public_schema", "owns_user_relations",
            "can_database_create", "can_public_schema_create",
            "can_table_write", "can_sequence_write", "can_assume_write_owner"
        )) {
            if ([string]$leftRole.$field -cne [string]$rightRole.$field) {
                return $false
            }
        }
        $same = (
            [bool]$leftRole.can_login -eq [bool]$rightRole.can_login -and
            [int]$leftRole.connection_limit -eq [int]$rightRole.connection_limit -and
            [bool]$leftRole.direct_connect -eq [bool]$rightRole.direct_connect -and
            [bool]$leftRole.effective_connect -eq [bool]$rightRole.effective_connect
        )
        $fenced = (
            $AllowFencedRight -and
            [string]$rightRole.disposition -ceq "fenced_runtime" -and
            -not [bool]$rightRole.can_login -and
            [int]$rightRole.connection_limit -eq 0 -and
            -not [bool]$rightRole.direct_connect -and
            (
                -not [bool]$rightRole.effective_connect -or
                [bool]$rightRole.is_database_owner
            )
        )
        $publicOnlyFenced = (
            $AllowFencedRight -and
            [string]$rightRole.disposition -cin @(
                "inert_unregistered", "nologin_owner"
            ) -and
            [bool]$leftRole.can_login -eq [bool]$rightRole.can_login -and
            [int]$leftRole.connection_limit -eq [int]$rightRole.connection_limit -and
            [bool]$leftRole.direct_connect -eq [bool]$rightRole.direct_connect -and
            -not [bool]$rightRole.effective_connect
        )
        if (-not $same -and -not $fenced -and -not $publicOnlyFenced) {
            return $false
        }
    }
    return $true
}

function Assert-TicketboxC07LiveProcessIdentity([object]$Identity) {
    $handleLease = Open-TicketboxVerifiedProcessIdentityHandle `
        -ProcessId ([int]$Identity.ProcessId) `
        -ExpectedIdentity $Identity
    try {
        if (Test-TicketboxProcessIdentityHandleExited $handleLease) {
            throw "C07 coordinator process 已退出。"
        }
    }
    finally { Close-TicketboxProcessIdentityHandle $handleLease }
}

function New-TicketboxC07IdentityFromPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$Prefix
    )
    foreach ($name in @(
        "${Prefix}_pid",
        "${Prefix}_started_filetime_high",
        "${Prefix}_started_filetime_low"
    )) {
        $property = $Payload.PSObject.Properties[$name]
        if (
            $null -eq $property -or
            ($property.Value -isnot [int] -and $property.Value -isnot [long])
        ) {
            throw "C07 identity 缺少数值字段：$name"
        }
    }
    $processId = [int]$Payload.PSObject.Properties["${Prefix}_pid"].Value
    $startedHigh = [int64]$Payload.PSObject.Properties[
        "${Prefix}_started_filetime_high"
    ].Value
    $startedLow = [int64]$Payload.PSObject.Properties[
        "${Prefix}_started_filetime_low"
    ].Value
    if (
        $processId -le 0 -or
        $startedHigh -lt 0 -or $startedHigh -gt [uint32]::MaxValue -or
        $startedLow -lt 0 -or $startedLow -gt [uint32]::MaxValue
    ) {
        throw "C07 identity 数值超出范围：$Prefix"
    }
    return New-TicketboxProcessIdentityFromFileTimeParts `
        -ProcessId $processId `
        -StartedFileTimeHigh ([uint32]$startedHigh) `
        -StartedFileTimeLow ([uint32]$startedLow)
}

function Read-TicketboxC07RecoveryEpoch([object]$ReleaseIdentity) {
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07RecoveryEpochPath) `
        -ExpectedKind "recovery_epoch"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @("schema", "installation_id", "recovery_epoch_id", "created_at_utc") `
        "recovery epoch"
    ConvertTo-TicketboxC07CanonicalUuid `
        ([string]$payload.recovery_epoch_id) `
        "recovery epoch id" | Out-Null
    if (
        [string]$payload.schema -cne $script:TicketboxC07RecoveryEpochSchema -or
        [string]$payload.installation_id -cne $ReleaseIdentity.InstallationId
    ) {
        throw "C07 protected recovery epoch 与 installation identity 不一致。"
    }
    return $envelope
}

function Get-TicketboxC07SuccessorIntentPredecessorIdentity {
    param([Parameter(Mandatory = $true)][object]$Intent)
    $payload = if ($null -ne $Intent.Payload) {
        $Intent.Payload
    }
    else {
        $Intent
    }
    $identity = [pscustomobject]@{
        State = "PENDING"
        OperationId = [string]$payload.predecessor_operation_id
        LegacyCompleted = $false
        InstallationId = [string]$payload.installation_id
        BuildManifestSha256 =
            [string]$payload.predecessor_build_manifest_sha256
        BackendVersionFloor =
            [string]$payload.predecessor_backend_version_floor
        DataRoot = [string]$payload.data_root
        InstallDir = [string]$payload.install_dir
        PgServiceName = [string]$payload.pg_service_name
        BackendServiceName = [string]$payload.backend_service_name
        PgPort = [int]$payload.pg_port
        BackendPort = [int]$payload.backend_port
        MigrationHelperRelativePath =
            [string]$payload.predecessor_migration_helper_relative_path
        MigrationHelperSize =
            [int64]$payload.predecessor_migration_helper_size
        MigrationHelperSha256 =
            [string]$payload.predecessor_migration_helper_sha256
    }
    return Get-TicketboxC07HistoricalReleaseIdentity $identity
}

function Read-TicketboxC07SuccessorIntent {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$SuccessorReleaseIdentity
    )
    $canonicalOperationId = ConvertTo-TicketboxC07CanonicalOperationId $OperationId
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07SuccessorIntentPath $canonicalOperationId) `
        -ExpectedKind "successor_intent"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "successor_operation_id",
            "successor_mode",
            "successor_release_fingerprint",
            "successor_build_manifest_sha256",
            "installation_id",
            "data_root",
            "install_dir",
            "pg_service_name",
            "backend_service_name",
            "pg_port",
            "backend_port",
            "predecessor_operation_id",
            "predecessor_release_fingerprint",
            "predecessor_backend_version_floor",
            "predecessor_build_manifest_sha256",
            "predecessor_migration_helper_relative_path",
            "predecessor_migration_helper_size",
            "predecessor_migration_helper_sha256",
            "predecessor_terminal_receipt_payload_sha256",
            "predecessor_terminal_authority_chain_sha256",
            "predecessor_terminal_stage",
            "predecessor_failure_code",
            "predecessor_database_binding_sha256",
            "predecessor_revision_manifest_sha256",
            "predecessor_freeze_proof_sha256",
            "predecessor_recovery_epoch_id",
            "predecessor_recovery_generation_evidence_sha256",
            "predecessor_isolated_restore_evidence_sha256",
            "predecessor_target_commit_evidence_sha256",
            "predecessor_target_recovery_generation_evidence_sha256",
            "predecessor_target_isolated_restore_evidence_sha256",
            "predecessor_runtime_acl_evidence_sha256",
            "predecessor_production_marker_sha256",
            "source_alembic_revision",
            "target_alembic_revision",
            "live_alembic_revision",
            "live_database_binding_sha256",
            "authorized_at_utc"
        ) `
        "successor intent"
    if (
        [string]$payload.schema -cne $script:TicketboxC07SuccessorIntentSchema -or
        [string]$payload.successor_operation_id -cne $canonicalOperationId -or
        [string]$payload.successor_mode -cnotin @("pre_ddl", "forward_repair") -or
        [string]$payload.successor_release_fingerprint -cne
            [string]$SuccessorReleaseIdentity.Fingerprint -or
        [string]$payload.successor_build_manifest_sha256 -cne
            [string]$SuccessorReleaseIdentity.BuildManifestSha256 -or
        [string]$payload.installation_id -cne
            [string]$SuccessorReleaseIdentity.InstallationId -or
        -not (Test-TicketboxPathEquals `
            ([string]$payload.data_root) `
            ([string]$SuccessorReleaseIdentity.DataRoot)) -or
        -not (Test-TicketboxPathEquals `
            ([string]$payload.install_dir) `
            ([string]$SuccessorReleaseIdentity.InstallDir)) -or
        [string]$payload.pg_service_name -cne
            [string]$SuccessorReleaseIdentity.PgServiceName -or
        [string]$payload.backend_service_name -cne
            [string]$SuccessorReleaseIdentity.BackendServiceName -or
        [int]$payload.pg_port -ne [int]$SuccessorReleaseIdentity.PgPort -or
        [int]$payload.backend_port -ne
            [int]$SuccessorReleaseIdentity.BackendPort -or
        [string]$payload.source_alembic_revision -cne "20260722_0001" -or
        [string]$payload.target_alembic_revision -cne
            $script:TicketboxC07TargetRevision
    ) {
        throw "C07 successor intent 与当前 release/install/revision authority 不一致。"
    }
    ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$payload.predecessor_operation_id
    ) | Out-Null
    ConvertTo-TicketboxC07CanonicalUuid (
        [string]$payload.predecessor_recovery_epoch_id
    ) "successor predecessor recovery epoch" | Out-Null
    foreach ($field in @(
        "successor_release_fingerprint",
        "successor_build_manifest_sha256",
        "predecessor_release_fingerprint",
        "predecessor_build_manifest_sha256",
        "predecessor_migration_helper_sha256",
        "predecessor_terminal_receipt_payload_sha256",
        "predecessor_terminal_authority_chain_sha256",
        "predecessor_database_binding_sha256",
        "predecessor_revision_manifest_sha256",
        "live_database_binding_sha256"
    )) {
        Assert-TicketboxC07Sha256 ([string]$payload.$field) "successor $field"
    }
    foreach ($field in @(
        "predecessor_freeze_proof_sha256",
        "predecessor_recovery_generation_evidence_sha256",
        "predecessor_isolated_restore_evidence_sha256",
        "predecessor_target_commit_evidence_sha256",
        "predecessor_target_recovery_generation_evidence_sha256",
        "predecessor_target_isolated_restore_evidence_sha256",
        "predecessor_runtime_acl_evidence_sha256",
        "predecessor_production_marker_sha256"
    )) {
        if (-not [string]::IsNullOrEmpty([string]$payload.$field)) {
            Assert-TicketboxC07Sha256 ([string]$payload.$field) "successor $field"
        }
    }
    if (
        [string]$payload.predecessor_terminal_stage -cnotin
            $script:TicketboxC07FailureStages -or
        [string]$payload.predecessor_failure_code -cnotmatch "^[a-z0-9_]{1,64}$" -or
        [string]$payload.live_alembic_revision -cnotin @(
            "20260722_0001",
            $script:TicketboxC07TargetRevision
        ) -or
        (
            [string]$payload.successor_mode -ceq "pre_ddl" -and
            (
                [string]$payload.predecessor_terminal_stage -cne
                    "refused_pre_ddl" -or
                [string]$payload.live_alembic_revision -cne "20260722_0001"
            )
        ) -or
        (
            [string]$payload.successor_mode -ceq "forward_repair" -and
            (
                [string]$payload.predecessor_terminal_stage -cne
                    "repair_required" -or
                [string]$payload.live_alembic_revision -cne
                    $script:TicketboxC07TargetRevision -or
                [string]::IsNullOrEmpty(
                    [string]$payload.predecessor_freeze_proof_sha256
                ) -or
                [string]::IsNullOrEmpty(
                    [string]$payload.predecessor_recovery_generation_evidence_sha256
                ) -or
                [string]::IsNullOrEmpty(
                    [string]$payload.predecessor_isolated_restore_evidence_sha256
                ) -or
                [string]::IsNullOrEmpty(
                    [string]$payload.predecessor_production_marker_sha256
                )
            )
        )
    ) {
        throw "C07 successor intent 的 terminal/no-return/live revision 组合无效。"
    }
    $predecessorReleaseIdentity =
        Get-TicketboxC07SuccessorIntentPredecessorIdentity $envelope
    if (
        [string]$predecessorReleaseIdentity.Fingerprint -cne
            [string]$payload.predecessor_release_fingerprint
    ) {
        throw "C07 successor intent predecessor release snapshot hash 不一致。"
    }
    return [pscustomobject]@{
        Path = Get-TicketboxC07SuccessorIntentPath $canonicalOperationId
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
        Text = $envelope.Text
        PredecessorReleaseIdentity = $predecessorReleaseIdentity
    }
}

function Assert-TicketboxC07DescriptorPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$RecoveryEpoch
    )
    $expectedNames = @(
        "schema",
        "operation_id",
        "release_fingerprint",
        "installation_id",
        "build_manifest_sha256",
        "backend_version_floor",
        "data_root_binding_sha256",
        "database_binding_sha256",
        "cluster_system_identifier",
        "database_name",
        "database_oid",
        "logical_server_id",
        "data_generation",
        "operation_kind",
        "source_alembic_revision",
        "target_alembic_revision",
        "revision_manifest_sha256",
        "successor_mode",
        "successor_intent_sha256",
        "predecessor_operation_id",
        "predecessor_terminal_receipt_payload_sha256",
        "predecessor_terminal_authority_chain_sha256",
        "predecessor_terminal_stage",
        "predecessor_failure_code",
        "predecessor_database_binding_sha256",
        "predecessor_revision_manifest_sha256",
        "recovery_epoch_id",
        "recovery_epoch_payload_sha256",
        "coordinator_pid",
        "coordinator_started_filetime_high",
        "coordinator_started_filetime_low",
        "lifecycle_owner_pid",
        "lifecycle_owner_started_filetime_high",
        "lifecycle_owner_started_filetime_low",
        "initial_heartbeat_sequence",
        "maintenance_window_ms",
        "captured_tick_count64",
        "captured_boot_identity",
        "captured_at_utc"
    )
    Assert-TicketboxC07ExactProperties $Payload $expectedNames "operation descriptor"
    if ([string]$Payload.schema -cne $script:TicketboxC07DescriptorSchema) {
        throw "C07 operation descriptor schema 不受支持。"
    }
    ConvertTo-TicketboxC07CanonicalOperationId ([string]$Payload.operation_id) | Out-Null
    foreach ($hashField in @(
        "release_fingerprint",
        "build_manifest_sha256",
        "data_root_binding_sha256",
        "database_binding_sha256",
        "recovery_epoch_payload_sha256",
        "revision_manifest_sha256"
    )) {
        Assert-TicketboxC07Sha256 ([string]$Payload.$hashField) $hashField
    }
    if (
        [string]$Payload.release_fingerprint -cne $ReleaseIdentity.Fingerprint -or
        [string]$Payload.installation_id -cne $ReleaseIdentity.InstallationId -or
        [string]$Payload.build_manifest_sha256 -cne $ReleaseIdentity.BuildManifestSha256 -or
        [string]$Payload.backend_version_floor -cne $ReleaseIdentity.BackendVersionFloor -or
        [string]$Payload.recovery_epoch_id -cne
            [string]$RecoveryEpoch.Payload.recovery_epoch_id -or
        [string]$Payload.recovery_epoch_payload_sha256 -cne
            $RecoveryEpoch.PayloadSha256 -or
        [string]$Payload.operation_kind -cne
            "c07_money_minor_bigint_v1" -or
        [string]$Payload.source_alembic_revision -cne
            "20260722_0001" -or
        [string]$Payload.target_alembic_revision -cne
            $script:TicketboxC07TargetRevision -or
        [int64]$Payload.initial_heartbeat_sequence -ne 0 -or
        [int64]$Payload.maintenance_window_ms -ne
            ($script:TicketboxC07MaintenanceWindowSeconds * 1000) -or
        [int64]$Payload.captured_tick_count64 -lt 0 -or
        [string]::IsNullOrEmpty([string]$Payload.captured_boot_identity)
    ) {
        throw "C07 operation descriptor 与当前受保护 release/recovery identity 不一致。"
    }
    $successorFields = @(
        "successor_mode",
        "successor_intent_sha256",
        "predecessor_operation_id",
        "predecessor_terminal_receipt_payload_sha256",
        "predecessor_terminal_authority_chain_sha256",
        "predecessor_terminal_stage",
        "predecessor_failure_code",
        "predecessor_database_binding_sha256",
        "predecessor_revision_manifest_sha256"
    )
    $populatedSuccessorFields = @(
        $successorFields | Where-Object {
            -not [string]::IsNullOrEmpty([string]$Payload.$_)
        }
    )
    if (
        $populatedSuccessorFields.Count -ne 0 -and
        $populatedSuccessorFields.Count -ne $successorFields.Count
    ) {
        throw "C07 successor descriptor predecessor lineage 必须全有或全无。"
    }
    if ($populatedSuccessorFields.Count -eq $successorFields.Count) {
        if (
            [string]$Payload.successor_mode -cnotin @(
                "pre_ddl",
                "forward_repair"
            ) -or
            [string]$Payload.predecessor_terminal_stage -cnotin
                $script:TicketboxC07FailureStages -or
            [string]$Payload.predecessor_failure_code -cnotmatch
                "^[a-z0-9_]{1,64}$"
        ) {
            throw "C07 successor descriptor terminal lineage shape 无效。"
        }
        ConvertTo-TicketboxC07CanonicalOperationId (
            [string]$Payload.predecessor_operation_id
        ) | Out-Null
        foreach ($field in @(
            "successor_intent_sha256",
            "predecessor_terminal_receipt_payload_sha256",
            "predecessor_terminal_authority_chain_sha256",
            "predecessor_database_binding_sha256",
            "predecessor_revision_manifest_sha256"
        )) {
            Assert-TicketboxC07Sha256 `
                ([string]$Payload.$field) `
                "descriptor $field"
        }
        $successorIntent = Read-TicketboxC07SuccessorIntent `
            -OperationId ([string]$Payload.operation_id) `
            -SuccessorReleaseIdentity $ReleaseIdentity
        $intent = $successorIntent.Payload
        if (
            [string]$successorIntent.PayloadSha256 -cne
                [string]$Payload.successor_intent_sha256 -or
            [string]$intent.successor_mode -cne
                [string]$Payload.successor_mode -or
            [string]$intent.predecessor_operation_id -cne
                [string]$Payload.predecessor_operation_id -or
            [string]$intent.predecessor_terminal_receipt_payload_sha256 -cne
                [string]$Payload.predecessor_terminal_receipt_payload_sha256 -or
            [string]$intent.predecessor_terminal_authority_chain_sha256 -cne
                [string]$Payload.predecessor_terminal_authority_chain_sha256 -or
            [string]$intent.predecessor_terminal_stage -cne
                [string]$Payload.predecessor_terminal_stage -or
            [string]$intent.predecessor_failure_code -cne
                [string]$Payload.predecessor_failure_code -or
            [string]$intent.predecessor_database_binding_sha256 -cne
                [string]$Payload.predecessor_database_binding_sha256 -or
            [string]$intent.predecessor_revision_manifest_sha256 -cne
                [string]$Payload.predecessor_revision_manifest_sha256
        ) {
            throw "C07 successor descriptor 未绑定 exact immutable intent。"
        }
    }
    $expectedDataRootHash = Get-TicketboxC07TextSha256 (
        $ReleaseIdentity.DataRoot.ToUpperInvariant() + "`n"
    )
    if ([string]$Payload.data_root_binding_sha256 -cne $expectedDataRootHash) {
        throw "C07 operation descriptor DataRoot binding 不一致。"
    }
    return [pscustomobject]@{
        OperationId = [string]$Payload.operation_id
        CoordinatorIdentity = New-TicketboxC07IdentityFromPayload $Payload "coordinator"
        LifecycleOwnerIdentity = New-TicketboxC07IdentityFromPayload $Payload "lifecycle_owner"
    }
}

function Read-TicketboxC07Descriptor {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$RecoveryEpoch
    )
    $path = Get-TicketboxC07DescriptorPath $OperationId
    $envelope = Read-TicketboxC07HostEnvelope -Path $path -ExpectedKind "descriptor"
    $validated = Assert-TicketboxC07DescriptorPayload `
        -Payload $envelope.Payload `
        -ReleaseIdentity $ReleaseIdentity `
        -RecoveryEpoch $RecoveryEpoch
    if ($validated.OperationId -cne $OperationId) {
        throw "C07 descriptor operation identity 与 authority 不一致。"
    }
    return [pscustomobject]@{
        Path = $path
        Payload = $envelope.Payload
        PayloadSha256 = $envelope.PayloadSha256
        CoordinatorIdentity = $validated.CoordinatorIdentity
        LifecycleOwnerIdentity = $validated.LifecycleOwnerIdentity
    }
}

function Get-TicketboxC07ReceiptChainText([object]$Receipt) {
    return [string]::Join("`n", @(
        "operation_id=$([string]$Receipt.operation_id)",
        "stage=$([string]$Receipt.stage)",
        "previous_stage=$([string]$Receipt.previous_stage)",
        "stage_sequence=$([int64]$Receipt.stage_sequence)",
        "authority_revision=$([int64]$Receipt.authority_revision)",
        "transition_kind=$([string]$Receipt.transition_kind)",
        "release_fingerprint=$([string]$Receipt.release_fingerprint)",
        "descriptor_sha256=$([string]$Receipt.descriptor_sha256)",
        "coordinator_binding_sha256=$([string]$Receipt.coordinator_binding_sha256)",
        "coordinator_binding_sequence=$([int64]$Receipt.coordinator_binding_sequence)",
        "database_binding_sha256=$([string]$Receipt.database_binding_sha256)",
        "recovery_epoch_id=$([string]$Receipt.recovery_epoch_id)",
        "freeze_proof_sha256=$([string]$Receipt.freeze_proof_sha256)",
        "freeze_proof_binding_sequence=$([int64]$Receipt.freeze_proof_binding_sequence)",
        "freeze_heartbeat_sequence=$([int64]$Receipt.freeze_heartbeat_sequence)",
        "ready_verification_sha256=$([string]$Receipt.ready_verification_sha256)",
        "previous_receipt_payload_sha256=$([string]$Receipt.previous_receipt_payload_sha256)",
        "previous_authority_chain_sha256=$([string]$Receipt.previous_authority_chain_sha256)",
        "transition_evidence_sha256=$([string]$Receipt.transition_evidence_sha256)",
        "failure_code=$([string]$Receipt.failure_code)"
    )) + "`n"
}

function Assert-TicketboxC07ReceiptShape {
    param(
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity,
        [Parameter(Mandatory = $true)][object]$Descriptor,
        [Parameter(Mandatory = $true)][object]$RecoveryEpoch
    )
    $expectedNames = @(
        "schema",
        "operation_id",
        "stage",
        "previous_stage",
        "stage_sequence",
        "authority_revision",
        "transition_kind",
        "release_fingerprint",
        "descriptor_sha256",
        "coordinator_binding_sha256",
        "coordinator_binding_sequence",
        "database_binding_sha256",
        "recovery_epoch_id",
        "freeze_proof_sha256",
        "freeze_proof_binding_sequence",
        "freeze_heartbeat_sequence",
        "ready_verification_sha256",
        "previous_receipt_payload_sha256",
        "previous_authority_chain_sha256",
        "transition_evidence_sha256",
        "authority_chain_sha256",
        "failure_code",
        "updated_at_utc"
    )
    Assert-TicketboxC07ExactProperties $Receipt $expectedNames "lifecycle receipt"
    if (
        [string]$Receipt.schema -cne $script:TicketboxC07ReceiptSchema -or
        [string]$Receipt.operation_id -cne [string]$Descriptor.Payload.operation_id -or
        [string]$Receipt.release_fingerprint -cne $ReleaseIdentity.Fingerprint -or
        [string]$Receipt.descriptor_sha256 -cne $Descriptor.PayloadSha256 -or
        [string]$Receipt.database_binding_sha256 -cne
            [string]$Descriptor.Payload.database_binding_sha256 -or
        [string]$Receipt.recovery_epoch_id -cne
            [string]$RecoveryEpoch.Payload.recovery_epoch_id
    ) {
        throw "C07 lifecycle receipt 与 descriptor/release/database/recovery identity 不一致。"
    }
    $stage = [string]$Receipt.stage
    if ($stage -notin ($script:TicketboxC07OrderedStages + $script:TicketboxC07FailureStages)) {
        throw "C07 lifecycle receipt stage 不受支持。"
    }
    foreach ($field in @(
        "descriptor_sha256",
        "coordinator_binding_sha256",
        "database_binding_sha256",
        "transition_evidence_sha256",
        "authority_chain_sha256"
    )) {
        Assert-TicketboxC07Sha256 ([string]$Receipt.$field) $field
    }
    foreach ($field in @(
        "freeze_proof_sha256",
        "ready_verification_sha256",
        "previous_receipt_payload_sha256",
        "previous_authority_chain_sha256"
    )) {
        $value = [string]$Receipt.$field
        if (-not [string]::IsNullOrEmpty($value)) {
            Assert-TicketboxC07Sha256 $value $field
        }
    }
    foreach ($field in @(
        "stage_sequence",
        "authority_revision",
        "coordinator_binding_sequence",
        "freeze_proof_binding_sequence",
        "freeze_heartbeat_sequence"
    )) {
        if (
            $Receipt.$field -isnot [int] -and
            $Receipt.$field -isnot [long]
        ) {
            throw "C07 lifecycle receipt 数值字段类型无效：$field"
        }
    }
    $stageSequence = [int64]$Receipt.stage_sequence
    $authorityRevision = [int64]$Receipt.authority_revision
    $bindingSequence = [int64]$Receipt.coordinator_binding_sequence
    $kind = [string]$Receipt.transition_kind
    $previousStage = [string]$Receipt.previous_stage
    if ($kind -cnotin @("captured", "takeover", "stage", "failure")) {
        throw "C07 lifecycle receipt transition kind 无效。"
    }
    if ($authorityRevision -eq 0) {
        if (
            $kind -cne "captured" -or $stage -cne "captured" -or
            $stageSequence -ne 0 -or $bindingSequence -ne 0 -or
            -not [string]::IsNullOrEmpty($previousStage) -or
            -not [string]::IsNullOrEmpty([string]$Receipt.previous_receipt_payload_sha256) -or
            -not [string]::IsNullOrEmpty([string]$Receipt.previous_authority_chain_sha256) -or
            [string]$Receipt.coordinator_binding_sha256 -cne $Descriptor.PayloadSha256
        ) {
            throw "C07 captured receipt 携带了不可能的历史或 binding。"
        }
    }
    else {
        if (
            $authorityRevision -lt 1 -or
            (
                ($kind -cne "takeover" -or $stage -cne "captured") -and
                [string]::IsNullOrEmpty($previousStage)
            ) -or
            [string]::IsNullOrEmpty([string]$Receipt.previous_receipt_payload_sha256) -or
            [string]::IsNullOrEmpty([string]$Receipt.previous_authority_chain_sha256)
        ) {
            throw "C07 lifecycle receipt 缺少前态 hash chain。"
        }
        if ($kind -eq "takeover") {
            $stageIndex = [array]::IndexOf(
                $script:TicketboxC07OrderedStages,
                $stage
            )
            $expectedEntryPrevious = if ($stageIndex -eq 0) {
                ""
            }
            else {
                [string]$script:TicketboxC07OrderedStages[$stageIndex - 1]
            }
            if (
                $previousStage -cne $expectedEntryPrevious -or
                $bindingSequence -lt 1 -or
                $stage -in $script:TicketboxC07FailureStages -or
                $stage -eq "ready"
            ) {
                throw "C07 coordinator takeover 边界无效。"
            }
        }
        else {
            $previousIndex = [array]::IndexOf($script:TicketboxC07OrderedStages, $previousStage)
            if ($previousIndex -lt 0 -or $stageSequence -ne ($previousIndex + 1)) {
                throw "C07 lifecycle receipt stage sequence 与前态不一致。"
            }
            if ($kind -eq "stage") {
                $stageIndex = [array]::IndexOf($script:TicketboxC07OrderedStages, $stage)
                if ($stageIndex -ne ($previousIndex + 1)) {
                    throw "C07 lifecycle receipt 非法跳级或倒退。"
                }
            }
            elseif (
                $kind -ne "failure" -or
                (
                    $stage -eq "refused_pre_ddl" -and
                    $previousStage -notin $script:TicketboxC07PreDdlStages
                ) -or
                (
                    $stage -eq "repair_required" -and
                    $previousStage -notin $script:TicketboxC07PostDdlStages
                )
            ) {
                throw "C07 failure terminal 与 DDL 边界不一致。"
            }
        }
    }
    if ($stage -in $script:TicketboxC07FailureStages) {
        if ([string]$Receipt.failure_code -cnotmatch "^[a-z0-9_]{1,64}$") {
            throw "C07 failure terminal 缺少稳定 failure code。"
        }
    }
    elseif ([string]$Receipt.failure_code -ne "") {
        throw "C07 非失败阶段不能携带 failure code。"
    }
    $crossedFreeze = (
        [string]$Receipt.freeze_proof_sha256 -ne "" -or
        [int64]$Receipt.freeze_heartbeat_sequence -ne 0
    )
    if ($crossedFreeze) {
        Assert-TicketboxC07Sha256 `
            ([string]$Receipt.freeze_proof_sha256) `
            "freeze proof hash"
        if ([int64]$Receipt.freeze_heartbeat_sequence -lt 1) {
            throw "C07 writers_frozen 之后必须绑定正 heartbeat sequence。"
        }
        if (
            [int64]$Receipt.freeze_proof_binding_sequence -lt 0 -or
            [int64]$Receipt.freeze_proof_binding_sequence -gt
                [int64]$Receipt.coordinator_binding_sequence
        ) {
            throw "C07 freeze proof binding sequence 越出 coordinator lineage。"
        }
    }
    elseif ([int64]$Receipt.freeze_proof_binding_sequence -ne 0) {
        throw "C07 未生成 freeze proof 却携带 binding sequence。"
    }
    elseif (
        (
            $stage -in $script:TicketboxC07OrderedStages -and
            [array]::IndexOf($script:TicketboxC07OrderedStages, $stage) -ge 1
        ) -or
        $stage -eq "repair_required" -or
        ($stage -eq "refused_pre_ddl" -and $previousStage -ne "captured")
    ) {
        throw "C07 已越过 writers_frozen 却缺少 freeze proof。"
    }
    if (
        (Get-TicketboxC07TextSha256 (Get-TicketboxC07ReceiptChainText $Receipt)) -cne
        [string]$Receipt.authority_chain_sha256
    ) {
        throw "C07 lifecycle receipt authority hash chain 不一致。"
    }
    if ($stage -eq "ready") {
        Assert-TicketboxC07Sha256 `
            ([string]$Receipt.ready_verification_sha256) `
            "ready verification hash"
    }
    elseif (-not [string]::IsNullOrEmpty([string]$Receipt.ready_verification_sha256)) {
        throw "C07 非 READY receipt 不能携带 ready verification。"
    }
}

function Read-TicketboxC07CoordinatorBindingAtSequence {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Descriptor,
        [ValidateRange(0, [int]::MaxValue)][int]$Sequence,
        [string]$ExpectedPayloadSha256 = ""
    )
    if ($Sequence -eq 0) {
        if (
            -not [string]::IsNullOrEmpty($ExpectedPayloadSha256) -and
            $ExpectedPayloadSha256 -cne $Descriptor.PayloadSha256
        ) {
            throw "C07 initial coordinator binding 与 descriptor 不一致。"
        }
        return [pscustomobject]@{
            Sequence = 0
            PayloadSha256 = $Descriptor.PayloadSha256
            CoordinatorIdentity = $Descriptor.CoordinatorIdentity
            LifecycleOwnerIdentity = $Descriptor.LifecycleOwnerIdentity
        }
    }
    $path = Get-TicketboxC07CoordinatorBindingPath `
        -OperationId $OperationId `
        -Sequence $Sequence
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "coordinator_binding"
    $payload = $envelope.Payload
    $expectedNames = @(
        "schema",
        "operation_id",
        "binding_sequence",
        "previous_binding_sha256",
        "previous_heartbeat_payload_sha256",
        "previous_heartbeat_sequence",
        "previous_receipt_payload_sha256",
        "previous_authority_chain_sha256",
        "resumed_stage",
        "old_coordinator_pid",
        "old_coordinator_started_filetime_high",
        "old_coordinator_started_filetime_low",
        "new_coordinator_pid",
        "new_coordinator_started_filetime_high",
        "new_coordinator_started_filetime_low",
        "new_lifecycle_owner_pid",
        "new_lifecycle_owner_started_filetime_high",
        "new_lifecycle_owner_started_filetime_low",
        "resumed_at_utc"
    )
    Assert-TicketboxC07ExactProperties $payload $expectedNames "coordinator binding"
    Assert-TicketboxC07Sha256 `
        ([string]$payload.previous_heartbeat_payload_sha256) `
        "coordinator binding previous heartbeat"
    if (
        [string]$payload.schema -cne $script:TicketboxC07CoordinatorBindingSchema -or
        [string]$payload.operation_id -cne $OperationId -or
        [int64]$payload.binding_sequence -ne $Sequence -or
        (
            $payload.previous_heartbeat_sequence -isnot [int] -and
            $payload.previous_heartbeat_sequence -isnot [long]
        ) -or
        [int64]$payload.previous_heartbeat_sequence -lt 0 -or
        (
            -not [string]::IsNullOrEmpty($ExpectedPayloadSha256) -and
            $envelope.PayloadSha256 -cne $ExpectedPayloadSha256
        )
    ) {
        throw "C07 coordinator binding identity/sequence 不一致。"
    }
    $previousBinding = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId $OperationId `
        -Descriptor $Descriptor `
        -Sequence ($Sequence - 1) `
        -ExpectedPayloadSha256 ([string]$payload.previous_binding_sha256)
    $oldCoordinator = New-TicketboxC07IdentityFromPayload `
        $payload `
        "old_coordinator"
    if (-not (Test-TicketboxProcessIdentityEquals `
        $oldCoordinator `
        $previousBinding.CoordinatorIdentity)) {
        throw "C07 coordinator binding predecessor identity 不一致。"
    }
    return [pscustomobject]@{
        Sequence = [int64]$Sequence
        PayloadSha256 = $envelope.PayloadSha256
        Payload = $payload
        CoordinatorIdentity = New-TicketboxC07IdentityFromPayload $payload "new_coordinator"
        LifecycleOwnerIdentity = New-TicketboxC07IdentityFromPayload $payload "new_lifecycle_owner"
    }
}

function Read-TicketboxC07CoordinatorBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][object]$Descriptor
    )
    $binding = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$Receipt.operation_id) `
        -Descriptor $Descriptor `
        -Sequence ([int]$Receipt.coordinator_binding_sequence) `
        -ExpectedPayloadSha256 ([string]$Receipt.coordinator_binding_sha256)
    if ($binding.Sequence -gt 0) {
        $resumedStage = [string]$binding.Payload.resumed_stage
        $resumedIndex = [array]::IndexOf(
            $script:TicketboxC07OrderedStages,
            $resumedStage
        )
        $receiptLineageStage = if (
            [string]$Receipt.stage -in $script:TicketboxC07FailureStages
        ) {
            [string]$Receipt.previous_stage
        }
        else {
            [string]$Receipt.stage
        }
        $receiptLineageIndex = [array]::IndexOf(
            $script:TicketboxC07OrderedStages,
            $receiptLineageStage
        )
        if (
            $resumedIndex -lt 0 -or
            $resumedStage -ceq "ready" -or
            $receiptLineageIndex -lt $resumedIndex -or
            (
                [string]$Receipt.transition_kind -ceq "takeover" -and
                $resumedStage -cne [string]$Receipt.stage
            )
        ) {
            throw "C07 coordinator binding 与 authority receipt stage lineage 不一致。"
        }
    }
    return $binding
}

function Read-TicketboxC07FreezeProof {
    param([Parameter(Mandatory = $true)][object]$Authority)
    $receipt = $Authority.Receipt
    $descriptor = $Authority.Descriptor
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path (
            Get-TicketboxC07FreezeProofPath `
                -OperationId ([string]$receipt.operation_id) `
                -BindingSequence (
                    [int]$receipt.freeze_proof_binding_sequence
                )
        ) `
        -ExpectedKind "freeze_proof"
    $payload = $envelope.Payload
    $expectedNames = @(
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
        "database_advisory_fence_available",
        "writers_frozen_at_utc"
    )
    Assert-TicketboxC07ExactProperties $payload $expectedNames "writers frozen proof"
    if (
        [string]$payload.schema -cne $script:TicketboxC07FreezeProofSchema -or
        [string]$payload.operation_id -cne [string]$receipt.operation_id -or
        [string]$payload.descriptor_sha256 -cne $descriptor.PayloadSha256 -or
        [string]$payload.operation_kind -cne
            [string]$descriptor.Payload.operation_kind -or
        [string]$payload.target_alembic_revision -cne
            [string]$descriptor.Payload.target_alembic_revision -or
        [string]$payload.revision_manifest_sha256 -cne
            [string]$descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.release_fingerprint -cne [string]$receipt.release_fingerprint -or
        [string]$payload.database_binding_sha256 -cne
            [string]$receipt.database_binding_sha256 -or
        [string]$payload.recovery_epoch_id -cne
            [string]$receipt.recovery_epoch_id -or
        $envelope.PayloadSha256 -cne [string]$receipt.freeze_proof_sha256 -or
        [int64]$payload.heartbeat_sequence -ne
            [int64]$receipt.freeze_heartbeat_sequence -or
        [string]$payload.backend_service_state -cne "stopped" -or
        [string]$payload.backend_service_start_policy -cne "disabled" -or
        [int]$payload.backend_service_pid -ne 0 -or
        [int]$payload.backend_listener_pid_count -ne 0 -or
        [int]$payload.runtime_process_count -ne 0 -or
        [int]$payload.database_client_session_count -ne 0 -or
        @($payload.database_client_sessions).Count -ne
            [int]$payload.database_client_session_count -or
        $payload.database_public_connect -isnot [bool] -or
        [bool]$payload.database_public_connect -or
        (
            $payload.database_role_capability_count -isnot [int] -and
            $payload.database_role_capability_count -isnot [long]
        ) -or
        [int64]$payload.database_role_capability_count -lt 2 -or
        @($payload.database_role_capabilities).Count -ne
            [int64]$payload.database_role_capability_count -or
        [string]$payload.database_authority_role -cne "postgres" -or
        [string]$payload.database_authority_scope -cne
            "process_local_secret_same_session_advisory_cut" -or
        [int64]$payload.database_max_prepared_transactions -ne 0 -or
        [int64]$payload.database_prepared_transaction_count -ne 0 -or
        [int64]$payload.database_logical_subscription_count -ne 0 -or
        [int64]$payload.database_logical_apply_worker_count -ne 0 -or
        [int64]$payload.database_unexpected_worker_count -ne 0 -or
        $payload.database_advisory_fence_available -isnot [bool] -or
        -not [bool]$payload.database_advisory_fence_available
    ) {
        throw "C07 writers frozen proof 未证明真实 writer/session/fence 隔离。"
    }
    $proofBinding = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$receipt.operation_id) `
        -Descriptor $descriptor `
        -Sequence ([int]$receipt.freeze_proof_binding_sequence) `
        -ExpectedPayloadSha256 ([string]$payload.coordinator_binding_sha256)
    $proofCoordinator = New-TicketboxC07IdentityFromPayload $payload "coordinator"
    $proofOwner = New-TicketboxC07IdentityFromPayload $payload "lifecycle_owner"
    if (
        -not (
            Test-TicketboxProcessIdentityEquals `
                $proofCoordinator `
                $proofBinding.CoordinatorIdentity
        ) -or
        -not (
            Test-TicketboxProcessIdentityEquals `
                $proofOwner `
                $proofBinding.LifecycleOwnerIdentity
        )
    ) {
        throw "C07 writers frozen proof 未绑定对应 coordinator generation。"
    }
    $intent = Read-TicketboxC07WriterFenceIntent $Authority
    $rolesMatch = if ([bool]$intent.IsLegacyV3) {
        Test-TicketboxC07LegacyV3WriterFenceRoleSetEquals `
            -Left @($intent.Roles) `
            -Right @($payload.database_role_capabilities) `
            -AllowFencedRight
    }
    else {
        Test-TicketboxC07WriterFenceRoleIdentitySetEquals `
            -Left @($intent.Roles) `
            -Right @($payload.database_role_capabilities)
    }
    if (
        [string]$payload.writer_fence_intent_sha256 -cne
            $intent.PayloadSha256 -or
        -not $rolesMatch
    ) {
        throw "C07 writers frozen proof 未绑定 durable writer-fence intent。"
    }
    return $envelope
}

function Read-TicketboxC07ReadyVerification([object]$Authority) {
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path (
            Get-TicketboxC07ReadyVerificationPath (
                [string]$Authority.Receipt.operation_id
            )
        ) `
        -ExpectedKind "ready_verification"
    $payload = $envelope.Payload
    $readySchema = [string]$payload.schema
    $isLegacyV3Ready = (
        $readySchema -ceq $script:TicketboxC07LegacyReadyVerificationSchema
    )
    $expectedReadyNames = @(
        "schema",
        "operation_id",
        "descriptor_sha256",
        "database_binding_sha256",
        "writer_fence_intent_sha256",
        "operation_kind",
        "alembic_target",
        "revision_manifest_sha256",
        "backend_service_state",
        "backend_service_start_policy",
        "backend_service_pid",
        "backend_listener_pid_count",
        "runtime_process_count",
        "database_runtime_session_count",
        "database_client_sessions",
        "database_role_capability_count",
        "database_role_capabilities",
        "database_max_prepared_transactions",
        "database_prepared_transaction_count",
        "database_logical_subscription_count",
        "database_logical_apply_worker_count",
        "database_unexpected_worker_count",
        "database_advisory_fence_available",
        "verified_at_utc"
    )
    if (-not $isLegacyV3Ready) {
        $expectedReadyNames = @(
            $expectedReadyNames[0..4] +
            @(
                "writer_fence_intent_schema",
                "writer_fence_authority_phase"
            ) +
            $expectedReadyNames[5..($expectedReadyNames.Count - 1)]
        )
    }
    Assert-TicketboxC07ExactProperties `
        $payload `
        $expectedReadyNames `
        "ready verification"
    $intent = Read-TicketboxC07WriterFenceIntent $Authority
    $readyRoles = @($payload.database_role_capabilities)
    $rolesMatch = if ($isLegacyV3Ready) {
        [bool]$intent.IsLegacyV3 -and
            (Test-TicketboxC07LegacyV3WriterFenceRoleSetEquals `
                -Left @($intent.Roles) `
                -Right $readyRoles `
                -AllowFencedRight)
    }
    else {
        Assert-TicketboxC07PublishedReadyRoleSet -Roles $readyRoles
        Test-TicketboxC07PublishedReadyRoleIdentityTransition `
            -Intent $intent `
            -ReadyRoles $readyRoles
    }
    if (
        $readySchema -cnotin @(
            $script:TicketboxC07LegacyReadyVerificationSchema,
            $script:TicketboxC07ReadyVerificationSchema
        ) -or
        [string]$payload.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$payload.descriptor_sha256 -cne
            $Authority.Descriptor.PayloadSha256 -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        [string]$payload.writer_fence_intent_sha256 -cne
            $intent.PayloadSha256 -or
        (
            -not $isLegacyV3Ready -and
            (
                [string]$payload.writer_fence_intent_schema -cne
                    [string]$intent.IntentSchema -or
                [string]$payload.writer_fence_authority_phase -cne
                    "published_runtime"
            )
        ) -or
        [string]$payload.operation_kind -cne
            [string]$Authority.Descriptor.Payload.operation_kind -or
        [string]$payload.alembic_target -cne
            [string]$Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.revision_manifest_sha256 -cne
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.backend_service_state -cne "stopped" -or
        [string]$payload.backend_service_start_policy -cne "disabled" -or
        [int]$payload.backend_service_pid -ne 0 -or
        [int]$payload.backend_listener_pid_count -ne 0 -or
        [int]$payload.runtime_process_count -ne 0 -or
        [int]$payload.database_runtime_session_count -ne 0 -or
        @($payload.database_client_sessions).Count -ne 0 -or
        $readyRoles.Count -ne
            [int64]$payload.database_role_capability_count -or
        -not $rolesMatch -or
        [int64]$payload.database_max_prepared_transactions -ne 0 -or
        [int64]$payload.database_prepared_transaction_count -ne 0 -or
        [int64]$payload.database_logical_subscription_count -ne 0 -or
        [int64]$payload.database_logical_apply_worker_count -ne 0 -or
        [int64]$payload.database_unexpected_worker_count -ne 0 -or
        $payload.database_advisory_fence_available -isnot [bool] -or
        -not [bool]$payload.database_advisory_fence_available -or
        $envelope.PayloadSha256 -cne
            [string]$Authority.Receipt.ready_verification_sha256
    ) {
        throw "C07 READY receipt 未绑定受保护二次 live verification。"
    }
    [void](ConvertTo-TicketboxC07CanonicalUtcTimestamp `
        -Value ([string]$payload.verified_at_utc) `
        -Label "C07 READY verified_at_utc")
    $envelope | Add-Member `
        -NotePropertyName ReadySchema `
        -NotePropertyValue $readySchema `
        -Force
    $envelope | Add-Member `
        -NotePropertyName ReadySemantics `
        -NotePropertyValue $(if ($isLegacyV3Ready) {
            "historical_ambiguous"
        } else { "published_runtime" }) `
        -Force
    return $envelope
}

function Read-TicketboxC07StageEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $path = Get-TicketboxC07StageEvidencePath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Stage $Stage
    $envelope = Read-TicketboxC07HostEnvelope -Path $path -ExpectedKind "stage_evidence"
    $payload = $envelope.Payload
    $expectedNames = @(
        "schema",
        "operation_id",
        "target_stage",
        "evidence_type",
        "producer_schema",
        "producer_result",
        "producer_payload_sha256",
        "producer_payload_json",
        "release_fingerprint",
        "database_binding_sha256",
        "recovery_epoch_id",
        "operation_kind",
        "target_alembic_revision",
        "revision_manifest_sha256",
        "source_stage",
        "source_stage_sequence",
        "source_authority_chain_sha256",
        "created_at_utc"
    )
    Assert-TicketboxC07ExactProperties $payload $expectedNames "$Stage stage evidence"
    $contract = $script:TicketboxC07StageEvidenceContracts[$Stage]
    if ($null -eq $contract) {
        throw "C07 $Stage 没有 typed evidence contract。"
    }
    if (
        [string]$payload.schema -cne $script:TicketboxC07StageEvidenceSchema -or
        [string]$payload.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$payload.target_stage -cne $Stage -or
        [string]$payload.evidence_type -cne "$Stage-evidence" -or
        [string]$payload.producer_schema -cne [string]$contract.Schema -or
        [string]$payload.producer_result -cne [string]$contract.Result -or
        [string]$payload.release_fingerprint -cne
            [string]$Authority.Receipt.release_fingerprint -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        [string]$payload.recovery_epoch_id -cne
            [string]$Authority.Receipt.recovery_epoch_id -or
        [string]$payload.operation_kind -cne
            [string]$Authority.Descriptor.Payload.operation_kind -or
        [string]$payload.target_alembic_revision -cne
            [string]$Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.revision_manifest_sha256 -cne
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.source_stage -cnotin
            $script:TicketboxC07OrderedStages -or
        (
            $payload.source_stage_sequence -isnot [int] -and
            $payload.source_stage_sequence -isnot [long]
        )
    ) {
        throw "C07 $Stage typed evidence 未绑定本 operation/authority。"
    }
    Assert-TicketboxC07Sha256 `
        ([string]$payload.producer_payload_sha256) `
        "$Stage producer payload hash"
    if (
        (Get-TicketboxC07TextSha256 ([string]$payload.producer_payload_json)) -cne
        [string]$payload.producer_payload_sha256
    ) {
        throw "C07 $Stage producer payload hash mismatch。"
    }
    try {
        $producer = ConvertFrom-TicketboxC07JsonText `
            -Text ([string]$payload.producer_payload_json) `
            -Label "$Stage producer payload"
    }
    catch { throw "C07 $Stage producer payload 不是 JSON。" }
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
    if ($Stage -ceq "target_committed") {
        $producerProperties += @(
            "migration_evidence_sha256",
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_count",
            "statistics_table_set_sha256"
        )
    }
    Assert-TicketboxC07ExactProperties `
        $producer `
        $producerProperties `
        "$Stage producer evidence"
    if (
        [string]$producer.schema -cne [string]$contract.Schema -or
        [string]$producer.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$producer.result -cne [string]$contract.Result -or
        [string]$producer.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        [string]$producer.operation_kind -cne
            [string]$Authority.Descriptor.Payload.operation_kind -or
        [string]$producer.alembic_target -cne
            [string]$Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$producer.revision_manifest_sha256 -cne
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256
    ) {
        throw "C07 $Stage producer evidence contract 不一致。"
    }
    Assert-TicketboxC07Sha256 ([string]$producer.subject_sha256) "$Stage subject hash"
    if ($Stage -ceq "target_committed") {
        foreach ($field in @(
            "migration_evidence_sha256",
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_set_sha256"
        )) {
            Assert-TicketboxC07Sha256 `
                ([string]$producer.$field) `
                "target committed $field"
        }
        if ([int]$producer.statistics_table_count -ne 18) {
            throw "C07 target committed statistics table count 不完整。"
        }
    }
    Assert-TicketboxC07Sha256 `
        ([string]$payload.source_authority_chain_sha256) `
        "$Stage source authority chain"
    $sourceIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        [string]$payload.source_stage
    )
    if (
        [int64]$payload.source_stage_sequence -ne $sourceIndex -or
        (
            [string]$payload.source_stage -cne $Stage -and
            $sourceIndex + 1 -ne [array]::IndexOf(
                $script:TicketboxC07OrderedStages,
                $Stage
            )
        )
    ) {
        throw "C07 $Stage typed evidence 的 source stage/sequence 不相邻。"
    }
    if ($Stage -in $script:TicketboxC07ProductionGatedStages) {
        $production = Read-TicketboxC07ProductionAuthority $Authority
        if (
            [string]$producer.subject_sha256 -cne
                [string]$production.PayloadSha256
        ) {
            throw "C07 $Stage 未绑定唯一 production authority artifact。"
        }
    }
    return $envelope
}

function Assert-TicketboxC07ProductionCoordinatorResult {
    param(
        [Parameter(Mandatory = $true)][object]$Result,
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][string]$RecoveryManifestSha256
    )
    $resultProperties = @(
            "schema",
            "operation_id",
            "mode",
            "result",
            "recovery_manifest_sha256",
            "recovery_dump_sha256",
            "recovery_inventory_sha256",
            "recovery_copies_sha256",
            "integrity_scope",
            "cluster_system_identifier",
            "database_oid",
            "logical_server_id",
            "data_generation",
            "source_alembic_revision",
            "target_alembic_revision",
            "migration_evidence_sha256",
            "money_facts_sha256",
            "role_authority_sha256",
            "runtime_acl_sha256",
            "legacy_session_count",
            "migrator_session_count",
            "migrator_can_login",
            "migrator_password_present",
            "live_postconditions_sha256"
    )
    $resultProperties += @(
        "resource_shape_sha256",
        "target_restore_evidence_sha256"
    )
    Assert-TicketboxC07ExactProperties `
        $Result `
        $resultProperties `
        "production coordinator result"
    $digestFields = @(
        "recovery_manifest_sha256",
        "recovery_dump_sha256",
        "recovery_inventory_sha256",
        "recovery_copies_sha256",
        "migration_evidence_sha256",
        "money_facts_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "live_postconditions_sha256"
    )
    $digestFields += @(
        "resource_shape_sha256",
        "target_restore_evidence_sha256"
    )
    foreach ($field in $digestFields) {
        Assert-TicketboxC07LowerSha256 `
            ([string]$Result.$field) `
            "production $field"
    }
    $descriptor = $Authority.Descriptor.Payload
    if (
        [string]$Result.schema -cne
            "ticketbox-c07-production-authority-result-v2" -or
        [string]$Result.operation_id -cne
            [string]$Authority.Receipt.operation_id -or
        [string]$Result.mode -cne $Mode -or
        [string]$Result.result -cne "production_authority_ready" -or
        ([string]$Result.recovery_manifest_sha256).ToUpperInvariant() -cne
            $RecoveryManifestSha256 -or
        [string]$Result.integrity_scope -cne "acl_hash_only" -or
        [string]$Result.cluster_system_identifier -cne
            [string]$descriptor.cluster_system_identifier -or
        [string]$Result.database_oid -cne [string]$descriptor.database_oid -or
        [string]$Result.logical_server_id -cne
            [string]$descriptor.logical_server_id -or
        [string]$Result.data_generation -cne
            [string]$descriptor.data_generation -or
        [string]$Result.source_alembic_revision -cne
            [string]$descriptor.source_alembic_revision -or
        [string]$Result.target_alembic_revision -cne
            [string]$descriptor.target_alembic_revision
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 production coordinator result 未绑定 exact target authority。" `
            -FailureClass "invariant" `
            -FailureCode "authority_chain_mismatch")
    }
    if (
        [int64]$Result.legacy_session_count -ne 0 -or
        [int64]$Result.migrator_session_count -ne 0 -or
        $Result.migrator_can_login -isnot [bool] -or
        [bool]$Result.migrator_can_login -or
        $Result.migrator_password_present -isnot [bool] -or
        [bool]$Result.migrator_password_present
    ) {
        throw (New-TicketboxC07ClassifiedFailure `
            -Message "C07 production coordinator result 未证明 exact role authority。" `
            -FailureClass "invariant" `
            -FailureCode "role_authority_invariant_failed")
    }
}

function Read-TicketboxC07ProductionAuthority {
    param([Parameter(Mandatory = $true)][object]$Authority)
    $path = Get-TicketboxC07ProductionAuthorityPath (
        [string]$Authority.Receipt.operation_id
    )
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "production_authority"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "mode",
            "result",
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
            "coordinator_result_sha256",
            "coordinator_result_json",
            "created_at_utc"
        ) `
        "production lifecycle authority"
    foreach ($field in @(
        "release_fingerprint",
        "migration_helper_sha256",
        "database_binding_sha256",
        "revision_manifest_sha256",
        "target_recovery_manifest_sha256",
        "target_restore_evidence_sha256",
        "money_facts_sha256",
        "resource_shape_sha256",
        "root_authority_chain_sha256",
        "target_restore_authority_chain_sha256",
        "target_restore_stage_evidence_sha256",
        "coordinator_binding_sha256",
        "freeze_proof_sha256",
        "coordinator_result_sha256"
    )) {
        Assert-TicketboxC07Sha256 ([string]$payload.$field) "production $field"
    }
    if (-not [string]::IsNullOrEmpty(
        [string]$payload.predecessor_production_authority_sha256
    )) {
        Assert-TicketboxC07Sha256 `
            ([string]$payload.predecessor_production_authority_sha256) `
            "production predecessor authority"
    }
    if (
        [string]$payload.schema -cne $script:TicketboxC07ProductionAuthoritySchema -or
        [string]$payload.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$payload.mode -cnotin @("fresh_install", "legacy_adoption") -or
        [string]$payload.result -cne "production_authority_ready" -or
        [string]$payload.release_fingerprint -cne
            [string]$Authority.Receipt.release_fingerprint -or
        [string]$payload.migration_helper_relative_path -cne
            [string]$Authority.ReleaseIdentity.MigrationHelperRelativePath -or
        [int64]$payload.migration_helper_size -ne
            [int64]$Authority.ReleaseIdentity.MigrationHelperSize -or
        [string]$payload.migration_helper_sha256 -cne
            [string]$Authority.ReleaseIdentity.MigrationHelperSha256 -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        [string]$payload.recovery_epoch_id -cne
            [string]$Authority.Receipt.recovery_epoch_id -or
        [string]$payload.operation_kind -cne
            [string]$Authority.Descriptor.Payload.operation_kind -or
        [string]$payload.source_alembic_revision -cne
            [string]$Authority.Descriptor.Payload.source_alembic_revision -or
        [string]$payload.target_alembic_revision -cne
            [string]$Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.revision_manifest_sha256 -cne
            [string]$Authority.Descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.predecessor_operation_id -cne
            [string]$Authority.Descriptor.Payload.predecessor_operation_id -or
        [string]$payload.predecessor_production_authority_sha256 -cne
            [string]$Authority.Descriptor.Payload.predecessor_production_authority_sha256 -or
        [int64]$payload.target_restore_stage_sequence -ne 7 -or
        [int64]$payload.coordinator_binding_sequence -lt 0 -or
        [int64]$payload.coordinator_binding_sequence -gt
            [int64]$Authority.Receipt.coordinator_binding_sequence -or
        [int64]$payload.heartbeat_sequence -lt 1 -or
        [string]$payload.freeze_proof_sha256 -cne
            [string]$Authority.Receipt.freeze_proof_sha256 -or
        (
            Get-TicketboxC07TextSha256 ([string]$payload.coordinator_result_json)
        ) -cne [string]$payload.coordinator_result_sha256
    ) {
        throw "C07 production lifecycle authority 未绑定 operation/release/database/DDL lineage。"
    }
    try {
        $result = ConvertFrom-TicketboxC07JsonText `
            -Text ([string]$payload.coordinator_result_json) `
            -Label "production coordinator result"
    }
    catch {
        throw "C07 production coordinator result 不是 JSON。"
    }
    Assert-TicketboxC07ProductionCoordinatorResult `
        -Result $result `
        -Authority $Authority `
        -Mode ([string]$payload.mode) `
        -RecoveryManifestSha256 (
            [string]$payload.target_recovery_manifest_sha256
        )
    $resultBindings = [ordered]@{
        recovery_manifest_sha256 = "target_recovery_manifest_sha256"
        target_restore_evidence_sha256 = "target_restore_evidence_sha256"
        money_facts_sha256 = "money_facts_sha256"
        resource_shape_sha256 = "resource_shape_sha256"
    }
    foreach ($resultField in $resultBindings.Keys) {
        $payloadField = [string]$resultBindings[$resultField]
        if (
            ([string]$result.$resultField).ToUpperInvariant() -cne
                [string]$payload.$payloadField
        ) {
            throw "C07 production authority $payloadField 未绑定 coordinator result。"
        }
    }
    $targetRestoreStageEvidence = Read-TicketboxC07StageEvidence `
        -Authority $Authority `
        -Stage "target_isolated_restore_verified"
    if (
        [string]$targetRestoreStageEvidence.PayloadSha256 -cne
            [string]$payload.target_restore_stage_evidence_sha256
    ) {
        throw "C07 production authority 未绑定 target restore stage evidence。"
    }
    Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$payload.operation_id) `
        -Descriptor $Authority.Descriptor `
        -Sequence ([int]$payload.coordinator_binding_sequence) `
        -ExpectedPayloadSha256 ([string]$payload.coordinator_binding_sha256) | Out-Null
    return [pscustomobject]@{
        Path = $path
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
        CoordinatorResult = $result
    }
}

function Read-TicketboxC07FailureEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $path = Get-TicketboxC07StageEvidencePath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -Stage $Stage
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "failure_evidence"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "target_stage",
            "failure_code",
            "release_fingerprint",
            "database_binding_sha256",
            "recovery_epoch_id",
            "created_at_utc"
        ) `
        "$Stage failure evidence"
    if (
        [string]$payload.schema -cne $script:TicketboxC07FailureEvidenceSchema -or
        [string]$payload.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$payload.target_stage -cne $Stage -or
        [string]$payload.failure_code -cne [string]$Authority.Receipt.failure_code -or
        [string]$payload.release_fingerprint -cne
            [string]$Authority.Receipt.release_fingerprint -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        [string]$payload.recovery_epoch_id -cne
            [string]$Authority.Receipt.recovery_epoch_id
    ) {
        throw "C07 failure evidence 未绑定本 operation/authority。"
    }
    return $envelope
}

function Read-TicketboxC07AuthorityCore {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [string]$ExpectedInstallationOperationId = "",
        [switch]$DurableHeartbeatOnly
    )
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path (Get-TicketboxC07AuthorityPath) `
        -ExpectedKind "authority_receipt"
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$envelope.Payload.operation_id
    )
    $pendingPath =
        Get-TicketboxPendingInstallationIdentityPath $DataRoot
    $releaseIdentity = $null
    if (-not [string]::IsNullOrEmpty($ExpectedInstallationOperationId)) {
        $expectedOperationId =
            ([guid]$ExpectedInstallationOperationId).ToString("D")
        if ($operationId -cne $expectedOperationId) {
            throw "C07 authority 与安装事务 operation 不一致。"
        }
        $releaseIdentity = Get-TicketboxC07ReleaseIdentity `
            -DataRoot $DataRoot `
            -ExpectedInstallationOperationId $expectedOperationId
    }
    elseif (Test-Path -LiteralPath $pendingPath) {
        $pending = Read-TicketboxPersistentInstallationIdentity `
            -DataRoot $DataRoot `
            -Pending
        if (
            $pending.State -cne "PENDING" -or
            [bool]$pending.LegacyCompleted -or
            $pending.OperationId -cne $operationId
        ) {
            throw "C07 authority 拒绝误用 foreign/mismatched PENDING identity。"
        }
        $releaseIdentity = Get-TicketboxC07ReleaseIdentity `
            -DataRoot $DataRoot `
            -ExpectedInstallationOperationId $pending.OperationId
        if (
            [string]$envelope.Payload.release_fingerprint -cne
                [string]$releaseIdentity.Fingerprint
        ) {
            throw "C07 authority 与 PENDING release fingerprint 不一致。"
        }
    }
    else {
        $releaseIdentity =
            Get-TicketboxC07ReleaseIdentity -DataRoot $DataRoot
    }
    $roots = Assert-TicketboxC07ArtifactRoots $releaseIdentity
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $roots.HostRoot `
        -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
        -OwnerAccount $script:TicketboxC07HostOwnerAccount
    $recoveryEpoch = Read-TicketboxC07RecoveryEpoch $releaseIdentity
    $descriptor = Read-TicketboxC07Descriptor `
        -OperationId $operationId `
        -ReleaseIdentity $releaseIdentity `
        -RecoveryEpoch $recoveryEpoch
    Assert-TicketboxC07ReceiptShape `
        -Receipt $envelope.Payload `
        -ReleaseIdentity $releaseIdentity `
        -Descriptor $descriptor `
        -RecoveryEpoch $recoveryEpoch
    $binding = Read-TicketboxC07CoordinatorBinding `
        -Receipt $envelope.Payload `
        -Descriptor $descriptor
    $result = [pscustomobject]@{
        ReleaseIdentity = $releaseIdentity
        Roots = $roots
        RecoveryEpoch = $recoveryEpoch
        Envelope = $envelope
        Receipt = $envelope.Payload
        Descriptor = $descriptor
        Binding = $binding
    }
    if (-not $DurableHeartbeatOnly) {
        Assert-TicketboxC07LiveDatabaseBinding `
            -Descriptor $descriptor `
            -Receipt $envelope.Payload `
            -ReleaseIdentity $releaseIdentity | Out-Null
    }
    if (-not [string]::IsNullOrEmpty([string]$envelope.Payload.freeze_proof_sha256)) {
        Read-TicketboxC07FreezeProof -Authority $result | Out-Null
    }
    $stage = [string]$envelope.Payload.stage
    if (
        -not $DurableHeartbeatOnly -and
        $stage -in @("writers_frozen", "recovery_generation_ready")
    ) {
        Assert-TicketboxC07WriterFenceWindow $result
    }
    if ($stage -in $script:TicketboxC07StageEvidenceContracts.Keys) {
        $stageEvidence = Read-TicketboxC07StageEvidence -Authority $result -Stage $stage
        if ($stageEvidence.PayloadSha256 -cne [string]$envelope.Payload.transition_evidence_sha256) {
            throw "C07 当前阶段 typed evidence 与 receipt 不一致。"
        }
    }
    elseif ($stage -in $script:TicketboxC07FailureStages) {
        $failureEvidence = Read-TicketboxC07FailureEvidence -Authority $result -Stage $stage
        if ($failureEvidence.PayloadSha256 -cne [string]$envelope.Payload.transition_evidence_sha256) {
            throw "C07 当前 failure evidence 与 receipt 不一致。"
        }
    }
    if ($stage -eq "ready") {
        $readyVerification = Read-TicketboxC07ReadyVerification $result
        $result | Add-Member `
            -NotePropertyName ReadyVerification `
            -NotePropertyValue $readyVerification
    }
    return $result
}

function Read-TicketboxC07DurableHeartbeatAuthority {
    param([Parameter(Mandatory = $true)][string]$DataRoot)

    # This is deliberately a narrow projection of the same protected
    # production authority reader. It skips only live PostgreSQL/CIM writer
    # probes so a helper process can renew the coordinator lease without
    # inheriting database credentials. All release, ceremony, descriptor,
    # binding, ACL, stage-evidence, and coordinator identities still come from
    # the existing host authority chain; no caller supplies an artifact path.
    return Read-TicketboxC07AuthorityCore `
        -DataRoot $DataRoot `
        -DurableHeartbeatOnly
}

function Assert-TicketboxC07ExternalHeartbeatLease {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$CoordinatorIdentity
    )
    $parentProcessId = Get-TicketboxParentProcessId
    if ([int]$parentProcessId -ne [int]$CoordinatorIdentity.ProcessId) {
        throw "C07 heartbeat helper 不是绑定 coordinator 的直接子进程。"
    }
    if (
        -not (Test-TicketboxProcessIdentityEquals `
            $CoordinatorIdentity `
            $Authority.Binding.CoordinatorIdentity)
    ) {
        throw "C07 heartbeat helper parent 与 operation coordinator binding 不一致。"
    }
    Assert-TicketboxC07LiveProcessIdentity $CoordinatorIdentity

    $ownerPath = Get-TicketboxLifecycleLockOwnerPath
    $ownerKind = Get-TicketboxPathEntryKindNoFollow $ownerPath
    if ($ownerKind -ceq "File") {
        $validatedOwner = Read-TicketboxLifecycleLockOwnerRecord `
            -Path $ownerPath `
            -FullControlAccounts $script:TicketboxC07HostFullControlAccounts `
            -OwnerAccount $script:TicketboxC07HostOwnerAccount
    }
    elseif (
        $ownerKind -ceq "Missing" -and
        (Test-TicketboxProcessIdentityEquals `
            $CoordinatorIdentity `
            $Authority.Binding.LifecycleOwnerIdentity)
    ) {
        # Direct (non-Inno bridge) coordinators own both lock handles in one
        # process and historically have no separate owner artifact. The
        # protected operation binding is therefore the owner record.
        $validatedOwner = $CoordinatorIdentity
    }
    else {
        throw "C07 heartbeat helper 缺少匹配的 primary lock owner identity。"
    }
    Assert-TicketboxC07LiveProcessIdentity $validatedOwner
    Assert-TicketboxLifecycleLockIsHeld (Get-TicketboxLifecycleLockPath)
    Assert-TicketboxLifecycleLockIsHeld (
        Get-TicketboxLifecycleOperationLockPath
    )
    if (
        -not (Test-TicketboxProcessIdentityEquals `
            $validatedOwner `
            $Authority.Binding.LifecycleOwnerIdentity)
    ) {
        throw "C07 heartbeat helper 的 primary owner/operation binding 不一致。"
    }
}

function Read-TicketboxC07HeartbeatForBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$ExpectedBinding,
        [AllowNull()][object]$Envelope
    )
    if ($null -eq $Envelope) {
        $Envelope = Read-TicketboxC07HostEnvelope `
            -Path (
                Get-TicketboxC07HeartbeatPath (
                    [string]$Authority.Receipt.operation_id
                )
            ) `
            -ExpectedKind "heartbeat"
    }
    $payload = $Envelope.Payload
    $expectedNames = @(
        "schema",
        "operation_id",
        "descriptor_sha256",
        "coordinator_binding_sha256",
        "coordinator_binding_sequence",
        "coordinator_pid",
        "coordinator_started_filetime_high",
        "coordinator_started_filetime_low",
        "maintenance_attempt_id",
        "maintenance_attempt_sequence",
        "maintenance_attempt_sha256",
        "maintenance_attempt_failure_sha256",
        "sequence",
        "maintenance_remaining_ceiling_ms",
        "observed_at_utc"
    )
    Assert-TicketboxC07ExactProperties $payload $expectedNames "heartbeat"
    $identity = New-TicketboxC07IdentityFromPayload $payload "coordinator"
    if (
        [string]$payload.schema -cne $script:TicketboxC07HeartbeatSchema -or
        [string]$payload.operation_id -cne [string]$Authority.Receipt.operation_id -or
        [string]$payload.descriptor_sha256 -cne $Authority.Descriptor.PayloadSha256 -or
        [string]$payload.coordinator_binding_sha256 -cne
            $ExpectedBinding.PayloadSha256 -or
        [int64]$payload.coordinator_binding_sequence -ne
            [int64]$ExpectedBinding.Sequence -or
        -not (Test-TicketboxProcessIdentityEquals `
            $identity `
            $ExpectedBinding.CoordinatorIdentity) -or
        $payload.maintenance_attempt_sequence -isnot [int] -and
            $payload.maintenance_attempt_sequence -isnot [long] -or
        [int64]$payload.maintenance_attempt_sequence -lt 0 -or
        ($payload.sequence -isnot [int] -and $payload.sequence -isnot [long]) -or
        [int64]$payload.sequence -lt 0 -or
        (
            $payload.maintenance_remaining_ceiling_ms -isnot [int] -and
            $payload.maintenance_remaining_ceiling_ms -isnot [long]
        ) -or
        [int64]$payload.maintenance_remaining_ceiling_ms -lt 0 -or
        [int64]$payload.maintenance_remaining_ceiling_ms -gt
            ($script:TicketboxC07MaintenanceWindowSeconds * 1000)
    ) {
        throw "C07 heartbeat 与当前 operation binding 不一致。"
    }
    $validatedAttempt = $null
    $attemptSequence = [int64]$payload.maintenance_attempt_sequence
    if ($attemptSequence -eq 0) {
        if (
            -not [string]::IsNullOrEmpty(
                [string]$payload.maintenance_attempt_id
            ) -or
            -not [string]::IsNullOrEmpty(
                [string]$payload.maintenance_attempt_sha256
            ) -or
            -not [string]::IsNullOrEmpty(
                [string]$payload.maintenance_attempt_failure_sha256
            )
        ) {
            throw "C07 initial heartbeat 携带了不可能的 maintenance attempt。"
        }
    }
    else {
        $validatedAttempt = Read-TicketboxC07MaintenanceAttempt `
            -Authority $Authority `
            -AttemptId ([string]$payload.maintenance_attempt_id) `
            -Sequence ([int]$attemptSequence) `
            -ExpectedPayloadSha256 (
                [string]$payload.maintenance_attempt_sha256
            )
        if (
            [string]$validatedAttempt.Payload.attempt_id -cne
                [string]$payload.maintenance_attempt_id
        ) {
            throw "C07 heartbeat maintenance attempt identity 不一致。"
        }
        $failureSha256 =
            [string]$payload.maintenance_attempt_failure_sha256
        if (-not [string]::IsNullOrEmpty($failureSha256)) {
            Read-TicketboxC07MaintenanceAttemptFailure `
                -Authority $Authority `
                -Attempt $validatedAttempt `
                -ExpectedPayloadSha256 $failureSha256 | Out-Null
        }
    }
    Add-Member `
        -InputObject $Envelope `
        -MemberType NoteProperty `
        -Name ValidatedMaintenanceAttempt `
        -Value $validatedAttempt `
        -Force
    return $Envelope
}

function Read-TicketboxC07Heartbeat([object]$Authority) {
    return Read-TicketboxC07HeartbeatForBinding `
        -Authority $Authority `
        -ExpectedBinding $Authority.Binding
}

function Get-TicketboxC07ExpectedAttemptRevisions {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Stage
    )
    $source = [string]$Authority.Descriptor.Payload.source_alembic_revision
    $target = [string]$Authority.Descriptor.Payload.target_alembic_revision
    if ($Stage -in $script:TicketboxC07PreDdlStages) {
        if (
            [string]$Authority.Descriptor.Payload.successor_mode -ceq
                "forward_repair"
        ) {
            return @($target)
        }
        return @($source)
    }
    if ($Stage -ceq "ddl_started") {
        # The durable database marker, not the host receipt alone, decides
        # whether a killed migrator stopped before or after Alembic commit.
        return @($source, $target)
    }
    if ($Stage -in $script:TicketboxC07PostDdlStages) {
        return @($target)
    }
    throw "C07 maintenance attempt 不接受 terminal/unknown source stage。"
}

function New-TicketboxC07ClassifiedFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [Parameter(Mandatory = $true)][ValidateSet("transient", "invariant")]
        [string]$FailureClass,
        [Parameter(Mandatory = $true)][string]$FailureCode,
        [Exception]$InnerException
    )
    if ($FailureCode -cnotmatch "^[a-z0-9_]{1,64}$") {
        throw "C07 classified failure code 无效。"
    }
    $failure = if ($null -eq $InnerException) {
        [InvalidOperationException]::new($Message)
    }
    else {
        [InvalidOperationException]::new($Message, $InnerException)
    }
    $failure.Data["TicketboxC07FailureClass"] = $FailureClass
    $failure.Data["TicketboxC07FailureCode"] = $FailureCode
    return $failure
}

function Read-TicketboxC07MaintenanceAttempt {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [ValidateRange(1, [int]::MaxValue)][int]$Sequence,
        [Parameter(Mandatory = $true)][string]$ExpectedPayloadSha256
    )
    $canonicalAttemptId = ConvertTo-TicketboxC07CanonicalOperationId $AttemptId
    Assert-TicketboxC07Sha256 `
        $ExpectedPayloadSha256 `
        "maintenance attempt hash"
    $path = Get-TicketboxC07MaintenanceAttemptPath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -AttemptId $canonicalAttemptId
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "maintenance_attempt"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "attempt_id",
            "attempt_sequence",
            "source_stage",
            "source_stage_sequence",
            "source_receipt_payload_sha256",
            "source_authority_chain_sha256",
            "previous_heartbeat_payload_sha256",
            "previous_heartbeat_sequence",
            "previous_attempt_id",
            "previous_attempt_sha256",
            "previous_attempt_failure_sha256",
            "release_fingerprint",
            "database_binding_sha256",
            "live_alembic_revision",
            "coordinator_binding_sha256",
            "coordinator_binding_sequence",
            "coordinator_pid",
            "coordinator_started_filetime_high",
            "coordinator_started_filetime_low",
            "maintenance_window_ms",
            "started_tick_count64",
            "started_boot_identity",
            "started_at_utc",
            "deadline_utc"
        ) `
        "maintenance attempt"
    foreach ($field in @(
        "source_receipt_payload_sha256",
        "source_authority_chain_sha256",
        "previous_heartbeat_payload_sha256",
        "release_fingerprint",
        "database_binding_sha256",
        "coordinator_binding_sha256"
    )) {
        Assert-TicketboxC07Sha256 ([string]$payload.$field) "attempt $field"
    }
    foreach ($field in @(
        "previous_attempt_sha256",
        "previous_attempt_failure_sha256"
    )) {
        if (-not [string]::IsNullOrEmpty([string]$payload.$field)) {
            Assert-TicketboxC07Sha256 ([string]$payload.$field) "attempt $field"
        }
    }
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07MaintenanceAttemptSchema -or
        [string]$payload.operation_id -cne
            [string]$Authority.Receipt.operation_id -or
        [string]$payload.attempt_id -cne $canonicalAttemptId -or
        [int64]$payload.attempt_sequence -ne $Sequence -or
        [string]$payload.attempt_id -cne (
            Get-TicketboxC07MaintenanceAttemptId `
                -OperationId ([string]$payload.operation_id) `
                -Sequence $Sequence
        ) -or
        $Sequence -gt $script:TicketboxC07MaximumMaintenanceAttempts -or
        [string]$payload.release_fingerprint -cne
            [string]$Authority.Receipt.release_fingerprint -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        $envelope.PayloadSha256 -cne $ExpectedPayloadSha256 -or
        (
            $payload.previous_heartbeat_sequence -isnot [int] -and
            $payload.previous_heartbeat_sequence -isnot [long]
        ) -or
        [int64]$payload.previous_heartbeat_sequence -lt 0 -or
        [int64]$payload.maintenance_window_ms -ne
            ($script:TicketboxC07MaintenanceWindowSeconds * 1000) -or
        [int64]$payload.started_tick_count64 -lt 0 -or
        [string]::IsNullOrEmpty([string]$payload.started_boot_identity)
    ) {
        throw "C07 maintenance attempt 未绑定 exact operation/release/database。"
    }
    $sourceIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        [string]$payload.source_stage
    )
    $currentAttemptStage = if (
        [string]$Authority.Receipt.stage -in $script:TicketboxC07FailureStages
    ) {
        [string]$Authority.Receipt.previous_stage
    }
    else { [string]$Authority.Receipt.stage }
    $currentIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        $currentAttemptStage
    )
    if (
        $sourceIndex -lt 0 -or
        $sourceIndex -gt $currentIndex -or
        [int64]$payload.source_stage_sequence -ne $sourceIndex
    ) {
        throw "C07 maintenance attempt source stage 不属于当前单调 lineage。"
    }
    if (
        [string]$payload.live_alembic_revision -notin @(
            Get-TicketboxC07ExpectedAttemptRevisions `
                -Authority $Authority `
                -Stage ([string]$payload.source_stage)
        )
    ) {
        throw "C07 maintenance attempt live Alembic revision 不符合 source stage。"
    }
    $binding = Read-TicketboxC07CoordinatorBindingAtSequence `
        -OperationId ([string]$payload.operation_id) `
        -Descriptor $Authority.Descriptor `
        -Sequence ([int]$payload.coordinator_binding_sequence) `
        -ExpectedPayloadSha256 ([string]$payload.coordinator_binding_sha256)
    $attemptCoordinator = New-TicketboxC07IdentityFromPayload `
        $payload `
        "coordinator"
    if (-not (Test-TicketboxProcessIdentityEquals `
        $attemptCoordinator `
        $binding.CoordinatorIdentity)) {
        throw "C07 maintenance attempt coordinator binding 不一致。"
    }
    $started = [DateTimeOffset]::MinValue
    $deadline = [DateTimeOffset]::MinValue
    foreach ($entry in @(
        @([string]$payload.started_at_utc, [ref]$started, "started"),
        @([string]$payload.deadline_utc, [ref]$deadline, "deadline")
    )) {
        if (-not [DateTimeOffset]::TryParseExact(
            [string]$entry[0],
            "o",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            $entry[1]
        ) -or ([DateTimeOffset]$entry[1].Value).Offset -ne [TimeSpan]::Zero) {
            throw "C07 maintenance attempt $($entry[2]) 不是 canonical UTC。"
        }
    }
    if (
        $deadline.UtcDateTime.Ticks -ne
            $started.UtcDateTime.AddSeconds(
                $script:TicketboxC07MaintenanceWindowSeconds
            ).Ticks
    ) {
        throw "C07 maintenance attempt deadline 不等于固定 attempt budget。"
    }
    if ($Sequence -eq 1) {
        if (
            -not [string]::IsNullOrEmpty([string]$payload.previous_attempt_id) -or
            -not [string]::IsNullOrEmpty([string]$payload.previous_attempt_sha256) -or
            -not [string]::IsNullOrEmpty(
                [string]$payload.previous_attempt_failure_sha256
            )
        ) {
            throw "C07 first maintenance attempt 携带 predecessor。"
        }
    }
    else {
        ConvertTo-TicketboxC07CanonicalOperationId `
            ([string]$payload.previous_attempt_id) | Out-Null
        Assert-TicketboxC07Sha256 `
            ([string]$payload.previous_attempt_sha256) `
            "previous attempt hash"
        Assert-TicketboxC07Sha256 `
            ([string]$payload.previous_attempt_failure_sha256) `
            "previous attempt failure hash"
        $previous = Read-TicketboxC07MaintenanceAttempt `
            -Authority $Authority `
            -AttemptId ([string]$payload.previous_attempt_id) `
            -Sequence ($Sequence - 1) `
            -ExpectedPayloadSha256 (
                [string]$payload.previous_attempt_sha256
            )
        Read-TicketboxC07MaintenanceAttemptFailure `
            -Authority $Authority `
            -Attempt $previous `
            -ExpectedPayloadSha256 (
                [string]$payload.previous_attempt_failure_sha256
            ) | Out-Null
    }
    return [pscustomobject]@{
        Path = $path
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
        CoordinatorIdentity = $attemptCoordinator
        StartedAtUtc = $started.UtcDateTime
        DeadlineUtc = $deadline.UtcDateTime
    }
}

function Read-TicketboxC07MaintenanceAttemptFailure {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$Attempt,
        [Parameter(Mandatory = $true)][string]$ExpectedPayloadSha256
    )
    Assert-TicketboxC07Sha256 `
        $ExpectedPayloadSha256 `
        "maintenance attempt failure hash"
    $path = Get-TicketboxC07MaintenanceAttemptFailurePath `
        -OperationId ([string]$Authority.Receipt.operation_id) `
        -AttemptId ([string]$Attempt.Payload.attempt_id)
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "maintenance_attempt_failure"
    $payload = $envelope.Payload
    Assert-TicketboxC07ExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "attempt_id",
            "attempt_sequence",
            "attempt_sha256",
            "failure_class",
            "failure_code",
            "action_kind",
            "failure_message_sha256",
            "failed_stage",
            "failed_stage_sequence",
            "failed_receipt_payload_sha256",
            "failed_authority_chain_sha256",
            "database_binding_sha256",
            "live_alembic_revision",
            "failed_at_utc"
        ) `
        "maintenance attempt failure"
    foreach ($field in @(
        "attempt_sha256",
        "failure_message_sha256",
        "failed_receipt_payload_sha256",
        "failed_authority_chain_sha256",
        "database_binding_sha256"
    )) {
        Assert-TicketboxC07Sha256 ([string]$payload.$field) "failure $field"
    }
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07MaintenanceAttemptFailureSchema -or
        [string]$payload.operation_id -cne
            [string]$Authority.Receipt.operation_id -or
        [string]$payload.attempt_id -cne
            [string]$Attempt.Payload.attempt_id -or
        [int64]$payload.attempt_sequence -ne
            [int64]$Attempt.Payload.attempt_sequence -or
        [string]$payload.attempt_sha256 -cne $Attempt.PayloadSha256 -or
        [string]$payload.failure_class -cne "transient" -or
        [string]$payload.failure_code -cnotmatch "^[a-z0-9_]{1,64}$" -or
        [string]$payload.action_kind -cnotmatch "^[a-z0-9_]{1,64}$" -or
        [string]$payload.database_binding_sha256 -cne
            [string]$Authority.Receipt.database_binding_sha256 -or
        $envelope.PayloadSha256 -cne $ExpectedPayloadSha256
    ) {
        throw "C07 maintenance attempt failure 未绑定 attempt/authority。"
    }
    $failedIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        [string]$payload.failed_stage
    )
    $attemptSourceIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        [string]$Attempt.Payload.source_stage
    )
    $currentAttemptStage = if (
        [string]$Authority.Receipt.stage -in $script:TicketboxC07FailureStages
    ) {
        [string]$Authority.Receipt.previous_stage
    }
    else { [string]$Authority.Receipt.stage }
    $currentIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        $currentAttemptStage
    )
    if (
        $failedIndex -lt $attemptSourceIndex -or
        $failedIndex -gt $currentIndex -or
        [int64]$payload.failed_stage_sequence -ne $failedIndex -or
        [string]$payload.live_alembic_revision -notin @(
            Get-TicketboxC07ExpectedAttemptRevisions `
                -Authority $Authority `
                -Stage ([string]$payload.failed_stage)
        )
    ) {
        throw "C07 maintenance attempt failure stage/revision lineage 无效。"
    }
    if ($failedIndex -eq $currentIndex) {
        $receiptMatched = if (
            [string]$Authority.Receipt.stage -in
                $script:TicketboxC07FailureStages
        ) {
            [string]$payload.failed_receipt_payload_sha256 -ceq
                [string]$Authority.Receipt.previous_receipt_payload_sha256 -and
            [string]$payload.failed_authority_chain_sha256 -ceq
                [string]$Authority.Receipt.previous_authority_chain_sha256
        }
        else {
            [string]$payload.failed_receipt_payload_sha256 -ceq
                [string]$Authority.Envelope.PayloadSha256 -and
            [string]$payload.failed_authority_chain_sha256 -ceq
                [string]$Authority.Receipt.authority_chain_sha256
        }
        if (-not $receiptMatched) {
            $firstTakeoverSequence =
                [int64]$Attempt.Payload.coordinator_binding_sequence + 1
            for (
                $bindingSequence = $firstTakeoverSequence;
                $bindingSequence -le [int64]$Authority.Binding.Sequence;
                $bindingSequence += 1
            ) {
                $binding = Read-TicketboxC07CoordinatorBindingAtSequence `
                    -OperationId ([string]$Authority.Receipt.operation_id) `
                    -Descriptor $Authority.Descriptor `
                    -Sequence ([int]$bindingSequence)
                if (
                    [string]$binding.Payload.resumed_stage -ceq
                        [string]$payload.failed_stage -and
                    [string]$binding.Payload.previous_receipt_payload_sha256 -ceq
                        [string]$payload.failed_receipt_payload_sha256 -and
                    [string]$binding.Payload.previous_authority_chain_sha256 -ceq
                        [string]$payload.failed_authority_chain_sha256
                ) {
                    $receiptMatched = $true
                    break
                }
            }
        }
        if (-not $receiptMatched) {
            throw "C07 maintenance attempt failure 未绑定 exact failed receipt。"
        }
    }
    $failedAt = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParseExact(
        [string]$payload.failed_at_utc,
        "o",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind,
        [ref]$failedAt
    ) -or $failedAt.Offset -ne [TimeSpan]::Zero) {
        throw "C07 maintenance attempt failure timestamp 不是 canonical UTC。"
    }
    return [pscustomobject]@{
        Path = $path
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
    }
}

function Write-TicketboxC07HeartbeatPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [ValidateRange(-1, 1200000)]
        [int64]$MaintenanceRemainingCeilingMilliseconds = -1,
        [AllowNull()][object]$CurrentHeartbeat
    )
    $current = $CurrentHeartbeat
    if ($null -eq $current) {
        $current = Read-TicketboxC07Heartbeat $Authority
    }
    if (
        [string]$current.Payload.operation_id -cne
            [string]$Authority.Receipt.operation_id -or
        [string]$current.Payload.descriptor_sha256 -cne
            [string]$Authority.Descriptor.PayloadSha256 -or
        [string]$current.Payload.coordinator_binding_sha256 -cne
            [string]$Authority.Binding.PayloadSha256 -or
        [int64]$current.Payload.coordinator_binding_sequence -ne
            [int64]$Authority.Binding.Sequence
    ) {
        throw "C07 verified heartbeat snapshot 与 current authority 不一致。"
    }
    $currentSequence = [int64]$current.Payload.sequence
    if ($currentSequence -eq [int64]::MaxValue) {
        throw "C07 heartbeat sequence 已耗尽。"
    }
    $remainingCeiling = [int64]$current.Payload.maintenance_remaining_ceiling_ms
    if (
        $null -ne $script:TicketboxC07ActiveMaintenanceBudget -and
        (
            [string]$script:TicketboxC07ActiveMaintenanceBudget.OperationId -cne
                [string]$Authority.Receipt.operation_id -or
            [string]$script:TicketboxC07ActiveMaintenanceBudget.AttemptId -cne
                [string]$current.Payload.maintenance_attempt_id -or
            [string]$script:TicketboxC07ActiveMaintenanceBudget.AttemptSha256 -cne
                [string]$current.Payload.maintenance_attempt_sha256
        )
    ) {
        throw "C07 active maintenance budget 与 current attempt 不一致。"
    }
    if (
        $MaintenanceRemainingCeilingMilliseconds -lt 0 -and
        $null -ne $script:TicketboxC07ActiveMaintenanceBudget -and
        [string]$script:TicketboxC07ActiveMaintenanceBudget.OperationId -ceq
            [string]$Authority.Receipt.operation_id
    ) {
        $MaintenanceRemainingCeilingMilliseconds =
            Get-TicketboxC07AuthorityBoundDeadlineRemainingMilliseconds `
                -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                -MaximumMilliseconds (
                    $script:TicketboxC07MaintenanceWindowSeconds * 1000
                ) `
                -Label "C07 durable maintenance heartbeat"
    }
    if ($MaintenanceRemainingCeilingMilliseconds -ge 0) {
        $remainingCeiling = [Math]::Min(
            $remainingCeiling,
            $MaintenanceRemainingCeilingMilliseconds
        )
    }
    $identity = $Authority.Binding.CoordinatorIdentity
    $payload = [ordered]@{
        schema = $script:TicketboxC07HeartbeatSchema
        operation_id = [string]$Authority.Receipt.operation_id
        descriptor_sha256 = $Authority.Descriptor.PayloadSha256
        coordinator_binding_sha256 = $Authority.Binding.PayloadSha256
        coordinator_binding_sequence = [int64]$Authority.Binding.Sequence
        coordinator_pid = [int]$identity.ProcessId
        coordinator_started_filetime_high = [uint32]$identity.StartedFileTimeHigh
        coordinator_started_filetime_low = [uint32]$identity.StartedFileTimeLow
        maintenance_attempt_id = [string]$current.Payload.maintenance_attempt_id
        maintenance_attempt_sequence =
            [int64]$current.Payload.maintenance_attempt_sequence
        maintenance_attempt_sha256 =
            [string]$current.Payload.maintenance_attempt_sha256
        maintenance_attempt_failure_sha256 =
            [string]$current.Payload.maintenance_attempt_failure_sha256
        sequence = $currentSequence + 1
        maintenance_remaining_ceiling_ms = [int64]$remainingCeiling
        observed_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $heartbeatPath = Get-TicketboxC07HeartbeatPath (
        [string]$Authority.Receipt.operation_id
    )
    if ((Get-TicketboxPathEntryKindNoFollow $heartbeatPath) -cne "File") {
        throw "C07 heartbeat writer 拒绝创建缺失的 heartbeat。"
    }
    return Write-TicketboxC07HostEnvelope `
        -Path $heartbeatPath `
        -ArtifactKind "heartbeat" `
        -Payload $payload `
        -ReplaceExisting `
        -ExpectedExistingPayloadSha256 ([string]$current.PayloadSha256)
}

function Write-TicketboxC07DurableHeartbeat {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$CoordinatorIdentity,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedDescriptorSha256,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedCoordinatorBindingSha256,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, [int64]::MaxValue)]
        [int64]$ExpectedCoordinatorBindingSequence,
        [Parameter(Mandatory = $true)][string]$ExpectedMaintenanceAttemptId,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedMaintenanceAttemptSha256,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 64)][int64]$ExpectedMaintenanceAttemptSequence,
        [Parameter(Mandatory = $true)][DateTime]$ExpectedDeadlineUtc,
        [ValidateRange(0, 1200000)]
        [Parameter(Mandatory = $true)]
        [int64]$MaintenanceRemainingCeilingMilliseconds
    )
    $authority = Read-TicketboxC07DurableHeartbeatAuthority $DataRoot
    $currentHeartbeat = Read-TicketboxC07Heartbeat $authority
    if (
        [string]$authority.Receipt.operation_id -cne
            $ExpectedOperationId -or
        [string]$authority.Descriptor.PayloadSha256 -cne
            $ExpectedDescriptorSha256 -or
        [string]$authority.Binding.PayloadSha256 -cne
            $ExpectedCoordinatorBindingSha256 -or
        [int64]$authority.Binding.Sequence -ne
            $ExpectedCoordinatorBindingSequence -or
        [string]$currentHeartbeat.Payload.maintenance_attempt_id -cne
            $ExpectedMaintenanceAttemptId -or
        [string]$currentHeartbeat.Payload.maintenance_attempt_sha256 -cne
            $ExpectedMaintenanceAttemptSha256 -or
        [int64]$currentHeartbeat.Payload.maintenance_attempt_sequence -ne
            $ExpectedMaintenanceAttemptSequence -or
        -not [string]::IsNullOrEmpty(
            [string]$currentHeartbeat.Payload.maintenance_attempt_failure_sha256
        )
    ) {
        throw "C07 heartbeat helper descriptor/operation binding 已漂移。"
    }
    Assert-TicketboxC07ExternalHeartbeatLease `
        -Authority $authority `
        -CoordinatorIdentity $CoordinatorIdentity
    if ($ExpectedDeadlineUtc.Kind -eq [DateTimeKind]::Unspecified) {
        throw "C07 heartbeat helper deadline 必须是显式 UTC 时间。"
    }
    $attempt = $currentHeartbeat.ValidatedMaintenanceAttempt
    if ($null -eq $attempt) {
        throw "C07 heartbeat helper 缺少已验证的 maintenance attempt snapshot。"
    }
    if (
        [string]$attempt.Payload.started_boot_identity -cne
            (Get-TicketboxWindowsBootIdentity)
    ) {
        throw "C07 heartbeat helper maintenance attempt 已跨 reboot。"
    }
    $authorityDeadline = [DateTime]$attempt.DeadlineUtc
    if (
        $ExpectedDeadlineUtc.ToUniversalTime().Ticks -ne
            $authorityDeadline.Ticks
    ) {
        throw "C07 heartbeat helper deadline 与 durable descriptor 不一致。"
    }
    $authorityRemaining = [Math]::Min(
        [int64]$currentHeartbeat.Payload.maintenance_remaining_ceiling_ms,
        [int64][Math]::Floor(
            ($authorityDeadline - [DateTime]::UtcNow).TotalMilliseconds
        )
    )
    $effectiveRemaining = [Math]::Min(
        $MaintenanceRemainingCeilingMilliseconds,
        [int64]$authorityRemaining
    )
    if ($effectiveRemaining -lt 1000) {
        throw "C07 heartbeat helper durable maintenance window 已耗尽。"
    }
    # The helper may replace only the already-existing heartbeat belonging to
    # this exact authority. It cannot create a generation, transition stage,
    # alter the descriptor/binding, or choose an artifact path.
    return Write-TicketboxC07HeartbeatPayload `
        -Authority $authority `
        -MaintenanceRemainingCeilingMilliseconds (
            $effectiveRemaining
        ) `
        -CurrentHeartbeat $currentHeartbeat
}
