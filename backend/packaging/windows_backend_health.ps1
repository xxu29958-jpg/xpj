#Requires -Version 5.1

function Get-TicketboxBackendListenerIdentity {
    param(
        [Parameter(Mandatory = $true)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$ShawlExe,
        [Parameter(Mandatory = $true)][string]$BackendExe
    )
    $listeners = @(
        Get-NetTCPConnection `
            -State Listen `
            -LocalAddress "127.0.0.1" `
            -LocalPort $BackendPort `
            -ErrorAction Stop
    )
    $listenerProcessIds = @(
        $listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique
    )
    if ($listenerProcessIds.Count -ne 1 -or $listenerProcessIds[0] -le 0) {
        throw "The backend port does not have exactly one loopback listener."
    }

    $escapedServiceName = $BackendServiceName.Replace("'", "''")
    $service = Get-CimInstance `
        -ClassName Win32_Service `
        -Filter "Name='$escapedServiceName'" `
        -ErrorAction Stop
    if (
        $null -eq $service -or
        [string]$service.State -ne "Running" -or
        [int]$service.ProcessId -le 0
    ) {
        throw "The backend SCM service is not provably running."
    }
    $listenerProcessId = $listenerProcessIds[0]
    $listener = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId=$listenerProcessId" `
        -ErrorAction Stop
    if (
        $null -eq $listener -or
        [string]::IsNullOrWhiteSpace([string]$listener.ExecutablePath)
    ) {
        throw "The backend listener process identity is unavailable."
    }
    $serviceProcessId = [int]$service.ProcessId
    if ([int]$listener.ParentProcessId -ne $serviceProcessId) {
        throw "The backend listener is not a direct child of the Shawl service process."
    }
    $serviceProcess = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId=$serviceProcessId" `
        -ErrorAction Stop
    if (
        $null -eq $serviceProcess -or
        [string]::IsNullOrWhiteSpace([string]$serviceProcess.ExecutablePath) -or
        -not (Test-TicketboxPathEquals ([string]$serviceProcess.ExecutablePath) $ShawlExe) -or
        -not (Test-TicketboxPathEquals ([string]$listener.ExecutablePath) $BackendExe)
    ) {
        throw "The backend listener process chain does not match the protected installation."
    }
    return [pscustomobject]@{
        ListenerProcessId = $listenerProcessId
        ServiceProcessId = $serviceProcessId
        ListenerCreationDate = [string]$listener.CreationDate
        ServiceCreationDate = [string]$serviceProcess.CreationDate
    }
}

function Assert-TicketboxBackendListenerUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$ExpectedIdentity,
        [Parameter(Mandatory = $true)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$ShawlExe,
        [Parameter(Mandatory = $true)][string]$BackendExe
    )
    $actual = Get-TicketboxBackendListenerIdentity `
        -BackendPort $BackendPort `
        -BackendServiceName $BackendServiceName `
        -ShawlExe $ShawlExe `
        -BackendExe $BackendExe
    if (
        $actual.ListenerProcessId -ne $ExpectedIdentity.ListenerProcessId -or
        $actual.ServiceProcessId -ne $ExpectedIdentity.ServiceProcessId -or
        $actual.ListenerCreationDate -cne $ExpectedIdentity.ListenerCreationDate -or
        $actual.ServiceCreationDate -cne $ExpectedIdentity.ServiceCreationDate
    ) {
        throw "The backend listener identity changed during the HTTP request."
    }
}

function Read-TicketboxBoundedUtf8HttpResponse {
    param(
        [Parameter(Mandatory = $true)][System.Net.WebResponse]$Response,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 1048576)][int]$MaximumBytes
    )
    if ($Response.ContentLength -gt $MaximumBytes) {
        throw "The loopback HTTP response exceeded the size limit."
    }
    $stream = $null
    $buffer = New-Object 'System.Byte[]' 8192
    $memory = New-Object System.IO.MemoryStream
    $payloadBytes = $null
    try {
        $stream = $Response.GetResponseStream()
        if ($null -eq $stream) { throw "The loopback HTTP response has no body." }
        $total = 0
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $read
            if ($total -gt $MaximumBytes) {
                throw "The loopback HTTP response exceeded the size limit."
            }
            $memory.Write($buffer, 0, $read)
        }
        $payloadBytes = $memory.ToArray()
        $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
        return $utf8.GetString($payloadBytes)
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        $memory.Dispose()
        [System.Array]::Clear($buffer, 0, $buffer.Length)
        if ($null -ne $payloadBytes) {
            [System.Array]::Clear($payloadBytes, 0, $payloadBytes.Length)
        }
    }
}

function Invoke-TicketboxDirectLoopbackHealthHttpRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$MaximumResponseBytes
    )
    $uri = New-Object System.Uri($Url)
    if (
        $uri.Scheme -cne "http" -or
        $uri.Host -cne "127.0.0.1" -or
        $uri.UserInfo.Length -ne 0 -or
        $uri.Query.Length -ne 0 -or
        $uri.Fragment.Length -ne 0 -or
        $uri.AbsolutePath -cne "/api/health/installation"
    ) {
        throw "The backend readiness URL violates the fixed loopback contract."
    }
    if ($TimeoutMilliseconds -lt 1) {
        throw "The backend readiness request has no timeout budget."
    }

    $request = [System.Net.HttpWebRequest]::Create($uri)
    $request.Method = "GET"
    $request.Accept = "application/json"
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.KeepAlive = $false
    $request.Timeout = $TimeoutMilliseconds
    $request.ReadWriteTimeout = $TimeoutMilliseconds
    $response = $null
    try {
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        if ([int]$response.StatusCode -ne 200) {
            throw "The backend readiness HTTP status is not 200."
        }
        $mediaType = ([string]$response.ContentType -split ";", 2)[0].Trim()
        if (-not [string]::Equals(
            $mediaType,
            "application/json",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "The backend readiness HTTP response is not JSON."
        }
        $responseText = Read-TicketboxBoundedUtf8HttpResponse `
            -Response $response `
            -MaximumBytes $MaximumResponseBytes
        return $responseText | ConvertFrom-Json -ErrorAction Stop
    }
    finally {
        if ($null -ne $response) { $response.Dispose() }
    }
}

function Get-TicketboxExpectedBackendVersion {
    param([Parameter(Mandatory = $true)][string]$ProgramDir)
    $manifestPath = Join-Path $ProgramDir "BUILD_PROVENANCE.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "The installed backend build manifest is missing: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    $version = [string]$manifest.backend_version
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw "The installed backend build manifest has no backend_version."
    }
    return $version
}

function Get-TicketboxExpectedInstallationId {
    param([Parameter(Mandatory = $true)][string]$AppData)
    $canonicalDataRoot = (ConvertTo-TicketboxCanonicalPath $AppData).ToLowerInvariant()
    $identityText = "ticketbox-installation-v1`0$canonicalDataRoot"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($identityText))
        $hex = ([System.BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
        return "ticketbox-$($hex.Substring(0, 32))"
    }
    finally { $sha256.Dispose() }
}

function Assert-TicketboxInstallationHealthResponse {
    param(
        [Parameter(Mandatory = $true)][object]$Payload,
        [Parameter(Mandatory = $true)][string]$ExpectedBackendVersion,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )
    $mobile = $Payload.mobile_connectivity
    if (
        @($Payload.PSObject.Properties).Count -ne 9 -or
        [string]$Payload.contract -cne "ticketbox-installation-health-v2" -or
        [string]$Payload.status -cne "ok" -or
        [string]$Payload.product -cne "ticketbox" -or
        [string]$Payload.backend_version -cne $ExpectedBackendVersion -or
        [string]$Payload.installation_id -cne $ExpectedInstallationId -or
        [string]$Payload.runtime_access_state -notin @("available", "repair_required") -or
        [string]$Payload.owner_state -notin @("configured", "recovery_required") -or
        [string]$Payload.owner_recovery_channel -notin @("development", "managed_host", "operator") -or
        $null -eq $mobile -or
        @($mobile.PSObject.Properties).Count -ne 3 -or
        [string]$mobile.mobile_endpoint_state -notin @("local_only", "public_configured_unverified") -or
        [string]$mobile.android_binding_state -notin @("setup_required", "configured_unverified") -or
        [string]$mobile.iphone_upload_state -notin @("setup_required", "configured_unverified") -or
        (
            [string]$mobile.mobile_endpoint_state -ceq "local_only" -and
            (
                [string]$mobile.android_binding_state -cne "setup_required" -or
                [string]$mobile.iphone_upload_state -cne "setup_required"
            )
        ) -or
        (
            [string]$mobile.mobile_endpoint_state -ceq "public_configured_unverified" -and
            (
                [string]$mobile.android_binding_state -cne "configured_unverified" -or
                [string]$mobile.iphone_upload_state -cne "configured_unverified"
            )
        )
    ) {
        throw "The installation-health response does not match this installation."
    }
}

function Wait-TicketboxInstalledBackendHealth {
    param(
        [Parameter(Mandatory = $true)][int]$BackendPort,
        [Parameter(Mandatory = $true)][string]$BackendServiceName,
        [Parameter(Mandatory = $true)][string]$ShawlExe,
        [Parameter(Mandatory = $true)][string]$BackendExe,
        [Parameter(Mandatory = $true)][string]$ProgramDir,
        [Parameter(Mandatory = $true)][string]$AppData,
        [Parameter(Mandatory = $true)][int]$ReadyTimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$RequestTimeoutMilliseconds,
        [Parameter(Mandatory = $true)][int]$PollMilliseconds,
        [Parameter(Mandatory = $true)][int]$MaximumResponseBytes
    )
    $url = "http://127.0.0.1:$BackendPort/api/health/installation"
    $expectedVersion = Get-TicketboxExpectedBackendVersion -ProgramDir $ProgramDir
    $expectedInstallation = Get-TicketboxExpectedInstallationId -AppData $AppData
    $deadline = New-TicketboxWaitDeadline $ReadyTimeoutMilliseconds
    $lastError = ""
    do {
        $remaining = [Math]::Max(
            1,
            $ReadyTimeoutMilliseconds - $deadline.ElapsedMilliseconds
        )
        $probeBudget = [int][Math]::Min(
            [long]$RequestTimeoutMilliseconds,
            [long]$remaining
        )
        try {
            $identity = Get-TicketboxBackendListenerIdentity `
                -BackendPort $BackendPort `
                -BackendServiceName $BackendServiceName `
                -ShawlExe $ShawlExe `
                -BackendExe $BackendExe
            $payload = Invoke-TicketboxDirectLoopbackHealthHttpRequest `
                -Url $url `
                -TimeoutMilliseconds $probeBudget `
                -MaximumResponseBytes $MaximumResponseBytes
            Assert-TicketboxBackendListenerUnchanged `
                -ExpectedIdentity $identity `
                -BackendPort $BackendPort `
                -BackendServiceName $BackendServiceName `
                -ShawlExe $ShawlExe `
                -BackendExe $BackendExe
            Assert-TicketboxInstallationHealthResponse `
                -Payload $payload `
                -ExpectedBackendVersion $expectedVersion `
                -ExpectedInstallationId $expectedInstallation
            return
        }
        catch { $lastError = $_.Exception.Message }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $ReadyTimeoutMilliseconds `
        -PollMilliseconds $PollMilliseconds)
    throw "The backend did not pass installation identity and readiness checks within $ReadyTimeoutMilliseconds ms: $lastError"
}
