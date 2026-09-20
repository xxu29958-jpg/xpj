"""Preserve bilateral split proposals and accepted settlement history."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0003"
down_revision = "20260920_0002"
branch_labels = None
depends_on = None

_TABLES = ("bill_split_change_proposals", "bill_split_agreement_changes")

_PROPOSAL_IMMUTABLE_SQL = "\nCREATE OR REPLACE FUNCTION ticketbox_split_proposal_immutable()\nRETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n    IF TG_OP = 'DELETE' THEN\n        RAISE EXCEPTION 'split proposal evidence is immutable' USING ERRCODE = '55000';\n    END IF;\n    IF (to_jsonb(NEW) - ARRAY['status', 'resolved_at', 'resolved_by_account_id'])\n       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'resolved_at', 'resolved_by_account_id'])\n       OR (OLD.status <> 'pending' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)) THEN\n        RAISE EXCEPTION 'split proposal evidence is immutable' USING ERRCODE = '55000';\n    END IF;\n    RETURN NEW;\nEND $$;\nCREATE TRIGGER trg_split_proposal_immutable BEFORE UPDATE OR DELETE ON bill_split_change_proposals\nFOR EACH ROW EXECUTE FUNCTION ticketbox_split_proposal_immutable();\n"
_CHANGE_IMMUTABLE_SQL = "\nCREATE OR REPLACE FUNCTION ticketbox_split_agreement_immutable()\nRETURNS trigger LANGUAGE plpgsql AS $$ BEGIN\n    RAISE EXCEPTION 'split agreement changes are append-only' USING ERRCODE = '55000';\nEND $$;\nCREATE TRIGGER trg_split_agreement_immutable BEFORE UPDATE OR DELETE ON bill_split_agreement_changes\nFOR EACH ROW EXECUTE FUNCTION ticketbox_split_agreement_immutable();\n"


def _create_tables():
    # Generated with Alembic CreateTableOp/CreateIndexOp from the new ORM tables.
    op.create_table('bill_split_change_proposals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('public_id', sa.String(length=36), nullable=False),
    sa.Column('invitation_id', sa.Integer(), nullable=False),
    sa.Column('proposed_by_account_id', sa.Integer(), nullable=False),
    sa.Column('original_debt_id', sa.Integer(), nullable=False),
    sa.Column('original_debt_row_version', sa.Integer(), nullable=False),
    sa.Column('return_debt_id', sa.Integer(), nullable=True),
    sa.Column('return_debt_row_version', sa.Integer(), nullable=True),
    sa.Column('share_before_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('new_share_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('settlement_net_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('settlement_before_net_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('original_paid_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('return_paid_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('original_forgiven_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('return_forgiven_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by_account_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("(status = 'pending' AND resolved_at IS NULL AND resolved_by_account_id IS NULL) OR (status <> 'pending' AND resolved_at IS NOT NULL)", name='ck_bscp_resolution'),
    sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'withdrawn', 'superseded', 'expired')", name='ck_bscp_status'),
    sa.CheckConstraint('(return_debt_id IS NULL AND return_debt_row_version IS NULL) OR (return_debt_id IS NOT NULL AND return_debt_row_version IS NOT NULL AND return_debt_row_version >= 1 AND return_debt_id <> original_debt_id)', name='ck_bscp_return_version'),
    sa.CheckConstraint('expires_at > created_at', name='ck_bscp_expiry'),
    sa.CheckConstraint('length(trim(reason)) BETWEEN 1 AND 500', name='ck_bscp_reason'),
    sa.CheckConstraint('new_share_amount_cents BETWEEN 0 AND 9000000000000', name='ck_bscp_new_share_amount_cents'),
    sa.CheckConstraint('original_debt_row_version >= 1', name='ck_bscp_original_version'),
    sa.CheckConstraint('original_forgiven_amount_cents BETWEEN 0 AND 9007199254740991', name='ck_bscp_original_forgiven_amount_cents'),
    sa.CheckConstraint('original_paid_amount_cents BETWEEN 0 AND 9007199254740991', name='ck_bscp_original_paid_amount_cents'),
    sa.CheckConstraint('return_forgiven_amount_cents BETWEEN 0 AND 9007199254740991', name='ck_bscp_return_forgiven_amount_cents'),
    sa.CheckConstraint('return_paid_amount_cents BETWEEN 0 AND 9007199254740991', name='ck_bscp_return_paid_amount_cents'),
    sa.CheckConstraint('settlement_before_net_amount_cents BETWEEN -9007199254740991 AND 9007199254740991', name='ck_bscp_settlement_before_net_amount_cents'),
    sa.CheckConstraint('settlement_net_amount_cents BETWEEN -9000000000000 AND 9000000000000', name='ck_bscp_settlement_net_amount_cents'),
    sa.CheckConstraint('share_before_amount_cents BETWEEN 0 AND 9000000000000', name='ck_bscp_share_before_amount_cents'),
    sa.ForeignKeyConstraint(['invitation_id'], ['bill_split_invitations.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['original_debt_id'], ['debts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposed_by_account_id'], ['accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resolved_by_account_id'], ['accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['return_debt_id'], ['debts.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bill_split_change_proposals_public_id'), 'bill_split_change_proposals', ['public_id'], unique=True)
    op.create_index('ix_bscp_invitation_created', 'bill_split_change_proposals', ['invitation_id', 'created_at'], unique=False)
    op.create_index('uq_bscp_one_pending_per_invitation', 'bill_split_change_proposals', ['invitation_id'], unique=True, postgresql_where=sa.text("status = 'pending'"))
    op.create_table('bill_split_agreement_changes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('public_id', sa.String(length=36), nullable=False),
    sa.Column('proposal_id', sa.Integer(), nullable=False),
    sa.Column('invitation_id', sa.Integer(), nullable=False),
    sa.Column('share_before_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('new_share_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('settlement_net_amount_cents', sa.BigInteger(), nullable=False),
    sa.Column('original_debt_id', sa.Integer(), nullable=False),
    sa.Column('return_debt_id', sa.Integer(), nullable=True),
    sa.Column('original_adjustment_id', sa.Integer(), nullable=True),
    sa.Column('return_adjustment_id', sa.Integer(), nullable=True),
    sa.Column('proposed_by_account_id', sa.Integer(), nullable=False),
    sa.Column('accepted_by_account_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('new_share_amount_cents BETWEEN 0 AND 9000000000000', name='ck_bsac_new_share_amount_cents'),
    sa.CheckConstraint('proposed_by_account_id <> accepted_by_account_id', name='ck_bsac_two_parties'),
    sa.CheckConstraint('return_adjustment_id IS NULL OR return_debt_id IS NOT NULL', name='ck_bsac_return_adjustment'),
    sa.CheckConstraint('return_debt_id IS NULL OR return_debt_id <> original_debt_id', name='ck_bsac_distinct_debts'),
    sa.CheckConstraint('settlement_net_amount_cents BETWEEN -9000000000000 AND 9000000000000', name='ck_bsac_settlement_net_amount_cents'),
    sa.CheckConstraint('share_before_amount_cents BETWEEN 0 AND 9000000000000', name='ck_bsac_share_before_amount_cents'),
    sa.ForeignKeyConstraint(['accepted_by_account_id'], ['accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['invitation_id'], ['bill_split_invitations.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['original_adjustment_id'], ['debt_adjustments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['original_debt_id'], ['debts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposal_id'], ['bill_split_change_proposals.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposed_by_account_id'], ['accounts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['return_adjustment_id'], ['debt_adjustments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['return_debt_id'], ['debts.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('proposal_id')
    )
    op.create_index(op.f('ix_bill_split_agreement_changes_public_id'), 'bill_split_agreement_changes', ['public_id'], unique=True)
    op.create_index('ix_bsac_invitation_created', 'bill_split_agreement_changes', ['invitation_id', 'created_at'], unique=False)


def _set_authority_revision(bind, expected, target):
    result = bind.execute(sa.text(
        "UPDATE dataset_authority SET schema_revision = :target "
        "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
    ), {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the split agreement edge")


def _replace_debt_source_checks(include_return):
    sources = "'bill_split', 'bill_split_return'" if include_return else "'bill_split'"
    op.drop_constraint("ck_debts_source_type_valid", "debts", type_="check")
    op.drop_constraint("ck_debts_bill_split_has_source_id", "debts", type_="check")
    op.create_check_constraint("ck_debts_source_type_valid", "debts", f"source_type IN ('manual', {sources})")
    shape = (f"(source_type IN ({sources})) = (source_id IS NOT NULL)" if include_return
             else "(source_type = 'bill_split') = (source_id IS NOT NULL)")
    op.create_check_constraint("ck_debts_bill_split_has_source_id", "debts", shape)


def upgrade():
    op.alter_column("debts", "source_type", existing_type=sa.String(16), type_=sa.String(32), existing_nullable=False)
    _replace_debt_source_checks(True)
    _create_tables()
    op.execute(_PROPOSAL_IMMUTABLE_SQL)
    op.execute(_CHANGE_IMMUTABLE_SQL)
    for table in _TABLES:
        op.execute(f"CREATE TRIGGER trg_currency_writer_{table} "
                   f"BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_require_currency_writer()")
    _set_authority_revision(op.get_bind(), down_revision, revision)
    assert_postcondition(op.get_bind())


def downgrade():
    bind = op.get_bind()
    for table in _TABLES:
        if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("cannot discard split agreement evidence")
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM debts WHERE source_type = 'bill_split_return')")):
        raise RuntimeError("cannot discard split return debt identity")
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION ticketbox_split_agreement_immutable()")
    op.execute("DROP FUNCTION ticketbox_split_proposal_immutable()")
    _replace_debt_source_checks(False)
    op.alter_column("debts", "source_type", existing_type=sa.String(32), type_=sa.String(16), existing_nullable=False)
    _set_authority_revision(bind, revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    for table in _TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        if not all(isinstance(column["type"], sa.BigInteger) for name, column in columns.items()
                   if name.endswith("_amount_cents")):
            raise RuntimeError("split agreement money must use BIGINT")
        triggers = set(bind.scalars(sa.text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:table) AND NOT tgisinternal AND tgenabled = 'O'"
        ), {"table": table}))
        immutable = "trg_split_proposal_immutable" if table == _TABLES[0] else "trg_split_agreement_immutable"
        if not {immutable, f"trg_currency_writer_{table}"} <= triggers:
            raise RuntimeError("split agreement evidence guards are missing")
    source = next(column for column in inspector.get_columns("debts") if column["name"] == "source_type")
    if not isinstance(source["type"], sa.String) or source["type"].length != 32:
        raise RuntimeError("split return source cannot fit in the debt column")
    live = bind.scalar(sa.text("SELECT version_num FROM alembic_version"))
    expected = revision if live == down_revision else live
    if bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1")) != expected:
        raise RuntimeError("dataset authority is not aligned with split agreements")
