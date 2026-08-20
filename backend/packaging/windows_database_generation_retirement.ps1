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

function Test-TicketboxDatabaseGenerationBootstrapRetirement {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$HostAuthority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword
    )
    $expected = Get-TicketboxDatabaseGenerationBootstrapRetirementJson $Intent $Candidate
    $observed = Invoke-TicketboxC07Sql `
        -Authority $HostAuthority `
        -Database $script:TicketboxC07DatabaseName `
        -Role $script:TicketboxC07RuntimeRole `
        -Password $RuntimePassword `
        -Label "database generation bootstrap retirement observation" `
        -Sql @"
SELECT COALESCE(pg_catalog.shobj_description(role.oid, 'pg_authid'), '')
FROM pg_catalog.pg_roles AS role
WHERE role.rolname = 'postgres';
"@
    $fields = @(ConvertFrom-TicketboxC07SingleRow `
        -Output $observed `
        -FieldCount 1 `
        -Label "database generation bootstrap retirement observation")
    if ([string]::IsNullOrEmpty([string]$fields[0])) { return $false }
    if ([string]$fields[0] -cne $expected) {
        throw "database generation bootstrap retirement marker 与 candidate 漂移。"
    }
    return $true
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
                [string]$Transition.powershell_path,
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
    try {
        [void](Test-TicketboxDatabaseGenerationBootstrapRetirement `
            $Intent $candidate $freshHost $runtimeCredentials.RuntimePassword)
    }
    finally {
        Close-TicketboxDatabaseGenerationRuntimeCredentials $runtimeCredentials
    }
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
        [void](Invoke-TicketboxOwnedOneShotService `
            -Name ([string]$stopped.ServiceName) `
            -ExpectedExecutable $shawl `
            -ExpectedRuntimeExecutables @($shawl, $powershell, $postgres) `
            -TimeoutMilliseconds ([int]$HostContract.release_config.database_tool_timeout_ms) `
            -PollMilliseconds ([int]$HostContract.release_config.service_poll_interval_ms))
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
        Throw-TicketboxDatabaseGenerationOperationFailure $primary $restore
    }
    [void](Write-TicketboxDatabaseGenerationServiceTransition `
        $StateRoot $transition "pgctl_restored" $LifecycleLock)
    $freshHost = Resolve-TicketboxInstalledDatabaseGenerationHostAuthority $HostContract
    $retired = Test-TicketboxDatabaseGenerationBootstrapRetirement `
        $Intent $Candidate $freshHost $RuntimePassword
    if (-not $retired) {
        if ($null -ne $primary) { throw $primary }
        throw "single-user bootstrap retirement 未通过 runtime 语义复读。"
    }
    Remove-TicketboxDatabaseGenerationServiceTransition $StateRoot $LifecycleLock
    return $freshHost
}
