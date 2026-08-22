#Requires -Version 5.1

function Get-TicketboxDatabaseGenerationProspectiveCurrent {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$TerminalState
    )
    if (
        [string]$Candidate.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$TerminalState.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$TerminalState.Payload.candidate_sha256 -cne [string]$Candidate.PayloadSha256 -or
        [string]$TerminalState.Payload.host_contract_sha256 -cne
            [string]$Intent.Payload.host_contract_sha256 -or
        [string]$TerminalState.Payload.projection_contract_sha256 -cne
            [string]$Intent.Payload.projection_contract_sha256
    ) {
        throw "database generation CURRENT 输入 authority chain 漂移。"
    }
    foreach ($digest in @(
        [string]$Intent.PayloadSha256,
        [string]$Candidate.PayloadSha256,
        [string]$Candidate.Payload.database_binding_sha256,
        [string]$TerminalState.PayloadSha256,
        [string]$TerminalState.Payload.runtime_credentials_sha256,
        [string]$TerminalState.Payload.bootstrap_retirement_sha256,
        [string]$TerminalState.Payload.runtime_projection_sha256,
        [string]$TerminalState.Payload.host_contract_sha256,
        [string]$TerminalState.Payload.projection_contract_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 $digest "CURRENT authority binding"
    }
    if (
        [string]$TerminalState.Payload.transient_credentials_state -cne "absent" -or
        [string]$TerminalState.Payload.bootstrap_recovery_state -cne "absent" -or
        [string]$TerminalState.Payload.maintenance_service_transition_state -cne "absent"
    ) {
        throw "database generation CURRENT 拒绝未完成 cleanup 的 terminal state。"
    }
    $payload = [ordered]@{
        schema = "ticketbox-current-database-generation-v1"
        operation_id = [string]$Intent.Payload.operation_id
        installation_id = [string]$Intent.Payload.installation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        candidate_sha256 = [string]$Candidate.PayloadSha256
        committed_revision = [string]$Candidate.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        database_binding_sha256 = [string]$Candidate.Payload.database_binding_sha256
        terminal_state_sha256 = [string]$TerminalState.PayloadSha256
        expected_predecessor_sha256 = [string]$Intent.Payload.expected_predecessor_sha256
    }
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload
    return [pscustomobject]@{
        Path = Get-TicketboxDatabaseGenerationRuntimeCurrentPath
        Payload = [pscustomobject]$payload
        PayloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
    }
}

function New-TicketboxDatabaseGenerationAdvanceCurrentTransition {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$TerminalState
    )
    $proposed = Get-TicketboxDatabaseGenerationProspectiveCurrent `
        $Intent $Candidate $TerminalState
    return [pscustomobject][ordered]@{
        schema = "ticketbox-database-generation-current-transition-v1"
        mode = "advance"
        expected_current_sha256 = [string]$Intent.Payload.expected_predecessor_sha256
        target_payload_sha256 = [string]$proposed.PayloadSha256
        target_payload = $proposed.Payload
    }
}

function Assert-TicketboxDatabaseGenerationCurrentTransition {
    param([Parameter(Mandatory = $true)][object]$Transition)
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Transition `
        -ExpectedNames @(
            "schema", "mode", "expected_current_sha256",
            "target_payload_sha256", "target_payload"
        ) `
        -Label "database generation CURRENT transition"
    if (
        [string]$Transition.schema -cne
            "ticketbox-database-generation-current-transition-v1" -or
        [string]$Transition.mode -cnotin @("advance", "restore_predecessor")
    ) {
        throw "database generation CURRENT transition is not closed."
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Transition.target_payload `
        -ExpectedNames (Get-TicketboxDatabaseGenerationPayloadProperties "current") `
        -Label "database generation CURRENT transition target"
    $targetSha256 = Get-TicketboxDatabaseGenerationTextSha256 (
        ConvertTo-TicketboxDatabaseGenerationCanonicalJson $Transition.target_payload
    )
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        ([string]$Transition.target_payload_sha256) `
        "database generation CURRENT transition target"
    if ($targetSha256 -cne [string]$Transition.target_payload_sha256) {
        throw "database generation CURRENT transition target digest changed."
    }
    $expected = [string]$Transition.expected_current_sha256
    if (-not [string]::IsNullOrEmpty($expected)) {
        Assert-TicketboxDatabaseGenerationLowerSha256 `
            $expected "database generation CURRENT transition predecessor"
    }
    if (
        [string]$Transition.mode -ceq "advance" -and
        [string]$Transition.target_payload.expected_predecessor_sha256 -cne $expected
    ) {
        throw "database generation advance transition lost its predecessor binding."
    }
    if (
        [string]$Transition.mode -ceq "restore_predecessor" -and
        [string]::IsNullOrEmpty($expected)
    ) {
        throw "database generation predecessor restoration requires exact CURRENT CAS."
    }
    return $Transition
}

function Publish-TicketboxDatabaseGenerationCurrent {
    param(
        [Parameter(Mandatory = $true)][object]$Transition,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $validated = Assert-TicketboxDatabaseGenerationCurrentTransition $Transition
    $existing = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
    if ($null -ne $existing) {
        if (
            [string]$existing.PayloadSha256 -ceq
                [string]$validated.target_payload_sha256
        ) { return $existing }
        if (
            [string]::IsNullOrEmpty([string]$validated.expected_current_sha256) -or
            [string]$existing.PayloadSha256 -cne
                [string]$validated.expected_current_sha256
        ) {
            throw "database generation current CAS predecessor/current 冲突。"
        }
        if (
            [string]$validated.mode -ceq "restore_predecessor" -and
            [string]$existing.Payload.expected_predecessor_sha256 -cne
                [string]$validated.target_payload_sha256
        ) {
            throw "database generation CURRENT rollback target is not its predecessor."
        }
    }
    elseif (-not [string]::IsNullOrEmpty([string]$validated.expected_current_sha256)) {
        throw "database generation current CAS predecessor 缺失。"
    }
    elseif ([string]$validated.mode -ceq "restore_predecessor") {
        throw "database generation predecessor restoration lacks CURRENT."
    }
    $path = Get-TicketboxDatabaseGenerationRuntimeCurrentPath
    $runtimeRoot = Split-Path -Parent $path
    [void](Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $runtimeRoot `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($script:TicketboxDatabaseGenerationRuntimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount)
    $envelope = [ordered]@{
        schema = "ticketbox-database-generation-envelope-v1"
        kind = "current"
        payload_sha256 = [string]$validated.target_payload_sha256
        payload = $validated.target_payload
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($script:TicketboxDatabaseGenerationRuntimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount `
        -ReplaceExisting:($null -ne $existing)
    return Read-TicketboxDatabaseGenerationCurrent
}
