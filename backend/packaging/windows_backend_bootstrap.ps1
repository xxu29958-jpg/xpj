#Requires -Version 5.1

$script:BootstrapAdminTokenContext = "ticketbox/bootstrap-owner/v1/admin-token"
$script:BootstrapUploadKeyContext = "ticketbox/bootstrap-owner/v1/upload-key"
$script:BootstrapPairingCodeContext = "ticketbox/bootstrap-owner/v1/pairing-code"
$script:BootstrapSecretMinimumBytes = 32
$script:BootstrapMaximumResponseBytes = 1048576

function Get-TicketboxBootstrapDigest([string]$Secret, [string]$Context) {
    $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($Secret)
    if ($secretBytes.Length -lt $script:BootstrapSecretMinimumBytes) {
        throw "HTTP bootstrap secret 少于 32 字节，拒绝使用低熵初始化凭据。"
    }
    $contextBytes = [System.Text.Encoding]::ASCII.GetBytes($Context)
    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    try {
        $hmac.Key = $secretBytes
        return $hmac.ComputeHash($contextBytes)
    }
    finally {
        $hmac.Dispose()
    }
}

function ConvertTo-TicketboxBase64Url([byte[]]$Bytes) {
    return [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-TicketboxBootstrapCredentials([string]$Secret) {
    $adminDigest = Get-TicketboxBootstrapDigest $Secret $script:BootstrapAdminTokenContext
    $uploadDigest = Get-TicketboxBootstrapDigest $Secret $script:BootstrapUploadKeyContext
    $pairingDigest = Get-TicketboxBootstrapDigest $Secret $script:BootstrapPairingCodeContext
    $pairingValue = [long]0
    foreach ($value in $pairingDigest) {
        $pairingValue = (($pairingValue * 256) + [int]$value) % 100000000
    }
    return [pscustomobject]@{
        AdminToken = "tbx_$(ConvertTo-TicketboxBase64Url $adminDigest)"
        UploadKey = "upl_$(ConvertTo-TicketboxBase64Url $uploadDigest)"
        PairingCode = $pairingValue.ToString("D8")
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

function Invoke-TicketboxOwnerBootstrapHttpRequest(
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
        $uri.AbsolutePath -cne "/api/bootstrap/owner"
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

function Assert-TicketboxBootstrapResponse([object]$Response, [object]$ExpectedCredentials) {
    if (
        [string]$Response.admin_token -cne $ExpectedCredentials.AdminToken -or
        [string]$Response.upload_key -cne $ExpectedCredentials.UploadKey -or
        [string]$Response.upload_url_path -cne "/u/$($ExpectedCredentials.UploadKey)" -or
        [string]$Response.pairing_code -cne $ExpectedCredentials.PairingCode -or
        [string]::IsNullOrWhiteSpace([string]$Response.account_name) -or
        [string]::IsNullOrWhiteSpace([string]$Response.ledger_id) -or
        [string]::IsNullOrWhiteSpace([string]$Response.ledger_name) -or
        [string]::IsNullOrWhiteSpace([string]$Response.device_name) -or
        [string]::IsNullOrWhiteSpace([string]$Response.pairing_expires_at)
    ) {
        throw "bootstrap 响应与本地派生凭据或身份契约不一致。"
    }
}

function Get-TicketboxOwnerHandoffTextSha256([string]$Text) {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))
        return ([System.BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-TicketboxOwnerHandoffInstallationId {
    $install = (ConvertTo-TicketboxCanonicalPath $InstallDir).ToUpperInvariant()
    $data = (ConvertTo-TicketboxCanonicalPath $DataRoot).ToUpperInvariant()
    return (Get-TicketboxOwnerHandoffTextSha256 `
        "ticketbox-owner-handoff-v2`0$install`0$data")
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

function Write-TicketboxOwnerHandoffMarker {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("pending", "confirmed")][string]$State,
        [Parameter(Mandatory = $true)][string]$Generation,
        [Parameter(Mandatory = $true)][string]$CredentialSha256,
        [switch]$ReplaceExisting
    )
    Assert-TicketboxProtectedDirectoryAcl (Split-Path -Parent $OwnerHandoffPendingPath)
    $ownerIdentity = Get-TicketboxOwnerHandoffLifecycleIdentity
    $text = [string]::Join([Environment]::NewLine, @(
        "SCHEMA=ticketbox-owner-handoff-v2",
        "STATE=$State",
        "GENERATION=$Generation",
        "INSTALLATION_ID=$(Get-TicketboxOwnerHandoffInstallationId)",
        "CREDENTIAL_SHA256=$CredentialSha256",
        "INSTALLER_OWNER_PID=$($ownerIdentity.ProcessId)",
        "INSTALLER_OWNER_STARTED_UTC=$($ownerIdentity.StartedUtc)"
    )) + [Environment]::NewLine
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $OwnerHandoffPendingPath `
        -Text $text `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM" `
        -ReplaceExisting:$ReplaceExisting
    $persisted = Read-TicketboxProtectedUtf8Artifact `
        -Path $OwnerHandoffPendingPath `
        -MaximumBytes 16384
    if ($persisted.Text -cne $text) {
        throw "owner 绑定交付标记持久化校验失败。"
    }
}

function Write-TicketboxOwnerHandoffPendingMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Generation,
        [Parameter(Mandatory = $true)][string]$CredentialSha256
    )
    Write-TicketboxOwnerHandoffMarker `
        -State "pending" `
        -Generation $Generation `
        -CredentialSha256 $CredentialSha256
}

function Write-TicketboxOwnerBootstrapFile([object]$Response) {
    Assert-TicketboxProtectedDirectoryAcl (Split-Path -Parent $OwnerBootstrapPath)
    $lines = @(
        "小票夹 Owner 身份（请妥善保存）",
        "owner account: $($Response.account_name)",
        "default ledger: $($Response.ledger_name) ($($Response.ledger_id))",
        "bootstrap device: $($Response.device_name)",
        "admin token: $($Response.admin_token)",
        "iOS upload URL path: $($Response.upload_url_path)",
        "iOS upload key: $($Response.upload_key)",
        "绑定此电脑码（仅供小票夹管理器首次连接）: $($Response.pairing_code)",
        "绑定此电脑码过期时间: $($Response.pairing_expires_at)",
        "下一步: 打开小票夹管理器，用此码绑定桌面账本",
        "Android: 桌面绑定成功后，在管理器中配置手机连接并生成一枚新的单次码"
    )
    $expected = [string]::Join([Environment]::NewLine, $lines) + [Environment]::NewLine
    $credentialSha256 = Get-TicketboxOwnerHandoffTextSha256 $expected
    Write-TicketboxOwnerHandoffPendingMarker `
        -Generation ([Guid]::NewGuid().ToString("D")) `
        -CredentialSha256 $credentialSha256
    Write-TicketboxProtectedUtf8FileDurable `
        -Path $OwnerBootstrapPath `
        -Text $expected `
        -FullControlAccounts @("SYSTEM", "BUILTIN\Administrators") `
        -OwnerAccount "SYSTEM"
    $persisted = Read-TicketboxProtectedUtf8Artifact `
        -Path $OwnerBootstrapPath `
        -MaximumBytes 16384
    if (
        $persisted.Text -cne $expected -or
        (Get-TicketboxOwnerHandoffTextSha256 $persisted.Text) -cne $credentialSha256
    ) {
        throw "owner 凭据文件持久化校验失败。"
    }
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

function Move-TicketboxLegacyOwnerHandoffArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$InstallerStatePath,
        [Parameter(Mandatory = $true)][string]$LegacyOwnerBootstrapPath,
        [Parameter(Mandatory = $true)][string]$LegacyOwnerHandoffPendingPath
    )

    Initialize-TicketboxInstallerStateDirectory $InstallerStatePath | Out-Null
    $legacyCredentialExists = Test-Path -LiteralPath $LegacyOwnerBootstrapPath
    $legacyMarkerExists = Test-Path -LiteralPath $LegacyOwnerHandoffPendingPath
    foreach ($path in @(
        $LegacyOwnerBootstrapPath,
        $LegacyOwnerHandoffPendingPath,
        $OwnerBootstrapPath,
        $OwnerHandoffPendingPath
    )) {
        if (Test-Path -LiteralPath $path) {
            Read-TicketboxProtectedUtf8Artifact `
                -Path $path `
                -MaximumBytes 16384 | Out-Null
        }
    }
    if ($legacyCredentialExists -and -not $legacyMarkerExists) {
        Move-TicketboxLegacyInstallerStateArtifact `
            -LegacyPath $LegacyOwnerBootstrapPath `
            -CurrentPath $OwnerBootstrapPath `
            -RetainLegacySource
        if (Test-Path -LiteralPath $OwnerHandoffPendingPath) {
            $record = Read-TicketboxOwnerHandoffRecord
            Assert-TicketboxOwnerHandoffCredential $record
        }
        else {
            $credential = Read-TicketboxOwnerHandoffArtifact $OwnerBootstrapPath
            Write-TicketboxOwnerHandoffPendingMarker `
                -Generation ([Guid]::NewGuid().ToString("D")) `
                -CredentialSha256 (Get-TicketboxOwnerHandoffTextSha256 $credential.Text)
            $record = Read-TicketboxOwnerHandoffRecord
            Assert-TicketboxOwnerHandoffCredential $record
        }
        Remove-TicketboxProtectedUtf8Artifact -Path $LegacyOwnerBootstrapPath
        return
    }
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $LegacyOwnerBootstrapPath `
        -CurrentPath $OwnerBootstrapPath
    Move-TicketboxLegacyInstallerStateArtifact `
        -LegacyPath $LegacyOwnerHandoffPendingPath `
        -CurrentPath $OwnerHandoffPendingPath
}

function Read-TicketboxOwnerHandoffRecord {
    $artifact = Read-TicketboxOwnerHandoffArtifact $OwnerHandoffPendingPath
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
        $lines.Count -ne 7 -or
        $lines[0] -cne "SCHEMA=ticketbox-owner-handoff-v2" -or
        $lines[1] -notin @("STATE=pending", "STATE=confirmed") -or
        -not $lines[2].StartsWith("GENERATION=", [System.StringComparison]::Ordinal) -or
        -not $lines[3].StartsWith("INSTALLATION_ID=", [System.StringComparison]::Ordinal) -or
        -not $lines[4].StartsWith("CREDENTIAL_SHA256=", [System.StringComparison]::Ordinal) -or
        -not $lines[5].StartsWith("INSTALLER_OWNER_PID=", [System.StringComparison]::Ordinal) -or
        -not $lines[6].StartsWith("INSTALLER_OWNER_STARTED_UTC=", [System.StringComparison]::Ordinal)
    ) {
        throw "owner 绑定交付标记格式无效。"
    }
    $generationText = $lines[2].Substring("GENERATION=".Length)
    [Guid]$generation = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($generationText, "D", [ref]$generation) -or
        $generation.ToString("D") -cne $generationText
    ) {
        throw "owner 绑定交付标记 generation 无效。"
    }
    $installationId = $lines[3].Substring("INSTALLATION_ID=".Length)
    $credentialSha256 = $lines[4].Substring("CREDENTIAL_SHA256=".Length)
    if (
        $installationId -cne (Get-TicketboxOwnerHandoffInstallationId) -or
        $credentialSha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "owner 绑定交付标记不属于当前安装身份。"
    }
    $ownerProcessText = $lines[5].Substring("INSTALLER_OWNER_PID=".Length)
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
    $ownerStartedText = $lines[6].Substring("INSTALLER_OWNER_STARTED_UTC=".Length)
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
        State = $lines[1].Substring("STATE=".Length)
        Generation = $generation.ToString("D")
        CredentialSha256 = $credentialSha256
        OwnerProcessId = $ownerProcessId
        OwnerStartedUtc = $ownerStartedAt.ToUniversalTime().ToString(
            "yyyy-MM-ddTHH:mm:ss.fffffffZ",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    }
}

function Assert-TicketboxOwnerHandoffCredential([object]$Record) {
    $artifact = Read-TicketboxOwnerHandoffArtifact $OwnerBootstrapPath
    $content = $artifact.Text
    if (
        (Get-TicketboxOwnerHandoffTextSha256 $content) -cne $Record.CredentialSha256
    ) {
        throw "owner 绑定交付凭据与受保护标记不匹配。"
    }
}

function Test-TicketboxOwnerHandoffProcessIsAlive {
    param(
        [Parameter(Mandatory = $true)][object]$Record,
        [scriptblock]$ProcessReader = {
            param($ProcessId)
            Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
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
        $started = & $StartedUtcReader $process
        return $started -ceq $Record.OwnerStartedUtc
    }
    catch {
        # The current installer already owns the exclusive machine lifecycle lock.
        # An unverifiable reused PID cannot retain authority from an older owner record.
        return $false
    }
}

function Read-TicketboxOwnerHandoffState {
    $record = Read-TicketboxOwnerHandoffRecord
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
    if (-not (Test-Path -LiteralPath $OwnerHandoffPendingPath)) {
        if (Test-Path -LiteralPath $OwnerBootstrapPath) {
            Assert-TicketboxOwnerHandoffArtifact $OwnerBootstrapPath
            throw "current installer-state 中存在无绑定标记的 owner 凭据；拒绝猜测来源或自动删除。"
        }
        return "absent"
    }
    $record = Read-TicketboxOwnerHandoffRecord
    $currentOwner = Get-TicketboxOwnerHandoffLifecycleIdentity
    if (
        $record.OwnerProcessId -eq $currentOwner.ProcessId -and
        $record.OwnerStartedUtc -ceq $currentOwner.StartedUtc
    ) {
        if ($record.State -ceq "pending") {
            Assert-TicketboxOwnerHandoffCredential $record
        }
        return $record.State
    }
    if (Test-TicketboxOwnerHandoffProcessIsAlive $record) {
        throw "上一个安装器仍持有 owner 绑定交付，拒绝接管。"
    }
    if ($record.State -ceq "pending") {
        if (-not (Test-Path -LiteralPath $OwnerBootstrapPath -PathType Leaf)) {
            $environment = Read-EnvMap $EnvPath
            if ($environment.ContainsKey("HTTP_BOOTSTRAP_SECRET")) {
                Remove-TicketboxSensitiveFile $OwnerHandoffPendingPath
                return "retry_bootstrap"
            }
            throw "owner 绑定交付凭据缺失且 bootstrap secret 已移除，拒绝重建。"
        }
        Assert-TicketboxOwnerHandoffCredential $record
    }
    Write-TicketboxOwnerHandoffMarker `
        -State $record.State `
        -Generation $record.Generation `
        -CredentialSha256 $record.CredentialSha256 `
        -ReplaceExisting
    if ($record.State -ceq "confirmed") {
        Complete-TicketboxOwnerBootstrapHandoff
        return "cleaned_confirmed"
    }
    return "pending"
}

function Set-TicketboxOwnerHandoffConfirmed {
    $record = Read-TicketboxOwnerHandoffRecord
    Assert-TicketboxOwnerHandoffCredential $record
    Write-TicketboxOwnerHandoffMarker `
        -State "confirmed" `
        -Generation $record.Generation `
        -CredentialSha256 $record.CredentialSha256 `
        -ReplaceExisting
    if ((Read-TicketboxOwnerHandoffState) -cne "confirmed") {
        throw "owner 绑定交付 confirmed 状态持久化校验失败。"
    }
}

function Complete-TicketboxOwnerBootstrapHandoff {
    $record = Read-TicketboxOwnerHandoffRecord
    $state = Read-TicketboxOwnerHandoffState
    if ($state -ceq "pending") {
        Assert-TicketboxOwnerHandoffCredential $record
        Set-TicketboxOwnerHandoffConfirmed
        $state = "confirmed"
    }
    if ($state -cne "confirmed") {
        throw "owner 绑定交付标记不允许清理：$state"
    }
    if (Test-Path -LiteralPath $OwnerBootstrapPath) {
        Assert-TicketboxOwnerHandoffArtifact $OwnerBootstrapPath
        Remove-TicketboxSensitiveFile $OwnerBootstrapPath
    }
    Remove-TicketboxSensitiveFile $OwnerHandoffPendingPath
    if (
        (Test-Path -LiteralPath $OwnerBootstrapPath) -or
        (Test-Path -LiteralPath $OwnerHandoffPendingPath)
    ) {
        throw "owner 绑定交付文件删除后仍然存在。"
    }
}

function Complete-FirstOwnerBootstrapIfEnabled([string]$DatabaseUrl) {
    $envMap = Read-EnvMap $EnvPath
    if (-not $envMap.ContainsKey("HTTP_BOOTSTRAP_SECRET")) {
        return
    }
    $secret = $envMap["HTTP_BOOTSTRAP_SECRET"]
    if ($secret.Trim().Length -eq 0) {
        return
    }
    if (
        (Test-Path -LiteralPath $OwnerHandoffPendingPath) -or
        (Test-Path -LiteralPath $OwnerBootstrapPath)
    ) {
        if (
            -not (Test-Path -LiteralPath $OwnerHandoffPendingPath -PathType Leaf) -or
            -not (Test-Path -LiteralPath $OwnerBootstrapPath -PathType Leaf)
        ) {
            throw "owner bootstrap 已部分持久化，但 handoff artifact 不完整。"
        }
        $record = Read-TicketboxOwnerHandoffRecord
        if ((Read-TicketboxOwnerHandoffState) -cne "pending") {
            throw "只能为已持久化的 pending owner handoff 退役 bootstrap secret。"
        }
        Assert-TicketboxOwnerHandoffCredential $record
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
    $expectedCredentials = Get-TicketboxBootstrapCredentials $secret
    $listenerExposureRecovered = $false

    Write-Step "首次初始化 owner 身份"
    $url = "http://127.0.0.1:$BackendPort/api/bootstrap/owner"
    $bodyText = @{
        account_name = $AccountName
        ledger_name = $LedgerName
        device_name = $DeviceName
        default_timezone = $Timezone
    } | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($bodyText)
    $deadline = New-TicketboxWaitDeadline $BootstrapRequestTimeoutMs
    $lastError = ""
    $response = $null
    do {
        $remaining = [Math]::Max(1, $BootstrapRequestTimeoutMs - $deadline.ElapsedMilliseconds)
        try {
            $response = Invoke-TicketboxOwnerBootstrapHttpRequest `
                -Url $url `
                -Secret $secret `
                -BodyBytes $bodyBytes `
                -TimeoutMilliseconds $remaining
            Assert-TicketboxBootstrapResponse $response $expectedCredentials
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
            $expectedCredentials = Get-TicketboxBootstrapCredentials $secret
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

    Write-TicketboxOwnerBootstrapFile $response
    Write-Ok "owner 凭证已写入：$OwnerBootstrapPath"
    Write-EnvNoBom -Path $EnvPath -Lines (New-BaseEnvLines $DatabaseUrl)
    Restart-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $BackendServiceName) `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments | Out-Null
    Wait-BackendHealth
}
