"""PG round-trip of 20260615_0001 (widen goals for debt_repayment, ADR-0049 §6).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM models — already
the slice-6 shape) then ``alembic stamp head``, so the migration's ``upgrade`` /
``downgrade`` bodies never execute on the normal path. This drives them directly
on PostgreSQL (the prod dialect): create_all → stamp head → downgrade past
20260615_0001 (restores the spending_limit-only ``goals`` shape + drops
``debt_goal_links``) → upgrade to head (re-widens). Pins that the migration is a
faithful, round-tripping transform of the legacy shape into the slice-6 shape.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its
own ``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_NEW_GOAL_COLUMNS = ("goal_version", "achieved_at", "achieved_version")


def _goals_columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("goals")}


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _type_check_sqltext() -> str:
    for cc in inspect(engine).get_check_constraints("goals"):
        if cc["name"] == "ck_goals_type_valid":
            return cc["sqltext"] or ""
    return ""


_SCOPE_INDEXES = ("uq_goals_active_total_scope", "uq_goals_active_category_scope")


def _scope_index_defs() -> dict[str, str]:
    """Full ``CREATE INDEX`` text (incl. the partial WHERE) per scope index.

    Read straight from ``pg_indexes.indexdef`` (``pg_get_indexdef``) — version-
    robust, and the only way to assert the partial predicate the migration owns
    (item ④: the scope indexes must gain ``goal_type = 'spending_limit'`` so a
    legacy-migrated DB does not cap a tenant at one active debt_repayment goal).
    """
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'goals'")
        ).all()
    return dict(rows)


def _assert_widened_shape() -> None:
    cols = _goals_columns()
    for name in _NEW_GOAL_COLUMNS:
        assert name in cols, f"{name} missing from widened goals"
    assert cols["month"]["nullable"] is True
    assert cols["target_amount_cents"]["nullable"] is True
    assert "debt_goal_links" in _table_names()
    assert "debt_repayment" in _type_check_sqltext()
    # item ④: the two scope indexes must be filtered to spending_limit so they
    # don't over-constrain debt goals.
    defs = _scope_index_defs()
    for name in _SCOPE_INDEXES:
        assert "goal_type" in defs[name], f"{name} not scoped to goal_type: {defs.get(name)}"


def _assert_legacy_shape() -> None:
    cols = _goals_columns()
    for name in _NEW_GOAL_COLUMNS:
        assert name not in cols, f"{name} should be dropped by downgrade"
    assert cols["month"]["nullable"] is False
    assert cols["target_amount_cents"]["nullable"] is False
    assert "debt_goal_links" not in _table_names()
    assert "debt_repayment" not in _type_check_sqltext()
    # Legacy scope indexes are unscoped (no goal_type filter).
    defs = _scope_index_defs()
    for name in _SCOPE_INDEXES:
        assert "goal_type" not in defs[name], f"{name} unexpectedly scoped: {defs.get(name)}"


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


def test_widen_goals_for_debt_repayment_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        # create_all builds the current (slice-6) models directly.
        _assert_widened_shape()

        _run_alembic(command.stamp, "20260615_0001")
        # Downgrade past 20260615_0001 → restores the spending_limit-only shape.
        _run_alembic(command.downgrade, "20260614_0003")
        _assert_legacy_shape()

        # Upgrade back to head → re-widens via the guarded ALTER path.
        _run_alembic(command.upgrade, "head")
        _assert_widened_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
