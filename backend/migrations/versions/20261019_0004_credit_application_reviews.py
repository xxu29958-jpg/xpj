"""Keep reviewed destinations for previously unallocated credit and their corrections."""
import sqlalchemy as sa
from alembic import op

revision = "20261019_0004"
down_revision = "20261019_0003"
branch_labels = None
depends_on = None


def _set_revision(expected, target):
    result = op.get_bind().execute(sa.text(
        "UPDATE dataset_authority SET schema_revision=:target WHERE singleton_id=1 AND schema_revision IN (:expected,:target)"),
        {"expected": expected, "target": target})
    if result.rowcount != 1:
        raise RuntimeError("dataset authority is outside the credit application migration edge")


def upgrade():
    op.create_table("credit_application_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("credit_movement_id", sa.Integer(), sa.ForeignKey("account_movements.id"), nullable=False),
        sa.Column("draw_movement_id", sa.Integer(), sa.ForeignKey("account_movements.id"), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("actor_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column("void_reason", sa.String(255)),
        sa.Column("void_actor_account_id", sa.Integer(), sa.ForeignKey("accounts.id")),
        sa.CheckConstraint("amount_minor BETWEEN 1 AND 9000000000000", name="ck_credit_application_reviews_amount_minor_money_bounds"),
        sa.CheckConstraint("(voided_at IS NULL AND void_reason IS NULL AND void_actor_account_id IS NULL) OR "
            "(voided_at IS NOT NULL AND void_reason IS NOT NULL AND void_actor_account_id IS NOT NULL)",
            name="ck_credit_application_void"))
    op.create_index("ix_credit_application_reviews_account_id", "credit_application_reviews", ["account_id"])
    op.add_column("credit_settlement_allocations", sa.Column("review_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_credit_allocation_review", "credit_settlement_allocations", "credit_application_reviews", ["review_id"], ["id"])
    op.execute("""
CREATE FUNCTION ticketbox_credit_application_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'credit application history cannot be removed' USING ERRCODE = '55000';
    END IF;
    IF OLD.voided_at IS NOT NULL OR NEW.voided_at IS NULL OR
        (to_jsonb(NEW) - ARRAY['voided_at','void_reason','void_actor_account_id']) IS DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['voided_at','void_reason','void_actor_account_id']) THEN
        RAISE EXCEPTION 'only an attributed first cancellation is allowed' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_credit_application_history BEFORE UPDATE OR DELETE ON credit_application_reviews
    FOR EACH ROW EXECUTE FUNCTION ticketbox_credit_application_history();
CREATE TRIGGER trg_credit_application_no_truncate BEFORE TRUNCATE ON credit_application_reviews
    FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_credit_application_history();
""")
    _set_revision(down_revision, revision)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM credit_application_reviews)")):
        raise RuntimeError("Reviewed credit destinations must remain readable; downgrade refused.")
    op.drop_column("credit_settlement_allocations", "review_id")
    op.drop_table("credit_application_reviews")
    op.execute("DROP FUNCTION ticketbox_credit_application_history()")
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    if not inspector.has_table("credit_application_reviews") or "review_id" not in {
            row["name"] for row in inspector.get_columns("credit_settlement_allocations")}:
        raise RuntimeError("credit application source relations are missing")
    names = set(bind.execute(sa.text("SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_credit_application_%'")).scalars())
    if names != {"trg_credit_application_history", "trg_credit_application_no_truncate"}:
        raise RuntimeError("credit application history guards are missing")
