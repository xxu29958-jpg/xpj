"""PG round-trip of 20260614_0003 (drop debt fact idempotency_key uniques).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM models, which no
longer declare these uniques) then ``alembic stamp head`` — so the migration's
``upgrade`` / ``downgrade`` bodies never execute on the normal path. This drives
them directly on PostgreSQL (the prod dialect): stamp head → downgrade past 0003
(``downgrade`` re-adds the four global ``UNIQUE(idempotency_key)`` constraints)
→ upgrade to head (``upgrade`` drops them via ``DROP CONSTRAINT IF EXISTS``).
Pins that the forward migration removes exactly the slice-1 fact-table uniques
and round-trips, and that ``create_all`` no longer carries them.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via
its own ``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

# table -> the slice-1 global idempotency_key unique constraint name.
_FACT_IDEMPOTENCY_UNIQUES = {
    "repayments": "uq_repayments_idempotency_key",
    "debt_adjustments": "uq_debt_adjustments_idempotency_key",
    "repayment_voids": "uq_repayment_voids_idempotency_key",
    "debt_voids": "uq_debt_voids_idempotency_key",
}


def _unique_constraint_names(table_name: str) -> set[str]:
    return {uc["name"] for uc in inspect(engine).get_unique_constraints(table_name)}


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


def test_drop_debt_fact_idempotency_unique_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        # create_all builds the current models, which no longer declare the
        # global idempotency_key uniques (uniqueness is tenant-scoped in
        # api_idempotency_keys per ADR-0049 §3.6 / [[0042]]).
        for table, name in _FACT_IDEMPOTENCY_UNIQUES.items():
            assert name not in _unique_constraint_names(table), table

        _run_alembic(command.stamp, "20260614_0003")
        # Downgrade past 0003 → downgrade() re-adds the four uniques.
        _run_alembic(command.downgrade, "20260614_0002")
        for table, name in _FACT_IDEMPOTENCY_UNIQUES.items():
            assert name in _unique_constraint_names(table), table

        # Upgrade back to head → upgrade() drops them via DROP CONSTRAINT IF EXISTS.
        _run_alembic(command.upgrade, "head")
        for table, name in _FACT_IDEMPOTENCY_UNIQUES.items():
            assert name not in _unique_constraint_names(table), table
    finally:
        _reset_empty_database()
        _drop_alembic_version()
