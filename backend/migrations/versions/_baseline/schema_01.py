"""Frozen PostgreSQL DDL for the 20260524_0001 historical baseline."""

from __future__ import annotations

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE app_meta (
        key VARCHAR(64) NOT NULL,
        value TEXT,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (key)
    )
    """,
    """
    CREATE TABLE pairing_attempt_failures (
        id SERIAL NOT NULL,
        remote_key VARCHAR(120) NOT NULL,
        failed_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE INDEX ix_pairing_attempt_failures_failed_at ON pairing_attempt_failures (failed_at)
    """,
    """
    CREATE INDEX ix_pairing_attempt_failures_remote_key ON pairing_attempt_failures (remote_key)
    """,
    """
    CREATE TABLE background_tasks (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64),
        task_type VARCHAR(64) NOT NULL,
        initiated_by_account_id INTEGER,
        initiated_by_device_id INTEGER,
        status VARCHAR(32) DEFAULT 'queued' NOT NULL,
        progress_current INTEGER DEFAULT '0' NOT NULL,
        progress_total INTEGER,
        progress_message TEXT,
        error_code VARCHAR(64),
        error_message TEXT,
        result_summary_json TEXT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        started_at TIMESTAMP WITH TIME ZONE,
        completed_at TIMESTAMP WITH TIME ZONE,
        last_progress_at TIMESTAMP WITH TIME ZONE,
        cancellation_requested_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_background_tasks_status_valid CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
        CONSTRAINT ck_background_tasks_progress_current_non_negative CHECK (progress_current >= 0),
        CONSTRAINT ck_background_tasks_progress_total_non_negative CHECK (progress_total IS NULL OR progress_total >= 0)
    )
    """,
    """
    CREATE INDEX ix_background_tasks_account_created ON background_tasks (initiated_by_account_id, created_at)
    """,
    """
    CREATE INDEX ix_background_tasks_initiated_by_account_id ON background_tasks (initiated_by_account_id)
    """,
    """
    CREATE UNIQUE INDEX ix_background_tasks_public_id ON background_tasks (public_id)
    """,
    """
    CREATE INDEX ix_background_tasks_status ON background_tasks (status)
    """,
    """
    CREATE INDEX ix_background_tasks_status_last_progress ON background_tasks (status, last_progress_at)
    """,
    """
    CREATE INDEX ix_background_tasks_task_type ON background_tasks (task_type)
    """,
    """
    CREATE INDEX ix_background_tasks_tenant_id ON background_tasks (tenant_id)
    """,
    """
    CREATE TABLE fx_rates (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        source VARCHAR(32) NOT NULL,
        home_currency_code VARCHAR(3) NOT NULL,
        currency_code VARCHAR(3) NOT NULL,
        rate_date DATE NOT NULL,
        rate_to_home NUMERIC(18, 8) NOT NULL,
        provider_base_currency VARCHAR(3) NOT NULL,
        provider_rate NUMERIC(18, 8),
        fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_fx_rates_source_home_currency_date UNIQUE (source, home_currency_code, currency_code, rate_date),
        CONSTRAINT ck_fx_rates_rate_positive CHECK (rate_to_home > 0)
    )
    """,
    """
    CREATE INDEX ix_fx_rates_currency_code ON fx_rates (currency_code)
    """,
    """
    CREATE INDEX ix_fx_rates_home_currency_code ON fx_rates (home_currency_code)
    """,
    """
    CREATE UNIQUE INDEX ix_fx_rates_public_id ON fx_rates (public_id)
    """,
    """
    CREATE INDEX ix_fx_rates_rate_date ON fx_rates (rate_date)
    """,
    """
    CREATE INDEX ix_fx_rates_source ON fx_rates (source)
    """,
    """
    CREATE INDEX ix_fx_rates_source_home_currency_date ON fx_rates (source, home_currency_code, currency_code, rate_date)
    """,
    """
    CREATE TABLE accounts (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        display_name VARCHAR(120) NOT NULL,
        identity_provider VARCHAR(64),
        cloud_subject_id VARCHAR(255),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        disabled_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE UNIQUE INDEX ix_accounts_public_id ON accounts (public_id)
    """,
    """
    CREATE TABLE schema_migrations (
        name VARCHAR(128) NOT NULL,
        applied_at TIMESTAMP WITH TIME ZONE NOT NULL,
        backend_version VARCHAR(32),
        note TEXT,
        PRIMARY KEY (name)
    )
    """,
    """
    CREATE TABLE bootstrap_secret_consumptions (
        secret_hash VARCHAR(64) NOT NULL,
        consumed_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (secret_hash)
    )
    """,
    """
    CREATE TABLE ledgers (
        id SERIAL NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        name VARCHAR(120) NOT NULL,
        owner_account_id INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        archived_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(owner_account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE UNIQUE INDEX ix_ledgers_ledger_id ON ledgers (ledger_id)
    """,
    """
    CREATE INDEX ix_ledgers_owner_account_id ON ledgers (owner_account_id)
    """,
    """
    CREATE TABLE devices (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        account_id INTEGER NOT NULL,
        device_name VARCHAR(120) NOT NULL,
        platform VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        last_seen_at TIMESTAMP WITH TIME ZONE,
        revoked_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        FOREIGN KEY(account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_devices_account_id ON devices (account_id)
    """,
    """
    CREATE UNIQUE INDEX ix_devices_public_id ON devices (public_id)
    """,
    """
    CREATE TABLE user_ui_preferences (
        id SERIAL NOT NULL,
        account_id INTEGER NOT NULL,
        account_name VARCHAR(128) NOT NULL,
        preferences TEXT NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_user_ui_preferences_account_id UNIQUE (account_id),
        CONSTRAINT fk_user_ui_preferences_account FOREIGN KEY(account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_user_ui_preferences_account_id ON user_ui_preferences (account_id)
    """,
    """
    CREATE TABLE ai_merchant_anon_map (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        merchant_canonical VARCHAR(255) NOT NULL,
        anon_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_ai_merchant_anon_canonical UNIQUE (tenant_id, merchant_canonical),
        CONSTRAINT uq_ai_merchant_anon_id UNIQUE (tenant_id, anon_id),
        CONSTRAINT fk_ai_merchant_anon_tenant FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_ai_merchant_anon_map_tenant_id ON ai_merchant_anon_map (tenant_id)
    """,
    """
    CREATE TABLE ai_member_anon_map (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        account_id INTEGER NOT NULL,
        anon_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_ai_member_anon_account UNIQUE (tenant_id, account_id),
        CONSTRAINT uq_ai_member_anon_id UNIQUE (tenant_id, anon_id),
        CONSTRAINT fk_ai_member_anon_tenant FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id),
        CONSTRAINT fk_ai_member_anon_account FOREIGN KEY(account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_ai_member_anon_map_tenant_id ON ai_member_anon_map (tenant_id)
    """,
    """
    CREATE TABLE budget_advisor_audit_logs (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        actor_account_id INTEGER,
        provider VARCHAR(64) NOT NULL,
        model VARCHAR(120),
        base_url VARCHAR(255),
        month VARCHAR(7),
        input_hash VARCHAR(64) NOT NULL,
        success INTEGER DEFAULT '0' NOT NULL,
        error_code VARCHAR(64),
        suggestion_count INTEGER DEFAULT '0' NOT NULL,
        duration_ms INTEGER,
        called_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_budget_advisor_audit_tenant FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id),
        CONSTRAINT fk_budget_advisor_audit_actor FOREIGN KEY(actor_account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_budget_advisor_audit_logs_tenant_id ON budget_advisor_audit_logs (tenant_id)
    """,
    """
    CREATE INDEX ix_budget_advisor_audit_tenant_called_at ON budget_advisor_audit_logs (tenant_id, called_at)
    """,
    """
    CREATE TABLE ai_transaction_temp_id_map (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        session_id VARCHAR(64) NOT NULL,
        expense_id INTEGER NOT NULL,
        temp_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_ai_tx_temp_session_expense UNIQUE (tenant_id, session_id, expense_id),
        CONSTRAINT uq_ai_tx_temp_session_id UNIQUE (tenant_id, session_id, temp_id),
        CONSTRAINT fk_ai_tx_temp_tenant FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_ai_transaction_temp_id_map_tenant_id ON ai_transaction_temp_id_map (tenant_id)
    """,
    """
    CREATE INDEX ix_ai_tx_temp_session ON ai_transaction_temp_id_map (tenant_id, session_id)
    """,
    """
    CREATE TABLE upload_links (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        account_id INTEGER NOT NULL,
        device_id INTEGER NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        default_timezone VARCHAR(64),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        last_used_at TIMESTAMP WITH TIME ZONE,
        revoked_at TIMESTAMP WITH TIME ZONE,
        daily_byte_budget INTEGER,
        per_remote_min_interval_seconds INTEGER DEFAULT '0' NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(account_id) REFERENCES accounts (id),
        FOREIGN KEY(device_id) REFERENCES devices (id),
        FOREIGN KEY(ledger_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_upload_links_account_id ON upload_links (account_id)
    """,
    """
    CREATE INDEX ix_upload_links_device_id ON upload_links (device_id)
    """,
    """
    CREATE INDEX ix_upload_links_ledger_id ON upload_links (ledger_id)
    """,
    """
    CREATE UNIQUE INDEX ix_upload_links_public_id ON upload_links (public_id)
    """,
    """
    CREATE UNIQUE INDEX ix_upload_links_token_hash ON upload_links (token_hash)
    """,
    """
    CREATE TABLE pairing_codes (
        id SERIAL NOT NULL,
        code_hash VARCHAR(64) NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        account_id INTEGER,
        device_name_hint VARCHAR(120),
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        used_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(ledger_id) REFERENCES ledgers (ledger_id),
        FOREIGN KEY(account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_pairing_codes_account_id ON pairing_codes (account_id)
    """,
    """
    CREATE UNIQUE INDEX ix_pairing_codes_code_hash ON pairing_codes (code_hash)
    """,
    """
    CREATE INDEX ix_pairing_codes_expires_at ON pairing_codes (expires_at)
    """,
    """
    CREATE INDEX ix_pairing_codes_ledger_id ON pairing_codes (ledger_id)
    """,
)
