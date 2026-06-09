"""PG round-trip of the ADR-0043 tag-management Alembic migration (20260606_0001).

``init_db`` on a fresh DB runs ``create_all`` then ``alembic stamp head`` — so
the migration's ``upgrade`` / ``downgrade`` bodies never execute on the normal
path. This drives them directly on PostgreSQL (the prod dialect): stamp →
downgrade past 0043 (drops the management columns + snapshot tables) → seed
legacy ``tags`` rows → upgrade to head, forcing the add-nullable → backfill-uuid
→ NOT NULL + unique-index ALTER three-step that the production DB actually runs.

Ported (PG-only) from the retired ``test_database_migration_tags.py``; the
legacy-SQLite-migrator half of that file went with ``migrate_sqlite_schema``.
Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its
own ``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import inspect, text

from app.database import Base, engine, seed_identity_data


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _table_columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def _reset_empty_database() -> None:
    Base.metadata.drop_all(bind=engine)


def _drop_alembic_version() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _alembic_cfg():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _run_alembic(action, *args) -> None:
    # Drive Alembic through the test engine's connection, one command per
    # transaction (mirrors init_db's _stamp_alembic_baseline_if_needed).
    cfg = _alembic_cfg()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, *args)


def test_alembic_tag_migration_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        # Seed the 'owner' ledger so tags.tenant_id satisfies its FK.
        seed_identity_data()
        _run_alembic(command.stamp, "20260606_0001")
        # Roll 0043 back → tags reverts to its pre-0043 shape.
        _run_alembic(command.downgrade, "20260603_0002")
        assert not ({"public_id", "row_version", "deleted_at"} & _table_columns("tags"))
        assert "tag_mutation_undo_groups" not in _table_names()

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tags (tenant_id, name, key, created_at, updated_at) VALUES "
                    "('owner', '食物', '食物', '2026-05-01 00:00:00', '2026-05-01 00:00:00'), "
                    "('owner', '差旅', '差旅', '2026-05-01 00:00:00', '2026-05-01 00:00:00')"
                )
            )

        # Upgrade back to head → the ALTER three-step + snapshot create_table run.
        _run_alembic(command.upgrade, "head")

        assert {"public_id", "row_version", "deleted_at"}.issubset(_table_columns("tags"))
        assert "ix_tags_public_id" in _indexes("tags")
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
        _reset_empty_database()
        _drop_alembic_version()
