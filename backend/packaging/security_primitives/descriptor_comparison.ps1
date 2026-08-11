#Requires -Version 5.1

function Test-TicketboxWindowsSecurityDescriptorEquals {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right,
        [switch]$AllowWindowsReplacementDaclProjection
    )

    if (Test-TicketboxWindowsByteArrayEquals -Left $Left -Right $Right) {
        return $true
    }
    try {
        $ignoredFlags =
            [Security.AccessControl.ControlFlags]::OwnerDefaulted -bor
            [Security.AccessControl.ControlFlags]::GroupDefaulted -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::SystemAclDefaulted -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInheritRequired -bor
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited -bor
            [Security.AccessControl.ControlFlags]::SystemAclAutoInherited
        $ignoredMask = [int]$ignoredFlags
        $leftDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Left, 0)
        $rightDescriptor = New-Object `
            Security.AccessControl.RawSecurityDescriptor($Right, 0)
        $leftSecurity = New-Object Security.AccessControl.FileSecurity
        $rightSecurity = New-Object Security.AccessControl.FileSecurity
        $leftSecurity.SetSecurityDescriptorBinaryForm($Left)
        $rightSecurity.SetSecurityDescriptorBinaryForm($Right)
        if (
            -not $leftSecurity.AreAccessRulesCanonical -or
            -not $rightSecurity.AreAccessRulesCanonical -or
            -not $leftSecurity.AreAuditRulesCanonical -or
            -not $rightSecurity.AreAuditRulesCanonical
        ) {
            return $false
        }
        $leftFlags = [int]$leftDescriptor.ControlFlags -band (-bnot $ignoredMask)
        $rightFlags = [int]$rightDescriptor.ControlFlags -band (-bnot $ignoredMask)
        $daclAutoInherited = [int](
            [Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
        )
        # ReplaceFileW may materialize the replaced file's otherwise exact
        # DACL as auto-inherited.  This projection is directional: the live
        # result is Left and the captured pre-replacement descriptor is Right.
        $allowProjectedInheritedAceProvenance =
            $AllowWindowsReplacementDaclProjection -and
            (([int]$leftDescriptor.ControlFlags -band $daclAutoInherited) -ne 0) -and
            (([int]$rightDescriptor.ControlFlags -band $daclAutoInherited) -eq 0)
        if (
            $leftFlags -ne $rightFlags -or
            -not $leftDescriptor.Owner.Equals($rightDescriptor.Owner) -or
            -not $leftDescriptor.Group.Equals($rightDescriptor.Group) -or
            $leftDescriptor.ResourceManagerControl -ne
                $rightDescriptor.ResourceManagerControl -or
            $leftDescriptor.Revision -ne $rightDescriptor.Revision
        ) {
            return $false
        }
        $normalizeDaclMasks = (
            ([int]$leftDescriptor.ControlFlags -bor
                [int]$rightDescriptor.ControlFlags) -band
                [int][Security.AccessControl.ControlFlags]::DiscretionaryAclAutoInherited
        ) -ne 0
        return (
            (Test-TicketboxWindowsRawAclEquals `
                -Left $leftDescriptor.DiscretionaryAcl `
                -Right $rightDescriptor.DiscretionaryAcl `
                -NormalizeInheritedProvenance `
                -NormalizeEquivalentQualifiedMasks:$normalizeDaclMasks `
                -IgnoreInheritedAceProvenance:$allowProjectedInheritedAceProvenance) -and
            (Test-TicketboxWindowsRawAclEquals `
                -Left $leftDescriptor.SystemAcl `
                -Right $rightDescriptor.SystemAcl `
                -NormalizeInheritedProvenance)
        )
    }
    catch {
        return $false
    }
}

function Test-TicketboxWindowsRawAclEquals {
    param(
        [AllowNull()][object]$Left,
        [AllowNull()][object]$Right,
        [switch]$NormalizeInheritedProvenance,
        [switch]$NormalizeEquivalentQualifiedMasks,
        [switch]$IgnoreInheritedAceProvenance
    )

    if ($null -eq $Left -or $null -eq $Right) {
        return $null -eq $Left -and $null -eq $Right
    }
    $aclBytes = @()
    foreach ($acl in @($Left, $Right)) {
        if ($NormalizeInheritedProvenance) {
            $aceFingerprints = @()
            $qualifiedMasks = @{}
            for ($index = 0; $index -lt $acl.Count; $index++) {
                $aceBytes = New-Object byte[] $acl[$index].BinaryLength
                $acl[$index].GetBinaryForm($aceBytes, 0)
                $ace = [Security.AccessControl.GenericAce]::CreateFromBinaryForm(
                    $aceBytes,
                    0
                )
                if ($IgnoreInheritedAceProvenance) {
                    $ace.AceFlags = [Security.AccessControl.AceFlags](
                        [int]$ace.AceFlags -band
                            (-bnot [int][Security.AccessControl.AceFlags]::Inherited)
                    )
                }
                $accessMask = $null
                if (
                    $NormalizeEquivalentQualifiedMasks -and
                    $ace -is [Security.AccessControl.QualifiedAce]
                ) {
                    $accessMask = [int64]$ace.AccessMask -band 0xFFFFFFFFL
                    $ace.AccessMask = 0
                }
                $normalizedAceBytes = New-Object byte[] $ace.BinaryLength
                $ace.GetBinaryForm($normalizedAceBytes, 0)
                $fingerprint = [Convert]::ToBase64String($normalizedAceBytes)
                if ($null -eq $accessMask) {
                    $aceFingerprints += $fingerprint
                }
                else {
                    $qualifiedMasks[$fingerprint] =
                        [int64]$qualifiedMasks[$fingerprint] -bor $accessMask
                }
            }
            $aceFingerprints += @(
                $qualifiedMasks.GetEnumerator() | ForEach-Object {
                    "{0}:{1:X8}" -f $_.Key, [int64]$_.Value
                }
            )
            $canonicalAcl = (
                [string]$acl.Revision + ":" +
                (@($aceFingerprints | Sort-Object -CaseSensitive) -join ",")
            )
            $bytes = [Text.Encoding]::UTF8.GetBytes($canonicalAcl)
        }
        else {
            $bytes = New-Object byte[] $acl.BinaryLength
            $acl.GetBinaryForm($bytes, 0)
        }
        $aclBytes += ,$bytes
    }
    return Test-TicketboxWindowsByteArrayEquals `
        -Left $aclBytes[0] `
        -Right $aclBytes[1]
}
