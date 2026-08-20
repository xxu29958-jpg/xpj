#Requires -Version 5.1

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging\windows_installation_safety.ps1')
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging\windows_release_config.ps1')

function Get-XpjTestPostgresContract {
    [CmdletBinding()]
    param()

    $path = Join-Path $PSScriptRoot 'test_postgres_contract.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Test PostgreSQL contract is missing: $path"
    }
    $contract = Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json
    $expectedFields = @(
        'schema_version',
        'application_role',
        'base_database',
        'smoke_database',
        'restore_database',
        'cluster_marker',
        'worker_marker_prefix',
        'ownership_marker_name',
        'deletion_marker_name',
        'credential_name',
        'passfile_name',
        'runtime_root_name',
        'runtime_parent',
        'ports',
        'forbidden_host_ports'
    )
    $actualFields = @($contract.PSObject.Properties.Name)
    if (@(Compare-Object ($expectedFields | Sort-Object) ($actualFields | Sort-Object)).Count -ne 0) {
        throw 'Test PostgreSQL contract fields do not match the supported schema'
    }
    if ($contract.schema_version -ne 7) {
        throw "Unsupported test PostgreSQL contract schema: $($contract.schema_version)"
    }
    foreach ($field in @('application_role', 'base_database', 'smoke_database', 'restore_database', 'cluster_marker', 'worker_marker_prefix', 'ownership_marker_name', 'deletion_marker_name', 'credential_name', 'passfile_name')) {
        if ([string]::IsNullOrWhiteSpace([string]$contract.$field)) {
            throw "Test PostgreSQL contract field is missing: $field"
        }
    }
    foreach ($field in @('application_role', 'base_database', 'smoke_database', 'restore_database')) {
        if ([string]$contract.$field -notmatch '^[a-z][a-z0-9_]{0,62}$') {
            throw "Test PostgreSQL contract database name is invalid: $field"
        }
    }
    if ([string]$contract.cluster_marker -notmatch '^[a-z0-9][a-z0-9_.:-]{0,127}$') {
        throw 'Test PostgreSQL cluster marker is invalid'
    }
    if ([string]$contract.worker_marker_prefix -notmatch '^[a-z0-9][a-z0-9_.:-]{0,127}$') {
        throw 'Test PostgreSQL worker marker prefix is invalid'
    }
    foreach ($field in @('ownership_marker_name', 'deletion_marker_name')) {
        if ([string]$contract.$field -notmatch '^\.[a-z0-9][a-z0-9._-]{0,62}$') {
            throw "Test PostgreSQL lifecycle marker name is invalid: $field"
        }
    }
    foreach ($field in @('credential_name', 'passfile_name')) {
        if ([string]$contract.$field -notmatch '^\.[a-z0-9][a-z0-9._-]{0,62}$') {
            throw "Test PostgreSQL secret file name is invalid: $field"
        }
    }
    if ([string]$contract.runtime_root_name -notmatch '^[a-z0-9][a-z0-9._-]{0,62}$') {
        throw 'Test PostgreSQL runtime root name is invalid'
    }
    if ([string]$contract.runtime_parent -cne 'local_app_data') {
        throw 'Test PostgreSQL runtime parent is invalid'
    }
    $portFields = @($contract.ports.PSObject.Properties.Name)
    if (@(Compare-Object @('gitea', 'local') ($portFields | Sort-Object)).Count -ne 0) {
        throw 'Test PostgreSQL port profiles are invalid'
    }
    $ports = @(
        [int]$contract.ports.gitea,
        [int]$contract.ports.local
    )
    if (@($ports | Where-Object { $_ -lt 1024 -or $_ -gt 65535 }).Count -ne 0) {
        throw 'Test PostgreSQL ports must be unprivileged TCP ports'
    }
    if (@($ports | Sort-Object -Unique).Count -ne $ports.Count) {
        throw 'Test PostgreSQL port profiles must be distinct'
    }
    $forbiddenHostPorts = @($contract.forbidden_host_ports | ForEach-Object { [int]$_ })
    if (
        $forbiddenHostPorts.Count -eq 0 -or
        @($forbiddenHostPorts | Where-Object { $_ -lt 1024 -or $_ -gt 65535 }).Count -ne 0 -or
        @($forbiddenHostPorts | Sort-Object -Unique).Count -ne $forbiddenHostPorts.Count -or
        @($forbiddenHostPorts | Where-Object { $_ -in $ports }).Count -ne 0
    ) {
        throw 'Test PostgreSQL forbidden host ports are invalid'
    }
    $databaseNames = @(
        [string]$contract.base_database,
        [string]$contract.smoke_database,
        [string]$contract.restore_database
    )
    if (@($databaseNames | Sort-Object -Unique).Count -ne $databaseNames.Count) {
        throw 'Test PostgreSQL database roles must be distinct'
    }
    return $contract
}

function ConvertTo-XpjPostgresPolicyVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $match = [regex]::Match(
        $Value,
        '^(?<major>[1-9][0-9]*)\.(?<minor>0|[1-9][0-9]*)(?:\.(?<patch>0|[1-9][0-9]*))?$'
    )
    if (-not $match.Success) {
        throw "Windows release config PostgreSQL $Label is invalid: $Value"
    }
    $patch = if ($match.Groups['patch'].Success) { [int]$match.Groups['patch'].Value } else { 0 }
    return [Version]::new(
        [int]$match.Groups['major'].Value,
        [int]$match.Groups['minor'].Value,
        $patch
    )
}

function Get-XpjPostgresReleasePolicy {
    [CmdletBinding()]
    param()

    $path = Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging\windows-release-config.json'
    $config = Read-TicketboxWindowsReleaseConfig -Path $path
    $policy = $config.postgres_version_policy
    if ($null -eq $policy) {
        throw 'Windows release config has no PostgreSQL version policy'
    }
    $fields = @($policy.PSObject.Properties.Name)
    if (@(Compare-Object @('maximum_exclusive', 'minimum') ($fields | Sort-Object)).Count -ne 0) {
        throw 'Windows release config PostgreSQL version policy fields are invalid'
    }
    $minimum = ConvertTo-XpjPostgresPolicyVersion `
        -Value ([string]$policy.minimum) `
        -Label 'minimum'
    $maximum = ConvertTo-XpjPostgresPolicyVersion `
        -Value ([string]$policy.maximum_exclusive) `
        -Label 'maximum_exclusive'
    if (
        $maximum.Minor -ne 0 -or
        $maximum.Build -ne 0 -or
        $minimum.CompareTo($maximum) -ge 0
    ) {
        throw 'Windows release config PostgreSQL maximum_exclusive must be a later major boundary'
    }
    return [pscustomobject]@{
        Minimum = $minimum
        MaximumExclusive = $maximum
        SupportedMajors = @($minimum.Major..($maximum.Major - 1) | ForEach-Object { [string]$_ })
    }
}

function Get-XpjSupportedPostgresMajorVersions {
    [CmdletBinding()]
    param()

    return @((Get-XpjPostgresReleasePolicy).SupportedMajors)
}

function Get-XpjPostgresBinaryVersion {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $resolvedBin = Resolve-XpjPostgresBin -PostgresBin $PostgresBin
    $output = @(& (Join-Path $resolvedBin 'postgres.exe') --version 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL version probe failed: $resolvedBin"
    }
    $match = [regex]::Match(
        (($output | ForEach-Object { $_.ToString() }) -join "`n").Trim(),
        '^postgres \(PostgreSQL\) (?<version>[1-9][0-9]*\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?)$'
    )
    if (-not $match.Success) {
        throw "PostgreSQL version probe returned an unsupported identity: $resolvedBin"
    }
    return ConvertTo-XpjPostgresPolicyVersion `
        -Value $match.Groups['version'].Value `
        -Label 'runtime version'
}

function Assert-XpjPostgresBinaryWithinReleasePolicy {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $resolvedBin = Resolve-XpjPostgresBin -PostgresBin $PostgresBin
    $version = Get-XpjPostgresBinaryVersion -PostgresBin $resolvedBin
    $policy = Get-XpjPostgresReleasePolicy
    if (
        $version.CompareTo($policy.Minimum) -lt 0 -or
        $version.CompareTo($policy.MaximumExclusive) -ge 0
    ) {
        throw "PostgreSQL runtime is outside the active release policy: $resolvedBin ($version)"
    }
    return $resolvedBin
}

function Find-XpjPostgresBinForCleanup {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RequiredMajor)

    if ($RequiredMajor -notmatch '^[1-9][0-9]*$') {
        throw "PostgreSQL cleanup major is invalid: $RequiredMajor"
    }
    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
    if ([string]::IsNullOrWhiteSpace($programFiles)) {
        throw 'Windows Program Files root is unavailable'
    }
    $candidate = Join-Path $programFiles "PostgreSQL\$RequiredMajor\bin"
    $resolved = Resolve-XpjPostgresBin -PostgresBin $candidate
    $version = Get-XpjPostgresBinaryVersion -PostgresBin $resolved
    if ($version.Major -ne [int]$RequiredMajor) {
        throw "PostgreSQL cleanup runtime major does not match its cluster: $resolved"
    }
    return $resolved
}

function Find-XpjPostgresBin {
    [CmdletBinding()]
    param([string]$RequiredVersion = '')

    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
    if ([string]::IsNullOrWhiteSpace($programFiles)) {
        throw 'Windows Program Files root is unavailable'
    }
    $policy = Get-XpjPostgresReleasePolicy
    $supportedVersions = @($policy.SupportedMajors)
    $candidates = @(
        Get-ChildItem (Join-Path $programFiles 'PostgreSQL\*\bin\pg_ctl.exe') -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Parent.Name -cin $supportedVersions }
    )
    if (-not [string]::IsNullOrWhiteSpace($RequiredVersion)) {
        if ($RequiredVersion -cnotin $supportedVersions) {
            throw "PostgreSQL version is outside the release policy: $RequiredVersion"
        }
        $candidates = @($candidates | Where-Object { $_.Directory.Parent.Name -ceq $RequiredVersion })
    }
    $supportedCandidates = @(
        foreach ($candidate in $candidates) {
            $bin = Resolve-XpjPostgresBin -PostgresBin $candidate.DirectoryName
            $version = Get-XpjPostgresBinaryVersion -PostgresBin $bin
            if (
                $version.CompareTo($policy.Minimum) -ge 0 -and
                $version.CompareTo($policy.MaximumExclusive) -lt 0
            ) {
                [pscustomobject]@{ Bin = $bin; Version = $version }
            }
        }
    )
    $selected = $supportedCandidates |
        Sort-Object Version -Descending |
        Select-Object -First 1
    if ($null -eq $selected) {
        $suffix = if ([string]::IsNullOrWhiteSpace($RequiredVersion)) { '' } else { " (required version: $RequiredVersion)" }
        throw "A PostgreSQL runtime allowed by the release policy is not installed under the OS Program Files root$suffix"
    }
    return [string]$selected.Bin
}

function Resolve-XpjPostgresBin {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $resolved = Resolve-XpjStoredPostgresBinPath -PostgresBin $PostgresBin
    foreach ($name in @('initdb.exe', 'pg_ctl.exe', 'postgres.exe', 'psql.exe')) {
        if ((Get-TicketboxPathEntryKindNoFollow -Path (Join-Path $resolved $name)) -cne 'File') {
            throw "PostgreSQL binary contract is incomplete: $resolved ($name)"
        }
    }
    return $resolved
}

function Resolve-XpjStoredPostgresBinPath {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $programFiles = [IO.Path]::GetFullPath(
        [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
    ).TrimEnd('\', '/')
    $postgresRoot = Join-Path $programFiles 'PostgreSQL'
    $resolved = [IO.Path]::GetFullPath($PostgresBin).TrimEnd('\', '/')
    $pinnedVendorBin = [IO.Path]::GetFullPath(
        (Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging\vendor\pg\bin')
    ).TrimEnd('\', '/')
    if ([string]::Equals($resolved, $pinnedVendorBin, [StringComparison]::OrdinalIgnoreCase)) {
        return $resolved
    }
    $prefix = $postgresRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PostgreSQL binary root escaped the closed test-runtime roots: $resolved"
    }
    if ([IO.Path]::GetFileName($resolved) -cne 'bin') {
        throw "PostgreSQL binary root is not a bin directory: $resolved"
    }
    $major = [IO.Path]::GetFileName([IO.Directory]::GetParent($resolved).FullName)
    if ($major -notmatch '^[1-9][0-9]*$') {
        throw "PostgreSQL binary root has no canonical major directory: $resolved"
    }
    return $resolved
}

function Assert-XpjRequestedPostgresBinMatchesOwnership {
    [CmdletBinding()]
    param(
        [AllowEmptyString()][string]$RequestedPostgresBin = '',
        [Parameter(Mandatory = $true)][string]$OwnershipPostgresBin
    )

    if ([string]::IsNullOrWhiteSpace($RequestedPostgresBin)) {
        return
    }
    $requested = Resolve-XpjStoredPostgresBinPath -PostgresBin $RequestedPostgresBin
    $owned = Resolve-XpjStoredPostgresBinPath -PostgresBin $OwnershipPostgresBin
    if (-not [string]::Equals($requested, $owned, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Requested PostgreSQL binary does not match the active cluster ownership marker'
    }
}

function Get-XpjStoredPostgresMajor {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $resolved = Resolve-XpjStoredPostgresBinPath -PostgresBin $PostgresBin
    $pinnedVendorBin = [IO.Path]::GetFullPath(
        (Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging\vendor\pg\bin')
    ).TrimEnd('\', '/')
    if ([string]::Equals($resolved, $pinnedVendorBin, [StringComparison]::OrdinalIgnoreCase)) {
        return (Get-XpjPostgresBinaryVersion -PostgresBin $resolved).Major
    }
    return [int][IO.Path]::GetFileName([IO.Directory]::GetParent($resolved).FullName)
}

function Get-XpjPostgresReleaseDisposition {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PostgresBin)

    $resolved = Resolve-XpjStoredPostgresBinPath -PostgresBin $PostgresBin
    $policy = Get-XpjPostgresReleasePolicy
    $storedMajor = Get-XpjStoredPostgresMajor -PostgresBin $resolved
    if ($storedMajor -notin @($policy.SupportedMajors | ForEach-Object { [int]$_ })) {
        return [pscustomobject]@{
            State = 'outside-policy'
            PostgresBin = $resolved
            Version = $null
        }
    }
    $version = Get-XpjPostgresBinaryVersion -PostgresBin $resolved
    $state = if (
        $version.CompareTo($policy.Minimum) -lt 0 -or
        $version.CompareTo($policy.MaximumExclusive) -ge 0
    ) {
        'outside-policy'
    }
    else {
        'active'
    }
    return [pscustomobject]@{
        State = $state
        PostgresBin = $resolved
        Version = $version
    }
}

function Get-XpjTestPostgresRuntimeOwnerSid {
    [CmdletBinding()]
    param()

    return [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
}

function Get-XpjTestPostgresRuntimeRoot {
    [CmdletBinding()]
    param()

    $contract = Get-XpjTestPostgresContract
    if ([string]$contract.runtime_parent -cne 'local_app_data') {
        throw "Unsupported test PostgreSQL runtime parent: $($contract.runtime_parent)"
    }
    $parent = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
    if ([string]::IsNullOrWhiteSpace($parent)) {
        throw 'Windows LocalApplicationData folder is unavailable'
    }
    return Join-Path `
        ([IO.Path]::GetFullPath($parent).TrimEnd('\', '/')) `
        ([string]$contract.runtime_root_name)
}

function Assert-XpjTestPostgresRuntimeRoot {
    [CmdletBinding()]
    param()

    $root = Get-XpjTestPostgresRuntimeRoot
    $ownerSid = Get-XpjTestPostgresRuntimeOwnerSid
    Assert-TicketboxProtectedDirectoryAcl `
        -Path $root `
        -FullControlAccounts @($ownerSid) `
        -OwnerAccount $ownerSid
    return $root
}

function Initialize-XpjTestPostgresRuntimeRoot {
    [CmdletBinding()]
    param()

    $root = Get-XpjTestPostgresRuntimeRoot
    $ownerSid = Get-XpjTestPostgresRuntimeOwnerSid
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $root `
        -FullControlAccounts @($ownerSid) `
        -OwnerAccount $ownerSid | Out-Null
    return Assert-XpjTestPostgresRuntimeRoot
}

function Get-XpjTestPostgresDefaultDataDir {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port)

    return Join-Path (Get-XpjTestPostgresRuntimeRoot) "xpj_pg_test$Port"
}

function Write-XpjTestPostgresProtectedMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text,
        [switch]$ReplaceExisting
    )

    $ownerSid = Get-XpjTestPostgresRuntimeOwnerSid
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $Path `
        -Text $Text `
        -FullControlAccounts @($ownerSid) `
        -OwnerAccount $ownerSid `
        -ReplaceExisting:$ReplaceExisting
}

function Read-XpjTestPostgresProtectedMarkerText {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    $ownerSid = Get-XpjTestPostgresRuntimeOwnerSid
    return [string](
        Read-TicketboxProtectedUtf8Artifact `
            -Path $Path `
            -FullControlAccounts @($ownerSid) `
            -OwnerAccount $ownerSid
    ).Text
}

function Remove-XpjTestPostgresProtectedMarker {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    $ownerSid = Get-XpjTestPostgresRuntimeOwnerSid
    Remove-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts @($ownerSid) `
        -OwnerAccount $ownerSid
}

function Resolve-XpjTestPostgresDataDir {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDir
    )

    $resolved = [IO.Path]::GetFullPath($DataDir).TrimEnd('\', '/')
    $runtimeRoot = [IO.Path]::GetFullPath((Get-XpjTestPostgresRuntimeRoot)).TrimEnd('\', '/')
    $runtimePrefix = $runtimeRoot + [IO.Path]::DirectorySeparatorChar
    if (
        [string]::Equals($resolved, $runtimeRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not $resolved.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Test PostgreSQL data directory must be a child of its protected runtime root: $resolved"
    }

    $leaf = [IO.Path]::GetFileName($resolved)
    if ($leaf -notmatch '^xpj_pg_[a-z0-9][a-z0-9._ -]*$') {
        throw "Test PostgreSQL data directory has no XPJ test prefix: $resolved"
    }

    $rootKind = Get-TicketboxPathEntryKindNoFollow -Path $runtimeRoot
    if ($rootKind -eq 'Directory') {
        $null = Assert-XpjTestPostgresRuntimeRoot
    }
    elseif ($rootKind -cne 'Missing') {
        throw "Test PostgreSQL runtime root is not a plain directory: $runtimeRoot"
    }

    $current = [IO.DirectoryInfo]::new($resolved)
    while (-not [string]::Equals($current.FullName.TrimEnd('\', '/'), $runtimeRoot, [StringComparison]::OrdinalIgnoreCase)) {
        if ($current.Exists -and (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw "Test PostgreSQL data directory crosses a reparse point: $($current.FullName)"
        }
        $current = $current.Parent
        if ($null -eq $current) {
            throw "Test PostgreSQL data directory escaped its protected runtime root: $resolved"
        }
    }
    return $resolved
}

function Get-XpjTestPostgresOwnershipMarkerPaths {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $markerName = [string](Get-XpjTestPostgresContract).ownership_marker_name
    return [pscustomobject]@{
        Host = $resolvedDataDir + $markerName
        Data = Join-Path $resolvedDataDir $markerName
    }
}

function Get-XpjTestPostgresDeletionMarkerPath {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $markerName = [string](Get-XpjTestPostgresContract).deletion_marker_name
    return $resolvedDataDir + $markerName
}

function Get-XpjTestPostgresProvisioningMarkerPath {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DataDir)

    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $DataDir
    return "$($paths.Host).provisioning"
}

function Get-XpjTestPostgresProvisioningBirthMarkerPath {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$GenerationRoot)

    $resolvedRoot = Resolve-XpjTestPostgresDataDir -DataDir $GenerationRoot
    return Join-Path $resolvedRoot '.xpj-test-postgres-provisioning-birth.json'
}

function ConvertTo-XpjTestPostgresProvisioningMarkerText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][string]$GenerationRoot,
        [Parameter(Mandatory = $true)][string]$StagingDir,
        [Parameter(Mandatory = $true)][Guid]$InstanceId,
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $resolvedGenerationRoot = Resolve-XpjTestPostgresDataDir -DataDir $GenerationRoot
    $resolvedStagingDir = Resolve-XpjTestPostgresDataDir -DataDir $StagingDir
    $expectedGenerationRoot = "$resolvedDataDir.provisioning.$($InstanceId.ToString('N'))"
    $expectedStagingDir = Join-Path $expectedGenerationRoot 'xpj_pg_data'
    if (-not [string]::Equals($resolvedGenerationRoot, $expectedGenerationRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Test PostgreSQL generation root does not match its identity: $resolvedGenerationRoot"
    }
    if (-not [string]::Equals($resolvedStagingDir, $expectedStagingDir, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Test PostgreSQL staging path does not match its generation: $resolvedStagingDir"
    }
    return ([ordered]@{
        schema = 'xpj-test-postgres-provisioning-v2'
        data_dir = $resolvedDataDir
        generation_root = $resolvedGenerationRoot
        staging_dir = $resolvedStagingDir
        cluster_marker = [string](Get-XpjTestPostgresContract).cluster_marker
        instance_id = $InstanceId.ToString('D')
        postgres_bin = Resolve-XpjStoredPostgresBinPath -PostgresBin $PostgresBin
        port = $Port
    } | ConvertTo-Json -Compress) + "`n"
}

function Read-XpjTestPostgresProvisioningMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $path = Get-XpjTestPostgresProvisioningMarkerPath -DataDir $resolvedDataDir
    if ((Get-TicketboxPathEntryKindNoFollow -Path $path) -cne 'File') {
        throw "Test PostgreSQL provisioning marker is not a plain file: $path"
    }
    $rawText = Read-XpjTestPostgresProtectedMarkerText -Path $path
    $payload = $rawText | ConvertFrom-Json
    $expectedFields = @(
        'schema',
        'data_dir',
        'generation_root',
        'staging_dir',
        'cluster_marker',
        'instance_id',
        'postgres_bin',
        'port'
    )
    $actualFields = @($payload.PSObject.Properties.Name)
    if (@(Compare-Object ($expectedFields | Sort-Object) ($actualFields | Sort-Object)).Count -ne 0) {
        throw "Test PostgreSQL provisioning marker fields are invalid: $path"
    }
    $instanceId = [Guid]::Empty
    if (
        [string]$payload.schema -cne 'xpj-test-postgres-provisioning-v2' -or
        [string]$payload.cluster_marker -cne [string](Get-XpjTestPostgresContract).cluster_marker -or
        -not [Guid]::TryParse([string]$payload.instance_id, [ref]$instanceId) -or
        $instanceId -eq [Guid]::Empty -or
        [int]$payload.port -ne $Port
    ) {
        throw "Test PostgreSQL provisioning marker identity is invalid: $path"
    }
    $text = ConvertTo-XpjTestPostgresProvisioningMarkerText `
        -DataDir $resolvedDataDir `
        -GenerationRoot ([string]$payload.generation_root) `
        -StagingDir ([string]$payload.staging_dir) `
        -InstanceId $instanceId `
        -PostgresBin ([string]$payload.postgres_bin) `
        -Port $Port
    if ($rawText -cne $text) {
        throw "Test PostgreSQL provisioning marker is not canonical: $path"
    }
    return [pscustomobject]@{
        Path = $path
        DataDir = $resolvedDataDir
        GenerationRoot = Resolve-XpjTestPostgresDataDir -DataDir ([string]$payload.generation_root)
        StagingDir = Resolve-XpjTestPostgresDataDir -DataDir ([string]$payload.staging_dir)
        InstanceId = $instanceId
        PostgresBin = Resolve-XpjStoredPostgresBinPath -PostgresBin ([string]$payload.postgres_bin)
        Port = $Port
        Text = $text
    }
}

function New-XpjTestPostgresProvisioning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][string]$PostgresBin,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $null = Initialize-XpjTestPostgresRuntimeRoot
    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $resolvedDataDir
    $provisioningPath = Get-XpjTestPostgresProvisioningMarkerPath -DataDir $resolvedDataDir
    foreach ($path in @($resolvedDataDir, $paths.Host, $provisioningPath)) {
        if ((Get-TicketboxPathEntryKindNoFollow -Path $path) -cne 'Missing') {
            throw "Refusing to provision over an existing PostgreSQL lifecycle path: $path"
        }
    }
    $instanceId = [Guid]::NewGuid()
    $generationRoot = "$resolvedDataDir.provisioning.$($instanceId.ToString('N'))"
    $stagingDir = Join-Path $generationRoot 'xpj_pg_data'
    if ((Get-TicketboxPathEntryKindNoFollow -Path $generationRoot) -cne 'Missing') {
        throw "Test PostgreSQL generation root already exists: $generationRoot"
    }
    $text = ConvertTo-XpjTestPostgresProvisioningMarkerText `
        -DataDir $resolvedDataDir `
        -GenerationRoot $generationRoot `
        -StagingDir $stagingDir `
        -InstanceId $instanceId `
        -PostgresBin $PostgresBin `
        -Port $Port
    Write-XpjTestPostgresProtectedMarker -Path $provisioningPath -Text $text
    $ownerSid = Get-XpjTestPostgresRuntimeOwnerSid
    Initialize-TicketboxProtectedDirectoryAtomically `
        -Path $generationRoot `
        -FullControlAccounts @($ownerSid) `
        -OwnerAccount $ownerSid | Out-Null
    if ((Get-TicketboxPathEntryKindNoFollow -Path $generationRoot) -cne 'Directory') {
        throw "Test PostgreSQL generation root is not a plain directory: $generationRoot"
    }
    if (@(Get-ChildItem -LiteralPath $generationRoot -Force).Count -ne 0) {
        throw "Test PostgreSQL generation root was not born empty: $generationRoot"
    }
    Write-XpjTestPostgresProtectedMarker `
        -Path (Get-XpjTestPostgresProvisioningBirthMarkerPath -GenerationRoot $generationRoot) `
        -Text $text
    return Read-XpjTestPostgresProvisioningMarker -DataDir $resolvedDataDir -Port $Port
}

function Assert-XpjTestPostgresProvisioningBirthMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Provisioning,
        [switch]$AllowMissingWhenEmpty
    )

    if ((Get-TicketboxPathEntryKindNoFollow -Path $Provisioning.GenerationRoot) -cne 'Directory') {
        throw "Test PostgreSQL generation root is not a plain directory: $($Provisioning.GenerationRoot)"
    }
    $path = Get-XpjTestPostgresProvisioningBirthMarkerPath `
        -GenerationRoot $Provisioning.GenerationRoot
    $kind = Get-TicketboxPathEntryKindNoFollow -Path $path
    if ($kind -eq 'Missing') {
        if (@(Get-ChildItem -LiteralPath $Provisioning.GenerationRoot -Force).Count -ne 0) {
            throw "Test PostgreSQL generation lost its birth evidence before becoming empty: $($Provisioning.GenerationRoot)"
        }
        if ($AllowMissingWhenEmpty) { return $null }
        throw "Test PostgreSQL generation has no trusted birth marker: $($Provisioning.GenerationRoot)"
    }
    if ($kind -cne 'File') {
        throw "Test PostgreSQL generation birth marker is not a plain file: $path"
    }
    if ((Read-XpjTestPostgresProtectedMarkerText -Path $path) -cne $Provisioning.Text) {
        throw "Test PostgreSQL generation birth marker changed: $path"
    }
    return $path
}

function Remove-XpjTestPostgresProvisioningGeneration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][Guid]$InstanceId
    )

    $provisioning = Read-XpjTestPostgresProvisioningMarker -DataDir $DataDir -Port $Port
    if ($provisioning.InstanceId -ne $InstanceId) {
        throw "Test PostgreSQL provisioning generation changed before cleanup: $($provisioning.Path)"
    }
    $rootKind = Get-TicketboxPathEntryKindNoFollow -Path $provisioning.GenerationRoot
    if ($rootKind -eq 'Directory') {
        $birthPath = Assert-XpjTestPostgresProvisioningBirthMarker `
            -Provisioning $provisioning `
            -AllowMissingWhenEmpty
        $expectedRoot = [IO.Path]::GetFullPath(
            [string]$provisioning.GenerationRoot
        ).TrimEnd('\', '/')
        Initialize-TicketboxExactTreeDeleteNativeMethods
        $expectedRootIdentity = @(
            [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity(
                $expectedRoot
            )
        )
        if ($expectedRootIdentity.Count -ne 2) {
            throw "Test PostgreSQL generation identity is invalid: $expectedRoot"
        }
        if ($null -eq $birthPath) {
            $verifyOpenedEmptyRoot = {
                param([string]$OpenedPath)

                $openedRoot = [IO.Path]::GetFullPath($OpenedPath).TrimEnd('\', '/')
                if (-not [string]::Equals(
                    $openedRoot,
                    $expectedRoot,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                    throw "Test PostgreSQL cleanup opened another generation root: $OpenedPath"
                }
                $openedIdentity = @(
                    [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity(
                        $openedRoot
                    )
                )
                if (
                    $openedIdentity.Count -ne 2 -or
                    [string]$openedIdentity[0] -cne [string]$expectedRootIdentity[0] -or
                    [string]$openedIdentity[1] -cne [string]$expectedRootIdentity[1]
                ) {
                    throw "Test PostgreSQL generation identity changed before cleanup: $OpenedPath"
                }
                if ([IO.Directory]::GetFileSystemEntries($openedRoot).Length -ne 0) {
                    throw "Test PostgreSQL markerless generation is no longer empty: $OpenedPath"
                }
            }.GetNewClosure()
            Remove-TicketboxTreeExact `
                -Path $provisioning.GenerationRoot `
                -OnRootHandleAcquired $verifyOpenedEmptyRoot
            Remove-XpjTestPostgresProvisioningMarker `
                -DataDir $DataDir `
                -Port $Port `
                -InstanceId $InstanceId
            return
        }
        $expectedText = [string]$provisioning.Text
        $externalPath = [string]$provisioning.Path
        foreach ($markerPath in @($externalPath, $birthPath)) {
            if ((Read-XpjTestPostgresProtectedMarkerText -Path $markerPath) -cne $expectedText) {
                throw "Test PostgreSQL provisioning evidence changed before cleanup: $markerPath"
            }
        }
        $verifyOpenedRoot = {
            param([string]$OpenedPath)

            $openedRoot = [IO.Path]::GetFullPath($OpenedPath).TrimEnd('\', '/')
            if (-not [string]::Equals(
                $openedRoot,
                $expectedRoot,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Test PostgreSQL cleanup opened another generation root: $OpenedPath"
            }
            $openedIdentity = @(
                [TicketboxExactTreeDeleteNativeMethods]::GetDirectoryIdentity(
                    $openedRoot
                )
            )
            if (
                $openedIdentity.Count -ne 2 -or
                [string]$openedIdentity[0] -cne [string]$expectedRootIdentity[0] -or
                [string]$openedIdentity[1] -cne [string]$expectedRootIdentity[1]
            ) {
                throw "Test PostgreSQL generation identity changed before cleanup: $OpenedPath"
            }
            foreach ($markerPath in @($externalPath, $birthPath)) {
                if ([TicketboxExactTreeDeleteNativeMethods]::InspectEntry($markerPath) -ne 1) {
                    throw "Test PostgreSQL provisioning evidence changed before cleanup: $markerPath"
                }
                if (
                    [TicketboxExactTreeDeleteNativeMethods]::ReadExactUtf8File(
                        $markerPath,
                        65536
                    ) -cne $expectedText
                ) {
                    throw "Test PostgreSQL provisioning evidence changed before cleanup: $markerPath"
                }
            }
        }.GetNewClosure()
        Remove-TicketboxTreeExact `
            -Path $provisioning.GenerationRoot `
            -DeferredRootLeafName ([IO.Path]::GetFileName($birthPath)) `
            -OnRootHandleAcquired $verifyOpenedRoot
    }
    elseif ($rootKind -cne 'Missing') {
        throw "Test PostgreSQL generation root is not a plain directory: $($provisioning.GenerationRoot)"
    }
    Remove-XpjTestPostgresProvisioningMarker `
        -DataDir $DataDir `
        -Port $Port `
        -InstanceId $InstanceId
}

function Remove-XpjTestPostgresProvisioningMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port,
        [Parameter(Mandatory = $true)][Guid]$InstanceId
    )

    $provisioning = Read-XpjTestPostgresProvisioningMarker -DataDir $DataDir -Port $Port
    if ($provisioning.InstanceId -ne $InstanceId) {
        throw "Test PostgreSQL provisioning generation changed before marker removal: $($provisioning.Path)"
    }
    Remove-XpjTestPostgresProtectedMarker -Path $provisioning.Path
    if ((Get-TicketboxPathEntryKindNoFollow -Path $provisioning.Path) -cne 'Missing') {
        throw "Test PostgreSQL provisioning marker still exists: $($provisioning.Path)"
    }
}

function Resolve-XpjTestPostgresProvisioning {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$Port
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $provisioningPath = Get-XpjTestPostgresProvisioningMarkerPath -DataDir $resolvedDataDir
    $provisioningKind = Get-TicketboxPathEntryKindNoFollow -Path $provisioningPath
    if ($provisioningKind -eq 'Missing') { return $null }
    if ($provisioningKind -cne 'File') {
        throw "Test PostgreSQL provisioning marker is not a plain file: $provisioningPath"
    }
    $provisioning = Read-XpjTestPostgresProvisioningMarker -DataDir $resolvedDataDir -Port $Port
    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $resolvedDataDir
    $dataKind = Get-TicketboxPathEntryKindNoFollow -Path $resolvedDataDir
    $generationKind = Get-TicketboxPathEntryKindNoFollow -Path $provisioning.GenerationRoot
    $stagingKind = Get-TicketboxPathEntryKindNoFollow -Path $provisioning.StagingDir

    if ($dataKind -eq 'Directory') {
        if ($stagingKind -cne 'Missing') {
            throw "Test PostgreSQL provisioning has both target and staging directories: $resolvedDataDir"
        }
        $dataMarkerKind = Get-TicketboxPathEntryKindNoFollow -Path $paths.Data
        if ($dataMarkerKind -cne 'File') {
            throw "Refusing to adopt a replacement directory after interrupted PostgreSQL provisioning: $resolvedDataDir"
        }
        $dataMarker = Read-XpjTestPostgresOwnershipMarker -Path $paths.Data -DataDir $resolvedDataDir
        if ($dataMarker.InstanceId -ne $provisioning.InstanceId) {
            throw "Test PostgreSQL promoted directory belongs to another generation: $resolvedDataDir"
        }
        if ($generationKind -eq 'Directory') {
            $null = Assert-XpjTestPostgresProvisioningBirthMarker `
                -Provisioning $provisioning
        }
        elseif ($generationKind -cne 'Missing') {
            throw "Test PostgreSQL generation root is not a plain directory after promotion"
        }
    }
    elseif ($dataKind -eq 'Missing') {
        if ($generationKind -eq 'Missing') {
            return [pscustomobject]@{ Completed = $false; Provisioning = $provisioning }
        }
        if ($generationKind -cne 'Directory') {
            throw "Test PostgreSQL generation root is not a plain directory: $($provisioning.GenerationRoot)"
        }
        $birthPath = Assert-XpjTestPostgresProvisioningBirthMarker `
            -Provisioning $provisioning `
            -AllowMissingWhenEmpty
        if ($null -eq $birthPath) {
            return [pscustomobject]@{ Completed = $false; Provisioning = $provisioning }
        }
        if ($stagingKind -eq 'Missing') {
            return [pscustomobject]@{ Completed = $false; Provisioning = $provisioning }
        }
        if ($stagingKind -cne 'Directory') {
            throw "Test PostgreSQL staging path is not a plain directory: $($provisioning.StagingDir)"
        }
        $stagingMarkerPath = Join-Path `
            $provisioning.StagingDir `
            ([string](Get-XpjTestPostgresContract).ownership_marker_name)
        $stagingMarkerKind = Get-TicketboxPathEntryKindNoFollow -Path $stagingMarkerPath
        if ($stagingMarkerKind -eq 'Missing') {
            return [pscustomobject]@{ Completed = $false; Provisioning = $provisioning }
        }
        if ($stagingMarkerKind -cne 'File') {
            throw "Test PostgreSQL staging ownership marker is not a plain file: $stagingMarkerPath"
        }
        $stagingMarker = Read-XpjTestPostgresOwnershipMarker `
            -Path $stagingMarkerPath `
            -DataDir $resolvedDataDir
        if ($stagingMarker.InstanceId -ne $provisioning.InstanceId) {
            throw "Test PostgreSQL staging directory belongs to another generation: $($provisioning.StagingDir)"
        }
        [IO.Directory]::Move($provisioning.StagingDir, $resolvedDataDir)
    }
    else {
        throw "Test PostgreSQL target path is not a plain directory: $resolvedDataDir ($dataKind)"
    }

    $ownershipText = ConvertTo-XpjTestPostgresOwnershipMarkerText `
        -DataDir $resolvedDataDir `
        -InstanceId $provisioning.InstanceId `
        -PostgresBin $provisioning.PostgresBin
    $hostKind = Get-TicketboxPathEntryKindNoFollow -Path $paths.Host
    if ($hostKind -eq 'Missing') {
        Write-XpjTestPostgresProtectedMarker -Path $paths.Host -Text $ownershipText
    }
    elseif ($hostKind -eq 'File') {
        $hostMarker = Read-XpjTestPostgresOwnershipMarker -Path $paths.Host -DataDir $resolvedDataDir
        if ($hostMarker.InstanceId -ne $provisioning.InstanceId -or $hostMarker.Text -cne $ownershipText) {
            throw "Test PostgreSQL host marker belongs to another generation: $($paths.Host)"
        }
    }
    else {
        throw "Test PostgreSQL host ownership marker is not a plain file: $($paths.Host)"
    }
    $ownership = Assert-XpjTestPostgresOwnership -DataDir $resolvedDataDir
    Remove-XpjTestPostgresProvisioningGeneration `
        -DataDir $resolvedDataDir `
        -Port $Port `
        -InstanceId $provisioning.InstanceId
    return [pscustomobject]@{
        Completed = $true
        Provisioning = $provisioning
        Ownership = $ownership
    }
}

function ConvertTo-XpjTestPostgresOwnershipMarkerText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][Guid]$InstanceId,
        [Parameter(Mandatory = $true)][string]$PostgresBin
    )

    $contract = Get-XpjTestPostgresContract
    return ([ordered]@{
        schema_version = 2
        data_dir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
        cluster_marker = [string]$contract.cluster_marker
        instance_id = $InstanceId.ToString('D')
        postgres_bin = Resolve-XpjStoredPostgresBinPath -PostgresBin $PostgresBin
    } | ConvertTo-Json -Compress) + "`n"
}

function Read-XpjTestPostgresOwnershipMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$DataDir
    )

    $kind = Get-TicketboxPathEntryKindNoFollow -Path $Path
    if ($kind -cne 'File') {
        throw "Test PostgreSQL ownership marker is not a plain file: $Path ($kind)"
    }
    $rawText = Read-XpjTestPostgresProtectedMarkerText -Path $Path
    $payload = $rawText | ConvertFrom-Json
    $actualFields = @($payload.PSObject.Properties.Name)
    $schemaVersion = 0
    if (
        'schema_version' -notin $actualFields -or
        -not [int]::TryParse([string]$payload.schema_version, [ref]$schemaVersion) -or
        $schemaVersion -notin @(1, 2)
    ) {
        throw "Test PostgreSQL ownership marker schema is invalid: $Path"
    }
    $expectedFields = @('schema_version', 'data_dir', 'cluster_marker', 'instance_id')
    if ($schemaVersion -eq 2) { $expectedFields += 'postgres_bin' }
    if (@(Compare-Object ($expectedFields | Sort-Object) ($actualFields | Sort-Object)).Count -ne 0) {
        throw "Test PostgreSQL ownership marker fields are invalid: $Path"
    }
    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    if (
        -not [string]::Equals([string]$payload.data_dir, $resolvedDataDir, [StringComparison]::OrdinalIgnoreCase) -or
        [string]$payload.cluster_marker -cne [string](Get-XpjTestPostgresContract).cluster_marker
    ) {
        throw "Test PostgreSQL ownership marker does not own ${resolvedDataDir}: $Path"
    }
    $instanceId = [Guid]::Empty
    if (-not [Guid]::TryParse([string]$payload.instance_id, [ref]$instanceId) -or $instanceId -eq [Guid]::Empty) {
        throw "Test PostgreSQL ownership marker has an invalid instance ID: $Path"
    }
    if ($schemaVersion -eq 2) {
        $postgresBin = Resolve-XpjStoredPostgresBinPath -PostgresBin ([string]$payload.postgres_bin)
    }
    else {
        $versionPath = Join-Path $resolvedDataDir 'PG_VERSION'
        $versionKind = Get-TicketboxPathEntryKindNoFollow -Path $versionPath
        if ($versionKind -eq 'File') {
            $requiredVersion = (Get-Content -Raw -Encoding UTF8 -LiteralPath $versionPath).Trim()
            $postgresBin = Find-XpjPostgresBinForCleanup -RequiredMajor $requiredVersion
        }
        elseif ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedDataDir) -eq 'Missing') {
            $postgresBin = Find-XpjPostgresBin
        }
        else {
            throw "Legacy test PostgreSQL ownership cannot resolve its binary version: $resolvedDataDir"
        }
    }
    $canonicalText = ConvertTo-XpjTestPostgresOwnershipMarkerText `
        -DataDir $resolvedDataDir `
        -InstanceId $instanceId `
        -PostgresBin $postgresBin
    $storedCanonicalText = if ($schemaVersion -eq 1) {
        ([ordered]@{
            schema_version = 1
            data_dir = $resolvedDataDir
            cluster_marker = [string](Get-XpjTestPostgresContract).cluster_marker
            instance_id = $instanceId.ToString('D')
        } | ConvertTo-Json -Compress) + "`n"
    }
    else {
        $canonicalText
    }
    if ($rawText -cne $storedCanonicalText) {
        throw "Test PostgreSQL ownership marker is not canonical: $Path"
    }
    return [pscustomobject]@{
        InstanceId = $instanceId
        PostgresBin = $postgresBin
        SchemaVersion = $schemaVersion
        Text = $canonicalText
    }
}

function Assert-XpjTestPostgresOwnership {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [switch]$AllowProvisioning
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $resolvedDataDir
    $hostMarker = Read-XpjTestPostgresOwnershipMarker -Path $paths.Host -DataDir $resolvedDataDir
    $dataKind = Get-TicketboxPathEntryKindNoFollow -Path $paths.Data
    if ($dataKind -eq 'Missing' -and $AllowProvisioning) {
        return [pscustomobject]@{
            InstanceId = $hostMarker.InstanceId
            PostgresBin = $hostMarker.PostgresBin
            HostSchemaVersion = $hostMarker.SchemaVersion
            DataSchemaVersion = 0
            Text = $hostMarker.Text
        }
    }
    $data = Read-XpjTestPostgresOwnershipMarker -Path $paths.Data -DataDir $resolvedDataDir
    if ($hostMarker.InstanceId -ne $data.InstanceId -or $hostMarker.Text -cne $data.Text) {
        throw "Test PostgreSQL host/data ownership markers disagree: $resolvedDataDir"
    }
    return [pscustomobject]@{
        InstanceId = $hostMarker.InstanceId
        PostgresBin = $hostMarker.PostgresBin
        HostSchemaVersion = $hostMarker.SchemaVersion
        DataSchemaVersion = $data.SchemaVersion
        Text = $hostMarker.Text
    }
}

function Update-XpjTestPostgresOwnershipSchema {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [switch]$AllowProvisioning
    )

    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $resolvedDataDir
    $ownership = Assert-XpjTestPostgresOwnership `
        -DataDir $resolvedDataDir `
        -AllowProvisioning:$AllowProvisioning
    if ($ownership.HostSchemaVersion -eq 1) {
        Write-XpjTestPostgresProtectedMarker `
            -Path $paths.Host `
            -Text $ownership.Text `
            -ReplaceExisting
    }
    if ($ownership.DataSchemaVersion -eq 1) {
        Write-XpjTestPostgresProtectedMarker `
            -Path $paths.Data `
            -Text $ownership.Text `
            -ReplaceExisting
    }
    $upgraded = Assert-XpjTestPostgresOwnership `
        -DataDir $resolvedDataDir `
        -AllowProvisioning:$AllowProvisioning
    if (
        $upgraded.HostSchemaVersion -ne 2 -or
        ($upgraded.DataSchemaVersion -notin @(0, 2))
    ) {
        throw "Test PostgreSQL ownership marker upgrade did not converge: $resolvedDataDir"
    }
    return $upgraded
}

function New-XpjTestPostgresOwnership {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DataDir,
        [Parameter(Mandatory = $true)][string]$PostgresBin
    )

    $null = Initialize-XpjTestPostgresRuntimeRoot
    $resolvedDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $paths = Get-XpjTestPostgresOwnershipMarkerPaths -DataDir $resolvedDataDir
    if ((Get-TicketboxPathEntryKindNoFollow -Path $resolvedDataDir) -cne 'Missing') {
        throw "Refusing to provision an existing PostgreSQL data directory: $resolvedDataDir"
    }
    if ((Get-TicketboxPathEntryKindNoFollow -Path $paths.Host) -cne 'Missing') {
        throw "Test PostgreSQL host ownership marker already exists: $($paths.Host)"
    }
    $instanceId = [Guid]::NewGuid()
    $text = ConvertTo-XpjTestPostgresOwnershipMarkerText -DataDir $resolvedDataDir -InstanceId $instanceId -PostgresBin $PostgresBin
    Write-XpjTestPostgresProtectedMarker -Path $paths.Host -Text $text
    return Assert-XpjTestPostgresOwnership -DataDir $resolvedDataDir -AllowProvisioning
}

function Enter-XpjTestPostgresLifecycleLock {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDir,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 65535)]
        [int]$Port,
        [ValidateRange(0, 3600)]
        [int]$TimeoutSeconds = 30
    )

    $canonicalDataDir = Resolve-XpjTestPostgresDataDir -DataDir $DataDir
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $dataDirBytes = [Text.Encoding]::UTF8.GetBytes($canonicalDataDir.ToUpperInvariant())
        $dataDirHash = ([BitConverter]::ToString($sha256.ComputeHash($dataDirBytes))).Replace('-', '')
    }
    finally {
        $sha256.Dispose()
    }
    $names = @(
        "Global\XpjTestPostgresLifecycle.DataDir.$dataDirHash",
        "Global\XpjTestPostgresLifecycle.Port.$Port"
    )
    $locks = New-Object 'System.Collections.Generic.List[Threading.Mutex]'
    try {
        foreach ($name in $names) {
            $mutex = [Threading.Mutex]::new($false, $name)
            try {
                try {
                    $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
                }
                catch [Threading.AbandonedMutexException] {
                    $acquired = $true
                }
                if (-not $acquired) {
                    throw "Timed out waiting for test PostgreSQL lifecycle lock $name (data dir: $canonicalDataDir, port: $Port)"
                }
                $locks.Add($mutex)
                $mutex = $null
            }
            finally {
                if ($null -ne $mutex) { $mutex.Dispose() }
            }
        }
        return [pscustomobject]@{
            Locks = $locks.ToArray()
            DataDir = $canonicalDataDir
            Port = $Port
        }
    }
    catch {
        for ($index = $locks.Count - 1; $index -ge 0; $index--) {
            try { $locks[$index].ReleaseMutex() } finally { $locks[$index].Dispose() }
        }
        throw
    }
}

function Exit-XpjTestPostgresLifecycleLock {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Mutex
    )

    $locks = @($Mutex.Locks)
    if ($locks.Count -eq 0) {
        throw 'Test PostgreSQL lifecycle lock bundle is empty'
    }
    for ($index = $locks.Count - 1; $index -ge 0; $index--) {
        try {
            $locks[$index].ReleaseMutex()
        }
        finally {
            $locks[$index].Dispose()
        }
    }
}
