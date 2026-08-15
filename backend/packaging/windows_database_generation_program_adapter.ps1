#Requires -Version 5.1

<#
.SYNOPSIS
  Validate the frozen database program and invoke its one managed-schema action.
.DESCRIPTION
  The Generation Owner retains lifecycle/database authority. This adapter only
  validates the immutable program/helper evidence and runs one exact target in
  a protected caller-owned migration transaction.
#>

$script:TicketboxDatabaseGenerationProgramValidationSchema =
    "ticketbox-database-generation-program-validation-v1"
$script:TicketboxManagedSchemaResultSchema =
    "ticketbox-managed-schema-upgrade-result-v2"
$script:TicketboxDatabaseGenerationProgramTimeoutMs = 1500000


function Assert-TicketboxDatabaseGenerationProgramAdapterDependencies {
    foreach ($commandName in @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "Assert-TicketboxC07MigrationHelperLeaseUnchanged",
        "Assert-TicketboxDatabaseGenerationExactProperties",
        "Assert-TicketboxDatabaseGenerationUpperSha256",
        "Close-TicketboxC07MigrationHelperLease",
        "ConvertTo-TicketboxDatabaseGenerationCanonicalJson",
        "Get-TicketboxDatabaseGenerationTextSha256",
        "Get-TicketboxPortableFileSha256",
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
            throw "database generation program adapter 缺少依赖：$commandName"
        }
    }
}

function Get-TicketboxDatabaseGenerationJsonLine {
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

function ConvertFrom-TicketboxDatabaseGenerationProgramValidation {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$ExpectedProgramSha256
    )

    $jsonLine = Get-TicketboxDatabaseGenerationJsonLine `
        -StandardOutput $StandardOutput `
        -Label "database generation program validation"
    try {
        $result = $jsonLine | ConvertFrom-Json
    }
    catch {
        throw "database generation program validation stdout 不是有效 JSON。"
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $result `
        -ExpectedNames @(
            "schema",
            "source_revision",
            "target_revision",
            "revision_count",
            "generation_program_sha256",
            "c07_source_revision",
            "c07_target_revision",
            "c07_revision_manifest",
            "c07_revision_manifest_sha256"
        ) `
        -Label "database generation program validation"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$result.generation_program_sha256) `
        "database generation program"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$result.c07_revision_manifest_sha256) `
        "database generation C07 manifest"
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $result.c07_revision_manifest `
        -ExpectedNames @(
            "schema",
            "operation_kind",
            "source_revision",
            "target_revision",
            "revisions"
        ) `
        -Label "database generation C07 manifest"
    $revisions = @($result.c07_revision_manifest.revisions)
    if ($revisions.Count -ne 1) {
        throw "C07 packaged revision manifest 必须只有 exact C07 revision。"
    }
    foreach ($revision in $revisions) {
        Assert-TicketboxDatabaseGenerationExactProperties `
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
            -Label "packaged revision manifest item"
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            ([string]$revision.module_sha256) `
            "C07 packaged revision module"
    }
    $manifestCanonical = ConvertTo-TicketboxDatabaseGenerationCanonicalJson `
        $result.c07_revision_manifest
    $manifestSha256 = (
        Get-TicketboxDatabaseGenerationTextSha256 $manifestCanonical
    ).ToLowerInvariant()
    if (
        $jsonLine -cne (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $result) -or
        [string]$result.schema -cne
            $script:TicketboxDatabaseGenerationProgramValidationSchema -or
        [string]$result.source_revision -cne "base" -or
        [string]::IsNullOrWhiteSpace([string]$result.target_revision) -or
        [int64]$result.revision_count -lt 1 -or
        [string]$result.generation_program_sha256 -cne
            $ExpectedProgramSha256.ToLowerInvariant() -or
        [string]$result.c07_source_revision -cne "20260722_0001" -or
        [string]$result.c07_target_revision -cne "20260729_0001" -or
        [string]$result.c07_revision_manifest.schema -cne
            "ticketbox-c07-revision-manifest-v1" -or
        [string]$result.c07_revision_manifest.operation_kind -cne
            "c07_money_minor_bigint_v1" -or
        [string]$result.c07_revision_manifest.source_revision -cne
            [string]$result.c07_source_revision -or
        [string]$result.c07_revision_manifest.target_revision -cne
            [string]$result.c07_target_revision -or
        [string]$result.c07_revision_manifest_sha256 -cne $manifestSha256
    ) {
        throw "database generation program 未绑定 exact release chain。"
    }
    return $result
}

function ConvertTo-TicketboxDatabaseGenerationProgramEvidence {
    param([Parameter(Mandatory = $true)][object]$Value)

    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Value `
        -ExpectedNames @("RelativePath", "Size", "Sha256") `
        -Label "database generation program evidence"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$Value.Sha256).ToLowerInvariant() `
        "database generation program"
    if (
        [string]$Value.RelativePath -cne "DATABASE_GENERATION_PROGRAM.json" -or
        [int64]$Value.Size -lt 1
    ) {
        throw "database generation program evidence 无效。"
    }
    return [pscustomobject][ordered]@{
        RelativePath = [string]$Value.RelativePath
        Size = [int64]$Value.Size
        Sha256 = ([string]$Value.Sha256).ToLowerInvariant()
    }
}

function Assert-TicketboxDatabaseGenerationProgram {
    param(
        [Parameter(Mandatory = $true)][string]$ProgramPath,
        [Parameter(Mandatory = $true)][object]$ProgramEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath
    )

    $evidence = ConvertTo-TicketboxDatabaseGenerationProgramEvidence `
        $ProgramEvidence
    $expectedPath = Join-Path `
        ([System.IO.Path]::GetDirectoryName(
            [System.IO.Path]::GetFullPath($ExpectedMigrationHelperPath)
        )) `
        $evidence.RelativePath
    if (
        -not (Test-TicketboxPathEquals $ProgramPath $expectedPath) -or
        (Get-TicketboxPathEntryKindNoFollow $ProgramPath) -cne "File"
    ) {
        throw "database generation program 不在 frozen payload root。"
    }
    Assert-NoTicketboxAncestorReparsePoints $ProgramPath
    $item = Get-Item -LiteralPath $ProgramPath -Force
    $sha256 = (Get-TicketboxPortableFileSha256 $ProgramPath).ToLowerInvariant()
    if (
        [int64]$item.Length -ne $evidence.Size -or
        $sha256 -cne $evidence.Sha256
    ) {
        throw "database generation program bytes 与 release evidence 不一致。"
    }
    return [pscustomobject][ordered]@{
        Path = [System.IO.Path]::GetFullPath($ProgramPath)
        Evidence = $evidence
    }
}

function Get-TicketboxDatabaseGenerationProgramFromHelper {
    param(
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [Parameter(Mandatory = $true)][string]$ProgramPath,
        [Parameter(Mandatory = $true)][object]$ProgramEvidence
    )

    Assert-TicketboxDatabaseGenerationProgramAdapterDependencies
    $program = Assert-TicketboxDatabaseGenerationProgram `
        -ProgramPath $ProgramPath `
        -ProgramEvidence $ProgramEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    $process = Invoke-TicketboxDatabaseGenerationBoundHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath `
        -Arguments @(
            "--validate-generation-program",
            "--generation-program-path",
            $program.Evidence.RelativePath,
            "--expected-generation-program-sha256",
            $program.Evidence.Sha256
        ) `
        -StandardInputText "" `
        -TimeoutMilliseconds $script:TicketboxDatabaseGenerationProgramTimeoutMs `
        -Label "database generation program validation"
    if (
        [int]$process.ExitCode -ne 0 -or
        -not [string]::IsNullOrWhiteSpace([string]$process.StandardError)
    ) {
        throw (
            "database generation program validation 被拒绝" +
            "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
        )
    }
    $result = ConvertFrom-TicketboxDatabaseGenerationProgramValidation `
        -StandardOutput ([string]$process.StandardOutput) `
        -ExpectedProgramSha256 $program.Evidence.Sha256
    Assert-TicketboxDatabaseGenerationProgram `
        -ProgramPath $program.Path `
        -ProgramEvidence $program.Evidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath | Out-Null
    return $result
}

function ConvertTo-TicketboxDatabaseGenerationHelperEvidence {
    param([Parameter(Mandatory = $true)][object]$MigrationHelperEvidence)

    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $MigrationHelperEvidence `
        -ExpectedNames @("RelativePath", "Size", "Sha256") `
        -Label "packaged migration helper evidence"
    if (
        [string]$MigrationHelperEvidence.RelativePath -cne
            "ticketbox-c07-migrator.exe" -or
        [int64]$MigrationHelperEvidence.Size -lt 1
    ) {
        throw "C07 packaged migration helper release path/size evidence 无效。"
    }
    Assert-TicketboxDatabaseGenerationUpperSha256 `
        ([string]$MigrationHelperEvidence.Sha256) `
        "packaged migration helper release SHA-256"
    return [pscustomobject][ordered]@{
        RelativePath = [string]$MigrationHelperEvidence.RelativePath
        Size = [int64]$MigrationHelperEvidence.Size
        Sha256 = [string]$MigrationHelperEvidence.Sha256
    }
}

function Get-TicketboxDatabaseGenerationMigrationHelperEvidence {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)

    return ConvertTo-TicketboxDatabaseGenerationHelperEvidence `
        ([pscustomobject][ordered]@{
            RelativePath = [string]$ReleaseIdentity.MigrationHelperRelativePath
            Size = [int64]$ReleaseIdentity.MigrationHelperSize
            Sha256 = [string]$ReleaseIdentity.MigrationHelperSha256
        })
}

function Get-TicketboxDatabaseGenerationProgramEvidence {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)

    return ConvertTo-TicketboxDatabaseGenerationProgramEvidence `
        ([pscustomobject][ordered]@{
            RelativePath = [string]$ReleaseIdentity.DatabaseGenerationProgramRelativePath
            Size = [int64]$ReleaseIdentity.DatabaseGenerationProgramSize
            Sha256 = [string]$ReleaseIdentity.DatabaseGenerationProgramSha256
        })
}

function Get-TicketboxInstalledDatabaseGenerationProgram {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)

    return Get-TicketboxDatabaseGenerationProgramFromHelper `
        -MigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath) `
        -MigrationHelperEvidence (
            Get-TicketboxDatabaseGenerationMigrationHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMigrationHelperPath ([string]$ReleaseIdentity.MigrationHelperPath) `
        -ProgramPath ([string]$ReleaseIdentity.DatabaseGenerationProgramPath) `
        -ProgramEvidence (Get-TicketboxDatabaseGenerationProgramEvidence $ReleaseIdentity)
}

function Assert-TicketboxDatabaseGenerationHelper {
    param(
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$ExpectedMigrationHelperPath
    )

    $helper = [System.IO.Path]::GetFullPath($MigrationHelperPath)
    $evidence = ConvertTo-TicketboxDatabaseGenerationHelperEvidence `
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

