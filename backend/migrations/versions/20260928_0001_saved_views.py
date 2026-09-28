"""Store ledger-shared named confirmed-stream queries.

Revision ID: 20260928_0001
Revises: 20260927_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0001"
down_revision = "20260927_0003"
branch_labels = None
depends_on = None


def _set_authority_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the saved-view edge")


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_key", sa.String(120), nullable=False),
        sa.Column("month_mode", sa.String(8), nullable=False),
        sa.Column("month", sa.String(7), nullable=True),
        sa.Column("filter", sa.String(32), nullable=False),
        sa.Column("tag_public_id", sa.String(36), nullable=True),
        sa.Column("home_currency_code", sa.String(3), nullable=False),
        sa.Column("created_by_account_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["tenant_id"], ["ledgers.ledger_id"], name="fk_saved_views_ledger"),
        sa.ForeignKeyConstraint(["created_by_account_id"], ["accounts.id"], name="fk_saved_views_actor"),
        sa.UniqueConstraint("public_id", name="uq_saved_views_public_id"),
        sa.UniqueConstraint("tenant_id", "name_key", name="uq_saved_views_tenant_name_key"),
        sa.CheckConstraint("month_mode IN ('fixed', 'current')", name="ck_saved_views_month_mode"),
        sa.CheckConstraint("filter IN ('', 'missing_category', 'missing_accounting_date')", name="ck_saved_views_filter"),
        sa.CheckConstraint("(month_mode = 'fixed' AND month IS NOT NULL) OR "
                           "(month_mode = 'current' AND month IS NULL)", name="ck_saved_views_month_binding"),
        sa.CheckConstraint("row_version >= 1", name="ck_saved_views_row_version"),
    )
    op.create_index("ix_saved_views_tenant_id", "saved_views", ["tenant_id"])
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM saved_views)")):
        raise RuntimeError("cannot erase saved financial views")
    op.drop_index("ix_saved_views_tenant_id", table_name="saved_views")
    op.drop_table("saved_views")
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind) -> None:
    inspector = sa.inspect(bind)
    required = {"id", "public_id", "tenant_id", "name", "name_key", "month_mode", "month",
                "filter", "tag_public_id", "home_currency_code", "created_by_account_id",
                "created_at", "updated_at", "row_version"}
    columns = {column["name"]: column for column in inspector.get_columns("saved_views")}
    if not required <= columns.keys() or any(columns[name]["nullable"] for name in required - {"month", "tag_public_id"}):
        raise RuntimeError("saved-view query schema is incomplete")
    unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("saved_views")}
    if ("tenant_id", "name_key") not in unique or ("public_id",) not in unique:
        raise RuntimeError("saved-view names or public identities are not unique")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with saved views")
