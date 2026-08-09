#requires -Version 5.1

Set-StrictMode -Version 2.0

function Write-TbxJson {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Depth = 16
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        [void](New-Item -ItemType Directory -Path $parent -Force)
    }
    $json = ($Value | ConvertTo-Json -Depth $Depth) + [Environment]::NewLine
    [IO.File]::WriteAllText($Path, $json, (New-Object Text.UTF8Encoding($false)))
}

function Get-TbxSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return [string](Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

function Invoke-TbxCapturedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    $stdoutPath = Join-Path $OutputDirectory ($Name + '.stdout.log')
    $stderrPath = Join-Path $OutputDirectory ($Name + '.stderr.log')
    $exitCode = $null
    $errorText = ''
    try {
        $lines = @(& $Action 2>&1 | ForEach-Object { [string]$_ })
        if ($null -ne $LASTEXITCODE) { $exitCode = [int]$LASTEXITCODE }
        [IO.File]::WriteAllLines($stdoutPath, $lines, (New-Object Text.UTF8Encoding($false)))
    }
    catch {
        $errorText = [string]$_.Exception.Message
        [IO.File]::WriteAllText($stdoutPath, '', (New-Object Text.UTF8Encoding($false)))
    }
    [IO.File]::WriteAllText(
        $stderrPath,
        $errorText + [Environment]::NewLine,
        (New-Object Text.UTF8Encoding($false))
    )
    return [ordered]@{ name = $Name; exit_code = $exitCode; error = $errorText }
}

function Get-TbxProcessOwner {
    param([Parameter(Mandatory = $true)][object]$Process)
    try {
        $owner = Invoke-CimMethod -InputObject $Process -MethodName GetOwner -ErrorAction Stop
        return ('{0}\{1}' -f [string]$owner.Domain, [string]$owner.User)
    }
    catch { return '' }
}

function Get-TbxRelevantProcesses {
    $rows = @()
    $all = @(Get-CimInstance -ClassName Win32_Process -ErrorAction SilentlyContinue)
    foreach ($process in $all) {
        $name = [string]$process.Name
        $path = [string]$process.ExecutablePath
        $command = [string]$process.CommandLine
        if (
            $name -notmatch '(?i)ticketbox|postgres|pg_ctl|setup|powershell|msedge' -and
            $path -notmatch '(?i)ticketbox' -and
            $command -notmatch '(?i)ticketbox'
        ) { continue }
        $rows += [ordered]@{
            process_id = [int]$process.ProcessId
            parent_process_id = [int]$process.ParentProcessId
            session_id = [int]$process.SessionId
            name = $name
            executable_path = $path
            command_line = $command
            creation_date = [string]$process.CreationDate
            owner = Get-TbxProcessOwner $process
        }
    }
    return @($rows)
}

function Get-TbxServiceEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )
    $escaped = $Name.Replace("'", "''")
    $service = Get-CimInstance -ClassName Win32_Service `
        -Filter "Name='$escaped'" -ErrorAction SilentlyContinue
    $principalName = "NT SERVICE\$Name"
    $resourceSid = ''
    try {
        $resourceSid = [string](
            New-Object Security.Principal.NTAccount($principalName)
        ).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch { $resourceSid = '' }
    $commands = @()
    if ($null -ne $service) {
        foreach ($verb in @('queryex', 'qc', 'qfailure', 'qfailureflag', 'qsidtype', 'sdshow')) {
            $capturedName = "sc-$Name-$verb"
            $commands += Invoke-TbxCapturedCommand `
                -Name $capturedName `
                -OutputDirectory $OutputDirectory `
                -Action { & sc.exe $verb $Name }.GetNewClosure()
        }
    }
    if ($null -eq $service) {
        return [ordered]@{
            name = $Name
            exists = $false
            resource_principal = $principalName
            resource_sid = $resourceSid
            commands = @($commands)
        }
    }
    $delayedAutoStart = $null
    $dependencies = @()
    $serviceRegistryPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$Name"
    if (Test-Path -LiteralPath $serviceRegistryPath) {
        $serviceRegistry = Get-ItemProperty -LiteralPath $serviceRegistryPath
        if ($null -ne $serviceRegistry.PSObject.Properties['DelayedAutostart']) {
            $delayedAutoStart = [int]$serviceRegistry.DelayedAutostart
        }
        if ($null -ne $serviceRegistry.PSObject.Properties['DependOnService']) {
            $dependencies = @($serviceRegistry.DependOnService | ForEach-Object { [string]$_ })
        }
    }
    return [ordered]@{
        name = [string]$service.Name
        exists = $true
        display_name = [string]$service.DisplayName
        state = [string]$service.State
        start_mode = [string]$service.StartMode
        start_name = [string]$service.StartName
        process_id = [int]$service.ProcessId
        path_name = [string]$service.PathName
        dependencies = @($dependencies)
        exit_code = [uint64]([uint32]$service.ExitCode)
        service_specific_exit_code = [uint64]([uint32]$service.ServiceSpecificExitCode)
        delayed_auto_start = $delayedAutoStart
        resource_principal = $principalName
        resource_sid = $resourceSid
        commands = @($commands)
    }
}

function Get-TbxRegistryEvidence {
    $result = [ordered]@{ exists = $false; values = [ordered]@{} }
    $path = 'HKLM:\Software\Ticketbox'
    if (-not (Test-Path -LiteralPath $path)) { return $result }
    $result.exists = $true
    $item = Get-ItemProperty -LiteralPath $path
    foreach ($name in @(
        'InstallDir', 'DataRoot', 'PgPort', 'BackendPort', 'Version',
        'BackendVersion', 'InstallationId', 'BuildManifestSha256',
        'BackendServiceName', 'PgServiceName'
    )) {
        if ($null -ne $item.PSObject.Properties[$name]) {
            $result.values[$name] = [string]$item.$name
        }
    }
    return $result
}

function Get-TbxIdentityEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = [ordered]@{ path = $Path; exists = $false; sha256 = ''; values = [ordered]@{} }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    $result.exists = $true
    $result.sha256 = Get-TbxSha256 $Path
    $allowed = @(
        'SCHEMA', 'STATE', 'OPERATION_ID', 'INSTALLATION_ID',
        'BUILD_MANIFEST_SHA256', 'MIGRATION_HELPER_SHA256',
        'BACKEND_VERSION_FLOOR', 'INSTALL_DIR', 'DATA_ROOT',
        'PG_PORT', 'BACKEND_PORT', 'PG_SERVICE_NAME', 'BACKEND_SERVICE_NAME'
    )
    foreach ($line in @(Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $key, $value = [string]$line -split '=', 2
        if ($allowed -contains $key) { $result.values[$key] = $value }
    }
    return $result
}

function Find-TbxJsonValue {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$Depth = 0
    )
    if ($null -eq $Value -or $Depth -gt 12) { return $null }
    foreach ($property in @($Value.PSObject.Properties)) {
        if ([string]$property.Name -ceq $Name) { return $property.Value }
        if ($property.Value -is [string] -or $property.Value -is [ValueType]) { continue }
        $nested = Find-TbxJsonValue -Value $property.Value -Name $Name -Depth ($Depth + 1)
        if ($null -ne $nested) { return $nested }
    }
    return $null
}

function Get-TbxFreshIntentEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = [ordered]@{
        path = $Path
        exists = $false
        sha256 = ''
        schema = ''
        operation_id = ''
        installation_id = ''
        release_fingerprint = ''
        build_manifest_sha256 = ''
        payload_sha256 = ''
        stage = ''
        state = ''
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    $result.exists = $true
    $result.sha256 = Get-TbxSha256 $Path
    try {
        $document = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        $payload = $document
        $payloadText = Find-TbxJsonValue -Value $document -Name 'payload_json'
        if ($payloadText -is [string] -and -not [string]::IsNullOrWhiteSpace($payloadText)) {
            $payload = [string]$payloadText | ConvertFrom-Json
        }
        $payloadSha256 = Find-TbxJsonValue -Value $document -Name 'payload_sha256'
        if ($payloadSha256 -is [string]) {
            $result.payload_sha256 = [string]$payloadSha256
        }
        foreach ($name in @(
            'schema', 'operation_id', 'installation_id', 'release_fingerprint',
            'build_manifest_sha256', 'stage', 'state'
        )) {
            $value = Find-TbxJsonValue -Value $payload -Name $name
            if ($null -ne $value -and $value -isnot [System.Array]) {
                $result[$name] = [string]$value
            }
        }
    }
    catch { $result.parse_error = [string]$_.Exception.Message }
    return $result
}

function ConvertTo-TbxRedactedObject {
    param(
        [AllowNull()][object]$Value,
        [string]$PropertyName = '',
        [int]$Depth = 0
    )
    if ($PropertyName -match '(?i)password|secret|token|pairing.?code|credential') {
        return '<redacted>'
    }
    if ($null -eq $Value -or $Value -is [string] -or $Value -is [ValueType]) {
        return $Value
    }
    if ($Depth -gt 16) { return '<depth-limit>' }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [System.Collections.IDictionary]) {
        $items = @()
        foreach ($item in $Value) {
            $items += ConvertTo-TbxRedactedObject -Value $item -Depth ($Depth + 1)
        }
        return @($items)
    }
    $result = [ordered]@{}
    foreach ($property in @($Value.PSObject.Properties)) {
        $result[[string]$property.Name] = ConvertTo-TbxRedactedObject `
            -Value $property.Value `
            -PropertyName ([string]$property.Name) `
            -Depth ($Depth + 1)
    }
    return $result
}

function Get-TbxHealthEvidence {
    param([Parameter(Mandatory = $true)][int]$Port)
    $result = [ordered]@{}
    foreach ($path in @('/api/health', '/api/health/installation')) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                -Uri ("http://127.0.0.1:{0}{1}" -f $Port, $path) -TimeoutSec 5
            $body = $null
            try { $body = [string]$response.Content | ConvertFrom-Json }
            catch { $body = [ordered]@{ raw = [string]$response.Content } }
            $result[$path] = [ordered]@{ status_code = [int]$response.StatusCode; body = $body }
        }
        catch { $result[$path] = [ordered]@{ status_code = 0; error = [string]$_.Exception.Message } }
    }
    return $result
}

function Get-TbxE2ETempRoot {
    $root = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
    if ([string]::IsNullOrWhiteSpace($root)) { throw 'No temporary root is available.' }
    return [IO.Path]::GetFullPath($root).TrimEnd('\')
}

function ConvertTo-TbxPgPassField {
    param([AllowEmptyString()][string]$Value)
    return $Value.Replace('\', '\\').Replace(':', '\:')
}

function New-TbxProtectedPgPassFile {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$UserName,
        [Parameter(Mandatory = $true)][string]$Password
    )
    $tempRoot = Get-TbxE2ETempRoot
    $directory = Join-Path $tempRoot ('ticketbox-pgpass-' + [Guid]::NewGuid().ToString('N'))
    try {
        [void](New-Item -ItemType Directory -Path $directory)
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetOwner($identity.User)
        $acl.SetAccessRuleProtection($true, $false)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $identity.User,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $directory -AclObject $acl
        $verifiedAcl = Get-Acl -LiteralPath $directory
        if (-not $verifiedAcl.AreAccessRulesProtected) {
            throw 'Temporary PostgreSQL passfile directory still inherits access rules.'
        }
        $path = Join-Path $directory 'pgpass.conf'
        $line = @(
            (ConvertTo-TbxPgPassField $HostName),
            (ConvertTo-TbxPgPassField ([string]$Port)),
            (ConvertTo-TbxPgPassField $Database),
            (ConvertTo-TbxPgPassField $UserName),
            (ConvertTo-TbxPgPassField $Password)
        ) -join ':'
        [IO.File]::WriteAllText(
            $path,
            $line + [Environment]::NewLine,
            (New-Object Text.UTF8Encoding($false))
        )
        $line = $null
        return [pscustomobject]@{ Directory = $directory; Path = $path }
    }
    catch {
        if (Test-Path -LiteralPath $directory -PathType Container) {
            Remove-Item -LiteralPath $directory -Recurse -Force
        }
        throw
    }
}

function Remove-TbxProtectedPgPassFile {
    param([Parameter(Mandatory = $true)][object]$PassFile)
    $directory = [IO.Path]::GetFullPath([string]$PassFile.Directory)
    $path = [IO.Path]::GetFullPath([string]$PassFile.Path)
    $tempRoot = Get-TbxE2ETempRoot
    if ([IO.Path]::GetDirectoryName($directory).TrimEnd('\') -ine $tempRoot -or
        -not ([IO.Path]::GetFileName($directory)).StartsWith(
            'ticketbox-pgpass-', [StringComparison]::Ordinal
        ) -or [IO.Path]::GetDirectoryName($path).TrimEnd('\') -ine $directory.TrimEnd('\') -or
        [IO.Path]::GetFileName($path) -cne 'pgpass.conf') {
        throw 'Refusing to remove an unexpected passfile path.'
    }
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        [IO.File]::WriteAllBytes($path, (New-Object byte[] 0))
        Remove-Item -LiteralPath $path -Force
    }
    if (Test-Path -LiteralPath $directory -PathType Container) {
        Remove-Item -LiteralPath $directory -Recurse -Force
    }
}

function Get-TbxDatabaseEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][int]$PgPort,
        [Parameter(Mandatory = $true)][string]$OutputDirectory
    )
    $result = [ordered]@{ available = $false; schema = [ordered]@{} }
    $pgData = Join-Path $DataRoot 'pgdata'
    $pgControl = Join-Path $InstallDir 'pg\bin\pg_controldata.exe'
    if ((Test-Path -LiteralPath $pgData -PathType Container) -and
        (Test-Path -LiteralPath $pgControl -PathType Leaf)) {
        [void](Invoke-TbxCapturedCommand -Name 'pg-controldata' -OutputDirectory $OutputDirectory `
            -Action { & $pgControl $pgData }.GetNewClosure())
        $controlText = Get-Content -LiteralPath (Join-Path $OutputDirectory 'pg-controldata.stdout.log') -Raw
        $match = [regex]::Match($controlText, '(?im)Database system identifier\s*:\s*(\d{18,20})')
        if ($match.Success) { $result.system_identifier = $match.Groups[1].Value }
    }
    $envPath = Join-Path $DataRoot 'app\.env'
    $psql = Join-Path $InstallDir 'pg\bin\psql.exe'
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $psql -PathType Leaf)) { return $result }
    $databaseUrl = $null
    $dbPassword = $null
    $passFile = $null
    $oldPassword = $env:PGPASSWORD
    $oldPassFile = $env:PGPASSFILE
    $oldSslMode = $env:PGSSLMODE
    $oldRequireAuth = $env:PGREQUIREAUTH
    try {
        $line = Get-Content -LiteralPath $envPath |
            Where-Object { $_.StartsWith('DATABASE_URL=') } | Select-Object -First 1
        if (-not $line) { throw 'DATABASE_URL is absent.' }
        $databaseUrl = $line.Substring('DATABASE_URL='.Length)
        $uri = New-Object Uri($databaseUrl)
        $userInfo = $uri.UserInfo.Split(':', 2)
        if ($userInfo.Count -ne 2) { throw 'DATABASE_URL user info is invalid.' }
        $dbUser = [Uri]::UnescapeDataString($userInfo[0])
        $dbPassword = [Uri]::UnescapeDataString($userInfo[1])
        $dbName = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
        if ($uri.Host -notin @('127.0.0.1', 'localhost')) { throw 'Database is not loopback.' }
        $port = if ($uri.Port -gt 0) { [int]$uri.Port } else { $PgPort }
        $passFile = New-TbxProtectedPgPassFile `
            -HostName '127.0.0.1' -Port $port -Database $dbName `
            -UserName $dbUser -Password $dbPassword
        $env:PGPASSWORD = $null
        $env:PGPASSFILE = [string]$passFile.Path
        $env:PGSSLMODE = 'disable'
        $env:PGREQUIREAUTH = 'scram-sha-256'
        $sql = @"
SELECT 'database=' || current_database();
SELECT 'role=' || current_user;
SELECT 'server_version_num=' || current_setting('server_version_num');
SELECT 'alembic_version=' || version_num FROM public.alembic_version;
SELECT 'public_table_count=' || COUNT(*)::text FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
SELECT 'app_meta_table=' || (to_regclass('public.app_meta') IS NOT NULL)::text;
"@
        $lines = @($sql | & $psql -X -w -A -t -v 'ON_ERROR_STOP=1' `
            -h 127.0.0.1 -p $port -U $dbUser -d $dbName 2>&1 | ForEach-Object { [string]$_ })
        $exitCode = [int]$LASTEXITCODE
        [IO.File]::WriteAllLines(
            (Join-Path $OutputDirectory 'database-schema-safe.stdout.log'),
            $lines,
            (New-Object Text.UTF8Encoding($false))
        )
        $result.available = ($exitCode -eq 0)
        $result.exit_code = $exitCode
        foreach ($outputLine in $lines) {
            $key, $value = [string]$outputLine -split '=', 2
            if ($key -in @(
                'database', 'role', 'server_version_num', 'alembic_version',
                'public_table_count', 'app_meta_table'
            )) { $result.schema[$key] = $value }
        }
    }
    catch { $result.error = [string]$_.Exception.Message }
    finally {
        $env:PGPASSWORD = $oldPassword
        $env:PGPASSFILE = $oldPassFile
        $env:PGSSLMODE = $oldSslMode
        $env:PGREQUIREAUTH = $oldRequireAuth
        if ($null -ne $passFile) { Remove-TbxProtectedPgPassFile $passFile }
        $dbPassword = $null
        $databaseUrl = $null
    }
    return $result
}

function Get-TbxInstallerStateInventory {
    $root = Join-Path $env:CommonProgramFiles 'Ticketbox\installer-state'
    $rows = @()
    if (Test-Path -LiteralPath $root -PathType Container) {
        foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Force)) {
            $rows += [ordered]@{
                name = [string]$file.Name
                length = [int64]$file.Length
                sha256 = Get-TbxSha256 $file.FullName
                content_copied = $false
            }
        }
    }
    return @($rows)
}

function Copy-TbxLogTreeEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $receipt = [ordered]@{
        source = $Source
        destination = $Destination
        source_exists = Test-Path -LiteralPath $Source -PathType Container
        copied = $false
        file_count = 0
        error = ''
    }
    if (-not $receipt.source_exists) { return $receipt }
    try {
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
        $receipt.copied = $true
        $receipt.file_count = @(
            Get-ChildItem -LiteralPath $Destination -File -Recurse -Force
        ).Count
    }
    catch { $receipt.error = [string]$_.Exception.Message }
    return $receipt
}

function Capture-TbxState {
    param(
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][string]$Phase,
        [switch]$IncludeProductLogs
    )
    [void](New-Item -ItemType Directory -Path $OutputDirectory -Force)
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $metadata = [ordered]@{
        phase = $Phase
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        computer_name = $env:COMPUTERNAME
        user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        user_interactive = [Environment]::UserInteractive
        process_session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
        powershell = $PSVersionTable.PSVersion.ToString()
        runner_image = $env:ImageOS
        runner_image_version = $env:ImageVersion
        os = [ordered]@{
            caption = [string]$os.Caption
            version = [string]$os.Version
            build_number = [string]$os.BuildNumber
            last_boot_up_time = [string]$os.LastBootUpTime
        }
    }
    $services = @(
        Get-TbxServiceEvidence -Name 'TicketboxPg' -OutputDirectory $OutputDirectory
        Get-TbxServiceEvidence -Name 'TicketboxBackend' -OutputDirectory $OutputDirectory
    )
    $registry = Get-TbxRegistryEvidence
    $roots = @()
    foreach ($path in @(
        (Join-Path $env:ProgramFiles 'Ticketbox'),
        (Join-Path $env:ProgramData 'Ticketbox'),
        (Join-Path $env:CommonProgramFiles 'Ticketbox')
    )) {
        $roots += [ordered]@{
            path = $path
            exists = Test-Path -LiteralPath $path
            entry_count = if (Test-Path -LiteralPath $path -PathType Container) {
                @(Get-ChildItem -LiteralPath $path -Force -Recurse -ErrorAction SilentlyContinue).Count
            } else { 0 }
        }
    }
    $dataRoot = if ($registry.exists) { [string]$registry.values.DataRoot } else {
        Join-Path $env:ProgramData 'Ticketbox'
    }
    $installDir = if ($registry.exists) { [string]$registry.values.InstallDir } else {
        Join-Path $env:ProgramFiles 'Ticketbox'
    }
    $ready = Get-TbxIdentityEvidence (Join-Path $dataRoot '.ticketbox-installation-identity')
    $pending = Get-TbxIdentityEvidence (Join-Path $dataRoot '.ticketbox-installation-identity.pending')
    $intentPath = Join-Path $env:CommonProgramFiles 'Ticketbox\c07-lifecycle\c07-fresh-bootstrap-intent.json'
    $freshIntent = Get-TbxFreshIntentEvidence $intentPath
    $receiptPath = Join-Path $env:CommonProgramFiles 'Ticketbox\installer-lifecycle-receipt.json'
    $receipt = [ordered]@{ exists = $false; sha256 = ''; document = $null }
    if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
        $receipt.exists = $true
        $receipt.sha256 = Get-TbxSha256 $receiptPath
        try {
            $rawReceipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $receipt.document = ConvertTo-TbxRedactedObject $rawReceipt
        }
        catch { $receipt.parse_error = [string]$_.Exception.Message }
    }
    $health = [ordered]@{}
    $database = [ordered]@{ available = $false }
    if ($registry.exists) {
        $backendPort = [int]$registry.values.BackendPort
        $pgPort = [int]$registry.values.PgPort
        if ($backendPort -gt 0) { $health = Get-TbxHealthEvidence -Port $backendPort }
        if ($pgPort -gt 0) {
            $database = Get-TbxDatabaseEvidence -DataRoot $dataRoot -InstallDir $installDir `
                -PgPort $pgPort -OutputDirectory $OutputDirectory
        }
    }
    $artifacts = @()
    foreach ($path in @(
        (Join-Path $installDir 'installer\windows-release-config.json'),
        (Join-Path $installDir 'installer\BUILD_PROVENANCE.json'),
        (Join-Path $installDir 'program\ticketbox-backend\BUILD_PROVENANCE.json'),
        (Join-Path $installDir 'program\ticketbox-backend\ticketbox-backend.exe'),
        (Join-Path $installDir 'program\ticketbox-backend\ticketbox-c07-migrator.exe'),
        (Join-Path $installDir 'manager\BUILD_PROVENANCE.json'),
        (Join-Path $installDir 'manager\ticketbox-manager.exe'),
        (Join-Path $installDir 'shawl\shawl.exe'),
        (Join-Path $installDir 'pg\bin\pg_ctl.exe'),
        (Join-Path $installDir 'pg\bin\postgres.exe'),
        (Join-Path $installDir 'pg\bin\psql.exe')
    )) {
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        $artifacts += [ordered]@{
            path = $path
            exists = $exists
            length = if ($exists) { [int64](Get-Item -LiteralPath $path).Length } else { 0 }
            sha256 = if ($exists) { Get-TbxSha256 $path } else { '' }
        }
    }
    $state = [ordered]@{
        schema = 'ticketbox-clean-e2e-state-v1'
        metadata = $metadata
        services = $services
        processes = @(Get-TbxRelevantProcesses)
        registry = $registry
        roots = $roots
        ready_identity = $ready
        pending_identity = $pending
        fresh_intent = $freshIntent
        lifecycle_receipt = $receipt
        installer_state_inventory = @(Get-TbxInstallerStateInventory)
        health = $health
        database = $database
        installed_artifacts = $artifacts
    }
    if ($IncludeProductLogs) {
        $state['log_capture'] = @(
            Copy-TbxLogTreeEvidence `
                -Source (Join-Path $dataRoot 'logs') `
                -Destination (Join-Path $OutputDirectory 'product-logs')
            Copy-TbxLogTreeEvidence `
                -Source (Join-Path $env:CommonProgramFiles 'Ticketbox\installer-logs') `
                -Destination (Join-Path $OutputDirectory 'installer-logs')
        )
    }
    Write-TbxJson -Value $state -Path (Join-Path $OutputDirectory 'STATE.json') -Depth 24
    return $state
}

function Assert-TbxZeroBaseline {
    param(
        [Parameter(Mandatory = $true)][object]$State,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $violations = @()
    foreach ($service in @($State.services)) {
        if ([bool]$service.exists) { $violations += "service:$($service.name)" }
    }
    foreach ($root in @($State.roots)) {
        if ([bool]$root.exists) { $violations += "root:$($root.path)" }
    }
    if ([bool]$State.registry.exists) { $violations += 'registry:HKLM/Software/Ticketbox' }
    if ([bool]$State.ready_identity.exists) { $violations += 'ready-identity' }
    if ([bool]$State.pending_identity.exists) { $violations += 'pending-identity' }
    $receipt = [ordered]@{
        schema = 'ticketbox-zero-install-baseline-v1'
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        violation_count = $violations.Count
        violations = @($violations)
    }
    Write-TbxJson -Value $receipt -Path $OutputPath
    if ($violations.Count -ne 0) { throw 'Clean-runner zero-install baseline failed.' }
    return $receipt
}

function Assert-TbxAcceptedArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactRoot,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $expected = [ordered]@{
        'BUILD_COMPLETE.json' = '84180CF65EFFF5B1E5DD0648B800152FD41DA32D5BCC411FC211B1986358EC2D'
        'BUILD_PROVENANCE.json' = 'D2FAD5223D0ECEC7D363854A83841CF62635E5693DEBF3A5FC9D2BE5682B1701'
        'Ticketbox-Setup-1.2.0.exe' = '5A66B8259CAE1E39814FC693D70FCFAEE58D06CE4CBA9005BEC8CB28E936B28F'
        'Ticketbox-Setup-1.2.0.exe.sha256' = 'BC7364B0C5D7D6EFAC98F0424C50A56C986642FDF942827A921127FF9659EAC5'
    }
    $actualNames = @(
        Get-ChildItem -LiteralPath $ArtifactRoot -Force |
            ForEach-Object { [string]$_.Name } | Sort-Object
    )
    $expectedNames = @($expected.Keys | Sort-Object)
    if (($actualNames -join "`n") -cne ($expectedNames -join "`n")) {
        throw 'Downloaded publish unit has an unexpected file set.'
    }
    $files = @()
    foreach ($name in $expected.Keys) {
        $path = Join-Path $ArtifactRoot $name
        $hash = Get-TbxSha256 $path
        if ($hash -cne [string]$expected[$name]) { throw "Accepted artifact hash mismatch: $name" }
        $files += [ordered]@{ name = $name; length = [int64](Get-Item $path).Length; sha256 = $hash }
    }
    $exePath = Join-Path $ArtifactRoot 'Ticketbox-Setup-1.2.0.exe'
    if ([int64](Get-Item -LiteralPath $exePath).Length -ne 105148499) {
        throw 'Accepted installer length mismatch.'
    }
    $complete = Get-Content -LiteralPath (Join-Path $ArtifactRoot 'BUILD_COMPLETE.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
    $provenance = Get-Content -LiteralPath (Join-Path $ArtifactRoot 'BUILD_PROVENANCE.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$complete.installer_sha256 -cne $expected['Ticketbox-Setup-1.2.0.exe'].ToLowerInvariant() -or
        [string]$complete.provenance_sha256 -cne $expected['BUILD_PROVENANCE.json'].ToLowerInvariant()) {
        throw 'BUILD_COMPLETE does not bind the accepted bytes.'
    }
    if ([string]$provenance.git.commit -cne '826521709c5220ec00987625b01f80117759c9aa' -or
        [bool]$provenance.git.dirty) { throw 'Provenance checkout identity mismatch.' }
    $receipt = [ordered]@{
        schema = 'ticketbox-accepted-artifact-verification-v1'
        verified_at_utc = [DateTime]::UtcNow.ToString('o')
        artifact_id = 9043258694
        source_run_id = 31331708842
        source_exact_head = '7eb77f1dffed743dc84332539cb696dbe539cd41'
        qualification_checkout = '826521709c5220ec00987625b01f80117759c9aa'
        source_tree = '7fd19279d5eb72a31b395a5ef634d03484f2689c'
        files = $files
    }
    Write-TbxJson -Value $receipt -Path $OutputPath
    (Get-Item -LiteralPath $exePath).IsReadOnly = $true
    return $receipt
}

function Protect-TbxTextEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string[]]$Secrets = @()
    )
    $textExtensions = @('.json', '.log', '.txt', '.xml', '.md', '.yml', '.yaml', '.ps1')
    $redactionRules = @(
        [pscustomobject]@{
            pattern = '(?im)((?:DATABASE_URL|PGPASSWORD|HTTP_BOOTSTRAP_SECRET|RUNTIME_PASSWORD|MIGRATOR_PASSWORD|OWNER_BOOTSTRAP_SECRET|BOOTSTRAP_SECRET)\s*[=:]\s*)(?!<redacted>)[^\r\n]+'
            replacement = '$1<redacted>'
        },
        [pscustomobject]@{
            pattern = '(?im)("[^"]*(?:password|secret|token|credential|pairing[_-]?code)[^"]*"\s*:\s*)(?!"<redacted>")(?:"(?:(?:\\.)|[^"\\])*"|[^,\r\n}\]]+)'
            replacement = '$1"<redacted>"'
        },
        [pscustomobject]@{
            pattern = '(?i)((?:--(?:db-)?password|--(?:bootstrap-)?secret|--token)\s+)(?!<redacted>)(?:"[^"]*"|\S+)'
            replacement = '$1<redacted>'
        },
        [pscustomobject]@{
            pattern = '(?i)(Authorization\s*:\s*Bearer\s+)(?!<redacted>)\S+'
            replacement = '$1<redacted>'
        },
        [pscustomobject]@{
            pattern = '(?i)(postgres(?:ql)?(?:\+[a-z0-9_.-]+)?://[^:\s/@]+:)(?!<redacted>)[^@\s/]+(@)'
            replacement = '$1<redacted>$2'
        }
    )
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force)) {
        if ($textExtensions -notcontains [string]$file.Extension.ToLowerInvariant()) { continue }
        $text = [IO.File]::ReadAllText($file.FullName)
        $changed = $false
        foreach ($secret in @($Secrets)) {
            if ([string]::IsNullOrEmpty($secret)) { continue }
            if ($text.Contains($secret)) {
                $text = $text.Replace($secret, '<redacted-transient-secret>')
                $changed = $true
            }
        }
        foreach ($rule in $redactionRules) {
            $redacted = [regex]::Replace($text, [string]$rule.pattern, [string]$rule.replacement)
            if ($redacted -cne $text) {
                $text = $redacted
                $changed = $true
            }
        }
        if ($changed) {
            [IO.File]::WriteAllText($file.FullName, $text, (New-Object Text.UTF8Encoding($false)))
        }
    }
    foreach ($secret in @($Secrets)) {
        if ([string]::IsNullOrEmpty($secret)) { continue }
        foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force)) {
            if ($textExtensions -notcontains [string]$file.Extension.ToLowerInvariant()) { continue }
            if ([IO.File]::ReadAllText($file.FullName).Contains($secret)) {
                throw 'Transient secret remains in text evidence after redaction.'
            }
        }
    }
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force)) {
        if ($textExtensions -notcontains [string]$file.Extension.ToLowerInvariant()) { continue }
        $text = [IO.File]::ReadAllText($file.FullName)
        foreach ($rule in $redactionRules) {
            if ([regex]::IsMatch($text, [string]$rule.pattern)) {
                throw "Sensitive value remains in text evidence: $($file.Name)"
            }
        }
    }
}

function Write-TbxEvidenceManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $resolvedOutput = [IO.Path]::GetFullPath($OutputPath)
    $files = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName)) {
        if ([IO.Path]::GetFullPath($file.FullName) -ceq $resolvedOutput) { continue }
        $relative = $file.FullName.Substring([IO.Path]::GetFullPath($Root).Length).TrimStart('\')
        $files += [ordered]@{
            path = $relative.Replace('\', '/')
            length = [int64]$file.Length
            sha256 = Get-TbxSha256 $file.FullName
        }
    }
    Write-TbxJson -Value ([ordered]@{
        schema = 'ticketbox-clean-e2e-evidence-manifest-v1'
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        file_count = $files.Count
        files = $files
    }) -Path $OutputPath -Depth 8
}
