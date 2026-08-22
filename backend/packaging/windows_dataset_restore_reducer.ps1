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
        [Parameter(Mandatory = $true)][object]$Release
    )
    $service = [int64]$Release.service_state_timeout_ms
    $database = [int64]$Release.database_tool_timeout_ms
    $postgres = [int64]$Release.postgres_ready_timeout_ms
    switch ($Action) {
        "build_candidate" { return (4 * $service) + (2 * $database) + $postgres }
        "restore_candidate" {
            return (4 * $service) + (2 * $database) + $postgres +
                [int64]$Release.dataset_restore_helper_timeout_ms
        }
        "verify_candidate" {
            return (2 * $service) + $database + $postgres +
                [int64]$Release.dataset_restore_helper_timeout_ms
        }
        "promote_candidate" { return 2 * $service }
        # The delegated H1 owner has twelve closed reducer actions. Fifteen
        # database-tool windows cover one per action plus retry observation.
        "publish_current" { return (6 * $service) + (15 * $database) + (2 * $postgres) }
        "verify_runtime" {
            return (2 * $service) + [int64]$Release.backend_ready_timeout_ms +
                [int64]$Release.backend_health_request_timeout_ms +
                [int64]$Release.dataset_payload_verification_timeout_ms
        }
        "retire_rollback" { return $database }
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
