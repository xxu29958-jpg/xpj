"""Frozen PostgreSQL DDL for the 20260524_0001 historical baseline."""

from __future__ import annotations

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE invitations (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        ledger_id VARCHAR(64) NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        role VARCHAR(32) NOT NULL,
        created_by_account_id INTEGER NOT NULL,
        note VARCHAR(80),
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        used_at TIMESTAMP WITH TIME ZONE,
        used_by_account_id INTEGER,
        revoked_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_invitations_role_invitable CHECK (role IN ('member', 'viewer')),
        FOREIGN KEY(ledger_id) REFERENCES ledgers (ledger_id),
        FOREIGN KEY(created_by_account_id) REFERENCES accounts (id),
        FOREIGN KEY(used_by_account_id) REFERENCES accounts (id)
    )
    """,
    """
    CREATE INDEX ix_invitations_created_by_account_id ON invitations (created_by_account_id)
    """,
    """
    CREATE INDEX ix_invitations_expires_at ON invitations (expires_at)
    """,
    """
    CREATE INDEX ix_invitations_ledger_id ON invitations (ledger_id)
    """,
    """
    CREATE UNIQUE INDEX ix_invitations_public_id ON invitations (public_id)
    """,
    """
    CREATE UNIQUE INDEX ix_invitations_token_hash ON invitations (token_hash)
    """,
    """
    CREATE INDEX ix_invitations_used_by_account_id ON invitations (used_by_account_id)
    """,
    """
    CREATE TABLE budgets (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        month VARCHAR(7) NOT NULL,
        total_amount_cents INTEGER NOT NULL,
        non_monthly_amount_cents INTEGER NOT NULL,
        rollover_amount_cents INTEGER NOT NULL,
        excluded_categories TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_budgets_total_non_negative CHECK (total_amount_cents >= 0),
        CONSTRAINT ck_budgets_non_monthly_non_negative CHECK (non_monthly_amount_cents >= 0),
        CONSTRAINT ck_budgets_month_format CHECK (length(month) = 7),
        CONSTRAINT uq_budgets_tenant_month UNIQUE (tenant_id, month),
        CONSTRAINT fk_budgets_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_budgets_month ON budgets (month)
    """,
    """
    CREATE UNIQUE INDEX ix_budgets_public_id ON budgets (public_id)
    """,
    """
    CREATE INDEX ix_budgets_tenant_id ON budgets (tenant_id)
    """,
    """
    CREATE INDEX ix_budgets_tenant_month ON budgets (tenant_id, month)
    """,
    """
    CREATE TABLE goals (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        name VARCHAR(80) NOT NULL,
        goal_type VARCHAR(32) NOT NULL,
        period VARCHAR(32) NOT NULL,
        month VARCHAR(7) NOT NULL,
        category VARCHAR(64),
        target_amount_cents INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        archived_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT ck_goals_type_valid CHECK (goal_type IN ('spending_limit')),
        CONSTRAINT ck_goals_period_valid CHECK (period IN ('monthly')),
        CONSTRAINT ck_goals_status_valid CHECK (status IN ('active', 'archived')),
        CONSTRAINT ck_goals_month_format CHECK (length(month) = 7),
        CONSTRAINT ck_goals_target_positive CHECK (target_amount_cents > 0),
        CONSTRAINT fk_goals_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_goals_category ON goals (category)
    """,
    """
    CREATE INDEX ix_goals_goal_type ON goals (goal_type)
    """,
    """
    CREATE INDEX ix_goals_month ON goals (month)
    """,
    """
    CREATE INDEX ix_goals_period ON goals (period)
    """,
    """
    CREATE UNIQUE INDEX ix_goals_public_id ON goals (public_id)
    """,
    """
    CREATE INDEX ix_goals_status ON goals (status)
    """,
    """
    CREATE INDEX ix_goals_tenant_category_month ON goals (tenant_id, category, month)
    """,
    """
    CREATE INDEX ix_goals_tenant_id ON goals (tenant_id)
    """,
    """
    CREATE INDEX ix_goals_tenant_month_status ON goals (tenant_id, month, status)
    """,
    """
    CREATE INDEX ix_goals_tenant_public_id ON goals (tenant_id, public_id)
    """,
    """
    CREATE UNIQUE INDEX uq_goals_active_category_scope ON goals (tenant_id, month, goal_type, period, category)
    """,
    """
    CREATE UNIQUE INDEX uq_goals_active_total_scope ON goals (tenant_id, month, goal_type, period)
    """,
    """
    CREATE TABLE dashboard_card_preferences (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        surface VARCHAR(32) NOT NULL,
        card_key VARCHAR(64) NOT NULL,
        position INTEGER NOT NULL,
        visible BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_dashboard_cards_surface_valid CHECK (surface IN ('android', 'web')),
        CONSTRAINT ck_dashboard_cards_position_non_negative CHECK (position >= 0),
        CONSTRAINT uq_dashboard_cards_tenant_surface_key UNIQUE (tenant_id, surface, card_key),
        CONSTRAINT uq_dashboard_cards_tenant_surface_position UNIQUE (tenant_id, surface, position),
        CONSTRAINT fk_dashboard_cards_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_dashboard_card_preferences_card_key ON dashboard_card_preferences (card_key)
    """,
    """
    CREATE UNIQUE INDEX ix_dashboard_card_preferences_public_id ON dashboard_card_preferences (public_id)
    """,
    """
    CREATE INDEX ix_dashboard_card_preferences_surface ON dashboard_card_preferences (surface)
    """,
    """
    CREATE INDEX ix_dashboard_card_preferences_tenant_id ON dashboard_card_preferences (tenant_id)
    """,
    """
    CREATE INDEX ix_dashboard_cards_tenant_surface_key ON dashboard_card_preferences (tenant_id, surface, card_key)
    """,
    """
    CREATE INDEX ix_dashboard_cards_tenant_surface_position ON dashboard_card_preferences (tenant_id, surface, position)
    """,
    """
    CREATE TABLE merchant_aliases (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        canonical_merchant VARCHAR(255) NOT NULL,
        canonical_key VARCHAR(255) NOT NULL,
        alias VARCHAR(255) NOT NULL,
        alias_key VARCHAR(255) NOT NULL,
        enabled BOOLEAN NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_merchant_aliases_tenant_alias_key UNIQUE (tenant_id, alias_key),
        CONSTRAINT fk_merchant_aliases_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_merchant_aliases_alias_key ON merchant_aliases (alias_key)
    """,
    """
    CREATE INDEX ix_merchant_aliases_canonical_key ON merchant_aliases (canonical_key)
    """,
    """
    CREATE UNIQUE INDEX ix_merchant_aliases_public_id ON merchant_aliases (public_id)
    """,
    """
    CREATE INDEX ix_merchant_aliases_tenant_alias_key ON merchant_aliases (tenant_id, alias_key)
    """,
    """
    CREATE INDEX ix_merchant_aliases_tenant_canonical ON merchant_aliases (tenant_id, canonical_key)
    """,
    """
    CREATE INDEX ix_merchant_aliases_tenant_id ON merchant_aliases (tenant_id)
    """,
    """
    CREATE TABLE tags (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        name VARCHAR(64) NOT NULL,
        key VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_tags_id_tenant_id UNIQUE (id, tenant_id),
        CONSTRAINT uq_tags_tenant_key UNIQUE (tenant_id, key),
        CONSTRAINT fk_tags_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_tags_key ON tags (key)
    """,
    """
    CREATE INDEX ix_tags_tenant_id ON tags (tenant_id)
    """,
    """
    CREATE INDEX ix_tags_tenant_key ON tags (tenant_id, key)
    """,
    """
    CREATE INDEX ix_tags_tenant_name ON tags (tenant_id, name)
    """,
    """
    CREATE TABLE category_rules (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        keyword VARCHAR(255) NOT NULL,
        category VARCHAR(64) NOT NULL,
        enabled BOOLEAN NOT NULL,
        priority INTEGER NOT NULL,
        amount_min_cents INTEGER,
        amount_max_cents INTEGER,
        source_contains VARCHAR(64),
        tag_contains VARCHAR(64),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT fk_category_rules_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_category_rules_category ON category_rules (category)
    """,
    """
    CREATE INDEX ix_category_rules_keyword ON category_rules (keyword)
    """,
    """
    CREATE INDEX ix_category_rules_priority ON category_rules (priority)
    """,
    """
    CREATE INDEX ix_category_rules_tenant_enabled_priority ON category_rules (tenant_id, enabled, priority, id)
    """,
    """
    CREATE INDEX ix_category_rules_tenant_id ON category_rules (tenant_id)
    """,
    """
    CREATE INDEX ix_category_rules_tenant_priority_id ON category_rules (tenant_id, priority, id)
    """,
    """
    CREATE TABLE rule_application_batches (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL,
        pending_scanned INTEGER NOT NULL,
        changed_count INTEGER NOT NULL,
        actor_account_id INTEGER,
        actor_device_id INTEGER,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        rolled_back_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (id),
        CONSTRAINT uq_rule_application_batches_id_tenant_id UNIQUE (id, tenant_id),
        CONSTRAINT fk_rule_application_batches_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id),
        FOREIGN KEY(actor_account_id) REFERENCES accounts (id),
        FOREIGN KEY(actor_device_id) REFERENCES devices (id)
    )
    """,
    """
    CREATE INDEX ix_rule_application_batches_actor_account_id ON rule_application_batches (actor_account_id)
    """,
    """
    CREATE INDEX ix_rule_application_batches_actor_device_id ON rule_application_batches (actor_device_id)
    """,
    """
    CREATE UNIQUE INDEX ix_rule_application_batches_public_id ON rule_application_batches (public_id)
    """,
    """
    CREATE INDEX ix_rule_application_batches_status ON rule_application_batches (status)
    """,
    """
    CREATE INDEX ix_rule_application_batches_tenant_created_at ON rule_application_batches (tenant_id, created_at)
    """,
    """
    CREATE INDEX ix_rule_application_batches_tenant_id ON rule_application_batches (tenant_id)
    """,
    """
    CREATE INDEX ix_rule_application_batches_tenant_status ON rule_application_batches (tenant_id, status)
    """,
    """
    CREATE TABLE exchange_rates (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        currency_code VARCHAR(3) NOT NULL,
        rate_date DATE NOT NULL,
        rate_to_cny NUMERIC(18, 8) NOT NULL,
        source VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_exchange_rates_tenant_currency_date UNIQUE (tenant_id, currency_code, rate_date),
        CONSTRAINT ck_exchange_rates_rate_positive CHECK (rate_to_cny > 0),
        CONSTRAINT fk_exchange_rates_tenant_ledger FOREIGN KEY(tenant_id) REFERENCES ledgers (ledger_id)
    )
    """,
    """
    CREATE INDEX ix_exchange_rates_currency_code ON exchange_rates (currency_code)
    """,
    """
    CREATE UNIQUE INDEX ix_exchange_rates_public_id ON exchange_rates (public_id)
    """,
    """
    CREATE INDEX ix_exchange_rates_rate_date ON exchange_rates (rate_date)
    """,
    """
    CREATE INDEX ix_exchange_rates_tenant_currency_date ON exchange_rates (tenant_id, currency_code, rate_date)
    """,
    """
    CREATE INDEX ix_exchange_rates_tenant_id ON exchange_rates (tenant_id)
    """,
)
