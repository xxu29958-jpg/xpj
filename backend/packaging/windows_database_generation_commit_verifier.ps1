#Requires -Version 5.1

function Assert-TicketboxDatabaseGenerationCommitReadyArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedCurrentSha256
    )
    $recoveryEvidencePath = Join-Path `
        $PSScriptRoot `
        "windows_database_generation_recovery_evidence.ps1"
    if ((Get-TicketboxPathEntryKindNoFollow $recoveryEvidencePath) -cne "File") {
        throw "database generation commit verifier dependency 不是可信普通文件：$recoveryEvidencePath"
    }
    Assert-NoTicketboxAncestorReparsePoints $recoveryEvidencePath
    . $recoveryEvidencePath

    $operationId = ([guid]$ExpectedOperationId).ToString("D")
    Assert-TicketboxDatabaseGenerationLowerSha256 $ExpectedCurrentSha256 "commit CURRENT"
    $stateRoot = Get-TicketboxDatabaseGenerationStateRoot (
        Get-TicketboxInstallerStateDirectory
    )
    $intent = Read-TicketboxDatabaseGenerationActiveIntent $stateRoot
    $sourceCreateAttempt = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "source-create-attempt"
    $source = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "source-binding"
    $target = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "target-authorization"
    $recoveryProof = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "target-recovery-proof"
    $recoveryAttempt = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "target-recovery-attempt"
    $recoveryArchive = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "target-recovery-archive"
    $recoveryBinding = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "target-recovery-binding"
    $recoveryVerification = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "target-recovery-verification"
    $candidate = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "candidate"
    $terminalState = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "terminal-state"
    $runtimeCredentials = Read-TicketboxDatabaseGenerationOperationArtifact `
        $stateRoot $operationId "runtime-credentials"
    $current = Read-TicketboxDatabaseGenerationCurrent
    foreach ($digest in @(
        [string]$terminalState.Payload.runtime_credentials_sha256,
        [string]$terminalState.Payload.bootstrap_retirement_sha256,
        [string]$terminalState.Payload.runtime_projection_sha256,
        [string]$terminalState.Payload.host_contract_sha256,
        [string]$terminalState.Payload.projection_contract_sha256
    )) {
        Assert-TicketboxDatabaseGenerationLowerSha256 $digest "terminal state authority binding"
    }
    [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
        $intent $source $recoveryAttempt $recoveryArchive $recoveryBinding `
        $recoveryVerification $recoveryProof)
    if (
        [string]$current.PayloadSha256 -cne $ExpectedCurrentSha256 -or
        [string]$current.Payload.operation_id -cne $operationId -or
        [string]$current.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$current.Payload.candidate_sha256 -cne [string]$candidate.PayloadSha256 -or
        [string]$current.Payload.terminal_state_sha256 -cne
            [string]$terminalState.PayloadSha256 -or
        [string]$terminalState.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$terminalState.Payload.candidate_sha256 -cne
            [string]$candidate.PayloadSha256 -or
        [string]$terminalState.Payload.host_contract_sha256 -cne
            [string]$intent.Payload.host_contract_sha256 -or
        [string]$terminalState.Payload.projection_contract_sha256 -cne
            [string]$intent.Payload.projection_contract_sha256 -or
        [string]$terminalState.Payload.runtime_credentials_sha256 -cne
            [string]$runtimeCredentials.PayloadSha256 -or
        [string]$runtimeCredentials.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$runtimeCredentials.Payload.candidate_sha256 -cne
            [string]$candidate.PayloadSha256 -or
        [string]$terminalState.Payload.transient_credentials_state -cne "absent" -or
        [string]$terminalState.Payload.bootstrap_recovery_state -cne "absent" -or
        [string]$terminalState.Payload.maintenance_service_transition_state -cne "absent" -or
        [string]$candidate.Payload.source_binding_sha256 -cne [string]$source.PayloadSha256 -or
        [string]$candidate.Payload.target_authorization_sha256 -cne [string]$target.PayloadSha256 -or
        [string]$source.Payload.create_attempt_sha256 -cne
            [string]$sourceCreateAttempt.PayloadSha256 -or
        [string]$sourceCreateAttempt.Payload.intent_sha256 -cne
            [string]$intent.PayloadSha256 -or
        [string]$source.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$target.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$target.Payload.source_binding_sha256 -cne [string]$source.PayloadSha256 -or
        [string]$target.Payload.target_recovery_evidence_sha256 -cne
            [string]$recoveryProof.PayloadSha256 -or
        [string]$candidate.Payload.database_binding_sha256 -cne
            [string]$target.Payload.database_binding_sha256 -or
        [string]$current.Payload.database_binding_sha256 -cne
            [string]$target.Payload.database_binding_sha256 -or
        [string]$recoveryProof.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$recoveryProof.Payload.source_binding_sha256 -cne [string]$source.PayloadSha256 -or
        [string]$recoveryProof.Payload.archive_sha256 -cne
            [string]$recoveryArchive.Payload.archive_sha256 -or
        [string]$recoveryProof.Payload.verification_sha256 -cne
            [string]$recoveryVerification.PayloadSha256 -or
        [string]$recoveryProof.Payload.cleanup_state -cne "restore_database_absent" -or
        [string]$recoveryProof.Payload.result -cne "isolated_restore_verified" -or
        [string]$current.Payload.committed_revision -cne [string]$intent.Payload.target_revision -or
        [string]$current.Payload.generation_program_sha256 -cne [string]$intent.Payload.generation_program_sha256
    ) {
        throw "database generation commit authority chain 漂移。"
    }
    $credentialsPath = Get-TicketboxDatabaseGenerationArtifactPath `
        $stateRoot "credentials" $operationId
    if ((Get-TicketboxPathEntryKindNoFollow $credentialsPath) -cne "Missing") {
        throw "database generation commit 前临时 credential 尚未清理。"
    }
    return $current
}
