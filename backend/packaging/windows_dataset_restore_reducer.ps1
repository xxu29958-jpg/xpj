#Requires -Version 5.1

# Closed, IO-free next-action policy for installed dataset restore.

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
