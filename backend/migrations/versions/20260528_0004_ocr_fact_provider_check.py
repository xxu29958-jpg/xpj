"""constrain ocr_facts provider names.

Revision ID: 20260528_0004
Revises: 20260528_0003
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0004"
down_revision: str | Sequence[str] | None = "20260528_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_ocr_facts_provider_valid"
CHECK_SQL = (
    "ocr_provider IN ("
    "'empty', 'mock', 'rapidocr', 'local_llm', "
    "'manual_text', 'legacy_expense_column'"
    ")"
)


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _has_check(bind, table_name: str, name: str) -> bool:
    return any(check.get("name") == name for check in sa.inspect(bind).get_check_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "ocr_facts") or _has_check(bind, "ocr_facts", CHECK_NAME):
        return
    with op.batch_alter_table("ocr_facts") as batch_op:
        batch_op.create_check_constraint(CHECK_NAME, CHECK_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "ocr_facts") or not _has_check(bind, "ocr_facts", CHECK_NAME):
        return
    with op.batch_alter_table("ocr_facts") as batch_op:
        batch_op.drop_constraint(CHECK_NAME, type_="check")
