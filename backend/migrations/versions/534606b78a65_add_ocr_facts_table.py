"""add ocr facts table.

Revision ID: 534606b78a65
Revises: 10fef44b2042
Create Date: 2026-05-25

v1.2 P0 — ``ocr_facts`` is the append-only snapshot of every successful
OCR extraction. The expense row stays the source of truth for *user-
confirmed* values; this table captures *what OCR actually saw* so
downstream learning signals (category self-learning, duplicate scoring,
budget P50/P75) can read the OCR side without coupling to the editable
ledger surface.

Autogenerate surfaced more legacy v1.0 schema drift — same situation
as 10fef44b2042. Drift fixes belong in their own revision under review;
this one is scoped to creating the new table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "534606b78a65"
down_revision: str | Sequence[str] | None = "10fef44b2042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # init_db() runs ``Base.metadata.create_all`` before
    # ``alembic upgrade head`` for the legacy-to-alembic bridge path;
    # guard create_table to keep the revision idempotent in that case.
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "ocr_facts" in table_names:
        return
    op.create_table(
        "ocr_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("ocr_provider", sa.String(length=64), nullable=False),
        sa.Column("ocr_model", sa.String(length=120), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("parsed_amount_cents", sa.Integer(), nullable=True),
        sa.Column("parsed_merchant", sa.String(length=255), nullable=True),
        sa.Column("parsed_category", sa.String(length=64), nullable=True),
        sa.Column(
            "parsed_expense_time",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("parse_confidence", sa.Float(), nullable=True),
        sa.Column(
            "extracted_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["expense_id"], ["expenses.id"], name="fk_ocr_facts_expense"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["ledgers.ledger_id"],
            name="fk_ocr_facts_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("ocr_facts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ocr_facts_expense_id"),
            ["expense_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_ocr_facts_public_id"),
            ["public_id"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_ocr_facts_tenant_id"),
            ["tenant_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_ocr_facts_tenant_expense",
            ["tenant_id", "expense_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_ocr_facts_tenant_provider_extracted",
            ["tenant_id", "ocr_provider", "extracted_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("ocr_facts", schema=None) as batch_op:
        batch_op.drop_index("ix_ocr_facts_tenant_provider_extracted")
        batch_op.drop_index("ix_ocr_facts_tenant_expense")
        batch_op.drop_index(batch_op.f("ix_ocr_facts_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_ocr_facts_public_id"))
        batch_op.drop_index(batch_op.f("ix_ocr_facts_expense_id"))
    op.drop_table("ocr_facts")
