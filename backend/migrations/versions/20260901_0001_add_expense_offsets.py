"""Add Expense refund, chargeback, and reversal facts.

Revision ID: 20260901_0001
Revises: 20260828_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260901_0001"
down_revision = "20260828_0001"
branch_labels = None
depends_on = None

_FACTS = "expense_offset_facts"
_REVISIONS = "expense_offset_revisions"
_CURRENCY_WRITER_FUNCTION = "ticketbox_require_currency_writer"
_CURRENCY_WRITER_TRIGGER = "trg_currency_writer_expense_offset_facts"
_CURRENCY_TRUNCATE_TRIGGER = "trg_currency_writer_expense_offset_facts_truncate"


def _set_dataset_authority_revision(
    bind: sa.Connection,
    *,
    expected_revision: str,
    target_revision: str,
) -> None:
    current = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))
    if current == target_revision:
        return
    if current != expected_revision:
        raise RuntimeError("dataset authority revision is outside this migration edge")
    updated = bind.execute(
        sa.text(
            "UPDATE dataset_authority SET schema_revision = :target_revision "
            "WHERE singleton_id = 1 AND schema_revision = :expected_revision"
        ),
        {
            "expected_revision": expected_revision,
            "target_revision": target_revision,
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority revision update lost its migration claim")


def _create_fact_table() -> None:
    op.create_table(
        _FACTS,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("original_currency_code", sa.String(length=3), nullable=False),
        sa.Column("original_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("home_currency_code", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("exchange_rate_to_cny", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("exchange_rate_date", sa.Date(), nullable=True),
        sa.Column("exchange_rate_source", sa.String(length=32), nullable=True),
        sa.Column("accounting_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("fact_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_actor_account_id", sa.Integer(), nullable=False),
        sa.Column("created_device_public_id", sa.String(length=36), nullable=True),
        sa.Column("created_device_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount_cents BETWEEN 1 AND 9000000000000",
            name="ck_expense_offset_facts_amount_cents_money_bounds",
        ),
        sa.CheckConstraint(
            "original_amount_minor BETWEEN 1 AND 9000000000000",
            name="ck_expense_offset_facts_original_amount_minor_money_bounds",
        ),
        sa.CheckConstraint(
            "kind IN ('refund', 'chargeback', 'reversal')",
            name="ck_expense_offset_facts_kind_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'voided')",
            name="ck_expense_offset_facts_status_valid",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_expense_offset_facts_reason_length",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_expense_offset_facts_row_version_positive",
        ),
        sa.CheckConstraint(
            "fact_revision >= 1",
            name="ck_expense_offset_facts_fact_revision_positive",
        ),
        sa.CheckConstraint(
            "(created_device_public_id IS NULL) = (created_device_name IS NULL)",
            name="ck_expense_offset_facts_device_snapshot_pair",
        ),
        sa.ForeignKeyConstraint(
            ["created_actor_account_id"],
            ["accounts.id"],
            name="fk_expense_offset_facts_created_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_offset_facts_expense_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_expense_offset_facts_id_tenant"),
    )
    op.create_index(
        "ix_expense_offset_facts_tenant_expense_accounting",
        _FACTS,
        ["tenant_id", "expense_id", "accounting_date", "id"],
        unique=False,
    )
    op.create_index(
        "uq_expense_offset_facts_active_reversal",
        _FACTS,
        ["tenant_id", "expense_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'reversal' AND status = 'active'"),
    )


def _ensure_currency_writer_triggers(bind: sa.Connection) -> None:
    existing = set(
        bind.scalars(
            sa.text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'expense_offset_facts'::regclass AND NOT tgisinternal"
            )
        )
    )
    if _CURRENCY_WRITER_TRIGGER not in existing:
        op.execute(
            f"CREATE TRIGGER {_CURRENCY_WRITER_TRIGGER} "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {_FACTS} FOR EACH ROW "
            f"EXECUTE FUNCTION {_CURRENCY_WRITER_FUNCTION}()"
        )
    if _CURRENCY_TRUNCATE_TRIGGER not in existing:
        op.execute(
            f"CREATE TRIGGER {_CURRENCY_TRUNCATE_TRIGGER} "
            f"BEFORE TRUNCATE ON {_FACTS} FOR EACH STATEMENT "
            f"EXECUTE FUNCTION {_CURRENCY_WRITER_FUNCTION}()"
        )


def _create_revision_table() -> None:
    op.create_table(
        _REVISIONS,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("offset_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("change_kind", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("actor_device_public_id", sa.String(length=36), nullable=True),
        sa.Column("actor_device_name", sa.String(length=120), nullable=True),
        sa.Column("before_snapshot", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("previous_row_version", sa.Integer(), nullable=True),
        sa.Column("resulting_row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_expense_offset_revisions_number_positive",
        ),
        sa.CheckConstraint(
            "change_kind IN ('created', 'correction', 'void')",
            name="ck_expense_offset_revisions_kind_valid",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_expense_offset_revisions_reason_length",
        ),
        sa.CheckConstraint(
            "(change_kind = 'created' AND before_snapshot IS NULL) OR "
            "(change_kind IN ('correction', 'void') AND before_snapshot IS NOT NULL)",
            name="ck_expense_offset_revisions_before_shape",
        ),
        sa.CheckConstraint(
            "resulting_row_version >= 1",
            name="ck_expense_offset_revisions_result_version_positive",
        ),
        sa.CheckConstraint(
            "(actor_device_public_id IS NULL) = (actor_device_name IS NULL)",
            name="ck_expense_offset_revisions_device_snapshot_pair",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["accounts.id"],
            name="fk_expense_offset_revisions_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_offset_revisions_expense_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["offset_id", "tenant_id"],
            ["expense_offset_facts.id", "expense_offset_facts.tenant_id"],
            name="fk_expense_offset_revisions_offset_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "offset_id",
            "revision_number",
            name="uq_expense_offset_revisions_offset_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_expense_offset_revisions_idempotency_key",
        ),
    )
    op.create_index(
        "ix_expense_offset_revisions_tenant_expense_created",
        _REVISIONS,
        ["tenant_id", "expense_id", "created_at"],
        unique=False,
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION ticketbox_reject_expense_offset_revision_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'expense_offset_revisions is append-only' USING ERRCODE = '55000'; "
        "END $$"
    )
    op.execute(
        "CREATE TRIGGER trg_expense_offset_revisions_append_only "
        "BEFORE UPDATE OR DELETE ON expense_offset_revisions FOR EACH ROW "
        "EXECUTE FUNCTION ticketbox_reject_expense_offset_revision_mutation()"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_FACTS):
        _create_fact_table()
    _ensure_currency_writer_triggers(bind)
    if not sa.inspect(bind).has_table(_REVISIONS):
        _create_revision_table()
    _set_dataset_authority_revision(
        bind,
        expected_revision=down_revision,
        target_revision=revision,
    )
    assert_postcondition(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (_REVISIONS, _FACTS):
        if sa.inspect(bind).has_table(table):
            has_rows = bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)"))
            if has_rows:
                raise RuntimeError("cannot downgrade while Expense offset facts exist")
    if sa.inspect(bind).has_table(_REVISIONS):
        op.drop_table(_REVISIONS)
    op.execute("DROP FUNCTION IF EXISTS ticketbox_reject_expense_offset_revision_mutation()")
    if sa.inspect(bind).has_table(_FACTS):
        op.drop_table(_FACTS)
    _set_dataset_authority_revision(
        bind,
        expected_revision=revision,
        target_revision=down_revision,
    )


def assert_postcondition(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_FACTS) or not inspector.has_table(_REVISIONS):
        raise RuntimeError("Expense offset fact tables are missing")
    trigger_exists = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_trigger "
            "WHERE tgname = 'trg_expense_offset_revisions_append_only' "
            "AND tgrelid = 'expense_offset_revisions'::regclass AND NOT tgisinternal)"
        )
    )
    if not trigger_exists:
        raise RuntimeError("Expense offset revision append-only trigger is missing")
    writer_triggers = set(
        bind.scalars(
            sa.text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'expense_offset_facts'::regclass AND NOT tgisinternal"
            )
        )
    )
    if {
        _CURRENCY_WRITER_TRIGGER,
        _CURRENCY_TRUNCATE_TRIGGER,
    } - writer_triggers:
        raise RuntimeError("Expense offset currency writer fence is missing")
    authority_revision = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))
    if authority_revision != revision:
        raise RuntimeError("dataset authority revision is not aligned with Alembic head")
