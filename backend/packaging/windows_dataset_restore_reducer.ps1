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
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$RestoredSourceState,
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$CandidateVerificationState,
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$PublishedCurrentState,
        [Parameter(Mandatory = $true)]
        [ValidateSet("absent", "present")][string]$RuntimeVerificationState
    )
    if (
        $CandidateVerificationState -ceq "present" -and
        $RestoredSourceState -ceq "absent"
    ) {
        throw "dataset restore candidate verification exists before restored source."
    }
    if (
        $PublishedCurrentState -ceq "present" -and
        $CandidateVerificationState -ceq "absent"
    ) {
        throw "dataset restore CURRENT exists before candidate verification."
    }
    if (
        $RuntimeVerificationState -ceq "present" -and
        $PublishedCurrentState -ceq "absent"
    ) {
        throw "dataset restore runtime verification exists before CURRENT publication."
    }
    switch ($PhysicalState) {
        "complete" {
            if (
                $RestoredSourceState -ceq "present" -and
                $CandidateVerificationState -ceq "present" -and
                $PublishedCurrentState -ceq "present" -and
                $RuntimeVerificationState -ceq "present"
            ) {
                return "done"
            }
            if ($PublishedCurrentState -ceq "present") {
                throw "dataset restore rollback retired before runtime verification."
            }
            if ($RestoredSourceState -ceq "present") {
                throw "dataset restore lost its candidate before CURRENT publication."
            }
            return "build_candidate"
        }
        "candidate_building" {
            if (
                $RestoredSourceState -ceq "present" -or
                $PublishedCurrentState -ceq "present"
            ) {
                throw "dataset restore building state conflicts with published authority."
            }
            return "restore_candidate"
        }
        "candidate_ready" {
            if ($RestoredSourceState -ceq "absent") { return "restore_candidate" }
            if ($PublishedCurrentState -ceq "present") {
                throw "dataset restore CURRENT exists before physical publication."
            }
            if ($CandidateVerificationState -ceq "absent") {
                return "verify_candidate"
            }
            return "promote_candidate"
        }
        { $_ -in @("old_pg_staged", "old_staged", "candidate_pg_published") } {
            if (
                $RestoredSourceState -ceq "absent" -or
                $CandidateVerificationState -ceq "absent" -or
                $PublishedCurrentState -ceq "present"
            ) {
                throw "dataset restore partial promotion lacks its immutable source evidence."
            }
            return "promote_candidate"
        }
        "candidate_published" {
            if ($RestoredSourceState -ceq "absent") {
                throw "published dataset candidate lacks restored-source evidence."
            }
            if ($CandidateVerificationState -ceq "absent") {
                throw "published dataset candidate lacks candidate verification."
            }
            if ($PublishedCurrentState -ceq "absent") { return "publish_current" }
            if ($RuntimeVerificationState -ceq "absent") { return "verify_runtime" }
            return "retire_rollback"
        }
        { $_ -in @("rollback_retiring", "cleanup_pending") } {
            if (
                $RestoredSourceState -ceq "absent" -or
                $CandidateVerificationState -ceq "absent" -or
                $PublishedCurrentState -ceq "absent" -or
                $RuntimeVerificationState -ceq "absent"
            ) {
                throw "dataset restore cleanup lacks committed runtime verification."
            }
            return "retire_rollback"
        }
        default { throw "unknown dataset restore physical state."
        }
    }
}
