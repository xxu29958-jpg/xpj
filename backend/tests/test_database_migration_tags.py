"""ADR-0043 slice A: tags management columns + undo snapshot tables migration.

Exercises the legacy SQLite path — a pre-0043 ``tags`` table (no public_id /
row_version / deleted_at) gets the three columns ALTERed in, public_id
backfilled with a UUID, and the management indexes created; the two undo
snapshot tables are materialised by ``create_all``.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import inspect, text

import app.database as database
from app.database import Base, engine, init_db
from tests._infra.migration_helpers import (
    indexes,
    reset_empty_database,
    table_columns,
    table_create_sql,
)


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _alembic_cfg():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _run_alembic(action, *args) -> None:
    # Mirror init_db's pattern: drive Alembic through the test engine's
    # connection (the in-test SQLite), one command per transaction.
    cfg = _alembic_cfg()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, *args)


def _drop_alembic_version() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def test_legacy_tags_gain_management_columns_and_snapshot_tables() -> None:
    reset_empty_database()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id VARCHAR(64) NOT NULL,
                    name VARCHAR(64) NOT NULL,
                    key VARCHAR(64) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tags (tenant_id, name, key, created_at, updated_at)
                VALUES ('owner', '食物', '食物', '2026-05-01 00:00:00', '2026-05-01 00:00:00')
                """
            )
        )

    database.reset_sqlite_backup_state(done=True)
    try:
        init_db()

        # tags gains the three management columns + addressing/soft-delete indexes.
        assert {"public_id", "row_version", "deleted_at"}.issubset(table_columns("tags"))
        assert "ix_tags_public_id" in indexes("tags")
        assert "ix_tags_tenant_deleted" in indexes("tags")
        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT public_id, row_version, deleted_at FROM tags WHERE id = 1")
            ).mappings().one()
        UUID(str(row["public_id"]))  # backfilled value is a real UUID
        assert int(row["row_version"]) == 1
        assert row["deleted_at"] is None

        # both undo snapshot tables exist with their load-bearing columns + the
        # composite (group_id, tenant_id) FK back to the groups table.
        names = _table_names()
        assert {"tag_mutation_undo_groups", "tag_mutation_undo_items"}.issubset(names)
        assert {
            "mutation_public_id",
            "op",
            "source_tag_public_id",
            "source_tag_name",
            "target_tag_public_id",
            "consumed_at",
            "created_at",
        }.issubset(table_columns("tag_mutation_undo_groups"))
        assert {
            "group_id",
            "expense_public_id",
            "original_tags",
            "original_tag_ids",
            "original_row_version",
        }.issubset(table_columns("tag_mutation_undo_items"))
        item_fks = inspect(engine).get_foreign_keys("tag_mutation_undo_items")
        assert any(fk["referred_table"] == "tag_mutation_undo_groups" for fk in item_fks)
        # op CHECK is materialized and constrains to delete/merge (rename 不快照).
        assert "ck_tag_mutation_undo_groups_op_valid" in table_create_sql(
            "tag_mutation_undo_groups"
        )
    finally:
        database.reset_sqlite_backup_state(done=False)
        reset_empty_database()


def test_alembic_alter_branch_round_trips_tag_columns() -> None:
    """Exercise the Alembic ALTER branch — the existing-Postgres (prod) path.

    In normal init_db the legacy SQLite migrator adds the columns first, so the
    Alembic ``_upgrade_tags_columns`` 3-step never runs on SQLite. Here we build
    the current schema, alembic-downgrade past 0043 (which drops the columns +
    snapshot tables), seed legacy rows, then alembic-upgrade to head — forcing
    the add-nullable → backfill-uuid → NOT NULL + unique-index path that the
    PostgreSQL prod DB actually runs. Also covers the migration's downgrade().
    """
    from alembic import command

    from app.database import seed_identity_data

    reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        # Seed the 'owner' ledger so tags.tenant_id satisfies its FK through the
        # batch table-rebuilds the ALTER path performs on SQLite.
        seed_identity_data()
        _run_alembic(command.stamp, "20260606_0001")
        # Roll back the 0043 revision → tags reverts to its pre-0043 shape.
        _run_alembic(command.downgrade, "20260603_0002")
        assert not ({"public_id", "row_version", "deleted_at"} & table_columns("tags"))
        assert "tag_mutation_undo_groups" not in _table_names()

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO tags (tenant_id, name, key, created_at, updated_at)
                    VALUES
                        ('owner', '食物', '食物', '2026-05-01 00:00:00', '2026-05-01 00:00:00'),
                        ('owner', '差旅', '差旅', '2026-05-01 00:00:00', '2026-05-01 00:00:00')
                    """
                )
            )

        # Upgrade back to head → the ALTER 3-step + snapshot create_table run.
        _run_alembic(command.upgrade, "head")

        assert {"public_id", "row_version", "deleted_at"}.issubset(table_columns("tags"))
        assert "ix_tags_public_id" in indexes("tags")
        assert {"tag_mutation_undo_groups", "tag_mutation_undo_items"}.issubset(_table_names())
        with engine.begin() as connection:
            public_ids = [
                row["public_id"]
                for row in connection.execute(
                    text("SELECT public_id FROM tags ORDER BY id")
                ).mappings().all()
            ]
        assert all(public_ids), "every backfilled public_id is non-null/non-empty"
        assert len(set(public_ids)) == len(public_ids) == 2, "public_id is unique per row"
        for value in public_ids:
            UUID(str(value))
    finally:
        reset_empty_database()
        _drop_alembic_version()
