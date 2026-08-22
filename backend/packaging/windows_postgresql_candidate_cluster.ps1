#Requires -Version 5.1

<#
.SYNOPSIS
  Bounded PostgreSQL cluster mechanisms used by install and dataset restore.
.DESCRIPTION
  This adapter observes candidate cluster state and resolves the next bounded
  mechanism action. Dataset identity, initdb mutation, and CURRENT publication
  remain outside this module.
#>

function Assert-TicketboxPostgresqlLoopbackConfigurationSafe {
    param([Parameter(Mandatory = $true)][string]$PgData)
    $autoConfigPath = Join-Path $PgData "postgresql.auto.conf"
    if (-not (Test-Path -LiteralPath $autoConfigPath -PathType Leaf)) { return }
    $autoConfig = [IO.File]::ReadAllText($autoConfigPath, [Text.Encoding]::ASCII)
    if ($autoConfig -match '(?m)^\s*(?:listen_addresses|port)\s*=') {
        throw "postgresql.auto.conf overrides the managed loopback/port boundary."
    }
}
function Set-TicketboxPostgresqlLoopbackConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$PgData,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )
    $configPath = Join-Path $PgData "postgresql.conf"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "PostgreSQL cluster lacks postgresql.conf."
    }
    $beginMarker = "# BEGIN Ticketbox installer overrides"
    $endMarker = "# END Ticketbox installer overrides"
    $legacyMarker = "# Ticketbox installer overrides"
    $newLine = [Environment]::NewLine
    $block = @(
        $beginMarker
        "listen_addresses = '127.0.0.1'"
        "port = $Port"
        $endMarker
    ) -join $newLine
    Assert-TicketboxPostgresqlLoopbackConfigurationSafe -PgData $PgData
    $content = [IO.File]::ReadAllText($configPath, [Text.Encoding]::ASCII)
    $markerIndex = $content.IndexOf($beginMarker, [StringComparison]::Ordinal)
    if ($markerIndex -ge 0) {
        if (
            $content.IndexOf(
                $beginMarker, $markerIndex + $beginMarker.Length,
                [StringComparison]::Ordinal
            ) -ge 0 -or
            $content.IndexOf($legacyMarker, [StringComparison]::Ordinal) -ge 0
        ) {
            throw "PostgreSQL managed configuration marker is ambiguous."
        }
        $endIndex = $content.IndexOf(
            $endMarker, $markerIndex + $beginMarker.Length,
            [StringComparison]::Ordinal
        )
        if ($endIndex -lt 0) {
            throw "PostgreSQL managed configuration block is truncated."
        }
        $without = $content.Substring(0, $markerIndex) +
            $content.Substring($endIndex + $endMarker.Length)
    }
    else {
        $legacyIndex = $content.IndexOf($legacyMarker, [StringComparison]::Ordinal)
        if ($legacyIndex -ge 0) {
            $escaped = [regex]::Escape($legacyMarker)
            $listen = "[ `t]*listen_addresses[ `t]*=[^`r`n]*`r?`n"
            $portLine = "[ `t]*port[ `t]*=[^`r`n]*(?:`r?`n)?"
            $legacyMatches = @(
                [regex]::Match($content, "(?m)^$escaped`r?`n$listen$portLine")
                [regex]::Match($content, "(?m)^$escaped`r?`n$portLine$listen")
            ) | Where-Object { $_.Success }
            if (
                $legacyMatches.Count -ne 1 -or
                $legacyMatches[0].Index -ne $legacyIndex
            ) {
                throw "PostgreSQL legacy managed configuration is ambiguous."
            }
            $without = $content.Substring(0, $legacyMatches[0].Index) +
                $content.Substring(
                    $legacyMatches[0].Index + $legacyMatches[0].Length
                )
        }
        else { $without = $content }
    }
    $updated = $without.TrimEnd() + $newLine + $newLine + $block + $newLine
    Write-TicketboxFileAtomically `
        -Path $configPath `
        -Bytes ([Text.Encoding]::ASCII.GetBytes($updated))
    $persisted = [IO.File]::ReadAllText($configPath, [Text.Encoding]::ASCII)
    if (-not $persisted.TrimEnd().EndsWith($block, [StringComparison]::Ordinal)) {
        throw "PostgreSQL managed configuration did not persist exactly."
    }
}

function Wait-TicketboxPostgresqlCandidateReady {
    param(
        [Parameter(Mandatory = $true)][string]$PgIsReadyPath,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds
    )
    $deadline = New-TicketboxWaitDeadline $TimeoutMilliseconds
    do {
        $remaining = [Math]::Max(
            1000, $TimeoutMilliseconds - $deadline.ElapsedMilliseconds
        )
        $probe = Invoke-TicketboxBoundedNativeProcess `
            -FilePath $PgIsReadyPath `
            -Arguments @("-h", "127.0.0.1", "-p", [string]$Port, "-q") `
            -TimeoutMilliseconds ([int][Math]::Min(5000, $remaining)) `
            -Label "restore candidate PostgreSQL readiness" `
            -ChildEnvironment @{}
        if ([int]$probe.ExitCode -eq 0) { return }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds)
    throw "restore candidate PostgreSQL did not become ready."
}

function Get-TicketboxPostgresqlRestoreCandidateClusterObservation {
    param(
        [Parameter(Mandatory = $true)][object]$Subject,
        [Parameter(Mandatory = $true)][ValidatePattern(
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Paths
    )
    $identity = $Subject.Identity
    $release = $Subject.Release
    $expectedPaths = Assert-TicketboxInstalledDatasetRestorePathAuthority $Paths
    if (
        [string]$expectedPaths.operation_id -cne ([guid]$OperationId).ToString("D") -or
        -not (Test-TicketboxPathEquals `
            ([string]$expectedPaths.data_root) ([string]$identity.DataRoot))
    ) {
        throw "restore candidate paths escaped the exact operation root."
    }
    $candidateRootKind = Get-TicketboxPathEntryKindNoFollow $Paths.candidate_root
    if ($candidateRootKind -notin @("Missing", "Directory")) {
        throw "restore candidate root is not a plain directory."
    }
    $candidateKind = Get-TicketboxPathEntryKindNoFollow $Paths.candidate_pgdata
    if ($candidateKind -notin @("Missing", "Directory")) {
        throw "restore candidate PGDATA is not a plain directory."
    }
    $pgBin = Join-Path ([string]$identity.InstallDir) "pg\bin"
    $initdb = Join-Path $pgBin "initdb.exe"
    $shawl = Join-Path ([string]$identity.InstallDir) "shawl\shawl.exe"
    $serviceName = [string]$release.pg_recovery_service_name
    $pwfile = Join-Path ([string]$Paths.candidate_root) ".initdb-password"
    $passwordKind = Get-TicketboxPathEntryKindNoFollow $pwfile
    if ($passwordKind -notin @("Missing", "File")) {
        throw "restore candidate initdb password path is not a protected file."
    }
    $requiredClusterFiles = @(
        (Join-Path ([string]$Paths.candidate_pgdata) "PG_VERSION"),
        (Join-Path ([string]$Paths.candidate_pgdata) "global\pg_control"),
        (Join-Path ([string]$Paths.candidate_pgdata) "postgresql.conf"),
        (Join-Path ([string]$Paths.candidate_pgdata) "pg_hba.conf")
    )
    $pgdataState = "missing"
    if ($candidateKind -ceq "Directory") {
        $complete = $true
        foreach ($required in $requiredClusterFiles) {
            if ((Get-TicketboxPathEntryKindNoFollow $required) -cne "File") {
                $complete = $false
            }
        }
        $pgdataState = if ($complete) { "complete" } else { "partial" }
    }
    $serviceKind = "absent"
    $serviceExecutable = ""
    $serviceState = "absent"
    $exitCode = [uint32]0
    $serviceSpecificExitCode = [uint32]0
    if (Test-TicketboxServiceExists $serviceName) {
        $actualExecutable = Get-TicketboxServiceExecutablePath $serviceName
        if (Test-TicketboxPathEquals $actualExecutable $shawl) {
            $serviceKind = "owned_initdb"
            $serviceExecutable = $shawl
            $initdbImage = New-TicketboxInitdbServiceImagePath `
                -ShawlPath $shawl `
                -ServiceName $serviceName `
                -WorkingDirectory $pgBin `
                -InitdbPath $initdb `
                -DataRoot ([string]$Paths.candidate_pgdata) `
                -PasswordFile $pwfile `
                -StopTimeoutMs ([int]$release.stop_timeout_ms)
            Assert-TicketboxInitdbServiceCommand `
                -Name $serviceName `
                -ExpectedShawl $shawl `
                -ExpectedServiceName $serviceName `
                -ExpectedWorkingDirectory $pgBin `
                -ExpectedInitdb $initdb `
                -ExpectedDataRoot ([string]$Paths.candidate_pgdata) `
                -ExpectedPasswordFile $pwfile `
                -ExpectedStopTimeoutMs ([int]$release.stop_timeout_ms) `
                -ExpectedImagePath $initdbImage
            Assert-TicketboxReleaseServiceIdentity `
                -Name $serviceName `
                -InstalledConfig $release `
                -TargetConfig $release `
                -AllowTargetSidTypePending | Out-Null
            Assert-TicketboxServiceStartMode `
                -Name $serviceName -ExpectedStartMode "Manual"
            Assert-TicketboxServiceHasNoFailureActions $serviceName
            $snapshot = Get-TicketboxServiceRuntimeSnapshot $serviceName
            $serviceState = [string]$snapshot.State
            $exitCode = [uint32]$snapshot.ExitCode
            $serviceSpecificExitCode = [uint32]$snapshot.ServiceSpecificExitCode
        }
        else {
            $pgCtl = Join-Path $pgBin "pg_ctl.exe"
            if (-not (Test-TicketboxPathEquals $actualExecutable $pgCtl)) {
                $serviceKind = "foreign"
                $serviceExecutable = [string]$actualExecutable
            }
            else {
                $serviceKind = "owned_pgctl"
                $serviceExecutable = $pgCtl
                Assert-TicketboxPgServiceCommand `
                    -Name $serviceName `
                    -ExpectedExecutable $pgCtl `
                    -ExpectedServiceName $serviceName `
                    -ExpectedDataRoot ([string]$Paths.candidate_pgdata)
                Assert-TicketboxReleaseServiceIdentity `
                    -Name $serviceName `
                    -InstalledConfig $release `
                    -TargetConfig $release `
                    -AllowTargetSidTypePending | Out-Null
            }
        }
    }
    return [pscustomobject][ordered]@{
        schema = "ticketbox-postgresql-restore-candidate-observation-v1"
        candidate_root_kind = $candidateRootKind.ToLowerInvariant()
        pgdata_state = $pgdataState
        password_kind = $passwordKind.ToLowerInvariant()
        service_kind = $serviceKind
        service_executable = $serviceExecutable
        service_state = $serviceState
        exit_code = $exitCode
        service_specific_exit_code = $serviceSpecificExitCode
    }
}

function Resolve-TicketboxPostgresqlRestoreCandidateClusterNextAction {
    param([Parameter(Mandatory = $true)][object]$Observation)
    Assert-TicketboxDatabaseGenerationExactProperties `
        -Value $Observation `
        -ExpectedNames @(
            "schema", "candidate_root_kind", "pgdata_state", "password_kind",
            "service_kind", "service_executable", "service_state", "exit_code",
            "service_specific_exit_code"
        ) `
        -Label "restore candidate cluster observation"
    if (
        [string]$Observation.schema -cne
            "ticketbox-postgresql-restore-candidate-observation-v1" -or
        [string]$Observation.candidate_root_kind -notin @("missing", "directory") -or
        [string]$Observation.pgdata_state -notin @("missing", "partial", "complete") -or
        [string]$Observation.password_kind -notin @("missing", "file") -or
        [string]$Observation.service_kind -notin @(
            "absent", "owned_initdb", "owned_pgctl", "foreign"
        )
    ) {
        throw "restore candidate cluster observation is not closed."
    }
    if ([string]$Observation.service_kind -ceq "foreign") {
        throw "restore candidate recovery service executable is foreign."
    }
    if ([string]$Observation.service_kind -ceq "owned_pgctl") {
        if (
            [string]$Observation.pgdata_state -cne "complete" -or
            [string]$Observation.password_kind -cne "missing"
        ) {
            throw "restore candidate recovery service owns an incomplete cluster."
        }
        return "reconcile_loopback"
    }
    if ([string]$Observation.service_kind -ceq "owned_initdb") {
        if ([string]$Observation.service_state -cne "stopped") {
            return "wait_initdb_terminal"
        }
        if (
            [uint32]$Observation.exit_code -ne 0 -or
            [uint32]$Observation.service_specific_exit_code -ne 0
        ) {
            return "reset_stale_attempt"
        }
        if ([string]$Observation.pgdata_state -ceq "complete") {
            return "retire_initdb_capability"
        }
        if (
            [string]$Observation.pgdata_state -ceq "missing" -and
            [string]$Observation.password_kind -ceq "file"
        ) {
            return "run_prepared_initdb"
        }
        return "reset_stale_attempt"
    }
    if ([string]$Observation.password_kind -cne "missing") {
        throw "restore candidate password artifact has no owning service capability."
    }
    if ([string]$Observation.pgdata_state -ceq "complete") {
        return "reconcile_loopback"
    }
    if ([string]$Observation.pgdata_state -ceq "partial") {
        return "reset_stale_attempt"
    }
    return "prepare_initdb"
}
