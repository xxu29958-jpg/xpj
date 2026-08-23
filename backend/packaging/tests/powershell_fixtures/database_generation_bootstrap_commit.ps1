# Exact empty-source commit chain used by the bootstrap-closure contract.

#Requires -Version 5.1

function New-TicketboxBootstrapCommitFixtureArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Sha256,
        [Parameter(Mandatory = $true)][hashtable]$Payload
    )
    return [pscustomobject]@{
        PayloadSha256 = $Sha256
        Payload = [pscustomobject]$Payload
    }
}

$commitIntent = $script:CommitFixtureIntent
$commitStateRoot = $script:CommitFixtureStateRoot
$commitOperation = [string]$commitIntent.Payload.operation_id
$commitAttemptId = "22222222-2222-4222-8222-222222222222"
$commitRestoreDatabase = "ticketbox_generation_restore_" + (
    ([guid]$commitAttemptId).ToString("N")
)
$commitSourceEvidence = New-TicketboxBootstrapCommitFixtureArtifact `
    ("2" * 64) @{
        schema = "ticketbox-database-generation-source-create-attempt-v1"
        operation_id = $commitOperation
        intent_sha256 = [string]$commitIntent.PayloadSha256
        cluster_system_identifier = "7612345678901234567"
        database_name = "ticketbox"
        temporary_database = "ticketbox_generation_" + (
            ([guid]$commitOperation).ToString("N")
        )
        observed_target_absent = $true
    }
$commitSource = New-TicketboxBootstrapCommitFixtureArtifact ("3" * 64) @{
    schema = "ticketbox-database-generation-source-binding-v1"
    operation_id = $commitOperation
    intent_sha256 = [string]$commitIntent.PayloadSha256
    source_evidence_sha256 = [string]$commitSourceEvidence.PayloadSha256
    source_kind = "empty"
    source_revision = "base"
    cluster_system_identifier = "7612345678901234567"
    database_oid = [uint32]16384
    writer_fence_sha256 = ("4" * 64)
}
$commitAttempt = New-TicketboxBootstrapCommitFixtureArtifact ("7" * 64) @{
    operation_id = $commitOperation
    create_attempt_id = $commitAttemptId
    intent_sha256 = [string]$commitIntent.PayloadSha256
    target_revision = [string]$commitIntent.Payload.target_revision
    generation_program_sha256 = [string]$commitIntent.Payload.generation_program_sha256
    source_binding_sha256 = [string]$commitSource.PayloadSha256
    source_cluster_system_identifier = [string]$commitSource.Payload.cluster_system_identifier
    source_database_oid = [string]$commitSource.Payload.database_oid
    restore_database = $commitRestoreDatabase
}
$commitArchive = New-TicketboxBootstrapCommitFixtureArtifact ("9" * 64) @{
    operation_id = $commitOperation
    attempt_sha256 = [string]$commitAttempt.PayloadSha256
    archive_sha256 = ("8" * 64)
}
$commitBinding = New-TicketboxBootstrapCommitFixtureArtifact ("a" * 64) @{
    operation_id = $commitOperation
    attempt_sha256 = [string]$commitAttempt.PayloadSha256
    restore_database = $commitRestoreDatabase
    restore_database_oid = "42"
}
$commitVerification = New-TicketboxBootstrapCommitFixtureArtifact ("b" * 64) @{
    operation_id = $commitOperation
    attempt_sha256 = [string]$commitAttempt.PayloadSha256
    binding_sha256 = [string]$commitBinding.PayloadSha256
    archive_sha256 = [string]$commitArchive.Payload.archive_sha256
    target_revision = [string]$commitIntent.Payload.target_revision
    generation_program_sha256 = [string]$commitIntent.Payload.generation_program_sha256
}
$commitProof = New-TicketboxBootstrapCommitFixtureArtifact ("6" * 64) @{
    operation_id = $commitOperation
    intent_sha256 = [string]$commitIntent.PayloadSha256
    source_binding_sha256 = [string]$commitSource.PayloadSha256
    target_revision = [string]$commitIntent.Payload.target_revision
    generation_program_sha256 = [string]$commitIntent.Payload.generation_program_sha256
    attempt_sha256 = [string]$commitAttempt.PayloadSha256
    archive_sha256 = [string]$commitArchive.Payload.archive_sha256
    verification_sha256 = [string]$commitVerification.PayloadSha256
    restore_database_oid = [string]$commitBinding.Payload.restore_database_oid
    cleanup_state = "restore_database_absent"
    result = "isolated_restore_verified"
}
$commitTarget = New-TicketboxBootstrapCommitFixtureArtifact ("5" * 64) @{
    intent_sha256 = [string]$commitIntent.PayloadSha256
    source_binding_sha256 = [string]$commitSource.PayloadSha256
    target_recovery_evidence_sha256 = [string]$commitProof.PayloadSha256
    database_binding_sha256 = ("0" * 64)
}
$commitCandidate = New-TicketboxBootstrapCommitFixtureArtifact ("c" * 64) @{
    source_binding_sha256 = [string]$commitSource.PayloadSha256
    target_authorization_sha256 = [string]$commitTarget.PayloadSha256
    database_binding_sha256 = [string]$commitTarget.Payload.database_binding_sha256
}
$commitRuntimeCredentials = New-TicketboxBootstrapCommitFixtureArtifact ("e" * 64) @{
    intent_sha256 = [string]$commitIntent.PayloadSha256
    candidate_sha256 = [string]$commitCandidate.PayloadSha256
}
$commitTerminal = New-TicketboxBootstrapCommitFixtureArtifact ("d" * 64) @{
    intent_sha256 = [string]$commitIntent.PayloadSha256
    candidate_sha256 = [string]$commitCandidate.PayloadSha256
    host_contract_sha256 = [string]$commitIntent.Payload.host_contract_sha256
    projection_contract_sha256 = [string]$commitIntent.Payload.projection_contract_sha256
    runtime_credentials_sha256 = [string]$commitRuntimeCredentials.PayloadSha256
    bootstrap_retirement_sha256 = ("1" * 64)
    runtime_projection_sha256 = ("2" * 64)
    transient_credentials_state = "absent"
    bootstrap_recovery_state = "absent"
    maintenance_service_transition_state = "absent"
}
$commitCurrent = New-TicketboxBootstrapCommitFixtureArtifact ("f" * 64) @{
    operation_id = $commitOperation
    intent_sha256 = [string]$commitIntent.PayloadSha256
    candidate_sha256 = [string]$commitCandidate.PayloadSha256
    terminal_state_sha256 = [string]$commitTerminal.PayloadSha256
    database_binding_sha256 = [string]$commitTarget.Payload.database_binding_sha256
    committed_revision = [string]$commitIntent.Payload.target_revision
    generation_program_sha256 = [string]$commitIntent.Payload.generation_program_sha256
}
$script:CommitFixtureArtifacts = @{
    "source-create-attempt" = $commitSourceEvidence
    "source-binding" = $commitSource
    "target-authorization" = $commitTarget
    "target-recovery-proof" = $commitProof
    "target-recovery-attempt" = $commitAttempt
    "target-recovery-archive" = $commitArchive
    "target-recovery-binding" = $commitBinding
    "target-recovery-verification" = $commitVerification
    "candidate" = $commitCandidate
    "terminal-state" = $commitTerminal
    "runtime-credentials" = $commitRuntimeCredentials
}

function Get-TicketboxInstallerStateDirectory { return $script:CommitFixtureStateRoot }
function Get-TicketboxDatabaseGenerationStateRoot { return $script:CommitFixtureStateRoot }
function Read-TicketboxDatabaseGenerationActiveIntent { return $script:CommitFixtureIntent }
function Read-TicketboxDatabaseGenerationOperationArtifact {
    param($StateRoot, $OperationId, $ArtifactKind, [switch]$AllowAbsent)
    if ([string]$OperationId -cne $commitOperation) {
        throw "foreign commit operation lookup"
    }
    if (-not $script:CommitFixtureArtifacts.ContainsKey([string]$ArtifactKind)) {
        if ($AllowAbsent) { return $null }
        throw "missing commit artifact: $ArtifactKind"
    }
    return $script:CommitFixtureArtifacts[[string]$ArtifactKind]
}
function Read-TicketboxDatabaseGenerationCurrent { return $commitCurrent }
function Get-TicketboxDatabaseGenerationArtifactPath {
    return (Join-Path $script:CommitFixtureStateRoot "missing-credentials.json")
}

$verifiedCurrent = Assert-TicketboxDatabaseGenerationCommitReadyArtifact `
    -ExpectedOperationId $commitOperation `
    -ExpectedCurrentSha256 ([string]$commitCurrent.PayloadSha256)
if ([string]$verifiedCurrent.PayloadSha256 -cne [string]$commitCurrent.PayloadSha256) {
    throw "empty-source commit verifier did not close through the bootstrap owner"
}
