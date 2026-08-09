#requires -Version 5.1

Set-StrictMode -Version 2.0

function Add-TbxValidationCheck {
    param(
        [Parameter(Mandatory = $true)][object]$Checks,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [AllowNull()][object]$Actual,
        [AllowNull()][object]$Expected,
        [Parameter(Mandatory = $true)][string]$Evidence
    )
    [void]$Checks.Add([ordered]@{
        name = $Name
        passed = $Passed
        actual = $Actual
        expected = $Expected
        evidence = $Evidence
    })
}

function Get-TbxServiceFromState {
    param([Parameter(Mandatory = $true)][object]$State, [Parameter(Mandatory = $true)][string]$Name)
    return @($State.services | Where-Object { [string]$_.name -ceq $Name }) |
        Select-Object -First 1
}

function Get-TbxArtifactFromState {
    param([Parameter(Mandatory = $true)][object]$State, [Parameter(Mandatory = $true)][string]$Suffix)
    return @($State.installed_artifacts | Where-Object {
        ([string]$_.path).EndsWith($Suffix, [StringComparison]::OrdinalIgnoreCase)
    }) | Select-Object -First 1
}

function Test-TbxServiceContract {
    param(
        [Parameter(Mandatory = $true)][object]$Checks,
        [Parameter(Mandatory = $true)][object]$State,
        [Parameter(Mandatory = $true)][string]$StateDirectory,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $service = Get-TbxServiceFromState $State $Name
    Add-TbxValidationCheck $Checks "$Name-exists" ($null -ne $service -and [bool]$service.exists) `
        $(if ($null -eq $service) { 'missing' } else { [bool]$service.exists }) $true 'STATE.json'
    Add-TbxValidationCheck $Checks "$Name-running" ($null -ne $service -and [string]$service.state -ceq 'Running') `
        $(if ($null -eq $service) { 'missing' } else { [string]$service.state }) 'Running' 'STATE.json'
    Add-TbxValidationCheck $Checks "$Name-auto" ($null -ne $service -and [string]$service.start_mode -ceq 'Auto') `
        $(if ($null -eq $service) { 'missing' } else { [string]$service.start_mode }) 'Auto' 'STATE.json'
    Add-TbxValidationCheck $Checks "$Name-delayed-auto" `
        ($null -ne $service -and [int]$service.delayed_auto_start -eq 1) `
        $(if ($null -eq $service) { 'missing' } else { $service.delayed_auto_start }) 1 'STATE.json'
    Add-TbxValidationCheck $Checks "$Name-real-pid" ($null -ne $service -and [int]$service.process_id -gt 0) `
        $(if ($null -eq $service) { 0 } else { [int]$service.process_id }) 'greater than zero' 'STATE.json'
    Add-TbxValidationCheck $Checks "$Name-logon" `
        ($null -ne $service -and [string]$service.start_name -ceq 'NT AUTHORITY\LocalService') `
        $(if ($null -eq $service) { 'missing' } else { [string]$service.start_name }) `
        'NT AUTHORITY\LocalService' 'STATE.json'
    Add-TbxValidationCheck $Checks "$Name-resource-sid" `
        ($null -ne $service -and [string]$service.resource_sid -match '^S-1-5-80-([0-9]+-){4}[0-9]+$') `
        $(if ($null -eq $service) { 'missing' } else { [string]$service.resource_sid }) `
        'S-1-5-80 service SID' 'STATE.json'
    $expectedDependencies = if ($Name -ceq 'TicketboxBackend') { @('TicketboxPg') } else { @() }
    $actualDependencies = if ($null -eq $service) { @() } else { @($service.dependencies) }
    Add-TbxValidationCheck $Checks "$Name-dependencies" `
        (($actualDependencies -join "`n") -ceq ($expectedDependencies -join "`n")) `
        $actualDependencies $expectedDependencies 'STATE.json'
    $expectedExecutable = if ($Name -ceq 'TicketboxPg') {
        Join-Path ([string]$State.registry.values.InstallDir) 'pg\bin\pg_ctl.exe'
    } else {
        Join-Path ([string]$State.registry.values.InstallDir) 'shawl\shawl.exe'
    }
    $expectedPrefix = '"' + $expectedExecutable + '" '
    Add-TbxValidationCheck $Checks "$Name-image-path" `
        ($null -ne $service -and ([string]$service.path_name).StartsWith(
            $expectedPrefix, [StringComparison]::OrdinalIgnoreCase
        )) `
        $(if ($null -eq $service) { 'missing' } else { [string]$service.path_name }) `
        ($expectedPrefix + '...') 'STATE.json'
    $commandFailures = if ($null -eq $service) { @('missing') } else {
        @($service.commands | Where-Object {
            $null -eq $_.exit_code -or [int]$_.exit_code -ne 0 -or [string]$_.error
        } | ForEach-Object { [string]$_.name })
    }
    Add-TbxValidationCheck $Checks "$Name-scm-query-success" `
        ($commandFailures.Count -eq 0) $commandFailures @() 'sc-*.stdout.log'
    $sidPath = Join-Path $StateDirectory "sc-$Name-qsidtype.stdout.log"
    $sidText = if (Test-Path -LiteralPath $sidPath) { Get-Content -LiteralPath $sidPath -Raw } else { '' }
    Add-TbxValidationCheck $Checks "$Name-sid-unrestricted" `
        ($sidText -match 'SERVICE_SID_TYPE\s*:\s*UNRESTRICTED') $sidText `
        'SERVICE_SID_TYPE: UNRESTRICTED' ([IO.Path]::GetFileName($sidPath))
    $failurePath = Join-Path $StateDirectory "sc-$Name-qfailure.stdout.log"
    $failureText = if (Test-Path -LiteralPath $failurePath) {
        Get-Content -LiteralPath $failurePath -Raw
    } else { '' }
    $failurePolicyMatches = $failureText -match '3600' -and
        $failureText -match '5000' -and $failureText -match '10000' -and
        $failureText -match '60000'
    Add-TbxValidationCheck $Checks "$Name-failure-policy" $failurePolicyMatches `
        $failureText 'reset=3600; restart delays=5000,10000,60000' `
        ([IO.Path]::GetFileName($failurePath))
}

function Test-TbxLifecycleContract {
    param(
        [Parameter(Mandatory = $true)][object]$Checks,
        [Parameter(Mandatory = $true)][object]$State,
        [string]$ExpectedOperationId = ''
    )
    $ready = $State.ready_identity
    $pending = $State.pending_identity
    Add-TbxValidationCheck $Checks 'ready-published' ([bool]$ready.exists) ([bool]$ready.exists) $true 'STATE.json'
    Add-TbxValidationCheck $Checks 'pending-consumed' (-not [bool]$pending.exists) ([bool]$pending.exists) $false 'STATE.json'
    Add-TbxValidationCheck $Checks 'ready-state' ([string]$ready.values.STATE -ceq 'READY') `
        ([string]$ready.values.STATE) 'READY' 'STATE.json'
    Add-TbxValidationCheck $Checks 'ready-operation-shaped' `
        ([string]$ready.values.OPERATION_ID -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') `
        ([string]$ready.values.OPERATION_ID) 'lowercase UUID' 'STATE.json'
    Add-TbxValidationCheck $Checks 'ready-installation-shaped' `
        ([string]$ready.values.INSTALLATION_ID -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') `
        ([string]$ready.values.INSTALLATION_ID) 'lowercase UUID' 'STATE.json'
    Add-TbxValidationCheck $Checks 'ready-version' `
        ([string]$ready.values.BACKEND_VERSION_FLOOR -ceq '1.2.0') `
        ([string]$ready.values.BACKEND_VERSION_FLOOR) '1.2.0' 'STATE.json'
    Add-TbxValidationCheck $Checks 'ready-build-manifest' `
        ([string]$ready.values.BUILD_MANIFEST_SHA256 -ceq 'D2FAD5223D0ECEC7D363854A83841CF62635E5693DEBF3A5FC9D2BE5682B1701') `
        ([string]$ready.values.BUILD_MANIFEST_SHA256) `
        'D2FAD5223D0ECEC7D363854A83841CF62635E5693DEBF3A5FC9D2BE5682B1701' 'STATE.json'
    Add-TbxValidationCheck $Checks 'ready-migration-helper' `
        ([string]$ready.values.MIGRATION_HELPER_SHA256 -ceq 'B2AC1AE9FF97B77EF2EC9BE84F7ABFD5BD509D46D1E286A819C640D37E54917C') `
        ([string]$ready.values.MIGRATION_HELPER_SHA256) `
        'B2AC1AE9FF97B77EF2EC9BE84F7ABFD5BD509D46D1E286A819C640D37E54917C' 'STATE.json'
    if ($ExpectedOperationId) {
        Add-TbxValidationCheck $Checks 'retry-preserved-operation-id' `
            ([string]$ready.values.OPERATION_ID -ceq $ExpectedOperationId) `
            ([string]$ready.values.OPERATION_ID) $ExpectedOperationId 'CONTROLLED_FAILURE.json and STATE.json'
    }
    Add-TbxValidationCheck $Checks 'fresh-intent-consumed' (-not [bool]$State.fresh_intent.exists) `
        ([bool]$State.fresh_intent.exists) $false 'STATE.json'
    $receipt = $State.lifecycle_receipt
    $document = $receipt.document
    Add-TbxValidationCheck $Checks 'lifecycle-receipt-present' ([bool]$receipt.exists) `
        ([bool]$receipt.exists) $true 'STATE.json'
    Add-TbxValidationCheck $Checks 'lifecycle-schema-v8' `
        ($null -ne $document -and [string]$document.schema -ceq 'ticketbox-windows-lifecycle-receipt-v8') `
        $(if ($null -eq $document) { 'missing' } else { [string]$document.schema }) `
        'ticketbox-windows-lifecycle-receipt-v8' 'STATE.json'
    Add-TbxValidationCheck $Checks 'lifecycle-fresh-install' `
        ($null -ne $document -and [string]$document.mode -ceq 'fresh_install') `
        $(if ($null -eq $document) { 'missing' } else { [string]$document.mode }) `
        'fresh_install' 'STATE.json'
    Add-TbxValidationCheck $Checks 'lifecycle-completed' `
        ($null -ne $document -and [bool]$document.install_completed) `
        $(if ($null -eq $document) { 'missing' } else { [bool]$document.install_completed }) `
        $true 'STATE.json'
    Add-TbxValidationCheck $Checks 'lifecycle-operation-matches-ready' `
        ($null -ne $document -and [string]$document.c07_installation_operation_id -ceq [string]$ready.values.OPERATION_ID) `
        $(if ($null -eq $document) { 'missing' } else { [string]$document.c07_installation_operation_id }) `
        ([string]$ready.values.OPERATION_ID) 'STATE.json'
    Add-TbxValidationCheck $Checks 'release-config-v2' `
        ($null -ne $document -and [string]$document.installed_release_config.schema -ceq 'ticketbox-windows-release-v2') `
        $(if ($null -eq $document) { 'missing' } else { [string]$document.installed_release_config.schema }) `
        'ticketbox-windows-release-v2' 'STATE.json'
    Add-TbxValidationCheck $Checks 'release-logon-local-service' `
        ($null -ne $document -and [string]$document.installed_release_config.service_logon_account -ceq 'NT AUTHORITY\LocalService') `
        $(if ($null -eq $document) { 'missing' } else { [string]$document.installed_release_config.service_logon_account }) `
        'NT AUTHORITY\LocalService' 'STATE.json'
    Add-TbxValidationCheck $Checks 'release-service-sid-unrestricted' `
        ($null -ne $document -and [string]$document.installed_release_config.service_sid_type -ceq 'unrestricted') `
        $(if ($null -eq $document) { 'missing' } else { [string]$document.installed_release_config.service_sid_type }) `
        'unrestricted' 'STATE.json'
}

function Test-TbxDatabaseAndHealth {
    param(
        [Parameter(Mandatory = $true)][object]$Checks,
        [Parameter(Mandatory = $true)][object]$State
    )
    $db = $State.database
    Add-TbxValidationCheck $Checks 'database-query-ready' ([bool]$db.available) ([bool]$db.available) $true 'STATE.json'
    Add-TbxValidationCheck $Checks 'database-system-identifier' `
        ([string]$db.system_identifier -match '^\d{18,20}$') `
        ([string]$db.system_identifier) '18-20 digit cluster ID' 'pg-controldata.stdout.log'
    Add-TbxValidationCheck $Checks 'database-schema-revision' `
        ([string]$db.schema.alembic_version -ceq '20260809_0001') `
        ([string]$db.schema.alembic_version) '20260809_0001' 'database-schema-safe.stdout.log'
    Add-TbxValidationCheck $Checks 'database-public-tables' `
        ([int]$db.schema.public_table_count -gt 0) ([int]$db.schema.public_table_count) `
        'greater than zero' 'database-schema-safe.stdout.log'
    Add-TbxValidationCheck $Checks 'database-app-meta' `
        ([string]$db.schema.app_meta_table -ceq 'true') ([string]$db.schema.app_meta_table) `
        'true' 'database-schema-safe.stdout.log'
    $basic = $State.health.'/api/health'
    $installation = $State.health.'/api/health/installation'
    Add-TbxValidationCheck $Checks 'backend-health' `
        ($null -ne $basic -and [int]$basic.status_code -eq 200 -and [string]$basic.body.status -ceq 'ok') `
        $(if ($null -eq $basic) { 'missing' } else { [int]$basic.status_code }) `
        'HTTP 200, status ok' 'STATE.json'
    Add-TbxValidationCheck $Checks 'installation-health-v2' `
        ($null -ne $installation -and [int]$installation.status_code -eq 200 -and
            [string]$installation.body.contract -ceq 'ticketbox-installation-health-v2' -and
            [string]$installation.body.status -ceq 'ok' -and
            [string]$installation.body.backend_version -ceq '1.2.0' -and
            [string]$installation.body.runtime_access_state -ceq 'available' -and
            [string]$installation.body.owner_state -ceq 'configured') `
        $(if ($null -eq $installation) { 'missing' } else { [int]$installation.status_code }) `
        'HTTP 200, v2, available, configured' 'STATE.json'
    Add-TbxValidationCheck $Checks 'health-installation-id-matches-ready' `
        ($null -ne $installation -and [string]$installation.body.installation_id -ceq [string]$State.ready_identity.values.INSTALLATION_ID) `
        $(if ($null -eq $installation) { 'missing' } else { [string]$installation.body.installation_id }) `
        ([string]$State.ready_identity.values.INSTALLATION_ID) 'STATE.json'
}

function Test-TbxInstalledArtifacts {
    param([Parameter(Mandatory = $true)][object]$Checks, [Parameter(Mandatory = $true)][object]$State)
    $expected = [ordered]@{
        'installer\windows-release-config.json' = 'C81F99DB2E15B3FB638C218C8DB9A448D2FBA6A1C33EA2AD9799F44F77B816E3'
        'installer\BUILD_PROVENANCE.json' = 'D2FAD5223D0ECEC7D363854A83841CF62635E5693DEBF3A5FC9D2BE5682B1701'
        'program\ticketbox-backend\BUILD_PROVENANCE.json' = '0808602B619C16F42A1E7F62FCF1C2AED96D84BCB04C970A6726C56A9A939EF0'
        'program\ticketbox-backend\ticketbox-backend.exe' = '13A9B9152B07C504FE44C6B177300ECD518D7702DA085BE64FEAF0916F447313'
        'program\ticketbox-backend\ticketbox-c07-migrator.exe' = 'B2AC1AE9FF97B77EF2EC9BE84F7ABFD5BD509D46D1E286A819C640D37E54917C'
        'manager\BUILD_PROVENANCE.json' = '69FA81C25F188A7C468A5840CEF57A395BBBB142D90BCB5CE777F983B4B2DE7F'
        'manager\ticketbox-manager.exe' = 'B65693227583FAF272F9B8D5B925D607FD8B6FDF4E8125F77BCBA5B6245FBE5D'
        'shawl\shawl.exe' = '0985555B71E7F943B8F3FC639952A9890AA62E66617942A2D0996985FE8E7C6D'
        'pg\bin\pg_ctl.exe' = '9E1C3375F47116EEF8D04C1F67CC79F03C7C3CCA99172511C4464CB9C6B8116F'
        'pg\bin\postgres.exe' = 'DB14DDB0EFC10B72B57DC29DBCE5A719E2755DCD0AE54297D0EA4BBFC75F79A0'
        'pg\bin\psql.exe' = 'E0113742A0520185E6DCAF90DAFBFD15B02633218D311715F3400613C206D1DC'
    }
    foreach ($suffix in $expected.Keys) {
        $artifact = Get-TbxArtifactFromState $State $suffix
        Add-TbxValidationCheck $Checks ("installed-" + ($suffix -replace '[\\.]', '-')) `
            ($null -ne $artifact -and [string]$artifact.sha256 -ceq [string]$expected[$suffix]) `
            $(if ($null -eq $artifact) { 'missing' } else { [string]$artifact.sha256 }) `
            ([string]$expected[$suffix]) 'STATE.json'
    }
}

function Invoke-TbxFinalValidation {
    param(
        [Parameter(Mandatory = $true)][string]$Scenario,
        [Parameter(Mandatory = $true)][object]$State,
        [Parameter(Mandatory = $true)][string]$StateDirectory,
        [Parameter(Mandatory = $true)][object]$InstallerResult,
        [Parameter(Mandatory = $true)][object]$ManagerProof,
        [Parameter(Mandatory = $true)][object]$StandardUserEvidence,
        [AllowNull()][object]$ServiceLifecycleProof,
        [Parameter(Mandatory = $true)][string]$InstallerPath,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [string]$ExpectedOperationId = '',
        [string]$InterruptedSystemIdentifier = ''
    )
    $checks = New-Object System.Collections.ArrayList
    Add-TbxValidationCheck $checks 'installer-exit-zero' ([int]$InstallerResult.exit_code -eq 0) `
        ([int]$InstallerResult.exit_code) 0 'installer UI receipt'
    Add-TbxValidationCheck $checks 'accepted-exe-unchanged' `
        ((Get-TbxSha256 $InstallerPath) -ceq '5A66B8259CAE1E39814FC693D70FCFAEE58D06CE4CBA9005BEC8CB28E936B28F') `
        (Get-TbxSha256 $InstallerPath) `
        '5A66B8259CAE1E39814FC693D70FCFAEE58D06CE4CBA9005BEC8CB28E936B28F' `
        'accepted artifact'
    Test-TbxLifecycleContract -Checks $checks -State $State -ExpectedOperationId $ExpectedOperationId
    Test-TbxServiceContract -Checks $checks -State $State -StateDirectory $StateDirectory -Name 'TicketboxPg'
    Test-TbxServiceContract -Checks $checks -State $State -StateDirectory $StateDirectory -Name 'TicketboxBackend'
    Test-TbxDatabaseAndHealth -Checks $checks -State $State
    Test-TbxInstalledArtifacts -Checks $checks -State $State
    Add-TbxValidationCheck $checks 'standard-user-not-admin' `
        (-not [bool]$StandardUserEvidence.administrators_member) `
        ([bool]$StandardUserEvidence.administrators_member) $false 'STANDARD_USER.json'
    Add-TbxValidationCheck $checks 'manager-window-launched' `
        ([int]$ManagerProof.window_handle -gt 0) ([int]$ManagerProof.window_handle) `
        'greater than zero' 'manager-gui-proof.json'
    Add-TbxValidationCheck $checks 'manager-pairing-completed' `
        ([bool]$ManagerProof.pairing_completed) ([bool]$ManagerProof.pairing_completed) `
        $true 'manager-gui-proof.json'
    Add-TbxValidationCheck $checks 'manager-code-not-persisted' `
        (-not [bool]$ManagerProof.pairing_code_persisted) ([bool]$ManagerProof.pairing_code_persisted) `
        $false 'manager-gui-proof.json'
    Add-TbxValidationCheck $checks 'manager-screenshot-after-code-clear' `
        ([bool]$ManagerProof.screenshot_saved_after_code_cleared) `
        ([bool]$ManagerProof.screenshot_saved_after_code_cleared) $true 'manager-after-pairing.png'
    if ($Scenario -ceq 'first-install') {
        Add-TbxValidationCheck $checks 'scm-stop-start-lifecycle' `
            ($null -ne $ServiceLifecycleProof -and [string]$ServiceLifecycleProof.status -ceq 'PASS') `
            $(if ($null -eq $ServiceLifecycleProof) { 'missing' } else { [string]$ServiceLifecycleProof.status }) `
            'PASS' 'service-lifecycle/SCM_LIFECYCLE_PROOF.json'
    }
    $sensitiveNames = @(
        'owner-bootstrap.txt', 'owner-handoff-pending',
        'installation-owner-handoff-v2.txt', 'bootstrap-exposure-recovery-pending',
        'installer-runtime-recovery-pending'
    )
    $residue = @($State.installer_state_inventory | Where-Object {
        $sensitiveNames -contains [string]$_.name
    } | ForEach-Object { [string]$_.name })
    Add-TbxValidationCheck $checks 'temporary-sensitive-material-consumed' `
        ($residue.Count -eq 0) $residue @() 'STATE.json'
    if ($InterruptedSystemIdentifier) {
        Add-TbxValidationCheck $checks 'retry-preserved-database-cluster' `
            ([string]$State.database.system_identifier -ceq $InterruptedSystemIdentifier) `
            ([string]$State.database.system_identifier) $InterruptedSystemIdentifier `
            'after-interruption/STATE.json and final/STATE.json'
    }
    $failed = @($checks | Where-Object { -not [bool]$_.passed })
    $validation = [ordered]@{
        schema = 'ticketbox-clean-windows-e2e-validation-v1'
        scenario = $Scenario
        validated_at_utc = [DateTime]::UtcNow.ToString('o')
        status = if ($failed.Count -eq 0) { 'PASS' } else { 'FAIL' }
        check_count = $checks.Count
        failed_check_count = $failed.Count
        checks = @($checks)
    }
    Write-TbxJson $validation $OutputPath -Depth 16
    if ($failed.Count -ne 0) {
        throw ('Final E2E validation failed: ' + (($failed | ForEach-Object { $_.name }) -join ', '))
    }
    return $validation
}
