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
    "ticketbox-database-generation-program-validation-v2"
$script:TicketboxManagedSchemaResultSchema =
    "ticketbox-managed-schema-upgrade-result-v2"
$script:TicketboxDatabaseGenerationProgramTimeoutMs = 1500000


function Assert-TicketboxDatabaseGenerationProgramAdapterDependencies {
    foreach ($commandName in @(
        "Assert-NoTicketboxAncestorReparsePoints",
        "Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged",
        "Assert-TicketboxDatabaseGenerationExactProperties",
        "Assert-TicketboxDatabaseGenerationUpperSha256",
        "Close-TicketboxDatabaseMaintenanceHelperLease",
        "ConvertTo-TicketboxDatabaseGenerationCanonicalJson",
        "Get-TicketboxPortableFileSha256",
        "Get-TicketboxPathEntryKindNoFollow",
        "Invoke-TicketboxBoundedNativeProcess",
        "Open-TicketboxVerifiedDatabaseMaintenanceHelperLease",
        "Test-TicketboxPathEquals",
        "Throw-TicketboxOperationFailure"
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
            "generation_program_sha256"
        ) `
        -Label "database generation program validation"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$result.generation_program_sha256) `
        "database generation program"
    if (
        $jsonLine -cne (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $result) -or
        [string]$result.schema -cne
            $script:TicketboxDatabaseGenerationProgramValidationSchema -or
        [string]$result.source_revision -cne "base" -or
        [string]::IsNullOrWhiteSpace([string]$result.target_revision) -or
        [int64]$result.revision_count -lt 1 -or
        [string]$result.generation_program_sha256 -cne
            $ExpectedProgramSha256.ToLowerInvariant()
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
        [Parameter(Mandatory = $true)][string]$ExpectedMaintenanceHelperPath
    )

    $evidence = ConvertTo-TicketboxDatabaseGenerationProgramEvidence `
        $ProgramEvidence
    $expectedPath = Join-Path `
        ([System.IO.Path]::GetDirectoryName(
            [System.IO.Path]::GetFullPath($ExpectedMaintenanceHelperPath)
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
        [Parameter(Mandatory = $true)][string]$MaintenanceHelperPath,
        [Parameter(Mandatory = $true)][object]$MaintenanceHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMaintenanceHelperPath,
        [Parameter(Mandatory = $true)][string]$ProgramPath,
        [Parameter(Mandatory = $true)][object]$ProgramEvidence
    )

    Assert-TicketboxDatabaseGenerationProgramAdapterDependencies
    $program = Assert-TicketboxDatabaseGenerationProgram `
        -ProgramPath $ProgramPath `
        -ProgramEvidence $ProgramEvidence `
        -ExpectedMaintenanceHelperPath $ExpectedMaintenanceHelperPath
    $process = Invoke-TicketboxDatabaseGenerationBoundHelper `
        -MaintenanceHelperPath $MaintenanceHelperPath `
        -MaintenanceHelperEvidence $MaintenanceHelperEvidence `
        -ExpectedMaintenanceHelperPath $ExpectedMaintenanceHelperPath `
        -ValidateProgram `
        -ProgramRelativePath $program.Evidence.RelativePath `
        -ExpectedProgramSha256 $program.Evidence.Sha256
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
        -ExpectedMaintenanceHelperPath $ExpectedMaintenanceHelperPath | Out-Null
    return $result
}

function ConvertTo-TicketboxDatabaseGenerationHelperEvidence {
    param([Parameter(Mandatory = $true)][object]$MaintenanceHelperEvidence)

    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $MaintenanceHelperEvidence `
        -ExpectedNames @("RelativePath", "Size", "Sha256") `
        -Label "packaged migration helper evidence"
    if (
        [string]$MaintenanceHelperEvidence.RelativePath -cne
            "ticketbox-database-maintenance.exe" -or
        [int64]$MaintenanceHelperEvidence.Size -lt 1
    ) {
        throw "database maintenance helper release path/size evidence 无效。"
    }
    Assert-TicketboxDatabaseGenerationUpperSha256 `
        ([string]$MaintenanceHelperEvidence.Sha256) `
        "packaged migration helper release SHA-256"
    return [pscustomobject][ordered]@{
        RelativePath = [string]$MaintenanceHelperEvidence.RelativePath
        Size = [int64]$MaintenanceHelperEvidence.Size
        Sha256 = [string]$MaintenanceHelperEvidence.Sha256
    }
}

function Get-TicketboxDatabaseMaintenanceHelperEvidence {
    param([Parameter(Mandatory = $true)][object]$ReleaseIdentity)

    return ConvertTo-TicketboxDatabaseGenerationHelperEvidence `
        ([pscustomobject][ordered]@{
            RelativePath = [string]$ReleaseIdentity.MaintenanceHelperRelativePath
            Size = [int64]$ReleaseIdentity.MaintenanceHelperSize
            Sha256 = [string]$ReleaseIdentity.MaintenanceHelperSha256
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
        -MaintenanceHelperPath ([string]$ReleaseIdentity.MaintenanceHelperPath) `
        -MaintenanceHelperEvidence (
            Get-TicketboxDatabaseMaintenanceHelperEvidence $ReleaseIdentity
        ) `
        -ExpectedMaintenanceHelperPath ([string]$ReleaseIdentity.MaintenanceHelperPath) `
        -ProgramPath ([string]$ReleaseIdentity.DatabaseGenerationProgramPath) `
        -ProgramEvidence (Get-TicketboxDatabaseGenerationProgramEvidence $ReleaseIdentity)
}

function Assert-TicketboxDatabaseGenerationHelper {
    param(
        [Parameter(Mandatory = $true)][string]$MaintenanceHelperPath,
        [Parameter(Mandatory = $true)][object]$MaintenanceHelperEvidence,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$ExpectedMaintenanceHelperPath
    )

    $helper = [System.IO.Path]::GetFullPath($MaintenanceHelperPath)
    $evidence = ConvertTo-TicketboxDatabaseGenerationHelperEvidence `
        $MaintenanceHelperEvidence
    if (
        -not (
            Test-TicketboxPathEquals `
                $helper `
                ([System.IO.Path]::GetFullPath($ExpectedMaintenanceHelperPath))
        )
    ) {
        throw "database maintenance helper path 与 release identity 不一致。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $helper) -cne "File") {
        throw "database maintenance helper 不是 regular frozen payload file。"
    }
    Assert-NoTicketboxAncestorReparsePoints $helper
    return [pscustomobject][ordered]@{
        Path = $helper
        Evidence = $evidence
    }
}

