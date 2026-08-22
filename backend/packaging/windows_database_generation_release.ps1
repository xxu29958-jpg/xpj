#Requires -Version 5.1

function Read-TicketboxDatabaseGenerationProgramContract {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        $ExpectedSha256 `
        "database generation program"
    $canonicalPath = ConvertTo-TicketboxWin32CanonicalPath $Path
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $bytes = [TicketboxExactTreeDeleteNativeMethods]::ReadExactFileBytes(
        $canonicalPath,
        16777216
    )
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actualSha256 = (
            [BitConverter]::ToString($sha.ComputeHash($bytes))
        ).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    if ($actualSha256 -cne $ExpectedSha256) {
        throw "database generation program 与安装器 build evidence 不一致。"
    }
    try {
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $program = $utf8.GetString($bytes) | ConvertFrom-Json
    }
    catch {
        throw "database generation program 不是 canonical JSON。"
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $program `
        @("revisions", "schema", "source_revision", "target_revision") `
        "database generation program"
    if (
        [string]$program.schema -cne
            "ticketbox-database-generation-program-v2" -or
        [string]$program.source_revision -cne "base" -or
        [string]$program.target_revision -cnotmatch
            '^[0-9]{8}_[0-9a-z_]+$' -or
        @($program.revisions).Count -lt 1
    ) {
        throw "database generation program root contract 无效。"
    }
    return [pscustomobject][ordered]@{
        RelativePath = $script:TicketboxDatabaseGenerationProgramRelativePath
        Size = [int64]$bytes.Length
        Sha256 = $actualSha256
        TargetRevision = [string]$program.target_revision
    }
}

function New-TicketboxDatabaseGenerationReleaseContract {
    param(
        [Parameter(Mandatory = $true)][object]$InstallationIdentity,
        [Parameter(Mandatory = $true)][object]$ReleaseCandidate
    )
    if (
        [string]$InstallationIdentity.State -cne "PENDING" -or
        -not (Test-TicketboxInstallationIdentityReleaseMatches `
            $InstallationIdentity $ReleaseCandidate)
    ) {
        throw "database generation release contract 与 PENDING installation identity 不一致。"
    }
    return [pscustomobject][ordered]@{
        InstallationOperationId = [string]$InstallationIdentity.OperationId
        InstallationId = [string]$InstallationIdentity.InstallationId
        BackendVersionFloor = [string]$InstallationIdentity.BackendVersionFloor
        MaintenanceHelperPath = [string]$ReleaseCandidate.MaintenanceHelperPath
        MaintenanceHelperRelativePath =
            [string]$ReleaseCandidate.MaintenanceHelperRelativePath
        MaintenanceHelperSize = [int64]$ReleaseCandidate.MaintenanceHelperSize
        MaintenanceHelperSha256 = [string]$ReleaseCandidate.MaintenanceHelperSha256
        DatabaseGenerationProgramPath =
            [string]$ReleaseCandidate.DatabaseGenerationProgramPath
        DatabaseGenerationProgramRelativePath =
            [string]$ReleaseCandidate.DatabaseGenerationProgramRelativePath
        DatabaseGenerationProgramSize =
            [int64]$ReleaseCandidate.DatabaseGenerationProgramSize
        DatabaseGenerationProgramSha256 =
            [string]$ReleaseCandidate.DatabaseGenerationProgramSha256
    }
}

function Assert-TicketboxDatabaseGenerationReleaseBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$ReleaseIdentity
    )
    $program = Get-TicketboxInstalledDatabaseGenerationProgram `
        -ReleaseIdentity $ReleaseIdentity
    $fresh = [string]::IsNullOrEmpty(
        [string]$Intent.Payload.expected_predecessor_sha256
    )
    if (
        (
            $fresh -and
            [string]$Intent.Payload.operation_id -cne
                ([guid][string]$ReleaseIdentity.InstallationOperationId).ToString("D")
        ) -or
        [string]$Intent.Payload.installation_id -cne
            ([guid][string]$ReleaseIdentity.InstallationId).ToString("D") -or
        [string]$Intent.Payload.target_backend_version -cne
            [string]$ReleaseIdentity.BackendVersionFloor -or
        [string]$Intent.Payload.database_maintenance_helper_relative_path -cne
            [string]$ReleaseIdentity.MaintenanceHelperRelativePath -or
        [int64]$Intent.Payload.database_maintenance_helper_size -ne
            [int64]$ReleaseIdentity.MaintenanceHelperSize -or
        [string]$Intent.Payload.database_maintenance_helper_sha256 -cne
            ([string]$ReleaseIdentity.MaintenanceHelperSha256).ToLowerInvariant() -or
        [string]$Intent.Payload.generation_program_relative_path -cne
            [string]$ReleaseIdentity.DatabaseGenerationProgramRelativePath -or
        [int64]$Intent.Payload.generation_program_size -ne
            [int64]$ReleaseIdentity.DatabaseGenerationProgramSize -or
        [string]$Intent.Payload.generation_program_sha256 -cne
            ([string]$ReleaseIdentity.DatabaseGenerationProgramSha256).ToLowerInvariant() -or
        [string]$Intent.Payload.target_revision -cne
            [string]$program.target_revision
    ) {
        throw "database generation intent 与 installed release evidence 漂移。"
    }
}
