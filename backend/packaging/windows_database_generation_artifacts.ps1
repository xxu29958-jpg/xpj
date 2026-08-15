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
    $root = Get-TicketboxDatabaseGenerationStateRoot $InstallerState
    return Initialize-TicketboxInstallerStateDirectory -Path $root
}

function Get-TicketboxDatabaseGenerationArtifactPath {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][ValidateSet(
            "credentials",
            "source-create-attempt",
            "source-binding",
            "target-recovery-attempt",
            "target-recovery-archive",
            "target-recovery-binding",
            "target-recovery-verification",
            "target-recovery-proof",
            "target-authorization",
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
                "expected_predecessor_sha256", "target_backend_version",
                "migration_helper_relative_path", "migration_helper_size",
                "migration_helper_sha256", "generation_program_relative_path",
                "generation_program_size", "generation_program_sha256",
                "host_contract_sha256", "projection_contract_sha256",
                "target_revision"
            )
        }
        "credentials" {
            return @(
                "schema", "operation_id", "intent_sha256", "runtime_password",
                "runtime_scram_salt", "migrator_password", "migrator_scram_salt"
            )
        }
        "source-create-attempt" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "cluster_system_identifier", "database_name",
                "temporary_database", "observed_target_absent"
            )
        }
        "source-binding" {
            return @(
                "schema", "operation_id", "intent_sha256",
                "create_attempt_sha256", "source_kind", "source_revision",
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
                "target_recovery_evidence_sha256", "database_binding_sha256"
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
        "current" {
            return @(
                "schema", "operation_id", "installation_id", "intent_sha256",
                "candidate_sha256", "committed_revision",
                "generation_program_sha256", "database_binding_sha256",
                "expected_predecessor_sha256"
            )
        }
        default { throw "unknown database generation payload kind: $Kind" }
    }
}

function Read-TicketboxDatabaseGenerationEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedKind,
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
        Path = $Path
        Payload = $envelope.payload
        PayloadSha256 = $payloadSha256
    }
}

function Write-TicketboxDatabaseGenerationEnvelope {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $payloadJson = ConvertTo-TicketboxDatabaseGenerationCanonicalJson $Payload
    $payloadSha256 = Get-TicketboxDatabaseGenerationTextSha256 $payloadJson
    $envelope = [ordered]@{
        schema = "ticketbox-database-generation-envelope-v1"
        kind = $Kind
        payload_sha256 = $payloadSha256
        payload = $Payload
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    return Read-TicketboxDatabaseGenerationEnvelope -Path $Path -ExpectedKind $Kind
}

function Read-TicketboxDatabaseGenerationOperationArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][ValidateSet(
            "credentials",
            "source-create-attempt",
            "source-binding",
            "target-recovery-attempt",
            "target-recovery-archive",
            "target-recovery-binding",
            "target-recovery-verification",
            "target-recovery-proof",
            "target-authorization",
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
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [switch]$AllowAbsent
    )
    return Read-TicketboxDatabaseGenerationEnvelope `
        -Path (Join-Path $StateRoot $script:TicketboxDatabaseGenerationCurrentName) `
        -ExpectedKind "current" `
        -AllowAbsent:$AllowAbsent
}

function New-TicketboxDatabaseGenerationChainedArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][ValidateSet(
            "source-create-attempt", "source-binding", "target-authorization", "candidate",
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
    return Write-TicketboxDatabaseGenerationEnvelope `
        $path $Kind $Payload $LifecycleLock
}

function Publish-TicketboxDatabaseGenerationCurrent {
    param(
        [Parameter(Mandatory = $true)][string]$StateRoot,
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $path = Join-Path $StateRoot $script:TicketboxDatabaseGenerationCurrentName
    $existing = Read-TicketboxDatabaseGenerationCurrent $StateRoot -AllowAbsent
    $payload = [ordered]@{
        schema = "ticketbox-current-database-generation-v1"
        operation_id = [string]$Intent.Payload.operation_id
        installation_id = [string]$Intent.Payload.installation_id
        intent_sha256 = [string]$Intent.PayloadSha256
        candidate_sha256 = [string]$Candidate.PayloadSha256
        committed_revision = [string]$Candidate.Payload.target_revision
        generation_program_sha256 = [string]$Intent.Payload.generation_program_sha256
        database_binding_sha256 = [string]$Candidate.Payload.database_binding_sha256
        expected_predecessor_sha256 = [string]$Intent.Payload.expected_predecessor_sha256
    }
    if ($null -ne $existing) {
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $payload)
        ) {
            throw "database generation current CAS predecessor/current 冲突。"
        }
        return $existing
    }
    if (-not [string]::IsNullOrEmpty([string]$Intent.Payload.expected_predecessor_sha256)) {
        throw "empty-source current publish 的 expected predecessor 必须为空。"
    }
    return Write-TicketboxDatabaseGenerationEnvelope `
        $path "current" $payload $LifecycleLock
}

function Assert-TicketboxDatabaseGenerationCommitReadyArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedCurrentSha256
    )
    foreach ($dependency in @(Get-TicketboxDatabaseGenerationExecutionDependencyPaths `
        -Root $PSScriptRoot)) {
        . $dependency
    }
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
    $current = Read-TicketboxDatabaseGenerationCurrent $stateRoot
    [void](Assert-TicketboxDatabaseGenerationRecoveryChain `
        $intent $source $recoveryAttempt $recoveryArchive $recoveryBinding `
        $recoveryVerification $recoveryProof)
    if (
        [string]$current.PayloadSha256 -cne $ExpectedCurrentSha256 -or
        [string]$current.Payload.operation_id -cne $operationId -or
        [string]$current.Payload.intent_sha256 -cne [string]$intent.PayloadSha256 -or
        [string]$current.Payload.candidate_sha256 -cne [string]$candidate.PayloadSha256 -or
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
