"""PG round-trip of 20260620_0001 (add scheduler_leases, known-bugs 🟢#4).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries
``scheduler_leases``) then ``alembic stamp head``, so the guarded ``create_table``
body never runs on the normal path — a divergence between the migration's
hand-written ``create_table`` and the ORM would ship UNDETECTED by the deployment
path. This drives the migration directly on PostgreSQL: create_all → stamp head →
downgrade past 20260620_0001 (drops the table) → upgrade to head (re-creates it via
the migration body), then REFLECTS the migration-built table and asserts its
columns / nullability / primary key — not just that the table name exists.

It also pins the one-way ``app_meta`` cleanup: a pre-table ``scheduler_lease:*`` row
is removed by the upgrade while an unrelated key (``schema_version``) survives.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its
own ``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_NOT_NULL_COLUMNS = ("name", "expires_at", "updated_at")


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("scheduler_leases")}


def _pk_columns() -> list[str]:
    return inspect(engine).get_pk_constraint("scheduler_leases")["constrained_columns"]


def _assert_full_shape() -> None:
    cols = _columns()
    assert set(cols) == set(_NOT_NULL_COLUMNS), f"unexpected columns: {set(cols)}"
    for name in _NOT_NULL_COLUMNS:
        assert cols[name]["nullable"] is False, f"{name} should be NOT NULL"
    assert _pk_columns() == ["name"], f"primary key should be (name), got {_pk_columns()}"


def _app_meta_keys() -> set[str]:
    with engine.begin() as connection:
        return set(connection.scalars(text("SELECT key FROM app_meta")))


def _seed_legacy_and_control_app_meta() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app_meta (key, value, updated_at) VALUES "
                "(:lease_key, :lease_val, now()), "
                "(:keep_key, :keep_val, now())"
            ),
            {
                "lease_key": "scheduler_lease:probe_sync",
                "lease_val": "1970-01-01T00:00:00+00:00",
                "keep_key": "schema_version",
                "keep_val": "test",
            },
        )


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
    cfg = _alembic_cfg()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, *args)


def test_add_scheduler_leases_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()  # the current ORM shape

        _run_alembic(command.stamp, "20260620_0001")
        _run_alembic(command.downgrade, "20260619_0001")
        assert "scheduler_leases" not in _table_names()  # downgrade drops it

        # Seed a pre-table lease row + an unrelated control key, then upgrade: the
        # migration must re-create the table AND purge the transient lease row.
        _seed_legacy_and_control_app_meta()

        _run_alembic(command.upgrade, "head")
        # Re-created via the migration's hand-written create_table — assert the FULL
        # shape (columns/nullability/PK), not just the table name, so a
        # migration↔ORM divergence fails here.
        _assert_full_shape()

        keys = _app_meta_keys()
        assert "scheduler_lease:probe_sync" not in keys  # transient row purged
        assert "schema_version" in keys  # unrelated key untouched
    finally:
        _reset_empty_database()
        _drop_alembic_version()
