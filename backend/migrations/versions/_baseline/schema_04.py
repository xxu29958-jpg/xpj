"""Frozen PostgreSQL DDL for the 20260524_0001 historical baseline."""

from __future__ import annotations

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE recurring_items (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        merchant_key VARCHAR(255) NOT NULL,
        merchant_name VARCHAR(255) NOT NULL,
        frequency VARCHAR(32) NOT NULL,
        baseline_amount_cents INTEGER NOT NULL,
        last_amount_cents INTEGER NOT NULL,
        occurrence_count INTEGER NOT NULL,
        last_seen_at TIMESTAMP WITH TIME ZONE,
        next_expected_date DATE,
        status VARCHAR(32) NOT NULL,
        confidence VARCHAR(32),
        source VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        paused_at TIMESTAMP WITH TIME ZONE,
        archived_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_recurring_items_frequency_valid CHECK (frequency IN ('monthly')),
        CONSTRAINT ck_recurring_items_status_valid CHECK (status IN ('active', 'paused', 'archived')),
        CONSTRAINT uq_recurring_items_tenant_merchant_frequency UNIQUE (tenant_id, merchant_key, frequency),
        CONSTRAINT fk_recurring_items_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_recurring_items_frequency ON recurring_items (frequency)
    """,
    """
    CREATE INDEX ix_recurring_items_last_seen_at ON recurring_items (last_seen_at)
    """,
    """
    CREATE INDEX ix_recurring_items_merchant_key ON recurring_items (merchant_key)
    """,
    """
    CREATE INDEX ix_recurring_items_next_expected_date ON recurring_items (next_expected_date)
    """,
    """
    CREATE UNIQUE INDEX ix_recurring_items_public_id ON recurring_items (public_id)
    """,
    """
    CREATE INDEX ix_recurring_items_status ON recurring_items (status)
    """,
    """
    CREATE INDEX ix_recurring_items_tenant_id ON recurring_items (tenant_id)
    """,
    """
    CREATE INDEX ix_recurring_items_tenant_merchant ON recurring_items (tenant_id, merchant_key)
    """,
    """
    CREATE INDEX ix_recurring_items_tenant_status_next ON recurring_items (tenant_id, status, next_expected_date)
    """,
    """
    CREATE TABLE upload_link_daily_usage (
        id SERIAL NOT NULL,
        upload_link_id INTEGER NOT NULL,
        ymd VARCHAR(10) NOT NULL,
        bytes_total INTEGER NOT NULL,
        request_count INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_upload_link_daily_usage_link_ymd UNIQUE (upload_link_id, ymd),
        FOREIGN KEY(upload_link_id) REFERENCES upload_links (id)
    )
    """,
    """
    CREATE INDEX ix_upload_link_daily_usage_upload_link_id ON upload_link_daily_usage (upload_link_id)
    """,
    """
    CREATE INDEX ix_upload_link_daily_usage_ymd ON upload_link_daily_usage (ymd)
    """,
    """
    CREATE TABLE upload_link_remote_attempts (
        id SERIAL NOT NULL,
        upload_link_id INTEGER NOT NULL,
        remote_key VARCHAR(120) NOT NULL,
        last_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_upload_link_remote_attempts_link_key UNIQUE (upload_link_id, remote_key),
        FOREIGN KEY(upload_link_id) REFERENCES upload_links (id)
    )
    """,
    """
    CREATE INDEX ix_upload_link_remote_attempts_remote_key ON upload_link_remote_attempts (remote_key)
    """,
    """
    CREATE INDEX ix_upload_link_remote_attempts_upload_link_id ON upload_link_remote_attempts (upload_link_id)
    """,
    """
    CREATE TABLE bill_split_invitations (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        sender_account_id INTEGER NOT NULL,
        sender_ledger_id VARCHAR(64) NOT NULL,
        sender_member_id INTEGER NOT NULL,
        sender_expense_id INTEGER NOT NULL,
        sender_display_name VARCHAR(255) NOT NULL,
        receiver_account_id INTEGER NOT NULL,
        receiver_display_name_snapshot VARCHAR(255),
        receiver_ledger_id VARCHAR(64),
        receiver_member_id INTEGER,
        amount_cents INTEGER NOT NULL,
        home_currency_code VARCHAR(3) NOT NULL,
        original_currency_code VARCHAR(3) NOT NULL,
        original_amount_minor INTEGER,
        exchange_rate_to_cny NUMERIC(18, 8),
        exchange_rate_date TIMESTAMP WITH TIME ZONE,
        exchange_rate_source VARCHAR(32),
        merchant_snapshot VARCHAR(255),
        category_suggestion VARCHAR(64),
        expense_time_snapshot TIMESTAMP WITH TIME ZONE,
        status VARCHAR(32) DEFAULT 'invited' NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        received_expense_id INTEGER,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        accepted_at TIMESTAMP WITH TIME ZONE,
        rejected_at TIMESTAMP WITH TIME ZONE,
        cancelled_at TIMESTAMP WITH TIME ZONE,
        expired_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_bill_split_invitations_status_valid CHECK (status IN ('invited', 'accepted', 'rejected', 'cancelled', 'expired')),
        CONSTRAINT ck_bill_split_invitations_amount_positive CHECK (amount_cents > 0),
        CONSTRAINT fk_bill_split_invitations_sender_member_tenant FOREIGN KEY(sender_member_id, sender_ledger_id) REFERENCES ledger_members (id, ledger_id),
        CONSTRAINT fk_bill_split_invitations_sender_expense_tenant FOREIGN KEY(sender_expense_id, sender_ledger_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT fk_bill_split_invitations_receiver_member_tenant FOREIGN KEY(receiver_member_id, receiver_ledger_id) REFERENCES ledger_members (id, ledger_id),
        CONSTRAINT fk_bill_split_invitations_received_expense_tenant FOREIGN KEY(received_expense_id, receiver_ledger_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT uq_bill_split_received_expense_id UNIQUE (received_expense_id),
        FOREIGN KEY(sender_account_id) REFERENCES accounts (id),
        FOREIGN KEY(sender_ledger_id) REFERENCES ledgers (ledger_id),
        FOREIGN KEY(receiver_account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_bill_split_invitations_expires_at_status ON bill_split_invitations (expires_at, status)
    """,
    """
    CREATE UNIQUE INDEX ix_bill_split_invitations_public_id ON bill_split_invitations (public_id)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_receiver_account_id ON bill_split_invitations (receiver_account_id)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_receiver_status_created ON bill_split_invitations (receiver_account_id, status, created_at)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_sender_account_id ON bill_split_invitations (sender_account_id)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_sender_expense_id ON bill_split_invitations (sender_expense_id)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_sender_ledger_id ON bill_split_invitations (sender_ledger_id)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_sender_status_created ON bill_split_invitations (sender_account_id, sender_ledger_id, status, created_at)
    """,
    """
    CREATE INDEX ix_bill_split_invitations_status ON bill_split_invitations (status)
    """,
    """
    CREATE TABLE budget_categories (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        month VARCHAR(7) NOT NULL,
        category VARCHAR(64) NOT NULL,
        amount_cents INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_budget_categories_amount_non_negative CHECK (amount_cents >= 0),
        CONSTRAINT ck_budget_categories_month_format CHECK (length(month) = 7),
        CONSTRAINT uq_budget_categories_tenant_month_category UNIQUE (tenant_id, month, category),
        CONSTRAINT fk_budget_categories_budget_month FOREIGN KEY(tenant_id, month) REFERENCES budgets (tenant_id, month)
    )
    """,
    """
    CREATE INDEX ix_budget_categories_category ON budget_categories (category)
    """,
    """
    CREATE INDEX ix_budget_categories_month ON budget_categories (month)
    """,
    """
    CREATE UNIQUE INDEX ix_budget_categories_public_id ON budget_categories (public_id)
    """,
    """
    CREATE INDEX ix_budget_categories_tenant_category ON budget_categories (tenant_id, category)
    """,
    """
    CREATE INDEX ix_budget_categories_tenant_id ON budget_categories (tenant_id)
    """,
    """
    CREATE INDEX ix_budget_categories_tenant_month ON budget_categories (tenant_id, month)
    """,
    """
    CREATE TABLE expense_tags (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        expense_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_expense_tags_expense_tenant FOREIGN KEY(expense_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT fk_expense_tags_tag_tenant FOREIGN KEY(tag_id, tenant_id) REFERENCES tags (id, tenant_id),
        CONSTRAINT uq_expense_tags_tenant_expense_tag UNIQUE (tenant_id, expense_id, tag_id),
        FOREIGN KEY(expense_id) REFERENCES expenses (id),
        FOREIGN KEY(tag_id) REFERENCES tags (id)
    )
    """,
    """
    CREATE INDEX ix_expense_tags_expense_id ON expense_tags (expense_id)
    """,
    """
    CREATE INDEX ix_expense_tags_tag_id ON expense_tags (tag_id)
    """,
    """
    CREATE INDEX ix_expense_tags_tenant_expense ON expense_tags (tenant_id, expense_id)
    """,
    """
    CREATE INDEX ix_expense_tags_tenant_id ON expense_tags (tenant_id)
    """,
    """
    CREATE INDEX ix_expense_tags_tenant_tag ON expense_tags (tenant_id, tag_id)
    """,
    """
    CREATE TABLE duplicate_ignores (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        expense_id INTEGER NOT NULL,
        duplicate_of_id INTEGER NOT NULL,
        kind VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_duplicate_ignores_expense_tenant FOREIGN KEY(expense_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT fk_duplicate_ignores_duplicate_tenant FOREIGN KEY(duplicate_of_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT uq_duplicate_ignore_tenant_pair_kind UNIQUE (tenant_id, expense_id, duplicate_of_id, kind)
    )
    """,
    """
    CREATE INDEX ix_duplicate_ignores_duplicate_of_id ON duplicate_ignores (duplicate_of_id)
    """,
    """
    CREATE INDEX ix_duplicate_ignores_expense_id ON duplicate_ignores (expense_id)
    """,
    """
    CREATE INDEX ix_duplicate_ignores_kind ON duplicate_ignores (kind)
    """,
    """
    CREATE INDEX ix_duplicate_ignores_tenant_id ON duplicate_ignores (tenant_id)
    """,
    """
    CREATE INDEX ix_duplicate_ignores_tenant_pair_kind ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)
    """,
    """
    CREATE TABLE rule_application_changes (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        batch_id INTEGER NOT NULL,
        expense_id INTEGER NOT NULL,
        rule_id INTEGER,
        matched_keyword VARCHAR(255),
        before_category VARCHAR(64) NOT NULL,
        after_category VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        rolled_back_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT fk_rule_application_changes_batch_tenant FOREIGN KEY(batch_id, tenant_id) REFERENCES rule_application_batches (id, tenant_id),
        CONSTRAINT fk_rule_application_changes_expense_tenant FOREIGN KEY(expense_id, tenant_id) REFERENCES expenses (id, tenant_id),
        FOREIGN KEY(batch_id) REFERENCES rule_application_batches (id),
        FOREIGN KEY(expense_id) REFERENCES expenses (id)
    )
    """,
    """
    CREATE INDEX ix_rule_application_changes_batch_id ON rule_application_changes (batch_id)
    """,
    """
    CREATE INDEX ix_rule_application_changes_expense_id ON rule_application_changes (expense_id)
    """,
    """
    CREATE UNIQUE INDEX ix_rule_application_changes_public_id ON rule_application_changes (public_id)
    """,
    """
    CREATE INDEX ix_rule_application_changes_rule_id ON rule_application_changes (rule_id)
    """,
    """
    CREATE INDEX ix_rule_application_changes_status ON rule_application_changes (status)
    """,
    """
    CREATE INDEX ix_rule_application_changes_tenant_batch ON rule_application_changes (tenant_id, batch_id)
    """,
    """
    CREATE INDEX ix_rule_application_changes_tenant_expense ON rule_application_changes (tenant_id, expense_id)
    """,
    """
    CREATE INDEX ix_rule_application_changes_tenant_id ON rule_application_changes (tenant_id)
    """,
    """
    CREATE TABLE expense_items (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        expense_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        kind VARCHAR(32) DEFAULT 'product' NOT NULL,
        name VARCHAR(255) NOT NULL,
        quantity_text VARCHAR(64),
        unit_price_cents INTEGER,
        amount_cents INTEGER,
        category VARCHAR(64) NOT NULL,
        raw_text TEXT,
        confidence FLOAT,
        is_ocr_draft BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_expense_items_position_non_negative CHECK (position >= 0),
        CONSTRAINT ck_expense_items_unit_price_non_negative CHECK (unit_price_cents IS NULL OR unit_price_cents >= 0),
        CONSTRAINT ck_expense_items_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
        CONSTRAINT ck_expense_items_kind_valid CHECK (kind IN ('product', 'discount', 'tax', 'service_fee')),
        CONSTRAINT ck_expense_items_amount_by_kind CHECK ((kind = 'product' AND (amount_cents IS NULL OR amount_cents >= 0)) OR (kind = 'discount' AND (amount_cents IS NULL OR amount_cents <= 0)) OR (kind IN ('tax', 'service_fee') AND (amount_cents IS NULL OR amount_cents >= 0))),
        CONSTRAINT fk_expense_items_expense_tenant FOREIGN KEY(expense_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT uq_expense_items_tenant_expense_position UNIQUE (tenant_id, expense_id, position),
        FOREIGN KEY(expense_id) REFERENCES expenses (id)
    )
    """,
    """
    CREATE INDEX ix_expense_items_expense_id ON expense_items (expense_id)
    """,
    """
    CREATE UNIQUE INDEX ix_expense_items_public_id ON expense_items (public_id)
    """,
    """
    CREATE INDEX ix_expense_items_tenant_category ON expense_items (tenant_id, category)
    """,
    """
    CREATE INDEX ix_expense_items_tenant_expense_position ON expense_items (tenant_id, expense_id, position)
    """,
    """
    CREATE INDEX ix_expense_items_tenant_id ON expense_items (tenant_id)
    """,
    """
    CREATE INDEX ix_expense_items_tenant_public_id ON expense_items (tenant_id, public_id)
    """,
)
