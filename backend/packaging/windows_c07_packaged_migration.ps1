#Requires -Version 5.1

<#
.SYNOPSIS
  Invoke the frozen C07 migration helper as the lifecycle coordinator's only DDL action.
.DESCRIPTION
  Dot-source windows_database_safety.ps1, windows_c07_database.ps1, and
  windows_c07_lifecycle.ps1 first.  The caller retains all lifecycle/database
  authority.  Fresh-source bootstrap receives empty stdin and returns its exact
  five-field source receipt.  Production receives only the exact frozen
  coordinator context and returns exact nine-field migration evidence.  Each
  action uses one protected temporary pgpass file.  The helper remains locked
  against write/delete replacement from pre-execution hash verification until
  post-execution identity verification completes.
#>

$script:TicketboxC07PackagedMigrationResultSchema =
    "ticketbox-c07-migration-evidence-v1"
$script:TicketboxC07PackagedMigrationContextSchema =
    "ticketbox-c07-production-migration-context-v5"
$script:TicketboxC07PackagedFreshSourceResultSchema =
    "ticketbox-c07-fresh-source-bootstrap-result-v1"
$script:TicketboxC07PackagedMaintenancePlanSchema =
    "ticketbox-c07-maintenance-plan-v2"
$script:TicketboxC07PackagedMaintenanceResultSchema =
    "ticketbox-c07-maintenance-upgrade-result-v3"
$script:TicketboxC07PackagedMoneyFactsResultSchema =
    "ticketbox-c07-money-facts-result-v2"
$script:TicketboxC07PackagedTargetSemanticResultSchema =
    "ticketbox-c07-target-semantic-result-v1"
$script:TicketboxC07PackagedMigrationTimeoutMs = 1500000

function Get-TicketboxC07PackagedRemainingTimeoutMilliseconds {
    param(
        [Parameter(Mandatory = $true)][string]$DeadlineUtc,
        [Parameter(Mandatory = $true)][int]$MaximumMilliseconds
    )
    [DateTime]$parsed = [DateTime]::MinValue
    if (
        -not [DateTime]::TryParseExact(
            $DeadlineUtc,
            "o",
            [Globalization.CultureInfo]::InvariantCulture,
            (
                [Globalization.DateTimeStyles]::AssumeUniversal -bor
                [Globalization.DateTimeStyles]::AdjustToUniversal
            ),
            [ref]$parsed
        )
    ) {
        throw "C07 packaged migration deadline 不是 canonical UTC。"
    }
    $remaining = ($parsed - [DateTime]::UtcNow).TotalMilliseconds
    if ($remaining -lt 1000) {
        throw "C07 packaged migration whole-operation window 已耗尽。"
    }
    return [int][Math]::Floor(
        [Math]::Min([double]$MaximumMilliseconds, $remaining)
    )
}

function Assert-TicketboxC07PackagedMigrationDependencies {
    foreach ($commandName in @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "Assert-TicketboxC07MigrationHelperLeaseUnchanged",
        "Assert-TicketboxC07ExactProperties",
        "Assert-TicketboxC07Sha256",
        "Close-TicketboxC07MigrationHelperLease",
        "ConvertTo-TicketboxC07CompactJson",
        "Get-TicketboxC07TextSha256",
        "Get-TicketboxPathEntryKindNoFollow",
        "Invoke-TicketboxC07WithPlainSecret",
        "Invoke-TicketboxBoundedNativeProcess",
        "New-TicketboxC07LocalDatabaseUrl",
        "New-TicketboxProtectedPgPassFile",
        "Open-TicketboxC07VerifiedMigrationHelperLease",
        "Remove-TicketboxProtectedPgPassArtifact",
        "Test-TicketboxPathEquals"
    )) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "C07 packaged migration bridge 缺少依赖：$commandName"
        }
    }
}

function Get-TicketboxC07PackagedJsonLine {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $newlineLength = 0
    if (
        $StandardOutput.EndsWith(
            "`r`n",
            [System.StringComparison]::Ordinal
        )
    ) {
        $newlineLength = 2
    }
    elseif (
        $StandardOutput.EndsWith(
            "`n",
            [System.StringComparison]::Ordinal
        )
    ) {
        $newlineLength = 1
    }
    if (
        $StandardOutput.Length -le $newlineLength -or
        $StandardOutput.Length -gt 16384 -or
        $newlineLength -eq 0
    ) {
        throw "$Label 未返回唯一的 bounded JSON 行。"
    }
    $jsonLine = $StandardOutput.Substring(
        0,
        $StandardOutput.Length - $newlineLength
    )
    if ($jsonLine.IndexOf("`r") -ge 0 -or $jsonLine.IndexOf("`n") -ge 0) {
        throw "$Label 未返回唯一的 bounded JSON 行。"
    }
    return $jsonLine
}

function ConvertFrom-TicketboxC07PackagedMigrationResult {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision
    )

    $jsonLine = Get-TicketboxC07PackagedJsonLine `
        -StandardOutput $StandardOutput `
        -Label "C07 packaged migration helper"
    try {
        $result = $jsonLine | ConvertFrom-Json
    }
    catch {
        throw "C07 packaged migration helper stdout 不是有效 JSON。"
    }
    Assert-TicketboxC07ExactProperties `
        -Value $result `
        -ExpectedNames @(
            "schema",
            "operation_id",
            "source_revision",
            "target_revision",
            "result",
            "alembic_revision",
            "money_facts_sha256",
            "statistics_table_count",
            "statistics_table_set_sha256"
        ) `
        -ArtifactName "packaged migration result"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.money_facts_sha256) `
        "C07 packaged migration canonical money facts"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.statistics_table_set_sha256) `
        "C07 packaged migration statistics table set"
    $canonical = ConvertTo-TicketboxC07CompactJson $result
    if (
        $jsonLine -cne $canonical -or
        [string]$result.schema -cne
            $script:TicketboxC07PackagedMigrationResultSchema -or
        [string]$result.operation_id -cne $OperationId -or
        [string]$result.source_revision -cne $SourceRevision -or
        [string]$result.target_revision -cne $TargetRevision -or
        [string]$result.alembic_revision -cne $TargetRevision -or
        [int]$result.statistics_table_count -ne 18 -or
        [string]$result.result -cnotin @(
            "target_committed",
            "target_observed_after_interruption"
        )
    ) {
        throw "C07 packaged migration helper result 未绑定 exact operation/revision。"
    }
    return $result
}

function ConvertFrom-TicketboxC07PackagedFreshSourceResult {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision
    )

    $jsonLine = Get-TicketboxC07PackagedJsonLine `
        -StandardOutput $StandardOutput `
        -Label "C07 fresh-source helper"
    try {
        $result = $jsonLine | ConvertFrom-Json
    }
    catch {
        throw "C07 fresh-source helper stdout 不是有效 JSON。"
    }
    Assert-TicketboxC07ExactProperties `
        -Value $result `
        -ExpectedNames @(
            "schema",
            "source_revision",
            "target_revision",
            "result",
            "alembic_revision"
        ) `
        -ArtifactName "packaged fresh-source result"
    $canonical = ConvertTo-TicketboxC07CompactJson $result
    if (
        $jsonLine -cne $canonical -or
        [string]$result.schema -cne
            $script:TicketboxC07PackagedFreshSourceResultSchema -or
        [string]$result.source_revision -cne $SourceRevision -or
        [string]$result.target_revision -cne $TargetRevision -or
        [string]$result.result -cne "source_committed" -or
        [string]$result.alembic_revision -cne $SourceRevision
    ) {
        throw "C07 fresh-source helper result 未绑定 exact source/target。"
    }
    return $result
}

function ConvertFrom-TicketboxC07PackagedMaintenancePlan {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$SourceRevision
    )

    $jsonLine = Get-TicketboxC07PackagedJsonLine `
        -StandardOutput $StandardOutput `
        -Label "C07 packaged maintenance plan"
    try {
        $result = $jsonLine | ConvertFrom-Json
    }
    catch {
        throw "C07 packaged maintenance plan stdout 不是有效 JSON。"
    }
    Assert-TicketboxC07ExactProperties `
        -Value $result `
        -ExpectedNames @(
            "schema",
            "operation_kind",
            "source_revision",
            "target_revision",
            "upgrade_required",
            "revision_manifest",
            "revision_manifest_sha256"
        ) `
        -ArtifactName "packaged maintenance plan"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.revision_manifest_sha256) `
        "C07 packaged revision manifest"
    Assert-TicketboxC07ExactProperties `
        -Value $result.revision_manifest `
        -ExpectedNames @(
            "schema",
            "operation_kind",
            "source_revision",
            "target_revision",
            "revisions"
        ) `
        -ArtifactName "packaged revision manifest"
    $revisions = @($result.revision_manifest.revisions)
    if ($revisions.Count -ne 1) {
        throw "C07 packaged revision manifest 必须只有 exact C07 revision。"
    }
    foreach ($revision in $revisions) {
        Assert-TicketboxC07ExactProperties `
            -Value $revision `
            -ExpectedNames @(
                "revision",
                "down_revision",
                "module_sha256",
                "transactionality",
                "reversibility",
                "downgrade_guard",
                "resources",
                "asset_recovery"
            ) `
            -ArtifactName "packaged revision manifest item"
        Assert-TicketboxC07LowerSha256 `
            ([string]$revision.module_sha256) `
            "C07 packaged revision module"
    }
    $manifestCanonical = ConvertTo-TicketboxC07CompactJson (
        $result.revision_manifest
    )
    $manifestSha256 = (
        Get-TicketboxC07TextSha256 $manifestCanonical
    ).ToLowerInvariant()
    if (
        $jsonLine -cne (ConvertTo-TicketboxC07CompactJson $result) -or
        [string]$result.schema -cne
            $script:TicketboxC07PackagedMaintenancePlanSchema -or
        [string]$result.source_revision -cne $SourceRevision -or
        [string]$result.source_revision -cne "20260722_0001" -or
        [string]$result.operation_kind -cne
            "c07_money_minor_bigint_v1" -or
        [string]$result.target_revision -cne "20260729_0001" -or
        [string]$result.revision_manifest.schema -cne
            "ticketbox-c07-revision-manifest-v1" -or
        [string]$result.revision_manifest.operation_kind -cne
            [string]$result.operation_kind -or
        [string]$result.revision_manifest.source_revision -cne
            [string]$result.source_revision -or
        [string]$result.revision_manifest.target_revision -cne
            [string]$result.target_revision -or
        [string]$result.revision_manifest_sha256 -cne $manifestSha256 -or
        $result.upgrade_required -isnot [bool] -or
        -not [bool]$result.upgrade_required
    ) {
        throw "C07 packaged maintenance plan 未绑定 exact source/head。"
    }
    return $result
}

function ConvertFrom-TicketboxC07PackagedMaintenanceResult {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)]
        [ValidateSet("isolated_replay")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs
    )

    $jsonLine = Get-TicketboxC07PackagedJsonLine `
        -StandardOutput $StandardOutput `
        -Label "C07 packaged maintenance upgrade"
    try {
        $result = $jsonLine | ConvertFrom-Json
    }
    catch {
        throw "C07 packaged maintenance upgrade stdout 不是有效 JSON。"
    }
    Assert-TicketboxC07ExactProperties `
        -Value $result `
        -ExpectedNames @(
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
        -ArtifactName "packaged maintenance result"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.target_shape_sha256) `
        "C07 packaged maintenance target shape"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.money_facts_sha256) `
        "C07 packaged maintenance money facts"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.resource_shape_sha256) `
        "C07 packaged maintenance resource shape"
    Assert-TicketboxC07Sha256 `
        $RevisionManifestSha256 `
        "C07 packaged maintenance expected revision manifest"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.revision_manifest_sha256) `
        "C07 packaged maintenance revision manifest"
    Assert-TicketboxC07Sha256 `
        $MaintenanceAuthoritySha256 `
        "C07 packaged maintenance authority"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.maintenance_authority_sha256) `
        "C07 packaged result maintenance authority"
    if (
        $jsonLine -cne (ConvertTo-TicketboxC07CompactJson $result) -or
        [string]$result.schema -cne
            $script:TicketboxC07PackagedMaintenanceResultSchema -or
        [string]$result.mode -cne $Mode -or
        [string]$result.operation_id -cne $OperationId -or
        [string]$result.source_revision -cne $SourceRevision -or
        [string]$result.target_revision -cne $TargetRevision -or
        [string]$result.revision_manifest_sha256 -cne
            $RevisionManifestSha256.ToLowerInvariant() -or
        [string]$result.maintenance_authority_sha256 -cne
            $MaintenanceAuthoritySha256.ToLowerInvariant() -or
        [int]$result.maintenance_remaining_ceiling_ms -ne
            $MaintenanceRemainingCeilingMs -or
        [string]$result.alembic_revision -cne $TargetRevision -or
        [string]$result.result -cne "isolated_forward_replay_verified"
    ) {
        throw "C07 packaged maintenance result 未绑定 exact operation/revision。"
    }
    return $result
}

function ConvertFrom-TicketboxC07PackagedMoneyFactsResult {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Database,
        [AllowEmptyString()][Parameter(Mandatory = $true)]
        [string]$SnapshotId,
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs
    )
    $jsonLine = Get-TicketboxC07PackagedJsonLine `
        -StandardOutput $StandardOutput `
        -Label "C07 packaged money-facts read"
    try { $result = $jsonLine | ConvertFrom-Json }
    catch { throw "C07 packaged money-facts stdout 不是有效 JSON。" }
    Assert-TicketboxC07ExactProperties `
        -Value $result `
        -ExpectedNames @(
            "schema",
            "operation_id",
            "database",
            "snapshot_id",
            "maintenance_authority_sha256",
            "maintenance_remaining_ceiling_ms",
            "alembic_revision",
            "money_facts_sha256"
        ) `
        -ArtifactName "packaged money-facts result"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.money_facts_sha256) `
        "packaged money facts"
    Assert-TicketboxC07Sha256 `
        $MaintenanceAuthoritySha256 `
        "packaged money-facts maintenance authority"
    Assert-TicketboxC07LowerSha256 `
        ([string]$result.maintenance_authority_sha256) `
        "packaged money-facts result authority"
    if (
        $jsonLine -cne (ConvertTo-TicketboxC07CompactJson $result) -or
        [string]$result.schema -cne
            $script:TicketboxC07PackagedMoneyFactsResultSchema -or
        [string]$result.operation_id -cne $OperationId -or
        [string]$result.database -cne $Database -or
        [string]$result.snapshot_id -cne $SnapshotId -or
        [string]$result.maintenance_authority_sha256 -cne
            $MaintenanceAuthoritySha256.ToLowerInvariant() -or
        [int]$result.maintenance_remaining_ceiling_ms -ne
            $MaintenanceRemainingCeilingMs -or
        [string]$result.alembic_revision -cne $ExpectedRevision
    ) {
        throw "C07 packaged money-facts result 未绑定 exact snapshot/database。"
    }
    return $result
}

function ConvertFrom-TicketboxC07PackagedTargetSemanticResult {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Database,
        [AllowEmptyString()][Parameter(Mandatory = $true)]
        [string]$SnapshotId,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs
    )
    $jsonLine = Get-TicketboxC07PackagedJsonLine `
        -StandardOutput $StandardOutput `
        -Label "C07 packaged target-semantic read"
    try { $result = $jsonLine | ConvertFrom-Json }
    catch { throw "C07 packaged target-semantic stdout 不是有效 JSON。" }
    Assert-TicketboxC07ExactProperties `
        -Value $result `
        -ExpectedNames @(
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
        -ArtifactName "packaged target-semantic result"
    foreach ($field in @(
        "revision_manifest_sha256",
        "maintenance_authority_sha256",
        "resource_shape_sha256",
        "money_facts_sha256"
    )) {
        Assert-TicketboxC07LowerSha256 `
            ([string]$result.$field) `
            "C07 packaged target-semantic $field"
    }
    Assert-TicketboxC07Sha256 `
        $RevisionManifestSha256 `
        "C07 packaged target-semantic expected revision manifest"
    Assert-TicketboxC07Sha256 `
        $MaintenanceAuthoritySha256 `
        "C07 packaged target-semantic expected authority"
    if (
        $jsonLine -cne (ConvertTo-TicketboxC07CompactJson $result) -or
        [string]$result.schema -cne
            $script:TicketboxC07PackagedTargetSemanticResultSchema -or
        [string]$result.operation_id -cne $OperationId -or
        [string]$result.database -cne $Database -or
        [string]$result.snapshot_id -cne $SnapshotId -or
        [string]$result.source_revision -cne $SourceRevision -or
        [string]$result.target_revision -cne $TargetRevision -or
        [string]$result.alembic_revision -cne $TargetRevision -or
        [string]$result.revision_manifest_sha256 -cne
            $RevisionManifestSha256.ToLowerInvariant() -or
        [string]$result.maintenance_authority_sha256 -cne
            $MaintenanceAuthoritySha256.ToLowerInvariant() -or
        [int]$result.maintenance_remaining_ceiling_ms -ne
            $MaintenanceRemainingCeilingMs
    ) {
        throw "C07 packaged target-semantic result 未绑定 exact target/snapshot。"
    }
    return $result
}

function ConvertTo-TicketboxC07PackagedMigrationHelperEvidence {
    param([Parameter(Mandatory = $true)][object]$MigrationHelperEvidence)

    Assert-TicketboxC07ExactProperties `
        -Value $MigrationHelperEvidence `
        -ExpectedNames @("RelativePath", "Size", "Sha256") `
        -ArtifactName "packaged migration helper evidence"
    if (
        [string]$MigrationHelperEvidence.RelativePath -cne
            "ticketbox-c07-migrator.exe" -or
        [int64]$MigrationHelperEvidence.Size -lt 1
    ) {
        throw "C07 packaged migration helper release path/size evidence 无效。"
    }
    Assert-TicketboxC07Sha256 `
        ([string]$MigrationHelperEvidence.Sha256) `
        "packaged migration helper release SHA-256"
    return [pscustomobject][ordered]@{
        RelativePath = [string]$MigrationHelperEvidence.RelativePath
        Size = [int64]$MigrationHelperEvidence.Size
        Sha256 = [string]$MigrationHelperEvidence.Sha256
    }
}

function Assert-TicketboxC07PackagedMigrationHelper {
    param(
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$ExpectedMigrationHelperPath
    )

    $helper = [System.IO.Path]::GetFullPath($MigrationHelperPath)
    $evidence = ConvertTo-TicketboxC07PackagedMigrationHelperEvidence `
        $MigrationHelperEvidence
    if (
        -not (
            Test-TicketboxPathEquals `
                $helper `
                ([System.IO.Path]::GetFullPath($ExpectedMigrationHelperPath))
        )
    ) {
        throw "C07 packaged migration helper path 与 release identity 不一致。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $helper) -cne "File") {
        throw "C07 packaged migration helper 不是 regular frozen payload file。"
    }
    Assert-NoTicketboxAncestorReparsePoints $helper
    return [pscustomobject][ordered]@{
        Path = $helper
        Evidence = $evidence
    }
}

function New-TicketboxC07MigrationHelperChildEnvironment {
    param(
        [AllowEmptyString()][string]$PgPassFilePath = ""
    )

    $childEnvironment = @{}
    foreach (
        $entry in [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).GetEnumerator()
    ) {
        $name = [string]$entry.Key
        if (
            [string]::IsNullOrEmpty($name) -or
            $name.StartsWith(
                "=",
                [System.StringComparison]::Ordinal
            )
        ) {
            # Do not copy Windows '=C:' per-drive pseudo variables into the
            # explicit child environment block. The helper uses absolute paths.
            continue
        }
        if (
            $name.StartsWith(
                "PG",
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            # libpq accepts connection, service, SSL, target-session and session
            # defaults through PG*. None are ambient authority for C07.
            continue
        }
        $childEnvironment[$name] = [string]$entry.Value
    }
    if (-not [string]::IsNullOrWhiteSpace($PgPassFilePath)) {
        $childEnvironment["PGPASSFILE"] =
            [System.IO.Path]::GetFullPath($PgPassFilePath)
    }
    return $childEnvironment
}

function Invoke-TicketboxC07BoundMigrationHelper {
    param(
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$ExpectedMigrationHelperPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [AllowEmptyString()][string]$PgPassFilePath = "",
        [Parameter(Mandatory = $true)][AllowEmptyString()]
        [string]$StandardInputText,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $binding = Assert-TicketboxC07PackagedMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    $pgpassArgumentIndexes = @(
        for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
            if ([string]$Arguments[$index] -ceq "--pgpassfile") {
                $index
            }
        }
    )
    if ([string]::IsNullOrWhiteSpace($PgPassFilePath)) {
        if ($pgpassArgumentIndexes.Count -ne 0) {
            throw "C07 packaged migration helper 不得携带未绑定的 pgpass 参数。"
        }
        $childEnvironment = New-TicketboxC07MigrationHelperChildEnvironment
    }
    else {
        $trustedPgPassFile = [System.IO.Path]::GetFullPath($PgPassFilePath)
        if ((Get-TicketboxPathEntryKindNoFollow $trustedPgPassFile) -cne "File") {
            throw "C07 packaged migration pgpass 不是受保护普通文件。"
        }
        Assert-NoTicketboxAncestorReparsePoints $trustedPgPassFile
        if (
            $pgpassArgumentIndexes.Count -ne 1 -or
            $pgpassArgumentIndexes[0] + 1 -ge $Arguments.Count
        ) {
            throw "C07 packaged migration helper 必须携带唯一 pgpass 参数。"
        }
        $argumentPgPassFile = [System.IO.Path]::GetFullPath(
            [string]$Arguments[$pgpassArgumentIndexes[0] + 1]
        )
        if (-not (Test-TicketboxPathEquals $argumentPgPassFile $trustedPgPassFile)) {
            throw "C07 packaged migration helper 的 argv/environment pgpass 不一致。"
        }
        $childEnvironment = New-TicketboxC07MigrationHelperChildEnvironment `
            -PgPassFilePath $trustedPgPassFile
    }
    $lease = $null
    try {
        $lease = Open-TicketboxC07VerifiedMigrationHelperLease `
            -Path $binding.Path `
            -ExpectedRelativePath $binding.Evidence.RelativePath `
            -ExpectedSize $binding.Evidence.Size `
            -ExpectedSha256 $binding.Evidence.Sha256
        $result = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $lease.Path `
            -Arguments $Arguments `
            -StandardInputText $StandardInputText `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -Label $Label `
            -ChildEnvironment $childEnvironment
        return $result
    }
    finally {
        try {
            if ($null -ne $lease) {
                Assert-TicketboxC07MigrationHelperLeaseUnchanged $lease
            }
        }
        finally {
            Close-TicketboxC07MigrationHelperLease $lease
        }
    }
}

function Invoke-TicketboxC07PackagedMoneyFactsAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [AllowEmptyString()][string]$SnapshotId = "",
        [Parameter(Mandatory = $true)][string]$ExpectedRevision,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [AllowEmptyString()][string]$CreateAttemptId = ""
    )
    Assert-TicketboxC07PackagedMigrationDependencies
    $helperBinding = Assert-TicketboxC07PackagedMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    $expectedDatabase = if ([string]::IsNullOrEmpty($CreateAttemptId)) {
        "ticketbox"
    }
    else {
        Get-TicketboxC07RestoreDatabaseName `
            -OperationId $OperationId `
            -CreateAttemptId $CreateAttemptId
    }
    if ($Database -cne $expectedDatabase) {
        throw "C07 packaged money-facts database 未绑定 operation。"
    }
    if (
        -not [string]::IsNullOrEmpty($SnapshotId) -and
        $SnapshotId -cnotmatch (
            "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}$"
        )
    ) {
        throw "C07 packaged money-facts snapshot ID 无效。"
    }
    Assert-TicketboxC07Sha256 `
        $MaintenanceAuthoritySha256 `
        "C07 packaged money-facts maintenance authority"
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $Database `
        -Role "ticketbox_migrator"
    $capturedHelper = $helperBinding.Path
    $capturedHelperEvidence = $helperBinding.Evidence
    $capturedExpectedHelper = [System.IO.Path]::GetFullPath(
        $ExpectedMigrationHelperPath
    )
    $capturedUrl = $databaseUrl
    $capturedDatabase = $Database
    $capturedOperationId = $OperationId
    $capturedSnapshotId = $SnapshotId
    $capturedExpectedRevision = $ExpectedRevision
    $capturedMaintenanceDeadlineUtc = $MaintenanceDeadlineUtc
    $capturedMaintenanceAuthoritySha256 =
        $MaintenanceAuthoritySha256.ToLowerInvariant()
    $deadlineTimeoutMs =
        Get-TicketboxC07PackagedRemainingTimeoutMilliseconds `
            -DeadlineUtc $MaintenanceDeadlineUtc `
            -MaximumMilliseconds $script:TicketboxC07PackagedMigrationTimeoutMs
    $budgetTimeoutMs = if (
        $null -ne $script:TicketboxC07ActiveMaintenanceBudget
    ) {
        [Math]::Min(
            $deadlineTimeoutMs,
            (
                Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                    -MaximumMilliseconds (
                        $script:TicketboxC07PackagedMigrationTimeoutMs
                    ) `
                    -Label "C07 packaged recovery money facts"
            )
        )
    }
    else {
        $deadlineTimeoutMs
    }
    $capturedTimeoutMs = [int][Math]::Min(
        $budgetTimeoutMs,
        $MaintenanceRemainingCeilingMs
    )
    if ($capturedTimeoutMs -lt 1) {
        throw "C07 packaged money-facts current ceiling 已耗尽。"
    }
    $capturedRemainingCeilingMs = $capturedTimeoutMs
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $MigratorPassword `
        -Action ({
            param([string]$PlainPassword)
            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword
            try {
                $arguments = @(
                    "--c07-money-facts-digest",
                    "--database-url", $passfile.DatabaseUrl,
                    "--pgpassfile", $passfile.Path,
                    "--operation-id", $capturedOperationId,
                    "--database", $capturedDatabase,
                    "--maintenance-deadline-utc",
                    $capturedMaintenanceDeadlineUtc,
                    "--maintenance-remaining-ceiling-ms",
                    [string]$capturedRemainingCeilingMs,
                    "--maintenance-authority-sha256",
                    $capturedMaintenanceAuthoritySha256
                )
                if (-not [string]::IsNullOrEmpty($capturedSnapshotId)) {
                    $arguments += @("--snapshot-id", $capturedSnapshotId)
                }
                $process = Invoke-TicketboxC07BoundMigrationHelper `
                    -MigrationHelperPath $capturedHelper `
                    -MigrationHelperEvidence $capturedHelperEvidence `
                    -ExpectedMigrationHelperPath $capturedExpectedHelper `
                    -Arguments $arguments `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $capturedTimeoutMs `
                    -Label "C07 packaged money-facts read"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace(
                        [string]$process.StandardError
                    )
                ) {
                    throw (
                        "C07 packaged money-facts read 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                return ConvertFrom-TicketboxC07PackagedMoneyFactsResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -OperationId $capturedOperationId `
                    -Database $capturedDatabase `
                    -SnapshotId $capturedSnapshotId `
                    -ExpectedRevision $capturedExpectedRevision `
                    -MaintenanceAuthoritySha256 (
                        $capturedMaintenanceAuthoritySha256.ToUpperInvariant()
                    ) `
                    -MaintenanceRemainingCeilingMs $capturedRemainingCeilingMs
            }
            finally {
                if ($null -ne $passfile) {
                    Remove-TicketboxProtectedPgPassArtifact `
                        -Path $passfile.Path `
                        -FullControlAccounts $passfile.FullControlAccounts `
                        -OwnerAccount $passfile.OwnerAccount
                }
            }
        }.GetNewClosure())
}

function Invoke-TicketboxC07PackagedTargetSemanticAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [AllowEmptyString()][string]$SnapshotId = "",
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [AllowEmptyString()][string]$CreateAttemptId = ""
    )
    Assert-TicketboxC07PackagedMigrationDependencies
    $helperBinding = Assert-TicketboxC07PackagedMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    $expectedDatabase = if ([string]::IsNullOrEmpty($CreateAttemptId)) {
        "ticketbox"
    }
    else {
        Get-TicketboxC07RestoreDatabaseName `
            -OperationId $OperationId `
            -CreateAttemptId $CreateAttemptId
    }
    if ($Database -cne $expectedDatabase) {
        throw "C07 packaged target-semantic database 未绑定 operation。"
    }
    if (
        -not [string]::IsNullOrEmpty($SnapshotId) -and
        $SnapshotId -cnotmatch (
            "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}$"
        )
    ) {
        throw "C07 packaged target-semantic snapshot ID 无效。"
    }
    Assert-TicketboxC07Sha256 `
        $RevisionManifestSha256 `
        "C07 packaged target-semantic revision manifest"
    Assert-TicketboxC07Sha256 `
        $MaintenanceAuthoritySha256 `
        "C07 packaged target-semantic authority"
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $Database `
        -Role "ticketbox_migrator"
    $capturedHelper = $helperBinding.Path
    $capturedHelperEvidence = $helperBinding.Evidence
    $capturedExpectedHelper = [System.IO.Path]::GetFullPath(
        $ExpectedMigrationHelperPath
    )
    $capturedUrl = $databaseUrl
    $capturedDatabase = $Database
    $capturedOperationId = $OperationId
    $capturedSnapshotId = $SnapshotId
    $capturedSourceRevision = $SourceRevision
    $capturedTargetRevision = $TargetRevision
    $capturedRevisionManifestSha256 =
        $RevisionManifestSha256.ToLowerInvariant()
    $capturedMaintenanceDeadlineUtc = $MaintenanceDeadlineUtc
    $capturedMaintenanceAuthoritySha256 =
        $MaintenanceAuthoritySha256.ToLowerInvariant()
    $deadlineTimeoutMs =
        Get-TicketboxC07PackagedRemainingTimeoutMilliseconds `
            -DeadlineUtc $MaintenanceDeadlineUtc `
            -MaximumMilliseconds $script:TicketboxC07PackagedMigrationTimeoutMs
    $budgetTimeoutMs = if (
        $null -ne $script:TicketboxC07ActiveMaintenanceBudget
    ) {
        [Math]::Min(
            $deadlineTimeoutMs,
            (
                Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                    -MaximumMilliseconds (
                        $script:TicketboxC07PackagedMigrationTimeoutMs
                    ) `
                    -Label "C07 packaged target-semantic read"
            )
        )
    }
    else {
        $deadlineTimeoutMs
    }
    $capturedTimeoutMs = [int][Math]::Min(
        $budgetTimeoutMs,
        $MaintenanceRemainingCeilingMs
    )
    if ($capturedTimeoutMs -lt 1) {
        throw "C07 packaged target-semantic current ceiling 已耗尽。"
    }
    $capturedRemainingCeilingMs = $capturedTimeoutMs
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $MigratorPassword `
        -Action ({
            param([string]$PlainPassword)
            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword
            try {
                $arguments = @(
                    "--c07-target-semantic-digest",
                    "--database-url", $passfile.DatabaseUrl,
                    "--pgpassfile", $passfile.Path,
                    "--operation-id", $capturedOperationId,
                    "--database", $capturedDatabase,
                    "--source-revision", $capturedSourceRevision,
                    "--target-revision", $capturedTargetRevision,
                    "--expected-revision-manifest-sha256",
                    $capturedRevisionManifestSha256,
                    "--maintenance-deadline-utc",
                    $capturedMaintenanceDeadlineUtc,
                    "--maintenance-remaining-ceiling-ms",
                    [string]$capturedRemainingCeilingMs,
                    "--maintenance-authority-sha256",
                    $capturedMaintenanceAuthoritySha256
                )
                if (-not [string]::IsNullOrEmpty($capturedSnapshotId)) {
                    $arguments += @("--snapshot-id", $capturedSnapshotId)
                }
                $process = Invoke-TicketboxC07BoundMigrationHelper `
                    -MigrationHelperPath $capturedHelper `
                    -MigrationHelperEvidence $capturedHelperEvidence `
                    -ExpectedMigrationHelperPath $capturedExpectedHelper `
                    -Arguments $arguments `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $capturedTimeoutMs `
                    -Label "C07 packaged target-semantic read"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace(
                        [string]$process.StandardError
                    )
                ) {
                    throw (
                        "C07 packaged target-semantic read 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                return ConvertFrom-TicketboxC07PackagedTargetSemanticResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -OperationId $capturedOperationId `
                    -Database $capturedDatabase `
                    -SnapshotId $capturedSnapshotId `
                    -SourceRevision $capturedSourceRevision `
                    -TargetRevision $capturedTargetRevision `
                    -RevisionManifestSha256 (
                        $capturedRevisionManifestSha256.ToUpperInvariant()
                    ) `
                    -MaintenanceAuthoritySha256 (
                        $capturedMaintenanceAuthoritySha256.ToUpperInvariant()
                    ) `
                    -MaintenanceRemainingCeilingMs (
                        $capturedRemainingCeilingMs
                    )
            }
            finally {
                if ($null -ne $passfile) {
                    Remove-TicketboxProtectedPgPassArtifact `
                        -Path $passfile.Path `
                        -FullControlAccounts $passfile.FullControlAccounts `
                        -OwnerAccount $passfile.OwnerAccount
                }
            }
        }.GetNewClosure())
}

function Get-TicketboxC07PackagedInstalledUpgradePlan {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [AllowEmptyString()][string]$CreateAttemptId = ""
    )

    Assert-TicketboxC07PackagedMigrationDependencies
    $process = Invoke-TicketboxC07BoundMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath `
        -Arguments @(
            "--c07-installed-upgrade-plan",
            "--source-revision",
            $SourceRevision
        ) `
        -StandardInputText "" `
        -TimeoutMilliseconds $script:TicketboxC07PackagedMigrationTimeoutMs `
        -Label "C07 packaged installed-upgrade plan"
    if (
        [int]$process.ExitCode -ne 0 -or
        -not [string]::IsNullOrWhiteSpace([string]$process.StandardError)
    ) {
        throw (
            "C07 packaged installed-upgrade plan 被拒绝" +
            "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
        )
    }
    return ConvertFrom-TicketboxC07PackagedMaintenancePlan `
        -StandardOutput ([string]$process.StandardOutput) `
        -SourceRevision $SourceRevision
}

function Invoke-TicketboxC07PackagedMaintenanceAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)]
        [ValidateSet("isolated_replay")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedRevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [AllowEmptyString()][string]$CreateAttemptId = ""
    )

    Assert-TicketboxC07PackagedMigrationDependencies
    $helperBinding = Assert-TicketboxC07PackagedMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    if ([string]::IsNullOrEmpty($CreateAttemptId)) {
        throw "C07 isolated replay 缺少 protected create-attempt identity。"
    }
    $expectedDatabase = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $OperationId `
        -CreateAttemptId $CreateAttemptId
    if ($Database -cne $expectedDatabase) {
        throw "C07 packaged maintenance database 未绑定 mode/operation。"
    }
    Assert-TicketboxC07Sha256 `
        $ExpectedRevisionManifestSha256 `
        "C07 packaged maintenance revision manifest"
    Assert-TicketboxC07Sha256 `
        $MaintenanceAuthoritySha256 `
        "C07 packaged maintenance authority"
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $Database `
        -Role "ticketbox_migrator"
    $capturedHelper = $helperBinding.Path
    $capturedHelperEvidence = $helperBinding.Evidence
    $capturedExpectedHelper = [System.IO.Path]::GetFullPath(
        $ExpectedMigrationHelperPath
    )
    $capturedUrl = $databaseUrl
    $capturedMode = $Mode
    $capturedOperationId = $OperationId
    $capturedSourceRevision = $SourceRevision
    $capturedTargetRevision = $TargetRevision
    $capturedRevisionManifestSha256 =
        $ExpectedRevisionManifestSha256.ToLowerInvariant()
    $capturedMaintenanceDeadlineUtc = $MaintenanceDeadlineUtc
    $capturedMaintenanceAuthoritySha256 =
        $MaintenanceAuthoritySha256.ToLowerInvariant()
    $deadlineTimeoutMs =
        Get-TicketboxC07PackagedRemainingTimeoutMilliseconds `
            -DeadlineUtc $MaintenanceDeadlineUtc `
            -MaximumMilliseconds $script:TicketboxC07PackagedMigrationTimeoutMs
    $budgetTimeoutMs = if (
        $null -ne $script:TicketboxC07ActiveMaintenanceBudget
    ) {
        [Math]::Min(
            $deadlineTimeoutMs,
            (
                Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                    -MaximumMilliseconds (
                        $script:TicketboxC07PackagedMigrationTimeoutMs
                    ) `
                    -Label "C07 packaged maintenance upgrade"
            )
        )
    }
    else {
        $deadlineTimeoutMs
    }
    $capturedTimeoutMs = [int][Math]::Min(
        $budgetTimeoutMs,
        $MaintenanceRemainingCeilingMs
    )
    if ($capturedTimeoutMs -lt 1) {
        throw "C07 packaged maintenance current ceiling 已耗尽。"
    }
    $capturedRemainingCeilingMs = $capturedTimeoutMs
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $MigratorPassword `
        -Action ({
            param([string]$PlainPassword)

            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword
            try {
                $arguments = @(
                    "--c07-maintenance-upgrade",
                    "--mode", $capturedMode,
                    "--database-url", $passfile.DatabaseUrl,
                    "--pgpassfile", $passfile.Path,
                    "--operation-id", $capturedOperationId,
                    "--source-revision", $capturedSourceRevision,
                    "--target-revision", $capturedTargetRevision,
                    "--expected-revision-manifest-sha256",
                    $capturedRevisionManifestSha256,
                    "--maintenance-deadline-utc",
                    $capturedMaintenanceDeadlineUtc,
                    "--maintenance-remaining-ceiling-ms",
                    [string]$capturedRemainingCeilingMs,
                    "--maintenance-authority-sha256",
                    $capturedMaintenanceAuthoritySha256
                )
                $process = Invoke-TicketboxC07BoundMigrationHelper `
                    -MigrationHelperPath $capturedHelper `
                    -MigrationHelperEvidence $capturedHelperEvidence `
                    -ExpectedMigrationHelperPath $capturedExpectedHelper `
                    -Arguments $arguments `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $capturedTimeoutMs `
                    -Label "C07 packaged maintenance upgrade"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace(
                        [string]$process.StandardError
                    )
                ) {
                    throw (
                        "C07 packaged maintenance upgrade 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                return ConvertFrom-TicketboxC07PackagedMaintenanceResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -Mode $capturedMode `
                    -OperationId $capturedOperationId `
                    -SourceRevision $capturedSourceRevision `
                    -TargetRevision $capturedTargetRevision `
                    -RevisionManifestSha256 (
                        $capturedRevisionManifestSha256.ToUpperInvariant()
                    ) `
                    -MaintenanceAuthoritySha256 (
                        $capturedMaintenanceAuthoritySha256.ToUpperInvariant()
                    ) `
                    -MaintenanceRemainingCeilingMs $capturedRemainingCeilingMs
            }
            finally {
                if ($null -ne $passfile) {
                    Remove-TicketboxProtectedPgPassArtifact `
                        -Path $passfile.Path `
                        -FullControlAccounts $passfile.FullControlAccounts `
                        -OwnerAccount $passfile.OwnerAccount
                }
            }
        }.GetNewClosure())
}

function Invoke-TicketboxC07PackagedIsolatedReplayAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$RestoreDatabase,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [Parameter(Mandatory = $true)][string]$MaintenanceDeadlineUtc,
        [ValidateRange(1, 1200000)]
        [Parameter(Mandatory = $true)][int]$MaintenanceRemainingCeilingMs,
        [Parameter(Mandatory = $true)][string]$MaintenanceAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [Parameter(Mandatory = $true)][string]$CreateAttemptId
    )
    return Invoke-TicketboxC07PackagedMaintenanceAction `
        -HostAuthority $HostAuthority `
        -MigratorPassword $MigratorPassword `
        -Mode "isolated_replay" `
        -Database $RestoreDatabase `
        -OperationId $OperationId `
        -SourceRevision $SourceRevision `
        -TargetRevision $TargetRevision `
        -ExpectedRevisionManifestSha256 $RevisionManifestSha256 `
        -MaintenanceDeadlineUtc $MaintenanceDeadlineUtc `
        -MaintenanceRemainingCeilingMs $MaintenanceRemainingCeilingMs `
        -MaintenanceAuthoritySha256 $MaintenanceAuthoritySha256 `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath `
        -CreateAttemptId $CreateAttemptId
}

function Invoke-TicketboxC07PackagedFreshSourceBootstrapAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath
    )

    Assert-TicketboxC07PackagedMigrationDependencies
    $helperBinding = Assert-TicketboxC07PackagedMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database "ticketbox" `
        -Role "ticketbox_migrator"
    $capturedHelper = $helperBinding.Path
    $capturedHelperEvidence = $helperBinding.Evidence
    $capturedExpectedHelper = [System.IO.Path]::GetFullPath(
        $ExpectedMigrationHelperPath
    )
    $capturedUrl = $databaseUrl
    $capturedSourceRevision = $SourceRevision
    $capturedTargetRevision = $TargetRevision
    $capturedTimeoutMs = $script:TicketboxC07PackagedMigrationTimeoutMs
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $MigratorPassword `
        -Action ({
            param([string]$PlainPassword)

            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword
            try {
                $process = Invoke-TicketboxC07BoundMigrationHelper `
                    -MigrationHelperPath $capturedHelper `
                    -MigrationHelperEvidence $capturedHelperEvidence `
                    -ExpectedMigrationHelperPath $capturedExpectedHelper `
                    -Arguments @(
                        "--c07-fresh-source-bootstrap",
                        "--database-url",
                        $passfile.DatabaseUrl,
                        "--pgpassfile",
                        $passfile.Path,
                        "--source-revision",
                        $capturedSourceRevision,
                        "--target-revision",
                        $capturedTargetRevision
                    ) `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $capturedTimeoutMs `
                    -Label "C07 packaged fresh-source bootstrap"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace(
                        [string]$process.StandardError
                    )
                ) {
                    throw (
                        "C07 packaged fresh-source bootstrap 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                return ConvertFrom-TicketboxC07PackagedFreshSourceResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -SourceRevision $capturedSourceRevision `
                    -TargetRevision $capturedTargetRevision
            }
            finally {
                if ($null -ne $passfile) {
                    Remove-TicketboxProtectedPgPassArtifact `
                        -Path $passfile.Path `
                        -FullControlAccounts $passfile.FullControlAccounts `
                        -OwnerAccount $passfile.OwnerAccount
                }
            }
        }.GetNewClosure())
}

function Invoke-TicketboxC07PackagedMigrationAction {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$SourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][object]$MigrationContext,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity
    )

    Assert-TicketboxC07PackagedMigrationDependencies
    $helperBinding = Assert-TicketboxC07PackagedMigrationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    Assert-TicketboxC07ExactProperties `
        -Value $MigrationContext `
        -ExpectedNames @(
            "schema",
            "operation_id",
            "release_fingerprint",
            "migration_helper_relative_path",
            "migration_helper_size",
            "migration_helper_sha256",
            "database_binding_sha256",
            "upload_root_binding_sha256",
            "recovery_epoch_id",
            "coordinator_binding_sha256",
            "coordinator_binding_sequence",
            "heartbeat_sequence",
            "operation_kind",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "successor_mode",
            "successor_intent_sha256",
            "predecessor_operation_id",
            "predecessor_terminal_authority_chain_sha256",
            "source_recovery_operation_id",
            "source_recovery_release_fingerprint",
            "source_recovery_revision_manifest_sha256",
            "source_recovery_freeze_proof_sha256",
            "maintenance_deadline_utc",
            "maintenance_remaining_ceiling_ms",
            "maintenance_authority_sha256",
            "writer_freeze_proof_path",
            "writer_freeze_proof_sha256",
            "recovery_manifest_path",
            "recovery_manifest_sha256",
            "isolated_restore_evidence_path",
            "isolated_restore_evidence_sha256",
            "lifecycle_root_authority_chain_sha256"
        ) `
        -ArtifactName "packaged migration context"
    if (
        [string]$MigrationContext.schema -cne
            $script:TicketboxC07PackagedMigrationContextSchema
    ) {
        throw "C07 packaged migration context schema 无效。"
    }
    Assert-TicketboxC07Sha256 `
        ([string]$MigrationContext.revision_manifest_sha256) `
        "C07 packaged migration context revision manifest"
    Assert-TicketboxC07Sha256 `
        ([string]$MigrationContext.maintenance_authority_sha256) `
        "C07 packaged migration context maintenance authority"
    Assert-TicketboxC07Sha256 `
        ([string]$MigrationContext.migration_helper_sha256) `
        "C07 packaged migration context helper SHA-256"
    if (
        [string]$MigrationContext.upload_root_binding_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        [string]$MigrationContext.upload_root_binding_sha256 -ceq ("0" * 64)
    ) {
        throw (
            "C07 packaged migration context upload-root binding " +
            "不是 non-zero canonical lowercase SHA-256。"
        )
    }
    $releaseHelperEvidence =
        ConvertTo-TicketboxC07PackagedMigrationHelperEvidence (
            [pscustomobject][ordered]@{
                RelativePath =
                    [string]$ReleaseIdentity.MigrationHelperRelativePath
                Size = [int64]$ReleaseIdentity.MigrationHelperSize
                Sha256 = [string]$ReleaseIdentity.MigrationHelperSha256
            }
        )
    if (
        [string]$MigrationContext.release_fingerprint -cne
            [string]$ReleaseIdentity.Fingerprint -or
        [string]$MigrationContext.migration_helper_relative_path -cne
            $releaseHelperEvidence.RelativePath -or
        [int64]$MigrationContext.migration_helper_size -ne
            $releaseHelperEvidence.Size -or
        [string]$MigrationContext.migration_helper_sha256 -cne
            $releaseHelperEvidence.Sha256 -or
        $helperBinding.Evidence.RelativePath -cne
            $releaseHelperEvidence.RelativePath -or
        [int64]$helperBinding.Evidence.Size -ne
            $releaseHelperEvidence.Size -or
        $helperBinding.Evidence.Sha256 -cne
            $releaseHelperEvidence.Sha256 -or
        -not (
            Test-TicketboxPathEquals `
                $ExpectedMigrationHelperPath `
                ([string]$ReleaseIdentity.MigrationHelperPath)
        )
    ) {
        throw "C07 packaged migration context/helper 与 release identity 不一致。"
    }
    $contextRemainingCeilingMs =
        [int]$MigrationContext.maintenance_remaining_ceiling_ms
    if (
        $contextRemainingCeilingMs -lt 1 -or
        $contextRemainingCeilingMs -gt 1200000
    ) {
        throw "C07 packaged migration context current ceiling 无效。"
    }

    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database "ticketbox" `
        -Role "ticketbox_migrator"
    $contextJson = ConvertTo-TicketboxC07CompactJson $MigrationContext
    $capturedHelper = $helperBinding.Path
    $capturedHelperEvidence = $helperBinding.Evidence
    $capturedExpectedHelper = [System.IO.Path]::GetFullPath(
        [string]$ReleaseIdentity.MigrationHelperPath
    )
    $capturedUrl = $databaseUrl
    $capturedContextJson = $contextJson
    $capturedOperationId = [string]$MigrationContext.operation_id
    $capturedSourceRevision = $SourceRevision
    $capturedTargetRevision = $TargetRevision
    $deadlineTimeoutMs =
        Get-TicketboxC07PackagedRemainingTimeoutMilliseconds `
            -DeadlineUtc ([string]$MigrationContext.maintenance_deadline_utc) `
            -MaximumMilliseconds $script:TicketboxC07PackagedMigrationTimeoutMs
    $budgetTimeoutMs = if (
        $null -ne $script:TicketboxC07ActiveMaintenanceBudget
    ) {
        [Math]::Min(
            $deadlineTimeoutMs,
            (
                Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                    -MaximumMilliseconds (
                        $script:TicketboxC07PackagedMigrationTimeoutMs
                    ) `
                    -Label "C07 packaged production migration"
            )
        )
    }
    else {
        $deadlineTimeoutMs
    }
    $capturedTimeoutMs = [int][Math]::Min(
        $budgetTimeoutMs,
        $contextRemainingCeilingMs
    )
    if ($capturedTimeoutMs -lt 1) {
        throw "C07 packaged production migration current ceiling 已耗尽。"
    }
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $MigratorPassword `
        -Action ({
            param([string]$PlainPassword)

            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword
            try {
                $process = Invoke-TicketboxC07BoundMigrationHelper `
                    -MigrationHelperPath $capturedHelper `
                    -MigrationHelperEvidence $capturedHelperEvidence `
                    -ExpectedMigrationHelperPath $capturedExpectedHelper `
                    -Arguments @(
                        "--c07-production-migrate",
                        "--database-url",
                        $passfile.DatabaseUrl,
                        "--pgpassfile",
                        $passfile.Path,
                        "--operation-id",
                        $capturedOperationId,
                        "--source-revision",
                        $capturedSourceRevision,
                        "--target-revision",
                        $capturedTargetRevision
                    ) `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText $capturedContextJson `
                    -TimeoutMilliseconds $capturedTimeoutMs `
                    -Label "C07 packaged production migration"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace(
                        [string]$process.StandardError
                    )
                ) {
                    throw (
                        "C07 packaged production migration 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                return ConvertFrom-TicketboxC07PackagedMigrationResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -OperationId $capturedOperationId `
                    -SourceRevision $capturedSourceRevision `
                    -TargetRevision $capturedTargetRevision
            }
            finally {
                if ($null -ne $passfile) {
                    Remove-TicketboxProtectedPgPassArtifact `
                        -Path $passfile.Path `
                        -FullControlAccounts $passfile.FullControlAccounts `
                        -OwnerAccount $passfile.OwnerAccount
                }
            }
        }.GetNewClosure())
}
