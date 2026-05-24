"""add learning feedback dual tables.

Revision ID: 10fef44b2042
Revises: 20260524_0002
Create Date: 2026-05-25

v1.2 P0 — pair of append-only tables backing the "建议层不污染账本"
contract. ``algorithm_decisions`` records every algorithm-emitted
suggestion (proposed category, duplicate candidate, recurring guess,
budget hint); ``ledger_learning_events`` records the user's reaction
to each (accept / reject / edit / ignore) plus manual overrides that
had no corresponding suggestion. The ledger itself never changes
based on these rows — they're a parallel learning signal stream.

Autogenerate also surfaced a pile of legacy v1.0 schema drift (FKs
that ORM declares but the legacy migrator never added, unique-index
vs. unique-constraint mismatches). That drift is intentionally NOT
fixed here — addressing it touches dozens of tables and belongs in
its own revision under code review. This revision is scoped to the
two new tables only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10fef44b2042"
down_revision: str | Sequence[str] | None = "20260524_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # init_db() runs ``Base.metadata.create_all`` before ``alembic
    # upgrade head`` for the legacy-to-alembic bridge path, so when this
    # revision fires the tables may already exist. Create each table
    # independently so a partially failed earlier run can recover.
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "algorithm_decisions" not in table_names:
        _create_algorithm_decisions()
    if "ledger_learning_events" not in table_names:
        _create_ledger_learning_events()


def _create_algorithm_decisions() -> None:
    op.create_table(
        "algorithm_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("subject_public_id", sa.String(length=36), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("output_payload", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="active",
            nullable=False,
        ),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["algorithm_decisions.id"],
            name="fk_algorithm_decisions_superseded_by",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["ledgers.ledger_id"],
            name="fk_algorithm_decisions_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("algorithm_decisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_algorithm_decisions_public_id"),
            ["public_id"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_algorithm_decisions_tenant_id"),
            ["tenant_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_algorithm_decisions_tenant_subject",
            ["tenant_id", "subject_kind", "subject_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_algorithm_decisions_tenant_type_created",
            ["tenant_id", "decision_type", "created_at"],
            unique=False,
        )


def _create_ledger_learning_events() -> None:
    op.create_table(
        "ledger_learning_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("before_payload", sa.Text(), nullable=True),
        sa.Column("after_payload", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["accounts.id"],
            name="fk_ledger_learning_events_actor",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["algorithm_decisions.id"],
            name="fk_ledger_learning_events_decision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["ledgers.ledger_id"],
            name="fk_ledger_learning_events_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table(
        "ledger_learning_events", schema=None
    ) as batch_op:
        batch_op.create_index(
            "ix_ledger_learning_events_decision",
            ["decision_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_ledger_learning_events_public_id"),
            ["public_id"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_ledger_learning_events_tenant_id"),
            ["tenant_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_ledger_learning_events_tenant_subject",
            ["tenant_id", "subject_kind", "subject_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_ledger_learning_events_tenant_type_created",
            ["tenant_id", "event_type", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "ledger_learning_events", schema=None
    ) as batch_op:
        batch_op.drop_index("ix_ledger_learning_events_tenant_type_created")
        batch_op.drop_index("ix_ledger_learning_events_tenant_subject")
        batch_op.drop_index(
            batch_op.f("ix_ledger_learning_events_tenant_id")
        )
        batch_op.drop_index(
            batch_op.f("ix_ledger_learning_events_public_id")
        )
        batch_op.drop_index("ix_ledger_learning_events_decision")
    op.drop_table("ledger_learning_events")

    with op.batch_alter_table("algorithm_decisions", schema=None) as batch_op:
        batch_op.drop_index("ix_algorithm_decisions_tenant_type_created")
        batch_op.drop_index("ix_algorithm_decisions_tenant_subject")
        batch_op.drop_index(batch_op.f("ix_algorithm_decisions_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_algorithm_decisions_public_id"))
    op.drop_table("algorithm_decisions")
