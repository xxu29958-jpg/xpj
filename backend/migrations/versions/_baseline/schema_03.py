"""Frozen PostgreSQL DDL for the 20260524_0001 historical baseline."""

from __future__ import annotations

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE expenses (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        amount_cents INTEGER,
        home_currency_code VARCHAR(3) DEFAULT 'CNY' NOT NULL,
        original_currency_code VARCHAR(3) DEFAULT 'CNY' NOT NULL,
        original_amount_minor INTEGER,
        exchange_rate_to_cny NUMERIC(18, 8),
        exchange_rate_date DATE,
        exchange_rate_source VARCHAR(32) DEFAULT 'base',
        fx_status VARCHAR(32) DEFAULT 'ready' NOT NULL,
        merchant VARCHAR(255),
        category VARCHAR(64) NOT NULL,
        note TEXT,
        source VARCHAR(64) NOT NULL,
        image_path VARCHAR(500),
        thumbnail_path VARCHAR(500),
        image_hash VARCHAR(128),
        raw_text TEXT,
        confidence FLOAT,
        ocr_draft_fields TEXT,
        draft_idempotency_key VARCHAR(128),
        duplicate_status VARCHAR(32) NOT NULL,
        duplicate_of_id INTEGER,
        duplicate_reason VARCHAR(500),
        tags TEXT,
        value_score INTEGER,
        regret_score INTEGER,
        status VARCHAR(32) NOT NULL,
        expense_time TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        confirmed_at TIMESTAMP WITH TIME ZONE,
        rejected_at TIMESTAMP WITH TIME ZONE,
        image_deleted_at TIMESTAMP WITH TIME ZONE,
        thumbnail_deleted_at TIMESTAMP WITH TIME ZONE,
        items_sum_status VARCHAR(32) DEFAULT 'no_items' NOT NULL,
        split_origin_invitation_id VARCHAR(36),
        PRIMARY KEY (id),
        CONSTRAINT uq_expenses_id_tenant_id UNIQUE (id, tenant_id),
        CONSTRAINT fk_expenses_duplicate_of_tenant FOREIGN KEY(duplicate_of_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT ck_expenses_amount_non_negative CHECK (amount_cents IS NULL OR amount_cents >= 0),
        CONSTRAINT ck_expenses_original_amount_non_negative CHECK (original_amount_minor IS NULL OR original_amount_minor >= 0),
        CONSTRAINT ck_expenses_exchange_rate_positive CHECK (exchange_rate_to_cny IS NULL OR exchange_rate_to_cny > 0),
        CONSTRAINT ck_expenses_fx_status_valid CHECK (fx_status IN ('ready', 'pending')),
        CONSTRAINT ck_expenses_status_valid CHECK (status IN ('pending', 'confirmed', 'rejected')),
        CONSTRAINT ck_expenses_duplicate_status_valid CHECK (duplicate_status IN ('none', 'suspected')),
        CONSTRAINT ck_expenses_items_sum_status_valid CHECK (items_sum_status IN ('matched', 'mismatch_known', 'mismatch_acknowledged', 'no_items')),
        CONSTRAINT fk_expenses_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_expenses_category_status ON expenses (category, status)
    """,
    """
    CREATE INDEX ix_expenses_confirmed_at ON expenses (confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_duplicate_of_id ON expenses (duplicate_of_id)
    """,
    """
    CREATE INDEX ix_expenses_duplicate_status ON expenses (duplicate_status)
    """,
    """
    CREATE INDEX ix_expenses_exchange_rate_date ON expenses (exchange_rate_date)
    """,
    """
    CREATE INDEX ix_expenses_expense_time ON expenses (expense_time)
    """,
    """
    CREATE INDEX ix_expenses_fx_status ON expenses (fx_status)
    """,
    """
    CREATE INDEX ix_expenses_home_currency_code ON expenses (home_currency_code)
    """,
    """
    CREATE INDEX ix_expenses_image_hash ON expenses (image_hash)
    """,
    """
    CREATE INDEX ix_expenses_original_currency_code ON expenses (original_currency_code)
    """,
    """
    CREATE UNIQUE INDEX ix_expenses_public_id ON expenses (public_id)
    """,
    """
    CREATE INDEX ix_expenses_split_origin_invitation_id ON expenses (split_origin_invitation_id)
    """,
    """
    CREATE INDEX ix_expenses_status ON expenses (status)
    """,
    """
    CREATE INDEX ix_expenses_status_amount_merchant ON expenses (status, amount_cents, merchant)
    """,
    """
    CREATE INDEX ix_expenses_status_category_confirmed_at ON expenses (status, category, confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_status_category_expense_time ON expenses (status, category, expense_time)
    """,
    """
    CREATE INDEX ix_expenses_status_confirmed_at ON expenses (status, confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_status_created_at ON expenses (status, created_at)
    """,
    """
    CREATE INDEX ix_expenses_status_expense_time ON expenses (status, expense_time)
    """,
    """
    CREATE INDEX ix_expenses_status_merchant_confirmed_at ON expenses (status, merchant, confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_status_merchant_expense_time ON expenses (status, merchant, expense_time)
    """,
    """
    CREATE INDEX ix_expenses_tenant_category_status ON expenses (tenant_id, category, status)
    """,
    """
    CREATE UNIQUE INDEX ix_expenses_tenant_draft_idempotency_key ON expenses (tenant_id, draft_idempotency_key)
    """,
    """
    CREATE INDEX ix_expenses_tenant_duplicate_status ON expenses (tenant_id, duplicate_status)
    """,
    """
    CREATE INDEX ix_expenses_tenant_id ON expenses (tenant_id)
    """,
    """
    CREATE INDEX ix_expenses_tenant_image_hash ON expenses (tenant_id, image_hash)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_amount_merchant ON expenses (tenant_id, status, amount_cents, merchant)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_category_confirmed_at ON expenses (tenant_id, status, category, confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_category_expense_time ON expenses (tenant_id, status, category, expense_time)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_confirmed_at ON expenses (tenant_id, status, confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_created_at ON expenses (tenant_id, status, created_at)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_expense_time ON expenses (tenant_id, status, expense_time)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_merchant_confirmed_at ON expenses (tenant_id, status, merchant, confirmed_at)
    """,
    """
    CREATE INDEX ix_expenses_tenant_status_merchant_expense_time ON expenses (tenant_id, status, merchant, expense_time)
    """,
    """
    CREATE TABLE monthly_income_plans (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        label VARCHAR(64) NOT NULL,
        source_type VARCHAR(32) NOT NULL,
        amount_cents INTEGER NOT NULL,
        pay_day INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        archived_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_monthly_income_plans_status_valid CHECK (status IN ('active', 'archived')),
        CONSTRAINT ck_monthly_income_plans_pay_day_range CHECK (pay_day >= 1 AND pay_day <= 31),
        CONSTRAINT ck_monthly_income_plans_amount_non_negative CHECK (amount_cents >= 0),
        CONSTRAINT fk_monthly_income_plans_tenant FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE UNIQUE INDEX ix_monthly_income_plans_public_id ON monthly_income_plans (public_id)
    """,
    """
    CREATE INDEX ix_monthly_income_plans_status ON monthly_income_plans (status)
    """,
    """
    CREATE INDEX ix_monthly_income_plans_tenant_id ON monthly_income_plans (tenant_id)
    """,
    """
    CREATE INDEX ix_monthly_income_plans_tenant_status ON monthly_income_plans (tenant_id, status)
    """,
    """
    CREATE TABLE ledger_members (
        id SERIAL NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        account_id INTEGER NOT NULL,
        role VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        disabled_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_ledger_members_role_valid CHECK (role IN ('owner', 'member', 'viewer')),
        CONSTRAINT uq_ledger_members_id_ledger_id UNIQUE (id, ledger_id),
        CONSTRAINT uq_ledger_member_ledger_account UNIQUE (ledger_id, account_id),
        FOREIGN KEY(ledger_id) REFERENCES ledgers (ledger_id),
        FOREIGN KEY(account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_ledger_members_account_id ON ledger_members (account_id)
    """,
    """
    CREATE INDEX ix_ledger_members_ledger_id ON ledger_members (ledger_id)
    """,
    """
    CREATE TABLE auth_tokens (
        id SERIAL NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        account_id INTEGER NOT NULL,
        device_id INTEGER NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        scope VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE,
        last_used_at TIMESTAMP WITH TIME ZONE,
        revoked_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_auth_tokens_scope_valid CHECK (scope IN ('app', 'admin')),
        FOREIGN KEY(account_id) REFERENCES accounts (id),
        FOREIGN KEY(device_id) REFERENCES devices (id),
        FOREIGN KEY(ledger_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_auth_tokens_account_id ON auth_tokens (account_id)
    """,
    """
    CREATE INDEX ix_auth_tokens_device_id ON auth_tokens (device_id)
    """,
    """
    CREATE INDEX ix_auth_tokens_expires_at ON auth_tokens (expires_at)
    """,
    """
    CREATE INDEX ix_auth_tokens_ledger_id ON auth_tokens (ledger_id)
    """,
    """
    CREATE INDEX ix_auth_tokens_scope ON auth_tokens (scope)
    """,
    """
    CREATE UNIQUE INDEX ix_auth_tokens_token_hash ON auth_tokens (token_hash)
    """,
    """
    CREATE TABLE ledger_audit_logs (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        action VARCHAR(64) NOT NULL,
        actor_account_id INTEGER,
        target_account_id INTEGER,
        target_member_id INTEGER,
        invitation_public_id VARCHAR(36),
        previous_role VARCHAR(32),
        new_role VARCHAR(32),
        result VARCHAR(32) NOT NULL,
        detail TEXT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(ledger_id) REFERENCES ledgers (ledger_id),
        FOREIGN KEY(actor_account_id) REFERENCES accounts (id),
        FOREIGN KEY(target_account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_action ON ledger_audit_logs (action)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_actor_account_id ON ledger_audit_logs (actor_account_id)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_invitation_public_id ON ledger_audit_logs (invitation_public_id)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_ledger_action ON ledger_audit_logs (ledger_id, action)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_ledger_created_at ON ledger_audit_logs (ledger_id, created_at)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_ledger_id ON ledger_audit_logs (ledger_id)
    """,
    """
    CREATE UNIQUE INDEX ix_ledger_audit_logs_public_id ON ledger_audit_logs (public_id)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_result ON ledger_audit_logs (result)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_target_account_id ON ledger_audit_logs (target_account_id)
    """,
    """
    CREATE INDEX ix_ledger_audit_logs_target_member_id ON ledger_audit_logs (target_member_id)
    """,
    """
    CREATE TABLE csv_import_batches (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        file_name VARCHAR(255) NOT NULL,
        status VARCHAR(32) NOT NULL,
        total_rows INTEGER NOT NULL,
        valid_rows INTEGER NOT NULL,
        error_rows INTEGER NOT NULL,
        applied_rows INTEGER NOT NULL,
        inserted_count INTEGER NOT NULL,
        locked_until TIMESTAMP WITH TIME ZONE,
        apply_token VARCHAR(36),
        last_error TEXT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        applied_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_csv_import_batches_status_valid CHECK (status IN ('parsed', 'parsed_with_errors', 'applying', 'applied', 'applied_with_errors')),
        CONSTRAINT ck_csv_import_batches_total_rows_non_negative CHECK (total_rows >= 0),
        CONSTRAINT ck_csv_import_batches_valid_rows_non_negative CHECK (valid_rows >= 0),
        CONSTRAINT ck_csv_import_batches_error_rows_non_negative CHECK (error_rows >= 0),
        CONSTRAINT ck_csv_import_batches_applied_rows_non_negative CHECK (applied_rows >= 0),
        CONSTRAINT ck_csv_import_batches_inserted_count_non_negative CHECK (inserted_count >= 0),
        CONSTRAINT uq_csv_import_batches_id_tenant_id UNIQUE (id, tenant_id),
        CONSTRAINT fk_csv_import_batches_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_csv_import_batches_locked_until ON csv_import_batches (locked_until)
    """,
    """
    CREATE UNIQUE INDEX ix_csv_import_batches_public_id ON csv_import_batches (public_id)
    """,
    """
    CREATE INDEX ix_csv_import_batches_status ON csv_import_batches (status)
    """,
    """
    CREATE INDEX ix_csv_import_batches_tenant_id ON csv_import_batches (tenant_id)
    """,
    """
    CREATE INDEX ix_csv_import_batches_tenant_public_id ON csv_import_batches (tenant_id, public_id)
    """,
    """
    CREATE INDEX ix_csv_import_batches_tenant_status_created_at ON csv_import_batches (tenant_id, status, created_at)
    """,
)
