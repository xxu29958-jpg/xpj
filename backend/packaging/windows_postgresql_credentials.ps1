#Requires -Version 5.1

function ConvertTo-TicketboxPostgresqlSecureString {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Value -cnotmatch '^[A-Za-z0-9_-]{32,128}$') {
        throw "$Label 不符合受保护随机凭据 shape。"
    }
    $secure = New-Object Security.SecureString
    foreach ($character in $Value.ToCharArray()) { $secure.AppendChar($character) }
    $secure.MakeReadOnly()
    return $secure
}

function New-TicketboxPostgresqlRandomSecret {
    $bytes = New-Object byte[] 48
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($bytes)
        return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    }
    finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $random.Dispose()
    }
}

function Assert-TicketboxPostgresqlSecureString {
    param(
        [AllowNull()][Security.SecureString]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Value -or $Value.Length -lt 32) {
        throw "$Label 缺失或不足 32 个字符；拒绝数据库 mutation。"
    }
}

function Invoke-TicketboxWithPlainPostgresqlSecret {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$Secret,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $pointer = [IntPtr]::Zero
    $plain = $null
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if (
            [string]::IsNullOrWhiteSpace($plain) -or
            $plain.Length -lt 32 -or
            $plain.Length -gt 128 -or
            $plain -cnotmatch '^[A-Za-z0-9_-]+$'
        ) {
            throw "PostgreSQL 凭据必须是 32 至 128 字符的受控 ASCII secret。"
        }
        return & $Action $plain
    }
    finally {
        $plain = $null
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

function ConvertTo-TicketboxPostgresqlScramVerifier {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [byte[]]$Salt
    )

    Assert-TicketboxPostgresqlSecureString $Password "PostgreSQL password"
    $generatedSalt = $false
    if ($null -eq $Salt) {
        $Salt = New-Object byte[] 16
        $generatedSalt = $true
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($Salt) }
        finally { $random.Dispose() }
    }
    if ($Salt.Length -ne 16) {
        throw "SCRAM salt 必须正好为 16 bytes。"
    }

    $saltCopy = New-Object byte[] $Salt.Length
    [Array]::Copy($Salt, $saltCopy, $Salt.Length)
    try {
        return Invoke-TicketboxWithPlainPostgresqlSecret -Secret $Password -Action {
            param([string]$PlainPassword)

            $derive = $null
            $saltedPassword = $null
            $clientKey = $null
            $storedKey = $null
            $serverKey = $null
            $clientHmac = $null
            $serverHmac = $null
            $sha = $null
            try {
                $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new(
                    $PlainPassword,
                    $saltCopy,
                    4096,
                    [Security.Cryptography.HashAlgorithmName]::SHA256
                )
                $saltedPassword = $derive.GetBytes(32)
                $clientHmac = [Security.Cryptography.HMACSHA256]::new($saltedPassword)
                $clientKey = $clientHmac.ComputeHash(
                    [Text.Encoding]::ASCII.GetBytes("Client Key")
                )
                $sha = [Security.Cryptography.SHA256]::Create()
                $storedKey = $sha.ComputeHash($clientKey)
                $serverHmac = [Security.Cryptography.HMACSHA256]::new($saltedPassword)
                $serverKey = $serverHmac.ComputeHash(
                    [Text.Encoding]::ASCII.GetBytes("Server Key")
                )
                return "SCRAM-SHA-256`$4096:$([Convert]::ToBase64String($saltCopy))" +
                    "`$$([Convert]::ToBase64String($storedKey)):" +
                    "$([Convert]::ToBase64String($serverKey))"
            }
            finally {
                if ($null -ne $derive) { $derive.Dispose() }
                if ($null -ne $clientHmac) { $clientHmac.Dispose() }
                if ($null -ne $serverHmac) { $serverHmac.Dispose() }
                if ($null -ne $sha) { $sha.Dispose() }
                foreach ($buffer in @(
                    $saltedPassword,
                    $clientKey,
                    $storedKey,
                    $serverKey
                )) {
                    if ($null -ne $buffer) {
                        [Array]::Clear($buffer, 0, $buffer.Length)
                    }
                }
            }
        }
    }
    finally {
        [Array]::Clear($saltCopy, 0, $saltCopy.Length)
        if ($generatedSalt) { [Array]::Clear($Salt, 0, $Salt.Length) }
    }
}
