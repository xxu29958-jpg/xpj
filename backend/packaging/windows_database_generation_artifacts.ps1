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
            "runtime-credentials",
            "source-create-attempt",
            "restored-source",
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
        "dataset-restore-request" {
            return @(
                "schema", "request_id", "backup_generation",
                "backup_manifest_sha256", "backup_id", "dataset_id",
                "backup_restore_epoch", "target_revision",
                "predecessor_current_sha256", "predecessor_intent_sha256",
                "predecessor_intent_payload", "release_manifest_sha256",
                "active_dataset_id", "active_restore_epoch", "restart_backend"
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
            "runtime-credentials",
            "source-create-attempt",
            "restored-source",
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
            "runtime-credentials", "source-create-attempt", "restored-source",
            "source-binding",
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
    return Write-TicketboxDatabaseGenerationEnvelope `
        $path $Kind $Payload $LifecycleLock
}

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

function Publish-TicketboxDatabaseGenerationCurrent {
    param(
        [Parameter(Mandatory = $true)][object]$Intent,
        [Parameter(Mandatory = $true)][object]$Candidate,
        [Parameter(Mandatory = $true)][object]$TerminalState,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $proposed = Get-TicketboxDatabaseGenerationProspectiveCurrent `
        $Intent $Candidate $TerminalState
    $existing = Read-TicketboxDatabaseGenerationCurrent -AllowAbsent
    if ($null -ne $existing) {
        if (
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $existing.Payload) -cne
            (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $proposed.Payload)
        ) {
            if (
                [string]::IsNullOrEmpty(
                    [string]$Intent.Payload.expected_predecessor_sha256
                ) -or
                [string]$existing.PayloadSha256 -cne
                    [string]$Intent.Payload.expected_predecessor_sha256
            ) {
                throw "database generation current CAS predecessor/current 冲突。"
            }
        }
        else {
            return $existing
        }
    }
    elseif (-not [string]::IsNullOrEmpty(
        [string]$Intent.Payload.expected_predecessor_sha256
    )) {
        throw "database generation current CAS predecessor 缺失。"
    }
    $path = [string]$proposed.Path
    $runtimeRoot = Split-Path -Parent $path
    [void](Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $runtimeRoot `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($script:TicketboxDatabaseGenerationRuntimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount)
    $envelope = [ordered]@{
        schema = "ticketbox-database-generation-envelope-v1"
        kind = "current"
        payload_sha256 = [string]$proposed.PayloadSha256
        payload = $proposed.Payload
    }
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $path `
        -Text (ConvertTo-TicketboxDatabaseGenerationCanonicalJson $envelope) `
        -FullControlAccounts $script:TicketboxDatabaseGenerationAclAccounts `
        -ReadExecuteAccounts @($script:TicketboxDatabaseGenerationRuntimeAccount) `
        -OwnerAccount $script:TicketboxDatabaseGenerationOwnerAccount
    return Read-TicketboxDatabaseGenerationCurrent
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
