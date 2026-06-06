"""Migrations for budgets, tags, and expense_tags join table.

``tags`` gains ADR-0043 management columns (``public_id`` / ``row_version`` /
``deleted_at``) here; the rest is idempotent index creation. The two undo
snapshot tables (``tag_mutation_undo_groups`` / ``tag_mutation_undo_items``)
are brand-new ORM tables, so ``create_all`` builds them on every path — they
need no legacy entry here.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import inspect, text


def _migrate_budgets(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_budgets_tenant_month "
        "ON budgets (tenant_id, month)"
    ))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_budgets_tenant_month ON budgets (tenant_id, month)"))


def _migrate_tags(connection) -> None:
    # ADR-0043: additive management columns. Alembic 20260606_0001 adds the
    # same three on the Postgres path; both are guarded so the legacy SQLite
    # run wins here and the Alembic add is a no-op (see
    # project_sqlite_legacy_migrator_column_complete — column-complete on both).
    columns = {column["name"] for column in inspect(connection).get_columns("tags")}
    if "public_id" not in columns:
        # Added nullable and never tightened to NOT NULL on SQLite — same as the
        # _recurring_goals public_id backfill. NOT NULL is enforced by the ORM
        # column + the Postgres (prod) Alembic path; the unique index below still
        # holds on SQLite, and no code path inserts a NULL public_id (ORM default
        # generates a UUID). Tightening on SQLite would force a table rebuild for
        # no functional gain in dev/test.
        connection.execute(text("ALTER TABLE tags ADD COLUMN public_id VARCHAR(36)"))
    if "row_version" not in columns:
        connection.execute(text("ALTER TABLE tags ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1"))
    if "deleted_at" not in columns:
        connection.execute(text("ALTER TABLE tags ADD COLUMN deleted_at DATETIME"))
    # Backfill public_id for legacy rows (SQLite has no UUID generator). Done
    # before the unique index so distinct UUIDs satisfy it.
    public_id_rows = connection.execute(
        text("SELECT id FROM tags WHERE public_id IS NULL OR public_id = ''")
    ).mappings().all()
    for row in public_id_rows:
        connection.execute(
            text("UPDATE tags SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_id_tenant_id ON tags (id, tenant_id)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_tenant_key ON tags (tenant_id, key)"
    ))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_key ON tags (tenant_id, key)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_name ON tags (tenant_id, name)"))
    # ADR-0043: unique addressing index + soft-delete filter index.
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tags_public_id ON tags (public_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_tenant_deleted ON tags (tenant_id, deleted_at)"))


def _migrate_expense_tags(connection) -> None:
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_tags_tenant_expense_tag "
        "ON expense_tags (tenant_id, expense_id, tag_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_expense "
        "ON expense_tags (tenant_id, expense_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_expense_tags_tenant_tag "
        "ON expense_tags (tenant_id, tag_id)"
    ))
