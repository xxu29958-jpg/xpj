#Requires -Version 5.1

$script:InstallationOwnerContract = "ticketbox-installation-owner-pairing-v1"
$script:InstallationOwnerPairingCodeContext =
    "ticketbox/installation-owner/v1/pairing-code"
$script:BootstrapSecretMinimumBytes = 32
$script:BootstrapMaximumResponseBytes = 1048576

function Assert-TicketboxBootstrapSecret([string]$Secret) {
    $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($Secret)
    try {
        if ($secretBytes.Length -lt $script:BootstrapSecretMinimumBytes) {
            throw "HTTP bootstrap secret 少于 32 字节，拒绝使用低熵初始化凭据。"
        }
    }
    finally {
        [System.Array]::Clear($secretBytes, 0, $secretBytes.Length)
    }
}

function Get-TicketboxBootstrapDigest([string]$Secret, [byte[]]$ContextBytes) {
    Assert-TicketboxBootstrapSecret $Secret
    $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($Secret)
    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    try {
        $hmac.Key = $secretBytes
        return $hmac.ComputeHash($ContextBytes)
    }
    finally {
        $hmac.Dispose()
        [System.Array]::Clear($secretBytes, 0, $secretBytes.Length)
    }
}

function Get-TicketboxInstallationOwnerPairingCode(
    [string]$Secret,
    [ValidateRange(0, 63)][int]$DerivationIndex
) {
    $prefix = [System.Text.Encoding]::ASCII.GetBytes(
        $script:InstallationOwnerPairingCodeContext
    )
    $context = New-Object 'System.Byte[]' ($prefix.Length + 1)
    [System.Array]::Copy($prefix, $context, $prefix.Length)
    $context[$prefix.Length] = [byte]$DerivationIndex
    $digest = $null
    try {
        $digest = Get-TicketboxBootstrapDigest $Secret $context
        $pairingValue = [long]0
        foreach ($value in $digest) {
            $pairingValue = (($pairingValue * 256) + [int]$value) % 100000000
        }
        return $pairingValue.ToString("D8")
    }
    finally {
        [System.Array]::Clear($prefix, 0, $prefix.Length)
        [System.Array]::Clear($context, 0, $context.Length)
        if ($null -ne $digest) {
            [System.Array]::Clear($digest, 0, $digest.Length)
        }
    }
}

function Get-TicketboxBackendListenerIdentity {
    $listeners = @(
        Get-NetTCPConnection `
            -State Listen `
            -LocalAddress "127.0.0.1" `
            -LocalPort $BackendPort `
            -ErrorAction Stop
    )
    $listenerProcessIds = @($listeners | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    if ($listenerProcessIds.Count -ne 1 -or $listenerProcessIds[0] -le 0) {
        throw "后端端口没有唯一的 loopback 监听进程。"
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
        throw "后端 SCM 服务未处于可证明的 Running 状态。"
    }
    $listenerProcessId = $listenerProcessIds[0]
    $listener = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId=$listenerProcessId" `
        -ErrorAction Stop
    if ($null -eq $listener -or [string]::IsNullOrWhiteSpace([string]$listener.ExecutablePath)) {
        throw "无法读取后端监听进程身份。"
    }
    $serviceProcessId = [int]$service.ProcessId
    if ([int]$listener.ParentProcessId -ne $serviceProcessId) {
        throw "后端监听进程不是 Shawl 服务进程的直接子进程。"
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
        throw "后端监听进程链与受保护安装目录不一致。"
    }
    return [pscustomobject]@{
        ListenerProcessId = $listenerProcessId
        ServiceProcessId = $serviceProcessId
        ListenerCreationDate = [string]$listener.CreationDate
        ServiceCreationDate = [string]$serviceProcess.CreationDate
    }
}

function Assert-TicketboxBackendListenerUnchanged([object]$ExpectedIdentity) {
    $actual = Get-TicketboxBackendListenerIdentity
    if (
        $actual.ListenerProcessId -ne $ExpectedIdentity.ListenerProcessId -or
        $actual.ServiceProcessId -ne $ExpectedIdentity.ServiceProcessId -or
        $actual.ListenerCreationDate -cne $ExpectedIdentity.ListenerCreationDate -or
        $actual.ServiceCreationDate -cne $ExpectedIdentity.ServiceCreationDate
    ) {
        throw "后端 HTTP 请求期间监听进程身份发生变化。"
    }
}

function Read-TicketboxBoundedUtf8HttpResponse(
    [System.Net.WebResponse]$Response,
    [ValidateRange(1, 1048576)][int]$MaximumBytes
) {
    if ($Response.ContentLength -gt $MaximumBytes) {
        throw "owner bootstrap HTTP 响应超过大小上限。"
    }
    $stream = $null
    $buffer = New-Object 'System.Byte[]' 8192
    $memory = New-Object System.IO.MemoryStream
    $payloadBytes = $null
    try {
        $stream = $Response.GetResponseStream()
        if ($null -eq $stream) {
            throw "owner bootstrap HTTP 响应没有 body。"
        }
        $total = 0
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $read
            if ($total -gt $MaximumBytes) {
                throw "owner bootstrap HTTP 响应超过大小上限。"
            }
            $memory.Write($buffer, 0, $read)
        }
        $payloadBytes = $memory.ToArray()
        $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
        return $utf8.GetString($payloadBytes)
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        $memory.Dispose()
        [System.Array]::Clear($buffer, 0, $buffer.Length)
        if ($null -ne $payloadBytes) {
            [System.Array]::Clear($payloadBytes, 0, $payloadBytes.Length)
        }
    }
}

function Invoke-TicketboxInstallationOwnerBootstrapHttpRequest(
    [string]$Url,
    [string]$Secret,
    [byte[]]$BodyBytes,
    [int]$TimeoutMilliseconds
) {
    $uri = New-Object System.Uri($Url)
    if (
        $uri.Scheme -cne "http" -or
        $uri.Host -cne "127.0.0.1" -or
        $uri.UserInfo.Length -ne 0 -or
        $uri.Query.Length -ne 0 -or
        $uri.Fragment.Length -ne 0 -or
        $uri.AbsolutePath -cne "/api/bootstrap/installation-owner"
    ) {
        throw "owner bootstrap URL 不符合固定 loopback 契约。"
    }
    if ($TimeoutMilliseconds -lt 1) {
        throw "owner bootstrap HTTP 请求没有可用超时预算。"
    }

    $identity = Get-TicketboxBackendListenerIdentity
    $request = [System.Net.HttpWebRequest]::Create($uri)
    $request.Method = "POST"
    $request.Accept = "application/json"
    $request.ContentType = "application/json; charset=utf-8"
    $request.Headers.Add("X-Bootstrap-Secret", $Secret)
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.KeepAlive = $false
    $request.Timeout = $TimeoutMilliseconds
    $request.ReadWriteTimeout = $TimeoutMilliseconds
    $request.ContentLength = $BodyBytes.Length
    $requestStream = $null
    $response = $null
    try {
        $requestStream = $request.GetRequestStream()
        $requestStream.Write($BodyBytes, 0, $BodyBytes.Length)
        $requestStream.Dispose()
        $requestStream = $null
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        if ([int]$response.StatusCode -ne 200) {
            throw "owner bootstrap HTTP 状态不符合契约。"
        }
        $mediaType = ([string]$response.ContentType -split ";", 2)[0].Trim()
        if (-not [string]::Equals(
            $mediaType,
            "application/json",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "owner bootstrap HTTP 响应不是 JSON。"
        }
        $responseText = Read-TicketboxBoundedUtf8HttpResponse `
            -Response $response `
            -MaximumBytes $script:BootstrapMaximumResponseBytes
        try {
            $payload = $responseText | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "owner bootstrap HTTP 响应不是有效 JSON。"
        }
    }
    catch {
        $requestFailure = $_.Exception
        if (
            $requestFailure -is [System.Net.WebException] -and
            $null -ne $requestFailure.Response
        ) {
            $requestFailure.Response.Dispose()
        }
        try {
            Assert-TicketboxBackendListenerUnchanged $identity
        }
        catch {
            throw (New-Object System.Security.SecurityException(
                "owner bootstrap HTTP 请求异常后的 listener 后验复核失败；bootstrap secret 可能已暴露，拒绝继续本轮重试。"
            ))
        }
        throw (New-Object System.InvalidOperationException(
            "owner bootstrap HTTP 请求失败；已隐藏底层响应，避免敏感请求上下文进入日志。"
        ))
    }
    finally {
        if ($null -ne $requestStream) {
            $requestStream.Dispose()
        }
        if ($null -ne $response) {
            $response.Dispose()
        }
    }
    try {
        Assert-TicketboxBackendListenerUnchanged $identity
    }
    catch {
        throw (New-Object System.Security.SecurityException(
            "owner bootstrap HTTP 响应后的 listener 后验复核失败；bootstrap secret 可能已暴露，拒绝继续本轮重试。"
        ))
    }
    return $payload
}

function Invoke-TicketboxDirectLoopbackHealthHttpRequest(
    [string]$Url,
    [int]$TimeoutMilliseconds
) {
    $uri = New-Object System.Uri($Url)
    if (
        $uri.Scheme -cne "http" -or
        $uri.Host -cne "127.0.0.1" -or
        $uri.UserInfo.Length -ne 0 -or
        $uri.Query.Length -ne 0 -or
        $uri.Fragment.Length -ne 0 -or
        $uri.AbsolutePath -cne "/api/health/installation"
    ) {
        throw "后端安装就绪 URL 不符合固定 loopback 契约。"
    }
    if ($TimeoutMilliseconds -lt 1) {
        throw "后端安装就绪请求没有可用超时预算。"
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
            throw "后端安装就绪 HTTP 状态不是 200。"
        }
        $mediaType = ([string]$response.ContentType -split ";", 2)[0].Trim()
        if (-not [string]::Equals(
            $mediaType,
            "application/json",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "后端安装就绪 HTTP 响应不是 JSON。"
        }
        $responseText = Read-TicketboxBoundedUtf8HttpResponse `
            -Response $response `
            -MaximumBytes $script:BootstrapMaximumResponseBytes
        return $responseText | ConvertFrom-Json -ErrorAction Stop
    }
    finally {
        if ($null -ne $response) {
            $response.Dispose()
        }
    }
}

function Get-TicketboxExpectedBackendVersion {
    $manifestPath = Join-Path $ProgramDir "BUILD_PROVENANCE.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "缺少已安装 backend build manifest：$manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    $version = [string]$manifest.backend_version
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw "已安装 backend build manifest 缺少 backend_version。"
    }
    return $version
}

function Get-TicketboxExpectedInstallationId {
    # The installed service exports TICKETBOX_DATA_DIR=$AppData. Match
    # config.installation_identity(): normcase(resolve(path)), UTF-8 SHA-256.
    $canonicalDataRoot = (ConvertTo-TicketboxCanonicalPath $AppData).ToLowerInvariant()
    $identityText = "ticketbox-installation-v1`0$canonicalDataRoot"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($identityText))
        $hex = ([System.BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
        return "ticketbox-$($hex.Substring(0, 32))"
    }
    finally {
        $sha256.Dispose()
    }
}

function Assert-TicketboxInstallationHealthResponse(
    [object]$Payload,
    [string]$ExpectedBackendVersion,
    [string]$ExpectedInstallationId
) {
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
        [string]$Payload.owner_recovery_channel -notin @(
            "development",
            "managed_host",
            "operator"
        ) -or
        $null -eq $mobile -or
        @($mobile.PSObject.Properties).Count -ne 3 -or
        [string]$mobile.mobile_endpoint_state -notin @(
            "local_only",
            "public_configured_unverified"
        ) -or
        [string]$mobile.android_binding_state -notin @(
            "setup_required",
            "configured_unverified"
        ) -or
        [string]$mobile.iphone_upload_state -notin @(
            "setup_required",
            "configured_unverified"
        ) -or
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
        throw "installation health 响应与当前安装身份不一致。"
    }
}

function Wait-BackendHealth {
    $url = "http://127.0.0.1:$BackendPort/api/health/installation"
    $expectedBackendVersion = Get-TicketboxExpectedBackendVersion
    $expectedInstallationId = Get-TicketboxExpectedInstallationId
    $deadline = New-TicketboxWaitDeadline $BackendReadyTimeoutMs
    $lastError = ""
    do {
        $remaining = [Math]::Max(1, $BackendReadyTimeoutMs - $deadline.ElapsedMilliseconds)
        $probeBudget = [int][Math]::Min([long]$BackendHealthRequestTimeoutMs, [long]$remaining)
        try {
            $identity = Get-TicketboxBackendListenerIdentity
            $payload = Invoke-TicketboxDirectLoopbackHealthHttpRequest `
                -Url $url `
                -TimeoutMilliseconds $probeBudget
            Assert-TicketboxBackendListenerUnchanged $identity
            Assert-TicketboxInstallationHealthResponse `
                -Payload $payload `
                -ExpectedBackendVersion $expectedBackendVersion `
                -ExpectedInstallationId $expectedInstallationId
            Write-Ok "后端已就绪：$url"
            return
        }
        catch {
            $lastError = $_.Exception.Message
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $BackendReadyTimeoutMs `
        -PollMilliseconds $BackendReadyPollIntervalMs)
    throw "后端服务未在 $BackendReadyTimeoutMs ms 内通过安装身份和就绪检查：$lastError"
}

function Assert-TicketboxInstallationOwnerBootstrapResponse {
    param(
        [Parameter(Mandatory = $true)][object]$Response,
        [Parameter(Mandatory = $true)][string]$Secret,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )

    $propertyNames = @($Response.PSObject.Properties.Name | Sort-Object)
    $expectedNames = @(
        "account_name",
        "claim_generation",
        "contract",
        "device_name",
        "installation_id",
        "ledger_id",
        "ledger_name",
        "operation_id",
        "pairing_code",
        "pairing_derivation_index",
        "pairing_expires_at"
    ) | Sort-Object
    if (($propertyNames -join "|") -cne ($expectedNames -join "|")) {
        throw "installation owner bootstrap 响应字段不符合 pairing-only 契约。"
    }
    $derivationIndex = -1
    $claimGeneration = 0
    [DateTimeOffset]$pairingExpiresAt = [DateTimeOffset]::MinValue
    if (
        [string]$Response.contract -cne $script:InstallationOwnerContract -or
        [string]$Response.operation_id -cne $ExpectedOperationId -or
        [string]$Response.installation_id -cne $ExpectedInstallationId -or
        [string]::IsNullOrWhiteSpace([string]$Response.account_name) -or
        [string]::IsNullOrWhiteSpace([string]$Response.ledger_id) -or
        [string]::IsNullOrWhiteSpace([string]$Response.ledger_name) -or
        [string]::IsNullOrWhiteSpace([string]$Response.device_name) -or
        -not [int]::TryParse(
            [string]$Response.pairing_derivation_index,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$derivationIndex
        ) -or
        $derivationIndex -lt 0 -or
        $derivationIndex -gt 63 -or
        -not [int]::TryParse(
            [string]$Response.claim_generation,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$claimGeneration
        ) -or
        $claimGeneration -lt 1 -or
        -not [DateTimeOffset]::TryParse(
            [string]$Response.pairing_expires_at,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$pairingExpiresAt
        ) -or
        $pairingExpiresAt.ToUniversalTime() -le [DateTimeOffset]::UtcNow
    ) {
        throw "installation owner bootstrap 响应身份或有效期无效。"
    }
    $expectedPairingCode = Get-TicketboxInstallationOwnerPairingCode `
        -Secret $Secret `
        -DerivationIndex $derivationIndex
    if ([string]$Response.pairing_code -cne $expectedPairingCode) {
        throw "installation owner bootstrap 响应与本地 pairing-only 派生不一致。"
    }
}

function Get-TicketboxOwnerHandoffProcessId {
    if ($InstallerLockOwnerProcessId -gt 0) { return $InstallerLockOwnerProcessId }
    return $PID
}

function Get-TicketboxOwnerHandoffLifecycleIdentity {
    $ownerProcessId = Get-TicketboxOwnerHandoffProcessId
    if ($InstallerLockOwnerProcessId -gt 0) {
        if (-not (Get-Command Get-TicketboxValidatedExternalLifecycleOwnerIdentity -ErrorAction SilentlyContinue)) {
            throw "owner handoff 缺少已验证的安装器生命周期身份 provider。"
        }
        $identity = Get-TicketboxValidatedExternalLifecycleOwnerIdentity $ownerProcessId
        return [pscustomobject]@{
            ProcessId = [int]$identity.ProcessId
            StartedUtc = [string]$identity.StartedUtc
        }
    }
    $process = Get-Process -Id $ownerProcessId -ErrorAction Stop
    return [pscustomobject]@{
        ProcessId = $ownerProcessId
        StartedUtc = $process.StartTime.ToUniversalTime().ToString(
            "yyyy-MM-ddTHH:mm:ss.fffffffZ",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    }
}

function Write-TicketboxOwnerHandoffRecord {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483647)][int]$ClaimGeneration,
        [Parameter(Mandatory = $true)][ValidateRange(0, 63)][int]$PairingDerivationIndex,
        [Parameter(Mandatory = $true)][string]$PairingCode,
        [Parameter(Mandatory = $true)][string]$PairingExpiresAt,
        [switch]$ReplaceExisting
    )
    [DateTimeOffset]$parsedPairingExpiresAt = [DateTimeOffset]::MinValue
    if (
        $OperationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        $InstallationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        $PairingCode -cnotmatch '^[0-9]{8}$' -or
        -not [DateTimeOffset]::TryParse(
            $PairingExpiresAt,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$parsedPairingExpiresAt
        )
    ) {
        throw "installation owner handoff 身份参数无效。"
    }
    Assert-TicketboxProtectedDirectoryAcl (Split-Path -Parent $OwnerHandoffPath)
    $ownerIdentity = Get-TicketboxOwnerHandoffLifecycleIdentity
    $text = [string]::Join([Environment]::NewLine, @(
        "SCHEMA=ticketbox-installation-owner-handoff-v2",
        "STATE=pending",
        "CONTRACT=$script:InstallationOwnerContract",
        "OPERATION_ID=$OperationId",
        "INSTALLATION_ID=$InstallationId",
        "CLAIM_GENERATION=$ClaimGeneration",
        "PAIRING_DERIVATION_INDEX=$PairingDerivationIndex",
        "PAIRING_CODE=$PairingCode",
        "PAIRING_EXPIRES_AT=$PairingExpiresAt",
        "INSTALLER_OWNER_PID=$($ownerIdentity.ProcessId)",
        "INSTALLER_OWNER_STARTED_UTC=$($ownerIdentity.StartedUtc)"
    )) + [Environment]::NewLine
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $OwnerHandoffPath `
        -Text $text `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting:$ReplaceExisting
    $persisted = Read-TicketboxProtectedUtf8Artifact `
        -Path $OwnerHandoffPath `
        -MaximumBytes 16384
    if ($persisted.Text -cne $text) {
        throw "owner 短期配对交付记录持久化校验失败。"
    }
}

function Write-TicketboxOwnerHandoffFromResponse {
    param(
        [Parameter(Mandatory = $true)][object]$Response,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId
    )
    Write-TicketboxOwnerHandoffRecord `
        -OperationId $OperationId `
        -InstallationId $InstallationId `
        -ClaimGeneration ([int]$Response.claim_generation) `
        -PairingDerivationIndex ([int]$Response.pairing_derivation_index) `
        -PairingCode ([string]$Response.pairing_code) `
        -PairingExpiresAt ([string]$Response.pairing_expires_at)
}

function Read-TicketboxOwnerHandoffArtifact([string]$Path) {
    Assert-TicketboxProtectedDirectoryAcl (Split-Path -Parent $Path)
    return Read-TicketboxProtectedUtf8Artifact `
        -Path $Path `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -MaximumBytes 16384
}

function Assert-TicketboxOwnerHandoffArtifact([string]$Path) {
    Read-TicketboxOwnerHandoffArtifact $Path | Out-Null
}

function Inspect-TicketboxRetiredOwnerHandoffArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerStatePath,
        [Parameter(Mandatory = $true)][string]$LegacyOwnerBootstrapPath,
        [Parameter(Mandatory = $true)][string]$LegacyOwnerHandoffPendingPath,
        [Parameter(Mandatory = $true)][string]$RetiredOwnerBootstrapPath,
        [Parameter(Mandatory = $true)][string]$RetiredOwnerHandoffPendingPath
    )

    Initialize-TicketboxInstallerStateDirectory $InstallerStatePath | Out-Null
    $retiredPaths = @(
        $LegacyOwnerBootstrapPath,
        $LegacyOwnerHandoffPendingPath,
        $RetiredOwnerBootstrapPath,
        $RetiredOwnerHandoffPendingPath
    )
    $observed = @()
    foreach ($path in $retiredPaths) {
        $kind = "Unclassifiable"
        try {
            $kind = Get-TicketboxPathEntryKindNoFollow $path
        }
        catch {
            # A retired protocol is not a current authority or trust input.
            # Record only that its shape could not be classified; never open,
            # repair, migrate, delete, or let it block the current protocol.
        }
        if ($kind -cne "Missing") {
            $observed += "${path} [$kind]"
        }
    }
    if ($observed.Count -gt 0) {
        Write-Warn2 (
            "发现旧 owner handoff 协议文件；它们仅作为受保护审计对象保留，" +
            "不会读取内容、迁移、删除、展示、阻断安装或成为当前 pairing handoff 权威：" +
            ($observed -join ";")
        )
    }
}

function Read-TicketboxOwnerHandoffRecord {
    $artifact = Read-TicketboxOwnerHandoffArtifact $OwnerHandoffPath
    $newLine = [Environment]::NewLine
    if (-not $artifact.Text.EndsWith($newLine, [System.StringComparison]::Ordinal)) {
        throw "owner 绑定交付标记必须以平台换行结尾。"
    }
    $body = $artifact.Text.Substring(0, $artifact.Text.Length - $newLine.Length)
    $lines = @($body.Split(
        [string[]]@($newLine),
        [System.StringSplitOptions]::None
    ))
    if (
        $lines.Count -ne 11 -or
        $lines[0] -cne "SCHEMA=ticketbox-installation-owner-handoff-v2" -or
        $lines[1] -cne "STATE=pending" -or
        $lines[2] -cne "CONTRACT=$script:InstallationOwnerContract" -or
        -not $lines[3].StartsWith("OPERATION_ID=", [System.StringComparison]::Ordinal) -or
        -not $lines[4].StartsWith("INSTALLATION_ID=", [System.StringComparison]::Ordinal) -or
        -not $lines[5].StartsWith("CLAIM_GENERATION=", [System.StringComparison]::Ordinal) -or
        -not $lines[6].StartsWith("PAIRING_DERIVATION_INDEX=", [System.StringComparison]::Ordinal) -or
        -not $lines[7].StartsWith("PAIRING_CODE=", [System.StringComparison]::Ordinal) -or
        -not $lines[8].StartsWith("PAIRING_EXPIRES_AT=", [System.StringComparison]::Ordinal) -or
        -not $lines[9].StartsWith("INSTALLER_OWNER_PID=", [System.StringComparison]::Ordinal) -or
        -not $lines[10].StartsWith("INSTALLER_OWNER_STARTED_UTC=", [System.StringComparison]::Ordinal)
    ) {
        throw "owner 绑定交付标记格式无效。"
    }
    $operationId = $lines[3].Substring("OPERATION_ID=".Length)
    $installationId = $lines[4].Substring("INSTALLATION_ID=".Length)
    $claimGenerationText = $lines[5].Substring("CLAIM_GENERATION=".Length)
    $claimGeneration = 0
    $pairingDerivationIndexText =
        $lines[6].Substring("PAIRING_DERIVATION_INDEX=".Length)
    $pairingDerivationIndex = -1
    $pairingCode = $lines[7].Substring("PAIRING_CODE=".Length)
    $pairingExpiresAtText = $lines[8].Substring("PAIRING_EXPIRES_AT=".Length)
    [DateTimeOffset]$pairingExpiresAt = [DateTimeOffset]::MinValue
    if (
        $operationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        $installationId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' -or
        -not [int]::TryParse(
            $claimGenerationText,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$claimGeneration
        ) -or
        $claimGeneration -lt 1 -or
        -not [int]::TryParse(
            $pairingDerivationIndexText,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$pairingDerivationIndex
        ) -or
        $pairingDerivationIndex -lt 0 -or
        $pairingDerivationIndex -gt 63 -or
        $pairingCode -cnotmatch '^[0-9]{8}$' -or
        -not [DateTimeOffset]::TryParse(
            $pairingExpiresAtText,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$pairingExpiresAt
        )
    ) {
        throw "owner 绑定交付标记事务身份无效。"
    }
    $ownerProcessText = $lines[9].Substring("INSTALLER_OWNER_PID=".Length)
    $ownerProcessId = 0
    if (
        $ownerProcessText -cnotmatch '^[1-9][0-9]*$' -or
        -not [int]::TryParse(
            $ownerProcessText,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$ownerProcessId
        ) -or $ownerProcessId -le 0
    ) {
        throw "owner 绑定交付标记 owner PID 无效。"
    }
    [DateTimeOffset]$ownerStartedAt = [DateTimeOffset]::MinValue
    $ownerStartedText = $lines[10].Substring("INSTALLER_OWNER_STARTED_UTC=".Length)
    $timestampFormat = "yyyy-MM-ddTHH:mm:ss.fffffffZ"
    $timestampStyles =
        [System.Globalization.DateTimeStyles]::AssumeUniversal -bor
        [System.Globalization.DateTimeStyles]::AdjustToUniversal
    if (
        -not [DateTimeOffset]::TryParseExact(
            $ownerStartedText,
            $timestampFormat,
            [System.Globalization.CultureInfo]::InvariantCulture,
            $timestampStyles,
            [ref]$ownerStartedAt
        ) -or
        $ownerStartedAt.ToUniversalTime().ToString(
            $timestampFormat,
            [System.Globalization.CultureInfo]::InvariantCulture
        ) -cne $ownerStartedText
    ) {
        throw "owner 绑定交付标记 owner 启动时间无效。"
    }
    return [pscustomobject]@{
        State = "pending"
        OperationId = $operationId
        InstallationId = $installationId
        ClaimGeneration = $claimGeneration
        PairingDerivationIndex = $pairingDerivationIndex
        PairingCode = $pairingCode
        PairingExpiresAt = $pairingExpiresAtText
        OwnerProcessId = $ownerProcessId
        OwnerStartedUtc = $ownerStartedAt.ToUniversalTime().ToString(
            "yyyy-MM-ddTHH:mm:ss.fffffffZ",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    }
}

function Test-TicketboxOwnerHandoffProcessIsAlive {
    param(
        [Parameter(Mandatory = $true)][object]$Record,
        [scriptblock]$ProcessReader = {
            param($ProcessId)
            Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        },
        [scriptblock]$HasExitedReader = {
            param($Process)
            $Process.Refresh()
            $Process.HasExited
        },
        [scriptblock]$StartedUtcReader = {
            param($Process)
            $Process.StartTime.ToUniversalTime().ToString(
                "yyyy-MM-ddTHH:mm:ss.fffffffZ",
                [System.Globalization.CultureInfo]::InvariantCulture
            )
        }
    )

    try { $process = & $ProcessReader $Record.OwnerProcessId }
    catch { return $false }
    if ($null -eq $process) { return $false }
    try {
        if ([bool](& $HasExitedReader $process)) { return $false }
        $started = & $StartedUtcReader $process
        if ($started -cne $Record.OwnerStartedUtc) { return $false }
        return -not [bool](& $HasExitedReader $process)
    }
    catch {
        # The current installer already owns the exclusive machine lifecycle lock.
        # An unverifiable reused PID cannot retain authority from an older owner record.
        return $false
    }
}

function Assert-TicketboxOwnerHandoffIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Record,
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )
    if (
        [string]$Record.OperationId -cne $ExpectedOperationId -or
        [string]$Record.InstallationId -cne $ExpectedInstallationId
    ) {
        throw "owner 绑定交付标记不属于当前 installation operation。"
    }
}

function Read-TicketboxOwnerHandoffState {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )
    $record = Read-TicketboxOwnerHandoffRecord
    Assert-TicketboxOwnerHandoffIdentity `
        -Record $record `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId
    $currentOwner = Get-TicketboxOwnerHandoffLifecycleIdentity
    if (
        $record.OwnerProcessId -ne $currentOwner.ProcessId -or
        $record.OwnerStartedUtc -cne $currentOwner.StartedUtc
    ) {
        throw "owner 绑定交付标记不属于当前安装器生命周期。"
    }
    return $record.State
}

function Adopt-TicketboxOwnerBootstrapHandoff {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )
    if (-not (Test-Path -LiteralPath $OwnerHandoffPath)) {
        return "absent"
    }
    $record = Read-TicketboxOwnerHandoffRecord
    Assert-TicketboxOwnerHandoffIdentity `
        -Record $record `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId
    $currentOwner = Get-TicketboxOwnerHandoffLifecycleIdentity
    if (
        $record.OwnerProcessId -eq $currentOwner.ProcessId -and
        $record.OwnerStartedUtc -ceq $currentOwner.StartedUtc
    ) {
        return "pending"
    }
    if (Test-TicketboxOwnerHandoffProcessIsAlive $record) {
        throw "上一个安装器仍持有 owner 绑定交付，拒绝接管。"
    }
    Write-TicketboxOwnerHandoffRecord `
        -OperationId $record.OperationId `
        -InstallationId $record.InstallationId `
        -ClaimGeneration $record.ClaimGeneration `
        -PairingDerivationIndex $record.PairingDerivationIndex `
        -PairingCode $record.PairingCode `
        -PairingExpiresAt $record.PairingExpiresAt `
        -ReplaceExisting
    return "pending"
}

function Complete-TicketboxOwnerBootstrapHandoff {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallationId
    )
    if (-not (Test-Path -LiteralPath $OwnerHandoffPath)) {
        return "already_absent"
    }
    $record = Read-TicketboxOwnerHandoffRecord
    Assert-TicketboxOwnerHandoffIdentity `
        -Record $record `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId
    if ((Read-TicketboxOwnerHandoffState `
        -ExpectedOperationId $ExpectedOperationId `
        -ExpectedInstallationId $ExpectedInstallationId) -cne "pending") {
        throw "owner 短期配对交付记录不允许清理。"
    }
    Remove-TicketboxSensitiveFile $OwnerHandoffPath
    if (Test-Path -LiteralPath $OwnerHandoffPath) {
        throw "owner 短期配对交付记录删除后仍然存在。"
    }
    return "removed"
}

function Complete-FirstOwnerBootstrapIfEnabled {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$InstallationOperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId
    )
    $envMap = Read-EnvMap $EnvPath
    if (-not $envMap.ContainsKey("HTTP_BOOTSTRAP_SECRET")) {
        return
    }
    $secret = $envMap["HTTP_BOOTSTRAP_SECRET"]
    if ($secret.Trim().Length -eq 0) {
        return
    }
    if (
        (Test-Path -LiteralPath $OwnerHandoffPath)
    ) {
        if (-not (Test-Path -LiteralPath $OwnerHandoffPath -PathType Leaf)) {
            throw "owner bootstrap handoff 不是普通文件。"
        }
        $record = Read-TicketboxOwnerHandoffRecord
        Assert-TicketboxOwnerHandoffIdentity `
            -Record $record `
            -ExpectedOperationId $InstallationOperationId `
            -ExpectedInstallationId $InstallationId
        if ((Read-TicketboxOwnerHandoffState `
            -ExpectedOperationId $InstallationOperationId `
            -ExpectedInstallationId $InstallationId) -cne "pending") {
            throw "只能为已持久化的 pending owner handoff 退役 bootstrap secret。"
        }
        Write-EnvNoBom -Path $EnvPath -Lines (New-BaseEnvLines $DatabaseUrl)
        Restart-TicketboxOwnedServiceIfExists `
            -Name $BackendServiceName `
            -ExpectedExecutable (Get-ExpectedServiceExecutable $BackendServiceName) `
            -BackendPort $BackendPort `
            -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
            @ServiceWaitArguments | Out-Null
        Wait-BackendHealth
        Write-Ok "已从持久化 owner handoff 续跑并退役 bootstrap secret。"
        return
    }
    Assert-TicketboxBootstrapSecret $secret
    $listenerExposureRecovered = $false

    Write-Step "建立 installation owner 短期配对"
    $url = "http://127.0.0.1:$BackendPort/api/bootstrap/installation-owner"
    $bodyText = @{
        operation_id = $InstallationOperationId
        installation_id = $InstallationId
        account_name = $AccountName
        ledger_name = $LedgerName
        device_name = $DeviceName
    } | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($bodyText)
    $deadline = New-TicketboxWaitDeadline $BootstrapRequestTimeoutMs
    $lastError = ""
    $response = $null
    do {
        $remaining = [Math]::Max(1, $BootstrapRequestTimeoutMs - $deadline.ElapsedMilliseconds)
        try {
            $response = Invoke-TicketboxInstallationOwnerBootstrapHttpRequest `
                -Url $url `
                -Secret $secret `
                -BodyBytes $bodyBytes `
                -TimeoutMilliseconds $remaining
            Assert-TicketboxInstallationOwnerBootstrapResponse `
                -Response $response `
                -Secret $secret `
                -ExpectedOperationId $InstallationOperationId `
                -ExpectedInstallationId $InstallationId
            break
        }
        catch [System.Security.SecurityException] {
            if ($listenerExposureRecovered) {
                Protect-TicketboxBootstrapAfterRepeatedListenerFailure `
                    -DatabaseUrl $DatabaseUrl `
                    -ExposedSecret $secret
                throw (New-Object System.Security.SecurityException(
                    "replacement listener 后验复核再次失败；已隔离当前 secret 并持久化下一轮恢复 intent。"
                ))
            }
            $secret = Invoke-TicketboxBootstrapExposureRecovery $DatabaseUrl $secret
            Assert-TicketboxBootstrapSecret $secret
            $listenerExposureRecovered = $true
            $deadline = New-TicketboxWaitDeadline $BootstrapRequestTimeoutMs
            $lastError = ""
            $response = $null
            continue
        }
        catch {
            $lastError = $_.Exception.Message
            $response = $null
        }
    } while (Wait-TicketboxPollBeforeDeadline `
        -Deadline $deadline `
        -TimeoutMilliseconds $BootstrapRequestTimeoutMs `
        -PollMilliseconds $BackendReadyPollIntervalMs)
    if ($null -eq $response) {
        throw "owner 初始化未在超时内完成可验证重试：$lastError"
    }

    Write-TicketboxOwnerHandoffFromResponse `
        -Response $response `
        -OperationId $InstallationOperationId `
        -InstallationId $InstallationId
    Write-Ok "installation owner 短期配对交付记录已写入：$OwnerHandoffPath"
    Write-EnvNoBom -Path $EnvPath -Lines (New-BaseEnvLines $DatabaseUrl)
    Restart-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $BackendServiceName) `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments | Out-Null
    Wait-BackendHealth
}
