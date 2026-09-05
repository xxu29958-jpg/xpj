"""Persist create-time context for external Debt.

Revision ID: 20260905_0001
Revises: 20260901_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260905_0001"
down_revision = "20260901_0001"
branch_labels = None
depends_on = None


def _set_authority_revision(bind: sa.Connection, *, expected: str, target: str) -> None:
    updated = bind.execute(
        sa.text(
            "UPDATE dataset_authority SET schema_revision = :target "
            "WHERE singleton_id = 1 AND schema_revision IN (:expected, :target)"
        ),
        {"expected": expected, "target": target},
    )
    if updated.rowcount != 1:
        raise RuntimeError("dataset authority revision is outside the Debt context migration edge")


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("debts")}
    if "note" not in columns:
        op.add_column("debts", sa.Column("note", sa.Text(), nullable=True))
    _set_authority_revision(bind, expected=down_revision, target=revision)
    assert_postcondition(bind)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("debts")}
    if "note" in columns:
        if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM debts WHERE note IS NOT NULL)")):
            raise RuntimeError("cannot downgrade while Debt context exists")
        op.drop_column("debts", "note")
    _set_authority_revision(bind, expected=revision, target=down_revision)


def assert_postcondition(bind: sa.Connection) -> None:
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("debts")}
    note = columns.get("note")
    if note is None or not note["nullable"] or not isinstance(note["type"], sa.Text):
        raise RuntimeError("nullable Debt context column is missing")
    current = bind.scalar(sa.text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))
    if current != revision:
        raise RuntimeError("dataset authority revision is not aligned with Debt context schema")
