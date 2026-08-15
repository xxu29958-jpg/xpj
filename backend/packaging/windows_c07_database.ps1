#Requires -Version 5.1

<#
.SYNOPSIS
  Host-authoritative PostgreSQL role and ACL policy adapter for C07.
.DESCRIPTION
  This file is dot-sourced only after the Windows service, installation-safety,
  database-safety, and bundled-database helpers. It deliberately has no
  caller-supplied DATABASE_URL, PGDATA, port, or PostgreSQL service identity.
#>

$script:TicketboxC07PostgresServiceName = "TicketboxPg"
$script:TicketboxC07DatabaseName = "ticketbox"
$script:TicketboxC07LegacyRuntimeRole = "ticketbox"
$script:TicketboxC07OwnerRole = "ticketbox_owner"
$script:TicketboxC07MigratorRole = "ticketbox_migrator"
$script:TicketboxC07RuntimeRole = "ticketbox_runtime"
$script:TicketboxC07RestorePrefix = "ticketbox_c07_restore_"
$script:TicketboxC07RestoreIdentitySchema = "ticketbox-c07-restore-db-v2"
$script:TicketboxC07RoleMarkerSchema = "ticketbox-c07-role-v2"
$script:TicketboxC07DatabaseMarkerSchema = "ticketbox-c07-database-v2"
$script:TicketboxC07RestoreMarkerSchema = "ticketbox-c07-restore-database-v3"
$script:TicketboxC07LegacyRestoreMarkerSchema =
    "ticketbox-c07-restore-database-v2"
$script:TicketboxC07MigrationEvidenceSchema =
    "ticketbox-c07-migration-evidence-v1"
$script:TicketboxC07ResourceMigrationEvidenceSchema =
    "ticketbox-c07-migration-evidence-v2"
$script:TicketboxC07RecoveryRestoreCreateIntentSchema =
    "ticketbox-c07-recovery-restore-create-intent-v1"
$script:TicketboxC07RecoveryIntegrityScope = "acl_hash_only"

$postgresqlHostOperations = Join-Path `
    (Split-Path -Parent $MyInvocation.MyCommand.Path) `
    "windows_pg_recovery_tools.ps1"
if (-not (Get-Command `
    "Invoke-TicketboxPostgresqlHostPsqlWithProtectedPassfile" `
    -CommandType Function `
    -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path -LiteralPath $postgresqlHostOperations -PathType Leaf)) {
        throw "缺少通用 PostgreSQL host operations：$postgresqlHostOperations"
    }
    . $postgresqlHostOperations
}

$postgresqlDatabaseCatalog = Join-Path `
    (Split-Path -Parent $MyInvocation.MyCommand.Path) `
    "windows_postgresql_database_catalog.ps1"
if (-not (Get-Command `
    "Get-TicketboxPostgresqlDatabaseCatalogObservation" `
    -CommandType Function `
    -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path -LiteralPath $postgresqlDatabaseCatalog -PathType Leaf)) {
        throw "缺少通用 PostgreSQL database-catalog 观察器：$postgresqlDatabaseCatalog"
    }
    . $postgresqlDatabaseCatalog
}

# Runtime DML is intentionally fail-closed. New tables do not inherit runtime
# privileges: a release that adds a real runtime consumer must review and add
# the table here. Migration/receipt/authority/audit objects live in separate
# narrow lists below and never inherit the business-table CRUD grant.
$script:TicketboxC07RuntimeBusinessTables = @(
    "accounts",
    "ai_member_anon_map",
    "ai_merchant_anon_map",
    "ai_transaction_temp_id_map",
    "algorithm_decisions",
    "api_idempotency_keys",
    "auth_tokens",
    "background_tasks",
    "bill_split_invitations",
    "bootstrap_secret_consumptions",
    "budget_advisor_quota_locks",
    "budget_categories",
    "budgets",
    "category_preferences",
    "category_rules",
    "csv_import_batches",
    "csv_import_rows",
    "dashboard_card_preferences",
    "debt_goal_links",
    "debts",
    "desktop_activation_attempts",
    "device_enrollment_attempts",
    "devices",
    "duplicate_ignores",
    "exchange_rates",
    "expense_items",
    "expense_splits",
    "expense_tags",
    "expenses",
    "fx_rates",
    "goals",
    "invitations",
    "ledger_members",
    "ledgers",
    "member_repayment_proposals",
    "merchant_aliases",
    "merchant_catalog",
    "monthly_income_plans",
    "pairing_attempt_failures",
    "pairing_codes",
    "recurring_items",
    "repayment_drafts",
    "rule_application_batches",
    "rule_application_changes",
    "scheduler_leases",
    "session_refresh_attempts",
    "tag_mutation_undo_groups",
    "tag_mutation_undo_items",
    "tags",
    "upload_link_daily_usage",
    "upload_link_remote_attempts",
    "upload_links",
    "user_ui_preferences"
)
$script:TicketboxC07RuntimeFinancialAppendTables = @(
    "debt_adjustments",
    "debt_forgivenesses",
    "debt_voids",
    "repayment_voids",
    "repayments"
)
$script:TicketboxC07RuntimeAuthorityTables = @("app_meta")
$script:TicketboxC07RuntimeMigrationAppendTables = @("schema_migrations")
$script:TicketboxC07RuntimeAuditAppendTables = @("ledger_audit_logs")
$script:TicketboxC07RuntimeAuditMutableTables = @("budget_advisor_audit_logs")
$script:TicketboxC07RuntimeRetentionFactTables = @(
    "ledger_learning_events",
    "ocr_facts"
)
$script:TicketboxC07RuntimeReadOnlyTables = @("alembic_version")
$script:TicketboxManagedSchemaCurrencyBindingTables = @(
    "installation_currency_bindings"
)
$script:TicketboxManagedSchemaAuthorityTables = @(
    "installation_idempotency_keys"
)
$script:TicketboxManagedSchemaAuditInsertTables = @(
    "installation_currency_audit_log"
)

function ConvertTo-TicketboxC07SqlLiteral {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value)

    return "'" + $Value.Replace("'", "''") + "'"
}

function ConvertTo-TicketboxC07SqlTextArray {
    param([Parameter(Mandatory = $true)][string[]]$Values)

    $items = @(
        $Values |
            ForEach-Object {
                if ($_ -cnotmatch '^[a-z][a-z0-9_]{0,62}$') {
                    throw "C07 PostgreSQL object allowlist 含非法 identifier。"
                }
                ConvertTo-TicketboxC07SqlLiteral $_
            }
    )
    return "ARRAY[" + ($items -join ", ") + "]::text[]"
}

function Get-TicketboxC07DatabaseTextSha256 {
    param([AllowEmptyString()][Parameter(Mandatory = $true)][string]$Text)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Assert-TicketboxC07DatabaseSha256 {
    param(
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch '^[0-9a-f]{64}$') {
        throw "$Label 不是 canonical SHA-256。"
    }
}

function Assert-TicketboxC07HostSha256 {
    param(
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch '^[0-9A-F]{64}$') {
        throw "$Label 不是 canonical host SHA-256。"
    }
}

function Assert-TicketboxC07DatabaseRequiredProperties {
    param(
        [AllowNull()][Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label,
        [switch]$Exact
    )

    if ($null -eq $Value) {
        throw "$Label 缺失。"
    }
    $actual = @($Value.PSObject.Properties.Name)
    foreach ($name in $Names) {
        if ($name -cnotin $actual) {
            throw "$Label 缺少字段：$name。"
        }
    }
    if (
        $Exact -and
        (
            $actual.Count -ne $Names.Count -or
            @($actual | Where-Object { $_ -cnotin $Names }).Count -ne 0
        )
    ) {
        throw "$Label 含未登记字段。"
    }
}

function Assert-TicketboxC07SecureString {
    param(
        [AllowNull()][Security.SecureString]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($null -eq $Value -or $Value.Length -lt 32) {
        throw "$Label 缺失或不足 32 个字符；拒绝数据库 mutation。"
    }
}

function Invoke-TicketboxC07WithPlainSecret {
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

function ConvertTo-TicketboxC07ScramVerifier {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [byte[]]$Salt
    )

    if ($null -eq $Salt) {
        $Salt = New-Object byte[] 16
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($Salt) }
        finally { $random.Dispose() }
    }
    if ($Salt.Length -ne 16) {
        throw "SCRAM salt 必须正好为 16 bytes。"
    }

    $saltCopy = New-Object byte[] $Salt.Length
    [Array]::Copy($Salt, $saltCopy, $Salt.Length)
    return Invoke-TicketboxC07WithPlainSecret -Secret $Password -Action {
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
            foreach ($buffer in @($saltedPassword, $clientKey, $storedKey, $serverKey)) {
                if ($null -ne $buffer) { [Array]::Clear($buffer, 0, $buffer.Length) }
            }
        }
    }
}

function Resolve-TicketboxC07DatabaseHostAuthority {
    if (
        $null -eq (Get-Command `
            -Name Resolve-TicketboxPostgresServiceHostAuthority `
            -CommandType Function `
            -ErrorAction SilentlyContinue)
    ) {
        throw "C07 缺少通用 PostgreSQL SCM 宿主权威解析器。"
    }
    if (
        [string]::IsNullOrWhiteSpace([string]$DataRoot) -or
        [string]::IsNullOrWhiteSpace([string]$InstallDir) -or
        [string]::IsNullOrWhiteSpace([string]$BackendServiceName)
    ) {
        throw "C07 PostgreSQL 宿主权威缺少安装路径或服务合同。"
    }
    $targetConfigVariable = Get-Variable `
        -Name ReleaseConfig `
        -Scope Script `
        -ErrorAction SilentlyContinue
    if ($null -eq $targetConfigVariable -or $null -eq $targetConfigVariable.Value) {
        throw "C07 PostgreSQL 宿主权威缺少通用 Windows release config。"
    }
    $targetConfig = $targetConfigVariable.Value
    $installedConfigVariable = Get-Variable `
        -Name PreviousReleaseConfig `
        -Scope Script `
        -ErrorAction SilentlyContinue
    $installedConfig = if (
        $null -ne $installedConfigVariable -and
        $null -ne $installedConfigVariable.Value
    ) {
        $installedConfigVariable.Value
    }
    else {
        $targetConfig
    }
    $serviceIdentityShapes = @(Get-TicketboxReleaseServiceIdentityShapes `
        -InstalledConfig $installedConfig `
        -TargetConfig $targetConfig `
        -ServiceName $script:TicketboxC07PostgresServiceName)
    $authority = Resolve-TicketboxPostgresServiceHostAuthority `
        -ServiceName $script:TicketboxC07PostgresServiceName `
        -ExpectedPgCtlPath (Join-Path $InstallDir "pg\bin\pg_ctl.exe") `
        -DataRoot $DataRoot `
        -InstallDir $InstallDir `
        -BackendServiceName $BackendServiceName `
        -AllowedServiceIdentityShapes $serviceIdentityShapes
    return [pscustomobject]@{
        Schema = "ticketbox-c07-host-db-authority-v1"
        ServiceName = [string]$authority.ServiceName
        ServiceProcessId = [int]$authority.ServiceProcessId
        PostmasterProcessId = [int]$authority.PostmasterProcessId
        PgCtlPath = [string]$authority.PgCtlPath
        PsqlPath = [string]$authority.PsqlPath
        PgData = [string]$authority.PgData
        PhysicalPgData = [string]$authority.PhysicalPgData
        Port = [int]$authority.Port
        UsesRuntimeBinding = [bool]$authority.UsesRuntimeBinding
        DataVolumeIdentity = [string]$authority.DataVolumeIdentity
    }
}


function Assert-TicketboxC07SqlTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role
    )

    $allowedRoles = @(
        "postgres",
        $script:TicketboxC07LegacyRuntimeRole,
        $script:TicketboxC07OwnerRole,
        $script:TicketboxC07MigratorRole,
        $script:TicketboxC07RuntimeRole
    )
    if ($Role -cnotin $allowedRoles) {
        throw "C07 拒绝未登记的 PostgreSQL role。"
    }
    $isRestore = $Database -cmatch (
        "^" + [regex]::Escape($script:TicketboxC07RestorePrefix) + "[0-9a-f]{32}$"
    )
    if ($Database -cnotin @("postgres", $script:TicketboxC07DatabaseName) -and -not $isRestore) {
        throw "C07 拒绝任意 PostgreSQL database target。"
    }
}

function New-TicketboxC07LocalDatabaseUrl {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role
    )

    Assert-TicketboxC07SqlTarget -Database $Database -Role $Role
    if ($Authority.Schema -cne "ticketbox-c07-host-db-authority-v1") {
        throw "C07 host database authority schema 无效。"
    }
    $encodedRole = [Uri]::EscapeDataString($Role)
    $encodedDatabase = [Uri]::EscapeDataString($Database)
    return "postgresql://${encodedRole}@127.0.0.1:$($Authority.Port)/" +
        "${encodedDatabase}?require_auth=scram-sha-256"
}

function Invoke-TicketboxC07SqlResult {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    $effectiveTimeoutMilliseconds = $TimeoutMilliseconds
    if (
        $null -ne (
            Get-Command `
                -Name "Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds" `
                -CommandType Function `
                -ErrorAction SilentlyContinue
        )
    ) {
        $effectiveTimeoutMilliseconds =
            Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                -MaximumMilliseconds $TimeoutMilliseconds `
                -Label $Label
    }
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $Authority `
        -Database $Database `
        -Role $Role
    return Invoke-TicketboxC07WithPlainSecret -Secret $Password -Action {
        param([string]$PlainPassword)

        return Invoke-TicketboxWithPgPassFile `
            -DatabaseUrl $databaseUrl `
            -Password $PlainPassword `
            -Action {
                param([string]$ProtectedDatabaseUrl)

                $commandResult = Invoke-TicketboxBoundedNativeProcess `
                    -FilePath $Authority.PsqlPath `
                    -Arguments @(
                        "--no-psqlrc",
                        "--no-password",
                        "--quiet",
                        "--tuples-only",
                        "--no-align",
                        "--set", "ON_ERROR_STOP=1",
                        "--dbname", $ProtectedDatabaseUrl
                    ) `
                    -StandardInputText ($Sql + "`n") `
                    -TimeoutMilliseconds $effectiveTimeoutMilliseconds `
                    -Label $Label
                return [pscustomobject]@{
                    ExitCode = [int]$commandResult.ExitCode
                    Output = [string]$commandResult.StandardOutput
                }
            }
    }
}

function New-TicketboxC07DatabaseClassifiedFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [Parameter(Mandatory = $true)][string]$FailureCode,
        [Exception]$InnerException
    )
    if ($FailureCode -cnotmatch "^[a-z0-9_]{1,64}$") {
        throw "C07 database classified failure code 无效。"
    }
    $failure = if ($null -eq $InnerException) {
        [InvalidOperationException]::new($Message)
    }
    else {
        [InvalidOperationException]::new($Message, $InnerException)
    }
    $failure.Data["TicketboxC07FailureClass"] = "invariant"
    $failure.Data["TicketboxC07FailureCode"] = $FailureCode
    return $failure
}

function Invoke-TicketboxC07Sql {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][Security.SecureString]$Password,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateRange(1000, 3600000)][int]$TimeoutMilliseconds = 600000
    )

    $result = Invoke-TicketboxC07SqlResult @PSBoundParameters
    if ($result.ExitCode -ne 0) {
        # psql exit=3 only means ON_ERROR_STOP observed a script error. It
        # does not distinguish invariant violations from timeout, deadlock,
        # cancellation, or resource failures, so every non-zero native result
        # remains transient unless a successful structured query says false.
        throw "$Label 失败（exit=$($result.ExitCode)）；原生输出已抑制。"
    }
    return ([string]$result.Output).Trim()
}

function Assert-TicketboxC07LiveHostConnection {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $timeoutMilliseconds = 600000
    if (
        $null -ne (
            Get-Command `
                -Name "Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds" `
                -CommandType Function `
                -ErrorAction SilentlyContinue
        )
    ) {
        $timeoutMilliseconds =
            Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                -MaximumMilliseconds 600000 `
                -Label "C07 live PostgreSQL authority validation"
    }
    $url = New-TicketboxC07LocalDatabaseUrl `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres"
    Invoke-TicketboxC07WithPlainSecret -Secret $SuperuserPassword -Action {
        param([string]$PlainPassword)

        Assert-TicketboxConnectedPostgresDataRoot `
            -PsqlPath $Authority.PsqlPath `
            -DatabaseUrl $url `
            -ExpectedDataRoot $Authority.PgData `
            -ExpectedPort $Authority.Port `
            -Password $PlainPassword `
            -TimeoutMilliseconds $timeoutMilliseconds
    } | Out-Null
}

function ConvertFrom-TicketboxC07SingleRow {
    param(
        [AllowEmptyString()][string]$Output,
        [Parameter(Mandatory = $true)][ValidateRange(1, 32)][int]$FieldCount,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $lines = @(
        $Output -split "`r?`n" |
            ForEach-Object { [string]$_ } |
            Where-Object { $_.Trim().Length -gt 0 }
    )
    if ($lines.Count -ne 1) {
        throw "$Label 未返回唯一结果行。"
    }
    $fields = @($lines[0].Split([char]9))
    if ($fields.Count -ne $FieldCount) {
        throw "$Label 返回字段数量异常。"
    }
    return $fields
}

function Get-TicketboxC07DatabaseCatalogObservation {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$Database
    )

    Assert-TicketboxC07SqlTarget -Database $Database -Role "postgres"
    $timeoutMilliseconds = 30000
    if (
        $null -ne (
            Get-Command `
                -Name "Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds" `
                -CommandType Function `
                -ErrorAction SilentlyContinue
        )
    ) {
        $timeoutMilliseconds =
            Get-TicketboxC07ActiveMaintenanceTimeoutMilliseconds `
                -MaximumMilliseconds $timeoutMilliseconds `
                -Label "C07 database catalog observation"
    }
    $databaseUrl = New-TicketboxC07LocalDatabaseUrl `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres"
    return Invoke-TicketboxC07WithPlainSecret `
        -Secret $SuperuserPassword `
        -Action {
            param([string]$PlainPassword)

            $observation =
                Get-TicketboxPostgresqlDatabaseCatalogObservation `
                    -PsqlPath $Authority.PsqlPath `
                    -DatabaseUrl $databaseUrl `
                    -Password $PlainPassword `
                    -TargetDatabase $Database `
                    -TimeoutMilliseconds $timeoutMilliseconds
            return [pscustomobject][ordered]@{
                ClusterSystemIdentifier =
                    [string]$observation.ClusterSystemIdentifier
                Database = [string]$observation.Database
                DatabaseOid = [uint32]$observation.DatabaseOid
                OwnerRoleOid = [uint32]$observation.OwnerRoleOid
                AllowsConnections = [bool]$observation.AllowsConnections
                Marker = [string]$observation.Comment
                Exists = [bool]$observation.Exists
            }
    }
}

function Get-TicketboxC07RoleBootstrapIdentity {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [switch]$AllowAbsent
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 role bootstrap identity inspect" `
        -Sql @"
SELECT
    (
        (owner_role.oid IS NOT NULL)::int +
        (migrator_role.oid IS NOT NULL)::int +
        (runtime_role.oid IS NOT NULL)::int
    )::text || E'\t' ||
    COALESCE(owner_role.oid::text, '') || E'\t' ||
    COALESCE(shobj_description(owner_role.oid, 'pg_authid'), '') || E'\t' ||
    COALESCE(migrator_role.oid::text, '') || E'\t' ||
    COALESCE(shobj_description(migrator_role.oid, 'pg_authid'), '') || E'\t' ||
    COALESCE(runtime_role.oid::text, '') || E'\t' ||
    COALESCE(shobj_description(runtime_role.oid, 'pg_authid'), '') || E'\t' ||
    'TBX_ROLE_IDENTITY_END'
FROM (SELECT 1) AS singleton
LEFT JOIN pg_roles AS owner_role
  ON owner_role.rolname = '$script:TicketboxC07OwnerRole'
LEFT JOIN pg_roles AS migrator_role
  ON migrator_role.rolname = '$script:TicketboxC07MigratorRole'
LEFT JOIN pg_roles AS runtime_role
  ON runtime_role.rolname = '$script:TicketboxC07RuntimeRole';
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 8 `
        -Label "C07 role bootstrap identity inspect"
    if ($fields[7] -cne "TBX_ROLE_IDENTITY_END") {
        throw "C07 role bootstrap identity 尾哨兵无效。"
    }
    $present = 0
    if (-not [int]::TryParse($fields[0], [ref]$present) -or $present -notin 0..3) {
        throw "C07 target role presence evidence 无效。"
    }
    if ($present -eq 0) {
        if (-not $AllowAbsent) {
            throw "C07 target roles 尚未建立。"
        }
        return [pscustomobject]@{ Exists = $false }
    }
    if ($present -ne 3) {
        throw "C07 target roles 只存在一部分；拒绝 mutation。"
    }
    $oids = @([uint32]0, [uint32]0, [uint32]0)
    foreach ($index in 0..2) {
        $parsedOid = [uint32]0
        if (
            -not [uint32]::TryParse($fields[1 + ($index * 2)], [ref]$parsedOid) -or
            $parsedOid -lt 1
        ) {
            throw "C07 target role OID 无效。"
        }
        $oids[$index] = $parsedOid
    }
    $roleNames = @(
        $script:TicketboxC07OwnerRole,
        $script:TicketboxC07MigratorRole,
        $script:TicketboxC07RuntimeRole
    )
    foreach ($index in 0..2) {
        $expected = (
            "$script:TicketboxC07RoleMarkerSchema|" +
            "$($operation.ToString('D'))|$Mode|roles_created|$($oids[$index])"
        )
        if ($fields[2 + ($index * 2)] -cne $expected) {
            throw "C07 role $($roleNames[$index]) 不属于本 operation/phase。"
        }
    }
    return [pscustomobject]@{
        Exists = $true
        OwnerRoleOid = $oids[0]
        MigratorRoleOid = $oids[1]
        RuntimeRoleOid = $oids[2]
    }
}

function Get-TicketboxC07RoleOid {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$Role,
        [switch]$AllowAbsent
    )

    Assert-TicketboxC07SqlTarget -Database "postgres" -Role $Role
    $roleLiteral = ConvertTo-TicketboxC07SqlLiteral $Role
    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 role OID inspect" `
        -Sql @"
SELECT
    (role.oid IS NOT NULL)::int::text || E'\t' ||
    COALESCE(role.oid::text, '')
FROM (SELECT 1) AS singleton
LEFT JOIN pg_roles AS role ON role.rolname = $roleLiteral;
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 2 `
        -Label "C07 role OID inspect"
    if ($fields[0] -ceq "0") {
        if (-not $AllowAbsent) {
            throw "C07 role $Role 不存在。"
        }
        return [uint32]0
    }
    $oid = [uint32]0
    if (
        $fields[0] -cne "1" -or
        -not [uint32]::TryParse($fields[1], [ref]$oid) -or
        $oid -lt 1
    ) {
        throw "C07 role $Role OID 无效。"
    }
    return $oid
}



function Set-TicketboxC07DatabaseMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $markerLiteral = ConvertTo-TicketboxC07SqlLiteral $Marker
    Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label $Label `
        -Sql "COMMENT ON DATABASE `"$Database`" IS $markerLiteral;" | Out-Null
}



function Get-TicketboxC07DatabasePrivilegeSql {
    param(
        [AllowEmptyString()][string]$ReadyMarker = "",
        [switch]$IncludeManagedSchemaCurrencyAuthority,
        [switch]$PreserveRuntimeFence
    )

    $businessTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeBusinessTables
    )
    $financialAppendTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeFinancialAppendTables
    )
    $authorityTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeAuthorityTables
    )
    $migrationAppendTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeMigrationAppendTables
    )
    $auditAppendTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeAuditAppendTables
    )
    $auditMutableTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeAuditMutableTables
    )
    $retentionFactTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeRetentionFactTables
    )
    $readOnlyTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeReadOnlyTables
    )
    $managedBindingTables = "ARRAY[]::text[]"
    $managedAuthorityTables = "ARRAY[]::text[]"
    $managedAuditInsertTables = "ARRAY[]::text[]"
    if ($IncludeManagedSchemaCurrencyAuthority) {
        $managedBindingTables = ConvertTo-TicketboxC07SqlTextArray @(
            $script:TicketboxManagedSchemaCurrencyBindingTables
        )
        $managedAuthorityTables = ConvertTo-TicketboxC07SqlTextArray @(
            $script:TicketboxManagedSchemaAuthorityTables
        )
        $managedAuditInsertTables = ConvertTo-TicketboxC07SqlTextArray @(
            $script:TicketboxManagedSchemaAuditInsertTables
        )
    }
    $databaseConnectSql = if ($PreserveRuntimeFence) {
        @"
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07MigratorRole";
ALTER ROLE "$script:TicketboxC07RuntimeRole" NOLOGIN CONNECTION LIMIT 0;
"@
    }
    else {
        @"
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07RuntimeRole", "$script:TicketboxC07MigratorRole";
"@
    }
    $readyMarkerSql = ""
    if (-not [string]::IsNullOrEmpty($ReadyMarker)) {
        $readyMarkerLiteral = ConvertTo-TicketboxC07SqlLiteral $ReadyMarker
        $readyMarkerSql = (
            "COMMENT ON DATABASE `"$script:TicketboxC07DatabaseName`" " +
            "IS $readyMarkerLiteral;"
        )
    }
    return @"
BEGIN;
ALTER DATABASE "$script:TicketboxC07DatabaseName" OWNER TO "$script:TicketboxC07OwnerRole";
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName" FROM PUBLIC;
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName" FROM "$script:TicketboxC07RuntimeRole";
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName" FROM "$script:TicketboxC07MigratorRole";
$databaseConnectSql
ALTER SCHEMA public OWNER TO "$script:TicketboxC07OwnerRole";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM "$script:TicketboxC07RuntimeRole";
REVOKE ALL ON SCHEMA public FROM "$script:TicketboxC07MigratorRole";
GRANT USAGE ON SCHEMA public TO "$script:TicketboxC07RuntimeRole";
DO `$ticketbox`$
DECLARE
    object_record record;
    table_name text;
    owner_name text;
    business_tables text[] := $businessTables;
    authority_tables text[] := $authorityTables;
    migration_append_tables text[] := $migrationAppendTables;
    audit_append_tables text[] := $auditAppendTables;
    audit_mutable_tables text[] := $auditMutableTables;
    financial_append_tables text[] := $financialAppendTables;
    retention_fact_tables text[] := $retentionFactTables;
    read_only_tables text[] := $readOnlyTables;
    managed_binding_tables text[] := $managedBindingTables;
    managed_authority_tables text[] := $managedAuthorityTables;
    managed_audit_insert_tables text[] := $managedAuditInsertTables;
    sequence_consumer_tables text[];
BEGIN
    sequence_consumer_tables :=
        business_tables ||
        financial_append_tables ||
        authority_tables ||
        audit_append_tables ||
        audit_mutable_tables ||
        retention_fact_tables ||
        managed_authority_tables ||
        managed_audit_insert_tables;

    -- Remove inherited blanket ACLs without granting any discovered object.
    -- Unknown named grantees are rejected below instead of being silently
    -- adopted into this operation.
    FOR object_record IN
        SELECT catalog_relation.oid, catalog_relation.relkind
        FROM pg_class AS catalog_relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = catalog_relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND catalog_relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    LOOP
        IF object_record.relkind = 'S' THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON SEQUENCE %s FROM PUBLIC, %I, %I',
                object_record.oid::regclass,
                '$script:TicketboxC07RuntimeRole',
                '$script:TicketboxC07MigratorRole'
            );
        ELSE
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON TABLE %s FROM PUBLIC, %I, %I',
                object_record.oid::regclass,
                '$script:TicketboxC07RuntimeRole',
                '$script:TicketboxC07MigratorRole'
            );
        END IF;
    END LOOP;

    FOREACH table_name IN ARRAY (
        business_tables ||
        financial_append_tables ||
        authority_tables ||
        migration_append_tables ||
        audit_append_tables ||
        audit_mutable_tables ||
        retention_fact_tables ||
        read_only_tables ||
        managed_binding_tables ||
        managed_authority_tables ||
        managed_audit_insert_tables
    ) LOOP
        SELECT pg_get_userbyid(relation.relowner)
        INTO owner_name
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = table_name
          AND relation.relkind IN ('r', 'p');
        IF NOT FOUND THEN
            -- Fresh authority is established before Alembic creates tables.
            CONTINUE;
        END IF;
        IF owner_name <> '$script:TicketboxC07OwnerRole' THEN
            RAISE EXCEPTION 'C07 allowlisted table % has wrong owner %',
                table_name, owner_name;
        END IF;
    END LOOP;

    FOREACH table_name IN ARRAY business_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY financial_append_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY authority_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY migration_append_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY audit_append_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY audit_mutable_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY retention_fact_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, DELETE ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY read_only_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY managed_binding_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, UPDATE ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY managed_authority_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY managed_audit_insert_tables LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            EXECUTE format(
                'GRANT INSERT ON TABLE public.%I TO %I',
                table_name,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;

    -- Only sequences owned by an explicitly allowlisted insert consumer are
    -- authorized. A future authority table/function receives nothing.
    FOR object_record IN
        SELECT DISTINCT sequence.oid
        FROM pg_class AS sequence
        JOIN pg_depend AS dependency
          ON dependency.objid = sequence.oid
         AND dependency.classid = 'pg_class'::regclass
         AND dependency.refclassid = 'pg_class'::regclass
         AND dependency.deptype IN ('a', 'i')
        JOIN pg_class AS owner_table ON owner_table.oid = dependency.refobjid
        JOIN pg_namespace AS namespace ON namespace.oid = owner_table.relnamespace
        WHERE namespace.nspname = 'public'
          AND sequence.relkind = 'S'
          AND owner_table.relname = ANY(sequence_consumer_tables)
    LOOP
        EXECUTE format(
            'GRANT USAGE, SELECT ON SEQUENCE %s TO %I',
            object_record.oid::regclass,
            '$script:TicketboxC07RuntimeRole'
        );
    END LOOP;
END
`$ticketbox`$;
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM PUBLIC;
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM "$script:TicketboxC07RuntimeRole";
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public FROM "$script:TicketboxC07MigratorRole";
REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system()
    FROM PUBLIC, "$script:TicketboxC07MigratorRole", "$script:TicketboxC07RuntimeRole";
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system()
    TO "$script:TicketboxC07OwnerRole", "$script:TicketboxC07RuntimeRole";
DO `$ticketbox`$
DECLARE creator_role text;
BEGIN
    FOREACH creator_role IN ARRAY ARRAY[
        'postgres',
        '$script:TicketboxC07OwnerRole',
        '$script:TicketboxC07MigratorRole',
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07LegacyRuntimeRole'
    ] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = creator_role) THEN
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I ' ||
                'REVOKE ALL ON TABLES FROM PUBLIC, %I',
                creator_role,
                '$script:TicketboxC07RuntimeRole'
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I ' ||
                'REVOKE ALL ON SEQUENCES FROM PUBLIC, %I',
                creator_role,
                '$script:TicketboxC07RuntimeRole'
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I ' ||
                'REVOKE EXECUTE ON ROUTINES FROM PUBLIC, %I',
                creator_role,
                '$script:TicketboxC07RuntimeRole'
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public ' ||
                'REVOKE ALL ON TABLES FROM PUBLIC, %I',
                creator_role,
                '$script:TicketboxC07RuntimeRole'
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public ' ||
                'REVOKE ALL ON SEQUENCES FROM PUBLIC, %I',
                creator_role,
                '$script:TicketboxC07RuntimeRole'
            );
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public ' ||
                'REVOKE EXECUTE ON ROUTINES FROM PUBLIC, %I',
                creator_role,
                '$script:TicketboxC07RuntimeRole'
            );
        END IF;
    END LOOP;
END
`$ticketbox`$;
DO `$ticketbox`$
DECLARE
    owner_oid oid := (SELECT oid FROM pg_roles
                      WHERE rolname = '$script:TicketboxC07OwnerRole');
    migrator_oid oid := (SELECT oid FROM pg_roles
                         WHERE rolname = '$script:TicketboxC07MigratorRole');
    runtime_oid oid := (SELECT oid FROM pg_roles
                        WHERE rolname = '$script:TicketboxC07RuntimeRole');
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_database AS database,
             LATERAL aclexplode(
                 COALESCE(database.datacl, acldefault('d', database.datdba))
             ) AS acl
        WHERE database.datname = '$script:TicketboxC07DatabaseName'
          AND (
              acl.grantee NOT IN (owner_oid, migrator_oid, runtime_oid)
              OR (
                  acl.grantee IN (migrator_oid, runtime_oid)
                  AND acl.privilege_type <> 'CONNECT'
              )
          )
    ) THEN
        RAISE EXCEPTION 'C07 database has a foreign or excessive ACL grantee';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_namespace AS namespace,
             LATERAL aclexplode(
                 COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
             ) AS acl
        WHERE namespace.nspname = 'public'
          AND (
              acl.grantee NOT IN (owner_oid, runtime_oid)
              OR (
                  acl.grantee = runtime_oid
                  AND acl.privilege_type <> 'USAGE'
              )
          )
    ) THEN
        RAISE EXCEPTION 'C07 public schema has a foreign or excessive ACL grantee';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                relation.relacl,
                acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char"
                         ELSE 'r'::"char"
                    END,
                    relation.relowner
                )
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND acl.grantee NOT IN (owner_oid, runtime_oid)
    ) THEN
        RAISE EXCEPTION 'C07 public relation has a foreign ACL grantee or owner';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(routine.proacl, acldefault('f', routine.proowner))
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee <> owner_oid
    ) THEN
        RAISE EXCEPTION 'C07 public routine has a foreign ACL grantee or owner';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_default_acl AS defaults
        JOIN pg_roles AS creator ON creator.oid = defaults.defaclrole
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS acl
        WHERE creator.rolname IN (
            'postgres',
            '$script:TicketboxC07OwnerRole',
            '$script:TicketboxC07MigratorRole',
            '$script:TicketboxC07RuntimeRole',
            '$script:TicketboxC07LegacyRuntimeRole'
        )
          AND acl.grantee <> defaults.defaclrole
    ) THEN
        RAISE EXCEPTION 'C07 creator default privileges retain a foreign grantee';
    END IF;
END
`$ticketbox`$;
ALTER ROLE "$script:TicketboxC07RuntimeRole" SET search_path = pg_catalog, public;
ALTER ROLE "$script:TicketboxC07MigratorRole" SET search_path = pg_catalog, public;
$readyMarkerSql
COMMIT;
"@
}

function Assert-TicketboxC07RoleCatalog {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [switch]$PreserveRuntimeFence
    )

    $runtimeLoginPredicate = if ($PreserveRuntimeFence) {
        "NOT rolcanlogin AND rolconnlimit = 0"
    }
    else { "rolcanlogin" }
    $runtimeConnectPredicate = if ($PreserveRuntimeFence) {
        "NOT has_database_privilege('$script:TicketboxC07RuntimeRole', '$script:TicketboxC07DatabaseName', 'CONNECT')"
    }
    else {
        "has_database_privilege('$script:TicketboxC07RuntimeRole', '$script:TicketboxC07DatabaseName', 'CONNECT')"
    }

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 role catalog verification" `
        -Sql @"
SELECT
    (COALESCE((SELECT NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
             AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      FROM pg_roles WHERE rolname = '$script:TicketboxC07OwnerRole'), false))::text || E'\t' ||
    (COALESCE((SELECT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
             AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
             AND rolconnlimit = 1 AND rolvaliduntil IS NOT NULL
             AND rolvaliduntil > clock_timestamp()
             AND rolvaliduntil <= clock_timestamp() + interval '1 hour'
      FROM pg_roles WHERE rolname = '$script:TicketboxC07MigratorRole'), false))::text || E'\t' ||
    (COALESCE((SELECT $runtimeLoginPredicate AND rolinherit AND NOT rolsuper AND NOT rolcreatedb
             AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      FROM pg_roles WHERE rolname = '$script:TicketboxC07RuntimeRole'), false))::text || E'\t' ||
    ((SELECT count(*) = 1
      FROM pg_auth_members AS membership
      JOIN pg_roles AS granted ON granted.oid = membership.roleid
      JOIN pg_roles AS member ON member.oid = membership.member
      WHERE granted.rolname = '$script:TicketboxC07OwnerRole'
        AND member.rolname = '$script:TicketboxC07MigratorRole'
        AND NOT membership.admin_option
        AND NOT membership.inherit_option
        AND membership.set_option))::text || E'\t' ||
    ((SELECT count(*) = 0
       FROM pg_auth_members AS membership
       JOIN pg_roles AS granted ON granted.oid = membership.roleid
       JOIN pg_roles AS member ON member.oid = membership.member
       WHERE (
           granted.rolname IN (
               '$script:TicketboxC07OwnerRole',
               '$script:TicketboxC07MigratorRole',
               '$script:TicketboxC07RuntimeRole'
           )
           OR member.rolname IN (
               '$script:TicketboxC07OwnerRole',
               '$script:TicketboxC07MigratorRole',
               '$script:TicketboxC07RuntimeRole'
           )
       )
         AND NOT (
             granted.rolname = '$script:TicketboxC07OwnerRole'
             AND member.rolname = '$script:TicketboxC07MigratorRole'
             AND NOT membership.admin_option
             AND NOT membership.inherit_option
             AND membership.set_option
         )))::text || E'\t' ||
    (COALESCE((SELECT COALESCE(
          rolconfig @> ARRAY['search_path=pg_catalog, public']::text[],
          false
      )
      FROM pg_roles
      WHERE rolname = '$script:TicketboxC07RuntimeRole'), false))::text || E'\t' ||
    (COALESCE((SELECT COALESCE(
          rolconfig @> ARRAY['search_path=pg_catalog, public']::text[],
          false
      )
      FROM pg_roles
      WHERE rolname = '$script:TicketboxC07MigratorRole'), false))::text || E'\t' ||
    (COALESCE((SELECT pg_get_userbyid(datdba) = '$script:TicketboxC07OwnerRole'
      FROM pg_database WHERE datname = '$script:TicketboxC07DatabaseName'), false))::text || E'\t' ||
    (COALESCE((SELECT pg_get_userbyid(nspowner) = '$script:TicketboxC07OwnerRole'
      FROM pg_namespace WHERE nspname = 'public'), false))::text || E'\t' ||
    ($runtimeConnectPredicate)::text || E'\t' ||
    (NOT has_database_privilege(
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07DatabaseName',
        'CREATE'
    ))::text || E'\t' ||
    (NOT has_database_privilege(
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07DatabaseName',
        'TEMPORARY'
    ))::text || E'\t' ||
    has_schema_privilege('$script:TicketboxC07RuntimeRole', 'public', 'USAGE')::text || E'\t' ||
    (NOT has_schema_privilege(
        '$script:TicketboxC07RuntimeRole',
        'public',
        'CREATE'
    ))::text || E'\t' ||
    (
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND pg_get_userbyid(relation.relowner) = '$script:TicketboxC07RuntimeRole'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_proc AS routine
            JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
            WHERE namespace.nspname = 'public'
              AND pg_get_userbyid(routine.proowner) = '$script:TicketboxC07RuntimeRole'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_type AS type
            JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
            WHERE namespace.nspname = 'public'
              AND pg_get_userbyid(type.typowner) = '$script:TicketboxC07RuntimeRole'
        )
    )::text;
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 15 `
        -Label "C07 role catalog verification"
    if (@($fields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 role catalog/ownership/privilege matrix 不符合发布合同。" `
            -FailureCode "role_authority_invariant_failed")
    }
}

function Assert-TicketboxC07RetiredRoleCatalog {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 retired role catalog verification" `
        -Sql @"
SELECT
    (COALESCE((SELECT NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
             AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
      FROM pg_roles WHERE rolname = '$script:TicketboxC07OwnerRole'), false))::text || E'\t' ||
    (COALESCE((SELECT NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
             AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
             AND NOT rolbypassrls AND rolconnlimit = 1
             AND rolpassword IS NULL
      FROM pg_authid WHERE rolname = '$script:TicketboxC07MigratorRole'), false))::text || E'\t' ||
    (COALESCE((SELECT rolcanlogin AND rolinherit AND NOT rolsuper
             AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
             AND NOT rolbypassrls AND rolpassword IS NOT NULL
      FROM pg_authid WHERE rolname = '$script:TicketboxC07RuntimeRole'), false))::text || E'\t' ||
    ((SELECT count(*) = 0
       FROM pg_auth_members AS membership
       JOIN pg_roles AS granted ON granted.oid = membership.roleid
       JOIN pg_roles AS member ON member.oid = membership.member
       WHERE granted.rolname IN (
                 '$script:TicketboxC07OwnerRole',
                 '$script:TicketboxC07MigratorRole',
                 '$script:TicketboxC07RuntimeRole',
                 '$script:TicketboxC07LegacyRuntimeRole'
             )
          OR member.rolname IN (
                 '$script:TicketboxC07OwnerRole',
                 '$script:TicketboxC07MigratorRole',
                 '$script:TicketboxC07RuntimeRole',
                 '$script:TicketboxC07LegacyRuntimeRole'
             )))::text || E'\t' ||
    (COALESCE((SELECT COALESCE(
          rolconfig @> ARRAY['search_path=pg_catalog, public']::text[],
          false
      )
      FROM pg_roles
      WHERE rolname = '$script:TicketboxC07RuntimeRole'), false))::text || E'\t' ||
    (COALESCE((SELECT COALESCE(
          rolconfig @> ARRAY['search_path=pg_catalog, public']::text[],
          false
      )
      FROM pg_roles
      WHERE rolname = '$script:TicketboxC07MigratorRole'), false))::text || E'\t' ||
    (COALESCE((SELECT pg_get_userbyid(datdba) = '$script:TicketboxC07OwnerRole'
      FROM pg_database WHERE datname = '$script:TicketboxC07DatabaseName'), false))::text || E'\t' ||
    (COALESCE((SELECT pg_get_userbyid(nspowner) = '$script:TicketboxC07OwnerRole'
      FROM pg_namespace WHERE nspname = 'public'), false))::text || E'\t' ||
    has_database_privilege(
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07DatabaseName',
        'CONNECT'
    )::text || E'\t' ||
    (NOT has_database_privilege(
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07DatabaseName',
        'CREATE'
    ))::text || E'\t' ||
    (NOT has_database_privilege(
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07DatabaseName',
        'TEMPORARY'
    ))::text || E'\t' ||
    (NOT has_database_privilege(
        '$script:TicketboxC07MigratorRole',
        '$script:TicketboxC07DatabaseName',
        'CONNECT'
    ))::text || E'\t' ||
    has_schema_privilege('$script:TicketboxC07RuntimeRole', 'public', 'USAGE')::text || E'\t' ||
    (NOT has_schema_privilege(
        '$script:TicketboxC07RuntimeRole',
        'public',
        'CREATE'
    ))::text || E'\t' ||
    (
        NOT EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND pg_get_userbyid(relation.relowner) = '$script:TicketboxC07RuntimeRole'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_proc AS routine
            JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
            WHERE namespace.nspname = 'public'
              AND pg_get_userbyid(routine.proowner) = '$script:TicketboxC07RuntimeRole'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_type AS type
            JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
            WHERE namespace.nspname = 'public'
              AND pg_get_userbyid(type.typowner) = '$script:TicketboxC07RuntimeRole'
        )
    )::text;
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 15 `
        -Label "C07 retired role catalog verification"
    if (@($fields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 retired role catalog/ownership/privilege matrix 不符合发布合同。" `
            -FailureCode "role_authority_invariant_failed")
    }
}

function Assert-TicketboxC07RuntimeAclContract {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [switch]$IncludeManagedSchemaCurrencyAuthority,
        [switch]$PreserveRuntimeFence
    )
    $runtimeConnectPredicate = if ($PreserveRuntimeFence) {
        "NOT has_database_privilege('$script:TicketboxC07RuntimeRole', current_database(), 'CONNECT')"
    }
    else {
        "has_database_privilege('$script:TicketboxC07RuntimeRole', current_database(), 'CONNECT')"
    }
    $specifications = @()
    foreach ($entry in @(
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeBusinessTables
            Privileges = @("SELECT", "INSERT", "UPDATE", "DELETE")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeFinancialAppendTables
            Privileges = @("SELECT", "INSERT")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeAuthorityTables
            Privileges = @("SELECT", "INSERT", "UPDATE")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeMigrationAppendTables
            Privileges = @("SELECT", "INSERT")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeAuditAppendTables
            Privileges = @("SELECT", "INSERT")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeAuditMutableTables
            Privileges = @("SELECT", "INSERT", "UPDATE", "DELETE")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeRetentionFactTables
            Privileges = @("SELECT", "INSERT", "DELETE")
        },
        [pscustomobject]@{
            Tables = $script:TicketboxC07RuntimeReadOnlyTables
            Privileges = @("SELECT")
        }
    )) {
        foreach ($table in @($entry.Tables)) {
            $specifications += [pscustomobject]@{
                Table = [string]$table
                Privileges = @($entry.Privileges)
            }
        }
    }
    if ($IncludeManagedSchemaCurrencyAuthority) {
        foreach ($entry in @(
            [pscustomobject]@{
                Tables = $script:TicketboxManagedSchemaCurrencyBindingTables
                Privileges = @("SELECT", "UPDATE")
            },
            [pscustomobject]@{
                Tables = $script:TicketboxManagedSchemaAuthorityTables
                Privileges = @("SELECT", "INSERT", "UPDATE")
            },
            [pscustomobject]@{
                Tables = $script:TicketboxManagedSchemaAuditInsertTables
                Privileges = @("INSERT")
            }
        )) {
            foreach ($table in @($entry.Tables)) {
                $specifications += [pscustomobject]@{
                    Table = [string]$table
                    Privileges = @($entry.Privileges)
                }
            }
        }
    }
    $duplicates = @(
        $specifications |
            Group-Object -Property Table |
            Where-Object { $_.Count -ne 1 }
    )
    if ($duplicates.Count -ne 0) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 runtime ACL allowlist 存在重复 authority。" `
            -FailureCode "release_identity_mismatch")
    }
    $expectedRows = @(
        $specifications | ForEach-Object {
            $privilegeItems = @(
                $_.Privileges | ForEach-Object {
                    ConvertTo-TicketboxC07SqlLiteral ([string]$_)
                }
            )
            "(" +
                (ConvertTo-TicketboxC07SqlLiteral ([string]$_.Table)) +
                ", " +
                ("ARRAY[" + ($privilegeItems -join ", ") + "]::text[]") +
                ")"
        }
    ) -join ",`n        "
    $sequenceConsumerTables = @(
        $script:TicketboxC07RuntimeBusinessTables +
        $script:TicketboxC07RuntimeFinancialAppendTables +
        $script:TicketboxC07RuntimeAuthorityTables +
        $script:TicketboxC07RuntimeAuditAppendTables +
        $script:TicketboxC07RuntimeAuditMutableTables +
        $script:TicketboxC07RuntimeRetentionFactTables
    )
    if ($IncludeManagedSchemaCurrencyAuthority) {
        $sequenceConsumerTables += @(
            $script:TicketboxManagedSchemaAuthorityTables +
            $script:TicketboxManagedSchemaAuditInsertTables
        )
    }
    $sequenceConsumers = ConvertTo-TicketboxC07SqlTextArray $sequenceConsumerTables
    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 structured runtime ACL attestation" `
        -Sql @"
WITH expected(table_name, expected_privileges) AS (
    VALUES
        $expectedRows
), relation AS (
    SELECT expected.table_name,
           expected.expected_privileges,
           catalog_relation.oid,
           pg_get_userbyid(catalog_relation.relowner) AS owner_name
    FROM expected
    LEFT JOIN pg_class AS catalog_relation
      ON catalog_relation.relname = expected.table_name
     AND catalog_relation.relnamespace = 'public'::regnamespace
     AND catalog_relation.relkind IN ('r', 'p')
), privilege_name(privilege) AS (
    VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
           ('TRUNCATE'), ('REFERENCES'), ('TRIGGER'), ('MAINTAIN')
), sequence_contract AS (
    SELECT sequence.oid,
           owner_table.relname = ANY($sequenceConsumers) AS is_consumer
    FROM pg_class AS sequence
    JOIN pg_namespace AS namespace
      ON namespace.oid = sequence.relnamespace
    LEFT JOIN pg_depend AS dependency
      ON dependency.objid = sequence.oid
     AND dependency.classid = 'pg_class'::regclass
     AND dependency.refclassid = 'pg_class'::regclass
     AND dependency.deptype IN ('a', 'i')
    LEFT JOIN pg_class AS owner_table ON owner_table.oid = dependency.refobjid
    WHERE namespace.nspname = 'public'
      AND sequence.relkind = 'S'
)
SELECT
    (SELECT count(*) = count(oid) FROM relation)::text || E'\t' ||
    COALESCE((
        SELECT bool_and(owner_name = '$script:TicketboxC07OwnerRole')
        FROM relation
    ), false)::text || E'\t' ||
    COALESCE((
        SELECT bool_and(
            has_table_privilege(
                '$script:TicketboxC07RuntimeRole',
                relation.oid,
                privilege_name.privilege
            ) = (
                privilege_name.privilege = ANY(relation.expected_privileges)
            )
        )
        FROM relation CROSS JOIN privilege_name
        WHERE relation.oid IS NOT NULL
    ), false)::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1
        FROM pg_class AS catalog_relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = catalog_relation.relnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                catalog_relation.relacl,
                acldefault('r', catalog_relation.relowner)
            )
        ) AS acl
        LEFT JOIN pg_roles AS grantee ON grantee.oid = acl.grantee
        WHERE namespace.nspname = 'public'
          AND catalog_relation.relkind IN ('r', 'p')
          AND COALESCE(grantee.rolname, 'PUBLIC') NOT IN (
              '$script:TicketboxC07OwnerRole',
              '$script:TicketboxC07RuntimeRole',
              '$script:TicketboxC07MigratorRole'
          )
    ))::text || E'\t' ||
    (
        $runtimeConnectPredicate
        AND NOT has_database_privilege(
            '$script:TicketboxC07RuntimeRole',
            current_database(),
            'CREATE'
        )
        AND NOT has_database_privilege(
            '$script:TicketboxC07RuntimeRole',
            current_database(),
            'TEMPORARY'
        )
        AND has_schema_privilege(
            '$script:TicketboxC07RuntimeRole',
            'public',
            'USAGE'
        )
        AND NOT has_schema_privilege(
            '$script:TicketboxC07RuntimeRole',
            'public',
            'CREATE'
        )
    )::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public'
          AND has_function_privilege(
              '$script:TicketboxC07RuntimeRole',
              routine.oid,
              'EXECUTE'
          )
    ))::text || E'\t' ||
    COALESCE((
        SELECT bool_and(
            CASE WHEN is_consumer THEN
                has_sequence_privilege(
                    '$script:TicketboxC07RuntimeRole', oid, 'USAGE'
                )
                AND has_sequence_privilege(
                    '$script:TicketboxC07RuntimeRole', oid, 'SELECT'
                )
                AND NOT has_sequence_privilege(
                    '$script:TicketboxC07RuntimeRole', oid, 'UPDATE'
                )
            ELSE
                NOT has_sequence_privilege(
                    '$script:TicketboxC07RuntimeRole', oid, 'USAGE'
                )
                AND NOT has_sequence_privilege(
                    '$script:TicketboxC07RuntimeRole', oid, 'SELECT'
                )
                AND NOT has_sequence_privilege(
                    '$script:TicketboxC07RuntimeRole', oid, 'UPDATE'
                )
            END
        )
        FROM sequence_contract
    ), true)::text || E'\t' ||
    (
        has_function_privilege(
            '$script:TicketboxC07RuntimeRole',
            'pg_catalog.pg_control_system()',
            'EXECUTE'
        )
    )::text;
"@
    try {
        $fields = ConvertFrom-TicketboxC07SingleRow `
            -Output $output `
            -FieldCount 8 `
            -Label "C07 structured runtime ACL attestation"
    }
    catch {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 structured runtime ACL attestation shape 无效。" `
            -FailureCode "runtime_acl_invariant_failed" `
            -InnerException $_.Exception)
    }
    if (@($fields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 runtime ACL structured attestation 未满足发布合同。" `
            -FailureCode "runtime_acl_invariant_failed")
    }
}

function Set-TicketboxManagedSchemaRuntimeAcl {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [switch]$PreserveRuntimeFence
    )

    Assert-TicketboxC07SecureString `
        $SuperuserPassword `
        "managed schema runtime ACL superuser authority"
    Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (Get-TicketboxC07DatabasePrivilegeSql `
            -IncludeManagedSchemaCurrencyAuthority `
            -PreserveRuntimeFence:$PreserveRuntimeFence) `
        -Label "managed schema exact runtime ACL application" | Out-Null
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -IncludeManagedSchemaCurrencyAuthority `
        -PreserveRuntimeFence:$PreserveRuntimeFence
    Assert-TicketboxC07RoleCatalog `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -PreserveRuntimeFence:$PreserveRuntimeFence
}


function Assert-TicketboxC07MigratorCredential {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword
    )

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role $script:TicketboxC07MigratorRole `
        -Password $MigratorPassword `
        -Label "C07 frozen migrator credential authority probe" `
        -Sql ("SELECT current_user || E'\t' || " +
            "current_setting('search_path');")
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 2 `
        -Label "C07 frozen migrator credential authority probe"
    if (
        $fields[0] -cne $script:TicketboxC07MigratorRole -or
        $fields[1] -cne "pg_catalog, public"
    ) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 frozen migrator credential/search_path authority 不匹配。" `
            -FailureCode "role_authority_invariant_failed")
    }
}










function Get-TicketboxC07RoleAuthoritySha256 {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $evidence = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 role authority canonical evidence" `
        -Sql @"
SELECT 'role' || E'\t' || rolname || E'\t' || oid::text || E'\t' ||
       rolcanlogin::text || E'\t' || rolinherit::text || E'\t' ||
       rolsuper::text || E'\t' || rolcreatedb::text || E'\t' ||
       rolcreaterole::text || E'\t' || rolreplication::text || E'\t' ||
       rolbypassrls::text || E'\t' || rolconnlimit::text || E'\t' ||
       (rolpassword IS NOT NULL)::text || E'\t' ||
       COALESCE(array_to_string(rolconfig, ','), '') || E'\t' ||
       COALESCE(shobj_description(oid, 'pg_authid'), '')
FROM pg_authid
WHERE rolname IN (
    '$script:TicketboxC07OwnerRole',
    '$script:TicketboxC07MigratorRole',
    '$script:TicketboxC07RuntimeRole',
    '$script:TicketboxC07LegacyRuntimeRole'
)
UNION ALL
SELECT 'membership' || E'\t' || granted.rolname || E'\t' ||
       member.rolname || E'\t' || membership.admin_option::text || E'\t' ||
       membership.inherit_option::text || E'\t' || membership.set_option::text
FROM pg_auth_members AS membership
JOIN pg_roles AS granted ON granted.oid = membership.roleid
JOIN pg_roles AS member ON member.oid = membership.member
WHERE granted.rolname IN (
          '$script:TicketboxC07OwnerRole',
          '$script:TicketboxC07MigratorRole',
          '$script:TicketboxC07RuntimeRole',
          '$script:TicketboxC07LegacyRuntimeRole'
      )
   OR member.rolname IN (
          '$script:TicketboxC07OwnerRole',
          '$script:TicketboxC07MigratorRole',
          '$script:TicketboxC07RuntimeRole',
          '$script:TicketboxC07LegacyRuntimeRole'
      )
ORDER BY 1;
"@
    return Get-TicketboxC07DatabaseTextSha256 ([string]$evidence).Trim()
}

function Get-TicketboxC07RuntimeAclSha256 {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $evidence = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 runtime ACL canonical evidence" `
        -Sql @"
WITH acl_rows AS (
    SELECT 'database'::text AS kind, database.datname AS object_name,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC') AS grantee,
           acl.privilege_type, acl.is_grantable
    FROM pg_database AS database,
         LATERAL aclexplode(
             COALESCE(database.datacl, acldefault('d'::"char", database.datdba))
         ) AS acl
    WHERE database.datname = current_database()
    UNION ALL
    SELECT 'schema', namespace.nspname,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'),
           acl.privilege_type, acl.is_grantable
    FROM pg_namespace AS namespace,
         LATERAL aclexplode(
             COALESCE(namespace.nspacl, acldefault('n'::"char", namespace.nspowner))
         ) AS acl
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT CASE WHEN relation.relkind = 'S' THEN 'sequence' ELSE 'relation' END,
           namespace.nspname || '.' || relation.relname,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'),
           acl.privilege_type, acl.is_grantable
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(
            relation.relacl,
            acldefault(
                CASE WHEN relation.relkind = 'S' THEN 'S'::"char"
                     ELSE 'r'::"char"
                END,
                relation.relowner
            )
        )
    ) AS acl
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
    UNION ALL
    SELECT 'routine', namespace.nspname || '.' ||
           routine.oid::regprocedure::text,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'),
           acl.privilege_type, acl.is_grantable
    FROM pg_proc AS routine
    JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(routine.proacl, acldefault('f'::"char", routine.proowner))
    ) AS acl
    WHERE namespace.nspname = 'public'
    UNION ALL
    SELECT 'routine', namespace.nspname || '.' ||
           routine.oid::regprocedure::text,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'),
           acl.privilege_type, acl.is_grantable
    FROM pg_proc AS routine
    JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(routine.proacl, acldefault('f'::"char", routine.proowner))
    ) AS acl
    WHERE routine.oid = 'pg_catalog.pg_control_system()'::regprocedure
)
SELECT kind || E'\t' || object_name || E'\t' || grantee || E'\t' ||
       privilege_type || E'\t' || is_grantable::text
FROM acl_rows
WHERE NOT (
    kind = 'database'
    AND object_name = current_database()
    AND grantee IN (
        '$script:TicketboxC07RuntimeRole',
        '$script:TicketboxC07MigratorRole'
    )
    AND privilege_type = 'CONNECT'
    AND NOT is_grantable
)
ORDER BY kind, object_name, grantee, privilege_type, is_grantable;
"@
    $canonicalEvidence = (([string]$evidence).Trim() -replace "`r`n", "`n") `
        -replace "`r", "`n"
    return Get-TicketboxC07DatabaseTextSha256 $canonicalEvidence
}


function Assert-TicketboxC07RuntimeCredential {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword
    )

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role $script:TicketboxC07RuntimeRole `
        -Password $RuntimePassword `
        -Label "C07 final runtime credential authority probe" `
        -Sql (
            "SELECT current_user || E'\t' || " +
            "current_setting('search_path');"
        )
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 2 `
        -Label "C07 final runtime credential authority probe"
    if (
        $fields[0] -cne $script:TicketboxC07RuntimeRole -or
        $fields[1] -cne "pg_catalog, public"
        ) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 final runtime credential/search_path authority 不匹配。" `
            -FailureCode "role_authority_invariant_failed")
    }
}







function Get-TicketboxC07MigratorRetirementSql {
    return @"
BEGIN;
REVOKE CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    FROM "$script:TicketboxC07MigratorRole";
DO `$ticketbox_membership`$
DECLARE
    migrator_oid oid := (
        SELECT oid FROM pg_roles
        WHERE rolname = '$script:TicketboxC07MigratorRole'
    );
    membership_record record;
BEGIN
    FOR membership_record IN
        SELECT granted.rolname AS granted_name, member.rolname AS member_name
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE membership.roleid = migrator_oid OR membership.member = migrator_oid
    LOOP
        EXECUTE format(
            'REVOKE %I FROM %I',
            membership_record.granted_name,
            membership_record.member_name
        );
    END LOOP;
END
`$ticketbox_membership`$;
ALTER ROLE "$script:TicketboxC07MigratorRole" NOLOGIN PASSWORD NULL;
COMMIT;
SELECT pg_terminate_backend(pid, 5000)
FROM pg_stat_activity
WHERE usename = '$script:TicketboxC07MigratorRole'
  AND pid <> pg_backend_pid();
"@
}

function Get-TicketboxC07MigratorRetirementVerificationSql {
    return @"
DO `$ticketbox`$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE granted.rolname = '$script:TicketboxC07MigratorRole'
           OR member.rolname = '$script:TicketboxC07MigratorRole'
    ) THEN
        RAISE EXCEPTION 'migrator still has a role membership';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_authid
        WHERE rolname = '$script:TicketboxC07MigratorRole'
          AND NOT rolcanlogin
          AND rolpassword IS NULL
    ) THEN
        RAISE EXCEPTION 'migrator credential was not retired';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE usename = '$script:TicketboxC07MigratorRole'
          AND pid <> pg_backend_pid()
    ) THEN
        RAISE EXCEPTION 'migrator sessions remain active';
    END IF;
    IF has_database_privilege(
        '$script:TicketboxC07MigratorRole',
        '$script:TicketboxC07DatabaseName',
        'CONNECT'
    ) THEN
        RAISE EXCEPTION 'migrator still has database CONNECT';
    END IF;
END
`$ticketbox`$;
"@
}
