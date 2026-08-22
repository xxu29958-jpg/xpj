#Requires -Version 5.1

# Restore path classification and same-volume filesystem reconciliation.

function Get-TicketboxInstalledDatasetRestorePaths {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$OperationId
    )
    $operation = ([guid]$OperationId).ToString("D")
    $candidateRoot = Join-Path $DataRoot "restore-candidates\$operation"
    $rollbackRoot = Join-Path $DataRoot "restore-rollbacks\$operation"
    return [pscustomobject][ordered]@{
        operation_id = $operation
        stable_pgdata = Join-Path $DataRoot "pgdata"
        stable_uploads = Join-Path $DataRoot "app\uploads"
        candidate_pgdata = Join-Path $candidateRoot "pgdata"
        candidate_uploads = Join-Path $candidateRoot "uploads"
        rollback_pgdata = Join-Path $rollbackRoot "pgdata"
        rollback_uploads = Join-Path $rollbackRoot "uploads"
        candidate_root = $candidateRoot
        rollback_root = $rollbackRoot
    }
}

function Resolve-TicketboxInstalledDatasetRestorePhysicalState {
    param([Parameter(Mandatory = $true)][object]$Paths)
    $present = @{}
    foreach ($name in @(
        "stable_pgdata", "stable_uploads", "candidate_pgdata",
        "candidate_uploads", "rollback_pgdata", "rollback_uploads"
    )) {
        $kind = Get-TicketboxPathEntryKindNoFollow ([string]$Paths.$name)
        if ($kind -notin @("Missing", "Directory")) {
            throw "dataset restore physical path is not a plain directory: $name"
        }
        $present[$name] = $kind -ceq "Directory"
    }
    $containers = @{}
    foreach ($name in @("candidate_root", "rollback_root")) {
        $kind = Get-TicketboxPathEntryKindNoFollow ([string]$Paths.$name)
        if ($kind -notin @("Missing", "Directory")) {
            throw "dataset restore container path is not a plain directory: $name"
        }
        $containers[$name] = $kind
    }
    $signature = @(
        "stable_pgdata", "stable_uploads", "candidate_pgdata",
        "candidate_uploads", "rollback_pgdata", "rollback_uploads"
    ) | ForEach-Object { if ($present[$_]) { "1" } else { "0" } }
    switch ($signature -join "") {
        "111000" { return "candidate_building" }
        "111100" { return "candidate_ready" }
        "011110" { return "old_pg_staged" }
        "001111" { return "old_staged" }
        "100111" { return "candidate_pg_published" }
        "110011" { return "candidate_published" }
        { $_ -in @("110001", "110010") } { return "rollback_retiring" }
        "110000" {
            if (
                $containers.candidate_root -ceq "Directory" -or
                $containers.rollback_root -ceq "Directory"
            ) {
                return "cleanup_pending"
            }
            return "complete"
        }
        default { throw "dataset restore physical state is not classifiable."
        }
    }
}

function Set-TicketboxInstalledDatasetRestorePhysicalSelection {
    param(
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)]
        [ValidateSet("Candidate", "Predecessor")][string]$Selection
    )
    while ($true) {
        $state = Resolve-TicketboxInstalledDatasetRestorePhysicalState $Paths
        if ($Selection -ceq "Predecessor") {
            switch ($state) {
                { $_ -in @("complete", "candidate_building", "candidate_ready") } {
                    if (
                        (Get-TicketboxPathEntryKindNoFollow ([string]$Paths.rollback_root)) -ceq
                            "Directory"
                    ) {
                        [IO.Directory]::Delete([string]$Paths.rollback_root, $false)
                    }
                    return
                }
                "candidate_published" {
                    [IO.Directory]::CreateDirectory([string]$Paths.candidate_root) | Out-Null
                    [IO.Directory]::Move(
                        [string]$Paths.stable_uploads, [string]$Paths.candidate_uploads
                    )
                }
                "candidate_pg_published" {
                    [IO.Directory]::Move(
                        [string]$Paths.stable_pgdata, [string]$Paths.candidate_pgdata
                    )
                }
                "old_staged" {
                    [IO.Directory]::Move(
                        [string]$Paths.rollback_uploads, [string]$Paths.stable_uploads
                    )
                }
                "old_pg_staged" {
                    [IO.Directory]::Move(
                        [string]$Paths.rollback_pgdata, [string]$Paths.stable_pgdata
                    )
                }
                default {
                    throw "dataset restore predecessor selection was invoked from an invalid state."
                }
            }
            continue
        }
        switch ($state) {
            "candidate_ready" {
                [IO.Directory]::CreateDirectory([string]$Paths.rollback_root) | Out-Null
                [IO.Directory]::Move(
                    [string]$Paths.stable_pgdata, [string]$Paths.rollback_pgdata
                )
            }
            "old_pg_staged" {
                [IO.Directory]::Move(
                    [string]$Paths.stable_uploads, [string]$Paths.rollback_uploads
                )
            }
            "old_staged" {
                [IO.Directory]::Move(
                    [string]$Paths.candidate_pgdata, [string]$Paths.stable_pgdata
                )
            }
            "candidate_pg_published" {
                [IO.Directory]::Move(
                    [string]$Paths.candidate_uploads, [string]$Paths.stable_uploads
                )
            }
            "candidate_published" { return }
            default { throw "dataset restore promotion was invoked from an invalid state."
            }
        }
    }
}

function Remove-TicketboxInstalledDatasetRestoreRollback {
    param(
        [Parameter(Mandatory = $true)][object]$Paths,
        [Parameter(Mandatory = $true)][object]$LifecycleLock
    )
    Assert-TicketboxLifecycleOperationLease $LifecycleLock
    $state = Resolve-TicketboxInstalledDatasetRestorePhysicalState $Paths
    if ($state -notin @("candidate_published", "rollback_retiring", "cleanup_pending")) {
        throw "dataset restore rollback may retire only after candidate publication."
    }
    foreach ($path in @($Paths.rollback_pgdata, $Paths.rollback_uploads)) {
        Remove-TicketboxDataRootExact -Path ([string]$path)
    }
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Paths.rollback_root)) -ceq "Directory") {
        [IO.Directory]::Delete([string]$Paths.rollback_root, $false)
    }
    if ((Get-TicketboxPathEntryKindNoFollow ([string]$Paths.candidate_root)) -ceq "Directory") {
        [IO.Directory]::Delete([string]$Paths.candidate_root, $false)
    }
    if ((Resolve-TicketboxInstalledDatasetRestorePhysicalState $Paths) -cne "complete") {
        throw "dataset restore rollback retirement did not reach complete state."
    }
}
