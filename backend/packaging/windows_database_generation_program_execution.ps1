# Exact frozen-helper execution for an already-validated generation program.

#Requires -Version 5.1

function New-TicketboxDatabaseGenerationHelperChildEnvironment {
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
            $name.StartsWith("=", [System.StringComparison]::Ordinal)
        ) { continue }
        if ($name.StartsWith("PG", [System.StringComparison]::OrdinalIgnoreCase)) {
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

function Invoke-TicketboxDatabaseGenerationBoundHelper {
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
    $binding = Assert-TicketboxDatabaseGenerationHelper `
        -MigrationHelperPath $MigrationHelperPath `
        -MigrationHelperEvidence $MigrationHelperEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    $pgpassArgumentIndexes = @(
        for ($index = 0; $index -lt $Arguments.Count; $index += 1) {
            if ([string]$Arguments[$index] -ceq "--pgpassfile") { $index }
        }
    )
    if ([string]::IsNullOrWhiteSpace($PgPassFilePath)) {
        if ($pgpassArgumentIndexes.Count -ne 0) {
            throw "C07 packaged migration helper 不得携带未绑定的 pgpass 参数。"
        }
        $childEnvironment = New-TicketboxDatabaseGenerationHelperChildEnvironment
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
        $childEnvironment = New-TicketboxDatabaseGenerationHelperChildEnvironment `
            -PgPassFilePath $trustedPgPassFile
    }
    $lease = $null
    try {
        $lease = Open-TicketboxC07VerifiedMigrationHelperLease `
            -Path $binding.Path `
            -ExpectedRelativePath $binding.Evidence.RelativePath `
            -ExpectedSize $binding.Evidence.Size `
            -ExpectedSha256 $binding.Evidence.Sha256
        return Invoke-TicketboxBoundedNativeProcess `
            -FilePath $lease.Path `
            -Arguments $Arguments `
            -StandardInputText $StandardInputText `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -Label $Label `
            -ChildEnvironment $childEnvironment
    }
    finally {
        try {
            if ($null -ne $lease) {
                Assert-TicketboxC07MigrationHelperLeaseUnchanged $lease
            }
        }
        finally { Close-TicketboxC07MigrationHelperLease $lease }
    }
}

function ConvertFrom-TicketboxManagedSchemaResult {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][object]$Plan
    )

    $jsonLine = Get-TicketboxDatabaseGenerationJsonLine `
        -StandardOutput $StandardOutput `
        -Label "managed schema migration helper"
    try { $result = $jsonLine | ConvertFrom-Json }
    catch { throw "managed schema migration helper stdout 不是有效 JSON。" }
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $result `
        -ExpectedNames @(
            "schema",
            "source_revision",
            "target_revision",
            "generation_program_sha256",
            "result",
            "alembic_revision"
        ) `
        -Label "managed schema migration result"
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$result.generation_program_sha256) `
        "managed schema generation program"
    if (
        $jsonLine -cne (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $result) -or
        [string]$result.schema -cne $script:TicketboxManagedSchemaResultSchema -or
        [string]$result.source_revision -cne [string]$Plan.source_revision -or
        [string]$result.target_revision -cne [string]$Plan.target_revision -or
        [string]$result.alembic_revision -cne [string]$Plan.target_revision -or
        [string]$result.generation_program_sha256 -cne
            [string]$Plan.generation_program_sha256 -or
        [string]$result.result -cnotin @(
            "target_committed",
            "target_observed_after_interruption"
        )
    ) {
        throw "managed schema migration result 未绑定 exact frozen plan。"
    }
    return $result
}

function Invoke-TicketboxPackagedManagedSchemaUpgrade {
    param(
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][object]$Plan,
        [Parameter(Mandatory = $true)][string]$MigrationHelperPath,
        [Parameter(Mandatory = $true)][object]$MigrationHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMigrationHelperPath,
        [Parameter(Mandatory = $true)][string]$ProgramPath,
        [Parameter(Mandatory = $true)][object]$ProgramEvidence
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract

    if (
        [string]$Plan.generation_operation_id -cnotmatch
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' -or
        (
            -not [bool]$Plan.upgrade_required -and
            [string]$Plan.source_revision -cne [string]$Plan.target_revision
        )
    ) {
        throw "managed schema migration plan 的 source/target/revision shape 无效。"
    }
    $databaseUrl = New-TicketboxPostgresqlLocalDatabaseUrl `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role $($databasePolicy.MigratorRole)
    $capturedPlan = $Plan
    $capturedHelper = $MigrationHelperPath
    $capturedEvidence = $MigrationHelperEvidence
    $capturedExpectedHelper = $ExpectedMigrationHelperPath
    $program = Assert-TicketboxDatabaseGenerationProgram `
        -ProgramPath $ProgramPath `
        -ProgramEvidence $ProgramEvidence `
        -ExpectedMigrationHelperPath $ExpectedMigrationHelperPath
    if ($program.Evidence.Sha256 -cne [string]$Plan.generation_program_sha256) {
        throw "managed schema plan 未绑定 exact generation program。"
    }
    $capturedProgram = $program
    $capturedUrl = $databaseUrl
    return Invoke-TicketboxWithPlainPostgresqlSecret `
        -Secret $MigratorPassword `
        -Action ({
            param([string]$PlainPassword)

            $passfile = New-TicketboxProtectedPgPassFile `
                -DatabaseUrl $capturedUrl `
                -Password $PlainPassword
            try {
                $process = Invoke-TicketboxDatabaseGenerationBoundHelper `
                    -MigrationHelperPath $capturedHelper `
                    -MigrationHelperEvidence $capturedEvidence `
                    -ExpectedMigrationHelperPath $capturedExpectedHelper `
                    -Arguments @(
                        "--managed-schema-upgrade",
                        "--database-url",
                        $passfile.DatabaseUrl,
                        "--pgpassfile",
                        $passfile.Path,
                        "--generation-program-path",
                        $capturedProgram.Evidence.RelativePath,
                        "--expected-generation-program-sha256",
                        $capturedProgram.Evidence.Sha256,
                        "--source-revision",
                        [string]$capturedPlan.source_revision,
                        "--target-revision",
                        [string]$capturedPlan.target_revision,
                        "--generation-operation-id",
                        [string]$capturedPlan.generation_operation_id
                    ) `
                    -PgPassFilePath $passfile.Path `
                    -StandardInputText "" `
                    -TimeoutMilliseconds $script:TicketboxDatabaseGenerationProgramTimeoutMs `
                    -Label "managed schema release migration"
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace([string]$process.StandardError)
                ) {
                    throw (
                        "managed schema release migration 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                return ConvertFrom-TicketboxManagedSchemaResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -Plan $capturedPlan
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
