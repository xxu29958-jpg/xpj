#Requires -Version 5.1

function Get-TicketboxDatabaseGenerationStateRoot {
    param([Parameter(Mandatory = $true)][string]$InstallerState)
    return Join-Path $InstallerState $script:TicketboxDatabaseGenerationRootName
}

function Initialize-TicketboxDatabaseGenerationStateRoot {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Initialize-TicketboxInstallerStateDirectory -Path $InstallerState | Out-Null
    $root = Get-TicketboxDatabaseGenerationStateRoot $InstallerState
    return Initialize-TicketboxInstallerStateDirectory -Path $root
}

function Get-TicketboxDatabaseGenerationArtifactPath {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][ValidateSet(
            "credentials",
            "runtime-credentials",
            "source-create-attempt",
            "restored-source",
            "candidate-verification",
            "runtime-verification",
            "source-binding",
            "target-recovery-attempt",
            "target-recovery-archive",
            "target-recovery-binding",
            "target-recovery-verification",
            "target-recovery-proof",
            "target-authorization",
            "terminal-state",
            "candidate"
        )][string]$Kind,
        [Parameter(Mandatory = $true)][string]$OperationId
    )
    $canonicalOperationId = ([guid]$OperationId).ToString("D")
    return Join-Path $StateRoot "operation-$canonicalOperationId-$Kind.json"
}

function Get-TicketboxDatabaseGenerationPayloadProperties {
    param([Parameter(Mandatory = $true)][string]$Kind)
    switch ($Kind) {
        "intent" {
            return @(
                "schema", "operation_id", "installation_id",
                "expected_predecessor_sha256", "source_request_sha256",
                "target_backend_version",
                "database_maintenance_helper_relative_path", "database_maintenance_helper_size",
                "database_maintenance_helper_sha256", "generation_program_relative_path",
                "generation_program_size", "generation_program_sha256",
                "host_contract_sha256", "projection_contract_sha256",
                "target_revision"
            )
        }
        "credentials" {
            return @(
                "schema", "operation_id", "intent_sha256", "runtime_password",
                "runtime_scram_salt", "migrator_password", "migrator_scram_salt",
                "backup_password", "backup_scram_salt"
            )
        }
        "runtime-credentials" {
            return @(
                "schema", "operation_id", "intent_sha256", "candidate_sha256",
                "runtime_password", "backup_password", "http_bootstrap_secret"
            )
        }
        "source-create-attempt" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "cluster_system_identifier", "database_name",
                "temporary_database", "observed_target_absent"
            )
        }
        "restored-source" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_request_sha256", "predecessor_current_sha256",
                "backup_manifest_sha256", "backup_id", "dataset_id",
                "restore_epoch", "source_revision",
                "cluster_system_identifier", "database_oid",
                "writer_fence_sha256", "result"
            )
        }
        "candidate-verification" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_request_sha256", "restored_source_sha256",
                "backup_manifest_sha256", "backup_id", "dataset_id",
                "restore_epoch", "target_revision", "original_count",
                "generation_program_sha256", "resource_shape_sha256",
                "money_facts_sha256", "result"
            )
        }
        "runtime-verification" {
            return @(
                "schema", "operation_id", "intent_sha256", "source_request_sha256",
                "current_sha256", "backup_manifest_sha256", "backup_id", "dataset_id",
                "restore_epoch", "original_count", "health_contract", "result"
            )
        }
        "dataset-restore-result" {
            return @(
                "schema", "restore_attempt_id", "request_sha256",
                "release_manifest_sha256", "backup_generation", "backup_id",
                "dataset_id", "restore_epoch", "generation_operation_id",
                "current_sha256", "result"
            )
        }
        "source-binding" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_evidence_sha256", "source_kind", "source_revision",
                "cluster_system_identifier", "database_oid", "writer_fence_sha256"
            )
        }
        "target-recovery-attempt" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_binding_sha256", "target_revision",
                "generation_program_sha256", "create_attempt_id",
                "restore_database", "source_cluster_system_identifier",
                "source_database_oid"
            )
        }
        "target-recovery-archive" {
            return @(
                "schema", "operation_id", "attempt_sha256",
                "archive_file_name", "archive_size", "archive_sha256",
                "pg_dump_sha256", "pg_restore_sha256"
            )
        }
        "target-recovery-binding" {
            return @(
                "schema", "operation_id", "attempt_sha256",
                "restore_database", "restore_database_oid", "marker"
            )
        }
        "target-recovery-verification" {
            return @(
                "schema", "operation_id", "attempt_sha256",
                "binding_sha256", "archive_sha256", "live_result_sha256",
                "restored_result_sha256", "target_revision",
                "generation_program_sha256", "resource_shape_sha256",
                "money_facts_sha256"
            )
        }
        "target-recovery-proof" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_binding_sha256", "target_revision",
                "generation_program_sha256", "attempt_sha256",
                "archive_sha256", "verification_sha256",
                "restore_database_oid", "cleanup_state", "result"
            )
        }
        "target-authorization" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_binding_sha256", "target_revision",
                "execution_authority_sha256", "role_authority_sha256",
                "runtime_acl_sha256", "post_migration_writer_fence_sha256",
                "target_recovery_evidence_sha256", "database_binding_sha256",
                "dataset_id", "restore_epoch", "schema_revision"
            )
        }
        "candidate" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "source_binding_sha256", "target_authorization_sha256",
                "database_binding_sha256", "target_revision",
                "generation_program_sha256"
            )
        }
        "terminal-state" {
            return @(
                "schema", "operation_id", "intent_sha256", "candidate_sha256",
                "runtime_credentials_sha256", "bootstrap_retirement_sha256",
                 "runtime_projection_sha256", "host_contract_sha256",
                 "projection_contract_sha256", "transient_credentials_state",
                 "bootstrap_recovery_state", "maintenance_service_transition_state"
            )
        }
        "current" {
            return @(
                "schema", "operation_id", "installation_id", "intent_sha256",
                "candidate_sha256", "committed_revision",
                "generation_program_sha256", "database_binding_sha256",
                "terminal_state_sha256", "expected_predecessor_sha256"
            )
        }
        default { throw "unknown database generation payload kind: $Kind" }
    }
}

function Read-TicketboxDatabaseGenerationEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedKind,
        [string[]]$ReadExecuteAccounts = @(),
        [switch]$AllowAbsent
    )
    $kind = Get-TicketboxPathEntryKindNoFollow $Path
    if ($kind -ceq "Missing" -and $AllowAbsent) { return $null }
    if ($kind -cne "File") {
        throw "database generation artifact 不是受保护普通文件：$Path"
    }
    $artifact = Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts $ReadExecuteAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    try { $envelope = $artifact.Text | ConvertFrom-Json }
    catch { throw "database generation artifact 不是有效 JSON：$Path" }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $envelope @("kind", "payload", "payload_sha256", "schema") "database generation envelope"
    if (
        [string]$envelope.schema -cne "ticketbox-database-generation-envelope-v1" -or
        [string]$envelope.kind -cne $ExpectedKind
    ) {
        throw "database generation artifact kind/schema 漂移：$Path"
    }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $envelope.payload `
        (Get-TicketboxDatabaseGenerationPayloadProperties $ExpectedKind) `
        "database generation $ExpectedKind payload"
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope.payload
    $payloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
    if (
        [string]$envelope.payload_sha256 -cne $payloadSha256 -or
        $artifact.Text -cne (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope)
    ) {
        throw "database generation artifact canonical payload/digest 漂移：$Path"
    }
    return [pscustomobject]@{
        Kind = $ExpectedKind
        Path = $Path
        Payload = $envelope.payload
        PayloadSha256 = $payloadSha256
    }
}

function New-TicketboxDatabaseGenerationEnvelopeText {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][object]$Payload
    )
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $Payload
    try { $closedPayload = $payloadJson | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "database generation $Kind payload 不是 canonical JSON。" }
    Assert-TicketboxDatabaseGenerationExactProperties `
        $closedPayload `
        (Get-TicketboxDatabaseGenerationPayloadProperties $Kind) `
        "database generation $Kind payload"
    $payloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
    $envelope = [ordered]@{
        schema = "ticketbox-database-generation-envelope-v1"
        kind = $Kind
        payload_sha256 = $payloadSha256
        payload = $Payload
    }
    return ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope
}

function New-TicketboxDatabaseGenerationActiveIntent {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Join-Path $StateRoot $script:TicketboxDatabaseGenerationActiveIntentName
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text (New-TicketboxDatabaseGenerationEnvelopeText "intent" $Payload) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    return Read-TicketboxDatabaseGenerationEnvelope $path "intent"
}

function Replace-TicketboxDatabaseGenerationActiveIntent {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedPayloadSha256,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    Assert-TicketboxDatabaseGenerationLowerSha256 `
        $ExpectedPayloadSha256 "database generation active intent CAS predecessor"
    $path = Join-Path $StateRoot $script:TicketboxDatabaseGenerationActiveIntentName
    $existing = Read-TicketboxDatabaseGenerationEnvelope $path "intent"
    if ([string]$existing.PayloadSha256 -cne $ExpectedPayloadSha256) {
        throw "database generation active intent CAS predecessor changed."
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (New-TicketboxDatabaseGenerationEnvelopeText "intent" $Payload) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount `
        -ReplaceExisting
    return Read-TicketboxDatabaseGenerationEnvelope $path "intent"
}

function Read-TicketboxDatabaseGenerationOperationArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][ValidateSet(
            "credentials",
            "runtime-credentials",
            "source-create-attempt",
            "restored-source",
            "candidate-verification",
            "runtime-verification",
            "source-binding",
            "target-recovery-attempt",
            "target-recovery-archive",
            "target-recovery-binding",
            "target-recovery-verification",
            "target-recovery-proof",
            "target-authorization",
            "terminal-state",
            "candidate"
        )][string]$Kind,
        [switch]$AllowAbsent
    )
    $path = Get-TicketboxDatabaseGenerationArtifactPath $StateRoot $Kind $OperationId
    return Read-TicketboxDatabaseGenerationEnvelope `
        -Path $path `
        -ExpectedKind $Kind `
        -AllowAbsent:$AllowAbsent
}

function Read-TicketboxDatabaseGenerationCurrent {
    param([switch]$AllowAbsent)
    return Read-TicketboxDatabaseGenerationEnvelope `
        -Path (Get-TicketboxDatabaseGenerationRuntimeCurrentPath) `
        -ExpectedKind "current" `
        -ReadExecuteAccounts @($script:TicketboxDatabaseGenerationRuntimeAccount) `
        -AllowAbsent:$AllowAbsent
}

function New-TicketboxDatabaseGenerationChainedArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][ValidateSet(
            "credentials", "runtime-credentials", "source-create-attempt", "restored-source",
            "candidate-verification", "runtime-verification", "source-binding",
            "target-authorization", "candidate", "terminal-state",
            "target-recovery-attempt", "target-recovery-archive",
            "target-recovery-binding", "target-recovery-verification",
            "target-recovery-proof"
        )][string]$Kind,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Get-TicketboxDatabaseGenerationArtifactPath $StateRoot $Kind $OperationId
    $existing = Read-TicketboxDatabaseGenerationEnvelope $path $Kind -AllowAbsent
    if ($null -ne $existing) {
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $Payload)
        ) {
            throw "existing database generation $Kind 与 live evidence 漂移。"
        }
        return $existing
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (New-TicketboxDatabaseGenerationEnvelopeText $Kind $Payload) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    return Read-TicketboxDatabaseGenerationEnvelope $path $Kind
}

function New-TicketboxDatabaseGenerationCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$SourceBinding,
        [Parameter(Mandatory = $true)][object]$TargetAuthorization,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-candidate-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        source_binding_sha256 = [string]$SourceBinding.PayloadSha256
        target_authorization_sha256 = [string]$TargetAuthorization.PayloadSha256
        database_binding_sha256 =
            [string]$TargetAuthorization.Payload.database_binding_sha256
        target_revision = [string]$Intent.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
    }
    return New-TicketboxDatabaseGenerationChainedArtifact `
        $StateRoot ([string]$Intent.Payload.operation_id) `
        "candidate" $payload $LifecycleLock
}

function New-TicketboxDatabaseGenerationTerminalState {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$RuntimeCredentials,
        [Parameter(Mandatory = $true)][object]$RuntimeProjection,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    if (
        [string]$Candidate.Payload.intent_sha256 -cne [string]$Intent.PayloadSha256 -or
        [string]$RuntimeCredentials.Artifact.Payload.intent_sha256 -cne
            [string]$Intent.PayloadSha256 -or
        [string]$RuntimeCredentials.Artifact.Payload.candidate_sha256 -cne
            [string]$Candidate.PayloadSha256 -or
        [string]$RuntimeProjection.Payload.operation_id -cne
            [string]$Intent.Payload.operation_id -or
        [string]$RuntimeProjection.Payload.candidate_sha256 -cne
            [string]$Candidate.PayloadSha256 -or
        [string]$RuntimeProjection.Payload.host_contract_sha256 -cne
            [string]$Intent.Payload.host_contract_sha256 -or
        [string]$RuntimeProjection.Payload.projection_contract_sha256 -cne
            [string]$Intent.Payload.projection_contract_sha256
    ) {
        throw "terminal state 拒绝不完整的 candidate/runtime authority chain。"
    }
    $payload = [ordered]@{
        schema = "ticketbox-database-generation-terminal-state-v1"
        operation_id = [string]$Intent.Payload.operation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        candidate_sha256 = [string]$Candidate.PayloadSha256
        runtime_credentials_sha256 =
            [string]$RuntimeCredentials.Artifact.PayloadSha256
        bootstrap_retirement_sha256 = Get-TicketboxDatabaseGenerationTextSha256 (
            Get-TicketboxDatabaseGenerationBootstrapRetirementJson $Intent $Candidate
        )
        runtime_projection_sha256 = [string]$RuntimeProjection.PayloadSha256
        host_contract_sha256 = [string]$Intent.Payload.host_contract_sha256
        projection_contract_sha256 =
            [string]$Intent.Payload.projection_contract_sha256
        transient_credentials_state = "absent"
        bootstrap_recovery_state = "absent"
        maintenance_service_transition_state = "absent"
    }
    return New-TicketboxDatabaseGenerationChainedArtifact `
        $StateRoot ([string]$Intent.Payload.operation_id) `
        "terminal-state" $payload $LifecycleLock
}

function Read-TicketboxDatabaseGenerationActiveIntent {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [switch]$AllowAbsent
    )
    return Read-TicketboxDatabaseGenerationEnvelope `
        -Path (Join-Path `
            $StateRoot `
            $script:TicketboxDatabaseGenerationActiveIntentName) `
        -ExpectedKind "intent" `
        -AllowAbsent:$AllowAbsent
}
