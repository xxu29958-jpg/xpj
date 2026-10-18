"""Retain the boundary between an existing obligation and its funds account."""
import sqlalchemy as sa
from alembic import op

revision = "20261018_0004"
down_revision = "20261018_0003"
branch_labels = None
depends_on = None


def _set_revision(expected, target):
    updated = op.get_bind().execute(sa.text("UPDATE dataset_authority SET schema_revision = :target WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"), {"expected": expected, "target": target})
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority is outside the credit adoption migration edge")


def upgrade():
    op.add_column("credit_facilities", sa.Column("adopted_at", sa.DateTime(timezone=True)))
    op.add_column("credit_facilities", sa.Column("adopted_from", sa.JSON()))
    op.create_check_constraint("ck_credit_facility_adoption", "credit_facilities",
        "(adopted_at IS NULL) = (adopted_from IS NULL)")
    _set_revision(down_revision, revision)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM credit_facilities WHERE adopted_at IS NOT NULL)")):
        raise RuntimeError("Existing credit adoption history must remain readable; downgrade refused.")
    op.drop_constraint("ck_credit_facility_adoption", "credit_facilities", type_="check")
    op.drop_column("credit_facilities", "adopted_from")
    op.drop_column("credit_facilities", "adopted_at")
    _set_revision(revision, down_revision)


def assert_postcondition(bind):
    inspector = sa.inspect(bind)
    if not {"adopted_at", "adopted_from"} <= {column["name"] for column in inspector.get_columns("credit_facilities")}:
        raise RuntimeError("credit adoption history columns are missing")
    if "ck_credit_facility_adoption" not in {item["name"] for item in inspector.get_check_constraints("credit_facilities")}:
        raise RuntimeError("credit adoption history boundary is missing")
