#Requires -Version 5.1

. (Join-Path $PSScriptRoot 'test_pg_process_contract.ps1')

function Test-XpjOpaquePostgresRootIsForeignServiceProcess {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Snapshot)

    $parentId = [int]$Snapshot.ParentProcessId
    if ($parentId -le 0) { return $false }
    $parents = @(Get-CimInstance Win32_Process -Filter "ProcessId = $parentId" -ErrorAction Stop)
    $services = @(Get-CimInstance Win32_Service -Filter "ProcessId = $parentId" -ErrorAction Stop)
    if ($parents.Count -ne 1 -or $services.Count -ne 1) { return $false }
    $childStarted = ([DateTime]$Snapshot.CreationDate).ToUniversalTime()
    $parentStarted = ([DateTime]$parents[0].CreationDate).ToUniversalTime()
    if ($childStarted -lt $parentStarted) { return $false }
    try {
        $serviceSid = ConvertTo-TicketboxAccountSid ([string]$services[0].StartName)
    }
    catch {
        return $false
    }
    $runtimeOwnerSid = Get-XpjTestPostgresRuntimeOwnerSid
    return -not [string]::Equals(
        [string]$serviceSid,
        [string]$runtimeOwnerSid,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Get-XpjFinalOwnershipScanProcessHandle {
    [CmdletBinding()]
    [OutputType([Diagnostics.Process])]
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        return $process
    }
    catch {
        # Win32_Process is a point-in-time snapshot. A process may complete
        # normally before we open its generation-pinning handle. Only the
        # cmdlet's exact object-not-found result proves that narrow outcome;
        # access failures and every other error remain fail-closed.
        $isMissingProcess = (
            [string]$_.FullyQualifiedErrorId -ceq
                'NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.GetProcessCommand' -and
            $_.CategoryInfo.Category -eq [Management.Automation.ErrorCategory]::ObjectNotFound -and
            [string]::Equals(
                [string]$_.TargetObject,
                [string]$ProcessId,
                [StringComparison]::Ordinal
            )
        )
        if ($isMissingProcess) {
            return
        }
        throw
    }
}

function Assert-NoXpjLivePostgresDataDirOwner {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $candidates = @(Get-CimInstance Win32_Process -Filter "Name = 'postgres.exe'" -ErrorAction Stop)
    $byPid = @{}
    foreach ($candidate in $candidates) { $byPid[[int]$candidate.ProcessId] = $candidate }
    $verifiedRoots = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($candidate in $candidates) {
        $root = $candidate
        $visited = New-Object 'System.Collections.Generic.HashSet[int]'
        while ($byPid.ContainsKey([int]$root.ParentProcessId)) {
            if (-not $visited.Add([int]$root.ProcessId)) {
                throw "PostgreSQL process ancestry contains a cycle at PID $($root.ProcessId)"
            }
            $parent = $byPid[[int]$root.ParentProcessId]
            $childStarted = ([DateTime]$root.CreationDate).ToUniversalTime()
            $parentStarted = ([DateTime]$parent.CreationDate).ToUniversalTime()
            if ($childStarted -lt $parentStarted) {
                throw "PostgreSQL PID ancestry crossed a reused parent generation at PID $($root.ProcessId)"
            }
            $root = $parent
        }
        $rootId = [int]$root.ProcessId
        if (-not $verifiedRoots.Add($rootId)) { continue }
        if (
            [string]::IsNullOrWhiteSpace([string]$root.CommandLine) -or
            [string]::IsNullOrWhiteSpace([string]$root.ExecutablePath)
        ) {
            # The protected runtime root grants access only to the invoking
            # principal. An opaque postgres tree is irrelevant only when its
            # live parent is an SCM service under a different principal.
            if (Test-XpjOpaquePostgresRootIsForeignServiceProcess -Snapshot $root) {
                continue
            }
            throw "Cannot prove PostgreSQL root PID $rootId is unrelated to ${resolvedDataDir}"
        }
        $handle = Get-XpjFinalOwnershipScanProcessHandle -ProcessId $rootId
        if ($null -eq $handle) { continue }
        try {
            $null = $handle.Handle
            $fresh = Get-XpjVerifiedProcessSnapshot -Snapshot $root -Handle $handle
            if (
                [string]::IsNullOrWhiteSpace([string]$fresh.CommandLine) -or
                [string]::IsNullOrWhiteSpace([string]$fresh.ExecutablePath)
            ) {
                throw "Cannot revalidate PostgreSQL root PID $rootId"
            }
            $snapshotExe = [IO.Path]::GetFullPath([string]$fresh.ExecutablePath)
            $handleExe = [IO.Path]::GetFullPath($handle.MainModule.FileName)
            if (-not [string]::Equals($snapshotExe, $handleExe, [StringComparison]::OrdinalIgnoreCase)) {
                throw "PostgreSQL root PID generation changed during final ownership scan: $rootId"
            }
            $candidateDataDir = Get-XpjPostgresDataArgument `
                -CommandLine ([string]$fresh.CommandLine) `
                -ProcessId $rootId
            if ([string]::Equals($candidateDataDir, $resolvedDataDir, [StringComparison]::OrdinalIgnoreCase)) {
                throw "PostgreSQL data directory is still owned by live PID ${rootId}: $resolvedDataDir"
            }
        }
        finally {
            $handle.Close()
        }
    }
}

function Get-XpjTestPostgresDirectoryIdentity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    if ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedDataDir) -cne 'Directory') {
        throw "Test PostgreSQL identity target is not a plain directory: $resolvedDataDir"
    }
    Initialize-TicketboxExactTreeDeleteNativeMethods
    $identity = @(
        [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity(
            $resolvedDataDir
        )
    )
    if (
        $identity.Count -ne 2 -or
        [string]$identity[0] -notmatch '^[0-9A-F]{16}$' -or
        [string]$identity[1] -notmatch '^[0-9A-F]{32}$'
    ) {
        throw "Test PostgreSQL directory identity is invalid: $resolvedDataDir"
    }
    return [pscustomobject]@{
        VolumeSerialNumber = [string]$identity[0]
        FileId = [string]$identity[1]
    }
}

function Assert-XpjTestPostgresDirectoryIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][string]$VolumeSerialNumber,
        [Parameter(Mandatory = $true)][string]$FileId
    )

    $actual = Get-XpjTestPostgresDirectoryIdentity -DataDir $DataDir
    if (
        $actual.VolumeSerialNumber -cne $VolumeSerialNumber -or
        $actual.FileId -cne $FileId
    ) {
        throw "Test PostgreSQL directory entity changed before deletion: $DataDir"
    }
    return $actual
}

function ConvertTo-XpjTestPostgresDeletionMarkerText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][Guid]$InstanceId,
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][string]$VolumeSerialNumber,
        [Parameter(Mandatory = $true)][string]$FileId,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    if (
        $VolumeSerialNumber -notmatch '^[0-9A-F]{16}$' -or
        $FileId -notmatch '^[0-9A-F]{32}$'
    ) {
        throw 'Test PostgreSQL deletion directory identity is invalid'
    }

    return ([ordered]@{
        schema = 'xpj-test-postgres-deletion-v2'
        state = 'deleting'
        data_dir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
        cluster_marker = [string](Get-XpjTestPostgresContract).cluster_marker
        instance_id = $InstanceId.ToString('D')
        postgres_bin = Resolve-XpjStoredPostgresBinPath -PostgresBin $PostgresBin
        volume_serial_number = $VolumeSerialNumber
        file_id = $FileId
        port = $Port
    } | ConvertTo-Json -Compress) + "`n"
}

function Read-XpjTestPostgresDeletionMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $path = Get-XpjTestPostgresDeletionMarkerPath -DataDir $resolvedDataDir
    if ((Get-TicketboxPathEntryKindNoFollow -Path $path) -cne 'File') {
        throw "Test PostgreSQL deletion marker is not a plain file: $path"
    }
    $rawText = Read-XpjTestPostgresProtectedMarkerText -Path $path
    $payload = $rawText | ConvertFrom-Json
    $expectedFields = @(
        'schema',
        'state',
        'data_dir',
        'cluster_marker',
        'instance_id',
        'postgres_bin',
        'volume_serial_number',
        'file_id',
        'port'
    )
    $actualFields = @($payload.PSObject.Properties.Name)
    $instanceId = [Guid]::Empty
    if (
        @(Compare-Object ($expectedFields | Sort-Object) ($actualFields | Sort-Object)).Count -ne 0 -or
        [string]$payload.schema -cne 'xpj-test-postgres-deletion-v2' -or
        [string]$payload.state -cne 'deleting' -or
        [string]$payload.cluster_marker -cne [string](Get-XpjTestPostgresContract).cluster_marker -or
        -not [Guid]::TryParse([string]$payload.instance_id, [ref]$instanceId) -or
        $instanceId -eq [Guid]::Empty -or
        [string]$payload.volume_serial_number -notmatch '^[0-9A-F]{16}$' -or
        [string]$payload.file_id -notmatch '^[0-9A-F]{32}$' -or
        [int]$payload.port -ne $Port
    ) {
        throw "Test PostgreSQL deletion marker identity is invalid: $path"
    }
    $postgresBin = Resolve-XpjStoredPostgresBinPath -PostgresBin ([string]$payload.postgres_bin)
    $text = ConvertTo-XpjTestPostgresDeletionMarkerText `
        -DataDir $resolvedDataDir `
        -InstanceId $instanceId `
        -PostgresBin $postgresBin `
        -VolumeSerialNumber ([string]$payload.volume_serial_number) `
        -FileId ([string]$payload.file_id) `
        -Port $Port
    if ($rawText -cne $text) {
        throw "Test PostgreSQL deletion marker is not canonical: $path"
    }
    return [pscustomobject]@{
        Path = $path
        DataDir = $resolvedDataDir
        InstanceId = $instanceId
        PostgresBin = $postgresBin
        VolumeSerialNumber = [string]$payload.volume_serial_number
        FileId = [string]$payload.file_id
        Port = $Port
        Text = $text
        OwnershipText = ConvertTo-XpjTestPostgresOwnershipMarkerText `
            -DataDir $resolvedDataDir `
            -InstanceId $instanceId `
            -PostgresBin $postgresBin
    }
}

function New-XpjTestPostgresDeletionMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][object]$Ownership,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $path = Get-XpjTestPostgresDeletionMarkerPath -DataDir $DataDir
    if ((Get-TicketboxPathEntryKindNoFollow -Path $path) -cne 'Missing') {
        throw "Test PostgreSQL deletion marker already exists: $path"
    }
    $directoryIdentity = Get-XpjTestPostgresDirectoryIdentity -DataDir $DataDir
    $text = ConvertTo-XpjTestPostgresDeletionMarkerText `
        -DataDir $DataDir `
        -InstanceId $Ownership.InstanceId `
        -PostgresBin $Ownership.PostgresBin `
        -VolumeSerialNumber $directoryIdentity.VolumeSerialNumber `
        -FileId $directoryIdentity.FileId `
        -Port $Port
    Write-XpjTestPostgresProtectedMarker -Path $path -Text $text
    return Read-XpjTestPostgresDeletionMarker -DataDir $DataDir -Port $Port
}

function Remove-XpjTestPostgresDeletionMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][Guid]$InstanceId,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $marker = Read-XpjTestPostgresDeletionMarker -DataDir $DataDir -Port $Port
    if ($marker.InstanceId -ne $InstanceId) {
        throw "Test PostgreSQL deletion authority changed: $($marker.Path)"
    }
    Remove-XpjTestPostgresProtectedMarker -Path $marker.Path
    if ((Get-TicketboxPathEntryKindNoFollow -Path $marker.Path) -cne 'Missing') {
        throw "Test PostgreSQL deletion marker still exists: $($marker.Path)"
    }
}

function Remove-XpjTestPostgresOwnershipMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][Guid]$InstanceId
    )

    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $DataDir
    $marker = Read-XpjTestPostgresOwnershipMarker -Path $paths.Host -DataDir $DataDir
    if ($marker.InstanceId -ne $InstanceId) {
        throw "Test PostgreSQL host ownership changed before marker removal: $($paths.Host)"
    }
    Remove-XpjTestPostgresProtectedMarker -Path $paths.Host
    if ((Get-TicketboxPathEntryKindNoFollow -Path $paths.Host) -cne 'Missing') {
        throw "Test PostgreSQL host ownership marker still exists: $($paths.Host)"
    }
}

function Remove-XpjTestPostgresCluster {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDir,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$PostgresExe,
        [Guid]$ProvisioningInstanceId = [Guid]::Empty
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $resolvedDataDir
    $deletionPath = Get-XpjTestPostgresDeletionMarkerPath -DataDir $resolvedDataDir
    $dataKind = Get-TicketboxPathEntryKindNoFollow -Path $resolvedDataDir
    $hostKind = Get-TicketboxPathEntryKindNoFollow -Path $paths.Host
    $deletionKind = Get-TicketboxPathEntryKindNoFollow -Path $deletionPath
    if (
        $dataKind -eq 'Missing' -and
        $hostKind -eq 'Missing' -and
        $deletionKind -eq 'Missing'
    ) {
        return
    }
    if ($deletionKind -notin @('Missing', 'File')) {
        throw "Test PostgreSQL deletion marker is not a plain file: $deletionPath"
    }
    $deletion = if ($deletionKind -eq 'File') {
        Read-XpjTestPostgresDeletionMarker -DataDir $resolvedDataDir -Port $Port
    }
    else {
        $null
    }
    if ($null -eq $deletion -and $hostKind -cne 'File') {
        throw "Refusing to remove a PostgreSQL data directory without its host ownership marker: $resolvedDataDir"
    }
    if ($dataKind -eq 'Missing') {
        if ($hostKind -eq 'File') {
            $ownership = Update-XpjTestPostgresOwnershipSchema `
                -DataDir $resolvedDataDir `
                -AllowProvisioning
            if (
                $null -ne $deletion -and
                (
                    $ownership.InstanceId -ne $deletion.InstanceId -or
                    $ownership.Text -cne $deletion.OwnershipText
                )
            ) {
                throw "Test PostgreSQL deletion and ownership authorities disagree: $resolvedDataDir"
            }
            if (
                $ProvisioningInstanceId -ne [Guid]::Empty -and
                $ownership.InstanceId -ne $ProvisioningInstanceId
            ) {
                throw "Test PostgreSQL provisioning authority changed: $resolvedDataDir"
            }
            Remove-XpjTestPostgresOwnershipMarker `
                -DataDir $resolvedDataDir `
                -InstanceId $ownership.InstanceId
        }
        elseif ($null -eq $deletion) {
            throw "Test PostgreSQL host ownership marker disappeared: $($paths.Host)"
        }
        if ($null -ne $deletion) {
            Remove-XpjTestPostgresDeletionMarker `
                -DataDir $resolvedDataDir `
                -InstanceId $deletion.InstanceId `
                -Port $Port
        }
        return
    }
    if ($dataKind -cne 'Directory') {
        throw "Test PostgreSQL data path is not a plain directory: $resolvedDataDir ($dataKind)"
    }
    if ($null -ne $deletion) {
        $null = Assert-XpjTestPostgresDirectoryIdentity `
            -DataDir $resolvedDataDir `
            -VolumeSerialNumber $deletion.VolumeSerialNumber `
            -FileId $deletion.FileId
    }
    if ($hostKind -cne 'File') {
        throw "Test PostgreSQL host ownership marker disappeared before tree cleanup: $($paths.Host)"
    }
    $dataMarkerKind = Get-TicketboxPathEntryKindNoFollow -Path $paths.Data
    if ($dataMarkerKind -notin @('Missing', 'File')) {
        throw "Test PostgreSQL data ownership marker is not a plain file: $($paths.Data)"
    }
    $isProvisioningCleanup = $ProvisioningInstanceId -ne [Guid]::Empty
    if ($null -eq $deletion) {
        if (
            $dataMarkerKind -eq 'Missing' -and
            @(Get-ChildItem -LiteralPath $resolvedDataDir -Force).Count -ne 0
        ) {
            throw "Test PostgreSQL data ownership evidence is missing from a non-empty directory: $resolvedDataDir"
        }
        $ownership = Update-XpjTestPostgresOwnershipSchema `
            -DataDir $resolvedDataDir `
            -AllowProvisioning:($isProvisioningCleanup -or $dataMarkerKind -eq 'Missing')
    }
    else {
        $hostMarker = Read-XpjTestPostgresOwnershipMarker `
            -Path $paths.Host `
            -DataDir $resolvedDataDir
        if (
            $hostMarker.InstanceId -ne $deletion.InstanceId -or
            $hostMarker.Text -cne $deletion.OwnershipText
        ) {
            throw "Test PostgreSQL deletion and host ownership markers disagree: $resolvedDataDir"
        }
        if ($dataMarkerKind -eq 'File') {
            $dataMarker = Read-XpjTestPostgresOwnershipMarker `
                -Path $paths.Data `
                -DataDir $resolvedDataDir
            if (
                $dataMarker.InstanceId -ne $deletion.InstanceId -or
                $dataMarker.Text -cne $deletion.OwnershipText
            ) {
                throw "Test PostgreSQL deletion and data ownership markers disagree: $resolvedDataDir"
            }
        }
        $ownership = [pscustomobject]@{
            InstanceId = $deletion.InstanceId
            PostgresBin = $deletion.PostgresBin
            Text = $deletion.OwnershipText
        }
    }
    if ($isProvisioningCleanup -and $ownership.InstanceId -ne $ProvisioningInstanceId) {
        throw "Test PostgreSQL provisioning authority changed: $resolvedDataDir"
    }
    $authoritativePostgresExe = Join-Path ([string]$ownership.PostgresBin) 'postgres.exe'
    if (-not [string]::Equals(
        [IO.Path]::GetFullPath($PostgresExe),
        [IO.Path]::GetFullPath($authoritativePostgresExe),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Test PostgreSQL cleanup binary disagrees with ownership: $PostgresExe"
    }
    $PostgresExe = $authoritativePostgresExe
    $pidFile = Join-Path $resolvedDataDir 'postmaster.pid'
    $hasRecordedPid = $false
    if ((Get-TicketboxPathEntryKindNoFollow -Path $pidFile) -eq 'File') {
        $null = Read-XpjPostmasterIdentityFile -DataDir $resolvedDataDir -Port $Port
        $hasRecordedPid = $true
    }
    if ($hasRecordedPid) {
        $ownedProcess = $null
        try {
            $ownedProcess = Assert-XpjOwnedPostgresProcess `
                -DataDir $resolvedDataDir `
                -Port $Port `
                -PostgresExe $PostgresExe `
                -AllowNoListener
        }
        catch {
            Remove-XpjStalePostmasterIdentity `
                -DataDir $resolvedDataDir `
                -PostgresExe $PostgresExe
        }
        finally {
            if ($null -ne $ownedProcess) {
                foreach ($process in $ownedProcess.Processes) { $process.Close() }
            }
        }
        if ($null -ne $ownedProcess) {
            Stop-XpjOwnedPostgresProcess `
                -DataDir $resolvedDataDir `
                -Port $Port `
                -PostgresExe $PostgresExe
        }
    }
    Assert-NoXpjLivePostgresDataDirOwner -DataDir $resolvedDataDir -Port $Port
    if ($null -eq $deletion) {
        $deletion = New-XpjTestPostgresDeletionMarker `
            -DataDir $resolvedDataDir `
            -Ownership $ownership `
            -Port $Port
    }
    $expectedRoot = $resolvedDataDir
    $expectedMarkerText = [string]$ownership.Text
    $expectedDeletionText = [string]$deletion.Text
    $expectedVolumeSerialNumber = [string]$deletion.VolumeSerialNumber
    $expectedFileId = [string]$deletion.FileId
    $deletionMarkerPath = [string]$deletion.Path
    $hostMarkerPath = [string]$paths.Host
    $dataMarkerPath = [string]$paths.Data
    # Revalidate the protected marker ACL and bytes immediately before the
    # exact root is opened.  The callback itself is invoked from a native
    # delegate and therefore must use only handle-bound native helpers; calling
    # script-scope functions there is not reliable under Windows PowerShell 5.1.
    if ((Read-XpjTestPostgresProtectedMarkerText -Path $deletionMarkerPath) -cne $expectedDeletionText) {
        throw "Test PostgreSQL deletion authority changed before opening the deletion root: $deletionMarkerPath"
    }
    if ((Read-XpjTestPostgresProtectedMarkerText -Path $hostMarkerPath) -cne $expectedMarkerText) {
        throw "Test PostgreSQL host ownership changed before opening the deletion root: $hostMarkerPath"
    }
    if (
        $dataMarkerKind -eq 'File' -and
        (Read-XpjTestPostgresProtectedMarkerText -Path $dataMarkerPath) -cne $expectedMarkerText
    ) {
        throw "Test PostgreSQL ownership changed before opening the deletion root: $dataMarkerPath"
    }
    $verifyOpenedRoot = {
        param([string]$OpenedPath)

        $openedRoot = [IO.Path]::GetFullPath($OpenedPath).TrimEnd('\', '/')
        if (-not [string]::Equals($openedRoot, $expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Test PostgreSQL deletion opened another root: $OpenedPath"
        }
        $openedIdentity = @(
            [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity($OpenedPath)
        )
        if (
            $openedIdentity.Count -ne 2 -or
            [string]$openedIdentity[0] -cne $expectedVolumeSerialNumber -or
            [string]$openedIdentity[1] -cne $expectedFileId
        ) {
            throw "Test PostgreSQL directory entity changed before deletion: $OpenedPath"
        }
        if ([TicketboxExactTreeDeleteNativeMethods]::InspectEntry($deletionMarkerPath) -ne 1) {
            throw "Test PostgreSQL deletion authority disappeared: $deletionMarkerPath"
        }
        if (
            [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                $deletionMarkerPath,
                65536
            ) -cne $expectedDeletionText
        ) {
            throw "Test PostgreSQL deletion authority changed: $deletionMarkerPath"
        }
        $hostKind = [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($hostMarkerPath)
        if ($hostKind -ne 1) {
            throw "Test PostgreSQL host ownership changed after opening the deletion root: $hostMarkerPath"
        }
        $hostText = [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
            $hostMarkerPath,
            65536
        )
        if ($hostText -cne $expectedMarkerText) {
            throw "Test PostgreSQL host ownership changed after opening the deletion root: $hostMarkerPath"
        }
        $dataKind = [TicketboxExactTreeDeleteNativeMethods]::InspectEntry($dataMarkerPath)
        if ($dataKind -eq 0) {
            return
        }
        if ($dataKind -ne 1) {
            throw "Test PostgreSQL data ownership changed after opening the deletion root: $dataMarkerPath"
        }
        $dataText = [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
            $dataMarkerPath,
            65536
        )
        if ($dataText -cne $expectedMarkerText) {
            throw "Test PostgreSQL ownership changed after opening the deletion root: $OpenedPath"
        }
    }.GetNewClosure()
    $deferredMarkerName = if ($dataMarkerKind -eq 'File') {
        [IO.Path]::GetFileName($dataMarkerPath)
    }
    else {
        ''
    }
    Remove-TicketboxTreeExact `
        -Path $resolvedDataDir `
        -DeferredRootLeafName $deferredMarkerName `
        -OnRootHandleAcquired $verifyOpenedRoot
    Remove-XpjTestPostgresOwnershipMarker -DataDir $resolvedDataDir -InstanceId $ownership.InstanceId
    Remove-XpjTestPostgresDeletionMarker `
        -DataDir $resolvedDataDir `
        -InstanceId $ownership.InstanceId `
        -Port $Port
    Write-Host "Removed data dir $resolvedDataDir"
}
