#Requires -Version 5.1

$script:TicketboxBackendBuildManifestName = "BUILD_PROVENANCE.json"
$script:TicketboxBackendBuildManifestSchema = 3
$script:TicketboxBuildToolchainConfigRelativePath = "packaging\windows-build-toolchain.json"
$script:TicketboxBuildLockInputHeaderPattern = '(?m)^# ticketbox-lock-input-sha256: ([0-9a-f]{64})\r?$'
$script:TicketboxForbiddenDatabasePayloadSegments = @(
    "sqlite",
    "sqlite3",
    "_sqlite3",
    "pysqlite2",
    "mysql",
    "mysqldb",
    "mysqlclient",
    "pymysql",
    "mariadb"
)

function Get-TicketboxWindowsBuildLockName([string]$BackendRoot) {
    $canonicalRoot = [System.IO.Path]::GetFullPath($BackendRoot).TrimEnd("\", "/").ToUpperInvariant()
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($canonicalRoot))
        $hex = -join ($digest | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $sha256.Dispose()
    }
    return "Global\Ticketbox.WindowsBuild.$hex"
}

function Enter-TicketboxWindowsBuildLock([string]$BackendRoot, [int]$TimeoutSeconds = 900) {
    if ($TimeoutSeconds -le 0) { throw "Windows build lock timeout must be positive." }
    $canonicalRoot = [System.IO.Path]::GetFullPath($BackendRoot).TrimEnd("\", "/")
    $stateKey = "Ticketbox.WindowsBuild.Lock." + (Get-TicketboxWindowsBuildLockName $canonicalRoot)
    $existing = [AppDomain]::CurrentDomain.GetData($stateKey)
    $currentThreadId = [System.Threading.Thread]::CurrentThread.ManagedThreadId
    if ($null -ne $existing -and [int]$existing.OwnerThreadId -eq $currentThreadId) {
        $existing.RefCount = [int]$existing.RefCount + 1
        return [pscustomobject]@{ StateKey = $stateKey; Active = $true }
    }

    $buildRoot = Join-Path $canonicalRoot "build"
    Assert-TicketboxNoReparsePath -Path $buildRoot -AllowedRoot $canonicalRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
    Assert-TicketboxNoReparsePath -Path $buildRoot -AllowedRoot $canonicalRoot -InspectTree | Out-Null
    $lockPath = Join-Path $buildRoot ".ticketbox-windows-build.lock"
    $mutex = $null
    $mutexAcquired = $false
    $fileLock = $null
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        try {
            $mutex = New-Object System.Threading.Mutex(
                $false,
                (Get-TicketboxWindowsBuildLockName $canonicalRoot)
            )
            try {
                $mutexAcquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
            }
            catch [System.Threading.AbandonedMutexException] {
                $mutexAcquired = $true
            }
            if (-not $mutexAcquired) {
                throw "Timed out waiting for the cross-session Windows build mutex."
            }
        }
        catch [System.UnauthorizedAccessException] {
            if ($null -ne $mutex) { $mutex.Dispose(); $mutex = $null }
        }
        catch [System.Security.SecurityException] {
            if ($null -ne $mutex) { $mutex.Dispose(); $mutex = $null }
        }

        while ($null -eq $fileLock) {
            try {
                $fileLock = [System.IO.File]::Open(
                    $lockPath,
                    [System.IO.FileMode]::OpenOrCreate,
                    [System.IO.FileAccess]::ReadWrite,
                    [System.IO.FileShare]::None
                )
            }
            catch [System.IO.IOException] {
                if ($stopwatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                    throw "Timed out waiting for the cross-session Windows build file lock."
                }
                Start-Sleep -Milliseconds 100
            }
        }
        $ownerBytes = [System.Text.Encoding]::UTF8.GetBytes(
            "pid=$PID; acquired_utc=$([DateTime]::UtcNow.ToString('o'))`n"
        )
        $fileLock.SetLength(0)
        $fileLock.Write($ownerBytes, 0, $ownerBytes.Length)
        $fileLock.Flush($true)
        $state = [pscustomobject]@{
            RefCount = 1
            FileLock = $fileLock
            Mutex = $mutex
            MutexAcquired = $mutexAcquired
            OwnerThreadId = $currentThreadId
        }
        [AppDomain]::CurrentDomain.SetData($stateKey, $state)
        return [pscustomobject]@{ StateKey = $stateKey; Active = $true }
    }
    catch {
        if ($null -ne $fileLock) { $fileLock.Dispose() }
        if ($null -ne $mutex) {
            try { if ($mutexAcquired) { $mutex.ReleaseMutex() } }
            finally { $mutex.Dispose() }
        }
        throw
    }
    finally { $stopwatch.Stop() }
}

function Exit-TicketboxWindowsBuildLock([object]$Lock) {
    if ($null -eq $Lock -or -not [bool]$Lock.Active) { return }
    $state = [AppDomain]::CurrentDomain.GetData([string]$Lock.StateKey)
    if ($null -eq $state) { throw "Windows build lock state is missing during release." }
    $state.RefCount = [int]$state.RefCount - 1
    $Lock.Active = $false
    if ([int]$state.RefCount -gt 0) { return }
    [AppDomain]::CurrentDomain.SetData([string]$Lock.StateKey, $null)
    $failures = @()
    try {
        try { $state.FileLock.Dispose() }
        catch { $failures += "file lock ($($_.Exception.Message))" }
    }
    finally {
        if ($null -ne $state.Mutex) {
            try {
                if ([bool]$state.MutexAcquired) { $state.Mutex.ReleaseMutex() }
            }
            catch { $failures += "global mutex ($($_.Exception.Message))" }
            try { $state.Mutex.Dispose() }
            catch { $failures += "global mutex dispose ($($_.Exception.Message))" }
        }
    }
    if ($failures.Count -gt 0) {
        throw "Windows build lock release failed: $($failures -join '; ')"
    }
}

function Get-TicketboxDirectoryPublicationIdentity([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $null }
    $paths = @(
        Get-ChildItem -LiteralPath $Path -Recurse -File -Force |
            ForEach-Object { $_.FullName }
    )
    if ($paths.Count -eq 0) { throw "Published directory must contain at least one file: $Path" }
    $snapshot = Get-TicketboxFileSetSnapshot $Path $paths
    return [pscustomobject]@{
        algorithm = "SHA-256"
        fingerprint = [string]$snapshot.fingerprint
        file_count = @($snapshot.files).Count
    }
}

function Test-TicketboxDirectoryPublicationIdentity([string]$Path, [object]$Expected) {
    if ($null -eq $Expected -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    try { $actual = Get-TicketboxDirectoryPublicationIdentity $Path }
    catch { return $false }
    return (
        [string]$Expected.algorithm -ceq "SHA-256" -and
        [string]$Expected.fingerprint -match '^[0-9a-f]{64}$' -and
        [string]$actual.fingerprint -ceq [string]$Expected.fingerprint -and
        [int64]$actual.file_count -eq [int64]$Expected.file_count
    )
}

function Write-TicketboxDirectoryPublicationReceipt([string]$Path, [object]$Receipt) {
    $temporaryPath = "$Path.$PID.tmp"
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes(
        (($Receipt | ConvertTo-Json -Depth 8) + "`n")
    )
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $temporaryPath,
            [System.IO.FileMode]::Create,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

function Remove-TicketboxKnownPublicationDirectory([string]$Path, [string]$PublishRoot) {
    $canonical = Assert-TicketboxNoReparsePath -Path $Path -AllowedRoot $PublishRoot -InspectTree
    if (Test-Path -LiteralPath $canonical) {
        Remove-Item -LiteralPath $canonical -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $canonical) {
        throw "Known publication directory still exists after cleanup: $canonical"
    }
}

function Read-TicketboxDirectoryPublicationReceipt(
    [string]$ReceiptPath,
    [string]$TargetDirectory,
    [string]$BackupDirectory,
    [string]$PublishRoot
) {
    try { $receipt = Get-Content -LiteralPath $ReceiptPath -Encoding UTF8 -Raw | ConvertFrom-Json }
    catch { throw "Windows publication receipt is not valid JSON: $ReceiptPath" }
    $actualNames = [string[]]@($receipt.PSObject.Properties.Name)
    $expectedNames = [string[]]@(
        "schema", "phase", "publish_root", "target_path", "backup_path",
        "staging_path", "had_target", "new_identity", "backup_identity"
    )
    [Array]::Sort($actualNames, [System.StringComparer]::Ordinal)
    [Array]::Sort($expectedNames, [System.StringComparer]::Ordinal)
    $canonicalRoot = [System.IO.Path]::GetFullPath($PublishRoot).TrimEnd("\", "/")
    $canonicalTarget = [System.IO.Path]::GetFullPath([string]$receipt.target_path).TrimEnd("\", "/")
    $canonicalBackup = [System.IO.Path]::GetFullPath([string]$receipt.backup_path).TrimEnd("\", "/")
    $canonicalStaging = [System.IO.Path]::GetFullPath([string]$receipt.staging_path).TrimEnd("\", "/")
    $pathsAreDistinct = @($canonicalTarget, $canonicalBackup, $canonicalStaging) |
        Select-Object -Unique
    $pathsHaveExactParent = @($canonicalTarget, $canonicalBackup, $canonicalStaging) |
        Where-Object {
            -not ([System.IO.Directory]::GetParent($_).FullName.TrimEnd("\", "/")).Equals(
                $canonicalRoot,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
    if (
        ($actualNames -join "`n") -cne ($expectedNames -join "`n") -or
        [string]$receipt.schema -cne "ticketbox-directory-publication-v1" -or
        [string]$receipt.phase -notin @("prepared", "backed_up", "promoted") -or
        -not ([System.IO.Path]::GetFullPath([string]$receipt.publish_root).TrimEnd("\", "/")).Equals($canonicalRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $canonicalTarget.Equals([System.IO.Path]::GetFullPath($TargetDirectory).TrimEnd("\", "/"), [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $canonicalBackup.Equals([System.IO.Path]::GetFullPath($BackupDirectory).TrimEnd("\", "/"), [System.StringComparison]::OrdinalIgnoreCase) -or
        @($pathsAreDistinct).Count -ne 3 -or
        @($pathsHaveExactParent).Count -ne 0
    ) {
        throw "Windows publication receipt paths or schema do not match the requested publication."
    }
    Assert-TicketboxNoReparsePath -Path ([string]$receipt.staging_path) -AllowedRoot $PublishRoot | Out-Null
    return $receipt
}

function Recover-TicketboxDirectoryPublication {
    param(
        [Parameter(Mandatory = $true)][string]$TargetDirectory,
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$PublishRoot
    )
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
        if (Test-Path -LiteralPath $BackupDirectory) {
            throw "Last-known-good backup exists without a publication receipt; refusing to guess: $BackupDirectory"
        }
        return
    }
    Assert-TicketboxNoReparsePath -Path $ReceiptPath -AllowedRoot $PublishRoot | Out-Null
    $receipt = Read-TicketboxDirectoryPublicationReceipt $ReceiptPath $TargetDirectory $BackupDirectory $PublishRoot
    $staging = [string]$receipt.staging_path
    $phase = [string]$receipt.phase
    $targetExists = Test-Path -LiteralPath $TargetDirectory -PathType Container
    $backupExists = Test-Path -LiteralPath $BackupDirectory -PathType Container
    $stagingExists = Test-Path -LiteralPath $staging -PathType Container
    $targetIsNew = $targetExists -and (Test-TicketboxDirectoryPublicationIdentity $TargetDirectory $receipt.new_identity)
    $targetIsOld = $targetExists -and [bool]$receipt.had_target -and (Test-TicketboxDirectoryPublicationIdentity $TargetDirectory $receipt.backup_identity)
    $backupIsOld = $backupExists -and [bool]$receipt.had_target -and (Test-TicketboxDirectoryPublicationIdentity $BackupDirectory $receipt.backup_identity)
    $stagingIsNew = $stagingExists -and (Test-TicketboxDirectoryPublicationIdentity $staging $receipt.new_identity)
    if (
        ($targetExists -and -not $targetIsNew -and -not $targetIsOld) -or
        ($backupExists -and -not $backupIsOld) -or
        ($stagingExists -and -not $stagingIsNew)
    ) {
        throw "Windows publication recovery found an unknown target/backup/staging directory; nothing was deleted."
    }

    if (-not $targetExists) {
        if ([bool]$receipt.had_target) {
            if (-not $backupIsOld) {
                throw "Published target is missing and no verified last-known-good backup is available."
            }
            Move-Item -LiteralPath $BackupDirectory -Destination $TargetDirectory
            if (-not (Test-TicketboxDirectoryPublicationIdentity $TargetDirectory $receipt.backup_identity)) {
                throw "Restored last-known-good publication failed identity verification."
            }
            if ($stagingIsNew) { Remove-TicketboxKnownPublicationDirectory $staging $PublishRoot }
            Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction Stop
            return
        }
        if ($backupExists -or -not $stagingIsNew -or $phase -ne "prepared") {
            throw "Initial publication recovery has no verified staging directory."
        }
        Move-Item -LiteralPath $staging -Destination $TargetDirectory
        if (-not (Test-TicketboxDirectoryPublicationIdentity $TargetDirectory $receipt.new_identity)) {
            throw "Recovered initial publication failed identity verification."
        }
        Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction Stop
        return
    }

    if ($targetIsNew) {
        if (
            $stagingExists -or
            ($backupExists -and -not $backupIsOld) -or
            ([bool]$receipt.had_target -and -not $backupExists -and $phase -ne "promoted")
        ) {
            throw "Promoted publication has an invalid residual staging/backup combination."
        }
        if ($backupIsOld) { Remove-TicketboxKnownPublicationDirectory $BackupDirectory $PublishRoot }
        Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction Stop
        return
    }
    if ($targetIsOld -and -not $backupExists -and $stagingIsNew -and $phase -eq "prepared") {
        Remove-TicketboxKnownPublicationDirectory $staging $PublishRoot
        Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction Stop
        return
    }
    throw "Windows publication recovery state is not one of the validated interruption states; nothing was deleted."
}

function Publish-TicketboxRecoverableDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$StagingDirectory,
        [Parameter(Mandatory = $true)][string]$TargetDirectory,
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][string]$ReceiptPath,
        [Parameter(Mandatory = $true)][string]$PublishRoot,
        [scriptblock]$ValidatePublished
    )
    Recover-TicketboxDirectoryPublication $TargetDirectory $BackupDirectory $ReceiptPath $PublishRoot
    if (Test-Path -LiteralPath $BackupDirectory) {
        throw "Last-known-good backup remains after recovery: $BackupDirectory"
    }
    Assert-TicketboxNoReparsePath -Path $StagingDirectory -AllowedRoot $PublishRoot -InspectTree | Out-Null
    Assert-TicketboxNoReparsePath -Path $TargetDirectory -AllowedRoot $PublishRoot | Out-Null
    $newIdentity = Get-TicketboxDirectoryPublicationIdentity $StagingDirectory
    $hadTarget = Test-Path -LiteralPath $TargetDirectory -PathType Container
    $backupIdentity = if ($hadTarget) { Get-TicketboxDirectoryPublicationIdentity $TargetDirectory } else { $null }
    $receipt = [ordered]@{
        schema = "ticketbox-directory-publication-v1"
        phase = "prepared"
        publish_root = [System.IO.Path]::GetFullPath($PublishRoot)
        target_path = [System.IO.Path]::GetFullPath($TargetDirectory)
        backup_path = [System.IO.Path]::GetFullPath($BackupDirectory)
        staging_path = [System.IO.Path]::GetFullPath($StagingDirectory)
        had_target = $hadTarget
        new_identity = $newIdentity
        backup_identity = $backupIdentity
    }
    Write-TicketboxDirectoryPublicationReceipt $ReceiptPath $receipt
    try {
        if ($hadTarget) {
            Move-Item -LiteralPath $TargetDirectory -Destination $BackupDirectory
            $receipt.phase = "backed_up"
            Write-TicketboxDirectoryPublicationReceipt $ReceiptPath $receipt
        }
        Move-Item -LiteralPath $StagingDirectory -Destination $TargetDirectory
        $receipt.phase = "promoted"
        Write-TicketboxDirectoryPublicationReceipt $ReceiptPath $receipt
        if (-not (Test-TicketboxDirectoryPublicationIdentity $TargetDirectory $newIdentity)) {
            throw "Promoted publication does not match the validated staging identity."
        }
        if ($null -ne $ValidatePublished) { & $ValidatePublished $TargetDirectory }
    }
    catch {
        $publishFailure = $_
        if (Test-TicketboxDirectoryPublicationIdentity $TargetDirectory $newIdentity) {
            Remove-TicketboxKnownPublicationDirectory $TargetDirectory $PublishRoot
        }
        if ($hadTarget -and (Test-TicketboxDirectoryPublicationIdentity $BackupDirectory $backupIdentity)) {
            Move-Item -LiteralPath $BackupDirectory -Destination $TargetDirectory
        }
        Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction SilentlyContinue
        throw $publishFailure
    }
    if (Test-Path -LiteralPath $BackupDirectory) {
        Remove-TicketboxKnownPublicationDirectory $BackupDirectory $PublishRoot
    }
    Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction Stop
}

function Get-TicketboxPathItemOrNull([string]$Path) {
    try { return Get-Item -LiteralPath $Path -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] { return $null }
}

function Assert-TicketboxNoReparsePath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$AllowedRoot,
        [switch]$AllowRoot,
        [switch]$InspectTree
    )
    $rootFull = [System.IO.Path]::GetFullPath($AllowedRoot)
    $candidateFull = [System.IO.Path]::GetFullPath($Path)
    $root = $rootFull.TrimEnd("\", "/")
    $candidate = $candidateFull.TrimEnd("\", "/")
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    $isRoot = $candidate.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)
    if ((-not $isRoot -and -not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) -or ($isRoot -and -not $AllowRoot)) {
        throw "Refusing Windows build mutation outside the allowed root: $candidate"
    }

    $probe = $candidateFull
    while ($probe.Length -gt 0) {
        $item = Get-TicketboxPathItemOrNull $probe
        if (
            $null -ne $item -and
            ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "Windows build path has a reparse-point ancestor: $($item.FullName)"
        }
        $parent = [System.IO.Directory]::GetParent($probe)
        if ($null -eq $parent) { break }
        $probe = $parent.FullName
    }

    $candidateItem = Get-TicketboxPathItemOrNull $candidate
    if (-not $InspectTree -or $null -eq $candidateItem -or -not $candidateItem.PSIsContainer) {
        return $candidate
    }
    $pending = New-Object System.Collections.Generic.Queue[string]
    $pending.Enqueue($candidate)
    while ($pending.Count -gt 0) {
        $directory = $pending.Dequeue()
        foreach ($child in Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop) {
            if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Windows build tree contains a reparse point: $($child.FullName)"
            }
            if ($child.PSIsContainer) { $pending.Enqueue($child.FullName) }
        }
    }
    return $candidate
}

function Get-TicketboxExecutionTreeEvidence(
    [string]$PythonPath,
    [object[]]$Components
) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Python execution-tree interpreter is missing: $PythonPath"
    }
    $records = @()
    foreach ($component in $Components) {
        $label = [string]$component.label
        $root = [System.IO.Path]::GetFullPath([string]$component.path)
        if ($label.Length -eq 0 -or -not (Test-Path -LiteralPath $root -PathType Container)) {
            throw "Python execution-tree component is invalid: $label ($root)"
        }
        Assert-TicketboxNoReparsePath -Path $root -AllowedRoot $root -AllowRoot -InspectTree | Out-Null
        $paths = @(
            Get-ChildItem -LiteralPath $root -Recurse -File -Force |
                ForEach-Object { $_.FullName }
        )
        $records += [ordered]@{
            label = $label
            snapshot = Get-TicketboxFileSetSnapshot $root $paths
        }
    }
    $orderedRecords = @($records | Sort-Object { [string]$_.label })
    $summaryComponents = @(
        $orderedRecords | ForEach-Object {
            [ordered]@{
                label = [string]$_.label
                algorithm = [string]$_.snapshot.algorithm
                fingerprint = [string]$_.snapshot.fingerprint
                file_count = @($_.snapshot.files).Count
            }
        }
    )
    $core = [ordered]@{
        interpreter = Get-TicketboxFileEvidence (Split-Path -Parent $PythonPath) $PythonPath
        components = $summaryComponents
    }
    $json = $core | ConvertTo-Json -Depth 12 -Compress
    return [ordered]@{
        algorithm = "SHA-256"
        fingerprint = Get-TicketboxSha256HexFromText $json
        interpreter = $core.interpreter
        components = $orderedRecords
    }
}

function Get-TicketboxPythonExecutionTreeSnapshot([string]$PythonPath) {
    $probe = @'
import json, site, sys
roots = [('environment', sys.prefix), ('base-runtime', sys.base_prefix)]
for index, path in enumerate(site.getsitepackages()):
    roots.append((f'site-packages-{index}', path))
print(json.dumps({'executable': sys.executable, 'roots': roots}))
'@
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $PythonPath -I -B -c $probe 2>&1)
        $probeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($probeExitCode -ne 0) {
        throw "Python execution-tree probe failed (exit=$probeExitCode): $($output -join [Environment]::NewLine)"
    }
    try { $layout = ($output -join [Environment]::NewLine) | ConvertFrom-Json }
    catch { throw "Python execution-tree probe returned invalid JSON." }
    $unique = @{}
    foreach ($entry in @($layout.roots)) {
        $label = [string]$entry[0]
        $path = [System.IO.Path]::GetFullPath([string]$entry[1]).TrimEnd("\", "/")
        $key = $path.ToUpperInvariant()
        if (-not $unique.ContainsKey($key)) {
            $unique[$key] = [ordered]@{ label = $label; path = $path }
        }
        elseif (-not ([string]$unique[$key].label).Contains($label)) {
            $unique[$key].label = "$($unique[$key].label)+$label"
        }
    }
    $collapsed = New-Object System.Collections.ArrayList
    foreach ($entry in @($unique.Values | Sort-Object { ([string]$_.path).Length })) {
        $entryPath = [string]$entry.path
        $ancestor = @(
            $collapsed | Where-Object {
                $ancestorPath = ([string]$_.path).TrimEnd("\", "/")
                $entryPath.StartsWith(
                    $ancestorPath + [System.IO.Path]::DirectorySeparatorChar,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
        ) | Select-Object -First 1
        if ($null -ne $ancestor) {
            $ancestor.label = "$($ancestor.label)+$($entry.label)"
        }
        else {
            [void]$collapsed.Add($entry)
        }
    }
    return Get-TicketboxExecutionTreeEvidence ([string]$layout.executable) @($collapsed)
}

function Assert-TicketboxExecutionTreeEvidence([object]$Evidence) {
    if (
        $null -eq $Evidence -or
        [string]$Evidence.algorithm -cne "SHA-256" -or
        [string]$Evidence.fingerprint -notmatch '^[0-9a-f]{64}$' -or
        [string]$Evidence.interpreter.sha256 -notmatch '^[0-9a-f]{64}$' -or
        @($Evidence.components).Count -eq 0
    ) {
        throw "Frozen backend Python execution-tree evidence is malformed."
    }
    $summaryComponents = @(
        $Evidence.components | ForEach-Object {
            $snapshot = $_.snapshot
            if ($null -ne $snapshot) {
                [ordered]@{
                    label = [string]$_.label
                    algorithm = [string]$snapshot.algorithm
                    fingerprint = [string]$snapshot.fingerprint
                    file_count = @($snapshot.files).Count
                }
            }
            else {
                [ordered]@{
                    label = [string]$_.label
                    algorithm = [string]$_.algorithm
                    fingerprint = [string]$_.fingerprint
                    file_count = [int64]$_.file_count
                }
            }
        }
    )
    $core = [ordered]@{ interpreter = $Evidence.interpreter; components = $summaryComponents }
    $actualFingerprint = Get-TicketboxSha256HexFromText ($core | ConvertTo-Json -Depth 12 -Compress)
    if ($actualFingerprint -cne [string]$Evidence.fingerprint) {
        throw "Frozen backend Python execution-tree evidence fingerprint is inconsistent."
    }
    foreach ($component in @($Evidence.components)) {
        $componentFingerprint = if ($null -ne $component.snapshot) {
            [string]$component.snapshot.fingerprint
        }
        else { [string]$component.fingerprint }
        if (
            [string]$component.label -eq "" -or
            $componentFingerprint -notmatch '^[0-9a-f]{64}$'
        ) {
            throw "Frozen backend Python execution-tree component evidence is malformed."
        }
    }
}

function Get-TicketboxCompactExecutionTreeEvidence([object]$Evidence) {
    Assert-TicketboxExecutionTreeEvidence $Evidence
    $components = @(
        $Evidence.components | ForEach-Object {
            [ordered]@{
                label = [string]$_.label
                algorithm = [string]$_.snapshot.algorithm
                fingerprint = [string]$_.snapshot.fingerprint
                file_count = @($_.snapshot.files).Count
            }
        }
    )
    return [ordered]@{
        algorithm = [string]$Evidence.algorithm
        fingerprint = [string]$Evidence.fingerprint
        interpreter = $Evidence.interpreter
        components = $components
    }
}

function Test-TicketboxForbiddenDatabasePayloadName([string]$Name) {
    $normalized = $Name.Replace("\\", "/").Trim([char[]]@("/", "'", '"')).ToLowerInvariant()
    if ($normalized.StartsWith("_internal/")) {
        $normalized = $normalized.Substring("_internal/".Length)
    }
    $moduleName = $normalized.Replace("/", ".")
    foreach ($forbidden in $script:TicketboxForbiddenDatabasePayloadSegments) {
        if ($moduleName -eq $forbidden -or $moduleName.StartsWith("$forbidden.")) {
            return $true
        }
    }
    $leaf = [System.IO.Path]::GetFileName($normalized)
    return $leaf -match '^(?:_?sqlite3|libsqlite3|mysqlclient|libmysql|libmariadb|mariadb)(?:[-_.].*)?$'
}

function Assert-TicketboxPostgresOnlyFrozenPayload {
    param(
        [Parameter(Mandatory = $true)][string]$DistDir,
        [Parameter(Mandatory = $true)][string[]]$ArchiveListing
    )
    if (-not (Test-Path -LiteralPath $DistDir -PathType Container)) {
        throw "Frozen backend payload directory is missing: $DistDir"
    }
    $violations = New-Object System.Collections.Generic.List[string]
    foreach ($file in Get-ChildItem -LiteralPath $DistDir -Recurse -File -Force) {
        $relativePath = Get-TicketboxRelativePath $DistDir $file.FullName
        if (Test-TicketboxForbiddenDatabasePayloadName $relativePath) {
            $violations.Add($relativePath)
        }
        if ($file.Extension -ieq ".zip") {
            Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
            $zip = [System.IO.Compression.ZipFile]::OpenRead($file.FullName)
            try {
                foreach ($entry in $zip.Entries) {
                    if (Test-TicketboxForbiddenDatabasePayloadName $entry.FullName) {
                        $violations.Add("$relativePath::$($entry.FullName)")
                    }
                }
            }
            finally {
                $zip.Dispose()
            }
        }
    }

    $archiveEntryCount = 0
    foreach ($line in $ArchiveListing) {
        $match = [regex]::Match([string]$line, ",\s*'([^']+)'\s*$")
        if (-not $match.Success) { continue }
        $archiveEntryCount++
        $entryName = $match.Groups[1].Value
        if (Test-TicketboxForbiddenDatabasePayloadName $entryName) {
            $violations.Add("embedded::$entryName")
        }
    }
    if ($archiveEntryCount -eq 0) {
        throw "PyInstaller archive listing contained no parseable payload entries."
    }
    if ($violations.Count -gt 0) {
        $sample = @($violations | Select-Object -First 12) -join ", "
        throw "Frozen backend contains forbidden SQLite/MySQL/MariaDB payloads: $sample"
    }
}

function Get-TicketboxWindowsBuildLockInputSnapshot([string]$BackendRoot) {
    return Get-TicketboxFileSetSnapshot $BackendRoot @(
        (Join-Path $BackendRoot "requirements.txt"),
        (Join-Path $BackendRoot "requirements-build.txt")
    )
}

function Assert-TicketboxBuildToolSourceCommon(
    [object]$Source,
    [string]$ExpectedVersion,
    [string]$ArchiveExtension,
    [string]$Label
) {
    if ($null -eq $Source) { throw "Windows build toolchain lacks $Label source identity." }
    $archiveName = [string]$Source.archive_name
    $urlText = [string]$Source.url
    $uri = $null
    if (
        [string]$Source.version -cne $ExpectedVersion -or
        $archiveName.Length -eq 0 -or
        [System.IO.Path]::GetFileName($archiveName) -cne $archiveName -or
        -not $archiveName.EndsWith($ArchiveExtension, [System.StringComparison]::OrdinalIgnoreCase) -or
        [string]$Source.sha256 -notmatch '^[0-9a-fA-F]{64}$'
    ) {
        throw "Windows build toolchain $Label archive identity is invalid."
    }
    try { $uri = New-Object System.Uri($urlText, [System.UriKind]::Absolute) }
    catch { throw "Windows build toolchain $Label URL is invalid." }
    if (
        $uri.Scheme -cne "https" -or
        $uri.UserInfo.Length -ne 0 -or
        $uri.Fragment.Length -ne 0 -or
        [System.Uri]::UnescapeDataString(
            $uri.AbsolutePath.Substring($uri.AbsolutePath.LastIndexOf("/") + 1)
        ) -cne $archiveName
    ) {
        throw "Windows build toolchain $Label source must be an exact credential-free HTTPS archive URL."
    }
}

function Assert-TicketboxBuildToolRelativePath([string]$Value, [string]$Label) {
    $normalized = $Value.Replace("/", "\")
    if (
        $normalized.Length -eq 0 -or
        [System.IO.Path]::IsPathRooted($normalized) -or
        $normalized.Contains(":") -or
        @($normalized.Split("\") | Where-Object { $_ -eq "" -or $_ -eq "." -or $_ -eq ".." }).Count -gt 0
    ) {
        throw "Windows build toolchain $Label must be a safe relative path."
    }
}

function Read-TicketboxBackendBuildToolSources([object]$Config) {
    $uv = $Config.build_tool_sources.uv
    $python = $Config.build_tool_sources.python
    $inno = $Config.build_tool_sources.inno_setup
    Assert-TicketboxBuildToolSourceCommon $uv ([string]$Config.uv_version) ".zip" "uv"
    Assert-TicketboxBuildToolSourceCommon $python ([string]$Config.python_version) ".tar.gz" "Python"
    Assert-TicketboxBuildToolSourceCommon $inno ([string]$inno.version) ".exe" "Inno Setup"

    foreach ($entry in @(
        @($uv.executable_relative_path, $uv.executable_sha256, "uv executable"),
        @($python.archive_payload_root, "", "Python archive payload root"),
        @($python.executable_relative_path, $python.executable_sha256, "Python executable"),
        @($python.runtime_relative_path, $python.runtime_sha256, "Python runtime"),
        @($inno.compiler_relative_path, $inno.compiler_sha256, "Inno compiler")
    )) {
        Assert-TicketboxBuildToolRelativePath ([string]$entry[0]) ([string]$entry[2])
        if ([string]$entry[1] -ne "" -and [string]$entry[1] -notmatch '^[0-9a-fA-F]{64}$') {
            throw "Windows build toolchain $($entry[2]) SHA-256 is invalid."
        }
    }
    if ([string]$inno.version -notmatch '^\d+\.\d+\.\d+$') {
        throw "Windows build toolchain Inno Setup version must be exact."
    }
    return [pscustomobject]@{
        uv = $uv
        python = $python
        inno = $inno
    }
}

function Read-TicketboxWindowsBuildToolchain([string]$BackendRoot) {
    $path = Join-Path $BackendRoot $script:TicketboxBuildToolchainConfigRelativePath
    $lockPath = Join-Path $BackendRoot "requirements-build.lock"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Windows build toolchain contract is missing: $path"
    }
    try {
        $config = Get-Content -LiteralPath $path -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "Windows build toolchain contract is not valid JSON: $path"
    }
    if ([int]$config.schema_version -ne 1) {
        throw "Unsupported Windows build toolchain schema: $($config.schema_version)"
    }
    foreach ($name in @("python_version", "uv_version", "pyinstaller_version")) {
        $value = [string]$config.$name
        if ($value -notmatch '^\d+\.\d+\.\d+$') {
            throw "Windows build toolchain $name must be an exact three-part version."
        }
    }
    $sources = Read-TicketboxBackendBuildToolSources $config
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        throw "Windows build dependency lock is missing: $lockPath"
    }
    $lockText = Get-Content -LiteralPath $lockPath -Encoding UTF8 -Raw
    $lockInputMatch = [regex]::Match($lockText, $script:TicketboxBuildLockInputHeaderPattern)
    if (-not $lockInputMatch.Success) {
        throw "Windows build dependency lock lacks its requirements input fingerprint."
    }
    $lockInputSnapshot = Get-TicketboxWindowsBuildLockInputSnapshot $BackendRoot
    if ($lockInputMatch.Groups[1].Value -cne $lockInputSnapshot.fingerprint) {
        throw "Windows build dependency lock is stale for requirements.txt or requirements-build.txt."
    }
    $pyInstallerMatch = [regex]::Match(
        $lockText,
        '(?m)^pyinstaller==(\d+\.\d+\.\d+)(?:\s|$)'
    )
    if (
        -not $pyInstallerMatch.Success -or
        $pyInstallerMatch.Groups[1].Value -cne [string]$config.pyinstaller_version
    ) {
        throw "Windows build dependency lock does not match the contracted PyInstaller version."
    }
    return [pscustomobject]@{
        path = $path
        lock_path = $lockPath
        python_version = [string]$config.python_version
        uv_version = [string]$config.uv_version
        pyinstaller_version = [string]$config.pyinstaller_version
        uv_source = $sources.uv
        python_source = $sources.python
        inno_source = $sources.inno
        lock_input_snapshot = $lockInputSnapshot
    }
}

function Get-TicketboxInstalledDistributionSnapshot([string[]]$Entries) {
    $sorted = [string[]]@(
        $Entries |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_.Length -gt 0 }
    )
    [Array]::Sort($sorted, [System.StringComparer]::OrdinalIgnoreCase)
    $text = ($sorted -join [Environment]::NewLine) + [Environment]::NewLine
    return [ordered]@{
        algorithm = "SHA-256"
        fingerprint = Get-TicketboxSha256HexFromText $text
        entries = @($sorted)
    }
}

function Get-TicketboxNormalizedBackendToolSource([object]$Source, [string]$Kind) {
    $normalized = [ordered]@{
        version = [string]$Source.version
        archive_name = [string]$Source.archive_name
        url = [string]$Source.url
        archive_sha256 = ([string]$Source.sha256).ToLowerInvariant()
    }
    if ($Kind -ceq "uv") {
        $normalized["executable_relative_path"] = [string]$Source.executable_relative_path
        $normalized["executable_sha256"] = ([string]$Source.executable_sha256).ToLowerInvariant()
    }
    elseif ($Kind -ceq "python") {
        $normalized["archive_payload_root"] = [string]$Source.archive_payload_root
        $normalized["executable_relative_path"] = [string]$Source.executable_relative_path
        $normalized["executable_sha256"] = ([string]$Source.executable_sha256).ToLowerInvariant()
        $normalized["runtime_relative_path"] = [string]$Source.runtime_relative_path
        $normalized["runtime_sha256"] = ([string]$Source.runtime_sha256).ToLowerInvariant()
    }
    else {
        throw "Unsupported backend build tool source kind: $Kind"
    }
    return $normalized
}

function New-TicketboxBackendBuildToolchainProvenance {
    param(
        [Parameter(Mandatory = $true)][string]$BackendRoot,
        [Parameter(Mandatory = $true)][object]$Config,
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string]$PythonSourcePath,
        [Parameter(Mandatory = $true)][string]$PythonVersion,
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][string]$UvVersion,
        [Parameter(Mandatory = $true)][string]$PyInstallerPath,
        [Parameter(Mandatory = $true)][string]$PyInstallerVersion,
        [Parameter(Mandatory = $true)][string[]]$InstalledDistributions,
        [Parameter(Mandatory = $true)][object]$PythonExecutionTree
    )
    if (
        $PythonVersion -cne $Config.python_version -or
        $UvVersion -cne $Config.uv_version -or
        $PyInstallerVersion -cne $Config.pyinstaller_version
    ) {
        throw "Actual Windows build toolchain versions do not match the checked-in contract."
    }
    $pythonSourceHash = Get-TicketboxFileSha256 $PythonSourcePath
    $uvSourceHash = Get-TicketboxFileSha256 $UvPath
    if (
        $pythonSourceHash -cne ([string]$Config.python_source.executable_sha256).ToLowerInvariant() -or
        $uvSourceHash -cne ([string]$Config.uv_source.executable_sha256).ToLowerInvariant()
    ) {
        throw "Actual Windows backend build tools do not match their pinned source payload hashes."
    }
    $distributionSnapshot = Get-TicketboxInstalledDistributionSnapshot $InstalledDistributions
    $pyinstallerDistribution = "pyinstaller==$PyInstallerVersion"
    if (@($distributionSnapshot.entries | Where-Object { $_ -ieq $pyinstallerDistribution }).Count -ne 1) {
        throw "Installed distribution snapshot does not contain the exact PyInstaller version."
    }
    Assert-TicketboxExecutionTreeEvidence $PythonExecutionTree
    return [ordered]@{
        contract = Get-TicketboxFileEvidence $BackendRoot $Config.path
        python = [ordered]@{
            version = $PythonVersion
            source = Get-TicketboxNormalizedBackendToolSource $Config.python_source "python"
            executable = Get-TicketboxFileEvidence $BackendRoot $PythonPath
        }
        uv = [ordered]@{
            version = $UvVersion
            source = Get-TicketboxNormalizedBackendToolSource $Config.uv_source "uv"
            executable = Get-TicketboxFileEvidence (Split-Path -Parent $UvPath) $UvPath
        }
        pyinstaller = [ordered]@{
            version = $PyInstallerVersion
            executable = Get-TicketboxFileEvidence $BackendRoot $PyInstallerPath
        }
        requirements = [ordered]@{
            input = Get-TicketboxFileEvidence $BackendRoot (Join-Path $BackendRoot "requirements-build.txt")
            lock = Get-TicketboxFileEvidence $BackendRoot $Config.lock_path
            input_snapshot = $Config.lock_input_snapshot
        }
        installed_distributions = $distributionSnapshot
        python_execution_tree = Get-TicketboxCompactExecutionTreeEvidence $PythonExecutionTree
        reproducibility_scope = "exact-build-tool-identities-and-complete-interpreter-execution-tree; frozen-bytes-not-claimed-reproducible"
    }
}

function Assert-TicketboxBackendToolchainEvidence([string]$BackendRoot, [object]$Recorded) {
    if ($null -eq $Recorded) { throw "Frozen backend manifest lacks build toolchain evidence." }
    $config = Read-TicketboxWindowsBuildToolchain $BackendRoot
    if (
        [string]$Recorded.python.version -cne $config.python_version -or
        [string]$Recorded.uv.version -cne $config.uv_version -or
        [string]$Recorded.pyinstaller.version -cne $config.pyinstaller_version
    ) {
        throw "Frozen backend toolchain versions do not match the checked-in contract."
    }
    Assert-TicketboxStructuredEvidence "Frozen backend toolchain contract" $Recorded.contract (Get-TicketboxFileEvidence $BackendRoot $config.path)
    $expectedRequirements = [ordered]@{
        input = Get-TicketboxFileEvidence $BackendRoot (Join-Path $BackendRoot "requirements-build.txt")
        lock = Get-TicketboxFileEvidence $BackendRoot $config.lock_path
        input_snapshot = $config.lock_input_snapshot
    }
    Assert-TicketboxStructuredEvidence "Frozen backend build requirements" $Recorded.requirements $expectedRequirements
    Assert-TicketboxStructuredEvidence `
        "Frozen backend Python source contract" `
        $Recorded.python.source `
        (Get-TicketboxNormalizedBackendToolSource $config.python_source "python")
    Assert-TicketboxStructuredEvidence `
        "Frozen backend uv source contract" `
        $Recorded.uv.source `
        (Get-TicketboxNormalizedBackendToolSource $config.uv_source "uv")
    foreach ($name in @("python", "uv", "pyinstaller")) {
        $evidence = $Recorded.$name.executable
        if (
            $null -eq $evidence -or
            [int64]$evidence.size -le 0 -or
            [string]$evidence.sha256 -notmatch '^[0-9a-f]{64}$'
        ) {
            throw "Frozen backend $name executable evidence is malformed."
        }
    }
    $entries = @($Recorded.installed_distributions.entries | ForEach-Object { [string]$_ })
    $actualSnapshot = Get-TicketboxInstalledDistributionSnapshot $entries
    Assert-TicketboxStructuredEvidence "Frozen backend installed distributions" $Recorded.installed_distributions $actualSnapshot
    $pyinstallerDistribution = "pyinstaller==$($config.pyinstaller_version)"
    if (@($entries | Where-Object { $_ -ieq $pyinstallerDistribution }).Count -ne 1) {
        throw "Frozen backend distribution evidence lacks the contracted PyInstaller version."
    }
    Assert-TicketboxExecutionTreeEvidence $Recorded.python_execution_tree
}

function Get-TicketboxBackendVersion([string]$BackendRoot) {
    $versionFile = Join-Path $BackendRoot "app\version.py"
    if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) {
        throw "Missing backend version source: $versionFile"
    }
    $content = Get-Content -LiteralPath $versionFile -Encoding UTF8 -Raw
    $match = [regex]::Match($content, '(?m)^\s*BACKEND_VERSION\s*=\s*"([^"]+)"\s*$')
    if (-not $match.Success) {
        throw "Cannot read BACKEND_VERSION from app\version.py."
    }
    return $match.Groups[1].Value
}

function Get-TicketboxBackendSourcePaths([string]$BackendRoot) {
    $requiredFiles = @(
        "alembic.ini",
        "requirements.txt",
        "requirements-build.txt",
        "requirements-build.lock",
        $script:TicketboxBuildToolchainConfigRelativePath,
        "packaging\prepare_windows_build_toolchain.ps1",
        "packaging\launch.py",
        "packaging\ticketbox-backend.spec",
        "scripts\build_backend_exe.ps1",
        "scripts\windows_build_provenance.ps1",
        "scripts\windows_backend_build_provenance.ps1"
    )
    $paths = @()
    foreach ($relativePath in $requiredFiles) {
        $path = Join-Path $BackendRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Frozen backend source set is missing: $path"
        }
        $paths += (Resolve-Path -LiteralPath $path).Path
    }
    foreach ($relativeDir in @("app", "migrations")) {
        $directory = Join-Path $BackendRoot $relativeDir
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            throw "Frozen backend source directory is missing: $directory"
        }
        $paths += @(
            Get-ChildItem -LiteralPath $directory -Recurse -File |
                Where-Object {
                    $_.Extension -notin @(".pyc", ".pyo") -and
                    $_.FullName -notmatch '[\\/]__pycache__[\\/]'
                } |
                ForEach-Object { $_.FullName }
        )
    }
    return @(Get-TicketboxOrdinalSortedPaths $paths)
}

function Get-TicketboxBackendSourceSnapshot([string]$BackendRoot) {
    return Get-TicketboxFileSetSnapshot $BackendRoot (Get-TicketboxBackendSourcePaths $BackendRoot)
}

function Get-TicketboxBackendPayloadSnapshot([string]$DistDir) {
    if (-not (Test-Path -LiteralPath $DistDir -PathType Container)) {
        throw "Frozen backend directory does not exist: $DistDir"
    }
    $manifestPath = Join-Path $DistDir $script:TicketboxBackendBuildManifestName
    $paths = @(
        Get-ChildItem -LiteralPath $DistDir -Recurse -File |
            Where-Object { $_.FullName -ne $manifestPath } |
            ForEach-Object { $_.FullName }
    )
    return Get-TicketboxFileSetSnapshot $DistDir $paths
}

function Write-TicketboxBackendBuildManifest(
    [string]$BackendRoot,
    [string]$DistDir,
    [object]$ToolchainProvenance,
    [object]$SourceSnapshot
) {
    if ($null -eq $ToolchainProvenance) {
        throw "Frozen backend manifest requires actual build toolchain provenance."
    }
    if ($null -eq $SourceSnapshot) {
        throw "Frozen backend manifest requires the exact pre-freeze source snapshot."
    }
    $payload = Get-TicketboxBackendPayloadSnapshot $DistDir
    $manifest = [ordered]@{
        schema_version = $script:TicketboxBackendBuildManifestSchema
        artifact_type = "ticketbox-frozen-backend"
        backend_version = Get-TicketboxBackendVersion $BackendRoot
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        toolchain = $ToolchainProvenance
        source = $SourceSnapshot
        payload = [ordered]@{
            algorithm = $payload.algorithm
            fingerprint = $payload.fingerprint
            files = @($payload.files)
            executable = Get-TicketboxFileEvidence $DistDir (Join-Path $DistDir "ticketbox-backend.exe")
        }
    }
    $manifestPath = Join-Path $DistDir $script:TicketboxBackendBuildManifestName
    Write-TicketboxJsonFile $manifestPath $manifest
    return $manifestPath
}

function Assert-TicketboxBackendBuildManifest([string]$BackendRoot, [string]$DistDir) {
    $manifestPath = Join-Path $DistDir $script:TicketboxBackendBuildManifestName
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Frozen backend lacks build provenance; rebuild it before packaging."
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "Frozen backend build provenance is not valid JSON: $manifestPath"
    }
    if (
        $manifest.schema_version -ne $script:TicketboxBackendBuildManifestSchema -or
        $manifest.artifact_type -cne "ticketbox-frozen-backend"
    ) {
        throw "Frozen backend build provenance schema or artifact type is unsupported."
    }
    if ($manifest.backend_version -cne (Get-TicketboxBackendVersion $BackendRoot)) {
        throw "Frozen backend version is stale; rebuild before packaging."
    }
    Assert-TicketboxBackendToolchainEvidence $BackendRoot $manifest.toolchain
    try {
        Assert-TicketboxFileSetSnapshot "Frozen backend source" $manifest.source (Get-TicketboxBackendSourceSnapshot $BackendRoot)
    }
    catch {
        throw "Frozen backend source evidence is stale; rebuild before packaging. $($_.Exception.Message)"
    }
    try {
        Assert-TicketboxFileSetSnapshot "Frozen backend payload" $manifest.payload (Get-TicketboxBackendPayloadSnapshot $DistDir)
    }
    catch {
        throw "Frozen backend payload evidence is stale or modified. $($_.Exception.Message)"
    }
    $exe = Get-TicketboxFileEvidence $DistDir (Join-Path $DistDir "ticketbox-backend.exe")
    Assert-TicketboxStructuredEvidence "Frozen backend executable" $manifest.payload.executable $exe
    return $manifest
}
