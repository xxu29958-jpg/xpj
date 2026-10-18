"""Retain the source and reviewed version of an Expense repayment correction."""

import sqlalchemy as sa
from alembic import op

revision = "20261018_0001"
down_revision = "20261015_0001"
branch_labels = None
depends_on = None


def _set_revision(bind, expected, target):
    changed = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if changed.rowcount != 1:
        raise RuntimeError("dataset authority is outside the repayment source migration edge")


def upgrade():
    op.add_column("repayment_drafts", sa.Column("source_expense_public_id", sa.String(36), nullable=True))
    op.add_column("repayment_drafts", sa.Column("source_expense_row_version", sa.Integer(), nullable=True))
    bind = op.get_bind()
    # Recover only the identity encoded by the old bridge. It never persisted an
    # OCC token; inventing today's version would silently authorize later edits.
    source_match = """
        draft.tenant_id = expense.tenant_id AND draft.source = 'other'
          AND draft.draft_idempotency_key = encode(sha256(convert_to(
            'repayment_expense|' || draft.tenant_id || '|' || draft.created_by_account_id::text
            || '|' || expense.public_id, 'UTF8')), 'hex')
    """
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM repayment_drafts AS draft "
        "JOIN expenses AS expense ON " + source_match + ")")):
        if not bind.scalar(sa.text("SELECT state = 'ACTIVE' FROM installation_currency_bindings WHERE singleton_id = 1")):
            raise RuntimeError("activate the currency binding before migrating repayment correction sources")
        bind.execute(sa.text(
            "SELECT set_config('xpj.currency_writer', currency_contract_version::text || ':' || binding_revision::text, true) "
            "FROM installation_currency_bindings WHERE singleton_id = 1"
        ))
        bind.execute(sa.text("UPDATE repayment_drafts AS draft SET source_expense_public_id = expense.public_id "
            "FROM expenses AS expense WHERE " + source_match))
    _set_revision(bind, down_revision, revision)
    assert_postcondition(bind)


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM repayment_drafts "
        "WHERE source_expense_public_id IS NOT NULL OR source_expense_row_version IS NOT NULL)")):
        raise RuntimeError("cannot erase retained repayment correction provenance")
    op.drop_column("repayment_drafts", "source_expense_row_version")
    op.drop_column("repayment_drafts", "source_expense_public_id")
    _set_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    columns = {item["name"]: item for item in sa.inspect(bind).get_columns("repayment_drafts")}
    source = columns.get("source_expense_public_id")
    version = columns.get("source_expense_row_version")
    if (source is None or not isinstance(source["type"], sa.String) or source["type"].length != 36
        or version is None or not isinstance(version["type"], sa.Integer)
        or any(not column["nullable"] or column["default"] is not None for column in (source, version))):
        raise RuntimeError("repayment sources must be nullable without invented historical intent")
