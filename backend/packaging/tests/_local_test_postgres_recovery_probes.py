"""PowerShell probe writers for local PostgreSQL recovery tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def write_abandoned_staging_probe(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            param($Contract, $PostgresBin, $FinalDir, $Owned, $Unowned)
            . $Contract
            function New-TestStagingReceipt($Staging, $Final) {
              [void](New-Item -ItemType Directory -Path $Staging)
              $handle = [XpjTestDirectoryMoveHandle]::OpenIdentity($Staging)
              try {
                $receiptPath = "$Staging.receipt.json"
                $instanceId = [guid]::NewGuid().ToString('N')
                New-XpjTestPostgresStagingReceipt -ReceiptPath $receiptPath -StagingDirectory $Staging -FinalDataDirectory $Final -Purpose local -Port 5438 -InstanceId $instanceId -DirectoryIdentity $handle.Identity
                return [pscustomobject]@{ Path=$receiptPath; Identity=$handle.Identity }
              } finally { $handle.Dispose() }
            }
            function Set-DeadReceiptOwner($Path) {
              $receipt = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
              $receipt.OwnerProcessId = 2147483647
              [IO.File]::WriteAllText($Path, ($receipt | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
            }
            [void](New-Item -ItemType Directory -Path $Unowned)
            $ownedReceipt = New-TestStagingReceipt $Owned $FinalDir
            Set-DeadReceiptOwner $ownedReceipt.Path
            Remove-XpjTestPostgresAbandonedStaging -PostgresBin $PostgresBin -DataDirectory $FinalDir -Purpose local -Port 5438
            if (Test-Path -LiteralPath $Owned) { throw 'owned staging was not removed' }
            if (-not (Test-Path -LiteralPath $Unowned)) { throw 'unowned staging was removed' }
            $missingFinal = "$FinalDir-missing-identity"
            $missingLeaf = Split-Path -Leaf $missingFinal
            $missing = Join-Path (Split-Path -Parent $missingFinal) ".$missingLeaf.xpj-init-missing"
            $missingReceipt = New-TestStagingReceipt $missing $missingFinal
            $missingPayload = Get-Content -LiteralPath $missingReceipt.Path -Raw -Encoding UTF8 | ConvertFrom-Json
            $missingPayload.PSObject.Properties.Remove('DirectoryIdentity')
            $missingPayload.OwnerProcessId = 2147483647
            [IO.File]::WriteAllText($missingReceipt.Path, ($missingPayload | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
            $missingRefused = $false
            try { Remove-XpjTestPostgresAbandonedStaging -PostgresBin $PostgresBin -DataDirectory $missingFinal -Purpose local -Port 5438 } catch { $missingRefused = $true }
            if (-not $missingRefused -or -not (Test-Path -LiteralPath $missing)) { throw 'identity-free staging receipt did not fail closed' }
            Add-Member -InputObject $missingPayload -NotePropertyName DirectoryIdentity -NotePropertyValue $missingReceipt.Identity
            [IO.File]::WriteAllText($missingReceipt.Path, ($missingPayload | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
            Remove-XpjTestPostgresAbandonedStaging -PostgresBin $PostgresBin -DataDirectory $missingFinal -Purpose local -Port 5438
            $replacementFinal = "$FinalDir-replacement"
            $replacementLeaf = Split-Path -Leaf $replacementFinal
            $replacement = Join-Path (Split-Path -Parent $replacementFinal) ".$replacementLeaf.xpj-init-replaced"
            $replacementReceipt = New-TestStagingReceipt $replacement $replacementFinal
            Set-DeadReceiptOwner $replacementReceipt.Path
            $original = "$replacement-original"
            [IO.Directory]::Move($replacement, $original)
            [void](New-Item -ItemType Directory -Path $replacement)
            $sentinel = Join-Path $replacement 'keep.txt'
            [IO.File]::WriteAllText($sentinel, 'keep')
            $replacementRefused = $false
            try { Remove-XpjTestPostgresAbandonedStaging -PostgresBin $PostgresBin -DataDirectory $replacementFinal -Purpose local -Port 5438 } catch { $replacementRefused = $true }
            if (-not $replacementRefused -or -not (Test-Path -LiteralPath $sentinel)) { throw 'replacement staging directory was not preserved' }
            Remove-Item -LiteralPath $replacement -Recurse -Force
            [IO.Directory]::Move($original, $replacement)
            Remove-XpjTestPostgresAbandonedStaging -PostgresBin $PostgresBin -DataDirectory $replacementFinal -Purpose local -Port 5438
            $currentFinal = "$FinalDir-current"
            $currentLeaf = Split-Path -Leaf $currentFinal
            $currentOwned = Join-Path (Split-Path -Parent $currentFinal) ".$currentLeaf.xpj-init-current"
            $currentReceipt = New-TestStagingReceipt $currentOwned $currentFinal
            Remove-XpjTestPostgresAbandonedStaging -PostgresBin $PostgresBin -DataDirectory $currentFinal -Purpose local -Port 5438
            if (Test-Path -LiteralPath $currentOwned) { throw 'current staging was not removed' }
            """
        ),
        encoding="ascii",
    )


def write_post_initdb_fault_probe(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            param($Contract, $PostgresBin, $FinalDir, $Port)
            . $Contract
            $originalProtect = (Get-Command Protect-XpjTestPostgresDirectoryTree).ScriptBlock
            $earlyFinal = "$FinalDir-early"
            try {
              function Protect-XpjTestPostgresDirectoryTree { param($Path) throw 'injected-before-protect' }
              try {
                New-XpjTestPostgresDataDirectory -PostgresBin $PostgresBin -DataDirectory $earlyFinal -Purpose local -Port $Port
                throw 'expected early injected failure'
              }
              catch {
                if ($_.Exception.Message -notmatch 'injected-before-protect' -or $_.Exception.Message -match 'ExpectedDirectoryIdentity') { throw }
              }
            }
            finally {
              Set-Item -LiteralPath Function:\\Protect-XpjTestPostgresDirectoryTree -Value $originalProtect
            }
            $earlyLeaf = Split-Path -Leaf $earlyFinal
            $earlyLeftovers = @(Get-ChildItem -LiteralPath (Split-Path -Parent $earlyFinal) -Filter ".$earlyLeaf.xpj-init-*" -Force)
            if ($earlyLeftovers.Count -ne 0 -or (Test-Path -LiteralPath $earlyFinal)) { throw 'pre-protection staging was stranded' }
            function Get-XpjTestPostgresControlSystemIdentifier { throw 'injected-after-initdb' }
            try {
              New-XpjTestPostgresDataDirectory -PostgresBin $PostgresBin -DataDirectory $FinalDir -Purpose local -Port $Port
              throw 'expected injected failure'
            }
            catch { if ($_.Exception.Message -notmatch 'injected-after-initdb') { throw } }
            $leaf = Split-Path -Leaf $FinalDir
            $leftovers = @(Get-ChildItem -LiteralPath (Split-Path -Parent $FinalDir) -Filter ".$leaf.xpj-init-*" -Force)
            if ($leftovers.Count -ne 0 -or (Test-Path -LiteralPath $FinalDir)) { throw 'post-initdb staging was stranded' }
            """
        ),
        encoding="ascii",
    )


def write_live_tombstone_probes(prepare: Path, resume: Path) -> None:
    prepare.write_text(
        dedent(
            """\
            param($Contract,$PostgresBin,$DataDir,$Port,$TombstonePath)
            . $Contract
            $marker = Assert-XpjTestPostgresDataOwnership -PostgresBin $PostgresBin -DataDirectory $DataDir -Purpose local -Port $Port
            New-XpjTestPostgresDeletionReceipt -PostgresBin $PostgresBin -DataDirectory $DataDir -Purpose local -Port $Port -SystemIdentifier $marker.SystemIdentifier | Out-Null
            $receiptPath = Get-XpjTestPostgresDeletionReceiptPath $DataDir
            $receipt = Read-XpjTestPostgresDeletionReceipt -ReceiptPath $receiptPath -DataDirectory $DataDir -Purpose local -Port $Port
            $move = [XpjTestDirectoryMoveHandle]::Open($DataDir)
            try { $move.RenameTo([string]$receipt.TombstoneDirectory) } finally { $move.Dispose() }
            Set-XpjTestPostgresDeletionReceiptPhase -Receipt $receipt -ReceiptPath $receiptPath -Phase tombstone
            [IO.File]::WriteAllText($TombstonePath,[string]$receipt.TombstoneDirectory)
            """
        ),
        encoding="ascii",
    )
    resume.write_text(
        dedent(
            """\
            param($Contract,$PostgresBin,$DataDir,$Port)
            . $Contract
            Complete-XpjTestPostgresPendingDeletion -PostgresBin $PostgresBin -DataDirectory $DataDir -Purpose local -Port $Port | Out-Null
            """
        ),
        encoding="ascii",
    )
