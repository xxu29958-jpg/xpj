#Requires -Version 5.1

# Closed, IO-free next-action policy for installed dataset restore.

function Get-TicketboxInstalledDatasetRestoreActionBudgetMilliseconds {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "build_candidate", "restore_candidate", "verify_candidate",
            "promote_candidate", "publish_current", "verify_runtime",
            "retire_rollback", "done"
        )][string]$Action,
        [Parameter(Mandatory = $true)][object]$Release,
        [Parameter(Mandatory = $true)][object]$BudgetContract
    )
    $expectedNames = @(
        "candidate_cluster_ms", "candidate_database_ms",
        "database_generation_ms", "schema"
    )
    $actualNames = @($BudgetContract.PSObject.Properties.Name | Sort-Object)
    if (
        [string]$BudgetContract.schema -cne
            "ticketbox-installed-dataset-restore-budget-v1" -or
        ($actualNames -join "|") -cne (($expectedNames | Sort-Object) -join "|")
    ) {
        throw "installed dataset restore budget contract is not closed."
    }
    foreach ($name in @(
        "candidate_cluster_ms", "candidate_database_ms", "database_generation_ms"
    )) {
        $value = $BudgetContract.$name
        if (
            ($value -isnot [int] -and $value -isnot [long]) -or
            [int64]$value -lt 1
        ) {
            throw "installed dataset restore budget contract has an invalid component."
        }
    }
    $service = [int64]$Release.service_state_timeout_ms
    $postgres = [int64]$Release.postgres_ready_timeout_ms
    $stopWriters = $service + $service
    $candidateService = $service + $postgres
    $candidateCluster = [int64]$BudgetContract.candidate_cluster_ms
    $candidateDatabase = [int64]$BudgetContract.candidate_database_ms
    $generation = [int64]$BudgetContract.database_generation_ms
    switch ($Action) {
        "build_candidate" {
            return $stopWriters + $candidateCluster +
                $candidateService + $candidateDatabase
        }
        "restore_candidate" {
            # A retry process has no in-memory candidate handle and must
            # re-observe/reconcile the already durable candidate first.
            return $stopWriters + $candidateCluster +
                $candidateService + $candidateDatabase +
                [int64]$Release.dataset_restore_helper_timeout_ms
        }
        "verify_candidate" {
            return $stopWriters + $candidateService + $candidateDatabase +
                [int64]$Release.dataset_restore_helper_timeout_ms
        }
        "promote_candidate" { return $stopWriters + $service }
        "publish_current" { return $service + $generation }
        "verify_runtime" {
            return $service + [int64]$Release.backend_ready_timeout_ms +
                [int64]$Release.backend_health_request_timeout_ms +
                [int64]$Release.dataset_payload_verification_timeout_ms
        }
        # Rollback retirement is resumable after durable runtime verification;
        # the admission floor leaves the process deadline authoritative.
        "retire_rollback" { return 1000 }
        "done" { return 1000 }
    }
}

function Resolve-TicketboxInstalledDatasetRestoreNextAction {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "complete", "candidate_building", "candidate_ready",
            "old_pg_staged", "old_staged", "candidate_pg_published",
            "candidate_published", "rollback_retiring", "cleanup_pending"
        )][string]$PhysicalState,
        [Parameter(Mandatory = $true)][bool]$RestoredSourcePresent,
        [Parameter(Mandatory = $true)][bool]$CandidateVerificationPresent,
        [Parameter(Mandatory = $true)][bool]$PublishedCurrentPresent,
        [Parameter(Mandatory = $true)][bool]$RuntimeVerificationPresent
    )
    if (
        $candidateVerificationPresent -and
        -not $restoredSourcePresent
    ) {
        throw "dataset restore candidate verification exists before restored source."
    }
    if (
        $publishedCurrentPresent -and
        -not $candidateVerificationPresent
    ) {
        throw "dataset restore CURRENT exists before candidate verification."
    }
    if (
        $runtimeVerificationPresent -and
        -not $publishedCurrentPresent
    ) {
        throw "dataset restore runtime verification exists before CURRENT publication."
    }
    switch ($PhysicalState) {
        "complete" {
            if (
                $restoredSourcePresent -and
                $candidateVerificationPresent -and
                $publishedCurrentPresent -and
                $runtimeVerificationPresent
            ) {
                return "done"
            }
            if ($publishedCurrentPresent) {
                throw "dataset restore rollback retired before runtime verification."
            }
            if ($restoredSourcePresent) {
                throw "dataset restore lost its candidate before CURRENT publication."
            }
            return "build_candidate"
        }
        "candidate_building" {
            if (
                $restoredSourcePresent -or
                $publishedCurrentPresent
            ) {
                throw "dataset restore building state conflicts with published authority."
            }
            return "restore_candidate"
        }
        "candidate_ready" {
            if (-not $restoredSourcePresent) { return "restore_candidate" }
            if ($publishedCurrentPresent) {
                throw "dataset restore CURRENT exists before physical publication."
            }
            if (-not $candidateVerificationPresent) {
                return "verify_candidate"
            }
            return "promote_candidate"
        }
        { $_ -in @("old_pg_staged", "old_staged", "candidate_pg_published") } {
            if (
                -not $restoredSourcePresent -or
                -not $candidateVerificationPresent -or
                $publishedCurrentPresent
            ) {
                throw "dataset restore partial promotion lacks its immutable source evidence."
            }
            return "promote_candidate"
        }
        "candidate_published" {
            if (-not $restoredSourcePresent) {
                throw "published dataset candidate lacks restored-source evidence."
            }
            if (-not $candidateVerificationPresent) {
                throw "published dataset candidate lacks candidate verification."
            }
            if (-not $publishedCurrentPresent) { return "publish_current" }
            if (-not $runtimeVerificationPresent) { return "verify_runtime" }
            return "retire_rollback"
        }
        { $_ -in @("rollback_retiring", "cleanup_pending") } {
            if (
                -not $restoredSourcePresent -or
                -not $candidateVerificationPresent -or
                -not $publishedCurrentPresent -or
                -not $runtimeVerificationPresent
            ) {
                throw "dataset restore cleanup lacks committed runtime verification."
            }
            return "retire_rollback"
        }
        default { throw "unknown dataset restore physical state."
        }
    }
}
