#requires -Version 5.1

Set-StrictMode -Version 2.0
Add-Type -AssemblyName UIAutomationClient | Out-Null
Add-Type -AssemblyName UIAutomationTypes | Out-Null

function Join-TbxCodePoints {
    param([Parameter(Mandatory = $true)][int[]]$CodePoints)
    return -join @($CodePoints | ForEach-Object { [char]$_ })
}

$script:TbxUiText = [ordered]@{
    product = Join-TbxCodePoints @(0x5C0F, 0x7968, 0x5939)
    next = Join-TbxCodePoints @(0x4E0B, 0x4E00, 0x6B65)
    install = Join-TbxCodePoints @(0x5B89, 0x88C5)
    finish = Join-TbxCodePoints @(0x5B8C, 0x6210)
    close = Join-TbxCodePoints @(0x5173, 0x95ED)
    success_heading = Join-TbxCodePoints @(
        0x5C0F, 0x7968, 0x5939, 0x5DF2, 0x5B89, 0x88C5
    )
    failure_heading = Join-TbxCodePoints @(
        0x5C0F, 0x7968, 0x5939, 0x5B89, 0x88C5, 0x672A, 0x5B8C, 0x6210
    )
    pairing_memo = Join-TbxCodePoints @(
        0x7ED1, 0x5B9A, 0x6B64, 0x7535, 0x8111, 0x7801
    )
    manager_checkbox = Join-TbxCodePoints @(
        0x5B8C, 0x6210, 0x540E, 0x6253, 0x5F00,
        0x5C0F, 0x7968, 0x5939, 0x7BA1, 0x7406, 0x5668
    )
    manager_title = Join-TbxCodePoints @(
        0x5C0F, 0x7968, 0x5939, 0x7BA1, 0x7406, 0x5668
    )
    pairing_input = (Join-TbxCodePoints @(
        0x7ED1, 0x5B9A, 0x6B64, 0x7535, 0x8111, 0x7684
    )) + ' 8 ' + (Join-TbxCodePoints @(0x4F4D, 0x7801))
    pairing_button = Join-TbxCodePoints @(
        0x7ED1, 0x5B9A, 0x6B64, 0x7535, 0x8111
    )
}

function Get-TbxDescendantProcessIds {
    param([Parameter(Mandatory = $true)][int[]]$RootIds)
    $known = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($id in $RootIds) { [void]$known.Add([int]$id) }
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $live = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($process in $all) { [void]$live.Add([int]$process.ProcessId) }
    for ($pass = 0; $pass -lt 24; $pass++) {
        $changed = $false
        foreach ($process in $all) {
            if ($known.Contains([int]$process.ParentProcessId) -and
                -not $known.Contains([int]$process.ProcessId)) {
                [void]$known.Add([int]$process.ProcessId)
                $changed = $true
            }
        }
        if (-not $changed) { break }
    }
    return @($known | Where-Object { $live.Contains([int]$_) } | ForEach-Object { [int]$_ })
}

function Get-TbxInstallerProcessIds {
    param([int]$RootProcessId = 0)
    $ids = @()
    if ($RootProcessId -gt 0) { $ids += Get-TbxDescendantProcessIds @($RootProcessId) }
    foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        if ([string]$process.Name -like 'Ticketbox-Setup-*.exe' -or
            [string]$process.CommandLine -match '(?i)Ticketbox-Setup-1\.2\.0\.exe') {
            $ids += [int]$process.ProcessId
        }
    }
    return @($ids | Sort-Object -Unique)
}

function Get-TbxTopLevelWindows {
    param([int[]]$ProcessIds = @(), [string]$NameContains = '')
    $windows = @()
    $collection = [Windows.Automation.AutomationElement]::RootElement.FindAll(
        [Windows.Automation.TreeScope]::Children,
        [Windows.Automation.Condition]::TrueCondition
    )
    foreach ($window in $collection) {
        try {
            $windowProcessId = [int]$window.Current.ProcessId
            $name = [string]$window.Current.Name
            $pidMatches = $ProcessIds.Count -gt 0 -and $ProcessIds -contains $windowProcessId
            $nameMatches = $NameContains -and $name.Contains($NameContains)
            if ($pidMatches -or $nameMatches) { $windows += $window }
        }
        catch { continue }
    }
    return @($windows)
}

function Wait-TbxTopLevelWindow {
    param(
        [int[]]$ProcessIds = @(),
        [string]$NameContains = '',
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $window = @(Get-TbxTopLevelWindows -ProcessIds $ProcessIds -NameContains $NameContains) |
            Select-Object -First 1
        if ($null -ne $window) { return $window }
        Start-Sleep -Milliseconds 200
    }
    return $null
}

function Get-TbxAutomationElements {
    param(
        [Parameter(Mandatory = $true)][object]$Root,
        [Parameter(Mandatory = $true)][object]$ControlType
    )
    $condition = New-Object Windows.Automation.PropertyCondition(
        [Windows.Automation.AutomationElement]::ControlTypeProperty,
        $ControlType
    )
    try {
        return @($Root.FindAll([Windows.Automation.TreeScope]::Descendants, $condition))
    }
    catch { return @() }
}

function Get-TbxEnabledButtonContaining {
    param(
        [Parameter(Mandatory = $true)][object]$Window,
        [Parameter(Mandatory = $true)][string]$Text
    )
    foreach ($button in @(Get-TbxAutomationElements $Window ([Windows.Automation.ControlType]::Button))) {
        try {
            if ($button.Current.IsEnabled -and ([string]$button.Current.Name).Contains($Text)) {
                return $button
            }
        }
        catch { continue }
    }
    return $null
}

function Invoke-TbxButton {
    param([Parameter(Mandatory = $true)][object]$Button)
    $pattern = $null
    if (-not $Button.TryGetCurrentPattern(
        [Windows.Automation.InvokePattern]::Pattern,
        [ref]$pattern
    )) { throw 'UI Automation InvokePattern is unavailable.' }
    $pattern.Invoke()
}

function Test-TbxWindowContainsName {
    param(
        [Parameter(Mandatory = $true)][object]$Window,
        [Parameter(Mandatory = $true)][string]$Text
    )
    try {
        $elements = $Window.FindAll(
            [Windows.Automation.TreeScope]::Descendants,
            [Windows.Automation.Condition]::TrueCondition
        )
        foreach ($element in $elements) {
            try {
                if (([string]$element.Current.Name).Contains($Text)) { return $true }
            }
            catch { continue }
        }
    }
    catch { return $false }
    return $false
}

function Get-TbxSafeWindowSnapshot {
    param([Parameter(Mandatory = $true)][object]$Window)
    $controls = @()
    try {
        $elements = $Window.FindAll(
            [Windows.Automation.TreeScope]::Descendants,
            [Windows.Automation.Condition]::TrueCondition
        )
        foreach ($element in $elements) {
            try {
                $name = [string]$element.Current.Name
                if (-not $name) { continue }
                $name = [regex]::Replace($name, '(?<!\d)\d{8}(?!\d)', '<redacted-8-digit>')
                if ($name.Length -gt 240) { $name = $name.Substring(0, 240) }
                $controls += [ordered]@{
                    type = [string]$element.Current.ControlType.ProgrammaticName
                    name = $name
                    enabled = [bool]$element.Current.IsEnabled
                }
            }
            catch { continue }
        }
    }
    catch { }
    return [ordered]@{
        title = [regex]::Replace([string]$Window.Current.Name, '(?<!\d)\d{8}(?!\d)', '<redacted>')
        process_id = [int]$Window.Current.ProcessId
        native_window_handle = [int]$Window.Current.NativeWindowHandle
        controls = @($controls)
    }
}

function Start-TbxInteractiveInstaller {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerPath,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][string]$TimelinePath
    )
    $timeline = New-Object System.Collections.ArrayList
    $arguments = '/LOG="{0}"' -f $LogPath
    $process = Start-Process -FilePath $InstallerPath -ArgumentList $arguments -PassThru
    [void]$timeline.Add([ordered]@{
        at_utc = [DateTime]::UtcNow.ToString('o')
        event = 'installer_process_started'
        process_id = [int]$process.Id
    })
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    while ([DateTime]::UtcNow -lt $deadline) {
        $ids = @(Get-TbxInstallerProcessIds -RootProcessId $process.Id)
        $window = @(Get-TbxTopLevelWindows -ProcessIds $ids -NameContains $script:TbxUiText.product) |
            Select-Object -First 1
        if ($null -eq $window) { Start-Sleep -Milliseconds 250; continue }
        if (Test-TbxWindowContainsName $window $script:TbxUiText.failure_heading) {
            Write-TbxJson (Get-TbxSafeWindowSnapshot $window) ($TimelinePath + '.failure-window.json')
            throw 'Installer reached its failure page before installation started.'
        }
        $installButton = Get-TbxEnabledButtonContaining $window $script:TbxUiText.install
        if ($null -ne $installButton) {
            Invoke-TbxButton $installButton
            [void]$timeline.Add([ordered]@{
                at_utc = [DateTime]::UtcNow.ToString('o')
                event = 'install_button_invoked'
                process_ids = $ids
            })
            Write-TbxJson @($timeline) $TimelinePath
            return [pscustomobject]@{
                root_process = $process
                root_process_id = [int]$process.Id
                timeline = $timeline
                timeline_path = $TimelinePath
                log_path = $LogPath
            }
        }
        $nextButton = Get-TbxEnabledButtonContaining $window $script:TbxUiText.next
        if ($null -ne $nextButton) {
            Invoke-TbxButton $nextButton
            [void]$timeline.Add([ordered]@{
                at_utc = [DateTime]::UtcNow.ToString('o')
                event = 'next_button_invoked'
            })
            Write-TbxJson @($timeline) $TimelinePath
            Start-Sleep -Milliseconds 700
            continue
        }
        Start-Sleep -Milliseconds 250
    }
    Write-TbxJson @($timeline) $TimelinePath
    throw 'Installer did not reach the semantic Install button before its deadline.'
}

function Get-TbxPairingCodeFromWindow {
    param([Parameter(Mandatory = $true)][object]$Window)
    foreach ($edit in @(Get-TbxAutomationElements $Window ([Windows.Automation.ControlType]::Edit))) {
        $pattern = $null
        try {
            if (-not $edit.TryGetCurrentPattern(
                [Windows.Automation.ValuePattern]::Pattern,
                [ref]$pattern
            )) { continue }
            $value = [string]$pattern.Current.Value
            if (-not $value.Contains($script:TbxUiText.pairing_memo)) { continue }
            $match = [regex]::Match($value, '(?<!\d)(\d{8})(?!\d)')
            if ($match.Success) { return [string]$match.Groups[1].Value }
        }
        catch { continue }
    }
    return ''
}

function Disable-TbxElevatedManagerLaunch {
    param([Parameter(Mandatory = $true)][object]$Window)
    foreach ($check in @(Get-TbxAutomationElements $Window ([Windows.Automation.ControlType]::CheckBox))) {
        try {
            if (-not ([string]$check.Current.Name).Contains($script:TbxUiText.manager_checkbox)) { continue }
            $pattern = $null
            if (-not $check.TryGetCurrentPattern(
                [Windows.Automation.TogglePattern]::Pattern,
                [ref]$pattern
            )) { throw 'Manager launch checkbox has no TogglePattern.' }
            if ($pattern.Current.ToggleState -eq [Windows.Automation.ToggleState]::On) {
                $pattern.Toggle()
            }
            return $true
        }
        catch { throw }
    }
    return $false
}

function Wait-TbxInstallerExit {
    param([Parameter(Mandatory = $true)][object]$Context, [int]$TimeoutSeconds = 90)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $remaining = @()
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = @(Get-TbxInstallerProcessIds -RootProcessId $Context.root_process_id)
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }
    if ($remaining.Count -ne 0) {
        throw ('Installer process tree did not exit after Finish: ' + ($remaining -join ','))
    }
    $Context.root_process.Refresh()
    if (-not $Context.root_process.HasExited) { throw 'Installer process did not exit after Finish.' }
    return [int]$Context.root_process.ExitCode
}

function Complete-TbxInteractiveInstaller {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][ref]$PairingCode,
        [int]$TimeoutMinutes = 25
    )
    $deadline = [DateTime]::UtcNow.AddMinutes($TimeoutMinutes)
    while ([DateTime]::UtcNow -lt $deadline) {
        $ids = @(Get-TbxInstallerProcessIds -RootProcessId $Context.root_process_id)
        $window = @(Get-TbxTopLevelWindows -ProcessIds $ids -NameContains $script:TbxUiText.product) |
            Select-Object -First 1
        if ($null -eq $window) {
            if ($ids.Count -eq 0) { throw 'Installer exited before a success or failure page was observed.' }
            Start-Sleep -Milliseconds 300
            continue
        }
        if (Test-TbxWindowContainsName $window $script:TbxUiText.failure_heading) {
            $failurePath = $Context.timeline_path + '.failure-window.json'
            Write-TbxJson (Get-TbxSafeWindowSnapshot $window) $failurePath
            $close = Get-TbxEnabledButtonContaining $window $script:TbxUiText.close
            if ($null -ne $close) {
                Invoke-TbxButton $close
                try { [void](Wait-TbxInstallerExit -Context $Context -TimeoutSeconds 30) }
                catch { }
            }
            throw 'Installer reached the explicit failure page.'
        }
        if (-not (Test-TbxWindowContainsName $window $script:TbxUiText.success_heading)) {
            Start-Sleep -Milliseconds 300
            continue
        }
        $code = Get-TbxPairingCodeFromWindow $window
        if ($code -notmatch '^\d{8}$') { throw 'Success page did not expose a valid transient pairing code.' }
        if (-not (Disable-TbxElevatedManagerLaunch $window)) {
            throw 'Success page did not expose the Manager launch checkbox.'
        }
        $finish = Get-TbxEnabledButtonContaining $window $script:TbxUiText.finish
        if ($null -eq $finish) { throw 'Success page did not expose the semantic Finish button.' }
        $PairingCode.Value = $code
        Invoke-TbxButton $finish
        [void]$Context.timeline.Add([ordered]@{
            at_utc = [DateTime]::UtcNow.ToString('o')
            event = 'success_finish_invoked'
            pairing_code_captured_in_memory = $true
            elevated_manager_launch_disabled = $true
        })
        Write-TbxJson @($Context.timeline) $Context.timeline_path
        $exitCode = Wait-TbxInstallerExit -Context $Context
        return [ordered]@{
            root_process_id = $Context.root_process_id
            exit_code = $exitCode
            success_page_observed = $true
            pairing_code_captured_in_memory = $true
            elevated_manager_launch_disabled = $true
            completed_at_utc = [DateTime]::UtcNow.ToString('o')
        }
    }
    throw 'Interactive installer exceeded its bounded completion deadline.'
}

function Invoke-TbxInterruptedInstall {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [int]$TimeoutMinutes = 15
    )
    $dataRoot = Join-Path $env:ProgramData 'Ticketbox'
    $pendingPath = Join-Path $dataRoot '.ticketbox-installation-identity.pending'
    $intentPath = Join-Path $env:CommonProgramFiles `
        'Ticketbox\c07-lifecycle\c07-fresh-bootstrap-intent.json'
    $deadline = [DateTime]::UtcNow.AddMinutes($TimeoutMinutes)
    $mutationRoots = @()
    while ([DateTime]::UtcNow -lt $deadline) {
        if ((Test-Path -LiteralPath $pendingPath -PathType Leaf) -and
            (Test-Path -LiteralPath $intentPath -PathType Leaf)) {
            $mutationRoots = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    [string]$_.CommandLine -match '(?i)install_bundled_services\.ps1'
                } | ForEach-Object { [int]$_.ProcessId })
            if ($mutationRoots.Count -gt 0) { break }
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path -LiteralPath $pendingPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $intentPath -PathType Leaf)) {
        throw 'Durable pending identity and fresh intent were not observed before deadline.'
    }
    $pending = Get-TbxIdentityEvidence $pendingPath
    $intent = Get-TbxFreshIntentEvidence $intentPath
    $operationId = [string]$pending.values.OPERATION_ID
    if ($operationId -notmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') {
        throw 'Pending operation ID is invalid.'
    }
    if ($intent.operation_id -and [string]$intent.operation_id -cne $operationId) {
        throw 'Fresh intent and PENDING operation IDs differ before injection.'
    }
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $mutationRoots = @($all | Where-Object {
        [string]$_.CommandLine -match '(?i)install_bundled_services\.ps1'
    } | ForEach-Object { [int]$_.ProcessId })
    if ($mutationRoots.Count -eq 0) { throw 'No live installation mutation child was found.' }
    $protectedHolderIds = @($all | Where-Object {
        [string]$_.CommandLine -match '(?i)(hold_installer_lifecycle_lock|hold_data_root_mutation_guard)\.ps1'
    } | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
    $mutationIds = @(Get-TbxDescendantProcessIds $mutationRoots |
        Where-Object { $protectedHolderIds -notcontains [int]$_ } | Sort-Object -Descending)
    $setupIds = @(Get-TbxInstallerProcessIds -RootProcessId $Context.root_process_id |
        Where-Object { $protectedHolderIds -notcontains [int]$_ } | Sort-Object -Descending)
    if ($setupIds.Count -eq 0) { throw 'No live Setup process was found for controlled death.' }
    $receiptIds = @($mutationIds + $setupIds + $protectedHolderIds | Sort-Object -Unique)
    $processTree = @($all | Where-Object { $receiptIds -contains [int]$_.ProcessId } |
        ForEach-Object {
            [ordered]@{
                process_id = [int]$_.ProcessId
                parent_process_id = [int]$_.ParentProcessId
                session_id = [int]$_.SessionId
                name = [string]$_.Name
                executable_path = [string]$_.ExecutablePath
                command_line = [string]$_.CommandLine
                creation_date = [string]$_.CreationDate
                owner = Get-TbxProcessOwner $_
            }
        })
    $receipt = [ordered]@{
        schema = 'ticketbox-controlled-process-death-v1'
        injected_at_utc = [DateTime]::UtcNow.ToString('o')
        predicate = 'pending identity and fresh intent durable; mutation child live'
        operation_id = $operationId
        installation_id = [string]$pending.values.INSTALLATION_ID
        pending_sha256 = [string]$pending.sha256
        fresh_intent_sha256 = [string]$intent.sha256
        fresh_intent_operation_matches = (-not $intent.operation_id -or [string]$intent.operation_id -ceq $operationId)
        mutation_process_ids = $mutationIds
        installer_process_ids = $setupIds
        protected_holder_process_ids = $protectedHolderIds
        process_tree_before_injection = $processTree
        holder_processes_killed = $false
        manual_state_cleanup = $false
    }
    Write-TbxJson $receipt $OutputPath
    foreach ($id in $mutationIds) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    foreach ($id in $setupIds) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    $cleanupDeadline = [DateTime]::UtcNow.AddMinutes(3)
    $remaining = @()
    while ([DateTime]::UtcNow -lt $cleanupDeadline) {
        $remaining = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            [string]$_.CommandLine -match '(?i)(install_bundled_services|hold_installer_lifecycle_lock|hold_data_root_mutation_guard)\.ps1' -or
            [string]$_.Name -like 'Ticketbox-Setup-*.exe'
        })
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($remaining.Count -ne 0) {
        $receipt.cleanup_converged = $false
        $receipt.remaining_process_ids = @($remaining | ForEach-Object { [int]$_.ProcessId })
        Write-TbxJson $receipt $OutputPath
        throw 'Installer owner/holder processes did not converge after controlled death.'
    }
    $receipt.cleanup_converged = $true
    $receipt.cleanup_observed_at_utc = [DateTime]::UtcNow.ToString('o')
    Write-TbxJson $receipt $OutputPath
    return $receipt
}

function Get-TbxHarnessOwnedInstallerProcessIds {
    param([int[]]$RootProcessIds = @())
    $ids = @()
    foreach ($rootId in @($RootProcessIds)) {
        if ([int]$rootId -gt 0) { $ids += Get-TbxDescendantProcessIds @([int]$rootId) }
    }
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $ids += @($all | Where-Object {
        [string]$_.Name -like 'Ticketbox-Setup-*.exe' -or
        [string]$_.CommandLine -match '(?i)(install_bundled_services|hold_installer_lifecycle_lock|hold_data_root_mutation_guard)\.ps1'
    } | ForEach-Object { [int]$_.ProcessId })
    return @($ids | Sort-Object -Unique)
}

function Stop-TbxHarnessOwnedInstallerProcesses {
    param(
        [int[]]$RootProcessIds = @(),
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $ids = @(Get-TbxHarnessOwnedInstallerProcessIds -RootProcessIds $RootProcessIds)
    $tree = @($all | Where-Object { $ids -contains [int]$_.ProcessId } | ForEach-Object {
        [ordered]@{
            process_id = [int]$_.ProcessId
            parent_process_id = [int]$_.ParentProcessId
            session_id = [int]$_.SessionId
            name = [string]$_.Name
            executable_path = [string]$_.ExecutablePath
            command_line = [string]$_.CommandLine
            owner = Get-TbxProcessOwner $_
        }
    })
    foreach ($processId in @($ids | Sort-Object -Descending)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $remaining = @()
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = @(Get-TbxHarnessOwnedInstallerProcessIds -RootProcessIds $RootProcessIds)
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }
    $receipt = [ordered]@{
        schema = 'ticketbox-harness-failure-process-cleanup-v1'
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        process_tree_before_cleanup = $tree
        stopped_process_ids = $ids
        remaining_process_ids = $remaining
        persisted_machine_state_removed = $false
        converged = ($remaining.Count -eq 0)
    }
    Write-TbxJson $receipt $OutputPath -Depth 10
    if ($remaining.Count -ne 0) { throw 'Harness-owned installer processes did not exit.' }
    return $receipt
}

function New-TbxStandardUser {
    param([Parameter(Mandatory = $true)][string]$EvidencePath)
    $suffix = if ($env:GITHUB_RUN_ATTEMPT) { [string]$env:GITHUB_RUN_ATTEMPT } else { '1' }
    $name = ('tbxe2e' + $suffix)
    if ($name.Length -gt 20) { $name = $name.Substring(0, 20) }
    if (Get-LocalUser -Name $name -ErrorAction SilentlyContinue) {
        throw 'Unexpected pre-existing E2E standard user.'
    }
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $plain = 'Aa1!' + [Convert]::ToBase64String($bytes).Replace('/', 'x').Replace('+', 'Y')
    $secure = ConvertTo-SecureString $plain -AsPlainText -Force
    $plain = $null
    $user = New-LocalUser -Name $name -Password $secure `
        -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword
    $credential = New-Object Management.Automation.PSCredential(
        ("$env:COMPUTERNAME\$name"),
        $secure
    )
    $adminMember = @(Get-LocalGroupMember -Group 'Administrators' -ErrorAction Stop | Where-Object {
        [string]$_.SID -ceq [string]$user.SID
    }).Count -ne 0
    if ($adminMember) { throw 'E2E Manager user unexpectedly belongs to Administrators.' }
    $safe = [ordered]@{
        schema = 'ticketbox-e2e-standard-user-v1'
        name = $name
        sid = [string]$user.SID
        enabled = [bool]$user.Enabled
        administrators_member = $adminMember
    }
    Write-TbxJson $safe $EvidencePath
    return [pscustomobject]@{
        name = $name
        sid = [string]$user.SID
        credential = $credential
        safe_evidence = $safe
    }
}

function Test-TbxStandardUserDesktop {
    param(
        [Parameter(Mandatory = $true)][object]$UserContext,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $notepad = Join-Path $env:WINDIR 'System32\notepad.exe'
    $process = Start-Process -FilePath $notepad -Credential $UserContext.credential `
        -LoadUserProfile -WorkingDirectory (Join-Path $env:WINDIR 'System32') -PassThru
    try {
        $window = Wait-TbxTopLevelWindow -ProcessIds @([int]$process.Id) -TimeoutSeconds 30
        if ($null -eq $window) { throw 'Standard-user interactive desktop probe has no window.' }
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
        $proof = [ordered]@{
            schema = 'ticketbox-standard-user-desktop-probe-v1'
            captured_at_utc = [DateTime]::UtcNow.ToString('o')
            process_id = [int]$process.Id
            session_id = [int]$cim.SessionId
            owner = Get-TbxProcessOwner $cim
            window_handle = [int]$window.Current.NativeWindowHandle
            window_present = $true
        }
        Write-TbxJson $proof $OutputPath
        return $proof
    }
    finally {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}

function Set-TbxAutomationValue {
    param(
        [Parameter(Mandatory = $true)][object]$Element,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $pattern = $null
    if (-not $Element.TryGetCurrentPattern(
        [Windows.Automation.ValuePattern]::Pattern,
        [ref]$pattern
    )) { throw 'UI Automation ValuePattern is unavailable.' }
    $pattern.SetValue($Value)
}

function Save-TbxWindowScreenshot {
    param(
        [Parameter(Mandatory = $true)][object]$Window,
        [Parameter(Mandatory = $true)][string]$Path
    )
    Add-Type -AssemblyName System.Drawing | Out-Null
    $rect = $Window.Current.BoundingRectangle
    $width = [int][Math]::Ceiling($rect.Width)
    $height = [int][Math]::Ceiling($rect.Height)
    if ($width -lt 100 -or $height -lt 100) { return $false }
    $bitmap = New-Object Drawing.Bitmap($width, $height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen([int]$rect.Left, [int]$rect.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    return $true
}

function Start-TbxManagerAsStandardUser {
    param(
        [Parameter(Mandatory = $true)][string]$ManagerPath,
        [Parameter(Mandatory = $true)][object]$UserContext,
        [Parameter(Mandatory = $true)][string]$PairingCode,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )
    $process = Start-Process -FilePath $ManagerPath -Credential $UserContext.credential `
        -LoadUserProfile -WorkingDirectory (Split-Path -Parent $ManagerPath) -PassThru
    $window = $null
    $deadline = [DateTime]::UtcNow.AddMinutes(2)
    while ([DateTime]::UtcNow -lt $deadline) {
        $ids = @(Get-TbxDescendantProcessIds @([int]$process.Id))
        $window = @(Get-TbxTopLevelWindows -ProcessIds $ids -NameContains $script:TbxUiText.manager_title) |
            Where-Object { [string]$_.Current.Name -notmatch '(?i)warning|error' } |
            Select-Object -First 1
        if ($null -ne $window) { break }
        if ($process.HasExited) { throw 'Manager exited before opening its product window.' }
        Start-Sleep -Milliseconds 250
    }
    if ($null -eq $window) { throw 'Manager product window did not open before deadline.' }
    $input = $null
    $button = $null
    $controlDeadline = [DateTime]::UtcNow.AddMinutes(1)
    while ([DateTime]::UtcNow -lt $controlDeadline) {
        foreach ($edit in @(Get-TbxAutomationElements $window ([Windows.Automation.ControlType]::Edit))) {
            if (([string]$edit.Current.Name).Contains($script:TbxUiText.pairing_input)) {
                $input = $edit
                break
            }
        }
        $button = Get-TbxEnabledButtonContaining $window $script:TbxUiText.pairing_button
        if ($null -ne $input -and $null -ne $button) { break }
        Start-Sleep -Milliseconds 250
    }
    if ($null -eq $input -or $null -eq $button) {
        Write-TbxJson (Get-TbxSafeWindowSnapshot $window) (Join-Path $OutputDirectory 'manager-window-unready.json')
        throw 'Manager pairing controls were not exposed through UI Automation.'
    }
    Set-TbxAutomationValue -Element $input -Value $PairingCode
    Invoke-TbxButton $button
    $paired = $false
    $pairDeadline = [DateTime]::UtcNow.AddMinutes(2)
    while ([DateTime]::UtcNow -lt $pairDeadline) {
        $pattern = $null
        if ($input.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$pattern) -and
            [string]::IsNullOrEmpty([string]$pattern.Current.Value)) {
            $paired = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $paired) {
        Write-TbxJson (Get-TbxSafeWindowSnapshot $window) (Join-Path $OutputDirectory 'manager-pair-failure.json')
        throw 'Manager did not consume the transient pairing code.'
    }
    Start-Sleep -Seconds 2
    $screenshotPath = Join-Path $OutputDirectory 'manager-after-pairing.png'
    $screenshotSaved = Save-TbxWindowScreenshot -Window $window -Path $screenshotPath
    $ids = @(Get-TbxDescendantProcessIds @([int]$process.Id))
    $owners = @()
    foreach ($id in $ids) {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if ($null -ne $cim) {
            $owners += [ordered]@{
                process_id = $id
                name = [string]$cim.Name
                session_id = [int]$cim.SessionId
                owner = Get-TbxProcessOwner $cim
            }
        }
    }
    $proof = [ordered]@{
        schema = 'ticketbox-manager-gui-proof-v1'
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        manager_process_id = [int]$process.Id
        manager_user = $UserContext.name
        manager_user_sid = $UserContext.sid
        window_title = [regex]::Replace([string]$window.Current.Name, '(?<!\d)\d{8}(?!\d)', '<redacted>')
        window_handle = [int]$window.Current.NativeWindowHandle
        pairing_completed = $true
        pairing_code_persisted = $false
        screenshot_saved_after_code_cleared = [bool]$screenshotSaved
        process_owners = @($owners)
    }
    Write-TbxJson $proof (Join-Path $OutputDirectory 'manager-gui-proof.json') -Depth 8
    return [pscustomobject]@{ process = $process; proof = $proof }
}
