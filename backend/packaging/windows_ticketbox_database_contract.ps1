#Requires -Version 5.1

function New-TicketboxDatabasePolicyFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [Parameter(Mandatory = $true)][string]$FailureCode,
        [Exception]$InnerException
    )

    if ($FailureCode -cnotmatch '^[a-z0-9_]{1,64}$') {
        throw "Ticketbox database policy failure code is invalid."
    }
    $failure = if ($null -eq $InnerException) {
        [InvalidOperationException]::new($Message)
    }
    else {
        [InvalidOperationException]::new($Message, $InnerException)
    }
    $failure.Data["TicketboxFailureCode"] = $FailureCode
    return $failure
}

function Get-TicketboxDatabaseAuthorizationContract {
    return [pscustomobject][ordered]@{
        Schema = "ticketbox-database-authorization-policy-v1"
        DatabaseName = "ticketbox"
        OwnerRole = "ticketbox_owner"
        MigratorRole = "ticketbox_migrator"
        RuntimeRole = "ticketbox_runtime"
        BackupRole = "ticketbox_backup"
        RetiredLegacyRole = "ticketbox"
        BusinessTables = @(
            "accounts", "ai_member_anon_map", "ai_merchant_anon_map",
            "ai_transaction_temp_id_map", "algorithm_decisions",
            "api_idempotency_keys", "auth_tokens", "background_tasks",
            "bill_split_invitations", "bootstrap_secret_consumptions",
            "budget_advisor_quota_locks", "budget_categories", "budgets",
            "category_preferences", "category_rules", "csv_import_batches",
            "csv_import_rows", "dashboard_card_preferences", "debt_goal_links",
            "debts", "desktop_activation_attempts", "device_enrollment_attempts",
            "devices", "duplicate_ignores", "exchange_rates", "expense_items",
            "expense_splits", "expense_tags", "expenses", "fx_rates", "goals",
            "invitations", "ledger_members", "ledgers",
            "member_repayment_proposals", "merchant_aliases", "merchant_catalog",
            "monthly_income_plans", "pairing_attempt_failures", "pairing_codes",
            "recurring_items", "repayment_drafts", "rule_application_batches",
            "rule_application_changes", "scheduler_leases",
            "session_refresh_attempts", "tag_mutation_undo_groups",
            "tag_mutation_undo_items", "tags", "upload_link_daily_usage",
            "upload_link_remote_attempts", "upload_links", "user_ui_preferences"
        )
        FinancialAppendTables = @(
            "debt_adjustments", "debt_forgivenesses", "debt_voids",
            "repayment_voids", "repayments"
        )
        AuthorityTables = @("app_meta", "installation_owner_claims")
        MigrationAppendTables = @("schema_migrations")
        AuditAppendTables = @("ledger_audit_logs")
        AuditMutableTables = @("budget_advisor_audit_logs")
        RetentionFactTables = @("ledger_learning_events", "ocr_facts")
        ReadOnlyTables = @("alembic_version", "dataset_authority")
        ManagedBindingTables = @("installation_currency_bindings")
        ManagedAuthorityTables = @("installation_idempotency_keys")
        ManagedAuditInsertTables = @("installation_currency_audit_log")
    }
}

function Get-TicketboxDatabaseRuntimePrivilegeSpecifications {
    param([switch]$IncludeManagedSchemaCurrencyAuthority)

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $classes = @(
        [pscustomobject]@{ Tables = $policy.BusinessTables; Privileges = @("SELECT", "INSERT", "UPDATE", "DELETE") },
        [pscustomobject]@{ Tables = $policy.FinancialAppendTables; Privileges = @("SELECT", "INSERT") },
        [pscustomobject]@{ Tables = $policy.AuthorityTables; Privileges = @("SELECT", "INSERT", "UPDATE") },
        [pscustomobject]@{ Tables = $policy.MigrationAppendTables; Privileges = @("SELECT", "INSERT") },
        [pscustomobject]@{ Tables = $policy.AuditAppendTables; Privileges = @("SELECT", "INSERT") },
        [pscustomobject]@{ Tables = $policy.AuditMutableTables; Privileges = @("SELECT", "INSERT", "UPDATE", "DELETE") },
        [pscustomobject]@{ Tables = $policy.RetentionFactTables; Privileges = @("SELECT", "INSERT", "DELETE") },
        [pscustomobject]@{ Tables = $policy.ReadOnlyTables; Privileges = @("SELECT") }
    )
    if ($IncludeManagedSchemaCurrencyAuthority) {
        $classes += @(
            [pscustomobject]@{ Tables = $policy.ManagedBindingTables; Privileges = @("SELECT", "UPDATE") },
            [pscustomobject]@{ Tables = $policy.ManagedAuthorityTables; Privileges = @("SELECT", "INSERT", "UPDATE") },
            [pscustomobject]@{ Tables = $policy.ManagedAuditInsertTables; Privileges = @("INSERT") }
        )
    }

    $specifications = @(
        foreach ($class in $classes) {
            foreach ($table in @($class.Tables)) {
                Assert-TicketboxPostgresqlDatabaseIdentifier `
                    -Value ([string]$table) `
                    -Label "Ticketbox runtime table"
                [pscustomobject][ordered]@{
                    Table = [string]$table
                    Privileges = @($class.Privileges)
                }
            }
        }
    )
    $duplicates = @(
        $specifications |
            Group-Object -Property Table |
            Where-Object { $_.Count -ne 1 }
    )
    if ($duplicates.Count -ne 0) {
        throw (New-TicketboxDatabasePolicyFailure `
            -Message "Ticketbox runtime ACL allowlist has duplicate authority." `
            -FailureCode "release_identity_mismatch")
    }
    return $specifications
}

function Get-TicketboxDatabaseSequenceConsumerTables {
    param([switch]$IncludeManagedSchemaCurrencyAuthority)

    $policy = Get-TicketboxDatabaseAuthorizationContract
    $tables = @(
        $policy.BusinessTables +
        $policy.FinancialAppendTables +
        $policy.AuthorityTables +
        $policy.AuditAppendTables +
        $policy.AuditMutableTables +
        $policy.RetentionFactTables
    )
    if ($IncludeManagedSchemaCurrencyAuthority) {
        $tables += @($policy.ManagedAuthorityTables + $policy.ManagedAuditInsertTables)
    }
    return $tables
}
