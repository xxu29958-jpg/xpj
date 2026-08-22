#Requires -Version 5.1

# The sole terminal transition from bootstrap PostgreSQL authority to the
# runtime-only authority bound by Generation CURRENT.

function Get-TicketboxDatabaseGenerationBootstrapRetirementJson {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate
    )
    if (
        [string]$Candidate.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$Candidate.Payload.operation_id -cne [string]$Intent.Payload.operation_id -or
        [string]$Candidate.Payload.target_revision -cne [string]$Intent.Payload.target_revision
    ) {
        throw "bootstrap retirement 拒绝非 exact candidate。"
    }
    return ConvertTo-TicketboxDatabaseGenerationCanonicalJson ([ordered]@{
        schema = "ticketbox-database-generation-bootstrap-retirement-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        candidate_sha256 = [string]$Candidate.PayloadSha256
        committed_revision = [string]$Candidate.Payload.target_revision
    })
}

function Read-TicketboxDatabaseGenerationBootstrapRetirementMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    $expected = Get-TicketboxDatabaseGenerationBootstrapRetirementJson $Intent $Candidate
    $observed = Invoke-TicketboxPostgresqlDatabaseCommand `
        -Authority $HostAuthority `
        -Database $($databasePolicy.DatabaseName) `
        -Role $Role `
        -Password $Password `
        -Label $Label `
        -Sql @"
SELECT pg_catalog.json_build_array(
           role.oid IS NOT NULL,
           CASE WHEN role.oid IS NULL THEN NULL
                ELSE pg_catalog.shobj_description(role.oid, 'pg_authid')
           END
       )::text
FROM (
    SELECT (
        SELECT catalog_role.oid
        FROM pg_catalog.pg_roles AS catalog_role
        WHERE catalog_role.rolname = 'postgres'
    ) AS oid
) AS role;
"@
    $fields = @(ConvertFrom-TicketboxPostgresqlHostEvidenceRow `
        -Output $observed `
        -FieldCount 1 `
        -Label "database generation bootstrap retirement observation")
    try { $state = [string]$fields[0] | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "database generation bootstrap retirement observation 不是闭合 JSON。" }
    if (
        $state -isnot [object[]] -or @($state).Count -ne 2 -or
        $state[0] -isnot [bool]
    ) {
        throw "database generation bootstrap retirement observation schema 无效。"
    }
    if (-not [bool]$state[0]) {
        throw "database generation bootstrap role 不存在。"
    }
    if ($null -eq $state[1] -or [string]::IsNullOrEmpty([string]$state[1])) {
        return $false
    }
    if ($state[1] -isnot [string] -or [string]$state[1] -cne $expected) {
        throw "database generation bootstrap retirement marker 与 candidate 漂移。"
    }
    return $true
}

function Test-TicketboxDatabaseGenerationBootstrapRetirement {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword
    )
    $databasePolicy = Get-TicketboxDatabaseAuthorizationContract
    return Read-TicketboxDatabaseGenerationBootstrapRetirementMarker `
        -Intent $Intent `
        -Candidate $Candidate `
        -HostAuthority $HostAuthority `
        -Role $($databasePolicy.RuntimeRole) `
        -Password $RuntimePassword `
        -Label "database generation runtime retirement observation"
}

function Test-TicketboxDatabaseGenerationBootstrapRetirementWithMaintenanceAuthority {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][object]$MaintenanceAuthority,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    [void](Assert-TicketboxDatabaseGenerationMaintenanceAuthority `
        $MaintenanceAuthority $Intent $HostAuthority $LifecycleLock)
    return Read-TicketboxDatabaseGenerationBootstrapRetirementMarker `
        -Intent $Intent `
        -Candidate $Candidate `
        -HostAuthority $HostAuthority `
        -Role "postgres" `
        -Password $MaintenanceAuthority.Secret `
        -Label "database generation maintenance retirement observation"
}

function Get-TicketboxDatabaseGenerationServiceTransitionPath {
    param([Parameter(Mandatory = $true)][string]$StateRoot)
    return Join-Path $StateRoot "postgres-service-transition.json"
}

function Read-TicketboxDatabaseGenerationServiceTransition {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxDatabaseGenerationServiceTransitionPath $StateRoot
    if ((Get-TicketboxPathEntryKindNoFollow $path) -ceq "Missing") {
        if ($AllowAbsent) { return $null }
        throw "database generation service transition 不存在。"
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    try { $payload = $artifact.Text | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "database generation service transition 不是有效 JSON。" }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $payload `
        @(
            "candidate_sha256", "formal_image_path", "helper_path",
            "helper_sha256", "intent_sha256", "operation_id", "phase",
            "physical_pg_data", "pg_ctl_path", "pg_data", "port",
            "postgres_path", "powershell_path", "schema", "service_name",
            "shawl_path", "temporary_image_path"
        ) `
        "database generation service transition"
    if (
        [string]$payload.schema -cne
            "ticketbox-database-generation-service-transition-v1" -or
        [string]$payload.phase -cnotin @(
            "intent_written", "host_stopped", "start_authorized",
            "restore_required", "pgctl_restored"
        )
    ) {
        throw "database generation service transition schema/phase 无效。"
    }
    foreach ($name in @("intent_sha256", "candidate_sha256", "helper_sha256")) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            ([string]$payload.$name) `
            ("service transition " + $name)
    }
    return $payload
}

function Write-TicketboxDatabaseGenerationServiceTransition {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $Payload.phase = $Phase
    Write-TicketboxProtectedUtf8FileDurable `
        -Path (Get-TicketboxDatabaseGenerationServiceTransitionPath $StateRoot) `
        -Text (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $Payload) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount `
        -ReplaceExisting
    return Read-TicketboxDatabaseGenerationServiceTransition $StateRoot
}

function Remove-TicketboxDatabaseGenerationServiceTransition {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Get-TicketboxDatabaseGenerationServiceTransitionPath $StateRoot
    if ((Get-TicketboxPathEntryKindNoFollow $path) -ceq "Missing") { return }
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $path `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
}

function Remove-TicketboxDatabaseGenerationTransientAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][string]$BootstrapRecoveryPath,
        [Parameter(Mandatory = $true)][string]$BootstrapAppData,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $serviceTransitionPath =
        Get-TicketboxDatabaseGenerationServiceTransitionPath $StateRoot
    if ((Get-TicketboxPathEntryKindNoFollow $serviceTransitionPath) -cne "Missing") {
        throw "transient authority retirement 遇到未闭合 service transition。"
    }
    Remove-PostgresBootstrapRecoveryState `
        -Path $BootstrapRecoveryPath `
        -AppData $BootstrapAppData
    Remove-TicketboxDatabaseGenerationCredentials `
        -StateRoot $StateRoot `
        -Intent $Intent `
        -LifecycleLock $LifecycleLock
    $credentialsPath = Get-TicketboxDatabaseGenerationArtifactPath `
        $StateRoot "credentials" $operationId
    if (
        (Get-TicketboxPathEntryKindNoFollow $BootstrapRecoveryPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow $credentialsPath) -cne "Missing" -or
        (Get-TicketboxPathEntryKindNoFollow $serviceTransitionPath) -cne "Missing"
    ) {
        throw "database generation transient authority retirement 未闭合。"
    }
}

function Restore-TicketboxDatabaseGenerationFormalPostgresqlService {
    param(
        [Parameter(Mandatory = $true)][object]$Transition,
        [Parameter(Mandatory = $true)][object]$HostContract
    )
    $serviceName = [string]$Transition.service_name
    $actualImagePath = Get-TicketboxServiceImagePathExact $serviceName
    if ($actualImagePath -ceq [string]$Transition.temporary_image_path) {
        Stop-TicketboxOwnedServiceIfExists `
            -Name $serviceName `
            -ExpectedExecutable ([string]$Transition.shawl_path) `
            -TimeoutMilliseconds ([int]$HostContract.release_config.service_state_timeout_ms) `
            -PollMilliseconds ([int]$HostContract.release_config.service_poll_interval_ms) `
            -BackendPort ([int]$Transition.port) `
            -ExpectedRuntimeExecutables @(
                [string]$Transition.shawl_path,
                [string]$Transition.postgres_path
            )
    }
    elseif ($actualImagePath -cne [string]$Transition.formal_image_path) {
        throw "database generation service transition 遇到第三种 ImagePath authority。"
    }
    $stopped = [pscustomobject]@{
        ServiceName = $serviceName
        PgCtlPath = [string]$Transition.pg_ctl_path
        PgData = [string]$Transition.pg_data
        FormalImagePath = [string]$Transition.formal_image_path
    }
    Restore-TicketboxPostgresqlFormalServiceCommand $stopped $HostContract
    [void](Start-TicketboxOwnedServiceIfExists `
        -Name $serviceName `
        -ExpectedExecutable ([string]$Transition.pg_ctl_path) `
        -TimeoutMilliseconds ([int]$HostContract.release_config.postgres_ready_timeout_ms) `
        -PollMilliseconds ([int]$HostContract.release_config.postgres_ready_poll_interval_ms))
}

function Repair-TicketboxDatabaseGenerationServiceTransition {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $transition = Read-TicketboxDatabaseGenerationServiceTransition `
        $StateRoot -AllowAbsent
    if ($null -eq $transition) { return }
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
        $StateRoot $operationId "candidate"
    $expectedHelper = [IO.Path]::GetFullPath((Join-Path `
        ([string]$HostContract.install_dir) `
        "installer\windows_database_generation_single_user.ps1"))
    $expectedShawl = [IO.Path]::GetFullPath((Join-Path `
        ([string]$HostContract.install_dir) "shawl\shawl.exe"))
    $expectedPowerShell = [IO.Path]::GetFullPath(
        (Get-TicketboxWindowsPowerShellExecutable)
    )
    $expectedPostgres = [IO.Path]::GetFullPath((Join-Path `
        (Split-Path -Parent ([string]$HostContract.pg_ctl_path)) "postgres.exe"))
    $expectedTemporaryImagePath = New-TicketboxPostgresqlSingleUserServiceImagePath `
        -ShawlPath $expectedShawl `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -WorkingDirectory (Split-Path -Parent $expectedHelper) `
        -PowerShellPath $expectedPowerShell `
        -HelperPath $expectedHelper `
        -PostgresPath $expectedPostgres `
        -PhysicalPgData ([string]$transition.physical_pg_data) `
        -OperationId $operationId `
        -IntentSha256 ([string]$Intent.PayloadSha256) `
        -CandidateSha256 ([string]$candidate.PayloadSha256) `
        -CommittedRevision ([string]$candidate.Payload.target_revision) `
        -StopTimeoutMilliseconds ([int]$HostContract.release_config.stop_timeout_ms) `
        -OperationTimeoutMilliseconds ([int]$HostContract.release_config.database_tool_timeout_ms)
    if (
        [string]$transition.operation_id -cne $operationId -or
        [string]$transition.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$transition.candidate_sha256 -cne [string]$candidate.PayloadSha256 -or
        [string]$transition.service_name -cne [string]$HostContract.pg_service_name -or
        -not (Test-TicketboxPathEquals `
            ([string]$transition.pg_ctl_path) ([string]$HostContract.pg_ctl_path)) -or
        -not (Test-TicketboxPathEquals ([string]$transition.helper_path) $expectedHelper) -or
        -not (Test-TicketboxPathEquals ([string]$transition.shawl_path) $expectedShawl) -or
        -not (Test-TicketboxPathEquals `
            ([string]$transition.powershell_path) $expectedPowerShell) -or
        -not (Test-TicketboxPathEquals ([string]$transition.postgres_path) $expectedPostgres) -or
        [string]$transition.temporary_image_path -cne $expectedTemporaryImagePath -or
        [string]$transition.helper_sha256 -cne
            (Get-TicketboxPortableFileSha256 $expectedHelper).ToLowerInvariant()
    ) {
        throw "database generation service transition 与 active intent/candidate 漂移。"
    }
    Restore-TicketboxDatabaseGenerationFormalPostgresqlService `
        $transition $HostContract
    [void](Write-TicketboxDatabaseGenerationServiceTransition `
        $StateRoot $transition "pgctl_restored" $LifecycleLock)
    $freshHost = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority $HostContract
    $runtimeCredentials = Read-TicketboxDatabaseGenerationRuntimeCredentials `
        $StateRoot $Intent $candidate
    $primary = $null
    $cleanup = @()
    try {
        [void](Test-TicketboxDatabaseGenerationBootstrapRetirement `
            $Intent $candidate $freshHost $runtimeCredentials.RuntimePassword)
    }
    catch { $primary = $_ }
    finally {
        try { Close-TicketboxDatabaseGenerationRuntimeCredentials $runtimeCredentials }
        catch { $cleanup += $_ }
    }
    Throw-TicketboxOperationFailure $primary $cleanup
    Remove-TicketboxDatabaseGenerationServiceTransition $StateRoot $LifecycleLock
}

function Retire-TicketboxDatabaseGenerationBootstrapAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostContract,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $helper = Join-Path `
        ([string]$HostContract.install_dir) `
        "installer\windows_database_generation_single_user.ps1"
    $shawl = Join-Path ([string]$HostContract.install_dir) "shawl\shawl.exe"
    $powershell = Get-TicketboxWindowsPowerShellExecutable
    $postgres = Join-Path (Split-Path -Parent ([string]$HostContract.pg_ctl_path)) "postgres.exe"
    foreach ($path in @($helper, $shawl, $postgres)) {
        if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
            throw "database generation single-user dependency 不是普通文件：$path"
        }
        Assert-NoTicketboxAncestorReparsePoints $path
    }
    $operationId = ([guid][string]$Intent.Payload.operation_id).ToString("D")
    $imagePath = New-TicketboxPostgresqlSingleUserServiceImagePath `
        -ShawlPath $shawl `
        -ServiceName ([string]$HostContract.pg_service_name) `
        -WorkingDirectory (Split-Path -Parent $helper) `
        -PowerShellPath $powershell `
        -HelperPath $helper `
        -PostgresPath $postgres `
        -PhysicalPgData ([string]$HostAuthority.PhysicalPgData) `
        -OperationId $operationId `
        -IntentSha256 ([string]$Intent.PayloadSha256) `
        -CandidateSha256 ([string]$Candidate.PayloadSha256) `
        -CommittedRevision ([string]$Candidate.Payload.target_revision) `
        -StopTimeoutMilliseconds ([int]$HostContract.release_config.stop_timeout_ms) `
        -OperationTimeoutMilliseconds ([int]$HostContract.release_config.database_tool_timeout_ms)
    $formalImagePath = Get-TicketboxServiceImagePathExact `
        ([string]$HostContract.pg_service_name)
    $transition = [pscustomobject][ordered]@{
        schema = "ticketbox-database-generation-service-transition-v1"
        operation_id = $operationId
        intent_sha256 = [string]$Intent.PayloadSha256
        candidate_sha256 = [string]$Candidate.PayloadSha256
        service_name = [string]$HostContract.pg_service_name
        pg_ctl_path = [IO.Path]::GetFullPath([string]$HostContract.pg_ctl_path)
        postgres_path = [IO.Path]::GetFullPath($postgres)
        shawl_path = [IO.Path]::GetFullPath($shawl)
        powershell_path = [IO.Path]::GetFullPath($powershell)
        helper_path = [IO.Path]::GetFullPath($helper)
        helper_sha256 = (Get-TicketboxPortableFileSha256 $helper).ToLowerInvariant()
        pg_data = [IO.Path]::GetFullPath([string]$HostAuthority.PgData)
        physical_pg_data = [IO.Path]::GetFullPath([string]$HostAuthority.PhysicalPgData)
        port = [int]$HostAuthority.Port
        formal_image_path = $formalImagePath
        temporary_image_path = $imagePath
        phase = "intent_written"
    }
    [void](Write-TicketboxDatabaseGenerationServiceTransition `
        $StateRoot $transition "intent_written" $LifecycleLock)
    $primary = $null
    $restore = $null
    $stopped = $null
    try {
        $stopped = Enter-TicketboxPostgresqlStoppedHostAuthority `
            $HostAuthority $HostContract $formalImagePath
        [void](Write-TicketboxDatabaseGenerationServiceTransition `
            $StateRoot $transition "host_stopped" $LifecycleLock)
        Set-TicketboxPostgresqlSingleUserServiceCommand `
            $stopped $HostContract $imagePath
        [void](Write-TicketboxDatabaseGenerationServiceTransition `
            $StateRoot $transition "start_authorized" $LifecycleLock)
        $snapshot = Invoke-TicketboxOwnedOneShotService `
            -Name ([string]$stopped.ServiceName) `
            -ExpectedExecutable $shawl `
            -ExpectedRuntimeExecutables @($shawl, $postgres) `
            -TimeoutMilliseconds ([int]$HostContract.release_config.database_tool_timeout_ms) `
            -PollMilliseconds ([int]$HostContract.release_config.service_poll_interval_ms)
        $serviceExitCode = [uint32]$snapshot.ExitCode
        $serviceSpecificExitCode = [uint32]$snapshot.ServiceSpecificExitCode
        if ($serviceExitCode -ne 0) {
            $nativeExit = if (
                $serviceExitCode -eq 1066 -and
                $serviceSpecificExitCode -ne 0
            ) {
                [uint64]$serviceSpecificExitCode
            }
            else { [uint64]$serviceExitCode }
            throw "database generation single-user service 失败（exit=$nativeExit）。"
        }
        [void](Write-TicketboxDatabaseGenerationServiceTransition `
            $StateRoot $transition "restore_required" $LifecycleLock)
    }
    catch { $primary = $_ }
    finally {
        try {
            Restore-TicketboxDatabaseGenerationFormalPostgresqlService `
                $transition $HostContract
        }
        catch { $restore = $_ }
    }
    if ($null -ne $restore) {
        Throw-TicketboxOperationFailure $primary $restore
    }
    [void](Write-TicketboxDatabaseGenerationServiceTransition `
        $StateRoot $transition "pgctl_restored" $LifecycleLock)
    $freshHost = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority $HostContract
    $retired = $false
    try {
        $retired = Test-TicketboxDatabaseGenerationBootstrapRetirement `
            $Intent $Candidate $freshHost $RuntimePassword
    }
    catch {
        if ($null -ne $primary) {
            Throw-TicketboxOperationFailure $primary $_
        }
        throw
    }
    if (-not $retired) {
        if ($null -ne $primary) { throw $primary }
        throw "single-user bootstrap retirement 未通过 runtime 语义复读。"
    }
    Remove-TicketboxDatabaseGenerationServiceTransition $StateRoot $LifecycleLock
    return $freshHost
}
