#Requires -Version 5.1

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

    $identity = Get-TicketboxBackendListenerIdentity `
        -BackendPort $BackendPort `
        -BackendServiceName $BackendServiceName `
        -ShawlExe $ShawlExe `
        -BackendExe $BackendExe
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
            Assert-TicketboxBackendListenerUnchanged `
                -ExpectedIdentity $identity `
                -BackendPort $BackendPort `
                -BackendServiceName $BackendServiceName `
                -ShawlExe $ShawlExe `
                -BackendExe $BackendExe
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
        Assert-TicketboxBackendListenerUnchanged `
            -ExpectedIdentity $identity `
            -BackendPort $BackendPort `
            -BackendServiceName $BackendServiceName `
            -ShawlExe $ShawlExe `
            -BackendExe $BackendExe
    }
    catch {
        throw (New-Object System.Security.SecurityException(
            "owner bootstrap HTTP 响应后的 listener 后验复核失败；bootstrap secret 可能已暴露，拒绝继续本轮重试。"
        ))
    }
    return $payload
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
        [string]$Response.contract -cne $script:TicketboxInstallationOwnerContract -or
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


function Complete-FirstOwnerBootstrapIfEnabled {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl,
        [Parameter(Mandatory = $true)][string]$InstallationOperationId,
        [Parameter(Mandatory = $true)][string]$InstallationId,
        [Parameter(Mandatory = $true)][int]$SecretByteCount
    )
    $envMap = Read-EnvMap $EnvPath
    if (-not $envMap.ContainsKey("HTTP_BOOTSTRAP_SECRET")) {
        return
    }
    $secret = $envMap["HTTP_BOOTSTRAP_SECRET"]
    if ($secret.Trim().Length -eq 0) {
        return
    }
    $ownerHandoffKind = Get-TicketboxPathEntryKindNoFollow $OwnerHandoffPath
    if ($ownerHandoffKind -ceq "File") {
        $record = Read-TicketboxOwnerHandoffRecord -Path $OwnerHandoffPath
        Assert-TicketboxOwnerHandoffIdentity `
            -Record $record `
            -ExpectedOperationId $InstallationOperationId `
            -ExpectedInstallationId $InstallationId
        if ((Read-TicketboxOwnerHandoffState `
            -Path $OwnerHandoffPath `
            -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
            -ExpectedOperationId $InstallationOperationId `
            -ExpectedInstallationId $InstallationId) -cne "pending") {
            throw "只能为已持久化的 pending owner handoff 退役 bootstrap secret。"
        }
        Write-EnvNoBom `
            -Path $EnvPath `
            -Lines (New-BaseEnvLines $DatabaseUrl) `
            -BackendServiceName $BackendServiceName
        Restart-TicketboxOwnedServiceIfExists `
            -Name $BackendServiceName `
            -ExpectedExecutable (Get-ExpectedServiceExecutable $BackendServiceName) `
            -BackendPort $BackendPort `
            -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
            @ServiceWaitArguments | Out-Null
        Wait-TicketboxInstalledBackendHealth `
            -BackendPort $BackendPort `
            -BackendServiceName $BackendServiceName `
            -ShawlExe $ShawlExe `
            -BackendExe $BackendExe `
            -ProgramDir $ProgramDir `
            -AppData $AppData `
            -ReadyTimeoutMilliseconds $BackendReadyTimeoutMs `
            -RequestTimeoutMilliseconds $BackendHealthRequestTimeoutMs `
            -PollMilliseconds $BackendReadyPollIntervalMs `
            -MaximumResponseBytes $script:BootstrapMaximumResponseBytes
        Write-Ok "已从持久化 owner handoff 续跑并退役 bootstrap secret。"
        return
    }
    if ($ownerHandoffKind -cne "Missing") {
        throw "owner bootstrap handoff 不是可信普通文件。"
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
                    -ExposedSecret $secret `
                    -SecretByteCount $SecretByteCount
                throw (New-Object System.Security.SecurityException(
                    "replacement listener 后验复核再次失败；已隔离当前 secret 并持久化下一轮恢复 intent。"
                ))
            }
            $secret = Invoke-TicketboxBootstrapExposureRecovery `
                -DatabaseUrl $DatabaseUrl `
                -ExposedSecret $secret `
                -SecretByteCount $SecretByteCount
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

    Write-TicketboxOwnerHandoffRecord `
        -Path $OwnerHandoffPath `
        -InstallerOwnerProcessId $InstallerLockOwnerProcessId `
        -OperationId $InstallationOperationId `
        -InstallationId $InstallationId `
        -ClaimGeneration ([int]$response.claim_generation) `
        -PairingDerivationIndex ([int]$response.pairing_derivation_index) `
        -PairingCode ([string]$response.pairing_code) `
        -PairingExpiresAt ([string]$response.pairing_expires_at) `
        -ReplaceExisting $false
    Write-Ok "installation owner 短期配对交付记录已写入：$OwnerHandoffPath"
    Write-EnvNoBom `
        -Path $EnvPath `
        -Lines (New-BaseEnvLines $DatabaseUrl) `
        -BackendServiceName $BackendServiceName
    Restart-TicketboxOwnedServiceIfExists `
        -Name $BackendServiceName `
        -ExpectedExecutable (Get-ExpectedServiceExecutable $BackendServiceName) `
        -BackendPort $BackendPort `
        -ExpectedRuntimeExecutables @($BackendExe, $ShawlExe) `
        @ServiceWaitArguments | Out-Null
    Wait-TicketboxInstalledBackendHealth `
        -BackendPort $BackendPort `
        -BackendServiceName $BackendServiceName `
        -ShawlExe $ShawlExe `
        -BackendExe $BackendExe `
        -ProgramDir $ProgramDir `
        -AppData $AppData `
        -ReadyTimeoutMilliseconds $BackendReadyTimeoutMs `
        -RequestTimeoutMilliseconds $BackendHealthRequestTimeoutMs `
        -PollMilliseconds $BackendReadyPollIntervalMs `
        -MaximumResponseBytes $script:BootstrapMaximumResponseBytes
}
