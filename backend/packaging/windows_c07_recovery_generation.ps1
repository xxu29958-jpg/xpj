#Requires -Version 5.1

<#
.SYNOPSIS
  Host-authoritative, same-generation PostgreSQL and receipt-asset recovery for C07.
.DESCRIPTION
  This file is a library for the Windows C07 coordinator.  It never accepts a
  DATABASE_URL, PGDATA, PostgreSQL port, uploads root, release identity, or
  recovery destination from its caller.  Those values are derived from the
  protected lifecycle authority, TicketboxPg SCM ImagePath/postmaster.pid, and a
  live PostgreSQL connection whose SHOW data_directory/port are cross-checked.

  The caller must already hold the lifecycle lock and have advanced the C07
  operation to writers_frozen.  A completed generation is still only a recovery
  candidate: the coordinator must run the isolated restore/reconcile function
  and then advance the lifecycle state with the returned evidence digest.

  Manifest, create-intent, identity, and restore evidence use ACL plus SHA-256
  for accidental-corruption detection.  They are explicitly acl_hash_only and
  do not claim resistance to a malicious SYSTEM/Administrators writer.

  Dot-source the installation-safety, atomic-artifact, lifecycle-lock, C07
  lifecycle, service/database-safety, and C07 database libraries before
  invoking this file.
#>

$atomicArtifactScript = Join-Path $PSScriptRoot "windows_atomic_artifacts.ps1"
if (-not (Test-Path -LiteralPath $atomicArtifactScript -PathType Leaf)) {
    throw "缺少 Windows atomic-artifact 适配脚本：$atomicArtifactScript"
}
. $atomicArtifactScript

$script:TicketboxC07RecoveryGenerationSchema =
    "ticketbox-c07-recovery-generation-v3"
$script:TicketboxC07RecoveryEnvelopeSchema =
    "ticketbox-c07-recovery-envelope-v1"
$script:TicketboxC07RecoveryCleanupSchema =
    "ticketbox-c07-recovery-cleanup-v1"
$script:TicketboxC07RecoveryRestoreIdentitySchema =
    "ticketbox-c07-recovery-restore-identity-v1"
$script:TicketboxC07RecoveryRestoreCreateIntentSchema =
    "ticketbox-c07-recovery-restore-create-intent-v1"
$script:TicketboxC07RecoveryRestoreEvidenceSchema =
    "ticketbox-c07-isolated-restore-evidence-v2"
$script:TicketboxC07TargetRecoveryGenerationSchema =
    "ticketbox-c07-target-recovery-generation-v2"
$script:TicketboxC07RecoveryUploadRootAuthoritySchema =
    "ticketbox-c07-recovery-upload-root-authority-v1"
$script:TicketboxC07TargetRecoveryRestoreEvidenceSchema =
    "ticketbox-c07-target-isolated-restore-evidence-v1"
$script:TicketboxC07ProductionRecoveryGenerationSchema =
    "ticketbox-c07-production-recovery-generation-v1"
$script:TicketboxC07ProductionTargetRecoveryGenerationSchema =
    "ticketbox-c07-production-target-recovery-generation-v1"
$script:TicketboxC07RecoveryIntegrityScope = "acl_hash_only"
$script:TicketboxC07RecoveryRootLeaf = "recovery-generations"
$script:TicketboxC07RecoveryDatabaseName = "ticketbox"
$script:TicketboxC07RecoverySourceRevision = "20260722_0001"
$script:TicketboxC07RecoveryTargetRevision = "20260729_0001"
$script:TicketboxC07RecoverySnapshotTimeoutMilliseconds = 60000
$script:TicketboxC07RecoverySnapshotStartupGuardMilliseconds = 250
$script:TicketboxC07RecoveryNativeTimeoutMilliseconds = 1200000
$script:TicketboxC07RecoveryMaximumInventoryRows = 2000000
$script:TicketboxC07RecoveryMaximumJsonLineBytes = 8192
$script:TicketboxC07RecoveryMaximumManifestBytes = 1048576
$script:TicketboxC07RecoveryFullControlAccounts = @(
    "SYSTEM",
    "BUILTIN\Administrators"
)
$script:TicketboxC07RecoveryOwnerAccount = "SYSTEM"
function Assert-TicketboxC07RecoveryDependencies {
    $required = @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "Assert-TicketboxC07LiveHostConnection",
        "Assert-TicketboxC07OperationLease",
        "Assert-TicketboxC07RestoreIdentity",
        "Assert-TicketboxExactFileAcl",
        "Assert-TicketboxProtectedDirectoryAcl",
        "ConvertTo-TicketboxCanonicalPath",
        "ConvertTo-TicketboxNativeCommandLineArgument",
        "Copy-TicketboxVerifiedArtifact",
        "Get-TicketboxC07DatabaseIdentity",
        "Get-TicketboxC07RestoreDatabaseName",
        "Get-TicketboxC07RestoreNamespaceDatabases",
        "Get-TicketboxPathEntryKindNoFollow",
        "Get-TicketboxVolumeIdentityForPath",
        "Initialize-TicketboxExactTreeDeleteNativeMethods",
        "Initialize-TicketboxProtectedDirectoryAtomically",
        "Invoke-TicketboxBoundedNativeProcess",
        "Invoke-TicketboxC07Sql",
        "Invoke-TicketboxC07WithPlainSecret",
        "Invoke-TicketboxWithPgPassFile",
        "New-TicketboxC07LocalDatabaseUrl",
        "New-TicketboxC07RestoreDatabase",
        "Assert-TicketboxC07RestoreAttemptNamespace",
        "Read-TicketboxC07Authority",
        "Read-TicketboxC07HostEnvelope",
        "Read-EnvMap",
        "Read-TicketboxProtectedUtf8Artifact",
        "Publish-TicketboxVerifiedArtifactDirectory",
        "Remove-TicketboxC07RestoreDatabaseExact",
        "Remove-TicketboxProtectedUtf8Artifact",
        "Remove-TicketboxTreeExact",
        "Resolve-TicketboxC07DatabaseHostAuthority",
        "Set-TicketboxExactFileAcl",
        "Sync-TicketboxDurableArtifactFile",
        "Test-TicketboxPathEquals",
        "Test-TicketboxPathWithin",
        "Write-TicketboxC07HostEnvelope",
        "Write-TicketboxProtectedUtf8FileDurable"
    )
    foreach ($name in $required) {
        if ($null -eq (Get-Command $name -ErrorAction SilentlyContinue)) {
            throw "C07 recovery-generation 缺少依赖函数：$name"
        }
    }
}

function Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds {
    param(
        [Parameter(Mandatory = $true)][int]$MaximumMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($null -eq $script:TicketboxC07ActiveMaintenanceBudget) {
        return $MaximumMilliseconds
    }
    return Get-TicketboxC07RemainingMaintenanceMilliseconds `
        -Budget $script:TicketboxC07ActiveMaintenanceBudget `
        -MaximumMilliseconds $MaximumMilliseconds `
        -Label $Label
}

function ConvertTo-TicketboxC07RecoveryMaintenanceDeadlineUtc {
    param(
        [Parameter(Mandatory = $true)][string]$Value
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
        throw "C07 recovery maintenance deadline 不是 canonical UTC。"
    }
    return $parsed.UtcDateTime.ToString("o")
}

function ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $parsed = [DateTimeOffset]::MinValue
    if (
        -not [DateTimeOffset]::TryParse(
            $Value,
            [Globalization.CultureInfo]::InvariantCulture,
            (
                [Globalization.DateTimeStyles]::AssumeUniversal -bor
                [Globalization.DateTimeStyles]::AdjustToUniversal
            ),
            [ref]$parsed
        ) -or
        $parsed.Offset -ne [TimeSpan]::Zero
    ) {
        throw "$Label 不是有效 UTC timestamp。"
    }
    return $parsed
}

function Get-TicketboxC07RecoverySnapshotLifetime {
    param(
        [Parameter(Mandatory = $true)][object]$Context
    )
    $deadlineText =
        ConvertTo-TicketboxC07RecoveryMaintenanceDeadlineUtc (
            [string]$Context.MaintenanceDeadlineUtc
        )
    $deadline = [DateTime]::ParseExact(
        $deadlineText,
        "o",
        [Globalization.CultureInfo]::InvariantCulture,
        (
            [Globalization.DateTimeStyles]::AssumeUniversal -bor
            [Globalization.DateTimeStyles]::AdjustToUniversal
        )
    )
    $now = [DateTime]::UtcNow
    $absoluteRemaining = [int64][Math]::Floor(
        ($deadline - $now).TotalMilliseconds
    )
    if ($absoluteRemaining -lt 1000) {
        throw "C07 recovery snapshot maintenance deadline 已耗尽。"
    }
    $maximum = [int][Math]::Min(
        [int64][int]::MaxValue,
        $absoluteRemaining
    )
    $currentRemaining =
        Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
            -MaximumMilliseconds $maximum `
            -Label "C07 snapshot absolute lifetime"
    if ($currentRemaining -lt 1000) {
        throw "C07 recovery snapshot current maintenance ceiling 已耗尽。"
    }
    $effectiveDeadline = $now.AddMilliseconds($currentRemaining)
    if ($effectiveDeadline -gt $deadline) {
        $effectiveDeadline = $deadline
    }
    $effectiveRemaining = [int][Math]::Floor(
        ($effectiveDeadline - [DateTime]::UtcNow).TotalMilliseconds
    )
    if ($effectiveRemaining -lt 1000) {
        throw "C07 recovery snapshot effective deadline 已耗尽。"
    }
    return [pscustomobject]@{
        MaintenanceDeadlineUtc = $effectiveDeadline.ToString("o")
        MaximumRemainingCeilingMilliseconds = $effectiveRemaining
    }
}

function Assert-TicketboxC07RecoveryMaintenanceBoundary {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [object[]]$AllowedClientSessions = @()
    )
    if ($null -eq $script:TicketboxC07ActiveMaintenanceBudget) { return }
    [void](Get-TicketboxC07RemainingMaintenanceMilliseconds `
        -Budget $script:TicketboxC07ActiveMaintenanceBudget `
        -Label "C07 recovery boundary")
    Assert-TicketboxC07WriterFenceWindow `
        -Authority $Authority `
        -AllowedClientSessions @($AllowedClientSessions)
}

function Get-TicketboxC07RecoveryHeartbeatOperation {
    param([Parameter(Mandatory = $true)][object]$Context)
    if ($null -eq $script:TicketboxC07ActiveMaintenanceBudget) {
        throw "C07 native maintenance heartbeat 缺少 active budget。"
    }
    Initialize-TicketboxBoundedNativeProcessMethods
    $dataRoot = [string]$Context.Authority.ReleaseIdentity.DataRoot
    $authority = Read-TicketboxC07Authority $dataRoot
    Assert-TicketboxC07OperationLease `
        -Authority $authority `
        -LifecycleLock $Context.LifecycleLock
    $remaining = Get-TicketboxC07RemainingMaintenanceMilliseconds `
        -Budget $script:TicketboxC07ActiveMaintenanceBudget `
        -Label "C07 native maintenance heartbeat operation"
    $identity = $authority.Binding.CoordinatorIdentity
    $heartbeat = Read-TicketboxC07Heartbeat $authority
    if (
        [int64]$heartbeat.Payload.maintenance_attempt_sequence -lt 1 -or
        -not [string]::IsNullOrEmpty(
            [string]$heartbeat.Payload.maintenance_attempt_failure_sha256
        )
    ) {
        throw "C07 native heartbeat operation 缺少 active maintenance attempt。"
    }
    $deadlineUtc = ([DateTime](
        $script:TicketboxC07ActiveMaintenanceBudget.DeadlineUtc
    )).ToUniversalTime()
    return [TicketboxC07DurableHeartbeatOperation]::new(
        $dataRoot,
        $Context.LifecycleLock,
        [string]$authority.Receipt.operation_id,
        [string]$authority.Descriptor.PayloadSha256,
        [string]$authority.Binding.PayloadSha256,
        [int64]$authority.Binding.Sequence,
        [string]$heartbeat.Payload.maintenance_attempt_id,
        [string]$heartbeat.Payload.maintenance_attempt_sha256,
        [int64]$heartbeat.Payload.maintenance_attempt_sequence,
        [int]$identity.ProcessId,
        [uint32]$identity.StartedFileTimeHigh,
        [uint32]$identity.StartedFileTimeLow,
        $deadlineUtc,
        [int64]$remaining,
        [string[]]$script:TicketboxC07HostFullControlAccounts,
        [string]$script:TicketboxC07HostOwnerAccount,
        [string[]]$script:TicketboxPersistentInstallationIdentityAclAccounts,
        [string]$script:TicketboxPersistentInstallationIdentityOwnerAccount,
        [string](Get-TicketboxLifecycleLockPath),
        [string](Get-TicketboxLifecycleOperationLockPath)
    )
}

function Protect-TicketboxC07RecoveryFile([string]$Path) {
    Set-TicketboxExactFileAcl `
        -Path $Path `
        -Accounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    Assert-TicketboxExactFileAcl `
        -Path $Path `
        -Accounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
}

function Get-TicketboxC07RecoveryTextSha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
        return ([BitConverter]::ToString(
            $sha.ComputeHash($bytes)
        )).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-TicketboxC07RecoveryBytesSha256([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString(
            $sha.ComputeHash($Bytes)
        )).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-TicketboxC07RecoveryFileSha256([string]$Path) {
    $stream = $null
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.FileStream]::new(
            $Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read,
            1048576,
            [IO.FileOptions]::SequentialScan
        )
        return ([BitConverter]::ToString(
            $sha.ComputeHash($stream)
        )).Replace("-", "").ToLowerInvariant()
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        $sha.Dispose()
    }
}

function Assert-TicketboxC07RecoverySha256 {
    param(
        [AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch "^[0-9a-f]{64}$") {
        throw "$Label 不是 canonical lowercase SHA-256。"
    }
}

function Assert-TicketboxC07RecoveryHostSha256 {
    param(
        [AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch "^[0-9A-F]{64}$") {
        throw "$Label 不是 host canonical uppercase SHA-256。"
    }
}

function Assert-TicketboxC07RecoveryExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if (
        $actual.Count -ne $wanted.Count -or
        [string]::Join("`n", $actual) -cne [string]::Join("`n", $wanted)
    ) {
        throw "$Label 属性集合不符合冻结 schema。"
    }
}

function ConvertFrom-TicketboxC07RecoveryJson {
    param(
        [Parameter(Mandatory = $true)][string]$Text
    )
    $parameters = @{
        InputObject = $Text
        ErrorAction = "Stop"
    }
    $convertFromJson = Get-Command `
        -Name "ConvertFrom-Json" `
        -CommandType Cmdlet `
        -ErrorAction Stop
    if ($convertFromJson.Parameters.ContainsKey("DateKind")) {
        $parameters["DateKind"] = "String"
    }
    return ConvertFrom-Json @parameters
}

function ConvertTo-TicketboxC07CanonicalOperationId([string]$OperationId) {
    $parsed = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($OperationId, "D", [ref]$parsed) -or
        $parsed -eq [Guid]::Empty
    ) {
        throw "C07 recovery operation ID 必须是非空 canonical GUID。"
    }
    $canonical = $parsed.ToString("D")
    if ($canonical -cne $OperationId) {
        throw "C07 recovery operation ID 不是 canonical lowercase GUID。"
    }
    return $canonical
}

function Assert-TicketboxC07RecoveryCanonicalGuid {
    param(
        [AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $parsed = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($Value, "D", [ref]$parsed) -or
        $parsed -eq [Guid]::Empty -or
        $parsed.ToString("D") -cne $Value
    ) {
        throw "$Label 不是 canonical non-empty UUID。"
    }
}

function Get-TicketboxC07RecoveryPaths {
    param(
        [Parameter(Mandatory = $true)][object]$Authority
    )
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Authority.Receipt.operation_id
    )
    $hostRoot = ConvertTo-TicketboxCanonicalPath $Authority.Roots.HostRoot
    $generationRoot = ConvertTo-TicketboxCanonicalPath (
        Join-Path $hostRoot $script:TicketboxC07RecoveryRootLeaf
    )
    if (
        -not (Test-TicketboxPathWithin $generationRoot $hostRoot) -or
        (Test-TicketboxPathEquals $generationRoot $hostRoot)
    ) {
        throw "C07 recovery generation root 越出受保护 lifecycle authority。"
    }
    $leaf = "operation-$operationId"
    return [pscustomobject]@{
        HostRoot = $hostRoot
        GenerationRoot = $generationRoot
        PartialRoot = Join-Path $generationRoot "$leaf.partial"
        ReadyRoot = Join-Path $generationRoot "$leaf.ready"
        RestoreAssetsRoot = Join-Path `
            $generationRoot `
            "$leaf-isolated-assets.partial"
        RestoreIdentityPath = Join-Path `
            $generationRoot `
            "$leaf-restore-identity.json"
        RestoreCreateIntentPath = Join-Path `
            $generationRoot `
            "$leaf-restore-create-intent.json"
        RestoreEvidencePath = Join-Path `
            (Join-Path $generationRoot "$leaf.ready") `
            "isolated-restore-evidence.json"
        CleanupPath = Join-Path $generationRoot "$leaf-cleanup.json"
        TargetPartialRoot = Join-Path $generationRoot "$leaf-target.partial"
        TargetReadyRoot = Join-Path $generationRoot "$leaf-target.ready"
        TargetRestoreAssetsRoot = Join-Path `
            $generationRoot `
            "$leaf-target-isolated-assets.partial"
        TargetRestoreIdentityPath = Join-Path `
            $generationRoot `
            "$leaf-target-restore-identity.json"
        TargetRestoreCreateIntentPath = Join-Path `
            $generationRoot `
            "$leaf-target-restore-create-intent.json"
        TargetRestoreEvidencePath = Join-Path `
            (Join-Path $generationRoot "$leaf-target.ready") `
            "target-isolated-restore-evidence.json"
        TargetCleanupPath = Join-Path `
            $generationRoot `
            "$leaf-target-cleanup.json"
        ManifestFileName = "manifest.json"
        InventoryFileName = "asset-inventory.jsonl"
        CopiesFileName = "asset-copies.jsonl"
        DumpFileName = "database.dump"
        AssetsLeaf = "assets"
    }
}

function Initialize-TicketboxC07RecoveryGenerationRoot {
    param([Parameter(Mandatory = $true)][object]$Paths)

    Assert-NoTicketboxAncestorReparsePoints $Paths.HostRoot
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $Paths.HostRoot `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $Paths.GenerationRoot `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
    return $Paths.GenerationRoot
}

function ConvertFrom-TicketboxC07RecoveryDotEnvPathValue {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    $candidate = $Value.Trim()
    if ($candidate.Length -ge 2) {
        $first = $candidate[0]
        $last = $candidate[$candidate.Length - 1]
        if (
            ($first -eq [char]0x27 -and $last -eq [char]0x27) -or
            ($first -eq [char]0x22 -and $last -eq [char]0x22)
        ) {
            $candidate = $candidate.Substring(1, $candidate.Length - 2)
        }
        elseif (
            $first -in @([char]0x27, [char]0x22) -or
            $last -in @([char]0x27, [char]0x22)
        ) {
            throw "C07 recovery UPLOAD_DIR 引号不完整。"
        }
    }
    if ($candidate -match '[\x00-\x1f\x7f]') {
        throw "C07 recovery UPLOAD_DIR 含非法控制字符。"
    }
    return $candidate
}

function Resolve-TicketboxC07RecoveryConfiguredUploadRoot {
    param([Parameter(Mandatory = $true)][object]$Authority)

    $dataRoot = ConvertTo-TicketboxCanonicalPath (
        [string]$Authority.ReleaseIdentity.DataRoot
    )
    $appRoot = ConvertTo-TicketboxCanonicalPath (Join-Path $dataRoot "app")
    if (-not (Test-TicketboxPathWithin $appRoot $dataRoot)) {
        throw "C07 recovery app root 越出受保护 DataRoot。"
    }
    Assert-NoTicketboxAncestorReparsePoints $appRoot
    if ((Get-TicketboxPathEntryKindNoFollow $appRoot) -cne "Directory") {
        throw "C07 recovery app root 缺失或不是普通目录。"
    }

    $envPath = ConvertTo-TicketboxCanonicalPath (Join-Path $appRoot ".env")
    $envKind = Get-TicketboxPathEntryKindNoFollow $envPath
    if ($envKind -cne "Missing" -and $envKind -cne "File") {
        throw "C07 recovery .env 不是 missing/plain-file。"
    }
    $configured = "uploads"
    if ($envKind -ceq "File") {
        Assert-NoTicketboxAncestorReparsePoints $envPath
        $environment = Read-EnvMap $envPath
        if ($environment.ContainsKey("UPLOAD_DIR")) {
            $configured = ConvertFrom-TicketboxC07RecoveryDotEnvPathValue (
                [string]$environment["UPLOAD_DIR"]
            )
        }
    }
    $candidate = if ([IO.Path]::IsPathRooted($configured)) {
        $configured
    }
    else {
        Join-Path $appRoot $configured
    }
    $uploadRoot = ConvertTo-TicketboxCanonicalPath $candidate
    Assert-NoTicketboxAncestorReparsePoints $uploadRoot
    if ((Get-TicketboxPathEntryKindNoFollow $uploadRoot) -cne "Directory") {
        throw "C07 recovery configured uploads root 缺失或不是普通目录。"
    }
    return $uploadRoot
}

function Get-TicketboxC07RecoveryUploadRootIdentity {
    param([Parameter(Mandatory = $true)][string]$UploadRoot)

    Initialize-TicketboxExactTreeDeleteNativeMethods
    $identity = @(
        [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity(
            (ConvertTo-TicketboxCanonicalPath $UploadRoot)
        )
    )
    if (
        $identity.Count -ne 2 -or
        [string]$identity[0] -cnotmatch '^[0-9A-F]{16}$' -or
        [string]$identity[1] -cnotmatch '^[0-9A-F]{32}$'
    ) {
        throw "C07 recovery uploads root directory identity 无效。"
    }
    return [pscustomobject][ordered]@{
        VolumeSerial = [string]$identity[0]
        FileId = [string]$identity[1]
    }
}

function Get-TicketboxC07RecoveryUploadRootBindingSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$ReleaseFingerprint,
        [Parameter(Mandatory = $true)][string]$UploadRoot,
        [Parameter(Mandatory = $true)][object]$DirectoryIdentity
    )

    $canonicalOperationId = ([guid]$OperationId).ToString("D")
    Assert-TicketboxC07RecoveryHostSha256 `
        $ReleaseFingerprint `
        "C07 recovery upload-root release fingerprint"
    $canonicalFingerprint = $ReleaseFingerprint.ToUpperInvariant()
    $volumeSerial = ([string]$DirectoryIdentity.VolumeSerial).ToUpperInvariant()
    $fileId = ([string]$DirectoryIdentity.FileId).ToUpperInvariant()
    if (
        $volumeSerial -cnotmatch '^[0-9A-F]{16}$' -or
        $fileId -cnotmatch '^[0-9A-F]{32}$'
    ) {
        throw "C07 recovery uploads root directory identity 无效。"
    }
    $text = [string]::Join("`n", @(
        "schema=$script:TicketboxC07RecoveryUploadRootAuthoritySchema",
        "operation_id=$canonicalOperationId",
        "release_fingerprint=$canonicalFingerprint",
        "upload_root=$((ConvertTo-TicketboxCanonicalPath $UploadRoot).ToUpperInvariant())",
        "volume_serial=$volumeSerial",
        "file_id=$fileId"
    )) + "`n"
    return Get-TicketboxC07RecoveryTextSha256 $text
}

function Get-TicketboxC07RecoveryUploadRootAuthorityPath {
    param([Parameter(Mandatory = $true)][object]$Authority)

    $operationId = ([guid][string]$Authority.Receipt.operation_id).ToString("D")
    return Join-Path `
        ([string]$Authority.Roots.HostRoot) `
        "operation-$operationId-recovery-upload-root-authority.json"
}

function Read-TicketboxC07RecoveryUploadRootAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [string]$ExpectedConfiguredRoot = ""
    )

    $path = Get-TicketboxC07RecoveryUploadRootAuthorityPath $Authority
    $envelope = Read-TicketboxC07HostEnvelope `
        -Path $path `
        -ExpectedKind "recovery_upload_root_authority"
    $payload = $envelope.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "release_fingerprint",
            "upload_root",
            "upload_root_volume_serial",
            "upload_root_file_id",
            "upload_root_binding_sha256"
        ) `
        "C07 recovery upload-root authority"
    $uploadRoot = ConvertTo-TicketboxCanonicalPath ([string]$payload.upload_root)
    $identity = Get-TicketboxC07RecoveryUploadRootIdentity $uploadRoot
    $expectedBinding = Get-TicketboxC07RecoveryUploadRootBindingSha256 `
        -OperationId ([string]$payload.operation_id) `
        -ReleaseFingerprint ([string]$payload.release_fingerprint) `
        -UploadRoot $uploadRoot `
        -DirectoryIdentity $identity
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryUploadRootAuthoritySchema -or
        [string]$payload.operation_id -cne
            [string]$Authority.Receipt.operation_id -or
        [string]$payload.release_fingerprint -cne
            [string]$Authority.ReleaseIdentity.Fingerprint -or
        [string]$payload.upload_root -cne $uploadRoot -or
        [string]$payload.upload_root_volume_serial -cne
            [string]$identity.VolumeSerial -or
        [string]$payload.upload_root_file_id -cne [string]$identity.FileId -or
        [string]$payload.upload_root_binding_sha256 -cne $expectedBinding -or
        (
            -not [string]::IsNullOrEmpty($ExpectedConfiguredRoot) -and
            -not (Test-TicketboxPathEquals $uploadRoot $ExpectedConfiguredRoot)
        )
    ) {
        throw "C07 recovery configured upload-root authority 已漂移。"
    }
    return [pscustomobject][ordered]@{
        Path = $path
        Root = $uploadRoot
        VolumeSerial = [string]$identity.VolumeSerial
        FileId = [string]$identity.FileId
        BindingSha256 = $expectedBinding
        Envelope = $envelope
    }
}

function Get-OrCreateTicketboxC07RecoveryUploadRootAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )

    Assert-TicketboxC07OperationLease $Authority $LifecycleLock
    $configuredRoot = Resolve-TicketboxC07RecoveryConfiguredUploadRoot $Authority
    $path = Get-TicketboxC07RecoveryUploadRootAuthorityPath $Authority
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -cne "Missing" -and $kind -cne "File") {
        throw "C07 recovery upload-root authority 路径不是 missing/plain-file。"
    }
    if ($kind -ceq "Missing") {
        $identity = Get-TicketboxC07RecoveryUploadRootIdentity $configuredRoot
        $binding = Get-TicketboxC07RecoveryUploadRootBindingSha256 `
            -OperationId ([string]$Authority.Receipt.operation_id) `
            -ReleaseFingerprint ([string]$Authority.ReleaseIdentity.Fingerprint) `
            -UploadRoot $configuredRoot `
            -DirectoryIdentity $identity
        $payload = [ordered]@{
            schema = $script:TicketboxC07RecoveryUploadRootAuthoritySchema
            operation_id = [string]$Authority.Receipt.operation_id
            release_fingerprint = [string]$Authority.ReleaseIdentity.Fingerprint
            upload_root = $configuredRoot
            upload_root_volume_serial = [string]$identity.VolumeSerial
            upload_root_file_id = [string]$identity.FileId
            upload_root_binding_sha256 = $binding
        }
        Write-TicketboxC07HostEnvelope `
            -Path $path `
            -ArtifactKind "recovery_upload_root_authority" `
            -Payload $payload | Out-Null
    }
    return Read-TicketboxC07RecoveryUploadRootAuthority `
        -Authority $Authority `
        -ExpectedConfiguredRoot $configuredRoot
}

function Get-TicketboxC07RecoveryContext {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [string[]]$AllowedStages = @("writers_frozen")
    )
    Assert-TicketboxC07RecoveryDependencies
    if ($null -eq $SuperuserPassword -or $SuperuserPassword.Length -lt 32) {
        throw "C07 recovery PostgreSQL authority 缺失或不足 32 个字符。"
    }
    $authority = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $authority $LifecycleLock
    $stage = [string]$authority.Receipt.stage
    if ($stage -cnotin $AllowedStages) {
        throw (
            "C07 recovery-generation 只允许在受控阶段运行；当前为 " +
            "$stage。"
        )
    }
    if (
        [string]::IsNullOrEmpty(
            [string]$authority.Receipt.freeze_proof_sha256
        )
    ) {
        throw "C07 recovery-generation 缺少受保护 writers-frozen proof。"
    }
    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$authority.Receipt.freeze_proof_sha256) `
        "C07 writers-frozen proof"

    $databaseAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    if (
        [string]$databaseAuthority.Schema -cne
        "ticketbox-c07-host-db-authority-v1"
    ) {
        throw "C07 PostgreSQL host authority schema 无效。"
    }
    Assert-TicketboxC07LiveHostConnection `
        $databaseAuthority `
        $SuperuserPassword
    $databaseIdentity = Get-TicketboxC07DatabaseIdentity `
        -Authority $databaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07RecoveryDatabaseName
    if (-not $databaseIdentity.Exists) {
        throw "C07 recovery source database 不存在。"
    }

    $pgBin = Split-Path -Parent $databaseAuthority.PsqlPath
    $pgDump = Join-Path $pgBin "pg_dump.exe"
    $pgRestore = Join-Path $pgBin "pg_restore.exe"
    foreach ($tool in @($pgDump, $pgRestore)) {
        Assert-NoTicketboxAncestorReparsePoints $tool
        if ((Get-TicketboxPathEntryKindNoFollow $tool) -cne "File") {
            throw "C07 recovery 受管 PostgreSQL tool 缺失或不是普通文件。"
        }
    }
    $uploadRootAuthority =
        Get-OrCreateTicketboxC07RecoveryUploadRootAuthority `
            -Authority $authority `
            -LifecycleLock $LifecycleLock
    $paths = Get-TicketboxC07RecoveryPaths $authority
    $capturedUtc = [DateTime]::ParseExact(
        [string]$authority.Descriptor.Payload.captured_at_utc,
        "o",
        [Globalization.CultureInfo]::InvariantCulture,
        (
            [Globalization.DateTimeStyles]::AssumeUniversal -bor
            [Globalization.DateTimeStyles]::AdjustToUniversal
        )
    )
    $maintenanceDeadlineUtc = $capturedUtc.AddMilliseconds(
        [int64]$authority.Descriptor.Payload.maintenance_window_ms
    ).ToString("o")
    return [pscustomobject]@{
        Authority = $authority
        LifecycleLock = $LifecycleLock
        MaintenanceDeadlineUtc = $maintenanceDeadlineUtc
        DatabaseAuthority = $databaseAuthority
        DatabaseIdentity = $databaseIdentity
        DatabaseUrl = New-TicketboxC07LocalDatabaseUrl `
            -Authority $databaseAuthority `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -Role "postgres"
        PgDumpPath = $pgDump
        PgRestorePath = $pgRestore
        UploadRoot = [string]$uploadRootAuthority.Root
        UploadRootBindingSha256 =
            [string]$uploadRootAuthority.BindingSha256
        Paths = $paths
    }
}

function Get-TicketboxC07TargetRecoveryContext {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [string[]]$AllowedStages = @(
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified"
        )
    )
    $context = Get-TicketboxC07RecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages $AllowedStages
    $sourcePaths = $context.Paths
    $targetPaths = [pscustomobject]@{
        HostRoot = $sourcePaths.HostRoot
        GenerationRoot = $sourcePaths.GenerationRoot
        PartialRoot = $sourcePaths.TargetPartialRoot
        ReadyRoot = $sourcePaths.TargetReadyRoot
        RestoreAssetsRoot = $sourcePaths.TargetRestoreAssetsRoot
        RestoreIdentityPath = $sourcePaths.TargetRestoreIdentityPath
        RestoreCreateIntentPath = $sourcePaths.TargetRestoreCreateIntentPath
        RestoreEvidencePath = $sourcePaths.TargetRestoreEvidencePath
        CleanupPath = $sourcePaths.TargetCleanupPath
        ManifestFileName = $sourcePaths.ManifestFileName
        InventoryFileName = $sourcePaths.InventoryFileName
        CopiesFileName = $sourcePaths.CopiesFileName
        DumpFileName = $sourcePaths.DumpFileName
        AssetsLeaf = $sourcePaths.AssetsLeaf
    }
    $targetContext = $context.PSObject.Copy()
    $targetContext.Paths = $targetPaths
    return $targetContext
}

function Resolve-TicketboxC07RecoveryAssetReference {
    param(
        [Parameter(Mandatory = $true)][string]$Reference,
        [Parameter(Mandatory = $true)][string]$LedgerId,
        [Parameter(Mandatory = $true)][string]$UploadRoot,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$AllowMissing
    )
    if ($LedgerId -cnotmatch "^[A-Za-z0-9_-]{1,64}$") {
        throw "$Label 的 ledger identity 无效。"
    }
    if (
        [string]::IsNullOrWhiteSpace($Reference) -or
        $Reference.Length -gt 500 -or
        $Reference -match "[\x00-\x1f\x7f]" -or
        $Reference.StartsWith("/") -or
        $Reference.StartsWith("\") -or
        $Reference -match "^[A-Za-z]:" -or
        $Reference.Contains(":")
    ) {
        throw "$Label 不是受支持的相对 upload reference。"
    }
    $normalized = $Reference.Replace("\", "/")
    $parts = @($normalized.Split("/"))
    if (
        $parts.Count -lt 3 -or
        $parts[0] -cne "uploads" -or
        @($parts | Where-Object {
            [string]::IsNullOrEmpty($_) -or $_ -in @(".", "..")
        }).Count -gt 0
    ) {
        throw "$Label 不符合 uploads 相对路径合同。"
    }
    $tail = @($parts[1..($parts.Count - 1)])
    $scoped = $tail[0] -ceq $LedgerId
    $legacy = (
        $LedgerId -ceq "owner" -and
        $tail.Count -ge 3 -and
        $tail[0] -cmatch "^[0-9]{4}$" -and
        $tail[1] -cmatch "^(0[1-9]|1[0-2])$"
    )
    if (-not $scoped -and -not $legacy) {
        throw "$Label 与 PostgreSQL ledger owner 不一致。"
    }

    $relativeTail = [IO.Path]::Combine([string[]]$tail)
    $candidate = ConvertTo-TicketboxCanonicalPath (
        Join-Path $UploadRoot $relativeTail
    )
    if (
        -not (Test-TicketboxPathWithin $candidate $UploadRoot) -or
        (Test-TicketboxPathEquals $candidate $UploadRoot)
    ) {
        throw "$Label 越出受保护 uploads root。"
    }
    Assert-NoTicketboxAncestorReparsePoints $candidate
    $kind = Get-TicketboxPathEntryKindNoFollow $candidate
    if ($kind -cne "File" -and -not ($AllowMissing -and $kind -ceq "Missing")) {
        throw "$Label 缺失、不是普通文件或经过 reparse point。"
    }
    $extension = [IO.Path]::GetExtension($candidate).ToLowerInvariant()
    if ($extension -cnotin @(".jpg", ".jpeg", ".png", ".webp", ".heic")) {
        throw "$Label 使用未知或不受支持的图片扩展名。"
    }
    return [pscustomobject]@{
        Reference = $normalized
        Path = $candidate
        Kind = $kind
        Legacy = [bool]$legacy
    }
}

function ConvertTo-TicketboxC07AssetInventoryRecord {
    param([Parameter(Mandatory = $true)][object]$Row)
    Assert-TicketboxC07RecoveryExactProperties `
        $Row `
        @(
            "expense_public_id",
            "ledger_id",
            "image_reference",
            "image_sha256",
            "image_deleted",
            "thumbnail_reference",
            "thumbnail_deleted"
        ) `
        "C07 recovery asset inventory record"
    foreach ($field in @(
        "expense_public_id",
        "ledger_id",
        "image_reference",
        "image_sha256",
        "thumbnail_reference"
    )) {
        if ($Row.$field -isnot [string]) {
            throw "C07 recovery asset inventory 的 $field 类型无效。"
        }
    }
    foreach ($field in @("image_deleted", "thumbnail_deleted")) {
        if ($Row.$field -isnot [bool]) {
            throw "C07 recovery asset inventory 的 $field 类型无效。"
        }
    }
    $publicId = [string]$Row.expense_public_id
    $parsed = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($publicId, "D", [ref]$parsed) -or
        $parsed.ToString("D") -cne $publicId
    ) {
        throw "C07 recovery asset inventory 含无效 expense public ID。"
    }
    $ledger = [string]$Row.ledger_id
    if ($ledger -cnotmatch "^[A-Za-z0-9_-]{1,64}$") {
        throw "C07 recovery asset inventory 含无效 ledger ID。"
    }
    $imageHash = [string]$Row.image_sha256
    if (-not [string]::IsNullOrEmpty($imageHash)) {
        $imageHash = $imageHash.ToLowerInvariant()
        Assert-TicketboxC07RecoverySha256 $imageHash "Expense.image_hash"
    }
    if (
        -not [bool]$Row.image_deleted -and
        -not [string]::IsNullOrEmpty([string]$Row.image_reference) -and
        [string]::IsNullOrEmpty($imageHash)
    ) {
        throw "PostgreSQL 引用的 active 原图缺少权威 SHA-256；拒绝把磁盘现状升级为恢复事实。"
    }
    return [pscustomobject][ordered]@{
        expense_public_id = $publicId
        ledger_id = $ledger
        image_reference = [string]$Row.image_reference
        image_sha256 = $imageHash
        image_deleted = [bool]$Row.image_deleted
        thumbnail_reference = [string]$Row.thumbnail_reference
        thumbnail_deleted = [bool]$Row.thumbnail_deleted
    }
}

function Get-TicketboxC07RecoveryAssetSourcePlan {
    param(
        [Parameter(Mandatory = $true)][object[]]$Inventory,
        [Parameter(Mandatory = $true)][string]$UploadRoot
    )
    $records = New-Object System.Collections.Generic.List[object]
    $originals = New-Object System.Collections.Generic.List[object]
    [decimal]$sourceBytes = 0
    $position = 0
    foreach ($raw in @($Inventory)) {
        $record = ConvertTo-TicketboxC07AssetInventoryRecord $raw
        $records.Add($record)
        $imageReference = [string]$record.image_reference
        $thumbnailReference = [string]$record.thumbnail_reference
        $imageResolution = $null
        $thumbnailResolution = $null
        if (-not [string]::IsNullOrEmpty($imageReference)) {
            $imageResolution = Resolve-TicketboxC07RecoveryAssetReference `
                -Reference $imageReference `
                -LedgerId ([string]$record.ledger_id) `
                -UploadRoot $UploadRoot `
                -Label "Expense.image_path" `
                -AllowMissing:([bool]$record.image_deleted)
        }
        if (-not [string]::IsNullOrEmpty($thumbnailReference)) {
            $thumbnailResolution = Resolve-TicketboxC07RecoveryAssetReference `
                -Reference $thumbnailReference `
                -LedgerId ([string]$record.ledger_id) `
                -UploadRoot $UploadRoot `
                -Label "Expense.thumbnail_path" `
                -AllowMissing
        }
        if (
            -not [bool]$record.image_deleted -and
            -not [string]::IsNullOrEmpty($imageReference)
        ) {
            if ($null -eq $imageResolution -or $imageResolution.Kind -cne "File") {
                throw "PostgreSQL 引用的 active 原图缺失；拒绝生成 recovery READY。"
            }
            $position++
            $file = Get-Item -LiteralPath $imageResolution.Path -Force
            if ($file.PSIsContainer -or $file.Length -le 0) {
                throw "PostgreSQL 引用的 active 原图不是普通有界文件。"
            }
            $sourceBytes += [decimal]$file.Length
            $thumbnailState = "absent"
            if ($null -ne $thumbnailResolution) {
                if ([bool]$record.thumbnail_deleted) {
                    $thumbnailState = "deleted_derived_cache"
                }
                elseif ($thumbnailResolution.Kind -ceq "File") {
                    $thumbnailState = "present_derived_cache"
                }
                else {
                    $thumbnailState = "missing_rebuildable_cache"
                }
            }
            $originals.Add([pscustomobject]@{
                Position = $position
                Record = $record
                SourcePath = [string]$imageResolution.Path
                ExpectedLength = [int64]$file.Length
                PackageFile = "asset-{0:d8}.bin" -f $position
                ThumbnailState = $thumbnailState
            })
        }
    }
    if ($sourceBytes -gt [decimal][int64]::MaxValue) {
        throw "C07 recovery asset bytes 超出本机可表示容量。"
    }
    return [pscustomobject]@{
        Inventory = $records.ToArray()
        Originals = $originals.ToArray()
        SourceBytes = [int64]$sourceBytes
    }
}

function ConvertFrom-TicketboxC07RecoveryBase64Json {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (
        [string]::IsNullOrEmpty($Text) -or
        $Text.Length -gt ($script:TicketboxC07RecoveryMaximumJsonLineBytes * 2) -or
        $Text -cnotmatch "^[A-Za-z0-9+/]+={0,2}$"
    ) {
        throw "$Label 的 base64 envelope 无效。"
    }
    try {
        $bytes = [Convert]::FromBase64String($Text)
        if ($bytes.Length -gt $script:TicketboxC07RecoveryMaximumJsonLineBytes) {
            throw "$Label 超出单行大小上限。"
        }
        $json = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
        return ConvertFrom-TicketboxC07RecoveryJson $json
    }
    catch {
        throw "$Label 不是 canonical UTF-8 JSON evidence。"
    }
}

function Get-TicketboxC07RecoverySnapshotPreflightSql {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 2147483647)]
        [int]$MaximumRemainingCeilingMilliseconds
    )
    $deadline =
        ConvertTo-TicketboxC07RecoveryMaintenanceDeadlineUtc (
            $MaintenanceDeadlineUtc
        )
    return @"
SET application_name = 'ticketbox-c07-snapshot:$OperationId';
DO `$ticketbox_timeout`$
DECLARE
  setting_count integer;
  configured_statement_ms bigint;
  configured_transaction_ms bigint;
  configured_idle_in_transaction_ms bigint;
  configured_lock_ms bigint;
  observed_at timestamptz;
  absolute_cap_ms bigint;
  armed_statement_ms bigint;
  armed_transaction_ms bigint;
  applied_lock_ms bigint;
BEGIN
  SELECT
    count(*)::integer,
    max(setting::bigint) FILTER (WHERE name = 'statement_timeout'),
    max(setting::bigint) FILTER (WHERE name = 'transaction_timeout'),
    max(setting::bigint) FILTER (
      WHERE name = 'idle_in_transaction_session_timeout'
    ),
    max(setting::bigint) FILTER (WHERE name = 'lock_timeout')
  INTO
    setting_count,
    configured_statement_ms,
    configured_transaction_ms,
    configured_idle_in_transaction_ms,
    configured_lock_ms
  FROM pg_settings
  WHERE name IN (
    'statement_timeout',
    'transaction_timeout',
    'idle_in_transaction_session_timeout',
    'lock_timeout'
  );
  IF setting_count <> 4 OR EXISTS (
    SELECT 1
    FROM pg_settings
    WHERE name IN (
      'statement_timeout',
      'transaction_timeout',
      'idle_in_transaction_session_timeout',
      'lock_timeout'
    )
      AND unit IS DISTINCT FROM 'ms'
  ) THEN
    RAISE EXCEPTION 'C07 snapshot timeout settings unavailable or non-ms';
  END IF;
  observed_at := clock_timestamp();
  absolute_cap_ms := LEAST(
    $MaximumRemainingCeilingMilliseconds::bigint,
    floor(
      extract(
        epoch FROM (
          TIMESTAMPTZ '$deadline' - observed_at
        )
      ) * 1000
    )::bigint
  ) - $script:TicketboxC07RecoverySnapshotStartupGuardMilliseconds::bigint;
  IF absolute_cap_ms < 1000 THEN
    RAISE EXCEPTION 'C07 snapshot maintenance deadline exhausted';
  END IF;
  armed_statement_ms := CASE
    WHEN configured_statement_ms = 0 THEN absolute_cap_ms
    ELSE LEAST(configured_statement_ms, absolute_cap_ms)
  END;
  armed_transaction_ms := CASE
    WHEN configured_transaction_ms = 0 THEN absolute_cap_ms
    ELSE LEAST(configured_transaction_ms, absolute_cap_ms)
  END;
  applied_lock_ms := CASE
    WHEN configured_lock_ms = 0 THEN LEAST(5000::bigint, absolute_cap_ms)
    ELSE LEAST(configured_lock_ms, 5000::bigint, absolute_cap_ms)
  END;
  PERFORM set_config(
    'ticketbox.c07_snapshot_maintenance_deadline_utc',
    '$deadline',
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_maximum_remaining_ceiling_ms',
    '$MaximumRemainingCeilingMilliseconds',
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_configured_statement_timeout_ms',
    configured_statement_ms::text,
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_configured_transaction_timeout_ms',
    configured_transaction_ms::text,
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_transaction_timeout_armed_ms',
    armed_transaction_ms::text,
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_configured_idle_in_transaction_timeout_ms',
    configured_idle_in_transaction_ms::text,
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_configured_lock_timeout_ms',
    configured_lock_ms::text,
    false
  );
  PERFORM set_config(
    'statement_timeout',
    armed_statement_ms::text || 'ms',
    false
  );
  PERFORM set_config(
    'transaction_timeout',
    armed_transaction_ms::text || 'ms',
    false
  );
  PERFORM set_config(
    'lock_timeout',
    applied_lock_ms::text || 'ms',
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_statement_timeout_applied_ms',
    armed_statement_ms::text,
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_lock_timeout_applied_ms',
    applied_lock_ms::text,
    false
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_preflight_observed_at_utc',
    to_char(
      observed_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    ),
    false
  );
END
`$ticketbox_timeout`$;
SELECT 'TBX_ARMED';
"@
}

function Get-TicketboxC07RecoverySnapshotSql {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 2147483647)]
        [int]$MaximumRemainingCeilingMilliseconds
    )
    $deadline =
        ConvertTo-TicketboxC07RecoveryMaintenanceDeadlineUtc (
            $MaintenanceDeadlineUtc
        )
    return @"
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO `$ticketbox`$
BEGIN
  IF NOT pg_try_advisory_lock(
    hashtext(current_database()),
    hashtext('xiaopiaojia:schema')
  ) THEN
    RAISE EXCEPTION 'C07 snapshot schema lease is busy';
  END IF;
END
`$ticketbox`$;
SELECT pg_stat_clear_snapshot();
DO `$ticketbox`$
BEGIN
  IF session_user <> 'postgres' OR current_user <> 'postgres' THEN
    RAISE EXCEPTION 'C07 snapshot cut is not database authority';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_stat_activity
    WHERE datid = (
      SELECT oid FROM pg_database WHERE datname = current_database()
    )
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
  ) THEN
    RAISE EXCEPTION 'C07 snapshot cut observed another client backend';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_database AS database_record
    CROSS JOIN LATERAL aclexplode(
      COALESCE(
        database_record.datacl,
        acldefault('d', database_record.datdba)
      )
    ) AS privilege
    WHERE database_record.datname = current_database()
      AND privilege.grantee = 0
      AND privilege.privilege_type = 'CONNECT'
  ) THEN
    RAISE EXCEPTION 'C07 snapshot cut observed PUBLIC CONNECT';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_roles AS role
    WHERE role.rolname !~ '^pg_'
      AND role.rolname NOT IN ('postgres', 'ticketbox_migrator')
      AND role.rolcanlogin
  ) THEN
    RAISE EXCEPTION 'C07 snapshot cut observed an unfenced login role';
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
    RAISE EXCEPTION 'C07 snapshot cut observed elevated external authority';
  END IF;
  IF current_setting('max_prepared_transactions')::bigint <> 0
     OR EXISTS (
       SELECT 1 FROM pg_prepared_xacts
       WHERE database = current_database()
     )
     OR EXISTS (
       SELECT 1 FROM pg_subscription
       WHERE subdbid = (
         SELECT oid FROM pg_database WHERE datname = current_database()
       )
     )
     OR EXISTS (
       SELECT 1
       FROM pg_stat_activity
       WHERE datid = (
         SELECT oid FROM pg_database WHERE datname = current_database()
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
      'C07 snapshot cut observed prepared/logical/background writer';
  END IF;
END
`$ticketbox`$;
SELECT 'TBX_BACKEND_PID:' || pg_backend_pid()::text;
SELECT 'TBX_FENCE_CUT:' || pg_backend_pid()::text;
SELECT 'TBX_SNAPSHOT:' || pg_export_snapshot();
SELECT 'TBX_META:' || replace(
  encode(
    convert_to(
      json_build_object(
        'database', current_database(),
        'database_oid', (
          SELECT oid::text FROM pg_database WHERE datname = current_database()
        ),
        'cluster_system_identifier', (
          SELECT system_identifier::text FROM pg_control_system()
        ),
        'data_directory', current_setting('data_directory'),
        'server_version_num', current_setting('server_version_num'),
        'database_size_bytes', pg_database_size(current_database())::text,
        'wal_bytes', COALESCE((SELECT sum(size) FROM pg_ls_waldir()), 0)::text,
        'server_id', (
          SELECT value FROM app_meta WHERE key = 'server_id'
        ),
        'data_generation', (
          SELECT value FROM app_meta WHERE key = 'data_generation'
        ),
        'alembic_heads', (
          SELECT COALESCE(json_agg(version_num ORDER BY version_num), '[]'::json)
          FROM alembic_version
        )
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
);
SELECT 'TBX_TABLESPACE:' || replace(
  encode(
    convert_to(
      json_build_object(
        'name', spcname,
        'location', pg_tablespace_location(oid),
        'size_bytes', pg_tablespace_size(oid)::text
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
)
FROM pg_tablespace
WHERE pg_tablespace_location(oid) <> ''
ORDER BY spcname;
SELECT 'TBX_ASSET:' || replace(
  encode(
    convert_to(
      json_build_object(
        'expense_public_id', public_id::text,
        'ledger_id', tenant_id,
        'image_reference', COALESCE(image_path, ''),
        'image_sha256', COALESCE(image_hash, ''),
        'image_deleted', image_deleted_at IS NOT NULL,
        'thumbnail_reference', COALESCE(thumbnail_path, ''),
        'thumbnail_deleted', thumbnail_deleted_at IS NOT NULL
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
)
FROM expenses
WHERE image_path IS NOT NULL OR thumbnail_path IS NOT NULL
ORDER BY public_id;
DO `$ticketbox_timeout`$
DECLARE
  holder_remaining_ms bigint;
  configured_statement_ms bigint;
  configured_transaction_ms bigint;
  configured_idle_in_transaction_ms bigint;
  configured_lock_ms bigint;
  armed_transaction_ms bigint;
  current_transaction_setting_ms bigint;
  statement_timeout_applied_ms bigint;
  lock_timeout_applied_ms bigint;
  transaction_started_at timestamptz;
  observed_at timestamptz;
  derived_upper_bound_expiry_at timestamptz;
BEGIN
  SELECT activity.xact_start
  INTO transaction_started_at
  FROM pg_stat_activity AS activity
  WHERE activity.pid = pg_backend_pid();
  observed_at := clock_timestamp();
  IF transaction_started_at IS NULL OR observed_at < transaction_started_at THEN
    RAISE EXCEPTION 'C07 snapshot READY transaction start evidence unavailable';
  END IF;
  holder_remaining_ms := LEAST(
    current_setting(
      'ticketbox.c07_snapshot_maximum_remaining_ceiling_ms'
    )::bigint,
    floor(
      extract(
        epoch FROM (
          current_setting(
            'ticketbox.c07_snapshot_maintenance_deadline_utc'
          )::timestamptz - observed_at
        )
      ) * 1000
    )::bigint
  );
  configured_statement_ms := current_setting(
    'ticketbox.c07_snapshot_configured_statement_timeout_ms'
  )::bigint;
  configured_transaction_ms := current_setting(
    'ticketbox.c07_snapshot_configured_transaction_timeout_ms'
  )::bigint;
  configured_idle_in_transaction_ms := current_setting(
    'ticketbox.c07_snapshot_configured_idle_in_transaction_timeout_ms'
  )::bigint;
  configured_lock_ms := current_setting(
    'ticketbox.c07_snapshot_configured_lock_timeout_ms'
  )::bigint;
  armed_transaction_ms := current_setting(
    'ticketbox.c07_snapshot_transaction_timeout_armed_ms'
  )::bigint;
  current_transaction_setting_ms := (
    SELECT setting::bigint
    FROM pg_settings
    WHERE name = 'transaction_timeout'
  );
  derived_upper_bound_expiry_at :=
    transaction_started_at +
    (armed_transaction_ms * interval '1 millisecond');
  IF holder_remaining_ms < 1000 THEN
    RAISE EXCEPTION 'C07 snapshot deadline expired before READY';
  END IF;
  IF armed_transaction_ms < 1
     OR current_transaction_setting_ms <> armed_transaction_ms THEN
    RAISE EXCEPTION
      'C07 transaction_timeout was not armed before target BEGIN';
  END IF;
  IF derived_upper_bound_expiry_at >
      current_setting(
        'ticketbox.c07_snapshot_maintenance_deadline_utc'
      )::timestamptz
  THEN
    RAISE EXCEPTION
      'C07 transaction_timeout derived upper-bound exceeds absolute deadline';
  END IF;
  holder_remaining_ms := LEAST(
    holder_remaining_ms,
    floor(
      extract(
        epoch FROM (derived_upper_bound_expiry_at - observed_at)
      ) * 1000
    )::bigint
  );
  IF holder_remaining_ms < 1 THEN
    RAISE EXCEPTION 'C07 snapshot transaction deadline exhausted before READY';
  END IF;
  statement_timeout_applied_ms := CASE
    WHEN configured_statement_ms = 0 THEN holder_remaining_ms
    ELSE LEAST(configured_statement_ms, holder_remaining_ms)
  END;
  lock_timeout_applied_ms := CASE
    WHEN configured_lock_ms = 0 THEN LEAST(5000::bigint, holder_remaining_ms)
    ELSE LEAST(configured_lock_ms, 5000::bigint, holder_remaining_ms)
  END;
  PERFORM set_config(
    'statement_timeout',
    statement_timeout_applied_ms::text || 'ms',
    true
  );
  PERFORM set_config(
    'lock_timeout',
    lock_timeout_applied_ms::text || 'ms',
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_holder_remaining_ms',
    holder_remaining_ms::text,
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_transaction_started_utc',
    to_char(
      transaction_started_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    ),
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_derived_upper_bound_expiry_utc',
    to_char(
      derived_upper_bound_expiry_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    ),
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_timeout_observed_at_utc',
    to_char(
      observed_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    ),
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_remaining_ms_before_statement',
    holder_remaining_ms::text,
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_statement_timeout_applied_ms',
    statement_timeout_applied_ms::text,
    true
  );
  PERFORM set_config(
    'ticketbox.c07_snapshot_lock_timeout_applied_ms',
    lock_timeout_applied_ms::text,
    true
  );
END
`$ticketbox_timeout`$;
SELECT 'TBX_TIMEOUTS:' || replace(
  encode(
    convert_to(
      json_build_object(
        'absolute_deadline_utc', current_setting(
          'ticketbox.c07_snapshot_maintenance_deadline_utc'
        ),
        'maximum_remaining_ceiling_ms', current_setting(
          'ticketbox.c07_snapshot_maximum_remaining_ceiling_ms'
        ),
        'remaining_ms_before_statement', current_setting(
          'ticketbox.c07_snapshot_holder_remaining_ms'
        ),
        'statement_timeout_configured_ceiling_ms', current_setting(
          'ticketbox.c07_snapshot_configured_statement_timeout_ms'
        ),
        'statement_timeout_applied_ms', current_setting(
          'ticketbox.c07_snapshot_statement_timeout_applied_ms'
        ),
        'transaction_timeout_configured_ceiling_ms', current_setting(
          'ticketbox.c07_snapshot_configured_transaction_timeout_ms'
        ),
        'transaction_timeout_armed_ms', current_setting(
          'ticketbox.c07_snapshot_transaction_timeout_armed_ms'
        ),
        'transaction_timeout_current_setting_ms', (
          SELECT setting FROM pg_settings
          WHERE name = 'transaction_timeout'
        ),
        'transaction_timeout_derived_upper_bound_expiry_utc', current_setting(
          'ticketbox.c07_snapshot_derived_upper_bound_expiry_utc'
        ),
        'transaction_timeout_reconfigured_in_transaction', false,
        'snapshot_exporter_preflight_observed_at_utc', current_setting(
          'ticketbox.c07_snapshot_preflight_observed_at_utc'
        ),
        'snapshot_exporter_transaction_started_utc', current_setting(
          'ticketbox.c07_snapshot_transaction_started_utc'
        ),
        'snapshot_exporter_deadline_utc', current_setting(
          'ticketbox.c07_snapshot_maintenance_deadline_utc'
        ),
        'timeout_observed_at_utc', current_setting(
          'ticketbox.c07_snapshot_timeout_observed_at_utc'
        ),
        'idle_in_transaction_session_timeout_configured_ms',
          current_setting(
            'ticketbox.c07_snapshot_configured_idle_in_transaction_timeout_ms'
          ),
        'idle_in_transaction_session_timeout_effective_ms', (
          SELECT setting FROM pg_settings
          WHERE name = 'idle_in_transaction_session_timeout'
        ),
        'lock_timeout_configured_ceiling_ms', current_setting(
          'ticketbox.c07_snapshot_configured_lock_timeout_ms'
        ),
        'lock_timeout_applied_ms', current_setting(
          'ticketbox.c07_snapshot_lock_timeout_applied_ms'
        ),
        'enforcement_kind',
          'pre_begin_transaction_plus_per_statement_absolute_v1',
        'observed_server_termination', 'not_observed_while_holder_live',
        'holder_wait', 'pg_sleep_until_active_statement'
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
);
SELECT 'TBX_READY';
SELECT pg_sleep_until(
  current_setting(
    'ticketbox.c07_snapshot_maintenance_deadline_utc'
  )::timestamptz
);
ROLLBACK;
"@
}

function Start-TicketboxC07RecoverySnapshotProcess {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][string]$ProtectedDatabaseUrl,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 2147483647)]
        [int]$MaximumRemainingCeilingMilliseconds
    )
    $arguments = @(
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--quiet",
        "--set", "ON_ERROR_STOP=1",
        "--dbname", $ProtectedDatabaseUrl,
        "--command", (
            Get-TicketboxC07RecoverySnapshotPreflightSql `
                -OperationId $OperationId `
                -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
                -MaximumRemainingCeilingMilliseconds (
                    $MaximumRemainingCeilingMilliseconds
                )
        ),
        "--command", (
            Get-TicketboxC07RecoverySnapshotSql `
                -OperationId $OperationId `
                -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
                -MaximumRemainingCeilingMilliseconds (
                    $MaximumRemainingCeilingMilliseconds
                )
        )
    )
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $PsqlPath
    $info.Arguments = [string]::Join(
        " ",
        @($arguments | ForEach-Object {
            ConvertTo-TicketboxNativeCommandLineArgument ([string]$_)
        })
    )
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $info.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    if (-not $process.Start()) {
        $process.Dispose()
        throw "C07 recovery exported-snapshot session 无法启动。"
    }
    return $process
}

function Read-TicketboxC07RecoverySnapshotProcess {
    param(
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$ExpectedMaintenanceDeadlineUtc,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1000, 2147483647)]
        [int]$MaximumRemainingCeilingMilliseconds,
        [ValidateRange(1000, 300000)][int]$TimeoutMilliseconds =
            $script:TicketboxC07RecoverySnapshotTimeoutMilliseconds
    )
    $expectedDeadline =
        ConvertTo-TicketboxC07RecoveryMaintenanceDeadlineUtc (
            $ExpectedMaintenanceDeadlineUtc
        )
    $absoluteDeadline =
        ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc `
            -Value $expectedDeadline `
            -Label "C07 recovery snapshot absolute deadline"
    $startupDeadline =
        [DateTimeOffset]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    $readDeadline = $startupDeadline
    if ($absoluteDeadline -lt $readDeadline) {
        $readDeadline = $absoluteDeadline
    }
    $backendPid = 0
    $fenceCutPid = 0
    $snapshotId = ""
    $armedSeen = $false
    $meta = $null
    $timeoutContract = $null
    $tablespaces = New-Object System.Collections.Generic.List[object]
    $assets = New-Object System.Collections.Generic.List[object]
    while ($true) {
        $remainingRaw = [int64][Math]::Floor(
            ($readDeadline - [DateTimeOffset]::UtcNow).TotalMilliseconds
        )
        if ($remainingRaw -lt 1) {
            throw "C07 recovery exported-snapshot evidence 超过绝对 deadline。"
        }
        $remaining = [int][Math]::Min(
            [int64][int]::MaxValue,
            $remainingRaw
        )
        $readTask = $Process.StandardOutput.ReadLineAsync()
        if (-not $readTask.Wait($remaining)) {
            throw "C07 recovery exported-snapshot evidence 超时。"
        }
        $line = $readTask.Result
        if ($null -eq $line) {
            throw "C07 recovery exported-snapshot session 提前退出。"
        }
        if ($line -ceq "TBX_READY") { break }
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -ceq "TBX_ARMED") {
            if ($armedSeen) {
                throw "C07 recovery snapshot pre-BEGIN arm evidence 重复。"
            }
            $armedSeen = $true
            continue
        }
        if ($line.StartsWith("TBX_BACKEND_PID:", [StringComparison]::Ordinal)) {
            if (
                $backendPid -ne 0 -or
                -not [int]::TryParse(
                    $line.Substring("TBX_BACKEND_PID:".Length),
                    [ref]$backendPid
                ) -or
                $backendPid -lt 1
            ) {
                throw "C07 recovery snapshot backend PID 无效或重复。"
            }
            continue
        }
        if ($line.StartsWith("TBX_FENCE_CUT:", [StringComparison]::Ordinal)) {
            if (
                $fenceCutPid -ne 0 -or
                -not [int]::TryParse(
                    $line.Substring("TBX_FENCE_CUT:".Length),
                    [ref]$fenceCutPid
                ) -or
                $fenceCutPid -lt 1
            ) {
                throw "C07 recovery snapshot same-session fence cut 无效。"
            }
            continue
        }
        if ($line.StartsWith("TBX_SNAPSHOT:", [StringComparison]::Ordinal)) {
            if (-not [string]::IsNullOrEmpty($snapshotId)) {
                throw "C07 recovery snapshot ID 重复。"
            }
            $snapshotId = $line.Substring("TBX_SNAPSHOT:".Length)
            if (
                $snapshotId -cnotmatch (
                    "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}$"
                )
            ) {
                throw "C07 recovery PostgreSQL exported snapshot ID 无效。"
            }
            continue
        }
        if ($line.StartsWith("TBX_META:", [StringComparison]::Ordinal)) {
            if ($null -ne $meta) {
                throw "C07 recovery snapshot metadata 重复。"
            }
            $meta = ConvertFrom-TicketboxC07RecoveryBase64Json `
                -Text $line.Substring("TBX_META:".Length) `
                -Label "C07 recovery snapshot metadata"
            continue
        }
        if ($line.StartsWith("TBX_TIMEOUTS:", [StringComparison]::Ordinal)) {
            if ($null -ne $timeoutContract) {
                throw "C07 recovery snapshot timeout evidence 重复。"
            }
            $timeoutContract = ConvertFrom-TicketboxC07RecoveryBase64Json `
                -Text $line.Substring("TBX_TIMEOUTS:".Length) `
                -Label "C07 recovery snapshot timeout evidence"
            continue
        }
        if ($line.StartsWith("TBX_TABLESPACE:", [StringComparison]::Ordinal)) {
            $tablespaces.Add((
                ConvertFrom-TicketboxC07RecoveryBase64Json `
                    -Text $line.Substring("TBX_TABLESPACE:".Length) `
                    -Label "C07 recovery tablespace evidence"
            ))
            continue
        }
        if ($line.StartsWith("TBX_ASSET:", [StringComparison]::Ordinal)) {
            if ($assets.Count -ge $script:TicketboxC07RecoveryMaximumInventoryRows) {
                throw "C07 recovery asset inventory 超出有界行数。"
            }
            $assets.Add((
                ConvertFrom-TicketboxC07RecoveryBase64Json `
                    -Text $line.Substring("TBX_ASSET:".Length) `
                    -Label "C07 recovery asset inventory"
            ))
            continue
        }
        throw "C07 recovery snapshot session 返回未登记 evidence line。"
    }
    if (
        [string]::IsNullOrEmpty($snapshotId) -or
        -not $armedSeen -or
        $backendPid -lt 1 -or
        $fenceCutPid -ne $backendPid -or
        $null -eq $meta -or
        $null -eq $timeoutContract -or
        $Process.HasExited
    ) {
        throw "C07 recovery exported snapshot 未保持 live transaction。"
    }
    Assert-TicketboxC07RecoveryExactProperties `
        $timeoutContract `
        @(
            "absolute_deadline_utc",
            "maximum_remaining_ceiling_ms",
            "remaining_ms_before_statement",
            "statement_timeout_configured_ceiling_ms",
            "statement_timeout_applied_ms",
            "transaction_timeout_configured_ceiling_ms",
            "transaction_timeout_armed_ms",
            "transaction_timeout_current_setting_ms",
            "transaction_timeout_derived_upper_bound_expiry_utc",
            "transaction_timeout_reconfigured_in_transaction",
            "snapshot_exporter_preflight_observed_at_utc",
            "snapshot_exporter_transaction_started_utc",
            "snapshot_exporter_deadline_utc",
            "timeout_observed_at_utc",
            "idle_in_transaction_session_timeout_configured_ms",
            "idle_in_transaction_session_timeout_effective_ms",
            "lock_timeout_configured_ceiling_ms",
            "lock_timeout_applied_ms",
            "enforcement_kind",
            "observed_server_termination",
            "holder_wait"
        ) `
        "C07 recovery snapshot timeout evidence"
    $maximumRemainingCeiling =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.maximum_remaining_ceiling_ms `
            "C07 snapshot maximum remaining ceiling"
    $remainingBeforeStatement =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.remaining_ms_before_statement `
            "C07 snapshot remaining before holder statement"
    $configuredStatement =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.statement_timeout_configured_ceiling_ms `
            "C07 snapshot configured statement_timeout"
    $appliedStatement =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.statement_timeout_applied_ms `
            "C07 snapshot applied statement_timeout"
    $configuredTransaction =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.transaction_timeout_configured_ceiling_ms `
            "C07 snapshot configured transaction_timeout"
    $armedTransaction =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.transaction_timeout_armed_ms `
            "C07 snapshot pre-BEGIN armed transaction_timeout"
    $currentTransactionSetting =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.transaction_timeout_current_setting_ms `
            "C07 snapshot current transaction_timeout setting"
    $configuredIdle =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.idle_in_transaction_session_timeout_configured_ms `
            "C07 snapshot configured idle-in-transaction timeout"
    $effectiveIdle =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.idle_in_transaction_session_timeout_effective_ms `
            "C07 snapshot effective idle-in-transaction timeout"
    $configuredLock =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.lock_timeout_configured_ceiling_ms `
            "C07 snapshot configured lock_timeout"
    $appliedLock =
        ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $timeoutContract.lock_timeout_applied_ms `
            "C07 snapshot applied lock_timeout"
    $expectedDeadlineValue = $absoluteDeadline
    $preflightObservedAt =
        ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc `
            -Value (
                [string]$timeoutContract.snapshot_exporter_preflight_observed_at_utc
            ) `
            -Label "C07 snapshot preflight timestamp"
    $transactionStartedAt =
        ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc `
            -Value (
                [string]$timeoutContract.snapshot_exporter_transaction_started_utc
            ) `
            -Label "C07 snapshot transaction start timestamp"
    $derivedUpperBoundExpiryAt =
        ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc `
            -Value (
                [string]$timeoutContract.transaction_timeout_derived_upper_bound_expiry_utc
            ) `
            -Label "C07 snapshot derived transaction expiry timestamp"
    $timeoutObservedAt =
        ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc `
            -Value ([string]$timeoutContract.timeout_observed_at_utc) `
            -Label "C07 snapshot timeout observation timestamp"
    $derivedArmedMilliseconds = [int64][Math]::Round(
        ($derivedUpperBoundExpiryAt - $transactionStartedAt).TotalMilliseconds
    )
    if (
        [string]$timeoutContract.absolute_deadline_utc -cne
            $expectedDeadline -or
        [string]$timeoutContract.snapshot_exporter_deadline_utc -cne
            $expectedDeadline -or
        $timeoutContract.transaction_timeout_reconfigured_in_transaction -isnot
            [bool] -or
        [bool]$timeoutContract.transaction_timeout_reconfigured_in_transaction -or
        $maximumRemainingCeiling -lt 1000 -or
        $maximumRemainingCeiling -gt
            [uint64]$MaximumRemainingCeilingMilliseconds -or
        $remainingBeforeStatement -lt 1 -or
        $remainingBeforeStatement -gt $maximumRemainingCeiling -or
        $armedTransaction -lt 1 -or
        $armedTransaction -gt $maximumRemainingCeiling -or
        $currentTransactionSetting -ne $armedTransaction -or
        [Math]::Abs($derivedArmedMilliseconds - [int64]$armedTransaction) -gt 2 -or
        $preflightObservedAt -gt $transactionStartedAt -or
        $transactionStartedAt -gt $timeoutObservedAt -or
        $timeoutObservedAt -ge $derivedUpperBoundExpiryAt -or
        $derivedUpperBoundExpiryAt -gt $expectedDeadlineValue -or
        [DateTimeOffset]::UtcNow -ge $derivedUpperBoundExpiryAt -or
        (
            $configuredTransaction -gt 0 -and
            $armedTransaction -gt $configuredTransaction
        ) -or
        $appliedStatement -lt 1 -or
        $appliedStatement -gt $remainingBeforeStatement -or
        (
            $configuredStatement -gt 0 -and
            $appliedStatement -gt $configuredStatement
        ) -or
        $effectiveIdle -ne $configuredIdle -or
        $appliedLock -lt 1 -or
        $appliedLock -gt 5000 -or
        $appliedLock -gt $remainingBeforeStatement -or
        (
            $configuredLock -gt 0 -and
            $appliedLock -gt $configuredLock
        ) -or
        [string]$timeoutContract.enforcement_kind -cne
            "pre_begin_transaction_plus_per_statement_absolute_v1" -or
        [string]$timeoutContract.observed_server_termination -cne
            "not_observed_while_holder_live" -or
        [string]$timeoutContract.holder_wait -cne
            "pg_sleep_until_active_statement"
    ) {
        throw "C07 recovery snapshot timeout evidence 未保持 deadline/no-widen。"
    }
    return [pscustomobject]@{
        Process = $Process
        BackendPid = $backendPid
        FenceCutVerified = $true
        SnapshotId = $snapshotId
        Meta = $meta
        Tablespaces = $tablespaces.ToArray()
        Assets = $assets.ToArray()
        TimeoutContract = $timeoutContract
        AbsoluteDeadlineUtc = $expectedDeadline
        TransactionDeadlineUtc = $derivedUpperBoundExpiryAt.UtcDateTime.ToString("o")
        SnapshotExporterTransactionStartedUtc =
            $transactionStartedAt.UtcDateTime.ToString("o")
    }
}

function Open-TicketboxC07RecoverySnapshot {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $lifetime = Get-TicketboxC07RecoverySnapshotLifetime -Context $Context
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $SuperuserPassword `
        -Action {
            param([string]$PlainPassword)
            return Invoke-TicketboxWithPgPassFile `
                -DatabaseUrl $Context.DatabaseUrl `
                -Password $PlainPassword `
                -Action {
                    param([string]$ProtectedDatabaseUrl)
                    $process = Start-TicketboxC07RecoverySnapshotProcess `
                        -PsqlPath $Context.DatabaseAuthority.PsqlPath `
                        -ProtectedDatabaseUrl $ProtectedDatabaseUrl `
                        -OperationId (
                            [string]$Context.Authority.Receipt.operation_id
                        ) `
                        -MaintenanceDeadlineUtc (
                            [string]$lifetime.MaintenanceDeadlineUtc
                        ) `
                        -MaximumRemainingCeilingMilliseconds (
                            [int]$lifetime.MaximumRemainingCeilingMilliseconds
                        )
                    try {
                        return Read-TicketboxC07RecoverySnapshotProcess `
                            -Process $process `
                            -ExpectedMaintenanceDeadlineUtc (
                                [string]$lifetime.MaintenanceDeadlineUtc
                            ) `
                            -MaximumRemainingCeilingMilliseconds (
                                [int]$lifetime.MaximumRemainingCeilingMilliseconds
                            ) `
                            -TimeoutMilliseconds (
                                Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
                                    -MaximumMilliseconds (
                                        $script:TicketboxC07RecoverySnapshotTimeoutMilliseconds
                                    ) `
                                    -Label "C07 snapshot startup"
                            )
                    }
                    catch {
                        if (-not $process.HasExited) {
                            $process.Kill()
                            [void]$process.WaitForExit(10000)
                        }
                        $process.Dispose()
                        throw
                    }
                }
        }
}

function Assert-TicketboxC07RecoverySnapshotAlive {
    param([Parameter(Mandatory = $true)][object]$Snapshot)
    if ($null -eq $Snapshot.Process -or $Snapshot.Process.HasExited) {
        throw "C07 recovery PostgreSQL exported snapshot 已失效。"
    }
    $transactionDeadline =
        ConvertTo-TicketboxC07RecoveryEvidenceTimestampUtc `
            -Value ([string]$Snapshot.TransactionDeadlineUtc) `
            -Label "C07 recovery snapshot transaction deadline"
    if ([DateTimeOffset]::UtcNow -ge $transactionDeadline) {
        $Snapshot.Process.Kill()
        [void]$Snapshot.Process.WaitForExit(10000)
        throw "C07 recovery PostgreSQL exported snapshot 超过 transaction deadline。"
    }
}

function Close-TicketboxC07RecoverySnapshot {
    param([AllowNull()][object]$Snapshot)
    if ($null -eq $Snapshot -or $null -eq $Snapshot.Process) { return }
    $process = $Snapshot.Process
    try {
        if (-not $process.HasExited) {
            $process.Kill()
            if (-not $process.WaitForExit(10000)) {
                throw "C07 recovery snapshot session 无法在有界时间内退出。"
            }
        }
    }
    finally {
        $process.Dispose()
    }
}

function ConvertTo-TicketboxC07RecoveryUnsignedInt64 {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    [uint64]$parsed = 0
    if (
        -not [uint64]::TryParse(
            [string]$Value,
            [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$parsed
        )
    ) {
        throw "$Label 不是有效非负 byte count。"
    }
    return $parsed
}

function Get-TicketboxC07RecoveryVolumeKey([string]$Path) {
    $canonical = ConvertTo-TicketboxCanonicalPath $Path
    $root = [IO.Path]::GetPathRoot($canonical)
    if ([string]::IsNullOrEmpty($root)) {
        throw "C07 recovery 无法解析本地 volume root。"
    }
    return $root.ToUpperInvariant()
}

function Get-TicketboxC07RecoveryVolumeFreeBytes([string]$Path) {
    $root = Get-TicketboxC07RecoveryVolumeKey $Path
    try {
        $drive = [IO.DriveInfo]::new($root)
        if (-not $drive.IsReady) {
            throw "volume is not ready"
        }
        return [uint64]$drive.AvailableFreeSpace
    }
    catch {
        throw "C07 recovery 无法取得受管 volume 可用空间。"
    }
}

function ConvertTo-TicketboxC07RecoveryRequiredBytes([decimal]$RawBytes) {
    if ($RawBytes -lt 0) {
        throw "C07 recovery 容量估算不能为负数。"
    }
    $withHeadroom = [decimal]::Ceiling($RawBytes * [decimal]1.20)
    if ($withHeadroom -gt [decimal][uint64]::MaxValue) {
        throw "C07 recovery 容量估算超出 uint64。"
    }
    return [uint64]$withHeadroom
}

function Get-TicketboxC07RecoveryCapacityPlan {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Snapshot,
        [Parameter(Mandatory = $true)][int64]$AssetBytes,
        [string]$ExpectedRevision = ""
    )
    if ($AssetBytes -lt 0) {
        throw "C07 recovery asset size 不能为负。"
    }
    $meta = $Snapshot.Meta
    $expectedMeta = @(
        "database",
        "database_oid",
        "cluster_system_identifier",
        "data_directory",
        "server_version_num",
        "database_size_bytes",
        "wal_bytes",
        "server_id",
        "data_generation",
        "alembic_heads"
    )
    Assert-TicketboxC07RecoveryExactProperties `
        $meta `
        $expectedMeta `
        "C07 recovery snapshot metadata"
    if (
        [string]$meta.database -cne
            $script:TicketboxC07RecoveryDatabaseName -or
        [string]$meta.database_oid -cne
            [string]$Context.DatabaseIdentity.DatabaseOid -or
        [string]$meta.cluster_system_identifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        -not (Test-TicketboxPathEquals `
            ([string]$meta.data_directory) `
            ([string]$Context.DatabaseAuthority.PgData))
    ) {
        throw (
            "C07 recovery live SHOW data_directory/database identity 与 " +
            "SCM authority 不一致。"
        )
    }
    foreach ($identity in @(
        [string]$meta.server_id,
        [string]$meta.data_generation
    )) {
        $parsed = [Guid]::Empty
        if (
            -not [Guid]::TryParseExact($identity, "D", [ref]$parsed) -or
            $parsed -eq [Guid]::Empty -or
            $parsed.ToString("D") -cne $identity
        ) {
            throw "C07 recovery logical database identity 无效。"
        }
    }
    if (@($meta.alembic_heads).Count -ne 1) {
        throw "C07 recovery source 必须具有唯一 Alembic head。"
    }
    if ([string]::IsNullOrEmpty($ExpectedRevision)) {
        $ExpectedRevision =
            [string]$Context.Authority.Descriptor.Payload.source_alembic_revision
    }
    if ([string]@($meta.alembic_heads)[0] -cne $ExpectedRevision) {
        throw "C07 recovery snapshot Alembic head 未绑定 expected revision。"
    }
    if (@($Snapshot.Tablespaces).Count -gt 0) {
        foreach ($tablespace in @($Snapshot.Tablespaces)) {
            Assert-TicketboxC07RecoveryExactProperties `
                $tablespace `
                @("name", "location", "size_bytes") `
                "C07 recovery external tablespace"
            ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
                $tablespace.size_bytes `
                "C07 recovery tablespace bytes" | Out-Null
        }
        throw (
            "C07 recovery 检测到 external tablespace；当前 release 未声明 " +
            "完整 capture/restore，fail closed。"
        )
    }
    $walPath = Join-Path $Context.DatabaseAuthority.PgData "pg_wal"
    Assert-NoTicketboxAncestorReparsePoints $walPath
    if ((Get-TicketboxPathEntryKindNoFollow $walPath) -cne "Directory") {
        throw (
            "C07 recovery pg_wal 缺失、外置或经过 reparse point；" +
            "当前 release fail closed。"
        )
    }
    $databaseBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $meta.database_size_bytes `
        "C07 recovery database bytes"
    if ($databaseBytes -eq 0) {
        throw "C07 recovery source database size 不得为零。"
    }
    $observedWalBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $meta.wal_bytes `
        "C07 recovery WAL bytes"
    $walReserve = [uint64][Math]::Max(
        [decimal]$databaseBytes,
        [decimal]$observedWalBytes
    )
    $dbVolume = Get-TicketboxC07RecoveryVolumeKey `
        $Context.DatabaseAuthority.PgData
    $generationVolume = Get-TicketboxC07RecoveryVolumeKey `
        $Context.Paths.GenerationRoot
    [decimal]$dumpEstimate = $databaseBytes
    [decimal]$restoreEstimate = $databaseBytes
    [decimal]$rewriteAndIndexEstimate = $databaseBytes
    [decimal]$assetEstimate = $AssetBytes
    [decimal]$isolatedAssetRestoreEstimate = $AssetBytes
    [decimal]$metadataEstimate = (
        ([decimal]@($Snapshot.Assets).Count * 2 *
            ($script:TicketboxC07RecoveryMaximumJsonLineBytes + 1)) +
        (
            4 *
            $script:TicketboxC07RecoveryMaximumManifestBytes
        )
    )
    if ($dbVolume -ceq $generationVolume) {
        $required = ConvertTo-TicketboxC07RecoveryRequiredBytes (
            $dumpEstimate +
            $restoreEstimate +
            $rewriteAndIndexEstimate +
            [decimal]$walReserve +
            $assetEstimate +
            $isolatedAssetRestoreEstimate +
            $metadataEstimate
        )
        $free = Get-TicketboxC07RecoveryVolumeFreeBytes `
            $Context.DatabaseAuthority.PgData
        if ($free -lt $required) {
            throw "C07 recovery 同卷磁盘预算不足；零 dump/零 READY。"
        }
        return [ordered]@{
            schema = "ticketbox-c07-recovery-capacity-v1"
            volume_mode = "shared"
            database_size_bytes = [string]$databaseBytes
            dump_estimate_bytes = [string][uint64]$dumpEstimate
            isolated_restore_estimate_bytes = [string][uint64]$restoreEstimate
            rewrite_index_estimate_bytes = [string][uint64]$rewriteAndIndexEstimate
            observed_wal_bytes = [string]$observedWalBytes
            wal_reserve_bytes = [string]$walReserve
            asset_generation_copy_bytes = [string][uint64]$assetEstimate
            asset_isolated_restore_bytes =
                [string][uint64]$isolatedAssetRestoreEstimate
            manifest_inventory_reserve_bytes =
                [string][uint64]$metadataEstimate
            required_with_headroom_bytes = [string]$required
            free_bytes_at_preflight = [string]$free
            headroom_percent = 20
        }
    }
    $dbRequired = ConvertTo-TicketboxC07RecoveryRequiredBytes (
        $restoreEstimate + $rewriteAndIndexEstimate + [decimal]$walReserve
    )
    $generationRequired = ConvertTo-TicketboxC07RecoveryRequiredBytes (
        $dumpEstimate +
        $assetEstimate +
        $isolatedAssetRestoreEstimate +
        $metadataEstimate
    )
    $dbFree = Get-TicketboxC07RecoveryVolumeFreeBytes `
        $Context.DatabaseAuthority.PgData
    $generationFree = Get-TicketboxC07RecoveryVolumeFreeBytes `
        $Context.Paths.GenerationRoot
    if ($dbFree -lt $dbRequired -or $generationFree -lt $generationRequired) {
        throw "C07 recovery 分卷磁盘预算不足；零 dump/零 READY。"
    }
    return [ordered]@{
        schema = "ticketbox-c07-recovery-capacity-v1"
        volume_mode = "split"
        database_size_bytes = [string]$databaseBytes
        dump_estimate_bytes = [string][uint64]$dumpEstimate
        isolated_restore_estimate_bytes = [string][uint64]$restoreEstimate
        rewrite_index_estimate_bytes = [string][uint64]$rewriteAndIndexEstimate
        observed_wal_bytes = [string]$observedWalBytes
        wal_reserve_bytes = [string]$walReserve
        asset_generation_copy_bytes = [string][uint64]$assetEstimate
        asset_isolated_restore_bytes =
            [string][uint64]$isolatedAssetRestoreEstimate
        manifest_inventory_reserve_bytes =
            [string][uint64]$metadataEstimate
        database_required_with_headroom_bytes = [string]$dbRequired
        database_free_bytes_at_preflight = [string]$dbFree
        generation_required_with_headroom_bytes = [string]$generationRequired
        generation_free_bytes_at_preflight = [string]$generationFree
        headroom_percent = 20
    }
}

function Assert-TicketboxC07RecoveryCapacityEvidence {
    param([Parameter(Mandatory = $true)][object]$Capacity)
    $common = @(
        "schema",
        "volume_mode",
        "database_size_bytes",
        "dump_estimate_bytes",
        "isolated_restore_estimate_bytes",
        "rewrite_index_estimate_bytes",
        "observed_wal_bytes",
        "wal_reserve_bytes",
        "asset_generation_copy_bytes",
        "asset_isolated_restore_bytes",
        "manifest_inventory_reserve_bytes",
        "headroom_percent"
    )
    $mode = [string]$Capacity.volume_mode
    if ($mode -ceq "shared") {
        $expectedProperties = @(
            $common +
            @(
                "required_with_headroom_bytes",
                "free_bytes_at_preflight"
            )
        )
    }
    elseif ($mode -ceq "split") {
        $expectedProperties = @(
            $common +
            @(
                "database_required_with_headroom_bytes",
                "database_free_bytes_at_preflight",
                "generation_required_with_headroom_bytes",
                "generation_free_bytes_at_preflight"
            )
        )
    }
    else {
        throw "C07 recovery capacity volume mode 无效。"
    }
    Assert-TicketboxC07RecoveryExactProperties `
        $Capacity `
        $expectedProperties `
        "C07 recovery capacity evidence"
    if (
        [string]$Capacity.schema -cne
            "ticketbox-c07-recovery-capacity-v1" -or
        [int]$Capacity.headroom_percent -ne 20
    ) {
        throw "C07 recovery capacity schema/headroom 无效。"
    }
    $values = @{}
    foreach ($field in @(
        "database_size_bytes",
        "dump_estimate_bytes",
        "isolated_restore_estimate_bytes",
        "rewrite_index_estimate_bytes",
        "observed_wal_bytes",
        "wal_reserve_bytes",
        "asset_generation_copy_bytes",
        "asset_isolated_restore_bytes",
        "manifest_inventory_reserve_bytes"
    )) {
        $values[$field] = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $Capacity.$field `
            "C07 recovery capacity $field"
    }
    if (
        $values.database_size_bytes -eq 0 -or
        $values.dump_estimate_bytes -ne $values.database_size_bytes -or
        $values.isolated_restore_estimate_bytes -ne
            $values.database_size_bytes -or
        $values.rewrite_index_estimate_bytes -ne
            $values.database_size_bytes -or
        $values.asset_generation_copy_bytes -ne
            $values.asset_isolated_restore_bytes -or
        $values.wal_reserve_bytes -lt $values.database_size_bytes -or
        $values.wal_reserve_bytes -lt $values.observed_wal_bytes -or
        $values.manifest_inventory_reserve_bytes -eq 0
    ) {
        throw "C07 recovery capacity 分项不符合冻结估算合同。"
    }
    if ($mode -ceq "shared") {
        $required = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $Capacity.required_with_headroom_bytes `
            "C07 recovery shared required bytes"
        $free = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $Capacity.free_bytes_at_preflight `
            "C07 recovery shared free bytes"
        $expectedRequired = ConvertTo-TicketboxC07RecoveryRequiredBytes (
            [decimal]$values.dump_estimate_bytes +
            [decimal]$values.isolated_restore_estimate_bytes +
            [decimal]$values.rewrite_index_estimate_bytes +
            [decimal]$values.wal_reserve_bytes +
            [decimal]$values.asset_generation_copy_bytes +
            [decimal]$values.asset_isolated_restore_bytes +
            [decimal]$values.manifest_inventory_reserve_bytes
        )
        if ($required -ne $expectedRequired -or $free -lt $required) {
            throw "C07 recovery shared volume capacity evidence 不一致。"
        }
        return
    }
    $databaseRequired = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $Capacity.database_required_with_headroom_bytes `
        "C07 recovery database required bytes"
    $databaseFree = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $Capacity.database_free_bytes_at_preflight `
        "C07 recovery database free bytes"
    $generationRequired = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $Capacity.generation_required_with_headroom_bytes `
        "C07 recovery generation required bytes"
    $generationFree = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $Capacity.generation_free_bytes_at_preflight `
        "C07 recovery generation free bytes"
    $expectedDatabaseRequired = ConvertTo-TicketboxC07RecoveryRequiredBytes (
        [decimal]$values.isolated_restore_estimate_bytes +
        [decimal]$values.rewrite_index_estimate_bytes +
        [decimal]$values.wal_reserve_bytes
    )
    $expectedGenerationRequired = ConvertTo-TicketboxC07RecoveryRequiredBytes (
        [decimal]$values.dump_estimate_bytes +
        [decimal]$values.asset_generation_copy_bytes +
        [decimal]$values.asset_isolated_restore_bytes +
        [decimal]$values.manifest_inventory_reserve_bytes
    )
    if (
        $databaseRequired -ne $expectedDatabaseRequired -or
        $generationRequired -ne $expectedGenerationRequired -or
        $databaseFree -lt $databaseRequired -or
        $generationFree -lt $generationRequired
    ) {
        throw "C07 recovery split volume capacity evidence 不一致。"
    }
}

function ConvertTo-TicketboxC07RecoveryInventoryJson {
    param([Parameter(Mandatory = $true)][object]$Record)
    $canonical = ConvertTo-TicketboxC07AssetInventoryRecord $Record
    return ($canonical | ConvertTo-Json -Depth 4 -Compress)
}

function Write-TicketboxC07RecoveryJsonLines {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object[]]$Records,
        [Parameter(Mandatory = $true)][ValidateSet(
            "inventory",
            "copies"
        )][string]$Kind
    )
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "Missing") {
        throw "C07 recovery JSONL artifact 已存在；拒绝覆盖。"
    }
    $parent = Split-Path -Parent $Path
    Assert-NoTicketboxAncestorReparsePoints $parent
    $stream = $null
    $writer = $null
    try {
        $stream = [IO.FileStream]::new(
            $Path,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None,
            1048576,
            [IO.FileOptions]::WriteThrough
        )
        $writer = [IO.StreamWriter]::new(
            $stream,
            [Text.UTF8Encoding]::new($false),
            1048576,
            $true
        )
        foreach ($record in @($Records)) {
            if ($Kind -ceq "inventory") {
                $line = ConvertTo-TicketboxC07RecoveryInventoryJson $record
            }
            else {
                $line = ([ordered]@{
                    expense_public_id = [string]$record.expense_public_id
                    ledger_id = [string]$record.ledger_id
                    image_reference = [string]$record.image_reference
                    package_file = [string]$record.package_file
                    source_sha256 = [string]$record.source_sha256
                    database_expected_sha256 =
                        [string]$record.database_expected_sha256
                    size_bytes = [string]$record.size_bytes
                    thumbnail_reference = [string]$record.thumbnail_reference
                    thumbnail_state = [string]$record.thumbnail_state
                } | ConvertTo-Json -Depth 4 -Compress)
            }
            if (
                [Text.UTF8Encoding]::new($false).GetByteCount($line) -gt
                $script:TicketboxC07RecoveryMaximumJsonLineBytes
            ) {
                throw "C07 recovery JSONL record 超出单行上限。"
            }
            $writer.Write($line)
            $writer.Write("`n")
        }
        $writer.Flush()
        $stream.Flush($true)
    }
    finally {
        if ($null -ne $writer) { $writer.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
    Protect-TicketboxC07RecoveryFile $Path
    $item = Get-Item -LiteralPath $Path -Force
    return [pscustomobject]@{
        FileName = $item.Name
        Sha256 = Get-TicketboxC07RecoveryFileSha256 $Path
        SizeBytes = [int64]$item.Length
        RowCount = @($Records).Count
    }
}

function Get-TicketboxC07RecoveryJsonLinesDigest {
    param(
        [Parameter(Mandatory = $true)][object[]]$Records,
        [Parameter(Mandatory = $true)][ValidateSet(
            "inventory",
            "copies"
        )][string]$Kind
    )
    $sha = [Security.Cryptography.SHA256]::Create()
    $encoding = [Text.UTF8Encoding]::new($false)
    [int64]$size = 0
    try {
        foreach ($record in @($Records)) {
            if ($Kind -ceq "inventory") {
                $line = ConvertTo-TicketboxC07RecoveryInventoryJson $record
            }
            else {
                $line = ([ordered]@{
                    expense_public_id = [string]$record.expense_public_id
                    ledger_id = [string]$record.ledger_id
                    image_reference = [string]$record.image_reference
                    package_file = [string]$record.package_file
                    source_sha256 = [string]$record.source_sha256
                    database_expected_sha256 =
                        [string]$record.database_expected_sha256
                    size_bytes = [string]$record.size_bytes
                    thumbnail_reference = [string]$record.thumbnail_reference
                    thumbnail_state = [string]$record.thumbnail_state
                } | ConvertTo-Json -Depth 4 -Compress)
            }
            $bytes = $encoding.GetBytes($line + "`n")
            if ($bytes.Length -gt $script:TicketboxC07RecoveryMaximumJsonLineBytes + 1) {
                throw "C07 recovery JSONL record 超出单行上限。"
            }
            [void]$sha.TransformBlock($bytes, 0, $bytes.Length, $bytes, 0)
            $size += $bytes.Length
        }
        [void]$sha.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        return [pscustomobject]@{
            Sha256 = ([BitConverter]::ToString(
                $sha.Hash
            )).Replace("-", "").ToLowerInvariant()
            SizeBytes = $size
            RowCount = @($Records).Count
        }
    }
    finally {
        $sha.Dispose()
    }
}

function Read-TicketboxC07RecoveryJsonLines {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet(
            "inventory",
            "copies"
        )][string]$Kind,
        [Parameter(Mandatory = $true)][int]$ExpectedRows
    )
    if (
        $ExpectedRows -lt 0 -or
        $ExpectedRows -gt $script:TicketboxC07RecoveryMaximumInventoryRows
    ) {
        throw "C07 recovery JSONL expected row count 无效。"
    }
    Assert-NoTicketboxAncestorReparsePoints $Path
    if ((Get-TicketboxPathEntryKindNoFollow $Path) -cne "File") {
        throw "C07 recovery JSONL artifact 缺失或不是普通文件。"
    }
    $records = New-Object System.Collections.Generic.List[object]
    $reader = $null
    try {
        $reader = [IO.StreamReader]::new(
            $Path,
            [Text.UTF8Encoding]::new($false, $true),
            $true,
            1048576
        )
        while (($line = $reader.ReadLine()) -ne $null) {
            if (
                [string]::IsNullOrEmpty($line) -or
                [Text.UTF8Encoding]::new($false).GetByteCount($line) -gt
                    $script:TicketboxC07RecoveryMaximumJsonLineBytes
            ) {
                throw "C07 recovery JSONL 含空行或超限行。"
            }
            if ($records.Count -ge $ExpectedRows) {
                throw "C07 recovery JSONL 行数超过 manifest。"
            }
            try {
                $record = ConvertFrom-TicketboxC07RecoveryJson $line
            }
            catch {
                throw "C07 recovery JSONL 含无效 JSON。"
            }
            if ($Kind -ceq "inventory") {
                $record = ConvertTo-TicketboxC07AssetInventoryRecord $record
            }
            $records.Add($record)
        }
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
    }
    if ($records.Count -ne $ExpectedRows) {
        throw "C07 recovery JSONL 行数与 manifest 不一致。"
    }
    # PowerShell emits an empty array as no pipeline object.  Preserve the
    # collection itself so a valid zero-row generation remains distinguishable
    # from a missing/failed JSONL read.
    return ,$records.ToArray()
}

function Invoke-TicketboxC07RecoverySnapshotDump {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Snapshot,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    Assert-TicketboxC07RecoverySnapshotAlive $Snapshot
    if (
        -not (Test-TicketboxPathWithin $OutputPath $Context.Paths.PartialRoot)
    ) {
        throw "C07 recovery dump path 越出本次 partial generation。"
    }
    Assert-NoTicketboxAncestorReparsePoints $OutputPath
    if ((Get-TicketboxPathEntryKindNoFollow $OutputPath) -cne "Missing") {
        throw "C07 recovery dump target 已存在或不是安全普通路径。"
    }
    if (
        $Snapshot.SnapshotId -cnotmatch (
            "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}$"
        )
    ) {
        throw "C07 recovery 拒绝不可信 exported snapshot ID。"
    }
    $exitCode = Invoke-TicketboxC07WithPlainSecret `
        -Secret $SuperuserPassword `
        -Action {
            param([string]$PlainPassword)
            return Invoke-TicketboxWithPgPassFile `
                -DatabaseUrl $Context.DatabaseUrl `
                -Password $PlainPassword `
                -Action {
                    param([string]$ProtectedDatabaseUrl)
                    $result = Invoke-TicketboxBoundedNativeProcess `
                        -FilePath $Context.PgDumpPath `
                        -Arguments @(
                            "--no-password",
                            "--lock-wait-timeout=30000",
                            "--format=custom",
                            "--no-owner",
                            "--no-privileges",
                            "--snapshot=$($Snapshot.SnapshotId)",
                            "--file", $OutputPath,
                            "--dbname", $ProtectedDatabaseUrl
                        ) `
                        -TimeoutMilliseconds (
                            Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
                                -MaximumMilliseconds (
                                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                                ) `
                                -Label "C07 recovery pg_dump"
                        ) `
                        -Label "C07 recovery pg_dump exported snapshot" `
                        -HeartbeatOperation (
                            Get-TicketboxC07RecoveryHeartbeatOperation $Context
                        )
                    return [int]$result.ExitCode
                }
        }
    if ($exitCode -ne 0) {
        throw "C07 recovery pg_dump 失败；原生输出已抑制。"
    }
    Assert-TicketboxC07RecoverySnapshotAlive $Snapshot
    if (
        (Get-TicketboxPathEntryKindNoFollow $OutputPath) -cne "File" -or
        (Get-Item -LiteralPath $OutputPath -Force).Length -le 0
    ) {
        throw "C07 recovery pg_dump 未产生非空普通 archive。"
    }
    Sync-TicketboxDurableArtifactFile $OutputPath
    Protect-TicketboxC07RecoveryFile $OutputPath
    $listResult = Invoke-TicketboxBoundedNativeProcess `
        -FilePath $Context.PgRestorePath `
        -Arguments @("--list", $OutputPath) `
        -TimeoutMilliseconds (
            Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
                -MaximumMilliseconds (
                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                ) `
                -Label "C07 recovery pg_restore list"
        ) `
        -Label "C07 recovery pg_restore --list" `
        -HeartbeatOperation (
            Get-TicketboxC07RecoveryHeartbeatOperation $Context
        )
    if (
        $listResult.ExitCode -ne 0 -or
        [string]::IsNullOrWhiteSpace([string]$listResult.StandardOutput)
    ) {
        throw "C07 recovery archive 未通过 pg_restore --list。"
    }
    $item = Get-Item -LiteralPath $OutputPath -Force
    return [pscustomobject]@{
        FileName = $item.Name
        Sha256 = Get-TicketboxC07RecoveryFileSha256 $OutputPath
        SizeBytes = [int64]$item.Length
        RestoreListSha256 = Get-TicketboxC07RecoveryTextSha256 (
            [string]$listResult.StandardOutput
        )
    }
}

function New-TicketboxC07RecoveryEnvelopeText {
    param([Parameter(Mandatory = $true)][object]$Payload)
    $payloadText = $Payload | ConvertTo-Json -Depth 16 -Compress
    $payloadBytes = [Text.UTF8Encoding]::new($false, $true).GetBytes(
        $payloadText
    )
    $payloadSha256 = Get-TicketboxC07RecoveryBytesSha256 $payloadBytes
    return ([ordered]@{
        schema = $script:TicketboxC07RecoveryEnvelopeSchema
        payload_sha256 = $payloadSha256
        payload_base64 = [Convert]::ToBase64String($payloadBytes)
    } | ConvertTo-Json -Depth 4 -Compress) + "`n"
}

function ConvertFrom-TicketboxC07RecoveryEnvelopeText {
    param([Parameter(Mandatory = $true)][string]$Text)
    if (
        [Text.UTF8Encoding]::new($false).GetByteCount($Text) -gt
        $script:TicketboxC07RecoveryMaximumManifestBytes
    ) {
        throw "C07 recovery manifest 超出大小上限。"
    }
    try {
        $envelope = ConvertFrom-TicketboxC07RecoveryJson $Text
    }
    catch {
        throw "C07 recovery manifest 不是有效 JSON。"
    }
    Assert-TicketboxC07RecoveryExactProperties `
        $envelope `
        @("schema", "payload_sha256", "payload_base64") `
        "C07 recovery manifest envelope"
    if (
        [string]$envelope.schema -cne
        $script:TicketboxC07RecoveryEnvelopeSchema
    ) {
        throw "C07 recovery manifest envelope schema 无效。"
    }
    $declared = [string]$envelope.payload_sha256
    Assert-TicketboxC07RecoverySha256 $declared "C07 recovery manifest payload"
    $payloadBase64 = [string]$envelope.payload_base64
    if (
        [string]::IsNullOrEmpty($payloadBase64) -or
        $payloadBase64.Length -gt
            ($script:TicketboxC07RecoveryMaximumManifestBytes * 2) -or
        $payloadBase64 -cnotmatch "^[A-Za-z0-9+/]+={0,2}$"
    ) {
        throw "C07 recovery manifest payload base64 无效。"
    }
    try {
        $payloadBytes = [Convert]::FromBase64String($payloadBase64)
    }
    catch {
        throw "C07 recovery manifest payload base64 无效。"
    }
    if (
        $payloadBytes.Length -gt
            $script:TicketboxC07RecoveryMaximumManifestBytes -or
        [Convert]::ToBase64String($payloadBytes) -cne $payloadBase64
    ) {
        throw "C07 recovery manifest payload base64 非 canonical。"
    }
    if (
        (Get-TicketboxC07RecoveryBytesSha256 $payloadBytes) -cne
        $declared
    ) {
        throw "C07 recovery manifest payload digest 不一致（acl_hash_only）。"
    }
    try {
        $payloadText = [Text.UTF8Encoding]::new(
            $false,
            $true
        ).GetString($payloadBytes)
        $payload = ConvertFrom-TicketboxC07RecoveryJson $payloadText
    }
    catch {
        throw "C07 recovery manifest payload 不是 canonical UTF-8 JSON。"
    }
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $declared
        Text = $Text
    }
}

function New-TicketboxC07RecoveryPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Snapshot,
        [Parameter(Mandatory = $true)][object]$Capacity,
        [Parameter(Mandatory = $true)][object]$DumpEvidence,
        [Parameter(Mandatory = $true)][object]$MoneyFactsEvidence,
        [Parameter(Mandatory = $true)][object]$InventoryEvidence,
        [Parameter(Mandatory = $true)][object]$CopiesEvidence
    )
    Assert-TicketboxC07RecoverySha256 `
        ([string]$Context.UploadRootBindingSha256) `
        "C07 recovery configured upload-root binding"
    $release = $Context.Authority.ReleaseIdentity
    $receipt = $Context.Authority.Receipt
    $meta = $Snapshot.Meta
    return [ordered]@{
        schema = $script:TicketboxC07RecoveryGenerationSchema
        operation_id = [string]$receipt.operation_id
        generation_id = [string]$receipt.operation_id
        release = [ordered]@{
            fingerprint = [string]$release.Fingerprint
            installation_id = [string]$release.InstallationId
            build_manifest_sha256 = [string]$release.BuildManifestSha256
            backend_version = [string]$release.BackendVersionFloor
        }
        lifecycle = [ordered]@{
            stage = [string]$receipt.stage
            operation_kind =
                [string]$Context.Authority.Descriptor.Payload.operation_kind
            target_alembic_revision =
                [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
            revision_manifest_sha256 =
                [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
            authority_chain_sha256 =
                [string]$receipt.authority_chain_sha256
            freeze_proof_sha256 = [string]$receipt.freeze_proof_sha256
            freeze_heartbeat_sequence =
                [string][int64]$receipt.freeze_heartbeat_sequence
        }
        integrity = [ordered]@{
            scope = $script:TicketboxC07RecoveryIntegrityScope
            malicious_writer_resistance = $false
            upload_root_binding_sha256 =
                [string]$Context.UploadRootBindingSha256
        }
        barrier = [ordered]@{
            mode = "bounded_quiesce_plus_pg_export_snapshot"
            exported_snapshot_id = [string]$Snapshot.SnapshotId
            captured_at_utc = [DateTime]::UtcNow.ToString("o")
        }
        database = [ordered]@{
            name = [string]$meta.database
            cluster_system_identifier =
                [string]$meta.cluster_system_identifier
            source_database_oid = [string]$meta.database_oid
            server_version_num = [string]$meta.server_version_num
            server_id = [string]$meta.server_id
            data_generation = [string]$meta.data_generation
            alembic_heads = @($meta.alembic_heads)
            dump_file = [string]$DumpEvidence.FileName
            dump_sha256 = [string]$DumpEvidence.Sha256
            dump_size_bytes = [string][int64]$DumpEvidence.SizeBytes
            restore_list_sha256 =
                [string]$DumpEvidence.RestoreListSha256
            money_facts_sha256 =
                [string]$MoneyFactsEvidence.money_facts_sha256
        }
        asset_inventory = [ordered]@{
            file = [string]$InventoryEvidence.FileName
            sha256 = [string]$InventoryEvidence.Sha256
            size_bytes = [string][int64]$InventoryEvidence.SizeBytes
            row_count = [string][int64]$InventoryEvidence.RowCount
        }
        original_copies = [ordered]@{
            file = [string]$CopiesEvidence.FileName
            sha256 = [string]$CopiesEvidence.Sha256
            size_bytes = [string][int64]$CopiesEvidence.SizeBytes
            row_count = [string][int64]$CopiesEvidence.RowCount
            asset_directory = "assets"
        }
        thumbnail_policy = [ordered]@{
            authority = "derived_rebuildable_cache"
            copied = $false
            references_audited = $true
        }
        capacity = $Capacity
        completion = [ordered]@{
            state = "generation_ready"
            created_by = "windows_c07_recovery_generation"
            created_at_utc = [DateTime]::UtcNow.ToString("o")
        }
    }
}

function Write-TicketboxC07RecoveryManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][object]$Payload
    )
    $path = Join-Path $Root "manifest.json"
    $text = New-TicketboxC07RecoveryEnvelopeText $Payload
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $manifest = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    if ($manifest.Text -cne $text) {
        throw "C07 recovery manifest 写后复读不一致。"
    }
    return $manifest
}

function Assert-TicketboxC07RecoveryRelativeFile {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$FileName,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][int64]$ExpectedBytes,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (
        $FileName -cnotmatch "^[A-Za-z0-9_.-]{1,128}$" -or
        $FileName -in @(".", "..") -or
        $ExpectedBytes -lt 0
    ) {
        throw "$Label 的相对文件合同无效。"
    }
    Assert-TicketboxC07RecoverySha256 $ExpectedSha256 "$Label digest"
    $path = ConvertTo-TicketboxCanonicalPath (Join-Path $Root $FileName)
    if (
        -not (Test-TicketboxPathWithin $path $Root) -or
        (Test-TicketboxPathEquals $path $Root)
    ) {
        throw "$Label 越出 recovery generation root。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
        throw "$Label 缺失或不是普通 non-reparse 文件。"
    }
    Assert-TicketboxExactFileAcl `
        -Path $path `
        -Accounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    $item = Get-Item -LiteralPath $path -Force
    if (
        $item.Length -ne $ExpectedBytes -or
        (Get-TicketboxC07RecoveryFileSha256 $path) -cne $ExpectedSha256
    ) {
        throw "$Label 的 size/digest 与 manifest 不一致。"
    }
    return $path
}

function Get-TicketboxC07RecoveryExpectedLifecycleBinding {
    param([Parameter(Mandatory = $true)][object]$Context)

    $receipt = $Context.Authority.Receipt
    $stage = [string]$receipt.stage
    $expectedLifecycleChain = ""
    $expectedFreezeProofSha256 = ""
    $expectedFreezeHeartbeatSequence = [int64]-1
    $expectedManifestSha256 = ""
    $stageEvidenceSha256 = ""
    if ($stage -ceq "writers_frozen") {
        if (
            [int64]$receipt.stage_sequence -ne 1 -or
            [string]$receipt.previous_stage -cne "captured"
        ) {
            throw "C07 recovery generation reader 只接受 seq1 writers_frozen。"
        }
        if ([string]$receipt.transition_kind -ceq "takeover") {
            if (
                [int64]$receipt.coordinator_binding_sequence -lt 1 -or
                [int64]$receipt.freeze_proof_binding_sequence -ne
                    [int64]$receipt.coordinator_binding_sequence
            ) {
                throw "C07 recovery generation takeover 未绑定当前 writer fence。"
            }
            # A READY generation may have been durably published immediately
            # before the prior coordinator died.  Its manifest is the immutable
            # generation fact; the replacement coordinator's proof only proves
            # that the writer fence is still live.  Read-TicketboxC07Authority
            # has already validated that current proof/window, so do not make
            # the old generation pretend it was created by the new process.
        }
        elseif ([string]$receipt.transition_kind -ceq "stage") {
            $expectedLifecycleChain = [string]$receipt.authority_chain_sha256
            $expectedFreezeProofSha256 = [string]$receipt.freeze_proof_sha256
            $expectedFreezeHeartbeatSequence =
                [int64]$receipt.freeze_heartbeat_sequence
        }
        else {
            throw "C07 writers_frozen receipt transition kind 无效。"
        }
    }
    elseif (
        $stage -in @(
            "recovery_generation_ready",
            "isolated_restore_verified",
            "ddl_started",
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified"
        )
    ) {
        if ($stage -ceq "recovery_generation_ready") {
            if (
                [int64]$receipt.stage_sequence -ne 2 -or
                [string]$receipt.previous_stage -cne "writers_frozen"
            ) {
                throw (
                    "C07 recovery generation reader 只接受 " +
                    "seq2 recovery_generation_ready。"
                )
            }
        }
        elseif ($stage -ceq "isolated_restore_verified") {
            if (
                [int64]$receipt.stage_sequence -ne 3 -or
                [string]$receipt.previous_stage -cne
                    "recovery_generation_ready"
            ) {
                throw (
                    "C07 isolated restore reader 只接受 " +
                    "seq3 isolated_restore_verified。"
                )
            }
        }
        elseif (
            $stage -ceq "ddl_started" -and
            [int64]$receipt.stage_sequence -ne 4 -or
            (
                $stage -ceq "ddl_started" -and
                [string]$receipt.previous_stage -cne
                    "isolated_restore_verified"
            )
        ) {
            throw "C07 production recovery reader 只接受 seq4 ddl_started。"
        }
        elseif (
            $stage -ceq "target_committed" -and
            [int64]$receipt.stage_sequence -ne 5
        ) {
            throw "C07 source recovery reader target_committed sequence 无效。"
        }
        elseif (
            $stage -ceq "target_recovery_generation_ready" -and
            [int64]$receipt.stage_sequence -ne 6
        ) {
            throw "C07 source recovery reader target generation sequence 无效。"
        }
        elseif (
            $stage -ceq "target_isolated_restore_verified" -and
            [int64]$receipt.stage_sequence -ne 7
        ) {
            throw "C07 source recovery reader target restore sequence 无效。"
        }
        if (
            $null -eq (
                Get-Command `
                    -Name "Read-TicketboxC07StageEvidence" `
                    -CommandType Function `
                    -ErrorAction SilentlyContinue
            )
        ) {
            throw "C07 production recovery reader 缺少 typed stage-evidence reader。"
        }
        $stageEvidence = Read-TicketboxC07StageEvidence `
            -Authority $Context.Authority `
            -Stage "recovery_generation_ready"
        $evidence = $stageEvidence.Payload
        if (
            [string]$evidence.target_stage -cne
                "recovery_generation_ready" -or
            [string]$evidence.source_stage -cne "writers_frozen" -or
            [int64]$evidence.source_stage_sequence -ne 1
        ) {
            throw (
                "C07 production recovery generation typed evidence " +
                "未绑定 writers_frozen source。"
            )
        }
        try {
            $producer = ConvertFrom-TicketboxC07RecoveryJson (
                [string]$evidence.producer_payload_json
            )
        }
        catch {
            throw "C07 production recovery producer evidence 不是 JSON。"
        }
        Assert-TicketboxC07RecoveryExactProperties `
            $producer `
            @(
                "schema",
                "operation_id",
                "result",
                "database_binding_sha256",
                "operation_kind",
                "alembic_target",
                "revision_manifest_sha256",
                "subject_sha256"
            ) `
            "C07 production recovery producer evidence"
        if (
            [string]$producer.schema -cne
                $script:TicketboxC07RecoveryGenerationSchema -or
            [string]$producer.operation_id -cne
                [string]$receipt.operation_id -or
            [string]$producer.result -cne "generation_ready" -or
            [string]$producer.database_binding_sha256 -cne
                [string]$receipt.database_binding_sha256 -or
            [string]$producer.operation_kind -cne
                [string]$Context.Authority.Descriptor.Payload.operation_kind -or
            [string]$producer.alembic_target -cne
                [string]$Context.Authority.Descriptor.Payload.target_alembic_revision -or
            [string]$producer.revision_manifest_sha256 -cne
                [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
        ) {
            throw "C07 production recovery producer identity 不一致。"
        }
        # The stage evidence commits the exact READY manifest through
        # producer.subject_sha256.  Its source authority chain records the
        # coordinator that performed the stage transition, which may be a
        # takeover coordinator rather than the process that durably published
        # the immutable generation.  Do not conflate those two facts.
        $expectedManifestSha256 = [string]$producer.subject_sha256
        $stageEvidenceSha256 = [string]$stageEvidence.PayloadSha256
        Assert-TicketboxC07RecoveryHostSha256 `
            $expectedManifestSha256 `
            "C07 production recovery manifest subject"
        Assert-TicketboxC07RecoveryHostSha256 `
            $stageEvidenceSha256 `
            "C07 production recovery stage evidence"
    }
    else {
        throw "C07 recovery manifest 不支持当前 lifecycle stage。"
    }
    if (-not [string]::IsNullOrEmpty($expectedLifecycleChain)) {
        Assert-TicketboxC07RecoveryHostSha256 `
            $expectedLifecycleChain `
            "C07 recovery expected lifecycle authority chain"
    }
    if (-not [string]::IsNullOrEmpty($expectedFreezeProofSha256)) {
        Assert-TicketboxC07RecoveryHostSha256 `
            $expectedFreezeProofSha256 `
            "C07 recovery expected writers-frozen proof"
    }
    return [pscustomobject]@{
        AuthorityChainSha256 = $expectedLifecycleChain
        FreezeProofSha256 = $expectedFreezeProofSha256
        FreezeHeartbeatSequence = $expectedFreezeHeartbeatSequence
        ManifestSubjectSha256 = $expectedManifestSha256
        StageEvidenceSha256 = $stageEvidenceSha256
    }
}

function Read-TicketboxC07RecoveryManifest {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$Root
    )
    Assert-NoTicketboxAncestorReparsePoints $Root
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $Root `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    $manifestPath = Join-Path $Root $Context.Paths.ManifestFileName
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $manifestPath `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $manifest = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $manifest.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "generation_id",
            "release",
            "lifecycle",
            "integrity",
            "barrier",
            "database",
            "asset_inventory",
            "original_copies",
            "thumbnail_policy",
            "capacity",
            "completion"
        ) `
        "C07 recovery generation payload"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.release `
        @(
            "fingerprint",
            "installation_id",
            "build_manifest_sha256",
            "backend_version"
        ) `
        "C07 recovery release binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.lifecycle `
        @(
            "stage",
            "operation_kind",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "authority_chain_sha256",
            "freeze_proof_sha256",
            "freeze_heartbeat_sequence"
        ) `
        "C07 recovery lifecycle binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.integrity `
        @(
            "scope",
            "malicious_writer_resistance",
            "upload_root_binding_sha256"
        ) `
        "C07 recovery integrity scope"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.barrier `
        @("mode", "exported_snapshot_id", "captured_at_utc") `
        "C07 recovery snapshot barrier"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.database `
        @(
            "name",
            "cluster_system_identifier",
            "source_database_oid",
            "server_version_num",
            "server_id",
            "data_generation",
            "alembic_heads",
            "dump_file",
            "dump_sha256",
            "dump_size_bytes",
            "restore_list_sha256",
            "money_facts_sha256"
        ) `
        "C07 recovery database binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.asset_inventory `
        @("file", "sha256", "size_bytes", "row_count") `
        "C07 recovery asset inventory binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.original_copies `
        @(
            "file",
            "sha256",
            "size_bytes",
            "row_count",
            "asset_directory"
        ) `
        "C07 recovery original copies binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.thumbnail_policy `
        @("authority", "copied", "references_audited") `
        "C07 recovery thumbnail policy"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.completion `
        @("state", "created_by", "created_at_utc") `
        "C07 recovery completion binding"

    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$payload.release.fingerprint) `
        "C07 recovery release fingerprint"
    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$payload.release.build_manifest_sha256) `
        "C07 recovery build manifest"
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.release.installation_id) `
        "C07 recovery installation ID"
    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$payload.lifecycle.authority_chain_sha256) `
        "C07 recovery lifecycle authority chain"
    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$payload.lifecycle.freeze_proof_sha256) `
        "C07 recovery writers-frozen proof"
    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$payload.lifecycle.revision_manifest_sha256) `
        "C07 recovery revision manifest"
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.database.server_id) `
        "C07 recovery logical server ID"
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.database.data_generation) `
        "C07 recovery logical data generation"
    Assert-TicketboxC07RecoveryCapacityEvidence $payload.capacity

    $inventoryRows = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.asset_inventory.row_count `
        "C07 recovery asset inventory rows"
    $copyRows = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.original_copies.row_count `
        "C07 recovery original copy rows"
    $inventoryBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.asset_inventory.size_bytes `
        "C07 recovery asset inventory bytes"
    $copyInventoryBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.original_copies.size_bytes `
        "C07 recovery original copy inventory bytes"
    $dumpBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.database.dump_size_bytes `
        "C07 recovery database dump bytes"
    if (
        $inventoryRows -gt
            [uint64]$script:TicketboxC07RecoveryMaximumInventoryRows -or
        $copyRows -gt $inventoryRows -or
        $dumpBytes -eq 0 -or
        $inventoryBytes -gt [uint64][int64]::MaxValue -or
        $copyInventoryBytes -gt [uint64][int64]::MaxValue -or
        $dumpBytes -gt [uint64][int64]::MaxValue
    ) {
        throw "C07 recovery manifest row/byte bounds 无效。"
    }

    $receipt = $Context.Authority.Receipt
    $lifecycleBinding =
        Get-TicketboxC07RecoveryExpectedLifecycleBinding $Context
    $expectedLifecycleChain =
        [string]$lifecycleBinding.AuthorityChainSha256
    $expectedFreezeProofSha256 =
        [string]$lifecycleBinding.FreezeProofSha256
    $expectedFreezeSequence =
        [int64]$lifecycleBinding.FreezeHeartbeatSequence
    if (
        -not [string]::IsNullOrEmpty(
            [string]$lifecycleBinding.ManifestSubjectSha256
        ) -and
        ([string]$manifest.PayloadSha256).ToUpperInvariant() -cne
            [string]$lifecycleBinding.ManifestSubjectSha256
    ) {
        throw (
            "C07 production recovery stage evidence subject 与 " +
            "READY manifest 不一致。"
        )
    }

    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryGenerationSchema -or
        [string]$payload.operation_id -cne
            [string]$Context.Authority.Receipt.operation_id -or
        [string]$payload.generation_id -cne
            [string]$Context.Authority.Receipt.operation_id -or
        [string]$payload.lifecycle.operation_kind -cne
            [string]$Context.Authority.Descriptor.Payload.operation_kind -or
        [string]$payload.lifecycle.target_alembic_revision -cne
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.lifecycle.revision_manifest_sha256 -cne
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.release.fingerprint -cne
            [string]$Context.Authority.ReleaseIdentity.Fingerprint -or
        [string]$payload.release.installation_id -cne
            [string]$Context.Authority.ReleaseIdentity.InstallationId -or
        [string]$payload.release.build_manifest_sha256 -cne
            [string]$Context.Authority.ReleaseIdentity.BuildManifestSha256 -or
        [string]$payload.release.backend_version -cne
            [string]$Context.Authority.ReleaseIdentity.BackendVersionFloor -or
        [string]$payload.lifecycle.stage -cne "writers_frozen" -or
        (
            -not [string]::IsNullOrEmpty($expectedFreezeProofSha256) -and
            [string]$payload.lifecycle.freeze_proof_sha256 -cne
                $expectedFreezeProofSha256
        ) -or
        (
            -not [string]::IsNullOrEmpty($expectedLifecycleChain) -and
            [string]$payload.lifecycle.authority_chain_sha256 -cne
                $expectedLifecycleChain
        ) -or
        (
            $expectedFreezeSequence -ge 0 -and
            [int64]$payload.lifecycle.freeze_heartbeat_sequence -ne
                $expectedFreezeSequence
        ) -or
        [string]$payload.integrity.scope -cne
            $script:TicketboxC07RecoveryIntegrityScope -or
        [bool]$payload.integrity.malicious_writer_resistance -or
        [string]$payload.integrity.upload_root_binding_sha256 -cne
            [string]$Context.UploadRootBindingSha256 -or
        [string]$payload.barrier.mode -cne
            "bounded_quiesce_plus_pg_export_snapshot" -or
        [string]$payload.barrier.exported_snapshot_id -cnotmatch
            "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}$" -or
        [string]$payload.database.name -cne
            $script:TicketboxC07RecoveryDatabaseName -or
        [string]$payload.database.cluster_system_identifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$payload.database.source_database_oid -cne
            [string]$Context.DatabaseIdentity.DatabaseOid -or
        [string]$payload.database.server_version_num -cnotmatch
            "^[1-9][0-9]{4,6}$" -or
        @($payload.database.alembic_heads).Count -ne 1 -or
        [string]@($payload.database.alembic_heads)[0] -cne
            [string]$Context.Authority.Descriptor.Payload.source_alembic_revision -or
        [string]$payload.database.dump_file -cne
            $Context.Paths.DumpFileName -or
        [string]$payload.asset_inventory.file -cne
            $Context.Paths.InventoryFileName -or
        [string]$payload.original_copies.file -cne
            $Context.Paths.CopiesFileName -or
        [string]$payload.original_copies.asset_directory -cne
            $Context.Paths.AssetsLeaf -or
        [string]$payload.completion.state -cne "generation_ready" -or
        [string]$payload.completion.created_by -cne
            "windows_c07_recovery_generation" -or
        [string]$payload.thumbnail_policy.authority -cne
            "derived_rebuildable_cache" -or
        [bool]$payload.thumbnail_policy.copied -or
        -not [bool]$payload.thumbnail_policy.references_audited
    ) {
        throw "C07 recovery manifest identity/authority binding 不一致。"
    }
    foreach ($digest in @(
        [pscustomobject]@{
            Value = [string]$payload.database.dump_sha256
            Label = "C07 recovery database dump"
        },
        [pscustomobject]@{
            Value = [string]$payload.asset_inventory.sha256
            Label = "C07 recovery asset inventory"
        },
        [pscustomobject]@{
            Value = [string]$payload.original_copies.sha256
            Label = "C07 recovery original copy inventory"
        },
        [pscustomobject]@{
            Value = [string]$payload.integrity.upload_root_binding_sha256
            Label = "C07 recovery configured upload-root binding"
        }
    )) {
        Assert-TicketboxC07RecoverySha256 $digest.Value $digest.Label
    }
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.database.restore_list_sha256) `
        "C07 recovery restore list"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.database.money_facts_sha256) `
        "C07 recovery canonical money facts"

    $dumpPath = Assert-TicketboxC07RecoveryRelativeFile `
        -Root $Root `
        -FileName ([string]$payload.database.dump_file) `
        -ExpectedSha256 ([string]$payload.database.dump_sha256) `
        -ExpectedBytes ([int64]$payload.database.dump_size_bytes) `
        -Label "C07 recovery database dump"
    $inventoryPath = Assert-TicketboxC07RecoveryRelativeFile `
        -Root $Root `
        -FileName ([string]$payload.asset_inventory.file) `
        -ExpectedSha256 ([string]$payload.asset_inventory.sha256) `
        -ExpectedBytes ([int64]$payload.asset_inventory.size_bytes) `
        -Label "C07 recovery asset inventory"
    $copiesPath = Assert-TicketboxC07RecoveryRelativeFile `
        -Root $Root `
        -FileName ([string]$payload.original_copies.file) `
        -ExpectedSha256 ([string]$payload.original_copies.sha256) `
        -ExpectedBytes ([int64]$payload.original_copies.size_bytes) `
        -Label "C07 recovery original copies inventory"
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $manifest.PayloadSha256
        ManifestPath = $manifestPath
        DumpPath = $dumpPath
        InventoryPath = $inventoryPath
        CopiesPath = $copiesPath
        Root = $Root
        LifecycleAuthorityChainSha256 =
            [string]$payload.lifecycle.authority_chain_sha256
        StageEvidenceSha256 =
            [string]$lifecycleBinding.StageEvidenceSha256
    }
}

function Assert-TicketboxC07RecoveryGenerationFiles {
    param([Parameter(Mandatory = $true)][object]$Generation)
    $payload = $Generation.Payload
    $copyCount = [int]$payload.original_copies.row_count
    $copies = Read-TicketboxC07RecoveryJsonLines `
        -Path $Generation.CopiesPath `
        -Kind "copies" `
        -ExpectedRows $copyCount
    $assetsRoot = ConvertTo-TicketboxCanonicalPath (
        Join-Path $Generation.Root $payload.original_copies.asset_directory
    )
    Assert-NoTicketboxAncestorReparsePoints $assetsRoot
    if ((Get-TicketboxPathEntryKindNoFollow $assetsRoot) -cne "Directory") {
        throw "C07 recovery original assets directory 缺失或经过 reparse。"
    }
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $assetsRoot `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    $expected = New-Object "System.Collections.Generic.HashSet[string]" (
        [StringComparer]::Ordinal
    )
    foreach ($record in @($copies)) {
        Assert-TicketboxC07RecoveryExactProperties `
            $record `
            @(
                "expense_public_id",
                "ledger_id",
                "image_reference",
                "package_file",
                "source_sha256",
                "database_expected_sha256",
                "size_bytes",
                "thumbnail_reference",
                "thumbnail_state"
            ) `
            "C07 recovery copy record"
        $fileName = [string]$record.package_file
        if ($fileName -cnotmatch "^asset-[0-9]{8}\.bin$") {
            throw "C07 recovery copy record 含不安全 package filename。"
        }
        Assert-TicketboxC07RecoveryCanonicalGuid `
            ([string]$record.expense_public_id) `
            "C07 recovery copy expense ID"
        if ([string]$record.ledger_id -cnotmatch "^[A-Za-z0-9_-]{1,64}$") {
            throw "C07 recovery copy record ledger ID 无效。"
        }
        Assert-TicketboxC07RecoverySha256 `
            ([string]$record.source_sha256) `
            "C07 recovery copy source"
        if (
            -not [string]::IsNullOrEmpty(
                [string]$record.database_expected_sha256
            )
        ) {
            Assert-TicketboxC07RecoverySha256 `
                ([string]$record.database_expected_sha256) `
                "C07 recovery copy database expected"
        }
        if (-not $expected.Add($fileName)) {
            throw "C07 recovery copy record package filename 重复。"
        }
        Assert-TicketboxC07RecoveryRelativeFile `
            -Root $assetsRoot `
            -FileName $fileName `
            -ExpectedSha256 ([string]$record.source_sha256) `
            -ExpectedBytes ([int64]$record.size_bytes) `
            -Label "C07 recovery original asset" | Out-Null
    }
    $actual = @(
        Get-ChildItem -LiteralPath $assetsRoot -Force |
            ForEach-Object {
                if (
                    $_.PSIsContainer -or
                    (Get-TicketboxPathEntryKindNoFollow $_.FullName) -cne "File"
                ) {
                    throw "C07 recovery assets directory 含未登记或非普通 entry。"
                }
                $_.Name
            }
    )
    if ($actual.Count -ne $expected.Count) {
        throw "C07 recovery assets directory 与 copy inventory 数量不一致。"
    }
    foreach ($name in $actual) {
        if (-not $expected.Contains($name)) {
            throw "C07 recovery assets directory 含未登记文件。"
        }
    }
    [decimal]$copyBytes = 0
    foreach ($record in @($copies)) {
        $copyBytes += [decimal](
            ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
                $record.size_bytes `
                "C07 recovery copy bytes"
        )
    }
    $generationCapacityBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.capacity.asset_generation_copy_bytes `
        "C07 recovery generation asset capacity"
    $isolatedCapacityBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.capacity.asset_isolated_restore_bytes `
        "C07 recovery isolated asset capacity"
    if (
        $copyBytes -gt [decimal][uint64]::MaxValue -or
        [uint64]$copyBytes -ne $generationCapacityBytes -or
        [uint64]$copyBytes -ne $isolatedCapacityBytes
    ) {
        throw "C07 recovery original copy bytes 与 capacity manifest 不一致。"
    }
    return ,$copies
}

function Get-TicketboxC07RecoveryLiveSourceBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )
    $output = Invoke-TicketboxC07Sql `
        -Authority $Context.DatabaseAuthority `
        -Database $script:TicketboxC07RecoveryDatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 recovery live source binding" `
        -TimeoutMilliseconds (
            Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
                -MaximumMilliseconds (
                    $script:TicketboxC07RecoverySnapshotTimeoutMilliseconds
                ) `
                -Label "C07 live source binding"
        ) `
        -Sql @"
SELECT 'TBX_META:' || replace(
  encode(
    convert_to(
      json_build_object(
        'database', current_database(),
        'database_oid', (
          SELECT oid::text FROM pg_database WHERE datname = current_database()
        ),
        'cluster_system_identifier', (
          SELECT system_identifier::text FROM pg_control_system()
        ),
        'server_id', (
          SELECT value FROM app_meta WHERE key = 'server_id'
        ),
        'data_generation', (
          SELECT value FROM app_meta WHERE key = 'data_generation'
        ),
        'alembic_heads', (
          SELECT COALESCE(json_agg(version_num ORDER BY version_num), '[]'::json)
          FROM alembic_version
        )
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
);
"@
    $lines = @(
        $output -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if (
        $lines.Count -ne 1 -or
        -not $lines[0].StartsWith(
            "TBX_META:",
            [StringComparison]::Ordinal
        )
    ) {
        throw "C07 recovery live source binding 返回未登记 evidence。"
    }
    $meta = ConvertFrom-TicketboxC07RecoveryBase64Json `
        -Text $lines[0].Substring("TBX_META:".Length) `
        -Label "C07 recovery live source binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $meta `
        @(
            "database",
            "database_oid",
            "cluster_system_identifier",
            "server_id",
            "data_generation",
            "alembic_heads"
        ) `
        "C07 recovery live source binding"
    return $meta
}

function Assert-TicketboxC07RecoveryLiveSourceBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )
    $meta = Get-TicketboxC07RecoveryLiveSourceBinding `
        -Context $Context `
        -SuperuserPassword $SuperuserPassword
    $expected = $Generation.Payload.database
    if (
        [string]$meta.database -cne
            $script:TicketboxC07RecoveryDatabaseName -or
        [string]$meta.database_oid -cne
            [string]$Context.DatabaseIdentity.DatabaseOid -or
        [string]$meta.cluster_system_identifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$meta.database_oid -cne
            [string]$expected.source_database_oid -or
        [string]$meta.server_id -cne [string]$expected.server_id -or
        [string]$meta.data_generation -cne
            [string]$expected.data_generation -or
        [string]::Join("`n", @($meta.alembic_heads)) -cne
            [string]::Join("`n", @($expected.alembic_heads))
    ) {
        throw (
            "C07 recovery generation 不再绑定当前 live source " +
            "database/logical generation。"
        )
    }
}

function Write-TicketboxC07RecoveryCleanupMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][ValidateSet(
            "cleanup_pending",
            "cleaned"
        )][string]$State
    )
    $payload = [ordered]@{
        schema = $script:TicketboxC07RecoveryCleanupSchema
        operation_id = $OperationId
        state = $State
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Assert-NoTicketboxAncestorReparsePoints $Paths.CleanupPath
    $kind = Get-TicketboxPathEntryKindNoFollow $Paths.CleanupPath
    if ($kind -cnotin @("Missing", "File")) {
        throw "C07 recovery cleanup marker target 不安全。"
    }
    if ($kind -ceq "File") {
        Read-TicketboxC07RecoveryCleanupMarker `
            -Paths $Paths `
            -OperationId $OperationId | Out-Null
    }
    $text = New-TicketboxC07RecoveryEnvelopeText $payload
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Paths.CleanupPath `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -ReplaceExisting:($kind -ceq "File")
}

function Read-TicketboxC07RecoveryCleanupMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][string]$OperationId
    )
    $canonicalOperationId = ConvertTo-TicketboxC07CanonicalOperationId (
        $OperationId
    )
    Assert-NoTicketboxAncestorReparsePoints $Paths.CleanupPath
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $Paths.CleanupPath `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $envelope = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $envelope.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @("schema", "operation_id", "state", "updated_at_utc") `
        "C07 recovery cleanup marker"
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryCleanupSchema -or
        [string]$payload.operation_id -cne $canonicalOperationId -or
        [string]$payload.state -cnotin @("cleanup_pending", "cleaned")
    ) {
        throw "C07 recovery cleanup marker authority binding 无效。"
    }
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
    }
}

function Clear-TicketboxC07RecoveryPartialGeneration {
    param(
        [Parameter(Mandatory = $true)][object]$Context
    )
    $paths = $Context.Paths
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    if (
        -not (Test-TicketboxPathWithin $paths.PartialRoot $paths.GenerationRoot) -or
        (Test-TicketboxPathEquals $paths.PartialRoot $paths.GenerationRoot)
    ) {
        throw "C07 recovery partial cleanup target 越界。"
    }
    if (Test-Path -LiteralPath $paths.PartialRoot) {
        try {
            Remove-TicketboxTreeExact -Path $paths.PartialRoot
        }
        catch {
            Write-TicketboxC07RecoveryCleanupMarker `
                -Paths $paths `
                -OperationId $operationId `
                -State "cleanup_pending"
            return [pscustomobject]@{
                State = "cleanup_pending"
                Error = $_.Exception.Message
            }
        }
    }
    if (Test-Path -LiteralPath $paths.CleanupPath) {
        Read-TicketboxC07RecoveryCleanupMarker `
            -Paths $paths `
            -OperationId $operationId | Out-Null
        Remove-TicketboxProtectedUtf8Artifact `
            -Path $paths.CleanupPath `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    }
    return [pscustomobject]@{
        State = "cleaned"
        Error = ""
    }
}

function Invoke-TicketboxC07RecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][scriptblock]$MoneyFactsAction
    )
    $context = Get-TicketboxC07RecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages @("writers_frozen")
    Initialize-TicketboxC07RecoveryGenerationRoot $context.Paths | Out-Null

    if (Test-Path -LiteralPath $context.Paths.ReadyRoot) {
        if (Test-Path -LiteralPath $context.Paths.PartialRoot) {
            throw (
                "C07 recovery 同时存在 READY 与 partial generation；" +
                "拒绝猜测权威。"
            )
        }
        if (Test-Path -LiteralPath $context.Paths.CleanupPath) {
            throw (
                "C07 recovery READY 与 cleanup marker 同时存在；" +
                "拒绝把未闭合清理当可复用 generation。"
            )
        }
        $existing = Read-TicketboxC07RecoveryManifest `
            -Context $context `
            -Root $context.Paths.ReadyRoot
        Assert-TicketboxC07RecoveryGenerationFiles $existing | Out-Null
        Assert-TicketboxC07RecoveryLiveSourceBinding `
            -Context $context `
            -Generation $existing `
            -SuperuserPassword $SuperuserPassword
        $existingRemaining =
            Get-TicketboxC07RemainingMaintenanceMilliseconds `
                -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                -MaximumMilliseconds (
                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                ) `
                -Label "C07 reused source recovery money facts"
        $existingAuthoritySha256 =
            [string]$context.Authority.Receipt.authority_chain_sha256
        $existingFacts = & $MoneyFactsAction `
            $context.DatabaseAuthority `
            $MigratorPassword `
            $script:TicketboxC07RecoveryDatabaseName `
            ([string]$context.Authority.Receipt.operation_id) `
            "" `
            $ExpectedSourceRevision `
            $context.MaintenanceDeadlineUtc `
            $existingRemaining `
            $existingAuthoritySha256 `
            ""
        Assert-TicketboxC07TargetMoneyFactsResult `
            -Evidence $existingFacts `
            -Context $context `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -SnapshotId "" `
            -ExpectedRevision $ExpectedSourceRevision `
            -MaximumRemainingCeilingMilliseconds $existingRemaining `
            -MaintenanceAuthoritySha256 $existingAuthoritySha256 | Out-Null
        if (
            [string]$existingFacts.money_facts_sha256 -cne
            [string]$existing.Payload.database.money_facts_sha256
        ) {
            throw "C07 recovery reused generation money facts 已与 live source 漂移。"
        }
        return [pscustomobject]@{
            State = "generation_ready"
            Reused = $true
            OperationId = [string]$context.Authority.Receipt.operation_id
            GenerationRoot = $context.Paths.ReadyRoot
            EvidenceSha256 = $existing.PayloadSha256
        }
    }
    $cleanup = Clear-TicketboxC07RecoveryPartialGeneration $context
    if ($cleanup.State -cne "cleaned") {
        throw "C07 recovery partial cleanup_pending；拒绝重入或生成 READY。"
    }

    $snapshot = $null
    $partialCreated = $false
    try {
        Assert-TicketboxC07RecoveryMaintenanceBoundary `
            -Authority $context.Authority
        $snapshot = Open-TicketboxC07RecoverySnapshot `
            -Context $context `
            -SuperuserPassword $SuperuserPassword
        if (-not [bool]$snapshot.FenceCutVerified) {
            throw "C07 snapshot 未证明同 session advisory-lock writer cut。"
        }
        $moneyRemaining =
            Get-TicketboxC07RemainingMaintenanceMilliseconds `
                -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                -MaximumMilliseconds (
                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                ) `
                -Label "C07 source generation money facts"
        $moneyAuthoritySha256 =
            [string]$context.Authority.Receipt.authority_chain_sha256
        $moneyFactsEvidence = & $MoneyFactsAction `
            $context.DatabaseAuthority `
            $MigratorPassword `
            $script:TicketboxC07RecoveryDatabaseName `
            ([string]$context.Authority.Receipt.operation_id) `
            ([string]$snapshot.SnapshotId) `
            $ExpectedSourceRevision `
            $context.MaintenanceDeadlineUtc `
            $moneyRemaining `
            $moneyAuthoritySha256 `
            ""
        Assert-TicketboxC07TargetMoneyFactsResult `
            -Evidence $moneyFactsEvidence `
            -Context $context `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -SnapshotId ([string]$snapshot.SnapshotId) `
            -ExpectedRevision $ExpectedSourceRevision `
            -MaximumRemainingCeilingMilliseconds $moneyRemaining `
            -MaintenanceAuthoritySha256 $moneyAuthoritySha256 | Out-Null
        $assetPlan = Get-TicketboxC07RecoveryAssetSourcePlan `
            -Inventory @($snapshot.Assets) `
            -UploadRoot $context.UploadRoot
        $capacity = Get-TicketboxC07RecoveryCapacityPlan `
            -Context $context `
            -Snapshot $snapshot `
            -AssetBytes $assetPlan.SourceBytes

        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $context.Paths.PartialRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
        $partialCreated = $true
        $assetsRoot = Join-Path `
            $context.Paths.PartialRoot `
            $context.Paths.AssetsLeaf
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $assetsRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null

        $dumpEvidence = Invoke-TicketboxC07RecoverySnapshotDump `
            -Context $context `
            -Snapshot $snapshot `
            -SuperuserPassword $SuperuserPassword `
            -OutputPath (
                Join-Path `
                    $context.Paths.PartialRoot `
                    $context.Paths.DumpFileName
            )
        $inventoryEvidence = Write-TicketboxC07RecoveryJsonLines `
            -Path (
                Join-Path `
                    $context.Paths.PartialRoot `
                    $context.Paths.InventoryFileName
            ) `
            -Records @($assetPlan.Inventory) `
            -Kind "inventory"

        $copyRecords = New-Object System.Collections.Generic.List[object]
        foreach ($original in @($assetPlan.Originals)) {
            if ($null -ne $script:TicketboxC07ActiveMaintenanceBudget) {
                [void](Get-TicketboxC07RemainingMaintenanceMilliseconds `
                    -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                    -Label "C07 recovery asset copy")
            }
            Assert-TicketboxC07RecoverySnapshotAlive $snapshot
            $record = $original.Record
            $copy = Copy-TicketboxVerifiedArtifact `
                -SourcePath $original.SourcePath `
                -DestinationPath (
                    Join-Path $assetsRoot $original.PackageFile
                ) `
                -ExpectedSourceSha256 ([string]$record.image_sha256) `
                -ExpectedLength ([int64]$original.ExpectedLength) `
                -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
                -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
            $copyRecords.Add([ordered]@{
                expense_public_id = [string]$record.expense_public_id
                ledger_id = [string]$record.ledger_id
                image_reference = [string]$record.image_reference
                package_file = [string]$original.PackageFile
                source_sha256 = [string]$copy.Sha256
                database_expected_sha256 = [string]$record.image_sha256
                size_bytes = [string][int64]$copy.SizeBytes
                thumbnail_reference = [string]$record.thumbnail_reference
                thumbnail_state = [string]$original.ThumbnailState
            })
        }
        $copiesEvidence = Write-TicketboxC07RecoveryJsonLines `
            -Path (
                Join-Path `
                    $context.Paths.PartialRoot `
                    $context.Paths.CopiesFileName
            ) `
            -Records $copyRecords.ToArray() `
            -Kind "copies"
        Assert-TicketboxC07RecoverySnapshotAlive $snapshot
        $payload = New-TicketboxC07RecoveryPayload `
            -Context $context `
            -Snapshot $snapshot `
            -Capacity $capacity `
            -DumpEvidence $dumpEvidence `
            -MoneyFactsEvidence $moneyFactsEvidence `
            -InventoryEvidence $inventoryEvidence `
            -CopiesEvidence $copiesEvidence
        $manifest = Write-TicketboxC07RecoveryManifest `
            -Root $context.Paths.PartialRoot `
            -Payload $payload
        Close-TicketboxC07RecoverySnapshot $snapshot
        $snapshot = $null
        Assert-TicketboxC07RecoveryMaintenanceBoundary `
            -Authority $context.Authority

        $partial = Read-TicketboxC07RecoveryManifest `
            -Context $context `
            -Root $context.Paths.PartialRoot
        Assert-TicketboxC07RecoveryGenerationFiles $partial | Out-Null
        if ($partial.PayloadSha256 -cne $manifest.PayloadSha256) {
            throw "C07 recovery partial validation digest 不一致。"
        }
        Publish-TicketboxVerifiedArtifactDirectory `
            -GenerationRoot $context.Paths.GenerationRoot `
            -PartialRoot $context.Paths.PartialRoot `
            -ReadyRoot $context.Paths.ReadyRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
        $partialCreated = $false
        $ready = Read-TicketboxC07RecoveryManifest `
            -Context $context `
            -Root $context.Paths.ReadyRoot
        Assert-TicketboxC07RecoveryGenerationFiles $ready | Out-Null
        Assert-TicketboxC07RecoveryLiveSourceBinding `
            -Context $context `
            -Generation $ready `
            -SuperuserPassword $SuperuserPassword
        if ($ready.PayloadSha256 -cne $manifest.PayloadSha256) {
            throw "C07 recovery READY 发布后 digest 不一致。"
        }
        return [pscustomobject]@{
            State = "generation_ready"
            Reused = $false
            OperationId = [string]$context.Authority.Receipt.operation_id
            GenerationRoot = $context.Paths.ReadyRoot
            EvidenceSha256 = $ready.PayloadSha256
        }
    }
    catch {
        $failure = $_.Exception
        if ($partialCreated -or (Test-Path -LiteralPath $context.Paths.PartialRoot)) {
            $cleanup = Clear-TicketboxC07RecoveryPartialGeneration $context
            if ($cleanup.State -cne "cleaned") {
                throw [InvalidOperationException]::new(
                    (
                        "C07 recovery generation 失败且 cleanup_pending；" +
                        "原错误已保留在 exception chain。"
                    ),
                    $failure
                )
            }
        }
        [Runtime.ExceptionServices.ExceptionDispatchInfo]::Capture(
            $failure
        ).Throw()
        throw "unreachable"
    }
    finally {
        if ($null -ne $snapshot) {
            Close-TicketboxC07RecoverySnapshot $snapshot
        }
    }
}

function Get-TicketboxC07RestoredInventorySql {
    return @"
SELECT 'TBX_META:' || replace(
  encode(
    convert_to(
      json_build_object(
        'database', current_database(),
        'database_oid', (
          SELECT oid::text FROM pg_database WHERE datname = current_database()
        ),
        'cluster_system_identifier', (
          SELECT system_identifier::text FROM pg_control_system()
        ),
        'server_id', (
          SELECT value FROM app_meta WHERE key = 'server_id'
        ),
        'data_generation', (
          SELECT value FROM app_meta WHERE key = 'data_generation'
        ),
        'alembic_heads', (
          SELECT COALESCE(json_agg(version_num ORDER BY version_num), '[]'::json)
          FROM alembic_version
        )
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
);
SELECT 'TBX_ASSET:' || replace(
  encode(
    convert_to(
      json_build_object(
        'expense_public_id', public_id::text,
        'ledger_id', tenant_id,
        'image_reference', COALESCE(image_path, ''),
        'image_sha256', COALESCE(image_hash, ''),
        'image_deleted', image_deleted_at IS NOT NULL,
        'thumbnail_reference', COALESCE(thumbnail_path, ''),
        'thumbnail_deleted', thumbnail_deleted_at IS NOT NULL
      )::text,
      'UTF8'
    ),
    'base64'
  ),
  E'\n',
  ''
)
FROM expenses
WHERE image_path IS NOT NULL OR thumbnail_path IS NOT NULL
ORDER BY public_id;
"@
}

function Get-TicketboxC07RestoredInventory {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$RestoreIdentity
    )
    $output = Invoke-TicketboxC07Sql `
        -Authority $Context.DatabaseAuthority `
        -Database ([string]$RestoreIdentity.Database) `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (Get-TicketboxC07RestoredInventorySql) `
        -Label "C07 isolated restore asset inventory" `
        -TimeoutMilliseconds (
            Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
                -MaximumMilliseconds (
                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                ) `
                -Label "C07 isolated restore inventory"
        )
    $meta = $null
    $assets = New-Object System.Collections.Generic.List[object]
    foreach ($line in @($output -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.StartsWith("TBX_META:", [StringComparison]::Ordinal)) {
            if ($null -ne $meta) {
                throw "C07 isolated restore metadata 重复。"
            }
            $meta = ConvertFrom-TicketboxC07RecoveryBase64Json `
                -Text $line.Substring("TBX_META:".Length) `
                -Label "C07 isolated restore metadata"
            continue
        }
        if ($line.StartsWith("TBX_ASSET:", [StringComparison]::Ordinal)) {
            if ($assets.Count -ge $script:TicketboxC07RecoveryMaximumInventoryRows) {
                throw "C07 isolated restore asset inventory 超出行数上限。"
            }
            $assets.Add((
                ConvertFrom-TicketboxC07RecoveryBase64Json `
                    -Text $line.Substring("TBX_ASSET:".Length) `
                    -Label "C07 isolated restore asset row"
            ))
            continue
        }
        throw "C07 isolated restore 返回未登记 evidence line。"
    }
    if ($null -eq $meta) {
        throw "C07 isolated restore 缺少 database metadata。"
    }
    return [pscustomobject]@{
        Meta = $meta
        Assets = $assets.ToArray()
    }
}

function Invoke-TicketboxC07RecoveryArchiveRestore {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$RestoreIdentity,
        [Parameter(Mandatory = $true)][string]$DumpPath
    )
    Assert-NoTicketboxAncestorReparsePoints $DumpPath
    if ((Get-TicketboxPathEntryKindNoFollow $DumpPath) -cne "File") {
        throw "C07 isolated restore archive 缺失或不是普通文件。"
    }
    $restoreUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $Context.DatabaseAuthority `
        -Database ([string]$RestoreIdentity.Database) `
        -Role "postgres"
    $exitCode = Invoke-TicketboxC07WithPlainSecret `
        -Secret $SuperuserPassword `
        -Action {
            param([string]$PlainPassword)
            return Invoke-TicketboxWithPgPassFile `
                -DatabaseUrl $restoreUrl `
                -Password $PlainPassword `
                -Action {
                    param([string]$ProtectedDatabaseUrl)
                    $result = Invoke-TicketboxBoundedNativeProcess `
                        -FilePath $Context.PgRestorePath `
                        -Arguments @(
                            "--no-password",
                            "--exit-on-error",
                            "--single-transaction",
                            "--no-owner",
                            "--no-privileges",
                            "--role=ticketbox_owner",
                            "--dbname", $ProtectedDatabaseUrl,
                            $DumpPath
                        ) `
                        -TimeoutMilliseconds (
                            Get-TicketboxC07RecoveryMaintenanceTimeoutMilliseconds `
                                -MaximumMilliseconds (
                                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                                ) `
                                -Label "C07 isolated pg_restore"
                        ) `
                        -Label "C07 isolated pg_restore" `
                        -HeartbeatOperation (
                            Get-TicketboxC07RecoveryHeartbeatOperation $Context
                        )
                    return [int]$result.ExitCode
                }
        }
    if ($exitCode -ne 0) {
        throw "C07 isolated pg_restore 失败；原生输出已抑制。"
    }
}

function Get-TicketboxC07RecoveryRestoreCreateAuthoritySha256 {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$OperationKind,
        [Parameter(Mandatory = $true)][string]$TargetAlembicRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][string]$ClusterSystemIdentifier,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][string]$GenerationPayloadSha256
    )
    $canonical = @(
        "schema=$script:TicketboxC07RecoveryRestoreCreateIntentSchema",
        "operation_id=$OperationId",
        "operation_kind=$OperationKind",
        "target_alembic_revision=$TargetAlembicRevision",
        "revision_manifest_sha256=$RevisionManifestSha256",
        "installation_id=$InstallationId",
        "cluster_system_identifier=$ClusterSystemIdentifier",
        "database=$Database",
        "attempt_id=$AttemptId",
        "generation_payload_sha256=$GenerationPayloadSha256",
        "integrity_scope=$script:TicketboxC07RecoveryIntegrityScope"
    ) -join "`n"
    return Get-TicketboxC07RecoveryTextSha256 $canonical
}

function Read-TicketboxC07RecoveryRestoreCreateIntent {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    $path = $Context.Paths.RestoreCreateIntentPath
    if (
        -not (Test-TicketboxPathWithin `
            $path `
            $Context.Paths.GenerationRoot) -or
        (Test-TicketboxPathEquals $path $Context.Paths.GenerationRoot)
    ) {
        throw "C07 restore create-intent path 越界。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -ceq "Missing") { return $null }
    if ($kind -cne "File") {
        throw "C07 restore create-intent 不是普通文件。"
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $envelope = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $envelope.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "operation_kind",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "installation_id",
            "cluster_system_identifier",
            "database",
            "attempt_id",
            "generation_payload_sha256",
            "create_authority_sha256",
            "database_oid",
            "state",
            "integrity_scope",
            "updated_at_utc"
        ) `
        "C07 restore create-intent"
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $attemptId = [string]$payload.attempt_id
    Assert-TicketboxC07RecoveryCanonicalGuid `
        $attemptId `
        "C07 restore create attempt ID"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.generation_payload_sha256) `
        "C07 restore create generation"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.create_authority_sha256) `
        "C07 restore create authority"
    Assert-TicketboxC07RecoveryHostSha256 `
        ([string]$payload.revision_manifest_sha256) `
        "C07 restore create revision manifest"
    $expectedAuthority = Get-TicketboxC07RecoveryRestoreCreateAuthoritySha256 `
        -OperationId $operationId `
        -OperationKind ([string]$payload.operation_kind) `
        -TargetAlembicRevision ([string]$payload.target_alembic_revision) `
        -RevisionManifestSha256 ([string]$payload.revision_manifest_sha256) `
        -InstallationId (
            [string]$Context.Authority.ReleaseIdentity.InstallationId
        ) `
        -ClusterSystemIdentifier (
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier
        ) `
        -Database (Get-TicketboxC07RestoreDatabaseName `
            -OperationId $operationId `
            -CreateAttemptId $attemptId) `
        -AttemptId $attemptId `
        -GenerationPayloadSha256 ([string]$Generation.PayloadSha256)
    $databaseOid = [string]$payload.database_oid
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryRestoreCreateIntentSchema -or
        [string]$payload.operation_id -cne $operationId -or
        [string]$payload.operation_kind -cne
            [string]$Context.Authority.Descriptor.Payload.operation_kind -or
        [string]$payload.target_alembic_revision -cne
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.revision_manifest_sha256 -cne
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.installation_id -cne
            [string]$Context.Authority.ReleaseIdentity.InstallationId -or
        [string]$payload.cluster_system_identifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$payload.database -cne
            (Get-TicketboxC07RestoreDatabaseName `
                -OperationId $operationId `
                -CreateAttemptId $attemptId) -or
        [string]$payload.generation_payload_sha256 -cne
            [string]$Generation.PayloadSha256 -or
        [string]$payload.create_authority_sha256 -cne
            $expectedAuthority -or
        [string]$payload.state -cnotin @(
            "create_pending",
            "identity_bound",
            "cleanup_pending"
        ) -or
        [string]$payload.integrity_scope -cne
            $script:TicketboxC07RecoveryIntegrityScope
    ) {
        throw "C07 restore create-intent authority binding 不一致。"
    }
    if ([string]$payload.state -ceq "create_pending") {
        if (-not [string]::IsNullOrEmpty($databaseOid)) {
            throw "C07 create_pending intent 不得提前绑定 database OID。"
        }
    }
    else {
        $parsedOid = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
            $databaseOid `
            "C07 restore create-intent database OID"
        if ($parsedOid -lt 1 -or $parsedOid -gt [uint32]::MaxValue) {
            throw "C07 restore create-intent database OID 越界。"
        }
    }
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
        CreateAuthoritySha256 = $expectedAuthority
        AttemptId = $attemptId
        Path = $path
    }
}

function New-TicketboxC07RecoveryRestoreCreateIntent {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $Context.Paths.RestoreCreateIntentPath) -cne "Missing"
    ) {
        throw "C07 restore create-intent 已存在；拒绝覆盖或换 attempt。"
    }
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $attemptId = [Guid]::NewGuid().ToString("D")
    $installationId =
        [string]$Context.Authority.ReleaseIdentity.InstallationId
    $cluster =
        [string]$Context.DatabaseIdentity.ClusterSystemIdentifier
    $database = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $operationId `
        -CreateAttemptId $attemptId
    $generationSha = [string]$Generation.PayloadSha256
    $authoritySha =
        Get-TicketboxC07RecoveryRestoreCreateAuthoritySha256 `
            -OperationId $operationId `
            -OperationKind (
                [string]$Context.Authority.Descriptor.Payload.operation_kind
            ) `
            -TargetAlembicRevision (
                [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
            ) `
            -RevisionManifestSha256 (
                [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
            ) `
            -InstallationId $installationId `
            -ClusterSystemIdentifier $cluster `
            -Database $database `
            -AttemptId $attemptId `
            -GenerationPayloadSha256 $generationSha
    $payload = [ordered]@{
        schema = $script:TicketboxC07RecoveryRestoreCreateIntentSchema
        operation_id = $operationId
        operation_kind =
            [string]$Context.Authority.Descriptor.Payload.operation_kind
        target_alembic_revision =
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
        installation_id = $installationId
        cluster_system_identifier = $cluster
        database = $database
        attempt_id = $attemptId
        generation_payload_sha256 = $generationSha
        create_authority_sha256 = $authoritySha
        database_oid = ""
        state = "create_pending"
        integrity_scope = $script:TicketboxC07RecoveryIntegrityScope
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Context.Paths.RestoreCreateIntentPath `
        -Text (New-TicketboxC07RecoveryEnvelopeText $payload) `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    return Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
}

function Set-TicketboxC07RecoveryRestoreCreateIntentState {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][ValidateSet(
            "identity_bound",
            "cleanup_pending"
        )][string]$State
    )
    Assert-TicketboxC07RestoreIdentity $Identity
    $intent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
    if ($null -eq $intent) {
        throw "C07 restore database mutation 缺少 protected create-intent。"
    }
    $priorState = [string]$intent.Payload.state
    if (
        ($State -ceq "identity_bound" -and
            $priorState -cnotin @("create_pending", "identity_bound")) -or
        ($State -ceq "cleanup_pending" -and
            $priorState -cnotin @("identity_bound", "cleanup_pending"))
    ) {
        throw "C07 restore create-intent state transition 无效。"
    }
    $payload = [ordered]@{
        schema = [string]$intent.Payload.schema
        operation_id = [string]$intent.Payload.operation_id
        operation_kind = [string]$intent.Payload.operation_kind
        target_alembic_revision =
            [string]$intent.Payload.target_alembic_revision
        revision_manifest_sha256 =
            [string]$intent.Payload.revision_manifest_sha256
        installation_id = [string]$intent.Payload.installation_id
        cluster_system_identifier =
            [string]$intent.Payload.cluster_system_identifier
        database = [string]$intent.Payload.database
        attempt_id = [string]$intent.Payload.attempt_id
        generation_payload_sha256 =
            [string]$intent.Payload.generation_payload_sha256
        create_authority_sha256 =
            [string]$intent.Payload.create_authority_sha256
        database_oid = [string][uint32]$Identity.DatabaseOid
        state = $State
        integrity_scope = $script:TicketboxC07RecoveryIntegrityScope
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    if (
        -not [string]::IsNullOrEmpty([string]$intent.Payload.database_oid) -and
        [uint32]$intent.Payload.database_oid -ne [uint32]$Identity.DatabaseOid
    ) {
        throw "C07 restore create-intent 拒绝更换 database OID。"
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $intent.Path `
        -Text (New-TicketboxC07RecoveryEnvelopeText $payload) `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -ReplaceExisting
    return Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
}

function Remove-TicketboxC07RecoveryRestoreCreateIntent {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    $intent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
    if ($null -eq $intent) { return }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $intent.Path `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
}

function New-TicketboxC07RecoveryRestoreDatabaseBound {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $intent = New-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
    $database = [string]$intent.Payload.database
    $expectedDatabase = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $operationId `
        -CreateAttemptId ([string]$intent.AttemptId)
    if ($database -cne $expectedDatabase) {
        throw "C07 restore create-intent 未绑定 canonical attempt database name。"
    }
    Assert-TicketboxC07RestoreAttemptNamespace `
        -Authority $Context.DatabaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -ExpectedDatabase $database | Out-Null
    $liveAfterIntent = Get-TicketboxC07DatabaseIdentity `
        -Authority $Context.DatabaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Database $database
    if ($liveAfterIntent.Exists) {
        throw (
            "C07 restore database 在 protected create-intent 后竞态出现；" +
            "拒绝调用可收编 helper。"
        )
    }
    $identity = New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $operationId `
        -CreateIntent $intent `
        -OperationKind (
            [string]$Context.Authority.Descriptor.Payload.operation_kind
        ) `
        -TargetAlembicRevision (
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
        ) `
        -RevisionManifestSha256 (
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
        )
    $liveAfterHelper = Get-TicketboxC07DatabaseIdentity `
        -Authority $Context.DatabaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Database $database
    if (
        -not $liveAfterHelper.Exists -or
        [string]$liveAfterHelper.ClusterSystemIdentifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$identity.ClusterSystemIdentifier -cne
            [string]$liveAfterHelper.ClusterSystemIdentifier -or
        [string]$identity.Database -cne $database -or
        [uint64]$identity.DatabaseOid -lt 1 -or
        [uint64]$identity.DatabaseOid -gt [uint32]::MaxValue -or
        [uint32]$identity.DatabaseOid -ne
            [uint32]$liveAfterHelper.DatabaseOid
    ) {
        throw (
            "C07 restore helper 返回后 live cluster/name/OID " +
            "未保持 exact identity。"
        )
    }
    $boundIntent = Set-TicketboxC07RecoveryRestoreCreateIntentState `
        -Context $Context `
        -Generation $Generation `
        -Identity $identity `
        -State "identity_bound"
    return [pscustomobject]@{
        Schema = [string]$identity.Schema
        OperationId = [string]$identity.OperationId
        ClusterSystemIdentifier =
            [string]$identity.ClusterSystemIdentifier
        Database = [string]$identity.Database
        DatabaseOid = [uint32]$identity.DatabaseOid
        OwnerRoleOid = [uint32]$identity.OwnerRoleOid
        MigratorRoleOid = [uint32]$identity.MigratorRoleOid
        MarkerPhase = [string]$identity.MarkerPhase
        State = [string]$identity.State
        CreateAttemptId = [string]$boundIntent.AttemptId
        CreateAuthoritySha256 =
            [string]$boundIntent.CreateAuthoritySha256
    }
}

function Read-TicketboxC07RecoveryRestoreIdentityArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    $path = $Context.Paths.RestoreIdentityPath
    if (
        -not (Test-TicketboxPathWithin `
            $path `
            $Context.Paths.GenerationRoot) -or
        (Test-TicketboxPathEquals $path $Context.Paths.GenerationRoot)
    ) {
        throw "C07 recovery restore identity artifact path 越界。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -ceq "Missing") { return $null }
    if ($kind -cne "File") {
        throw "C07 recovery restore identity artifact 不是普通文件。"
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $envelope = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $envelope.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "generation_payload_sha256",
            "create_attempt_id",
            "create_authority_sha256",
            "restore_identity",
            "state",
            "integrity_scope",
            "updated_at_utc"
        ) `
        "C07 recovery restore identity artifact"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.restore_identity `
        @(
            "schema",
            "operation_id",
            "cluster_system_identifier",
            "database",
            "database_oid",
            "owner_role_oid",
            "migrator_role_oid",
            "marker_phase",
            "state"
        ) `
        "C07 recovery protected restore identity"
    $identity = [pscustomobject]@{
        Schema = [string]$payload.restore_identity.schema
        OperationId = [string]$payload.restore_identity.operation_id
        ClusterSystemIdentifier =
            [string]$payload.restore_identity.cluster_system_identifier
        Database = [string]$payload.restore_identity.database
        DatabaseOid = [uint32]$payload.restore_identity.database_oid
        OwnerRoleOid = [uint32]$payload.restore_identity.owner_role_oid
        MigratorRoleOid = [uint32]$payload.restore_identity.migrator_role_oid
        MarkerPhase = [string]$payload.restore_identity.marker_phase
        State = [string]$payload.restore_identity.state
        CreateAttemptId = [string]$payload.create_attempt_id
    }
    Assert-TicketboxC07RestoreIdentity $identity
    $intent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
    if ($null -eq $intent) {
        throw "C07 protected restore identity 缺少 create-intent authority。"
    }
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $identityState = [string]$payload.state
    $intentState = [string]$intent.Payload.state
    $statePairValid = (
        (
            $identityState -ceq "active" -and
            $intentState -cin @("identity_bound", "cleanup_pending")
        ) -or
        (
            $identityState -ceq "cleanup_pending" -and
            $intentState -ceq "cleanup_pending"
        )
    )
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryRestoreIdentitySchema -or
        [string]$payload.operation_id -cne $operationId -or
        [string]$payload.generation_payload_sha256 -cne
            [string]$Generation.PayloadSha256 -or
        [string]$payload.create_attempt_id -cne
            [string]$intent.AttemptId -or
        [string]$payload.create_authority_sha256 -cne
            [string]$intent.CreateAuthoritySha256 -or
        [string]$identity.OperationId -cne $operationId -or
        [string]$identity.ClusterSystemIdentifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$identity.Database -cne
            (Get-TicketboxC07RestoreDatabaseName `
                -OperationId $operationId `
                -CreateAttemptId ([string]$intent.AttemptId)) -or
        [string]$intent.Payload.database_oid -cne
            [string][uint32]$identity.DatabaseOid -or
        $identityState -cne [string]$identity.State -or
        -not $statePairValid -or
        [string]$payload.integrity_scope -cne
            $script:TicketboxC07RecoveryIntegrityScope
    ) {
        throw "C07 recovery protected restore identity binding 不一致。"
    }
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.generation_payload_sha256) `
        "C07 recovery restore generation binding"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.create_authority_sha256) `
        "C07 recovery restore create-intent authority"
    return [pscustomobject]@{
        Identity = $identity
        CreateAttemptId = [string]$intent.AttemptId
        State = if ($intentState -ceq "cleanup_pending") {
            "cleanup_pending"
        }
        else {
            $identityState
        }
        IdentityArtifactState = $identityState
        CreateIntentState = $intentState
        PayloadSha256 = $envelope.PayloadSha256
        Path = $path
    }
}

function Write-TicketboxC07RecoveryRestoreIdentityArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)][object]$Identity
    )
    Assert-TicketboxC07RestoreIdentity $Identity
    $intent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
    if ($null -eq $intent) {
        throw "C07 recovery 拒绝写入无 create-intent 的 restore identity。"
    }
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $expectedIntentState = if ([string]$Identity.State -ceq "active") {
        "identity_bound"
    }
    else {
        "cleanup_pending"
    }
    if (
        [string]$Identity.OperationId -cne $operationId -or
        [string]$Identity.ClusterSystemIdentifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$Identity.Database -cne
            (Get-TicketboxC07RestoreDatabaseName `
                -OperationId $operationId `
                -CreateAttemptId ([string]$intent.AttemptId)) -or
        [string]$intent.Payload.database_oid -cne
            [string][uint32]$Identity.DatabaseOid -or
        [string]$intent.Payload.state -cne $expectedIntentState -or
        [string]$Identity.State -cnotin @("active", "cleanup_pending")
    ) {
        throw "C07 recovery 拒绝写入不匹配的 restore identity。"
    }
    Assert-TicketboxC07RecoverySha256 `
        ([string]$Generation.PayloadSha256) `
        "C07 recovery generation payload"
    $payload = [ordered]@{
        schema = $script:TicketboxC07RecoveryRestoreIdentitySchema
        operation_id = $operationId
        generation_payload_sha256 = [string]$Generation.PayloadSha256
        create_attempt_id = [string]$intent.AttemptId
        create_authority_sha256 =
            [string]$intent.CreateAuthoritySha256
        restore_identity = [ordered]@{
            schema = [string]$Identity.Schema
            operation_id = [string]$Identity.OperationId
            cluster_system_identifier =
                [string]$Identity.ClusterSystemIdentifier
            database = [string]$Identity.Database
            database_oid = [string][uint32]$Identity.DatabaseOid
            owner_role_oid = [string][uint32]$Identity.OwnerRoleOid
            migrator_role_oid = [string][uint32]$Identity.MigratorRoleOid
            marker_phase = [string]$Identity.MarkerPhase
            state = [string]$Identity.State
        }
        state = [string]$Identity.State
        integrity_scope = $script:TicketboxC07RecoveryIntegrityScope
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $path = $Context.Paths.RestoreIdentityPath
    Assert-NoTicketboxAncestorReparsePoints $path
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -cnotin @("Missing", "File")) {
        throw "C07 recovery restore identity artifact target 不安全。"
    }
    if ($kind -ceq "File") {
        $prior = Read-TicketboxC07RecoveryRestoreIdentityArtifact `
            -Context $Context `
            -Generation $Generation
        if (
            [uint32]$prior.Identity.DatabaseOid -ne
                [uint32]$Identity.DatabaseOid -or
            [uint32]$prior.Identity.OwnerRoleOid -ne
                [uint32]$Identity.OwnerRoleOid -or
            [uint32]$prior.Identity.MigratorRoleOid -ne
                [uint32]$Identity.MigratorRoleOid
        ) {
            throw "C07 recovery restore identity artifact 拒绝替换 exact identity。"
        }
    }
    $text = New-TicketboxC07RecoveryEnvelopeText $payload
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -ReplaceExisting:($kind -ceq "File")
    return Read-TicketboxC07RecoveryRestoreIdentityArtifact `
        -Context $Context `
        -Generation $Generation
}

function Repair-TicketboxC07RecoveryRestoreIdentityArtifact {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)][object]$CreateIntent,
        [Parameter(Mandatory = $true)][object]$LiveIdentity
    )
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $database = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $operationId `
        -CreateAttemptId ([string]$CreateIntent.AttemptId)
    $intentState = [string]$CreateIntent.Payload.state
    if (
        $intentState -cnotin @("create_pending", "identity_bound") -or
        -not [bool]$LiveIdentity.Exists -or
        [string]$LiveIdentity.Database -cne $database -or
        [string]$LiveIdentity.ClusterSystemIdentifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [uint64]$LiveIdentity.DatabaseOid -lt 1 -or
        [uint64]$LiveIdentity.DatabaseOid -gt [uint32]::MaxValue -or
        (
            $intentState -ceq "identity_bound" -and
            [string]$CreateIntent.Payload.database_oid -cne
                [string][uint32]$LiveIdentity.DatabaseOid
        )
    ) {
        throw (
            "C07 restore identity repair 缺少 protected intent + " +
            "live cluster/name/OID exact proof。"
        )
    }

    # The database helper is the sole reader of the PostgreSQL ownership marker
    # and role OIDs.  With a pre-existing live database it refuses an absent,
    # foreign, or mismatched marker before mutation; only the same operation's
    # exact registered/active identity can be resumed.
    $identity = New-TicketboxC07RestoreDatabase `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $operationId `
        -CreateIntent $CreateIntent `
        -OperationKind (
            [string]$Context.Authority.Descriptor.Payload.operation_kind
        ) `
        -TargetAlembicRevision (
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
        ) `
        -RevisionManifestSha256 (
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
        )
    $liveAfterRepair = Get-TicketboxC07DatabaseIdentity `
        -Authority $Context.DatabaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Database $database
    if (
        -not [bool]$liveAfterRepair.Exists -or
        [string]$identity.OperationId -cne $operationId -or
        [string]$identity.Database -cne $database -or
        [string]$identity.ClusterSystemIdentifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$liveAfterRepair.ClusterSystemIdentifier -cne
            [string]$identity.ClusterSystemIdentifier -or
        [uint32]$liveAfterRepair.DatabaseOid -ne
            [uint32]$identity.DatabaseOid -or
        [uint32]$LiveIdentity.DatabaseOid -ne
            [uint32]$identity.DatabaseOid -or
        [string]$identity.MarkerPhase -cne "active" -or
        [string]$identity.State -cne "active"
    ) {
        throw "C07 restore identity repair 后 live marker/owner/OID 漂移。"
    }
    $boundIntent = Set-TicketboxC07RecoveryRestoreCreateIntentState `
        -Context $Context `
        -Generation $Generation `
        -Identity $identity `
        -State "identity_bound"
    if (
        [string]$boundIntent.AttemptId -cne
            [string]$CreateIntent.AttemptId -or
        [string]$boundIntent.CreateAuthoritySha256 -cne
            [string]$CreateIntent.CreateAuthoritySha256 -or
        [string]$boundIntent.Payload.database_oid -cne
            [string][uint32]$identity.DatabaseOid
    ) {
        throw "C07 restore identity repair attempt/authority/OID 未保持。"
    }
    return Write-TicketboxC07RecoveryRestoreIdentityArtifact `
        -Context $Context `
        -Generation $Generation `
        -Identity $identity
}

function Clear-TicketboxC07RecoveryRestoreDatabase {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    $operationId = ConvertTo-TicketboxC07CanonicalOperationId (
        [string]$Context.Authority.Receipt.operation_id
    )
    $intent = Read-TicketboxC07RecoveryRestoreCreateIntent `
        -Context $Context `
        -Generation $Generation
    $protected = Read-TicketboxC07RecoveryRestoreIdentityArtifact `
        -Context $Context `
        -Generation $Generation
    if ($null -eq $intent) {
        $namespaceEntries = @(
            Get-TicketboxC07RestoreNamespaceDatabases `
                -Authority $Context.DatabaseAuthority `
                -SuperuserPassword $SuperuserPassword
        )
        if ($namespaceEntries.Count -gt 0 -or $null -ne $protected) {
            return [pscustomobject]@{
                State = "repair_required"
                Database = ""
                Error = (
                    "restore namespace/identity exists without protected " +
                    "create-intent; zero mutation performed"
                )
            }
        }
        return [pscustomobject]@{
            State = "cleaned"
            Database = ""
        }
    }
    $database = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $operationId `
        -CreateAttemptId ([string]$intent.AttemptId)
    if ($null -eq $protected) {
        $live = Get-TicketboxC07DatabaseIdentity `
            -Authority $Context.DatabaseAuthority `
            -SuperuserPassword $SuperuserPassword `
            -Database $database
        if (-not $live.Exists) {
            Remove-TicketboxC07RecoveryRestoreCreateIntent `
                -Context $Context `
                -Generation $Generation
            return [pscustomobject]@{
                State = "cleaned"
                Database = $database
            }
        }
        try {
            $protected =
                Repair-TicketboxC07RecoveryRestoreIdentityArtifact `
                    -Context $Context `
                    -SuperuserPassword $SuperuserPassword `
                    -Generation $Generation `
                    -CreateIntent $intent `
                    -LiveIdentity $live
        }
        catch {
            return [pscustomobject]@{
                State = "repair_required"
                Database = $database
                Error = (
                    "protected intent and live restore identity could not " +
                    "be reconciled; zero destructive mutation performed"
                )
            }
        }
    }
    $result = Remove-TicketboxC07RestoreDatabaseExact `
        -SuperuserPassword $SuperuserPassword `
        -Identity $protected.Identity `
        -CreateAttemptId ([string]$protected.CreateAttemptId)
    if ([string]$result.State -ceq "cleaned") {
        Remove-TicketboxProtectedUtf8Artifact `
            -Path $Context.Paths.RestoreIdentityPath `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
        Remove-TicketboxC07RecoveryRestoreCreateIntent `
            -Context $Context `
            -Generation $Generation
        return $result
    }
    Set-TicketboxC07RecoveryRestoreCreateIntentState `
        -Context $Context `
        -Generation $Generation `
        -Identity $result `
        -State "cleanup_pending" | Out-Null
    Write-TicketboxC07RecoveryRestoreIdentityArtifact `
        -Context $Context `
        -Generation $Generation `
        -Identity $result | Out-Null
    return $result
}

function Assert-TicketboxC07RecoveryAssetReconcile {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Inventory,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Copies
    )
    $copyByExpense = @{}
    foreach ($copy in @($Copies)) {
        $publicId = [string]$copy.expense_public_id
        if ($copyByExpense.ContainsKey($publicId)) {
            throw "C07 recovery 同一 Expense 存在重复 original copy。"
        }
        $copyByExpense[$publicId] = $copy
    }
    $expectedCopies = 0
    foreach ($raw in @($Inventory)) {
        $record = ConvertTo-TicketboxC07AssetInventoryRecord $raw
        $requiresOriginal = (
            -not [bool]$record.image_deleted -and
            -not [string]::IsNullOrEmpty([string]$record.image_reference)
        )
        $hasCopy = $copyByExpense.ContainsKey(
            [string]$record.expense_public_id
        )
        if ($requiresOriginal) {
            $expectedCopies++
            if (-not $hasCopy) {
                throw "C07 isolated restore 的 active Expense 缺少 original copy。"
            }
            $copy = $copyByExpense[[string]$record.expense_public_id]
            if (
                [string]$copy.ledger_id -cne [string]$record.ledger_id -or
                [string]$copy.image_reference -cne
                    [string]$record.image_reference -or
                [string]$copy.thumbnail_reference -cne
                    [string]$record.thumbnail_reference
            ) {
                throw "C07 isolated restore asset owner/reference 对账失败。"
            }
            if (
                [string]$copy.source_sha256 -cne
                [string]$record.image_sha256
            ) {
                throw "C07 isolated restore original digest 与 PostgreSQL 不一致。"
            }
        }
        elseif ($hasCopy) {
            throw "C07 recovery package 为 deleted/nonexistent image 带入多余 bytes。"
        }
    }
    if ($expectedCopies -ne $copyByExpense.Count) {
        throw "C07 recovery copy inventory 含未被 PostgreSQL 引用的 original。"
    }
    return [pscustomobject]@{
        InventoryRows = @($Inventory).Count
        OriginalCopies = $expectedCopies
    }
}

function Initialize-TicketboxC07RecoveryParentDirectories {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Root
    )
    if (
        -not (Test-TicketboxPathWithin $Parent $Root) -or
        (Test-TicketboxPathEquals $Parent $Root)
    ) {
        if (Test-TicketboxPathEquals $Parent $Root) { return }
        throw "C07 isolated asset parent 越出受保护 restore root。"
    }
    $pending = New-Object System.Collections.Generic.List[string]
    $cursor = ConvertTo-TicketboxCanonicalPath $Parent
    while (-not (Test-TicketboxPathEquals $cursor $Root)) {
        if (-not (Test-TicketboxPathWithin $cursor $Root)) {
            throw "C07 isolated asset parent walk 越界。"
        }
        $pending.Insert(0, $cursor)
        $next = Split-Path -Parent $cursor
        if (
            [string]::IsNullOrEmpty($next) -or
            (Test-TicketboxPathEquals $next $cursor)
        ) {
            throw "C07 isolated asset parent walk 未到达 restore root。"
        }
        $cursor = $next
    }
    foreach ($path in $pending.ToArray()) {
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $path `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
    }
}

function Test-TicketboxC07RecoveryIsolatedAssets {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)][object[]]$Inventory,
        [Parameter(Mandatory = $true)][object[]]$Copies
    )
    $root = $Context.Paths.RestoreAssetsRoot
    if (
        -not (Test-TicketboxPathWithin `
            $root `
            $Context.Paths.GenerationRoot) -or
        (Test-TicketboxPathEquals $root $Context.Paths.GenerationRoot)
    ) {
        throw "C07 isolated asset restore root 越界。"
    }
    if (Test-Path -LiteralPath $root) {
        try {
            Remove-TicketboxTreeExact -Path $root
        }
        catch {
            throw [InvalidOperationException]::new(
                "C07 上次 isolated asset restore cleanup_pending。",
                $_.Exception
            )
        }
    }
    $created = $false
    try {
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $root `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
        $created = $true
        $isolatedUploadRoot = Join-Path $root "uploads"
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $isolatedUploadRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null

        $copyByExpense = @{}
        foreach ($copy in @($Copies)) {
            $copyByExpense[[string]$copy.expense_public_id] = $copy
        }
        foreach ($raw in @($Inventory)) {
            $record = ConvertTo-TicketboxC07AssetInventoryRecord $raw
            if (
                [bool]$record.image_deleted -or
                [string]::IsNullOrEmpty([string]$record.image_reference)
            ) {
                continue
            }
            $copy = $copyByExpense[[string]$record.expense_public_id]
            if ($null -eq $copy) {
                throw "C07 isolated asset restore 缺少 package copy mapping。"
            }
            $source = Assert-TicketboxC07RecoveryRelativeFile `
                -Root (
                    Join-Path `
                        $Generation.Root `
                        $Generation.Payload.original_copies.asset_directory
                ) `
                -FileName ([string]$copy.package_file) `
                -ExpectedSha256 ([string]$copy.source_sha256) `
                -ExpectedBytes ([int64]$copy.size_bytes) `
                -Label "C07 isolated asset source"
            $target = Resolve-TicketboxC07RecoveryAssetReference `
                -Reference ([string]$record.image_reference) `
                -LedgerId ([string]$record.ledger_id) `
                -UploadRoot $isolatedUploadRoot `
                -Label "C07 isolated restored Expense.image_path" `
                -AllowMissing
            $parent = Split-Path -Parent $target.Path
            Initialize-TicketboxC07RecoveryParentDirectories `
                -Parent $parent `
                -Root $isolatedUploadRoot
            $targetKind = Get-TicketboxPathEntryKindNoFollow $target.Path
            if ($targetKind -ceq "Missing") {
                Copy-TicketboxVerifiedArtifact `
                    -SourcePath $source `
                    -DestinationPath $target.Path `
                    -ExpectedSourceSha256 ([string]$copy.source_sha256) `
                    -ExpectedLength ([int64]$copy.size_bytes) `
                    -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
                    -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
            }
            elseif ($targetKind -ceq "File") {
                Assert-TicketboxExactFileAcl `
                    -Path $target.Path `
                    -Accounts $script:TicketboxC07RecoveryFullControlAccounts `
                    -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
                if (
                    (Get-TicketboxC07RecoveryFileSha256 $target.Path) -cne
                        [string]$copy.source_sha256 -or
                    (Get-Item -LiteralPath $target.Path -Force).Length -ne
                        [int64]$copy.size_bytes
                ) {
                    throw "C07 duplicate isolated asset reference bytes 冲突。"
                }
            }
            else {
                throw "C07 isolated asset target 不是普通 file/missing。"
            }
        }
        $restoredPlan = Get-TicketboxC07RecoveryAssetSourcePlan `
            -Inventory $Inventory `
            -UploadRoot $isolatedUploadRoot
        if (
            @($restoredPlan.Originals).Count -ne @($Copies).Count -or
            [int64]$restoredPlan.SourceBytes -ne
                [int64]$Generation.Payload.capacity.asset_isolated_restore_bytes
        ) {
            throw "C07 isolated asset restore 行数/bytes 对账失败。"
        }
        return [pscustomobject]@{
            State = "isolated_assets_reconciled"
            OriginalCopies = @($restoredPlan.Originals).Count
            Bytes = [int64]$restoredPlan.SourceBytes
        }
    }
    finally {
        if ($created -or (Test-Path -LiteralPath $root)) {
            try {
                Remove-TicketboxTreeExact -Path $root
            }
            catch {
                throw [InvalidOperationException]::new(
                    (
                        "C07 isolated asset restore cleanup_pending；" +
                        "不得发布 verified evidence。"
                    ),
                    $_.Exception
                )
            }
        }
    }
}

function Read-TicketboxC07RecoveryRestoreEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    $path = $Context.Paths.RestoreEvidencePath
    if (
        -not (Test-TicketboxPathWithin $path $Generation.Root) -or
        (Test-TicketboxPathEquals $path $Generation.Root)
    ) {
        throw "C07 isolated restore evidence path 越出 READY generation。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -ceq "Missing") { return $null }
    if ($kind -cne "File") {
        throw "C07 isolated restore evidence 不是普通文件。"
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $envelope = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $envelope.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "operation_kind",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "installation_id",
            "generation_payload_sha256",
            "source_cluster_system_identifier",
            "source_database_oid",
            "restore_database",
            "restore_database_oid",
            "restore_create_attempt_id",
            "restore_create_authority_sha256",
            "logical_server_id",
            "logical_data_generation",
            "asset_inventory_sha256",
            "asset_inventory_rows",
            "original_copies_verified",
            "isolated_asset_bytes",
            "thumbnails",
            "forward_replay_source_revision",
            "forward_replay_target_revision",
            "forward_replay_result",
            "target_shape_sha256",
            "money_facts_sha256",
            "result",
            "integrity_scope",
            "verified_at_utc"
        ) `
        "C07 isolated restore evidence"
    $expected = $Generation.Payload.database
    $restoreOid = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.restore_database_oid `
        "C07 isolated restore database OID"
    $inventoryRows = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.asset_inventory_rows `
        "C07 isolated restore inventory rows"
    $copyRows = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.original_copies_verified `
        "C07 isolated restore original copies"
    $assetBytes = ConvertTo-TicketboxC07RecoveryUnsignedInt64 `
        $payload.isolated_asset_bytes `
        "C07 isolated restore asset bytes"
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryRestoreEvidenceSchema -or
        [string]$payload.operation_id -cne
            [string]$Context.Authority.Receipt.operation_id -or
        [string]$payload.operation_kind -cne
            [string]$Context.Authority.Descriptor.Payload.operation_kind -or
        [string]$payload.target_alembic_revision -cne
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.revision_manifest_sha256 -cne
            [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256 -or
        [string]$payload.installation_id -cne
            [string]$Context.Authority.ReleaseIdentity.InstallationId -or
        [string]$payload.generation_payload_sha256 -cne
            [string]$Generation.PayloadSha256 -or
        [string]$payload.source_cluster_system_identifier -cne
            [string]$expected.cluster_system_identifier -or
        [string]$payload.source_database_oid -cne
            [string]$expected.source_database_oid -or
        [string]$payload.restore_database -cne
            (Get-TicketboxC07RestoreDatabaseName `
                -OperationId (
                    [string]$Context.Authority.Receipt.operation_id
                ) `
                -CreateAttemptId (
                    [string]$payload.restore_create_attempt_id
                )) -or
        [string]$payload.logical_server_id -cne
            [string]$expected.server_id -or
        [string]$payload.logical_data_generation -cne
            [string]$expected.data_generation -or
        [string]$payload.asset_inventory_sha256 -cne
            [string]$Generation.Payload.asset_inventory.sha256 -or
        $inventoryRows -ne
            [uint64]$Generation.Payload.asset_inventory.row_count -or
        $copyRows -ne
            [uint64]$Generation.Payload.original_copies.row_count -or
        $assetBytes -ne
            [uint64]$Generation.Payload.capacity.asset_isolated_restore_bytes -or
        $restoreOid -eq [uint64]$expected.source_database_oid -or
        $restoreOid -lt 1 -or
        $restoreOid -gt [uint32]::MaxValue -or
        [string]$payload.thumbnails -cne
            "audited_rebuildable_not_copied" -or
        [string]$payload.forward_replay_source_revision -cne
            [string]$Context.Authority.Descriptor.Payload.source_alembic_revision -or
        [string]$payload.forward_replay_target_revision -cne
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.forward_replay_result -cne
            "isolated_forward_replay_verified" -or
        [string]$payload.result -cne "isolated_restore_reconciled" -or
        [string]$payload.integrity_scope -cne
            $script:TicketboxC07RecoveryIntegrityScope
    ) {
        throw "C07 isolated restore durable evidence binding 不一致。"
    }
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.generation_payload_sha256) `
        "C07 isolated restore generation"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.asset_inventory_sha256) `
        "C07 isolated restore asset inventory"
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.restore_create_attempt_id) `
        "C07 isolated restore create attempt"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.restore_create_authority_sha256) `
        "C07 isolated restore create authority"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.target_shape_sha256) `
        "C07 isolated restore target shape"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$payload.money_facts_sha256) `
        "C07 isolated restore canonical money facts"
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
        Path = $path
    }
}

function Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )
    $databases = @(
        Get-TicketboxC07RestoreNamespaceDatabases `
            -Authority $Context.DatabaseAuthority `
            -SuperuserPassword $SuperuserPassword
    )
    if ($databases.Count -ne 0) {
        throw (
            "C07 isolated restore evidence 要求 restore namespace 已完全清除。"
        )
    }
}

function Write-TicketboxC07RecoveryRestoreEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )
    $existing = Read-TicketboxC07RecoveryRestoreEvidence `
        -Context $Context `
        -Generation $Generation
    if ($null -ne $existing) {
        Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
            -Context $Context `
            -SuperuserPassword $SuperuserPassword
        return $existing
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $Context.Paths.RestoreIdentityPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $Context.Paths.RestoreCreateIntentPath) -cne "Missing"
    ) {
        throw (
            "C07 isolated restore create-intent/cleanup identity 尚未清除；" +
            "拒绝发布 durable verified evidence。"
        )
    }
    Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
        -Context $Context `
        -SuperuserPassword $SuperuserPassword
    $text = New-TicketboxC07RecoveryEnvelopeText $Payload
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Context.Paths.RestoreEvidencePath `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    return Read-TicketboxC07RecoveryRestoreEvidence `
        -Context $Context `
        -Generation $Generation
}

function Read-TicketboxC07ProductionRecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword
    )

    $context = Get-TicketboxC07RecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages @(
            "ddl_started",
            "target_committed",
            "target_recovery_generation_ready",
            "target_isolated_restore_verified"
        )
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.ReadyRoot) -cne "Directory" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.PartialRoot) -cne "Missing"
    ) {
        throw (
            "C07 production recovery reader 要求唯一 READY generation，" +
            "不得残留 partial。"
        )
    }
    $generation = Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    Assert-TicketboxC07RecoveryGenerationFiles $generation | Out-Null
    if ([string]$context.Authority.Receipt.stage -ceq "ddl_started") {
        Assert-TicketboxC07RecoveryLiveSourceBinding `
            -Context $context `
            -Generation $generation `
            -SuperuserPassword $SuperuserPassword
    }
    $restoreEvidence = Read-TicketboxC07RecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    if ($null -eq $restoreEvidence) {
        throw (
            "C07 production recovery reader 缺少受保护 " +
            "isolated-restore evidence。"
        )
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.RestoreIdentityPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.RestoreCreateIntentPath) -cne "Missing"
    ) {
        throw (
            "C07 production recovery reader 检出 restore identity/" +
            "create-intent residue。"
        )
    }
    Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
        -Context $context `
        -SuperuserPassword $SuperuserPassword
    return [pscustomobject]@{
        Schema = $script:TicketboxC07ProductionRecoveryGenerationSchema
        OperationId = [string]$context.Authority.Receipt.operation_id
        Result = "production_recovery_generation_verified"
        Payload = $generation.Payload
        PayloadSha256 = [string]$generation.PayloadSha256
        ManifestPath = [string]$generation.ManifestPath
        DumpPath = [string]$generation.DumpPath
        InventoryPath = [string]$generation.InventoryPath
        CopiesPath = [string]$generation.CopiesPath
        Root = [string]$generation.Root
        LifecycleAuthorityChainSha256 =
            [string]$generation.LifecycleAuthorityChainSha256
        StageEvidenceSha256 =
            [string]$generation.StageEvidenceSha256
        SourceDatabaseIdentity = [pscustomobject]@{
            Database = $script:TicketboxC07RecoveryDatabaseName
            ClusterSystemIdentifier =
                [string]$context.DatabaseIdentity.ClusterSystemIdentifier
            DatabaseOid = [uint32]$context.DatabaseIdentity.DatabaseOid
            GenerationPayloadSha256 = [string]$generation.PayloadSha256
        }
        RestoreEvidence = [pscustomobject]@{
            Payload = $restoreEvidence.Payload
            PayloadSha256 = [string]$restoreEvidence.PayloadSha256
            Path = [string]$restoreEvidence.Path
        }
    }
}

function Read-TicketboxC07HistoricalProductionRecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$PredecessorAuthority,
        [Parameter(Mandatory = $true)][object]$SuccessorIntent,
        [AllowNull()][Security.SecureString]$SuperuserPassword
    )

    Assert-TicketboxC07RecoveryDependencies
    if ($null -eq $SuperuserPassword -or $SuperuserPassword.Length -lt 32) {
        throw "C07 historical recovery PostgreSQL authority 缺失或不足 32 个字符。"
    }
    $current = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $current $LifecycleLock
    if (
        [string]$current.Descriptor.Payload.successor_mode -cne
            "forward_repair" -or
        [string]$SuccessorIntent.Payload.successor_mode -cne
            "forward_repair" -or
        [string]$SuccessorIntent.Payload.successor_operation_id -cne
            [string]$current.Receipt.operation_id -or
        [string]$SuccessorIntent.Payload.predecessor_operation_id -cne
            [string]$PredecessorAuthority.Receipt.operation_id -or
        [string]$SuccessorIntent.Payload.predecessor_terminal_receipt_payload_sha256 -cne
            [string]$PredecessorAuthority.Envelope.PayloadSha256 -or
        [string]$SuccessorIntent.Payload.predecessor_terminal_authority_chain_sha256 -cne
            [string]$PredecessorAuthority.Receipt.authority_chain_sha256
    ) {
        throw "C07 historical recovery 未绑定 exact forward-repair successor。"
    }
    $generationStage = Read-TicketboxC07StageEvidence `
        -Authority $PredecessorAuthority `
        -Stage "recovery_generation_ready"
    $restoreStage = Read-TicketboxC07StageEvidence `
        -Authority $PredecessorAuthority `
        -Stage "isolated_restore_verified"
    if (
        [string]$generationStage.PayloadSha256 -cne
            [string]$SuccessorIntent.Payload.predecessor_recovery_generation_evidence_sha256 -or
        [string]$restoreStage.PayloadSha256 -cne
            [string]$SuccessorIntent.Payload.predecessor_isolated_restore_evidence_sha256
    ) {
        throw "C07 historical recovery stage lineage 与 successor intent 不一致。"
    }

    # A failure receipt contains the exact previous receipt hashes but the
    # previous receipt itself is deliberately not mutable state.  Project only
    # the previous monotonic stage needed by the immutable generation reader;
    # the terminal receipt and both stage-evidence envelopes were validated
    # above before this projection is constructed.
    $sourceStage = [string]$PredecessorAuthority.Receipt.previous_stage
    $sourceStageIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        $sourceStage
    )
    if ($sourceStageIndex -lt 3) {
        throw "C07 forward-repair predecessor 尚未完成 source isolated restore。"
    }
    $projectedReceipt = $PredecessorAuthority.Receipt.PSObject.Copy()
    $projectedReceipt.stage = $sourceStage
    $projectedReceipt.stage_sequence = [int64]$sourceStageIndex
    $projectedReceipt.previous_stage =
        [string]$script:TicketboxC07OrderedStages[$sourceStageIndex - 1]
    $projectedReceipt.transition_kind = "stage"
    $projectedReceipt.authority_chain_sha256 =
        [string]$PredecessorAuthority.Receipt.previous_authority_chain_sha256
    $projected = $PredecessorAuthority.PSObject.Copy()
    $projected.Receipt = $projectedReceipt

    $databaseAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection `
        $databaseAuthority `
        $SuperuserPassword
    $databaseIdentity = Get-TicketboxC07DatabaseIdentity `
        -Authority $databaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07RecoveryDatabaseName
    if (-not $databaseIdentity.Exists) {
        throw "C07 historical recovery live database 不存在。"
    }
    $paths = Get-TicketboxC07RecoveryPaths $projected
    $uploadRootAuthority = Read-TicketboxC07RecoveryUploadRootAuthority `
        -Authority $projected `
        -ExpectedConfiguredRoot (
            Resolve-TicketboxC07RecoveryConfiguredUploadRoot $projected
        )
    $context = [pscustomobject]@{
        Authority = $projected
        LifecycleLock = $LifecycleLock
        MaintenanceDeadlineUtc = ""
        DatabaseAuthority = $databaseAuthority
        DatabaseIdentity = $databaseIdentity
        DatabaseUrl = ""
        PgDumpPath = ""
        PgRestorePath = ""
        UploadRoot = [string]$uploadRootAuthority.Root
        UploadRootBindingSha256 =
            [string]$uploadRootAuthority.BindingSha256
        Paths = $paths
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow $paths.ReadyRoot) -cne
            "Directory" -or
        (Get-TicketboxPathEntryKindNoFollow $paths.PartialRoot) -cne
            "Missing"
    ) {
        throw "C07 historical recovery 要求 predecessor 唯一 READY generation。"
    }
    $generation = Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $paths.ReadyRoot
    Assert-TicketboxC07RecoveryGenerationFiles $generation | Out-Null
    $restoreEvidence = Read-TicketboxC07RecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    if ($null -eq $restoreEvidence) {
        throw "C07 historical recovery 缺少 predecessor isolated-restore evidence。"
    }
    $generationProducer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$generationStage.Payload.producer_payload_json) `
        -Label "historical recovery generation producer"
    $restoreProducer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$restoreStage.Payload.producer_payload_json) `
        -Label "historical recovery restore producer"
    if (
        [string]$generation.StageEvidenceSha256 -cne
            [string]$generationStage.PayloadSha256 -or
        [string]$generationProducer.subject_sha256 -cne
            ([string]$generation.PayloadSha256).ToUpperInvariant() -or
        [string]$restoreProducer.subject_sha256 -cne
            ([string]$restoreEvidence.PayloadSha256).ToUpperInvariant()
    ) {
        throw "C07 historical recovery manifest/restore subjects 与 lineage 不一致。"
    }
    Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
        -Context $context `
        -SuperuserPassword $SuperuserPassword
    return [pscustomobject]@{
        Schema = $script:TicketboxC07ProductionRecoveryGenerationSchema
        OperationId = [string]$projected.Receipt.operation_id
        Result = "production_recovery_generation_verified"
        Payload = $generation.Payload
        PayloadSha256 = [string]$generation.PayloadSha256
        ManifestPath = [string]$generation.ManifestPath
        DumpPath = [string]$generation.DumpPath
        InventoryPath = [string]$generation.InventoryPath
        CopiesPath = [string]$generation.CopiesPath
        Root = [string]$generation.Root
        LifecycleAuthorityChainSha256 =
            [string]$generation.LifecycleAuthorityChainSha256
        StageEvidenceSha256 = [string]$generation.StageEvidenceSha256
        SourceDatabaseIdentity = [pscustomobject]@{
            Database = $script:TicketboxC07RecoveryDatabaseName
            ClusterSystemIdentifier =
                [string]$databaseIdentity.ClusterSystemIdentifier
            DatabaseOid = [uint32]$databaseIdentity.DatabaseOid
            GenerationPayloadSha256 = [string]$generation.PayloadSha256
        }
        RestoreEvidence = [pscustomobject]@{
            Payload = $restoreEvidence.Payload
            PayloadSha256 = [string]$restoreEvidence.PayloadSha256
            Path = [string]$restoreEvidence.Path
        }
    }
}

function Read-TicketboxC07HistoricalProductionTargetRecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [Parameter(Mandatory = $true)][object]$PredecessorAuthority,
        [Parameter(Mandatory = $true)][object]$SuccessorIntent,
        [AllowNull()][Security.SecureString]$SuperuserPassword
    )

    Assert-TicketboxC07RecoveryDependencies
    if ($null -eq $SuperuserPassword -or $SuperuserPassword.Length -lt 32) {
        throw "C07 historical target recovery PostgreSQL authority 缺失或不足 32 个字符。"
    }
    $current = Read-TicketboxC07Authority $DataRoot
    Assert-TicketboxC07OperationLease $current $LifecycleLock
    if (
        [string]$current.Descriptor.Payload.successor_mode -cne
            "forward_repair" -or
        [string]$SuccessorIntent.Payload.successor_mode -cne
            "forward_repair" -or
        [string]$SuccessorIntent.Payload.successor_operation_id -cne
            [string]$current.Receipt.operation_id -or
        [string]$SuccessorIntent.Payload.predecessor_operation_id -cne
            [string]$PredecessorAuthority.Receipt.operation_id -or
        [string]$SuccessorIntent.Payload.predecessor_terminal_receipt_payload_sha256 -cne
            [string]$PredecessorAuthority.Envelope.PayloadSha256 -or
        [string]$SuccessorIntent.Payload.predecessor_terminal_authority_chain_sha256 -cne
            [string]$PredecessorAuthority.Receipt.authority_chain_sha256
    ) {
        throw "C07 historical target recovery 未绑定 exact forward-repair successor。"
    }

    $generationStage = Read-TicketboxC07StageEvidence `
        -Authority $PredecessorAuthority `
        -Stage "target_recovery_generation_ready"
    $restoreStage = Read-TicketboxC07StageEvidence `
        -Authority $PredecessorAuthority `
        -Stage "target_isolated_restore_verified"
    if (
        [string]$generationStage.PayloadSha256 -cne
            [string]$SuccessorIntent.Payload.predecessor_target_recovery_generation_evidence_sha256 -or
        [string]$restoreStage.PayloadSha256 -cne
            [string]$SuccessorIntent.Payload.predecessor_target_isolated_restore_evidence_sha256
    ) {
        throw "C07 historical target recovery stage lineage 与 successor intent 不一致。"
    }

    $targetStage = "target_isolated_restore_verified"
    $targetStageIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        $targetStage
    )
    $previousStage = [string]$PredecessorAuthority.Receipt.previous_stage
    $previousIndex = [array]::IndexOf(
        $script:TicketboxC07OrderedStages,
        $previousStage
    )
    if ($previousIndex -lt $targetStageIndex) {
        throw "C07 forward-repair predecessor 尚未完成 target isolated restore。"
    }
    $projectedAuthorityChainSha256 =
        [string]$PredecessorAuthority.Receipt.previous_authority_chain_sha256
    if ($previousIndex -gt $targetStageIndex) {
        $runtimeAclStage = Read-TicketboxC07StageEvidence `
            -Authority $PredecessorAuthority `
            -Stage "runtime_acl_verified"
        if (
            [string]$runtimeAclStage.PayloadSha256 -cne
                [string]$SuccessorIntent.Payload.predecessor_runtime_acl_evidence_sha256
        ) {
            throw "C07 historical target recovery runtime ACL lineage 已漂移。"
        }
        $projectedAuthorityChainSha256 =
            [string]$runtimeAclStage.Payload.source_authority_chain_sha256
    }
    Assert-TicketboxC07RecoveryHostSha256 `
        $projectedAuthorityChainSha256 `
        "C07 historical target restore authority chain"

    $projectedReceipt = $PredecessorAuthority.Receipt.PSObject.Copy()
    $projectedReceipt.stage = $targetStage
    $projectedReceipt.stage_sequence = [int64]$targetStageIndex
    $projectedReceipt.previous_stage = "target_recovery_generation_ready"
    $projectedReceipt.transition_kind = "stage"
    $projectedReceipt.transition_evidence_sha256 =
        [string]$restoreStage.PayloadSha256
    $projectedReceipt.authority_chain_sha256 =
        $projectedAuthorityChainSha256
    $projected = $PredecessorAuthority.PSObject.Copy()
    $projected.Receipt = $projectedReceipt

    $databaseAuthority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection `
        $databaseAuthority `
        $SuperuserPassword
    $databaseIdentity = Get-TicketboxC07DatabaseIdentity `
        -Authority $databaseAuthority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07RecoveryDatabaseName
    if (-not $databaseIdentity.Exists) {
        throw "C07 historical target recovery live database 不存在。"
    }
    $sourcePaths = Get-TicketboxC07RecoveryPaths $projected
    $uploadRootAuthority = Read-TicketboxC07RecoveryUploadRootAuthority `
        -Authority $projected `
        -ExpectedConfiguredRoot (
            Resolve-TicketboxC07RecoveryConfiguredUploadRoot $projected
        )
    $paths = [pscustomobject]@{
        HostRoot = $sourcePaths.HostRoot
        GenerationRoot = $sourcePaths.GenerationRoot
        PartialRoot = $sourcePaths.TargetPartialRoot
        ReadyRoot = $sourcePaths.TargetReadyRoot
        RestoreAssetsRoot = $sourcePaths.TargetRestoreAssetsRoot
        RestoreIdentityPath = $sourcePaths.TargetRestoreIdentityPath
        RestoreCreateIntentPath = $sourcePaths.TargetRestoreCreateIntentPath
        RestoreEvidencePath = $sourcePaths.TargetRestoreEvidencePath
        CleanupPath = $sourcePaths.TargetCleanupPath
        ManifestFileName = $sourcePaths.ManifestFileName
        InventoryFileName = $sourcePaths.InventoryFileName
        CopiesFileName = $sourcePaths.CopiesFileName
        DumpFileName = $sourcePaths.DumpFileName
        AssetsLeaf = $sourcePaths.AssetsLeaf
    }
    $context = [pscustomobject]@{
        Authority = $projected
        LifecycleLock = $LifecycleLock
        MaintenanceDeadlineUtc = ""
        DatabaseAuthority = $databaseAuthority
        DatabaseIdentity = $databaseIdentity
        DatabaseUrl = ""
        PgDumpPath = ""
        PgRestorePath = ""
        UploadRoot = [string]$uploadRootAuthority.Root
        UploadRootBindingSha256 =
            [string]$uploadRootAuthority.BindingSha256
        Paths = $paths
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow $paths.ReadyRoot) -cne
            "Directory" -or
        (Get-TicketboxPathEntryKindNoFollow $paths.PartialRoot) -cne
            "Missing"
    ) {
        throw "C07 historical target recovery 要求 predecessor 唯一 READY generation。"
    }
    $generation = Read-TicketboxC07TargetRecoveryManifest `
        -Context $context `
        -Root $paths.ReadyRoot
    Assert-TicketboxC07TargetRecoveryGenerationFiles $generation | Out-Null
    if (
        [string]$generation.TargetCommitStageEvidenceSha256 -cne
            [string]$SuccessorIntent.Payload.predecessor_target_commit_evidence_sha256
    ) {
        throw "C07 historical target recovery target-commit lineage 已漂移。"
    }
    Assert-TicketboxC07RecoveryLiveSourceBinding `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $SuperuserPassword
    $restore = Read-TicketboxC07TargetRecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    if ($null -eq $restore) {
        throw "C07 historical target recovery 缺少 predecessor zero-replay restore evidence。"
    }
    $generationProducer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$generationStage.Payload.producer_payload_json) `
        -Label "historical target recovery generation producer"
    $restoreProducer = ConvertFrom-TicketboxC07JsonText `
        -Text ([string]$restoreStage.Payload.producer_payload_json) `
        -Label "historical target recovery restore producer"
    if (
        [string]$generationProducer.subject_sha256 -cne
            ([string]$generation.PayloadSha256).ToUpperInvariant() -or
        [string]$restoreProducer.subject_sha256 -cne
            ([string]$restore.PayloadSha256).ToUpperInvariant()
    ) {
        throw "C07 historical target recovery manifest/restore subjects 与 lineage 不一致。"
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $paths.RestoreIdentityPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $paths.RestoreCreateIntentPath) -cne "Missing"
    ) {
        throw "C07 historical target recovery 检出 restore residue。"
    }
    Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
        -Context $context `
        -SuperuserPassword $SuperuserPassword
    return [pscustomobject]@{
        Schema = $script:TicketboxC07ProductionTargetRecoveryGenerationSchema
        OperationId = [string]$projected.Receipt.operation_id
        Result = "production_target_recovery_generation_verified"
        Payload = $generation.Payload
        PayloadSha256 = [string]$generation.PayloadSha256
        ManifestPath = [string]$generation.ManifestPath
        DumpPath = [string]$generation.DumpPath
        InventoryPath = [string]$generation.InventoryPath
        CopiesPath = [string]$generation.CopiesPath
        Root = [string]$generation.Root
        LifecycleAuthorityChainSha256 =
            [string]$generation.LifecycleAuthorityChainSha256
        TargetCommitStageEvidenceSha256 =
            [string]$generation.TargetCommitStageEvidenceSha256
        RestoreEvidence = [pscustomobject]@{
            Payload = $restore.Payload
            PayloadSha256 = [string]$restore.PayloadSha256
            Path = [string]$restore.Path
        }
    }
}

function Test-TicketboxC07RecoveryGenerationRestore {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][scriptblock]$ForwardReplayAction
    )
    $context = Get-TicketboxC07RecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages @(
            "writers_frozen",
            "recovery_generation_ready",
            "isolated_restore_verified"
        )
    if (-not (Test-Path -LiteralPath $context.Paths.ReadyRoot)) {
        throw "C07 isolated restore 缺少 verified generation candidate。"
    }
    $generation = Read-TicketboxC07RecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    $copies = Assert-TicketboxC07RecoveryGenerationFiles $generation
    Assert-TicketboxC07RecoveryLiveSourceBinding `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $SuperuserPassword
    $inventory = Read-TicketboxC07RecoveryJsonLines `
        -Path $generation.InventoryPath `
        -Kind "inventory" `
        -ExpectedRows ([int]$generation.Payload.asset_inventory.row_count
        )
    Assert-TicketboxC07RecoveryAssetReconcile `
        -Inventory $inventory `
        -Copies $copies | Out-Null

    $durableEvidence = Read-TicketboxC07RecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    if ($null -ne $durableEvidence) {
        if (
            (Get-TicketboxPathEntryKindNoFollow `
                $context.Paths.RestoreIdentityPath) -cne "Missing" -or
            (Get-TicketboxPathEntryKindNoFollow `
                $context.Paths.RestoreCreateIntentPath) -cne "Missing"
        ) {
            throw (
                "C07 isolated restore durable evidence 与 create-intent/" +
                "cleanup identity " +
                "同时存在；拒绝猜测终态。"
            )
        }
        Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
            -Context $context `
            -SuperuserPassword $SuperuserPassword
        return [pscustomobject]@{
            State = "isolated_restore_verified"
            OperationId = [string]$durableEvidence.Payload.operation_id
            EvidenceSha256 = $durableEvidence.PayloadSha256
            GenerationEvidenceSha256 = $generation.PayloadSha256
            InventoryRows =
                [int]$durableEvidence.Payload.asset_inventory_rows
            OriginalCopies =
                [int]$durableEvidence.Payload.original_copies_verified
            RestoreDatabaseState = "cleaned"
            Reused = $true
        }
    }
    if (
        [string]$context.Authority.Receipt.stage -ceq
            "isolated_restore_verified"
    ) {
        throw (
            "C07 isolated_restore_verified 缺少 durable restore evidence；" +
            "拒绝重新执行 cleanup/restore/forward replay。"
        )
    }

    $preCleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
        -Context $context `
        -SuperuserPassword $SuperuserPassword `
        -Generation $generation
    if ([string]$preCleanup.State -cne "cleaned") {
        throw (
            "C07 isolated restore 前次数据库仍 cleanup_pending；" +
            "拒绝复用或覆盖。"
        )
    }

    $restoreIdentity = $null
    $verification = $null
    $forwardReplay = $null
    $operationId = [string]$context.Authority.Receipt.operation_id
    try {
        $restoreIdentity =
            New-TicketboxC07RecoveryRestoreDatabaseBound `
                -Context $context `
                -Generation $generation `
                -SuperuserPassword $SuperuserPassword
        Write-TicketboxC07RecoveryRestoreIdentityArtifact `
            -Context $context `
            -Generation $generation `
            -Identity $restoreIdentity | Out-Null
        Invoke-TicketboxC07RecoveryArchiveRestore `
            -Context $context `
            -SuperuserPassword $SuperuserPassword `
            -RestoreIdentity $restoreIdentity `
            -DumpPath $generation.DumpPath
        $restored = Get-TicketboxC07RestoredInventory `
            -Context $context `
            -SuperuserPassword $SuperuserPassword `
            -RestoreIdentity $restoreIdentity
        $expectedDatabase = $generation.Payload.database
        if (
            [string]$restored.Meta.database -cne
                [string]$restoreIdentity.Database -or
            [string]$restored.Meta.database_oid -cne
                [string]$restoreIdentity.DatabaseOid -or
            [string]$restored.Meta.cluster_system_identifier -cne
                [string]$restoreIdentity.ClusterSystemIdentifier -or
            [string]$restored.Meta.server_id -cne
                [string]$expectedDatabase.server_id -or
            [string]$restored.Meta.data_generation -cne
                [string]$expectedDatabase.data_generation -or
            [string]::Join("`n", @($restored.Meta.alembic_heads)) -cne
                [string]::Join("`n", @($expectedDatabase.alembic_heads))
        ) {
            throw "C07 isolated restore database/logical identity 对账失败。"
        }
        if (
            [string]$restored.Meta.database_oid -ceq
            [string]$expectedDatabase.source_database_oid
        ) {
            throw "C07 isolated restore 未使用 distinct database OID。"
        }
        $restoredDigest = Get-TicketboxC07RecoveryJsonLinesDigest `
            -Records @($restored.Assets) `
            -Kind "inventory"
        if (
            $restoredDigest.Sha256 -cne
                [string]$generation.Payload.asset_inventory.sha256 -or
            $restoredDigest.SizeBytes -ne
                [int64]$generation.Payload.asset_inventory.size_bytes -or
            $restoredDigest.RowCount -ne
                [int]$generation.Payload.asset_inventory.row_count
        ) {
            throw (
                "C07 isolated restore PostgreSQL Expense.image_path/" +
                "thumbnail_path inventory 与 recovery generation 不一致。"
            )
        }
        $restoreDatabase = [string]$restoreIdentity.Database
        Invoke-TicketboxC07Sql `
            -Authority $context.DatabaseAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Sql (
                "GRANT CONNECT ON DATABASE `"$restoreDatabase`" " +
                "TO `"$script:TicketboxC07MigratorRole`";"
            ) `
            -Label "C07 isolated replay migrator window open" | Out-Null
        try {
            $replayRemaining =
                Get-TicketboxC07RemainingMaintenanceMilliseconds `
                    -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                    -MaximumMilliseconds (
                        $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                    ) `
                    -Label "C07 isolated forward replay"
            $forwardReplay = & $ForwardReplayAction `
                $context.DatabaseAuthority `
                $MigratorPassword `
                $restoreDatabase `
                $operationId `
                $ExpectedSourceRevision `
                $TargetRevision `
                ([string]$context.Authority.Descriptor.Payload.revision_manifest_sha256) `
                $context.MaintenanceDeadlineUtc `
                $replayRemaining `
                ([string]$context.Authority.Receipt.authority_chain_sha256) `
                ([string]$restoreIdentity.CreateAttemptId)
        }
        finally {
            Invoke-TicketboxC07Sql `
                -Authority $context.DatabaseAuthority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $SuperuserPassword `
                -Sql @"
REVOKE CONNECT ON DATABASE "$restoreDatabase"
    FROM "$script:TicketboxC07MigratorRole";
SELECT pg_terminate_backend(pid, 5000)
FROM pg_stat_activity
WHERE datname = '$restoreDatabase'
  AND usename = '$script:TicketboxC07MigratorRole'
  AND pid <> pg_backend_pid();
"@ `
                -Label "C07 isolated replay migrator window close" | Out-Null
        }
        Assert-TicketboxC07RecoveryExactProperties `
            $forwardReplay `
            @(
                "schema",
                "mode",
                "operation_id",
                "source_revision",
                "target_revision",
                "revision_manifest_sha256",
                "maintenance_authority_sha256",
                "maintenance_remaining_ceiling_ms",
                "resource_shape_sha256",
                "result",
                "alembic_revision",
                "target_shape_sha256",
                "money_facts_sha256"
            ) `
            "C07 isolated forward replay"
        if (
            [string]$forwardReplay.schema -cne
                "ticketbox-c07-maintenance-upgrade-result-v3" -or
            [string]$forwardReplay.mode -cne "isolated_replay" -or
            [string]$forwardReplay.operation_id -cne $operationId -or
            [string]$forwardReplay.source_revision -cne
                $ExpectedSourceRevision -or
            [string]$forwardReplay.target_revision -cne $TargetRevision -or
            [string]$forwardReplay.revision_manifest_sha256 -cne
                (
                    [string]$context.Authority.Descriptor.Payload.revision_manifest_sha256
                ).ToLowerInvariant() -or
            [string]$forwardReplay.maintenance_authority_sha256 -cne
                (
                    [string]$context.Authority.Receipt.authority_chain_sha256
                ).ToLowerInvariant() -or
            [int]$forwardReplay.maintenance_remaining_ceiling_ms -lt 1 -or
            [int]$forwardReplay.maintenance_remaining_ceiling_ms -gt
                $replayRemaining -or
            [string]$forwardReplay.alembic_revision -cne $TargetRevision -or
            [string]$forwardReplay.money_facts_sha256 -cne
                [string]$generation.Payload.database.money_facts_sha256 -or
            [string]$forwardReplay.result -cne
                "isolated_forward_replay_verified"
        ) {
            throw "C07 isolated forward replay 未绑定 exact restore/source/target。"
        }
        Assert-TicketboxC07RecoverySha256 `
            ([string]$forwardReplay.resource_shape_sha256) `
            "C07 isolated forward replay resource shape"
        Assert-TicketboxC07RecoverySha256 `
            ([string]$forwardReplay.target_shape_sha256) `
            "C07 isolated forward replay target shape"
        Assert-TicketboxC07RecoverySha256 `
            ([string]$forwardReplay.money_facts_sha256) `
            "C07 isolated forward replay canonical money facts"
        $postReplayRestored = Get-TicketboxC07RestoredInventory `
            -Context $context `
            -SuperuserPassword $SuperuserPassword `
            -RestoreIdentity $restoreIdentity
        if (
            [string]$postReplayRestored.Meta.database -cne
                [string]$restoreIdentity.Database -or
            [string]$postReplayRestored.Meta.database_oid -cne
                [string]$restoreIdentity.DatabaseOid -or
            [string]$postReplayRestored.Meta.cluster_system_identifier -cne
                [string]$restoreIdentity.ClusterSystemIdentifier -or
            [string]$postReplayRestored.Meta.server_id -cne
                [string]$expectedDatabase.server_id -or
            [string]$postReplayRestored.Meta.data_generation -cne
                [string]$expectedDatabase.data_generation -or
            [string]::Join(
                "`n",
                @($postReplayRestored.Meta.alembic_heads)
            ) -cne $TargetRevision
        ) {
            throw (
                "C07 isolated forward replay 后 database/logical identity/" +
                "Alembic target 对账失败。"
            )
        }
        $postReplayDigest = Get-TicketboxC07RecoveryJsonLinesDigest `
            -Records @($postReplayRestored.Assets) `
            -Kind "inventory"
        if (
            $postReplayDigest.Sha256 -cne $restoredDigest.Sha256 -or
            $postReplayDigest.SizeBytes -ne $restoredDigest.SizeBytes -or
            $postReplayDigest.RowCount -ne $restoredDigest.RowCount -or
            $postReplayDigest.Sha256 -cne
                [string]$generation.Payload.asset_inventory.sha256 -or
            $postReplayDigest.SizeBytes -ne
                [int64]$generation.Payload.asset_inventory.size_bytes -or
            $postReplayDigest.RowCount -ne
                [int]$generation.Payload.asset_inventory.row_count
        ) {
            throw (
                "C07 isolated forward replay 改变了 PostgreSQL asset facts；" +
                "不得发布 verified evidence。"
            )
        }
        $reconcile = Assert-TicketboxC07RecoveryAssetReconcile `
            -Inventory @($postReplayRestored.Assets) `
            -Copies $copies
        $isolatedAssets = Test-TicketboxC07RecoveryIsolatedAssets `
            -Context $context `
            -Generation $generation `
            -Inventory @($postReplayRestored.Assets) `
            -Copies $copies
        $verificationPayload = [ordered]@{
            schema = $script:TicketboxC07RecoveryRestoreEvidenceSchema
            operation_id = $operationId
            operation_kind =
                [string]$context.Authority.Descriptor.Payload.operation_kind
            target_alembic_revision =
                [string]$context.Authority.Descriptor.Payload.target_alembic_revision
            revision_manifest_sha256 =
                [string]$context.Authority.Descriptor.Payload.revision_manifest_sha256
            installation_id =
                [string]$context.Authority.ReleaseIdentity.InstallationId
            generation_payload_sha256 = $generation.PayloadSha256
            source_cluster_system_identifier =
                [string]$expectedDatabase.cluster_system_identifier
            source_database_oid =
                [string]$expectedDatabase.source_database_oid
            restore_database = [string]$restoreIdentity.Database
            restore_database_oid = [string]$restoreIdentity.DatabaseOid
            restore_create_attempt_id =
                [string]$restoreIdentity.CreateAttemptId
            restore_create_authority_sha256 =
                [string]$restoreIdentity.CreateAuthoritySha256
            logical_server_id = [string]$expectedDatabase.server_id
            logical_data_generation =
                [string]$expectedDatabase.data_generation
            asset_inventory_sha256 = $postReplayDigest.Sha256
            asset_inventory_rows = [string][int]$reconcile.InventoryRows
            original_copies_verified =
                [string][int]$reconcile.OriginalCopies
            isolated_asset_bytes =
                [string][int64]$isolatedAssets.Bytes
            thumbnails = "audited_rebuildable_not_copied"
            forward_replay_source_revision =
                [string]$forwardReplay.source_revision
            forward_replay_target_revision =
                [string]$forwardReplay.target_revision
            forward_replay_result = [string]$forwardReplay.result
            target_shape_sha256 =
                [string]$forwardReplay.target_shape_sha256
            money_facts_sha256 =
                [string]$forwardReplay.money_facts_sha256
            result = "isolated_restore_reconciled"
            integrity_scope = $script:TicketboxC07RecoveryIntegrityScope
            verified_at_utc = [DateTime]::UtcNow.ToString("o")
        }
        $verificationText = $verificationPayload |
            ConvertTo-Json -Depth 8 -Compress
        $verification = [pscustomobject]@{
            Payload = $verificationPayload
            EvidenceSha256 =
                Get-TicketboxC07RecoveryTextSha256 $verificationText
        }
    }
    finally {
        if ($null -ne $restoreIdentity) {
            $cleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
                -Context $context `
                -SuperuserPassword $SuperuserPassword `
                -Generation $generation
            if ([string]$cleanup.State -cne "cleaned") {
                $verification = $null
                throw (
                    "C07 isolated restore 已完成对账但数据库 cleanup_pending；" +
                    "不得发布 verified evidence。"
                )
            }
        }
    }
    if ($null -eq $verification) {
        throw "C07 isolated restore 未产生 verified evidence。"
    }
    $durableEvidence = Write-TicketboxC07RecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation `
        -Payload $verification.Payload `
        -SuperuserPassword $SuperuserPassword
    if (
        [string]$durableEvidence.PayloadSha256 -cne
        [string]$verification.EvidenceSha256
    ) {
        throw "C07 isolated restore durable evidence digest 复读不一致。"
    }
    return [pscustomobject]@{
        State = "isolated_restore_verified"
        OperationId = $operationId
        EvidenceSha256 = $durableEvidence.PayloadSha256
        GenerationEvidenceSha256 = $generation.PayloadSha256
        InventoryRows = [int]$verification.Payload.asset_inventory_rows
        OriginalCopies = [int]$verification.Payload.original_copies_verified
        RestoreDatabaseState = "cleaned"
        Reused = $false
    }
}

function Assert-TicketboxC07TargetSemanticResult {
    param(
        [Parameter(Mandatory = $true)][object]$Evidence,
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$Database,
        [AllowEmptyString()][string]$SnapshotId,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$ExpectedTargetRevision,
        [Parameter(Mandatory = $true)][int]$MaximumRemainingCeilingMilliseconds,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256
    )
    Assert-TicketboxC07RecoveryExactProperties `
        $Evidence `
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
        "C07 target semantic evidence"
    $remaining = [int]$Evidence.maintenance_remaining_ceiling_ms
    if (
        [string]$Evidence.schema -cne
            "ticketbox-c07-target-semantic-result-v1" -or
        [string]$Evidence.operation_id -cne
            [string]$Context.Authority.Receipt.operation_id -or
        [string]$Evidence.database -cne $Database -or
        [string]$Evidence.snapshot_id -cne $SnapshotId -or
        [string]$Evidence.source_revision -cne
            $ExpectedSourceRevision -or
        [string]$Evidence.target_revision -cne
            $ExpectedTargetRevision -or
        [string]$Evidence.alembic_revision -cne
            $ExpectedTargetRevision -or
        [string]$Evidence.revision_manifest_sha256 -cne
            (
                [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
            ).ToLowerInvariant() -or
        [string]$Evidence.maintenance_authority_sha256 -cne
            $MaintenanceAuthoritySha256.ToLowerInvariant() -or
        $remaining -lt 1 -or
        $remaining -gt $MaximumRemainingCeilingMilliseconds
    ) {
        throw "C07 target semantic evidence 未绑定 exact target/snapshot/authority。"
    }
    foreach ($field in @(
        "resource_shape_sha256",
        "money_facts_sha256"
    )) {
        Assert-TicketboxC07RecoverySha256 `
            ([string]$Evidence.$field) "C07 target semantic $field"
    }
    return $Evidence
}

function Assert-TicketboxC07TargetMoneyFactsResult {
    param(
        [Parameter(Mandatory = $true)][object]$Evidence,
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$Database,
        [AllowEmptyString()][string]$SnapshotId,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][int]$MaximumRemainingCeilingMilliseconds,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256
    )
    Assert-TicketboxC07RecoveryExactProperties `
        $Evidence `
        @(
            "schema",
            "operation_id",
            "database",
            "snapshot_id",
            "maintenance_authority_sha256",
            "maintenance_remaining_ceiling_ms",
            "alembic_revision",
            "money_facts_sha256"
        ) `
        "C07 target money facts evidence"
    $remaining = [int]$Evidence.maintenance_remaining_ceiling_ms
    if (
        [string]$Evidence.schema -cne
            "ticketbox-c07-money-facts-result-v2" -or
        [string]$Evidence.operation_id -cne
            [string]$Context.Authority.Receipt.operation_id -or
        [string]$Evidence.database -cne $Database -or
        [string]$Evidence.snapshot_id -cne $SnapshotId -or
        [string]$Evidence.maintenance_authority_sha256 -cne
            $MaintenanceAuthoritySha256.ToLowerInvariant() -or
        $remaining -lt 1 -or
        $remaining -gt $MaximumRemainingCeilingMilliseconds -or
        [string]$Evidence.alembic_revision -cne $ExpectedRevision
    ) {
        throw "C07 target money facts 未绑定 exact target/snapshot/authority。"
    }
    Assert-TicketboxC07RecoverySha256 `
        ([string]$Evidence.money_facts_sha256) `
        "C07 target canonical money facts"
    return $Evidence
}

function New-TicketboxC07TargetRecoveryPayload {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Snapshot,
        [Parameter(Mandatory = $true)][object]$Capacity,
        [Parameter(Mandatory = $true)][object]$DumpEvidence,
        [Parameter(Mandatory = $true)][object]$MoneyFactsEvidence,
        [Parameter(Mandatory = $true)][object]$SemanticEvidence,
        [Parameter(Mandatory = $true)][object]$InventoryEvidence,
        [Parameter(Mandatory = $true)][object]$CopiesEvidence,
        [Parameter(Mandatory = $true)][string]$TargetCommitEvidenceSha256,
        [Parameter(Mandatory = $true)][string]$MigrationEvidenceSha256
    )
    Assert-TicketboxC07RecoveryHostSha256 `
        $TargetCommitEvidenceSha256 "C07 target commit evidence"
    Assert-TicketboxC07RecoverySha256 `
        $MigrationEvidenceSha256 "C07 target migration evidence"
    Assert-TicketboxC07RecoverySha256 `
        ([string]$Context.UploadRootBindingSha256) `
        "C07 target configured upload-root binding"
    if (
        [string]$MoneyFactsEvidence.money_facts_sha256 -cne
            [string]$SemanticEvidence.money_facts_sha256
    ) {
        throw "C07 target snapshot money-facts attestations 不一致。"
    }
    $release = $Context.Authority.ReleaseIdentity
    $receipt = $Context.Authority.Receipt
    $meta = $Snapshot.Meta
    return [ordered]@{
        schema = $script:TicketboxC07TargetRecoveryGenerationSchema
        operation_id = [string]$receipt.operation_id
        generation_id = [string]$receipt.operation_id
        generation_kind = "post_ddl_target"
        release = [ordered]@{
            fingerprint = [string]$release.Fingerprint
            installation_id = [string]$release.InstallationId
            build_manifest_sha256 = [string]$release.BuildManifestSha256
            backend_version = [string]$release.BackendVersionFloor
        }
        lifecycle = [ordered]@{
            stage = "target_committed"
            operation_kind =
                [string]$Context.Authority.Descriptor.Payload.operation_kind
            source_alembic_revision =
                [string]$Context.Authority.Descriptor.Payload.source_alembic_revision
            target_alembic_revision =
                [string]$Context.Authority.Descriptor.Payload.target_alembic_revision
            revision_manifest_sha256 =
                [string]$Context.Authority.Descriptor.Payload.revision_manifest_sha256
            authority_chain_sha256 =
                [string]$receipt.authority_chain_sha256
            freeze_proof_sha256 = [string]$receipt.freeze_proof_sha256
            freeze_heartbeat_sequence =
                [string][int64]$receipt.freeze_heartbeat_sequence
            target_commit_evidence_sha256 = $TargetCommitEvidenceSha256
            migration_evidence_sha256 = $MigrationEvidenceSha256
        }
        integrity = [ordered]@{
            scope = $script:TicketboxC07RecoveryIntegrityScope
            malicious_writer_resistance = $false
            upload_root_binding_sha256 =
                [string]$Context.UploadRootBindingSha256
        }
        barrier = [ordered]@{
            mode = "post_ddl_bounded_quiesce_plus_pg_export_snapshot"
            exported_snapshot_id = [string]$Snapshot.SnapshotId
            captured_at_utc = [DateTime]::UtcNow.ToString("o")
        }
        database = [ordered]@{
            name = [string]$meta.database
            cluster_system_identifier =
                [string]$meta.cluster_system_identifier
            source_database_oid = [string]$meta.database_oid
            server_version_num = [string]$meta.server_version_num
            server_id = [string]$meta.server_id
            data_generation = [string]$meta.data_generation
            alembic_heads = @($meta.alembic_heads)
            dump_file = [string]$DumpEvidence.FileName
            dump_sha256 = [string]$DumpEvidence.Sha256
            dump_size_bytes = [string][int64]$DumpEvidence.SizeBytes
            restore_list_sha256 =
                [string]$DumpEvidence.RestoreListSha256
            money_facts_sha256 =
                [string]$MoneyFactsEvidence.money_facts_sha256
            resource_shape_sha256 =
                [string]$SemanticEvidence.resource_shape_sha256
        }
        asset_inventory = [ordered]@{
            file = [string]$InventoryEvidence.FileName
            sha256 = [string]$InventoryEvidence.Sha256
            size_bytes = [string][int64]$InventoryEvidence.SizeBytes
            row_count = [string][int64]$InventoryEvidence.RowCount
        }
        original_copies = [ordered]@{
            file = [string]$CopiesEvidence.FileName
            sha256 = [string]$CopiesEvidence.Sha256
            size_bytes = [string][int64]$CopiesEvidence.SizeBytes
            row_count = [string][int64]$CopiesEvidence.RowCount
            asset_directory = "assets"
        }
        thumbnail_policy = [ordered]@{
            authority = "derived_rebuildable_cache"
            copied = $false
            references_audited = $true
        }
        capacity = $Capacity
        completion = [ordered]@{
            state = "target_generation_ready"
            created_by = "windows_c07_target_recovery_generation"
            created_at_utc = [DateTime]::UtcNow.ToString("o")
        }
    }
}

function Read-TicketboxC07TargetRecoveryManifest {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$Root
    )
    Assert-NoTicketboxAncestorReparsePoints $Root
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $Root `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    $manifestPath = Join-Path $Root $Context.Paths.ManifestFileName
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $manifestPath `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $manifest = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $manifest.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "generation_id",
            "generation_kind",
            "release",
            "lifecycle",
            "integrity",
            "barrier",
            "database",
            "asset_inventory",
            "original_copies",
            "thumbnail_policy",
            "capacity",
            "completion"
        ) `
        "C07 target recovery generation payload"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.release `
        @(
            "fingerprint",
            "installation_id",
            "build_manifest_sha256",
            "backend_version"
        ) `
        "C07 target recovery release binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.lifecycle `
        @(
            "stage",
            "operation_kind",
            "source_alembic_revision",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "authority_chain_sha256",
            "freeze_proof_sha256",
            "freeze_heartbeat_sequence",
            "target_commit_evidence_sha256",
            "migration_evidence_sha256"
        ) `
        "C07 target recovery lifecycle binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.integrity `
        @(
            "scope",
            "malicious_writer_resistance",
            "upload_root_binding_sha256"
        ) `
        "C07 target recovery integrity"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.barrier `
        @("mode", "exported_snapshot_id", "captured_at_utc") `
        "C07 target recovery snapshot barrier"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.database `
        @(
            "name",
            "cluster_system_identifier",
            "source_database_oid",
            "server_version_num",
            "server_id",
            "data_generation",
            "alembic_heads",
            "dump_file",
            "dump_sha256",
            "dump_size_bytes",
            "restore_list_sha256",
            "money_facts_sha256",
            "resource_shape_sha256"
        ) `
        "C07 target recovery database binding"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.asset_inventory `
        @("file", "sha256", "size_bytes", "row_count") `
        "C07 target recovery asset inventory"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.original_copies `
        @(
            "file",
            "sha256",
            "size_bytes",
            "row_count",
            "asset_directory"
        ) `
        "C07 target recovery original copies"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.thumbnail_policy `
        @("authority", "copied", "references_audited") `
        "C07 target recovery thumbnail policy"
    Assert-TicketboxC07RecoveryExactProperties `
        $payload.completion `
        @("state", "created_by", "created_at_utc") `
        "C07 target recovery completion"

    $authority = $Context.Authority
    $descriptor = $authority.Descriptor.Payload
    $targetCommitEvidence = Read-TicketboxC07StageEvidence `
        -Authority $authority `
        -Stage "target_committed"
    $targetCommitProducer =
        ([string]$targetCommitEvidence.Payload.producer_payload_json) |
            ConvertFrom-TicketboxC07RecoveryJson
    Assert-TicketboxC07RecoveryExactProperties `
        $targetCommitProducer `
        @(
            "schema",
            "operation_id",
            "result",
            "database_binding_sha256",
            "operation_kind",
            "alembic_target",
            "revision_manifest_sha256",
            "subject_sha256",
            "migration_evidence_sha256",
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_count",
            "statistics_table_set_sha256"
        ) `
        "C07 target commit producer"
    if (
        [string]$targetCommitProducer.operation_id -cne
            [string]$authority.Receipt.operation_id -or
        [string]$targetCommitProducer.result -cne "target_committed" -or
        [string]$targetCommitProducer.database_binding_sha256 -cne
            [string]$authority.Receipt.database_binding_sha256 -or
        [string]$targetCommitProducer.operation_kind -cne
            [string]$descriptor.operation_kind -or
        [string]$targetCommitProducer.alembic_target -cne
            [string]$descriptor.target_alembic_revision -or
        [string]$targetCommitProducer.revision_manifest_sha256 -cne
            [string]$descriptor.revision_manifest_sha256
    ) {
        throw "C07 target commit producer 未绑定 lifecycle descriptor。"
    }
    foreach ($digest in @(
        [string]$targetCommitProducer.subject_sha256,
        [string]$targetCommitProducer.migration_evidence_sha256,
        [string]$targetCommitProducer.resource_shape_sha256,
        [string]$targetCommitProducer.money_facts_sha256,
        [string]$targetCommitProducer.statistics_table_set_sha256
    )) {
        Assert-TicketboxC07RecoveryHostSha256 `
            $digest "C07 target commit producer digest"
    }
    if ([int]$targetCommitProducer.statistics_table_count -ne 18) {
        throw "C07 target commit producer statistics table count 不完整。"
    }

    foreach ($digest in @(
        [string]$payload.database.dump_sha256,
        [string]$payload.database.restore_list_sha256,
        [string]$payload.database.money_facts_sha256,
        [string]$payload.database.resource_shape_sha256,
        [string]$payload.asset_inventory.sha256,
        [string]$payload.original_copies.sha256,
        [string]$payload.integrity.upload_root_binding_sha256,
        [string]$payload.lifecycle.migration_evidence_sha256
    )) {
        Assert-TicketboxC07RecoverySha256 `
            $digest "C07 target recovery digest"
    }
    foreach ($hostDigest in @(
        [string]$payload.release.fingerprint,
        [string]$payload.release.build_manifest_sha256,
        [string]$payload.lifecycle.authority_chain_sha256,
        [string]$payload.lifecycle.freeze_proof_sha256,
        [string]$payload.lifecycle.revision_manifest_sha256,
        [string]$payload.lifecycle.target_commit_evidence_sha256
    )) {
        Assert-TicketboxC07RecoveryHostSha256 `
            $hostDigest "C07 target recovery host digest"
    }
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.release.installation_id) `
        "C07 target recovery installation ID"
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.database.server_id) `
        "C07 target recovery server ID"
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.database.data_generation) `
        "C07 target recovery data generation"
    Assert-TicketboxC07RecoveryCapacityEvidence $payload.capacity
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07TargetRecoveryGenerationSchema -or
        [string]$payload.operation_id -cne
            [string]$authority.Receipt.operation_id -or
        [string]$payload.generation_id -cne
            [string]$authority.Receipt.operation_id -or
        [string]$payload.generation_kind -cne "post_ddl_target" -or
        [string]$payload.release.fingerprint -cne
            [string]$authority.ReleaseIdentity.Fingerprint -or
        [string]$payload.release.installation_id -cne
            [string]$authority.ReleaseIdentity.InstallationId -or
        [string]$payload.release.build_manifest_sha256 -cne
            [string]$authority.ReleaseIdentity.BuildManifestSha256 -or
        [string]$payload.release.backend_version -cne
            [string]$authority.ReleaseIdentity.BackendVersionFloor -or
        [string]$payload.lifecycle.stage -cne "target_committed" -or
        [string]$payload.lifecycle.operation_kind -cne
            [string]$descriptor.operation_kind -or
        [string]$payload.lifecycle.source_alembic_revision -cne
            [string]$descriptor.source_alembic_revision -or
        [string]$payload.lifecycle.target_alembic_revision -cne
            [string]$descriptor.target_alembic_revision -or
        [string]$payload.lifecycle.revision_manifest_sha256 -cne
            [string]$descriptor.revision_manifest_sha256 -or
        [string]$payload.lifecycle.target_commit_evidence_sha256 -cne
            [string]$targetCommitEvidence.PayloadSha256 -or
        [string]$payload.lifecycle.migration_evidence_sha256 -cne
            (
                [string]$targetCommitProducer.migration_evidence_sha256
            ).ToLowerInvariant() -or
        [string]$payload.database.resource_shape_sha256 -cne
            (
                [string]$targetCommitProducer.resource_shape_sha256
            ).ToLowerInvariant() -or
        [string]$payload.database.money_facts_sha256 -cne
            (
                [string]$targetCommitProducer.money_facts_sha256
            ).ToLowerInvariant() -or
        [string]$payload.integrity.scope -cne
            $script:TicketboxC07RecoveryIntegrityScope -or
        [bool]$payload.integrity.malicious_writer_resistance -or
        [string]$payload.integrity.upload_root_binding_sha256 -cne
            [string]$Context.UploadRootBindingSha256 -or
        [string]$payload.barrier.mode -cne
            "post_ddl_bounded_quiesce_plus_pg_export_snapshot" -or
        [string]$payload.barrier.exported_snapshot_id -cnotmatch
            "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}$" -or
        [string]$payload.database.name -cne
            $script:TicketboxC07RecoveryDatabaseName -or
        [string]$payload.database.cluster_system_identifier -cne
            [string]$Context.DatabaseIdentity.ClusterSystemIdentifier -or
        [string]$payload.database.source_database_oid -cne
            [string]$Context.DatabaseIdentity.DatabaseOid -or
        @($payload.database.alembic_heads).Count -ne 1 -or
        [string]@($payload.database.alembic_heads)[0] -cne
            [string]$descriptor.target_alembic_revision -or
        [string]$payload.database.dump_file -cne
            $Context.Paths.DumpFileName -or
        [string]$payload.asset_inventory.file -cne
            $Context.Paths.InventoryFileName -or
        [string]$payload.original_copies.file -cne
            $Context.Paths.CopiesFileName -or
        [string]$payload.original_copies.asset_directory -cne
            $Context.Paths.AssetsLeaf -or
        [string]$payload.completion.state -cne
            "target_generation_ready" -or
        [string]$payload.completion.created_by -cne
            "windows_c07_target_recovery_generation" -or
        [string]$payload.thumbnail_policy.authority -cne
            "derived_rebuildable_cache" -or
        [bool]$payload.thumbnail_policy.copied -or
        -not [bool]$payload.thumbnail_policy.references_audited
    ) {
        throw "C07 target recovery manifest identity/authority binding 不一致。"
    }
    $stage = [string]$authority.Receipt.stage
    if ($stage -cne "target_committed") {
        $generationStageEvidence = Read-TicketboxC07StageEvidence `
            -Authority $authority `
            -Stage "target_recovery_generation_ready"
        $producer =
            ([string]$generationStageEvidence.Payload.producer_payload_json) |
                ConvertFrom-TicketboxC07RecoveryJson
        if (
            [string]$producer.subject_sha256 -cne
                ([string]$manifest.PayloadSha256).ToUpperInvariant()
        ) {
            throw "C07 target recovery stage evidence 未绑定 READY manifest。"
        }
    }
    $dumpPath = Assert-TicketboxC07RecoveryRelativeFile `
        -Root $Root `
        -FileName ([string]$payload.database.dump_file) `
        -ExpectedSha256 ([string]$payload.database.dump_sha256) `
        -ExpectedBytes ([int64]$payload.database.dump_size_bytes) `
        -Label "C07 target recovery database dump"
    $inventoryPath = Assert-TicketboxC07RecoveryRelativeFile `
        -Root $Root `
        -FileName ([string]$payload.asset_inventory.file) `
        -ExpectedSha256 ([string]$payload.asset_inventory.sha256) `
        -ExpectedBytes ([int64]$payload.asset_inventory.size_bytes) `
        -Label "C07 target recovery asset inventory"
    $copiesPath = Assert-TicketboxC07RecoveryRelativeFile `
        -Root $Root `
        -FileName ([string]$payload.original_copies.file) `
        -ExpectedSha256 ([string]$payload.original_copies.sha256) `
        -ExpectedBytes ([int64]$payload.original_copies.size_bytes) `
        -Label "C07 target recovery original copies"
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $manifest.PayloadSha256
        ManifestPath = $manifestPath
        DumpPath = $dumpPath
        InventoryPath = $inventoryPath
        CopiesPath = $copiesPath
        Root = $Root
        LifecycleAuthorityChainSha256 =
            [string]$payload.lifecycle.authority_chain_sha256
        TargetCommitStageEvidenceSha256 =
            [string]$targetCommitEvidence.PayloadSha256
    }
}

function Assert-TicketboxC07TargetRecoveryGenerationFiles {
    param([Parameter(Mandatory = $true)][object]$Generation)
    return Assert-TicketboxC07RecoveryGenerationFiles $Generation
}

function Invoke-TicketboxC07TargetRecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][scriptblock]$MoneyFactsAction,
        [Parameter(Mandatory = $true)][scriptblock]$TargetSemanticAction,
        [Parameter(Mandatory = $true)][string]$TargetCommitEvidenceSha256,
        [Parameter(Mandatory = $true)][string]$MigrationEvidenceSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedResourceShapeSha256,
        [Parameter(Mandatory = $true)][string]$ExpectedMoneyFactsSha256
    )
    Assert-TicketboxC07RecoveryHostSha256 `
        $TargetCommitEvidenceSha256 "C07 target commit evidence"
    foreach ($digest in @(
        $MigrationEvidenceSha256,
        $ExpectedResourceShapeSha256,
        $ExpectedMoneyFactsSha256
    )) {
        Assert-TicketboxC07RecoverySha256 `
            $digest "C07 target generation expected digest"
    }
    $context = Get-TicketboxC07TargetRecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages @("target_committed")
    if (
        [string]$context.Authority.Descriptor.Payload.source_alembic_revision -cne
            $ExpectedSourceRevision -or
        [string]$context.Authority.Descriptor.Payload.target_alembic_revision -cne
            $TargetRevision
    ) {
        throw "C07 target generation source/target 未绑定 descriptor。"
    }
    Initialize-TicketboxC07RecoveryGenerationRoot $context.Paths | Out-Null
    $operationId = [string]$context.Authority.Receipt.operation_id
    $authoritySha256 =
        [string]$context.Authority.Receipt.authority_chain_sha256

    if (Test-Path -LiteralPath $context.Paths.ReadyRoot) {
        if (
            (Get-TicketboxPathEntryKindNoFollow `
                $context.Paths.PartialRoot) -cne "Missing" -or
            (Get-TicketboxPathEntryKindNoFollow `
                $context.Paths.CleanupPath) -cne "Missing"
        ) {
            throw "C07 target recovery READY 与 partial/cleanup residue 冲突。"
        }
        $existing = Read-TicketboxC07TargetRecoveryManifest `
            -Context $context `
            -Root $context.Paths.ReadyRoot
        Assert-TicketboxC07TargetRecoveryGenerationFiles $existing | Out-Null
        Assert-TicketboxC07RecoveryLiveSourceBinding `
            -Context $context `
            -Generation $existing `
            -SuperuserPassword $SuperuserPassword
        $remaining = Get-TicketboxC07RemainingMaintenanceMilliseconds `
            -Budget $script:TicketboxC07ActiveMaintenanceBudget `
            -MaximumMilliseconds (
                $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
            ) `
            -Label "C07 reused target recovery live evidence"
        $liveMoney = & $MoneyFactsAction `
            $context.DatabaseAuthority `
            $MigratorPassword `
            $script:TicketboxC07RecoveryDatabaseName `
            $operationId `
            "" `
            $TargetRevision `
            $context.MaintenanceDeadlineUtc `
            $remaining `
            $authoritySha256 `
            ""
        Assert-TicketboxC07TargetMoneyFactsResult `
            -Evidence $liveMoney `
            -Context $context `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -SnapshotId "" `
            -ExpectedRevision $TargetRevision `
            -MaximumRemainingCeilingMilliseconds $remaining `
            -MaintenanceAuthoritySha256 $authoritySha256 | Out-Null
        $liveSemantic = & $TargetSemanticAction `
            $context.DatabaseAuthority `
            $MigratorPassword `
            $script:TicketboxC07RecoveryDatabaseName `
            $operationId `
            "" `
            $ExpectedSourceRevision `
            $TargetRevision `
            ([string]$context.Authority.Descriptor.Payload.revision_manifest_sha256) `
            $context.MaintenanceDeadlineUtc `
            $remaining `
            $authoritySha256 `
            ""
        Assert-TicketboxC07TargetSemanticResult `
            -Evidence $liveSemantic `
            -Context $context `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -SnapshotId "" `
            -ExpectedSourceRevision $ExpectedSourceRevision `
            -ExpectedTargetRevision $TargetRevision `
            -MaximumRemainingCeilingMilliseconds $remaining `
            -MaintenanceAuthoritySha256 $authoritySha256 | Out-Null
        if (
            [string]$liveSemantic.resource_shape_sha256 -cne
                [string]$existing.Payload.database.resource_shape_sha256 -or
            [string]$liveSemantic.money_facts_sha256 -cne
                [string]$existing.Payload.database.money_facts_sha256 -or
            [string]$liveMoney.money_facts_sha256 -cne
                [string]$existing.Payload.database.money_facts_sha256 -or
            [string]$liveMoney.money_facts_sha256 -cne
                [string]$liveSemantic.money_facts_sha256
        ) {
            throw "C07 reused target generation shape/money facts 已漂移。"
        }
        return [pscustomobject]@{
            State = "target_generation_ready"
            Reused = $true
            OperationId = $operationId
            GenerationRoot = $context.Paths.ReadyRoot
            EvidenceSha256 = $existing.PayloadSha256
        }
    }
    $cleanup = Clear-TicketboxC07RecoveryPartialGeneration $context
    if ($cleanup.State -cne "cleaned") {
        throw "C07 target recovery partial cleanup_pending。"
    }

    $snapshot = $null
    $partialCreated = $false
    try {
        Assert-TicketboxC07RecoveryMaintenanceBoundary `
            -Authority $context.Authority
        $snapshot = Open-TicketboxC07RecoverySnapshot `
            -Context $context `
            -SuperuserPassword $SuperuserPassword
        if (-not [bool]$snapshot.FenceCutVerified) {
            throw "C07 target snapshot 未证明 same-session writer cut。"
        }
        $remaining = Get-TicketboxC07RemainingMaintenanceMilliseconds `
            -Budget $script:TicketboxC07ActiveMaintenanceBudget `
            -MaximumMilliseconds (
                $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
            ) `
            -Label "C07 target generation evidence"
        $moneyFacts = & $MoneyFactsAction `
            $context.DatabaseAuthority `
            $MigratorPassword `
            $script:TicketboxC07RecoveryDatabaseName `
            $operationId `
            ([string]$snapshot.SnapshotId) `
            $TargetRevision `
            $context.MaintenanceDeadlineUtc `
            $remaining `
            $authoritySha256 `
            ""
        Assert-TicketboxC07TargetMoneyFactsResult `
            -Evidence $moneyFacts `
            -Context $context `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -SnapshotId ([string]$snapshot.SnapshotId) `
            -ExpectedRevision $TargetRevision `
            -MaximumRemainingCeilingMilliseconds $remaining `
            -MaintenanceAuthoritySha256 $authoritySha256 | Out-Null
        $semantic = & $TargetSemanticAction `
            $context.DatabaseAuthority `
            $MigratorPassword `
            $script:TicketboxC07RecoveryDatabaseName `
            $operationId `
            ([string]$snapshot.SnapshotId) `
            $ExpectedSourceRevision `
            $TargetRevision `
            ([string]$context.Authority.Descriptor.Payload.revision_manifest_sha256) `
            $context.MaintenanceDeadlineUtc `
            $remaining `
            $authoritySha256 `
            ""
        Assert-TicketboxC07TargetSemanticResult `
            -Evidence $semantic `
            -Context $context `
            -Database $script:TicketboxC07RecoveryDatabaseName `
            -SnapshotId ([string]$snapshot.SnapshotId) `
            -ExpectedSourceRevision $ExpectedSourceRevision `
            -ExpectedTargetRevision $TargetRevision `
            -MaximumRemainingCeilingMilliseconds $remaining `
            -MaintenanceAuthoritySha256 $authoritySha256 | Out-Null
        if (
            [string]$semantic.resource_shape_sha256 -cne
                $ExpectedResourceShapeSha256 -or
            [string]$semantic.money_facts_sha256 -cne
                $ExpectedMoneyFactsSha256 -or
            [string]$moneyFacts.money_facts_sha256 -cne
                $ExpectedMoneyFactsSha256 -or
            [string]$semantic.money_facts_sha256 -cne
                [string]$moneyFacts.money_facts_sha256
        ) {
            throw "C07 target snapshot 未复现 committed DDL resource/money evidence。"
        }
        $assetPlan = Get-TicketboxC07RecoveryAssetSourcePlan `
            -Inventory @($snapshot.Assets) `
            -UploadRoot $context.UploadRoot
        $capacity = Get-TicketboxC07RecoveryCapacityPlan `
            -Context $context `
            -Snapshot $snapshot `
            -AssetBytes $assetPlan.SourceBytes `
            -ExpectedRevision $TargetRevision
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $context.Paths.PartialRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
        $partialCreated = $true
        $assetsRoot = Join-Path `
            $context.Paths.PartialRoot `
            $context.Paths.AssetsLeaf
        Initialize-TicketboxProtectedDirectoryAtomically `
            -Path $assetsRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
        $dumpEvidence = Invoke-TicketboxC07RecoverySnapshotDump `
            -Context $context `
            -Snapshot $snapshot `
            -SuperuserPassword $SuperuserPassword `
            -OutputPath (
                Join-Path `
                    $context.Paths.PartialRoot `
                    $context.Paths.DumpFileName
            )
        $inventoryEvidence = Write-TicketboxC07RecoveryJsonLines `
            -Path (
                Join-Path `
                    $context.Paths.PartialRoot `
                    $context.Paths.InventoryFileName
            ) `
            -Records @($assetPlan.Inventory) `
            -Kind "inventory"
        $copyRecords = New-Object System.Collections.Generic.List[object]
        foreach ($original in @($assetPlan.Originals)) {
            [void](Get-TicketboxC07RemainingMaintenanceMilliseconds `
                -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                -Label "C07 target recovery asset copy")
            Assert-TicketboxC07RecoverySnapshotAlive $snapshot
            $record = $original.Record
            $copy = Copy-TicketboxVerifiedArtifact `
                -SourcePath $original.SourcePath `
                -DestinationPath (
                    Join-Path $assetsRoot $original.PackageFile
                ) `
                -ExpectedSourceSha256 ([string]$record.image_sha256) `
                -ExpectedLength ([int64]$original.ExpectedLength) `
                -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
                -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
            $copyRecords.Add([ordered]@{
                expense_public_id = [string]$record.expense_public_id
                ledger_id = [string]$record.ledger_id
                image_reference = [string]$record.image_reference
                package_file = [string]$original.PackageFile
                source_sha256 = [string]$copy.Sha256
                database_expected_sha256 = [string]$record.image_sha256
                size_bytes = [string][int64]$copy.SizeBytes
                thumbnail_reference = [string]$record.thumbnail_reference
                thumbnail_state = [string]$original.ThumbnailState
            })
        }
        $copiesEvidence = Write-TicketboxC07RecoveryJsonLines `
            -Path (
                Join-Path `
                    $context.Paths.PartialRoot `
                    $context.Paths.CopiesFileName
            ) `
            -Records $copyRecords.ToArray() `
            -Kind "copies"
        Assert-TicketboxC07RecoverySnapshotAlive $snapshot
        $payload = New-TicketboxC07TargetRecoveryPayload `
            -Context $context `
            -Snapshot $snapshot `
            -Capacity $capacity `
            -DumpEvidence $dumpEvidence `
            -MoneyFactsEvidence $moneyFacts `
            -SemanticEvidence $semantic `
            -InventoryEvidence $inventoryEvidence `
            -CopiesEvidence $copiesEvidence `
            -TargetCommitEvidenceSha256 $TargetCommitEvidenceSha256 `
            -MigrationEvidenceSha256 $MigrationEvidenceSha256
        $manifest = Write-TicketboxC07RecoveryManifest `
            -Root $context.Paths.PartialRoot `
            -Payload $payload
        Close-TicketboxC07RecoverySnapshot $snapshot
        $snapshot = $null
        Assert-TicketboxC07RecoveryMaintenanceBoundary `
            -Authority $context.Authority
        $partial = Read-TicketboxC07TargetRecoveryManifest `
            -Context $context `
            -Root $context.Paths.PartialRoot
        Assert-TicketboxC07TargetRecoveryGenerationFiles $partial | Out-Null
        if ($partial.PayloadSha256 -cne $manifest.PayloadSha256) {
            throw "C07 target recovery partial digest 不一致。"
        }
        Publish-TicketboxVerifiedArtifactDirectory `
            -GenerationRoot $context.Paths.GenerationRoot `
            -PartialRoot $context.Paths.PartialRoot `
            -ReadyRoot $context.Paths.ReadyRoot `
            -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
            -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount | Out-Null
        $partialCreated = $false
        $ready = Read-TicketboxC07TargetRecoveryManifest `
            -Context $context `
            -Root $context.Paths.ReadyRoot
        Assert-TicketboxC07TargetRecoveryGenerationFiles $ready | Out-Null
        Assert-TicketboxC07RecoveryLiveSourceBinding `
            -Context $context `
            -Generation $ready `
            -SuperuserPassword $SuperuserPassword
        if ($ready.PayloadSha256 -cne $manifest.PayloadSha256) {
            throw "C07 target recovery READY digest 不一致。"
        }
        return [pscustomobject]@{
            State = "target_generation_ready"
            Reused = $false
            OperationId = $operationId
            GenerationRoot = $context.Paths.ReadyRoot
            EvidenceSha256 = $ready.PayloadSha256
        }
    }
    catch {
        $failure = $_.Exception
        if (
            $partialCreated -or
            (Test-Path -LiteralPath $context.Paths.PartialRoot)
        ) {
            $cleanup = Clear-TicketboxC07RecoveryPartialGeneration $context
            if ($cleanup.State -cne "cleaned") {
                throw [InvalidOperationException]::new(
                    "C07 target generation 失败且 cleanup_pending。",
                    $failure
                )
            }
        }
        [Runtime.ExceptionServices.ExceptionDispatchInfo]::Capture(
            $failure
        ).Throw()
        throw "unreachable"
    }
    finally {
        if ($null -ne $snapshot) {
            Close-TicketboxC07RecoverySnapshot $snapshot
        }
    }
}

function Read-TicketboxC07TargetRecoveryRestoreEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation
    )
    $path = $Context.Paths.RestoreEvidencePath
    if (
        -not (Test-TicketboxPathWithin $path $Generation.Root) -or
        (Test-TicketboxPathEquals $path $Generation.Root)
    ) {
        throw "C07 target restore evidence path 越出 READY generation。"
    }
    Assert-NoTicketboxAncestorReparsePoints $path
    $kind = Get-TicketboxPathEntryKindNoFollow $path
    if ($kind -ceq "Missing") { return $null }
    if ($kind -cne "File") {
        throw "C07 target restore evidence 不是普通文件。"
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount `
        -MaximumBytes $script:TicketboxC07RecoveryMaximumManifestBytes
    $envelope = ConvertFrom-TicketboxC07RecoveryEnvelopeText $artifact.Text
    $payload = $envelope.Payload
    Assert-TicketboxC07RecoveryExactProperties `
        $payload `
        @(
            "schema",
            "operation_id",
            "installation_id",
            "generation_payload_sha256",
            "source_cluster_system_identifier",
            "source_database_oid",
            "restore_database",
            "restore_database_oid",
            "restore_create_attempt_id",
            "restore_create_authority_sha256",
            "logical_server_id",
            "logical_data_generation",
            "asset_inventory_sha256",
            "asset_inventory_rows",
            "original_copies_verified",
            "isolated_asset_bytes",
            "thumbnails",
            "restore_mode",
            "restored_target_revision",
            "resource_shape_sha256",
            "money_facts_sha256",
            "result",
            "integrity_scope",
            "verified_at_utc"
        ) `
        "C07 target isolated restore evidence"
    $expected = $Generation.Payload.database
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07TargetRecoveryRestoreEvidenceSchema -or
        [string]$payload.operation_id -cne
            [string]$Context.Authority.Receipt.operation_id -or
        [string]$payload.installation_id -cne
            [string]$Context.Authority.ReleaseIdentity.InstallationId -or
        [string]$payload.generation_payload_sha256 -cne
            [string]$Generation.PayloadSha256 -or
        [string]$payload.source_cluster_system_identifier -cne
            [string]$expected.cluster_system_identifier -or
        [string]$payload.source_database_oid -cne
            [string]$expected.source_database_oid -or
        [string]$payload.restore_database -cne
            (Get-TicketboxC07RestoreDatabaseName `
                -OperationId (
                    [string]$Context.Authority.Receipt.operation_id
                ) `
                -CreateAttemptId (
                    [string]$payload.restore_create_attempt_id
                )) -or
        [string]$payload.logical_server_id -cne
            [string]$expected.server_id -or
        [string]$payload.logical_data_generation -cne
            [string]$expected.data_generation -or
        [string]$payload.asset_inventory_sha256 -cne
            [string]$Generation.Payload.asset_inventory.sha256 -or
        [uint64]$payload.asset_inventory_rows -ne
            [uint64]$Generation.Payload.asset_inventory.row_count -or
        [uint64]$payload.original_copies_verified -ne
            [uint64]$Generation.Payload.original_copies.row_count -or
        [uint64]$payload.isolated_asset_bytes -ne
            [uint64]$Generation.Payload.capacity.asset_isolated_restore_bytes -or
        [uint64]$payload.restore_database_oid -eq
            [uint64]$expected.source_database_oid -or
        [string]$payload.thumbnails -cne
            "audited_rebuildable_not_copied" -or
        [string]$payload.restore_mode -cne
            "exact_target_restore_without_forward_replay" -or
        [string]$payload.restored_target_revision -cne
            [string]$Context.Authority.Descriptor.Payload.target_alembic_revision -or
        [string]$payload.resource_shape_sha256 -cne
            [string]$expected.resource_shape_sha256 -or
        [string]$payload.money_facts_sha256 -cne
            [string]$expected.money_facts_sha256 -or
        [string]$payload.result -cne
            "target_isolated_restore_verified" -or
        [string]$payload.integrity_scope -cne
            $script:TicketboxC07RecoveryIntegrityScope
    ) {
        throw "C07 target isolated restore durable evidence binding 不一致。"
    }
    foreach ($digest in @(
        [string]$payload.generation_payload_sha256,
        [string]$payload.restore_create_authority_sha256,
        [string]$payload.asset_inventory_sha256,
        [string]$payload.resource_shape_sha256,
        [string]$payload.money_facts_sha256
    )) {
        Assert-TicketboxC07RecoverySha256 `
            $digest "C07 target restore digest"
    }
    Assert-TicketboxC07RecoveryCanonicalGuid `
        ([string]$payload.restore_create_attempt_id) `
        "C07 target restore create attempt"
    return [pscustomobject]@{
        Payload = $payload
        PayloadSha256 = $envelope.PayloadSha256
        Path = $path
    }
}

function Write-TicketboxC07TargetRecoveryRestoreEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Generation,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword
    )
    $existing = Read-TicketboxC07TargetRecoveryRestoreEvidence `
        -Context $Context `
        -Generation $Generation
    if ($null -ne $existing) {
        Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
            -Context $Context `
            -SuperuserPassword $SuperuserPassword
        return $existing
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $Context.Paths.RestoreIdentityPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $Context.Paths.RestoreCreateIntentPath) -cne "Missing"
    ) {
        throw "C07 target restore identity/create-intent residue 未清除。"
    }
    Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
        -Context $Context `
        -SuperuserPassword $SuperuserPassword
    $text = New-TicketboxC07RecoveryEnvelopeText $Payload
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Context.Paths.RestoreEvidencePath `
        -Text $text `
        -FullControlAccounts $script:TicketboxC07RecoveryFullControlAccounts `
        -OwnerAccount $script:TicketboxC07RecoveryOwnerAccount
    return Read-TicketboxC07TargetRecoveryRestoreEvidence `
        -Context $Context `
        -Generation $Generation
}

function Test-TicketboxC07TargetRecoveryGenerationRestore {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][scriptblock]$MoneyFactsAction,
        [Parameter(Mandatory = $true)][scriptblock]$TargetSemanticAction
    )
    $context = Get-TicketboxC07TargetRecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages @(
            "target_recovery_generation_ready",
            "target_isolated_restore_verified"
        )
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.ReadyRoot) -cne "Directory" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.PartialRoot) -cne "Missing"
    ) {
        throw "C07 target isolated restore 要求唯一 target READY generation。"
    }
    $generation = Read-TicketboxC07TargetRecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    $copies = Assert-TicketboxC07TargetRecoveryGenerationFiles $generation
    Assert-TicketboxC07RecoveryLiveSourceBinding `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $SuperuserPassword
    $inventory = Read-TicketboxC07RecoveryJsonLines `
        -Path $generation.InventoryPath `
        -Kind "inventory" `
        -ExpectedRows ([int]$generation.Payload.asset_inventory.row_count)
    Assert-TicketboxC07RecoveryAssetReconcile `
        -Inventory $inventory `
        -Copies $copies | Out-Null
    $durable = Read-TicketboxC07TargetRecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    if ($null -ne $durable) {
        if (
            (Get-TicketboxPathEntryKindNoFollow `
                $context.Paths.RestoreIdentityPath) -cne "Missing" -or
            (Get-TicketboxPathEntryKindNoFollow `
                $context.Paths.RestoreCreateIntentPath) -cne "Missing"
        ) {
            throw "C07 target restore evidence 与 identity residue 冲突。"
        }
        Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
            -Context $context `
            -SuperuserPassword $SuperuserPassword
        return [pscustomobject]@{
            State = "target_isolated_restore_verified"
            OperationId = [string]$durable.Payload.operation_id
            EvidenceSha256 = $durable.PayloadSha256
            GenerationEvidenceSha256 = $generation.PayloadSha256
            InventoryRows = [int]$durable.Payload.asset_inventory_rows
            OriginalCopies =
                [int]$durable.Payload.original_copies_verified
            RestoreDatabaseState = "cleaned"
            Reused = $true
        }
    }
    if (
        [string]$context.Authority.Receipt.stage -ceq
            "target_isolated_restore_verified"
    ) {
        throw "C07 target_isolated_restore_verified 缺少 durable evidence。"
    }
    $preCleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
        -Context $context `
        -SuperuserPassword $SuperuserPassword `
        -Generation $generation
    if ([string]$preCleanup.State -cne "cleaned") {
        throw "C07 target isolated restore 前次数据库仍 cleanup_pending。"
    }

    $restoreIdentity = $null
    $verification = $null
    $operationId = [string]$context.Authority.Receipt.operation_id
    try {
        $restoreIdentity =
            New-TicketboxC07RecoveryRestoreDatabaseBound `
                -Context $context `
                -Generation $generation `
                -SuperuserPassword $SuperuserPassword
        Write-TicketboxC07RecoveryRestoreIdentityArtifact `
            -Context $context `
            -Generation $generation `
            -Identity $restoreIdentity | Out-Null
        Invoke-TicketboxC07RecoveryArchiveRestore `
            -Context $context `
            -SuperuserPassword $SuperuserPassword `
            -RestoreIdentity $restoreIdentity `
            -DumpPath $generation.DumpPath
        $restored = Get-TicketboxC07RestoredInventory `
            -Context $context `
            -SuperuserPassword $SuperuserPassword `
            -RestoreIdentity $restoreIdentity
        $expectedDatabase = $generation.Payload.database
        if (
            [string]$restored.Meta.database -cne
                [string]$restoreIdentity.Database -or
            [string]$restored.Meta.database_oid -cne
                [string]$restoreIdentity.DatabaseOid -or
            [string]$restored.Meta.cluster_system_identifier -cne
                [string]$restoreIdentity.ClusterSystemIdentifier -or
            [string]$restored.Meta.server_id -cne
                [string]$expectedDatabase.server_id -or
            [string]$restored.Meta.data_generation -cne
                [string]$expectedDatabase.data_generation -or
            [string]::Join("`n", @($restored.Meta.alembic_heads)) -cne
                $TargetRevision -or
            [string]$restored.Meta.database_oid -ceq
                [string]$expectedDatabase.source_database_oid
        ) {
            throw "C07 target restore database/logical/revision identity 对账失败。"
        }
        $restoredDigest = Get-TicketboxC07RecoveryJsonLinesDigest `
            -Records @($restored.Assets) `
            -Kind "inventory"
        if (
            $restoredDigest.Sha256 -cne
                [string]$generation.Payload.asset_inventory.sha256 -or
            $restoredDigest.SizeBytes -ne
                [int64]$generation.Payload.asset_inventory.size_bytes -or
            $restoredDigest.RowCount -ne
                [int]$generation.Payload.asset_inventory.row_count
        ) {
            throw "C07 target restore PostgreSQL asset inventory 不一致。"
        }
        $restoreDatabase = [string]$restoreIdentity.Database
        Invoke-TicketboxC07Sql `
            -Authority $context.DatabaseAuthority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Sql (
                "GRANT CONNECT ON DATABASE `"$restoreDatabase`" " +
                "TO `"$script:TicketboxC07MigratorRole`";"
            ) `
            -Label "C07 target restore evidence window open" | Out-Null
        try {
            $remaining = Get-TicketboxC07RemainingMaintenanceMilliseconds `
                -Budget $script:TicketboxC07ActiveMaintenanceBudget `
                -MaximumMilliseconds (
                    $script:TicketboxC07RecoveryNativeTimeoutMilliseconds
                ) `
                -Label "C07 target restore semantic evidence"
            $authoritySha256 =
                [string]$context.Authority.Receipt.authority_chain_sha256
            $moneyFacts = & $MoneyFactsAction `
                $context.DatabaseAuthority `
                $MigratorPassword `
                $restoreDatabase `
                $operationId `
                "" `
                $TargetRevision `
                $context.MaintenanceDeadlineUtc `
                $remaining `
                $authoritySha256 `
                ([string]$restoreIdentity.CreateAttemptId)
            Assert-TicketboxC07TargetMoneyFactsResult `
                -Evidence $moneyFacts `
                -Context $context `
                -Database $restoreDatabase `
                -SnapshotId "" `
                -ExpectedRevision $TargetRevision `
                -MaximumRemainingCeilingMilliseconds $remaining `
                -MaintenanceAuthoritySha256 $authoritySha256 | Out-Null
            $semantic = & $TargetSemanticAction `
                $context.DatabaseAuthority `
                $MigratorPassword `
                $restoreDatabase `
                $operationId `
                "" `
                $ExpectedSourceRevision `
                $TargetRevision `
                ([string]$context.Authority.Descriptor.Payload.revision_manifest_sha256) `
                $context.MaintenanceDeadlineUtc `
                $remaining `
                $authoritySha256 `
                ([string]$restoreIdentity.CreateAttemptId)
            Assert-TicketboxC07TargetSemanticResult `
                -Evidence $semantic `
                -Context $context `
                -Database $restoreDatabase `
                -SnapshotId "" `
                -ExpectedSourceRevision $ExpectedSourceRevision `
                -ExpectedTargetRevision $TargetRevision `
                -MaximumRemainingCeilingMilliseconds $remaining `
                -MaintenanceAuthoritySha256 $authoritySha256 | Out-Null
        }
        finally {
            Invoke-TicketboxC07Sql `
                -Authority $context.DatabaseAuthority `
                -Database "postgres" `
                -Role "postgres" `
                -Password $SuperuserPassword `
                -Sql @"
REVOKE CONNECT ON DATABASE "$restoreDatabase"
    FROM "$script:TicketboxC07MigratorRole";
SELECT pg_terminate_backend(pid, 5000)
FROM pg_stat_activity
WHERE datname = '$restoreDatabase'
  AND usename = '$script:TicketboxC07MigratorRole'
  AND pid <> pg_backend_pid();
"@ `
                -Label "C07 target restore evidence window close" | Out-Null
        }
        if (
            [string]$semantic.resource_shape_sha256 -cne
                [string]$expectedDatabase.resource_shape_sha256 -or
            [string]$semantic.money_facts_sha256 -cne
                [string]$expectedDatabase.money_facts_sha256 -or
            [string]$moneyFacts.money_facts_sha256 -cne
                [string]$expectedDatabase.money_facts_sha256 -or
            [string]$moneyFacts.money_facts_sha256 -cne
                [string]$semantic.money_facts_sha256
        ) {
            throw "C07 target restore shape/money facts 与 live target generation 不一致。"
        }
        $postEvidence = Get-TicketboxC07RestoredInventory `
            -Context $context `
            -SuperuserPassword $SuperuserPassword `
            -RestoreIdentity $restoreIdentity
        $postDigest = Get-TicketboxC07RecoveryJsonLinesDigest `
            -Records @($postEvidence.Assets) `
            -Kind "inventory"
        if (
            [string]::Join("`n", @($postEvidence.Meta.alembic_heads)) -cne
                $TargetRevision -or
            $postDigest.Sha256 -cne $restoredDigest.Sha256 -or
            $postDigest.SizeBytes -ne $restoredDigest.SizeBytes -or
            $postDigest.RowCount -ne $restoredDigest.RowCount
        ) {
            throw "C07 target restore evidence read 改变了 revision/asset facts。"
        }
        $reconcile = Assert-TicketboxC07RecoveryAssetReconcile `
            -Inventory @($postEvidence.Assets) `
            -Copies $copies
        $isolatedAssets = Test-TicketboxC07RecoveryIsolatedAssets `
            -Context $context `
            -Generation $generation `
            -Inventory @($postEvidence.Assets) `
            -Copies $copies
        $verificationPayload = [ordered]@{
            schema = $script:TicketboxC07TargetRecoveryRestoreEvidenceSchema
            operation_id = $operationId
            installation_id =
                [string]$context.Authority.ReleaseIdentity.InstallationId
            generation_payload_sha256 = $generation.PayloadSha256
            source_cluster_system_identifier =
                [string]$expectedDatabase.cluster_system_identifier
            source_database_oid =
                [string]$expectedDatabase.source_database_oid
            restore_database = [string]$restoreIdentity.Database
            restore_database_oid = [string]$restoreIdentity.DatabaseOid
            restore_create_attempt_id =
                [string]$restoreIdentity.CreateAttemptId
            restore_create_authority_sha256 =
                [string]$restoreIdentity.CreateAuthoritySha256
            logical_server_id = [string]$expectedDatabase.server_id
            logical_data_generation =
                [string]$expectedDatabase.data_generation
            asset_inventory_sha256 = $postDigest.Sha256
            asset_inventory_rows = [string][int]$reconcile.InventoryRows
            original_copies_verified =
                [string][int]$reconcile.OriginalCopies
            isolated_asset_bytes =
                [string][int64]$isolatedAssets.Bytes
            thumbnails = "audited_rebuildable_not_copied"
            restore_mode = "exact_target_restore_without_forward_replay"
            restored_target_revision = $TargetRevision
            resource_shape_sha256 =
                [string]$semantic.resource_shape_sha256
            money_facts_sha256 =
                [string]$moneyFacts.money_facts_sha256
            result = "target_isolated_restore_verified"
            integrity_scope = $script:TicketboxC07RecoveryIntegrityScope
            verified_at_utc = [DateTime]::UtcNow.ToString("o")
        }
        $verificationText = $verificationPayload |
            ConvertTo-Json -Depth 8 -Compress
        $verification = [pscustomobject]@{
            Payload = $verificationPayload
            EvidenceSha256 =
                Get-TicketboxC07RecoveryTextSha256 $verificationText
        }
    }
    finally {
        if ($null -ne $restoreIdentity) {
            $cleanup = Clear-TicketboxC07RecoveryRestoreDatabase `
                -Context $context `
                -SuperuserPassword $SuperuserPassword `
                -Generation $generation
            if ([string]$cleanup.State -cne "cleaned") {
                $verification = $null
                throw "C07 target restore 对账完成但 cleanup_pending。"
            }
        }
    }
    if ($null -eq $verification) {
        throw "C07 target restore 未产生 verified evidence。"
    }
    $durable = Write-TicketboxC07TargetRecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation `
        -Payload $verification.Payload `
        -SuperuserPassword $SuperuserPassword
    if (
        [string]$durable.PayloadSha256 -cne
            [string]$verification.EvidenceSha256
    ) {
        throw "C07 target restore durable evidence digest 复读不一致。"
    }
    return [pscustomobject]@{
        State = "target_isolated_restore_verified"
        OperationId = $operationId
        EvidenceSha256 = $durable.PayloadSha256
        GenerationEvidenceSha256 = $generation.PayloadSha256
        InventoryRows = [int]$verification.Payload.asset_inventory_rows
        OriginalCopies =
            [int]$verification.Payload.original_copies_verified
        RestoreDatabaseState = "cleaned"
        Reused = $false
    }
}

function Read-TicketboxC07ProductionTargetRecoveryGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock,
        [AllowNull()][Security.SecureString]$SuperuserPassword
    )
    $context = Get-TicketboxC07TargetRecoveryContext `
        -DataRoot $DataRoot `
        -LifecycleLock $LifecycleLock `
        -SuperuserPassword $SuperuserPassword `
        -AllowedStages @("target_isolated_restore_verified")
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.ReadyRoot) -cne "Directory" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.PartialRoot) -cne "Missing"
    ) {
        throw "C07 production target recovery 要求唯一 READY generation。"
    }
    $generation = Read-TicketboxC07TargetRecoveryManifest `
        -Context $context `
        -Root $context.Paths.ReadyRoot
    Assert-TicketboxC07TargetRecoveryGenerationFiles $generation | Out-Null
    Assert-TicketboxC07RecoveryLiveSourceBinding `
        -Context $context `
        -Generation $generation `
        -SuperuserPassword $SuperuserPassword
    $restore = Read-TicketboxC07TargetRecoveryRestoreEvidence `
        -Context $context `
        -Generation $generation
    if ($null -eq $restore) {
        throw "C07 production target recovery 缺少 zero-replay restore evidence。"
    }
    if (
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.RestoreIdentityPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow `
            $context.Paths.RestoreCreateIntentPath) -cne "Missing"
    ) {
        throw "C07 production target recovery 检出 restore residue。"
    }
    Assert-TicketboxC07RecoveryNoRestoreDatabaseResidue `
        -Context $context `
        -SuperuserPassword $SuperuserPassword
    return [pscustomobject]@{
        Schema = $script:TicketboxC07ProductionTargetRecoveryGenerationSchema
        OperationId = [string]$context.Authority.Receipt.operation_id
        Result = "production_target_recovery_generation_verified"
        Payload = $generation.Payload
        PayloadSha256 = [string]$generation.PayloadSha256
        ManifestPath = [string]$generation.ManifestPath
        DumpPath = [string]$generation.DumpPath
        InventoryPath = [string]$generation.InventoryPath
        CopiesPath = [string]$generation.CopiesPath
        Root = [string]$generation.Root
        LifecycleAuthorityChainSha256 =
            [string]$generation.LifecycleAuthorityChainSha256
        TargetCommitStageEvidenceSha256 =
            [string]$generation.TargetCommitStageEvidenceSha256
        RestoreEvidence = [pscustomobject]@{
            Payload = $restore.Payload
            PayloadSha256 = [string]$restore.PayloadSha256
            Path = [string]$restore.Path
        }
    }
}
