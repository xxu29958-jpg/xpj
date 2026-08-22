# Exact frozen-helper execution for an already-validated generation program.

#Requires -Version 5.1

function New-TicketboxDatabaseGenerationHelperChildEnvironment {
    param(
        [AllowEmptyString()][string]$PgPassFilePath = ""
    )

    $childEnvironment = @{}
    foreach ($name in @(
        "SystemRoot",
        "WINDIR",
        "ComSpec",
        "TEMP",
        "TMP",
        "PATH",
        "PATHEXT"
    )) {
        $value = [Environment]::GetEnvironmentVariable(
            $name,
            [EnvironmentVariableTarget]::Process
        )
        if ($null -ne $value) {
            $childEnvironment[$name] = [string]$value
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($PgPassFilePath)) {
        $childEnvironment["PGPASSFILE"] =
            [System.IO.Path]::GetFullPath($PgPassFilePath)
    }
    return $childEnvironment
}

function Invoke-TicketboxDatabaseGenerationBoundHelper {
    [CmdletBinding(DefaultParameterSetName = "ValidateProgram")]
    param(
        [Parameter(Mandatory = $true)][string]$MaintenanceHelperPath,
        [Parameter(Mandatory = $true)][object]$MaintenanceHelperEvidence,
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()][string]$ExpectedMaintenanceHelperPath,
        [Parameter(Mandatory = $true)][string]$ProgramRelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedProgramSha256,
        [Parameter(Mandatory = $true, ParameterSetName = "ValidateProgram")]
        [switch]$ValidateProgram,
        [Parameter(Mandatory = $true, ParameterSetName = "UpgradeManagedSchema")]
        [switch]$UpgradeManagedSchema,
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [switch]$VerifyTarget,
        [Parameter(Mandatory = $true, ParameterSetName = "UpgradeManagedSchema")]
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [string]$DatabaseUrl,
        [Parameter(Mandatory = $true, ParameterSetName = "UpgradeManagedSchema")]
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [string]$PgPassFilePath,
        [Parameter(Mandatory = $true, ParameterSetName = "UpgradeManagedSchema")]
        [string]$SourceRevision,
        [Parameter(Mandatory = $true, ParameterSetName = "UpgradeManagedSchema")]
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [string]$TargetRevision,
        [Parameter(Mandatory = $true, ParameterSetName = "UpgradeManagedSchema")]
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [string]$OperationId,
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [string]$Database,
        [Parameter(Mandatory = $true, ParameterSetName = "VerifyTarget")]
        [AllowEmptyString()][string]$RestoreAttemptId
    )
    $binding = Assert-TicketboxDatabaseGenerationHelper `
        -MaintenanceHelperPath $MaintenanceHelperPath `
        -MaintenanceHelperEvidence $MaintenanceHelperEvidence `
        -ExpectedMaintenanceHelperPath $ExpectedMaintenanceHelperPath
    if ($PSCmdlet.ParameterSetName -ceq "ValidateProgram") {
        $arguments = @(
            "--validate-generation-program",
            "--generation-program-path", $ProgramRelativePath,
            "--expected-generation-program-sha256", $ExpectedProgramSha256
        )
        $childEnvironment = New-TicketboxDatabaseGenerationHelperChildEnvironment
        $timeoutMilliseconds = $script:TicketboxDatabaseGenerationProgramTimeoutMs
        $label = "database generation program validation"
    }
    else {
        $trustedPgPassFile = [System.IO.Path]::GetFullPath($PgPassFilePath)
        if ((Get-TicketboxPathEntryKindNoFollow $trustedPgPassFile) -cne "File") {
            throw "database maintenance pgpass 不是受保护普通文件。"
        }
        Assert-NoTicketboxAncestorReparsePoints $trustedPgPassFile
        $childEnvironment = New-TicketboxDatabaseGenerationHelperChildEnvironment `
            -PgPassFilePath $trustedPgPassFile
        if ($PSCmdlet.ParameterSetName -ceq "UpgradeManagedSchema") {
            $arguments = @(
                "--managed-schema-upgrade",
                "--database-url", $DatabaseUrl,
                "--pgpassfile", $trustedPgPassFile,
                "--generation-program-path", $ProgramRelativePath,
                "--expected-generation-program-sha256", $ExpectedProgramSha256,
                "--source-revision", $SourceRevision,
                "--target-revision", $TargetRevision,
                "--generation-operation-id", $OperationId
            )
            $timeoutMilliseconds = $script:TicketboxDatabaseGenerationProgramTimeoutMs
            $label = "managed schema release migration"
        }
        else {
            $arguments = @(
                "--database-generation-verify-target",
                "--database-url", $DatabaseUrl,
                "--pgpassfile", $trustedPgPassFile,
                "--generation-program-path", $ProgramRelativePath,
                "--expected-generation-program-sha256", $ExpectedProgramSha256,
                "--operation-id", $OperationId,
                "--database", $Database,
                "--target-revision", $TargetRevision
            )
            if (-not [string]::IsNullOrEmpty($RestoreAttemptId)) {
                $arguments += @("--restore-attempt-id", $RestoreAttemptId)
            }
            $timeoutMilliseconds = $script:TicketboxDatabaseGenerationRecoveryTimeoutMs
            $label = "database generation target verification"
        }
    }
    $lease = $null
    $primary = $null
    $cleanup = @()
    $result = $null
    try {
        $lease = Open-TicketboxVerifiedDatabaseMaintenanceHelperLease `
            -Path $binding.Path `
            -ExpectedRelativePath $binding.Evidence.RelativePath `
            -ExpectedSize $binding.Evidence.Size `
            -ExpectedSha256 $binding.Evidence.Sha256
        $result = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $lease.Path `
            -Arguments $arguments `
            -StandardInputText "" `
            -TimeoutMilliseconds $timeoutMilliseconds `
            -Label $label `
            -ChildEnvironment $childEnvironment
    }
    catch { $primary = $_ }
    finally {
        try {
            if ($null -ne $lease) {
                Assert-TicketboxDatabaseMaintenanceHelperLeaseUnchanged $lease
            }
        }
        catch { $cleanup += $_ }
        try { Close-TicketboxDatabaseMaintenanceHelperLease $lease }
        catch { $cleanup += $_ }
    }
    Throw-TicketboxOperationFailure $primary $cleanup
    return $result
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
        [Parameter(Mandatory = $true)][string]$MaintenanceHelperPath,
        [Parameter(Mandatory = $true)][object]$MaintenanceHelperEvidence,
        [Parameter(Mandatory = $true)][string]$ExpectedMaintenanceHelperPath,
        [Parameter(Mandatory = $true)][string]$ProgramPath,
        [Parameter(Mandatory = $true)][object]$ProgramEvidence
    )
    Assert-TicketboxDatabaseGenerationProgramAdapterDependencies
    foreach ($commandName in @(
        "Get-TicketboxDatabaseAuthorizationContract",
        "Invoke-TicketboxWithPlainPostgresqlSecret",
        "New-TicketboxPostgresqlLocalDatabaseUrl",
        "New-TicketboxProtectedPgPassFile",
        "Remove-TicketboxProtectedPgPassArtifact"
    )) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "managed schema execution 缺少依赖：$commandName"
        }
    }
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
    $capturedHelper = $MaintenanceHelperPath
    $capturedEvidence = $MaintenanceHelperEvidence
    $capturedExpectedHelper = $ExpectedMaintenanceHelperPath
    $program = Assert-TicketboxDatabaseGenerationProgram `
        -ProgramPath $ProgramPath `
        -ProgramEvidence $ProgramEvidence `
        -ExpectedMaintenanceHelperPath $ExpectedMaintenanceHelperPath
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
            $primary = $null
            $cleanup = @()
            $operationResult = $null
            try {
                $process = Invoke-TicketboxDatabaseGenerationBoundHelper `
                    -MaintenanceHelperPath $capturedHelper `
                    -MaintenanceHelperEvidence $capturedEvidence `
                    -ExpectedMaintenanceHelperPath $capturedExpectedHelper `
                    -UpgradeManagedSchema `
                    -DatabaseUrl $passfile.DatabaseUrl `
                    -PgPassFilePath $passfile.Path `
                    -ProgramRelativePath $capturedProgram.Evidence.RelativePath `
                    -ExpectedProgramSha256 $capturedProgram.Evidence.Sha256 `
                    -SourceRevision ([string]$capturedPlan.source_revision) `
                    -TargetRevision ([string]$capturedPlan.target_revision) `
                    -OperationId ([string]$capturedPlan.generation_operation_id)
                if (
                    [int]$process.ExitCode -ne 0 -or
                    -not [string]::IsNullOrWhiteSpace([string]$process.StandardError)
                ) {
                    throw (
                        "managed schema release migration 被拒绝" +
                        "（exit=$([int]$process.ExitCode)）；原生输出已抑制。"
                    )
                }
                $operationResult = ConvertFrom-TicketboxManagedSchemaResult `
                    -StandardOutput ([string]$process.StandardOutput) `
                    -Plan $capturedPlan
            }
            catch { $primary = $_ }
            finally {
                if ($null -ne $passfile) {
                    try {
                        Remove-TicketboxProtectedPgPassArtifact `
                            -Path $passfile.Path `
                            -FullControlAccounts $passfile.FullControlAccounts `
                            -OwnerAccount $passfile.OwnerAccount
                    }
                    catch { $cleanup += $_ }
                }
            }
            Throw-TicketboxOperationFailure $primary $cleanup
            return $operationResult
        }.GetNewClosure())
}
