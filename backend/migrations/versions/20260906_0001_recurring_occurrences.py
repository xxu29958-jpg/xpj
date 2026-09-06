"""Add explicit monthly recurring fulfillment without creating payment facts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0001"
down_revision = "20260905_0001"
branch_labels = None
depends_on = None

_OCCURRENCES = "recurring_occurrences"
_REVISIONS = "recurring_occurrence_revisions"


def _set_authority_revision(bind, expected, target):
    updated = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority is outside the recurring occurrence migration edge")


def _create_occurrences():
    op.create_table(
        _OCCURRENCES,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("series_id", sa.Integer(), primary_key=True),
        sa.Column("period_start", sa.Date(), primary_key=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id", "tenant_id"], ["recurring_items.id", "recurring_items.tenant_id"],
            name="fk_recurring_occurrences_series_tenant", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_recurring_occurrences_expense_tenant", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "expense_id", name="uq_recurring_occurrences_payment"),
        sa.CheckConstraint("EXTRACT(DAY FROM period_start) = 1", name="ck_recurring_occurrences_month"),
        sa.CheckConstraint("row_version >= 1", name="ck_recurring_occurrences_version"),
    )


def _create_revisions():
    op.create_table(
        _REVISIONS,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_expense_id", sa.Integer(), nullable=True),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("actor_account_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "series_id", "period_start"],
            ["recurring_occurrences.tenant_id", "recurring_occurrences.series_id", "recurring_occurrences.period_start"],
            name="fk_recurring_occurrence_revisions_occurrence", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_recurring_occurrence_revisions_previous_payment", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_recurring_occurrence_revisions_payment", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], name="fk_recurring_occurrence_revision_actor", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "series_id", "period_start", "revision_number", name="uq_recurring_occurrence_revision"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_recurring_occurrence_revision_intent"),
        sa.CheckConstraint("revision_number >= 1", name="ck_recurring_occurrence_revisions_version"),
    )


def upgrade():
    bind = op.get_bind()
    uniques = {entry["name"] for entry in sa.inspect(bind).get_unique_constraints("recurring_items")}
    if "uq_recurring_items_id_tenant" not in uniques:
        op.create_unique_constraint("uq_recurring_items_id_tenant", "recurring_items", ["id", "tenant_id"])
    if not sa.inspect(bind).has_table(_OCCURRENCES):
        _create_occurrences()
    if not sa.inspect(bind).has_table(_REVISIONS):
        _create_revisions()
    op.execute("""
        CREATE OR REPLACE FUNCTION ticketbox_recurring_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'recurring occurrence revisions are immutable';
        END $$;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_recurring_occurrence_revision_immutable ON recurring_occurrence_revisions")
    op.execute("""
        CREATE TRIGGER trg_recurring_occurrence_revision_immutable
        BEFORE UPDATE OR DELETE ON recurring_occurrence_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_recurring_revision_immutable()
    """)
    _set_authority_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM recurring_occurrences)")):
        raise RuntimeError("cannot downgrade while recurring occurrence history exists")
    op.drop_table(_REVISIONS)
    op.drop_table(_OCCURRENCES)
    op.execute("DROP FUNCTION ticketbox_recurring_revision_immutable()")
    op.drop_constraint("uq_recurring_items_id_tenant", "recurring_items", type_="unique")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    for table in (_OCCURRENCES, _REVISIONS):
        if not inspector.has_table(table):
            raise RuntimeError("recurring occurrence schema is missing")
    names = {entry["name"] for entry in inspector.get_unique_constraints(_OCCURRENCES)}
    if "uq_recurring_occurrences_payment" not in names:
        raise RuntimeError("recurring payment uniqueness is missing")
    trigger = bind.scalar(sa.text(
        "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_recurring_occurrence_revision_immutable' "
        "AND tgrelid = 'recurring_occurrence_revisions'::regclass AND tgenabled = 'O'"
    ))
    if trigger != 1:
        raise RuntimeError("recurring occurrence history is not immutable")
    live_revision = bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_revision = revision if live_revision == down_revision else live_revision
    authority = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))
    if authority != expected_revision:
        raise RuntimeError("dataset authority is not aligned with recurring occurrence schema")
