#Requires -Version 5.1

function Get-TicketboxWindowsSecurityDescriptorDifferenceDiagnostic {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )

    try {
        $leftDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Left, 0)
        $rightDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Right, 0)
        $leftFlags = [int]$leftDescriptor.ControlFlags -band 0xFFFF
        $rightFlags = [int]$rightDescriptor.ControlFlags -band 0xFFFF
        $flagsXor = ($leftFlags -bxor $rightFlags) -band 0xFFFF
        $daclFlags = [int](
            [Security.AccessControl.ControlFlags]::DiscretionaryAclPresent -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclUntrusted -bor
            [Security.AccessControl.ControlFlags]::ServerSecurity -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected
        )
        $saclFlags = [int](
            [Security.AccessControl.ControlFlags]::SystemAclPresent -bor
            [Security.AccessControl.ControlFlags]::SystemAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::SystemAclProtected
        )
        $ownerEqual = if (
            $null -eq $leftDescriptor.Owner -or
            $null -eq $rightDescriptor.Owner
        ) {
            $null -eq $leftDescriptor.Owner -and
                $null -eq $rightDescriptor.Owner
        }
        else {
            $leftDescriptor.Owner.Equals($rightDescriptor.Owner)
        }
        $groupEqual = if (
            $null -eq $leftDescriptor.Group -or
            $null -eq $rightDescriptor.Group
        ) {
            $null -eq $leftDescriptor.Group -and
                $null -eq $rightDescriptor.Group
        }
        else {
            $leftDescriptor.Group.Equals($rightDescriptor.Group)
        }
        $daclBinaryEqual = Test-TicketboxWindowsRawAclEquals `
            -Left $leftDescriptor.DiscretionaryAcl `
            -Right $rightDescriptor.DiscretionaryAcl
        $saclBinaryEqual = Test-TicketboxWindowsRawAclEquals `
            -Left $leftDescriptor.SystemAcl `
            -Right $rightDescriptor.SystemAcl
        $daclComponentEqual =
            ($flagsXor -band $daclFlags) -eq 0 -and $daclBinaryEqual
        $saclComponentEqual =
            ($flagsXor -band $saclFlags) -eq 0 -and $saclBinaryEqual
        $diagnosticFormat =
            "security_descriptor_diagnostic " +
            "control_flags_left=0x{0:X4} control_flags_right=0x{1:X4} " +
            "control_flags_xor=0x{2:X4} owner_equal={3} group_equal={4} " +
            "dacl_component_equal={5} dacl_binary_equal={6} " +
            "sacl_component_equal={7} sacl_binary_equal={8} " +
            "rm_control_equal={9} revision_equal={10}"
        return $diagnosticFormat -f @(
            $leftFlags,
            $rightFlags,
            $flagsXor,
            $ownerEqual.ToString().ToLowerInvariant(),
            $groupEqual.ToString().ToLowerInvariant(),
            $daclComponentEqual.ToString().ToLowerInvariant(),
            $daclBinaryEqual.ToString().ToLowerInvariant(),
            $saclComponentEqual.ToString().ToLowerInvariant(),
            $saclBinaryEqual.ToString().ToLowerInvariant(),
            ($leftDescriptor.ResourceManagerControl -eq
                $rightDescriptor.ResourceManagerControl).ToString().ToLowerInvariant(),
            ($leftDescriptor.Revision -eq
                $rightDescriptor.Revision).ToString().ToLowerInvariant()
        )
    }
    catch {
        return (
            "security_descriptor_diagnostic control_flags_left=unavailable " +
            "control_flags_right=unavailable control_flags_xor=unavailable " +
            "owner_equal=unavailable group_equal=unavailable " +
            "dacl_component_equal=unavailable dacl_binary_equal=unavailable " +
            "sacl_component_equal=unavailable sacl_binary_equal=unavailable " +
            "rm_control_equal=unavailable revision_equal=unavailable"
        )
    }
}

function Get-TicketboxWindowsCreationSecuritySddl {
    param([Parameter(Mandatory = $true)][byte[]]$SecurityBytes)

    $security = New-Object Security.AccessControl.FileSecurity
    try {
        $security.SetSecurityDescriptorBinaryForm($SecurityBytes)
        $sections =
            [Security.AccessControl.AccessControlSections]::Access -bor
            [Security.AccessControl.AccessControlSections]::Owner -bor
            [Security.AccessControl.AccessControlSections]::Group
        return $security.GetSecurityDescriptorSddlForm($sections)
    }
    catch {
        throw "Windows file creation security descriptor 无效。"
    }
}

function Test-TicketboxWindowsCreationSecurityEquals {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )

    try {
        $leftDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Left, 0)
        $rightDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Right, 0)
        $saclFlags = [int](
            [Security.AccessControl.ControlFlags]::SystemAclPresent -bor
            [Security.AccessControl.ControlFlags]::SystemAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::SystemAclProtected
        )
        $leftDescriptor.SystemAcl = $rightDescriptor.SystemAcl
        $leftDescriptor.SetFlags([Security.AccessControl.ControlFlags](
            ([int]$leftDescriptor.ControlFlags -band (-bnot $saclFlags)) -bor
            ([int]$rightDescriptor.ControlFlags -band $saclFlags)
        ))
        $normalizedLeft = New-Object byte[] $leftDescriptor.BinaryLength
        $leftDescriptor.GetBinaryForm($normalizedLeft, 0)
        return Test-TicketboxWindowsSecurityDescriptorEquals `
            -Left $normalizedLeft `
            -Right $Right
    }
    catch {
        return $false
    }
}
