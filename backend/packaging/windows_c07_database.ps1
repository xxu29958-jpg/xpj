#Requires -Version 5.1

<#
.SYNOPSIS
  Host-authoritative PostgreSQL role and isolated-restore database helpers for C07.
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
$script:TicketboxC07ProductionMarkerSchema =
    "ticketbox-c07-production-authority-v1"
$script:TicketboxC07ProductionResultSchema =
    "ticketbox-c07-production-authority-result-v2"
$script:TicketboxC07TargetCommitResultSchema =
    "ticketbox-c07-target-commit-result-v1"
$script:TicketboxC07MigrationEvidenceSchema =
    "ticketbox-c07-migration-evidence-v1"
$script:TicketboxC07ResourceMigrationEvidenceSchema =
    "ticketbox-c07-migration-evidence-v2"
$script:TicketboxC07ProductionLifecycleBindingSchema =
    "ticketbox-c07-production-lifecycle-binding-v2"
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

function Assert-TicketboxC07MigratorCredentialWindow {
    param([Parameter(Mandatory = $true)][DateTime]$ValidUntilUtc)

    $now = [DateTime]::UtcNow
    if (
        $ValidUntilUtc.Kind -eq [DateTimeKind]::Unspecified -or
        $ValidUntilUtc.ToUniversalTime() -le $now -or
        $ValidUntilUtc.ToUniversalTime() -gt $now.AddHours(1)
    ) {
        throw "C07 migrator credential TTL 必须为未来一小时内的显式 UTC 时间。"
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

function New-TicketboxC07DatabaseMarker {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)]
        [ValidateSet("database_created", "roles_created", "objects_reassigned", "authority_ready")]
        [string]$Phase,
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][object]$Roles,
        [uint32]$LegacyRoleOid = 0
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    if (
        -not $Catalog.Exists -or
        [uint32]$Catalog.DatabaseOid -lt 1 -or
        [uint32]$Catalog.OwnerRoleOid -lt 1 -or
        -not $Roles.Exists
    ) {
        throw "C07 database marker 缺少 database/role OID。"
    }
    return (
        "$script:TicketboxC07DatabaseMarkerSchema|" +
        "$($operation.ToString('D'))|$Mode|$Phase|" +
        "$($Catalog.ClusterSystemIdentifier)|$($Catalog.DatabaseOid)|" +
        "$($Roles.OwnerRoleOid)|$($Roles.MigratorRoleOid)|" +
        "$($Roles.RuntimeRoleOid)|$LegacyRoleOid"
    )
}

function Assert-TicketboxC07DatabaseMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][object]$Roles,
        [uint32]$LegacyRoleOid = 0,
        [switch]$AllowUnregisteredIsolatedResidue
    )

    if ([string]::IsNullOrEmpty([string]$Catalog.Marker)) {
        if (
            $AllowUnregisteredIsolatedResidue -and
            -not $Catalog.AllowsConnections -and
            [uint32]$Catalog.OwnerRoleOid -eq [uint32]$Roles.OwnerRoleOid
        ) {
            return "unregistered"
        }
        throw "C07 database 缺少本 operation 的 durable phase marker。"
    }
    $parts = @(([string]$Catalog.Marker).Split([char]"|"))
    if ($parts.Count -ne 10) {
        throw "C07 database phase marker 结构无效。"
    }
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $expected = @(
        $script:TicketboxC07DatabaseMarkerSchema,
        $operation.ToString("D"),
        $Mode,
        $parts[3],
        [string]$Catalog.ClusterSystemIdentifier,
        [string]$Catalog.DatabaseOid,
        [string]$Roles.OwnerRoleOid,
        [string]$Roles.MigratorRoleOid,
        [string]$Roles.RuntimeRoleOid,
        [string]$LegacyRoleOid
    )
    foreach ($index in 0..9) {
        if ($parts[$index] -cne $expected[$index]) {
            throw "C07 database phase marker 与 live cluster/database/role OID 不一致。"
        }
    }
    if ($parts[3] -cnotin @(
        "database_created",
        "roles_created",
        "objects_reassigned",
        "authority_ready"
    )) {
        throw "C07 database phase marker 的 phase 无效。"
    }
    if (
        (
            $Mode -ceq "fresh_install" -or
            $parts[3] -cin @("objects_reassigned", "authority_ready")
        ) -and
        [uint32]$Catalog.OwnerRoleOid -ne [uint32]$Roles.OwnerRoleOid
    ) {
        throw "C07 database phase marker 的 live owner role OID 不匹配。"
    }
    if (
        $Mode -ceq "legacy_adoption" -and
        $parts[3] -ceq "roles_created" -and
        [uint32]$Catalog.OwnerRoleOid -ne $LegacyRoleOid
    ) {
        throw "C07 legacy roles_created phase 不再由 legacy role 持有。"
    }
    return $parts[3]
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

function Get-TicketboxC07RoleBootstrapSql {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeVerifier,
        [Parameter(Mandatory = $true)][string]$MigratorVerifier,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [ValidateSet("published", "frozen")]
        [string]$RuntimeAdmissionState = "published"
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    if (
        $RuntimeVerifier -cnotmatch '^SCRAM-SHA-256\$4096:' -or
        $MigratorVerifier -cnotmatch '^SCRAM-SHA-256\$4096:'
    ) {
        throw "C07 role bootstrap 只接受 SCRAM-SHA-256 verifier。"
    }
    $runtimeVerifierSql = Escape-SqlLiteral $RuntimeVerifier
    $migratorVerifierSql = Escape-SqlLiteral $MigratorVerifier
    $validUntil = $MigratorValidUntilUtc.ToUniversalTime().ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    $operationSql = ConvertTo-TicketboxC07SqlLiteral $operation.ToString("D")
    $modeSql = ConvertTo-TicketboxC07SqlLiteral $Mode
    $runtimeRoleCreateSql = if ($RuntimeAdmissionState -ceq "frozen") {
        'NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE ' +
            "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0 PASSWORD '$runtimeVerifierSql'"
    }
    else {
        'LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE ' +
            "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD '$runtimeVerifierSql'"
    }
    $runtimeRoleAlterSql = if ($RuntimeAdmissionState -ceq "frozen") {
        'NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE ' +
            'NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0'
    }
    else {
        'LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE ' +
            'NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1'
    }
    $databaseAdmissionSql = if ($RuntimeAdmissionState -ceq "frozen") {
        @"
DO `$ticketbox_database_admission`$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_database
        WHERE datname = '$script:TicketboxC07DatabaseName'
    ) THEN
        EXECUTE 'REVOKE CONNECT ON DATABASE '
            || quote_ident('$script:TicketboxC07DatabaseName')
            || ' FROM ' || quote_ident('$script:TicketboxC07RuntimeRole');
        EXECUTE 'GRANT CONNECT ON DATABASE '
            || quote_ident('$script:TicketboxC07DatabaseName')
            || ' TO ' || quote_ident('$script:TicketboxC07MigratorRole');
    END IF;
END
`$ticketbox_database_admission`$;
"@
    }
    else { "" }
    $markerSchemaSql = ConvertTo-TicketboxC07SqlLiteral (
        $script:TicketboxC07RoleMarkerSchema
    )
    return @"
SET log_statement = 'none';
SET log_min_duration_statement = -1;
SET log_min_error_statement = 'panic';
BEGIN;
DO `$ticketbox`$
DECLARE
    operation_id text := $operationSql;
    bootstrap_mode text := $modeSql;
    marker_schema text := $markerSchemaSql;
    existing_count integer;
    role_oid oid;
    role_name text;
    expected_marker text;
    actual_marker text;
BEGIN
    SELECT count(*) INTO existing_count
    FROM pg_roles
    WHERE rolname IN (
        '$script:TicketboxC07OwnerRole',
        '$script:TicketboxC07MigratorRole',
        '$script:TicketboxC07RuntimeRole'
    );
    IF existing_count NOT IN (0, 3) THEN
        RAISE EXCEPTION 'partial C07 role residue';
    END IF;

    IF existing_count = 3 THEN
        FOREACH role_name IN ARRAY ARRAY[
            '$script:TicketboxC07OwnerRole',
            '$script:TicketboxC07MigratorRole',
            '$script:TicketboxC07RuntimeRole'
        ] LOOP
            SELECT oid, shobj_description(oid, 'pg_authid')
            INTO STRICT role_oid, actual_marker
            FROM pg_roles
            WHERE rolname = role_name;
            expected_marker := format(
                '%s|%s|%s|roles_created|%s',
                marker_schema,
                operation_id,
                bootstrap_mode,
                role_oid
            );
            IF actual_marker IS DISTINCT FROM expected_marker THEN
                RAISE EXCEPTION 'C07 role marker mismatch for %', role_name;
            END IF;
        END LOOP;
    ELSE
        CREATE ROLE "$script:TicketboxC07OwnerRole"
            NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        CREATE ROLE "$script:TicketboxC07RuntimeRole"
            $runtimeRoleCreateSql;
        CREATE ROLE "$script:TicketboxC07MigratorRole"
            LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
            PASSWORD '$migratorVerifierSql' VALID UNTIL '$validUntil';

        FOREACH role_name IN ARRAY ARRAY[
            '$script:TicketboxC07OwnerRole',
            '$script:TicketboxC07MigratorRole',
            '$script:TicketboxC07RuntimeRole'
        ] LOOP
            SELECT oid INTO STRICT role_oid
            FROM pg_roles
            WHERE rolname = role_name;
            expected_marker := format(
                '%s|%s|%s|roles_created|%s',
                marker_schema,
                operation_id,
                bootstrap_mode,
                role_oid
            );
            EXECUTE format(
                'COMMENT ON ROLE %I IS %L',
                role_name,
                expected_marker
            );
        END LOOP;
    END IF;

    -- Existing exact residue is reused without rotating either credential.
    -- The caller proves the durable same-operation credentials by performing
    -- authenticated runtime/migrator probes before authority_ready is written.
    ALTER ROLE "$script:TicketboxC07OwnerRole"
        NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS;
    ALTER ROLE "$script:TicketboxC07RuntimeRole"
        $runtimeRoleAlterSql;
    ALTER ROLE "$script:TicketboxC07MigratorRole"
        LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
        VALID UNTIL '$validUntil';
    IF EXISTS (
        SELECT 1
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
          )
    ) THEN
        RAISE EXCEPTION 'foreign C07 role membership residue';
    END IF;
    GRANT "$script:TicketboxC07OwnerRole" TO "$script:TicketboxC07MigratorRole"
        WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
    REVOKE "$script:TicketboxC07OwnerRole" FROM "$script:TicketboxC07RuntimeRole";
END
`$ticketbox`$;
$databaseAdmissionSql
SELECT rolname || E'\t' || oid::text
FROM pg_roles
WHERE rolname IN (
    '$script:TicketboxC07OwnerRole',
    '$script:TicketboxC07MigratorRole',
    '$script:TicketboxC07RuntimeRole'
)
ORDER BY rolname;
COMMIT;
"@
}

function Renew-TicketboxC07FrozenMigratorCredentialWindow {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")][string]$Mode
    )

    Assert-TicketboxC07MigratorCredentialWindow $MigratorValidUntilUtc
    $runtimeVerifier = ConvertTo-TicketboxC07ScramVerifier $RuntimePassword
    $migratorVerifier = ConvertTo-TicketboxC07ScramVerifier $MigratorPassword
    Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (Get-TicketboxC07RoleBootstrapSql `
            -RuntimeVerifier $runtimeVerifier `
            -MigratorVerifier $migratorVerifier `
            -MigratorValidUntilUtc $MigratorValidUntilUtc `
            -OperationId $OperationId `
            -Mode $Mode `
            -RuntimeAdmissionState "frozen") `
        -Label "C07 frozen migrator credential-window renewal" | Out-Null
    Assert-TicketboxC07MigratorCredential `
        -Authority $Authority `
        -MigratorPassword $MigratorPassword
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
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

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
    (COALESCE((SELECT rolcanlogin AND rolinherit AND NOT rolsuper AND NOT rolcreatedb
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
        [switch]$IncludeManagedSchemaCurrencyAuthority
    )
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
        has_database_privilege(
            '$script:TicketboxC07RuntimeRole',
            current_database(),
            'CONNECT'
        )
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
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
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
            -IncludeManagedSchemaCurrencyAuthority) `
        -Label "managed schema exact runtime ACL application" | Out-Null
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -IncludeManagedSchemaCurrencyAuthority
}

function Assert-TicketboxC07RoleCredentials {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword
    )

    foreach ($probe in @(
        [pscustomobject]@{
            Role = $script:TicketboxC07RuntimeRole
            Password = $RuntimePassword
        },
        [pscustomobject]@{
            Role = $script:TicketboxC07MigratorRole
            Password = $MigratorPassword
        }
    )) {
        $output = Invoke-TicketboxC07Sql `
            -Authority $Authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role ([string]$probe.Role) `
            -Password $probe.Password `
            -Label "C07 durable credential authority probe" `
            -Sql (
                "SELECT current_user || E'\t' || " +
                "current_setting('search_path');"
            )
        $fields = ConvertFrom-TicketboxC07SingleRow `
            -Output $output `
            -FieldCount 2 `
            -Label "C07 durable credential authority probe"
        if (
            $fields[0] -cne [string]$probe.Role -or
            $fields[1] -cne "pg_catalog, public"
        ) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 durable credential/search_path authority 不匹配。" `
                -FailureCode "role_authority_invariant_failed")
        }
    }
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

function Assert-TicketboxC07LegacyClusterSurface {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][uint32]$LegacyRoleOid
    )

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 legacy cross-database authority preflight" `
        -Sql @"
SELECT (
    NOT EXISTS (
        SELECT 1
        FROM pg_database
        WHERE datallowconn
          AND NOT datistemplate
          AND datname NOT IN ('postgres', '$script:TicketboxC07DatabaseName')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_database
        WHERE datname <> '$script:TicketboxC07DatabaseName'
          AND datdba = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_database AS database,
             LATERAL aclexplode(
                 COALESCE(database.datacl, acldefault('d', database.datdba))
             ) AS acl
        WHERE database.datname <> '$script:TicketboxC07DatabaseName'
          AND acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_namespace
        WHERE nspname !~ '^pg_'
          AND nspname <> 'information_schema'
          AND nspowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND relation.relowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND routine.proowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_type AS type
        JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND type.typowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_namespace AS namespace,
             LATERAL aclexplode(
                 COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
             ) AS acl
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
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
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(routine.proacl, acldefault('f', routine.proowner))
        ) AS acl
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_type AS type
        JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
        CROSS JOIN LATERAL aclexplode(
            COALESCE(type.typacl, acldefault('T', type.typowner))
        ) AS acl
        WHERE namespace.nspname !~ '^pg_'
          AND namespace.nspname <> 'information_schema'
          AND acl.grantee = $LegacyRoleOid
    )
)::text;
"@
    if ($output.Trim() -cne "true") {
        throw (
            "C07 legacy role 存在跨数据库 owner/ACL surface，" +
            "或 managed cluster 含未登记 database；零 mutation 拒绝。"
        )
    }
}

function Assert-TicketboxC07LegacyRoleRetired {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][uint32]$LegacyRoleOid
    )

    $cluster = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 legacy cluster retirement postcondition" `
        -Sql @"
SELECT (
    EXISTS (
        SELECT 1
        FROM pg_authid
        WHERE oid = $LegacyRoleOid
          AND rolname = '$script:TicketboxC07LegacyRuntimeRole'
          AND NOT rolcanlogin
          AND rolpassword IS NULL
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_auth_members
        WHERE roleid = $LegacyRoleOid OR member = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE usesysid = $LegacyRoleOid
          AND pid <> pg_backend_pid()
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_database WHERE datdba = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_database AS database,
             LATERAL aclexplode(
                 COALESCE(database.datacl, acldefault('d', database.datdba))
             ) AS acl
        WHERE acl.grantee = $LegacyRoleOid
    )
)::text;
"@
    if ($cluster.Trim() -cne "true") {
        throw "C07 legacy cluster role/membership/session/ACL 尚未退休。"
    }
    $database = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 legacy database retirement postcondition" `
        -Sql @"
SELECT (
    NOT EXISTS (
        SELECT 1
        FROM pg_namespace
        WHERE nspowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_class WHERE relowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typowner = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_namespace AS namespace,
             LATERAL aclexplode(
                 COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
             ) AS acl
        WHERE acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_class AS relation
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
        WHERE acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        CROSS JOIN LATERAL aclexplode(
            COALESCE(routine.proacl, acldefault('f', routine.proowner))
        ) AS acl
        WHERE acl.grantee = $LegacyRoleOid
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_type AS type
        CROSS JOIN LATERAL aclexplode(
            COALESCE(type.typacl, acldefault('T', type.typowner))
        ) AS acl
        WHERE acl.grantee = $LegacyRoleOid
    )
)::text;
"@
    if ($database.Trim() -cne "true") {
        throw "C07 legacy role 仍拥有 live database object。"
    }
}

function ConvertTo-TicketboxC07ProductionRevision {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -cnotmatch '^[A-Za-z0-9_]{1,128}$') {
        throw "$Label 不是 canonical Alembic revision。"
    }
    return $Value
}

function New-TicketboxC07ProductionMarker {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "migration_started",
            "migration_completed",
            "runtime_acl_verified",
            "production_ready"
        )]
        [string]$Phase,
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RecoveryManifestSha256,
        [AllowEmptyString()][string]$MigrationEvidenceSha256 = "",
        [AllowEmptyString()][string]$RoleAuthoritySha256 = "",
        [AllowEmptyString()][string]$RuntimeAclSha256 = "",
        [AllowEmptyString()][string]$LivePostconditionsSha256 = ""
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $source = ConvertTo-TicketboxC07ProductionRevision `
        $ExpectedSourceRevision "C07 source revision"
    $target = ConvertTo-TicketboxC07ProductionRevision `
        $TargetRevision "C07 target revision"
    Assert-TicketboxC07DatabaseSha256 `
        $RecoveryManifestSha256 "C07 recovery manifest"
    $zero = "0" * 64
    $hashes = @(
        $MigrationEvidenceSha256,
        $RoleAuthoritySha256,
        $RuntimeAclSha256,
        $LivePostconditionsSha256
    )
    for ($index = 0; $index -lt $hashes.Count; $index++) {
        if ([string]::IsNullOrEmpty([string]$hashes[$index])) {
            $hashes[$index] = $zero
        }
        Assert-TicketboxC07DatabaseSha256 `
            ([string]$hashes[$index]) "C07 production marker hash"
    }
    return (
        "$script:TicketboxC07ProductionMarkerSchema|" +
        "$($operation.ToString('D'))|$Mode|$Phase|" +
        "$($Catalog.ClusterSystemIdentifier)|$($Catalog.DatabaseOid)|" +
        "$source|$target|$RecoveryManifestSha256|" +
        "$($hashes[0])|$($hashes[1])|$($hashes[2])|$($hashes[3])"
    )
}

function Assert-TicketboxC07ProductionMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$RecoveryManifestSha256
    )

    $parts = @(([string]$Catalog.Marker).Split([char]"|"))
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $source = ConvertTo-TicketboxC07ProductionRevision `
        $ExpectedSourceRevision "C07 source revision"
    $target = ConvertTo-TicketboxC07ProductionRevision `
        $TargetRevision "C07 target revision"
    Assert-TicketboxC07DatabaseSha256 `
        $RecoveryManifestSha256 "C07 recovery manifest"
    if (
        $parts.Count -ne 13 -or
        $parts[0] -cne $script:TicketboxC07ProductionMarkerSchema -or
        $parts[1] -cne $operation.ToString("D") -or
        $parts[2] -cne $Mode -or
        $parts[3] -cnotin @(
            "migration_started",
            "migration_completed",
            "runtime_acl_verified",
            "production_ready"
        ) -or
        $parts[4] -cne [string]$Catalog.ClusterSystemIdentifier -or
        $parts[5] -cne [string]$Catalog.DatabaseOid -or
        $parts[6] -cne $source -or
        $parts[7] -cne $target -or
        $parts[8] -cne $RecoveryManifestSha256
    ) {
        throw "C07 production marker 与 operation/live database/recovery 不一致。"
    }
    foreach ($index in 9..12) {
        Assert-TicketboxC07DatabaseSha256 `
            $parts[$index] "C07 production marker hash"
    }
    $zero = "0" * 64
    $phaseShapeValid = switch ($parts[3]) {
        "migration_started" {
            $parts[9] -ceq $zero -and
            $parts[10] -ceq $zero -and
            $parts[11] -ceq $zero -and
            $parts[12] -ceq $zero
        }
        "migration_completed" {
            $parts[9] -cne $zero -and
            $parts[10] -ceq $zero -and
            $parts[11] -ceq $zero -and
            $parts[12] -ceq $zero
        }
        "runtime_acl_verified" {
            $parts[9] -cne $zero -and
            $parts[10] -cne $zero -and
            $parts[11] -cne $zero -and
            $parts[12] -ceq $zero
        }
        "production_ready" {
            $parts[9] -cne $zero -and
            $parts[10] -cne $zero -and
            $parts[11] -cne $zero -and
            $parts[12] -cne $zero
        }
        default { $false }
    }
    if (-not $phaseShapeValid) {
        throw "C07 production marker phase/hash shape 无效。"
    }
    return [pscustomobject]@{
        Phase = $parts[3]
        MigrationEvidenceSha256 = $parts[9]
        RoleAuthoritySha256 = $parts[10]
        RuntimeAclSha256 = $parts[11]
        LivePostconditionsSha256 = $parts[12]
    }
}

function Get-TicketboxC07ProductionDatabaseState {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 production database state" `
        -Sql @"
SELECT
    (SELECT system_identifier::text FROM pg_control_system()) || E'\t' ||
    (SELECT oid::text FROM pg_database WHERE datname = current_database()) || E'\t' ||
    COALESCE((SELECT value FROM public.app_meta WHERE key = 'server_id'), '') || E'\t' ||
    COALESCE((SELECT value FROM public.app_meta WHERE key = 'data_generation'), '') || E'\t' ||
    COALESCE((
        SELECT string_agg(version_num, ',' ORDER BY version_num)
        FROM public.alembic_version
    ), '');
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 5 `
        -Label "C07 production database state"
    if (
        $fields[0] -cnotmatch '^[1-9][0-9]{0,19}$' -or
        $fields[1] -cnotmatch '^[1-9][0-9]{0,9}$' -or
        $fields[2] -cnotmatch (
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-' +
            '[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        ) -or
        $fields[3] -cnotmatch (
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-' +
            '[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        )
    ) {
        throw "C07 production database logical/physical identity 无效。"
    }
    return [pscustomobject]@{
        ClusterSystemIdentifier = $fields[0]
        DatabaseOid = [uint32]$fields[1]
        LogicalServerId = $fields[2]
        DataGeneration = $fields[3]
        AlembicRevision = $fields[4]
    }
}

function Assert-TicketboxC07ProductionRecoveryBinding {
    param(
        [Parameter(Mandatory = $true)][object]$RecoveryGeneration,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][object]$DatabaseState
    )

    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $RecoveryGeneration `
        -Names @(
            "Payload",
            "PayloadSha256",
            "ManifestPath",
            "DumpPath",
            "InventoryPath",
            "CopiesPath"
        ) `
        -Label "C07 strong recovery generation"
    if (
        $null -eq (
            Get-Command Assert-TicketboxC07RecoveryGenerationFiles `
                -ErrorAction SilentlyContinue
        )
    ) {
        throw "C07 production coordinator 缺少 recovery file authority validator。"
    }
    Assert-TicketboxC07RecoveryGenerationFiles $RecoveryGeneration | Out-Null
    $payload = $RecoveryGeneration.Payload
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload `
        -Names @(
            "schema",
            "operation_id",
            "release",
            "lifecycle",
            "integrity",
            "database",
            "asset_inventory",
            "original_copies"
        ) `
        -Label "C07 recovery payload"
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload.release `
        -Names @(
            "fingerprint",
            "installation_id",
            "build_manifest_sha256",
            "backend_version"
        ) `
        -Label "C07 recovery release binding"
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload.database `
        -Names @(
            "name",
            "cluster_system_identifier",
            "source_database_oid",
            "server_id",
            "data_generation",
            "alembic_heads",
            "dump_sha256",
            "money_facts_sha256"
        ) `
        -Label "C07 recovery database binding"
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload.lifecycle `
        -Names @(
            "stage",
            "operation_kind",
            "target_alembic_revision",
            "revision_manifest_sha256",
            "authority_chain_sha256",
            "freeze_proof_sha256",
            "freeze_heartbeat_sequence"
        ) `
        -Label "C07 recovery root lifecycle binding" `
        -Exact
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $source = ConvertTo-TicketboxC07ProductionRevision `
        $ExpectedSourceRevision "C07 source revision"
    Assert-TicketboxC07DatabaseSha256 `
        ([string]$RecoveryGeneration.PayloadSha256) "C07 recovery manifest"
    foreach ($hostDigest in @(
        [string]$payload.release.fingerprint,
        [string]$payload.release.build_manifest_sha256
    )) {
        Assert-TicketboxC07HostSha256 $hostDigest "C07 recovery host digest"
    }
    foreach ($digest in @(
        [string]$payload.database.dump_sha256,
        [string]$payload.database.money_facts_sha256,
        [string]$payload.asset_inventory.sha256,
        [string]$payload.original_copies.sha256
    )) {
        Assert-TicketboxC07DatabaseSha256 $digest "C07 recovery bound digest"
    }
    foreach ($lifecycleDigest in @(
        [string]$payload.lifecycle.authority_chain_sha256,
        [string]$payload.lifecycle.freeze_proof_sha256,
        [string]$payload.lifecycle.revision_manifest_sha256
    )) {
        Assert-TicketboxC07HostSha256 `
            $lifecycleDigest "C07 recovery root lifecycle digest"
    }
    $installation = [Guid]::Empty
    if (
        [string]$payload.schema -cne "ticketbox-c07-recovery-generation-v3" -or
        [string]$payload.operation_id -cne $operation.ToString("D") -or
        [string]$payload.lifecycle.stage -cne "writers_frozen" -or
        [int64]$payload.lifecycle.freeze_heartbeat_sequence -lt 1 -or
        -not [Guid]::TryParseExact(
            [string]$payload.release.installation_id,
            "D",
            [ref]$installation
        ) -or
        $installation -eq [Guid]::Empty -or
        [string]$payload.release.installation_id -cne
            $installation.ToString("D") -or
        [string]$payload.database.name -cne $script:TicketboxC07DatabaseName -or
        [string]$payload.integrity.scope -cne "acl_hash_only" -or
        [bool]$payload.integrity.malicious_writer_resistance -or
        [string]$payload.database.cluster_system_identifier -cne
            [string]$DatabaseState.ClusterSystemIdentifier -or
        [uint32]$payload.database.source_database_oid -ne
            [uint32]$DatabaseState.DatabaseOid -or
        [string]$payload.database.server_id -cne
            [string]$DatabaseState.LogicalServerId -or
        [string]$payload.database.data_generation -cne
            [string]$DatabaseState.DataGeneration -or
        @($payload.database.alembic_heads).Count -ne 1 -or
        [string]@($payload.database.alembic_heads)[0] -cne $source
    ) {
        throw "C07 recovery generation 与 operation/live source authority 不一致。"
    }
    return [pscustomobject]@{
        ManifestSha256 = [string]$RecoveryGeneration.PayloadSha256
        DumpSha256 = [string]$payload.database.dump_sha256
        MoneyFactsSha256 = [string]$payload.database.money_facts_sha256
        InventorySha256 = [string]$payload.asset_inventory.sha256
        CopiesSha256 = [string]$payload.original_copies.sha256
        IntegrityScope = [string]$payload.integrity.scope
        ReleaseFingerprint = [string]$payload.release.fingerprint
        InstallationId = [string]$payload.release.installation_id
        BuildManifestSha256 = [string]$payload.release.build_manifest_sha256
        BackendVersion = [string]$payload.release.backend_version
        RootAuthorityChainSha256 =
            [string]$payload.lifecycle.authority_chain_sha256
        RootFreezeProofSha256 =
            [string]$payload.lifecycle.freeze_proof_sha256
        RootHeartbeatSequence =
            [int64]$payload.lifecycle.freeze_heartbeat_sequence
    }
}

function Assert-TicketboxC07ProductionLifecycleBinding {
    param(
        [Parameter(Mandatory = $true)][object]$LifecycleAuthority,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$Recovery,
        [Parameter(Mandatory = $true)][string]$ExpectedStage,
        [Parameter(Mandatory = $true)][int64]$ExpectedStageSequence,
        [string]$ExpectedTargetRecoveryManifestSha256 = ""
    )

    $properties = @(
        "schema",
        "operation_id",
        "root_authority_chain_sha256",
        "current_authority_chain_sha256",
        "current_receipt_payload_sha256",
        "current_stage",
        "current_stage_sequence",
        "current_coordinator_binding_sha256",
        "current_coordinator_binding_sequence",
        "current_heartbeat_sequence",
        "current_freeze_proof_sha256",
        "recovery_manifest_sha256",
        "target_recovery_manifest_sha256"
    )
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $LifecycleAuthority `
        -Names $properties `
        -Label "C07 production lifecycle authority binding" `
        -Exact
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    foreach ($digestName in @(
        "root_authority_chain_sha256",
        "current_authority_chain_sha256",
        "current_receipt_payload_sha256",
        "current_coordinator_binding_sha256",
        "current_freeze_proof_sha256",
        "recovery_manifest_sha256",
        "target_recovery_manifest_sha256"
    )) {
        if (
            [string]$LifecycleAuthority.$digestName -cnotmatch
                '^[0-9A-F]{64}$'
        ) {
            throw "C07 production lifecycle authority $digestName 不是 canonical SHA-256。"
        }
    }
    $stageSequence = [int64]0
    $bindingSequence = [int64]0
    $heartbeatSequence = [int64]0
    if ([string]::IsNullOrEmpty($ExpectedTargetRecoveryManifestSha256)) {
        $ExpectedTargetRecoveryManifestSha256 = "0" * 64
    }
    if ($ExpectedTargetRecoveryManifestSha256 -cnotmatch '^[0-9A-F]{64}$') {
        throw "C07 target recovery lifecycle binding 不是 canonical SHA-256。"
    }
    if (
        [string]$LifecycleAuthority.schema -cne
            $script:TicketboxC07ProductionLifecycleBindingSchema -or
        [string]$LifecycleAuthority.operation_id -cne
            $operation.ToString("D") -or
        [string]$LifecycleAuthority.root_authority_chain_sha256 -cne
            [string]$Recovery.RootAuthorityChainSha256 -or
        [string]$LifecycleAuthority.recovery_manifest_sha256 -cne
            ([string]$Recovery.ManifestSha256).ToUpperInvariant() -or
        [string]$LifecycleAuthority.target_recovery_manifest_sha256 -cne
            $ExpectedTargetRecoveryManifestSha256 -or
        [string]$LifecycleAuthority.current_stage -cne $ExpectedStage -or
        -not [int64]::TryParse(
            [string]$LifecycleAuthority.current_stage_sequence,
            [ref]$stageSequence
        ) -or
        $stageSequence -ne $ExpectedStageSequence -or
        -not [int64]::TryParse(
            [string]$LifecycleAuthority.current_coordinator_binding_sequence,
            [ref]$bindingSequence
        ) -or
        $bindingSequence -lt 0 -or
        -not [int64]::TryParse(
            [string]$LifecycleAuthority.current_heartbeat_sequence,
            [ref]$heartbeatSequence
        ) -or
        $heartbeatSequence -lt 1
    ) {
        throw "C07 production lifecycle root/current authority binding 不一致。"
    }
    return [pscustomobject]@{
        RootAuthorityChainSha256 =
            [string]$LifecycleAuthority.root_authority_chain_sha256
        CurrentAuthorityChainSha256 =
            [string]$LifecycleAuthority.current_authority_chain_sha256
        CurrentReceiptPayloadSha256 =
            [string]$LifecycleAuthority.current_receipt_payload_sha256
        CurrentStage = [string]$LifecycleAuthority.current_stage
        CurrentStageSequence = $stageSequence
        CurrentCoordinatorBindingSha256 =
            [string]$LifecycleAuthority.current_coordinator_binding_sha256
        CurrentCoordinatorBindingSequence = $bindingSequence
        CurrentHeartbeatSequence = $heartbeatSequence
        CurrentFreezeProofSha256 =
            [string]$LifecycleAuthority.current_freeze_proof_sha256
        RecoveryManifestSha256 =
            [string]$LifecycleAuthority.recovery_manifest_sha256
        TargetRecoveryManifestSha256 =
            [string]$LifecycleAuthority.target_recovery_manifest_sha256
    }
}

function Get-TicketboxC07MigrationEvidenceSha256 {
    param(
        [Parameter(Mandatory = $true)][object]$Evidence,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    if (
        [string]$Evidence.schema -ceq
            $script:TicketboxC07ResourceMigrationEvidenceSchema
    ) {
        Assert-TicketboxC07DatabaseRequiredProperties `
            -Value $Evidence `
            -Names @(
                "schema",
                "operation_id",
                "source_revision",
                "target_revision",
                "result",
                "alembic_revision",
                "resource_shape_sha256",
                "money_facts_sha256",
                "statistics_table_count",
                "statistics_table_set_sha256"
            ) `
            -Label "C07 resource-attested migration evidence" `
            -Exact
        if (
            [string]$Evidence.operation_id -cne
                $operation.ToString("D") -or
            [string]$Evidence.source_revision -cne
                $ExpectedSourceRevision -or
            [string]$Evidence.target_revision -cne $TargetRevision -or
            [string]$Evidence.alembic_revision -cne $TargetRevision -or
            [string]$Evidence.result -cnotin @(
                "target_committed",
                "target_observed_after_interruption"
            )
        ) {
            throw (
                "C07 resource-attested migration evidence 与 " +
                "operation/revision 不一致。"
            )
        }
        foreach ($field in @(
            "resource_shape_sha256",
            "money_facts_sha256",
            "statistics_table_set_sha256"
        )) {
            Assert-TicketboxC07DatabaseSha256 `
                -Value ([string]$Evidence.$field) `
                -Label "C07 migration $field"
        }
        if ([int]$Evidence.statistics_table_count -ne 18) {
            throw "C07 migration statistics table count 不完整。"
        }
        $canonical = @(
            "schema=$($Evidence.schema)",
            "operation_id=$($Evidence.operation_id)",
            "source_revision=$($Evidence.source_revision)",
            "target_revision=$($Evidence.target_revision)",
            "result=target_committed",
            "alembic_revision=$($Evidence.alembic_revision)",
            "resource_shape_sha256=$($Evidence.resource_shape_sha256)",
            "money_facts_sha256=$($Evidence.money_facts_sha256)",
            "statistics_table_count=$($Evidence.statistics_table_count)",
            "statistics_table_set_sha256=$($Evidence.statistics_table_set_sha256)"
        ) -join "`n"
        return Get-TicketboxC07DatabaseTextSha256 $canonical
    }
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $Evidence `
        -Names @(
            "schema",
            "operation_id",
            "source_revision",
            "target_revision",
            "result",
            "alembic_revision",
            "money_facts_sha256",
            "statistics_table_count",
            "statistics_table_set_sha256"
        ) `
        -Label "C07 migration evidence" `
        -Exact
    if (
        [string]$Evidence.schema -cne $script:TicketboxC07MigrationEvidenceSchema -or
        [string]$Evidence.operation_id -cne $operation.ToString("D") -or
        [string]$Evidence.source_revision -cne $ExpectedSourceRevision -or
        [string]$Evidence.target_revision -cne $TargetRevision -or
        [string]$Evidence.alembic_revision -cne $TargetRevision -or
        [string]$Evidence.result -cnotin @(
            "target_committed",
            "target_observed_after_interruption"
        )
    ) {
        throw "C07 migration evidence 与 operation/revision 不一致。"
    }
    Assert-TicketboxC07DatabaseSha256 `
        -Value ([string]$Evidence.money_facts_sha256) `
        -Label "C07 migration canonical money facts"
    Assert-TicketboxC07DatabaseSha256 `
        -Value ([string]$Evidence.statistics_table_set_sha256) `
        -Label "C07 migration statistics table set"
    if ([int]$Evidence.statistics_table_count -ne 18) {
        throw "C07 migration statistics table count 不完整。"
    }
    $canonical = @(
        "schema=$($Evidence.schema)",
        "operation_id=$($Evidence.operation_id)",
        "source_revision=$($Evidence.source_revision)",
        "target_revision=$($Evidence.target_revision)",
        "result=target_committed",
        "alembic_revision=$($Evidence.alembic_revision)",
        "money_facts_sha256=$($Evidence.money_facts_sha256)",
        "statistics_table_count=$($Evidence.statistics_table_count)",
        "statistics_table_set_sha256=$($Evidence.statistics_table_set_sha256)"
    ) -join "`n"
    return Get-TicketboxC07DatabaseTextSha256 $canonical
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
             COALESCE(database.datacl, acldefault('d', database.datdba))
         ) AS acl
    WHERE database.datname = current_database()
    UNION ALL
    SELECT 'schema', namespace.nspname,
           COALESCE(pg_get_userbyid(acl.grantee), 'PUBLIC'),
           acl.privilege_type, acl.is_grantable
    FROM pg_namespace AS namespace,
         LATERAL aclexplode(
             COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
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
        COALESCE(routine.proacl, acldefault('f', routine.proowner))
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
        COALESCE(routine.proacl, acldefault('f', routine.proowner))
    ) AS acl
    WHERE routine.oid = 'pg_catalog.pg_control_system()'::regprocedure
)
SELECT kind || E'\t' || object_name || E'\t' || grantee || E'\t' ||
       privilege_type || E'\t' || is_grantable::text
FROM acl_rows
ORDER BY kind, object_name, grantee, privilege_type, is_grantable;
"@
    return Get-TicketboxC07DatabaseTextSha256 ([string]$evidence).Trim()
}

function Get-TicketboxC07MigratorRetirementState {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )

    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 migrator retirement state" `
        -Sql @"
SELECT
    role.rolcanlogin::text || E'\t' ||
    (role.rolpassword IS NOT NULL)::text || E'\t' ||
    (
        SELECT count(*)::text FROM pg_auth_members
        WHERE roleid = role.oid OR member = role.oid
    ) || E'\t' ||
    (
        SELECT count(*)::text FROM pg_stat_activity
        WHERE usesysid = role.oid AND pid <> pg_backend_pid()
    ) || E'\t' ||
    has_database_privilege(
        role.rolname,
        '$script:TicketboxC07DatabaseName',
        'CONNECT'
    )::text
FROM pg_authid AS role
WHERE role.rolname = '$script:TicketboxC07MigratorRole';
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 5 `
        -Label "C07 migrator retirement state"
    return [pscustomobject]@{
        CanLogin = $fields[0] -ceq "true"
        PasswordPresent = $fields[1] -ceq "true"
        MembershipCount = [int]$fields[2]
        SessionCount = [int]$fields[3]
        CanConnect = $fields[4] -ceq "true"
        IsActive = (
            $fields[0] -ceq "true" -and
            $fields[1] -ceq "true" -and
            [int]$fields[2] -eq 1 -and
            $fields[4] -ceq "true"
        )
        IsRetired = (
            $fields[0] -ceq "false" -and
            $fields[1] -ceq "false" -and
            [int]$fields[2] -eq 0 -and
            [int]$fields[3] -eq 0 -and
            $fields[4] -ceq "false"
        )
    }
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

function Get-TicketboxC07ProductionLiveState {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )

    $legacyPostcondition = @"
NOT EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = '$script:TicketboxC07LegacyRuntimeRole'
)
"@
    if ($Mode -ceq "legacy_adoption") {
        $legacyPostcondition = @"
EXISTS (
    SELECT 1
    FROM pg_authid
    WHERE rolname = '$script:TicketboxC07LegacyRuntimeRole'
      AND NOT rolcanlogin
      AND rolpassword IS NULL
)
"@
    }
    $financialAppendTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeFinancialAppendTables
    )
    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 production live postconditions" `
        -Sql @"
WITH role_ids AS (
    SELECT
        (SELECT oid FROM pg_roles
         WHERE rolname = '$script:TicketboxC07OwnerRole') AS owner_oid,
        (SELECT oid FROM pg_roles
         WHERE rolname = '$script:TicketboxC07MigratorRole') AS migrator_oid,
        (SELECT oid FROM pg_roles
         WHERE rolname = '$script:TicketboxC07RuntimeRole') AS runtime_oid,
        (SELECT oid FROM pg_roles
         WHERE rolname = '$script:TicketboxC07LegacyRuntimeRole') AS legacy_oid
)
SELECT
    (
        SELECT count(*)::text
        FROM pg_stat_activity, role_ids
        WHERE usesysid = role_ids.legacy_oid
          AND pid <> pg_backend_pid()
    ) || E'\t' ||
    (
        SELECT count(*)::text
        FROM pg_stat_activity, role_ids
        WHERE usesysid = role_ids.migrator_oid
          AND pid <> pg_backend_pid()
    ) || E'\t' ||
    (
        SELECT rolcanlogin::text
        FROM pg_authid
        WHERE rolname = '$script:TicketboxC07MigratorRole'
    ) || E'\t' ||
    (
        SELECT (rolpassword IS NOT NULL)::text
        FROM pg_authid
        WHERE rolname = '$script:TicketboxC07MigratorRole'
    ) || E'\t' ||
    (
        EXISTS (
            SELECT 1 FROM pg_roles
            WHERE rolname = '$script:TicketboxC07OwnerRole'
              AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
              AND NOT rolcreatedb AND NOT rolcreaterole
              AND NOT rolreplication AND NOT rolbypassrls
        )
        AND EXISTS (
            SELECT 1 FROM pg_authid
            WHERE rolname = '$script:TicketboxC07RuntimeRole'
              AND rolcanlogin AND rolinherit AND NOT rolsuper
              AND NOT rolcreatedb AND NOT rolcreaterole
              AND NOT rolreplication AND NOT rolbypassrls
              AND rolpassword IS NOT NULL
        )
        AND EXISTS (
            SELECT 1 FROM pg_authid
            WHERE rolname = '$script:TicketboxC07MigratorRole'
              AND NOT rolcanlogin AND NOT rolsuper
              AND NOT rolcreatedb AND NOT rolcreaterole
              AND NOT rolreplication AND NOT rolbypassrls
              AND rolpassword IS NULL
        )
        AND $legacyPostcondition
        AND NOT EXISTS (
            SELECT 1
            FROM pg_auth_members AS membership, role_ids
            WHERE membership.roleid IN (
                      role_ids.owner_oid,
                      role_ids.migrator_oid,
                      role_ids.runtime_oid,
                      role_ids.legacy_oid
                  )
               OR membership.member IN (
                      role_ids.owner_oid,
                      role_ids.migrator_oid,
                      role_ids.runtime_oid,
                      role_ids.legacy_oid
                  )
        )
        AND (
            SELECT pg_get_userbyid(datdba) = '$script:TicketboxC07OwnerRole'
            FROM pg_database WHERE datname = current_database()
        )
        AND (
            SELECT pg_get_userbyid(nspowner) = '$script:TicketboxC07OwnerRole'
            FROM pg_namespace WHERE nspname = 'public'
        )
        AND has_database_privilege(
            '$script:TicketboxC07RuntimeRole',
            current_database(),
            'CONNECT'
        )
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
        AND NOT has_database_privilege(
            '$script:TicketboxC07MigratorRole',
            current_database(),
            'CONNECT'
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
        AND NOT EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = ANY($financialAppendTables)
              AND (
                  has_table_privilege(
                      '$script:TicketboxC07RuntimeRole',
                      relation.oid,
                      'UPDATE'
                  )
                  OR has_table_privilege(
                      '$script:TicketboxC07RuntimeRole',
                      relation.oid,
                      'DELETE'
                  )
                  OR has_table_privilege(
                      '$script:TicketboxC07RuntimeRole',
                      relation.oid,
                      'TRUNCATE'
                  )
              )
        )
    )::text;
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 5 `
        -Label "C07 production live postconditions"
    if (
        $fields[0] -cnotmatch '^[0-9]+$' -or
        $fields[1] -cnotmatch '^[0-9]+$' -or
        $fields[2] -cnotin @("true", "false") -or
        $fields[3] -cnotin @("true", "false") -or
        $fields[4] -cne "true"
    ) {
        throw "C07 production live role/session/ACL postcondition 不成立。"
    }
    return [pscustomobject]@{
        LegacySessionCount = [int]$fields[0]
        MigratorSessionCount = [int]$fields[1]
        MigratorCanLogin = $fields[2] -ceq "true"
        MigratorPasswordPresent = $fields[3] -ceq "true"
    }
}

function Assert-TicketboxC07ProductionTargetRecoveryBinding {
    param(
        [Parameter(Mandatory = $true)][object]$TargetRecoveryGeneration,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][object]$DatabaseState
    )
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $TargetRecoveryGeneration `
        -Names @(
            "Payload",
            "PayloadSha256",
            "ManifestPath",
            "DumpPath",
            "InventoryPath",
            "CopiesPath",
            "RestoreEvidence"
        ) `
        -Label "C07 post-DDL target recovery generation"
    if (
        $null -eq (
            Get-Command Assert-TicketboxC07TargetRecoveryGenerationFiles `
                -ErrorAction SilentlyContinue
        )
    ) {
        throw "C07 production coordinator 缺少 target recovery validator。"
    }
    Assert-TicketboxC07TargetRecoveryGenerationFiles `
        $TargetRecoveryGeneration | Out-Null
    $payload = $TargetRecoveryGeneration.Payload
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload `
        -Names @(
            "schema",
            "operation_id",
            "generation_kind",
            "release",
            "lifecycle",
            "integrity",
            "database",
            "asset_inventory",
            "original_copies"
        ) `
        -Label "C07 target recovery payload"
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload.database `
        -Names @(
            "name",
            "cluster_system_identifier",
            "source_database_oid",
            "server_id",
            "data_generation",
            "alembic_heads",
            "dump_sha256",
            "money_facts_sha256",
            "resource_shape_sha256"
        ) `
        -Label "C07 target recovery database binding"
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $target = ConvertTo-TicketboxC07ProductionRevision `
        $TargetRevision "C07 target recovery revision"
    foreach ($digest in @(
        [string]$TargetRecoveryGeneration.PayloadSha256,
        [string]$payload.database.dump_sha256,
        [string]$payload.database.money_facts_sha256,
        [string]$payload.database.resource_shape_sha256,
        [string]$TargetRecoveryGeneration.RestoreEvidence.PayloadSha256
    )) {
        Assert-TicketboxC07DatabaseSha256 `
            $digest "C07 target recovery digest"
    }
    if (
        [string]$payload.schema -cne
            "ticketbox-c07-target-recovery-generation-v2" -or
        [string]$payload.operation_id -cne
            $operation.ToString("D") -or
        [string]$payload.generation_kind -cne "post_ddl_target" -or
        [string]$payload.database.name -cne
            $script:TicketboxC07DatabaseName -or
        [string]$payload.database.cluster_system_identifier -cne
            [string]$DatabaseState.ClusterSystemIdentifier -or
        [uint32]$payload.database.source_database_oid -ne
            [uint32]$DatabaseState.DatabaseOid -or
        [string]$payload.database.server_id -cne
            [string]$DatabaseState.LogicalServerId -or
        [string]$payload.database.data_generation -cne
            [string]$DatabaseState.DataGeneration -or
        @($payload.database.alembic_heads).Count -ne 1 -or
        [string]@($payload.database.alembic_heads)[0] -cne $target -or
        [string]$TargetRecoveryGeneration.RestoreEvidence.Payload.resource_shape_sha256 -cne
            [string]$payload.database.resource_shape_sha256 -or
        [string]$TargetRecoveryGeneration.RestoreEvidence.Payload.money_facts_sha256 -cne
            [string]$payload.database.money_facts_sha256
    ) {
        throw "C07 target recovery generation 与 live target authority 不一致。"
    }
    return [pscustomobject]@{
        ManifestSha256 =
            [string]$TargetRecoveryGeneration.PayloadSha256
        DumpSha256 = [string]$payload.database.dump_sha256
        MoneyFactsSha256 =
            [string]$payload.database.money_facts_sha256
        ResourceShapeSha256 =
            [string]$payload.database.resource_shape_sha256
        InventorySha256 = [string]$payload.asset_inventory.sha256
        CopiesSha256 = [string]$payload.original_copies.sha256
        IntegrityScope = [string]$payload.integrity.scope
        RestoreEvidenceSha256 =
            [string]$TargetRecoveryGeneration.RestoreEvidence.PayloadSha256
    }
}

function New-TicketboxC07ProductionResult {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][object]$Recovery,
        [Parameter(Mandatory = $true)][object]$DatabaseState,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$MigrationEvidenceSha256,
        [Parameter(Mandatory = $true)][string]$RoleAuthoritySha256,
        [Parameter(Mandatory = $true)][string]$RuntimeAclSha256,
        [Parameter(Mandatory = $true)][object]$Live,
        [Parameter(Mandatory = $true)][string]$LivePostconditionsSha256
    )

    if (
        $null -eq $Recovery.PSObject.Properties["ResourceShapeSha256"] -or
        $null -eq $Recovery.PSObject.Properties["RestoreEvidenceSha256"]
    ) {
        throw "C07 production READY requires exact target recovery evidence。"
    }
    $payload = [ordered]@{
        schema = $script:TicketboxC07ProductionResultSchema
        operation_id = $OperationId
        mode = $Mode
        result = "production_authority_ready"
        recovery_manifest_sha256 = $Recovery.ManifestSha256
        recovery_dump_sha256 = $Recovery.DumpSha256
        recovery_inventory_sha256 = $Recovery.InventorySha256
        recovery_copies_sha256 = $Recovery.CopiesSha256
        integrity_scope = $Recovery.IntegrityScope
        cluster_system_identifier = $DatabaseState.ClusterSystemIdentifier
        database_oid = [string]$DatabaseState.DatabaseOid
        logical_server_id = $DatabaseState.LogicalServerId
        data_generation = $DatabaseState.DataGeneration
        source_alembic_revision = $ExpectedSourceRevision
        target_alembic_revision = $TargetRevision
        migration_evidence_sha256 = $MigrationEvidenceSha256
        money_facts_sha256 = $Recovery.MoneyFactsSha256
        resource_shape_sha256 = $Recovery.ResourceShapeSha256
        role_authority_sha256 = $RoleAuthoritySha256
        runtime_acl_sha256 = $RuntimeAclSha256
        legacy_session_count = [int]$Live.LegacySessionCount
        migrator_session_count = [int]$Live.MigratorSessionCount
        migrator_can_login = [bool]$Live.MigratorCanLogin
        migrator_password_present = [bool]$Live.MigratorPasswordPresent
        live_postconditions_sha256 = $LivePostconditionsSha256
        target_restore_evidence_sha256 = $Recovery.RestoreEvidenceSha256
    }
    return [pscustomobject]$payload
}

function New-TicketboxC07TargetCommitResult {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][object]$DatabaseState,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][string]$SourceRecoveryManifestSha256,
        [Parameter(Mandatory = $true)][string]$MigrationEvidenceSha256,
        [Parameter(Mandatory = $true)][object]$MigrationEvidence
    )
    foreach ($field in @(
        "resource_shape_sha256",
        "money_facts_sha256",
        "statistics_table_set_sha256"
    )) {
        Assert-TicketboxC07DatabaseSha256 `
            ([string]$MigrationEvidence.$field) "C07 target commit $field"
    }
    if ([int]$MigrationEvidence.statistics_table_count -ne 18) {
        throw "C07 target commit statistics table count 不完整。"
    }
    return [pscustomobject][ordered]@{
        schema = $script:TicketboxC07TargetCommitResultSchema
        operation_id = $OperationId
        mode = $Mode
        result = "target_committed"
        cluster_system_identifier =
            [string]$DatabaseState.ClusterSystemIdentifier
        database_oid = [string]$DatabaseState.DatabaseOid
        logical_server_id = [string]$DatabaseState.LogicalServerId
        data_generation = [string]$DatabaseState.DataGeneration
        source_alembic_revision = $ExpectedSourceRevision
        target_alembic_revision = $TargetRevision
        alembic_revision = [string]$DatabaseState.AlembicRevision
        source_recovery_manifest_sha256 =
            $SourceRecoveryManifestSha256
        migration_evidence_sha256 = $MigrationEvidenceSha256
        resource_shape_sha256 =
            [string]$MigrationEvidence.resource_shape_sha256
        money_facts_sha256 =
            [string]$MigrationEvidence.money_facts_sha256
        statistics_table_count =
            [int]$MigrationEvidence.statistics_table_count
        statistics_table_set_sha256 =
            [string]$MigrationEvidence.statistics_table_set_sha256
    }
}

function Assert-TicketboxC07PrecommittedProductionResult {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][object]$TargetRecovery,
        [Parameter(Mandatory = $true)][object]$DatabaseState,
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][object]$ExpectedResult
    )

    $resultProperties = @(
        "schema",
        "operation_id",
        "mode",
        "result",
        "recovery_manifest_sha256",
        "recovery_dump_sha256",
        "recovery_inventory_sha256",
        "recovery_copies_sha256",
        "integrity_scope",
        "cluster_system_identifier",
        "database_oid",
        "logical_server_id",
        "data_generation",
        "source_alembic_revision",
        "target_alembic_revision",
        "migration_evidence_sha256",
        "money_facts_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "legacy_session_count",
        "migrator_session_count",
        "migrator_can_login",
        "migrator_password_present",
        "live_postconditions_sha256",
        "resource_shape_sha256",
        "target_restore_evidence_sha256"
    )
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $ExpectedResult `
        -Names $resultProperties `
        -Label "C07 precommitted production result" `
        -Exact
    foreach ($field in @(
        "recovery_manifest_sha256",
        "recovery_dump_sha256",
        "recovery_inventory_sha256",
        "recovery_copies_sha256",
        "migration_evidence_sha256",
        "money_facts_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "live_postconditions_sha256",
        "resource_shape_sha256",
        "target_restore_evidence_sha256"
    )) {
        Assert-TicketboxC07DatabaseSha256 `
            ([string]$ExpectedResult.$field) `
            "C07 precommitted production $field"
    }
    if (
        [string]$ExpectedResult.schema -cne
            $script:TicketboxC07ProductionResultSchema -or
        [string]$ExpectedResult.operation_id -cne $OperationId -or
        [string]$ExpectedResult.mode -cne $Mode -or
        [string]$ExpectedResult.result -cne "production_authority_ready" -or
        [string]$ExpectedResult.recovery_manifest_sha256 -cne
            [string]$TargetRecovery.ManifestSha256 -or
        [string]$ExpectedResult.recovery_dump_sha256 -cne
            [string]$TargetRecovery.DumpSha256 -or
        [string]$ExpectedResult.recovery_inventory_sha256 -cne
            [string]$TargetRecovery.InventorySha256 -or
        [string]$ExpectedResult.recovery_copies_sha256 -cne
            [string]$TargetRecovery.CopiesSha256 -or
        [string]$ExpectedResult.integrity_scope -cne
            [string]$TargetRecovery.IntegrityScope -or
        [string]$ExpectedResult.cluster_system_identifier -cne
            [string]$DatabaseState.ClusterSystemIdentifier -or
        [string]$ExpectedResult.database_oid -cne
            [string]$DatabaseState.DatabaseOid -or
        [string]$ExpectedResult.logical_server_id -cne
            [string]$DatabaseState.LogicalServerId -or
        [string]$ExpectedResult.data_generation -cne
            [string]$DatabaseState.DataGeneration -or
        [string]$ExpectedResult.source_alembic_revision -cne
            $ExpectedSourceRevision -or
        [string]$ExpectedResult.target_alembic_revision -cne $TargetRevision -or
        [string]$DatabaseState.AlembicRevision -cne $TargetRevision -or
        [string]$ExpectedResult.money_facts_sha256 -cne
            [string]$TargetRecovery.MoneyFactsSha256 -or
        [string]$ExpectedResult.resource_shape_sha256 -cne
            [string]$TargetRecovery.ResourceShapeSha256 -or
        [string]$ExpectedResult.target_restore_evidence_sha256 -cne
            [string]$TargetRecovery.RestoreEvidenceSha256 -or
        [int]$ExpectedResult.legacy_session_count -ne 0 -or
        [int]$ExpectedResult.migrator_session_count -ne 0 -or
        [bool]$ExpectedResult.migrator_can_login -or
        [bool]$ExpectedResult.migrator_password_present
    ) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message (
                "C07 precommitted production result 与 exact target/recovery " +
                "authority 不一致。"
            ) `
            -FailureCode "authority_chain_mismatch")
    }

    $production = Assert-TicketboxC07ProductionMarker `
        -Catalog $Catalog `
        -OperationId $OperationId `
        -Mode $Mode `
        -ExpectedSourceRevision $ExpectedSourceRevision `
        -TargetRevision $TargetRevision `
        -RecoveryManifestSha256 $TargetRecovery.ManifestSha256
    if (
        [string]$production.Phase -cne "production_ready" -or
        [string]$production.MigrationEvidenceSha256 -cne
            [string]$ExpectedResult.migration_evidence_sha256 -or
        [string]$production.RoleAuthoritySha256 -cne
            [string]$ExpectedResult.role_authority_sha256 -or
        [string]$production.RuntimeAclSha256 -cne
            [string]$ExpectedResult.runtime_acl_sha256 -or
        [string]$production.LivePostconditionsSha256 -cne
            [string]$ExpectedResult.live_postconditions_sha256
    ) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 precommitted production marker 已漂移。" `
            -FailureCode "runtime_acl_invariant_failed")
    }

    $migratorState = Get-TicketboxC07MigratorRetirementState `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword
    if (-not $migratorState.IsRetired -or $migratorState.IsActive) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 precommitted production migrator retirement 已漂移。" `
            -FailureCode "role_authority_invariant_failed")
    }
    Assert-TicketboxC07RetiredRoleCatalog $Authority $SuperuserPassword
    Assert-TicketboxC07RuntimeCredential `
        -Authority $Authority `
        -RuntimePassword $RuntimePassword
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword
    $live = Get-TicketboxC07ProductionLiveState `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -Mode $Mode
    $roleAuthoritySha256 = Get-TicketboxC07RoleAuthoritySha256 `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword
    $runtimeAclSha256 = Get-TicketboxC07RuntimeAclSha256 `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword
    if (
        [int]$live.LegacySessionCount -ne 0 -or
        [int]$live.MigratorSessionCount -ne 0 -or
        [bool]$live.MigratorCanLogin -or
        [bool]$live.MigratorPasswordPresent -or
        [string]$roleAuthoritySha256 -cne
            [string]$ExpectedResult.role_authority_sha256 -or
        [string]$runtimeAclSha256 -cne
            [string]$ExpectedResult.runtime_acl_sha256
    ) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 precommitted production live role/ACL authority 已漂移。" `
            -FailureCode "runtime_acl_invariant_failed")
    }
    return $ExpectedResult
}

function Invoke-TicketboxC07ProductionAuthorityCoordinator {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [AllowNull()][Security.SecureString]$RuntimePassword,
        [AllowNull()][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
        [Parameter(Mandatory = $true)][string]$TargetRevision,
        [Parameter(Mandatory = $true)][object]$RecoveryGeneration,
        [AllowNull()][object]$TargetRecoveryGeneration,
        [AllowNull()][object]$PredecessorTargetRecoveryGeneration,
        [Parameter(Mandatory = $true)][object]$LifecycleAuthority,
        [Parameter(Mandatory = $true)][scriptblock]$MigrationAction,
        [AllowNull()][object]$SuccessorIntent,
        [AllowNull()][object]$ExpectedProductionResult,
        [switch]$StopAfterMigrationCompleted
    )

    Assert-TicketboxC07SecureString `
        $SuperuserPassword "C07 production coordinator superuser authority"
    Assert-TicketboxC07SecureString `
        $RuntimePassword "C07 production coordinator runtime credential"
    Assert-TicketboxC07SecureString `
        $MigratorPassword "C07 production coordinator migrator credential"
    Assert-TicketboxC07MigratorCredentialWindow $MigratorValidUntilUtc
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $operationText = $operation.ToString("D")
    $sourceRevision = ConvertTo-TicketboxC07ProductionRevision `
        $ExpectedSourceRevision "C07 source revision"
    $targetRevision = ConvertTo-TicketboxC07ProductionRevision `
        $TargetRevision "C07 target revision"
    if ($sourceRevision -ceq $targetRevision) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 source/target revision 不得相同。" `
            -FailureCode "release_identity_mismatch")
    }

    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    $databaseState = Get-TicketboxC07ProductionDatabaseState `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword
    $sourceRecoveryOperationId = $operationText
    $isForwardRepair = $false
    if ($null -ne $SuccessorIntent) {
        $intent = $SuccessorIntent.Payload
        if (
            [string]$intent.schema -cne
                "ticketbox-c07-successor-intent-v2" -or
            [string]$intent.successor_operation_id -cne $operationText -or
            [string]$intent.successor_mode -cne "forward_repair" -or
            [string]$intent.predecessor_terminal_stage -cne
                "repair_required" -or
            [string]$intent.live_alembic_revision -cne $targetRevision
        ) {
            throw "C07 production coordinator forward-repair intent 无效。"
        }
        $sourceRecoveryOperationId = ConvertTo-TicketboxC07OperationGuid (
            [string]$intent.predecessor_operation_id
        )
        $sourceRecoveryOperationId = $sourceRecoveryOperationId.ToString("D")
        $isForwardRepair = $true
    }
    $recovery = Assert-TicketboxC07ProductionRecoveryBinding `
        -RecoveryGeneration $RecoveryGeneration `
        -OperationId $sourceRecoveryOperationId `
        -ExpectedSourceRevision $sourceRevision `
        -DatabaseState $databaseState
    $targetRecovery = $null
    if ($null -ne $TargetRecoveryGeneration) {
        if ($StopAfterMigrationCompleted) {
            throw "C07 DDL-only coordinator 不接受 post-DDL target recovery。"
        }
        $targetRecovery = Assert-TicketboxC07ProductionTargetRecoveryBinding `
            -TargetRecoveryGeneration $TargetRecoveryGeneration `
            -OperationId $operationText `
            -TargetRevision $targetRevision `
            -DatabaseState $databaseState
    }
    $expectedLifecycleStage = "ddl_started"
    $expectedLifecycleStageSequence = [int64]4
    $expectedTargetRecoveryManifestSha256 = "0" * 64
    if ($null -ne $targetRecovery) {
        $expectedLifecycleStage = "target_isolated_restore_verified"
        $expectedLifecycleStageSequence = [int64]7
        $expectedTargetRecoveryManifestSha256 =
            ([string]$targetRecovery.ManifestSha256).ToUpperInvariant()
    }
    $lifecycle = Assert-TicketboxC07ProductionLifecycleBinding `
        -LifecycleAuthority $LifecycleAuthority `
        -OperationId $operationText `
        -Recovery $recovery `
        -ExpectedStage $expectedLifecycleStage `
        -ExpectedStageSequence $expectedLifecycleStageSequence `
        -ExpectedTargetRecoveryManifestSha256 (
            $expectedTargetRecoveryManifestSha256
        )
    $readyRecovery = if ($null -ne $targetRecovery) {
        $targetRecovery
    }
    else {
        $recovery
    }
    $catalog = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    if ($null -ne $ExpectedProductionResult) {
        if ($StopAfterMigrationCompleted -or $null -eq $targetRecovery) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message (
                    "C07 precommitted production validation 仅接受 post-DDL " +
                    "target recovery。"
                ) `
                -FailureCode "authority_chain_mismatch")
        }
        return Assert-TicketboxC07PrecommittedProductionResult `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -RuntimePassword $RuntimePassword `
            -OperationId $operationText `
            -Mode $Mode `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -TargetRecovery $targetRecovery `
            -DatabaseState $databaseState `
            -Catalog $catalog `
            -ExpectedResult $ExpectedProductionResult
    }
    $forwardTailRecovery = $null
    if ($isForwardRepair) {
        if (
            [string]::IsNullOrEmpty([string]$catalog.Marker) -or
            -not ([string]$catalog.Marker).StartsWith(
                "$script:TicketboxC07ProductionMarkerSchema|",
                [StringComparison]::Ordinal
            )
        ) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message (
                    "C07 forward-repair 缺少 predecessor durable migration marker；" +
                    "拒绝猜测 DDL 终态。"
                ) `
                -FailureCode "database_identity_or_revision_drift")
        }
        $markerParts = @(([string]$catalog.Marker).Split([char]"|"))
        if ($markerParts.Count -ne 13) {
            throw "C07 forward-repair predecessor marker shape 无效。"
        }
        if ($markerParts[1] -ceq $sourceRecoveryOperationId) {
            if (
                (Get-TicketboxC07DatabaseTextSha256 `
                    ([string]$catalog.Marker)).ToUpperInvariant() -cne
                    [string]$intent.predecessor_production_marker_sha256
            ) {
                throw (New-TicketboxC07DatabaseClassifiedFailure `
                    -Message "C07 forward-repair predecessor marker 与 immutable intent 已漂移。" `
                    -FailureCode "database_identity_or_revision_drift")
            }
            $oldMarkerPhase = [string]$markerParts[3]
            if ($oldMarkerPhase -cin @(
                "runtime_acl_verified",
                "production_ready"
            )) {
                if ($null -eq $PredecessorTargetRecoveryGeneration) {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message (
                            "C07 forward-repair tail marker 缺少 predecessor " +
                            "target recovery lineage。"
                        ) `
                        -FailureCode "authority_chain_mismatch")
                }
                $forwardTailRecovery =
                    Assert-TicketboxC07ProductionTargetRecoveryBinding `
                        -TargetRecoveryGeneration (
                            $PredecessorTargetRecoveryGeneration
                        ) `
                        -OperationId $sourceRecoveryOperationId `
                        -TargetRevision $targetRevision `
                        -DatabaseState $databaseState
                $oldMarker = Assert-TicketboxC07ProductionMarker `
                    -Catalog $catalog `
                    -OperationId $sourceRecoveryOperationId `
                    -Mode $Mode `
                    -ExpectedSourceRevision $sourceRevision `
                    -TargetRevision $targetRevision `
                    -RecoveryManifestSha256 (
                        $forwardTailRecovery.ManifestSha256
                    )
                if (
                    [string]$oldMarker.MigrationEvidenceSha256 -cne
                        ([string]$PredecessorTargetRecoveryGeneration.Payload.lifecycle.migration_evidence_sha256).ToLowerInvariant()
                ) {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 predecessor tail marker migration evidence 已漂移。" `
                        -FailureCode "resource_shape_mismatch")
                }
                $currentRoleSha256 = Get-TicketboxC07RoleAuthoritySha256 `
                    -Authority $authority `
                    -SuperuserPassword $SuperuserPassword
                $currentAclSha256 = Get-TicketboxC07RuntimeAclSha256 `
                    -Authority $authority `
                    -SuperuserPassword $SuperuserPassword
                $roleHashesMatch = (
                    ([string]$oldMarker.RoleAuthoritySha256).ToLowerInvariant() -ceq
                        ([string]$currentRoleSha256).ToLowerInvariant() -and
                    ([string]$oldMarker.RuntimeAclSha256).ToLowerInvariant() -ceq
                        ([string]$currentAclSha256).ToLowerInvariant()
                )
                $migratorState = Get-TicketboxC07MigratorRetirementState `
                    -Authority $authority `
                    -SuperuserPassword $SuperuserPassword
                if (
                    [bool]$migratorState.IsActive -eq
                        [bool]$migratorState.IsRetired
                ) {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 predecessor migrator retirement state 不唯一。" `
                        -FailureCode "role_authority_invariant_failed")
                }
                $requiresRetiredCatalogValidation = $false
                if ($oldMarkerPhase -ceq "production_ready") {
                    if (-not $migratorState.IsRetired -or -not $roleHashesMatch) {
                        throw (New-TicketboxC07DatabaseClassifiedFailure `
                            -Message "C07 predecessor READY marker role/ACL authority 已漂移。" `
                            -FailureCode "runtime_acl_invariant_failed")
                    }
                    $requiresRetiredCatalogValidation = $true
                }
                elseif ($migratorState.IsActive) {
                    if (-not $roleHashesMatch) {
                        throw (New-TicketboxC07DatabaseClassifiedFailure `
                            -Message "C07 predecessor runtime ACL marker authority 已漂移。" `
                            -FailureCode "runtime_acl_invariant_failed")
                    }
                }
                elseif ($migratorState.IsRetired) {
                    $requiresRetiredCatalogValidation = $true
                }
                else {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 predecessor migrator 处于 partial retirement residue。" `
                        -FailureCode "role_authority_invariant_failed")
                }
                if ($requiresRetiredCatalogValidation) {
                    # A crash may land after the migrator retirement commit but
                    # before production_ready replaces runtime_acl_verified.
                    # In either retired phase, independently re-prove the final
                    # role catalog and live authority instead of applying the
                    # active TTL/LOGIN role contract.
                    Assert-TicketboxC07RetiredRoleCatalog `
                        $authority $SuperuserPassword
                    Assert-TicketboxC07RuntimeAclContract `
                        -Authority $authority `
                        -SuperuserPassword $SuperuserPassword
                    Assert-TicketboxC07RuntimeCredential `
                        -Authority $authority `
                        -RuntimePassword $RuntimePassword
                    $retiredLive = Get-TicketboxC07ProductionLiveState `
                        -Authority $authority `
                        -SuperuserPassword $SuperuserPassword `
                        -Mode $Mode
                    if (
                        [int]$retiredLive.LegacySessionCount -ne 0 -or
                        [int]$retiredLive.MigratorSessionCount -ne 0 -or
                        [bool]$retiredLive.MigratorCanLogin -or
                        [bool]$retiredLive.MigratorPasswordPresent
                    ) {
                        throw (New-TicketboxC07DatabaseClassifiedFailure `
                            -Message "C07 predecessor migrator retirement state 不完整。" `
                            -FailureCode "role_authority_invariant_failed")
                    }
                }
            }
            else {
                $oldMarker = Assert-TicketboxC07ProductionMarker `
                    -Catalog $catalog `
                    -OperationId $sourceRecoveryOperationId `
                    -Mode $Mode `
                    -ExpectedSourceRevision $sourceRevision `
                    -TargetRevision $targetRevision `
                    -RecoveryManifestSha256 $recovery.ManifestSha256
                if (
                    [string]$oldMarker.Phase -cnotin @(
                        "migration_started",
                        "migration_completed"
                    )
                ) {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 forward-repair predecessor marker phase 不可安全转移。" `
                        -FailureCode "database_identity_or_revision_drift")
                }
            }
            $transferMarker = New-TicketboxC07ProductionMarker `
                -OperationId $operationText `
                -Mode $Mode `
                -Phase "migration_started" `
                -Catalog $catalog `
                -ExpectedSourceRevision $sourceRevision `
                -TargetRevision $targetRevision `
                -RecoveryManifestSha256 $recovery.ManifestSha256
            Set-TicketboxC07DatabaseMarker `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -Database $script:TicketboxC07DatabaseName `
                -Marker $transferMarker `
                -Label "C07 forward-repair durable operation transfer"
            $catalog.Marker = $transferMarker
        }
        elseif ($markerParts[1] -cne $operationText) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 forward-repair marker 绑定 foreign operation。" `
                -FailureCode "database_identity_or_revision_drift")
        }
        elseif ($null -ne $PredecessorTargetRecoveryGeneration) {
            $forwardTailRecovery =
                Assert-TicketboxC07ProductionTargetRecoveryBinding `
                    -TargetRecoveryGeneration (
                        $PredecessorTargetRecoveryGeneration
                    ) `
                    -OperationId $sourceRecoveryOperationId `
                    -TargetRevision $targetRevision `
                    -DatabaseState $databaseState
        }
    }
    $production = $null
    if (
        -not [string]::IsNullOrEmpty([string]$catalog.Marker) -and
        ([string]$catalog.Marker).StartsWith(
            "$script:TicketboxC07ProductionMarkerSchema|",
            [StringComparison]::Ordinal
        )
    ) {
        $markerParts = @(([string]$catalog.Marker).Split([char]"|"))
        $markerRecoveryManifestSha256 = $recovery.ManifestSha256
        if (
            $markerParts.Count -eq 13 -and
            $markerParts[3] -cin @(
                "runtime_acl_verified",
                "production_ready"
            ) -and
            $null -ne $targetRecovery
        ) {
            $markerRecoveryManifestSha256 =
                $targetRecovery.ManifestSha256
        }
        $production = Assert-TicketboxC07ProductionMarker `
            -Catalog $catalog `
            -OperationId $operationText `
            -Mode $Mode `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -RecoveryManifestSha256 $markerRecoveryManifestSha256
    }
    else {
        if ($databaseState.AlembicRevision -cne $sourceRevision) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message (
                    "C07 production coordinator 缺少 durable migration marker，" +
                    "且 live revision 不是 expected source；零 DDL 拒绝。"
                ) `
                -FailureCode "database_identity_or_revision_drift")
        }
        if ($Mode -ceq "fresh_install") {
            Initialize-TicketboxC07FreshDatabaseAuthority `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operationText | Out-Null
        }
        else {
            Invoke-TicketboxC07LegacyDatabaseAdoption `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operationText | Out-Null
        }
        $catalog = Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName
        $roles = Get-TicketboxC07RoleBootstrapIdentity `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -OperationId $operationText `
            -Mode $Mode
        $legacyRoleOid = 0
        if ($Mode -ceq "legacy_adoption") {
            $legacyRoleOid = Get-TicketboxC07RoleOid `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -Role $script:TicketboxC07LegacyRuntimeRole
        }
        $authorityPhase = Assert-TicketboxC07DatabaseMarker `
            -Catalog $catalog `
            -OperationId $operationText `
            -Mode $Mode `
            -Roles $roles `
            -LegacyRoleOid $legacyRoleOid
        if ($authorityPhase -cne "authority_ready") {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 role authority 尚未完成，拒绝开始 migration。" `
                -FailureCode "role_authority_invariant_failed")
        }
        $startedMarker = New-TicketboxC07ProductionMarker `
            -OperationId $operationText `
            -Mode $Mode `
            -Phase "migration_started" `
            -Catalog $catalog `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -RecoveryManifestSha256 $recovery.ManifestSha256
        Set-TicketboxC07DatabaseMarker `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName `
            -Marker $startedMarker `
            -Label "C07 production migration durable start"
        $catalog.Marker = $startedMarker
        $production = Assert-TicketboxC07ProductionMarker `
            -Catalog $catalog `
            -OperationId $operationText `
            -Mode $Mode `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -RecoveryManifestSha256 $recovery.ManifestSha256
    }

    $phase = [string]$production.Phase
    $migrationEvidenceSha256 = [string]$production.MigrationEvidenceSha256
    $migrationEvidence = $null
    $migratorCredentialWindowRenewed = $false
    $retryRuntimeAdmission = $false
    if ($phase -ceq "runtime_acl_verified") {
        $runtimeAclResidue =
            Resolve-TicketboxC07ManagedOrPublishedWriterFenceObservation
        if ([string]$runtimeAclResidue.AuthorityPhase -ceq "managed_frozen") {
            $residueMigratorState = Get-TicketboxC07MigratorRetirementState `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword
            if (-not [bool]$residueMigratorState.IsActive) {
                throw (New-TicketboxC07DatabaseClassifiedFailure `
                    -Message (
                        "C07 runtime ACL marker 的 frozen residue 缺少可控 migrator；" +
                        "拒绝猜测 admission。"
                    ) `
                    -FailureCode "role_authority_invariant_failed")
            }
            $retryRuntimeAdmission = $true
        }
    }
    if ($phase -ceq "migration_started") {
        $databaseState = Get-TicketboxC07ProductionDatabaseState `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword
        if ($databaseState.AlembicRevision -ceq $sourceRevision) {
            Renew-TicketboxC07FrozenMigratorCredentialWindow `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operationText `
                -Mode $Mode
            $migratorCredentialWindowRenewed = $true
            $migrationEvidence = & $MigrationAction `
                $authority `
                $MigratorPassword `
                $sourceRevision `
                $targetRevision
            if ($null -eq $migrationEvidence) {
                throw "C07 MigrationAction 未返回 typed evidence。"
            }
        }
        elseif ($databaseState.AlembicRevision -ceq $targetRevision) {
            Renew-TicketboxC07FrozenMigratorCredentialWindow `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operationText `
                -Mode $Mode
            $migratorCredentialWindowRenewed = $true
            # A committed Alembic revision is not proof that every C07 column
            # and validated CHECK reached the frozen target shape.  Re-enter
            # the frozen helper: at target it performs no DDL, but validates
            # the complete money shape before this coordinator can publish
            # migration_completed.
            $migrationEvidence = & $MigrationAction `
                $authority `
                $MigratorPassword `
                $sourceRevision `
                $targetRevision
            if ($null -eq $migrationEvidence) {
                throw "C07 target-observed MigrationAction 未返回 typed evidence。"
            }
        }
        else {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 migration_started residue 位于未知 revision；拒绝重跑 DDL。" `
                -FailureCode "database_identity_or_revision_drift")
        }
        $afterMigration = Get-TicketboxC07ProductionDatabaseState `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword
        if ($afterMigration.AlembicRevision -cne $targetRevision) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 MigrationAction 未提交 exact target revision。" `
                -FailureCode "database_identity_or_revision_drift")
        }
        try {
            $migrationEvidenceSha256 = Get-TicketboxC07MigrationEvidenceSha256 `
                -Evidence $migrationEvidence `
                -OperationId $operationText `
                -ExpectedSourceRevision $sourceRevision `
                -TargetRevision $targetRevision
        }
        catch {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 migration evidence 未满足 frozen resource shape。" `
                -FailureCode "resource_shape_mismatch" `
                -InnerException $_.Exception)
        }
        if ($null -ne $forwardTailRecovery) {
            if (
                ([string]$migrationEvidence.resource_shape_sha256).ToLowerInvariant() -cne
                    ([string]$forwardTailRecovery.ResourceShapeSha256).ToLowerInvariant()
            ) {
                throw (New-TicketboxC07DatabaseClassifiedFailure `
                    -Message "C07 successor target-observed shape 与 predecessor recovery 不一致。" `
                    -FailureCode "resource_shape_mismatch")
            }
            if (
                ([string]$migrationEvidence.money_facts_sha256).ToLowerInvariant() -cne
                    ([string]$forwardTailRecovery.MoneyFactsSha256).ToLowerInvariant()
            ) {
                throw (New-TicketboxC07DatabaseClassifiedFailure `
                    -Message "C07 successor target-observed money facts 与 predecessor recovery 不一致。" `
                    -FailureCode "money_facts_mismatch")
            }
        }
        $catalog = Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName
        $completedMarker = New-TicketboxC07ProductionMarker `
            -OperationId $operationText `
            -Mode $Mode `
            -Phase "migration_completed" `
            -Catalog $catalog `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -RecoveryManifestSha256 $readyRecovery.ManifestSha256 `
            -MigrationEvidenceSha256 $migrationEvidenceSha256
        Set-TicketboxC07DatabaseMarker `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName `
            -Marker $completedMarker `
            -Label "C07 production migration durable completion"
        $phase = "migration_completed"
    }
    elseif ($phase -cne "production_ready") {
        Assert-TicketboxC07DatabaseSha256 `
            $migrationEvidenceSha256 "C07 durable migration evidence"
    }

    if ($StopAfterMigrationCompleted) {
        if ($phase -cne "migration_completed") {
            throw "C07 DDL-only coordinator 未停在 durable migration_completed。"
        }
        if ($null -eq $migrationEvidence) {
            Renew-TicketboxC07FrozenMigratorCredentialWindow `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operationText `
                -Mode $Mode
            $migrationEvidence = & $MigrationAction `
                $authority `
                $MigratorPassword `
                $sourceRevision `
                $targetRevision
            if ($null -eq $migrationEvidence) {
                throw "C07 target-observed DDL evidence 缺失。"
            }
            $observedEvidenceSha256 =
                try {
                    Get-TicketboxC07MigrationEvidenceSha256 `
                        -Evidence $migrationEvidence `
                        -OperationId $operationText `
                        -ExpectedSourceRevision $sourceRevision `
                        -TargetRevision $targetRevision
                }
                catch {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 target-observed DDL evidence shape 无效。" `
                        -FailureCode "resource_shape_mismatch" `
                        -InnerException $_.Exception)
                }
            if ($observedEvidenceSha256 -cne $migrationEvidenceSha256) {
                throw (New-TicketboxC07DatabaseClassifiedFailure `
                    -Message "C07 target-observed DDL evidence 与 durable marker 不一致。" `
                    -FailureCode "resource_shape_mismatch")
            }
            if ($null -ne $forwardTailRecovery) {
                if (
                    ([string]$migrationEvidence.resource_shape_sha256).ToLowerInvariant() -cne
                        ([string]$forwardTailRecovery.ResourceShapeSha256).ToLowerInvariant()
                ) {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 resumed successor shape 与 predecessor recovery 不一致。" `
                        -FailureCode "resource_shape_mismatch")
                }
                if (
                    ([string]$migrationEvidence.money_facts_sha256).ToLowerInvariant() -cne
                        ([string]$forwardTailRecovery.MoneyFactsSha256).ToLowerInvariant()
                ) {
                    throw (New-TicketboxC07DatabaseClassifiedFailure `
                        -Message "C07 resumed successor money facts 与 predecessor recovery 不一致。" `
                        -FailureCode "money_facts_mismatch")
                }
            }
        }
        if (
            [string]$migrationEvidence.schema -cnotin @(
                $script:TicketboxC07ResourceMigrationEvidenceSchema,
                "ticketbox-c07-maintenance-upgrade-result-v3"
            )
        ) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message (
                    "C07 DDL-only coordinator 缺少 post-DDL " +
                    "resource-attested migration evidence。"
                ) `
                -FailureCode "resource_shape_mismatch")
        }
        $targetState = Get-TicketboxC07ProductionDatabaseState `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword
        if ($targetState.AlembicRevision -cne $targetRevision) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 DDL-only coordinator target revision 漂移。" `
                -FailureCode "database_identity_or_revision_drift")
        }
        return New-TicketboxC07TargetCommitResult `
            -OperationId $operationText `
            -Mode $Mode `
            -DatabaseState $targetState `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -SourceRecoveryManifestSha256 $recovery.ManifestSha256 `
            -MigrationEvidenceSha256 $migrationEvidenceSha256 `
            -MigrationEvidence $migrationEvidence
    }

    if ($phase -ceq "migration_completed" -or $retryRuntimeAdmission) {
        if ($null -eq $targetRecovery) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 runtime admission 缺少 post-DDL target recovery。" `
                -FailureCode "authority_chain_mismatch")
        }
        $migrationState = Get-TicketboxC07ProductionDatabaseState `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword
        if ($migrationState.AlembicRevision -cne $targetRevision) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 migration completion marker 与 live revision 不一致。" `
                -FailureCode "database_identity_or_revision_drift")
        }
        $migratorState = Get-TicketboxC07MigratorRetirementState `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword
        if (-not $migratorState.IsActive) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 migrator 在 ACL matrix durable latch 前已漂移。" `
                -FailureCode "role_authority_invariant_failed")
        }
        if (-not $migratorCredentialWindowRenewed) {
            Renew-TicketboxC07FrozenMigratorCredentialWindow `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operationText `
                -Mode $Mode
            $migratorCredentialWindowRenewed = $true
        }
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Sql (Get-TicketboxC07DatabasePrivilegeSql -PreserveRuntimeFence) `
            -Label "C07 production target ACL application while frozen" | Out-Null
        $frozen = Get-TicketboxC07WriterDatabaseFenceObservation `
            -AuthorityPhase "managed_frozen"
        Assert-TicketboxC07WriterDatabaseFence -Observation $frozen
        Assert-TicketboxC07MigratorCredential `
            -Authority $authority `
            -MigratorPassword $MigratorPassword
        try {
            Invoke-TicketboxC07Sql `
                -Authority $authority `
                -Database $script:TicketboxC07DatabaseName `
                -Role "postgres" `
                -Password $SuperuserPassword `
                -Label "C07 controlled runtime admission publication" `
                -Sql @"
BEGIN;
ALTER ROLE "$script:TicketboxC07RuntimeRole"
    LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1;
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07RuntimeRole";
COMMIT;
"@ | Out-Null
            Assert-TicketboxC07RuntimeCredential `
                -Authority $authority `
                -RuntimePassword $RuntimePassword
            Assert-TicketboxC07RoleCatalog $authority $SuperuserPassword
            try {
                Test-TicketboxC07DatabaseRoleMatrix `
                    -SuperuserPassword $SuperuserPassword `
                    -RuntimePassword $RuntimePassword `
                    -MigratorPassword $MigratorPassword `
                    -OperationId $operationText
            }
            catch {
                $matrixFailure = $_.Exception
                try {
                    Assert-TicketboxC07RuntimeAclContract `
                        -Authority $authority `
                        -SuperuserPassword $SuperuserPassword
                }
                catch {
                    if (
                        [string]$_.Exception.Data["TicketboxC07FailureClass"] -ceq
                            "invariant"
                    ) {
                        throw
                    }
                    throw [AggregateException]::new(
                        "C07 role matrix 与 structured ACL 诊断均失败。",
                        [Exception[]]@($matrixFailure, $_.Exception)
                    )
                }
                throw $matrixFailure
            }
            Assert-TicketboxC07RuntimeAclContract `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword
            $roleAuthoritySha256 = Get-TicketboxC07RoleAuthoritySha256 `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword
            $runtimeAclSha256 = Get-TicketboxC07RuntimeAclSha256 `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword
            $catalog = Get-TicketboxC07DatabaseCatalogObservation `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -Database $script:TicketboxC07DatabaseName
            $aclMarker = New-TicketboxC07ProductionMarker `
                -OperationId $operationText `
                -Mode $Mode `
                -Phase "runtime_acl_verified" `
                -Catalog $catalog `
                -ExpectedSourceRevision $sourceRevision `
                -TargetRevision $targetRevision `
                -RecoveryManifestSha256 $readyRecovery.ManifestSha256 `
                -MigrationEvidenceSha256 $migrationEvidenceSha256 `
                -RoleAuthoritySha256 $roleAuthoritySha256 `
                -RuntimeAclSha256 $runtimeAclSha256
            Set-TicketboxC07DatabaseMarker `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -Database $script:TicketboxC07DatabaseName `
                -Marker $aclMarker `
                -Label "C07 production runtime ACL durable verification"
            $phase = "runtime_acl_verified"
            $production = [pscustomobject]@{
                Phase = $phase
                MigrationEvidenceSha256 = $migrationEvidenceSha256
                RoleAuthoritySha256 = $roleAuthoritySha256
                RuntimeAclSha256 = $runtimeAclSha256
                LivePostconditionsSha256 = "0" * 64
            }
        }
        catch {
            $publicationFailure = $_.Exception
            $refenceFailure = $null
            try {
                Enter-TicketboxC07CurrentWriterDatabaseFence `
                    -Authority $LifecycleAuthority `
                    -AuthorityPhase "managed_frozen" | Out-Null
            }
            catch { $refenceFailure = $_.Exception }
            if ($null -ne $refenceFailure) {
                throw [AggregateException]::new(
                    "C07 runtime admission 与 fail-closed compensation 均失败。",
                    [Exception[]]@($publicationFailure, $refenceFailure)
                )
            }
            throw $publicationFailure
        }
    }

    if ($phase -ceq "runtime_acl_verified") {
        $migratorState = Get-TicketboxC07MigratorRetirementState `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword
        if ($migratorState.IsActive) {
            $currentRoleSha256 = Get-TicketboxC07RoleAuthoritySha256 `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword
            $currentAclSha256 = Get-TicketboxC07RuntimeAclSha256 `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword
            if (
                $currentRoleSha256 -cne
                    [string]$production.RoleAuthoritySha256 -or
                $currentAclSha256 -cne [string]$production.RuntimeAclSha256
            ) {
                throw (New-TicketboxC07DatabaseClassifiedFailure `
                    -Message "C07 runtime ACL durable latch 后发生 role/ACL drift。" `
                    -FailureCode "runtime_acl_invariant_failed")
            }
            Disable-TicketboxC07MigratorLogin `
                -SuperuserPassword $SuperuserPassword `
                -OperationId $operationText `
                -Mode $Mode
        }
        elseif (-not $migratorState.IsRetired) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 migrator 处于 partial retirement residue。" `
                -FailureCode "role_authority_invariant_failed")
        }
        $published = Get-TicketboxC07WriterDatabaseFenceObservation `
            -AuthorityPhase "published_runtime"
        Assert-TicketboxC07PublishedDatabaseAuthority -Observation $published
    }

    $finalState = Get-TicketboxC07ProductionDatabaseState `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword
    if ($finalState.AlembicRevision -cne $targetRevision) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 final live revision 不等于 target。" `
            -FailureCode "database_identity_or_revision_drift")
    }
    $live = Get-TicketboxC07ProductionLiveState `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Mode $Mode
    if (
        $live.LegacySessionCount -ne 0 -or
        $live.MigratorSessionCount -ne 0 -or
        $live.MigratorCanLogin -or
        $live.MigratorPasswordPresent
    ) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 production READY 前仍有 legacy/migrator authority。" `
            -FailureCode "role_authority_invariant_failed")
    }
    Assert-TicketboxC07RuntimeCredential `
        -Authority $authority `
        -RuntimePassword $RuntimePassword
    Assert-TicketboxC07RuntimeAclContract `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword
    $finalRoleSha256 = Get-TicketboxC07RoleAuthoritySha256 `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword
    $finalAclSha256 = Get-TicketboxC07RuntimeAclSha256 `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword
    if ($null -eq $targetRecovery) {
        throw (New-TicketboxC07DatabaseClassifiedFailure `
            -Message "C07 production READY 缺少 post-DDL target recovery。" `
            -FailureCode "authority_chain_mismatch")
    }
    $liveCanonical = @(
        "schema=$script:TicketboxC07ProductionResultSchema",
        "operation_id=$operationText",
        "mode=$Mode",
        "recovery_manifest_sha256=$($readyRecovery.ManifestSha256)",
        "release_fingerprint=$($recovery.ReleaseFingerprint)",
        "installation_id=$($recovery.InstallationId)",
        "build_manifest_sha256=$($recovery.BuildManifestSha256)",
        "backend_version=$($recovery.BackendVersion)",
        "root_authority_chain_sha256=$($lifecycle.RootAuthorityChainSha256)",
        "current_authority_chain_sha256=$($lifecycle.CurrentAuthorityChainSha256)",
        "current_receipt_payload_sha256=$($lifecycle.CurrentReceiptPayloadSha256)",
        "current_stage=$($lifecycle.CurrentStage)",
        "current_stage_sequence=$($lifecycle.CurrentStageSequence)",
        (
            "current_coordinator_binding_sha256=" +
            $lifecycle.CurrentCoordinatorBindingSha256
        ),
        (
            "current_coordinator_binding_sequence=" +
            $lifecycle.CurrentCoordinatorBindingSequence
        ),
        "current_heartbeat_sequence=$($lifecycle.CurrentHeartbeatSequence)",
        "current_freeze_proof_sha256=$($lifecycle.CurrentFreezeProofSha256)",
        "lifecycle_recovery_manifest_sha256=$($lifecycle.RecoveryManifestSha256)",
        (
            "lifecycle_target_recovery_manifest_sha256=" +
            $lifecycle.TargetRecoveryManifestSha256
        ),
        "cluster_system_identifier=$($finalState.ClusterSystemIdentifier)",
        "database_oid=$($finalState.DatabaseOid)",
        "logical_server_id=$($finalState.LogicalServerId)",
        "data_generation=$($finalState.DataGeneration)",
        "source_revision=$sourceRevision",
        "target_revision=$targetRevision",
        "migration_evidence_sha256=$migrationEvidenceSha256",
        "money_facts_sha256=$($readyRecovery.MoneyFactsSha256)",
        "resource_shape_sha256=$($targetRecovery.ResourceShapeSha256)",
        "target_restore_evidence_sha256=$($targetRecovery.RestoreEvidenceSha256)",
        "role_authority_sha256=$finalRoleSha256",
        "runtime_acl_sha256=$finalAclSha256",
        "legacy_session_count=$($live.LegacySessionCount)",
        "migrator_session_count=$($live.MigratorSessionCount)",
        "migrator_can_login=$($live.MigratorCanLogin.ToString().ToLowerInvariant())",
        (
            "migrator_password_present=" +
            $live.MigratorPasswordPresent.ToString().ToLowerInvariant()
        )
    ) -join "`n"
    $livePostconditionsSha256 =
        Get-TicketboxC07DatabaseTextSha256 $liveCanonical

    $publishReady = $phase -cne "production_ready"
    if ($phase -ceq "production_ready") {
        if (
            $migrationEvidenceSha256 -cne
                [string]$production.MigrationEvidenceSha256 -or
            $finalRoleSha256 -cne [string]$production.RoleAuthoritySha256 -or
            $finalAclSha256 -cne [string]$production.RuntimeAclSha256
        ) {
            throw (New-TicketboxC07DatabaseClassifiedFailure `
                -Message "C07 production READY marker 与 durable authority drift。" `
                -FailureCode "runtime_acl_invariant_failed")
        }
        if (
            $livePostconditionsSha256 -cne
                [string]$production.LivePostconditionsSha256
        ) {
            # A lifecycle takeover changes the current protected receipt/chain
            # while retaining the same writers_frozen root. Re-publish only
            # after every live role/ACL/session/database postcondition above
            # has been revalidated against the new typed lifecycle binding.
            $publishReady = $true
        }
    }
    if ($publishReady) {
        $catalog = Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName
        $readyMarker = New-TicketboxC07ProductionMarker `
            -OperationId $operationText `
            -Mode $Mode `
            -Phase "production_ready" `
            -Catalog $catalog `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -RecoveryManifestSha256 $readyRecovery.ManifestSha256 `
            -MigrationEvidenceSha256 $migrationEvidenceSha256 `
            -RoleAuthoritySha256 $finalRoleSha256 `
            -RuntimeAclSha256 $finalAclSha256 `
            -LivePostconditionsSha256 $livePostconditionsSha256
        Set-TicketboxC07DatabaseMarker `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName `
            -Marker $readyMarker `
            -Label "C07 production authority READY publication"
        $catalog.Marker = $readyMarker
        $published = Assert-TicketboxC07ProductionMarker `
            -Catalog $catalog `
            -OperationId $operationText `
            -Mode $Mode `
            -ExpectedSourceRevision $sourceRevision `
            -TargetRevision $targetRevision `
            -RecoveryManifestSha256 $readyRecovery.ManifestSha256
        if ($published.Phase -cne "production_ready") {
            throw "C07 production READY marker 未能复读。"
        }
    }
    return New-TicketboxC07ProductionResult `
        -OperationId $operationText `
        -Mode $Mode `
        -Recovery $readyRecovery `
        -DatabaseState $finalState `
        -ExpectedSourceRevision $sourceRevision `
        -TargetRevision $targetRevision `
        -MigrationEvidenceSha256 $migrationEvidenceSha256 `
        -RoleAuthoritySha256 $finalRoleSha256 `
        -RuntimeAclSha256 $finalAclSha256 `
        -Live $live `
        -LivePostconditionsSha256 $livePostconditionsSha256
}

function Assert-TicketboxC07FreshPreflight {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$OperationId
    )

    $legacyOid = Get-TicketboxC07RoleOid `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -Role $script:TicketboxC07LegacyRuntimeRole `
        -AllowAbsent
    if ($legacyOid -ne 0) {
        throw "C07 fresh authority 发现 legacy runtime role；零 mutation 拒绝。"
    }
    $roles = Get-TicketboxC07RoleBootstrapIdentity `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $OperationId `
        -Mode "fresh_install" `
        -AllowAbsent
    $database = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $Authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    if ($database.Exists -and -not $roles.Exists) {
        throw "C07 fresh authority 发现无 role identity 的 database；零 mutation 拒绝。"
    }
    $phase = "absent"
    if ($database.Exists) {
        $phase = Assert-TicketboxC07DatabaseMarker `
            -Catalog $database `
            -OperationId $OperationId `
            -Mode "fresh_install" `
            -Roles $roles `
            -AllowUnregisteredIsolatedResidue
    }
    return [pscustomobject]@{
        Roles = $roles
        Database = $database
        Phase = $phase
    }
}

function Initialize-TicketboxC07FreshDatabaseAuthority {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [AllowNull()][Security.SecureString]$RuntimePassword,
        [AllowNull()][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)][string]$OperationId
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    Assert-TicketboxC07SecureString $SuperuserPassword "C07 superuser authority"
    Assert-TicketboxC07SecureString $RuntimePassword "C07 runtime credential"
    Assert-TicketboxC07SecureString $MigratorPassword "C07 migrator credential"
    Assert-TicketboxC07MigratorCredentialWindow $MigratorValidUntilUtc

    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    $preflight = Assert-TicketboxC07FreshPreflight `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $operation.ToString("D")
    if ($preflight.Phase -ceq "authority_ready") {
        Renew-TicketboxC07FrozenMigratorCredentialWindow `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -RuntimePassword $RuntimePassword `
            -MigratorPassword $MigratorPassword `
            -MigratorValidUntilUtc $MigratorValidUntilUtc `
            -OperationId $operation.ToString("D") `
            -Mode "fresh_install"
        $frozen = Get-TicketboxC07WriterDatabaseFenceObservation `
            -AuthorityPhase "managed_frozen"
        Assert-TicketboxC07WriterDatabaseFence -Observation $frozen
        return Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName
    }

    $runtimeVerifier = ConvertTo-TicketboxC07ScramVerifier $RuntimePassword
    $migratorVerifier = ConvertTo-TicketboxC07ScramVerifier $MigratorPassword
    $roleSql = Get-TicketboxC07RoleBootstrapSql `
        -RuntimeVerifier $runtimeVerifier `
        -MigratorVerifier $migratorVerifier `
        -MigratorValidUntilUtc $MigratorValidUntilUtc `
        -OperationId $operation.ToString("D") `
        -Mode "fresh_install" `
        -RuntimeAdmissionState "frozen"
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql $roleSql `
        -Label "C07 fresh role transaction" | Out-Null
    $roles = Get-TicketboxC07RoleBootstrapIdentity `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $operation.ToString("D") `
        -Mode "fresh_install"
    $database = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    if (-not $database.Exists) {
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "C07 fresh isolated database create" `
            -Sql @"
CREATE DATABASE "$script:TicketboxC07DatabaseName"
    OWNER "$script:TicketboxC07OwnerRole" TEMPLATE template0 ENCODING 'UTF8'
    ALLOW_CONNECTIONS false;
"@ | Out-Null
        $database = Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName
    }
    if (
        -not $database.Exists -or
        [uint32]$database.OwnerRoleOid -ne [uint32]$roles.OwnerRoleOid
    ) {
        throw "C07 fresh database owner/OID 不符合本 operation。"
    }
    $phase = Assert-TicketboxC07DatabaseMarker `
        -Catalog $database `
        -OperationId $operation.ToString("D") `
        -Mode "fresh_install" `
        -Roles $roles `
        -AllowUnregisteredIsolatedResidue
    if ($phase -ceq "unregistered") {
        $createdMarker = New-TicketboxC07DatabaseMarker `
            -OperationId $operation.ToString("D") `
            -Mode "fresh_install" `
            -Phase "database_created" `
            -Catalog $database `
            -Roles $roles
        Set-TicketboxC07DatabaseMarker `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName `
            -Marker $createdMarker `
            -Label "C07 fresh database identity registration"
        $database.Marker = $createdMarker
    }
    if (-not $database.AllowsConnections) {
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "C07 fresh restricted database opening" `
            -Sql @"
BEGIN;
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName" FROM PUBLIC;
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName"
    FROM "$script:TicketboxC07RuntimeRole";
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName"
    FROM "$script:TicketboxC07MigratorRole";
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07MigratorRole";
ALTER DATABASE "$script:TicketboxC07DatabaseName" ALLOW_CONNECTIONS true;
COMMIT;
"@ | Out-Null
    }
    $readyCatalog = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    $readyMarker = New-TicketboxC07DatabaseMarker `
        -OperationId $operation.ToString("D") `
        -Mode "fresh_install" `
        -Phase "authority_ready" `
        -Catalog $readyCatalog `
        -Roles $roles
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (Get-TicketboxC07DatabasePrivilegeSql -PreserveRuntimeFence) `
        -Label "C07 fresh database privilege transaction" | Out-Null
    Assert-TicketboxC07MigratorCredential `
        -Authority $authority `
        -MigratorPassword $MigratorPassword
    $frozen = Get-TicketboxC07WriterDatabaseFenceObservation `
        -AuthorityPhase "managed_frozen"
    Assert-TicketboxC07WriterDatabaseFence -Observation $frozen
    Set-TicketboxC07DatabaseMarker `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName `
        -Marker $readyMarker `
        -Label "C07 fresh authority READY publication"
    $final = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    $finalPhase = Assert-TicketboxC07DatabaseMarker `
        -Catalog $final `
        -OperationId $operation.ToString("D") `
        -Mode "fresh_install" `
        -Roles $roles
    if ($finalPhase -cne "authority_ready" -or -not $final.AllowsConnections) {
        throw "C07 fresh database authority 未到达可复读 READY phase。"
    }
    return Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
}

function Invoke-TicketboxC07LegacyDatabaseAdoption {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [AllowNull()][Security.SecureString]$RuntimePassword,
        [AllowNull()][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)][string]$OperationId
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    Assert-TicketboxC07SecureString $SuperuserPassword "C07 legacy adoption superuser authority"
    Assert-TicketboxC07SecureString $RuntimePassword "C07 runtime credential"
    Assert-TicketboxC07SecureString $MigratorPassword "C07 migrator credential"
    Assert-TicketboxC07MigratorCredentialWindow $MigratorValidUntilUtc
    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    $legacyOid = Get-TicketboxC07RoleOid `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Role $script:TicketboxC07LegacyRuntimeRole
    Assert-TicketboxC07LegacyClusterSurface `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -LegacyRoleOid $legacyOid
    $otherOwned = Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 legacy database ownership preflight" `
        -Sql @"
SELECT count(*)::text
FROM pg_database
WHERE datname <> '$script:TicketboxC07DatabaseName'
  AND datdba = $legacyOid;
"@
    if ($otherOwned.Trim() -cne "0") {
        throw "C07 legacy role 仍拥有其他 database；零 mutation 拒绝。"
    }
    $roles = Get-TicketboxC07RoleBootstrapIdentity `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $operation.ToString("D") `
        -Mode "legacy_adoption" `
        -AllowAbsent
    $database = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    if (-not $database.Exists) {
        throw "C07 legacy adoption 缺少唯一 source database。"
    }
    if (
        -not $roles.Exists -and
        -not [string]::IsNullOrEmpty([string]$database.Marker)
    ) {
        throw "C07 legacy database 已有 foreign operation marker；零 mutation 拒绝。"
    }
    if ($roles.Exists -and -not [string]::IsNullOrEmpty($database.Marker)) {
        $phase = Assert-TicketboxC07DatabaseMarker `
            -Catalog $database `
            -OperationId $operation.ToString("D") `
            -Mode "legacy_adoption" `
            -Roles $roles `
            -LegacyRoleOid $legacyOid
        if ($phase -ceq "authority_ready") {
            Renew-TicketboxC07FrozenMigratorCredentialWindow `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -RuntimePassword $RuntimePassword `
                -MigratorPassword $MigratorPassword `
                -MigratorValidUntilUtc $MigratorValidUntilUtc `
                -OperationId $operation.ToString("D") `
                -Mode "legacy_adoption"
            $frozen = Get-TicketboxC07WriterDatabaseFenceObservation `
                -AuthorityPhase "managed_frozen"
            Assert-TicketboxC07WriterDatabaseFence -Observation $frozen
            Assert-TicketboxC07LegacyRoleRetired `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -LegacyRoleOid $legacyOid
            return Get-TicketboxC07DatabaseCatalogObservation `
                -Authority $authority `
                -SuperuserPassword $SuperuserPassword `
                -Database $script:TicketboxC07DatabaseName
        }
    }
    elseif ([uint32]$database.OwnerRoleOid -ne [uint32]$legacyOid) {
        throw "C07 legacy database 无本 operation marker 且 owner 不是 legacy role。"
    }
    $runtimeVerifier = ConvertTo-TicketboxC07ScramVerifier $RuntimePassword
    $migratorVerifier = ConvertTo-TicketboxC07ScramVerifier $MigratorPassword
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (Get-TicketboxC07RoleBootstrapSql `
            -RuntimeVerifier $runtimeVerifier `
            -MigratorVerifier $migratorVerifier `
            -MigratorValidUntilUtc $MigratorValidUntilUtc `
            -OperationId $operation.ToString("D") `
            -Mode "legacy_adoption" `
            -RuntimeAdmissionState "frozen") `
        -Label "C07 legacy target role transaction" | Out-Null
    $roles = Get-TicketboxC07RoleBootstrapIdentity `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $operation.ToString("D") `
        -Mode "legacy_adoption"
    $database = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    $phase = "unregistered"
    if (-not [string]::IsNullOrEmpty($database.Marker)) {
        $phase = Assert-TicketboxC07DatabaseMarker `
            -Catalog $database `
            -OperationId $operation.ToString("D") `
            -Mode "legacy_adoption" `
            -Roles $roles `
            -LegacyRoleOid $legacyOid
    }
    if ($phase -ceq "unregistered") {
        if ([uint32]$database.OwnerRoleOid -ne [uint32]$legacyOid) {
            throw "C07 legacy adoption 无法收编 owner 已改变的未登记 residue。"
        }
        $rolesCreatedMarker = New-TicketboxC07DatabaseMarker `
            -OperationId $operation.ToString("D") `
            -Mode "legacy_adoption" `
            -Phase "roles_created" `
            -Catalog $database `
            -Roles $roles `
            -LegacyRoleOid $legacyOid
        Set-TicketboxC07DatabaseMarker `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName `
            -Marker $rolesCreatedMarker `
            -Label "C07 legacy adoption operation registration"
        $phase = "roles_created"
    }
    if ($phase -ceq "roles_created") {
        $reassignedCatalog = Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $script:TicketboxC07DatabaseName
        $reassignedCatalog.OwnerRoleOid = $roles.OwnerRoleOid
        $reassignedMarker = New-TicketboxC07DatabaseMarker `
            -OperationId $operation.ToString("D") `
            -Mode "legacy_adoption" `
            -Phase "objects_reassigned" `
            -Catalog $reassignedCatalog `
            -Roles $roles `
            -LegacyRoleOid $legacyOid
        $reassignedMarkerLiteral = ConvertTo-TicketboxC07SqlLiteral $reassignedMarker
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "C07 legacy object adoption transaction" `
            -Sql @"
BEGIN;
REASSIGN OWNED BY "$script:TicketboxC07LegacyRuntimeRole"
    TO "$script:TicketboxC07OwnerRole";
REVOKE ALL ON DATABASE "$script:TicketboxC07DatabaseName"
    FROM "$script:TicketboxC07LegacyRuntimeRole";
REVOKE ALL ON SCHEMA public FROM "$script:TicketboxC07LegacyRuntimeRole";
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "$script:TicketboxC07LegacyRuntimeRole";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "$script:TicketboxC07LegacyRuntimeRole";
REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA public
    FROM "$script:TicketboxC07LegacyRuntimeRole";
DROP OWNED BY "$script:TicketboxC07LegacyRuntimeRole";
DO `$ticketbox_membership`$
DECLARE membership_record record;
BEGIN
    FOR membership_record IN
        SELECT granted.rolname AS granted_name, member.rolname AS member_name
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE membership.roleid = $legacyOid OR membership.member = $legacyOid
    LOOP
        EXECUTE format(
            'REVOKE %I FROM %I',
            membership_record.granted_name,
            membership_record.member_name
        );
    END LOOP;
END
`$ticketbox_membership`$;
ALTER ROLE "$script:TicketboxC07LegacyRuntimeRole" NOLOGIN PASSWORD NULL;
COMMENT ON DATABASE "$script:TicketboxC07DatabaseName" IS $reassignedMarkerLiteral;
COMMIT;
"@ | Out-Null
        $phase = "objects_reassigned"
    }
    $readyCatalog = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    $readyMarker = New-TicketboxC07DatabaseMarker `
        -OperationId $operation.ToString("D") `
        -Mode "legacy_adoption" `
        -Phase "authority_ready" `
        -Catalog $readyCatalog `
        -Roles $roles `
        -LegacyRoleOid $legacyOid
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database $script:TicketboxC07DatabaseName `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Sql (Get-TicketboxC07DatabasePrivilegeSql -PreserveRuntimeFence) `
        -Label "C07 legacy privilege transaction" | Out-Null
    $frozen = Get-TicketboxC07WriterDatabaseFenceObservation `
        -AuthorityPhase "managed_frozen"
    Assert-TicketboxC07WriterDatabaseFence -Observation $frozen
    Assert-TicketboxC07LegacyRoleRetired `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -LegacyRoleOid $legacyOid
    Assert-TicketboxC07MigratorCredential `
        -Authority $authority `
        -MigratorPassword $MigratorPassword
    Set-TicketboxC07DatabaseMarker `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName `
        -Marker $readyMarker `
        -Label "C07 legacy authority READY publication"
    $final = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
    $finalPhase = Assert-TicketboxC07DatabaseMarker `
        -Catalog $final `
        -OperationId $operation.ToString("D") `
        -Mode "legacy_adoption" `
        -Roles $roles `
        -LegacyRoleOid $legacyOid
    if ($finalPhase -cne "authority_ready" -or -not $final.AllowsConnections) {
        throw "C07 legacy database authority 未到达可复读 READY phase。"
    }
    return Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $script:TicketboxC07DatabaseName
}

function Test-TicketboxC07DatabaseRoleMatrix {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [AllowNull()][Security.SecureString]$RuntimePassword,
        [AllowNull()][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][string]$OperationId
    )

    Assert-TicketboxC07SecureString $SuperuserPassword "C07 role test superuser authority"
    Assert-TicketboxC07SecureString $RuntimePassword "C07 role test runtime credential"
    Assert-TicketboxC07SecureString $MigratorPassword "C07 role test migrator credential"
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $probe = "ticketbox_c07_permission_probe_$($operation.ToString('N'))"
    $financialAppendTables = ConvertTo-TicketboxC07SqlTextArray (
        $script:TicketboxC07RuntimeFinancialAppendTables
    )
    $createProbe = @"
BEGIN;
SET LOCAL ROLE "$script:TicketboxC07OwnerRole";
CREATE TABLE public."$probe" (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    value BIGINT NOT NULL
);
CREATE FUNCTION public."${probe}_definer"()
RETURNS BIGINT
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog
AS `$function`$ SELECT 1::BIGINT `$function`$;
COMMIT;
"@
    $dropProbe = @"
BEGIN;
SET LOCAL ROLE "$script:TicketboxC07OwnerRole";
DROP FUNCTION IF EXISTS public."${probe}_definer"();
DROP TABLE IF EXISTS public."$probe";
COMMIT;
"@
    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    try {
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Sql (Get-TicketboxC07DatabasePrivilegeSql) `
            -Label "C07 explicit runtime allowlist application" `
            | Out-Null
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role $script:TicketboxC07MigratorRole `
            -Password $MigratorPassword `
            -Sql $createProbe `
            -Label "C07 role matrix probe create" `
            | Out-Null

        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role $script:TicketboxC07RuntimeRole `
            -Password $RuntimePassword `
            -Label "C07 runtime DML matrix" `
            -Sql @"
BEGIN;
INSERT INTO public.accounts (public_id, display_name, created_at)
VALUES ('$OperationId', 'C07 permission probe', clock_timestamp());
UPDATE public.accounts
SET display_name = 'C07 permission probe updated'
WHERE public_id = '$OperationId';
SELECT display_name FROM public.accounts WHERE public_id = '$OperationId';
SELECT system_identifier::text FROM pg_catalog.pg_control_system();
SELECT pg_catalog.shobj_description(oid, 'pg_database')
FROM pg_catalog.pg_database
WHERE datname = current_database();
DELETE FROM public.accounts WHERE public_id = '$OperationId';
ROLLBACK;
"@ | Out-Null

        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role $script:TicketboxC07RuntimeRole `
            -Password $RuntimePassword `
            -Label "C07 runtime DDL denial matrix" `
            -Sql @"
DO `$ticketbox`$
DECLARE
    denied boolean;
    fact_table text;
BEGIN
    denied := false;
    BEGIN EXECUTE 'CREATE TABLE public."${probe}_runtime_create" (id bigint)';
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN RAISE EXCEPTION 'runtime CREATE unexpectedly succeeded'; END IF;

    denied := false;
    BEGIN EXECUTE 'ALTER TABLE public."$probe" ADD COLUMN runtime_alter bigint';
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN RAISE EXCEPTION 'runtime ALTER unexpectedly succeeded'; END IF;

    denied := false;
    BEGIN EXECUTE 'DROP TABLE public."$probe"';
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN RAISE EXCEPTION 'runtime DROP unexpectedly succeeded'; END IF;
END
`$ticketbox`$;
"@ | Out-Null

        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role $script:TicketboxC07RuntimeRole `
            -Password $RuntimePassword `
            -Label "C07 future authority and routine denial matrix" `
            -Sql @"
DO `$ticketbox`$
DECLARE denied boolean;
BEGIN
    denied := false;
    BEGIN EXECUTE 'INSERT INTO public."$probe" (value) VALUES (1)';
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN
        RAISE EXCEPTION 'future authority table DML unexpectedly succeeded';
    END IF;

    denied := false;
    BEGIN PERFORM public."${probe}_definer"();
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN
        RAISE EXCEPTION 'future SECURITY DEFINER EXECUTE unexpectedly succeeded';
    END IF;

    denied := false;
    BEGIN DELETE FROM public.app_meta WHERE false;
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN RAISE EXCEPTION 'app_meta DELETE unexpectedly succeeded'; END IF;

    denied := false;
    BEGIN UPDATE public.schema_migrations SET note = note WHERE false;
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN
        RAISE EXCEPTION 'schema_migrations UPDATE unexpectedly succeeded';
    END IF;

    denied := false;
    BEGIN UPDATE public.alembic_version SET version_num = version_num WHERE false;
    EXCEPTION WHEN insufficient_privilege THEN denied := true;
    END;
    IF NOT denied THEN
        RAISE EXCEPTION 'alembic_version UPDATE unexpectedly succeeded';
    END IF;

    FOREACH fact_table IN ARRAY $financialAppendTables LOOP
        denied := false;
        BEGIN
            EXECUTE format(
                'UPDATE public.%I SET id = id WHERE false',
                fact_table
            );
        EXCEPTION WHEN insufficient_privilege THEN denied := true;
        END;
        IF NOT denied THEN
            RAISE EXCEPTION 'append-only fact % UPDATE unexpectedly succeeded', fact_table;
        END IF;

        denied := false;
        BEGIN
            EXECUTE format('DELETE FROM public.%I WHERE false', fact_table);
        EXCEPTION WHEN insufficient_privilege THEN denied := true;
        END;
        IF NOT denied THEN
            RAISE EXCEPTION 'append-only fact % DELETE unexpectedly succeeded', fact_table;
        END IF;

        denied := false;
        BEGIN
            EXECUTE format('TRUNCATE TABLE public.%I', fact_table);
        EXCEPTION WHEN insufficient_privilege THEN denied := true;
        END;
        IF NOT denied THEN
            RAISE EXCEPTION 'append-only fact % TRUNCATE unexpectedly succeeded', fact_table;
        END IF;
    END LOOP;
END
`$ticketbox`$;
"@ | Out-Null

        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database $script:TicketboxC07DatabaseName `
            -Role $script:TicketboxC07MigratorRole `
            -Password $MigratorPassword `
            -Label "C07 migrator SET LOCAL ROLE matrix" `
            -Sql @"
BEGIN;
SET LOCAL ROLE "$script:TicketboxC07OwnerRole";
ALTER TABLE public."$probe" ADD COLUMN migrator_probe BIGINT;
ROLLBACK;
"@ | Out-Null
    }
    finally {
        try {
            Invoke-TicketboxC07Sql `
                -Authority $authority `
                -Database $script:TicketboxC07DatabaseName `
                -Role $script:TicketboxC07MigratorRole `
                -Password $MigratorPassword `
                -Sql $dropProbe `
                -Label "C07 role matrix probe cleanup" `
                | Out-Null
        }
        catch {
            if (
                [string]$_.Exception.Data["TicketboxC07FailureClass"] -ceq
                    "invariant"
            ) {
                throw
            }
            throw "C07 role matrix probe cleanup 失败；数据库保持非 READY。"
        }
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

function Enable-TicketboxC07MigratorForManagedSchemaUpgrade {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][Security.SecureString]$RuntimePassword,
        [Parameter(Mandatory = $true)][Security.SecureString]$MigratorPassword,
        [Parameter(Mandatory = $true)][DateTime]$MigratorValidUntilUtc,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )

    Assert-TicketboxC07SecureString `
        $SuperuserPassword `
        "managed schema superuser authority"
    Assert-TicketboxC07MigratorCredentialWindow $MigratorValidUntilUtc
    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    Get-TicketboxC07RoleBootstrapIdentity `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $OperationId `
        -Mode $Mode | Out-Null

    $migratorVerifier = ConvertTo-TicketboxC07ScramVerifier $MigratorPassword
    $migratorVerifierSql = Escape-SqlLiteral $migratorVerifier
    $validUntil = $MigratorValidUntilUtc.ToUniversalTime().ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ",
        [Globalization.CultureInfo]::InvariantCulture
    )
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "managed schema migrator activation" `
        -Sql @"
BEGIN;
DO `$ticketbox`$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_authid
        WHERE rolname = '$script:TicketboxC07OwnerRole'
          AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
          AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'schema owner role is not least privilege';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_authid
        WHERE rolname = '$script:TicketboxC07RuntimeRole'
          AND rolcanlogin AND rolinherit AND NOT rolsuper AND NOT rolcreatedb
          AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls
          AND rolpassword IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'runtime role authority drifted';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_authid
        WHERE rolname = '$script:TicketboxC07MigratorRole'
          AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
          AND NOT rolbypassrls AND rolconnlimit = 1 AND rolpassword IS NULL
    ) THEN
        RAISE EXCEPTION 'migrator is not fully retired';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE granted.rolname IN (
                  '$script:TicketboxC07OwnerRole',
                  '$script:TicketboxC07MigratorRole',
                  '$script:TicketboxC07RuntimeRole'
              )
           OR member.rolname IN (
                  '$script:TicketboxC07OwnerRole',
                  '$script:TicketboxC07MigratorRole',
                  '$script:TicketboxC07RuntimeRole'
              )
    ) THEN
        RAISE EXCEPTION 'retired role membership residue exists';
    END IF;
END
`$ticketbox`$;
ALTER ROLE "$script:TicketboxC07MigratorRole"
    LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1
    PASSWORD '$migratorVerifierSql' VALID UNTIL '$validUntil';
GRANT CONNECT ON DATABASE "$script:TicketboxC07DatabaseName"
    TO "$script:TicketboxC07MigratorRole";
GRANT "$script:TicketboxC07OwnerRole" TO "$script:TicketboxC07MigratorRole"
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
COMMIT;
"@ | Out-Null
    Assert-TicketboxC07RoleCredentials `
        -Authority $authority `
        -RuntimePassword $RuntimePassword `
        -MigratorPassword $MigratorPassword
}

function Disable-TicketboxC07MigratorLogin {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("fresh_install", "legacy_adoption")]
        [string]$Mode
    )

    Assert-TicketboxC07SecureString $SuperuserPassword "C07 migrator disable superuser authority"
    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    Get-TicketboxC07RoleBootstrapIdentity `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -OperationId $OperationId `
        -Mode $Mode | Out-Null
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 migrator credential retirement" `
        -Sql (Get-TicketboxC07MigratorRetirementSql) | Out-Null
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 migrator retirement zero verification" `
        -Sql (Get-TicketboxC07MigratorRetirementVerificationSql) | Out-Null
}

function ConvertTo-TicketboxC07OperationGuid {
    param([Parameter(Mandatory = $true)][string]$OperationId)

    $parsed = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($OperationId, "D", [ref]$parsed) -or
        $parsed -eq [Guid]::Empty
    ) {
        throw "C07 operation ID 必须是非空 canonical GUID。"
    }
    if ($parsed.ToString("D") -cne $OperationId) {
        throw "C07 operation ID 不是 canonical lowercase GUID。"
    }
    return $parsed
}

function ConvertTo-TicketboxC07RestoreAttemptGuid {
    param([Parameter(Mandatory = $true)][string]$AttemptId)

    $parsed = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact($AttemptId, "D", [ref]$parsed) -or
        $parsed -eq [Guid]::Empty -or
        $AttemptId -cne $parsed.ToString("D")
    ) {
        throw "C07 restore create attempt ID 必须是 canonical non-empty UUID。"
    }
    return $parsed
}

function Get-TicketboxC07RestoreDatabaseName {
    param(
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$CreateAttemptId
    )
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $attempt =
        ConvertTo-TicketboxC07RestoreAttemptGuid $CreateAttemptId
    $binding = (
        "ticketbox-c07-restore-attempt-v1|" +
        "$($operation.ToString('D'))|$($attempt.ToString('D'))"
    )
    $digest =
        (Get-TicketboxC07DatabaseTextSha256 $binding).ToLowerInvariant()
    return $script:TicketboxC07RestorePrefix + $digest.Substring(0, 40)
}

function Get-TicketboxC07LegacyRestoreDatabaseName {
    param([Parameter(Mandatory = $true)][string]$OperationId)

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    return $script:TicketboxC07RestorePrefix + $operation.ToString("N")
}

function Assert-TicketboxC07RestoreDatabaseName {
    param([Parameter(Mandatory = $true)][string]$Database)

    $prefix = [regex]::Escape($script:TicketboxC07RestorePrefix)
    if ($Database -cnotmatch "^${prefix}[0-9a-f]{40}$") {
        throw "C07 restore database name 不属于 canonical attempt namespace。"
    }
}

function Get-TicketboxC07RestoreNamespaceDatabases {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword
    )
    $prefixLiteral =
        ConvertTo-TicketboxC07SqlLiteral $script:TicketboxC07RestorePrefix
    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 restore attempt namespace inspect" `
        -Sql @"
SELECT datname
FROM pg_database
WHERE left(datname, length($prefixLiteral)) = $prefixLiteral
ORDER BY datname;
"@
    $entries = @(
        $output -split "`r?`n" |
            ForEach-Object { [string]$_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if (@($entries | Select-Object -Unique).Count -ne $entries.Count) {
        throw "C07 restore namespace catalog 返回重复 database name。"
    }
    return $entries
}

function Assert-TicketboxC07RestoreAttemptNamespace {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$ExpectedDatabase
    )
    Assert-TicketboxC07RestoreDatabaseName $ExpectedDatabase
    $entries = @(
        Get-TicketboxC07RestoreNamespaceDatabases `
            -Authority $Authority `
            -SuperuserPassword $SuperuserPassword
    )
    if (@($entries | Where-Object { $_ -cne $ExpectedDatabase }).Count -gt 0) {
        throw (
            "C07 restore namespace 含 legacy/other-attempt/foreign database；" +
            "拒绝收编或删除。"
        )
    }
    return $entries
}

function Assert-TicketboxC07UnregisteredRestoreAttemptFence {
    param(
        [Parameter(Mandatory = $true)][object]$Authority,
        [Parameter(Mandatory = $true)][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][uint32]$OwnerRoleOid
    )
    Assert-TicketboxC07RestoreDatabaseName $Database
    $databaseLiteral = ConvertTo-TicketboxC07SqlLiteral $Database
    $output = Invoke-TicketboxC07Sql `
        -Authority $Authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 unregistered restore attempt fence inspect" `
        -Sql @"
SELECT
    (database.datname = $databaseLiteral)::text || E'\t' ||
    (database.datdba = $OwnerRoleOid)::text || E'\t' ||
    (NOT database.datallowconn)::text || E'\t' ||
    (NOT database.datistemplate)::text || E'\t' ||
    (database.encoding = pg_char_to_encoding('UTF8'))::text || E'\t' ||
    (database.datconnlimit = -1)::text || E'\t' ||
    (database.datacl IS NULL)::text || E'\t' ||
    (COALESCE(shobj_description(database.oid, 'pg_database'), '') = '')::text ||
        E'\t' ||
    (NOT EXISTS (
        SELECT 1
        FROM pg_stat_activity AS activity
        WHERE activity.datname = database.datname
          AND activity.pid <> pg_backend_pid()
    ))::text
FROM pg_database AS database
WHERE database.datname = $databaseLiteral;
"@
    $fields = ConvertFrom-TicketboxC07SingleRow `
        -Output $output `
        -FieldCount 9 `
        -Label "C07 unregistered restore attempt fence inspect"
    if (@($fields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw (
            "C07 unregistered restore database 不满足 exact attempt " +
            "name/owner/fenced-empty-comment shape。"
        )
    }
}

function Get-TicketboxC07RestoreDatabaseCreateSql {
    param([Parameter(Mandatory = $true)][string]$Database)

    Assert-TicketboxC07RestoreDatabaseName $Database
    return @"
CREATE DATABASE "$Database"
    OWNER "$script:TicketboxC07OwnerRole" TEMPLATE template0 ENCODING 'UTF8'
    ALLOW_CONNECTIONS false;
"@
}

function Get-TicketboxC07RestoreDatabaseOpenSql {
    param(
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$ActiveMarker
    )

    Assert-TicketboxC07RestoreDatabaseName $Database
    $markerParts = @($ActiveMarker.Split([char]"|"))
    if (
        $markerParts.Count -gt 0 -and
        $markerParts[0] -ceq $script:TicketboxC07LegacyRestoreMarkerSchema
    ) {
        throw (
            "C07 legacy restore marker v2 缺少 create-attempt binding；" +
            "拒绝静默开放。"
        )
    }
    if (
        $markerParts.Count -ne 9 -or
        $markerParts[0] -cne $script:TicketboxC07RestoreMarkerSchema -or
        $markerParts[3] -cne "active" -or
        (Get-TicketboxC07RestoreDatabaseName `
            -OperationId $markerParts[1] `
            -CreateAttemptId $markerParts[2]) -cne $Database -or
        $markerParts[4] -cnotmatch '^[1-9][0-9]{0,19}$' -or
        $markerParts[5] -cne $Database -or
        $markerParts[6] -cnotmatch '^[1-9][0-9]{0,9}$' -or
        $markerParts[7] -cnotmatch '^[1-9][0-9]{0,9}$' -or
        $markerParts[8] -cnotmatch '^[1-9][0-9]{0,9}$'
    ) {
        throw "C07 restore open 只接受 validated active marker。"
    }
    ConvertTo-TicketboxC07RestoreAttemptGuid $markerParts[2] | Out-Null
    $activeMarkerLiteral = ConvertTo-TicketboxC07SqlLiteral $ActiveMarker
    return @"
BEGIN;
DO `$ticketbox`$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE datname = '$Database'
          AND pid <> pg_backend_pid()
    ) THEN
        RAISE EXCEPTION 'C07 restore database has a foreign active session';
    END IF;
END
`$ticketbox`$;
REVOKE ALL ON DATABASE "$Database" FROM PUBLIC;
REVOKE ALL ON DATABASE "$Database" FROM "$script:TicketboxC07RuntimeRole";
REVOKE ALL ON DATABASE "$Database" FROM "$script:TicketboxC07MigratorRole";
DO `$ticketbox`$
DECLARE
    foreign_grantee record;
BEGIN
    FOR foreign_grantee IN
        SELECT DISTINCT role.rolname
        FROM pg_database AS database
        CROSS JOIN LATERAL aclexplode(
                 COALESCE(database.datacl, acldefault('d', database.datdba))
             ) AS acl
        JOIN pg_roles AS role ON role.oid = acl.grantee
        WHERE database.datname = '$Database'
          AND acl.grantee <> database.datdba
    LOOP
        EXECUTE format(
            'REVOKE ALL PRIVILEGES ON DATABASE %I FROM %I',
            '$Database',
            foreign_grantee.rolname
        );
    END LOOP;
END
`$ticketbox`$;
COMMENT ON DATABASE "$Database" IS $activeMarkerLiteral;
ALTER DATABASE "$Database" ALLOW_CONNECTIONS true;
COMMIT;
"@
}

function Assert-TicketboxC07RestoreCreateIntent {
    param(
        [Parameter(Mandatory = $true)][object]$CreateIntent,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$OperationKind,
        [Parameter(Mandatory = $true)][string]$TargetAlembicRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256
    )

    $wrapperProperties = @(
        "Payload",
        "PayloadSha256",
        "CreateAuthoritySha256",
        "AttemptId",
        "Path"
    )
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $CreateIntent `
        -Names $wrapperProperties `
        -Label "C07 protected restore create-intent wrapper" `
        -Exact
    $payloadProperties = @(
        "schema",
        "operation_id",
        "operation_kind",
        "target_alembic_revision",
        "revision_manifest_sha256",
        "installation_id",
        "cluster_system_identifier",
        "database",
        "attempt_id",
        "generation_payload_sha256",
        "create_authority_sha256",
        "database_oid",
        "state",
        "integrity_scope",
        "updated_at_utc"
    )
    $payload = $CreateIntent.Payload
    Assert-TicketboxC07DatabaseRequiredProperties `
        -Value $payload `
        -Names $payloadProperties `
        -Label "C07 protected restore create-intent payload" `
        -Exact
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $operationText = $operation.ToString("D")
    $intentOperation = ConvertTo-TicketboxC07OperationGuid (
        [string]$payload.operation_id
    )
    $installation = [Guid]::Empty
    $attempt = [Guid]::Empty
    if (
        -not [Guid]::TryParseExact(
            [string]$payload.installation_id,
            "D",
            [ref]$installation
        ) -or
        $installation -eq [Guid]::Empty -or
        [string]$payload.installation_id -cne $installation.ToString("D") -or
        -not [Guid]::TryParseExact(
            [string]$payload.attempt_id,
            "D",
            [ref]$attempt
        ) -or
        $attempt -eq [Guid]::Empty -or
        [string]$payload.attempt_id -cne $attempt.ToString("D")
    ) {
        throw "C07 protected restore create-intent GUID binding 无效。"
    }
    Assert-TicketboxC07DatabaseSha256 `
        -Value ([string]$CreateIntent.PayloadSha256) `
        -Label "C07 protected restore create-intent payload"
    Assert-TicketboxC07DatabaseSha256 `
        -Value ([string]$payload.generation_payload_sha256) `
        -Label "C07 protected restore generation payload"
    Assert-TicketboxC07DatabaseSha256 `
        -Value ([string]$payload.create_authority_sha256) `
        -Label "C07 protected restore create authority"
    Assert-TicketboxC07HostSha256 `
        -Value $RevisionManifestSha256 `
        -Label "C07 expected restore revision manifest"
    Assert-TicketboxC07HostSha256 `
        -Value ([string]$payload.revision_manifest_sha256) `
        -Label "C07 protected restore revision manifest"
    $expectedAuthority = Get-TicketboxC07DatabaseTextSha256 (
        @(
            "schema=$script:TicketboxC07RecoveryRestoreCreateIntentSchema",
            "operation_id=$operationText",
            "operation_kind=$OperationKind",
            "target_alembic_revision=$TargetAlembicRevision",
            "revision_manifest_sha256=$RevisionManifestSha256",
            "installation_id=$($installation.ToString('D'))",
            "cluster_system_identifier=$([string]$payload.cluster_system_identifier)",
            "database=$Database",
            "attempt_id=$($attempt.ToString('D'))",
            "generation_payload_sha256=$([string]$payload.generation_payload_sha256)",
            "integrity_scope=$script:TicketboxC07RecoveryIntegrityScope"
        ) -join "`n"
    )
    $updatedAt = [DateTimeOffset]::MinValue
    if (
        [string]$payload.schema -cne
            $script:TicketboxC07RecoveryRestoreCreateIntentSchema -or
        $intentOperation -ne $operation -or
        [string]$payload.operation_id -cne $operationText -or
        [string]$payload.operation_kind -cne $OperationKind -or
        [string]$payload.target_alembic_revision -cne
            $TargetAlembicRevision -or
        [string]$payload.revision_manifest_sha256 -cne
            $RevisionManifestSha256 -or
        [string]$payload.database -cne $Database -or
        [string]$payload.cluster_system_identifier -cnotmatch
            '^[1-9][0-9]{0,19}$' -or
        [string]$payload.create_authority_sha256 -cne $expectedAuthority -or
        [string]$CreateIntent.CreateAuthoritySha256 -cne $expectedAuthority -or
        [string]$CreateIntent.AttemptId -cne $attempt.ToString("D") -or
        [string]$payload.integrity_scope -cne
            $script:TicketboxC07RecoveryIntegrityScope -or
        [string]$payload.state -cnotin @(
            "create_pending",
            "identity_bound"
        ) -or
        [string]::IsNullOrWhiteSpace([string]$CreateIntent.Path) -or
        -not [DateTimeOffset]::TryParseExact(
            [string]$payload.updated_at_utc,
            "o",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$updatedAt
        ) -or
        $updatedAt.Offset -ne [TimeSpan]::Zero
    ) {
        throw "C07 protected restore create-intent exact authority binding 不一致。"
    }
    $databaseOid = [uint32]0
    if ([string]$payload.state -ceq "create_pending") {
        if (-not [string]::IsNullOrEmpty([string]$payload.database_oid)) {
            throw "C07 create_pending intent 不得提前绑定 database OID。"
        }
    }
    elseif (
        -not [uint32]::TryParse(
            [string]$payload.database_oid,
            [ref]$databaseOid
        ) -or
        $databaseOid -lt 1
    ) {
        throw "C07 identity_bound intent database OID 无效。"
    }
    return [pscustomobject]@{
        OperationId = $operationText
        Database = $Database
        ClusterSystemIdentifier =
            [string]$payload.cluster_system_identifier
        AttemptId = $attempt.ToString("D")
        CreateAuthoritySha256 = $expectedAuthority
        State = [string]$payload.state
        DatabaseOid = $databaseOid
    }
}

function New-TicketboxC07RestoreDatabase {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][object]$CreateIntent,
        [Parameter(Mandatory = $true)][string]$OperationKind,
        [Parameter(Mandatory = $true)][string]$TargetAlembicRevision,
        [Parameter(Mandatory = $true)][string]$RevisionManifestSha256,
        [AllowNull()][scriptblock]$AfterCreateCrashProbe = $null
    )

    Assert-TicketboxC07SecureString $SuperuserPassword "C07 restore superuser authority"
    $createAttempt =
        ConvertTo-TicketboxC07RestoreAttemptGuid (
            [string]$CreateIntent.AttemptId
        )
    $database = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $OperationId `
        -CreateAttemptId $createAttempt.ToString("D")
    $intent = Assert-TicketboxC07RestoreCreateIntent `
        -CreateIntent $CreateIntent `
        -OperationId $OperationId `
        -Database $database `
        -OperationKind $OperationKind `
        -TargetAlembicRevision $TargetAlembicRevision `
        -RevisionManifestSha256 $RevisionManifestSha256
    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    Assert-TicketboxC07RestoreAttemptNamespace `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -ExpectedDatabase $database | Out-Null
    $catalog = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $database
    if (
        [string]$catalog.ClusterSystemIdentifier -cne
            [string]$intent.ClusterSystemIdentifier
    ) {
        throw "C07 protected restore create-intent cluster authority 不一致。"
    }
    if (
        $intent.State -ceq "identity_bound" -and
        (
            -not $catalog.Exists -or
            [uint32]$catalog.DatabaseOid -ne [uint32]$intent.DatabaseOid
        )
    ) {
        throw "C07 identity_bound intent 与 live database identity 不一致。"
    }
    $ownerRoleOid = Get-TicketboxC07RoleOid `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Role $script:TicketboxC07OwnerRole
    $migratorRoleOid = Get-TicketboxC07RoleOid `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Role $script:TicketboxC07MigratorRole
    if (-not $catalog.Exists) {
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "C07 isolated restore database create" `
            -Sql (Get-TicketboxC07RestoreDatabaseCreateSql $database) | Out-Null
        if ($null -ne $AfterCreateCrashProbe) {
            & $AfterCreateCrashProbe $database $intent.AttemptId
        }
        $catalog = Get-TicketboxC07DatabaseCatalogObservation `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $database
    }
    if (
        -not $catalog.Exists -or
        [uint32]$catalog.OwnerRoleOid -ne [uint32]$ownerRoleOid
    ) {
        throw "C07 isolated restore database owner/OID 与 C07 authority 不一致。"
    }
    $phase = "unregistered"
    if (-not [string]::IsNullOrEmpty($catalog.Marker)) {
        $phase = Assert-TicketboxC07RestoreDatabaseMarker `
            -Catalog $catalog `
            -OperationId $OperationId `
            -CreateAttemptId $intent.AttemptId `
            -OwnerRoleOid $ownerRoleOid `
            -MigratorRoleOid $migratorRoleOid
    }
    else {
        if ($intent.State -cne "create_pending") {
            throw (
                "C07 restore database marker 丢失且 intent 已越过 create_pending；" +
                "拒绝重建身份。"
            )
        }
        Assert-TicketboxC07RestoreAttemptNamespace `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -ExpectedDatabase $database | Out-Null
        Assert-TicketboxC07UnregisteredRestoreAttemptFence `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $database `
            -OwnerRoleOid $ownerRoleOid
    }
    if ($phase -ceq "unregistered") {
        $registeredMarker = New-TicketboxC07RestoreDatabaseMarker `
            -Catalog $catalog `
            -OperationId $OperationId `
            -CreateAttemptId $intent.AttemptId `
            -Phase "registered" `
            -OwnerRoleOid $ownerRoleOid `
            -MigratorRoleOid $migratorRoleOid
        Set-TicketboxC07DatabaseMarker `
            -Authority $authority `
            -SuperuserPassword $SuperuserPassword `
            -Database $database `
            -Marker $registeredMarker `
            -Label "C07 isolated restore exact identity registration"
        $catalog.Marker = $registeredMarker
        $phase = "registered"
    }
    if ($phase -ceq "registered") {
        $activeMarker = New-TicketboxC07RestoreDatabaseMarker `
            -Catalog $catalog `
            -OperationId $OperationId `
            -CreateAttemptId $intent.AttemptId `
            -Phase "active" `
            -OwnerRoleOid $ownerRoleOid `
            -MigratorRoleOid $migratorRoleOid
        Invoke-TicketboxC07Sql `
            -Authority $authority `
            -Database "postgres" `
            -Role "postgres" `
            -Password $SuperuserPassword `
            -Label "C07 isolated restore ACL/open transaction" `
            -Sql (Get-TicketboxC07RestoreDatabaseOpenSql `
                -Database $database `
                -ActiveMarker $activeMarker) | Out-Null
        $phase = "active"
    }
    $final = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database $database
    $finalPhase = Assert-TicketboxC07RestoreDatabaseMarker `
        -Catalog $final `
        -OperationId $OperationId `
        -CreateAttemptId $intent.AttemptId `
        -OwnerRoleOid $ownerRoleOid `
        -MigratorRoleOid $migratorRoleOid
    if ($finalPhase -cne "active" -or -not $final.AllowsConnections) {
        throw "C07 isolated restore database 未到达 active phase。"
    }
    $acl = Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 isolated restore database ACL verification" `
        -Sql @"
SELECT
    (NOT has_database_privilege(
        '$script:TicketboxC07MigratorRole', '$database', 'CONNECT'
    ))::text || E'\t' ||
    (NOT has_database_privilege(
        '$script:TicketboxC07RuntimeRole', '$database', 'CONNECT'
    ))::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1
        FROM pg_database AS database,
             LATERAL aclexplode(
                 COALESCE(database.datacl, acldefault('d', database.datdba))
             ) AS acl
        WHERE database.datname = '$database'
           AND acl.grantee = 0
    ))::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1
        FROM pg_database AS database,
             LATERAL aclexplode(
                 COALESCE(database.datacl, acldefault('d', database.datdba))
             ) AS acl
        WHERE database.datname = '$database'
          AND acl.grantee <> database.datdba
    ))::text || E'\t' ||
    (NOT EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE datname = '$database'
          AND pid <> pg_backend_pid()
    ))::text;
"@
    $aclFields = ConvertFrom-TicketboxC07SingleRow `
        -Output $acl `
        -FieldCount 5 `
        -Label "C07 isolated restore database ACL verification"
    if (@($aclFields | Where-Object { $_ -cne "true" }).Count -ne 0) {
        throw "C07 isolated restore database ACL 未保持最小授权。"
    }
    return [pscustomobject]@{
        Schema = $script:TicketboxC07RestoreIdentitySchema
        OperationId = $OperationId
        ClusterSystemIdentifier = $final.ClusterSystemIdentifier
        Database = $final.Database
        DatabaseOid = [uint32]$final.DatabaseOid
        OwnerRoleOid = [uint32]$ownerRoleOid
        MigratorRoleOid = [uint32]$migratorRoleOid
        MarkerPhase = "active"
        State = "active"
        CreateAttemptId = [string]$intent.AttemptId
    }
}

function New-TicketboxC07RestoreDatabaseMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$CreateAttemptId,
        [Parameter(Mandatory = $true)]
        [ValidateSet("registered", "active", "cleanup_pending")]
        [string]$Phase,
        [Parameter(Mandatory = $true)][uint32]$OwnerRoleOid,
        [Parameter(Mandatory = $true)][uint32]$MigratorRoleOid
    )

    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $attempt = ConvertTo-TicketboxC07RestoreAttemptGuid $CreateAttemptId
    $expectedDatabase = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $OperationId `
        -CreateAttemptId $CreateAttemptId
    if (
        -not $Catalog.Exists -or
        [string]$Catalog.Database -cne $expectedDatabase -or
        [uint32]$Catalog.DatabaseOid -lt 1 -or
        [uint32]$Catalog.OwnerRoleOid -ne $OwnerRoleOid -or
        $MigratorRoleOid -lt 1
    ) {
        throw "C07 restore marker 缺少 exact database/role identity。"
    }
    return (
        "$script:TicketboxC07RestoreMarkerSchema|" +
        "$($operation.ToString('D'))|$($attempt.ToString('D'))|$Phase|" +
        "$($Catalog.ClusterSystemIdentifier)|$expectedDatabase|" +
        "$($Catalog.DatabaseOid)|$OwnerRoleOid|$MigratorRoleOid"
    )
}

function Assert-TicketboxC07RestoreDatabaseMarker {
    param(
        [Parameter(Mandatory = $true)][object]$Catalog,
        [Parameter(Mandatory = $true)][string]$OperationId,
        [Parameter(Mandatory = $true)][string]$CreateAttemptId,
        [Parameter(Mandatory = $true)][uint32]$OwnerRoleOid,
        [Parameter(Mandatory = $true)][uint32]$MigratorRoleOid
    )

    if ([string]::IsNullOrEmpty([string]$Catalog.Marker)) {
        throw "C07 restore database 缺少 durable ownership marker。"
    }
    $operation = ConvertTo-TicketboxC07OperationGuid $OperationId
    $attempt = ConvertTo-TicketboxC07RestoreAttemptGuid $CreateAttemptId
    $parts = @(([string]$Catalog.Marker).Split([char]"|"))
    if (
        $parts.Count -gt 0 -and
        $parts[0] -ceq $script:TicketboxC07LegacyRestoreMarkerSchema
    ) {
        throw (
            "C07 legacy restore marker v2 缺少 create-attempt binding；" +
            "拒绝静默升级、收编或删除。"
        )
    }
    $expectedDatabase = Get-TicketboxC07RestoreDatabaseName `
        -OperationId $OperationId `
        -CreateAttemptId $CreateAttemptId
    if (
        $parts.Count -ne 9 -or
        $parts[0] -cne $script:TicketboxC07RestoreMarkerSchema -or
        $parts[1] -cne $operation.ToString("D") -or
        $parts[2] -cne $attempt.ToString("D") -or
        $parts[3] -cnotin @("registered", "active", "cleanup_pending") -or
        $parts[4] -cne [string]$Catalog.ClusterSystemIdentifier -or
        $parts[5] -cne $expectedDatabase -or
        $parts[6] -cne [string]$Catalog.DatabaseOid -or
        $parts[7] -cne [string]$OwnerRoleOid -or
        $parts[8] -cne [string]$MigratorRoleOid -or
        [uint32]$Catalog.OwnerRoleOid -ne $OwnerRoleOid
    ) {
        throw (
            "C07 restore database marker 与 live " +
            "attempt/cluster/name/OID/roles 不一致。"
        )
    }
    return $parts[3]
}

function Assert-TicketboxC07RestoreIdentity {
    param([Parameter(Mandatory = $true)][object]$Identity)

    if ($Identity.Schema -cne $script:TicketboxC07RestoreIdentitySchema) {
        throw "C07 restore identity schema 无效。"
    }
    $createAttemptProperty =
        $Identity.PSObject.Properties["CreateAttemptId"]
    if (
        $null -eq $createAttemptProperty -or
        [string]::IsNullOrWhiteSpace([string]$createAttemptProperty.Value)
    ) {
        throw "C07 restore identity 缺少 create-attempt binding。"
    }
    $expectedDatabase = Get-TicketboxC07RestoreDatabaseName `
        -OperationId ([string]$Identity.OperationId) `
        -CreateAttemptId ([string]$createAttemptProperty.Value)
    if ([string]$Identity.Database -cne $expectedDatabase) {
        throw "C07 restore database name 与 operation UUID 不一致。"
    }
    if (
        [string]$Identity.ClusterSystemIdentifier -cnotmatch '^[1-9][0-9]{0,19}$' -or
        [uint64]$Identity.DatabaseOid -lt 1 -or
        [uint64]$Identity.DatabaseOid -gt [uint32]::MaxValue -or
        [uint64]$Identity.OwnerRoleOid -lt 1 -or
        [uint64]$Identity.OwnerRoleOid -gt [uint32]::MaxValue -or
        [uint64]$Identity.MigratorRoleOid -lt 1 -or
        [uint64]$Identity.MigratorRoleOid -gt [uint32]::MaxValue -or
        [string]$Identity.MarkerPhase -cnotin @("active", "cleanup_pending") -or
        [string]$Identity.State -cnotin @("active", "cleanup_pending")
    ) {
        throw "C07 restore identity 的 cluster/OID/state 无效。"
    }
}

function Remove-TicketboxC07RestoreDatabaseExact {
    param(
        [AllowNull()][Security.SecureString]$SuperuserPassword,
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][string]$CreateAttemptId
    )

    Assert-TicketboxC07SecureString $SuperuserPassword "C07 restore cleanup superuser authority"
    Assert-TicketboxC07RestoreIdentity $Identity
    $attempt = ConvertTo-TicketboxC07RestoreAttemptGuid $CreateAttemptId
    if (
        [string]$Identity.CreateAttemptId -cne
            $attempt.ToString("D")
    ) {
        throw "C07 restore cleanup create-attempt identity 不一致。"
    }
    $authority = Resolve-TicketboxC07DatabaseHostAuthority
    Assert-TicketboxC07LiveHostConnection $authority $SuperuserPassword
    $live = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database ([string]$Identity.Database)
    if ($live.ClusterSystemIdentifier -cne [string]$Identity.ClusterSystemIdentifier) {
        throw "C07 restore cleanup cluster system identifier 不匹配；零 mutation 拒绝。"
    }
    if (-not $live.Exists) {
        return [pscustomobject]@{
            Schema = $Identity.Schema
            OperationId = $Identity.OperationId
            ClusterSystemIdentifier = $Identity.ClusterSystemIdentifier
            Database = $Identity.Database
            DatabaseOid = [uint32]$Identity.DatabaseOid
            OwnerRoleOid = [uint32]$Identity.OwnerRoleOid
            MigratorRoleOid = [uint32]$Identity.MigratorRoleOid
            MarkerPhase = "cleanup_pending"
            State = "cleaned"
            CreateAttemptId = $attempt.ToString("D")
        }
    }
    if ([uint32]$live.DatabaseOid -ne [uint32]$Identity.DatabaseOid) {
        throw "C07 restore cleanup database OID 已被替换；零 mutation 拒绝。"
    }
    $catalog = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database ([string]$Identity.Database)
    $markerPhase = Assert-TicketboxC07RestoreDatabaseMarker `
        -Catalog $catalog `
        -OperationId ([string]$Identity.OperationId) `
        -CreateAttemptId ($attempt.ToString("D")) `
        -OwnerRoleOid ([uint32]$Identity.OwnerRoleOid) `
        -MigratorRoleOid ([uint32]$Identity.MigratorRoleOid)
    if ($markerPhase -cnotin @("active", "cleanup_pending")) {
        throw "C07 restore cleanup marker phase 不允许删除。"
    }
    $pendingMarker = New-TicketboxC07RestoreDatabaseMarker `
        -Catalog $catalog `
        -OperationId ([string]$Identity.OperationId) `
        -CreateAttemptId ($attempt.ToString("D")) `
        -Phase "cleanup_pending" `
        -OwnerRoleOid ([uint32]$Identity.OwnerRoleOid) `
        -MigratorRoleOid ([uint32]$Identity.MigratorRoleOid)
    $pendingMarkerLiteral = ConvertTo-TicketboxC07SqlLiteral $pendingMarker
    Invoke-TicketboxC07Sql `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 isolated restore cleanup latch" `
        -Sql @"
BEGIN;
COMMENT ON DATABASE "$($Identity.Database)" IS $pendingMarkerLiteral;
ALTER DATABASE "$($Identity.Database)" ALLOW_CONNECTIONS false;
COMMIT;
"@ | Out-Null
    $dropResult = Invoke-TicketboxC07SqlResult `
        -Authority $authority `
        -Database "postgres" `
        -Role "postgres" `
        -Password $SuperuserPassword `
        -Label "C07 isolated restore database exact cleanup" `
        -Sql "DROP DATABASE `"$($Identity.Database)`" WITH (FORCE);"
    if ($dropResult.ExitCode -ne 0) {
        return [pscustomobject]@{
            Schema = $Identity.Schema
            OperationId = $Identity.OperationId
            ClusterSystemIdentifier = $Identity.ClusterSystemIdentifier
            Database = $Identity.Database
            DatabaseOid = [uint32]$Identity.DatabaseOid
            OwnerRoleOid = [uint32]$Identity.OwnerRoleOid
            MigratorRoleOid = [uint32]$Identity.MigratorRoleOid
            MarkerPhase = "cleanup_pending"
            State = "cleanup_pending"
            CreateAttemptId = $attempt.ToString("D")
        }
    }
    $after = Get-TicketboxC07DatabaseCatalogObservation `
        -Authority $authority `
        -SuperuserPassword $SuperuserPassword `
        -Database ([string]$Identity.Database)
    if ($after.ClusterSystemIdentifier -cne [string]$Identity.ClusterSystemIdentifier) {
        throw "C07 restore cleanup 后 cluster identity 改变。"
    }
    if ($after.Exists) {
        return [pscustomobject]@{
            Schema = $Identity.Schema
            OperationId = $Identity.OperationId
            ClusterSystemIdentifier = $Identity.ClusterSystemIdentifier
            Database = $Identity.Database
            DatabaseOid = [uint32]$Identity.DatabaseOid
            OwnerRoleOid = [uint32]$Identity.OwnerRoleOid
            MigratorRoleOid = [uint32]$Identity.MigratorRoleOid
            MarkerPhase = "cleanup_pending"
            State = "cleanup_pending"
            CreateAttemptId = $attempt.ToString("D")
        }
    }
    return [pscustomobject]@{
        Schema = $Identity.Schema
        OperationId = $Identity.OperationId
        ClusterSystemIdentifier = $Identity.ClusterSystemIdentifier
        Database = $Identity.Database
        DatabaseOid = [uint32]$Identity.DatabaseOid
        OwnerRoleOid = [uint32]$Identity.OwnerRoleOid
        MigratorRoleOid = [uint32]$Identity.MigratorRoleOid
        MarkerPhase = "cleanup_pending"
        State = "cleaned"
        CreateAttemptId = $attempt.ToString("D")
    }
}
