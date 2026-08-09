#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('first-install', 'interrupted-retry')]
    [string]$Scenario,
    [Parameter(Mandatory = $true)][string]$ArtifactRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$scriptRoot = Split-Path -Parent $PSCommandPath
. (Join-Path $scriptRoot 'Evidence.ps1')
. (Join-Path $scriptRoot 'UiAutomation.ps1')
. (Join-Path $scriptRoot 'Validation.ps1')

$artifact = [IO.Path]::GetFullPath($ArtifactRoot)
$evidence = [IO.Path]::GetFullPath($EvidenceRoot)
$installer = Join-Path $artifact 'Ticketbox-Setup-1.2.0.exe'
$pairingCode = ''
$status = 'FAIL'
$failure = $null
$artifactReceipt = $null
$baselineReceipt = $null
$standardUser = $null
$desktopProbe = $null
$controlledFailure = $null
$interruptedState = $null
$installerResult = $null
$managerContext = $null
$serviceLifecycle = $null
$finalState = $null
$validation = $null
$started = [DateTime]::UtcNow

function Write-TbxHarnessBinding {
    param([Parameter(Mandatory = $true)][string]$OutputPath)
    $head = [string](& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve harness HEAD.' }
    $sourceTree = [string](& git rev-parse '7eb77f1dffed743dc84332539cb696dbe539cd41^{tree}').Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceTree -cne '7fd19279d5eb72a31b395a5ef634d03484f2689c') {
        throw 'Candidate source tree binding failed.'
    }
    $changed = @(& git diff --name-only 7eb77f1dffed743dc84332539cb696dbe539cd41 HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate harness-only changes.' }
    $invalid = @($changed | Where-Object {
        [string]$_ -cne '.github/workflows/windows-clean-e2e-7eb77f1d.yml' -and
        -not ([string]$_).StartsWith('.github/e2e/windows/', [StringComparison]::Ordinal)
    })
    if ($invalid.Count -ne 0) { throw 'Harness branch changes product-candidate paths.' }
    $binding = [ordered]@{
        schema = 'ticketbox-e2e-harness-binding-v1'
        harness_head = $head
        source_exact_head = '7eb77f1dffed743dc84332539cb696dbe539cd41'
        qualification_checkout = '826521709c5220ec00987625b01f80117759c9aa'
        common_tree = $sourceTree
        product_source_changed = $false
        harness_files = @($changed)
        official_semantics = @(
            [ordered]@{
                topic = 'fresh-hosted-windows-vm-and-administrator-context'
                source = 'https://docs.github.com/en/actions/reference/runners/github-hosted-runners'
            },
            [ordered]@{
                topic = 'interactive-inno-setup-log-and-exit-codes'
                source = 'https://jrsoftware.org/ishelp/topic_setupcmdline.htm'
                companion = 'https://jrsoftware.org/ishelp/topic_setupexitcodes.htm'
            },
            [ordered]@{
                topic = 'localservice-logon-and-independent-service-sid'
                source = 'https://learn.microsoft.com/en-us/windows/win32/services/localservice-account'
                companion = 'https://learn.microsoft.com/en-us/windows/win32/api/winsvc/ns-winsvc-service_sid_info'
            },
            [ordered]@{
                topic = 'semantic-ui-automation-testing'
                source = 'https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/using-ui-automation-for-automated-testing'
            },
            [ordered]@{
                topic = 'libpq-password-file'
                source = 'https://www.postgresql.org/docs/17/libpq-connect.html'
                companion = 'https://www.postgresql.org/docs/17/libpq-pgpass.html'
            }
        )
    }
    Write-TbxJson $binding $OutputPath
    return $binding
}

function Assert-TbxInterruptedBoundary {
    param(
        [Parameter(Mandatory = $true)][object]$State,
        [Parameter(Mandatory = $true)][object]$Receipt,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $installationHealth = $null
    if ($null -ne $State.health.'/api/health/installation') {
        $installationHealth = $State.health.'/api/health/installation'
    }
    $falseReady = [bool]$State.ready_identity.exists -or (
        $null -ne $installationHealth -and
        [int]$installationHealth.status_code -eq 200 -and
        [string]$installationHealth.body.runtime_access_state -ceq 'available'
    )
    $checks = [ordered]@{
        pending_present = [bool]$State.pending_identity.exists
        ready_absent = -not [bool]$State.ready_identity.exists
        fresh_intent_present = [bool]$State.fresh_intent.exists
        operation_preserved = (
            [string]$State.pending_identity.values.OPERATION_ID -ceq
            [string]$Receipt.operation_id
        )
        cluster_identifier_present = (
            [string]$State.database.system_identifier -match '^\d{18,20}$'
        )
        no_false_ready = -not $falseReady
        manual_state_cleanup = [bool]$Receipt.manual_state_cleanup
    }
    $failed = @($checks.GetEnumerator() | Where-Object {
        if ([string]$_.Key -ceq 'manual_state_cleanup') { return [bool]$_.Value }
        return -not [bool]$_.Value
    })
    $document = [ordered]@{
        schema = 'ticketbox-interrupted-boundary-validation-v1'
        validated_at_utc = [DateTime]::UtcNow.ToString('o')
        status = if ($failed.Count -eq 0) { 'PASS' } else { 'FAIL' }
        operation_id = [string]$Receipt.operation_id
        database_system_identifier = [string]$State.database.system_identifier
        checks = $checks
    }
    Write-TbxJson $document $OutputPath
    if ($failed.Count -ne 0) { throw 'Interrupted install boundary failed closed validation.' }
    return $document
}

function Get-TbxFailureRecord {
    param([Parameter(Mandatory = $true)][object]$ErrorRecord, [string]$Secret = '')
    $message = [string]$ErrorRecord.Exception.Message
    $stack = [string]$ErrorRecord.ScriptStackTrace
    if ($Secret) {
        $message = $message.Replace($Secret, '<redacted-transient-secret>')
        $stack = $stack.Replace($Secret, '<redacted-transient-secret>')
    }
    return [ordered]@{
        exception_type = [string]$ErrorRecord.Exception.GetType().FullName
        message = $message
        script_stack_trace = $stack
    }
}

function Get-TbxOptionalValue {
    param([AllowNull()][object]$Value, [Parameter(Mandatory = $true)][string]$Name)
    if ($null -eq $Value) { return '' }
    if ($Value -is [Collections.IDictionary]) {
        if ($Value.Contains($Name)) { return $Value[$Name] }
        return ''
    }
    $property = $Value.PSObject.Properties[$Name]
    if ($null -eq $property) { return '' }
    return $property.Value
}

function Wait-TbxServiceState {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet('Running', 'Stopped')][string]$DesiredState,
        [int]$TimeoutSeconds = 90
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastState = 'Missing'
    while ([DateTime]::UtcNow -lt $deadline) {
        $escaped = $Name.Replace("'", "''")
        $service = Get-CimInstance Win32_Service -Filter "Name='$escaped'" `
            -ErrorAction SilentlyContinue
        $lastState = if ($null -eq $service) { 'Missing' } else { [string]$service.State }
        if ($lastState -ceq $DesiredState) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Service $Name did not reach $DesiredState; last state=$lastState."
}

function Wait-TbxBackendHealthy {
    param([Parameter(Mandatory = $true)][int]$Port, [int]$TimeoutSeconds = 120)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastFailure = ''
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                -Uri ("http://127.0.0.1:{0}/api/health" -f $Port) -TimeoutSec 3
            $body = [string]$response.Content | ConvertFrom-Json
            if ([int]$response.StatusCode -eq 200 -and [string]$body.status -ceq 'ok') { return }
            $lastFailure = "status=$([int]$response.StatusCode)"
        }
        catch { $lastFailure = [string]$_.Exception.Message }
        Start-Sleep -Milliseconds 500
    }
    throw "Backend did not become healthy after SCM restart: $lastFailure"
}

function Invoke-TbxServiceLifecycleProbe {
    param([Parameter(Mandatory = $true)][string]$OutputDirectory)
    [void](New-Item -ItemType Directory -Path $OutputDirectory -Force)
    $steps = New-Object System.Collections.ArrayList
    foreach ($name in @('TicketboxBackend', 'TicketboxPg')) {
        $command = Invoke-TbxCapturedCommand -Name ("stop-$name") `
            -OutputDirectory $OutputDirectory -Action { & sc.exe stop $name }.GetNewClosure()
        [void]$steps.Add($command)
        if ($null -eq $command.exit_code -or [int]$command.exit_code -ne 0) {
            throw "SCM stop failed for $name."
        }
        Wait-TbxServiceState -Name $name -DesiredState 'Stopped'
    }
    $stoppedState = Capture-TbxState `
        -OutputDirectory (Join-Path $OutputDirectory 'stopped') `
        -Phase 'explicit-scm-stopped'
    foreach ($name in @('TicketboxPg', 'TicketboxBackend')) {
        $command = Invoke-TbxCapturedCommand -Name ("start-$name") `
            -OutputDirectory $OutputDirectory -Action { & sc.exe start $name }.GetNewClosure()
        [void]$steps.Add($command)
        if ($null -eq $command.exit_code -or [int]$command.exit_code -ne 0) {
            throw "SCM start failed for $name."
        }
        Wait-TbxServiceState -Name $name -DesiredState 'Running'
    }
    $registry = Get-TbxRegistryEvidence
    if (-not [bool]$registry.exists) { throw 'SCM restart lost Ticketbox registry state.' }
    Wait-TbxBackendHealthy -Port ([int]$registry.values.BackendPort)
    $restartedState = Capture-TbxState `
        -OutputDirectory (Join-Path $OutputDirectory 'restarted') `
        -Phase 'explicit-scm-restarted'
    $stoppedServices = @($stoppedState.services | Where-Object { [string]$_.state -ceq 'Stopped' })
    $runningServices = @($restartedState.services | Where-Object { [string]$_.state -ceq 'Running' })
    $proof = [ordered]@{
        schema = 'ticketbox-scm-lifecycle-proof-v1'
        status = 'PASS'
        completed_at_utc = [DateTime]::UtcNow.ToString('o')
        commands = @($steps)
        both_services_stopped = ($stoppedServices.Count -eq 2)
        both_services_restarted = ($runningServices.Count -eq 2)
        ready_identity_survived = [bool]$restartedState.ready_identity.exists
        pending_identity_absent = -not [bool]$restartedState.pending_identity.exists
        database_system_identifier_before_restart = [string]$stoppedState.database.system_identifier
        database_system_identifier_after_restart = [string]$restartedState.database.system_identifier
        database_system_identifier_preserved = (
            [string]$stoppedState.database.system_identifier -ceq
            [string]$restartedState.database.system_identifier
        )
        backend_healthy_after_restart = (
            [int]$restartedState.health.'/api/health'.status_code -eq 200
        )
    }
    if (-not $proof.both_services_stopped -or -not $proof.both_services_restarted -or
        -not $proof.ready_identity_survived -or -not $proof.pending_identity_absent -or
        [string]$proof.database_system_identifier_before_restart -notmatch '^\d{18,20}$' -or
        -not $proof.database_system_identifier_preserved -or -not $proof.backend_healthy_after_restart) {
        $proof.status = 'FAIL'
    }
    Write-TbxJson $proof (Join-Path $OutputDirectory 'SCM_LIFECYCLE_PROOF.json') -Depth 10
    if ([string]$proof.status -cne 'PASS') { throw 'SCM stop/start lifecycle proof failed.' }
    return $proof
}

try {
    Write-Host "[TBX E2E] scenario=$Scenario"
    $harnessBinding = Write-TbxHarnessBinding (Join-Path $evidence 'HARNESS_BINDING.json')
    $artifactReceipt = Assert-TbxAcceptedArtifact `
        -ArtifactRoot $artifact `
        -OutputPath (Join-Path $evidence 'ACCEPTED_ARTIFACT.json')
    $baselineDirectory = Join-Path $evidence 'baseline'
    $baselineState = Capture-TbxState -OutputDirectory $baselineDirectory -Phase 'zero-install'
    $baselineReceipt = Assert-TbxZeroBaseline `
        -State $baselineState `
        -OutputPath (Join-Path $evidence 'ZERO_INSTALL_BASELINE.json')
    Write-Host '[TBX E2E] zero-install baseline PASS'

    $standardUser = New-TbxStandardUser -EvidencePath (Join-Path $evidence 'STANDARD_USER.json')
    $desktopProbe = Test-TbxStandardUserDesktop `
        -UserContext $standardUser `
        -OutputPath (Join-Path $evidence 'STANDARD_USER_DESKTOP_PROBE.json')
    Write-Host '[TBX E2E] semantic standard-user desktop probe PASS'

    if ($Scenario -ceq 'interrupted-retry') {
        $firstContext = Start-TbxInteractiveInstaller `
            -InstallerPath $installer `
            -LogPath (Join-Path $evidence 'installer-interrupted.log') `
            -TimelinePath (Join-Path $evidence 'installer-interrupted-ui.json')
        $controlledFailure = Invoke-TbxInterruptedInstall `
            -Context $firstContext `
            -OutputPath (Join-Path $evidence 'CONTROLLED_FAILURE.json')
        Write-Host '[TBX E2E] controlled process-death boundary observed'
        $interruptedDirectory = Join-Path $evidence 'after-interruption'
        $interruptedState = Capture-TbxState `
            -OutputDirectory $interruptedDirectory `
            -Phase 'after-controlled-process-death'
        [void](Assert-TbxInterruptedBoundary `
            -State $interruptedState `
            -Receipt $controlledFailure `
            -OutputPath (Join-Path $evidence 'INTERRUPTED_BOUNDARY_VALIDATION.json'))
        Write-Host '[TBX E2E] retrying same EXE without machine-state cleanup'
    }

    $logName = if ($Scenario -ceq 'interrupted-retry') {
        'installer-no-clean-retry.log'
    } else { 'installer-first-install.log' }
    $timelineName = if ($Scenario -ceq 'interrupted-retry') {
        'installer-no-clean-retry-ui.json'
    } else { 'installer-first-install-ui.json' }
    $successContext = Start-TbxInteractiveInstaller `
        -InstallerPath $installer `
        -LogPath (Join-Path $evidence $logName) `
        -TimelinePath (Join-Path $evidence $timelineName)
    $installerResult = Complete-TbxInteractiveInstaller `
        -Context $successContext `
        -PairingCode ([ref]$pairingCode)
    Write-TbxJson $installerResult (Join-Path $evidence 'INSTALLER_SUCCESS.json')
    Write-Host '[TBX E2E] interactive installer success page committed'

    $registry = Get-TbxRegistryEvidence
    if (-not [bool]$registry.exists) { throw 'Installer succeeded without Ticketbox registry state.' }
    $managerPath = Join-Path ([string]$registry.values.InstallDir) 'manager\ticketbox-manager.exe'
    $managerDirectory = Join-Path $evidence 'manager'
    [void](New-Item -ItemType Directory -Path $managerDirectory -Force)
    $managerContext = Start-TbxManagerAsStandardUser `
        -ManagerPath $managerPath `
        -UserContext $standardUser `
        -PairingCode $pairingCode `
        -OutputDirectory $managerDirectory
    Write-Host '[TBX E2E] standard-user Manager GUI and pairing PASS'

    if ($Scenario -ceq 'first-install') {
        $serviceLifecycle = Invoke-TbxServiceLifecycleProbe `
            -OutputDirectory (Join-Path $evidence 'service-lifecycle')
        Write-Host '[TBX E2E] explicit SCM stop/start lifecycle PASS'
    }

    $finalDirectory = Join-Path $evidence 'final'
    $finalState = Capture-TbxState `
        -OutputDirectory $finalDirectory `
        -Phase 'installed-manager-running' `
        -IncludeProductLogs
    $expectedOperationId = if ($null -eq $controlledFailure) {
        ''
    } else { [string]$controlledFailure.operation_id }
    $interruptedCluster = if ($null -eq $interruptedState) {
        ''
    } else { [string]$interruptedState.database.system_identifier }
    $validation = Invoke-TbxFinalValidation `
        -Scenario $Scenario `
        -State $finalState `
        -StateDirectory $finalDirectory `
        -InstallerResult $installerResult `
        -ManagerProof $managerContext.proof `
        -StandardUserEvidence $standardUser.safe_evidence `
        -ServiceLifecycleProof $serviceLifecycle `
        -InstallerPath $installer `
        -OutputPath (Join-Path $evidence 'VALIDATION.json') `
        -ExpectedOperationId $expectedOperationId `
        -InterruptedSystemIdentifier $interruptedCluster
    $status = 'PASS'
}
catch {
    $failure = Get-TbxFailureRecord -ErrorRecord $_ -Secret $pairingCode
    Write-Host ('[TBX E2E] FAIL: ' + [string]$failure.message)
    try {
        $failureStateDirectory = Join-Path $evidence 'failure-state'
        [void](Capture-TbxState `
            -OutputDirectory $failureStateDirectory `
            -Phase 'harness-failure' `
            -IncludeProductLogs)
    }
    catch {
        $failure.state_capture_error = [string]$_.Exception.Message
    }
}
finally {
    $artifactHashAfter = Get-TbxSha256 $installer
    $readyValues = if ($null -eq $finalState) { $null } else { $finalState.ready_identity.values }
    $readyOperationId = [string](Get-TbxOptionalValue $readyValues 'OPERATION_ID')
    $databaseValues = if ($null -eq $finalState) { $null } else { $finalState.database }
    $databaseSystemIdentifier = [string](Get-TbxOptionalValue $databaseValues 'system_identifier')
    $managerProof = if ($null -eq $managerContext) { $null } else { $managerContext.proof }
    $result = [ordered]@{
        schema = 'ticketbox-clean-windows-e2e-result-v1'
        scenario = $Scenario
        status = $status
        started_at_utc = $started.ToString('o')
        completed_at_utc = [DateTime]::UtcNow.ToString('o')
        source_exact_head = '7eb77f1dffed743dc84332539cb696dbe539cd41'
        qualification_checkout = '826521709c5220ec00987625b01f80117759c9aa'
        accepted_artifact_id = 9043258694
        accepted_installer_sha256 = $artifactHashAfter
        zero_install_baseline_pass = ($null -ne $baselineReceipt)
        standard_user_desktop_probe_pass = ($null -ne $desktopProbe)
        controlled_failure_injected = ($null -ne $controlledFailure)
        no_manual_machine_state_cleanup = $true
        ready_operation_id = $readyOperationId
        original_interrupted_operation_id = if ($null -eq $controlledFailure) {
            ''
        } else { [string]$controlledFailure.operation_id }
        operation_id_preserved = if ($null -eq $controlledFailure) {
            $null
        } else { $readyOperationId -ceq [string]$controlledFailure.operation_id }
        database_system_identifier = $databaseSystemIdentifier
        database_system_identifier_preserved = if ($null -eq $interruptedState) {
            $null
        } else {
            $databaseSystemIdentifier -ceq [string]$interruptedState.database.system_identifier
        }
        installer = $installerResult
        manager = $managerProof
        service_lifecycle = $serviceLifecycle
        validation_status = if ($null -eq $validation) { 'NOT_RUN' } else { [string]$validation.status }
        evidence_finalization_status = 'COMPLETE'
        failure = $failure
    }
    $resultPath = Join-Path $evidence 'RESULT.json'
    $manifestPath = Join-Path $evidence 'EVIDENCE_MANIFEST.json'
    try {
        Write-TbxJson $result $resultPath -Depth 12
        Protect-TbxTextEvidence -Root $evidence -Secrets @($pairingCode)
        Write-TbxEvidenceManifest -Root $evidence -OutputPath $manifestPath
    }
    catch {
        $status = 'FAIL'
        $manifestFailure = [ordered]@{
            schema = 'ticketbox-evidence-finalization-failure-v1'
            message = [string]$_.Exception.Message
        }
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
            Remove-Item -LiteralPath $manifestPath -Force
        }
        $result.status = 'FAIL'
        $result.evidence_finalization_status = 'FAIL'
        if ($null -eq $result.failure) { $result.failure = $manifestFailure }
        Write-TbxJson $manifestFailure (Join-Path $evidence 'EVIDENCE_FINALIZATION_FAILURE.json')
        Write-TbxJson $result $resultPath -Depth 12
        Protect-TbxTextEvidence -Root $evidence -Secrets @($pairingCode)
    }
    $pairingCode = $null
}

if ($status -cne 'PASS') {
    Write-Error 'Ticketbox clean-Windows E2E failed; inspect the uploaded evidence artifact.'
    exit 1
}
Write-Host "[TBX E2E] PASS scenario=$Scenario"
exit 0
