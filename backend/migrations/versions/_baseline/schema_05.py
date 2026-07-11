"""Frozen PostgreSQL DDL for the 20260524_0001 historical baseline."""

from __future__ import annotations

STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE expense_splits (
        id SERIAL NOT NULL,
        public_id VARCHAR(36) NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        expense_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        amount_cents INTEGER NOT NULL,
        note VARCHAR(200),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_expense_splits_position_non_negative CHECK (position >= 0),
        CONSTRAINT ck_expense_splits_amount_non_negative CHECK (amount_cents >= 0),
        CONSTRAINT fk_expense_splits_expense_tenant FOREIGN KEY(expense_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT fk_expense_splits_member_tenant FOREIGN KEY(member_id, tenant_id) REFERENCES ledger_members (id, ledger_id),
        CONSTRAINT uq_expense_splits_tenant_expense_position UNIQUE (tenant_id, expense_id, position),
        CONSTRAINT uq_expense_splits_tenant_expense_member UNIQUE (tenant_id, expense_id, member_id),
        FOREIGN KEY(expense_id) REFERENCES expenses (id),
        FOREIGN KEY(member_id) REFERENCES ledger_members (id)
    )
    """,
    """
    CREATE INDEX ix_expense_splits_expense_id ON expense_splits (expense_id)
    """,
    """
    CREATE INDEX ix_expense_splits_member_id ON expense_splits (member_id)
    """,
    """
    CREATE UNIQUE INDEX ix_expense_splits_public_id ON expense_splits (public_id)
    """,
    """
    CREATE INDEX ix_expense_splits_tenant_expense_position ON expense_splits (tenant_id, expense_id, position)
    """,
    """
    CREATE INDEX ix_expense_splits_tenant_id ON expense_splits (tenant_id)
    """,
    """
    CREATE INDEX ix_expense_splits_tenant_member ON expense_splits (tenant_id, member_id)
    """,
    """
    CREATE INDEX ix_expense_splits_tenant_public_id ON expense_splits (tenant_id, public_id)
    """,
    """
    CREATE TABLE csv_import_rows (
        id SERIAL NOT NULL,
        tenant_id VARCHAR(64) NOT NULL,
        batch_id INTEGER NOT NULL,
        line_number INTEGER NOT NULL,
        status VARCHAR(32) NOT NULL,
        apply_token VARCHAR(36),
        error_code VARCHAR(64),
        error_message VARCHAR(255),
        amount_cents INTEGER,
        original_currency_code VARCHAR(3) NOT NULL,
        original_amount_minor INTEGER,
        exchange_rate_to_cny NUMERIC(18, 8),
        exchange_rate_date DATE,
        exchange_rate_source VARCHAR(32),
        merchant VARCHAR(255),
        category VARCHAR(64) NOT NULL,
        note TEXT,
        expense_time TIMESTAMP WITH TIME ZONE,
        tags TEXT,
        source VARCHAR(64) NOT NULL,
        expense_id INTEGER,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_csv_import_rows_line_number_valid CHECK (line_number >= 2),
        CONSTRAINT ck_csv_import_rows_status_valid CHECK (status IN ('valid', 'error', 'applying', 'applied', 'insert_failed')),
        CONSTRAINT ck_csv_import_rows_amount_non_negative CHECK (amount_cents IS NULL OR amount_cents >= 0),
        CONSTRAINT fk_csv_import_rows_batch_tenant FOREIGN KEY(batch_id, tenant_id) REFERENCES csv_import_batches (id, tenant_id),
        CONSTRAINT fk_csv_import_rows_expense_tenant FOREIGN KEY(expense_id, tenant_id) REFERENCES expenses (id, tenant_id),
        CONSTRAINT uq_csv_import_rows_tenant_batch_line UNIQUE (tenant_id, batch_id, line_number),
        FOREIGN KEY(batch_id) REFERENCES csv_import_batches (id),
        FOREIGN KEY(expense_id) REFERENCES expenses (id)
    )
    """,
    """
    CREATE INDEX ix_csv_import_rows_batch_id ON csv_import_rows (batch_id)
    """,
    """
    CREATE INDEX ix_csv_import_rows_expense_id ON csv_import_rows (expense_id)
    """,
    """
    CREATE INDEX ix_csv_import_rows_status ON csv_import_rows (status)
    """,
    """
    CREATE INDEX ix_csv_import_rows_tenant_batch_line ON csv_import_rows (tenant_id, batch_id, line_number)
    """,
    """
    CREATE INDEX ix_csv_import_rows_tenant_batch_status ON csv_import_rows (tenant_id, batch_id, status)
    """,
    """
    CREATE INDEX ix_csv_import_rows_tenant_id ON csv_import_rows (tenant_id)
    """,
)
