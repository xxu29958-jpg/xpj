#Requires -Version 5.1

$script:TicketboxInstallerRecipeRelativePaths = @(
    "scripts\windows_build_provenance.ps1",
    "scripts\windows_backend_build_provenance.ps1",
    "requirements-build.lock",
    "packaging\windows-build-toolchain.json",
    "packaging\prepare_windows_build_toolchain.ps1",
    "packaging\prepare_windows_installer_vendor.ps1",
    "packaging\build_pg_bundle.ps1",
    "packaging\build_inno_installer.ps1",
    "packaging\ticketbox-installer.iss",
    "packaging\ticketbox-installer-windows.isph",
    "packaging\ticketbox-installer-flow.isph",
    "packaging\languages\ChineseSimplified.isl",
    "packaging\ticketbox.ico",
    "packaging\windows-release-config.json",
    "packaging\windows_release_config.ps1",
    "packaging\prepare_bundled_upgrade.ps1",
    "packaging\windows_service_contract.ps1",
    "packaging\windows_service_identity.ps1",
    "packaging\windows_service_lifecycle.ps1",
    "packaging\windows_installation_safety.ps1",
    "packaging\windows_lifecycle_receipt.ps1",
    "packaging\windows_lifecycle_lock.ps1",
    "packaging\hold_installer_lifecycle_lock.ps1",
    "packaging\hold_data_root_mutation_guard.ps1",
    "packaging\install_windows_prerequisites.ps1",
    "packaging\windows_database_safety.ps1",
    "packaging\windows_pg_recovery_tools.ps1",
    "packaging\windows_bundled_database.ps1",
    "packaging\windows_c07_database.ps1",
    "packaging\windows_security_primitives.ps1",
    "packaging\security_primitives\byte_array.ps1",
    "packaging\security_primitives\token_privilege_native.ps1",
    "packaging\security_primitives\token_privilege.ps1",
    "packaging\security_primitives\descriptor_comparison.ps1",
    "packaging\security_primitives\descriptor_diagnostic.ps1",
    "packaging\security_primitives\file_security.ps1",
    "packaging\windows_c07_superuser_recovery.ps1",
    "packaging\windows_c07_heartbeat_authority.ps1",
    "packaging\windows_c07_lifecycle.ps1",
    "packaging\windows_c07_heartbeat_helper.ps1",
    "packaging\windows_c07_failure_summary.ps1",
    "packaging\windows_atomic_artifacts.ps1",
    "packaging\atomic_artifacts\native.ps1",
    "packaging\atomic_artifacts\file.ps1",
    "packaging\atomic_artifacts\directory.ps1",
    "packaging\windows_c07_recovery_generation.ps1",
    "packaging\windows_c07_packaged_migration.ps1",
    "packaging\windows_backend_bootstrap.ps1",
    "packaging\windows_bootstrap_exposure_recovery.ps1",
    "packaging\install_bundled_services.ps1",
    "packaging\uninstall_bundled_services.ps1"
)

function Get-TicketboxSha256HexFromText([string]$Value) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Value)
        return ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}
function Get-TicketboxFileSha256([string]$Path) {
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}
function Get-TicketboxRelativePath([string]$Root, [string]$Path) {
    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $prefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "路径不在预期根目录下：$fullPath（root=$rootPath）"
    }
    return $fullPath.Substring($prefix.Length).Replace("\", "/")
}
function Get-TicketboxFileEvidence([string]$Root, [string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "构建 provenance 缺少文件：$Path"
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = Get-TicketboxRelativePath $Root $item.FullName
        size = [int64]$item.Length
        sha256 = Get-TicketboxFileSha256 $item.FullName
    }
}
function Get-TicketboxOrdinalSortedPaths([string[]]$Paths) {
    $sortedPaths = [string[]]@(
        $Paths | ForEach-Object { [System.IO.Path]::GetFullPath($_) }
    )
    [Array]::Sort($sortedPaths, [System.StringComparer]::OrdinalIgnoreCase)
    return $sortedPaths
}
function Get-TicketboxFileSetSnapshot([string]$Root, [string[]]$Paths) {
    if ($Paths.Count -eq 0) {
        throw "构建 provenance 文件集合为空：$Root"
    }
    $recordsByPath =
        [System.Collections.Generic.SortedDictionary[string, object]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($path in $Paths) {
        $record = Get-TicketboxFileEvidence $Root $path
        $relativePath = [string]$record.path
        if ($relativePath -cmatch "[^\x20-\x7e]") {
            throw (
                "构建 provenance canonical manifest 相对路径只允许可打印 ASCII；" +
                "这可避免不同 .NET Unicode 版本改变 OrdinalIgnoreCase 结果：" +
                $relativePath
            )
        }
        if ($recordsByPath.ContainsKey($relativePath)) {
            throw (
                "构建 provenance 包含 ordinal-ignore-case 等价的重复相对路径：" +
                $relativePath
            )
        }
        $recordsByPath.Add($relativePath, $record)
    }
    $records = [object[]]@($recordsByPath.Values)
    $fingerprintInput = ($records | ForEach-Object {
        "{0}`0{1}`0{2}`n" -f $_.path, $_.size, $_.sha256
    }) -join ""
    return [pscustomobject]@{
        algorithm = "SHA-256"
        fingerprint = Get-TicketboxSha256HexFromText $fingerprintInput
        files = @($records)
    }
}
function Assert-TicketboxFileSetSnapshot([string]$Label, [object]$Recorded, [object]$Actual) {
    if ($null -eq $Recorded) {
        throw "$Label 缺少记录的文件集合。"
    }
    if ($Recorded.algorithm -cne "SHA-256" -or $Actual.algorithm -cne "SHA-256") {
        throw "$Label 的 hash 算法不是 SHA-256。"
    }
    if ($Recorded.fingerprint -cne $Actual.fingerprint) {
        throw "$Label 的汇总指纹与当前文件集合不一致。"
    }

    $recordedFiles = @($Recorded.files)
    $actualFiles = @($Actual.files)
    if ($recordedFiles.Count -ne $actualFiles.Count) {
        throw "$Label 的文件记录数量不一致：recorded=$($recordedFiles.Count)，actual=$($actualFiles.Count)"
    }
    for ($index = 0; $index -lt $actualFiles.Count; $index++) {
        $recordedFile = $recordedFiles[$index]
        $actualFile = $actualFiles[$index]
        if (
            $recordedFile.path -cne $actualFile.path -or
            [int64]$recordedFile.size -ne [int64]$actualFile.size -or
            $recordedFile.sha256 -cne $actualFile.sha256
        ) {
            throw "$Label 的文件记录不一致：index=$index，recorded=$($recordedFile.path)，actual=$($actualFile.path)"
        }
    }
}
function Copy-TicketboxFileSetSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )
    $sourceRootPath = [System.IO.Path]::GetFullPath($SourceRoot)
    $destinationRootPath = [System.IO.Path]::GetFullPath($DestinationRoot)
    foreach ($record in @($Snapshot.files)) {
        $relativePath = ([string]$record.path).Replace("/", "\")
        $sourcePath = Join-Path $sourceRootPath $relativePath
        $destinationPath = Join-Path $destinationRootPath $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "构建快照复制缺少源文件：$sourcePath"
        }
        $destinationParent = Split-Path -Parent $destinationPath
        New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
    }
    $copiedPaths = @(
        @($Snapshot.files) | ForEach-Object {
            Join-Path $destinationRootPath (([string]$_.path).Replace("/", "\"))
        }
    )
    $copiedSnapshot = Get-TicketboxFileSetSnapshot $destinationRootPath $copiedPaths
    Assert-TicketboxFileSetSnapshot "构建输入 staging" $Snapshot $copiedSnapshot
    return $copiedSnapshot
}
function Enter-TicketboxFileSetReadLocks {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][object]$Snapshot
    )
    $rootPath = [System.IO.Path]::GetFullPath($Root)
    $streams = New-Object System.Collections.Generic.List[System.IO.FileStream]
    try {
        foreach ($record in @($Snapshot.files)) {
            $path = Join-Path $rootPath (([string]$record.path).Replace("/", "\"))
            $stream = [System.IO.File]::Open(
                $path,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
            $streams.Add($stream)
        }
        Assert-TicketboxFileSetSnapshot `
            "已锁定构建输入" `
            $Snapshot `
            (Get-TicketboxFileSetSnapshot $rootPath @(
                @($Snapshot.files) | ForEach-Object {
                    Join-Path $rootPath (([string]$_.path).Replace("/", "\"))
                }
            ))
        return $streams
    }
    catch {
        foreach ($stream in $streams) { $stream.Dispose() }
        throw
    }
}
function Exit-TicketboxFileSetReadLocks([object]$Streams) {
    if ($null -eq $Streams) { return }
    foreach ($stream in @($Streams)) { $stream.Dispose() }
}

$script:TicketboxInstalledBackendManifestRelativePath =
    "dist/ticketbox-backend/BUILD_PROVENANCE.json"
$script:TicketboxInstalledBackendPayloadManifestName = "BUILD_PROVENANCE.json"
$script:TicketboxInstalledC07ExternalAuthorityPaths = @(
    "_internal/app/database/_c07_fresh_source_bootstrap.py",
    "_internal/app/database/_c07_maintenance_upgrade.py",
    "_internal/app/database/_c07_production_migration.py",
    "_internal/app/database/_managed_schema_upgrade.py",
    "_internal/alembic.ini",
    "_internal/migrations/env.py",
    "_internal/migrations/versions/20260722_0001_bind_repayment_draft_idem_to_account.py",
    "_internal/migrations/versions/20260729_0001_money_minor_bigint_expand.py",
    "_internal/migrations/versions/20260802_0001_currency_binding_authority.py",
    "_internal/migrations/versions/20260809_0001_add_installation_owner_claim.py"
)

function Get-TicketboxOpenFileSha256Lower(
    [Parameter(Mandatory = $true)][System.IO.FileStream]$Stream
) {
    $Stream.Position = 0
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (
            [System.BitConverter]::ToString($sha256.ComputeHash($Stream))
        ).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
        $Stream.Position = 0
    }
}

function Read-TicketboxUtf8JsonFromOpenFile(
    [Parameter(Mandatory = $true)][System.IO.FileStream]$Stream,
    [Parameter(Mandatory = $true)][string]$Label
) {
    $Stream.Position = 0
    $reader = New-Object System.IO.StreamReader(
        $Stream,
        (New-Object System.Text.UTF8Encoding($false, $true)),
        $true,
        4096,
        $true
    )
    try {
        $text = $reader.ReadToEnd()
    }
    finally {
        $reader.Dispose()
        $Stream.Position = 0
    }
    try {
        return $text | ConvertFrom-Json
    }
    catch {
        throw "$Label 不是有效 UTF-8 JSON。"
    }
}

function Get-TicketboxInstalledPayloadAcl([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($PSVersionTable.PSEdition -eq "Core") {
        return [System.IO.FileSystemAclExtensions]::GetAccessControl($item)
    }
    return $item.GetAccessControl()
}

function Set-TicketboxInstalledPayloadAcl(
    [string]$Path,
    [System.Security.AccessControl.FileSystemSecurity]$Acl
) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($PSVersionTable.PSEdition -eq "Core") {
        [System.IO.FileSystemAclExtensions]::SetAccessControl($item, $Acl)
        return
    }
    $item.SetAccessControl($Acl)
}

function Copy-TicketboxInstalledPayloadAcl(
    [System.Security.AccessControl.FileSystemSecurity]$Acl,
    [switch]$Directory
) {
    $sddl = $Acl.GetSecurityDescriptorSddlForm(
        [System.Security.AccessControl.AccessControlSections]::Access
    )
    $copy = if ($Directory) {
        New-Object System.Security.AccessControl.DirectorySecurity
    }
    else {
        New-Object System.Security.AccessControl.FileSecurity
    }
    $copy.SetSecurityDescriptorSddlForm(
        $sddl,
        [System.Security.AccessControl.AccessControlSections]::Access
    )
    return $copy
}

function Get-TicketboxInstalledPayloadAclEvidence(
    [System.Security.AccessControl.FileSystemSecurity]$Acl
) {
    $rules = @($Acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    ) | ForEach-Object {
        "{0}|{1}|{2}|{3}|{4}|{5}" -f
            $_.IdentityReference.Value,
            [int]$_.AccessControlType,
            [int64]$_.FileSystemRights,
            [int]$_.InheritanceFlags,
            [int]$_.PropagationFlags,
            [bool]$_.IsInherited
    })
    [Array]::Sort($rules, [System.StringComparer]::Ordinal)
    return [pscustomobject][ordered]@{
        Protected = [bool]$Acl.AreAccessRulesProtected
        Rules = @($rules)
    }
}

function Get-TicketboxInstalledPayloadEntries([string]$PayloadRoot) {
    if ((Get-TicketboxPathEntryKindNoFollow $PayloadRoot) -cne "Directory") {
        throw "已安装 frozen backend payload root 不是普通目录。"
    }
    Assert-NoTicketboxAncestorReparsePoints $PayloadRoot
    $entries = @(
        Get-Item -LiteralPath $PayloadRoot -Force -ErrorAction Stop
    ) + @(
        Get-ChildItem -LiteralPath $PayloadRoot -Force -Recurse -ErrorAction Stop
    )
    foreach ($entry in $entries) {
        $kind = Get-TicketboxPathEntryKindNoFollow $entry.FullName
        if ($kind -cnotin @("File", "Directory")) {
            throw "已安装 frozen backend payload 含非普通目录项：$($entry.FullName)"
        }
        Assert-NoTicketboxAncestorReparsePoints $entry.FullName
    }
    return @($entries)
}

function Get-TicketboxInstalledPayloadMutationDeniedRights {
    return (
        [System.Security.AccessControl.FileSystemRights]::CreateFiles -bor
        [System.Security.AccessControl.FileSystemRights]::CreateDirectories -bor
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::WriteAttributes -bor
        [System.Security.AccessControl.FileSystemRights]::WriteExtendedAttributes
    )
}

function Test-TicketboxInstalledPayloadMutationDenyRule(
    [Parameter(Mandatory = $true)]
    [System.Security.AccessControl.FileSystemAccessRule]$Rule,
    [Parameter(Mandatory = $true)][bool]$ExpectedInherited,
    [Parameter(Mandatory = $true)]
    [System.Security.AccessControl.InheritanceFlags]$ExpectedInheritanceFlags
) {
    $everyoneSid = "S-1-1-0"
    return (
        $Rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value -ceq $everyoneSid -and
        $Rule.AccessControlType -eq
            [System.Security.AccessControl.AccessControlType]::Deny -and
        [int64]$Rule.FileSystemRights -eq
            [int64](Get-TicketboxInstalledPayloadMutationDeniedRights) -and
        $Rule.InheritanceFlags -eq $ExpectedInheritanceFlags -and
        $Rule.PropagationFlags -eq
            [System.Security.AccessControl.PropagationFlags]::None -and
        [bool]$Rule.IsInherited -eq $ExpectedInherited
    )
}

function Remove-TicketboxInterruptedInstalledPayloadMutationDenyExact {
    param(
        [Parameter(Mandatory = $true)][string]$PayloadRoot,
        [Parameter(Mandatory = $true)][string[]]$FullControlAccounts,
        [string[]]$RequiredReadExecuteAccounts = @(),
        [string[]]$AllowedReadExecuteAccounts = @(),
        [Parameter(Mandatory = $true)][string]$OwnerAccount
    )

    if ((Get-TicketboxPathEntryKindNoFollow $PayloadRoot) -cne "Directory") {
        throw "中断 payload mutation lease root 不是普通目录。"
    }
    Assert-NoTicketboxAncestorReparsePoints $PayloadRoot
    $entries = @(Get-TicketboxInstalledPayloadEntries $PayloadRoot)
    $rootAcl = Get-TicketboxInstalledPayloadAcl $PayloadRoot
    $rootRules = @($rootAcl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    ))
    $requiredInheritance =
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $rootDenyRules = @($rootRules | Where-Object {
        $_.AccessControlType -eq
            [System.Security.AccessControl.AccessControlType]::Deny
    })
    if ($rootDenyRules.Count -eq 0) {
        return $false
    }
    if (
        $rootDenyRules.Count -ne 1 -or
        -not (Test-TicketboxInstalledPayloadMutationDenyRule `
            -Rule $rootDenyRules[0] `
            -ExpectedInherited $false `
            -ExpectedInheritanceFlags $requiredInheritance)
    ) {
        throw "中断 payload DACL 不只含唯一的 installer mutation deny。"
    }

    $fullControlSids = @(
        $FullControlAccounts |
            ForEach-Object { ConvertTo-TicketboxAccountSid $_ } |
            Sort-Object -Unique
    )
    $requiredReadExecuteSids = @(
        $RequiredReadExecuteAccounts |
            ForEach-Object { ConvertTo-TicketboxAccountSid $_ } |
            Sort-Object -Unique
    )
    $allowedReadExecuteSids = @(
        @($RequiredReadExecuteAccounts) + @($AllowedReadExecuteAccounts) |
            ForEach-Object { ConvertTo-TicketboxAccountSid $_ } |
            Sort-Object -Unique
    )
    if (
        $fullControlSids.Count -eq 0 -or
        @($fullControlSids | Where-Object {
            $_ -in $allowedReadExecuteSids
        }).Count -ne 0
    ) {
        throw "中断 payload DACL 的预期账户集合无效。"
    }
    $expectedOwnerSid = ConvertTo-TicketboxAccountSid $OwnerAccount
    $actualOwnerSid = $rootAcl.GetOwner(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
    if ($actualOwnerSid -cne $expectedOwnerSid) {
        throw "中断 payload DACL owner 不是 installer-authored owner。"
    }

    $seenFullControlSids = New-Object System.Collections.Generic.HashSet[string]
    $seenReadExecuteSids = New-Object System.Collections.Generic.HashSet[string]
    $readExecuteForbidden =
        [System.Security.AccessControl.FileSystemRights]::Write -bor
        [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in @($rootRules | Where-Object {
        $_.AccessControlType -eq
            [System.Security.AccessControl.AccessControlType]::Allow
    })) {
        $sid = $rule.IdentityReference.Value
        $hasInheritance =
            ($rule.InheritanceFlags -band $requiredInheritance) -eq
                $requiredInheritance
        if ($sid -in $fullControlSids) {
            if (
                ($rule.FileSystemRights -band
                    [System.Security.AccessControl.FileSystemRights]::FullControl) -ne
                    [System.Security.AccessControl.FileSystemRights]::FullControl -or
                -not $hasInheritance
            ) {
                throw "中断 payload DACL 的 privileged allow 已漂移：$sid"
            }
            [void]$seenFullControlSids.Add($sid)
            continue
        }
        if ($sid -in $allowedReadExecuteSids) {
            if (
                ($rule.FileSystemRights -band
                    [System.Security.AccessControl.FileSystemRights]::ReadAndExecute) -ne
                    [System.Security.AccessControl.FileSystemRights]::ReadAndExecute -or
                ($rule.FileSystemRights -band $readExecuteForbidden) -ne 0 -or
                -not $hasInheritance
            ) {
                throw "中断 payload DACL 的 read-execute allow 已漂移：$sid"
            }
            [void]$seenReadExecuteSids.Add($sid)
            continue
        }
        throw "中断 payload DACL 含未知 allow SID：$sid"
    }
    foreach ($sid in $fullControlSids) {
        if (-not $seenFullControlSids.Contains($sid)) {
            throw "中断 payload DACL 缺少 privileged allow：$sid"
        }
    }
    foreach ($sid in $requiredReadExecuteSids) {
        if (-not $seenReadExecuteSids.Contains($sid)) {
            throw "中断 payload DACL 缺少 required read-execute allow：$sid"
        }
    }

    foreach ($entry in $entries) {
        $entryDenyRules = @((Get-TicketboxInstalledPayloadAcl `
            $entry.FullName).GetAccessRules(
                $true,
                $true,
                [System.Security.Principal.SecurityIdentifier]
            ) | Where-Object {
                $_.AccessControlType -eq
                    [System.Security.AccessControl.AccessControlType]::Deny
            })
        $expectedInherited = -not [string]::Equals(
            [System.IO.Path]::GetFullPath($entry.FullName),
            [System.IO.Path]::GetFullPath($PayloadRoot),
            [System.StringComparison]::OrdinalIgnoreCase
        )
        $expectedInheritanceFlags = if ($entry.PSIsContainer) {
            $requiredInheritance
        }
        else {
            [System.Security.AccessControl.InheritanceFlags]::None
        }
        if (
            $entryDenyRules.Count -ne 1 -or
            -not (Test-TicketboxInstalledPayloadMutationDenyRule `
                -Rule $entryDenyRules[0] `
                -ExpectedInherited $expectedInherited `
                -ExpectedInheritanceFlags $expectedInheritanceFlags)
        ) {
            throw "中断 payload 项的 mutation deny 已漂移：$($entry.FullName)"
        }
    }

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $tokenSids = @([string]$identity.User.Value)
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        $tokenSids += ConvertTo-TicketboxAccountSid "BUILTIN\Administrators"
    }
    $changePermissions =
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions
    $authorized = @($rootRules | Where-Object {
        $_.AccessControlType -eq
            [System.Security.AccessControl.AccessControlType]::Allow -and
        $_.IdentityReference.Value -in $tokenSids -and
        ($_.FileSystemRights -band $changePermissions) -eq $changePermissions
    }).Count -gt 0
    if (-not $authorized) {
        throw "当前安装 token 未由精确 payload DACL 授予 WRITE_DAC。"
    }

    $originalAcl = Copy-TicketboxInstalledPayloadAcl $rootAcl -Directory
    $originalEvidence = Get-TicketboxInstalledPayloadAclEvidence $originalAcl
    $cleanAcl = Copy-TicketboxInstalledPayloadAcl $rootAcl -Directory
    $cleanRules = @($cleanAcl.GetAccessRules(
        $true,
        $false,
        [System.Security.Principal.SecurityIdentifier]
    ) | Where-Object {
        $_.AccessControlType -eq
            [System.Security.AccessControl.AccessControlType]::Deny
    })
    if (
        $cleanRules.Count -ne 1 -or
        -not (Test-TicketboxInstalledPayloadMutationDenyRule `
            -Rule $cleanRules[0] `
            -ExpectedInherited $false `
            -ExpectedInheritanceFlags $requiredInheritance)
    ) {
        throw "中断 payload root 的显式 mutation deny 已漂移。"
    }
    [void]$cleanAcl.RemoveAccessRuleSpecific($cleanRules[0])
    $expectedEvidence = Get-TicketboxInstalledPayloadAclEvidence $cleanAcl
    $aclMutationStarted = $false
    try {
        $aclMutationStarted = $true
        Set-TicketboxInstalledPayloadAcl $PayloadRoot $cleanAcl
        $persisted = Get-TicketboxInstalledPayloadAcl $PayloadRoot
        Assert-TicketboxStructuredEvidence `
            "中断 payload mutation deny 精确退役" `
            (Get-TicketboxInstalledPayloadAclEvidence $persisted) `
            $expectedEvidence
        foreach ($entry in Get-TicketboxInstalledPayloadEntries $PayloadRoot) {
            $remainingDeny = @((Get-TicketboxInstalledPayloadAcl `
                $entry.FullName).GetAccessRules(
                    $true,
                    $true,
                    [System.Security.Principal.SecurityIdentifier]
                ) | Where-Object {
                    $_.AccessControlType -eq
                        [System.Security.AccessControl.AccessControlType]::Deny
                })
            if ($remainingDeny.Count -ne 0) {
                throw "中断 payload mutation deny 未从磁盘完全退役：$($entry.FullName)"
            }
        }
        return $true
    }
    catch {
        $operationFailure = $_.Exception
        if (-not $aclMutationStarted) {
            throw
        }
        try {
            Set-TicketboxInstalledPayloadAcl $PayloadRoot $originalAcl
            $restored = Get-TicketboxInstalledPayloadAcl $PayloadRoot
            Assert-TicketboxStructuredEvidence `
                "中断 payload mutation deny 失败补偿" `
                (Get-TicketboxInstalledPayloadAclEvidence $restored) `
                $originalEvidence
            foreach ($entry in Get-TicketboxInstalledPayloadEntries $PayloadRoot) {
                $restoredDenyRules = @((Get-TicketboxInstalledPayloadAcl `
                    $entry.FullName).GetAccessRules(
                        $true,
                        $true,
                        [System.Security.Principal.SecurityIdentifier]
                    ) | Where-Object {
                        $_.AccessControlType -eq
                            [System.Security.AccessControl.AccessControlType]::Deny
                    })
                $restoredInherited = -not [string]::Equals(
                    [System.IO.Path]::GetFullPath($entry.FullName),
                    [System.IO.Path]::GetFullPath($PayloadRoot),
                    [System.StringComparison]::OrdinalIgnoreCase
                )
                $restoredInheritanceFlags = if ($entry.PSIsContainer) {
                    $requiredInheritance
                }
                else {
                    [System.Security.AccessControl.InheritanceFlags]::None
                }
                if (
                    $restoredDenyRules.Count -ne 1 -or
                    -not (Test-TicketboxInstalledPayloadMutationDenyRule `
                        -Rule $restoredDenyRules[0] `
                        -ExpectedInherited $restoredInherited `
                        -ExpectedInheritanceFlags $restoredInheritanceFlags)
                ) {
                    throw "中断 payload mutation deny 失败补偿未恢复 exact ACE：$($entry.FullName)"
                }
            }
        }
        catch {
            $compensationFailure = $_.Exception
            $aggregate = [System.AggregateException]::new(
                "中断 payload mutation deny 退役与 ACL 补偿均失败。",
                [Exception[]]@($operationFailure, $compensationFailure)
            )
            $aggregate.Data["TicketboxPayloadLeaseRecoveryFailureCode"] =
                "mutation_deny_recovery_compensation_failed"
            throw $aggregate
        }
        throw $operationFailure
    }
}

function Remove-TicketboxInterruptedInstalledPayloadMutationDeny {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$InstallerManifestPath,
        [ValidateRange(1, 99)][int]$ExpectedPgMajor,
        [string[]]$ServiceReadExecuteAccounts = @()
    )

    $canonicalInstallDir = Assert-TicketboxInstallRootDomain $InstallDir
    $expectedManifestPath = [System.IO.Path]::GetFullPath(
        (Join-Path $canonicalInstallDir "installer\BUILD_PROVENANCE.json")
    )
    $actualManifestPath = [System.IO.Path]::GetFullPath($InstallerManifestPath)
    if (-not [string]::Equals(
        $actualManifestPath,
        $expectedManifestPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "中断 payload lease recovery 只接受安装目录内 primary manifest。"
    }
    if ((Get-TicketboxPathEntryKindNoFollow $actualManifestPath) -cne "File") {
        throw "中断 payload lease recovery 缺少普通 primary manifest。"
    }
    Assert-NoTicketboxAncestorReparsePoints $actualManifestPath
    Read-TicketboxInstalledBuildManifest `
        -Path $actualManifestPath `
        -ExpectedPgMajor $ExpectedPgMajor | Out-Null
    $payloadRoot = Join-Path `
        $canonicalInstallDir `
        "program\ticketbox-backend"
    return Remove-TicketboxInterruptedInstalledPayloadMutationDenyExact `
        -PayloadRoot $payloadRoot `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -RequiredReadExecuteAccounts @("BUILTIN\Users") `
        -AllowedReadExecuteAccounts $ServiceReadExecuteAccounts `
        -OwnerAccount "SYSTEM"
}

function Add-TicketboxInstalledPayloadMutationDeny([string]$PayloadRoot) {
    $sourceAcl = Get-TicketboxInstalledPayloadAcl $PayloadRoot
    $originalAcl = Copy-TicketboxInstalledPayloadAcl $sourceAcl -Directory
    $guardedAcl = Copy-TicketboxInstalledPayloadAcl $sourceAcl -Directory
    $everyone = New-Object System.Security.Principal.SecurityIdentifier(
        "S-1-1-0"
    )
    $deniedRights = Get-TicketboxInstalledPayloadMutationDeniedRights
    $inheritance =
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $everyone,
        $deniedRights,
        $inheritance,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Deny
    )
    # This closes ordinary installer-time mutation races.  It is deliberately
    # not described as a sandbox against a local Administrator/SYSTEM actor,
    # which can change the DACL or terminate the installer.
    [void]$guardedAcl.AddAccessRule($rule)
    Set-TicketboxInstalledPayloadAcl $PayloadRoot $guardedAcl
    return [pscustomobject][ordered]@{
        Root = [System.IO.Path]::GetFullPath($PayloadRoot)
        EveryoneSid = $everyone.Value
        DeniedRights = $deniedRights
        OriginalAcl = $originalAcl
        OriginalAclEvidence = Get-TicketboxInstalledPayloadAclEvidence $originalAcl
    }
}

function Assert-TicketboxInstalledPayloadMutationDeny(
    [Parameter(Mandatory = $true)][object]$Guard,
    [Parameter(Mandatory = $true)][object[]]$Entries
) {
    foreach ($entry in $Entries) {
        $acl = Get-TicketboxInstalledPayloadAcl $entry.FullName
        $matching = @($acl.GetAccessRules(
            $true,
            $true,
            [System.Security.Principal.SecurityIdentifier]
        ) | Where-Object {
            $_.IdentityReference.Value -ceq [string]$Guard.EveryoneSid -and
            $_.AccessControlType -eq
                [System.Security.AccessControl.AccessControlType]::Deny -and
            ($_.FileSystemRights -band $Guard.DeniedRights) -eq
                $Guard.DeniedRights
        })
        if ($matching.Count -eq 0) {
            throw "已安装 frozen backend payload 项未继承 mutation deny：$($entry.FullName)"
        }
    }
}

function Restore-TicketboxInstalledPayloadMutationDeny(
    [AllowNull()][object]$Guard
) {
    if ($null -eq $Guard) { return }
    Set-TicketboxInstalledPayloadAcl $Guard.Root $Guard.OriginalAcl
    $restored = Get-TicketboxInstalledPayloadAcl $Guard.Root
    Assert-TicketboxStructuredEvidence `
        "已安装 frozen backend payload 原 DACL 恢复" `
        (Get-TicketboxInstalledPayloadAclEvidence $restored) `
        $Guard.OriginalAclEvidence
}

function ConvertTo-TicketboxInstalledPayloadRecords([object]$Payload) {
    if (
        $null -eq $Payload -or
        [string]$Payload.algorithm -cne "SHA-256" -or
        [string]$Payload.fingerprint -cnotmatch "^[0-9a-f]{64}$"
    ) {
        throw "已安装 frozen backend secondary payload authority 无效。"
    }
    $records = @($Payload.files)
    if ($records.Count -eq 0) {
        throw "已安装 frozen backend secondary payload 文件集为空。"
    }
    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($record in $records) {
        $propertyNames = @($record.PSObject.Properties.Name)
        if (
            $propertyNames.Count -ne 3 -or
            "path" -notin $propertyNames -or
            "size" -notin $propertyNames -or
            "sha256" -notin $propertyNames
        ) {
            throw "已安装 frozen backend secondary payload 文件证据 shape 无效。"
        }
        $relativePath = [string]$record.path
        $segments = @($relativePath.Split("/"))
        if (
            [string]::IsNullOrWhiteSpace($relativePath) -or
            [System.IO.Path]::IsPathRooted($relativePath) -or
            $relativePath.Contains("\") -or
            $relativePath.Contains(":") -or
            $relativePath -cmatch "[^\x20-\x7e]" -or
            $relativePath.StartsWith("/") -or
            $relativePath.EndsWith("/") -or
            @($segments | Where-Object {
                [string]::IsNullOrEmpty($_) -or $_ -in @(".", "..")
            }).Count -gt 0
        ) {
            throw "已安装 frozen backend secondary payload 路径不是 canonical 相对路径。"
        }
        if (-not $seen.Add($relativePath)) {
            throw "已安装 frozen backend secondary payload 路径大小写重复：$relativePath"
        }
        $size = [int64]0
        if (
            -not [int64]::TryParse([string]$record.size, [ref]$size) -or
            $size -lt 0 -or
            [string]$record.sha256 -cnotmatch "^[0-9a-f]{64}$"
        ) {
            throw "已安装 frozen backend secondary payload size/SHA-256 无效：$relativePath"
        }
        $paths.Add($relativePath)
    }
    $sorted = [string[]]@($paths)
    [Array]::Sort($sorted, [System.StringComparer]::OrdinalIgnoreCase)
    for ($index = 0; $index -lt $sorted.Count; $index++) {
        if ($sorted[$index] -cne [string]$records[$index].path) {
            $failure = [System.IO.InvalidDataException]::new(
                "已安装 frozen backend secondary payload 文件记录未按 ordinal-ignore-case 排序。"
            )
            $failure.Data["TicketboxInstallPublicFailureCode"] =
                "backend_payload_manifest_order_invalid"
            throw $failure
        }
    }
    foreach ($requiredPath in $script:TicketboxInstalledC07ExternalAuthorityPaths) {
        if (-not $seen.Contains($requiredPath)) {
            throw "已安装 C07 外置迁移 authority 缺少必需文件：$requiredPath"
        }
    }
    $migrationRecords = @($records | Where-Object {
        ([string]$_.path).StartsWith(
            "_internal/migrations/",
            [System.StringComparison]::Ordinal
        )
    })
    if ($migrationRecords.Count -lt 3) {
        throw "已安装 C07 外置 migrations authority 文件集不完整。"
    }
    return @($records)
}

function Assert-TicketboxInstalledBackendManifestChain(
    [Parameter(Mandatory = $true)][object]$Primary,
    [Parameter(Mandatory = $true)][object]$Secondary,
    [Parameter(Mandatory = $true)][System.IO.FileStream]$SecondaryStream
) {
    if (
        [int]$Secondary.schema_version -ne 4 -or
        [string]$Secondary.artifact_type -cne "ticketbox-frozen-backend" -or
        [string]$Secondary.backend_version -cne [string]$Primary.backend.version
    ) {
        throw "installed primary/secondary backend identity 不一致。"
    }
    $manifestEvidence = $Primary.backend.manifest
    $manifestProperties = @($manifestEvidence.PSObject.Properties.Name)
    if (
        $manifestProperties.Count -ne 3 -or
        [string]$manifestEvidence.path -cne
            $script:TicketboxInstalledBackendManifestRelativePath -or
        [int64]$manifestEvidence.size -ne [int64]$SecondaryStream.Length -or
        [string]$manifestEvidence.sha256 -cnotmatch "^[0-9a-f]{64}$" -or
        [string]$manifestEvidence.sha256 -cne
            (Get-TicketboxOpenFileSha256Lower $SecondaryStream)
    ) {
        throw "installed primary 未精确绑定 secondary backend manifest size/SHA-256。"
    }
    if (
        [string]$Primary.backend.payload_algorithm -cne "SHA-256" -or
        [string]$Primary.backend.payload_fingerprint -cne
            [string]$Secondary.payload.fingerprint
    ) {
        throw "installed primary/secondary backend payload fingerprint 不一致。"
    }
    $primaryHelper = $Primary.backend.c07_migration_helper
    $secondaryHelper = $Secondary.payload.c07_migration_helper
    foreach ($name in @("path", "size", "sha256")) {
        if ([string]$primaryHelper.$name -cne [string]$secondaryHelper.$name) {
            throw "installed primary/secondary C07 migration helper evidence 不一致。"
        }
    }
    $helperRecords = @($Secondary.payload.files | Where-Object {
        [string]$_.path -ceq [string]$secondaryHelper.path
    })
    if ($helperRecords.Count -ne 1) {
        throw "installed secondary payload 未唯一绑定 C07 migration helper record。"
    }
    foreach ($name in @("path", "size", "sha256")) {
        if ([string]$helperRecords[0].$name -cne [string]$secondaryHelper.$name) {
            throw "installed secondary C07 migration helper evidence 与 payload record 不一致。"
        }
    }
    Assert-TicketboxStructuredEvidence `
        "installed primary/secondary C07 migration helper smoke" `
        $Primary.backend.c07_migration_helper_smoke `
        $Secondary.payload.c07_migration_helper_smoke
    Assert-TicketboxC07MigrationHelperSmokeEvidence `
        $Secondary.payload.c07_migration_helper_smoke `
        $secondaryHelper `
        $Secondary.payload `
        (Split-Path -Parent $SecondaryStream.Name)
}

function Enter-TicketboxInstalledC07PayloadAuthorityLease {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$InstallerManifestPath,
        [ValidateRange(0, 99)][int]$ExpectedPgMajor = 0
    )

    foreach ($requiredFunction in @(
        "Get-TicketboxPathEntryKindNoFollow",
        "Assert-NoTicketboxAncestorReparsePoints",
        "Read-TicketboxInstalledBuildManifest"
    )) {
        if (-not (Get-Command $requiredFunction -CommandType Function -ErrorAction SilentlyContinue)) {
            throw "installed C07 payload authority lease 缺少依赖：$requiredFunction"
        }
    }
    $canonicalInstallDir = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd("\", "/")
    $expectedPrimaryPath = [System.IO.Path]::GetFullPath(
        (Join-Path $canonicalInstallDir "installer\BUILD_PROVENANCE.json")
    )
    $primaryPath = [System.IO.Path]::GetFullPath($InstallerManifestPath)
    if (-not [string]::Equals(
        $primaryPath,
        $expectedPrimaryPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "installed C07 payload authority 只接受安装目录内 primary manifest。"
    }
    $payloadRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $canonicalInstallDir "program\ticketbox-backend")
    )
    $secondaryPath = Join-Path `
        $payloadRoot `
        $script:TicketboxInstalledBackendPayloadManifestName
    $streams = New-Object System.Collections.Generic.List[System.IO.FileStream]
    $streamEvidence = New-Object System.Collections.Generic.List[object]
    $guard = $null
    try {
        $entries = @(Get-TicketboxInstalledPayloadEntries $payloadRoot)
        $guard = Add-TicketboxInstalledPayloadMutationDeny $payloadRoot
        $sealedEntries = @(Get-TicketboxInstalledPayloadEntries $payloadRoot)
        $beforePaths = [string[]]@($entries | ForEach-Object { $_.FullName })
        $afterPaths = [string[]]@($sealedEntries | ForEach-Object { $_.FullName })
        [Array]::Sort($beforePaths, [System.StringComparer]::OrdinalIgnoreCase)
        [Array]::Sort($afterPaths, [System.StringComparer]::OrdinalIgnoreCase)
        if (($beforePaths -join "`n") -cne ($afterPaths -join "`n")) {
            throw "installed frozen backend payload 在 ACL seal 期间发生目录项漂移。"
        }
        Assert-TicketboxInstalledPayloadMutationDeny $guard $sealedEntries

        foreach ($manifestPath in @($primaryPath, $secondaryPath)) {
            if ((Get-TicketboxPathEntryKindNoFollow $manifestPath) -cne "File") {
                throw "installed build provenance manifest 不是普通文件：$manifestPath"
            }
            Assert-NoTicketboxAncestorReparsePoints $manifestPath
            $streams.Add([System.IO.File]::Open(
                $manifestPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            ))
            $manifestStream = $streams[$streams.Count - 1]
            $streamEvidence.Add([pscustomobject][ordered]@{
                Path = $manifestPath
                Size = [int64]$manifestStream.Length
                Sha256 = Get-TicketboxOpenFileSha256Lower $manifestStream
            })
        }
        $primaryResult = Read-TicketboxInstalledBuildManifest `
            -Path $primaryPath `
            -ExpectedPgMajor $ExpectedPgMajor
        $primary = Read-TicketboxUtf8JsonFromOpenFile $streams[0] "installed primary provenance"
        $secondary = Read-TicketboxUtf8JsonFromOpenFile $streams[1] "installed secondary provenance"
        Assert-TicketboxStructuredEvidence `
            "installed primary manifest locked reread" `
            $primaryResult.Manifest `
            $primary
        Assert-TicketboxInstalledBackendManifestChain $primary $secondary $streams[1]
        $records = @(ConvertTo-TicketboxInstalledPayloadRecords $secondary.payload)

        $fingerprintRows = New-Object System.Collections.Generic.List[string]
        $recordedPaths = New-Object System.Collections.Generic.List[string]
        foreach ($record in $records) {
            $relativePath = [string]$record.path
            $path = [System.IO.Path]::GetFullPath(
                (Join-Path $payloadRoot $relativePath.Replace("/", "\"))
            )
            $prefix = $payloadRoot.TrimEnd("\", "/") +
                [System.IO.Path]::DirectorySeparatorChar
            if (-not $path.StartsWith(
                $prefix,
                [System.StringComparison]::OrdinalIgnoreCase
            )) {
                throw "installed secondary payload 路径逃逸 payload root：$relativePath"
            }
            if ((Get-TicketboxPathEntryKindNoFollow $path) -cne "File") {
                throw "installed secondary payload 记录不是普通文件：$relativePath"
            }
            Assert-NoTicketboxAncestorReparsePoints $path
            $stream = [System.IO.File]::Open(
                $path,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
            $streams.Add($stream)
            $sha256 = Get-TicketboxOpenFileSha256Lower $stream
            if (
                [int64]$stream.Length -ne [int64]$record.size -or
                $sha256 -cne [string]$record.sha256
            ) {
                throw "installed secondary payload size/SHA-256 漂移：$relativePath"
            }
            $streamEvidence.Add([pscustomobject][ordered]@{
                Path = $path
                Size = [int64]$stream.Length
                Sha256 = $sha256
            })
            $recordedPaths.Add($relativePath)
            $fingerprintRows.Add(
                ("{0}`0{1}`0{2}`n" -f $relativePath, $stream.Length, $sha256)
            )
        }
        $actualPaths = [string[]]@($sealedEntries | Where-Object {
            -not $_.PSIsContainer -and
            -not [string]::Equals(
                $_.FullName,
                $secondaryPath,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        } | ForEach-Object {
            Get-TicketboxRelativePath $payloadRoot $_.FullName
        })
        [Array]::Sort($actualPaths, [System.StringComparer]::OrdinalIgnoreCase)
        if (($actualPaths -join "`n") -cne (@($recordedPaths) -join "`n")) {
            throw "installed secondary payload 文件集合存在 extra/missing 路径。"
        }
        $actualFingerprint = Get-TicketboxSha256HexFromText (
            @($fingerprintRows) -join ""
        )
        if ($actualFingerprint -cne [string]$secondary.payload.fingerprint) {
            throw "installed secondary payload 汇总 fingerprint 漂移。"
        }
        return [pscustomobject][ordered]@{
            InstallDir = $canonicalInstallDir
            PayloadRoot = $payloadRoot
            PrimaryManifestPath = $primaryPath
            SecondaryManifestPath = $secondaryPath
            InstalledBuildManifest = $primaryResult
            PayloadFingerprint = $actualFingerprint
            PayloadFileCount = $records.Count
            Guard = $guard
            Streams = @($streams.ToArray())
            StreamEvidence = @($streamEvidence.ToArray())
        }
    }
    catch {
        foreach ($stream in $streams) {
            $stream.Dispose()
        }
        Restore-TicketboxInstalledPayloadMutationDeny $guard
        throw
    }
}

function Close-TicketboxInstalledC07PayloadAuthorityLease(
    [AllowNull()][object]$Lease
) {
    if ($null -eq $Lease) { return }
    $failure = $null
    try {
        $streams = @($Lease.Streams)
        $evidence = @($Lease.StreamEvidence)
        if ($streams.Count -ne $evidence.Count) {
            throw "installed C07 payload authority lease evidence 数量漂移。"
        }
        for ($index = 0; $index -lt $streams.Count; $index++) {
            $stream = $streams[$index]
            if ($stream.SafeFileHandle.IsClosed) {
                throw "installed C07 payload authority lease 中途关闭。"
            }
            $sha256 = Get-TicketboxOpenFileSha256Lower $stream
            if (
                [int64]$stream.Length -ne [int64]$evidence[$index].Size -or
                $sha256 -cne [string]$evidence[$index].Sha256
            ) {
                throw "installed C07 payload authority lease 字节身份漂移：$($evidence[$index].Path)"
            }
        }
    }
    catch {
        $failure = $_.Exception
    }
    finally {
        foreach ($stream in @($Lease.Streams)) {
            if (-not $stream.SafeFileHandle.IsClosed) {
                $stream.Dispose()
            }
        }
        try {
            Restore-TicketboxInstalledPayloadMutationDeny $Lease.Guard
        }
        catch {
            if ($null -eq $failure) {
                $failure = $_.Exception
            }
            else {
                $restoreFailure = $_.Exception
                $aggregateFailure = [AggregateException]::new(
                    (
                        "installed C07 payload authority lease 关闭失败；" +
                        "字节验证与 DACL 恢复错误均已保留。"
                    ),
                    [Exception[]]@($failure, $restoreFailure)
                )
                $aggregateFailure.Data["TicketboxC07FailureCode"] =
                    "installed_payload_lease_close_failed"
                $failure = $aggregateFailure
            }
        }
    }
    if ($null -ne $failure) { throw $failure }
}

function Assert-TicketboxStructuredEvidence(
    [string]$Label,
    [object]$Recorded,
    [object]$Expected
) {
    if ($null -eq $Recorded -or $null -eq $Expected) { throw "$Label 缺少结构化证据。" }
    if (
        ($Recorded | ConvertTo-Json -Depth 20 -Compress) -cne
        ($Expected | ConvertTo-Json -Depth 20 -Compress)
    ) {
        throw "$Label 与本轮已验证输入不一致。"
    }
}
function ConvertTo-TicketboxVendorVersion([string]$Value, [string]$Label) {
    $match = [regex]::Match($Value, '^(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?$')
    if (-not $match.Success) {
        throw "$Label 必须是 2 到 4 段纯数字版本：$Value"
    }
    $parts = @()
    foreach ($index in 1..4) {
        if ($match.Groups[$index].Success) { $parts += [int]$match.Groups[$index].Value }
        else { $parts += 0 }
    }
    return [Version]("{0}.{1}.{2}.{3}" -f $parts[0], $parts[1], $parts[2], $parts[3])
}
function Get-TicketboxVendorVersionPolicy([object]$Config, [string]$Vendor) {
    $propertyName = "${Vendor}_version_policy"
    $property = $Config.PSObject.Properties[$propertyName]
    if ($null -eq $property -or $null -eq $property.Value) {
        throw "Windows release config 缺少 $propertyName。"
    }
    $policy = $property.Value
    $minimum = [string]$policy.minimum
    $maximumExclusive = [string]$policy.maximum_exclusive
    $minimumVersion = ConvertTo-TicketboxVendorVersion $minimum "$propertyName.minimum"
    $maximumVersion = ConvertTo-TicketboxVendorVersion $maximumExclusive "$propertyName.maximum_exclusive"
    if ($minimumVersion.CompareTo($maximumVersion) -ge 0) {
        throw "Windows release config 的 $propertyName 必须满足 minimum < maximum_exclusive。"
    }
    return [pscustomobject]@{
        minimum = $minimum
        maximum_exclusive = $maximumExclusive
        minimum_version = $minimumVersion
        maximum_version = $maximumVersion
    }
}
function Assert-TicketboxVendorVersionAllowed([object]$Config, [string]$Vendor, [string]$Version) {
    $policy = Get-TicketboxVendorVersionPolicy $Config $Vendor
    $candidate = ConvertTo-TicketboxVendorVersion $Version "$Vendor executable version"
    if (
        $candidate.CompareTo($policy.minimum_version) -lt 0 -or
        $candidate.CompareTo($policy.maximum_version) -ge 0
    ) {
        throw "$Vendor 版本不符合 release config 策略：version=$Version，允许 [$($policy.minimum), $($policy.maximum_exclusive))"
    }
    return [pscustomobject]@{
        minimum = $policy.minimum
        maximum_exclusive = $policy.maximum_exclusive
    }
}
function Invoke-TicketboxGitText([string]$Root, [string[]]$Arguments, [switch]$AllowEmpty) {
    $output = @(& git -C $Root @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $rawText = ($output | ForEach-Object { $_.ToString() }) -join "`n"
    $text = if ($AllowEmpty) { $rawText.TrimEnd() } else { $rawText.Trim() }
    if ($exitCode -ne 0) {
        throw "git provenance 探针失败（exit=$exitCode）：$text"
    }
    if (-not $AllowEmpty -and $text.Length -eq 0) {
        throw "git provenance 探针没有输出：git $($Arguments -join ' ')"
    }
    return $text
}
function Get-TicketboxGitProvenance([string]$Root) {
    $commit = Invoke-TicketboxGitText $Root @("rev-parse", "--verify", "HEAD")
    if ($commit -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw "git HEAD 不是支持的 commit id：$commit"
    }
    $status = Invoke-TicketboxGitText $Root @("status", "--porcelain=v1", "--untracked-files=all") -AllowEmpty
    $statusEntries = @($status -split "`n" | Where-Object { $_.Trim().Length -gt 0 })
    return [pscustomobject]@{
        commit = $commit.ToLowerInvariant()
        dirty = $statusEntries.Count -gt 0
        status_entry_count = $statusEntries.Count
        status_fingerprint = Get-TicketboxSha256HexFromText $status
    }
}
function Get-TicketboxIsccEngineVersion([string]$Path) {
    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\", "/")
    $probeDirectory = Join-Path $tempRoot ("ticketbox-iscc-probe-{0}-{1}" -f $PID, [Guid]::NewGuid().ToString("N"))
    $probePath = Join-Path $probeDirectory "probe.iss"
    $probeText = @(
        "[Setup]",
        "AppName=TicketboxCompilerProbe",
        "AppVersion=1.0.0",
        "DefaultDirName={tmp}\TicketboxCompilerProbe",
        "Uninstallable=no",
        "OutputBaseFilename=probe"
    ) -join [Environment]::NewLine
    try {
        New-Item -ItemType Directory -Path $probeDirectory | Out-Null
        [System.IO.File]::WriteAllText(
            $probePath,
            $probeText + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
        )
        $output = @(& $Path "/O$probeDirectory" $probePath 2>&1)
        $exitCode = $LASTEXITCODE
        $text = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        if ($exitCode -ne 0) {
            throw "ISCC engine version probe failed (exit=$exitCode): $text"
        }
        $match = [regex]::Match(
            $text,
            '(?m)^Compiler engine version:\s+Inno Setup\s+(\d+\.\d+\.\d+)\s*$'
        )
        if (-not $match.Success) { throw "Cannot parse ISCC engine version output." }
        return $match.Groups[1].Value
    }
    finally {
        $canonicalProbe = [System.IO.Path]::GetFullPath($probeDirectory)
        $tempPrefix = $tempRoot + [System.IO.Path]::DirectorySeparatorChar
        if (
            $canonicalProbe.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $canonicalProbe)
        ) {
            Remove-Item -LiteralPath $canonicalProbe -Recurse -Force
        }
    }
}

function Get-TicketboxIsccProvenance([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 ISCC.exe：$Path"
    }
    $item = Get-Item -LiteralPath $Path
    $versionInfo = $item.VersionInfo
    $identityText = "$($versionInfo.ProductName) $($versionInfo.FileDescription)"
    if ($identityText -notmatch '(?i)Inno Setup') {
        throw "指定编译器的 Windows 版本身份不是 Inno Setup：$identityText"
    }
    if ([string]::IsNullOrWhiteSpace($versionInfo.FileVersion)) {
        throw "ISCC.exe 缺少 Windows FileVersion，拒绝生成不可追溯安装包。"
    }
    return [pscustomobject]@{
        product_name = $versionInfo.ProductName
        product_version = $versionInfo.ProductVersion
        file_version = $versionInfo.FileVersion
        engine_version = Get-TicketboxIsccEngineVersion $item.FullName
        executable = Get-TicketboxFileEvidence (Split-Path -Parent $Path) $Path
    }
}
function Invoke-TicketboxExecutableProbe([string]$Path, [string[]]$Arguments, [string]$Label) {
    $output = @(& $Path @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = (($output | ForEach-Object { $_.ToString() }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        throw "$Label 探针失败（exit=$exitCode）：$text"
    }
    if ($text.Length -eq 0) {
        throw "$Label 探针没有输出，拒绝继续。"
    }
    return $text
}
function Read-TicketboxPgBundleManifest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "缺少 PostgreSQL BUNDLE_MANIFEST.txt：$Path"
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $match = [regex]::Match($line, '^\s*([a-z0-9_]+)\s*=\s*(.*?)\s*$')
        if ($match.Success) {
            $name = $match.Groups[1].Value
            if ($values.ContainsKey($name)) {
                throw "PostgreSQL BUNDLE_MANIFEST.txt 字段重复：$name"
            }
            $values[$name] = $match.Groups[2].Value
        }
    }
    foreach ($required in @(
        "pg_version",
        "source_zip",
        "source_sha256",
        "source_url",
        "payload_file_count",
        "payload_fingerprint",
        "license"
    )) {
        if (-not $values.ContainsKey($required) -or $values[$required].Trim().Length -eq 0) {
            throw "PostgreSQL BUNDLE_MANIFEST.txt 缺少字段：$required"
        }
    }
    if ($values["source_sha256"] -notmatch '^[0-9a-fA-F]{64}$') {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 source_sha256 格式无效。"
    }
    if (
        $values["payload_file_count"] -notmatch '^\d+$' -or
        [int64]$values["payload_file_count"] -le 0
    ) {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 payload_file_count 格式无效。"
    }
    if ($values["payload_fingerprint"] -notmatch '^[0-9a-fA-F]{64}$') {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 payload_fingerprint 格式无效。"
    }
    $sourceUri = $null
    if (
        -not [Uri]::TryCreate($values["source_url"], [UriKind]::Absolute, [ref]$sourceUri) -or
        $sourceUri.Scheme -ne "https"
    ) {
        throw "PostgreSQL BUNDLE_MANIFEST.txt 的 source_url 必须是 HTTPS 绝对地址。"
    }
    return $values
}

function Get-TicketboxInstallerRecipePaths([string]$BackendRoot) {
    $paths = @()
    foreach ($relativePath in $script:TicketboxInstallerRecipeRelativePaths) {
        $path = Join-Path $BackendRoot $relativePath
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Windows 安装器配方缺少必需文件：$path"
        }
        $paths += (Resolve-Path -LiteralPath $path).Path
    }
    return @(Get-TicketboxOrdinalSortedPaths $paths)
}

function Get-TicketboxInstallerRecipeSnapshot([string]$BackendRoot) {
    return Get-TicketboxFileSetSnapshot $BackendRoot (Get-TicketboxInstallerRecipePaths $BackendRoot)
}

function Get-TicketboxNormalizedCompilerDefines([string[]]$Defines) {
    $normalized = [string[]]@()
    $names = @{}
    foreach ($define in $Defines) {
        $match = [regex]::Match([string]$define, '^/D([A-Za-z][A-Za-z0-9_]*)=(.+)$')
        if (-not $match.Success) {
            throw "ISCC define does not use the required /DName=Value form: $define"
        }
        $name = $match.Groups[1].Value
        if ($names.ContainsKey($name)) { throw "Duplicate ISCC define: $name" }
        $names[$name] = $true
        $normalized += [string]$define
    }
    [Array]::Sort($normalized, [System.StringComparer]::Ordinal)
    return $normalized
}

function Assert-TicketboxInstallerBuildProvenance(
    [string]$BackendRoot,
    [string]$Path,
    [object]$ExpectedCompilerProvenance,
    [object]$ExpectedBuildInputs,
    [string[]]$ExpectedCompilerDefines
) {
    try {
        $manifest = Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
    }
    catch {
        throw "安装器 provenance 不是有效 JSON：$Path。$($_.Exception.Message)"
    }
    if ($manifest.schema_version -ne 3 -or $manifest.artifact_type -cne "ticketbox-windows-installer-inputs") {
        throw "安装器 provenance schema/artifact_type 不受支持。"
    }
    Assert-TicketboxStructuredEvidence "安装器 ISCC defines" @($manifest.compiler_defines) @(Get-TicketboxNormalizedCompilerDefines $ExpectedCompilerDefines)
    Assert-TicketboxFileSetSnapshot `
        "Windows 安装器 recipe" `
        $manifest.recipe `
        (Get-TicketboxInstallerRecipeSnapshot $BackendRoot)
    $currentGit = Get-TicketboxGitProvenance $BackendRoot
    if (
        $manifest.git.commit -cne $currentGit.commit -or
        [bool]$manifest.git.dirty -ne [bool]$currentGit.dirty -or
        [int]$manifest.git.status_entry_count -ne [int]$currentGit.status_entry_count -or
        $manifest.git.status_fingerprint -cne $currentGit.status_fingerprint
    ) {
        throw "安装器 provenance 的 Git SHA/dirty state 与当前工作树不一致。"
    }
    $expectsCompiler = $null -ne $ExpectedCompilerProvenance
    if ([bool]$manifest.compiler.included -ne $expectsCompiler) {
        throw "安装器 provenance 的 ISCC identity presence 不一致。"
    }
    if ($expectsCompiler) {
        $recordedExe = $manifest.compiler.executable
        $expectedExe = $ExpectedCompilerProvenance.executable
        if (
            [string]$manifest.compiler.product_name -cne [string]$ExpectedCompilerProvenance.product_name -or
            [string]$manifest.compiler.product_version -cne [string]$ExpectedCompilerProvenance.product_version -or
            [string]$manifest.compiler.file_version -cne [string]$ExpectedCompilerProvenance.file_version -or
            [string]$manifest.compiler.engine_version -cne [string]$ExpectedCompilerProvenance.engine_version -or
            ($manifest.compiler.version_policy | ConvertTo-Json -Compress) -cne
            ($ExpectedCompilerProvenance.version_policy | ConvertTo-Json -Compress) -or
            $recordedExe.path -cne $expectedExe.path -or
            [int64]$recordedExe.size -ne [int64]$expectedExe.size -or
            $recordedExe.sha256 -cne $expectedExe.sha256
        ) {
            throw "安装器 provenance 的 ISCC identity 与选定编译器不一致。"
        }
    }
    Assert-TicketboxStructuredEvidence `
        "安装器 backend provenance" `
        $manifest.backend `
        $ExpectedBuildInputs.backend
    Assert-TicketboxStructuredEvidence `
        "安装器 Desktop Manager provenance" `
        $manifest.manager `
        $ExpectedBuildInputs.manager
    Assert-TicketboxStructuredEvidence `
        "安装器 PostgreSQL provenance" `
        $manifest.postgresql `
        $ExpectedBuildInputs.postgresql
    Assert-TicketboxStructuredEvidence `
        "安装器 Shawl provenance" `
        $manifest.shawl `
        $ExpectedBuildInputs.shawl
    return $manifest
}

function Write-TicketboxJsonFile([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $temporaryPath = "$Path.$PID.tmp"
    $json = $Value | ConvertTo-Json -Depth 12
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $json + "`n", $encoding)
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    }
}

$backendBuildProvenanceScript = Join-Path $PSScriptRoot "windows_backend_build_provenance.ps1"
if (-not (Test-Path -LiteralPath $backendBuildProvenanceScript -PathType Leaf)) {
    throw "Missing backend build provenance helper: $backendBuildProvenanceScript"
}
. $backendBuildProvenanceScript
